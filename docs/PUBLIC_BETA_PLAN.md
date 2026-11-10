# Kavach public beta: what changed and why

## 1. Languages (verified live on 2026-11-10)
AssemblyAI TTS speaks English, Spanish, German, French, Italian and Portuguese. Streaming speech-to-text (Universal-3.6 Pro)
accepted `es`, `pt` and `en`. **Hindi has speech-to-text but no text-to-speech yet**, and the warning must be spoken, so Hindi waits.

Launched: **English, Spanish, Portuguese** (large scam-call populations, both fully supported end to end).
Next, one `Pack` each in `app/lang.py`: German, French, Italian. Then Hindi when TTS supports it.
Per family: STT language, TTS language, warning text, takeover persona (made-up older person, per language), Telegram texts,
number-word guard. Not yet translated: the PDF report (English) and the app's own screens (English).

## 2. Voices (the "unfamiliar voice" problem)
- The takeover now speaks in the **parent's own cloned voice**, and the warning in the **son's**.
- `POST /v1/voices` (multipart `file`, `name`, `language`, `consent_attested`, header `Idempotency-Key`) exists and creates a
  clone, so cloning is now **inside the app**: up to 3 takes (each with its own text), joined to 30 s, then "Make my voice".
  *Not yet run against the real endpoint with a real recording* (needs the account's biometric terms accepted and a consented
  sample); the request shape is covered by a mock test, and a failure shows the reason in the app and falls back to a library voice.
- Cloned voices expire after 60 days unless consent is renewed (`extend_biometric_consent`): renewal is **not built yet**.
- Deleting a recording deletes the clone at AssemblyAI.
- The persona prompt now asks for real-person speech: small reactions, pauses, trailing off, one filler at most, plain words.

## 3. No Shizuku, no Developer mode (Standard mode)
Android blocks call-audio capture and in-call playback for normal apps. What works for everyone:
| Need | Standard mode (default) | Pro mode (optional, unchanged) |
|---|---|---|
| Hear the caller | Mic with the call on **speaker** (card says so) | Shizuku: direct, no speaker |
| Hang up from Telegram | `TelecomManager.endCall` (normal "answer phone calls" permission) | Shizuku |
| Detect a call, show the card | Accessibility service (kept in this build) | same |
| Warn the parent | Played through the speaker | privately in the earpiece |
| Takeover voice reaches the caller | Through the speaker and mic (lower quality) | injected into the call |
Everything in Standard mode needs only normal permission prompts, no Developer options.
**Honest limits:** speaker mode means the scammer can hear Kavach's warning, and takeover audio is noisier. Next step is to
replace the Accessibility service with a foreground service plus the default-dialer role (call screening, speaker control),
which also makes Google Play and Play Protect easier. That needs Kotlin changes that can only be tested on a phone.

## 4. Accounts, families, Telegram
- Son/daughter: email + password sign-up (scrypt-hashed), choose the language and what to call the parent.
- Parent's phone: joins with a 6-digit code (10 min, single use, rate-limited) and gets its own token.
- One Telegram bot for everyone: "Connect Telegram" opens `t.me/<bot>?start=<one-time token>`, linking that chat to the family.
- Every call, report, voice note and End-call press is scoped to its family; another family's call id is a 404.
- The original single-household setup (shared access key, `.env` chat id) still works as the "default" family.
- Not built: email verification, password reset, phone-number login, WhatsApp channel, abuse monitoring.

## 5. Before the public can use it
1. **Deploy**: push the server and move Render off the free plan. The free plan has no disk, so every deploy would delete all
   accounts. `render.yaml` now asks for a Starter plan with a 1 GB disk at `/data` (about $7/month).
2. Accept AssemblyAI's biometric-data terms in the dashboard (needed for cloning).
3. Build the app with `eas build --profile beta` (no access key inside).
4. Publish a privacy policy and a deletion contact; the consent wording is in the app and server.
5. Rotate the keys that were used during the hackathon.
