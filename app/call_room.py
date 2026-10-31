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
SOURCE_PEER, SOURCE_WARNING, SOURCE_PERSONA = 0, 1, 2


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
        self.stt: dict[str, Stt] = {}
        self.clocks: dict[str, AudioClock] = {}
        self.listeners: set[Peer] = set()
        self.takeover = False
        self.turn_idx = 0
        self.ended = False
        # Hooks later milestones attach to (detector, warner, persona). Each is an async callable.
        self.on_final_hooks: list[Callable] = []
        self.on_speech_started_hooks: list[Callable] = []
        self.store.start_call(call_id)

    # ---- lifecycle -------------------------------------------------------------------------------

    async def join(self, role: str, ws: Sendable, caller_number: str | None = None) -> None:
        if role not in ROLES:
            raise ValueError(f"unknown role {role}")
        if role in self.parties:
            await self.leave(role)
        self.parties[role] = Peer(ws)
        self.clocks[role] = AudioClock(self.sample_rate)
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
        for role in list(self.stt):
            stt = self.stt.pop(role)
            await stt.close()
        self.store.update_call(self.call_id, ended_at=time.time())
        self.log_event("call_end", {})
        await self.broadcast({"type": "call_ended"})

    # ---- audio -----------------------------------------------------------------------------------

    async def on_audio(self, role: str, pcm: bytes) -> None:
        """Audio from one party: tap to its STT channel, relay to the other party (unless muted)."""
        if role not in self.parties:
            return
        self.clocks[role].add(len(pcm), time.monotonic())
        stt = self.stt.get(role)
        if stt:
            await stt.send_audio(pcm)
        other = "receiver" if role == "caller" else "caller"
        if role == "receiver" and self.takeover:
            return  # takeover: the scammer must not hear the receiver
        await self.send_audio(other, SOURCE_PEER, pcm)

    async def send_audio(self, role: str, source: int, pcm: bytes) -> None:
        peer = self.parties.get(role)
        if peer:
            await peer.send_bytes(bytes([source]) + pcm)

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
        targets = list(self.parties.values()) + list(self.listeners)
        results = await asyncio.gather(*(p.send_text(text) for p in targets))
        for peer, ok in zip(targets, results):
            if not ok and peer in self.listeners:
                self.listeners.discard(peer)

    def log_event(self, type_: str, payload: dict, at: float | None = None) -> None:
        self.store.add_event(self.call_id, type_, at if at is not None else time.monotonic(), payload)

    async def _on_stt_event(self, channel: str, ev: dict) -> None:
        now = time.monotonic()
        kind = ev["type"]
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
        elif kind == "error":
            self.log_event("stt_error", {"channel": channel, "error": ev["error"]}, now)
            await self.broadcast({"type": "stt_status", "channel": channel, "ok": False, "error": ev["error"]})


class RoomRegistry:
    def __init__(self, stt_factory: SttFactory, store: Store, sample_rate: int):
        self.rooms: dict[str, CallRoom] = {}
        self.stt_factory = stt_factory
        self.store = store
        self.sample_rate = sample_rate

    def get(self, call_id: str) -> CallRoom:
        room = self.rooms.get(call_id)
        if room is None or room.ended:
            room = CallRoom(call_id, self.stt_factory, self.store, self.sample_rate)
            self.rooms[call_id] = room
        return room
