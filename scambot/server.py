"""The demo scammer as its own small server, separate from Kavach.

Run:      uv run uvicorn scambot.server:app --port 8100
Trigger:  curl -X POST "localhost:8100/call?base=https://<public address>"
Status:   curl localhost:8100/status

/call only answers requests made on this machine, so nobody on the internet can make it ring a phone. Twilio reaches
/twilio/stream/<one-time token> through PUBLIC_BASE_URL.
"""

import logging

from fastapi import FastAPI, HTTPException, Request, WebSocket

from app.llm import LLM
from app.stt import SttSession
from app.tts import TtsPool
from scambot.call import TwilioDesk, TwilioError
from scambot.config import BotSettings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
settings = BotSettings()
llm = LLM(settings)
desk = TwilioDesk(settings, llm, TtsPool(settings), lambda channel, on_event: SttSession(channel, settings, on_event))
app = FastAPI(title="Kavach demo scammer")


def local_only(request: Request) -> None:
    # A request through the public tunnel arrives with forwarding headers; only this Mac's own requests have none.
    forwarded = any(h in request.headers for h in ("x-forwarded-for", "cf-connecting-ip"))
    if forwarded or request.client is None or request.client.host not in ("127.0.0.1", "::1"):
        raise HTTPException(status_code=403, detail="Only this machine can use this.")


@app.post("/call")
async def call(request: Request, base: str = "") -> dict:
    """`base` is the public https address (the tunnel's), when it is not already in PUBLIC_BASE_URL."""
    local_only(request)
    try:
        return await desk.start_call(base or settings.public_base_url)
    except TwilioError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/status")
def status(request: Request) -> dict:
    local_only(request)
    return {"configured": desk.configured, "public_base_url": settings.public_base_url, "in_call": desk.active is not None,
            "live": desk.active.transcript[-8:] if desk.active else [], "last": desk.last}


@app.websocket("/twilio/stream/{token}")
async def stream(ws: WebSocket, token: str) -> None:
    await desk.run(ws, token)
