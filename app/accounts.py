"""Accounts, families and pairing: what lets one Kavach server look after many families.

* The son or daughter signs up with an email and password. That creates a family and a session token.
* The protected parent's phone joins the family with a 6-digit pairing code (10 minutes, single use).
* One Telegram bot serves every family: a one-time deep link `t.me/<bot>?start=<token>` ties a chat to a family.
* Every request carries a token (or the legacy shared access key, which stands for the "default" family, so the
  original single-household setup keeps working). The token tells the server which family the request belongs to.

Passwords are stored as salted scrypt hashes and tokens as SHA-256 hashes, so a leaked database cannot be replayed.
"""

import hashlib
import hmac
import re
import secrets
import time
from dataclasses import dataclass, field

from app import lang

DEFAULT_FAMILY = "default"
SCHEMA = """
CREATE TABLE IF NOT EXISTS families (
  id TEXT PRIMARY KEY, name TEXT, language TEXT NOT NULL DEFAULT 'en', timezone TEXT NOT NULL DEFAULT 'UTC',
  parent_address TEXT NOT NULL DEFAULT 'Mom', son_name TEXT NOT NULL DEFAULT '',
  report_hint TEXT NOT NULL DEFAULT 'your local police or national fraud reporting service',
  son_voice_id TEXT, papa_voice_id TEXT, son_voice_expires REAL, papa_voice_expires REAL, voice_notes TEXT, created REAL
);
CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY AUTOINCREMENT, email TEXT UNIQUE NOT NULL, pw TEXT NOT NULL, family_id TEXT NOT NULL, created REAL
);
CREATE TABLE IF NOT EXISTS tokens (
  hash TEXT PRIMARY KEY, family_id TEXT NOT NULL, role TEXT NOT NULL, user_id INTEGER, created REAL
);
CREATE TABLE IF NOT EXISTS pair_codes (code TEXT PRIMARY KEY, family_id TEXT NOT NULL, expires REAL NOT NULL, used INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS tg_links (hash TEXT PRIMARY KEY, family_id TEXT NOT NULL, expires REAL NOT NULL);
CREATE TABLE IF NOT EXISTS tg_chats (chat_id TEXT PRIMARY KEY, family_id TEXT NOT NULL, linked REAL);
"""
EMAIL_RE = re.compile(r"[^@\s]{1,64}@[^@\s]{1,190}\.[^@\s]{2,24}")
EDITABLE = ("name", "language", "timezone", "parent_address", "son_name", "report_hint")
PAIR_TTL_S, LINK_TTL_S = 600, 900


class AccountError(ValueError):
    """A refusal whose message is safe to show the person."""


@dataclass
class Family:
    id: str
    name: str = ""
    language: str = "en"
    timezone: str = "UTC"
    parent_address: str = "Mom"
    son_name: str = ""
    report_hint: str = "your local police or national fraud reporting service"
    son_voice_id: str | None = None
    papa_voice_id: str | None = None
    chat_ids: list = field(default_factory=list)

    @property
    def pack(self) -> lang.Pack:
        return lang.get(self.language)


