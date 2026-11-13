"""How the protected person really talks, learned from their own side of their calls, so the takeover voice can talk
the same way and the caller notices no change.

Two parts. `measure` is plain counting (how long their replies are). `learn` asks the model for a short description of
their manner and the small phrases they repeat. Only the MANNER is kept: no names, numbers, places or facts, and a phrase
is kept only if the person really said it. The takeover voice still passes its own guard, and still says made-up details only.
"""

import logging
import re
import statistics

from pydantic import BaseModel, Field, field_validator

from app.llm import LLM, LLMError

log = logging.getLogger("kavach.style")

MIN_WORDS = 40      # less than this is not enough to say how someone talks
MAX_TURNS = 150     # the most recent turns are used
UNSAFE = re.compile(r"\d|@|https?://|www\.")

PROMPT = """You study how ONE person talks on the phone, from their own lines in recent calls (the other side is left out).
Describe their MANNER of speaking so that an actor could talk like them. Language of the lines: {label}.

Reply with ONLY one JSON object:
{{"summary": "two short sentences, in English, on how they talk: pace, politeness, how they greet and react, short or long replies, how they ask things",
  "phrases": ["up to six small words or phrases, in {label}, that they say again and again, copied exactly, five words at most each"]}}

Rules:
- Manner only. No names, places, numbers, dates, money, family details, or what the calls were about.
- A phrase must be an everyday filler, greeting or reaction they really used more than once ("okay okay", "one minute", "tell me").
- If there is too little to go on, return an empty phrases list."""


class StyleCard(BaseModel):
    summary: str = ""
    phrases: list[str] = Field(default_factory=list)

    @field_validator("summary", mode="before")
    @classmethod
    def clean_summary(cls, v):
        return re.sub(r"\s+", " ", str(v or "")).strip()[:300]

    @field_validator("phrases", mode="before")
    @classmethod
    def clean_phrases(cls, v):
        return [str(p).strip().strip('"').strip()[:40] for p in (v or []) if str(p).strip()][:8]


def _words(text: str) -> list[str]:
    return re.findall(r"[^\W\d_]+(?:'[^\W\d_]+)?", text.lower())


def measure(texts: list[str]) -> dict:
    """Plain counts over the person's own lines."""
    lengths = [len(_words(t)) for t in texts if _words(t)]
    return {"turns": len(lengths), "words": sum(lengths),
            "words_per_turn": round(statistics.median(lengths)) if lengths else 0}


def keep_phrases(phrases: list[str], texts: list[str]) -> list[str]:
    """Only phrases the person really said, more than once, with nothing that could be a number or an address."""
    said = " ".join(" ".join(_words(t)) for t in texts)
    out = []
    for p in phrases:
        norm = " ".join(_words(p))
        if not norm or UNSAFE.search(p) or len(norm.split()) > 5 or norm in (" ".join(_words(o)) for o in out):
            continue
        if len(re.findall(r"(?<!\S)" + re.escape(norm) + r"(?!\S)", said)) >= 2:
            out.append(p)
    return out[:6]


async def learn(llm: LLM, model: str, texts: list[str], label: str = "English") -> dict | None:
    """A style card from the person's own lines, or None when there is too little speech or the model fails."""
    texts = [t.strip() for t in texts if t and t.strip()][-MAX_TURNS:]
    stats = measure(texts)
    if stats["words"] < MIN_WORDS:
        return None
    lines = "\n".join("- " + UNSAFE.sub("", t)[:200] for t in texts)
    try:
        card, _ms, _model = await llm.chat_json(
            StyleCard, [{"role": "system", "content": PROMPT.format(label=label)},
                        {"role": "user", "content": "Their lines:\n" + lines + "\n\nJSON:"}],
            model=model, max_tokens=300, timeout=12, lane="other", max_wait=20.0, total_timeout=30)
    except LLMError as e:
        log.warning("could not learn a speaking style: %s", e)
        return None
    summary = "" if UNSAFE.search(card.summary) else card.summary
    return {**stats, "summary": summary, "phrases": keep_phrases(card.phrases, texts)}
