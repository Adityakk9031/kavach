# API notes (verified 2026-10-31)

Facts below were read from the live docs on 2026-10-31. Each has its source.
If code and this file disagree, re-check the doc, then fix whichever is wrong.

Short source keys used below:

| Key | URL |
|---|---|
| TTS-QS | https://www.assemblyai.com/docs/tts/getting-started/quickstart |
| TTS-VOICES | https://www.assemblyai.com/docs/tts/voices |
| TTS-CLONE | https://www.assemblyai.com/docs/tts/cloned-voices |
| TTS-FRAMES | https://www.assemblyai.com/docs/tts/message-frames |
| TTS-LIMITS | https://www.assemblyai.com/docs/tts/limits |
| TTS-HTTP | https://www.assemblyai.com/docs/tts/api-reference/http-api/overview |
| TTS-TOKEN | https://www.assemblyai.com/docs/tts/authenticate-with-a-temporary-token |
| TTS-PROMPT | https://www.assemblyai.com/docs/tts/prompting-guide |
| TTS-WSBASICS | https://www.assemblyai.com/docs/tts/connect-parameters |
| TTS-BLOG | https://www.assemblyai.com/blog/text-to-speech-api |
| STT-QS | https://www.assemblyai.com/docs/streaming/getting-started/transcribe-streaming-audio |
| STT-MODELS | https://www.assemblyai.com/docs/streaming/select-the-speech-model |
| STT-LANG | https://www.assemblyai.com/docs/faq/language-support-for-real-time-transcription |
| STT-MSGS | https://www.assemblyai.com/docs/streaming/message-sequence |
| STT-TURN | https://www.assemblyai.com/docs/streaming/turn-detection |
| STT-LIMITS | https://www.assemblyai.com/docs/streaming/rate-limits |
| STT-TOKEN | https://www.assemblyai.com/docs/streaming/authenticate-with-a-temporary-token |
| STT-MULTI | https://www.assemblyai.com/docs/streaming/label-speakers-and-separate-channels |
| STT-ML | https://www.assemblyai.com/docs/streaming/multilingual-transcription |
| STT-LLM | https://www.assemblyai.com/docs/streaming/guides/real_time_llm_gateway |
| GW-QS | https://www.assemblyai.com/docs/llm-gateway/quickstart |
| GW-CHOOSE | https://www.assemblyai.com/docs/llm-gateway/choose-a-model |
| GW-MODELS | https://llm-gateway.assemblyai.com/v1/models (public JSON, queried live) |
| GW-SO | https://www.assemblyai.com/docs/llm-gateway/structured-outputs |
| GW-LAT | https://www.assemblyai.com/docs/llm-gateway/improve-latency |
| TG | https://core.telegram.org/bots/api#sendmessage |
| PYPI | https://pypi.org/pypi/assemblyai/json |

---

## 1. Python SDK

- Package `assemblyai`. TTS is in the Python SDK **from release 1.8.2**. [TTS-QS]
- Latest on PyPI today is **1.8.2**, `requires_python >=3.8`. [PYPI] → pin `assemblyai>=1.8.2`.
- TTS classes: `aai.TextToSpeech` (HTTP, `.synthesize()`), `aai.TTSConfig`, `aai.TTSSession` (sync WebSocket), `aai.AsyncTTSSession` (asyncio twin), `aai.TTSContainer`, error `aai.TTSError`. [TTS-QS, TTS-CLONE]
- Session methods: `speak(text)` (Generate+Flush, yields audio until FlushDone), `generate()`, `flush()` → `flush_id`, `audio(flush_id)`, `cancel()`, `keep_alive()`. `session.begin`, `session.termination`. [TTS-QS]
- The SDKs turn **word boundaries off** unless asked; on the raw wire they are on by default. [TTS-QS]
- Streaming STT classes (v3): `from assemblyai.streaming.v3 import RealTimeTranscriber, RealTimeTranscriberOptions, RealTimeParameters, RealTimeEvents, RealTimeError, BeginEvent, TurnEvent, TerminationEvent`. Events registered with `client.on(RealTimeEvents.Turn, fn)`. [STT-QS]
- LLM Gateway: `aai.LLMGateway().chat.completions.create(...)`, or the OpenAI SDK with `base_url="https://llm-gateway.assemblyai.com/v1"`. [GW-QS]
- **Decision for Kavach:** use the raw WebSocket protocols (with `websockets` ≥ 14) for TTS and STT inside our asyncio server, because we need per-frame control (Cancel tail dropping, timing of first `Audio`, `SpeechStarted`). The SDK is used for the M0 key check and voice listing. Recorded in DECISIONS.md.

