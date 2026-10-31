"""Run rendered eval calls through the LIVE backend (same relay, STT, detector, warner as a real call) and score them.

    uv run uvicorn app.main:app --port 8000        # other terminal, wait for the voice to warm
    uv run python -m eval.run_eval --split test

Each call is streamed in real time on two sockets (caller channel, receiver channel), like two phones. When the
warning's first audio reaches the receiver the call is ended 1.5 s later (the metrics need only the first trigger);
calls that never trigger run to the end. Calls start at least 25 s apart (free plan: 5 new STT sessions a minute,
two per call). Results are written after every call, so a crashed run resumes with the same --run-id.
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

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.config import get_settings  # noqa: E402
from eval.metrics import compute  # noqa: E402

HERE = Path(__file__).resolve().parent
SCRIPTS, AUDIO, RESULTS = HERE / "scripts", HERE / "audio", HERE / "results"
SOURCE_WARNING = 1
CHUNK_BYTES = 1600  # 50 ms at 16 kHz s16le


def load_channels(script_id: str, rate: int) -> tuple[bytearray, bytearray, dict]:
    timing = json.loads((AUDIO / f"{script_id}.timing.json").read_text())
    with wave.open(str(AUDIO / f"{script_id}.wav")) as w:
        assert w.getframerate() == rate and w.getnchannels() == 1
        pcm = w.readframes(w.getnframes())
    tracks = {"caller": bytearray(pcm), "receiver": bytearray(pcm)}
    for t in timing["turns"]:
        other = "receiver" if t["speaker"] == "caller" else "caller"
        a, b = int(t["start_ms"] * rate / 1000) * 2, int(t["end_ms"] * rate / 1000) * 2
        tracks[other][a:b] = bytes(b - a)  # each party's microphone only carries their own speech
    return tracks["caller"], tracks["receiver"], timing


async def stream(ws, pcm: bytearray, t0: float, rate: int) -> None:
    for i in range(0, len(pcm), CHUNK_BYTES):
        await asyncio.sleep(max(0, t0 + i / (rate * 2) - time.monotonic()))
        await ws.send(bytes(pcm[i:i + CHUNK_BYTES]))


async def drain(ws, on_event=None) -> None:
    async for raw in ws:
        if isinstance(raw, str) and on_event:
            on_event(json.loads(raw))


async def run_call(base: str, call_id: str, script: dict, rate: int) -> dict:
    caller_pcm, receiver_pcm, timing = load_channels(script["id"], rate)
    tail = bytes(rate * 2 * 6)
    caller_pcm += tail
    receiver_pcm += tail
    ws_base = base.replace("http", "ws", 1)
    marks: dict = {}
    warning_states: list[str] = []

    async def receiver_reader(ws):
        async for raw in ws:
            if isinstance(raw, bytes):
                if raw[0] == SOURCE_WARNING and "first_warning" not in marks:
                    marks["first_warning"] = time.monotonic()
                continue
            ev = json.loads(raw)
            if ev["type"] == "warning":
                warning_states.append(ev["state"])
            elif ev["type"] == "call_ended":
                return

    async with websockets.connect(f"{ws_base}/ws/call/{call_id}/caller?caller_number=" + script["caller_number"].replace("+", "%2B").replace(" ", "")) as caller, \
               websockets.connect(f"{ws_base}/ws/call/{call_id}/receiver") as receiver:
        reader = asyncio.create_task(receiver_reader(receiver))
        cdrain = asyncio.create_task(drain(caller))
        await asyncio.sleep(2.0)  # both STT sessions reach Begin
        marks["t0"] = t0 = time.monotonic()
        streams = [asyncio.create_task(stream(caller, caller_pcm, t0, rate)),
                   asyncio.create_task(stream(receiver, receiver_pcm, t0, rate))]
        both = asyncio.gather(*streams)
        while not both.done():
            if "first_warning" in marks and time.monotonic() - marks["first_warning"] > 1.5:
                break  # triggered and warned: that is all the metrics need
            await asyncio.sleep(0.05)
        for s in streams:
            s.cancel()
        await asyncio.gather(*streams, return_exceptions=True)
        marks["ended_at"] = time.monotonic()
        await caller.send(json.dumps({"type": "end_call"}))
        try:
            await asyncio.wait_for(reader, 10)
        except asyncio.TimeoutError:
            pass
        cdrain.cancel()

    async with httpx.AsyncClient(timeout=20) as client:
        events = (await client.get(f"{base}/api/calls/{call_id}/events")).json()
        turns = (await client.get(f"{base}/api/calls/{call_id}/turns")).json()
    return score(script, timing, marks, events, turns, warning_states)


def score(script: dict, timing: dict, marks: dict, events: list[dict], turns: list[dict], warning_states: list[str]) -> dict:
    by: dict[str, list[dict]] = {}
    for e in events:
        by.setdefault(e["type"], []).append(e["payload"])
    trigger = (by.get("trigger") or [None])[0]
    caller_turns = [t for t in timing["turns"] if t["speaker"] == "caller"]
    trigger_script_turn = None
    if trigger:
        row = next((t for t in turns if t["channel"] == "caller" and t["idx"] == trigger["turn_idx"]), None)
        if row and row["audio_end_ms"] is not None:  # caller-channel clock == script timeline (both start at t0)
            trigger_script_turn = min(caller_turns, key=lambda t: abs(t["end_ms"] - row["audio_end_ms"]))["i"]
    warn_s = (marks["first_warning"] - marks["t0"]) if "first_warning" in marks else None
    dec = script["decisive_turn_index"]
    dec_end_s = timing["turns"][dec]["end_ms"] / 1000 if dec is not None else None
    s56 = script["first_s5_s6_turn_index"]
    first_audio = (by.get("warn_first_audio") or [{}])[0]
    detects = by.get("detect", [])
    return {
        "id": script["id"], "label": script["label"], "category": script["category"], "scam_type": script["scam_type"],
        "subtype": script["subtype"], "split": script["split"],
        "decisive_turn_index": dec, "first_s5_s6_turn_index": s56,
        "triggered": trigger is not None,
        "trigger_reason": trigger["reason"] if trigger else None,
        "trigger_script_turn": trigger_script_turn,
        "caught_before_s5s6": (trigger_script_turn < s56) if (trigger_script_turn is not None and s56 is not None) else None,
        "warning_first_audio_s": round(warn_s, 2) if warn_s is not None else None,
        "decisive_end_s": dec_end_s,
        "decisive_to_warning_s": round(warn_s - dec_end_s, 2) if (warn_s is not None and dec_end_s is not None) else None,
        "tts_ttfa_ms": first_audio.get("ttfa_ms"),
        "turn_end_to_audio_ms": first_audio.get("turn_end_to_audio_ms"),
        "warning_voice_cloned": (by.get("warn_tts_sent") or [{}])[0].get("cloned"),
        "warning_states": warning_states,
        "max_risk": max((d["risk_cum"] for d in detects), default=0),
        "detections": [{"turn_idx": d["turn_idx"], "stages": d["stages_all"], "risk_llm": d["risk_llm"],
                        "risk_cum": d["risk_cum"], "llm_ms": d["llm_ms"], "trigger": d["trigger"]} for d in detects],
        "detect_errors": len(by.get("detect_error", [])),
        "stt_incidents": len(by.get("stt_closed", [])) + len(by.get("stt_error", [])) + len(by.get("loop_lag", [])),
        "stt_finals": [{"channel": t["channel"], "text": t["text"], "latency_ms": t["stt_latency_ms"]} for t in turns],
        "duration_streamed_s": round(marks["ended_at"] - marks["t0"], 1),
    }


async def main(a) -> int:
    S = get_settings()
    RESULTS.mkdir(exist_ok=True)
    run_id = a.run_id or time.strftime("%Y%m%d-%H%M%S")
    path = RESULTS / f"{a.split}-{run_id}.json"
    scripts = [json.loads(p.read_text()) for p in sorted(SCRIPTS.glob("*.json"))]
    scripts = [s for s in scripts if s["split"] == a.split and (AUDIO / f"{s['id']}.timing.json").exists()]
    if a.ids:
        scripts = [s for s in scripts if s["id"] in a.ids]
    if a.limit:
        scripts = scripts[:a.limit]
    results = []
    if path.exists():
        results = json.loads(path.read_text())["results"]
    done = {r["id"] for r in results}
    async with httpx.AsyncClient(timeout=10) as c:
        cfg = (await c.get(f"{a.base}/api/config")).json()
    print(f"run {run_id}: {len(scripts)} calls ({len(done)} already done), config {cfg}")
    last_start = 0.0
    for n, script in enumerate(scripts, 1):
        if script["id"] in done:
            continue
        wait = a.min_gap - (time.monotonic() - last_start)
        if wait > 0:
            await asyncio.sleep(wait)
        last_start = time.monotonic()
        try:
            r = await run_call(a.base, f"{run_id}-{script['id']}", script, S.sample_rate)
        except Exception as e:
            print(f"  [{n}/{len(scripts)}] {script['id']}: ERROR {type(e).__name__}: {e}")
            continue
        results.append(r)
        flag = "TRIGGER" if r["triggered"] else "quiet  "
        print(f"  [{n}/{len(scripts)}] {r['id']:<40} {r['label']:5} {flag} risk {r['max_risk']:>5} "
              f"d2w={r['decisive_to_warning_s']} before_s5s6={r['caught_before_s5s6']}")
        path.write_text(json.dumps({"run_id": run_id, "split": a.split, "config": cfg, "metrics": compute(results),
                                    "finished": False, "results": results}, indent=1))
    out = {"run_id": run_id, "split": a.split, "config": cfg, "metrics": compute(results), "finished": True,
           "results": results}
    path.write_text(json.dumps(out, indent=1))
    (RESULTS / f"latest-{a.split}.json").write_text(json.dumps(out, indent=1))
    print(json.dumps(out["metrics"], indent=1))
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8000")
    ap.add_argument("--split", default="test", choices=["train", "test"])
    ap.add_argument("--run-id")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--ids", nargs="*")
    ap.add_argument("--min-gap", type=float, default=25.0)
    sys.exit(asyncio.run(main(ap.parse_args())))
