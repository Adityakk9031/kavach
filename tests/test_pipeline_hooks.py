"""Trigger hooks must be isolated: a slow or crashing hook cannot block the others or the next turn's detection."""

import asyncio
from types import SimpleNamespace

from app.call_room import CallRoom
from app.detector import Decision, RiskTracker
from app.pipeline import CallPipeline
from app.store import Store
from tests.test_tts_warner import NoStt


class StubDetector:
    def __init__(self):
        self.calls = 0

    def new_tracker(self):
        return RiskTracker(60)

    async def process(self, tracker, window):
        self.calls += 1
        trig = self.calls >= 1
        return Decision(95, 90.0, ["S1", "S6"], ["S1", "S6"], trig, "threshold", ["S1", "S6"]), \
            {"llm_ms": 5, "model": "stub", "rationale": "", "evidence_quotes": []}


def turn(i):
    return {"channel": "caller", "text": f"t{i}", "idx": i, "turn_id": i + 1, "audio_end_ms": 100 * i, "final_at": 0.0}


async def test_slow_hook_does_not_block_other_hooks_or_next_detection():
    room = CallRoom("h1", NoStt, Store(":memory:"))
    det = StubDetector()
    pipe = CallPipeline(room, det)
    done = []

    async def slow_warning(p, d, info):
        await asyncio.sleep(1.5)  # a warning that takes seconds to play
        done.append("warning")

    async def crashing(p, d, info):
        raise RuntimeError("tts down")

    async def alert(p, d, info):
        done.append("alert")

    pipe.on_trigger += [slow_warning, crashing, alert]
    await pipe.on_final(room, turn(0))
    await pipe.on_final(room, turn(2))  # the next turn arrives while the warning is still "playing"
    await asyncio.wait_for(pipe.queue.join(), 1.0)  # both turns analysed well before the slow hook finishes
    await asyncio.sleep(0.05)
    assert det.calls == 2 and done == ["alert"]  # alert not delayed behind the warning, crash did not stop it
    assert any(e["type"] == "hook_error" for e in room.store.events("h1"))
    await asyncio.sleep(1.6)
    assert done == ["alert", "warning"]
    await pipe.close()
