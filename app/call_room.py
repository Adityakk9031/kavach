"""The simulated phone line: relays audio between the Caller and Receiver tabs and taps each channel to STT.

Wire format to a browser tab:
  * binary frame = 1 header byte (audio source) + PCM s16le mono at settings.sample_rate
  * text frame   = JSON event
Audio sources let the browser flush one stream (e.g. the warning on barge-in) without touching the others.
"""

import asyncio
import bisect
import json
import logging
import time
from collections.abc import Callable
from typing import Protocol

from app.store import Store

log = logging.getLogger("kavach.room")

ROLES = ("caller", "receiver")
# The Caller side stands in for the scammer's phone. It must learn nothing about what Kavach is doing (warning,
# takeover, decoy, risk, evidence): only call presence, STT status, and the transcript of its OWN speech.
CALLER_EVENTS = {"presence", "stt_status", "call_ended", "call_rejected"}


def caller_may_see(event: dict) -> bool:
    return event.get("type") in CALLER_EVENTS or (event.get("type") == "transcript" and event.get("channel") == "caller")
SOURCE_PEER, SOURCE_WARNING, SOURCE_PERSONA, SOURCE_FAMILY = 0, 1, 2, 3


class Sendable(Protocol):
    async def send_bytes(self, data: bytes) -> None: ...
    async def send_text(self, data: str) -> None: ...


class Stt(Protocol):
    model: str | None
    async def start(self) -> None: ...
    async def send_audio(self, pcm: bytes) -> None: ...
    async def close(self) -> None: ...


SttFactory = Callable[[str, Callable], Stt]


class AudioClock:
    """Maps a channel's STT audio timeline (ms since its first byte) to the monotonic time it was sent."""

    def __init__(self, sample_rate: int):
        self.bytes_per_ms = sample_rate * 2 / 1000
        self.total_bytes = 0
        self._ends_ms: list[float] = []
        self._times: list[float] = []

    def add(self, n_bytes: int, at: float) -> None:
        self.total_bytes += n_bytes
        self._ends_ms.append(self.total_bytes / self.bytes_per_ms)
        self._times.append(at)

    @property
    def audio_ms(self) -> float:
        return self.total_bytes / self.bytes_per_ms

    def time_at(self, audio_ms: float) -> float | None:
        """Monotonic time when the chunk containing `audio_ms` was sent, or None if not sent yet."""
        i = bisect.bisect_left(self._ends_ms, audio_ms)
        return self._times[i] if i < len(self._times) else None


class Peer:
    def __init__(self, ws: Sendable):
        self.ws = ws
        self.lock = asyncio.Lock()  # one writer at a time per socket

    async def send_bytes(self, data: bytes) -> bool:
        try:
            async with self.lock:
                await self.ws.send_bytes(data)
            return True
        except Exception:
            return False

    async def send_text(self, data: str) -> bool:
        try:
            async with self.lock:
                await self.ws.send_text(data)
            return True
        except Exception:
            return False


