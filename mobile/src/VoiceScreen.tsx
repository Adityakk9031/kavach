// Each person records 10-30 seconds of their own voice on their own phone, after agreeing: Papa on the protected phone
// (Kavach speaks in it when he hands a call over), the son or daughter on the family phone (the warning Papa hears).
// The sample goes to the Kavach server, which keeps it so a cloned voice can be made from it.
import React, { useCallback, useEffect, useRef, useState } from 'react';
import { PermissionsAndroid, Platform, Switch, Text, TextInput, View } from 'react-native';
import { AudioBridge, BridgeHandle } from './AudioBridge';
import { voiceRecorderUrl } from './bridge';
import { Btn, C, Panel, Screen, T, Title, input } from './ui';
import { normalizeUrl, type Settings } from './config';
import { call } from './account';

export type Person = 'papa' | 'son';
type Rec = { state: 'idle' | 'ready' | 'recording' | 'uploading' | 'uploaded' | 'error'; seconds: number; message: string };
type Job = { state: 'working' | 'ready' | 'failed'; error?: string | null };
type Listing = { samples: Record<string, { seconds: number; recorded_at: string; speaker_name: string }>; consent_text: string; min_seconds: number; max_seconds: number;
  jobs?: Record<string, Job>; state?: Record<string, { cloned: boolean }> };

// A different short text for each take, read the way you would really talk
const READ_ALOUD = [
  'Hello, this is me speaking calmly. Today the weather is pleasant, and I am sitting at home with a cup of tea. ' +
    'Please do not worry about me. If anything seems strange, I will call you back and we will talk it through together.',
  'Oh, one more thing. If someone calls and rushes you, or tells you to keep a secret, just stop and take a breath. Hang up and ring me. There is no hurry at all.',
  'You know I am always here for you. Whatever happens, we will sort it out together, step by step, nice and slowly. Take your time.',
];

