"""The family's side of a call, from Telegram.

* A voice note sent to the bot plays on the protected person's phone at once, even after the call has been cut:
  the son cannot ring a father whose line is busy with a scammer, so his voice goes straight to the Kavach app.
* "End the call": drops the call on the person's side.

Only the one configured Telegram chat can do either. Voice notes are decoded in memory and never stored.
"""

import io
import logging
import re
import time

import av

from app.call_room import CallRoom, RoomRegistry

log = logging.getLogger("kavach.family")
MAX_SECONDS = 120
CONTROL_RE = re.compile(r"c:([\w-]{4,16}):e")


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

    def _authorized(self, chat_id) -> bool:
        return str(chat_id) == str(self.settings.telegram_chat_id)

    async def _say(self, text: str) -> None:
        try:
            await self.alerter.send_message(text)
        except Exception:
            log.exception("could not reply in Telegram")

    # ---- a voice note -----------------------------------------------------------------------------------------

    async def handle_message(self, update: dict) -> None:
        msg = update.get("message") or {}
        voice = msg.get("voice")
        if not voice or not self._authorized((msg.get("chat") or {}).get("id")):
            return
        room = self.rooms.family_target()
        if room is None:
            await self._say("No call to send this to. Papa's Kavach app is not connected right now.")
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
        # The family's voice comes first: stop a warning that is still playing in Papa's earpiece.
        if room.warning is not None and room.warning.active:
            await room.warning.barge_in("family")
        delivered = await room.play_family(pcm)
        seconds = round(len(pcm) / 2 / self.settings.sample_rate)
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
        if room is None or room.ended:
            await self.alerter.answer_callback(cq["id"], "That call has already ended.")
            return
        room.log_event("ended_from_telegram", {})
        await self.alerter.answer_callback(cq["id"], "Ending the call.")
        await room.end()
        await self._say("☎️ The call was ended. Send a voice note now and it will play on Papa's phone.")
