// Runs web/audio.js's Player against a fake Web Audio engine and prints what happened to the peer's volume.
import { Player, SOURCE, DUCK_LEVEL } from '../../web/audio.js';

class Param {
  constructor() { this.calls = []; }
  cancelScheduledValues(t) { this.calls.push(['cancel', t]); }
  setTargetAtTime(v, t, k) { this.calls.push(['target', v, +t.toFixed(3), k]); }
}
class FakeCtx {
  constructor() { this.currentTime = 10; this.destination = {}; this.gains = []; }
  createGain() { const g = { gain: new Param(), connect() { return this; } }; this.gains.push(g); return g; }
  createBuffer(ch, len, rate) { return { duration: len / rate, copyToChannel() {} }; }
  createBufferSource() { return { connect() {}, start() {}, stop() {}, onended: null }; }
  resume() {}
}
globalThis.AudioContext = FakeCtx;

const out = {};
const p = new Player();
const peer = () => p.gain(SOURCE.PEER).gain.calls;

p.play(SOURCE.PEER, new Int16Array(800));
out.afterPeerOnly = peer().length;                       // playing the scammer's voice alone changes nothing

p.play(SOURCE.WARNING, new Int16Array(16000));           // 1 s of warning audio
out.afterWarning = peer().slice();
out.duckLevel = DUCK_LEVEL;
out.warningEnds = +p.next[SOURCE.WARNING].toFixed(3);

p.play(SOURCE.WARNING, new Int16Array(16000));           // more warning audio arrives: the restore moves later
out.afterMore = peer().slice(-3);
out.warningEndsLater = +p.next[SOURCE.WARNING].toFixed(3);

p.ctx.currentTime = 11;
p.flush(SOURCE.WARNING);                                 // the person spoke: warning stopped, scammer back at once
out.afterFlush = peer().slice(-2);
out.beforeOtherFlush = peer().length;
p.flush(SOURCE.PERSONA);                                 // flushing another source must not touch the peer's volume
out.afterOtherFlush = peer().length;
// the family's voice note: every other voice goes down while it plays, and comes back when it ends or is flushed
const q = new Player();
q.ctx.currentTime = 20;
q.play(SOURCE.FAMILY, new Int16Array(32000));            // 2 s
out.familyOthers = [SOURCE.PEER, SOURCE.WARNING, SOURCE.PERSONA].map((src) => q.gain(src).gain.calls.filter((c) => c[0] === 'target').map((c) => [c[1], c[2]]));
out.familyEnds = +q.next[SOURCE.FAMILY].toFixed(3);
q.ctx.currentTime = 21;
q.flush(SOURCE.FAMILY);
out.familyAfterFlush = [SOURCE.PEER, SOURCE.WARNING, SOURCE.PERSONA].map((src) => q.gain(src).gain.calls.slice(-1)[0].slice(0, 3));
console.log(JSON.stringify(out));
