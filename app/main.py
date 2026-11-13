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

from app import lang
from app.accounts import DEFAULT_FAMILY, AccountError, Accounts, Identity
from app.call_room import ROLES, Peer, RoomRegistry
from app.config import get_settings
from app.detector import Detector
from app.llm import LLM
from app import report as report_mod
from app.alerts import Alerter, CallAlerts
from app.evidence import EvidenceCollector
from app.family import DESK, FamilyDesk
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
store = Store(settings.db_path, settings.database_url)
accounts = Accounts(store, settings)


def stt_factory(channel: str, on_event, family=None):
    if not settings.assemblyai_api_key:
        return NullStt(channel, on_event)
    return SttSession(channel, settings, on_event, [family.pack.stt] if family is not None else None)


llm = LLM(settings)
detector = Detector(settings, llm)


tts_pool = TtsPool(settings)
warner = Warner(settings, tts_pool)
persona = Persona(settings, llm, tts_pool)
alerter = Alerter(settings)


def attach_pipeline(room) -> None:
    if settings.assemblyai_api_key:
        room.pipeline = CallPipeline(room, detector)
        warner.attach(room, room.pipeline)  # with no cloned voice yet it warns in a library voice, and says so
        persona.attach(room)
        decoys = tuple({settings.decoy.name} | {p.decoy_name for p in lang.PACKS.values()})
        room.evidence = EvidenceCollector(room, llm, settings.persona_model, room.pipeline, decoys)
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


desk = FamilyDesk(alerter, store, rooms, settings, accounts)


async def telegram_update(update: dict) -> None:
    """Whatever the family sends the bot: a button press (end the call / answer a question) or a voice note."""
    data = (update.get("callback_query") or {}).get("data", "")
    if data.startswith("c:"):
        await desk.handle_control(update)
    elif data.startswith("a:"):
        await handle_answer_callback(update, alerter, store, settings, accounts)
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


PUBLIC_API = {"/api/account/signup", "/api/account/login", "/api/account/session", "/api/auth-config", "/api/pair", "/api/languages"}


def ident_of(request: Request) -> Identity:
    return request.state.identity


def family_of(ident: Identity):
    """The family record for a request. The original household (the shared access key) keeps its .env settings: None."""
    return None if ident.family_id == DEFAULT_FAMILY else accounts.family(ident.family_id)


def call_owner(call_id: str) -> str | None:
    rows = store.query("SELECT family_id FROM calls WHERE id=?", (call_id,))
    return None if not rows else (rows[0]["family_id"] or DEFAULT_FAMILY)


def own_call(request: Request, call_id: str) -> None:
    """404 unless the call belongs to the caller's family (the admin key sees all). Never confirms another family's call."""
    ident = ident_of(request)
    if ident.role != "admin" and call_owner(call_id) != ident.family_id:
        raise HTTPException(404, "unknown call")


def need_son(request: Request) -> Identity:
    ident = ident_of(request)
    if ident.role not in ("son", "admin"):
        raise HTTPException(403, "Only the family member who set this up can do that.")
    return ident


def key_ok(supplied: str | None) -> bool:
    """True if no access key is configured, or the supplied one matches (constant-time compare)."""
    required = settings.kavach_access_key
    return not required or secrets.compare_digest((supplied or "").encode(), required.encode())


@app.middleware("http")
async def require_access_key(request, call_next):
    """The pages themselves are public (they hold no data); everything that returns or changes data needs the key."""
    path = request.url.path
    if (path.startswith("/api/") or path.startswith("/eval-audio/")) and path not in PUBLIC_API:
        ident = accounts.identify(request.query_params.get("key") or request.headers.get("x-kavach-key"))
        if ident is None:
            return JSONResponse({"error": "access key required"}, status_code=401)
        request.state.identity = ident
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


class SignupBody(BaseModel):
    email: str
    password: str
    language: str = "en"
    timezone: str = "UTC"
    parent_address: str = "Mom"
    son_name: str = ""


class LoginBody(BaseModel):
    email: str
    password: str


class PairBody(BaseModel):
    code: str


class FamilyBody(BaseModel):
    language: str | None = None
    timezone: str | None = None
    parent_address: str | None = None
    son_name: str | None = None
    report_hint: str | None = None


def family_json(fam) -> dict:
    return {"id": fam.id, "language": fam.language, "timezone": fam.timezone, "parent_address": fam.parent_address,
            "son_name": fam.son_name, "report_hint": fam.report_hint, "telegram_linked": bool(fam.chat_ids)}


