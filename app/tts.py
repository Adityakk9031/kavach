"""Async client for one AssemblyAI TTS-1 WebSocket session (docs/API_NOTES.md §2).

One session is meant to live for a long time and speak many requests (a warm session skips the handshake and
the voice load). Frames are PascalCase JSON. `Cancel` is barge-in: Audio frames that arrive between our Cancel
and the server's `Cancelled` belong to the cancelled request and are dropped here, never delivered.
"""

import asyncio
import base64
import json
import logging
import time
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from urllib.parse import urlencode

import websockets

from app.config import Settings

log = logging.getLogger("kavach.tts")

OnAudio = Callable[[bytes], Awaitable[None]]


class TtsError(RuntimeError):
    def __init__(self, message: str, code: int | None = None, error_type: str | None = None):
        super().__init__(message)
        self.code, self.error_type = code, error_type


@dataclass
class Request:
    text: str
    on_audio: OnAudio
    sent_at: float = field(default_factory=time.monotonic)
    first_audio_at: float | None = None
    done_at: float | None = None
    flush_id: int | None = None
    audio_ms: float = 0.0
    cancelled: bool = False
    done: asyncio.Event = field(default_factory=asyncio.Event)

    @property
    def ttfa_ms(self) -> float | None:
        return None if self.first_audio_at is None else (self.first_audio_at - self.sent_at) * 1000


