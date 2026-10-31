# Progress

Evidence for each verification gate. A milestone is done only when every gate item has evidence here.

## M0 — Repo, config, health, key check — ⏳ IN PROGRESS (blocked on keys)

| Gate item | Status | Evidence |
|---|---|---|
| `uv run pytest -q` passes | ✅ 2026-10-31 | `4 passed in 0.30s` (tests/test_health.py: health ok + no secret leak, missing-secret listing, plan defaults, `.env` git-ignored) |
| `/health` route serves | ✅ 2026-10-31 | `curl localhost:8765/health` → `{"status":"ok","ready":false,"missing_secrets":[...4 names...],"language":"english","stt_model":"universal-3-6-pro","detector_model":"gpt-6-luna","assemblyai_sdk":"1.8.2"}` |
| SDK has TTS | ✅ 2026-10-31 | `assemblyai 1.8.2` exposes `TTSSession`, `AsyncTTSSession`, `TextToSpeech`, `TTSConfig`, `LLMGateway` |
| Key works + one TTS voice listed | ❌ blocked | `scripts/check_keys.py` → `0/5 checks passed`, all SKIP: no `.env` yet |
| Cloned voice resolves | ❌ blocked | needs `KAVACH_WARNING_VOICE_ID` |
| Telegram `getMe` | ❌ blocked | needs `TELEGRAM_BOT_TOKEN` |

**Regression 2026-10-31 (during M1):** `uv run pytest -q` → `12 passed`; `check_keys.py` still `0/5` (no `.env`).

## M1 — Call relay + per-channel streaming STT — ⏳ IN PROGRESS (live STT blocked on key)

Built: `app/call_room.py` (relay, per-channel STT taps, takeover mute, audio-source header byte, `AudioClock` for STT latency), `app/stt.py` (raw v3 WebSocket client, `NullStt` when no key), `app/store.py` (SQLite schema from PLAN §3), WS endpoints `/ws/call/{id}/{caller|receiver}` and `/ws/events/{id}`, pages `web/index.html`, `caller.html`, `receiver.html`, `audio.js` (16 kHz AudioWorklet capture, per-source gapless player with flush), `scripts/smoke_call.py`.

| Gate item | Status | Evidence |
|---|---|---|
| `pytest tests/test_call_room.py` (fake STT) | ✅ 2026-10-31 | 8 tests pass: relay both directions + per-channel STT tap; takeover mutes receiver→caller but keeps the STT tap; final turn broadcast with `stt_latency_ms` and stored in `turns`/`events`; empty finals ignored; `end` terminates both STT sessions; `AudioClock` mapping; STT URL (`language_codes=["en"]` JSON-encoded) + message normalization; real FastAPI WS endpoints relay bytes between two sockets |
| Two browser tabs connect to one call | ✅ 2026-10-31 | Built-in browser: Caller tab + Receiver tab on `call=uicheck` → both show `On the line: caller, receiver`; STT status shows `STT disabled: ASSEMBLYAI_API_KEY not set` (expected without key) |
| Browser audio path end to end | ✅ 2026-10-31 | In-page check with `audio.js`: 1 s 440 Hz sine streamed caller→server→receiver: `sentSamples 16000, gotSamples 16000, frames 20, sources [0]`; `Player.flush` stops playback. Events logged in SQLite (`joined`, `stt_error`, `call_end`, `left`) |
| Mic failure handled | ✅ 2026-10-31 | Mic is blocked in the built-in browser pane; Receiver page shows `Microphone unavailable (NotAllowedError). You can still hear the caller.` Real mic capture **not yet verified** — needs your browser |
| Live per-party transcripts + latency | ❌ blocked | `scripts/smoke_call.py` written; needs `ASSEMBLYAI_API_KEY` |
| STT model A/B latency table | ❌ blocked | needs key: run smoke with `STT_MODEL=universal-3-6-pro` and `STT_MODEL=universal-streaming-english` |

Known issue: in the built-in browser, `streamPcm` took 1.37 s to send 1 s of audio (timer throttling). No samples are lost (pacing follows the clock) but scripted caller audio can arrive in bursts. Re-check in a normal visible Chrome tab; if it persists, move scripted streaming into the AudioWorklet.
