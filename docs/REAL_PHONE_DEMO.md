# Real phone call demo (Option A: the laptop listens to a real call)

A real call on your real phone, on speaker, with the laptop next to it. Kavach hears the call through the laptop
microphone, warns you in your headphones, can speak to the caller for you, alerts Telegram and writes the complaint.

**What this is, honestly:** the call goes over the normal phone network, but Kavach is not *inside* the call. It is a
listening device next to the phone. A phone app cannot listen to a call (Android and iPhone both block it), so a real
product would sit in the network. This demo shows the whole experience on a real call.

## What you need
- The laptop running Kavach, with the microphone working.
- **Headphones** plugged into the laptop (for the warning: you hear your cloned voice, the caller does not).
- Your phone, and a friend with a second phone who agrees to play the scammer (script: `docs/demo/scam_call_script.txt`).
- Only use made-up details. No real scammer numbers. Both of you agree to the call being listened to: recording or
  analysing a call without the other person's consent can be illegal.

## Rehearse first, with no phone and no friend (3 minutes)
```bash
uv run uvicorn app.main:app --port 8000
```
Open `http://localhost:8000/web/speaker.html?call=rehearsal1&mode=eval` in Chrome, click **Start listening**, then
**Test without a phone: play a sample scammer call**. Within about 40 seconds the warning plays; click **Hand over to
Kavach** to see the decoy talk, then **Take back** and **End call**. (`mode=eval` sends no Telegram alerts.)

## The real call
1. Start the server (above) and wait for the line `warning session ready … voice=01a19208…`.
2. Open `http://localhost:8000/web/speaker.html?call=real1` in Chrome. Use a fresh `call=` name every time.
   (No `mode=eval`: this one sends the real Telegram alerts.)
3. Put the **headphones on**. In the page, set **Warning plays in** to your headphones, and **Decoy voice plays from**
   to the laptop speakers. (If Chrome shows only "Default output", set your headphones as the computer's output and
   skip this; then also keep the volume low. The page will tell you it is muting the microphone while the warning plays.)
4. Type the friend's number in **Caller's number** (it goes in the complaint). Click **Start listening** and allow the
   microphone when Chrome asks. The microphone level bar should move when anyone talks.
5. Your friend calls your phone. Answer, put it on **speaker**, and put the phone **next to the laptop microphone**.
6. Your friend reads the script, pausing after each paragraph.
7. After paragraph 2 or 3 you should hear **your cloned voice in the headphones**: "Papa, stop… …". The page shows
   the risk meter, the lit stages and the warning banner. Your phone on the table is not affected.
8. To make Kavach take over: click **Hand over to Kavach**. The old man now speaks **from the laptop speaker**; the
   phone's microphone carries it to your friend, who hears him and answers his questions. The evidence panel fills in.
9. Click **Take back** to stop the decoy. Then hang up the phone call and click **End call**.
10. Within a few seconds: the "Complaint draft ready" panel appears (PDF link, two questions), and your Telegram gets the
    messages. Answer the two questions on the page or with the Telegram buttons.

## What to expect, and the limits
- **Half-duplex.** The one microphone hears the whole room. While Kavach's own voice plays out loud, the microphone is
  muted (otherwise Kavach would hear itself and answer itself). So the caller cannot be heard while the decoy is talking:
  keep the decoy's turns short, and let the caller finish.
- **Your own voice is also heard** by the same microphone and treated as the caller's. Stay quiet during the test, or
  talk only when the script says so.
- **No automatic interruption.** Kavach cannot tell your voice from the caller's with one microphone, so speaking does
  not stop the warning. Click **Stop warning** if you want to cut it off.
- **The takeover is crude here.** It works by sound through the air. In a real deployment (a Kavach phone number), the
  decoy would be sent straight into the call and your voice muted.
- **Echo.** Keep the headphones on for the warning. If the warning plays from the laptop speaker, the phone's
  microphone can carry it to the caller.

## If something goes wrong
- **Level bar does not move:** allow the microphone for the page (lock icon in the address bar → Microphone → Allow),
  then reload. Check Chrome is using the right microphone.
- **No warning after the friend finishes paragraph 3:** check the status line shows `caller STT: universal-3-6-pro`.
  Speak clearly; the phone speaker needs to be loud enough for the laptop microphone.
- **"This call has ended":** you reused a call name. Use a new one.
- **No Telegram message:** the alert only goes to the chat that messaged the bot (`TELEGRAM_CHAT_ID` in `.env`).
- **LLM rate-limit warnings in the server log:** wait a minute, then try again.

## Not covered
Real telephony (a number that Kavach answers or joins), iPhone/Android apps, call recording by the phone network.
