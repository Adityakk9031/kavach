# The Kavach phone app

An app for the **protected person** (React Native / Expo). The family gets Telegram messages. The Python brain is unchanged.

```
 Papa's phone (Kavach app)  <--internet-->  Kavach server (Python)  --->  AssemblyAI (listen, voice, AI)
 Friend's phone (test caller) <--internet-->        |
                                                    +--->  Telegram bot  --->  the family's phone
```

## Why there is a server (and why that is a good thing)
The scam detection, the cloned-voice warning, the decoy persona, the evidence and the complaint run in Python on a server,
not inside the phone. A phone app cannot run that Python (on iPhone it is not possible at all), and putting the AssemblyAI
keys inside an app would let anyone who gets the app extract them. So the keys stay on the server, and the app only
needs the server's address and an access code. At the demo the server is **not your laptop**: it is a small cloud
server, so you only use phones.

## What each side does
- **The app (Papa):** warning plays in the earpiece, risk meter and scam signs, **Hand over to Kavach**, **Take back**,
  **Hang up**, evidence, and the complaint draft with the two questions (money / OTP).
- **Telegram (the family):** warning alert, takeover alert, and the call-end message with the complaint PDF and two buttons
  (Money sent? OTP shared?). Nothing is controlled from Telegram.
- **The test caller (a second phone running the same app):** plays the scammer, so you can demo with two real phones.

## What the app does NOT do
It cannot listen to an ordinary phone-network call: Android and iPhone do not let apps hear the other person. Here
Kavach carries the call itself between the two phones, which is how it can whisper the warning and mute the person.
A real deployment would put Kavach in the call path (a Kavach number or call forwarding).

## Run it (Expo Go)
1. **Server with an https address.** A phone only gives the microphone to a secure (https) address. Set
   `KAVACH_ACCESS_KEY=<a long random code>` in the server's environment so nobody else can use it.
2. On the laptop: `cd mobile && npm install && npx expo start`. Scan the QR code with the **Expo Go** app (App Store /
   Play Store) on each phone.
3. In the app: **Setup**, enter the server address (https://...) and the access code, tap **Test connection**, **Save**.
4. Both phones open **Home** and use the **same call code**. Papa's phone taps **I am being called**; the friend's phone taps
   **I am the test caller** and reads `docs/demo/scam_call_script.txt` (or taps the sample scammer call).
5. **Rehearsal** mode (default) sends no Telegram messages. Switch it off for the real demo.

## Checks that were run (no phone involved)
- The whole app compiles (`npm run typecheck`, 0 errors) and the Android bundle builds (`npx expo export`).
- The app's message handling: 6 tests (`npm test`).
- The hidden audio page (`web/bridge.html`) driven in a real browser against the real server with the sample scam: it
  reported the connection, detection (risk and signs), the warning in the cloned voice, the decoy's replies and audio,
  the evidence, and the call-end and report messages that the app turns into screens.

## Not checked (needs a real phone)
- The app on a real phone in Expo Go: screens, layout, the microphone permission prompt, and the sound.
- The WebView's microphone on iPhone and Android with an https server (the part most likely to need a fix).
- Take back through the app's bridge (it works at the server level and in the earlier browser tests).
- A cloud-hosted server: not set up yet.
