"""Generate the eval dataset: English two-party call scripts written by an LLM (not the detector's model).

    uv run python -m eval.generate_scripts            # all 90 (skips ones already on disk)
    uv run python -m eval.generate_scripts --limit 6  # quick trial

Composition (PLAN §F6): 45 scam across 6 types, 30 legit across 5 types, 15 hard negatives.
Each script: label, category, scam_type, caller_number, turns, decisive_turn_index (first caller turn after which a
careful human is sure it is a scam; null for non-scams), first_s5_s6_turn_index (first caller turn asking for a
credential or payment), and a deterministic train/test split.
"""

import argparse
import asyncio
import json
import random
import sys
from pathlib import Path

from pydantic import BaseModel, Field, model_validator

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.config import get_settings  # noqa: E402
from app.llm import LLM, LLMError  # noqa: E402

OUT = Path(__file__).resolve().parent / "scripts"

# (category, type, count, situation brief)
SPEC = [
    ("scam", "digital_arrest", 10, "Fake police / CBI / cyber-crime / narcotics officer says a parcel or the person's Aadhaar/SIM is linked to a crime, demands the person stay on the call and keep it secret, threatens arrest, and finally demands money to a 'safe' or 'verification' account."),
    ("scam", "bank_kyc", 8, "Fake bank or RBI executive says KYC expired or the account will be blocked, then asks for an OTP, card number, PIN or Aadhaar details to 'update' it."),
    ("scam", "courier_customs", 8, "Fake courier or customs agent says a parcel is held, demands a clearance fee or fine by UPI or gift card, with urgency."),
    ("scam", "investment_task", 7, "Fake investment / online-task / part-time-job recruiter promises easy returns, gets the person to deposit money and pay more 'fees' to withdraw."),
    ("scam", "fake_relative", 6, "Caller pretends to be a grandchild, nephew or relative in an emergency (accident, arrest, hospital), begs the person to keep it secret and send money urgently."),
    ("scam", "remote_access", 6, "Fake tech-support or bank-app support asks the person to install AnyDesk/TeamViewer or an APK, or share their screen, to 'fix' a problem, then pushes a payment or credentials."),
    ("legit", "bank_fraud_team_no_otp", 6, "A real bank fraud team calls about a suspicious transaction, only asks yes or no, blocks the card, and says they will never ask for an OTP, PIN or CVV. No payment or credential is requested."),
    ("legit", "delivery", 6, "A real delivery person or customer-care agent coordinates delivery, address, or timing. Nothing sensitive is requested on the call."),
    ("legit", "doctor_clinic", 6, "A clinic, hospital or pharmacy confirms an appointment, report pickup or refill. Fees, if mentioned, are paid in person later."),
    ("legit", "family_chat", 6, "A relative chats about health, travel, festival plans or a small favour. Warm everyday talk, no urgency or secrecy."),
    ("legit", "telemarketing", 6, "A polite telemarketer offers insurance, a broadband plan or a credit card; the person declines or asks to be sent details. No pressure, no credentials."),
    ("hard_negative", "safe_mention", 15, "A genuine call that talks about sensitive things in a SAFE way: an official warns about scams and says never to share OTPs or PINs; a police community-awareness call; a bank confirming a transaction while stating it never asks for OTP; a delivery agent saying the code is for in-person use only. The caller NEVER asks for money, OTP, PIN, card or Aadhaar details, and never threatens or demands secrecy."),
]
CITIES = ["Mumbai", "Delhi", "Pune", "Bengaluru", "Hyderabad", "Chennai", "Kolkata", "Nagpur", "Lucknow", "Jaipur"]
NAMES = ["Mr. Sharma", "Mrs. Iyer", "Mr. Gupta", "Mrs. Khan", "Mr. Reddy", "Mrs. Banerjee", "Mr. Patil", "Mr. Singh"]
AMOUNTS = ["twelve thousand rupees", "twenty five thousand rupees", "fifty thousand rupees", "eighty thousand rupees", "one lakh rupees", "nine thousand five hundred rupees"]


