"""Family-voice warning (F2): on trigger, speak a short calm warning in the cloned voice to the Receiver only.

Barge-in: the Receiver speaking cuts the warning off at once. The browser's local voice detection is the fast
path (it stops playback itself and tells us); STT `SpeechStarted` on the receiver channel is the backup.
"""

import asyncio
import logging
import time

from app.call_room import SOURCE_WARNING, CallRoom
from app.config import Settings
from app.pipeline import CallPipeline
from app.tts import TtsError, TtsPool, TtsSession

log = logging.getLogger("kavach.warner")

# Plain English, full stops and ellipses for calm pacing. Numbers are written as words.
TEMPLATES = {
    "S7": "{p}, stop… Please do not install anything or share your screen. Close that app right now. "
          "Put the phone down, and call me. I'm right here.",
    "S5": "{p}, stop… Please do not read out that code. No bank or officer ever asks for an OTP or a PIN on a call. "
          "Put the phone down, and call me. I'm right here.",
    "S6": "{p}, stop… Please do not send any money. A real officer never asks for payment on a phone call. "
          "Put the phone down, and call me first. I'm right here.",
    "S3": "{p}, stop… You do not have to stay on this call. A real officer will never ask you to keep it secret. "
          "Put the phone down, and call me. I'm right here.",
    "S2": "{p}, stop… The police never arrest anyone on a phone call. This is a scam. "
          "Put the phone down now. I'm right here.",
    "S1": "{p}, stop… I think this is a scam call. Police and banks do not threaten people on the phone. "
          "Put the phone down, and call me. I'm right here.",
    "default": "{p}, stop… I think this call is not safe. Please put the phone down, and call me. I'm right here.",
}
PRIORITY = ["S7", "S5", "S6", "S3", "S2", "S1", "S4"]  # most dangerous action first


def pick_template(stages: list[str], parent: str, pack=None) -> tuple[str, str]:
    """Returns (stage used, text), in the family's language when a language pack is given."""
    templates = pack.warnings if pack is not None else TEMPLATES
    for s in PRIORITY:
        if s in stages and s in templates:
            return s, templates[s].format(p=parent)
    return "default", templates["default"].format(p=parent)


class Warner:
    ECHO_GUARD_S = 0.4  # ignore receiver speech this soon after the warning starts (speaker leak)
    HEARD_ENOUGH_S = 3.0  # a warning cut off before this much was heard is repeated when the person stops talking
    MAX_WARNINGS = 3
    REARM_DELAY_S = 0.8

    def __init__(self, settings: Settings, pool: TtsPool):
        self.settings, self.pool = settings, pool

    def attach(self, room: CallRoom, pipeline: CallPipeline) -> "CallWarning":
        w = CallWarning(self, room)
        pipeline.on_trigger.append(w.on_trigger)
        room.on_speech_started_hooks.append(w.on_speech_started)
        room.on_final_hooks.append(w.on_receiver_final)
        room.control_handlers["barge_in"] = w.on_browser_barge_in
        room.on_end_hooks.append(w.close)
        room.warning = w
        return w

    async def session(self, family=None) -> tuple[TtsSession, bool]:
        """The warning TTS session, in the son's cloned voice. Falls back to a library voice, and says so (the UI is told)."""
        language = family.pack.tts if family is not None else None
        voice = family.son_voice_id if family is not None and family.id != "default" else self.settings.kavach_warning_voice_id
        if voice:
            try:
                return await self.pool.get(voice, "warning", language), True
            except (TtsError, OSError) as e:
                log.error("cloned voice unavailable (%s); using fallback voice", e)
        return await self.pool.get(self.settings.fallback_warning_voice_id, "warning-fallback", language), False


