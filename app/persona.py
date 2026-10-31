"""Takeover persona (F3): a slow, polite, slightly confused person who keeps the scammer talking and asks the
questions that make them state their details (UPI ID, account, IFSC, name, officer ID, callback number, links).

Safety: the persona only ever says the clearly fake decoy details from config. Every reply passes `guard()`, which
blocks digits, e-mail/UPI/URL shapes and number-words that are not the decoy phone, and falls back to a stalling line.
Take back is instant: cancel the TTS, flush both tabs' persona playback, unmute the receiver.
"""

import asyncio
import logging
import re
import time

from app.call_room import SOURCE_PERSONA, CallRoom
from app.config import Settings
from app.llm import LLM, LLMError
from app.tts import TtsError, TtsPool, TtsSession

log = logging.getLogger("kavach.persona")

STALLS = [
    "Sorry, uh, the line is not very clear. Can you say that again, slowly?",
    "One minute please, I am looking for my glasses. Please repeat that.",
    "Ah, I am writing it down. Can you say it once more, slowly?",
]
OPENING = "Hello? Ah, sorry, I was not hearing properly. Please continue, I am listening."

NUMBER_WORDS = {"zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "oh"}


def system_prompt(s: Settings) -> str:
    d = s.decoy
    return f"""You are {d.name}, a 72-year-old retired clerk from {d.city}, on a phone call with a stranger who may be a scammer.
You are slow, polite, a little hard of hearing and confused by technology.

Your real goal: keep them talking as long as possible and make them state their details: the exact UPI ID or account
number and IFSC, the bank, their full name, officer or badge or case ID, a callback phone number, any link or app name.
How: ask them to repeat things slowly, ask them to spell names and IDs letter by letter, say you are writing it down,
ask for a number to call back if the line drops, ask which bank and branch, ask who their senior officer is.

Hard rules:
- Never agree to pay or send anything. Stall: you are looking for your glasses, your passbook, the card is in another
  room, the phone is slow, you want to ask your son. Never actually complete anything.
- Never give an OTP, PIN, CVV, card number, password or Aadhaar number. If asked, stall ("my glasses... one moment").
- The ONLY facts about yourself you may mention are: name {d.name}, city {d.city}, bank {d.bank}, last four digits of
  your account "{d.account_last4}", and the phone number "{d.phone}". All of these are fake. Invent nothing else about yourself.
- Reply with one or two SHORT spoken sentences. Plain words written for text to speech: no digits (write numbers as
  words), no lists, no stage directions, no quotes. Light fillers like "uh" or "ah" are fine.
Output only what you say aloud."""


def guard(text: str, decoy_phone: str) -> tuple[str, str | None]:
    """Return (safe text, reason it was replaced or None). Blocks anything that could be a real identifier."""
    t = text.strip().strip('"').strip()
    if not t:
        return STALLS[0], "empty"
    if re.search(r"\d", t):
        return STALLS[1], "digits"
    if re.search(r"@|https?://|www\.|\.com\b|\.in\b", t, re.I):
        return STALLS[1], "address-like"
    words = re.findall(r"[a-z]+", t.lower())
    run = best = 0
    for w in words:
        run = run + 1 if w in NUMBER_WORDS else 0
        best = max(best, run)
    decoy_run = sum(1 for w in re.findall(r"[a-z]+", decoy_phone.lower()) if w in NUMBER_WORDS)
    if best > 4 and decoy_run < 6:
        return STALLS[1], "number-run"
    if best > 4 and decoy_phone.lower().replace(",", "") not in t.lower().replace(",", ""):
        return STALLS[1], "number-run-not-decoy"
    if len(t) > 400:
        return STALLS[2], "too-long"
    return t, None


class Persona:
    def __init__(self, settings: Settings, llm: LLM, pool: TtsPool):
        self.settings, self.llm, self.pool = settings, llm, pool

    def attach(self, room: CallRoom) -> "CallPersona":
        p = CallPersona(self, room)
        room.on_final_hooks.append(p.on_final)
        room.on_speech_started_hooks.append(p.on_speech_started)
        room.control_handlers["takeover"] = p.on_takeover
        room.control_handlers["takeback"] = p.on_takeback
        room.persona = p
        return p


class CallPersona:
    def __init__(self, persona: Persona, room: CallRoom):
        self.persona, self.room = persona, room
        self.s = persona.settings
        self.active = False
        self.history: list[dict] = []
        self.session: TtsSession | None = None
        self.request = None
        self.play_until = 0.0
        self.pending: asyncio.Task | None = None
        self.on_takeover_hooks: list = []
        self.replies = 0

    @property
    def speaking(self) -> bool:
        return (self.request is not None and not self.request.done.is_set()) or time.monotonic() < self.play_until

    # ---- control ---------------------------------------------------------------------------------

    async def on_takeover(self, room: CallRoom, role: str, msg: dict) -> None:
        if role != "receiver" or self.active or room.ended:
            return
        self.active = True
        room.takeover = True  # receiver microphone no longer reaches the caller
        # A warning still playing would talk over the persona: the user chose to hand over.
        if room.warning is not None and room.warning.active:
            await room.warning.barge_in("takeover")
        room.store.update_call(room.call_id, takeover_at=time.time())
        room.log_event("takeover", {"by": role})
        await room.broadcast({"type": "takeover", "state": "on"})
        for hook in self.on_takeover_hooks:
            await hook(self)
        self.pending = asyncio.create_task(self._reply(opening=True))

    async def on_takeback(self, room: CallRoom, role: str, msg: dict) -> None:
        if role != "receiver" or not self.active:
            return
        t0 = time.monotonic()
        self.active = False
        room.takeover = False  # unmute first: the user's voice reaches the caller again immediately
        if self.pending:
            self.pending.cancel()
        sent = None
        if self.session is not None and self.request is not None and not self.request.done.is_set():
            sent = await self.session.cancel()
        self.play_until = 0.0
        for role_ in ("caller", "receiver"):
            await room.flush_playback(role_, SOURCE_PERSONA)
        room.log_event("takeback", {"cancel_sent_ms": round((sent - t0) * 1000) if sent else None,
                                    "total_ms": round((time.monotonic() - t0) * 1000)}, t0)
        await room.broadcast({"type": "takeover", "state": "off"})

    # ---- conversation ----------------------------------------------------------------------------

    async def on_final(self, room: CallRoom, turn: dict) -> None:
        if not self.active or turn["channel"] != "caller":
            return
        self.history.append({"role": "user", "content": turn["text"]})
        if self.pending and not self.pending.done():
            self.pending.cancel()  # the scammer said more: answer the latest thing only
        self.pending = asyncio.create_task(self._reply(turn=turn))

    async def on_speech_started(self, room: CallRoom, channel: str, ev: dict) -> None:
        """The scammer starts talking over the persona: stop talking, like a polite person would."""
        if channel == "caller" and self.active and self.speaking:
            await self._interrupt("caller_speech")

    async def _interrupt(self, why: str) -> None:
        t0 = time.monotonic()
        if self.session is not None and self.request is not None and not self.request.done.is_set():
            await self.session.cancel()
        self.play_until = 0.0
        for role_ in ("caller", "receiver"):
            await self.room.flush_playback(role_, SOURCE_PERSONA)
        self.room.log_event("persona_interrupted", {"why": why}, t0)

    async def _reply(self, turn: dict | None = None, opening: bool = False) -> None:
        room = self.room
        try:
            t_start = time.monotonic()
            llm_ms = None
            if opening:
                text, replaced = OPENING, None
            else:
                try:
                    msgs = [{"role": "system", "content": system_prompt(self.s)}] + self.history[-12:]
                    raw, llm_ms = await self.persona.llm.chat(
                        self.s.persona_model, msgs, max_tokens=120, temperature=0.7, timeout=6)
                    text, replaced = guard(raw, self.s.decoy.phone)
                except LLMError as e:
                    log.warning("persona LLM failed: %s", e)
                    text, replaced = STALLS[self.replies % len(STALLS)], "llm-error"
            if replaced:
                room.log_event("persona_guard", {"reason": replaced})
            if not self.active:
                return
            self.history.append({"role": "assistant", "content": text})
            self.replies += 1
            idx = room.turn_idx
            room.turn_idx += 1
            room.store.add_turn(room.call_id, "persona", idx, text, None, None, time.monotonic(), None, is_decoy=True)
            turn_end_at = None
            if turn and turn.get("audio_end_ms") is not None and "caller" in room.clocks:
                turn_end_at = room.clocks["caller"].time_at(turn["audio_end_ms"])
            await room.broadcast({"type": "persona", "state": "speaking", "text": text, "decoy": True})
            await self._speak(text, t_start, turn_end_at, llm_ms)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("persona reply failed")

    async def _speak(self, text: str, t_start: float, turn_end_at: float | None, llm_ms: int | None) -> None:
        room = self.room
        try:
            session = await self.persona.pool.get(self.s.persona_voice_id, "persona")
        except (TtsError, OSError) as e:
            room.log_event("persona_error", {"error": str(e)})
            return
        self.session = session
        first = True

        async def on_audio(pcm: bytes) -> None:
            nonlocal first
            if not self.active:
                return
            now = time.monotonic()
            self.play_until = max(self.play_until, now) + len(pcm) / 2 / self.s.sample_rate
            if first:
                first = False
                room.log_event("persona_first_audio", {
                    "llm_ms": llm_ms, "tts_ttfa_ms": round(self.request.ttfa_ms) if self.request else None,
                    "turn_end_to_audio_ms": round((now - turn_end_at) * 1000) if turn_end_at else None,
                    "text": text}, now)
            await room.send_audio("caller", SOURCE_PERSONA, pcm)  # the scammer hears the persona
            await room.send_audio("receiver", SOURCE_PERSONA, pcm)  # the user can listen in

        self.request = await session.speak(text, on_audio)
        await self.request.done.wait()
        if self.active:
            await room.broadcast({"type": "persona", "state": "done"})
