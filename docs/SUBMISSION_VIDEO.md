# Kavach submission video (≤ 2 minutes)

The strongest asset you have is a **real scam call to a real phone**, with Kavach detecting it, warning in the
family voice, taking over the call, and the family ending it from Telegram. That is the video. Keep it under 2
minutes — judges often stop at 2:00.

## Two ways to shoot it (pick one)

**A. Film the phone (most convincing, slight audio risk).**
A second camera films the parent's phone in hand during a real call. Shows the ringing, the on/off card, the
takeover button, the Telegram alert — all real. Risk: a screen recorder may not capture Kavach's warning (it rides
the accessibility audio stream). Filming with a camera captures the room audio, so the warning is heard. Test one
take first.

**B. Browser demo (crisp audio, less "wow").**
The laptop demo in `docs/DEMO_SCRIPT.md`. Every sound is clean because it is captured digitally. Use this as a
fallback if the phone audio does not record well.

Recommended: open on A (the real phone), and if the warning is inaudible in the recording, cut to B for the
warning moment only.

## Before you record (the live setup we used today)

1. The scam-caller and a cloudflared tunnel are running on the laptop; Claude places the call on your cue.
2. The phone has the current APK, Shizuku started, Kavach on in Accessibility, the family voice recorded.
3. Telegram open on the family chat, visible for the alert shots.
4. The Twilio trial cuts the call after about 2.5 minutes and plays its own message, so **end the call from Telegram
   before then** — which also demos the End button.

## The script

| Time | On screen | Voiceover |
|---|---|---|
| 0:00 | Title card: "Kavach — scam-call protection that speaks." | "Every day an elderly parent in India gets a call from a fake policeman. Today's apps show a banner. A frightened 70-year-old mid-call doesn't look at a banner." |
| 0:08 | The phone rings. Answer, put to ear. The Kavach card at the top shows "Kavach is on" and "Listening". | "This is a real call. Kavach is listening to the caller's side." |
| 0:18 | Scammer talks ("Inspector… Cyber Crime… digital arrest"). The card line changes to "Listening · scam risk" with the number. | "It tracks the scam as it unfolds — authority, threat, secrecy, urgency." |
| 0:30 | The warning plays in the family member's voice.  | "When it's sure, it warns the parent — quietly, in their own child's voice. The scammer is muted and can't hear it." |
| 0:45 | Tap **"Let Kavach talk to the caller."** Stay silent. | "The parent can hand the call to Kavach." |
| 0:50 | Kavach's voice answers the scammer (slow, confused). The scammer keeps talking. | "Kavach plays a confused old man, wastes the scammer's time, and pulls out the UPI ID, the account, the name — in the scammer's own words." |
| 1:20 | Switch to Telegram: the alert is there (risk, stage, snippet). | "The family got this on Telegram the moment it started." |
| 1:35 | Tap **End call** under the Telegram alert. The call on the phone drops. | "From anywhere, the family can end the call." |
| 1:45 | The complaint-draft PDF arrives in Telegram (or show the report). | "And Kavach writes the 1930 complaint draft — a draft, nothing is filed." |
| 1:50 | Title card again, with the caption below. | "Others beep. Kavach speaks, takes over, alerts the family, and writes the complaint. This is our hackathon demo: today it works on English calls. Next, we test it properly, add more languages, and release it for everyone." |

## Honesty line (caption it on the last card)

"Hackathon demo build. English calls only for now. Public release after proper testing, with more languages."

Optionally say it too: "Today Kavach runs through Shizuku and a voice clone we set up by hand; the public build folds
both into one install." Judges trust teams that show the seams.

## What only you can do vs what Claude does

- **You:** record, play the parent, keep Telegram visible, press End, pick takes.
- **Claude:** place the scam call on your cue, keep the server awake, confirm each feature fired from the logs
  afterwards.
