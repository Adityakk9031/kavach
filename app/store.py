"""Persistence. Postgres (Supabase) when DATABASE_URL is set, SQLite otherwise (tests and a laptop).

The SQL in the app is written once, in the SQLite style (`?` placeholders); `_pg` turns it into Postgres. Writes that
nobody waits for (`write`) go to a background thread on Postgres, so a call's audio never waits on the network; a read
first lets those writes finish, so it always sees them.
"""

import json
import logging
import queue
import re
import sqlite3
import threading
import time
from pathlib import Path

log = logging.getLogger("kavach.store")

SCHEMA = """
CREATE TABLE IF NOT EXISTS calls (
  id TEXT PRIMARY KEY, mode TEXT NOT NULL DEFAULT 'live', script_id TEXT, caller_number TEXT,
  started_at REAL, ended_at REAL, label TEXT, scam_type TEXT, max_risk REAL,
  warned_at REAL, takeover_at REAL, money_shared INTEGER, otp_shared INTEGER,
  report_md_path TEXT, report_pdf_path TEXT, family_id TEXT
);
CREATE TABLE IF NOT EXISTS turns (
  id INTEGER PRIMARY KEY AUTOINCREMENT, call_id TEXT NOT NULL, channel TEXT NOT NULL, idx INTEGER,
  text TEXT, audio_start_ms INTEGER, audio_end_ms INTEGER, final_at_mono REAL, stt_latency_ms REAL,
  is_decoy INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS detections (
  id INTEGER PRIMARY KEY AUTOINCREMENT, call_id TEXT NOT NULL, turn_id INTEGER, stages TEXT,
  evidence_quotes TEXT, risk_llm INTEGER, risk_cum REAL, rationale TEXT, triggered INTEGER,
  llm_ms INTEGER, model TEXT
);
CREATE TABLE IF NOT EXISTS evidence (
  id INTEGER PRIMARY KEY AUTOINCREMENT, call_id TEXT NOT NULL, turn_id INTEGER, type TEXT,
  value TEXT, normalized TEXT, quote TEXT, ts_ms INTEGER, valid INTEGER
);
CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY AUTOINCREMENT, call_id TEXT NOT NULL, ts_mono REAL, ts_wall REAL,
  type TEXT NOT NULL, payload TEXT
);
CREATE TABLE IF NOT EXISTS answer_tokens (token TEXT PRIMARY KEY, call_id TEXT NOT NULL, created REAL);
CREATE INDEX IF NOT EXISTS events_call ON events(call_id, ts_mono);
CREATE INDEX IF NOT EXISTS turns_call ON turns(call_id, idx);
CREATE INDEX IF NOT EXISTS detections_call ON detections(call_id);
CREATE INDEX IF NOT EXISTS evidence_call ON evidence(call_id);
"""


def _pg(sql: str) -> str:
    """SQLite-style SQL as Postgres: placeholders, auto-increment keys, and 8-byte floats (times need them)."""
    sql = sql.replace("%", "%%").replace("?", "%s")
    sql = sql.replace("INTEGER PRIMARY KEY AUTOINCREMENT", "BIGSERIAL PRIMARY KEY")
    return re.sub(r"\bREAL\b", "DOUBLE PRECISION", sql)


