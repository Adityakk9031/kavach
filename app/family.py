"""The family's side of a call, from Telegram.

* A voice note sent to the bot plays on the protected person's phone at once, even after the call has been cut:
  the son cannot ring a father whose line is busy with a scammer, so his voice goes straight to the Kavach app.
* "End the call": drops the real call on the person's phone, and says so only when the phone confirms it.

Only the one configured Telegram chat can do either. Voice notes are decoded in memory and never stored.
"""

import io
import logging
import re
import time

import av

from app.call_room import CallRoom, RoomRegistry

log = logging.getLogger("kavach.family")
DESK = "family-desk"  # events table key for what the family does in Telegram
MAX_SECONDS = 120
VOICE_ID_RE = re.compile(r"[\w.-]{3,64}")
CONTROL_RE =re.compile(r"c:([\w-]{4,16}):e")


def decode_voice_note(data: bytes, rate: int = 16000, max_seconds: int = MAX_SECONDS) -> bytes:
    """Telegram voice notes are OGG/Opus. Returns 16 kHz mono signed 16-bit PCM (what the app plays). ValueError if the
    bytes are not audio, are too short to hear, or are longer than `max_seconds`."""
    try:
        container = av.open(io.BytesIO(data))
        stream = next(s for s in container.streams if s.type == "audio")
    except (av.error.FFmpegError, StopIteration, ValueError, OSError) as e:
        raise ValueError("that is not a playable audio message") from e
    resampler = av.AudioResampler(format="s16", layout="mono", rate=rate)
    out = bytearray()
    limit = max_seconds * rate * 2
    try:
        for frame in container.decode(stream):
            for r in resampler.resample(frame):
                out += r.to_ndarray().tobytes()  # exact samples, no padding
            if len(out) > limit:
                raise ValueError(f"longer than {max_seconds} seconds")
        for r in resampler.resample(None):
            out += r.to_ndarray().tobytes()
    except av.error.FFmpegError as e:
        raise ValueError("that audio could not be decoded") from e
    if len(out) < int(rate * 2 * 0.3):
        raise ValueError("too short to hear")
    return bytes(out)


class FamilyDesk:
    def __init__(self, alerter, store, rooms: RoomRegistry, settings):
        self.alerter, self.store, self.rooms, self.settings = alerter, store, rooms, settings

    def _log(self, type_: str, **payload) -> None:
        """What the family did in Telegram and what came of it, kept apart from any call so a test can be checked from
        the logs even when no call was on."""
        try:
            self.store.add_event(DESK, type_, time.monotonic(), payload)
        except Exception:
            log.exception("could not log a family action")

    def _authorized(self, chat_id) -> bool:
        return str(chat_id) == str(self.settings.telegram_chat_id)

    async def _say(self, text: str) -> None:
        try:
            await self.alerter.send_message(text)
        except Exception:
            log.exception("could not reply in Telegram")

    # ---- Papa's cloned voice for the takeover ----------------------------------------------------------------------

    async def _set_voice(self, text: str) -> None:
        """`/setvoice <voice id>`: the takeover persona speaks in this voice from the next takeover on (until a restart;
        put PERSONA_VOICE_ID in .env to keep it). The clone itself is made in the AssemblyAI dashboard."""
        parts = text.split()
        if len(parts) == 1:
            await self._say(f"The takeover voice is now: {self.settings.persona_voice_id}\n"
                            "To change it: /setvoice <voice id from the AssemblyAI dashboard>")
        elif len(parts) == 2 and VOICE_ID_RE.fullmatch(parts[1]):
            self.settings.persona_voice_id = parts[1]
            await self._say(f"Done. Kavach will speak in voice {parts[1]} when it takes over a call.")
        else:
            await self._say("That does not look like a voice id. Copy it exactly from the AssemblyAI dashboard.")

    # ---- a voice note -----------------------------------------------------------------------------------------

    async def handle_message(self, update: dict) -> None:
        msg = update.get("message") or {}
        voice = msg.get("voice")
        if not self._authorized((msg.get("chat") or {}).get("id")):
            return
        text = (msg.get("text") or "").strip()
        if text.startswith("/setvoice"):
            await self._set_voice(text)
            return
        if not voice:
            return
        room = self.rooms.family_target()
        # With no call running, the phone's always-on link is surer than the socket of a call that has just ended.
        phone = getattr(self.rooms, "phone", None) if room is None or room.ended else None
        self._log("voice_note", call=getattr(room, "call_id", None), call_running=bool(room and not room.ended),
                  phone_link=getattr(self.rooms, "phone", None) is not None, seconds=voice.get("duration"))
        if room is None and phone is None:
            self._log("voice_note_result", result="no phone")
            await self._say("I could not send this. Papa's phone is not connected to Kavach right now.")
            return
        if voice.get("duration", 0) > MAX_SECONDS:
            await self._say(f"That voice note is too long. Keep it under {MAX_SECONDS} seconds.")
            return
        try:
            pcm = decode_voice_note(await self.alerter.download_file(voice["file_id"]), self.settings.sample_rate)
        except ValueError as e:
            await self._say(f"I could not play that: {e}.")
            return
        except Exception:
            log.exception("could not fetch the voice note")
            await self._say("I could not download that voice note. Please try again.")
            return
        seconds = round(len(pcm) / 2 / self.settings.sample_rate)
        if phone is not None:
            delivered = await self.rooms.play_on_phone(pcm)
            self._log("voice_note_result", result="played" if delivered else "no ack", via="phone link")
            await self._say(f"▶️ Playing on Papa's phone now ({seconds} s)." if delivered
                            else "Papa's phone did not confirm it got this. It may have no internet right now.")
            return
        # The family's voice comes first: stop a warning that is still playing in Papa's earpiece.
        if room.warning is not None and room.warning.active:
            await room.warning.barge_in("family")
        delivered = await room.play_family(pcm)
        self._log("voice_note_result", result="played" if delivered else "no ack", via="call")
        await self._say(f"▶️ Playing on Papa's phone now ({seconds} s)." if delivered
                        else "Papa's app is not connected, so it could not be played.")

    # ---- the End-the-call button ------------------------------------------------------------------------------

    async def handle_control(self, update: dict) -> None:
        cq = update.get("callback_query") or {}
        message = cq.get("message") or {}
        if not self._authorized((message.get("chat") or {}).get("id")):
            log.warning("ignored a control press from an unexpected chat")
            return
        m = CONTROL_RE.fullmatch(cq.get("data", ""))
        if not m:
            return
        call_id = self.store.call_for_token(m.group(1))
        room = self.rooms.rooms.get(call_id) if call_id else None
        self._log("end_pressed", call=call_id, running=bool(room and not room.ended))
        if room is None or room.ended:
            await self.alerter.answer_callback(cq["id"], "That call has already ended.")
            return
        room.log_event("ended_from_telegram", {})
        await self.alerter.answer_callback(cq["id"], "Ending the call.")
        if room.phone_call:
            result = await room.hang_up()
            self._log("end_result", call=call_id, result=result)
            if not (result or "").startswith("ok"):
                room.log_event("hang_up_failed", {"result": result})
                await self._say("⚠️ I could not cut Papa's phone call, so it is still on. Kavach is still protecting it. "
                                "Please try ringing or messaging Papa.")
                return
        await room.end()
        await self._say("☎️ The call was ended. Send a voice note now and it will play on Papa's phone.")
