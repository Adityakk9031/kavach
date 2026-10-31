"""Render eval scripts to two-voice audio with TTS-1.

    uv run python -m eval.render_audio --split test

One long-lived TTS WebSocket session per voice (the free plan allows 5 new sessions a minute), turns rendered
one after another. Output per script in eval/audio/: `<id>.wav` (16 kHz mono, both speakers mixed in time order)
and `<id>.timing.json` (per-turn start/end in ms on the call's timeline). The runner rebuilds each party's channel
from these two files, so the backend sees exactly what two separate microphones would send.
"""

import argparse
import asyncio
import json
import random
import sys
import time
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.config import get_settings  # noqa: E402
from app.tts import TtsSession  # noqa: E402

HERE = Path(__file__).resolve().parent
SCRIPTS, AUDIO = HERE / "scripts", HERE / "audio"

# Library English voices; no Indian-accent voice appears in the starter list, so accents are mixed.
CALLER_VOICES = ["aai-titus", "aai-buford", "aai-steven", "aai-peter", "aai-ewald", "aai-troy"]
RECEIVER_VOICES = ["aai-audrey", "aai-sara", "aai-gunnar", "aai-nancy", "aai-carrie", "aai-abdiel"]


class SessionOpener:
    """Opens at most `per_minute` new TTS sessions per rolling minute and keeps them for reuse."""

    def __init__(self, settings, per_minute: int = 4):
        self.settings, self.per_minute = settings, per_minute
        self.sessions: dict[str, TtsSession] = {}
        self.opened: list[float] = []

    async def get(self, voice: str) -> TtsSession:
        s = self.sessions.get(voice)
        if s and s.connected:
            return s
        while True:
            now = time.monotonic()
            self.opened = [t for t in self.opened if now - t < 60]
            if len(self.opened) < self.per_minute:
                break
            await asyncio.sleep(60 - (now - self.opened[0]) + 0.5)
        self.opened.append(time.monotonic())
        s = TtsSession(self.settings, voice, label=voice)
        await s.start()
        self.sessions[voice] = s
        return s

    async def close(self):
        await asyncio.gather(*(s.close() for s in self.sessions.values()), return_exceptions=True)


async def speak(opener: SessionOpener, voice: str, text: str) -> bytes:
    for attempt in range(3):
        session = await opener.get(voice)
        chunks: list[bytes] = []

        async def on_audio(pcm: bytes):
            chunks.append(pcm)

        try:
            req = await session.speak(text, on_audio)
            await asyncio.wait_for(req.done.wait(), 60)
        except Exception as e:
            print(f"    retry {attempt + 1} ({voice}): {e}")
            opener.sessions.pop(voice, None)
            continue
        if chunks and session.connected:
            return b"".join(chunks)
        opener.sessions.pop(voice, None)
    raise RuntimeError(f"could not render turn with {voice}: {text[:60]}")


def silence(ms: int, rate: int) -> bytes:
    return bytes(int(rate * ms / 1000) * 2)


async def render(script: dict, opener: SessionOpener, rate: int) -> dict:
    rng = random.Random(script["id"])
    voices = {"caller": rng.choice(CALLER_VOICES), "receiver": rng.choice(RECEIVER_VOICES)}
    pcm = bytearray(silence(300, rate))
    timing = []
    for i, turn in enumerate(script["turns"]):
        audio = await speak(opener, voices[turn["speaker"]], turn["text"])
        start = len(pcm) / 2 / rate * 1000
        pcm += audio
        end = len(pcm) / 2 / rate * 1000
        timing.append({"i": i, "speaker": turn["speaker"], "voice": voices[turn["speaker"]], "text": turn["text"],
                       "start_ms": round(start), "end_ms": round(end)})
        pcm += silence(rng.randint(600, 1200), rate)  # natural gap between turns
    pcm += silence(500, rate)
    wav_path = AUDIO / f"{script['id']}.wav"
    with wave.open(str(wav_path), "wb") as w:
        w.setnchannels(1), w.setsampwidth(2), w.setframerate(rate), w.writeframes(bytes(pcm))
    meta = {"id": script["id"], "sample_rate": rate, "duration_s": round(len(pcm) / 2 / rate, 2), "voices": voices,
            "turns": timing}
    (AUDIO / f"{script['id']}.timing.json").write_text(json.dumps(meta, indent=1))
    return meta


async def main(split: str, limit: int | None) -> None:
    S = get_settings()
    AUDIO.mkdir(exist_ok=True)
    scripts = [json.loads(p.read_text()) for p in sorted(SCRIPTS.glob("*.json"))]
    scripts = [s for s in scripts if split == "all" or s["split"] == split]
    todo = [s for s in scripts if not (AUDIO / f"{s['id']}.timing.json").exists()]
    if limit:
        todo = todo[:limit]
    chars = sum(len(t["text"]) for s in todo for t in s["turns"])
    print(f"{len(scripts)} scripts in split '{split}', rendering {len(todo)} ({chars} chars, ~${chars * 15 / 1e6:.2f})")
    opener = SessionOpener(S)
    try:
        for n, script in enumerate(todo, 1):
            t0 = time.monotonic()
            meta = await render(script, opener, S.sample_rate)
            print(f"  [{n}/{len(todo)}] {script['id']}: {meta['duration_s']} s audio in {time.monotonic() - t0:.1f} s")
    finally:
        await opener.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", default="test", choices=["train", "test", "all"])
    ap.add_argument("--limit", type=int)
    a = ap.parse_args()
    asyncio.run(main(a.split, a.limit))
