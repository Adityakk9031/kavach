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

    def _prune(self, now: float) -> None:
        while self.events and now - self.events[0][0] >= self.window:
            self.events.popleft()

    def _fits(self, tokens: int) -> bool:
        return len(self.events) < self.max_requests and sum(t for _, t in self.events) + tokens <= self.max_tokens

    async def acquire(self, tokens: int, max_wait: float | None = None) -> float:
        """Wait until a request of `tokens` fits. Returns seconds waited. With `max_wait`, fail fast instead of
        queueing: a call-path request (the detector) must never sit behind a full budget."""
        waited = 0.0
        async with self.lock:
            while True:
                now = time.monotonic()
                self._prune(now)
                if self._fits(tokens):
                    self.events.append((now, tokens))
                    return waited
                wait = self.window - (now - self.events[0][0]) + 0.05 if self.events else 0.5
                if max_wait is not None and waited + wait > max_wait:
                    raise LLMError(f"local rate budget exhausted (would wait {wait:.1f}s)")
                waited += wait
                await asyncio.sleep(wait)


# (requests per window, reserved tokens per window), kept under this account's observed limits (30 req/min and
# 20k tokens/min on qwen, 30 req/min and 200k tokens/min on gemma). Each model's budget is split into lanes so the
# detector (the call path) cannot be starved by persona/evidence calls during a takeover.
MODEL_LIMITS = {"qwen3.5-4b-32k-fast": {"detector": (12, 8000), "persona": (10, 7000), "other": (6, 3000)},
                "gemma-4-31b": {"detector": (8, 50000), "persona": (8, 50000), "other": (12, 80000)}}
DEFAULT_LIMITS = {"detector": (8, 5000), "persona": (8, 5000), "other": (8, 5000)}


class LLM:
    def __init__(self, settings: Settings, limiters: dict | None = None):
        # Pass one dict to several LLM objects (e.g. tests) so they share a budget, as the real account does.
        self.limiters: dict[tuple[str, str], RateLimiter] = limiters if limiters is not None else {}
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
                   timeout: float | None = None, lane: str = "other", max_wait: float | None = None) -> tuple[str, int]:
        """Returns (reply text, latency ms). `lane` picks the rate budget; `max_wait` makes it fail fast."""
        body = {"model": model, "messages": messages, "max_tokens": max_tokens, "temperature": temperature}
        est_prompt = sum(len(m["content"]) for m in messages) // 4 + 50  # English averages ~4 characters per token
        limits = MODEL_LIMITS.get(model, DEFAULT_LIMITS)[lane]
        limiter = self.limiters.setdefault((model, lane), RateLimiter(*limits))
        t0 = time.perf_counter()
        for attempt in range(2):
            await limiter.acquire(est_prompt + max_tokens, max_wait)
            t0 = time.perf_counter()  # latency excludes our own pacing wait
            try:
                r = await self._client.post("/chat/completions", json=body, timeout=timeout)
            except httpx.HTTPError as e:
                raise LLMError(f"{model}: {type(e).__name__}: {e}") from e
            if r.status_code == 429 and attempt == 0:
                retry_after = float(r.headers.get("retry-after", "5") or 5)
                if retry_after > (max_wait if max_wait is not None else 10):
                    break
                log.warning("429 from %s, retrying in %.1fs", model, retry_after)
                await asyncio.sleep(retry_after + 0.2)
                continue
            break
        ms = round((time.perf_counter() - t0) * 1000)
        if r.status_code != 200:
            raise LLMError(f"{model}: HTTP {r.status_code}: {r.text[:200]}")
        try:
            return r.json()["choices"][0]["message"]["content"] or "", ms
        except (KeyError, IndexError, TypeError, ValueError) as e:
            raise ValueError(f"unexpected response body from {model}: {str(r.text)[:120]}") from e

    async def chat_json(self, schema: type[T], messages: list[dict], model: str | None = None,
                        fallback_model: str | None = None, max_tokens: int = 500, timeout: float | None = None,
                        retries: int = 1, temperature: float = 0.2, lane: str = "other",
                        max_wait: float | None = None, total_timeout: float | None = None) -> tuple[T, int, str]:
        """Call, extract JSON, validate; see `_chat_json`. `total_timeout` bounds the WHOLE thing (retries and
        fallback included): the detector uses it so one slow attempt cannot push the warning past its budget."""
        try:
            return await asyncio.wait_for(
                self._chat_json(schema, messages, model, fallback_model, max_tokens, timeout, retries, temperature,
                                lane, max_wait), total_timeout)
        except asyncio.TimeoutError as e:
            raise LLMError(f"total time limit {total_timeout}s exceeded") from e

    async def _chat_json(self, schema, messages, model, fallback_model, max_tokens, timeout, retries, temperature,
                         lane, max_wait):
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
                    text, ms = await self.chat(m, msgs, max_tokens=max_tokens, temperature=temperature, timeout=timeout,
                                               lane=lane, max_wait=max_wait)
                    total += ms
                    return schema.model_validate(extract_json(text)), total, m
                except (ValueError, ValidationError, TypeError, KeyError, IndexError) as e:
                    last_err = e
                    log.warning("bad JSON from %s (attempt %d): %s", m, attempt + 1, str(e)[:120])
                    msgs = messages + [{"role": "user", "content":
                                        f"Your last reply was not valid. Error: {str(e)[:200]}. "
                                        "Reply with ONLY the JSON object, nothing else."}]
                except LLMError as e:
                    last_err = e
                    log.warning("LLM call failed (attempt %d on %s): %s", attempt + 1, m, e)
                    if attempt < retries:
                        await asyncio.sleep(0.3)  # one quick retry of the same model: failures are usually transient
                        continue
                    break  # then the fallback model
        raise LLMError(f"all models failed: {last_err}")
