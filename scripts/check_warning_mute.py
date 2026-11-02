"""Live check: while the family-voice warning plays, the person's microphone must NOT reach the caller.

Runs the scripted digital-arrest call (the receiver's microphone track is continuous, with replies), listens on the
CALLER socket, and counts audio frames that arrive from the receiver (source 0) inside the warning window versus outside.

    uv run uvicorn app.main:app --port 8000     # other terminal
    uv run python scripts/check_warning_mute.py
"""

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

import httpx
import websockets

sys.path.insert(0, str(Path(__file__).resolve().parent))
import smoke_call as sc  # noqa: E402

S = sc.S
SOURCE_PEER, SOURCE_WARNING = 0, 1


async def main(base: str) -> int:
    call_id = f"mutecheck-{int(time.time())}"
    sc.OUT.mkdir(parents=True, exist_ok=True)
    async with httpx.AsyncClient(timeout=60) as client:
        turns = [(role, await sc.render(client, i, role, text)) for i, (role, text) in enumerate(sc.SCRIPT[:5])]
    tracks = sc.build_channels(turns)
    for t in tracks.values():
        t += bytes(S.sample_rate * 2 * 12)
    ws_base = base.replace("http", "ws", 1)
    peer_frames_at_caller: list[float] = []   # arrival times of frames from the receiver, seen by the caller
    warn_frames: list[float] = []             # warning frames at the receiver
    flushes: list[float] = []                 # stop-warning commands seen by the receiver
    states: list[tuple[float, str]] = []

    async def caller_reader(ws):
        async for raw in ws:
            if isinstance(raw, bytes) and raw[0] == SOURCE_PEER:
                peer_frames_at_caller.append(time.monotonic())

    async def receiver_reader(ws):
        async for raw in ws:
            if isinstance(raw, bytes):
                if raw[0] == SOURCE_WARNING:
                    warn_frames.append(time.monotonic())
                continue
            ev = json.loads(raw)
            if ev["type"] == "flush_playback" and ev.get("source") == SOURCE_WARNING:
                flushes.append(time.monotonic())
            elif ev["type"] == "warning":
                states.append((time.monotonic(), ev["state"]))
            elif ev["type"] == "call_ended":
                return

    async with websockets.connect(f"{ws_base}/ws/call/{call_id}/caller?mode=eval") as caller, \
               websockets.connect(f"{ws_base}/ws/call/{call_id}/receiver?mode=eval") as receiver:
        readers = [asyncio.create_task(caller_reader(caller)), asyncio.create_task(receiver_reader(receiver))]
        await asyncio.sleep(1.5)
        t0 = time.monotonic()
        await asyncio.gather(sc.stream(caller, tracks["caller"], t0), sc.stream(receiver, tracks["receiver"], t0))
        await caller.send(json.dumps({"type": "end_call"}))
        await asyncio.wait_for(readers[1], 15)
        readers[0].cancel()

    if not warn_frames:
        print("no warning played: nothing to check")
        return 1
    # The warning is audible from its first frame until its audio has played out, or until it was stopped.
    audio_s = len(warn_frames) * 0.08
    start = warn_frames[0]
    end = start + audio_s
    stops = [f for f in flushes if f >= start]
    if stops:
        end = min(end, stops[0])
    inside = [t for t in peer_frames_at_caller if start + 0.05 <= t <= end - 0.05]
    before = [t for t in peer_frames_at_caller if t < start - 0.05]
    after = [t for t in peer_frames_at_caller if t > end + 0.4]
    print(json.dumps({
        "warning_audible_s": round(end - start, 2), "ended_by": "person spoke (stop command)" if stops and end == stops[0] else "played out",
        "frames_from_person_reaching_caller": {"before_warning": len(before), "DURING_warning": len(inside), "after_warning": len(after)},
        "states": [s for _, s in states],
    }, indent=1))
    ok = len(inside) == 0 and len(before) > 10 and len(after) > 10
    print("PASS: the caller hears nothing from the person while the warning plays, and hears them again afterwards"
          if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8000")
    sys.exit(asyncio.run(main(ap.parse_args().base)))
