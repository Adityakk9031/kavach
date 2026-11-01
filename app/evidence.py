"""Evidence extraction (F3): the details a scammer states that the user (and police) need.

Two layers on every final caller turn: regexes catch structured identifiers for free (UPI IDs, IFSC codes, phone
numbers, URLs, e-mails, long account numbers, amounts) and an LLM pass finds the rest (names, agency, officer IDs,
apps). Every LLM item is checked against the turn's own text, so a hallucinated value is stored with valid=0 and
never reaches the report. Items are de-duplicated per call.
"""

import asyncio
import json
import logging
import re
from dataclasses import dataclass

from pydantic import BaseModel, Field, field_validator

from app.call_room import CallRoom
from app.llm import LLM, LLMError

log = logging.getLogger("kavach.evidence")

TYPES = ["upi_id", "bank_account", "ifsc", "phone_number", "url", "email", "person_name", "agency", "officer_id",
         "amount", "app_name"]

UPI_RE = re.compile(r"\b[a-zA-Z0-9._-]{2,}@(?!(?:gmail|yahoo|outlook|hotmail|rediffmail)\.)[a-zA-Z]{2,}\b")
EMAIL_RE = re.compile(r"\b[\w.+-]+@(?:gmail|yahoo|outlook|hotmail|rediffmail|[\w-]+\.[a-z]{2,})(?:\.[a-z]{2,})*\b", re.I)
IFSC_RE = re.compile(r"\b[A-Z]{4}0[A-Z0-9]{6}\b")
URL_RE = re.compile(r"\b(?:https?://\S+|(?:www\.)?[a-z0-9-]+(?:\.[a-z0-9-]+)*\.(?:com|in|net|org|co|xyz|info|top|link|app)(?:/\S*)?)\b", re.I)
PHONE_RE = re.compile(r"(?:\+?91[\s-]?)?\b[6-9](?:[\s-]?\d){9}\b")
ACCOUNT_RE = re.compile(r"\b\d(?:[\s-]?\d){8,17}\b")
AMOUNT_RE = re.compile(r"(?:rs\.?|₹|inr)\s?[\d,]+(?:\.\d+)?|\b[\d,]{4,}\s?(?:rupees|rs)\b|\b\d+(?:\.\d+)?\s?(?:lakh|lakhs|crore)\b", re.I)
AGENCY_RE = re.compile(r"\b(?:from|with|of|at)\s+(?:the\s+)?((?:[A-Z][A-Za-z&.-]*\s+){0,4}(?:Cell|Branch|Department|Bureau|Police|Bank|"
                       r"Customs|Office|Unit|Agency|Division|Commission|Directorate|Court|Authority|Ministry|Team))\b")
# "This is Inspector Vikram Rathore", "I am Rathore", "my name is Sharma": the caller naming themself.
NAME_RE = re.compile(r"\b(?i:this is|i am|i'm|my name is|name is)\s+(?:(?:Inspector|Sub-Inspector|Officer|Mr\.?|Mrs\.?|Ms\.?|Director|Agent|Sir|Mister)\s+)?"
                     r"([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2})\b")
ORG_WORDS = {"police", "bank", "cell", "department", "branch", "bureau", "office", "customs", "court", "agency", "division",
             "commission", "directorate", "authority", "ministry", "team", "crime", "cyber", "head", "reserve", "india"}
NOT_NAMES = {"calling", "from", "here", "speaking", "sorry", "not", "the", "a", "an", "very", "your", "serious", "calm",
             "sure", "afraid", "going", "trying", "just", "also", "now", "writing", "looking", "telling", "reaching"}
UPI_LABEL = re.compile(r"^(?i:upi\s*id)[\s:]*")
KNOWN_APPS = ["anydesk", "teamviewer", "quicksupport", "rustdesk", "ammyy", "airdroid", "phonepe", "google pay", "gpay",
              "paytm", "whatsapp", "telegram", "skype", "zoom"]


def digits(s: str) -> str:
    return re.sub(r"\D", "", s)


def norm(kind: str, value: str) -> str:
    v = value.strip()
    if kind in ("phone_number", "bank_account"):
        d = digits(v)
        return d[-10:] if kind == "phone_number" and len(d) > 10 else d
    if kind in ("upi_id", "email", "url", "ifsc"):
        return v.lower().rstrip(".,;")
    return re.sub(r"[^a-z0-9 ]", "", v.lower()).strip()


@dataclass
class Item:
    type: str
    value: str
    quote: str
    source: str  # "regex" | "llm"
    valid: bool = True

    @property
    def key(self) -> tuple[str, str]:
        return self.type, norm(self.type, self.value)