class Turn(BaseModel):
    speaker: str
    text: str = Field(min_length=2)


class Draft(BaseModel):
    caller_number: str = "+91 98XXXXXXXX"
    turns: list[Turn]
    decisive_turn_index: int | None = None
    first_s5_s6_turn_index: int | None = None

    @model_validator(mode="after")
    def check(self):
        n = len(self.turns)
        if not 6 <= n <= 16:
            raise ValueError(f"need 6-16 turns, got {n}")
        for i, t in enumerate(self.turns):
            if t.speaker != ("caller" if i % 2 == 0 else "receiver"):
                raise ValueError(f"turn {i} speaker must alternate caller/receiver starting with caller")
            if any(c in t.text for c in "[]{}*#_`") or t.text.strip().startswith("("):
                raise ValueError(f"turn {i} contains markup or stage directions")
        for name in ("decisive_turn_index", "first_s5_s6_turn_index"):
            v = getattr(self, name)
            if v is not None and not (0 <= v < n and v % 2 == 0):
                raise ValueError(f"{name}={v} must be the index of a caller turn")
        return self


def prompt_for(category: str, kind: str, brief: str, rng: random.Random) -> str:
    scam = category == "scam"
    return f"""Write a realistic phone call transcript between a CALLER and an elderly Indian person (RECEIVER) for a scam-detection test set.

Call type: {kind.replace('_', ' ')}
Situation: {brief}
Details to weave in (use naturally): city {rng.choice(CITIES)}, receiver addressed as {rng.choice(NAMES)}, amount {rng.choice(AMOUNTS)}.
Make this call different from typical examples: vary the caller's name, tone and the order of events (seed {rng.randint(1, 10**6)}).

Rules:
- 8 to 14 turns, strictly alternating, starting with the caller: turn 0 caller, turn 1 receiver, turn 2 caller, and so on.
- Natural spoken English with light Indian-English phrasing. Short turns of 1 to 3 sentences. Write it to be read aloud: no markdown, no brackets, no stage directions, no emoji.
- The receiver is realistic: confused, worried or polite; sometimes asks questions or hesitates.
- {"This IS a scam. The caller is the scammer." if scam else "This is NOT a scam. The caller is genuine and never asks for money, OTPs, PINs, card numbers, Aadhaar or other credentials, never threatens, and never asks for secrecy."}

Also give:
- "decisive_turn_index": {"the 0-based index of the first CALLER turn after which a careful human listener would be sure this is a scam" if scam else "null"}
- "first_s5_s6_turn_index": {"the 0-based index of the first CALLER turn where the caller asks for a credential (OTP, PIN, CVV, card number, Aadhaar, password) or for a payment; null if the call never does" if scam else "null"}
- "caller_number": a plausible fake Indian phone number like "+91 98XXXXXXXX" with some digits replaced by X

Reply with ONLY one JSON object:
{{"caller_number": "...", "turns": [{{"speaker": "caller", "text": "..."}}, {{"speaker": "receiver", "text": "..."}}], "decisive_turn_index": ..., "first_s5_s6_turn_index": ...}}"""


def build_plan() -> list[dict]:
    plan = []
    for category, kind, count, brief in SPEC:
        for i in range(count):
            plan.append({"id": f"{category}_{kind}_{i:02d}", "category": category, "scam_type": kind if category == "scam" else None,
                         "subtype": kind, "brief": brief, "pos": i})
    # Deterministic ~60/40 split, stratified by type: each type gives floor(40%) of its calls to test, and the
    # remainder to hit each category's exact 40% (18 of 45, 12 of 30, 6 of 15) goes to the largest fractions.
    for category in ("scam", "legit", "hard_negative"):
        group = [p for p in plan if p["category"] == category]
        types = sorted({p["subtype"] for p in group})
        size = {t: sum(1 for p in group if p["subtype"] == t) for t in types}
        test_n = {t: int(size[t] * 0.4 + 1e-9) for t in types}
        spare = round(len(group) * 0.4) - sum(test_n.values())
        for t in sorted(types, key=lambda t: (-(size[t] * 0.4 - test_n[t]), t))[:spare]:
            test_n[t] += 1
        for t in types:  # spread the test calls evenly through the type's positions
            members = sorted((p for p in group if p["subtype"] == t), key=lambda p: p["pos"])
            quota = test_n[t] / size[t]
            for k, p in enumerate(members):
                p["split"] = "test" if int((k + 1) * quota + 1e-9) > int(k * quota + 1e-9) else "train"
    return plan


