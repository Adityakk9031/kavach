// Shared audio helpers for the Caller and Receiver tabs.
// Wire format (see app/call_room.py): binary frame = 1 source byte + PCM s16le mono at 16 kHz.

export const SAMPLE_RATE = 16000;
export const CHUNK_SAMPLES = 800; // 50 ms
export const SOURCE = { PEER: 0, WARNING: 1, PERSONA: 2 };

// AudioWorklet that downsamples the mic to 16 kHz Int16 and posts 50 ms chunks.
const CAPTURE_WORKLET = `
class Capture extends AudioWorkletProcessor {
  constructor(opts) {
    super();
    this.ratio = sampleRate / ${SAMPLE_RATE};
    this.pos = 0;            // fractional read position into the input stream
    this.buf = new Int16Array(${CHUNK_SAMPLES});
    this.n = 0;
    this.prev = 0;
  }
  process(inputs) {
    const ch = inputs[0] && inputs[0][0];
    if (!ch) return true;
    // Linear-interpolation resampler; pos is relative to the start of this block.
    while (this.pos < ch.length) {
      const i = Math.floor(this.pos), f = this.pos - i;
      const a = i === 0 && f < 0 ? this.prev : ch[i], b = i + 1 < ch.length ? ch[i + 1] : ch[i];
      const s = Math.max(-1, Math.min(1, a + (b - a) * f));
      this.buf[this.n++] = s < 0 ? s * 0x8000 : s * 0x7fff;
      if (this.n === this.buf.length) {
        this.port.postMessage(this.buf.buffer, [this.buf.buffer]);
        this.buf = new Int16Array(${CHUNK_SAMPLES});
        this.n = 0;
      }
      this.pos += this.ratio;
    }
    this.pos -= ch.length;
    this.prev = ch[ch.length - 1];
    return true;
  }
}
registerProcessor('kavach-capture', Capture);
`;

export async function startMic(onChunk) {
  const stream = await navigator.mediaDevices.getUserMedia({
    audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true },
  });
  const ctx = new AudioContext();
  const url = URL.createObjectURL(new Blob([CAPTURE_WORKLET], { type: 'application/javascript' }));
  await ctx.audioWorklet.addModule(url);
  const src = ctx.createMediaStreamSource(stream);
  const node = new AudioWorkletNode(ctx, 'kavach-capture');
  node.port.onmessage = (e) => onChunk(e.data);
  src.connect(node);
  // Worklet must be pulled by the graph; route through a muted gain so nothing is heard.
  const mute = ctx.createGain();
  mute.gain.value = 0;
  node.connect(mute).connect(ctx.destination);
  return {
    stop() { stream.getTracks().forEach((t) => t.stop()); ctx.close(); },
  };
}

// Decode an audio file and resample it to 16 kHz mono Int16 (for scripted calls).
export async function fileToPcm16(file) {
  const data = await file.arrayBuffer();
  const tmp = new AudioContext();
  const decoded = await tmp.decodeAudioData(data);
  tmp.close();
  const frames = Math.ceil(decoded.duration * SAMPLE_RATE);
  const off = new OfflineAudioContext(1, frames, SAMPLE_RATE);
  const src = off.createBufferSource();
  src.buffer = decoded;
  src.connect(off.destination);
  src.start();
  const rendered = (await off.startRendering()).getChannelData(0);
  const out = new Int16Array(rendered.length);
  for (let i = 0; i < rendered.length; i++) {
    const s = Math.max(-1, Math.min(1, rendered[i]));
    out[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
  }
  return out;
}

// Stream Int16 PCM in real time as 50 ms chunks. Returns a stopper.
export function streamPcm(pcm, onChunk, onDone) {
  let i = 0;
  const t0 = performance.now();
  const timer = setInterval(() => {
    const due = Math.floor(((performance.now() - t0) / 1000) * SAMPLE_RATE);
    while (i < due && i < pcm.length) {
      const chunk = pcm.slice(i, i + CHUNK_SAMPLES);
      onChunk(chunk.buffer);
      i += CHUNK_SAMPLES;
    }
    if (i >= pcm.length) { clearInterval(timer); onDone && onDone(); }
  }, 20);
  return { stop() { clearInterval(timer); } };
}

// Gapless player with one queue per source, so one source can be flushed instantly.
export class Player {
  constructor(onFirstAudio) {
    this.ctx = new AudioContext();
    this.next = {};      // source -> scheduled end time
    this.nodes = {};     // source -> Set of playing nodes
    this.gains = {};
    this.onFirstAudio = onFirstAudio; // (source) => void, fires when a source starts after silence
  }
  resume() { return this.ctx.resume(); }
  gain(source) {
    if (!this.gains[source]) {
      this.gains[source] = this.ctx.createGain();
      this.gains[source].connect(this.ctx.destination);
    }
    return this.gains[source];
  }
  play(source, int16) {
    const f = new Float32Array(int16.length);
    for (let i = 0; i < int16.length; i++) f[i] = int16[i] / 0x8000;
    const buf = this.ctx.createBuffer(1, f.length, SAMPLE_RATE);
    buf.copyToChannel(f, 0);
    const node = this.ctx.createBufferSource();
    node.buffer = buf;
    node.connect(this.gain(source));
    const now = this.ctx.currentTime;
    const idle = !this.next[source] || this.next[source] < now;
    // Small lead after silence absorbs network jitter without adding noticeable delay.
    const start = idle ? now + 0.04 : this.next[source];
    node.start(start);
    this.next[source] = start + buf.duration;
    (this.nodes[source] ||= new Set()).add(node);
    node.onended = () => this.nodes[source].delete(node);
    if (idle && this.onFirstAudio) this.onFirstAudio(source, (start - now) * 1000);
  }
  flush(source) {
    for (const n of this.nodes[source] || []) { try { n.stop(); } catch (_) {} }
    this.nodes[source] = new Set();
    this.next[source] = 0;
  }
  isPlaying(source) {
    return (this.next[source] || 0) > this.ctx.currentTime;
  }
}

// Connect a tab to the call. handlers: {onEvent(json), onAudio(source, Int16Array)}
export function connectCall(callId, role, handlers, params = {}) {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  const qs = new URLSearchParams(params).toString();
  const ws = new WebSocket(`${proto}://${location.host}/ws/call/${encodeURIComponent(callId)}/${role}${qs ? '?' + qs : ''}`);
  ws.binaryType = 'arraybuffer';
  ws.onmessage = (e) => {
    if (typeof e.data === 'string') handlers.onEvent(JSON.parse(e.data));
    else {
      const bytes = new Uint8Array(e.data);
      // Copy past the header byte so the Int16 view is 2-byte aligned.
      const pcm = new Int16Array(bytes.slice(1).buffer);
      handlers.onAudio(bytes[0], pcm);
    }
  };
  return {
    ws,
    sendAudio(buf) { if (ws.readyState === 1) ws.send(buf); },
    send(obj) { if (ws.readyState === 1) ws.send(JSON.stringify(obj)); },
    clientEvent(name, payload = {}) { this.send({ type: 'client_event', name, payload }); },
  };
}

export function callIdFromUrl() {
  return new URLSearchParams(location.search).get('call') || 'demo';
}
