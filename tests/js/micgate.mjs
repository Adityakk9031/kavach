import { MicGate, silenceLike } from '../../web/speakerlink.js';

const out = {};
const quiet = { personaPlaying: false, warningPlaying: false, warningOnSameSpeaker: false };

let g = new MicGate(400);
out.idle = g.shouldMute(quiet, 1000);                                             // nothing playing: mic passes through

out.personaSpeaking = g.shouldMute({ ...quiet, personaPlaying: true }, 2000);     // persona out loud: muted
out.tailJustAfter = g.shouldMute(quiet, 2300);                                    // 300 ms later: still inside the echo tail
out.tailOver = g.shouldMute(quiet, 2401);                                         // past the tail: open again

g = new MicGate(400);
out.warningOnHeadphones = g.shouldMute({ ...quiet, warningPlaying: true, warningOnSameSpeaker: false }, 1000);
out.warningOnSharedSpeaker = g.shouldMute({ ...quiet, warningPlaying: true, warningOnSameSpeaker: true }, 1100);
out.afterSharedWarningTail = g.shouldMute(quiet, 1300);
out.afterSharedWarningOpen = g.shouldMute(quiet, 1600);

const s = silenceLike(new Int16Array([5, -7, 900, 123]).buffer);
out.silenceBytes = s.byteLength;
out.silenceIsZero = new Int16Array(s).every((v) => v === 0);
console.log(JSON.stringify(out));
