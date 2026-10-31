"""M2: risk math (offline) and the 10 fixed transcripts (live LLM, needs ASSEMBLYAI_API_KEY)."""

import json
import os

import pytest

from app.config import get_settings
from app.detector import Decision, Detection, Detector, RiskTracker, format_window
from app.llm import LLM, extract_json
from tests.fixtures.transcripts import LEGIT, SCAMS


def det(risk, stages=()):
    return Detection(stages=list(stages), risk=risk)


def test_risk_rises_fast():
    t = RiskTracker(threshold=70)
    d = t.update(det(90, ["S1"]))
    assert d.risk_cum == pytest.approx(63.0)  # 0 + 0.7 * 90
    d = t.update(det(90, ["S1", "S2"]))
    assert d.risk_cum == pytest.approx(81.9) and d.trigger and d.reason == "threshold"


def test_risk_decays_slowly_and_never_below_llm_score():
    t = RiskTracker()
    t.update(det(100))
    t.update(det(100))
    high = t.risk
    d = t.update(det(10))
    assert d.risk_cum == pytest.approx(high - 4.0)  # decays by 4, not collapsing to 10
    for _ in range(60):
        t.update(det(10))
    assert t.risk == 10  # floor is the current LLM score


def test_combo_rule_triggers_below_threshold():
    t = RiskTracker(threshold=95)
    assert not t.update(det(30, ["S1"])).trigger
    d = t.update(det(30, ["S5"]))  # S5 together with S1 seen earlier
    assert d.trigger and d.reason == "combo"


def test_pressure_or_action_alone_does_not_trigger_combo():
    t = RiskTracker(threshold=95)
    assert not t.update(det(20, ["S1", "S2", "S3", "S4"])).trigger
    t2 = RiskTracker(threshold=95)
    assert not t2.update(det(20, ["S5", "S6", "S7"])).trigger


def test_new_stages_reported_once():
    t = RiskTracker()
    assert t.update(det(10, ["S1"])).new_stages == ["S1"]
    assert t.update(det(10, ["S1", "S2"])).new_stages == ["S2"]


def test_detection_validation_cleans_model_noise():
    d = Detection.model_validate({"stages": ["s1", "S9", "S1", "x"], "risk": "87.6", "evidence_quotes": "ignored"[:0]})
    assert d.stages == ["S1"] and d.risk == 88
    assert Detection.model_validate({"risk": 250}).risk == 100
    assert Detection.model_validate({"risk": -5}).risk == 0


def test_extract_json_tolerates_fences_prose_and_truncation():
    assert extract_json('```json\n{"risk": 5, "stages": []}\n```')["risk"] == 5
    assert extract_json('Sure! Here you go: {"risk": 7, "stages": ["S1"],} thanks')["risk"] == 7
    assert extract_json('<think>hmm {x}</think>{"risk": 9}')["risk"] == 9
    assert extract_json('{"risk": 11, "stages": ["S1", "S2"')["stages"] == ["S1", "S2"]
    with pytest.raises(ValueError):
        extract_json("no json here")


def test_format_window_labels_speakers():
    out = format_window([{"channel": "caller", "text": "hi"}, {"channel": "receiver", "text": "yes"}])
    assert out == "CALLER: hi\nLISTENER: yes"


live = pytest.mark.skipif(not get_settings().assemblyai_api_key, reason="needs ASSEMBLYAI_API_KEY")


async def run_call(detector: Detector, turns):
    tracker = detector.new_tracker()
    seen, log = [], []
    for speaker, text in turns:
        seen.append({"channel": speaker, "text": text})
        if speaker != "caller":
            continue
        decision, info = await detector.process(tracker, seen)
        assert decision is not None, info
        log.append({"turn": len(seen), "stages": decision.stages_now, "risk_llm": decision.risk_llm,
                    "risk_cum": decision.risk_cum, "trigger": decision.trigger, "reason": decision.reason,
                    "llm_ms": info["llm_ms"], "model": info["model"]})
    return log


@live
@pytest.mark.parametrize("name", list(SCAMS))
async def test_scam_transcripts_trigger(name):
    llm = LLM(get_settings())
    try:
        log = await run_call(Detector(get_settings(), llm), SCAMS[name])
    finally:
        await llm.aclose()
    os.makedirs("data/m2", exist_ok=True)
    json.dump(log, open(f"data/m2/scam_{name}.json", "w"), indent=1)
    assert any(r["trigger"] for r in log), log


@live
@pytest.mark.parametrize("name", list(LEGIT))
async def test_legit_transcripts_do_not_trigger(name):
    llm = LLM(get_settings())
    try:
        log = await run_call(Detector(get_settings(), llm), LEGIT[name])
    finally:
        await llm.aclose()
    os.makedirs("data/m2", exist_ok=True)
    json.dump(log, open(f"data/m2/legit_{name}.json", "w"), indent=1)
    assert not any(r["trigger"] for r in log), log


async def test_rate_limiter_waits_when_window_is_full():
    import time as _t

    from app.llm import RateLimiter

    rl = RateLimiter(max_requests=2, max_tokens=10_000, window=0.3)
    t0 = _t.monotonic()
    for _ in range(3):
        await rl.acquire(100)
    assert _t.monotonic() - t0 >= 0.3  # third request had to wait for the window to slide


async def test_rate_limiter_counts_reserved_tokens():
    import time as _t

    from app.llm import RateLimiter

    rl = RateLimiter(max_requests=100, max_tokens=500, window=0.3)
    await rl.acquire(300)
    t0 = _t.monotonic()
    await rl.acquire(300)  # 600 > 500, must wait for the first to expire
    assert _t.monotonic() - t0 >= 0.25
