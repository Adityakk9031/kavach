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

## M3 — Family-voice warning + barge-in — ✅ gate met (browser mic path not yet exercised)

Built: `app/tts.py` (TTS-1 WebSocket session: PascalCase frames, drops Audio between our `Cancel` and the server's `Cancelled`, per-request TTFA, KeepAlive, long-lived shared pool), `app/warner.py` (7 stage templates + default, parent name from config, numbers as words; trigger → speak to Receiver only; barge-in from browser VAD and from STT `SpeechStarted`; 0.4 s echo guard; fallback voice is announced in the UI, never silent), receiver page warning banner + local voice detector (3 consecutive loud 50 ms chunks while the warning plays → flush local playback, then `barge_in` to server). Cloned-voice session is opened at server start (1.7 s once).

| Gate item | Status | Evidence |
|---|---|---|
| Offline: protocol, cancel tail-dropping, templates, warner flow | ✅ | `uv run pytest -k "not transcripts"` → `33 passed` (fake TTS server emits post-Cancel audio tail; asserted never delivered; next request after Cancel delivered in full; templates contain no digits/brackets) |
| Warning plays in the cloned voice ≤ 3 s after the trigger turn | ✅ 2026-10-31 | `scripts/smoke_warning.py --barge none --runs 3`: caller's last word → first warning audio at the Receiver: **1536, 1665, 1678 ms**; trigger → audio 385/451/405 ms; TTS first audio 384/450/404 ms. `Begin.resolved_voice` = `01a19208-766c-7003-97c5-4f0cf646ade8` (your clone) in every run; `cloned: true`. 9.1–9.4 s of audio per warning. Sample: `docs/evidence/m3_warning_cloned_voice_sample.wav` |
| Barge-in stops it | ✅ 2026-10-31 | `--barge browser --runs 2` (barge-in sent 1.0 s after first frame): both runs `speaking → interrupted`; stop-playback command reached the Receiver in **1 ms**; run 1: TTS still generating, `Cancel` truncated the warning at 1.74 s; run 2: all 8.88 s already delivered, the flush still cut ~7.9 s of buffered playback. Events in SQLite (`barge_in`, `warn_first_audio`, `warn_tts_sent`). Turn-end → first audio in these two runs: 1915 and 1496 ms |

Bug found and fixed during the gate: the server delivers the warning ~8× faster than real time, so it was fully delivered ~1 s in while the browser kept playing for ~8 s more; barge-in originally only worked while the TTS request was open. Now it stays live until the estimated end of playback (`play_until`); regression test `test_barge_in_after_delivery_but_during_playback_still_flushes`.

Not verified (explicit):
- Real microphone capture and the browser voice-detector threshold (peak > 2500 for 3×50 ms): the in-app browser blocks the mic. Needs a manual check in Chrome with headphones.
- Subjective voice quality: listen to the sample wav.
- Latencies are local loopback with TTS-rendered audio; real mic audio and network add some.
- Barge-in via STT `SpeechStarted` (backup path) is wired and unit-tested but not exercised live; SpeechStarted arrives ~1 s into speech.
- A shared TTS session means a `Cancel` in one call would cancel text queued by another concurrent call. Fine for the demo and a sequential eval; do not run concurrent eval calls through the warner.

## M4 — Eval harness, tuning, scoreboard — ✅ built; first held-out run done, final run pending (see below)

Built: `eval/generate_scripts.py` (90 scripts written by `gemma-4-31b`, a different model family from the detector: 45 scam in 6 types, 30 legit in 5 types, 15 hard negatives; exact stratified split 54 train / 36 test), `eval/render_audio.py` (TTS-1, one session per voice, 36 test calls = 47.7 min of audio, ~$0.57), `eval/run_eval.py` (replays each call through the LIVE backend on two sockets, real time; errored/missing calls counted; only a complete run is published; `--rescore`), `eval/metrics.py`, `eval/tune.py`, `web/scoreboard.html`. Dataset check: `tests/test_eval.py` validates every script (alternating speakers, decisive index = a caller turn, null for non-scams).

**Tuning (train split only; test never touched):** replay of each train script's text through the detector, cached, then an offline sweep (`docs/evidence/m4_train_sweep_prompt_v1.txt`, `_v2.txt`).
- Prompt v1, threshold 70: recall 26/27, **2/18 legit false alarms**, 0/9 hard negatives. Failure analysis (`m4_train_failures_prompt_v1.txt`): any bank/courier caller read as "authority impersonation" (a real fraud-team call scored 85); cash-on-delivery read as a payment request; a job/deposit scam with no authority or threat stayed under threshold.
- Prompt v2 (one revision, general rules, not per-call): threshold 70 → **27/27 recall, 0/18 legit, 0/9 hard negatives**. Threshold fixed at **60** by the rule "lowest threshold with full recall and zero false alarms on train" (also warns before the ask more often, 81% vs 67% on train). Not changed after seeing any test result.

**Held-out test, run 1** (36 calls, `eval/results/test-final.json`, copies in `docs/evidence/m4_test_run1_*.json`; ran on the code BEFORE the independent-review fixes; re-scored with the stricter trigger→turn rule, 0 mappings changed):

| Metric | Result |
|---|---|
| Scam recall | **18 / 18** |
| False alarms, legit | **0 / 12** |
| False alarms, hard negatives | **0 / 6** |
| Caller's last word → first warning audio | median **1529 ms**, p90 1668 ms (n=17) |
| Warning TTS time to first audio | median 401 ms |
| Decisive turn → warning | median **−11.9 s** (warned *before* the labelled decisive turn ended in 11 of 17), p90 +2.1 s |
| Caught before the S5/S6 ask | **15 / 18** (83%); late: `investment_task_02`, `investment_task_04` (warned at the ask), `investment_task_06` (14 s late) |
| Errors / STT incidents / detector errors | 0 / 0 / 0 |

How to read it honestly:
- **Small test set.** 18/18 and 0/18 are consistent with true rates anywhere from ~82% to 100% recall and 0% to ~18.5% false alarms (95% bounds). The margins are thin: two scams only just triggered (cumulative risk 60.5 and 61.6 vs threshold 60) and the two highest-risk negatives peaked at 54.6 and 52.5.
- **"Decisive turn" is an LLM label** (gemma), usually later than where a person would first worry, so the median is negative. The latency that matters is the 1.5 s from the caller's last word to warning audio.
- **One warning never played** (`scam_digital_arrest_07`): triggered at turn 3, but the scripted receiver's reply began 0.4 s later and cancelled the warning before any audio (barge-in worked as specified), and the trigger fires once, so it was lost. 14 of 18 scam warnings were talked over by the scripted receiver at some point. Fix: a warning cut off before 3 s were heard is repeated when the person stops talking (max 3); `tests/test_tts_warner.py`.
- Because the code changed substantially afterwards (review fixes, re-arm), **the final published numbers will be a second full run on the final code** (decision #20).

## M5 — Takeover persona + evidence — ✅ gate passed on attempt 4 (3 failed attempts explained)

Built: `app/persona.py` (decoy-only persona; output guard blocks digits/addresses/invented number runs, replaced by a stall; 0.7 s reply debounce; yields when the caller talks; Take back = unmute first, cancel TTS, flush both tabs), `app/evidence.py` (regex on every caller turn + LLM pass once flagged, scanned over the unflagged opening too, every item validated against the turn text and a plausibility check), receiver page Hand over / Take back / live evidence panel, `scripts/smoke_takeover.py`.

Gate `scripts/smoke_takeover.py` (scripted scammer, `--seconds 150`), `takeover-d`, evidence `docs/evidence/m5_takeover_gate_pass_scripted.json`: **6 of 6 planted details captured** (UPI ID, account, IFSC, callback number, name, link) vs the required 3; 8 scripted caller turns / 9 persona replies; persona reply median **2.2 s** after the caller stops; **take-back while the persona was mid-sentence: cancel sent in 0 ms, 0 persona frames after 400 ms, the user's voice reached the caller again, UI state off**; no persona line contained a digit or address (1 unsafe LLM output replaced by the guard); every persona turn flagged `is_decoy` in SQLite; 0 STT incidents.

Failed attempts (kept in `docs/evidence/`, not hidden):
1. `takeover-a` (1 of 6): **harness bug**: the scammer bot sent audio only while speaking, so STT never saw the silence that ends a turn and finals arrived 9–28 s late. Fixed with a continuous-audio pump (what a real open mic does). Not a product fault: the eval runner already streams continuous audio (0.4 s finals).
2. `takeover-b` (3 of 6) passed the planted-detail bar but "FAIL"ed my own gate for two gate bugs (a 0 ms take-back is falsy; take-back not exercised mid-sentence).
3. `takeover-c` (1 of 6): the LLM scammer **refused** mid-call ("I cannot fulfill this request…"). An LLM scammer makes the gate non-deterministic, so the gate now uses the fixed script the brief asks for; `--adaptive` keeps the LLM scammer (informational).

Real defects found and fixed along the way: STT split one scammer line into two finals and the persona answered twice (now debounced); the claimed name/agency said before the call was flagged never reached the evidence (now scanned once flagged); evidence quality (victim's name labelled as the caller's, a bare title as an agency, an empty UPI value): plausibility checks + tests.

Limits to state plainly: in the scripted gate the scammer reveals details regardless, so it proves capture, safety, pacing and take-back, **not** that the persona can coax details out of a reluctant scammer. The adaptive runs (b: account, IFSC, callback elicited; a, c: little) show that varies. The bot reads the persona's text from events, it does not run STT on the persona's audio.

## M6 — Telegram alerts + 1930 report — ✅ gate met 2026-11-01 (arrival on your phone not confirmed by me)

Built: `app/alerts.py` (max 3 per call, slots for takeover and call-end are never spent on anything else, eval calls never alert, failures logged not raised), `app/report.py` (Markdown + ReportLab PDF, "DRAFT — review before filing" banner and footer on every page, next steps 1930 / cybercrime.gov.in / Sanchar Saathi / bank), `app/finalize.py` (report only for flagged calls), receiver-page report panel with the two questions only the user can answer, `/api/calls/{id}/report[.md|.pdf]`.

| Gate item | Status | Evidence |
|---|---|---|
| Every field filled from a call; PDF opens | ✅ offline | `tests/test_report_alerts.py`: seeded call fills all 11 evidence fields, quotes verified against the caller's actual words, PDF text read back with `pypdf` (banner on every page, number, UPI, IFSC, steps) |
| Alert content, rate limit, mock Telegram API | ✅ offline | 12 tests |
| **A real Telegram message arrives** | ✅ API accepted 4 messages | chat id found after you messaged the bot (`1524903598`); test message id 3; then a live scripted scam call (`e2e-scam-1`, mode live) sent warning, takeover and call-end alerts: ids 4, 5, 6, the last with the PDF attached. Telegram's API accepted them, and the user confirmed on 2026-11-01 that they arrived on their phone |
| Report from a live call | ✅ | `docs/evidence/m6_sample_complaint_draft.pdf/.md`: 3 pages, 8 captured details, banner on every page |

## Independent review (separate subagent, spec + repo only, no network)

22 findings (1 blocker, 5 high, 9 medium, 7 low). Fixed with tests: report UI missing (blocker); report/alert for any call that merely mentions a phone number; Telegram token would be logged by httpx; a long warning delayed the family alert and the next detection (hooks now isolated); detector starved by persona/evidence LLM calls (separate budget lane, fail-fast, 3 s total deadline); eval silently dropped errored calls and published incomplete runs; trigger→turn mapping; weak persona guard; invalid evidence never upgraded; unverified quotes in the report; alert slots; call never ended when a tab closed; ended call ids reusable; STT-restart clock offset; TTS Cancelled safety net; null-risk crash; dashboard page. Not fixed (documented limits): shared TTS session cancels across concurrent calls; no auth; receiver mic still reaches the caller while the warning plays (on speakers the scammer may hear it: use headphones); evidence LLM pass only after the call is flagged (LLM budget).


## Final state 2026-11-01

- Held-out test, run 2 on final code: recall 18/18, false alarms 1/12 normal + 0/6 hard negatives, warning 1.55 s after the caller stops (see README / VERIFICATION_REPORT.md; run 1 was 0/12 false alarms).
- Found by the e2e run and fixed: a warning could start after the person had already handed over (now skipped); `warned_at` now means audio actually started; agency is also captured by pattern; nested duplicate quotes dropped.
- Regression of every earlier gate on the final code and a fresh-clone install: see `docs/evidence/regression_final*/` and VERIFICATION_REPORT.md. Two scoring errors in my own scripts were found and fixed during it (a re-armed warning scored as a failure; barge-in timing when speech had already interrupted).
- Still needs a human: real microphone test in Chrome with headphones; confirm the Telegram messages arrived; listen to the cloned voice; rehearse docs/DEMO_SCRIPT.md; submit by 2026-11-07 18:00 IST. The AssemblyAI key and bot token were pasted into chat: rotate both after the hackathon.


## Second review round and final verification 2026-11-01

Second independent review: 17 findings plus unsupported claims. Fixed (all with tests): the caller side no longer receives
warning/takeover/persona/risk/evidence events; hang-up broadcasts at once, drops all audio, and the report arrives as its own
`report_ready` event; `ended_at` is written first so an id cannot be reused during finalize; no warning or alert after the
call ended; STT-restart clock offset taken at the new session's first byte (and reset on rejoin); persona may ask about UPI/IFSC
(only address shapes are blocked); LLM budget split in three lanes with a corrected token estimate (it was counting a third of a
character per token and starved the persona); tests are isolated from the network and the real DB; demo bot uses the fixed
script and reads events from a listener socket; DEMO_SCRIPT timing rewritten; organisation names are not person names; echo guard
counts from the first warning audio and a takeover click always cancels.

Found while verifying (all mine, all fixed): live M2 tests failed first on my own 429 burst, then on the detector's fail-fast under
a shared budget (tests now pace like a real call); the M5 gate failed on a take-back that was not mid-sentence and exposed the
token-budget bug above.

Final evidence: `docs/evidence/regression_final3/` (keys 5/5, 114 offline tests, M1, M3 warning, M3 barge-in), `regression_final4/`
(M2 10/10, M5 PASS), `m4_test_run3_final_code.json`: recall 18/18, false alarms 0/12 + 0/6, warning 1.46 s after the caller stops,
13/18 before the ask, 0 errors; `app/` identical to commit 69ce935. Screens driven in a real browser: answer, warning banner, chips,
hand over, take back, evidence panel, report panel with the two questions, PDF link; no Telegram alerts for test calls.

Still needs the user: real microphone test in Chrome with headphones; rehearse docs/DEMO_SCRIPT.md; submit by 2026-11-07 18:00 IST;
rotate the AssemblyAI key and bot token (both were pasted in chat).

## Option A: real phone call on speaker (Listener page) 2026-11-02

Built: `web/speaker.html` (one tab, two sockets: `caller` carries the laptop microphone = the phone's speaker, `receiver` carries events and the warning), `web/speakerlink.js` (half-duplex `MicGate`: the microphone stream is replaced by silence while Kavach's own voice plays out loud, plus a 400 ms echo tail, so Kavach never hears and answers itself; the warning only mutes the mic when it shares the speaker with the decoy), output-device pickers (warning to headphones, decoy to speakers), `web/demo/scammer_digital_arrest.wav` (94 s scammer-only sample), `docs/REAL_PHONE_DEMO.md`, `docs/demo/scam_call_script.txt`.

Verified in a real browser (microphone blocked in that browser, so the sample call stands in for it, through the same `feed()` path): both sockets connect, speech recognition up, risk 77 and Authority/Threat/Secrecy chips, warning in the cloned voice 1.56 s after the scammer's turn (104 chunks received), 46 mic chunks muted while it played on the shared output; hand over: decoy text, 313 audio chunks on the caller socket, 350 mic chunks muted while it spoke, evidence panel filled; take back and end call; report panel with PDF link (HTTP 200); no Telegram alerts (rehearsal mode). Offline: 3 Node tests for `MicGate`; suite 126 passed twice in a row (one earlier run had a single timing flake in `test_warning_cut_off_before_it_was_heard…`, which passes alone 3/3).

NOT verified: a real microphone and a real phone call (needs the user); the Telegram answer buttons pressed on a real phone (message with buttons was sent for call `btn-2`, nobody pressed them); that the laptop microphone picks up a phone speaker clearly enough, and the acoustic path of the decoy voice into the phone's microphone.
Limits (also in the guide): half-duplex (caller is not heard while the decoy speaks); one microphone hears the whole room, so the user's own voice counts as the caller's; no automatic barge-in (a Stop warning button instead); the takeover works through the air, not inside the call.

## Person's microphone muted toward the caller while the warning plays 2026-11-02

The warning already reached only the person's earpiece; now the person's microphone also does not reach the caller while it is audible (server: `CallRoom.on_audio`; speech recognition still hears the person, so speaking over the warning still interrupts it, and the call is two-way again at once). Receiver page tells the person ("Your microphone is muted to the caller while this plays"). Listener page (real phone on speaker): Kavach cannot mute the phone's own microphone, so it shows a red "press MUTE on your phone now" message and the guide says so.
Live check (`scripts/check_warning_mute.py`, evidence `docs/evidence/mute_during_warning_live_check.txt`): during a 9.04 s warning, frames from the person reaching the caller: before 416, DURING 0, after 344. Offline suite: 128 passed.

## Phone app (React Native / Expo) 2026-11-02

Built `mobile/` (Expo SDK 58, RN 0.88): setup (server address + access code, kept on the phone; no AssemblyAI key in the app), home (call code, rehearsal switch), protected-person screen (warning banner, risk meter and stage chips, hand over / take back / hang up, evidence, transcript, complaint draft with the two questions), test-caller screen, and a hidden WebView audio bridge (`web/bridge.html`) that owns mic and speaker and reuses the proven audio code. Python backend unchanged; server access code (`KAVACH_ACCESS_KEY`) gates `/api`, `/eval-audio` and the sockets (4 tests). The Telegram "take over" idea was removed: Telegram is notifications only.
Checked without a phone: `tsc` 0 errors; `npx expo export --platform android` exit 0; 6 logic tests pass; bridge page driven in a browser against the server with the sample scam (connected, detection, cloned-voice warning, persona replies + 778 audio chunks, evidence, call end, report). NOT checked: the app on a real phone (Expo Go), the WebView microphone on iPhone/Android over https, take back via the bridge, a cloud-hosted server (not set up).

## Family controls from Telegram, floating takeover, hosting files 2026-11-02

Server: the scam alert and takeover alert carry a "☎️ End the call" button (one token per call); a voice note sent to the bot is downloaded, decoded (PyAV, OGG/Opus → 16 kHz PCM) and played on Papa's phone through the app, even after the call was cut; the scammer neither hears it nor sees an event; Papa's microphone is muted toward the caller while it plays and other sounds are lowered. Only the configured chat can use any of it. `/setvoice <id>` in the same chat sets the takeover persona's voice (Papa's clone) without a restart. Found by the new tests: the End button had not been attached to alerts (fixed).
App: after the warning a red card floats over the screen, "Let Kavach take over".
Added `Dockerfile`, `.dockerignore`, `docs/HOSTING.md` (not built or deployed here: Docker is not installed on this machine, no host account used).
Checked: offline suite 146 passed; app `tsc` 0 errors, 7 app tests pass. NOT checked: End button and voice note pressed on a real phone; the floating card on a real phone; Papa's clone (needs his recording, consent and the dashboard); a cloud-hosted server.

## Voice samples recorded in the app 2026-11-02

New "My voice" screen: Papa and the son each enter a name, agree to the consent text, and record 10–30 s while reading a calm paragraph. A hidden page (`web/voicerec.html`) records and uploads the PCM to `POST /api/voices/{papa|son}` with the consent header; the server (`app/voices.py`) refuses missing consent, <10 s, >35 s, near-silence, and stores `data/voices/<person>.wav` + a JSON consent record (git-ignored). `GET /api/voices` lists, `/api/voices/<person>.wav` downloads, `DELETE` removes (all behind the access key).
AssemblyAI creates clones only in its dashboard (re-checked in its docs; no create endpoint), so the server cannot upload the sample itself: the owner downloads the WAV, makes the clone in the dashboard, then sends `/setvoice <id>` to the Telegram bot.
Checked: 8 new server tests; recorder page driven in a browser against a real server with a simulated microphone (11.6 s recorded, uploaded, 369,644-byte WAV stored with consent record; test files deleted); app `tsc` clean. NOT checked: recording with a real microphone on a phone; the Voice screen on a phone.

## App redesign, iPad and Mac (web) 2026-11-03

New design system (`mobile/src/ui.tsx`): darker navy theme, larger type and touch targets, shield logo drawn in code, status pills, section labels, a centred 560 px column so iPad and Mac windows look tidy. Home, Setup, Protect (big risk number, status pill), My voice, Test caller and the report panel use it. `supportsTablet` on; `AudioBridge.web.tsx` runs the same audio page in a microphone-enabled iframe so the app also runs in a Mac browser (`expo start --web`). Added react-dom, react-native-web, @expo/metro-runtime (`expo install`).
Checked: tsc 0 errors; 7 app tests; native (iOS+Android) and web exports exit 0; screens screenshotted in a browser at phone and desktop widths (Home, Setup, My voice). Test isolation fix: a KAVACH_ACCESS_KEY in the local .env had made 2 tests fail; the tests now clear it. Server suite 154 passed twice. NOT checked: an iOS device or simulator (Xcode not installed), the Protect screen with a live call after the redesign, the Mac web microphone path.

## No setup screen for demo users 2026-11-03

The app now opens straight on Home. Server address and access code are built in from `mobile/.env` (`EXPO_PUBLIC_KAVACH_SERVER`, `EXPO_PUBLIC_KAVACH_KEY`; git-ignored, template in `mobile/.env.example`); a server saved under "Server and access code" still wins. Anyone holding the app can extract the code: fine for a selected-members demo, replace with sign-in before public use. Server: CORS added so the Mac web app can call the API (still needs the key). Checked: web build opens on Home with no setup; tsc 0; 155 server tests pass. NOT checked: on an Android phone.

## Twilio demo call and simpler Home 2026-11-03

`app/twilio_call.py`: `POST /api/twilio/call` rings only `TWILIO_TARGET_NUMBER` (the owner's phone) through Twilio's REST API with a `<Connect><Stream>` back to `wss://<server>/twilio/stream/<one-time token>`; the stream handler converts 8 kHz mu-law to 16 kHz for AssemblyAI STT, answers in character with the LLM, speaks with TTS (voice `SCAMMER_VOICE_ID`, default aai-michael), sends mu-law frames back, clears the line when the person talks over it, hangs up after 240 s, one call at a time. `GET /api/twilio/status`. Steps in `docs/TWILIO_SETUP.md`.
App Home now: "Call my phone" (plus live transcript), "Protect my call", "My voice", and the old test items moved under "Developer tools"; the rehearsal Switch replaced by a plain toggle.
Checked: 5 new tests with a fake Twilio, STT, TTS and LLM (opening, listening at 16 kHz, reply to what was said, barge-in clear, one-time token, only one call, refusal cases); 160 server tests pass; tsc 0; Home screenshotted in a browser. NOT checked: a real Twilio call (no keys on the server yet), audio quality over a phone line, Indian-number calling rules. NOT built: Kavach protection (risk, warning, takeover) on this same call.

## First-time-user flow 2026-11-03

Removed the "Call my phone" button from the app: the Twilio demo call is triggered from chat only (API stays). New first launch: three welcome pages, then "Who will use this phone?" (I want to be protected / I look after someone), remembered on the phone (`src/prefs.ts`). Home differs by role: protected person gets "You are protected", one big "Protect my call", a "Your voice" card (shows Recorded / Not yet) and "How Kavach helps"; family gets what they can do from Telegram (end call, voice note, answer two questions, complaint PDF) and a voice card. Test items (code, rehearsal, test caller, show welcome again) sit under "Tester tools". Protect screen says "Kavach is ready, waiting for the call". Protect from Home now sends real Telegram alerts (rehearsal only in Tester tools).
Twilio: keys saved in local `.env` only. Read-only check of the Twilio account: valid Trial account, BUT it lists no phone numbers and no verified caller ids, so +17372508034 / +918809522106 are not set up there yet; a call would be refused. Not on Render either: the four TWILIO_* values must be added there. NOT checked: a real Twilio call.
Checked: tsc 0; welcome, role choice and Papa Home screenshotted in a browser at phone width. NOT checked: family Home, on a real phone.

## Back navigation 2026-11-03

User got stuck after choosing a role. Now: "Protected ▾ / Family ▾" at the top of Home reopens "Who will use this phone?" (with Cancel), role choice has "‹ Back" to the welcome pages, welcome pages have Back, Protect has "‹ Home" mid-call, Setup has Back, Android's hardware back button returns to Home (or cancels the switch) instead of closing the app. Checked in a browser: Papa Home → switch → Family Home → switch → Papa Home. NOT checked: Android hardware back on a phone.

## Demo scammer moved out of Kavach 2026-11-03

The user pointed out that ringing a phone has nothing to do with Kavach. `scambot/` is now its own small server (`uv run uvicorn scambot.server:app --port 8100`), run on the Mac; Kavach (`app/`, `render.yaml`, the Docker image) has no Twilio code or settings, and a test checks that. `/call` and `/status` answer only requests from this machine, so the public tunnel cannot be used to ring anyone, and the server can only ring TWILIO_TARGET_NUMBER. Twilio needs a public https address for the audio stream: the user opens that tunnel. 162 tests pass. NOT checked: a real Twilio call.
