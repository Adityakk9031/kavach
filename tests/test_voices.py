"""Voice samples recorded in the app: only with consent, only 10-30 s, only audible; kept off the public pages."""

import wave

import numpy as np
import pytest
from fastapi.testclient import TestClient

import app.main as main
from app import voices


def pcm(seconds: float, amp: int = 8000, rate: int = 16000) -> bytes:
    t = np.arange(int(seconds * rate)) / rate
    return (amp * np.sin(2 * np.pi * 180 * t)).astype("int16").tobytes()


def test_a_consented_sample_is_stored_as_wav_with_its_consent_record(tmp_path):
    rec = voices.save_sample(tmp_path, "papa", "Ramesh <b>Kumar</b>", pcm(12), consent=True)
    assert rec["seconds"] == 12.0 and rec["consent"] is True and rec["speaker_name"] == "Ramesh bKumarb"
    with wave.open(str(tmp_path / "papa.wav")) as w:
        assert (w.getnchannels(), w.getsampwidth(), w.getframerate()) == (1, 2, 16000)
        assert w.getnframes() == 12 * 16000
    assert voices.list_samples(tmp_path)["papa"]["consent_text"] == voices.CONSENT_TEXT
    assert voices.delete_sample(tmp_path, "papa") and voices.list_samples(tmp_path) == {}


@pytest.mark.parametrize("person,audio,consent,why", [
    ("papa", pcm(12), False, "consent"),
    ("stranger", pcm(12), True, "papa or son"),
    ("son", pcm(4), True, "too short"),
    ("son", pcm(50), True, "too long"),
    ("son", pcm(12, amp=100), True, "silent"),
])
def test_bad_samples_are_refused_and_nothing_is_written(tmp_path, person, audio, consent, why):
    with pytest.raises(ValueError, match=why):
        voices.save_sample(tmp_path, person, "x", audio, consent=consent)
    assert list(tmp_path.iterdir()) == []


def test_a_slightly_long_recording_is_cut_to_30_seconds(tmp_path):
    rec = voices.save_sample(tmp_path, "son", "Aman", pcm(33), consent=True)
    assert rec["seconds"] == 30.0


def test_the_api_needs_the_key_consent_and_a_real_sample(tmp_path, monkeypatch):
    s = main.get_settings()
    monkeypatch.setattr(s, "voices_dir", str(tmp_path))
    monkeypatch.setattr(main.settings, "kavach_access_key", "k3y")
    with TestClient(main.app) as c:
        h = {"x-kavach-key": "k3y"}
        assert c.post("/api/voices/papa", content=pcm(12)).status_code == 401
        assert c.post("/api/voices/papa?name=Papa", content=pcm(12), headers=h).status_code == 400  # no consent
        ok = c.post("/api/voices/papa?name=Papa", content=pcm(12), headers={**h, "x-kavach-consent": "yes"})
        assert ok.status_code == 200 and ok.json()["seconds"] == 12.0
        assert c.post("/api/voices/son", content=pcm(2), headers={**h, "x-kavach-consent": "yes"}).status_code == 400
        listing = c.get("/api/voices", headers=h).json()
        assert list(listing["samples"]) == ["papa"] and listing["min_seconds"] == 10
        wav = c.get("/api/voices/papa.wav", headers=h)
        assert wav.status_code == 200 and wav.content[:4] == b"RIFF"
        assert c.get("/api/voices/papa.wav").status_code == 401
        assert c.get("/api/voices/son.wav", headers=h).status_code == 404
        assert c.delete("/api/voices/papa", headers=h).json() == {"deleted": True}
