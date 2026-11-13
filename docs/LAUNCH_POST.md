# Kavach public beta: launch posts (problem, solution, languages)

---

## LinkedIn

We are getting Kavach ready for its first public launch. Here is the biggest problem we hit, and how we solved it.

𝗧𝗵𝗲 𝗽𝗿𝗼𝗯𝗹𝗲𝗺
Kavach has to hear a phone call to spot a scam. Android does not allow that. Only system apps can capture call audio.
The workaround we used before, Shizuku, needs Developer options and stops every time the phone restarts.
A parent cannot be expected to set that up.

𝗢𝘂𝗿 𝘀𝗼𝗹𝘂𝘁𝗶𝗼𝗻
Standard mode, which works on any Android phone:
• Put the call on speaker, and Kavach listens through the microphone
• Only normal permissions: microphone, phone calls, notifications, and one Accessibility switch
• No Developer options, no extra tools, and it keeps working after a restart

𝗟𝗮𝗻𝗴𝘂𝗮𝗴𝗲𝘀 𝘄𝗲 𝘀𝘂𝗽𝗽𝗼𝗿𝘁: 𝟲
English, Spanish, Portuguese, German, French and Italian.
Hindi is next, as soon as Hindi text-to-speech is available.

#ScamPrevention #Android #VoiceAI #BuildInPublic

---

## X (thread)

1/
The biggest problem before Kavach's public launch: Android doesn't let apps hear phone calls. Only system apps can capture call audio.

2/
Our old workaround, Shizuku, needs Developer options and stops on every restart. Not something a parent can set up.

3/
The solution: Standard mode. Put the call on speaker, and Kavach listens through the mic. Normal permissions only, works on any Android phone.

4/
Languages: English, Spanish, Portuguese, German, French, Italian.
Hindi next, once Hindi text-to-speech is out.

---

## Reddit (r/SideProject or r/androiddev)

**Title:**
Android won't let apps hear phone calls. Here's how our scam-call app works anyway.

**Body:**

**The problem**
Kavach listens to a phone call to spot a scam while it happens. But capturing call audio needs a system-only permission
(`CAPTURE_AUDIO_OUTPUT`), so a normal app can't do it. Our earlier workaround, Shizuku, needs Developer options and
wireless debugging, and it stops on every reboot. That doesn't work for elderly parents.

**The solution**
Standard mode: the call goes on speaker and Kavach listens through the microphone. It needs only normal permissions
(microphone, phone calls, notifications) and one Accessibility switch. No root, no Shizuku, and it survives a restart.

**Languages**
English, Spanish, Portuguese, German, French and Italian. Hindi is next, once Hindi text-to-speech is available.

Has anyone found a cleaner way to hear the caller without root or speakerphone?
