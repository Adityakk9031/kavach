"""M3 live gate: scam call -> trigger -> warning in the cloned voice on the Receiver tab -> optional barge-in.

    uv run uvicorn app.main:app --port 8000          # other terminal; wait for 'session ready' (voice warm)
    uv run python scripts/smoke_warning.py --runs 3 --barge none
    uv run python scripts/smoke_warning.py --runs 2 --barge browser

The script plays the caller's turns and the receiver's first two replies, then stays quiet so the warning can
play. `--barge browser` sends the same `barge_in` message the receiver page sends when its voice detector fires,
1.0 s after the first warning frame, and counts warning frames that arrive after the cancel.
Saves the warning audio the Receiver got to data/warning/<call>.wav so you can listen to it.
"""

import argparse
import asyncio
import json
import sys
import time
import wave
from pathlib import Path

import httpx
import websockets

sys.path.insert(0, str(Path(__file__).resolve().parent))
import smoke_call as sc  # noqa: E402

S = sc.S
OUT = Path("data/warning")
SOURCE_WARNING = 1
CLONE_UUID_HINT = "resolved"


async def run(base: str, call_id: str, barge: str) -> dict:
    OUT.mkdir(parents=True, exist_ok=True)
    sc.OUT.mkdir(parents=True, exist_ok=True)
    async with httpx.AsyncClient(timeout=60) as client:
        turns = [(role, await sc.render(client, i, role, text)) for i, (role, text) in enumerate(sc.SCRIPT[:5])]
    tracks = sc.build_channels(turns)
    quiet = bytes(S.sample_rate * 2 * 14)  # room for a ~10 s warning after the last caller word
    for t in tracks.values():
        t += quiet

    ws_base = base.replace("http", "ws", 1)
    frames: list[tuple[float, bytes]] = []  # (arrival time, pcm) of warning frames at the Receiver
    marks: dict = {}
    states: list[str] = []

    async def receiver_reader(ws):
        async for raw in ws:
            if isinstance(raw, bytes):
                if raw[0] == SOURCE_WARNING:
                    now = time.monotonic()
                    frames.append((now, raw[1:]))
                    if "first" not in marks:
                        marks["first"] = now
            else:
                ev = json.loads(raw)
                if ev["type"] == "flush_playback" and ev.get("source") == SOURCE_WARNING:
                    marks.setdefault("flushed", time.monotonic())
                if ev["type"] == "warning":
                    states.append(ev["state"])
                if ev["type"] == "call_ended":
                    return

    async def barger(ws):
        while "first" not in marks:
            await asyncio.sleep(0.01)
        await asyncio.sleep(1.0)
        marks["barge_sent"] = time.monotonic()
        await ws.send(json.dumps({"type": "barge_in"}))

    async with websockets.connect(f"{ws_base}/ws/call/{call_id}/caller?caller_number=%2B919876543210") as caller, \
               websockets.connect(f"{ws_base}/ws/call/{call_id}/receiver") as receiver:
        readers = [asyncio.create_task(receiver_reader(receiver)), asyncio.create_task(sc.collect(caller, [], {}))]
        if barge == "browser":
            readers.append(asyncio.create_task(barger(receiver)))
        await asyncio.sleep(1.5)
        t0 = time.monotonic()
        await asyncio.gather(sc.stream(caller, tracks["caller"], t0), sc.stream(receiver, tracks["receiver"], t0))
        await caller.send(json.dumps({"type": "end_call"}))
        await asyncio.wait_for(readers[0], 15)
        for r in readers[1:]:
            r.cancel()

    async with httpx.AsyncClient(timeout=20) as client:
        events = (await client.get(f"{base}/api/calls/{call_id}/events")).json()
    by = {}
    for e in events:
        by.setdefault(e["type"], []).append(e["payload"])

    pcm = b"".join(p for _, p in frames)
    if pcm:
        with wave.open(str(OUT / f"{call_id}.wav"), "wb") as w:
            w.setnchannels(1), w.setsampwidth(2), w.setframerate(S.sample_rate), w.writeframes(pcm)
    first_audio = (by.get("warn_first_audio") or [{}])[0]
    sent = (by.get("warn_tts_sent") or [{}])[0]
    result = {
        "call_id": call_id, "barge": barge,
        "triggered": bool(by.get("trigger")),
        "warning_voice": {"requested": sent.get("voice"), "resolved_uuid": sent.get("resolved_voice"),
                          "cloned": sent.get("cloned")},
        "trigger_to_first_audio_ms": first_audio.get("trigger_to_audio_ms"),
        "turn_end_to_first_audio_ms": first_audio.get("turn_end_to_audio_ms"),
        "tts_ttfa_ms": first_audio.get("ttfa_ms"),
        "warning_frames": len(frames),
        "warning_audio_s": round(len(pcm) / 2 / S.sample_rate, 2),
        "warning_states": states,
        "wav": str(OUT / f"{call_id}.wav") if pcm else None,
    }
    if barge == "browser" and "barge_sent" in marks:
        late = [t for t, _ in frames if t > marks["barge_sent"] + 0.25]
        be = (by.get("barge_in") or [{}])[0]
        heard_s = 1.0  # the barge-in fired 1.0 s after the first frame
        result.update({
            "barge_to_stop_playback_cmd_ms": round((marks["flushed"] - marks["barge_sent"]) * 1000)
            if "flushed" in marks else None,
            "frames_after_cancel_plus_250ms": len(late),
            "tts_still_generating_at_barge": be.get("tts_still_generating"),
            "warning_audio_that_would_have_kept_playing_s": round(max(0.0, result["warning_audio_s"] - heard_s), 1),
            "interrupted": "interrupted" in states})
    return result


async def main(args) -> int:
    results = []
    for i in range(args.runs):
        cid = f"warn-{args.barge}-{int(time.time())}-{i}"
        print(f"--- run {i + 1}/{args.runs} call_id={cid}")
        r = await run(args.base, cid, args.barge)
        print(json.dumps(r, indent=1))
        results.append(r)
        if i < args.runs - 1:
            await asyncio.sleep(25)  # stay under the free plan's 5 new STT sessions per minute
    ok = all(r["triggered"] and r["turn_end_to_first_audio_ms"] is not None and r["turn_end_to_first_audio_ms"] <= 3000
             and (args.barge != "browser" or (r.get("interrupted") and r.get("barge_to_stop_playback_cmd_ms") is not None
                                              and r["barge_to_stop_playback_cmd_ms"] < 500)) for r in results)
    lat = sorted(r["turn_end_to_first_audio_ms"] for r in results if r["turn_end_to_first_audio_ms"] is not None)
    print(f"\nturn_end -> first warning audio (ms): {lat}")
    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--base", default="http://localhost:8000")
    p.add_argument("--runs", type=int, default=1)
    p.add_argument("--barge", choices=["none", "browser"], default="none")
    sys.exit(asyncio.run(main(p.parse_args())))
