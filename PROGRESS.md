# Progress

Evidence for each verification gate. A milestone is done only when every gate item has evidence here.

## M0 — Repo, config, health, key check — ⏳ 4/5 live checks pass (Telegram token pending)

| Gate item | Status | Evidence |
|---|---|---|
| `uv run pytest -q` passes | ✅ 2026-10-31 | `4 passed in 0.30s` (tests/test_health.py: health ok + no secret leak, missing-secret listing, plan defaults, `.env` git-ignored) |
| `/health` route serves | ✅ 2026-10-31 | `curl localhost:8765/health` → `{"status":"ok","ready":false,"missing_secrets":[...4 names...],"language":"english","stt_model":"universal-3-6-pro","detector_model":"gpt-6-luna","assemblyai_sdk":"1.8.2"}` |
| SDK has TTS | ✅ 2026-10-31 | `assemblyai 1.8.2` exposes `TTSSession`, `AsyncTTSSession`, `TextToSpeech`, `TTSConfig`, `LLMGateway` |
| Key works + one TTS voice listed | ✅ 2026-10-31 | `data/check/m0_check.txt`: STT `Begin` in 1420 ms model=universal-3-6-pro; TTS synthesized with `voice_id=aai-gunnar model=assemblyai-tts-1`; LLM `qwen3.5-4b-32k-fast` replied in 993 ms |
| Cloned voice resolves | ✅ 2026-10-31 | `resolved=01a19208-766c-7003-97c5-4f0cf646ade8 lang=english model=assemblyai-tts-1 expires=2026-12-30, first audio 399 ms after Generate (35 frames)` |
| Telegram `getMe` | ❌ blocked | needs `TELEGRAM_BOT_TOKEN` (check prints `SKIP`) |

