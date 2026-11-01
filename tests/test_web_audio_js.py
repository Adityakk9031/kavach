"""The browser player lowers the other party's voice while the family-voice warning plays (run in Node, fake audio)."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="needs node")


def run_player_script() -> dict:
    out = subprocess.run(["node", "tests/js/player_duck.mjs"], capture_output=True, text=True, timeout=30,
                         cwd=Path(__file__).resolve().parent.parent)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout.strip().splitlines()[-1])


def test_peer_volume_is_lowered_for_the_warning_and_restored_after():
    r = run_player_script()
    assert r["afterPeerOnly"] == 0  # the scammer alone is never turned down
    assert r["duckLevel"] == 0.25
    cancel, down, up = r["afterWarning"]
    assert cancel[0] == "cancel"
    assert down[:2] == ["target", 0.25] and down[2] == pytest.approx(10.0)  # turned down as the warning starts
    assert up[:2] == ["target", 1.0] and up[2] == pytest.approx(r["warningEnds"] + 0.1)  # back up after it ends


def test_restore_moves_later_when_more_warning_audio_arrives():
    r = run_player_script()
    assert r["warningEndsLater"] > r["warningEnds"]
    assert r["afterMore"][-1][1] == 1.0 and r["afterMore"][-1][2] == pytest.approx(r["warningEndsLater"] + 0.1)


def test_stopping_the_warning_restores_the_other_voice_immediately_and_only_for_the_warning():
    r = run_player_script()
    assert r["afterFlush"][-1][:2] == ["target", 1.0] and r["afterFlush"][-1][2] == pytest.approx(11.0)
    assert len(r["afterFlush"]) == 2
    assert r["afterOtherFlush"] == r["beforeOtherFlush"]  # flushing the persona's source left the peer's volume alone
