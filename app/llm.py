"""LLM Gateway client: one shared keep-alive connection, JSON-returning calls validated with Pydantic.

The models this account can use (qwen3.5-4b-32k-fast, gemma-4-31b) do not enforce `response_format`
(docs/API_NOTES.md §4), so JSON comes from the prompt and is repaired, parsed and validated here.
"""

import asyncio
import json
import logging
import re
import time
from collections import deque
from typing import TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from app.config import Settings

log = logging.getLogger("kavach.llm")
T = TypeVar("T", bound=BaseModel)


class LLMError(RuntimeError):
    pass


def extract_json(text: str) -> dict:
    """Pull the first JSON object out of a model reply: tolerates code fences, prose and trailing commas."""
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.S)
    candidate = fenced.group(1) if fenced else None
    if candidate is None:
        start = text.find("{")
        if start < 0:
            raise ValueError("no JSON object in reply")
        depth, in_str, esc = 0, False, False
        for i in range(start, len(text)):
            c = text[i]
            if in_str:
                esc = (c == "\\") and not esc
                if c == '"' and not esc:
                    in_str = False
                continue
            if c == '"':
                in_str = True
            elif c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    candidate = text[start:i + 1]
                    break
        if candidate is None:
            candidate = text[start:]  # truncated; the repair below may still save it
    candidate = re.sub(r",\s*([}\]])", r"\1", candidate)
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        repaired = candidate.rstrip()
        repaired += "]" * max(0, repaired.count("[") - repaired.count("]"))
        repaired += "}" * max(0, repaired.count("{") - repaired.count("}"))
        return json.loads(repaired)


class RateLimiter:
    """Sliding 60 s window over requests and reserved tokens. This account's Gateway limits are 30 requests and
    20,000 tokens per minute per model, and max_tokens is reserved while a request is in flight (observed 429)."""

    def __init__(self, max_requests: int = 26, max_tokens: int = 16000, window: float = 60.0):
        self.max_requests, self.max_tokens, self.window = max_requests, max_tokens, window
        self.events: deque[tuple[float, int]] = deque()
        self.lock = asyncio.Lock()

    async def acquire(self, tokens: int) -> float:
        """Wait until a request of `tokens` fits. Returns seconds waited."""
        waited = 0.0
        async with self.lock:
            while True:
                now = time.monotonic()
                while self.events and now - self.events[0][0] >= self.window:
                    self.events.popleft()
                used = sum(t for _, t in self.events)
                if len(self.events) < self.max_requests and used + tokens <= self.max_tokens:
                    self.events.append((now, tokens))
                    return waited
                wait = self.window - (now - self.events[0][0]) + 0.05 if self.events else 0.5
                waited += wait
                await asyncio.sleep(wait)


# (requests per window, reserved tokens per window), kept under this account's observed limits.
MODEL_LIMITS = {"qwen3.5-4b-32k-fast": (26, 16000), "gemma-4-31b": (26, 150000)}


class LLM:
    def __init__(self, settings: Settings):
        self.limiters: dict[str, RateLimiter] = {}
        self.settings = settings
        self._client = httpx.AsyncClient(
            base_url=settings.llm_gateway_url,
            headers={"authorization": settings.assemblyai_api_key},
            timeout=httpx.Timeout(15.0, connect=5.0),
            limits=httpx.Limits(max_keepalive_connections=4, keepalive_expiry=120),
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def chat(self, model: str, messages: list[dict], max_tokens: int = 400, temperature: float = 0.2,
                   timeout: float | None = None) -> tuple[str, int]:
        """Returns (reply text, latency ms)."""
        body = {"model": model, "messages": messages, "max_tokens": max_tokens, "temperature": temperature}
        est_prompt = sum(len(m["content"]) for m in messages) // 3 + 50
        limiter = self.limiters.setdefault(model, RateLimiter(*MODEL_LIMITS.get(model, (26, 16000))))
        t0 = time.perf_counter()
        for attempt in range(2):
            await limiter.acquire(est_prompt + max_tokens)
            t0 = time.perf_counter()  # latency excludes our own pacing wait
            try:
                r = await self._client.post("/chat/completions", json=body, timeout=timeout)
            except httpx.HTTPError as e:
                raise LLMError(f"{model}: {type(e).__name__}: {e}") from e
            if r.status_code == 429 and attempt == 0:
                retry_after = float(r.headers.get("retry-after", "5") or 5)
                if retry_after > 10:
                    break
                log.warning("429 from %s, retrying in %.1fs", model, retry_after)
                await asyncio.sleep(retry_after + 0.2)
                continue
            break
        ms = round((time.perf_counter() - t0) * 1000)
        if r.status_code != 200:
            raise LLMError(f"{model}: HTTP {r.status_code}: {r.text[:200]}")
        return r.json()["choices"][0]["message"]["content"] or "", ms

    async def chat_json(self, schema: type[T], messages: list[dict], model: str | None = None,
                        fallback_model: str | None = None, max_tokens: int = 500, timeout: float | None = None,
                        retries: int = 1, temperature: float = 0.2) -> tuple[T, int, str]:
        """Call, extract JSON, validate. One retry on bad JSON (with the error fed back), then the fallback model.
        Returns (validated object, total latency ms, model that answered)."""
        models = [model or self.settings.detector_model]
        if fallback_model and fallback_model != models[0]:
            models.append(fallback_model)
        total, last_err = 0, None
        for m in models:
            msgs = list(messages)
            for attempt in range(retries + 1):
                try:
                    text, ms = await self.chat(m, msgs, max_tokens=max_tokens, temperature=temperature, timeout=timeout)
                    total += ms
                    return schema.model_validate(extract_json(text)), total, m
                except (ValueError, ValidationError) as e:
                    last_err = e
                    log.warning("bad JSON from %s (attempt %d): %s", m, attempt + 1, str(e)[:120])
                    msgs = messages + [{"role": "user", "content":
                                        f"Your last reply was not valid. Error: {str(e)[:200]}. "
                                        "Reply with ONLY the JSON object, nothing else."}]
                except LLMError as e:
                    last_err = e
                    log.warning("LLM call failed: %s", e)
                    break  # go to the fallback model
        raise LLMError(f"all models failed: {last_err}")
