"""FastAPI entry point. Run with: uv run uvicorn app.main:app --reload"""

import asyncio
import json
import logging
import secrets
import time
from contextlib import asynccontextmanager
from importlib.metadata import version
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, RedirectResponse
from pydantic import BaseModel
from fastapi.staticfiles import StaticFiles

from app.call_room import ROLES, Peer, RoomRegistry
from app.config import get_settings
from app.detector import Detector
from app.llm import LLM
from app import report as report_mod
from app.alerts import Alerter, CallAlerts
from app.evidence import EvidenceCollector
from app.family import FamilyDesk
from app.finalize import handle_answer_callback, make_finalize
from app.persona import Persona
from app.pipeline import CallPipeline
from app.store import Store
from app import voices as voices_mod
from app.stt import NullStt, SttSession
from app.tts import TtsPool
from app.warner import Warner

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
# httpx logs every request URL at INFO, and the Telegram bot token is part of its URL: keep those lines out of logs.
for _noisy in ("httpx", "httpcore"):
    logging.getLogger(_noisy).setLevel(logging.WARNING)

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
alerter = Alerter(settings)


def attach_pipeline(room) -> None:
    if settings.assemblyai_api_key:
        room.pipeline = CallPipeline(room, detector)
        if settings.kavach_warning_voice_id:
            warner.attach(room, room.pipeline)
        persona.attach(room)
        room.evidence = EvidenceCollector(room, llm, settings.persona_model, room.pipeline, (settings.decoy.name,))
        room.alerts = CallAlerts(alerter, room, room.pipeline, room.persona, settings.max_alerts_per_call)

        room.finalize_hooks.append(make_finalize(room, store, settings))


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


desk = FamilyDesk(alerter, store, rooms, settings)


async def telegram_update(update: dict) -> None:
    """Whatever the family sends the bot: a button press (end the call / answer a question) or a voice note."""
    data = (update.get("callback_query") or {}).get("data", "")
    if data.startswith("c:"):
        await desk.handle_control(update)
    elif data.startswith("a:"):
        await handle_answer_callback(update, alerter, store, settings)
    elif "message" in update:
        await desk.handle_message(update)


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
    poller = None
    if alerter.enabled:  # listen for the family's button presses (money / OTP answers)
        poller = asyncio.create_task(alerter.poll(telegram_update))
    yield
    task.cancel()
    if poller:
        poller.cancel()
    await tts_pool.close()
    await alerter.aclose()
    await llm.aclose()


app = FastAPI(title="Kavach", version="0.1.0", lifespan=lifespan)


def key_ok(supplied: str | None) -> bool:
    """True if no access key is configured, or the supplied one matches (constant-time compare)."""
    required = settings.kavach_access_key
    return not required or secrets.compare_digest((supplied or "").encode(), required.encode())


@app.middleware("http")
async def require_access_key(request, call_next):
    """The pages themselves are public (they hold no data); everything that returns or changes data needs the key."""
    path = request.url.path
    if (path.startswith("/api/") or path.startswith("/eval-audio/")) and not key_ok(
            request.query_params.get("key") or request.headers.get("x-kavach-key")):
        return JSONResponse({"error": "access key required"}, status_code=401)
    return await call_next(request)
# The Kavach web app (a Mac browser) runs on another origin. Access is by the key header, not cookies, so any origin may
# ask; without the key the answer is still 401. Added last, so it is outermost and answers the browser's preflight first.
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
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


@app.get("/api/voices")
def voice_samples() -> dict:
    """Which people have a consented voice sample on the server, and the consent wording the app shows."""
    s = get_settings()
    return {"samples": voices_mod.list_samples(s.voices_dir), "consent_text": voices_mod.CONSENT_TEXT,
            "min_seconds": voices_mod.MIN_SECONDS, "max_seconds": voices_mod.MAX_SECONDS,
            "persona_voice_id": s.persona_voice_id}


@app.post("/api/voices/{person}")
async def upload_voice_sample(person: str, request: Request, name: str = "") -> dict:
    """Body: raw 16 kHz mono signed 16-bit PCM. Header `x-kavach-consent: yes` records the speaker's consent."""
    s = get_settings()
    consent = request.headers.get("x-kavach-consent", "").lower() == "yes"
    body = await request.body()
    try:
        return voices_mod.save_sample(s.voices_dir, person, name, body, s.sample_rate, consent)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/voices/{person}.wav")
def download_voice_sample(person: str) -> FileResponse:
    path = Path(get_settings().voices_dir) / f"{person}.wav"
    if person not in voices_mod.PEOPLE or not path.exists():
        raise HTTPException(status_code=404, detail="no sample")
    return FileResponse(path, media_type="audio/wav", filename=f"kavach-{person}-voice-sample.wav")


@app.delete("/api/voices/{person}")
def delete_voice_sample(person: str) -> dict:
    return {"deleted": voices_mod.delete_sample(get_settings().voices_dir, person)}


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


class ReportAnswers(BaseModel):
    money_shared: bool | None = None
    otp_shared: bool | None = None
    notes: str = ""


@app.post("/api/calls/{call_id}/report")
def update_report(call_id: str, answers: ReportAnswers):
    """The user answers the two questions only they can answer; the draft is rebuilt with their answers."""
    if not store.query("SELECT 1 FROM calls WHERE id=?", (call_id,)):
        raise HTTPException(404, "unknown call")
    store.update_call(call_id, money_shared=None if answers.money_shared is None else int(answers.money_shared),
                      otp_shared=None if answers.otp_shared is None else int(answers.otp_shared))
    r, md, pdf = report_mod.generate(store, call_id, settings.reports_dir, notes=answers.notes[:1000])
    return {"md": f"/api/calls/{call_id}/report.md", "pdf": f"/api/calls/{call_id}/report.pdf", "missing": r.missing}


