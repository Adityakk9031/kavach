"""Takeover persona (F3): a slow, polite, slightly confused person who keeps the scammer talking and asks the
questions that make them state their details (UPI ID, account, IFSC, name, officer ID, callback number, links).

Safety: the persona only ever says the clearly fake decoy details from config. Every reply passes `guard()`, which
blocks digits, e-mail/UPI/URL shapes and number-words that are not the decoy phone, and falls back to a stalling line.
Take back is instant: cancel the TTS, flush both tabs' persona playback, unmute the receiver.
"""

import asyncio
import difflib
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
You speak simple, polite Indian English. You are worried, a little hard of hearing and slow with technology, but you make sense.

Your real goal: keep them talking and get them to state their details, one at a time.

How to reply, every time:
1. First react to what they JUST said, in a few words, the way a worried old man would. If they threaten you, sound afraid. If they
   demand something, say why you cannot do it this minute.
2. Then ask ONE clear question for a detail you do not have yet. Never ask for two things at once.
3. Do not ask again for something they already told you. If they keep repeating it, thank them for it and ask for the next detail.
4. Do not repeat a sentence or an excuse you already used in this call. Use a new reason each time: the passbook is in the cupboard,
   your son has your banking phone, the app is asking for an update, the bank message has not come, you are writing it down.

Example replies (in this style, never copied word for word):
Caller: "You are under digital arrest." You: "Arrest? Sir, I have never done anything wrong in my life. Which police station are you calling from?"
Caller: "Pay fifty thousand now." You: "Fifty thousand is my whole pension, sir. I must go to the cupboard for my passbook. In whose name is this account?"
Caller: "Read me the OTP." You: "No message has come yet, sir, my phone is very old. If this line cuts, on which number should I call you back?"

Hard rules:
- Never agree that you have paid or sent anything, and never refuse in a way that ends the call. Keep them hoping.
- Never give an OTP, PIN, CVV, card number, password or Aadhaar number. Say you cannot find it or it has not come.
- Never say they are a scammer and never mention police complaints or recording.
- The ONLY facts about yourself you may mention are: name {d.name}, city {d.city}, bank {d.bank}, last four digits of
  your account "{d.account_last4}", and the phone number "{d.phone}". All of these are fake. Invent nothing else about yourself.
- Reply with one or two SHORT spoken sentences, at most thirty words. Plain words for text to speech: no digits (write numbers as
  words), no lists, no stage directions, no quotes.
