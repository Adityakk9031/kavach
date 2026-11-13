"""Scam-stage detection and cumulative risk.

Per finalized caller turn, an LLM looks at a rolling window of the last few turns and returns the
stages it sees. `RiskTracker` (pure, no I/O) turns those into a cumulative risk with hysteresis and a
trigger decision. The detector never raises into the call path: on failure it reports `error`.
"""

import logging
from dataclasses import dataclass, field

from pydantic import BaseModel, Field, field_validator

from app.config import Settings
from app.llm import LLM, LLMError

log = logging.getLogger("kavach.detector")

STAGES = {
    "S1": "Authority impersonation (police, CBI, ED, customs, TRAI, RBI, bank, courier, court)",
    "S2": "Threat or fear (arrest, warrant, case filed, account freeze, illegal parcel, SIM block)",
    "S3": "Isolation or secrecy (don't tell anyone, stay on the call, move to video call, don't disconnect)",
    "S4": "Urgency (within one hour, immediately, or else)",
    "S5": "Credential request (one-time code, PIN, CVV, card number, national ID or Social Security number, bank login, password)",
    "S6": "Payment request (bank or instant transfer, wire, crypto, 'safe account' or 'verification' account, gift cards, fees or fines)",
    "S7": "Remote access (AnyDesk, TeamViewer, screen share, installing an APK)",
}
PRESSURE = {"S1", "S2", "S3"}
ACTION = {"S5", "S6", "S7"}

SYSTEM_PROMPT = f"""You are a scam-call detector protecting an elderly person anywhere in the world. You read a live phone
transcript and report which scam stages the CALLER has used so far.

Stages:
{chr(10).join(f"{k}: {v}" for k, v in STAGES.items())}

Rules:
- The call may be in English, Spanish, Portuguese, German, French or Italian. Judge it the same way in any of them and copy quotes exactly as spoken.
- Tag a stage only when the CALLER does it in this call. The listener's own words never count.
- Ordinary callers identify themselves: a bank, courier, clinic, shop or company saying who they are and why they
  call is NOT S1. S1 means authority is used as LEVERAGE: claiming to be police, a tax agency, customs, a central bank, a government office or the bank's
  "fraud department" in order to frighten, pressure or control the listener.
- S2 is a threat aimed at the listener (arrest, legal action, losing money unless they comply). A bank protecting
  the customer ("we blocked your card for your safety", "visit your branch") is NOT a threat.
- S5 means the caller ASKS the listener to give, read out or enter a credential. A caller warning
  "never share your OTP" or "we will never ask for your PIN" is NOT S5.
- S6 means the caller asks the listener to send money to fix a problem, avoid a threat, unlock earnings, a job,
  a prize or a parcel, or to a personal account, UPI ID or gift card. Payment the listener already expects is NOT
  S6: cash on delivery for something they ordered, a clinic fee paid at the counter, a bill they know about.
- Job, task, prize and investment scams usually have NO authority or threat. Asking the listener to pay a deposit,
  "security fee", "registration fee" or "tax" to unlock earnings, a bonus or a payout is S6 and is a scam: risk 75+.
- Strong signs of a genuine call: the caller warns about scams, tells the listener NOT to share codes, offers to
  verify through an official number or the branch, lets the listener hang up, and asks for nothing sensitive.
  Rate such calls 0-15 however many sensitive words (bank, police, OTP, block) appear.
- Impersonation scams (fake police, tax agency, customs, bank fraud department or tech support claiming a crime, a debt,
  a frozen account or a parcel, and demanding the person stay on the line and pay) are the most common. Rate them high once authority plus a threat or secrecy appears.
- risk is 0-100, your confidence that this call is a scam RIGHT NOW given everything so far:
  0-15 normal call; 20-40 something odd but no demand yet; 50-65 clear pressure tactics without a demand;
  70+ the caller demands money or credentials while using pressure, secrecy or a false identity.

Reply with ONLY one JSON object, no prose:
{{"stages": ["S1", ...], "evidence_quotes": ["short exact quote from the caller", ...], "risk": 0-100, "rationale": "one sentence"}}"""


