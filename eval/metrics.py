"""Eval metrics. Pure functions over per-call result dicts (see eval/run_eval.py for the fields)."""

import statistics


def percentile(values: list[float], p: float) -> float | None:
    if not values:
        return None
    v = sorted(values)
    k = (len(v) - 1) * p
    lo, hi = int(k), min(int(k) + 1, len(v) - 1)
    return v[lo] + (v[hi] - v[lo]) * (k - lo)


def rate(num: int, den: int) -> float | None:
    return None if den == 0 else num / den


def compute(results: list[dict]) -> dict:
    scams = [r for r in results if r["label"] == "scam"]
    legit = [r for r in results if r["category"] == "legit"]
    hard = [r for r in results if r["category"] == "hard_negative"]
    negatives = legit + hard
    caught = [r for r in scams if r["triggered"]]
    with_warning = [r for r in caught if r.get("decisive_to_warning_s") is not None]
    d2w = [r["decisive_to_warning_s"] for r in with_warning]
    ttfa = [r["tts_ttfa_ms"] for r in caught if r.get("tts_ttfa_ms") is not None]
    t2a = [r["turn_end_to_audio_ms"] for r in caught if r.get("turn_end_to_audio_ms") is not None]
    asked = [r for r in scams if r.get("first_s5_s6_turn_index") is not None]
    before = [r for r in asked if r["triggered"] and r.get("caught_before_s5s6")]
    tp, fn = len(caught), len(scams) - len(caught)
    fp = sum(r["triggered"] for r in negatives)
    tn = len(negatives) - fp
    return {
        "n_calls": len(results), "n_scam": len(scams), "n_legit": len(legit), "n_hard_negative": len(hard),
        "recall": rate(tp, len(scams)),
        "fpr_legit": rate(sum(r["triggered"] for r in legit), len(legit)),
        "fpr_hard_negative": rate(sum(r["triggered"] for r in hard), len(hard)),
        "fpr_all_negatives": rate(fp, len(negatives)),
        "precision": rate(tp, tp + fp),
        "decisive_to_warning_s": {"n": len(d2w), "median": statistics.median(d2w) if d2w else None,
                                  "p90": percentile(d2w, 0.9),
                                  "pct_warned_before_decisive_turn_ended": rate(sum(x < 0 for x in d2w), len(d2w))},
        "turn_end_to_warning_audio_ms": {"n": len(t2a), "median": statistics.median(t2a) if t2a else None,
                                         "p90": percentile(t2a, 0.9)},
        "warning_tts_first_audio_ms_median": statistics.median(ttfa) if ttfa else None,
        "pct_caught_before_s5_s6": rate(len(before), len(asked)),
        "n_scams_with_s5_s6": len(asked),
        "confusion": {"tp": tp, "fn": fn, "fp": fp, "tn": tn},
        "by_scam_type": {t: {"n": sum(1 for r in scams if r["scam_type"] == t),
                             "caught": sum(1 for r in scams if r["scam_type"] == t and r["triggered"])}
                         for t in sorted({r["scam_type"] for r in scams})},
        "warned_without_audio": sum(1 for r in caught if r.get("decisive_to_warning_s") is None),
    }
