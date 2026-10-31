"""M4 offline: metrics math, scoring a call from events, dataset schema/split rules."""

import json
from pathlib import Path

import pytest

from eval.generate_scripts import Draft, build_plan
from eval.metrics import compute, percentile
from eval.run_eval import score


def r(**kw):
    base = {"id": "x", "label": "scam", "category": "scam", "scam_type": "digital_arrest", "triggered": True,
            "decisive_to_warning_s": 2.0, "tts_ttfa_ms": 400, "turn_end_to_audio_ms": 1500,
            "first_s5_s6_turn_index": 8, "caught_before_s5s6": True}
    return {**base, **kw}


def test_percentile_interpolates():
    assert percentile([1, 2, 3, 4, 5], 0.5) == 3
    assert percentile([1, 2, 3, 4, 5], 0.9) == pytest.approx(4.6)
    assert percentile([], 0.5) is None


def test_metrics_confusion_and_rates():
    results = [
        r(id="a"), r(id="b", decisive_to_warning_s=-1.0), r(id="c", triggered=False, decisive_to_warning_s=None,
                                                             tts_ttfa_ms=None, turn_end_to_audio_ms=None,
                                                             caught_before_s5s6=None),
        r(id="d", decisive_to_warning_s=5.0, caught_before_s5s6=False),
        r(id="l1", label="legit", category="legit", scam_type=None, triggered=False, decisive_to_warning_s=None),
        r(id="l2", label="legit", category="legit", scam_type=None, triggered=True, decisive_to_warning_s=None),
        r(id="h1", label="legit", category="hard_negative", scam_type=None, triggered=False, decisive_to_warning_s=None),
        r(id="h2", label="legit", category="hard_negative", scam_type=None, triggered=False, decisive_to_warning_s=None),
    ]
    m = compute(results)
    assert m["confusion"] == {"tp": 3, "fn": 1, "fp": 1, "tn": 3}
    assert m["recall"] == 0.75
    assert m["fpr_legit"] == 0.5 and m["fpr_hard_negative"] == 0.0 and m["fpr_all_negatives"] == 0.25
    assert m["decisive_to_warning_s"]["median"] == 2.0 and m["decisive_to_warning_s"]["n"] == 3
    assert m["decisive_to_warning_s"]["pct_warned_before_decisive_turn_ended"] == pytest.approx(1 / 3)
    assert m["pct_caught_before_s5_s6"] == pytest.approx(2 / 4)  # a, b before; c missed; d late
    assert m["warning_tts_first_audio_ms_median"] == 400


def test_metrics_handle_empty_groups():
    m = compute([r()])
    assert m["fpr_legit"] is None and m["fpr_hard_negative"] is None and m["recall"] == 1.0


SCRIPT = {"id": "s", "label": "scam", "category": "scam", "scam_type": "digital_arrest", "subtype": "digital_arrest",
          "split": "test", "decisive_turn_index": 4, "first_s5_s6_turn_index": 8}
TIMING = {"turns": [{"i": i, "speaker": "caller" if i % 2 == 0 else "receiver", "start_ms": i * 5000,
                     "end_ms": i * 5000 + 4000} for i in range(10)]}


def test_score_maps_trigger_to_script_turn_and_times():
    events = [
        {"type": "detect", "payload": {"turn_idx": 2, "stages_all": ["S1"], "risk_llm": 80, "risk_cum": 56, "llm_ms": 700, "trigger": False}},
        {"type": "detect", "payload": {"turn_idx": 4, "stages_all": ["S1", "S3"], "risk_llm": 95, "risk_cum": 80, "llm_ms": 700, "trigger": True}},
        {"type": "trigger", "payload": {"turn_idx": 4, "reason": "threshold"}},
        {"type": "warn_first_audio", "payload": {"ttfa_ms": 400, "turn_end_to_audio_ms": 1600}},
        {"type": "warn_tts_sent", "payload": {"cloned": True}},
    ]
    # room turn idx counts finals from both channels; caller turn idx 4 is the STT final whose audio ended ~24 s
    turns = [{"channel": "caller", "idx": 4, "audio_end_ms": 24100, "text": "x", "stt_latency_ms": 400}]
    marks = {"t0": 100.0, "first_warning": 127.0, "ended_at": 129.0}
    out = score(SCRIPT, TIMING, marks, events, turns, ["speaking"])
    assert out["triggered"] and out["trigger_script_turn"] == 4  # nearest caller turn end (24000 ms)
    assert out["caught_before_s5s6"] is True  # turn 4 < first ask at turn 8
    assert out["decisive_end_s"] == 24.0 and out["warning_first_audio_s"] == 27.0
    assert out["decisive_to_warning_s"] == 3.0
    assert out["max_risk"] == 80 and out["tts_ttfa_ms"] == 400


def test_score_untriggered_call():
    out = score({**SCRIPT, "label": "legit", "category": "legit", "scam_type": None, "decisive_turn_index": None,
                 "first_s5_s6_turn_index": None}, TIMING, {"t0": 0.0, "ended_at": 60.0}, [], [], [])
    assert out["triggered"] is False and out["decisive_to_warning_s"] is None and out["caught_before_s5s6"] is None


def test_draft_validation_rules():
    turns = lambda n: [{"speaker": "caller" if i % 2 == 0 else "receiver", "text": f"line {i} here"} for i in range(n)]
    Draft.model_validate({"turns": turns(8), "decisive_turn_index": 4})
    with pytest.raises(ValueError):
        Draft.model_validate({"turns": turns(4)})  # too short
    with pytest.raises(ValueError):
        Draft.model_validate({"turns": turns(8), "decisive_turn_index": 3})  # receiver turn
    bad = turns(8)
    bad[1]["speaker"] = "caller"
    with pytest.raises(ValueError):
        Draft.model_validate({"turns": bad})  # not alternating
    bad = turns(8)
    bad[2]["text"] = "(laughs) hello there"
    with pytest.raises(ValueError):
        Draft.model_validate({"turns": bad})  # stage directions


def test_plan_composition_and_split():
    plan = build_plan()
    cats = {c: sum(1 for p in plan if p["category"] == c) for c in ("scam", "legit", "hard_negative")}
    assert cats == {"scam": 45, "legit": 30, "hard_negative": 15}
    test = {c: sum(1 for p in plan if p["category"] == c and p["split"] == "test") for c in cats}
    assert test == {"scam": 18, "legit": 12, "hard_negative": 6}  # exactly 40% of each category
    assert {p["subtype"] for p in plan if p["split"] == "test"} == {p["subtype"] for p in plan}  # every type in test
    assert len({p["id"] for p in plan}) == 90


@pytest.mark.skipif(not list(Path("eval/scripts").glob("*.json")), reason="scripts not generated yet")
def test_generated_scripts_are_valid_and_consistent():
    for p in Path("eval/scripts").glob("*.json"):
        s = json.loads(p.read_text())
        Draft.model_validate({"turns": s["turns"], "decisive_turn_index": s["decisive_turn_index"],
                              "first_s5_s6_turn_index": s["first_s5_s6_turn_index"]})
        if s["label"] == "scam":
            assert s["decisive_turn_index"] is not None, p.name
            if s["first_s5_s6_turn_index"] is not None:
                assert s["decisive_turn_index"] <= s["first_s5_s6_turn_index"], p.name
        else:
            assert s["decisive_turn_index"] is None and s["first_s5_s6_turn_index"] is None, p.name
        assert s["split"] in ("train", "test")
