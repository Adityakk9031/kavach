"""One AssemblyAI streaming STT (v3) session per call channel.

Raw WebSocket protocol (docs/API_NOTES.md §3): binary PCM frames in, JSON `Begin`, `SpeechStarted`,
`Turn`, `Termination`, `Error` out. Each `Turn` re-transcribes the whole turn, so consumers replace
rather than append. Always ends with `Terminate` because sessions are billed by wall-clock time.
"""

import asyncio
import json
import logging
import time
from collections.abc import Awaitable, Callable
from urllib.parse import urlencode

import websockets

from app.config import Settings

log = logging.getLogger("kavach.stt")

# Callback receives normalized events:
#   {"type": "begin", "model": ..., "session_id": ...}
#   {"type": "speech_started", "audio_ms": int}
#   {"type": "partial" | "final", "text": str, "turn_order": int, "audio_start_ms": int|None, "audio_end_ms": int|None}
#   {"type": "error", "error": str}
#   {"type": "closed"}
OnEvent = Callable[[dict], Awaitable[None]]


def build_url(settings: Settings, language_codes: list[str] | None = None) -> str:
    params = {
        "speech_model": settings.stt_model,
        "sample_rate": settings.sample_rate,
        "encoding": "pcm_s16le",
        "format_turns": "true",
    }
    if settings.stt_model.startswith("universal-3"):
        params["language_codes"] = json.dumps(language_codes or settings.stt_language_codes)
        params["mode"] = settings.stt_mode
    return f"{settings.stt_ws_url}?{urlencode(params)}"


def normalize(msg: dict) -> dict | None:
    """Map a raw server message to our event shape. Returns None for messages we ignore."""
    kind = msg.get("type")
    if kind == "Begin":
        return {"type": "begin", "model": msg.get("configuration", {}).get("model"), "session_id": msg.get("id")}
    if kind == "SpeechStarted":
        return {"type": "speech_started", "audio_ms": msg.get("timestamp")}
    if kind == "Turn":
        words = msg.get("words") or []
        return {
            "type": "final" if msg.get("end_of_turn") else "partial",
            "text": msg.get("transcript", ""),
            "turn_order": msg.get("turn_order"),
            "audio_start_ms": words[0]["start"] if words else None,
            "audio_end_ms": words[-1]["end"] if words else None,
        }
    if kind == "Error":
        return {"type": "error", "error": msg.get("error") or str(msg)}
    return None  # Termination, Heartbeat, unknown types


class SttSession:
    def __init__(self, channel: str, settings: Settings, on_event: OnEvent, language_codes: list[str] | None = None):
        self.language_codes = language_codes
        self.channel = channel
        self.settings = settings
        self.on_event = on_event
        self._ws = None
        self._reader: asyncio.Task | None = None
        self._terminated = asyncio.Event()
        self._close_info: dict = {"code": None, "reason": "", "clean": True}
        self.model: str | None = None

    async def start(self) -> None:
        self._ws = await websockets.connect(
            build_url(self.settings, self.language_codes),
            additional_headers={"Authorization": self.settings.assemblyai_api_key},
            max_size=None,
        )
        first = json.loads(await asyncio.wait_for(self._ws.recv(), 10))
        event = normalize(first)
        if not event or event["type"] != "begin":
            await self._ws.close()
            raise RuntimeError(f"STT {self.channel}: expected Begin, got {first}")
        self.model = event["model"]
        if self.model != self.settings.stt_model:
            log.warning("STT %s asked for %s but Begin says %s", self.channel, self.settings.stt_model, self.model)
        await self.on_event(event)
        self._reader = asyncio.create_task(self._read(), name=f"stt-{self.channel}")

    async def _read(self) -> None:
        try:
            async for raw in self._ws:
                msg = json.loads(raw)
                if msg.get("type") == "Termination":
                    self._terminated.set()
                    continue
                event = normalize(msg)
                if event:
                    await self.on_event(event)
        except websockets.ConnectionClosed as e:
            code = e.rcvd.code if e.rcvd else None
            self._close_info = {"code": code, "reason": e.rcvd.reason if e.rcvd else "",
                                "clean": self._terminated.is_set() or code == 1000}
            if not self._close_info["clean"]:
                log.warning("STT %s closed unexpectedly: %s", self.channel, self._close_info)
        except Exception as e:  # never let a reader crash silently
            log.exception("STT %s reader failed", self.channel)
            await self.on_event({"type": "error", "error": f"{type(e).__name__}: {e}"})
        finally:
            clean = self._terminated.is_set() and self._close_info["clean"]
            self._terminated.set()
            await self.on_event({"type": "closed", **self._close_info, "clean": clean})

    @property
    def accepting(self) -> bool:
        """True once audio is being forwarded to AssemblyAI (the session's own timeline starts at that first byte)."""
        return self._ws is not None and not self._terminated.is_set()

    async def send_audio(self, pcm: bytes) -> None:
        if self._ws is None or self._terminated.is_set():
            return
        try:
            await self._ws.send(pcm)
        except websockets.ConnectionClosed:
            pass

    async def close(self, timeout: float = 5.0) -> None:
        if self._ws is None:
            return
        if not self._terminated.is_set():
            try:
                await self._ws.send(json.dumps({"type": "Terminate"}))
                await asyncio.wait_for(self._terminated.wait(), timeout)
            except (websockets.ConnectionClosed, asyncio.TimeoutError):
                pass
        await self._ws.close()
        if self._reader:
            await asyncio.gather(self._reader, return_exceptions=True)


class NullStt:
    """Used when no API key is configured, so the relay and UI still work."""

    model = None

    def __init__(self, channel: str, on_event: OnEvent):
        self.channel = channel
        self.on_event = on_event

    async def start(self) -> None:
        await self.on_event({"type": "error", "error": "STT disabled: ASSEMBLYAI_API_KEY not set"})

    async def send_audio(self, pcm: bytes) -> None:
        pass

    async def close(self) -> None:
        pass


def now() -> float:
    return time.monotonic()