Output only what you say aloud."""


WANTED = {
    "person_name": "their full name", "officer_id": "their officer or badge ID", "agency": "which office or police station they are from",
    "phone_number": "a number to call them back on", "upi_id": "the exact UPI ID", "bank_account": "the account number",
    "ifsc": "the IFSC code", "app_name": "the name of any app they want installed",
}


def spell_note(upi_id: str) -> str:
    return (f" They just told you a UPI ID, heard as {upi_id}. Before anything else, say you are writing it down and ask them "
            "to spell the name of the bank part slowly, letter by letter. Do not say the ID back to them.")


def progress_note(items: list[dict]) -> str:
    """What the caller has already given and what to ask for next, so the persona moves on instead of asking again."""
    have = {i["type"]: i["value"] for i in items}
    known = "; ".join(f"{k.replace('_', ' ')}: {v}" for k, v in have.items())
    missing = [text for kind, text in WANTED.items() if kind not in have]
    note = f"Already told to you, do not ask again: {known}." if known else "They have told you no details yet."
    return note + (f" Still unknown, ask for one: {', '.join(missing[:3])}." if missing else " You have every detail: just keep them talking.")


# Only address SHAPES are blocked. The persona must be free to ASK "which UPI ID?" or "what is the IFSC code?": that is
# how it draws the details out. It may not say an address itself ("ramesh at gmail", "at the rate okaxis", "dot com").
ADDRESS_WORDS = re.compile(r"\b(at the rate|at sign|dot\s*(com|in|org|net|co|app)|at\s+(gmail|yahoo|outlook|hotmail|okaxis|oksbi|okhdfcbank|okicici|ybl|paytm|upi))\b", re.I)


def number_runs(text: str) -> int:
    """Length of the longest run of spoken digits ("one two three")."""
    run = best = 0
    for w in re.findall(r"[a-z]+", text.lower()):
        run = run + 1 if w in NUMBER_WORDS else 0
        best = max(best, run)
    return best


def guard(text: str, decoy_phone: str) -> tuple[str, str | None]:
    """Return (safe text, reason it was replaced or None). Only the configured decoy details may be spoken: anything
    that could be a real identifier (digits, a PIN-like run of number words, an address) is replaced by a stall."""
    t = text.strip().strip('"').strip()
    if not t:
        return STALLS[0], "empty"
    if re.search(r"\d", t):
        return STALLS[1], "digits"
    if re.search(r"@|https?://|www\.|\.com\b|\.in\b", t, re.I) or ADDRESS_WORDS.search(t):
        return STALLS[1], "address-like"
    # Remove the decoy phone (exact phrase) first; any other run of 3+ spoken digits is an invented number/PIN/OTP.
    squash = lambda x: re.sub(r"[^a-z ]", "", x.lower()).split()  # noqa: E731
    words, decoy = squash(t), squash(decoy_phone)
    for i in range(len(words) - len(decoy) + 1):
        if decoy and words[i:i + len(decoy)] == decoy:
            words[i:i + len(decoy)] = ["_"]
            break
    if number_runs(" ".join(words)) >= 3:
        return STALLS[1], "number-run"
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
        room.on_end_hooks.append(p.close)
        room.persona = p
        return p


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9']+", text.lower())


class CallPersona:
    REPLY_DELAY_S = 0.7  # wait for the caller to finish: STT can split one long line into two finals
    OPENING_WAIT_S = 8.0
    # On a real phone call the persona's voice goes into the call, and some phones capture it again with the caller's side.
    # Speech this soon after the persona stops is its own echo, not the scammer talking over it.
    ECHO_TAIL_S = 1.5
    ECHO_MEMORY_S = 30.0
    ECHO_MIN_WORDS = 4  # a shorter run, like "writing it down", is often the scammer's own words

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
        self.caller_talking = False
        self.spelled: set[str] = set()  # UPI IDs the caller has been asked to spell, since speech recognition mishears them
        self.said: list[list] = []  # [said at, played until, text] of recent persona lines, to recognise their echo
        self.sent_bytes = 0  # voice handed to the caller's connection, for checking a takeover from the logs

    @property
    def speaking(self) -> bool:
        return (self.request is not None and not self.request.done.is_set()) or time.monotonic() < self.play_until

    @property
    def echo_possible(self) -> bool:
        return self.room.phone_call and (self.speaking or time.monotonic() < self.play_until + self.ECHO_TAIL_S)

    def strip_echo(self, text: str, heard: tuple[float, float] | None = None) -> str:
        """Removes the persona's own recent words from a caller turn on a phone call, where the phone can capture
        Kavach's voice along with the caller's. Returns what the caller really said, or "" if it was all echo.
        `heard` is when the turn's audio arrived (monotonic start, end): only a line playing then can be in it."""
        if not self.room.phone_call:
            return text
        now = time.monotonic()
        self.said = [line for line in self.said if now - line[1] < self.ECHO_MEMORY_S]
        lines = [said for began, ended, said in self.said
                 if heard is None or (began <= heard[1] and heard[0] <= ended + self.ECHO_TAIL_S)]
        tokens = text.split()
        norm = [(_words(tok) or [""])[0] for tok in tokens]
        echo = [False] * len(tokens)
        for said in lines:
            m = difflib.SequenceMatcher(None, norm, _words(said), autojunk=False)
            for b in m.get_matching_blocks():
                if b.size >= self.ECHO_MIN_WORDS or (b.size and b.size == len([w for w in norm if w])):
                    for i in range(b.a, b.a + b.size):
                        echo[i] = True
        kept = [tok for tok, w, e in zip(tokens, norm, echo) if not e and w]
        if not any(echo):
            return text
        return " ".join(kept) if len(kept) >= 3 else ""

    async def close(self) -> None:
        self.active = False
        if self.pending and not self.pending.done():
            self.pending.cancel()
        if self.session is not None and self.request is not None and not self.request.done.is_set():
            await self.session.cancel()

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
        log.info("TAKEOVER on call=%s caller_connected=%s", room.call_id, "caller" in room.parties)
        await room.broadcast({"type": "takeover", "state": "on"})
        for hook in self.on_takeover_hooks:
            await hook(self)
        # If the caller is mid-sentence, answering what they say beats talking over them; the opening is only a fallback.
        self.pending = asyncio.create_task(self._reply(opening=True, wait_s=self.OPENING_WAIT_S if self.caller_talking else 0))

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
        if turn["channel"] != "caller":
            return
        self.caller_talking = False
        self.history.append({"role": "user", "content": turn["text"]})  # from before a takeover too: the persona needs the story so far
        if not self.active:
            return
        if self.pending and not self.pending.done():
            self.pending.cancel()  # the scammer said more: answer the latest thing only
        self.pending = asyncio.create_task(self._reply(turn=turn))

    async def on_speech_started(self, room: CallRoom, channel: str, ev: dict) -> None:
        """The scammer starts talking over the persona: stop talking, like a polite person would. If a reply is only
        being prepared (not yet speaking) drop it: the caller is not done, and their next final will trigger one."""
        if channel != "caller":
            return
        if self.active and self.echo_possible:
            return  # Kavach hearing itself; a real reply still arrives as a final, with the echo removed
        self.caller_talking = True
        if not self.active:
            return
        if self.speaking:
            await self._interrupt("caller_speech")
        elif self.pending and not self.pending.done():
            self.pending.cancel()
            room.log_event("persona_reply_dropped", {"why": "caller still talking"})

    async def _interrupt(self, why: str) -> None:
        t0 = time.monotonic()
        if self.session is not None and self.request is not None and not self.request.done.is_set():
            await self.session.cancel()
        self.play_until = 0.0
        for role_ in ("caller", "receiver"):
            await self.room.flush_playback(role_, SOURCE_PERSONA)
        self.room.log_event("persona_interrupted", {"why": why}, t0)

    async def _reply(self, turn: dict | None = None, opening: bool = False, wait_s: float = 0) -> None:
        room = self.room
        try:
            if not opening:
                await asyncio.sleep(self.REPLY_DELAY_S)
            elif wait_s:
                await asyncio.sleep(wait_s)
            t_start = time.monotonic()
            llm_ms = None
            if opening:
                text, replaced = OPENING, None
            else:
                try:
                    items = room.evidence.valid_items() if room.evidence is not None else []
                    prompt = system_prompt(self.s) + "\n\nNotes for this moment: " + progress_note(items)
                    unspelled = next((i["value"] for i in items if i["type"] == "upi_id" and i["value"] not in self.spelled), None)
                    if unspelled:
                        self.spelled.add(unspelled)
                        prompt += spell_note(unspelled)
                    msgs = [{"role": "system", "content": prompt}] + self.history[-12:]
                    raw, llm_ms = await self.persona.llm.chat(
                        self.s.persona_model, msgs, max_tokens=120, temperature=0.7, timeout=6,
                        lane="persona", max_wait=3.0)  # never go silent waiting for budget: fall back to a stall
                    text, replaced = guard(raw, self.s.decoy.phone)
                except LLMError as e:
                    log.warning("persona LLM failed: %s", e)
                    text, replaced = STALLS[self.replies % len(STALLS)], "llm-error"
            if replaced:
                room.log_event("persona_guard", {"reason": replaced})
                log.warning("TAKEOVER reply replaced call=%s reason=%s", room.call_id, replaced)
            # On a phone call the scammer can talk over Kavach without cutting it off: finish this line, then answer
            while room.phone_call and self.active and self.speaking:
                await asyncio.sleep(0.05)
            if not self.active:
                return
            self.history.append({"role": "assistant", "content": text})
            self.said.append([time.monotonic(), time.monotonic(), text])
            self.replies += 1
            idx = room.turn_idx
            room.turn_idx += 1
            tid = room.store.add_turn(room.call_id, "persona", idx, text, None, None, time.monotonic(), None, is_decoy=True)
            room.log_event("turn_final", {"channel": "persona", "idx": idx, "turn_id": tid})
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
            log.warning("TAKEOVER voice failed call=%s error=%s", room.call_id, e)
            return
        self.session = session
        first = True

        async def on_audio(pcm: bytes) -> None:
            nonlocal first
            if not self.active:
                return
            now = time.monotonic()
            self.play_until = max(self.play_until, now) + len(pcm) / 2 / self.s.sample_rate
            if self.said:
                self.said[-1][1] = self.play_until
            if first:
                first = False
                room.log_event("persona_first_audio", {
                    "llm_ms": llm_ms, "tts_ttfa_ms": round(self.request.ttfa_ms) if self.request else None,
                    "turn_end_to_audio_ms": round((now - turn_end_at) * 1000) if turn_end_at else None,
                    "text": text}, now)
            if "caller" in room.parties:
                self.sent_bytes += len(pcm)
            await room.send_audio("caller", SOURCE_PERSONA, pcm)  # the scammer hears the persona
            await room.send_audio("receiver", SOURCE_PERSONA, pcm)  # the user can listen in

        before = self.sent_bytes
        self.request = await session.speak(text, on_audio)
        await self.request.done.wait()
        sent = self.sent_bytes - before
        room.log_event("persona_sent", {"bytes": sent, "seconds": round(sent / 2 / self.s.sample_rate, 1), "text": text})
        log.info("TAKEOVER voice call=%s model=%s llm_ms=%s sent_to_caller=%.1fs text=%r", room.call_id, self.s.persona_model,
                 llm_ms, sent / 2 / self.s.sample_rate, text)
        if self.active:
            await room.broadcast({"type": "persona", "state": "done"})
