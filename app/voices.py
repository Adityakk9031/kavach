"""Voice samples recorded in the Kavach app by the parent and by the son, and the cloned voices made from them.

A sample is saved only with the speaker's recorded consent. Up to three takes are joined (a clone is clearer from a few
natural takes than from one) and capped at 30 s, which is all AssemblyAI uses. `clone_voice` then sends the sample to
AssemblyAI's voices endpoint (multipart: file, name, language, consent_attested, plus an Idempotency-Key) and returns the
new voice's id. Files live under `voices_dir/<family>/`, never in git.
"""

import asyncio
import io
import json
import re
import secrets
import time
import wave
from pathlib import Path

import httpx
import numpy as np

PEOPLE = ("papa", "son")
MIN_SECONDS, MAX_SECONDS = 10.0, 30.0
MIN_EXTRA_TAKE_SECONDS = 5.0
CONSENT_DAYS = 60  # AssemblyAI cloned voices must have their consent renewed every 60 days
CONSENT_TEXT = ("I agree that Kavach may keep this recording of my voice and use it to make a cloned voice that speaks "
                "for me on calls to protect my family. I can ask for it to be deleted at any time.")


def _clean_name(name: str) -> str:
    return re.sub(r"[^\w .'-]", "", name).strip()[:40]


def save_sample(directory: str | Path, person: str, speaker_name: str, pcm: bytes, rate: int = 16000,
                consent: bool = False, take: int = 1) -> dict:
    """Store one sample (signed 16-bit mono PCM) as a WAV plus a small JSON record. ValueError says why it was refused."""
    if person not in PEOPLE:
        raise ValueError("person must be papa or son")
    if not consent:
        raise ValueError("the speaker's consent is required")
    if len(pcm) % 2:
        pcm = pcm[:-1]
    seconds = len(pcm) / 2 / rate
    need = MIN_SECONDS if take == 1 else MIN_EXTRA_TAKE_SECONDS
    if take not in (1, 2, 3):
        raise ValueError("take must be 1, 2 or 3")
    if seconds < need:
        raise ValueError(f"too short: {seconds:.0f} s recorded, at least {need:.0f} s needed")
    if seconds > MAX_SECONDS + 5:
        raise ValueError(f"too long: keep it under {MAX_SECONDS:.0f} s")
    samples = np.frombuffer(pcm, dtype="int16")
    if int(np.abs(samples).max(initial=0)) < 1500:
        raise ValueError("almost silent: speak closer to the microphone")
    pcm = pcm[: int(MAX_SECONDS * rate) * 2]  # the clone uses at most 30 s anyway
    root = Path(directory)
    root.mkdir(parents=True, exist_ok=True)
    if take == 1:
        for old in root.glob(f"{person}.t*.wav"):
            old.unlink()
        _write_wav(root / f"{person}.wav", pcm, rate)
    else:
        _write_wav(root / f"{person}.t{take}.wav", pcm, rate)
        pcm = _joined(root, person, rate)
        _write_wav(root / f"{person}.wav", pcm, rate)
    record = {"person": person, "speaker_name": _clean_name(speaker_name) or person.title(),
              "seconds": round(len(pcm) / 2 / rate, 1), "takes": 1 + len(list(root.glob(f"{person}.t*.wav"))),
              "recorded_at": time.strftime("%Y-%m-%d %H:%M:%S"), "consent": True, "consent_text": CONSENT_TEXT}
    (root / f"{person}.json").write_text(json.dumps(record, indent=2))
    return record


def _write_wav(path: Path, pcm: bytes, rate: int) -> None:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm)


def _joined(root: Path, person: str, rate: int) -> bytes:
    """Take 1 followed by the other takes, with a short gap between them, cut to 30 s."""
    parts = [root / f"{person}.t{n}.wav" for n in (2, 3) if (root / f"{person}.t{n}.wav").exists()]
    first = root / f"{person}.t1.wav"
    first = first if first.exists() else root / f"{person}.wav"
    out = b""
    gap = b"\x00\x00" * int(rate * 0.25)
    for path in [first, *parts]:
        with wave.open(str(path)) as w:
            out += w.readframes(w.getnframes()) + gap
    return out[: int(MAX_SECONDS * rate) * 2]


def list_samples(directory: str | Path) -> dict:
    out = {}
    for person in PEOPLE:
        meta = Path(directory) / f"{person}.json"
        if meta.exists() and (Path(directory) / f"{person}.wav").exists():
            out[person] = json.loads(meta.read_text())
    return out


def delete_sample(directory: str | Path, person: str) -> bool:
    if person not in PEOPLE:
        return False
    found = False
    for p in [*Path(directory).glob(f"{person}.t*.wav"), *(Path(directory) / f"{person}.{e}" for e in ("wav", "json"))]:
        if p.exists():
            p.unlink()
            found = True
    return found


async def delete_remote_voice(settings, voice_id: str) -> bool:
    """Remove a cloned voice from AssemblyAI (consent withdrawn). Best effort: False if it was already gone."""
    base = settings.tts_http_url.rsplit("/", 1)[0]
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.delete(f"{base}/voices/{voice_id}", headers={"Authorization": settings.assemblyai_api_key})
    return r.status_code == 204


async def clone_voice(settings, wav_path: Path, label: str, language: str, client: httpx.AsyncClient | None = None) -> dict:
    """Make a cloned voice from a consented sample. Returns {"voice_id", "expires"} or raises RuntimeError with a reason
    that is safe to show. The caller has already recorded the speaker's consent (save_sample refuses without it)."""
    base = settings.tts_http_url.rsplit("/", 1)[0]  # https://tts.us.assemblyai.com/v1
    own = client is None
    client = client or httpx.AsyncClient(timeout=60)
    try:
        slug = f"kavach-{re.sub(r'[^a-z0-9]+', '-', label.lower()).strip('-')}-{secrets.token_hex(3)}"[:60]
        r = await client.post(f"{base}/voices", headers={"Authorization": settings.assemblyai_api_key, "Idempotency-Key": secrets.token_hex(16)},
                              files={"file": ("sample.wav", wav_path.read_bytes(), "audio/wav")},
                              data={"name": slug, "language": language, "consent_attested": "true"})
        body = r.json() if r.content else {}
        if r.status_code >= 300:
            raise RuntimeError(body.get("message") or f"the voice service answered {r.status_code}")
        voice_id = body.get("slug") or body.get("id")
        if not voice_id:
            raise RuntimeError("the voice service did not return a voice")
        for _ in range(20):  # a new voice is usually ready within seconds
            if "assemblyai-tts-1" in (body.get("ready_models") or []):
                break
            await asyncio.sleep(1.5)
            g = await client.get(f"{base}/voices/{body.get('id') or voice_id}", headers={"Authorization": settings.assemblyai_api_key})
            if g.status_code == 200:
                body = g.json()
        return {"voice_id": voice_id, "expires": time.time() + CONSENT_DAYS * 86400}
    finally:
        if own:
            await client.aclose()
