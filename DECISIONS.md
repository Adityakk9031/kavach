# Decisions

One line each: decision, then reason. Sources for API facts are in docs/API_NOTES.md.

| # | Date | Decision | Reason |
|---|---|---|---|
| 1 | 2026-10-31 | Backend owns all AssemblyAI connections; browsers only talk to our FastAPI WS | Key never leaves the server; one code path for live and eval; no browser temp tokens needed |
| 2 | 2026-10-31 | 16 kHz PCM s16le mono everywhere (TTS requested at `sample_rate=16000`) | STT default input; TTS supports 16000; no server resampling |
| 3 | 2026-10-31 | Raw WebSocket clients (`websockets`) for STT and TTS, SDK only for key checks | Need frame-level control: drop audio between `Cancel` and `Cancelled`, timestamp first `Audio`, `SpeechStarted` |
| 4 | 2026-10-31 | STT default `universal-3-6-pro` + `language_codes=["en"]`; `universal-streaming-english` is a config fallback | Docs: fastest, best entity accuracy, entity-aware endpointing, and `SpeechStarted` barge-in signal (Universal-Streaming lacks it). A/B in M1 |
| 5 | 2026-10-31 | Detector/extractor LLM `gpt-6-luna` (`reasoning_effort: none`), fallback `mercury-3` | Live Gateway catalog: 0.87 s p50 / 1.18 s p95, highest extraction quality among sub-1 s models, JSON-schema support |
| 6 | 2026-10-31 | Eval script generator `claude-sonnet-5-5` | Different model family from the detector, so the test isn't graded by its own author |
| 7 | 2026-10-31 | Render eval audio with one TTS WS session per voice, reused across scripts | Free plan allows 5 new TTS sessions/min; sessions last up to 1 h |
| 8 | 2026-10-31 | Threshold/prompt tuning replays cached train-split transcripts through the detector offline | STT is throttled at 1.25× real time and session-limited; final test numbers still come from full live-pipeline runs |
| 9 | 2026-10-31 | Persona voice `aai-gunnar` (older man, slow pace) | Fits a slow, polite, slightly confused persona; distinct from the cloned family voice |
| 10 | 2026-10-31 | PDF via ReportLab | Pure-Python wheel; WeasyPrint needs Pango/Cairo system libs on macOS |
| 11 | 2026-10-31 | Project Python pinned to 3.12 via `uv` | Local default is 3.14; avoids missing wheels |
| 12 | 2026-10-31 | Demo Caller tab can play a pre-rendered scam script instead of a live mic | Two live mics on one laptop cross-talk; same WS path as the eval harness |
| 13 | 2026-10-31 | **Supersedes 5 and 6.** Detector, extractor and persona use `qwen3.5-4b-32k-fast`; fallback and eval script generator use `gemma-4-31b` | Probed all 56 Gateway models with this account: only these two are accessible (rest: "Your account does not have access"). qwen: 0.28 s p50 but no `response_format`, so JSON comes from the prompt + `json-repair` + Pydantic validation + 1 retry. gemma is a different family from qwen, so the eval still isn't graded by its author |
| 14 | 2026-10-31 | Pace everything for the free plan (5 new STT and 5 new TTS sessions/min, 50 TTS HTTP req/min) | Account model access looks like the free tier; plan not confirmed. Pacing for free is safe on paid too |
| 15 | 2026-10-31 | Keep STT `universal-3-6-pro` (A/B measured) | ~440 ms vs ~800 ms to final on the same 6-turn call; only U3.6 emits `SpeechStarted` (barge-in). Intermittent stalls seen on both models, see PROGRESS M1 |
