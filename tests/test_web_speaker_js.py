"""The Listener page's half-duplex rule: Kavach's own voice must never reach its transcription (run in Node)."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="needs node")


def run() -> dict:
    out = subprocess.run(["node", "tests/js/micgate.mjs"], capture_output=True, text=True, timeout=30,
                         cwd=Path(__file__).resolve().parent.parent)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout.strip().splitlines()[-1])


def test_microphone_is_silenced_while_the_persona_speaks_plus_a_short_echo_tail():
    r = run()
    assert r["idle"] is False  # normal listening: the scammer's voice goes through
    assert r["personaSpeaking"] is True
    assert r["tailJustAfter"] is True  # 300 ms after the persona stopped: the room still echoes
    assert r["tailOver"] is False


def test_the_warning_only_silences_the_microphone_when_it_shares_the_speaker():
    r = run()
    assert r["warningOnHeadphones"] is False  # headphones cannot leak into the microphone: keep listening
    assert r["warningOnSharedSpeaker"] is True
    assert r["afterSharedWarningTail"] is True and r["afterSharedWarningOpen"] is False


def test_silence_chunks_keep_their_length_and_are_all_zero():
    r = run()
    assert r["silenceBytes"] == 8 and r["silenceIsZero"] is True  # the stream stays continuous: STT needs it
