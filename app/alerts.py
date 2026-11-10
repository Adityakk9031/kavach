"""Family alerts over the Telegram Bot API (F4).

Rules: at most 3 alerts per call, at most one per stage change, and a slot is always kept for the end-of-call
message. Sending never blocks the call: failures are logged as events. With no token/chat id the alerter logs
`alert_skipped` and does nothing.
"""

import asyncio
import json
import logging
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx

from app import lang
from app.config import Settings

log = logging.getLogger("kavach.alerts")
IST = ZoneInfo("Asia/Kolkata")  # kept for the original single household's tests; families use their own time zone
STAGE_NAMES = {"S1": "Authority", "S2": "Threat", "S3": "Secrecy", "S4": "Urgency", "S5": "Credential request",
               "S6": "Payment request", "S7": "Remote access"}
ACTION = {"S5", "S6", "S7"}


def ist_now(ts: float | None = None) -> str:
    return datetime.fromtimestamp(ts, IST).strftime("%d %b %Y, %H:%M IST") if ts else datetime.now(IST).strftime("%d %b %Y, %H:%M IST")


def local_now(tz: str = "UTC", ts: float | None = None) -> str:
    """The time in the family's own time zone, with its abbreviation (UTC, EST, IST…)."""
    zone = ZoneInfo(tz or "UTC")
    when = datetime.fromtimestamp(ts, zone) if ts else datetime.now(zone)
    return when.strftime("%d %b %Y, %H:%M %Z")


def snippet(text: str, limit: int = 140) -> str:
    """At most two short lines of what the caller said."""
    t = " ".join(text.split())
    if len(t) <= limit:
        return t
    cut = t[:limit].rsplit(" ", 1)[0]
    return cut + "…"


def stage_list(stages: list[str], t: dict | None = None) -> str:
    t = t or lang.EN.t
    return ", ".join(t["stages"].get(s, s) for s in sorted(stages)) or t["none_yet"]


def answer_keyboard(token: str, money: bool | None = None, otp: bool | None = None, t: dict | None = None) -> dict:
    """Four buttons under the call-end message: the two questions only a person can answer. A ✅ marks the chosen
    answer. callback_data is `a:<token>:<m|o>:<y|n>` (well under Telegram's 64-byte limit)."""
    def btn(label: str, q: str, yes: bool, current: bool | None) -> dict:
        mark = "✅ " if current is yes else ""
        return {"text": f"{mark}{label}", "callback_data": f"a:{token}:{q}:{'y' if yes else 'n'}"}

    t = t or {}
    return {"inline_keyboard": [
        [btn(t.get("money_yes", "Money sent: Yes"), "m", True, money), btn(t.get("money_no", "Money sent: No"), "m", False, money)],
        [btn(t.get("otp_yes", "OTP/PIN shared: Yes"), "o", True, otp), btn(t.get("otp_no", "OTP/PIN shared: No"), "o", False, otp)]]}


def control_keyboard(token: str, label: str = "☎️ End the call") -> dict:
    """Under the warning / takeover alerts: the family can end the call from Telegram."""
    return {"inline_keyboard": [[{"text": label, "callback_data": f"c:{token}:e"}]]}


class AlertPolicy:
    """Decides whether an alert may go out. Pure, so it is easy to test."""

    def __init__(self, max_per_call: int = 3):
        self.max, self.sent = max_per_call, 0
        self.kinds: set[str] = set()
        self.stages_alerted: set[str] = set()

    MANDATORY = ("takeover", "call_end")

    def allow(self, kind: str, stages: list[str] | None = None) -> bool:
        if kind in ("warning", "takeover", "call_end") and kind in self.kinds:
            return False
        # Slots still owed to the messages the family must get (takeover, call end) are never spent on anything else.
        owed = [k for k in self.MANDATORY if k not in self.kinds and k != kind]
        reserved = len(owed) if kind not in self.MANDATORY else 0
        if kind == "call_end":
            reserved = 0
        if self.sent + 1 > self.max - reserved:
            return False
        if kind == "stage_update":
            fresh = (set(stages or []) & ACTION) - self.stages_alerted
            if not fresh:
                return False
        return True

    def record(self, kind: str, stages: list[str] | None = None) -> None:
        self.sent += 1
        self.kinds.add(kind)
        if stages:
            self.stages_alerted |= set(stages)


