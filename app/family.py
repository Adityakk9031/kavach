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

from app import lang
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
    def __init__(self, alerter, store, rooms: RoomRegistry, settings, accounts=None):
        self.alerter, self.store, self.rooms, self.settings, self.accounts = alerter, store, rooms, settings, accounts

    def _log(self, type_: str, **payload) -> None:
        """What the family did in Telegram and what came of it, kept apart from any call so a test can be checked from
        the logs even when no call was on."""
        try:
            self.store.add_event(DESK, type_, time.monotonic(), payload)
        except Exception:
            log.exception("could not log a family action")

    def _who(self, chat_id):
        """(allowed, family, language texts, how the parent is addressed). Only a chat linked to a family, or the one
        chat configured for the original household, may act."""
        fam = self.accounts.family_for_chat(chat_id) if self.accounts is not None else None
        if fam is not None:
            return True, fam, fam.pack.t, fam.parent_address
        ok = str(chat_id) == str(self.settings.telegram_chat_id)
        return ok, None, lang.EN.t, self.settings.parent_address

    def _authorized(self, chat_id) -> bool:
        return self._who(chat_id)[0]

    async def _say(self, text: str, chat_id=None, fam=None) -> None:
        try:
            if fam is not None and chat_id is not None:
                await self.alerter.send_message(text, chat_id=chat_id)
            else:
                await self.alerter.send_message(text)
        except Exception:
            log.exception("could not reply in Telegram")

    def _own_call(self, room, fam) -> bool:
        return fam is None or room is None or (room.family.id if room.family else "default") == fam.id

    # ---- linking a chat to a family: /start <token> ----------------------------------------------------------

    async def _start(self, chat_id, text: str) -> None:
        parts = text.split(maxsplit=1)
        if len(parts) < 2 or self.accounts is None:
            await self._say(lang.EN.t["welcome"], chat_id, fam=True)
            return
        fam = self.accounts.link_chat(parts[1].strip(), chat_id)
        if fam is None:
            await self._say(lang.EN.t["link_bad"], chat_id, fam=True)
            return
        self._log("telegram_linked", family=fam.id)
        await self._say(fam.pack.t["linked"].format(p=fam.parent_address), chat_id, fam=True)

    # ---- Papa's cloned voice for the takeover (the original household; families record theirs in the app) -------

    async def _set_voice(self, text: str) -> None:
        """`/setvoice <voice id>`: the takeover persona speaks in this voice from the next takeover on (until a restart;
        put PERSONA_VOICE_ID in .env to keep it)."""
        parts = text.split()
        if len(parts) == 1:
            await self._say(f"The takeover voice is now: {self.settings.persona_voice_id}\n"
                            "To change it: /setvoice <voice id from the AssemblyAI dashboard>")
        elif len(parts) == 2 and VOICE_ID_RE.fullmatch(parts[1]):
            self.settings.persona_voice_id = parts[1]
            await self._say(lang.EN.t["voice_set"].format(voice=parts[1]))
        else:
            await self._say("That does not look like a voice id. Copy it exactly from the AssemblyAI dashboard.")

    # ---- a voice note -----------------------------------------------------------------------------------------

    async def handle_message(self, update: dict) -> None:
        msg = update.get("message") or {}
        chat_id = (msg.get("chat") or {}).get("id")
        text = (msg.get("text") or "").strip()
        if text.startswith("/start"):
            await self._start(chat_id, text)
            return
        allowed, fam, t, p = self._who(chat_id)
        if not allowed:
            return
        voice = msg.get("voice")
        if text.startswith("/setvoice") and (fam is None or fam.id == "default"):
            await self._set_voice(text)
            return
        if not voice:
            return
        say = lambda m: self._say(m, chat_id, fam)  # noqa: E731
        fid = fam.id if fam is not None else None
        room = self.rooms.family_target(family_id=fid) if fid else self.rooms.family_target()
        # With no call running, the phone's always-on link is surer than the socket of a call that has just ended.
        link = (self.rooms.phones.get(fid) if fid else getattr(self.rooms, "phone", None))
        phone = link if room is None or room.ended else None
        self._log("voice_note", call=getattr(room, "call_id", None), call_running=bool(room and not room.ended),
                  phone_link=link is not None, seconds=voice.get("duration"))
        if room is None and phone is None:
            self._log("voice_note_result", result="no phone")
            await say(t["no_phone"].format(p=p))
            return
        if voice.get("duration", 0) > MAX_SECONDS:
            await say(t["too_long"].format(n=MAX_SECONDS))
            return
        try:
            pcm = decode_voice_note(await self.alerter.download_file(voice["file_id"]), self.settings.sample_rate)
        except ValueError as e:
            await say(t["cannot_play"].format(why=e))
            return
        except Exception:
            log.exception("could not fetch the voice note")
            await say(t["cannot_download"])
            return
        seconds = round(len(pcm) / 2 / self.settings.sample_rate)
        if phone is not None:
            delivered = await (self.rooms.play_on_phone(pcm, family_id=fid) if fid else self.rooms.play_on_phone(pcm))
            self._log("voice_note_result", result="played" if delivered else "no ack", via="phone link")
            await say(t["playing"].format(p=p, n=seconds) if delivered else t["no_confirm"].format(p=p))
            return
        # The family's voice comes first: stop a warning that is still playing in the parent's earpiece.
        if room.warning is not None and room.warning.active:
            await room.warning.barge_in("family")
        delivered = await room.play_family(pcm)
        self._log("voice_note_result", result="played" if delivered else "no ack", via="call")
        await say(t["playing"].format(p=p, n=seconds) if delivered else t["app_offline"].format(p=p))

    # ---- the End-the-call button ------------------------------------------------------------------------------

    async def handle_control(self, update: dict) -> None:
        cq = update.get("callback_query") or {}
        message = cq.get("message") or {}
        chat_id = (message.get("chat") or {}).get("id")
        allowed, fam, t, p = self._who(chat_id)
        if not allowed:
            log.warning("ignored a control press from an unexpected chat")
            return
        m = CONTROL_RE.fullmatch(cq.get("data", ""))
        if not m:
            return
        say = lambda msg: self._say(msg, chat_id, fam)  # noqa: E731
        call_id = self.store.call_for_token(m.group(1))
        room = self.rooms.rooms.get(call_id) if call_id else None
        if room is not None and not self._own_call(room, fam):
            await self.alerter.answer_callback(cq["id"], t["already_ended"])  # never reveal or end another family's call
            return
        self._log("end_pressed", call=call_id, running=bool(room and not room.ended))
        if room is None or room.ended:
            await self.alerter.answer_callback(cq["id"], t["already_ended"])
            return
        room.log_event("ended_from_telegram", {})
        await self.alerter.answer_callback(cq["id"], t["ending"])
        if room.phone_call:
            result = await room.hang_up()
            self._log("end_result", call=call_id, result=result)
            if not (result or "").startswith("ok"):
                room.log_event("hang_up_failed", {"result": result})
                await say(t["could_not_cut"].format(p=p))
                return
        await room.end()
        await say(t["call_ended"].format(p=p))