@app.get("/api/languages")
def languages() -> dict:
    """The languages a family can choose now. Hindi is not offered yet: AssemblyAI speech-to-text covers it, text-to-speech
    does not, and a family warning has to be spoken."""
    return {"languages": lang.available(), "coming": ["hi"]}


def supabase_on() -> bool:
    return bool(settings.supabase_url and settings.supabase_anon_key)


@app.get("/api/auth-config")
def auth_config() -> dict:
    """Where the app signs people in. The anon key is public by design: it only lets someone sign up or log in."""
    if not supabase_on():
        return {"supabase": False}
    return {"supabase": True, "url": settings.supabase_url.rstrip("/"), "anon_key": settings.supabase_anon_key}


class SessionBody(BaseModel):
    access_token: str
    language: str = "en"
    timezone: str = "UTC"
    parent_address: str = "Mom"
    son_name: str = ""


async def supabase_user(access_token: str) -> dict | None:
    """Asks Supabase whose token this is. Supabase checks the signature, the expiry and that the session still exists."""
    import httpx
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(settings.supabase_url.rstrip("/") + "/auth/v1/user",
                             headers={"apikey": settings.supabase_anon_key, "Authorization": f"Bearer {access_token}"})
    return r.json() if r.status_code == 200 else None


@app.post("/api/account/session")
async def account_session(body: SessionBody) -> dict:
    """The app signed in with Supabase and shows its token here once; it gets back the Kavach token that the app, the
    call service on the phone and the WebSockets use from then on."""
    if not supabase_on():
        raise HTTPException(400, "This server does not use Supabase sign-in.")
    try:
        user = await supabase_user(body.access_token)
    except Exception:
        raise HTTPException(503, "Could not reach the sign-in service. Please try again.")
    if not user or not user.get("id") or not user.get("email"):
        raise HTTPException(401, "Your sign-in has expired. Please log in again.")
    if not (user.get("email_confirmed_at") or user.get("confirmed_at")):
        raise HTTPException(400, "Please confirm your email first: open the link we sent you.")
    fam, token, new = accounts.supabase_session(user["id"], user["email"], body.language, body.timezone, body.parent_address, body.son_name)
    return {"token": token, "role": "son", "family": family_json(fam), "new": new}


def _legacy_only() -> None:
    if supabase_on():
        raise HTTPException(400, "Please update the Kavach app to sign in.")


@app.post("/api/account/signup")
def signup(body: SignupBody) -> dict:
    _legacy_only()
    try:
        fam, token = accounts.signup(body.email, body.password, body.language, body.timezone, body.parent_address, body.son_name)
    except AccountError as e:
        raise HTTPException(400, str(e))
    return {"token": token, "role": "son", "family": family_json(fam)}


@app.post("/api/account/login")
def login(body: LoginBody) -> dict:
    _legacy_only()
    try:
        fam, token = accounts.login(body.email, body.password)
    except AccountError as e:
        raise HTTPException(400, str(e))
    return {"token": token, "role": "son", "family": family_json(fam)}


@app.post("/api/pair")
def pair(body: PairBody, request: Request) -> dict:
    """The protected phone enters the 6-digit code its family showed, and gets its own token (no email or password)."""
    try:
        fam, token = accounts.redeem_pair_code(body.code, request.client.host if request.client else "?")
    except AccountError as e:
        raise HTTPException(400, str(e))
    return {"token": token, "role": "parent", "family": family_json(fam)}


@app.get("/api/me")
def me(request: Request) -> dict:
    """Everything the app needs to draw its screens for this person: role, family, voices, Telegram, the parent's phone."""
    ident = ident_of(request)
    fam = accounts.family(ident.family_id)
    return {"role": ident.role, "family": family_json(fam), "voices": accounts.voice_state(fam.id),
            "phone_connected": fam.id in rooms.phones, "telegram_bot_ready": alerter.has_token,
            "languages": lang.available()}


@app.put("/api/family")
def update_family(body: FamilyBody, request: Request) -> dict:
    ident = need_son(request)
    try:
        fam = accounts.update_family(ident.family_id, **body.model_dump())
    except AccountError as e:
        raise HTTPException(400, str(e))
    return family_json(fam)