class Store:
    def __init__(self, path: str, url: str = ""):
        self.pg = bool(url)
        self._url = url
        self._lock = threading.RLock()
        if self.pg:
            self._connect()
            self._pending: queue.Queue = queue.Queue()
            threading.Thread(target=self._drain, daemon=True, name="kavach-db").start()
        else:
            if path != ":memory:":
                Path(path).parent.mkdir(parents=True, exist_ok=True)
            self._db = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
            self._db.row_factory = sqlite3.Row
        self.script(SCHEMA)
        self.add_column("calls", "family_id", "TEXT")  # databases made before families existed
        self.script("CREATE INDEX IF NOT EXISTS calls_family ON calls(family_id);")

    # ---- the two databases ---------------------------------------------------------------------------------

    def _connect(self) -> None:
        import psycopg
        from psycopg.rows import dict_row
        # prepare_threshold=None: Supabase's pooler shares server connections, where prepared statements break
        self._db = psycopg.connect(self._url, autocommit=True, row_factory=dict_row, prepare_threshold=None,
                                   connect_timeout=10)

    def script(self, schema: str) -> None:
        """Create tables. On Supabase every table also gets row-level security with no policy: Supabase serves the
        `public` schema over its own web API, and this keeps that API from reading Kavach's tables. The server
        itself connects as the owner, which is not affected."""
        with self._lock:
            if not self.pg:
                self._db.executescript(schema)
                return
            for stmt in filter(None, (x.strip() for x in schema.split(";"))):
                self._db.execute(_pg(stmt))
            for table in re.findall(r"CREATE TABLE IF NOT EXISTS (\w+)", schema):
                self._db.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")

    def add_column(self, table: str, column: str, kind: str) -> None:
        with self._lock:
            if self.pg:
                self._db.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} {_pg(kind)}")
                return
            try:
                self._db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {kind}")
            except sqlite3.OperationalError:
                pass  # already there

    def _run(self, sql: str, args: tuple):
        with self._lock:
            if not self.pg:
                return self._db.execute(sql, args)
            import psycopg
            try:
                return self._db.execute(_pg(sql), args)
            except (psycopg.OperationalError, psycopg.InterfaceError):  # the connection dropped: once more on a new one
                log.warning("database connection lost, reconnecting")
                try:
                    self._db.close()
                except Exception:
                    pass
                self._connect()
                return self._db.execute(_pg(sql), args)

    def _drain(self) -> None:
        while True:
            sql, args = self._pending.get()
            try:
                self._run(sql, args)
            except Exception:
                log.exception("background write failed: %s", sql[:80])
            finally:
                self._pending.task_done()

    def _exec(self, sql: str, args: tuple = ()):
        if self.pg:
            self._pending.join()  # keep the order: earlier background writes land first
        return self._run(sql, args)

    def write(self, sql: str, args: tuple = ()) -> None:
        """A write whose result nobody needs. On Postgres it does not wait for the network."""
        if self.pg:
            self._pending.put((sql, args))
        else:
            self._run(sql, args)

    def insert(self, sql: str, args: tuple = ()) -> int:
        """An INSERT into a table with an `id` key; returns the new id."""
        if self.pg:
            return self._exec(sql + " RETURNING id", args).fetchone()["id"]
        return self._exec(sql, args).lastrowid

    def query(self, sql: str, args: tuple = ()) -> list[dict]:
        return [dict(r) for r in self._exec(sql, args).fetchall()]

    def start_call(self, call_id: str, mode: str = "live", caller_number: str | None = None,
                   script_id: str | None = None) -> None:
        self._exec(
            "INSERT INTO calls(id, mode, caller_number, script_id, started_at) VALUES (?,?,?,?,?) "
            "ON CONFLICT(id) DO UPDATE SET caller_number=COALESCE(excluded.caller_number, calls.caller_number)",
            (call_id, mode, caller_number, script_id, time.time()),
        )

    def update_call(self, call_id: str, **fields) -> None:
        if not fields:
            return
        cols = ", ".join(f"{k}=?" for k in fields)
        self.write(f"UPDATE calls SET {cols} WHERE id=?", (*fields.values(), call_id))

    def add_event(self, call_id: str, type_: str, ts_mono: float, payload: dict | None = None) -> None:
        self.write(
            "INSERT INTO events(call_id, ts_mono, ts_wall, type, payload) VALUES (?,?,?,?,?)",
            (call_id, ts_mono, time.time(), type_, json.dumps(payload or {})),
        )

    def add_turn(self, call_id: str, channel: str, idx: int, text: str, audio_start_ms: int | None,
                 audio_end_ms: int | None, final_at_mono: float, stt_latency_ms: float | None,
                 is_decoy: bool = False) -> int:
        return self.insert(
            "INSERT INTO turns(call_id, channel, idx, text, audio_start_ms, audio_end_ms, final_at_mono, "
            "stt_latency_ms, is_decoy) VALUES (?,?,?,?,?,?,?,?,?)",
            (call_id, channel, idx, text, audio_start_ms, audio_end_ms, final_at_mono, stt_latency_ms,
             int(is_decoy)),
        )

    def make_answer_token(self, call_id: str) -> str:
        """A short random token for Telegram buttons: it stands for one call and cannot be guessed from the call id."""
        import secrets
        token = secrets.token_urlsafe(6)
        self._exec("INSERT INTO answer_tokens(token, call_id, created) VALUES (?,?,?)", (token, call_id, time.time()))
        return token

    def call_for_token(self, token: str) -> str | None:
        rows = self.query("SELECT call_id FROM answer_tokens WHERE token=?", (token,))
        return rows[0]["call_id"] if rows else None

    def events(self, call_id: str) -> list[dict]:
        rows = self.query("SELECT * FROM events WHERE call_id=? ORDER BY ts_mono", (call_id,))
        for r in rows:
            r["payload"] = json.loads(r["payload"] or "{}")
        return rows

    def turns(self, call_id: str) -> list[dict]:
        return self.query("SELECT * FROM turns WHERE call_id=? ORDER BY final_at_mono", (call_id,))