Finding: this account can use only 2 of 56 Gateway models (`qwen3.5-4b-32k-fast`, `gemma-4-31b`); detector/persona/eval-writer defaults changed (DECISIONS #13).

**Regression 2026-10-31 (during M1):** `uv run pytest -q` → `12 passed`; `check_keys.py` still `0/5` (no `.env`).

## M1 — Call relay + per-channel streaming STT — ⚠️ live gate passes 4 of 6 runs; intermittent silent stall unexplained

Built: `app/call_room.py` (relay, per-channel STT taps, takeover mute, audio-source header byte, `AudioClock` for STT latency), `app/stt.py` (raw v3 WebSocket client, `NullStt` when no key), `app/store.py` (SQLite schema from PLAN §3), WS endpoints `/ws/call/{id}/{caller|receiver}` and `/ws/events/{id}`, pages `web/index.html`, `caller.html`, `receiver.html`, `audio.js` (16 kHz AudioWorklet capture, per-source gapless player with flush), `scripts/smoke_call.py`.

| Gate item | Status | Evidence |
|---|---|---|
| `pytest tests/test_call_room.py` (fake STT) | ✅ 2026-10-31 | 8 tests pass: relay both directions + per-channel STT tap; takeover mutes receiver→caller but keeps the STT tap; final turn broadcast with `stt_latency_ms` and stored in `turns`/`events`; empty finals ignored; `end` terminates both STT sessions; `AudioClock` mapping; STT URL (`language_codes=["en"]` JSON-encoded) + message normalization; real FastAPI WS endpoints relay bytes between two sockets |
| Two browser tabs connect to one call | ✅ 2026-10-31 | Built-in browser: Caller tab + Receiver tab on `call=uicheck` → both show `On the line: caller, receiver`; STT status shows `STT disabled: ASSEMBLYAI_API_KEY not set` (expected without key) |
| Browser audio path end to end | ✅ 2026-10-31 | In-page check with `audio.js`: 1 s 440 Hz sine streamed caller→server→receiver: `sentSamples 16000, gotSamples 16000, frames 20, sources [0]`; `Player.flush` stops playback. Events logged in SQLite (`joined`, `stt_error`, `call_end`, `left`) |
| Mic failure handled | ✅ 2026-10-31 | Mic is blocked in the built-in browser pane; Receiver page shows `Microphone unavailable (NotAllowedError). You can still hear the caller.` Real mic capture **not yet verified** — needs your browser |
| Live per-party transcripts + latency | ✅ 2026-10-31 (3 consecutive runs) | `universal-3-6-pro`, 2 channels, 6 turns/run: `smoke-dbg` 6 finals, STT latency median ~420 ms, word match 0.976; `u36-run2` 6 finals, 484/462 ms, 0.976; `u36-run3` 6 finals, 438/437 ms, 0.976. Raw: `data/smoke/ab_output.txt`, `data/smoke/result-*.json`, SQLite `turns.stt_latency_ms` |
| STT model A/B latency table | ✅ 2026-10-31 | `universal-3-6-pro`: ~440 ms mean/turn (3 runs), has `SpeechStarted`. `universal-streaming-english`: `en-run1` 801 ms mean, 0.96 match; no `SpeechStarted`; ~3x more partials. **Keep `universal-3-6-pro`.** |
| Reliability | ❌ open | 2 of 6 live runs stalled silently with **no error logged**: `smoke-u36` (u36, first run after server start): 0 finals, only 1 `speech_started`; `en-run2` (english): 2 of 6 finals, match 0.315. Both opened `Begin` normally. Direct STT socket and relay tests (`relay_dbg*.py`) with the same audio worked. Not root-caused. Suspects: free-tier session limits, pacing of two simultaneous streams. Next: add a stall watchdog + log raw STT frames per session, re-test. |

Known issue: in the built-in browser, `streamPcm` took 1.37 s to send 1 s of audio (timer throttling). No samples are lost (pacing follows the clock) but scripted caller audio can arrive in bursts. Re-check in a normal visible Chrome tab; if it persists, move scripted streaming into the AudioWorklet.

## M1 update — soak + reliability (2026-10-31)

Soak (4 live calls, `universal-3-6-pro`): 3 clean (6 finals, 0.976 match, ~440 ms), 1 degraded (`soak-3`): both STT sockets dropped together (no close code) ~16 s in; finals were delayed up to 29 s; auto-restart (new, `app/call_room.py`) recovered both channels but ~2 turns were lost (match 0.73). Cause not established (stalled event loop vs network). Added `loop_lag` events (`app/main.py`) so the next occurrence is attributable. Overall live record to date: 7 clean / 3 degraded of 10.

## M2 — Scam-stage detector + risk score + UI chips — ✅ gate met (with caveats)

Built: `app/llm.py` (shared keep-alive client, JSON extraction/repair, Pydantic validation, 1 retry, fallback model, **per-model rate limiter + 429 handling**), `app/detector.py` (stages S1–S7, `RiskTracker`: rise 0.7·gap, decay 4/turn, threshold 70 or ACTION∩PRESSURE combo), `app/pipeline.py` (per-call ordered worker, timings logged as events), receiver page chips + risk meter.

| Gate item | Status | Evidence |
|---|---|---|
| 10 fixed transcripts (5 scam must trigger, 5 legit must not), live LLM | ✅ 2026-10-31 | `uv run pytest tests/test_detector.py -k transcripts` → `10 passed in 25.07s`. Per-turn logs in `docs/evidence/scam_*.json`, `legit_*.json`. Scams reached cum risk 79–93 and triggered; legit calls peaked at cum 17.5 (bank-fraud-team call, S1 only), hard negatives ("never share your OTP", "call 1930") scored 0–5 |
| Risk math unit tests (offline) | ✅ | 8 tests: fast rise, slow decay with floor, combo rule, no combo from one group, new-stage reporting, validation of noisy model output, JSON extraction from fences/prose/truncation |
| Live spoken scam through the simulator lights chips | ✅ 2026-10-31 | `scripts/smoke_call.py --call-id m2live` (TTS-rendered digital-arrest call, two sockets, real STT): `detect` events turn0 S1 risk 45→cum 31.5; turn2 S1,S2 cum 68.9; turn4 S1,S2,S3 cum 87.2 → **trigger (threshold) 1253 ms after the caller's last word**. Receiver page screenshot shows risk 87, Authority/Threat/Secrecy chips on, WARNING state |

Caveats / findings:
- **LLM account limits** (headers): `qwen3.5-4b-32k-fast` = 30 req/min, 20,000 tokens/min, and `max_tokens` is reserved while a request is in flight. Repeated test runs hit 429 and one live transcript test failed because of it (error logged, not a wrong answer). Mitigations: limiter (26 req / 16k tokens per 60 s per model), `max_tokens` 350→200, retry once on 429 if `retry-after` ≤ 10 s. **Do not run the live suite concurrently with other LLM work.** Eval (M4) must be paced to this budget.
- Fixtures are hand-written and easy; real difficulty is measured in M4.
- First LLM call after a cold connection is ~1.2 s vs 0.6–0.8 s warm; call-start pre-warm not yet implemented.
- Latency budget so far: STT final ≈ 0.45 s + detector ≈ 0.7–1.2 s → trigger 1.05–1.65 s after the turn end. Leaves ~1.35–1.95 s for TTS first audio.
- `gemma-4-31b` fallback timed out (ReadTimeout) under the 2.5 s limit; it is too slow to be a useful live fallback.
