"""FastAPI entry point. Run with: uv run uvicorn app.main:app --reload"""

import asyncio
import json
import logging
import time
from contextlib import asynccontextmanager
from importlib.metadata import version
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.call_room import ROLES, Peer, RoomRegistry
from app.config import get_settings
from app.detector import Detector
from app.llm import LLM
from app.evidence import EvidenceCollector
from app.persona import Persona
from app.pipeline import CallPipeline
from app.store import Store
from app.stt import NullStt, SttSession
from app.tts import TtsPool
from app.warner import Warner

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

settings = get_settings()
store = Store(settings.db_path)


def stt_factory(channel: str, on_event):
    if not settings.assemblyai_api_key:
        return NullStt(channel, on_event)
    return SttSession(channel, settings, on_event)


llm = LLM(settings)
detector = Detector(settings, llm)


tts_pool = TtsPool(settings)
warner = Warner(settings, tts_pool)
persona = Persona(settings, llm, tts_pool)


def attach_pipeline(room) -> None:
    if settings.assemblyai_api_key:
        room.pipeline = CallPipeline(room, detector)
        if settings.kavach_warning_voice_id:
            warner.attach(room, room.pipeline)
        persona.attach(room)
        room.evidence = EvidenceCollector(room, llm, settings.persona_model, room.pipeline)


rooms = RoomRegistry(stt_factory, store, settings.sample_rate, on_new_room=attach_pipeline)

async def loop_lag_monitor(threshold_ms: int = 300) -> None:
    """Log any time the event loop is blocked longer than the threshold (a stalled loop drops STT sockets)."""
    log = logging.getLogger("kavach.lag")
    while True:
        t0 = time.monotonic()
        await asyncio.sleep(0.1)
        lag = (time.monotonic() - t0 - 0.1) * 1000
        if lag > threshold_ms:
            log.warning("event loop blocked for %.0f ms", lag)
            for room in list(rooms.rooms.values()):
                if not room.ended:
                    room.log_event("loop_lag", {"ms": round(lag)})


@asynccontextmanager
async def lifespan(_app):
    task = asyncio.create_task(loop_lag_monitor())
    if settings.assemblyai_api_key and settings.kavach_warning_voice_id:
        # Open the cloned-voice session now so the first warning skips handshake + voice load.
        async def warm():
            try:
                await warner.session()
            except Exception:
                logging.getLogger("kavach").exception("could not pre-warm warning voice")
        asyncio.create_task(warm())
    yield
    task.cancel()
    await tts_pool.close()
    await llm.aclose()


app = FastAPI(title="Kavach", version="0.1.0", lifespan=lifespan)
WEB = Path(__file__).resolve().parent.parent / "web"
app.mount("/web", StaticFiles(directory=WEB, html=True), name="web")
(Path(__file__).resolve().parent.parent / "eval" / "audio").mkdir(parents=True, exist_ok=True)
app.mount("/eval-audio", StaticFiles(directory=Path(__file__).resolve().parent.parent / "eval" / "audio"), name="eval-audio")


@app.get("/")
def index() -> RedirectResponse:
    return RedirectResponse("/web/index.html")


@app.get("/health")
def health() -> dict:
    """Liveness plus config readiness. Reports which secrets are missing, never their values."""
    s = get_settings()
    missing = s.missing_secrets()
    return {
        "status": "ok",
        "ready": not missing,
        "missing_secrets": missing,
        "language": s.language,
        "stt_model": s.stt_model,
        "detector_model": s.detector_model,
        "assemblyai_sdk": version("assemblyai"),
    }


@app.get("/api/config")
def public_config() -> dict:
    """Non-secret settings, recorded with every eval run so results can be reproduced."""
    s = get_settings()
    return {"risk_threshold": s.risk_threshold, "risk_rise": s.risk_rise, "risk_decay_per_turn": s.risk_decay_per_turn,
            "detector_model": s.detector_model, "stt_model": s.stt_model, "stt_mode": s.stt_mode,
            "language": s.language, "warning_voice_cloned": bool(s.kavach_warning_voice_id)}


EVAL_RESULTS = Path(__file__).resolve().parent.parent / "eval" / "results"
EVAL_AUDIO = Path(__file__).resolve().parent.parent / "eval" / "audio"
EVAL_SCRIPTS = Path(__file__).resolve().parent.parent / "eval" / "scripts"


@app.get("/api/eval/latest")
def eval_latest(split: str = "test"):
    path = EVAL_RESULTS / f"latest-{split}.json"
    if not path.exists():
        return {"error": f"no finished {split} run yet"}
    return json.loads(path.read_text())


@app.get("/api/eval/script/{script_id}")
def eval_script(script_id: str):
    path = EVAL_SCRIPTS / f"{Path(script_id).name}.json"
    return json.loads(path.read_text()) if path.exists() else {"error": "not found"}


@app.get("/api/calls/{call_id}/events")
def call_events(call_id: str) -> list[dict]:
    return store.events(call_id)


@app.get("/api/calls/{call_id}/turns")
def call_turns(call_id: str) -> list[dict]:
    return store.turns(call_id)


@app.websocket("/ws/call/{call_id}/{role}")
async def call_socket(ws: WebSocket, call_id: str, role: str, caller_number: str | None = None):
    """One tab of the call. Binary in = PCM from the mic; text in = JSON control messages."""
    if role not in ROLES:
        await ws.close(code=1008, reason="role must be caller or receiver")
        return
    await ws.accept()
    room = rooms.get(call_id)
    await room.join(role, ws, caller_number=caller_number)
    try:
        while True:
            msg = await ws.receive()
            if msg["type"] == "websocket.disconnect":
                break
            if msg.get("bytes") is not None:
                await room.on_audio(role, msg["bytes"])
            elif msg.get("text") is not None:
                await handle_control(room, role, json.loads(msg["text"]))
    except WebSocketDisconnect:
        pass
    finally:
        if room.parties.get(role) and room.parties[role].ws is ws:
            await room.leave(role)


async def handle_control(room, role: str, msg: dict) -> None:
    kind = msg.get("type")
    if kind in room.control_handlers:
        await room.control_handlers[kind](room, role, msg)
    elif kind == "end_call":
        await room.end()
    elif kind == "client_event":
        # Browser-side timings (e.g. playback actually started) for latency logging.
        room.log_event(f"client_{msg.get('name', 'event')}", {"role": role, **msg.get("payload", {})})


@app.websocket("/ws/events/{call_id}")
async def events_socket(ws: WebSocket, call_id: str):
    """Read-only event stream for the dashboard."""
    await ws.accept()
    room = rooms.get(call_id)
    peer = Peer(ws)
    room.listeners.add(peer)
    await peer.send_text(json.dumps({"type": "presence", "parties": sorted(room.parties), "call_id": call_id}))
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        room.listeners.discard(peer)
