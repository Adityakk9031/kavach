"""Family alerts over the Telegram Bot API (F4).

Rules: at most 3 alerts per call, at most one per stage change, and a slot is always kept for the end-of-call
message. Sending never blocks the call: failures are logged as events. With no token/chat id the alerter logs
`alert_skipped` and does nothing.
"""

import asyncio
import logging
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx

from app.config import Settings

log = logging.getLogger("kavach.alerts")
IST = ZoneInfo("Asia/Kolkata")
STAGE_NAMES = {"S1": "Authority", "S2": "Threat", "S3": "Secrecy", "S4": "Urgency", "S5": "Credential request",
               "S6": "Payment request", "S7": "Remote access"}
ACTION = {"S5", "S6", "S7"}


def ist_now(ts: float | None = None) -> str:
    return datetime.fromtimestamp(ts, IST).strftime("%d %b %Y, %H:%M IST") if ts else datetime.now(IST).strftime("%d %b %Y, %H:%M IST")


def snippet(text: str, limit: int = 140) -> str:
    """At most two short lines of what the caller said."""
    t = " ".join(text.split())
    if len(t) <= limit:
        return t
    cut = t[:limit].rsplit(" ", 1)[0]
    return cut + "…"


def stage_list(stages: list[str]) -> str:
    return ", ".join(STAGE_NAMES.get(s, s) for s in sorted(stages)) or "none yet"


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
        self.enabled = bool(settings.telegram_bot_token and settings.telegram_chat_id)
        self.client = client or httpx.AsyncClient(timeout=15)
        self.base = f"https://api.telegram.org/bot{settings.telegram_bot_token}"

    async def send_message(self, text: str) -> dict:
        r = await self.client.post(f"{self.base}/sendMessage", json={
            "chat_id": self.settings.telegram_chat_id, "text": text[:4000], "disable_web_page_preview": True})
        body = r.json()
        if not body.get("ok"):
            raise RuntimeError(body.get("description", f"HTTP {r.status_code}"))
        return body

    async def send_document(self, path: Path, caption: str) -> dict:
        with open(path, "rb") as f:
            r = await self.client.post(f"{self.base}/sendDocument", data={
                "chat_id": self.settings.telegram_chat_id, "caption": caption[:900]}, files={"document": (path.name, f)})
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

    def _caller(self) -> str:
        row = self.room.store.query("SELECT caller_number FROM calls WHERE id=?", (self.room.call_id,))
        return (row[0]["caller_number"] if row else None) or "unknown number"

    def _body(self, headline: str, risk: float, stages: list[str]) -> str:
        return (f"{headline}\n"
                f"Risk {round(risk)}/100 · {stage_list(stages)}\n"
                f"Caller: {self._caller()}\n"
                f"“{snippet(self.last_caller_text)}”\n"
                f"{ist_now()}")

    async def on_trigger(self, pipeline, decision, info: dict) -> None:
        self.last_stages = decision.stages_all
        await self._send("warning", self._body("🚨 Kavach: possible scam call detected",
                                               decision.risk_cum, decision.stages_all), decision.stages_all)

    async def on_new_stage(self, pipeline, decision, info: dict) -> None:
        self.last_stages = decision.stages_all
        if not pipeline.triggered:
            return
        await self._send("stage_update", self._body("⚠️ Kavach: the call is escalating",
                                                    decision.risk_cum, decision.stages_all), decision.new_stages)

    async def on_takeover(self, persona) -> None:
        await self._send("takeover", self._body("🛡️ Kavach has taken over the call (decoy persona is talking)",
                                                self.pipeline.max_risk, self.last_stages), None)

    async def call_ended(self, report_text: str, pdf_path: Path | None) -> None:
        await self._send("call_end", report_text, None, document=pdf_path)

    async def _send(self, kind: str, text: str, stages: list[str] | None, document: Path | None = None) -> None:
        room = self.room
        if room.mode == "eval":
            room.log_event("alert_skipped", {"kind": kind, "reason": "eval call"})
            return
        if room.ended and kind != "call_end":
            room.log_event("alert_suppressed", {"kind": kind, "reason": "call already ended"})
            return
        if not self.alerter.enabled:
            room.log_event("alert_skipped", {"kind": kind, "reason": "telegram not configured"})
            return
        if not self.policy.allow(kind, stages):
            room.log_event("alert_suppressed", {"kind": kind, "sent": self.policy.sent})
            return
        self.policy.record(kind, stages)  # reserve the slot now so concurrent triggers cannot exceed the cap

        async def go():
            try:
                body = await self.alerter.send_message(text)
                if document is not None and document.exists():
                    await self.alerter.send_document(document, "1930 complaint draft (review before filing)")
                room.log_event("alert_sent", {"kind": kind, "message_id": body["result"]["message_id"]})
            except Exception as e:
                room.log_event("alert_failed", {"kind": kind, "error": str(e)[:200]})
                log.warning("alert %s failed: %s", kind, e)

        task = asyncio.create_task(go())
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)

    async def drain(self, timeout: float = 20) -> None:
        if self.tasks:
            await asyncio.wait(list(self.tasks), timeout=timeout)
