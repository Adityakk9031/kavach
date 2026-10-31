# Kavach: 3-minute demo script

Everything below happens on one laptop. You play the protected parent in the browser; a bot plays the scammer.
Total: 3:00. The "say" lines are meant to be short.

## Before you start (5 minutes, not part of the 3)

1. Terminal 1: `uv run uvicorn app.main:app --port 8000`. Wait for the log line `warning session ready ... voice=01a19208…`
   (your cloned voice is loaded; the first warning is fast because of it).
2. **Wear headphones.** The warning plays through the Receiver tab; speakers would leak it into the mic and cut it off.
3. Chrome tab 1: `http://localhost:8000/web/receiver.html?call=demo1`. Click **Answer call**, allow the microphone.
   The status line should show `receiver STT: universal-3-6-pro`.
4. Chrome tab 2 (keep it ready): `http://localhost:8000/web/scoreboard.html`.
5. Your phone is on the table with Telegram open on the bot chat (the alerts arrive there).
6. Terminal 2, ready but not started:
   `uv run python scripts/smoke_takeover.py --demo --call-id demo1 --seconds 150`
7. Use a fresh call id (`demo2`, `demo3`…) for every take: a finished call id is refused.

## The 3 minutes

| Time | What happens on screen | Say |
|---|---|---|
| 0:00 | Face camera or the title slide | "Every day, someone's parent gets a call from a fake policeman. Google, Truecaller and Airtel can show a banner or beep. Kavach does something else." |
| 0:10 | Press Enter in Terminal 2. The bot starts: "This is Inspector Vikram Rathore from the Mumbai Cyber Crime Cell…" Receiver tab: transcript appears live, stage chips light up one by one (Authority, Threat, Secrecy), the risk bar climbs | "This is a digital-arrest scam call. Kavach listens to the caller's audio, separately from mine, and tracks the scam stages as they happen." |
| 0:35 | The bar crosses the line. **The warning plays in your headphones in your cloned voice** and a banner shows "Kavach is speaking" | "It took about a second and a half from the end of his sentence. That is my voice, a clone I made with consent. Not a beep." |
| 0:50 | Say out loud, over the warning: "Wait, who is this?" The warning stops mid-sentence; banner says "Warning stopped: you spoke" | "And if my parent starts talking, it stops instantly. It never talks over them." |
| 1:00 | Click **Hand over to Kavach** | "Now my parent can just hand the call over." |
| 1:05 | The persona speaks slowly ("Ah, sorry, I was not hearing properly…"). The bot scammer keeps talking. **Evidence panel fills in live**: name, agency, UPI ID, account number, IFSC, phone | "Kavach now plays a slow, confused old man who wastes the scammer's time and keeps asking him to repeat things. The caller can't hear my parent at all. And look at the evidence panel: the UPI ID, the account, the IFSC, his phone number, all in his own words." |
| 1:50 | Pick up the phone: the Telegram alerts are there (warning, takeover) | "The family got this on Telegram: risk score, stages, what he said, the time." |
| 2:00 | Click **Take back**, then **Hang up**. The "Complaint draft ready" panel appears. Answer "Did you send money?" → No, "OTP shared?" → No, click **Save answers**, open the PDF | "The moment my parent takes back, the persona stops and the call is theirs. And Kavach has written the police complaint for 1930 and cybercrime.gov.in. It is a draft: it files nothing. My parent reviews it." |
| 2:20 | Switch to the scoreboard tab. Point at the tiles: scam recall, false alarms on normal calls, false alarms on hard negatives, seconds from the decisive turn to the warning, caught before the ask | "And we can prove it works. 36 held-out calls the system never saw during tuning, played through the same pipeline: these are the numbers." (Read the figures on the screen.) |
| 2:45 | Click a wrong call, if there is one, and open its transcript | "Here is one it got wrong, and why. We show those too." |
| 2:55 | Back to the title | "Others beep. Kavach speaks, in your son's voice, takes over the call, alerts the family, and writes the complaint." |

## If something goes wrong on stage

- **No warning played:** check the Receiver tab shows `caller STT` and `receiver STT` both green. If a transcription
  connection dropped, Kavach restarts it automatically, but start a new call id and run the bot again.
- **Warning cut itself off right away:** speakers are leaking into the mic. Put headphones on.
- **No Telegram message:** the alert only goes to a chat that has messaged the bot. Run
  `uv run python scripts/check_keys.py --find-chat-id`, put the id in `.env` as `TELEGRAM_CHAT_ID`, restart the server.
- **LLM rate limit message in the server log:** wait a minute. The account allows 30 requests a minute on the
  detector model, and the bot, the persona and the detector share it.
- **Offline fallback:** play `docs/evidence/m3_warning_cloned_voice_sample.wav` to show the voice, and open the
  evidence PDF from a recorded run in `data/reports/`.

## Honest limits to say if asked

- It is a call simulator, not real telephony: there is no phone-network integration in this version.
- English only for now. Hindi is planned once the TTS model speaks it.
- The test calls are synthetic TTS audio, which is cleaner than a real phone line: real-world numbers may be lower.
- The persona only ever says clearly fake details, and the report never submits anything.