class Alerter:
    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None):
        self.settings = settings
        self.enabled = bool(settings.telegram_bot_token)  # which chats get an alert is decided per family
        self._username: str | None = None
        self.client = client or httpx.AsyncClient(timeout=15)
        self.base = f"https://api.telegram.org/bot{settings.telegram_bot_token}"

    @property
    def has_token(self) -> bool:
        return bool(self.settings.telegram_bot_token)

    async def bot_username(self) -> str | None:
        """The bot's @name, for the deep link that connects a chat to a family."""
        if self._username is None and self.has_token:
            try:
                body = (await self.client.get(f"{self.base}/getMe")).json()
                self._username = (body.get("result") or {}).get("username")
            except Exception:
                log.warning("could not read the bot's name")
        return self._username

    async def send_message(self, text: str, reply_markup: dict | None = None, chat_id: str | int | None = None) -> dict:
        payload = {"chat_id": chat_id or self.settings.telegram_chat_id, "text": text[:4000], "disable_web_page_preview": True}
        if reply_markup:
            payload["reply_markup"] = reply_markup
        r = await self.client.post(f"{self.base}/sendMessage", json=payload)
        body = r.json()
        if not body.get("ok"):
            raise RuntimeError(body.get("description", f"HTTP {r.status_code}"))
        return body

    async def download_file(self, file_id: str) -> bytes:
        """A file the family sent to the bot (a voice note). The bot token is part of the download URL: never log it."""
        r = await self.client.post(f"{self.base}/getFile", json={"file_id": file_id})
        body = r.json()
        if not body.get("ok"):
            raise RuntimeError(body.get("description", f"HTTP {r.status_code}"))
        f = await self.client.get(f"https://api.telegram.org/file/bot{self.settings.telegram_bot_token}/{body['result']['file_path']}")
        f.raise_for_status()
        return f.content

    async def answer_callback(self, callback_id: str, text: str) -> None:
        """Stops the spinner on the pressed button and shows a short confirmation."""
        await self.client.post(f"{self.base}/answerCallbackQuery", json={"callback_query_id": callback_id, "text": text})

    async def edit_markup(self, chat_id: int | str, message_id: int, reply_markup: dict) -> None:
        await self.client.post(f"{self.base}/editMessageReplyMarkup", json={
            "chat_id": chat_id, "message_id": message_id, "reply_markup": reply_markup})

    async def poll(self, handler, long_poll_s: int = 25) -> None:
        """Receive button presses (callback queries) by long polling, and hand each update to `handler`. Runs until
        cancelled; transient network or API errors are retried."""
        offset = None
        while True:
            try:
                params = {"timeout": long_poll_s, "allowed_updates": json.dumps(["callback_query", "message"])}
                if offset is not None:
                    params["offset"] = offset
                r = await self.client.get(f"{self.base}/getUpdates", params=params, timeout=long_poll_s + 15)
                body = r.json()
                if not body.get("ok"):
                    log.warning("getUpdates failed: %s", body.get("description"))
                    await asyncio.sleep(5)
                    continue
                for update in body["result"]:
                    offset = update["update_id"] + 1
                    try:
                        await handler(update)
                    except Exception:
                        log.exception("telegram update handler failed")
                await asyncio.sleep(0)  # always give the loop a chance to run (and to cancel us)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.warning("telegram polling error: %s", e)
                await asyncio.sleep(5)

    async def send_document(self, path: Path, caption: str, chat_id: str | int | None = None) -> dict:
        with open(path, "rb") as f:
            r = await self.client.post(f"{self.base}/sendDocument", data={
                "chat_id": chat_id or self.settings.telegram_chat_id, "caption": caption[:900]}, files={"document": (path.name, f)})
        body = r.json()
        if not body.get("ok"):
            raise RuntimeError(body.get("description", f"HTTP {r.status_code}"))
        return body

    async def aclose(self) -> None:
        await self.client.aclose()


