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
