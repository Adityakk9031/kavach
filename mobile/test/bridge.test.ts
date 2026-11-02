// Run with: node --test test/   (Node 24 runs TypeScript directly)
import test from 'node:test';
import assert from 'node:assert/strict';
import { bridgeUrl, initialState, reduce } from '../src/bridge.ts';

const run = (msgs: any[]) => msgs.reduce(reduce, initialState);

test('bridge url carries the call, role, mode, key and caller number, and no stray slashes', () => {
  const u = new URL(bridgeUrl({ serverUrl: 'https://k.example.com/', accessKey: 'a b&c' },
    { call: 'app-xy12', role: 'caller', mode: 'eval', callerNumber: '+91 98201 33456' }));
  assert.equal(u.origin + u.pathname, 'https://k.example.com/web/bridge.html');
  assert.deepEqual(Object.fromEntries(u.searchParams), { call: 'app-xy12', role: 'caller', mode: 'eval', key: 'a b&c', caller_number: '+91 98201 33456' });
  assert.equal(new URL(bridgeUrl({ serverUrl: 'https://k.example.com', accessKey: '' }, { call: 'c', role: 'receiver', mode: 'live' })).searchParams.has('key'), false);
});

test('a scam call: risk climbs, stages light up, warning speaks then finishes', () => {
  const s = run([
    { type: 'bridge', state: 'connected' }, { type: 'bridge', state: 'mic_on' }, { type: 'stt_status', channel: 'caller', ok: true },
    { type: 'detection', risk_cum: 31.5, stages_all: ['S1'], stages_now: ['S1'], trigger: false },
    { type: 'detection', risk_cum: 77.3, stages_all: ['S1', 'S2', 'S3'], stages_now: ['S2', 'S3'], trigger: true, rationale: 'fake officer' },
    { type: 'warning', state: 'speaking', text: 'Papa, stop…', cloned: true },
  ]);
  assert.equal(s.connected && s.micOn && s.sttOk.caller, true);
  assert.equal(s.risk, 77); assert.deepEqual(s.stages, ['S1', 'S2', 'S3']); assert.equal(s.triggered, true);
  assert.equal(s.warning?.state, 'speaking'); assert.equal(s.warning?.text, 'Papa, stop…');
  const done = reduce(s, { type: 'warning', state: 'done' });
  assert.equal(done.warning?.state, 'done'); assert.equal(done.warning?.text, 'Papa, stop…'); // text kept for display
});

test('the risk meter never un-triggers, and detector errors change nothing', () => {
  let s = run([{ type: 'detection', risk_cum: 80, stages_all: ['S1'], stages_now: [], trigger: true }]);
  s = reduce(s, { type: 'detection', risk_cum: 40, stages_all: ['S1'], stages_now: [], trigger: false });
  assert.equal(s.triggered, true);
  assert.equal(reduce(s, { type: 'detection', error: 'timeout' }), s);
});

test('takeover, persona text, evidence de-duplication, end and report', () => {
  let s = run([
    { type: 'takeover', state: 'on' }, { type: 'persona', state: 'speaking', text: 'Ah, my glasses…' },
    { type: 'evidence', items: [{ type: 'upi_id', value: 'a@okbank', normalized: 'a@okbank', quote: 'pay a@okbank' }] },
    { type: 'evidence', items: [{ type: 'upi_id', value: 'a@okbank', normalized: 'a@okbank', quote: 'again' },
                                { type: 'ifsc', value: 'HDFC0001234', normalized: 'hdfc0001234', quote: 'ifsc' }] },
  ]);
  assert.equal(s.takeover, true); assert.equal(s.personaText, 'Ah, my glasses…');
  assert.deepEqual(s.evidence.map((e) => e.type), ['upi_id', 'ifsc']); // the repeated UPI ID was not added twice
  s = reduce(s, { type: 'takeover', state: 'off' }); assert.equal(s.takeover, false);
  s = reduce(s, { type: 'call_ended' }); assert.equal(s.ended, true);
  s = reduce(s, { type: 'report_ready', report: { md: '/api/calls/x/report.md', pdf: '/api/calls/x/report.pdf' } });
  assert.equal(s.report?.pdf, '/api/calls/x/report.pdf');
});

test('transcript: a newer partial replaces the old one; finals stay; capped', () => {
  let s = run([
    { type: 'transcript', channel: 'caller', final: false, text: 'This is' },
    { type: 'transcript', channel: 'caller', final: false, text: 'This is Inspector' },
  ]);
  assert.deepEqual(s.transcript.map((t) => t.text), ['This is Inspector']);
  s = reduce(s, { type: 'transcript', channel: 'caller', final: true, text: 'This is Inspector Rathore.', stt_latency_ms: 400 });
  s = reduce(s, { type: 'transcript', channel: 'receiver', final: true, text: 'Who?' });
  assert.deepEqual(s.transcript.map((t) => [t.channel, t.final]), [['caller', true], ['receiver', true]]);
  for (let i = 0; i < 100; i++) s = reduce(s, { type: 'transcript', channel: 'caller', final: true, text: `t${i}` });
  assert.equal(s.transcript.length, 60);
});

test('failures are explained in plain words', () => {
  assert.match(run([{ type: 'mic_error', name: 'InsecureContext' }]).micError!, /https/);
  assert.match(run([{ type: 'mic_error', name: 'NotAllowedError' }]).micError!, /phone settings/);
  assert.match(run([{ type: 'call_rejected', reason: 'This call has ended.' }]).rejected!, /ended/);
  assert.equal(run([{ type: 'call_rejected', reason: 'x' }]).ended, true);
  assert.match(run([{ type: 'bridge', state: 'socket_error' }]).closed!, /Could not connect/);
  assert.equal(reduce(initialState, { type: 'something_new' }), initialState); // unknown messages are ignored
});
