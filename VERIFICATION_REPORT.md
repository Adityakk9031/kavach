# Verification report

Written 2026-11-01. Final code = commit 69ce935 (nothing under app/ changed after it). Every claim names the evidence. "Pass" means I ran it and recorded the output;
anything I could not run is listed under *Not verified*. Full chronological log with the failed attempts:
[PROGRESS.md](PROGRESS.md). Raw outputs: [docs/evidence/](docs/evidence/).

## Result per feature

| Feature | Status | Evidence |
|---|---|---|
| **F1** Live listening and scam-stage detection | **Pass** | Live streaming STT per party (`m1_smoke_call.txt`: 6/6 finals, 0.976 word match, ~0.4 s to final). 10 fixed transcripts, 5 scam / 5 legit: 10/10 (`regression_final2/m2_live_transcripts.txt`). Held-out test: recall 18/18 in two runs. Risk is cumulative with hysteresis (8 unit tests); trigger = threshold or action-stage-with-pressure-stage. UI chips and risk meter shown in the browser. |
| **F2** Family-voice warning + barge-in | **Pass** (mic path not verified) | Cloned voice resolved in every run (`01a19208…`). Caller's last word → first warning audio **1.3–1.9 s** over 8 live runs (target ≤ 3 s; `regression_final2/m3_warning.txt`, `m3_warning_cloned_voice_sample.wav`). Barge-in: stop command reaches the receiver in ~1 ms, including already-delivered audio; a warning cut off before 3 s were heard is repeated (`m3_barge_rerun.txt`). |
| **F3** Takeover persona + evidence | **Pass** (scripted scammer) | `m5_takeover_gate_pass_scripted.json`: 6/6 planted details captured over 150 s, persona replies 2.2–3.2 s after the scammer stops, take-back mid-sentence cancels in 0 ms with 0 stray frames and the user's voice reaching the caller, no digit/address in any persona line, every persona turn flagged decoy in SQLite. 3 earlier failed attempts documented. |
| **F4** Family alert (Telegram) | **Pass** (receipt confirmed by the user on their phone, 2026-11-01) | Live call sent 3 messages (warning, takeover, call-end with PDF): Telegram message ids 4, 5, 6 (`e2e-scam-1` events). Rate limit: ≤ 3 per call, takeover and call-end slots never spent on stage updates; eval calls never alert (12 offline tests). |
| **F5** 1930 complaint draft (md + pdf) | **Pass** | `m6_sample_complaint_draft.pdf/.md` generated from the live call: 3 pages, DRAFT banner on every page, caller number, stages, UPI/account/IFSC/phone/link/amount, verified timestamped quotes, next steps (1930, cybercrime.gov.in, Sanchar Saathi, bank). The money/OTP questions are asked in the UI. Never submits anything. A real PDF opened with `pypdf`; **not** opened by eye by me. |
| **F6** Eval harness + scoreboard | **Pass, with an honest caveat** | 90 scripts, 36-call held-out test, tuned on train only, scoreboard shows all required metrics, confusion matrix and per-call audio/transcript (screenshot taken). Results below. |

## Held-out test results (36 calls, `docs/evidence/m4_test_run{1,2,3}*.json`)

Same frozen prompt and threshold (60); the code changed between runs. **Run 3 is on the final code**: `app/` is
identical to commit `69ce935`.

| | Run 1 (`f549bd5`) | Run 2 (`bc5bf5a`) | **Run 3 (`69ce935`, final)** |
|---|---|---|---|
| Scam recall | 18/18 | 18/18 | **18/18** |
| False alarms, normal calls | 0/12 | 1/12 | **0/12** |
| False alarms, hard negatives | 0/6 | 0/6 | **0/6** |
| Caller's last word → warning audio, median / p90 | 1529 / 1668 ms | 1552 / 1625 ms | **1461 / 1571 ms** (n=11: in 7 calls the first attempt was cut off by the scripted reply and repeated) |
| Warning voice first audio, median | 401 ms | 398 ms | **401 ms** |
| Caught before the OTP/money ask | 15/18 | 12/18 | **13/18** |
| Errors / STT incidents / detector errors | 0/0/0 | 0/0/1 | **0/0/0** |

