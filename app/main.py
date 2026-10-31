"""FastAPI entry point. Run with: uv run uvicorn app.main:app --reload"""

import json
import logging
from importlib.metadata import version
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.call_room import ROLES, Peer, RoomRegistry
from app.config import get_settings
from app.store import Store
from app.stt import NullStt, SttSession

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

settings = get_settings()
store = Store(settings.db_path)


def stt_factory(channel: str, on_event):
    if not settings.assemblyai_api_key:
        return NullStt(channel, on_event)
    return SttSession(channel, settings, on_event)


rooms = RoomRegistry(stt_factory, store, settings.sample_rate)

app = FastAPI(title="Kavach", version="0.1.0")
WEB = Path(__file__).resolve().parent.parent / "web"
app.mount("/web", StaticFiles(directory=WEB, html=True), name="web")


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
    if kind == "end_call":
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