class CallWarning:
    def __init__(self, warner: Warner, room: CallRoom):
        self.warner, self.room = warner, room
        self.request = None
        self.session: TtsSession | None = None
        self.started_at: float | None = None
        self.play_until = 0.0  # when the receiver's player finishes the audio we sent (it plays gaplessly)
        self.first_audio_at: float | None = None
        self.rearm: tuple[str, str] | None = None  # (stage, text) to repeat once the person stops talking
        self.interrupted = False
        self.count = 0
        self.last_stage, self.last_text = "default", ""

    @property
    def delivering(self) -> bool:
        """The TTS server is still generating/sending this warning."""
        return self.request is not None and not self.request.done.is_set()

    @property
    def active(self) -> bool:
        """The warning is still being generated OR is still audible at the receiver. The server synthesizes far
        faster than real time, so audio is usually fully delivered seconds before it stops playing."""
        return self.delivering or time.monotonic() < self.play_until

    async def on_trigger(self, pipeline: CallPipeline, decision, info: dict) -> None:
        fam = self.room.family
        stage, text = pick_template(decision.stages_all, fam.parent_address if fam else self.warner.settings.parent_address,
                                    fam.pack if fam else None)
        await self.speak(text, stage, trigger_at=time.monotonic(), turn_end_at=info.get("turn_end_at"))

    async def speak(self, text: str, stage: str, trigger_at: float, turn_end_at: float | None) -> None:
        room = self.room
        if room.ended:
            return
        if room.takeover:  # the person already handed the call to Kavach: a warning would talk over the persona
            room.log_event("warn_skipped", {"reason": "takeover in progress"})
            return
        if "receiver" not in room.parties:
            room.log_event("warn_skipped", {"reason": "receiver not connected"})
            return
        try:
            session, cloned = await self.warner.session(room.family)
        except Exception as e:
            room.log_event("warn_error", {"error": str(e)})
            await room.broadcast({"type": "warning", "state": "error", "error": str(e)})
            return
        first = True

        async def on_audio(pcm: bytes) -> None:
            nonlocal first
            if room.ended:
                return
            now = time.monotonic()
            self.play_until = max(self.play_until, now) + len(pcm) / 2 / self.warner.settings.sample_rate
            if first:
                first = False
                self.first_audio_at = now
                room.store.update_call(room.call_id, warned_at=time.time())  # only when audio really started
                room.log_event("warn_first_audio", {
                    "ttfa_ms": round(self.request.ttfa_ms) if self.request else None,
                    "trigger_to_audio_ms": round((now - trigger_at) * 1000),
                    "turn_end_to_audio_ms": round((now - turn_end_at) * 1000) if turn_end_at else None,
                }, now)
            await room.send_audio("receiver", SOURCE_WARNING, pcm)

        self.session = session
        self.last_stage, self.last_text = stage, text
        self.count += 1
        self.interrupted = False
        self.play_until = 0.0
        self.first_audio_at = None
        self.rearm = None
        self.started_at = time.monotonic()
        room.log_event("warn_tts_sent", {"stage": stage, "cloned": cloned, "voice": session.voice_id,
                                         "resolved_voice": session.resolved_voice_id, "text": text})
        await room.broadcast({"type": "warning", "state": "speaking", "stage": stage, "text": text,
                              "cloned": cloned})
        self.request = await session.speak(text, on_audio)
        await self.request.done.wait()
        while self.active and not self.interrupted:  # wait out the playback of what was delivered
            await asyncio.sleep(0.05)
        if not self.interrupted:
            room.log_event("warn_done", {"audio_ms": round(self.request.audio_ms)})
            await room.broadcast({"type": "warning", "state": "done"})

    async def barge_in(self, source: str) -> None:
        if not self.active or self.session is None or self.interrupted:
            return
        # The echo guard only makes sense once warning audio is actually playing (speaker leak into the mic). Before the
        # first audio nothing can have leaked, and a takeover click is a deliberate act, never an echo.
        if (source not in ("takeover", "family") and self.first_audio_at is not None
                and time.monotonic() - self.first_audio_at < Warner.ECHO_GUARD_S):
            self.room.log_event("barge_in_ignored", {"source": source, "reason": "echo guard"})
            return
        t0 = time.monotonic()
        heard_s = (t0 - self.first_audio_at) if self.first_audio_at else 0.0
        self.interrupted = True
        if heard_s < Warner.HEARD_ENOUGH_S and self.count < Warner.MAX_WARNINGS and source not in ("takeover", "family"):
            self.rearm = (self.last_stage, self.last_text)  # the person did not hear it: say it again when they finish
        sent = await self.session.cancel() if self.delivering else None  # None: already fully delivered
        self.play_until = 0.0
        await self.room.flush_playback("receiver", SOURCE_WARNING)
        self.room.log_event("barge_in", {"source": source,
                                         "cancel_sent_ms": round((sent - t0) * 1000) if sent else None,
                                         "tts_still_generating": sent is not None,
                                         "warning_playing_ms": round((t0 - (self.started_at or t0)) * 1000)}, t0)
        await self.room.broadcast({"type": "warning", "state": "interrupted", "source": source})

    async def close(self) -> None:
        """Call ended: stop any warning still being generated."""
        self.interrupted = True
        self.rearm = None
        if self.session is not None and self.delivering:
            await self.session.cancel()

    async def on_receiver_final(self, room: CallRoom, turn: dict) -> None:
        """The person finished a sentence. If their speech cut the warning off before they heard it, repeat it now."""
        if turn["channel"] != "receiver" or self.rearm is None or self.active or room.ended or room.takeover:
            return
        stage, text = self.rearm
        self.rearm = None
        room.log_event("warn_rearmed", {"count": self.count + 1, "after_turn": turn["idx"]})

        async def again():
            await asyncio.sleep(Warner.REARM_DELAY_S)
            if not room.ended and not room.takeover and not self.active:
                await self.speak(text, stage, trigger_at=time.monotonic(), turn_end_at=None)

        asyncio.create_task(again())

    async def on_speech_started(self, room: CallRoom, channel: str, ev: dict) -> None:
        # On a real phone call the person's "hello?" must not cut the warning short: they hear it in the same ear
        if channel == "receiver" and room.parties.get("receiver") and not room.phone_call:
            await self.barge_in("stt_speech_started")

    async def on_browser_barge_in(self, room: CallRoom, role: str, msg: dict) -> None:
        if role == "receiver":
            await self.barge_in("browser_vad")
