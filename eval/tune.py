"""Tune the risk threshold on the TRAIN split only, without touching the test split.

    uv run python -m eval.tune collect     # run the detector over train scripts' text (LLM), cache per-turn output
    uv run python -m eval.tune sweep       # offline: try thresholds / rise / decay / combo rule on the cache

`collect` replays each train script's own text turn by turn, exactly as the pipeline would see it, and stores the
LLM's per-turn stages and risk. `sweep` then re-runs only the cumulative-risk math, which is pure and instant, so the
choice of threshold needs no further LLM calls. Train text is used directly (not re-transcribed): STT word match was
0.976 in M1, and test-split numbers, which do go through real STT, are the ones reported.
"""

import argparse
import asyncio
import itertools
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.config import get_settings  # noqa: E402
from app.detector import ACTION, PRESSURE, Detection, Detector, RiskTracker  # noqa: E402
from app.llm import LLM  # noqa: E402

HERE = Path(__file__).resolve().parent
CACHE = HERE / "results" / "train_detections.json"


async def collect(limit: int | None, concurrency: int) -> None:
    S = get_settings()
    scripts = [json.loads(p.read_text()) for p in sorted((HERE / "scripts").glob("*.json"))]
    scripts = [s for s in scripts if s["split"] == "train"]
    if limit:
        scripts = scripts[:limit]
    cache = json.loads(CACHE.read_text()) if CACHE.exists() else {}
    todo = [s for s in scripts if s["id"] not in cache or cache[s["id"]].get("prompt") != PROMPT_VERSION]
    print(f"{len(scripts)} train scripts, {len(todo)} to collect, detector {S.detector_model}")
    llm = LLM(S)
    det = Detector(S, llm)
    sem = asyncio.Semaphore(concurrency)

    async def one(script):
        async with sem:
            tracker = det.new_tracker()  # only used for its API; per-turn raw output is what we cache
            window, rows = [], []
            for i, t in enumerate(script["turns"]):
                window.append({"channel": t["speaker"], "text": t["text"]})
                if t["speaker"] != "caller":
                    continue
                try:
                    d, ms, model = await det.analyse(window[-S.detector_window_turns:])
                    rows.append({"turn": i, "stages": d.stages, "risk": d.risk, "quotes": d.evidence_quotes,
                                 "rationale": d.rationale, "llm_ms": ms, "model": model})
                except Exception as e:
                    rows.append({"turn": i, "error": str(e)})
            cache[script["id"]] = {"prompt": PROMPT_VERSION, "rows": rows}
            CACHE.write_text(json.dumps(cache, indent=1))
            errs = sum(1 for r in rows if "error" in r)
            print(f"  {script['id']}: {len(rows)} turns{f', {errs} ERRORS' if errs else ''}")

    try:
        await asyncio.gather(*(one(s) for s in todo))
    finally:
        await llm.aclose()


def prompt_version() -> str:
    import hashlib

    from app.detector import SYSTEM_PROMPT
    return hashlib.sha1(SYSTEM_PROMPT.encode()).hexdigest()[:8]


PROMPT_VERSION = prompt_version()


def simulate(script: dict, rows: list[dict], threshold: int, rise: float, decay: float, combo: bool) -> dict:
    t = RiskTracker(threshold, rise, decay)
    for r in rows:
        if "error" in r:
            continue
        d = t.update(Detection(stages=r["stages"], risk=r["risk"]))
        trig = d.trigger and (combo or d.reason == "threshold")
        if trig:
            return {"triggered": True, "turn": r["turn"], "reason": d.reason}
    return {"triggered": False, "turn": None, "reason": None}


