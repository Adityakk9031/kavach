# Putting the Kavach server on the internet (for the phone app)

The phone app needs an **https** address for the server (phones only allow the microphone on https).
Keys stay on the server. The app only gets the address and the access code.

## Environment variables to set on the host
| Name | Value |
|---|---|
| `ASSEMBLYAI_API_KEY` | your AssemblyAI key |
| `KAVACH_WARNING_VOICE_ID` | the cloned warning voice id |
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` | the family bot and chat |
| `KAVACH_ACCESS_KEY` | a long random code; the app asks for it once |
| `PERSONA_VOICE_ID` | Papa's cloned voice (optional; can also be set from Telegram with `/setvoice <id>`) |

## Option 1: a cloud host (recommended for the demo)
Any host that runs a Dockerfile gives you an https address automatically (Render, Railway, Fly.io).
1. Push this repo to the host (the `Dockerfile` is in the repo root).
2. Set the variables above. The host provides `PORT`; the Dockerfile uses it.
3. Open `https://<your-host>/health` — it should say `"ready": true`.
4. In the phone app, Setup: server = that address, access code = `KAVACH_ACCESS_KEY`.
The database is a file; on free hosts it resets on redeploy, which is fine for a demo.

## Option 2: your laptop with a tunnel
Run `uv run uvicorn app.main:app --port 8000`, then expose it with a tunnel that gives an https address
(for example `cloudflared tunnel --url http://localhost:8000`). The laptop must stay on and awake during the demo.

## Papa's voice for the takeover
Record Papa saying a few calm sentences (with his consent), make the clone in the AssemblyAI dashboard, and then
either set `PERSONA_VOICE_ID`, or send `/setvoice <voice id>` to the Telegram bot. Text-to-speech there is English only.