class Detection(BaseModel):
    stages: list[str] = Field(default_factory=list)
    evidence_quotes: list[str] = Field(default_factory=list)
    risk: int = Field(ge=0, le=100)
    rationale: str = ""

    @field_validator("stages", mode="before")
    @classmethod
    def clean_stages(cls, v):
        out = []
        for s in v or []:
            s = str(s).strip().upper()
            if s in STAGES and s not in out:
                out.append(s)
        return out

    @field_validator("risk", mode="before")
    @classmethod
    def clamp_risk(cls, v):
        return max(0, min(100, int(round(float(v)))))

    @field_validator("evidence_quotes", mode="before")
    @classmethod
    def clean_quotes(cls, v):
        return [str(q)[:200] for q in (v or [])][:5]


@dataclass
class Decision:
    risk_llm: int
    risk_cum: float
    stages_now: list[str]
    stages_all: list[str]
    trigger: bool
    reason: str | None  # "threshold" | "combo" | None
    new_stages: list[str] = field(default_factory=list)


class RiskTracker:
    """Cumulative risk: rises fast toward a higher LLM score, decays slowly when the LLM score is lower."""

    def __init__(self, threshold: int = 60, rise: float = 0.7, decay: float = 4.0):
        self.threshold, self.rise, self.decay = threshold, rise, decay
        self.risk = 0.0
        self.stages: set[str] = set()
        self.warned = False

    def update(self, det: Detection) -> Decision:
        if det.risk > self.risk:
            self.risk += self.rise * (det.risk - self.risk)
        else:
            self.risk = max(float(det.risk), self.risk - self.decay)
        new = [s for s in det.stages if s not in self.stages]
        self.stages |= set(det.stages)
        reason = None
        if self.risk >= self.threshold:
            reason = "threshold"
        elif self.stages & ACTION and self.stages & PRESSURE:
            reason = "combo"
        return Decision(det.risk, round(self.risk, 1), sorted(det.stages), sorted(self.stages),
                        reason is not None, reason, sorted(new))


def format_window(turns: list[dict]) -> str:
    label = {"caller": "CALLER", "receiver": "LISTENER", "persona": "LISTENER", "warning": "LISTENER"}
    return "\n".join(f"{label.get(t['channel'], t['channel'].upper())}: {t['text']}" for t in turns)


class Detector:
    def __init__(self, settings: Settings, llm: LLM):
        self.settings, self.llm = settings, llm

    def new_tracker(self) -> RiskTracker:
        s = self.settings
        return RiskTracker(s.risk_threshold, s.risk_rise, s.risk_decay_per_turn)

    async def analyse(self, window: list[dict]) -> tuple[Detection, int, str]:
        """LLM call over the rolling window. Returns (detection, latency ms, model)."""
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": "Transcript so far:\n" + format_window(window) + "\n\nJSON:"},
        ]
        return await self.llm.chat_json(
            Detection, messages, model=self.settings.detector_model,
            fallback_model=self.settings.detector_fallback_model, max_tokens=200,
            timeout=self.settings.detector_timeout_s, lane="detector", max_wait=1.0,
            total_timeout=self.settings.detector_total_s,
        )

    async def process(self, tracker: RiskTracker, window: list[dict]) -> tuple[Decision | None, dict]:
        """Analyse and update the tracker. Never raises; on LLM failure returns (None, {"error": ...})."""
        try:
            det, ms, model = await self.analyse(window[-self.settings.detector_window_turns:])
        except LLMError as e:
            log.error("detector failed: %s", e)
            return None, {"error": str(e)}
        return tracker.update(det), {"llm_ms": ms, "model": model, "rationale": det.rationale,
                                     "evidence_quotes": det.evidence_quotes}
