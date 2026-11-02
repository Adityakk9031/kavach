"""Voice samples recorded in the Kavach app by Papa and by the son, kept for making cloned voices.

AssemblyAI creates a voice clone only in its dashboard (there is no upload API), so Kavach stores the consented
sample here; the owner uploads that file in the dashboard once and tells Kavach the voice id (`/setvoice` in Telegram).
A sample is saved only with the speaker's recorded consent. Files live under `voices_dir`, never in git.
"""

import json
import re
import time
import wave
from pathlib import Path

import numpy as np

PEOPLE = ("papa", "son")
MIN_SECONDS, MAX_SECONDS = 10.0, 30.0
CONSENT_TEXT = ("I agree that Kavach may keep this recording of my voice and use it to make a cloned voice that speaks "
                "for me on calls to protect my family. I can ask for it to be deleted at any time.")


def _clean_name(name: str) -> str:
    return re.sub(r"[^\w .'-]", "", name).strip()[:40]


def save_sample(directory: str | Path, person: str, speaker_name: str, pcm: bytes, rate: int = 16000,
                consent: bool = False) -> dict:
    """Store one sample (signed 16-bit mono PCM) as a WAV plus a small JSON record. ValueError says why it was refused."""
    if person not in PEOPLE:
        raise ValueError("person must be papa or son")
    if not consent:
        raise ValueError("the speaker's consent is required")
    if len(pcm) % 2:
        pcm = pcm[:-1]
    seconds = len(pcm) / 2 / rate
    if seconds < MIN_SECONDS:
        raise ValueError(f"too short: {seconds:.0f} s recorded, at least {MIN_SECONDS:.0f} s needed")
    if seconds > MAX_SECONDS + 5:
        raise ValueError(f"too long: keep it under {MAX_SECONDS:.0f} s")
    samples = np.frombuffer(pcm, dtype="int16")
    if int(np.abs(samples).max(initial=0)) < 1500:
        raise ValueError("almost silent: speak closer to the microphone")
    pcm = pcm[: int(MAX_SECONDS * rate) * 2]  # the clone uses at most 30 s anyway
    root = Path(directory)
    root.mkdir(parents=True, exist_ok=True)
    with wave.open(str(root / f"{person}.wav"), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm)
    record = {"person": person, "speaker_name": _clean_name(speaker_name) or person.title(),
              "seconds": round(len(pcm) / 2 / rate, 1), "recorded_at": time.strftime("%Y-%m-%d %H:%M:%S"),
              "consent": True, "consent_text": CONSENT_TEXT}
    (root / f"{person}.json").write_text(json.dumps(record, indent=2))
    return record


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
    for ext in ("wav", "json"):
        p = Path(directory) / f"{person}.{ext}"
        if p.exists():
            p.unlink()
            found = True
    return found
