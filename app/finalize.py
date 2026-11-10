"""What happens when a call ends: write the complaint draft and tell the family, but only for calls that were flagged."""

import asyncio
import logging
import re
from pathlib import Path

from app import lang
from app import report as report_mod
from app.alerts import answer_keyboard

log = logging.getLogger("kavach.finalize")
CALLBACK_RE = re.compile(r"a:([\w-]{4,16}):([mo]):([yn])")


def was_flagged(room) -> bool:
    """A call is worth a complaint draft only if Kavach actually flagged it (warning triggered or takeover used).
    Merely mentioning a phone number or a website (a delivery agent, say) must not produce a complaint."""
    pipeline_triggered = room.pipeline is not None and room.pipeline.triggered
    took_over = room.takeover or (room.persona is not None and (room.persona.active or room.persona.replies > 0))
    return bool(pipeline_triggered or took_over)


def make_finalize(room, store, settings):
    async def finalize() -> dict:
        # Let the last detections and evidence land first.
        for q in (room.pipeline.queue, room.evidence.queue):
            try:
                await asyncio.wait_for(q.join(), 8)
            except asyncio.TimeoutError:
                room.log_event("finalize_timeout", {})
        if not was_flagged(room):
            return {}
        fam = getattr(room, "family", None)
        extra = {"tz": fam.timezone, "hint": fam.report_hint} if fam is not None else {}
        r, md, pdf = report_mod.generate(store, room.call_id, settings.reports_dir, **extra)
        n = sum(len(v) for v in r.evidence.values())
        t = fam.pack.t if fam is not None else lang.EN.t
        await room.alerts.call_ended(t["report_ready"].format(n=n, hint=r.hint), pdf)
        await room.alerts.drain()
        room.log_event("report_ready", {"md": str(md), "pdf": str(pdf), "details": n})
        return {"report": {"md": f"/api/calls/{room.call_id}/report.md", "pdf": f"/api/calls/{room.call_id}/report.pdf"}}

    return finalize


async def handle_answer_callback(update: dict, alerter, store, settings, accounts=None) -> None:
    """A family member pressed one of the call-end buttons: record the answer, rebuild the draft, confirm in Telegram.
    Only presses from the configured chat count; anything else is ignored."""
    cq = update.get("callback_query")
    if not cq:
        return
    message = cq.get("message") or {}
    chat = (message.get("chat") or {}).get("id")
    fam = accounts.family_for_chat(chat) if accounts is not None else None
    if fam is None and str(chat) != str(settings.telegram_chat_id):
        log.warning("ignored a button press from an unexpected chat")
        return
    t = fam.pack.t if fam is not None else lang.EN.t
    m = CALLBACK_RE.fullmatch(cq.get("data", ""))
    if not m:
        return
    token, question, answer = m.groups()
    call_id = store.call_for_token(token)
    owner = store.query("SELECT family_id FROM calls WHERE id=?", (call_id,)) if call_id else []
    if call_id is None or (fam is not None and owner and (owner[0]["family_id"] or "default") != fam.id):
        await alerter.answer_callback(cq["id"], t["expired"])
        return
    field = "money_shared" if question == "m" else "otp_shared"
    store.update_call(call_id, **{field: 1 if answer == "y" else 0})
    row = store.query("SELECT money_shared, otp_shared FROM calls WHERE id=?", (call_id,))[0]
    money = None if row["money_shared"] is None else bool(row["money_shared"])
    otp = None if row["otp_shared"] is None else bool(row["otp_shared"])
    label = t["money_label"] if question == "m" else t["otp_label"]
    await alerter.answer_callback(cq["id"], t["saved"].format(label=label, answer=t["yes"] if answer == "y" else t["no"]))
    await alerter.edit_markup(message["chat"]["id"], message["message_id"], answer_keyboard(token, money, otp, t))
    extra = {"tz": fam.timezone, "hint": fam.report_hint} if fam is not None else {}
    r, md, pdf = report_mod.generate(store, call_id, settings.reports_dir, **extra)  # the draft now carries the answer
    if money is not None and otp is not None:  # both answered: send the finished draft once
        await alerter.send_document(Path(pdf), t["doc_caption2"], chat_id=chat)