@app.get("/api/calls/{call_id}/report.md")
def report_md(call_id: str):
    row = store.query("SELECT report_md_path FROM calls WHERE id=?", (call_id,))
    if not row or not row[0]["report_md_path"]:
        raise HTTPException(404, "no report for this call")
    return PlainTextResponse(Path(row[0]["report_md_path"]).read_text(), media_type="text/markdown; charset=utf-8")


@app.get("/api/calls/{call_id}/report.pdf")
def report_pdf(call_id: str):
    row = store.query("SELECT report_pdf_path FROM calls WHERE id=?", (call_id,))
    if not row or not row[0]["report_pdf_path"]:
        raise HTTPException(404, "no report for this call")
    return FileResponse(row[0]["report_pdf_path"], media_type="application/pdf", filename=f"kavach-complaint-{call_id}.pdf")


@app.get("/api/calls/{call_id}/evidence")
def call_evidence(call_id: str) -> list[dict]:
    return store.query("SELECT type, value, normalized, quote, ts_ms FROM evidence WHERE call_id=? AND valid=1 ORDER BY id", (call_id,))


@app.get("/api/calls/{call_id}/events")
def call_events(call_id: str) -> list[dict]:
    return store.events(call_id)


@app.get("/api/calls/{call_id}/turns")
def call_turns(call_id: str) -> list[dict]:
    return store.turns(call_id)


@app.get("/api/calls/live")
def live_call() -> dict:
    """The call the phone's background listener is streaming now, so the app can open onto it."""
    running = [r for r in rooms.rooms.values() if not r.ended and r.call_id.startswith("apk-")]
    room = max(running, key=lambda r: r.started_wall, default=None)
    return {"call_id": room.call_id if room else None}


@app.get("/api/calls/takeover-check")
def takeover_check() -> dict:
    """What the latest background-listener call did: Kavach's lines and voice sent, and what the phone reported back."""
    latest = store.query("SELECT id FROM calls WHERE id LIKE 'apk-%' ORDER BY rowid DESC LIMIT 1")
    if not latest:
        return {"call_id": None}
    call_id = latest[0]["id"]
    events = store.events(call_id)
    wanted = {"takeover": [], "persona_sent": [], "persona_guard": [], "persona_error": [], "client_voice_route": [],
              "client_warning_mute": [], "warning_start": []}
    for e in events:
        if e["type"] in wanted:
            wanted[e["type"]].append(e["payload"])
    room = rooms.rooms.get(call_id)
    return {"call_id": call_id, "running": room is not None and not room.ended, "seconds_sent_to_caller":
            round(sum(p.get("seconds", 0) for p in wanted["persona_sent"]), 1), **wanted}


@app.post("/api/calls/{call_id}/control")
async def call_control(call_id: str, body: dict):
    """Hand over, take back or end from the app, which watches the call instead of being a party on it."""
    room = rooms.rooms.get(call_id)
    if room is None or room.ended:
        raise HTTPException(404, "No such running call")
    if body.get("type") not in ("takeover", "takeback", "end_call"):
        raise HTTPException(400, "Unknown command")
    await handle_control(room, "receiver", {"type": body["type"]})
    return {"ok": True}


@app.websocket("/ws/call/{call_id}/{role}")
async def call_socket(ws: WebSocket, call_id: str, role: str, caller_number: str | None = None, mode: str | None = None):
    """One tab of the call. Binary in = PCM from the mic; text in = JSON control messages."""
    if not key_ok(ws.query_params.get("key")):
        await ws.close(code=4403)  # refused before the handshake completes
        return
    if role not in ROLES:
        await ws.close(code=1008, reason="role must be caller or receiver")
        return
    await ws.accept()
    done = store.query("SELECT 1 FROM calls WHERE id=? AND ended_at IS NOT NULL", (call_id,))
    if done:  # reusing an id would mix two calls in one report
        await ws.close(code=4409, reason="This call has ended. Use a new call id.")
        return
    room = rooms.get(call_id)
    await room.join(role, ws, caller_number=caller_number, mode=mode)
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
            # A tab that closes or crashes without "Hang up" still ends the call: the report and the family's
            # call-end message must not depend on the user pressing a button.
            if role == "caller" or not room.parties:
                asyncio.create_task(room.end())


async def handle_control(room, role: str, msg: dict) -> None:
    kind = msg.get("type")
    if kind in room.control_handlers:
        await room.control_handlers[kind](room, role, msg)
    elif kind == "end_call":
        await room.end()
    elif kind == "client_event":
        # Browser-side timings (e.g. playback actually started) for latency logging.
        room.log_event(f"client_{msg.get('name', 'event')}", {"role": role, **msg.get("payload", {})})
        if msg.get("name") in ("voice_route", "warning_mute"):
            logging.getLogger("kavach.phone").info("PHONE %s call=%s %s", msg["name"], room.call_id, msg.get("payload"))


@app.websocket("/ws/events/{call_id}")
async def events_socket(ws: WebSocket, call_id: str):
    """Read-only event stream for the dashboard."""
    if not key_ok(ws.query_params.get("key")):
        await ws.close(code=4403)
        return
    await ws.accept()
    peer = Peer(ws)
    room = rooms.rooms.get(call_id)  # a viewer never creates a call (no workers, no DB row)
    if room is not None and not room.ended:
        room.listeners.add(peer)
        await peer.send_text(json.dumps({"type": "presence", "parties": sorted(room.parties), "call_id": call_id}))
    else:
        rooms.waiting.setdefault(call_id, set()).add(peer)  # attached when the call starts
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        if room is not None:
            room.listeners.discard(peer)
        rooms.waiting.get(call_id, set()).discard(peer)
