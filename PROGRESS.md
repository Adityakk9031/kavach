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
