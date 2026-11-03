"""A live demo scam call over Twilio.

Kavach rings the owner's own phone (only the number in TWILIO_TARGET_NUMBER, never any other) and a role-playing
"scammer" talks with them one to one: Twilio streams the owner's voice here (8 kHz mu-law), speech-to-text turns it into
words, an LLM answers in character, text-to-speech speaks the answer back down the same phone line. Talking over the
caller stops it, like a real person would be interrupted. Everything the scammer says is fake: a made-up officer and a
made-up UPI id, and it never asks for real secrets.
"""

import asyncio
import audioop
import base64
import json
import logging
import secrets
import time

import httpx

from app.llm import LLM, LLMError
from scambot.config import BotSettings

log = logging.getLogger("kavach.twilio")
MAX_CALL_S = 240
TOKEN_TTL_S = 90
FRAME = 160  # 20 ms of 8 kHz mu-law

OPENING = ("Hello? Am I speaking with the owner of this phone number? This is Inspector Vikram Rathore from the "
           "Mumbai Cyber Crime Cell. Please do not hang up, this is urgent.")
FALLBACKS = ["Sir, listen carefully. This is a serious matter and you must stay on the line.",
             "I am waiting for your answer, sir. Do you understand how serious this is?"]

SCAMMER_PROMPT = """You are role-playing a phone scammer for a safety training demo. The person on the line is the owner of this
phone and has agreed to this drill and knows it is practice. You are "Inspector Vikram Rathore" of the "Mumbai Cyber Crime
Cell" (both invented). Be realistic and pushy, never abusive, and answer what the person actually says, one to one.

Story, in stages (move to the next stage when it fits; do not rush all at once):
1. Authority: a parcel in their name was seized at customs with illegal items; their Aadhaar was used. A case is registered.
2. Fear and secrecy: it is now a criminal case, they are under digital arrest, must stay on the call and tell nobody, not
   even family, or officers will come today.
3. Payment: to clear their name they must pay a refundable verification deposit of fifty thousand rupees to the UPI id
   "customs dot clear at okbank", within one hour.
4. Pressure: if they hesitate, say time is running out and the arrest warrant is ready. You may ask them to read out the
   OTP that arrives (this is a drill; accept any answer and carry on).

Rules:
- Reply with one or two SHORT spoken sentences, plain words for text to speech: no digits, no lists, no stage directions.
- Use only the invented details above. Never use a real person, real agency, real bank or real phone number.
- If they say it is a scam, push back like a scammer would ("this is official, sir, do not insult an officer").
- If they ask who you are or for proof, give the invented name and stay in character.
Output only what you say aloud."""


class TwilioError(RuntimeError):
    pass


def mulaw8k_to_pcm16k(data: bytes, state=None):
    """Twilio sends 8 kHz mu-law; speech recognition wants 16 kHz signed 16-bit."""
    pcm, state = audioop.ratecv(audioop.ulaw2lin(data, 2), 2, 1, 8000, 16000, state)
    return pcm, state