def regex_items(text: str) -> list[Item]:
    items: list[Item] = []
    taken: list[tuple[int, int]] = []

    def add(kind: str, m: re.Match) -> None:
        if any(a <= m.start() < b for a, b in taken):
            return
        taken.append((m.start(), m.end()))
        a = max(0, m.start() - 40)
        value = m.group(0).strip()
        if kind == "upi_id":
            value = UPI_LABEL.sub("", value)  # STT can glue the spoken label on: "upiidcustoms.clear@okbank"
        items.append(Item(kind, value, text[a:m.end() + 40].strip(), "regex"))

    for m in NAME_RE.finditer(text):
        words = m.group(1).split()
        if words and not any(w.lower() in NOT_NAMES or w.lower() in ORG_WORDS for w in words):
            items.append(Item("person_name", m.group(1).strip(), text[max(0, m.start() - 20):m.end() + 40].strip(), "regex"))
    for kind, rx in (("upi_id", UPI_RE), ("email", EMAIL_RE), ("ifsc", IFSC_RE), ("url", URL_RE),
                     ("phone_number", PHONE_RE), ("bank_account", ACCOUNT_RE), ("amount", AMOUNT_RE)):
        for m in rx.finditer(text):
            if kind == "url" and "@" in text[max(0, m.start() - 1):m.start()]:
                continue  # the domain part of an e-mail or UPI ID
            add(kind, m)
    for m in AGENCY_RE.finditer(text):
        items.append(Item("agency", m.group(1).strip(), text[max(0, m.start() - 40):m.end() + 40].strip(), "regex"))
    low = text.lower()
    for app in KNOWN_APPS:
        i = low.find(app)
        if i >= 0 and app in ("anydesk", "teamviewer", "quicksupport", "rustdesk", "ammyy", "airdroid"):
            items.append(Item("app_name", text[i:i + len(app)], text[max(0, i - 40):i + len(app) + 40], "regex"))
    return items


class LlmItem(BaseModel):
    type: str
    value: str
    quote: str = ""

    @field_validator("type")
    @classmethod
    def known(cls, v):
        v = v.strip().lower().replace(" ", "_")
        if v not in TYPES:
            raise ValueError(f"unknown type {v}")
        return v


class LlmOut(BaseModel):
    entities: list[LlmItem] = Field(default_factory=list)


PROMPT = f"""You read one sentence group spoken by a CALLER who may be a scammer. List the concrete details the caller
states that police would need. Types: {', '.join(TYPES)}.
- upi_id, bank_account, ifsc, phone_number, url, email: exactly as stated, digits normalised (no spaces).
- person_name: the name the caller gives for themself. agency: the organisation they claim to be from.
- officer_id: a badge, case, employee or reference number they give. amount: money they demand. app_name: an app they ask the listener to install or use.
Only include things the caller actually says in THIS text. person_name is ONLY the caller's own name, never the name of the person they are speaking to. If there are none, return an empty list.
Reply with ONLY JSON: {{"entities": [{{"type": "...", "value": "...", "quote": "short exact words from the text"}}]}}"""


TITLES = {"inspector", "officer", "sir", "madam", "mister", "mr", "mrs", "ms", "sub", "constable", "director", "agent",
          "executive", "manager", "sergeant", "commissioner", "the", "a", "an", "police", "bank", "department", "team"}


def plausible(item: LlmItem, listener_names: tuple[str, ...] = ()) -> bool:
    """Cheap sanity checks on an LLM item before it can reach a police complaint: not empty, not a bare title, the
    right shape for its type, and not the listener's own name (the caller addresses the victim by name)."""
    v = item.value.strip()
    if len(v) < 3:
        return False
    words = re.findall(r"[a-z0-9]+", v.lower())
    if item.type in ("person_name", "agency", "app_name") and all(w in TITLES for w in words):
        return False
    if item.type == "upi_id" and not re.fullmatch(r"[A-Za-z0-9._-]{2,}@[A-Za-z]{2,}", v):
        return False  # no spaces or stray words: a mashed "UPI ID x@y" must not reach a complaint
    if item.type == "upi_id" and v.lower().startswith("upiid"):
        return False
    if item.type == "ifsc" and not IFSC_RE.fullmatch(v.upper().replace(" ", "")):
        return False
    if item.type in ("phone_number", "bank_account") and len(digits(v)) < (10 if item.type == "phone_number" else 8):
        return False
    if item.type == "person_name" and any(w in ORG_WORDS for w in words):
        return False  # "Mumbai Police" is an organisation, not a person
    if item.type == "person_name":
        mine = {w for n in listener_names for w in re.findall(r"[a-z]+", n.lower())} - TITLES
        theirs = {w for w in words if w not in TITLES}
        if mine and theirs and theirs <= mine:
            return False  # that is the person being called, not the caller
    if item.type == "amount" and not re.search(r"\d|thousand|lakh|crore|hundred|rupee", v.lower()):
        return False  # "the money" is not an amount
    return True


