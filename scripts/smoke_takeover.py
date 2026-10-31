"""M5 live gate / demo caller: an LLM-driven scammer bot calls; the receiver hands over to Kavach; the persona keeps it talking.

    uv run uvicorn app.main:app --port 8000
    uv run python scripts/smoke_takeover.py --seconds 120

The bot plays the CALLER (spoken with TTS, streamed in real time on the caller socket) and reacts to what the persona
says. It carries planted details (UPI ID, account, IFSC, callback number, name, link) and reveals them only as a
scammer would when pushed. The receiver socket sends `takeover` after the bot's second line and `takeback` at the end.
PASS = at least 3 planted details show up in the server's validated evidence, the persona spoke only decoy-safe text,
and take-back unmuted the receiver and stopped persona audio quickly.

The bot reads the persona's text from the `persona` events (it does not run STT on the persona's audio); the persona
audio itself is still counted on the caller socket.
"""

import argparse
import asyncio
import contextlib
import json
import re
import sys
import time
from pathlib import Path

import httpx
import websockets

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.config import get_settings  # noqa: E402
from app.llm import LLM  # noqa: E402

S = get_settings()
SOURCE_PERSONA = 2
RATE = S.sample_rate
CHUNK = RATE * 2 // 20

FACTS = {
    "name": "Inspector Vikram Rathore",
    "agency": "Mumbai Cyber Crime Cell",
    "officer_id": "badge number four four seven one",
    "upi": "customs.clear@okbank",
    "account": "50100234567891",
    "ifsc": "HDFC0001234",
    "callback": "9820133456",
    "link": "www.rbi-verify.in",
}
# what to look for in the server's evidence (normalised comparison)
CHECKS = {
    "upi_id": ("upi", lambda v: "customs.clear@okbank" in v.lower().replace(" ", "")),
    "bank_account": ("account", lambda v: re.sub(r"\D", "", v).endswith("50100234567891")),
    "ifsc": ("ifsc", lambda v: v.upper().replace(" ", "") == "HDFC0001234"),
    "phone_number": ("callback", lambda v: re.sub(r"\D", "", v)[-10:] == "9820133456"),
    "person_name": ("name", lambda v: "rathore" in v.lower()),
    "url": ("link", lambda v: "rbi-verify" in v.lower()),
}

SYSTEM = f"""You are role-playing a phone SCAMMER for a safety test of a scam-protection product. The listener is an
elderly person. You pose as {FACTS['name']} of the {FACTS['agency']}. Story: a parcel in the listener's name carries
drugs; they must stay on the call, tell nobody, and pay a "refundable verification deposit" of fifty thousand rupees.
Your real details (reveal them naturally, one or two per turn, only when instructing payment or when the listener asks):
UPI ID {FACTS['upi']}; bank account {FACTS['account']} with IFSC {FACTS['ifsc']}; callback number {FACTS['callback']};
your {FACTS['officer_id']}; website {FACTS['link']}. If the listener asks you to repeat or spell something, do it
patiently once. Be pushy and impatient but keep it to one or two short spoken sentences. Plain spoken English, no
markdown or stage directions. Output only what you say."""

# Deterministic scammer for the gate (the brief's "scripted scammer"): the planted details are always spoken, so the
# gate measures what Kavach does with them (hold the call, stay safe, capture evidence, take back), not whether an
# LLM scammer happens to be cooperative. `--adaptive` uses an LLM scammer instead (variable, informational only).
SCRIPT_LINES = [
    "Mister Kumar, are you there? Please stay on the line, this is very serious.",
    "Listen carefully. Do not tell anyone about this call, not even your family, or officers will be sent to arrest you today.",
    f"To clear your name you must pay a refundable verification deposit of fifty thousand rupees. Use the UPI ID {FACTS['upi']}.",
    f"Or transfer to the HDFC bank account number {FACTS['account']}, IFSC code {FACTS['ifsc']}.",
    f"If the line drops, call me back on {FACTS['callback']}. I am {FACTS['name']}, and my badge number is 4471.",
    f"You can check your case file on the website {FACTS['link']}. Do it now, the arrest warrant goes out in one hour.",
    "Mister Kumar, I am waiting. Confirm that you have noted the UPI ID and the account number.",
    "Do not disconnect this call. Pay the deposit immediately, or I will have no choice but to proceed.",
]

OPENING = (f"Hello, am I speaking with Mister Ramesh Kumar? This is {FACTS['name']} from the {FACTS['agency']}. "
           "A parcel in your name was seized with illegal drugs and fake passports.")


async def tts(client: httpx.AsyncClient, text: str) -> bytes:
    r = await client.post(S.tts_http_url, headers={"Authorization": S.assemblyai_api_key}, json={
        "text": text, "voice_id": "aai-titus", "language": S.language, "container": "raw", "encoding": "pcm_s16le",
        "sample_rate": RATE, "stream": False})
    r.raise_for_status()
    return r.content