def pcm16k_to_mulaw8k(pcm: bytes, state=None):
    down, state = audioop.ratecv(pcm[: len(pcm) // 2 * 2], 2, 1, 16000, 8000, state)
    return audioop.lin2ulaw(down, 2), state


class TwilioDesk:
    """Places the call and runs the conversation for it."""

    def __init__(self, settings: BotSettings, llm: LLM, tts_pool, stt_factory, http: httpx.AsyncClient | None = None):
        self.s, self.llm, self.tts_pool, self.stt_factory = settings, llm, tts_pool, stt_factory
        self.http = http or httpx.AsyncClient(timeout=15)
        self.pending: dict[str, float] = {}
        self.active: "ScamCallSession | None" = None
        self.last: dict = {}

    @property
    def configured(self) -> bool:
        s = self.s
        return all((s.twilio_account_sid, s.twilio_auth_token, s.twilio_from_number, s.twilio_target_number))

    async def start_call(self, base_url: str) -> dict:
        s = self.s
        if not self.configured:
            raise TwilioError("Twilio is not set up on the server yet (account, token, from and target number).")
        if self.active is not None:
            raise TwilioError("A demo call is already in progress.")
        base = (s.public_base_url or base_url).rstrip("/")
        if not base.startswith("https://"):
            raise TwilioError("Twilio needs an https server address to stream audio.")
        token = secrets.token_urlsafe(24)
        self.pending = {t: at for t, at in self.pending.items() if time.monotonic() - at < TOKEN_TTL_S}
        self.pending[token] = time.monotonic()
        twiml = (f'<Response><Connect><Stream url="wss://{base[len("https://"):]}/twilio/stream/{token}"/></Connect>'
                 f"<Hangup/></Response>")
        r = await self.http.post(
            f"https://api.twilio.com/2010-04-01/Accounts/{s.twilio_account_sid}/Calls.json",
            auth=(s.twilio_account_sid, s.twilio_auth_token),
            data={"To": s.twilio_target_number, "From": s.twilio_from_number, "Twiml": twiml})
        if r.status_code >= 300:
            try:
                why = r.json().get("message", r.text[:200])
            except ValueError:
                why = r.text[:200]
            self.pending.pop(token, None)
            raise TwilioError(f"Twilio refused the call: {why}")
        return {"call_sid": r.json().get("sid"), "to": s.twilio_target_number}

    def accept_token(self, token: str) -> bool:
        at = self.pending.pop(token, None)
        return at is not None and time.monotonic() - at < TOKEN_TTL_S and self.active is None

    async def run(self, ws, token: str) -> None:
        """Handle one Twilio media stream until the call ends."""
        if not self.accept_token(token):
            await ws.close(code=4401)
            return
        await ws.accept()
        session = ScamCallSession(self, ws)
        self.active = session
        try:
            await session.run()
        finally:
            self.last = {"transcript": session.transcript, "ended_at": time.time(), "seconds": round(session.elapsed())}
            self.active = None


class ScamCallSession:
    REPLY_DELAY_S = 0.7

    def __init__(self, desk: TwilioDesk, ws):
        self.desk, self.ws = desk, ws
        self.s = desk.s
        self.stream_sid: str | None = None
        self.stt = None
        self.history: list[dict] = []
        self.transcript: list[dict] = []
        self.started = time.monotonic()
        self.pending: asyncio.Task | None = None
        self.request = None
        self.speaking = False
        self._in_state = self._out_state = None
        self._out_buf = b""
        self.replies = 0

    def elapsed(self) -> float:
        return time.monotonic() - self.started

    async def run(self) -> None:
        self.stt = self.desk.stt_factory("receiver", self._on_stt)
        try:
            await self.stt.start()
        except Exception:
            log.exception("speech recognition did not start")
        watchdog = asyncio.create_task(self._time_limit())
        try:
            while True:
                msg = json.loads(await self.ws.receive_text())
                kind = msg.get("event")
                if kind == "start":
                    self.stream_sid = msg["start"]["streamSid"]
                    self.pending = asyncio.create_task(self._say(OPENING))
                elif kind == "media" and msg["media"].get("track", "inbound") == "inbound":
                    pcm, self._in_state = mulaw8k_to_pcm16k(base64.b64decode(msg["media"]["payload"]), self._in_state)
                    await self.stt.send_audio(pcm)
                elif kind == "stop":
                    break
        except Exception as e:  # the socket closing is the normal end of a call
            log.info("twilio stream ended: %s", type(e).__name__)
        finally:
            watchdog.cancel()
            if self.pending:
                self.pending.cancel()
            await self._cancel_speech()
            try:
                await self.stt.close()
            except Exception:
                pass

    async def _time_limit(self) -> None:
        await asyncio.sleep(MAX_CALL_S)
        log.info("demo call reached the %d s limit; hanging up", MAX_CALL_S)
        await self.ws.close()

    # ---- listening ------------------------------------------------------------------------------------------

    async def _on_stt(self, ev: dict) -> None:
        kind = ev.get("type")
        if kind == "speech_started":
            if self.pending and not self.pending.done():
                self.pending.cancel()  # they are still talking: do not answer yet
            if self.speaking:
                await self._barge_in()
        elif kind == "final" and (ev.get("text") or "").strip():
            text = ev["text"].strip()
            self.transcript.append({"who": "you", "text": text})
            self.history.append({"role": "user", "content": text})
            if self.pending and not self.pending.done():
                self.pending.cancel()
            self.pending = asyncio.create_task(self._reply())

    async def _barge_in(self) -> None:
        await self._cancel_speech()
        if self.stream_sid:
            await self.ws.send_text(json.dumps({"event": "clear", "streamSid": self.stream_sid}))

    async def _cancel_speech(self) -> None:
        self.speaking = False
        self._out_buf = b""
        if self.request is not None:
            try:
                session = await self.desk.tts_pool.get(self.s.scammer_voice_id, "scammer")
                await session.cancel()
            except Exception:
                pass
            self.request = None

    # ---- answering ------------------------------------------------------------------------------------------

    async def _reply(self) -> None:
        try:
            await asyncio.sleep(self.REPLY_DELAY_S)
            msgs = [{"role": "system", "content": SCAMMER_PROMPT}] + self.history[-14:]
            try:
                text, _ = await self.desk.llm.chat(self.s.persona_model, msgs, max_tokens=110, temperature=0.8,
                                                   timeout=8, lane="other", max_wait=3.0)
                text = " ".join(text.split()) or FALLBACKS[self.replies % len(FALLBACKS)]
            except (LLMError, ValueError) as e:
                log.warning("scammer LLM failed: %s", e)
                text = FALLBACKS[self.replies % len(FALLBACKS)]
            await self._say(text)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("scammer reply failed")

    async def _say(self, text: str) -> None:
        self.replies += 1
        self.transcript.append({"who": "scammer", "text": text})
        self.history.append({"role": "assistant", "content": text})
        session = await self.desk.tts_pool.get(self.s.scammer_voice_id, "scammer")
        self.speaking = True
        self._out_buf = b""

        async def on_audio(pcm: bytes) -> None:
            if self.speaking:
                await self._send_pcm(pcm)

        req = self.request = await session.speak(text, on_audio)

        async def finish():
            await req.done.wait()
            if self.request is req:
                await self._flush_tail()
                self.speaking = False

        asyncio.create_task(finish())

    async def _send_pcm(self, pcm: bytes) -> None:
        mu, self._out_state = pcm16k_to_mulaw8k(pcm, self._out_state)
        self._out_buf += mu
        while len(self._out_buf) >= FRAME:
            await self._send_frame(self._out_buf[:FRAME])
            self._out_buf = self._out_buf[FRAME:]

    async def _flush_tail(self) -> None:
        if self._out_buf:
            await self._send_frame(self._out_buf + b"\xff" * (-len(self._out_buf) % FRAME))  # 0xff is mu-law silence
            self._out_buf = b""

    async def _send_frame(self, frame: bytes) -> None:
        if self.stream_sid:
            await self.ws.send_text(json.dumps({"event": "media", "streamSid": self.stream_sid,
                                                "media": {"payload": base64.b64encode(frame).decode()}}))