def evaluate(scripts: list[dict], cache: dict, **params) -> dict:
    out = {"scam": [], "legit": [], "hard_negative": []}
    for s in scripts:
        if s["id"] not in cache:
            continue
        out[s["category"]].append((s, simulate(s, cache[s["id"]]["rows"], **params)))
    sc = out["scam"]
    caught = [(s, r) for s, r in sc if r["triggered"]]
    asked = [(s, r) for s, r in sc if s["first_s5_s6_turn_index"] is not None]
    before = [1 for s, r in asked if r["triggered"] and r["turn"] < s["first_s5_s6_turn_index"]]
    gaps = sorted(r["turn"] - s["decisive_turn_index"] for s, r in caught)
    fp = lambda g: sum(r["triggered"] for _, r in out[g])  # noqa: E731
    return {"recall": len(caught) / len(sc) if sc else None, "n_scam": len(sc),
            "fp_legit": fp("legit"), "n_legit": len(out["legit"]),
            "fp_hard": fp("hard_negative"), "n_hard": len(out["hard_negative"]),
            "before_ask": len(before) / len(asked) if asked else None,
            "median_turns_after_decisive": gaps[len(gaps) // 2] if gaps else None,
            "early": sum(1 for g in gaps if g < 0)}


def sweep() -> dict:
    cache = json.loads(CACHE.read_text())
    scripts = [json.loads(p.read_text()) for p in sorted((HERE / "scripts").glob("*.json"))]
    scripts = [s for s in scripts if s["split"] == "train" and s["id"] in cache]
    errs = sum(1 for v in cache.values() for r in v["rows"] if "error" in r)
    print(f"{len(scripts)} train scripts in cache ({errs} errored turns), prompt {PROMPT_VERSION}\n")
    print(f"{'thr':>4} {'rise':>5} {'dec':>4} {'combo':>5} | {'recall':>6} {'FP legit':>9} {'FP hard':>8} {'before ask':>10} {'turns after decisive (median, early)':>38}")
    results = []
    for thr, rise, dec, combo in itertools.product([40, 50, 60, 70, 80, 90], [0.5, 0.7, 0.9], [4.0], [True, False]):
        e = evaluate(scripts, cache, threshold=thr, rise=rise, decay=dec, combo=combo)
        results.append(((thr, rise, dec, combo), e))
        print(f"{thr:>4} {rise:>5} {dec:>4} {str(combo):>5} | {e['recall']:>6.2f} {e['fp_legit']:>3}/{e['n_legit']:<5} "
              f"{e['fp_hard']:>3}/{e['n_hard']:<4} {e['before_ask']:>10.2f} {str(e['median_turns_after_decisive']):>26} {e['early']:>6}")
    return {"results": results}


def failures(threshold: int, rise: float, combo: bool) -> None:
    cache = json.loads(CACHE.read_text())
    scripts = [json.loads(p.read_text()) for p in sorted((HERE / "scripts").glob("*.json"))]
    for s in scripts:
        if s["split"] != "train" or s["id"] not in cache:
            continue
        r = simulate(s, cache[s["id"]]["rows"], threshold, rise, 4.0, combo)
        bad = (s["label"] == "scam") != r["triggered"]
        if bad:
            rows = [x for x in cache[s["id"]]["rows"] if "error" not in x]
            print(f"\n{'MISSED' if s['label'] == 'scam' else 'FALSE ALARM'}: {s['id']} (decisive {s['decisive_turn_index']}, ask {s['first_s5_s6_turn_index']}, fired at {r['turn']})")
            for x in rows:
                print(f"   turn {x['turn']:>2} risk {x['risk']:>3} {','.join(x['stages']) or '-':16} {x['rationale'][:110]}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["collect", "sweep", "failures"])
    ap.add_argument("--limit", type=int)
    ap.add_argument("--concurrency", type=int, default=2)
    ap.add_argument("--threshold", type=int, default=70)
    ap.add_argument("--rise", type=float, default=0.7)
    ap.add_argument("--no-combo", action="store_true")
    a = ap.parse_args()
    if a.cmd == "collect":
        asyncio.run(collect(a.limit, a.concurrency))
    elif a.cmd == "sweep":
        sweep()
    else:
        failures(a.threshold, a.rise, not a.no_combo)