@dataclass
class Identity:
    family_id: str
    role: str  # son | parent | admin
    user_id: int | None = None


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _pw_hash(password: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    return salt.hex() + "$" + hashlib.scrypt(password.encode(), salt=salt, n=2 ** 14, r=8, p=1).hex()


def _pw_ok(password: str, stored: str) -> bool:
    salt_hex, _, digest = stored.partition("$")
    return hmac.compare_digest(_pw_hash(password, bytes.fromhex(salt_hex)).partition("$")[2], digest)


class Throttle:
    """At most `limit` failures per `window_s` per key, so codes and passwords cannot be guessed."""

    def __init__(self, limit: int = 8, window_s: float = 600):
        self.limit, self.window, self.fails = limit, window_s, {}

    def blocked(self, key: str) -> bool:
        now = time.time()
        self.fails[key] = [t for t in self.fails.get(key, []) if now - t < self.window]
        return len(self.fails[key]) >= self.limit

    def fail(self, key: str) -> None:
        self.fails.setdefault(key, []).append(time.time())


class Accounts:
    def __init__(self, store, settings):
        self.store, self.settings = store, settings
        with store._lock:
            store._db.executescript(SCHEMA)
        self.throttle = Throttle()
        self.ensure_default()

    # ---- the original single household, kept working -------------------------------------------------------

    def ensure_default(self) -> None:
        s = self.settings
        if not self.store.query("SELECT 1 FROM families WHERE id=?", (DEFAULT_FAMILY,)):
            self.store._exec(
                "INSERT INTO families(id, name, language, parent_address, son_voice_id, papa_voice_id, created) VALUES (?,?,?,?,?,?,?)",
                (DEFAULT_FAMILY, "Default", "en", s.parent_address, None, None, time.time()))  # its voices come from .env
        if s.telegram_chat_id and not self.store.query("SELECT 1 FROM tg_chats WHERE chat_id=?", (str(s.telegram_chat_id),)):
            self.store._exec("INSERT INTO tg_chats(chat_id, family_id, linked) VALUES (?,?,?)", (str(s.telegram_chat_id), DEFAULT_FAMILY, time.time()))

    # ---- families ----------------------------------------------------------------------------------------------

    def family(self, family_id: str) -> Family | None:
        rows = self.store.query("SELECT * FROM families WHERE id=?", (family_id,))
        if not rows:
            return None
        r = rows[0]
        chats = [c["chat_id"] for c in self.store.query("SELECT chat_id FROM tg_chats WHERE family_id=?", (family_id,))]
        return Family(id=r["id"], name=r["name"] or "", language=r["language"], timezone=r["timezone"], parent_address=r["parent_address"],
                      son_name=r["son_name"] or "", report_hint=r["report_hint"], son_voice_id=r["son_voice_id"],
                      papa_voice_id=r["papa_voice_id"], chat_ids=chats)

    def update_family(self, family_id: str, **fields) -> Family:
        clean = {}
        for k, v in fields.items():
            if k not in EDITABLE or v is None:
                continue
            v = str(v).strip()
            if k == "language" and v.lower()[:2] not in lang.PACKS:
                raise AccountError("That language is not available yet.")
            if k == "language":
                v = v.lower()[:2]
            if k == "timezone":
                try:
                    from zoneinfo import ZoneInfo
                    ZoneInfo(v)
                except Exception:
                    raise AccountError("Unknown time zone.")
            if k in ("name", "parent_address", "son_name"):
                v = re.sub(r"[^\w .'-]", "", v)[:40]
                if k == "parent_address" and not v:
                    raise AccountError("Say what you call them, for example Mom or Grandpa.")
            if k == "report_hint":
                v = v[:120] or "your local police or national fraud reporting service"
            clean[k] = v
        if clean:
            cols = ", ".join(f"{k}=?" for k in clean)
            self.store._exec(f"UPDATE families SET {cols} WHERE id=?", (*clean.values(), family_id))
        return self.family(family_id)

    # ---- sign-up, log-in, tokens -------------------------------------------------------------------------------

    def _issue(self, family_id: str, role: str, user_id: int | None = None) -> str:
        token = secrets.token_urlsafe(32)
        self.store._exec("INSERT INTO tokens(hash, family_id, role, user_id, created) VALUES (?,?,?,?,?)",
                         (_hash(token), family_id, role, user_id, time.time()))
        return token

    def signup(self, email: str, password: str, language: str = "en", timezone: str = "UTC", parent_address: str = "Mom",
               son_name: str = "") -> tuple[Family, str]:
        email = email.strip().lower()
        if not EMAIL_RE.fullmatch(email):
            raise AccountError("That email address does not look right.")
        if len(password) < 8:
            raise AccountError("Use a password of at least 8 characters.")
        if self.store.query("SELECT 1 FROM users WHERE email=?", (email,)):
            raise AccountError("There is already an account with that email. Log in instead.")
        fid = secrets.token_hex(6)
        self.store._exec("INSERT INTO families(id, created) VALUES (?,?)", (fid, time.time()))
        self.update_family(fid, language=language, timezone=timezone or "UTC", parent_address=parent_address or "Mom", son_name=son_name)
        cur = self.store._exec("INSERT INTO users(email, pw, family_id, created) VALUES (?,?,?,?)", (email, _pw_hash(password), fid, time.time()))
        return self.family(fid), self._issue(fid, "son", cur.lastrowid)

    def login(self, email: str, password: str) -> tuple[Family, str]:
        email = email.strip().lower()
        if self.throttle.blocked(email):
            raise AccountError("Too many tries. Please wait a few minutes.")
        rows = self.store.query("SELECT * FROM users WHERE email=?", (email,))
        if not rows or not _pw_ok(password, rows[0]["pw"]):
            self.throttle.fail(email)
            raise AccountError("The email or password is wrong.")
        return self.family(rows[0]["family_id"]), self._issue(rows[0]["family_id"], "son", rows[0]["id"])

    def identify(self, key: str | None) -> Identity | None:
        """Who a request is from. No access key configured = open (local use), standing for the default family."""
        required = self.settings.kavach_access_key
        if not required:
            ident = self._token_identity(key)
            return ident or Identity(DEFAULT_FAMILY, "admin")
        if key and secrets.compare_digest(key.encode(), required.encode()):
            return Identity(DEFAULT_FAMILY, "admin")
        return self._token_identity(key)

    def _token_identity(self, key: str | None) -> Identity | None:
        if not key:
            return None
        rows = self.store.query("SELECT family_id, role, user_id FROM tokens WHERE hash=?", (_hash(key),))
        return Identity(rows[0]["family_id"], rows[0]["role"], rows[0]["user_id"]) if rows else None

    # ---- pairing the parent's phone ----------------------------------------------------------------------------

    def new_pair_code(self, family_id: str) -> dict:
        self.store._exec("DELETE FROM pair_codes WHERE family_id=? OR expires<?", (family_id, time.time()))
        for _ in range(20):
            code = f"{secrets.randbelow(10 ** 6):06d}"
            if not self.store.query("SELECT 1 FROM pair_codes WHERE code=?", (code,)):
                self.store._exec("INSERT INTO pair_codes(code, family_id, expires) VALUES (?,?,?)", (code, family_id, time.time() + PAIR_TTL_S))
                return {"code": code, "expires_in_s": PAIR_TTL_S}
        raise AccountError("Please try again.")

    def redeem_pair_code(self, code: str, client: str) -> tuple[Family, str]:
        if self.throttle.blocked("pair:" + client):
            raise AccountError("Too many wrong codes. Please wait a few minutes.")
        rows = self.store.query("SELECT * FROM pair_codes WHERE code=? AND used=0 AND expires>?", (code.strip(), time.time()))
        if not rows:
            self.throttle.fail("pair:" + client)
            raise AccountError("That code is wrong or has expired. Ask your family for a new one.")
        self.store._exec("UPDATE pair_codes SET used=1 WHERE code=?", (code.strip(),))
        fid = rows[0]["family_id"]
        return self.family(fid), self._issue(fid, "parent")

    # ---- Telegram ----------------------------------------------------------------------------------------------

    def new_telegram_link(self, family_id: str) -> str:
        token = secrets.token_urlsafe(12)
        self.store._exec("INSERT INTO tg_links(hash, family_id, expires) VALUES (?,?,?)", (_hash(token), family_id, time.time() + LINK_TTL_S))
        return token

    def link_chat(self, token: str, chat_id) -> Family | None:
        rows = self.store.query("SELECT family_id FROM tg_links WHERE hash=? AND expires>?", (_hash(token), time.time()))
        if not rows:
            return None
        self.store._exec("DELETE FROM tg_links WHERE hash=?", (_hash(token),))
        self.store._exec("INSERT OR REPLACE INTO tg_chats(chat_id, family_id, linked) VALUES (?,?,?)", (str(chat_id), rows[0]["family_id"], time.time()))
        return self.family(rows[0]["family_id"])

    def family_for_chat(self, chat_id) -> Family | None:
        rows = self.store.query("SELECT family_id FROM tg_chats WHERE chat_id=?", (str(chat_id),))
        return self.family(rows[0]["family_id"]) if rows else None

    # ---- cloned voices -----------------------------------------------------------------------------------------

    def set_voice(self, family_id: str, person: str, voice_id: str | None, expires: float | None = None) -> None:
        col = "son" if person == "son" else "papa"
        self.store._exec(f"UPDATE families SET {col}_voice_id=?, {col}_voice_expires=? WHERE id=?", (voice_id, expires, family_id))

    def voice_id(self, family_id: str, person: str) -> str | None:
        col = "son" if person == "son" else "papa"
        rows = self.store.query(f"SELECT {col}_voice_id AS v FROM families WHERE id=?", (family_id,))
        return rows[0]["v"] if rows else None

    def voice_state(self, family_id: str) -> dict:
        r = self.store.query("SELECT son_voice_id, papa_voice_id, son_voice_expires, papa_voice_expires FROM families WHERE id=?", (family_id,))
        r = r[0] if r else {}
        return {"son": {"cloned": bool(r.get("son_voice_id")), "expires": r.get("son_voice_expires")},
                "papa": {"cloned": bool(r.get("papa_voice_id")), "expires": r.get("papa_voice_expires")}}
