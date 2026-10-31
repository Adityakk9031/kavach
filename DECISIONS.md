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
| 16 | 2026-10-31 | Render TTS audio for the **test split only** (36 calls); tune on the train split by replaying each script's own text through the detector | Tuning only needs the detector's output, not audio; skips ~54 calls of rendering and, more importantly, ~54 real-time STT streams that the free plan (5 new sessions/min, 1.25x real-time cap) would make take over an hour. Test numbers still go through real TTS -> relay -> STT -> detector -> warner |
| 17 | 2026-10-31 | Dataset: 90 scripts written by `gemma-4-31b` (detector is `qwen3.5-4b`, a different model family); split is stratified by type, exactly 18/12/6 test and 27/18/9 train for scam/legit/hard-negative | Prevents the detector being graded by its own author; every type appears in test |
| 18 | 2026-10-31 | Eval runner ends a triggered call 1.5 s after the warning's first audio; untriggered calls run to the end | Metrics need only the first trigger; saves ~40% of wall time on scam calls |
| 19 | 2026-10-31 | Eval results are JSON files in `eval/results/` (not the `eval_runs`/`eval_results` tables from PLAN §3) | Results are read by the scoreboard as one document, resumable per call; the SQLite call/event tables still hold each call's raw events |
| 20 | 2026-10-31 | The numbers published in the README/scoreboard come from a second full test run on the final code; run 1 is kept as evidence | Code changed after run 1 (review fixes, warning re-arm, LLM lanes). Prompt and threshold are frozen, so this is not tuning on test |
| 21 | 2026-10-31 | The M5 gate uses a fixed scammer script; the LLM scammer is `--adaptive`/demo only | An LLM scammer refused mid-call and varies run to run; the brief asks for a scripted scammer |
| 22 | 2026-10-31 | A warning cut off before 3 s were heard is repeated when the person stops speaking, max 3 | Eval run 1: a warning was cancelled by the person's reply 0.4 s in and never replayed |
| 23 | 2026-10-31 | Evidence LLM pass runs only once the call is flagged (and then also over the earlier turns); regexes always run | LLM budget (30 req/min): detector + persona + evidence share it |