class Pump:
    """An open microphone: real-time 50 ms chunks forever, speech when there is some and digital silence otherwise.
    Streaming STT decides a turn is over from the audio it receives, so a line followed by NO audio never ends."""

    def __init__(self, ws):
        self.ws, self.q = ws, asyncio.Queue()
        self.task = asyncio.create_task(self._run())

    async def _run(self):
        t0, n, silence = time.monotonic(), 0, bytes(CHUNK)
        while True:
            await asyncio.sleep(max(0, t0 + n * 0.05 - time.monotonic()))
            try:
                chunk = self.q.get_nowait()
            except asyncio.QueueEmpty:
                chunk = silence
            await self.ws.send(chunk)
            n += 1

    async def say(self, pcm: bytes) -> None:
        for i in range(0, len(pcm), CHUNK):
            self.q.put_nowait(pcm[i:i + CHUNK].ljust(CHUNK, b"\x00"))
        while not self.q.empty():
            await asyncio.sleep(0.05)

    def stop(self):
        self.task.cancel()


class State:
    """Everything the readers and the scripted loop share."""

    def __init__(self):
        self.persona_texts: list[str] = []
        self.speaking = False
        self.done_at = 0.0
        self.persona_frames = 0
        self.frames_after_takeback = 0
        self.peer_frames_after_takeback = 0
        self.marks: dict = {}
        self.pre_takeback_speaking = None
        self.pump = None


async def caller_reader(ws, st: State):
    async for raw in ws:
        if isinstance(raw, bytes):
            if raw[0] == SOURCE_PERSONA:
                st.persona_frames += 1
                if "takeback_sent" in st.marks and time.monotonic() > st.marks["takeback_sent"] + 0.4:
                    st.frames_after_takeback += 1
            elif raw[0] == 0 and "takeback_sent" in st.marks:
                st.peer_frames_after_takeback += 1
            continue
        ev = json.loads(raw)
        if ev["type"] == "persona":
            if ev.get("text"):
                st.persona_texts.append(ev["text"])
                st.speaking = True
                print(f"  [persona] {ev['text']}")
            elif ev["state"] == "done":
                st.speaking = False
                st.done_at = time.monotonic()
        elif ev["type"] == "takeover" and ev["state"] == "off":
            st.marks["takeback_event"] = time.monotonic()


async def drain(ws):
    async for _ in ws:
        pass


async def scammer_loop(a, caller, receiver, client, llm, st: State) -> int:
    pump = Pump(caller)
    """Speak, wait for the persona (if the receiver handed over), let the LLM scammer answer, repeat."""
    history: list[dict] = []
    line, turn, t_start = OPENING, 0, time.monotonic()
    while time.monotonic() - t_start < a.seconds:
        print(f"[scammer {turn}] {line}")
        history.append({"role": "assistant", "content": line})
        await pump.say(await tts(client, line))
        if receiver is not None and turn == 1:  # scripted run: the "user" hands over after the second scammer line
            await receiver.send(json.dumps({"type": "takeover"}))
        turn += 1
        if a.demo:
            await asyncio.sleep(7)  # time for the warning to play and for the human to react / hand over
            heard = st.persona_texts[-1] if st.persona_texts else "(the listener says nothing)"
        elif turn <= 1:
            await asyncio.sleep(1.5)
            line = SCRIPT_LINES[0]
            continue
        else:
            t_wait = time.monotonic()
            while time.monotonic() - t_wait < 22:  # bounded wait for the persona to answer and finish
                await asyncio.sleep(0.2)
                if len(st.persona_texts) >= turn - 1 and not st.speaking and st.done_at > t_wait:
                    break
            heard = st.persona_texts[-1] if st.persona_texts else "(silence)"
        history.append({"role": "user", "content": heard})
        if a.demo or a.adaptive:
            line, _ = await llm.chat(S.script_gen_model, [{"role": "system", "content": SYSTEM}] + history[-14:],
                                     max_tokens=120, temperature=0.8, timeout=40)
            line = line.strip().strip('"')
        else:
            if turn - 1 >= len(SCRIPT_LINES):
                break  # the script is finished
            line = SCRIPT_LINES[turn - 1]
    st.pump = pump
    return turn