class CallRoom:
    def __init__(self, call_id: str, stt_factory: SttFactory, store: Store, sample_rate: int = 16000):
        self.call_id = call_id
        self.stt_factory = stt_factory
        self.store = store
        self.sample_rate = sample_rate
        self.parties: dict[str, Peer] = {}
        self.hang_up_result: asyncio.Future | None = None
        self.stt: dict[str, Stt] = {}
        self.clocks: dict[str, AudioClock] = {}
        self.listeners: set[Peer] = set()
        self.takeover = False
        self.turn_idx = 0
        self.stt_restarts: dict[str, int] = {}
        self.stt_offset_ms: dict[str, float] = {}  # audio already sent before the current STT session started
        self._offset_pending: set[str] = set()
        self.ended = False
        # Hooks later milestones attach to (detector, warner, persona). Each is an async callable.
        self.on_final_hooks: list[Callable] = []
        self.on_speech_started_hooks: list[Callable] = []
        self.on_end_hooks: list[Callable] = []  # stop workers (run last)
        self.finalize_hooks: list[Callable] = []  # build report / send alerts; may return a dict for the UI (run first)
        self.mode = "live"
        self.family_until = 0.0  # monotonic time until which the son's voice note is playing in Papa's phone
        self.started_wall, self.ended_wall = time.time(), None
        self.control_handlers: dict[str, Callable] = {}  # JSON control message type -> async (room, role, msg)
        self.pipeline = None
        self.warning = None
        self.persona = None
        self.evidence = None
        self.family = None  # whose call this is (None: the original single household)
        self.store.start_call(call_id)

    # ---- lifecycle -------------------------------------------------------------------------------

    async def join(self, role: str, ws: Sendable, caller_number: str | None = None, mode: str | None = None) -> None:
        if role not in ROLES:
            raise ValueError(f"unknown role {role}")
        if mode in ("live", "eval"):
            self.mode = mode
            self.store.update_call(self.call_id, mode=mode)
        if role in self.parties:
            await self.leave(role)
        self.parties[role] = Peer(ws)
        self.clocks[role] = AudioClock(self.sample_rate)
        self.stt_offset_ms.pop(role, None)  # a rejoining tab starts a new audio clock: forget the old session's offset
        self.stt_restarts.pop(role, None)
        self._offset_pending.discard(role)
        if caller_number:
            self.store.update_call(self.call_id, caller_number=caller_number)
        self.log_event("joined", {"role": role})
        stt = self.stt_factory(role, lambda ev, r=role: self._on_stt_event(r, ev))
        self.stt[role] = stt
        try:
            await stt.start()
        except Exception as e:
            log.exception("STT start failed for %s", role)
            await self.broadcast({"type": "stt_status", "channel": role, "ok": False, "error": str(e)})
        await self.broadcast({"type": "presence", "parties": sorted(self.parties)})

    async def leave(self, role: str) -> None:
        self.parties.pop(role, None)
        stt = self.stt.pop(role, None)
        if stt:
            await stt.close()
        self.log_event("left", {"role": role})
        await self.broadcast({"type": "presence", "parties": sorted(self.parties)})

    async def end(self) -> None:
        if self.ended:
            return
        self.ended = True
        self.ended_wall = time.time()
        self.store.update_call(self.call_id, ended_at=self.ended_wall)  # first: the id can no longer be reused
        await self.broadcast({"type": "call_ended"})  # tabs stop audio and controls at once; the report follows
        for role in list(self.stt):  # close STT so the last finals still reach the workers below
            stt = self.stt.pop(role)
            await stt.close()
        extra: dict = {}
        for hook in self.finalize_hooks:
            try:
                extra.update(await hook() or {})
            except Exception:
                log.exception("finalize hook failed")
        for hook in self.on_end_hooks:
            await hook()
        self.log_event("call_end", {})
        if extra:
            await self.broadcast({"type": "report_ready", **extra})

    # ---- audio -----------------------------------------------------------------------------------

    async def on_audio(self, role: str, pcm: bytes) -> None:
        """Audio from one party: tap to its STT channel, relay to the other party (unless muted)."""
        if role not in self.parties or self.ended:
            return
        clock = self.clocks[role]
        before_ms = clock.audio_ms
        clock.add(len(pcm), time.monotonic())
        stt = self.stt.get(role)
        if stt:
            if role in self._offset_pending and getattr(stt, "accepting", True):
                # The restarted session's timeline begins at the first byte it receives (during its handshake, not
                # after it): everything before this chunk is the offset.
                self.stt_offset_ms[role] = before_ms
                self._offset_pending.discard(role)
            await stt.send_audio(pcm)
        other = "receiver" if role == "caller" else "caller"
        if role == "receiver" and (self.takeover or (self.warning is not None and self.warning.active)
                                   or time.monotonic() < self.family_until):
            # Takeover, or the family-voice warning is playing: the caller must not hear the person. (Their audio
            # still goes to speech recognition above, so speaking over the warning still interrupts it.)
            return
        await self.send_audio(other, SOURCE_PEER, pcm)

    async def send_audio(self, role: str, source: int, pcm: bytes) -> None:
        if self.ended:
            return
        peer = self.parties.get(role)
        if peer:
            await peer.send_bytes(bytes([source]) + pcm)

    @property
    def phone_call(self) -> bool:
        """A real phone call heard by the phone's background listener, rather than a call between two browser tabs."""
        return self.call_id.startswith("apk-")

    async def hang_up(self, wait_s: float = 5.0) -> str | None:
        """Ask the person's phone to drop the real call. Returns what the phone reports ("ok ..." once the call has really
        gone), or None if it did not answer in time."""
        peer = self.parties.get("receiver")
        if peer is None:
            return None
        self.hang_up_result = asyncio.get_running_loop().create_future()
        await peer.send_text(json.dumps({"type": "hang_up"}))
        try:
            return await asyncio.wait_for(self.hang_up_result, wait_s)
        except asyncio.TimeoutError:
            return None

    def hang_up_reported(self, result: str) -> None:
        if self.hang_up_result is not None and not self.hang_up_result.done():
            self.hang_up_result.set_result(result)

    async def play_family(self, pcm: bytes) -> bool:
        """The family's voice note, to the protected person's phone only. Works after the call has ended too (the person's
        app is still open on its report screen), which is when a son whose father's line was busy needs it most. While it
        plays, the person's microphone does not reach the caller. Returns False if the person's app is not connected."""
        peer = self.parties.get("receiver")
        if peer is None:
            return False
        seconds = len(pcm) / 2 / self.sample_rate
        self.family_until = max(self.family_until, time.monotonic()) + seconds
        self.log_event("family_voice", {"seconds": round(seconds, 1), "call_ended": self.ended})
        await peer.send_text(json.dumps({"type": "family", "state": "playing", "seconds": round(seconds, 1),
                                         "call_id": self.call_id}))
        step = self.sample_rate * 2  # one second per frame
        for i in range(0, len(pcm), step):
            if not await peer.send_bytes(bytes([SOURCE_FAMILY]) + pcm[i:i + step]):
                return False
        return True

    async def flush_playback(self, role: str, source: int) -> None:
        """Tell a tab to drop queued audio of one source immediately (barge-in, take back)."""
        await self.send_event(role, {"type": "flush_playback", "source": source})

    # ---- events ----------------------------------------------------------------------------------

    async def send_event(self, role: str, event: dict) -> None:
        peer = self.parties.get(role)
        if peer:
            await peer.send_text(json.dumps(event))

    async def broadcast(self, event: dict) -> None:
        text = json.dumps({**event, "call_id": self.call_id})
        targets = [peer for role, peer in self.parties.items() if role != "caller" or caller_may_see(event)]
        targets += list(self.listeners)
        results = await asyncio.gather(*(p.send_text(text) for p in targets))
        for peer, ok in zip(targets, results):
            if not ok and peer in self.listeners:
                self.listeners.discard(peer)

    def log_event(self, type_: str, payload: dict, at: float | None = None) -> None:
        self.store.add_event(self.call_id, type_, at if at is not None else time.monotonic(), payload)

    async def _on_stt_event(self, channel: str, ev: dict) -> None:
        now = time.monotonic()
        kind = ev["type"]
        off = self.stt_offset_ms.get(channel, 0.0)
        if off:  # a restarted STT session counts its audio from 0; put it back on the channel's own clock
            ev = dict(ev)
            for k in ("audio_ms", "audio_start_ms", "audio_end_ms"):
                if ev.get(k) is not None:
                    ev[k] = ev[k] + off
        if kind == "begin":
            self.log_event("stt_begin", {"channel": channel, "model": ev["model"], "session": ev["session_id"]}, now)
            await self.broadcast({"type": "stt_status", "channel": channel, "ok": True, "model": ev["model"]})
        elif kind == "speech_started":
            self.log_event("speech_started", {"channel": channel, "audio_ms": ev["audio_ms"]}, now)
            await self.broadcast({"type": "speech_started", "channel": channel})
            for hook in self.on_speech_started_hooks:
                await hook(self, channel, ev)
        elif kind == "partial":
            await self.broadcast({"type": "transcript", "channel": channel, "final": False,
                                  "text": ev["text"], "turn_order": ev["turn_order"]})
        elif kind == "final":
            if not ev["text"].strip():
                return
            if channel == "caller" and self.persona is not None:
                clock = self.clocks.get(channel)
                start = clock.time_at(ev["audio_start_ms"]) if clock and ev.get("audio_start_ms") is not None else None
                end = clock.time_at(ev["audio_end_ms"]) if clock and ev.get("audio_end_ms") is not None else None
                kept = self.persona.strip_echo(ev["text"], (start, end or now) if start is not None else None)
                if kept != ev["text"]:
                    self.log_event("echo_removed", {"heard": ev["text"], "kept": kept}, now)
                    if not kept:
                        return
                    ev = dict(ev, text=kept)
            latency_ms = None
            if ev["audio_end_ms"] is not None:
                sent_at = self.clocks[channel].time_at(ev["audio_end_ms"]) if channel in self.clocks else None
                if sent_at is not None:
                    latency_ms = round((now - sent_at) * 1000)
            idx = self.turn_idx
            self.turn_idx += 1
            turn_id = self.store.add_turn(self.call_id, channel, idx, ev["text"], ev["audio_start_ms"],
                                          ev["audio_end_ms"], now, latency_ms)
            self.log_event("turn_final", {"channel": channel, "idx": idx, "turn_id": turn_id,
                                          "stt_latency_ms": latency_ms, "audio_end_ms": ev["audio_end_ms"]}, now)
            turn = {"type": "transcript", "channel": channel, "final": True, "text": ev["text"],
                    "turn_order": ev["turn_order"], "idx": idx, "turn_id": turn_id, "stt_latency_ms": latency_ms,
                    "audio_end_ms": ev["audio_end_ms"], "final_at": now}
            await self.broadcast({k: v for k, v in turn.items() if k != "final_at"})
            for hook in self.on_final_hooks:
                await hook(self, turn)
        elif kind == "closed":
            await self._on_stt_closed(channel, ev)
        elif kind == "error":
            self.log_event("stt_error", {"channel": channel, "error": ev["error"]}, now)
            await self.broadcast({"type": "stt_status", "channel": channel, "ok": False, "error": ev["error"]})


    MAX_STT_RESTARTS = 2

    async def _on_stt_closed(self, channel: str, ev: dict) -> None:
        """An STT session ended. If the call is still live and nobody asked for it, say so and restart it."""
        if self.ended or channel not in self.stt or ev.get("clean", True):
            return
        self.log_event("stt_closed", {"channel": channel, "code": ev.get("code"), "reason": ev.get("reason")})
        restarts = self.stt_restarts.get(channel, 0)
        if restarts >= self.MAX_STT_RESTARTS:
            await self.broadcast({"type": "stt_status", "channel": channel, "ok": False,
                                  "error": f"STT closed ({ev.get('code')}) and restart limit reached"})
            return
        self.stt_restarts[channel] = restarts + 1
        stt = self.stt_factory(channel, lambda e, r=channel: self._on_stt_event(r, e))
        self.stt[channel] = stt
        self._offset_pending.add(channel)  # the offset is fixed when the new session takes its first audio byte
        try:
            await stt.start()
            self.log_event("stt_restarted", {"channel": channel, "attempt": restarts + 1})
        except Exception as e:
            self.log_event("stt_error", {"channel": channel, "error": f"restart failed: {e}"})
            await self.broadcast({"type": "stt_status", "channel": channel, "ok": False, "error": str(e)})