@app.post("/api/family/pair-code")
def family_pair_code(request: Request) -> dict:
    ident = need_son(request)
    try:
        return accounts.new_pair_code(ident.family_id)
    except AccountError as e:
        raise HTTPException(503, str(e))


@app.post("/api/family/telegram-link")
async def family_telegram_link(request: Request) -> dict:
    """A one-time link that opens the Kavach bot with a token, so the bot knows which family a chat belongs to."""
    ident = need_son(request)
    username = await alerter.bot_username()
    if not username:
        raise HTTPException(503, "The Telegram bot is not set up on this server.")
    return {"url": f"https://t.me/{username}?start={accounts.new_telegram_link(ident.family_id)}", "bot": username}


def voice_dir(ident: Identity) -> Path:
    base = Path(get_settings().voices_dir)
    return base if ident.family_id == DEFAULT_FAMILY else base / ident.family_id


CLONE_JOBS: dict[tuple[str, str], dict] = {}


@app.get("/api/voices")
def voice_samples(request: Request) -> dict:
    """Which people have a consented voice sample on the server, and the consent wording the app shows."""
    s = get_settings()
    ident = ident_of(request)
    return {"samples": voices_mod.list_samples(voice_dir(ident)), "consent_text": voices_mod.CONSENT_TEXT,
            "min_seconds": voices_mod.MIN_SECONDS, "max_seconds": voices_mod.MAX_SECONDS, "max_takes": 3,
            "persona_voice_id": s.persona_voice_id, "state": accounts.voice_state(ident.family_id),
            "jobs": {p: CLONE_JOBS.get((ident.family_id, p)) for p in voices_mod.PEOPLE if CLONE_JOBS.get((ident.family_id, p))}}


@app.post("/api/voices/{person}")
async def upload_voice_sample(person: str, request: Request, name: str = "", take: int = 1) -> dict:
    """Body: raw 16 kHz mono signed 16-bit PCM. Header `x-kavach-consent: yes` records the speaker's consent. `take` 1-3:
    a few natural takes make a clearer clone than one."""
    s = get_settings()
    consent = request.headers.get("x-kavach-consent", "").lower() == "yes"
    body = await request.body()
    try:
        return voices_mod.save_sample(voice_dir(ident_of(request)), person, name, body, s.sample_rate, consent, take)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/voices/{person}/clone")
async def clone_voice(person: str, request: Request) -> dict:
    """Make the cloned voice from the saved takes, in the background. Poll GET /api/voices for the result."""
    ident = ident_of(request)
    s = get_settings()
    if person not in voices_mod.PEOPLE:
        raise HTTPException(400, "person must be papa or son")
    wav = voice_dir(ident) / f"{person}.wav"
    if not wav.exists():
        raise HTTPException(400, "Record the sample first.")
    if not s.assemblyai_api_key:
        raise HTTPException(503, "Voice cloning is not set up on this server.")
    key = (ident.family_id, person)
    if CLONE_JOBS.get(key, {}).get("state") == "working":
        return CLONE_JOBS[key]
    fam = accounts.family(ident.family_id)
    CLONE_JOBS[key] = job = {"state": "working", "error": None}

    async def run() -> None:
        try:
            made = await voices_mod.clone_voice(s, wav, f"{ident.family_id}-{person}", fam.pack.tts)
            if ident.family_id == DEFAULT_FAMILY:  # the original household keeps its voices in settings
                if person == "son":
                    s.kavach_warning_voice_id = made["voice_id"]
                else:
                    s.persona_voice_id = made["voice_id"]
            accounts.set_voice(ident.family_id, person, made["voice_id"], made["expires"])
            job.update(state="ready")
        except Exception as e:  # shown to the person, so it is plain words
            logging.getLogger("kavach.voices").warning("voice clone failed: %s", e)
            job.update(state="failed", error=str(e)[:200])

    asyncio.create_task(run())
    return job


@app.get("/api/voices/{person}.wav")
def download_voice_sample(person: str, request: Request) -> FileResponse:
    path = voice_dir(ident_of(request)) / f"{person}.wav"
    if person not in voices_mod.PEOPLE or not path.exists():
        raise HTTPException(status_code=404, detail="no sample")
    return FileResponse(path, media_type="audio/wav", filename=f"kavach-{person}-voice-sample.wav")


