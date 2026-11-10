"""SQLite persistence. Small and synchronous: writes are rare (finals, key events), not per audio frame."""

import json
import sqlite3
import threading
import time
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS calls (
  id TEXT PRIMARY KEY, mode TEXT NOT NULL DEFAULT 'live', script_id TEXT, caller_number TEXT,
  started_at REAL, ended_at REAL, label TEXT, scam_type TEXT, max_risk REAL,
  warned_at REAL, takeover_at REAL, money_shared INTEGER, otp_shared INTEGER,
  report_md_path TEXT, report_pdf_path TEXT
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
"""


class Store:
    def __init__(self, path: str):
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self._db.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        with self._lock:
            self._db.executescript(SCHEMA)
            try:  # older databases: calls now belong to a family
                self._db.execute("ALTER TABLE calls ADD COLUMN family_id TEXT")
            except sqlite3.OperationalError:
                pass

    def _exec(self, sql: str, args: tuple = ()) -> sqlite3.Cursor:
        with self._lock:
            return self._db.execute(sql, args)

    def query(self, sql: str, args: tuple = ()) -> list[dict]:
        return [dict(r) for r in self._exec(sql, args).fetchall()]

    def start_call(self, call_id: str, mode: str = "live", caller_number: str | None = None,
                   script_id: str | None = None) -> None:
        self._exec(
            "INSERT INTO calls(id, mode, caller_number, script_id, started_at) VALUES (?,?,?,?,?) "
            "ON CONFLICT(id) DO UPDATE SET caller_number=COALESCE(excluded.caller_number, caller_number)",
            (call_id, mode, caller_number, script_id, time.time()),
        )

    def update_call(self, call_id: str, **fields) -> None:
        if not fields:
            return
        cols = ", ".join(f"{k}=?" for k in fields)
        self._exec(f"UPDATE calls SET {cols} WHERE id=?", (*fields.values(), call_id))

    def add_event(self, call_id: str, type_: str, ts_mono: float, payload: dict | None = None) -> None:
        self._exec(
            "INSERT INTO events(call_id, ts_mono, ts_wall, type, payload) VALUES (?,?,?,?,?)",
            (call_id, ts_mono, time.time(), type_, json.dumps(payload or {})),
        )

    def add_turn(self, call_id: str, channel: str, idx: int, text: str, audio_start_ms: int | None,
                 audio_end_ms: int | None, final_at_mono: float, stt_latency_ms: float | None,
                 is_decoy: bool = False) -> int:
        cur = self._exec(
            "INSERT INTO turns(call_id, channel, idx, text, audio_start_ms, audio_end_ms, final_at_mono, "
            "stt_latency_ms, is_decoy) VALUES (?,?,?,?,?,?,?,?,?)",
            (call_id, channel, idx, text, audio_start_ms, audio_end_ms, final_at_mono, stt_latency_ms,
             int(is_decoy)),
        )
        return cur.lastrowid

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