def supported_by_text(item: LlmItem, text: str) -> bool:
    """The value must be in the turn's text: digit strings must match as digits, words as lower-case tokens."""
    if item.type in ("phone_number", "bank_account"):
        d, t = digits(item.value), digits(text)
        return len(d) >= 6 and d in t
    if item.type in ("upi_id", "email", "url", "ifsc"):
        return norm(item.type, item.value) in re.sub(r"\s+", "", text.lower())
    words = re.findall(r"[a-z0-9]+", item.value.lower())
    have = set(re.findall(r"[a-z0-9]+", text.lower()))
    return bool(words) and all(w in have or w.rstrip("s") in have for w in words)


class EvidenceCollector:
    """Per-call worker. Runs on every final caller turn once the call is flagged (trigger or takeover)."""

    def __init__(self, room: CallRoom, llm: LLM | None, model: str, pipeline=None, listener_names: tuple[str, ...] = ()):
        self.room, self.llm, self.model, self.pipeline = room, llm, model, pipeline
        self.listener_names = listener_names
        self.items: dict[tuple[str, str], dict] = {}
        self.unscanned: list[str] = []  # caller turns heard before the call was flagged (regex only so far)
        self.queue: asyncio.Queue = asyncio.Queue()
        self._worker = asyncio.create_task(self._run())
        room.on_final_hooks.append(self.on_final)
        room.on_end_hooks.append(self.close)

    def active(self) -> bool:
        flagged = (self.pipeline is not None and self.pipeline.triggered) or self.room.takeover
        return flagged

    async def on_final(self, room: CallRoom, turn: dict) -> None:
        if turn["channel"] != "caller":
            return
        # Regexes are free, so identifiers are always captured; the LLM pass waits until the call is flagged.
        await self.queue.put(turn)

    async def _run(self) -> None:
        while True:
            turn = await self.queue.get()
            try:
                await self.process(turn)
            except Exception:
                log.exception("evidence failed")
            finally:
                self.queue.task_done()

    async def process(self, turn: dict) -> list[dict]:
        text = turn["text"]
        found = regex_items(text)
        if self.llm is not None and self.active():
            # The opening line ("I am Inspector X from agency Y") is usually said before the call is flagged: scan
            # it together with the current turn, once, in a single request.
            llm_text = "\n".join(self.unscanned[-6:] + [text])
            self.unscanned.clear()
            try:
                out, _, _ = await self.llm.chat_json(
                    LlmOut, [{"role": "system", "content": PROMPT}, {"role": "user", "content": llm_text}],
                    model=self.model, max_tokens=250, timeout=8, temperature=0.0, lane="other", max_wait=5.0)
                for e in out.entities:
                    found.append(Item(e.type, e.value, e.quote or llm_text[:80], "llm",
                                      supported_by_text(e, llm_text) and plausible(e, self.listener_names)))
            except LLMError as e:
                self.room.log_event("evidence_llm_error", {"turn_idx": turn["idx"], "error": str(e)[:160]})
        elif self.llm is not None:
            self.unscanned.append(text)
        for it in found:
            if it.valid and it.source == "regex" and it.type in ("person_name", "agency"):
                it.valid = plausible(LlmItem(type=it.type, value=it.value), self.listener_names)
        new = []
        for it in found:
            old = self.items.get(it.key)
            if old is not None:
                if it.valid and not old["valid"]:  # a hallucinated value later stated for real: keep the real one
                    old.update(valid=True, quote=it.quote[:200], source=it.source, turn_idx=turn["idx"],
                               ts_ms=turn.get("audio_end_ms"))
                    self.room.store._exec("UPDATE evidence SET valid=1, quote=?, turn_id=?, ts_ms=? WHERE call_id=? AND type=? AND normalized=?",
                                          (old["quote"], turn.get("turn_id"), old["ts_ms"], self.room.call_id, it.type, it.key[1]))
                    new.append(old)
                continue
            row = {"type": it.type, "value": it.value, "normalized": it.key[1], "quote": it.quote[:200],
                   "source": it.source, "valid": it.valid, "turn_idx": turn["idx"], "ts_ms": turn.get("audio_end_ms")}
            self.items[it.key] = row
            new.append(row)
            self.room.store._exec(
                "INSERT INTO evidence(call_id, turn_id, type, value, normalized, quote, ts_ms, valid) VALUES (?,?,?,?,?,?,?,?)",
                (self.room.call_id, turn.get("turn_id"), it.type, it.value, it.key[1], row["quote"], row["ts_ms"],
                 int(it.valid)))
        if new:
            self.room.log_event("evidence", {"turn_idx": turn["idx"], "items": [(n["type"], n["value"], n["valid"]) for n in new]})
            await self.room.broadcast({"type": "evidence", "items": [n for n in new if n["valid"]]})
        return new

    def valid_items(self) -> list[dict]:
        return [v for v in self.items.values() if v["valid"]]

    async def close(self) -> None:
        self._worker.cancel()
        await asyncio.gather(self._worker, return_exceptions=True)