## 2. Text-to-Speech (AssemblyAI TTS-1)

### Model, languages, controls
- Model id `assemblyai-tts-1`. [TTS-QS headers `x-tts-model`]
- Languages: **English, Spanish, German, Italian, Portuguese, French** only. `language` takes the full English name (`english`), not a code. **No Hindi.** ✅ prompt fact confirmed. [TTS-VOICES, TTS-BLOG]
- **No SSML, no speed parameter, no emotion controls** today ("coming soon"). Punctuation shapes delivery: `?` rising tone, `!` emphasis, `,` / `…` short pause (several in a row don't lengthen it), ALL-CAPS word = stress, `--` at end = cutoff, fillers written literally. ✅ confirmed. [TTS-BLOG FAQ, TTS-PROMPT]
- Server normalizes currency, phone numbers, dates, emails, URLs. Digit-by-digit: write `1-9-3-0`. [TTS-PROMPT] → the prompt's "write numbers in words" rule still works; `1-9-3-0` is the doc-recommended alternative. We'll use words ("one nine three zero") per the prompt and verify by ear.
- Square/curly/angle brackets are read aloud — strip `[pause]`-style tags before sending. [TTS-PROMPT]

### WebSocket API
- URL: `wss://tts.us.assemblyai.com/v1/ws` (EU: `tts.eu.assemblyai.com`). Auth: API key in `Authorization` header (raw or `Bearer `), or `token=` query param for browsers. [TTS-QS, TTS-TOKEN]
- Query params: `voice_id`, `language`, `sample_rate`, `encoding`, `inactivity_timeout`, `extend_biometric_consent`, `word_boundaries`. [TTS-QS, TTS-FRAMES Begin]
- `sample_rate` ∈ {8000, 16000, 22050, **24000** (default), 44100, 48000}; `encoding` `pcm_s16le` (default), `pcm_mulaw`, `pcm_alaw` (+ `mp3` on HTTP). Audio is mono, raw, no header. [TTS-WSBASICS, TTS-HTTP]
- Frame names are **PascalCase** (the prompt writes `cancel`; the wire is `{"type":"Cancel"}`). Conflict noted, docs win.
  - Client → server: `Generate {text}`, `Flush`, `Cancel`, `KeepAlive`, `Terminate`. [TTS-FRAMES]
  - Server → client: `Begin {id, expires_at, configuration}`, `Audio {audio(base64), flush_id}`, `FlushDone {flush_id, audio_duration_ms}`, `WordBoundaries {flush_id, audio_start_ms, words[{word,start,end,confidence}]}`, `Cancelled {audio_duration_seconds}`, `Termination {...}`, `Error {error_code, error, error_type, retryable, param, retry_after_seconds}`. [TTS-FRAMES]
- Server speaks first: `Begin` or `Error`. Unknown voice → `Error` 3012 `voice_not_found` before Begin. [TTS-VOICES]
- `Generate` text is joined **exactly as sent** — keep spaces at fragment edges. Short text is silent until `Flush`. [TTS-FRAMES]
- `Flush` concludes a request → exactly one `FlushDone` per Flush. `FlushDone` = delivered, not played. [TTS-FRAMES]
- **`Cancel` (barge-in):** stops in-flight synthesis, discards unflushed text and queued flushes; server answers `Cancelled`. `Audio` frames already in flight may arrive **between Cancel and Cancelled — drop them**, and stop already-scheduled playback buffers. Next request gets a new, possibly skipped, `flush_id`; read it from frames. You need not wait for `Cancelled` before sending the next `Generate`. [TTS-FRAMES]
- `Audio` chunks ≈ 80 ms at 24 kHz; never empty; a request's audio never interleaves with another's. [TTS-FRAMES]
- Word timestamps: `WordBoundaries` per request after its `FlushDone`, best-effort; none for a cancelled request. ✅ confirmed. [TTS-FRAMES]
- Session max **3600 s**; idle close after **120 s** with no frame either way (`KeepAlive` resets it; it is **not** a warm-up). [TTS-FRAMES, TTS-LIMITS]
- Open the session **when the call starts** — a cloned/catalog voice loads on session open, so the first audio is slower if text arrives right after `Begin`. There is no pre-warm endpoint. [TTS-VOICES, TTS-CLONE, TTS-FRAMES]

### Limits [TTS-LIMITS]
| Limit | Value |
|---|---|
| Chars per `Generate` | 2000 (close 3006) |
| Unsynthesized backlog | 8000 chars (close 3010) |
| Text intake pacing | ~100 chars/s sustained after first 1500 + 1000 burst (no close, just slower) |
| Control frames (Flush/KeepAlive/Cancel/empty Generate) | 20/s sustained, burst ~60 (close 3010) |
| Unread audio | 300 s or 16 MiB (close 3011) |
| **New WS sessions / minute** | **5 on free plan**, 100+ paid; counted separately from STT (close 3009 before Begin) |
| HTTP API text | 1–5000 chars/request |
| **HTTP requests / minute** | **50 free**, 1000+ paid (429 `rate_limited`) |
✅ prompt fact "free-tier session rate limits are low" confirmed.

### HTTP API [TTS-HTTP, TTS-QS]
- `POST https://tts.us.assemblyai.com/v1/speech`, header `Authorization: <key>`, body `{text, voice_id, language?, container: "wav"|"raw", encoding?, sample_rate?, stream: false}`.
- Response headers: `x-tts-model`, `x-tts-voice-id`, `x-tts-language`, `x-tts-encoding`, `x-tts-sample-rate`, `x-tts-billed-characters`, `x-tts-audio-duration-ms`, `x-tts-voice-expires-at` (cloned only).

### Voices [TTS-VOICES]
- `voice_id` takes a library slug (`aai-audrey`), a UUID, or a slug of your own cloned voice (lowercase). Default `aai-jane`.
- 11 built-in voices: `aai-jane, aai-alba, aai-anna, aai-charles, aai-eve, aai-george, aai-jean, aai-mary, aai-michael, aai-paul, aai-vera`.
- Catalog English voices (selection) with accents: Audrey/Sara/Peter/Titus/Ewald (US), Buford/Carrie/Nancy/Yasmin/Percival (UK), Steven (AU), Troy (Scottish), Gunnar ("older man, fairly slow pace"), Abdiel/Dorsey (older men). Thousands more in the dashboard catalog. **No Indian-English voice is listed among the starters** — check the dashboard catalog for Indian-accent voices before rendering eval audio.
- `Begin.configuration.voice_id`, `.resolved_voice{voice_id, language}`, `.voice_expires_at`.

### Voice cloning [TTS-CLONE]
- **Dashboard-only creation** (voice catalog → "Create voice clone"). ✅ confirmed. Delete via dashboard or `DELETE /v1/voices/{id}`.
- 10–30 s of one speaker, recorded in the voice's language; WAV, close mic (AirPods fine), quiet room; speak in the tone you want (calm).
- Requires speaker consent attestation **and** the account accepting biometric data terms at https://www.assemblyai.com/dashboard/settings/data-controls (else 3006 `biometric_terms_not_accepted`).
- Cloned voice usable **60 days** after consent (`voice_expires_at`); renew with `extend_biometric_consent=true`. Expired → `voice_expired`, must re-clone.
- A clone belongs to its **data zone** (US voice only on `tts.us...`).
- Just-created voice may return 3014 `voice_not_paired` briefly; retry shortly.
- Prompt's note "Voice Agent API can't use cloned voices": **not checked** (not needed — persona is our own loop anyway).

### Temporary tokens [TTS-TOKEN]
- `GET https://token.us.assemblyai.com/v1/token?product=tts&expires_in_seconds=1..600` with API key → `{"token": ...}`; browser passes `token=` query param. Mint one per connection.
- Kavach's browsers never connect to AssemblyAI directly (all audio is relayed by our backend), so tokens are not needed in v1. Recorded in DECISIONS.md.

### Pricing [TTS-BLOG]
- $15 per 1M characters, cloning included; billed on characters sent (incl. spaces). Blog claims ~90 ms time-to-first-audio.

## 3. Streaming Speech-to-Text (v3)

- URL: `wss://streaming.assemblyai.com/v3/ws?<params>`; auth: key in `Authorization` header, **no `Bearer`**. [STT-QS]
- Temp token: `GET https://streaming.assemblyai.com/v3/token?expires_in_seconds=60` (SDK `client.create_temporary_token`). Not needed for Kavach v1 (server-side). [STT-TOKEN]
- Models (`speech_model`): [STT-MODELS]
  - `universal-3-6-pro` (**default**, "Fastest", 32 languages, best entity accuracy, `SpeechStarted`, prompting, keyterms)
  - `universal-3-5-pro`
  - `universal-streaming-english` (English only, cost-effective) ✅ prompt fact confirmed — the model exists and is English-only.
  - `universal-streaming-multilingual`
- English steering on U3.6 Pro: `language_codes=["en"]` connection param. [STT-ML] (Universal-3.5 Pro list includes Hindi — useful for the Hindi roadmap. [STT-LANG])
- Audio: **binary** frames of raw PCM, default 16 kHz s16le mono, ~50 ms chunks (800 samples). Also `ogg_opus`, `opus`, `aac`. Faster-than-real-time allowed but **throttled to ~1.25× real time**; >5 min buffered → close 3007. [STT-MSGS]
- Client JSON frames: `UpdateConfiguration`, `ForceEndpoint`, `KeepAlive`, `Terminate`. [STT-MSGS]
- Server frames: `Begin {id, expires_at, configuration{model, mode, ...}}`, `SpeechStarted {timestamp, confidence}` (**U3.6 Pro only**; Universal-Streaming skips it), `Turn {turn_order, end_of_turn, turn_is_formatted, transcript, end_of_turn_confidence, words[{start,end,text,confidence,word_is_final}], utterance}`, `SpeakerRevision`, `Heartbeat`, `Termination`, `Error`. [STT-MSGS]
- Each `Turn` re-transcribes the whole turn — **replace, don't append**. Final has `end_of_turn: true` and is formatted. [STT-TURN]
- `SpeechStarted` is emitted only once a real transcript exists → docs call it **a reliable barge-in signal**. [STT-TURN]
- Turn detection: `mode` ∈ `min_latency | balanced | max_accuracy`; `min_turn_silence` (128/128/512 ms) and `max_turn_silence` (640/1280/2560 ms). **Entity-aware endpointing** keeps phone numbers / IDs / emails in one turn (p90 EOT latency 0.83 → 1.64 s on held turns). Both updatable mid-stream. [STT-TURN]
- Unknown query params are **ignored silently** — always check `Begin.configuration.model`. [STT-MSGS]
- Multichannel: docs recommend **one session per channel**. ✅ matches our per-party tap design. [STT-MULTI]
- Rate limit: **new sessions/minute: 5 free, 100+ paid** (paid auto-scales). Over limit → `Error` "Too many concurrent sessions", close 1008. Only opening counts. [STT-LIMITS]
- Billing is per session **wall-clock duration**; un-terminated sessions auto-close after 3 h and are billed for all of it → always send `Terminate`. [STT-LIMITS]
- Optional server-side LLM per turn: `llm_gateway` connection param (JSON config with `{{turn}}` placeholder) → `LLMGatewayResponse` frames. [STT-LLM] Possible latency optimization; v1 calls the Gateway ourselves to keep a rolling window.
- Keyterms: connection param **`keyterms_prompt`**, a list of up to 100 words/phrases (string-typed in the query, JSON-encoded). Contextual prompt param `prompt` (U3.x Pro). [STT-SPEC https://www.assemblyai.com/docs/streaming/api-spec/streaming-websocket]
- `language_codes` in the query string is a **JSON-encoded string**, e.g. `language_codes=["en"]` (spec example `'["en", "es"]'`), U3.5/U3.6 Pro only; `hi` is an accepted code (Hindi roadmap). Updatable mid-stream with `UpdateConfiguration`. [STT-SPEC, STT-ML]

## 4. LLM Gateway

- Base URL `https://llm-gateway.assemblyai.com/v1` (EU: `llm-gateway.eu.assemblyai.com`), `POST /chat/completions`, header `authorization: <API key>`. **OpenAI-compatible** ✅ confirmed. [GW-QS]
- Gateway auto-retries 5xx; supports model fallbacks (`fallback_config`), structured outputs (`response_format: {type: "json_schema", json_schema: {name, schema, strict}}`), and `post_processing_steps: [{"type": "json-repair"}]`. [GW-QS, GW-SO]
- Reuse one `httpx.AsyncClient` (keep-alive) for every call. [GW-LAT]
- `GET /v1/models` is public, returns `supported_parameters`, `available_regions`, `retirement_date`, and benchmark latency/quality per bucket. [GW-CHOOSE]
- Live query today, 30 s bucket, sorted by p50 latency (information-extraction quality / p50 s / p95 s / supports `response_format`): [GW-MODELS]

| model (reasoning) | IE quality | p50 | p95 | JSON schema |
|---|---|---|---|---|
| qwen3.5-4b-32k-fast | 80 | 0.28 | 0.57 | ❌ |
| mercury-3 (none) | 85 | 0.39 | 0.59 | ✅ |
| gemini-2.5-flash-lite | 74 | 0.70 | 1.07 | ✅ |
| **gpt-6-luna (none)** | **88** | **0.87** | **1.18** | ✅ |
| claude-haiku-4-5-20251001 | 85 | 0.99 | 1.71 | ✅ |
| claude-sonnet-5-5 | 93 | 1.44 | 3.62 | ✅ |

  → Detector/extractor default `gpt-6-luna` with `reasoning_effort: "none"`, fallback `mercury-3`. Script generation (offline) `claude-sonnet-5-5` — a different model family from the detector so the eval isn't graded by the model that wrote it. All are config values. Benchmarks are the vendor's; we re-measure on our own prompts in M2.

## 5. Telegram Bot API [TG]
- `POST https://api.telegram.org/bot<token>/sendMessage` with JSON `{chat_id, text, parse_mode?, disable_notification?}`; `text` 1–4096 chars. Response `{ok, result | description}`.
- `sendDocument` (multipart) can attach the PDF report.
- Chat id discovery: user messages the bot once, then `getUpdates` shows `message.chat.id`.

## 6. Conflicts with the build prompt

| Prompt said | Docs say | Resolution |
|---|---|---|
| Send `cancel` | Frame is `{"type": "Cancel"}` (PascalCase) | Use `Cancel` |
| English STT model is `universal-streaming-english` | It exists, but default `universal-3-6-pro` is faster, has better entity accuracy, entity-aware endpointing, and `SpeechStarted` (the doc-endorsed barge-in signal) which Universal-Streaming lacks | Default `universal-3-6-pro` + `language_codes=["en"]`; `universal-streaming-english` kept as a config fallback; compare both in M1 |
| Write numbers in words | Words work; docs also offer `1-9-3-0` for digit-by-digit | Keep words, verify by listening |
| Browser should use temp tokens | Correct, but our browsers never talk to AssemblyAI | No browser token needed in v1 |