The system is a small LLM at the margin and not deterministic: the same frozen system on the same audio gave 0, 1 and 0
false alarms on the 12 normal calls. The one false alarm (run 2) was a genuine bank fraud-team call that says "I am
blocking your debit card immediately" (peak risk 54.6, 78.2, then 7). The test set is small (95% intervals: recall
about 82–100%; false alarms about 0–27%). Margins are thin (run 3: top non-scam peaks 50.8 and 45.5 vs threshold 60;
weakest scam peaks 54.6 by the stage rule and 61.6). Audio is synthetic. See README "Results".

## Regression of earlier gates on the final code (`docs/evidence/regression_final*/`)

| Gate | Result |
|---|---|
| M0 keys | 5/5 OK (STT, TTS library voice, LLM Gateway, cloned voice, Telegram) |
| Offline tests | 114 passed; they are genuinely offline now (no network, no real database) |
| M1 relay + STT | pass: 6 finals, ~0.4 s, 0.976 match |
| M2 live transcripts | 10/10 on the final code (`regression_final4/`). Earlier passes failed for reasons that were mine: LLM rate-limit 429s from my own burst of tests, then the detector's fail-fast under a shared budget; the tests now pace themselves like a real call |
| M3 warning | pass: 1430 / 1452 / 1495 ms (first regression pass mis-scored a correctly re-armed warning as a failure; scoring fixed) |
| M3 barge-in | pass (2 of 3 runs were already stopped by the receiver's own speech; 1 by the explicit barge-in in 1 ms) |
| M5 takeover | pass on the final code (`regression_final4/`, `m5_takeover_gate_pass_final_code.json`): 5 of 6 planted details (3 required), take-back mid-sentence in 1 ms, 0 stray frames, persona reply median 2.1 s. An earlier pass failed my own gate and exposed a token-budget bug (the persona fell back to stall lines); fixed |
| Fresh clone | `git clone` → `uv sync` → keys 5/5 → 101 tests → server serves all pages and the saved results |

## Independent review

Two rounds by a separate subagent given only the spec and the repo (static reading, no network). Round 1: 22 findings;
round 2: 17 findings plus claims that the evidence did not support (a mislabelled "final code" run, a mis-described test
failure, a demo script that would have broken the warning, a demo bot that was unreliable, the scammer's screen receiving
Kavach's internals, audio still playing after hang-up, a persona filter that stopped it asking about UPI IDs). All real
HIGH and MEDIUM items from both rounds were fixed with tests and re-verified live. Not fixed, on purpose: the shared TTS
session, no authentication, the stage-update alert that can never fit under a 3-per-call cap.

## Not verified (read this)

- **Real microphone capture** and the browser's voice detector in Chrome with headphones (the user will do this). The
  browser panel I can drive blocks the mic, so every live test used TTS-rendered audio streamed over WebSockets. Every
  screen except the mic path was exercised in a real browser: answering, warning banner, chips, hand-over, evidence,
  take back, report panel.
- **How the cloned voice sounds** to the user.
- **Real telephony.** It is a simulator.
- **The persona coaxing details from a reluctant scammer**: the gate scammer reveals them; an adaptive LLM scammer got
  1-3 of 6, varying by run.
- A 36-call test set cannot separate a real 95% recall from 85%, and the audio is synthetic.

## Known limitations

English only; no authentication on call ids; one shared TTS session (a barge-in on one call would cancel another
concurrent call's warning); the receiver's microphone still reaches the caller while the warning plays (use
headphones); the evidence LLM pass only runs once a call is flagged; the "Credential request" stage can be tagged
generously by the small model.