class CallAlerts:
    """Per-call: listens to the pipeline / persona / room and sends the permitted alerts."""

    def __init__(self, alerter: Alerter, room, pipeline, persona, max_per_call: int = 3):
        self.alerter, self.room, self.pipeline = alerter, room, pipeline
        self.policy = AlertPolicy(max_per_call)
        self.tasks: set[asyncio.Task] = set()
        self._token: str | None = None
        self.last_caller_text = ""
        self.last_stages: list[str] = []
        pipeline.on_trigger.append(self.on_trigger)
        pipeline.on_new_stage.append(self.on_new_stage)
        if persona is not None:
            persona.on_takeover_hooks.append(self.on_takeover)
        room.on_final_hooks.append(self.remember)

    async def remember(self, room, turn: dict) -> None:
        if turn["channel"] == "caller":
            self.last_caller_text = turn["text"]

    @property
    def family(self):
        return getattr(self.room, "family", None)

    @property
    def t(self) -> dict:
        return self.family.pack.t if self.family is not None else lang.EN.t

    @property
    def parent(self) -> str:
        return self.family.parent_address if self.family is not None else self.alerter.settings.parent_address

    def _chats(self) -> list:
        """Every Telegram chat linked to this family. The original single household uses the configured chat."""
        if self.family is None:
            return [None] if self.alerter.settings.telegram_chat_id else []
        return list(self.family.chat_ids)

    def _caller(self) -> str:
        row = self.room.store.query("SELECT caller_number FROM calls WHERE id=?", (self.room.call_id,))
        return (row[0]["caller_number"] if row else None) or self.t["unknown"]

    def _body(self, headline: str, risk: float, stages: list[str]) -> str:
        when = local_now(self.family.timezone) if self.family is not None else ist_now()
        return (f"{headline}\n"
                f"{self.t['risk'].format(risk=round(risk))} · {stage_list(stages, self.t)}\n"
                f"{self.t['caller']}: {self._caller()}\n"
                f"“{snippet(self.last_caller_text)}”\n"
                f"{when}")

    def token(self) -> str:
        """One short token per call, shared by every button we put in Telegram for it."""
        if self._token is None:
            self._token = self.room.store.make_answer_token(self.room.call_id)
        return self._token

    async def on_trigger(self, pipeline, decision, info: dict) -> None:
        self.last_stages = decision.stages_all
        await self._send("warning", self._body(self.t["warn_head"], decision.risk_cum, decision.stages_all) +
                         "\n" + self.t["warn_tail"].format(p=self.parent), decision.stages_all, control=True)

    async def on_new_stage(self, pipeline, decision, info: dict) -> None:
        self.last_stages = decision.stages_all
        if not pipeline.triggered:
            return
        await self._send("stage_update", self._body(self.t["escalate_head"],
                                                    decision.risk_cum, decision.stages_all), decision.new_stages)

    async def on_takeover(self, persona) -> None:
        await self._send("takeover", self._body(self.t["takeover_head"],
                                                self.pipeline.max_risk, self.last_stages), None, control=True)

    async def call_ended(self, report_text: str, pdf_path: Path | None) -> None:
        await self._send("call_end", report_text, None, document=pdf_path, keyboard=True)

    async def _send(self, kind: str, text: str, stages: list[str] | None, document: Path | None = None,
                    keyboard: bool = False, control: bool = False) -> None:
        room = self.room
        if room.mode == "eval":
            room.log_event("alert_skipped", {"kind": kind, "reason": "eval call"})
            return
        if room.ended and kind != "call_end":
            room.log_event("alert_suppressed", {"kind": kind, "reason": "call already ended"})
            return
        chats = self._chats()
        if not self.alerter.enabled or not chats:
            room.log_event("alert_skipped", {"kind": kind, "reason": "telegram not configured" if not self.alerter.enabled else "no telegram chat linked"})
            return
        if not self.policy.allow(kind, stages):
            room.log_event("alert_suppressed", {"kind": kind, "sent": self.policy.sent})
            return
        self.policy.record(kind, stages)  # reserve the slot now so concurrent triggers cannot exceed the cap

        async def go():
            try:
                markup = (answer_keyboard(self.token(), t=self.t) if keyboard
                          else control_keyboard(self.token(), self.t["end_button"]) if control else None)
                first = None
                for chat in chats:
                    kw = {"chat_id": chat} if chat is not None else {}
                    body = await self.alerter.send_message(text, markup, **kw)
                    first = first or body
                    if document is not None and document.exists():
                        await self.alerter.send_document(document, self.t["doc_caption"], **kw)
                room.log_event("alert_sent", {"kind": kind, "message_id": first["result"]["message_id"]})
            except Exception as e:
                room.log_event("alert_failed", {"kind": kind, "error": str(e)[:200]})
                log.warning("alert %s failed: %s", kind, e)

        task = asyncio.create_task(go())
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)

    async def drain(self, timeout: float = 20) -> None:
        if self.tasks:
            await asyncio.wait(list(self.tasks), timeout=timeout)
