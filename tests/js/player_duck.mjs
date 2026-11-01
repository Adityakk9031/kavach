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
console.log(JSON.stringify(out));