async def main(a) -> int:
    if not S.assemblyai_api_key:
        print("no ASSEMBLYAI_API_KEY")
        return 2
    ws_base = a.base.replace("http", "ws", 1)
    st = State()
    llm = LLM(S)
    t_start = time.monotonic()
    # --demo is a real call (mode=live, family alerts go out) and a human is the receiver; otherwise it is a test.
    mode = "live" if (a.demo or a.live_alerts) else "eval"
    async with contextlib.AsyncExitStack() as stack:
        client = await stack.enter_async_context(httpx.AsyncClient(timeout=60))
        caller = await stack.enter_async_context(
            websockets.connect(f"{ws_base}/ws/call/{a.call_id}/caller?mode={mode}&caller_number=%2B919820133456"))
        receiver = None if a.demo else await stack.enter_async_context(
            websockets.connect(f"{ws_base}/ws/call/{a.call_id}/receiver?mode={mode}"))
        tasks = [asyncio.create_task(caller_reader(caller, st))] + ([asyncio.create_task(drain(receiver))] if receiver else [])
        await asyncio.sleep(2.5)
        turns = await scammer_loop(a, caller, receiver, client, llm, st)
        if a.demo:
            await caller.send(json.dumps({"type": "end_call"}))
            await asyncio.sleep(3)
        else:
            # One more scammer line, then take back the moment the persona starts to answer (mid-sentence).
            await st.pump.say(await tts(client, "Hello? Mister Kumar? Do you understand what I am saying? Answer me now."))
            t_w = time.monotonic()
            while not st.speaking and time.monotonic() - t_w < 20:
                await asyncio.sleep(0.02)
            await asyncio.sleep(0.6)  # let it get a few words in
            st.pre_takeback_speaking = st.speaking
            await receiver.send(json.dumps({"type": "takeback"}))
            st.marks["takeback_sent"] = time.monotonic()
            await asyncio.sleep(1.0)
            await receiver.send(b"\x01\x00" * 1600)  # the user's voice must now reach the caller
            await asyncio.sleep(1.0)
            await caller.send(json.dumps({"type": "end_call"}))
            await asyncio.sleep(6)
        if st.pump:
            st.pump.stop()
        for t in tasks:
            t.cancel()
    await llm.aclose()
    if a.demo:
        print("demo call finished")
        return 0
    return await grade(a, st, turns, t_start)


async def grade(a, st: State, turns: int, t_start: float) -> int:
    async with httpx.AsyncClient(timeout=20) as client:
        evidence = (await client.get(f"{a.base}/api/calls/{a.call_id}/evidence")).json()
        events = (await client.get(f"{a.base}/api/calls/{a.call_id}/events")).json()
        call_turns = (await client.get(f"{a.base}/api/calls/{a.call_id}/turns")).json()
    found = {}
    for kind, (label, ok) in CHECKS.items():
        hit = [e for e in evidence if e["type"] == kind and ok(e["value"])]
        if hit:
            found[label] = hit[0]["value"]
    ev_by: dict = {}
    for e in events:
        ev_by.setdefault(e["type"], []).append(e["payload"])
    takeback = (ev_by.get("takeback") or [{}])[0]
    persona_turns = [t for t in call_turns if t["channel"] == "persona"]
    unsafe = [t["text"] for t in persona_turns if re.search(r"\d|@|http|www", t["text"])]
    first_audio = [p.get("turn_end_to_audio_ms") for p in ev_by.get("persona_first_audio", []) if p.get("turn_end_to_audio_ms")]
    result = {
        "call_id": a.call_id, "seconds": round(time.monotonic() - t_start), "scammer_turns": turns,
        "persona_replies": len(persona_turns), "persona_audio_frames_heard_by_caller": st.persona_frames,
        "planted_details_found_in_evidence": found, "n_found": len(found), "of": len(CHECKS),
        "all_valid_evidence": [(e["type"], e["value"]) for e in evidence],
        "persona_guard_replacements": len(ev_by.get("persona_guard", [])),
        "persona_turns_flagged_decoy_in_db": all(t["is_decoy"] == 1 for t in persona_turns),
        "persona_lines_with_digits_or_addresses": unsafe,
        "persona_reply_after_caller_stops_ms": {"median": sorted(first_audio)[len(first_audio) // 2] if first_audio else None,
                                                "n": len(first_audio)},
        "takeback": {"persona_was_speaking": st.pre_takeback_speaking, "server_ms": takeback.get("total_ms"),
                     "cancel_sent_ms": takeback.get("cancel_sent_ms"),
                     "persona_frames_after_400ms": st.frames_after_takeback,
                     "receiver_voice_reached_caller_frames": st.peer_frames_after_takeback,
                     "ui_state_off_event": "takeback_event" in st.marks},
        "stt_incidents": len(ev_by.get("stt_closed", [])) + len(ev_by.get("stt_error", [])),
    }
    out = Path("data/takeover")
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{a.call_id}.json").write_text(json.dumps({**result, "persona_texts": st.persona_texts,
                                                      "transcript": [(t["channel"], t["text"]) for t in call_turns]}, indent=1))
    print(json.dumps(result, indent=1))
    ok = (len(found) >= 3 and not unsafe and result["persona_turns_flagged_decoy_in_db"]
          and st.frames_after_takeback == 0 and st.peer_frames_after_takeback > 0 and "takeback_event" in st.marks
          and takeback.get("total_ms") is not None and takeback["total_ms"] < 500 and len(persona_turns) >= 4
          and bool(st.pre_takeback_speaking))
    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8000")
    ap.add_argument("--call-id", default=f"takeover-{int(time.time())}")
    ap.add_argument("--seconds", type=int, default=120)
    ap.add_argument("--live-alerts", action="store_true",
                    help="scripted run as a REAL call: the family gets the Telegram alerts and the call-end PDF")
    ap.add_argument("--adaptive", action="store_true",
                    help="LLM-driven scammer instead of the fixed script (variable; informational, not the gate)")
    ap.add_argument("--demo", action="store_true",
                    help="caller only: a human plays the protected person in the Receiver tab (same --call-id) and "
                         "clicks Hand over / Take back; real call, so family alerts are sent")
    sys.exit(asyncio.run(main(ap.parse_args())))