@app.delete("/api/voices/{person}")
async def delete_voice_sample(person: str, request: Request) -> dict:
    """Withdraws consent: the recording is deleted here, and the cloned voice is deleted at AssemblyAI."""
    ident = ident_of(request)
    if person in voices_mod.PEOPLE:
        old = accounts.voice_id(ident.family_id, person)
        accounts.set_voice(ident.family_id, person, None, None)
        if old and get_settings().assemblyai_api_key:
            asyncio.create_task(voices_mod.delete_remote_voice(get_settings(), old))
    return {"deleted": voices_mod.delete_sample(voice_dir(ident), person)}


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
def update_report(call_id: str, answers: ReportAnswers, request: Request):
    """The user answers the two questions only they can answer; the draft is rebuilt with their answers."""
    if not store.query("SELECT 1 FROM calls WHERE id=?", (call_id,)):
        raise HTTPException(404, "unknown call")
    own_call(request, call_id)
    store.update_call(call_id, money_shared=None if answers.money_shared is None else int(answers.money_shared),
                      otp_shared=None if answers.otp_shared is None else int(answers.otp_shared))
    fam = accounts.family(call_owner(call_id) or DEFAULT_FAMILY)
    extra = {"tz": fam.timezone, "hint": fam.report_hint} if fam is not None and fam.id != DEFAULT_FAMILY else {}
    r, md, pdf = report_mod.generate(store, call_id, settings.reports_dir, notes=answers.notes[:1000], **extra)
    return {"md": f"/api/calls/{call_id}/report.md", "pdf": f"/api/calls/{call_id}/report.pdf", "missing": r.missing}


def report_file(call_id: str, column: str) -> str:
    """The report's path. The database is the record; the file is rebuilt from it if the host lost its disk."""
    row = store.query(f"SELECT {column} AS path FROM calls WHERE id=?", (call_id,))
    if not row or not row[0]["path"]:
        raise HTTPException(404, "no report for this call")
    if not Path(row[0]["path"]).exists():
        fam = accounts.family(call_owner(call_id) or DEFAULT_FAMILY)
        extra = {"tz": fam.timezone, "hint": fam.report_hint} if fam is not None and fam.id != DEFAULT_FAMILY else {}
        report_mod.generate(store, call_id, settings.reports_dir, **extra)
        row = store.query(f"SELECT {column} AS path FROM calls WHERE id=?", (call_id,))
    return row[0]["path"]


@app.get("/api/calls/{call_id}/report.md")
def report_md(call_id: str, request: Request):
    own_call(request, call_id)
    return PlainTextResponse(Path(report_file(call_id, "report_md_path")).read_text(), media_type="text/markdown; charset=utf-8")


@app.get("/api/calls/{call_id}/report.pdf")
def report_pdf(call_id: str, request: Request):
    own_call(request, call_id)
    return FileResponse(report_file(call_id, "report_pdf_path"), media_type="application/pdf", filename=f"kavach-complaint-{call_id}.pdf")


@app.get("/api/calls/{call_id}/evidence")
def call_evidence(call_id: str, request: Request) -> list[dict]:
    own_call(request, call_id)
    return store.query("SELECT type, value, normalized, quote, ts_ms FROM evidence WHERE call_id=? AND valid=1 ORDER BY id", (call_id,))


@app.get("/api/calls/{call_id}/events")
def call_events(call_id: str, request: Request) -> list[dict]:
    own_call(request, call_id)
    return store.events(call_id)


@app.get("/api/calls/{call_id}/turns")
def call_turns(call_id: str, request: Request) -> list[dict]:
    own_call(request, call_id)
    return store.turns(call_id)


@app.get("/api/calls/live")
def live_call(request: Request) -> dict:
    """The call the phone's background listener is streaming now, so the app can open onto it."""
    ident = ident_of(request)
    running = [r for r in rooms.rooms.values() if not r.ended and r.call_id.startswith("apk-")
               and (ident.role == "admin" or (r.family.id if r.family else DEFAULT_FAMILY) == ident.family_id)]
    room = max(running, key=lambda r: r.started_wall, default=None)
    return {"call_id": room.call_id if room else None}


@app.get("/api/phone")
def phone_status(request: Request) -> dict:
    """Whether the protected person's phone is linked to Kavach right now (its always-on connection), for the family's app."""
    return {"connected": ident_of(request).family_id in rooms.phones}