async def make_one(llm: LLM, model: str, item: dict, sem: asyncio.Semaphore) -> dict | None:
    rng = random.Random(item["id"])
    scam = item["category"] == "scam"
    async with sem:
        try:
            draft, ms, used = await llm.chat_json(
                Draft, [{"role": "user", "content": prompt_for(item["category"], item["subtype"], item["brief"], rng)}],
                model=model, max_tokens=1800, timeout=90, retries=2, temperature=0.9)
        except LLMError as e:
            print(f"  FAIL {item['id']}: {e}")
            return None
    if scam and draft.decisive_turn_index is None:
        print(f"  REJECT {item['id']}: scam without decisive_turn_index")
        return None
    if not scam:
        draft.decisive_turn_index = None
        draft.first_s5_s6_turn_index = None
    if scam and draft.first_s5_s6_turn_index is not None and draft.decisive_turn_index > draft.first_s5_s6_turn_index:
        draft.decisive_turn_index = draft.first_s5_s6_turn_index  # sure no later than the ask itself
    out = {"id": item["id"], "label": "scam" if scam else "legit", "category": item["category"],
           "scam_type": item["scam_type"], "subtype": item["subtype"], "split": item["split"],
           "caller_number": draft.caller_number, "decisive_turn_index": draft.decisive_turn_index,
           "first_s5_s6_turn_index": draft.first_s5_s6_turn_index, "generator": used,
           "turns": [t.model_dump() for t in draft.turns]}
    (OUT / f"{item['id']}.json").write_text(json.dumps(out, indent=1))
    print(f"  ok {item['id']} ({len(draft.turns)} turns, {ms} ms)")
    return out


def resplit() -> int:
    """Rewrite the `split` field of every script on disk from the current plan. Returns how many changed."""
    split = {p["id"]: p["split"] for p in build_plan()}
    changed = 0
    for path in sorted(OUT.glob("*.json")):
        d = json.loads(path.read_text())
        if split.get(d["id"]) and d["split"] != split[d["id"]]:
            d["split"] = split[d["id"]]
            path.write_text(json.dumps(d, indent=1))
            changed += 1
    return changed


async def main(limit: int | None, concurrency: int) -> None:
    S = get_settings()
    OUT.mkdir(parents=True, exist_ok=True)
    plan = [p for p in build_plan() if not (OUT / f"{p['id']}.json").exists()]
    if limit:
        # spread the trial across categories rather than taking only the first type
        seen, picked = {}, []
        for p in plan:
            if seen.get(p["subtype"], 0) < 1:
                seen[p["subtype"]] = 1
                picked.append(p)
        plan = picked[:limit]
    print(f"generating {len(plan)} scripts with {S.script_gen_model}, concurrency {concurrency}")
    llm = LLM(S)
    try:
        sem = asyncio.Semaphore(concurrency)
        done = await asyncio.gather(*(make_one(llm, S.script_gen_model, p, sem) for p in plan))
    finally:
        await llm.aclose()
    print(f"done: {sum(d is not None for d in done)}/{len(plan)} ok")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int)
    ap.add_argument("--concurrency", type=int, default=4)
    ap.add_argument("--resplit", action="store_true", help="only re-apply the train/test split to scripts on disk")
    a = ap.parse_args()
    if a.resplit:
        print(f"{resplit()} scripts changed split")
    else:
        asyncio.run(main(a.limit, a.concurrency))
        print(f"{resplit()} scripts changed split")
