"""M1 live gate: stream a two-voice call through the running server and measure per-channel STT.

    uv run uvicorn app.main:app --port 8000          # in another terminal
    uv run python scripts/smoke_call.py              # renders the script once with TTS-1, then streams it

Each party's audio goes over its own WebSocket in real time (50 ms chunks), with silence while the
other party talks, exactly like two browser tabs. Prints every final transcript with its STT latency
(server receipt of the final minus when the last word's audio was sent) and a word-match score.
"""

import argparse
import asyncio
import difflib
import json
import statistics
import sys
import time
from pathlib import Path

import httpx
import websockets

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.config import get_settings  # noqa: E402

S = get_settings()
OUT = Path("data/smoke")
CHUNK_BYTES = S.sample_rate * 2 // 20  # 50 ms
GAP_MS = 800

SCRIPT = [
    ("caller", "Hello, am I speaking with Mister Sharma? This is Inspector Vikram Rathore from the Mumbai cyber crime cell."),
    ("receiver", "Yes, this is Sharma speaking. What is this about?"),
    ("caller", "A parcel booked in your name was seized at customs with illegal drugs and fake passports inside."),
    ("receiver", "What? I have not sent any parcel to anyone."),
    ("caller", "Your Aadhaar number was used. You must stay on this call and not tell anyone, or we will issue an arrest warrant."),
    ("receiver", "Please, I don't understand. What should I do?"),
]
VOICES = {"caller": "aai-titus", "receiver": "aai-audrey"}


async def render(client: httpx.AsyncClient, i: int, role: str, text: str) -> bytes:
    path = OUT / f"turn{i}_{role}.pcm"
    if path.exists():
        return path.read_bytes()
    r = await client.post(
        S.tts_http_url,
        headers={"Authorization": S.assemblyai_api_key},
        json={"text": text, "voice_id": VOICES[role], "language": S.language, "container": "raw",
              "encoding": "pcm_s16le", "sample_rate": S.sample_rate, "stream": False},
    )
    r.raise_for_status()
    path.write_bytes(r.content)
    return r.content


def build_channels(turns: list[tuple[str, bytes]]) -> dict[str, bytearray]:
    """Two equal-length tracks: each party's speech where they talk, silence elsewhere."""
    gap = bytes(S.sample_rate * 2 * GAP_MS // 1000)
    tracks = {"caller": bytearray(gap), "receiver": bytearray(gap)}
    for role, pcm in turns:
        other = "receiver" if role == "caller" else "caller"
        tracks[role] += pcm + gap
        tracks[other] += bytes(len(pcm)) + gap
    tail = bytes(S.sample_rate * 2 * 3)  # 3 s so the last turn can end
    for t in tracks.values():
        t += tail
    return tracks


async def stream(ws, pcm: bytearray, t0: float) -> None:
    for i in range(0, len(pcm), CHUNK_BYTES):
        due = t0 + (i / (S.sample_rate * 2))
        await asyncio.sleep(max(0, due - time.monotonic()))
        await ws.send(bytes(pcm[i:i + CHUNK_BYTES]))


async def collect(ws, finals: list, status: dict, counts: dict | None = None) -> None:
    async for raw in ws:
        if isinstance(raw, bytes):
            continue
        ev = json.loads(raw)
        if counts is not None:
            key = f"{ev['type']}:{ev.get('channel')}:{'final' if ev.get('final') else 'partial'}"
            counts[key] = counts.get(key, 0) + 1
        if ev["type"] == "transcript" and ev["final"]:
            finals.append(ev)
            if counts is not None:
                print(f"  [{ev['channel']:8}] STT {ev['stt_latency_ms']!s:>5} ms | {ev['text']}")
        elif ev["type"] == "stt_status":
            status[ev["channel"]] = ev
            if counts is not None:
                print(f"  [{ev['channel']:8}] STT session: {ev.get('model') or ev.get('error')}")
        elif ev["type"] == "call_ended":
            return


def score(expected: str, got: str) -> float:
    norm = lambda s: [w.strip(".,?!").lower() for w in s.split()]  # noqa: E731
    return difflib.SequenceMatcher(None, norm(expected), norm(got)).ratio()


async def main(base: str, call_id: str) -> int:
    if not S.assemblyai_api_key:
        print("ASSEMBLYAI_API_KEY not set in .env")
        return 2
    OUT.mkdir(parents=True, exist_ok=True)
    async with httpx.AsyncClient(timeout=60) as client:
        health = (await client.get(f"{base}/health")).json()
        print(f"server ok, stt_model={health['stt_model']}")
        turns = [(role, await render(client, i, role, text)) for i, (role, text) in enumerate(SCRIPT)]
    tracks = build_channels(turns)
    print(f"streaming {len(tracks['caller']) / (S.sample_rate * 2):.1f} s per channel, call_id={call_id}")

    ws_base = base.replace("http", "ws", 1)
    finals: list = []
    status: dict = {}
    async with websockets.connect(f"{ws_base}/ws/call/{call_id}/caller?mode=eval&caller_number=%2B919876543210") as caller, \
               websockets.connect(f"{ws_base}/ws/call/{call_id}/receiver") as receiver:
        counts: dict = {}
        reader = asyncio.create_task(collect(receiver, finals, status, counts))
        drain = asyncio.create_task(collect(caller, [], {}))  # keep the caller socket read
        await asyncio.sleep(1.5)  # let both STT sessions reach Begin
        t0 = time.monotonic()
        await asyncio.gather(stream(caller, tracks["caller"], t0), stream(receiver, tracks["receiver"], t0))
        await caller.send(json.dumps({"type": "end_call"}))
        await asyncio.wait_for(asyncio.gather(reader, drain), 15)

    print("event counts seen by receiver socket:", json.dumps(counts))
    # Match finals to script turns by best word overlap within the same channel.
    rows = []
    for i, (role, text) in enumerate(SCRIPT):
        got = " ".join(f["text"] for f in finals if f["channel"] == role and score(text, f["text"]) > 0.3)
        rows.append({"turn": i, "channel": role, "expected": text, "got": got, "match": round(score(text, got), 3)})
    lat = {ch: [f["stt_latency_ms"] for f in finals if f["channel"] == ch and f["stt_latency_ms"] is not None]
           for ch in ("caller", "receiver")}
    summary = {
        "call_id": call_id,
        "stt_model": {ch: status.get(ch, {}).get("model") for ch in ("caller", "receiver")},
        "finals": len(finals),
        "latency_ms": {ch: {"n": len(v), "median": statistics.median(v) if v else None, "max": max(v) if v else None}
                       for ch, v in lat.items()},
        "mean_word_match": round(statistics.mean(r["match"] for r in rows), 3),
        "turns": rows,
    }
    path = OUT / f"result-{call_id}.json"
    path.write_text(json.dumps(summary, indent=2))
    print(json.dumps({k: v for k, v in summary.items() if k != "turns"}, indent=2))
    print(f"saved {path}")
    ok = (all(status.get(ch, {}).get("ok") for ch in ("caller", "receiver"))
          and all(r["match"] >= 0.6 for r in rows))
    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--base", default="http://localhost:8000")
    p.add_argument("--call-id", default=f"smoke-{int(time.time())}")
    a = p.parse_args()
    sys.exit(asyncio.run(main(a.base, a.call_id)))