@app.get("/api/calls/takeover-check")
def takeover_check(request: Request) -> dict:
    """What the latest background-listener call did: Kavach's lines and voice sent, and what the phone reported back."""
    if ident_of(request).role != "admin":
        raise HTTPException(403, "Operators only.")
    latest = store.query("SELECT id FROM calls WHERE id LIKE 'apk-%' ORDER BY started_at DESC LIMIT 1")
    if not latest:
        return {"call_id": None}
    call_id = latest[0]["id"]
    events = store.events(call_id)
    wanted = {"takeover": [], "persona_sent": [], "persona_guard": [], "persona_error": [], "client_voice_route": [],
              "client_warning_mute": [], "client_warning_sound": [], "warn_first_audio": [], "warn_done": [],
              "client_hang_up": [], "hang_up_failed": []}
    for e in events:
        if e["type"] in wanted:
            wanted[e["type"]].append(e["payload"])
    room = rooms.rooms.get(call_id)
    desk = [{"type": e["type"], "ago_s": round(time.time() - e["ts_wall"]), **e["payload"]} for e in store.events(DESK)[-10:]]
    return {"call_id": call_id, "running": room is not None and not room.ended, "seconds_sent_to_caller":
            round(sum(p.get("seconds", 0) for p in wanted["persona_sent"]), 1), **wanted,
            "echo_removed": [e["payload"] for e in events if e["type"] == "echo_removed"],
            "phone_link": rooms.phone is not None, "telegram": desk}


@app.post("/api/calls/{call_id}/control")
async def call_control(call_id: str, body: dict, request: Request):
    """Hand over, take back or end from the app, which watches the call instead of being a party on it."""
    room = rooms.rooms.get(call_id)
    if room is None or room.ended or (ident_of(request).role != "admin" and (room.family.id if room.family else DEFAULT_FAMILY) != ident_of(request).family_id):
        raise HTTPException(404, "No such running call")
    if body.get("type") not in ("takeover", "takeback", "end_call"):
        raise HTTPException(400, "Unknown command")
    if body["type"] == "end_call" and room.phone_call:
        result = await room.hang_up()
        if not (result or "").startswith("ok"):
            room.log_event("hang_up_failed", {"result": result})
            raise HTTPException(502, "The phone could not end the call")
    await handle_control(room, "receiver", {"type": body["type"]})
    return {"ok": True}


@app.websocket("/ws/call/{call_id}/{role}")
async def call_socket(ws: WebSocket, call_id: str, role: str, caller_number: str | None = None, mode: str | None = None):
    """One tab of the call. Binary in = PCM from the mic; text in = JSON control messages."""
    ident = accounts.identify(ws.query_params.get("key"))
    if ident is None:
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
    owner = call_owner(call_id)
    if owner is not None and owner != ident.family_id and ident.role != "admin":
        await ws.close(code=4403, reason="not your call")  # a call id never lets another family in
        return
    room = rooms.get(call_id, family_of(ident))
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
        if msg.get("name") in ("voice_route", "warning_mute", "warning_sound", "hang_up"):
            logging.getLogger("kavach.phone").info("PHONE %s call=%s %s", msg["name"], room.call_id, msg.get("payload"))
        if msg.get("name") == "hang_up":
            room.hang_up_reported(str(msg.get("payload", {}).get("result", "")))


@app.websocket("/ws/phone")
async def phone_socket(ws: WebSocket):
    """Held open all the time by the phone's background service, so a family voice note reaches it with no call on."""
    ident = accounts.identify(ws.query_params.get("key"))
    if ident is None:
        await ws.close(code=4403)
        return
    await ws.accept()
    peer = Peer(ws)
    fid = ident.family_id
    rooms.phones[fid] = peer
    log = logging.getLogger("kavach.phone")
    log.info("PHONE link up")
    try:
        while True:
            msg = await ws.receive()
            if msg["type"] == "websocket.disconnect":
                break
            if msg.get("text") and json.loads(msg["text"]).get("type") == "note_received":
                rooms.phone_heard.set()
    except WebSocketDisconnect:
        pass
    finally:
        if rooms.phones.get(fid) is peer:
            rooms.phones.pop(fid, None)
            log.info("PHONE link down")


@app.websocket("/ws/events/{call_id}")
async def events_socket(ws: WebSocket, call_id: str):
    """Read-only event stream for the dashboard."""
    ident = accounts.identify(ws.query_params.get("key"))
    owner = call_owner(call_id)
    if ident is None or (owner is not None and owner != ident.family_id and ident.role != "admin"):
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
