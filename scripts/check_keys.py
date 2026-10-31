"""M0 gate: prove every external credential works, without printing any secret.

    uv run python scripts/check_keys.py                 # run all checks
    uv run python scripts/check_keys.py --find-chat-id  # print Telegram chat ids that messaged the bot
"""

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path
from urllib.parse import urlencode

import httpx
import websockets

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.config import get_settings  # noqa: E402

S = get_settings()
OUT = Path("data/check")


def report(name: str, status: str, detail: str) -> None:
    print(f"[{status:4}] {name}: {detail}")


async def check_stt() -> str:
    params = {"speech_model": S.stt_model, "sample_rate": S.sample_rate, "encoding": "pcm_s16le"}
    if S.stt_model.startswith("universal-3"):
        params["language_codes"] = json.dumps(S.stt_language_codes)
    url = f"{S.stt_ws_url}?{urlencode(params)}"
    t0 = time.perf_counter()
    async with websockets.connect(url, additional_headers={"Authorization": S.assemblyai_api_key}) as ws:
        first = json.loads(await asyncio.wait_for(ws.recv(), 10))
        ms = (time.perf_counter() - t0) * 1000
        if first.get("type") != "Begin":
            raise RuntimeError(f"expected Begin, got {first}")
        await ws.send(json.dumps({"type": "Terminate"}))
        async for raw in ws:
            if isinstance(raw, str) and json.loads(raw).get("type") == "Termination":
                break
    model = first["configuration"].get("model")
    if model != S.stt_model:
        raise RuntimeError(f"requested {S.stt_model} but Begin says {model}")
    return f"Begin in {ms:.0f} ms, model={model}, session={first['id']}"


async def check_tts_library_voice() -> str:
    headers = {"Authorization": S.assemblyai_api_key}
    async with httpx.AsyncClient(timeout=30) as client:
        listed = ""
        r = await client.get(S.tts_http_url.replace("/speech", "/voices"), headers=headers)
        if r.status_code == 200:
            body = r.json()
            voices = body.get("voices") or body.get("data") or (body if isinstance(body, list) else [])
            if voices:
                v = voices[0]
                listed = f"listed {len(voices)} voices, first={v.get('slug') or v.get('voice_id') or v}; "
        else:
            listed = f"GET /v1/voices -> {r.status_code} (no list route; resolving a voice by synthesis); "
        t0 = time.perf_counter()
        r = await client.post(
            S.tts_http_url,
            headers=headers,
            json={"text": "Kavach key check.", "voice_id": S.persona_voice_id, "container": "wav",
                  "language": S.language, "stream": False},
        )
        ms = (time.perf_counter() - t0) * 1000
    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code}: {r.text[:300]}")
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "tts_library_voice.wav").write_bytes(r.content)
    h = r.headers
    return (f"{listed}synthesized with voice_id={h.get('x-tts-voice-id')} model={h.get('x-tts-model')} "
            f"{h.get('x-tts-sample-rate')} Hz, {h.get('x-tts-audio-duration-ms')} ms audio in {ms:.0f} ms "
            f"-> {OUT / 'tts_library_voice.wav'}")


async def check_cloned_voice() -> str:
    params = {"voice_id": S.kavach_warning_voice_id, "sample_rate": S.sample_rate, "encoding": "pcm_s16le"}
    url = f"{S.tts_ws_url}?{urlencode(params)}"
    async with websockets.connect(url, additional_headers={"Authorization": S.assemblyai_api_key}) as ws:
        first = json.loads(await asyncio.wait_for(ws.recv(), 10))
        if first.get("type") == "Error":
            raise RuntimeError(f"{first['error_code']} {first['error_type']}: {first['error']}")
        cfg = first["configuration"]
        t0 = time.perf_counter()
        await ws.send(json.dumps({"type": "Generate", "text": f"{S.parent_address}, this is a test of Kavach."}))
        await ws.send(json.dumps({"type": "Flush"}))
        first_audio_ms, n = None, 0
        async for raw in ws:
            msg = json.loads(raw)
            if msg["type"] == "Audio":
                first_audio_ms = first_audio_ms or (time.perf_counter() - t0) * 1000
                n += 1
            elif msg["type"] == "FlushDone":
                await ws.send(json.dumps({"type": "Terminate"}))
            elif msg["type"] in ("Termination", "Error"):
                break
    expires = cfg.get("voice_expires_at")
    exp_txt = time.strftime("%Y-%m-%d", time.gmtime(expires)) if expires else "none"
    return (f"resolved={cfg['resolved_voice']['voice_id']} lang={cfg['language']} model={cfg['model']} "
            f"expires={exp_txt}, first audio {first_audio_ms:.0f} ms after Generate ({n} frames)")


async def check_llm() -> str:
    t0 = time.perf_counter()
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(
            f"{S.llm_gateway_url}/chat/completions",
            headers={"authorization": S.assemblyai_api_key},
            json={"model": S.detector_model, "reasoning_effort": S.detector_reasoning_effort, "max_tokens": 20,
                  "messages": [{"role": "user", "content": "Reply with exactly: kavach ok"}]},
        )
    ms = (time.perf_counter() - t0) * 1000
    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code}: {r.text[:300]}")
    reply = r.json()["choices"][0]["message"]["content"]
    return f"model={S.detector_model} replied {reply.strip()!r} in {ms:.0f} ms"


async def check_telegram() -> str:
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(f"https://api.telegram.org/bot{S.telegram_bot_token}/getMe")
    body = r.json()
    if not body.get("ok"):
        raise RuntimeError(body.get("description"))
    chat = "chat id set" if S.telegram_chat_id else "TELEGRAM_CHAT_ID not set (use --find-chat-id)"
    return f"bot @{body['result']['username']} ok; {chat}"


async def find_chat_id() -> None:
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(f"https://api.telegram.org/bot{S.telegram_bot_token}/getUpdates")
    chats = {}
    for u in r.json().get("result", []):
        chat = (u.get("message") or u.get("my_chat_member") or {}).get("chat")
        if chat:
            chats[chat["id"]] = chat.get("first_name") or chat.get("title") or ""
    if not chats:
        print("No messages yet. Send your bot any message from Telegram, then run this again.")
    for cid, name in chats.items():
        print(f"chat_id={cid}  ({name})")


CHECKS = [
    ("AssemblyAI streaming STT", check_stt, ["assemblyai_api_key"]),
    ("AssemblyAI TTS (library voice)", check_tts_library_voice, ["assemblyai_api_key"]),
    ("AssemblyAI LLM Gateway", check_llm, ["assemblyai_api_key"]),
    ("AssemblyAI TTS (cloned voice)", check_cloned_voice, ["assemblyai_api_key", "kavach_warning_voice_id"]),
    ("Telegram bot", check_telegram, ["telegram_bot_token"]),
]


async def main() -> int:
    failed = 0
    for name, fn, needs in CHECKS:
        missing = [n.upper() for n in needs if not getattr(S, n)]
        if missing:
            report(name, "SKIP", f"missing {', '.join(missing)}")
            failed += 1
            continue
        try:
            report(name, "OK", await fn())
        except Exception as e:  # report every failure, keep going
            report(name, "FAIL", f"{type(e).__name__}: {e}")
            failed += 1
    print(f"\n{len(CHECKS) - failed}/{len(CHECKS)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--find-chat-id", action="store_true")
    args = p.parse_args()
    if args.find_chat_id:
        asyncio.run(find_chat_id())
    else:
        sys.exit(asyncio.run(main()))
