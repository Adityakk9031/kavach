# Kavach phone app (React Native + Expo)

See [../docs/PHONE_APP.md](../docs/PHONE_APP.md) for what it does, how it connects, and how to run it on two phones.

```bash
npm install
npx expo start      # scan the QR code with Expo Go
npm test            # the app's message-handling tests
npm run typecheck   # TypeScript, 0 errors expected
```

Structure: `App.tsx` (screens), `src/ProtectScreen.tsx` (the protected person), `src/CallerScreen.tsx` (the test
caller), `src/AudioBridge.tsx` (a hidden WebView that owns the microphone and speaker; it loads the server's
`web/bridge.html`), `src/bridge.ts` (message handling, tested), `src/config.ts` (server address + access code, kept on
the phone; no AssemblyAI key is ever in the app).
