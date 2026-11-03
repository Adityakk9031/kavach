# Twilio demo call: set-up steps

Kavach rings **your own phone** and plays a pretend scammer you can talk to. It only ever calls the single number set in
`TWILIO_TARGET_NUMBER`, so it cannot be used to call anyone else.

## In the Twilio console (console.twilio.com)
1. **Verify your phone number** (needed on a trial account): Phone Numbers → Manage → **Verified Caller IDs** → Add a new
   Caller ID → your mobile number in `+91…` format → enter the code Twilio sends.
2. **Get a Twilio number** with Voice: Phone Numbers → Manage → Buy a number (a trial account includes one free). This is the
   "From" number.
3. **Allow calls to India**: Voice → Settings → **Geo permissions** → tick *India*. Without this Twilio refuses the call.
4. **Copy your keys** from the console home page: *Account SID* and *Auth Token*.
5. Trial accounts say a short "trial account" message when you pick up. That is Twilio, not Kavach; upgrading removes it.

## On the Kavach server (Render → kavach service → Environment)
Add these, then let it redeploy:

| Name | Value |
|---|---|
| `TWILIO_ACCOUNT_SID` | Account SID from step 4 |
| `TWILIO_AUTH_TOKEN` | Auth Token from step 4 |
| `TWILIO_FROM_NUMBER` | the Twilio number from step 2, e.g. `+1…` |
| `TWILIO_TARGET_NUMBER` | your own number from step 1, e.g. `+91…` |

You do not have to send these keys to anyone: they only need to be on the server. Optional: `PUBLIC_BASE_URL` (only if the
server cannot work out its own https address), `SCAMMER_VOICE_ID` (default `aai-michael`).

## Make the call
- In the Kavach app: Home → **Call my phone**. Or: `curl -X POST https://<server>/api/twilio/call -H "x-kavach-key: <access code>"`.
- Pick up and talk. The caller listens to your voice, answers what you say, and stops when you talk over it.
- `GET /api/twilio/status` shows whether a call is on and the last lines said. A demo call hangs up after 4 minutes.

## What this does and does not do yet
- Done: Twilio rings you, a live one-to-one pretend scammer listens and replies, with the made-up officer and UPI id.
- Not yet: Kavach's own protection (risk meter, the warning in a trusted voice, takeover) on this same phone call. That is the next
  step: send the call's two sides through Kavach's detector and play the warning into the same call.