class RoomRegistry:
    def __init__(self, stt_factory: SttFactory, store: Store, sample_rate: int,
                 on_new_room: Callable[[CallRoom], None] | None = None):
        self.on_new_room = on_new_room
        self.waiting: dict[str, set] = {}  # dashboard viewers that connected before their call started
        self.rooms: dict[str, CallRoom] = {}
        self.stt_factory = stt_factory
        self.store = store
        self.sample_rate = sample_rate
        self.phones: dict[str, Peer] = {}  # each family's protected phone: its always-on link, for voice notes with no call on
        self.phone_heard = asyncio.Event()

    @property
    def phone(self) -> "Peer | None":  # the original single household
        return self.phones.get("default")

    @phone.setter
    def phone(self, peer: "Peer | None") -> None:
        if peer is None:
            self.phones.pop("default", None)
        else:
            self.phones["default"] = peer

    async def play_on_phone(self, pcm: bytes, wait_s: float = 5.0, family_id: str = "default") -> bool:
        """Send a family voice note over the phone's always-on link. True only once the phone says the note arrived, since
        a link that has quietly died still accepts what is written to it."""
        peer = self.phones.get(family_id)
        if peer is None:
            return False
        self.phone_heard.clear()
        step = self.sample_rate * 2  # one second per frame
        for i in range(0, len(pcm), step):
            if not await peer.send_bytes(bytes([SOURCE_FAMILY]) + pcm[i:i + step]):
                return False
        try:
            await asyncio.wait_for(self.phone_heard.wait(), wait_s)
            return True
        except asyncio.TimeoutError:
            return False

    def family_target(self, grace_s: float = 900.0, family_id: str | None = None) -> "CallRoom | None":
        """The call a family message goes to: a running call whose person's app is connected, else (the 'cut the call, then
        speak to Papa' case) the most recently ended call whose app is still connected within `grace_s` seconds."""
        now = time.time()
        connected = [r for r in self.rooms.values() if "receiver" in r.parties
                     and (family_id is None or (r.family.id if r.family else "default") == family_id)]
        running = [r for r in connected if not r.ended]
        pool = running or [r for r in connected if r.ended and r.ended_wall and now - r.ended_wall <= grace_s]
        return max(pool, key=lambda r: r.started_wall, default=None)

    def get(self, call_id: str, family=None) -> CallRoom:
        room = self.rooms.get(call_id)
        if room is None or room.ended:
            factory = (lambda ch, cb, f=family: self.stt_factory(ch, cb, f)) if family is not None else self.stt_factory
            room = CallRoom(call_id, factory, self.store, self.sample_rate)
            room.family = family
            if family is not None:
                self.store.update_call(call_id, family_id=family.id)
            self.rooms[call_id] = room
            room.listeners |= self.waiting.pop(call_id, set())
            if self.on_new_room:
                self.on_new_room(room)
        return room