export function VoiceScreen({ settings, person, onBack }: { settings: Settings; person: Person; onBack: () => void }) {
  const [name, setName] = useState('');
  const [agreed, setAgreed] = useState(false);
  const [rec, setRec] = useState<Rec>({ state: 'idle', seconds: 0, message: '' });
  const [listing, setListing] = useState<Listing | null>(null);
  const [ready, setReady] = useState(Platform.OS !== 'android');
  const [take, setTake] = useState(1);
  const [job, setJob] = useState<Job | null>(null);
  const bridge = useRef<BridgeHandle>(null);

  useEffect(() => {
    if (Platform.OS !== 'android') return;
    PermissionsAndroid.request(PermissionsAndroid.PERMISSIONS.RECORD_AUDIO).finally(() => setReady(true));
  }, []);

  const refresh = useCallback(async () => {
    try {
      const r = await fetch(`${normalizeUrl(settings.serverUrl)}/api/voices`, { headers: { 'x-kavach-key': settings.accessKey } });
      if (r.ok) setListing(await r.json());
    } catch { /* offline: the list just stays as it was */ }
  }, [settings]);
  useEffect(() => { refresh(); }, [refresh]);

  const onMessage = (m: any) => {
    if (m.type !== 'rec') return;
    setRec({ state: m.state, seconds: m.seconds ?? 0, message: m.message ?? '' });
    if (m.state === 'uploaded') refresh();
  };

  const minS = take === 1 ? (listing?.min_seconds ?? 10) : 5;
  const maxS = listing?.max_seconds ?? 30;
  const busy = rec.state === 'recording' || rec.state === 'uploading';
  const have = listing?.samples[person];
  const canStart = ready && agreed && name.trim().length > 0 && !busy;
  const taken = rec.state === 'uploaded';

  async function makeVoice() {
    setJob({ state: 'working' });
    const r = await call(settings, `/api/voices/${person}/clone`, 'POST');
    if (!r.ok) { setJob({ state: 'failed', error: r.error }); return; }
    for (let i = 0; i < 60; i++) {
      await new Promise((res) => setTimeout(res, 2500));
      const l = await call<Listing>(settings, '/api/voices');
      const j = l.ok ? l.data.jobs?.[person] : undefined;
      if (j && j.state !== 'working') { setJob(j); return; }
    }
    setJob({ state: 'failed', error: 'This is taking longer than usual. Check back in a minute.' });
  }

  return (
    <Screen>
      {ready && (
        <AudioBridge key={`${person}-${name}-${take}`} ref={bridge} onMessage={onMessage} uri={voiceRecorderUrl(settings, person, name.trim(), take)} />
      )}
      <Title title={person === 'papa' ? 'Your voice' : 'Your voice for the warning'}
        subtitle={person === 'papa' ? 'If you hand a call over, Kavach talks to the caller in this voice.'
          : 'Papa hears the scam warning in this voice, so he knows it is family.'} />

      <Panel>
        <Text style={T.body}>Your name</Text>
        <TextInput value={name} onChangeText={setName} placeholder="Name" placeholderTextColor={C.muted}
          style={input} />
      </Panel>

      <Panel>
        <Text style={T.h2}>Your agreement</Text>
        <Text style={[T.muted, { marginVertical: 6 }]}>{listing?.consent_text ?? 'Loading…'}</Text>
        <View style={{ flexDirection: 'row', alignItems: 'center' }}>
          <Switch value={agreed} onValueChange={setAgreed} disabled={busy} trackColor={{ true: C.accent, false: C.line }} thumbColor={C.onDark} />
          <Text style={[T.body, { flex: 1, marginLeft: 10 }]}>I agree, and this is my own voice.</Text>
        </View>
      </Panel>

      <Panel>
        <Text style={T.h2}>Take {take} of 3: read this aloud, calmly ({minS}–{maxS} seconds)</Text>
        <Text style={[T.body, { marginTop: 6 }]}>{READ_ALOUD[take - 1]}</Text>
        <Text style={[T.muted, { marginTop: 6 }]}>Use a quiet room, hold the phone close, no music or other people talking.</Text>
      </Panel>

      {rec.state === 'recording' && (
        <Panel style={{ borderColor: C.danger }}>
          <Text style={[T.h2, { color: C.danger }]}>Recording… {rec.seconds.toFixed(0)} s</Text>
          <Text style={T.muted}>{rec.seconds < minS ? `Keep going until ${minS} s.` : 'You can stop now.'}</Text>
        </Panel>
      )}
      {rec.state === 'uploading' && <Panel><Text style={T.body}>Saving to the server…</Text></Panel>}
      {rec.state === 'uploaded' && (
        <Panel style={{ borderColor: C.accent }}>
          <Text style={[T.h2, { color: C.accent }]}>Take {take} saved ({rec.seconds} s)</Text>
          <Text style={T.muted}>Another take or two makes the cloned voice clearer and more natural. When you are happy, make your voice.</Text>
        </Panel>
      )}
      {rec.state === 'error' && <Panel style={{ borderColor: C.danger }}><Text style={{ color: C.danger }}>{rec.message}</Text></Panel>}
      {have && rec.state !== 'uploaded' && (
        <Panel><Text style={T.muted}>A sample from {have.speaker_name} ({have.seconds} s, {have.recorded_at}) is already saved. Recording again replaces it.</Text></Panel>
      )}

      {job?.state === 'working' && <Panel><Text style={T.body}>Making your voice… this takes up to a minute.</Text></Panel>}
      {job?.state === 'ready' && <Panel style={{ borderColor: C.accent }}><Text style={[T.h2, { color: C.accent }]}>Your voice is ready</Text><Text style={T.muted}>Kavach will use it from the next call.</Text></Panel>}
      {job?.state === 'failed' && <Panel style={{ borderColor: C.danger }}><Text style={{ color: C.danger }}>{job.error || 'Could not make the voice.'}</Text></Panel>}
      {taken && take < 3 && <Btn label={`Record take ${take + 1} (clearer voice)`} onPress={() => { setTake(take + 1); setRec({ state: 'idle', seconds: 0, message: '' }); }} />}
      {taken && job?.state !== 'working' && <Btn label="Make my voice" kind="primary" onPress={makeVoice} />}
      {rec.state === 'recording'
        ? <Btn label="Stop and save" kind="primary" disabled={rec.seconds < minS} onPress={() => bridge.current?.send({ type: 'rec_stop' })} />
        : taken ? null : <Btn label={have ? 'Record again' : 'Start recording'} kind="primary" disabled={!canStart}
            onPress={() => { setRec({ state: 'ready', seconds: 0, message: '' }); bridge.current?.send({ type: 'rec_start' }); }} />}
      {!canStart && !busy && <Text style={T.muted}>Enter your name and agree to start.</Text>}
      <Btn label="Back" onPress={() => { bridge.current?.send({ type: 'rec_cancel' }); onBack(); }} />
    </Screen>
  );
}