class TtsSession:
    def __init__(self, settings: Settings, voice_id: str, label: str = "tts"):
        self.settings, self.voice_id, self.label = settings, voice_id, label
        self.ws = None
        self.begin: dict = {}
        self._reader: asyncio.Task | None = None
        self._keepalive: asyncio.Task | None = None
        self._pending: deque[Request] = deque()  # sent, audio not finished, in flush order
        self._cancels_outstanding = 0  # Cancels sent but not yet answered by Cancelled
        self._send_lock = asyncio.Lock()
        self.closed = asyncio.Event()
        self.close_reason: str | None = None

    @property
    def connected(self) -> bool:
        return self.ws is not None and not self.closed.is_set()

    @property
    def resolved_voice_id(self) -> str | None:
        return (self.begin.get("configuration", {}).get("resolved_voice") or {}).get("voice_id")

    def _url(self) -> str:
        s = self.settings
        q = {"voice_id": self.voice_id, "language": s.language, "sample_rate": s.sample_rate,
             "encoding": "pcm_s16le", "word_boundaries": "false"}
        return f"{s.tts_ws_url}?{urlencode(q)}"

    async def start(self) -> None:
        t0 = time.monotonic()
        self.ws = await websockets.connect(
            self._url(), additional_headers={"Authorization": self.settings.assemblyai_api_key}, max_size=None)
        first = json.loads(await asyncio.wait_for(self.ws.recv(), 15))
        if first.get("type") == "Error":
            await self.ws.close()
            raise TtsError(first.get("error", "TTS error"), first.get("error_code"), first.get("error_type"))
        if first.get("type") != "Begin":
            raise TtsError(f"expected Begin, got {first.get('type')}")
        self.begin = first
        self.closed.clear()
        log.info("%s session ready in %.0f ms voice=%s", self.label, (time.monotonic() - t0) * 1000,
                 self.resolved_voice_id)
        self._reader = asyncio.create_task(self._read(), name=f"tts-read-{self.label}")
        self._keepalive = asyncio.create_task(self._keep_alive(), name=f"tts-ka-{self.label}")

    async def _keep_alive(self) -> None:
        while not self.closed.is_set():
            await asyncio.sleep(60)  # idle timeout is 120 s; KeepAlive is a control frame, keep it rare
            if self.connected and not self._pending:
                await self._send({"type": "KeepAlive"})

    async def _send(self, frame: dict) -> None:
        async with self._send_lock:
            await self.ws.send(json.dumps(frame))

    async def _read(self) -> None:
        try:
            async for raw in self.ws:
                msg = json.loads(raw)
                kind = msg.get("type")
                if kind == "Audio":
                    await self._on_audio(msg)
                elif kind == "FlushDone":
                    self._on_flush_done(msg)
                elif kind == "Cancelled":
                    self._cancels_outstanding = max(0, self._cancels_outstanding - 1)
                elif kind == "Error":
                    self.close_reason = f"{msg.get('error_code')} {msg.get('error_type')}: {msg.get('error')}"
                    log.error("%s TTS error: %s", self.label, self.close_reason)
                    break
        except websockets.ConnectionClosed as e:
            self.close_reason = self.close_reason or f"closed {e.rcvd.code if e.rcvd else None}"
        except Exception as e:
            self.close_reason = f"{type(e).__name__}: {e}"
            log.exception("%s reader failed", self.label)
        finally:
            self.closed.set()
            for req in self._pending:  # nothing will finish these
                req.done.set()
            self._pending.clear()

    def _current(self, flush_id: int) -> Request | None:
        for req in self._pending:
            if req.flush_id == flush_id:
                return req
        for req in self._pending:  # first Audio of a request: bind the oldest request without an id
            if req.flush_id is None and not req.cancelled:
                req.flush_id = flush_id
                return req
        return None

    async def _on_audio(self, msg: dict) -> None:
        if self._cancels_outstanding > 0:
            return  # tail of a cancelled request: must not be played
        req = self._current(msg["flush_id"])
        if req is None or req.cancelled:
            return
        pcm = base64.b64decode(msg["audio"])
        if req.first_audio_at is None:
            req.first_audio_at = time.monotonic()
        req.audio_ms += len(pcm) / 2 / self.settings.sample_rate * 1000
        await req.on_audio(pcm)

    def _on_flush_done(self, msg: dict) -> None:
        req = self._current(msg["flush_id"])
        if req is not None:
            req.done_at = time.monotonic()
            req.done.set()
            try:
                self._pending.remove(req)
            except ValueError:
                pass

    async def speak(self, text: str, on_audio: OnAudio) -> Request:
        """Queue one request. Returns immediately; audio is delivered to on_audio as it streams.
        Await `request.done.wait()` for completion."""
        if not self.connected:
            raise TtsError(f"{self.label} session not connected ({self.close_reason})")
        req = Request(text=text, on_audio=on_audio)
        self._pending.append(req)
        req.sent_at = time.monotonic()
        await self._send({"type": "Generate", "text": text})
        await self._send({"type": "Flush"})
        return req

    async def cancel(self) -> float | None:
        """Barge-in. Returns monotonic time the Cancel frame was sent, or None if nothing was in flight."""
        if not self._pending or not self.connected:
            return None
        for req in self._pending:
            req.cancelled = True
        self._cancels_outstanding += 1
        at = time.monotonic()
        await self._send({"type": "Cancel"})
        # Safety net: the server answers every Cancel with Cancelled, but if one ever goes missing, audio must not
        # stay muted for the rest of the session.
        asyncio.get_running_loop().call_later(3.0, self._expire_cancel)
        for req in list(self._pending):
            req.done_at = at
            req.done.set()
        self._pending.clear()  # cancelled requests get no FlushDone
        return at

    def _expire_cancel(self) -> None:
        if self._cancels_outstanding > 0:
            log.warning("%s: no Cancelled received within 3 s; resuming audio", self.label)
            self._cancels_outstanding = 0

    async def close(self) -> None:
        for task in (self._keepalive, self._reader):
            if task:
                task.cancel()
        if self.ws:
            try:
                await self._send({"type": "Terminate"})
            except Exception:
                pass
            await self.ws.close()
        self.closed.set()


class TtsPool:
    """One long-lived session per voice, shared by calls. Reconnects when a session has died."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.sessions: dict[str, TtsSession] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    async def get(self, voice_id: str, label: str = "tts") -> TtsSession:
        lock = self._locks.setdefault(voice_id, asyncio.Lock())
        async with lock:
            session = self.sessions.get(voice_id)
            if session is None or not session.connected:
                if session:
                    log.warning("%s session for %s ended (%s); reconnecting", label, voice_id, session.close_reason)
                session = TtsSession(self.settings, voice_id, label)
                await session.start()
                self.sessions[voice_id] = session
            return session

    async def close(self) -> None:
        await asyncio.gather(*(s.close() for s in self.sessions.values()), return_exceptions=True)
