// Papa and the son each record 10-30 seconds of their own voice here, after agreeing. The sample goes to the Kavach
// server, which keeps it so a cloned voice can be made from it (AssemblyAI makes clones only in its dashboard).
import React, { useCallback, useEffect, useRef, useState } from 'react';
import { PermissionsAndroid, Platform, Switch, Text, TextInput, View } from 'react-native';
import { AudioBridge, BridgeHandle } from './AudioBridge';
import { voiceRecorderUrl } from './bridge';
import { Btn, C, Panel, Screen, T, Title, input } from './ui';
import { normalizeUrl, type Settings } from './config';

type Person = 'papa' | 'son';
type Rec = { state: 'idle' | 'ready' | 'recording' | 'uploading' | 'uploaded' | 'error'; seconds: number; message: string };
type Listing = { samples: Record<string, { seconds: number; recorded_at: string; speaker_name: string }>; consent_text: string; min_seconds: number; max_seconds: number };

const READ_ALOUD = 'Hello, this is me speaking calmly. Today the weather is pleasant, and I am sitting at home with a cup of tea. ' +
  'Please do not worry about me. If anything seems strange, I will call you back and we will talk it through together.';

export function VoiceScreen({ settings, onBack }: { settings: Settings; onBack: () => void }) {
  const [person, setPerson] = useState<Person>('papa');
  const [name, setName] = useState('');
  const [agreed, setAgreed] = useState(false);
  const [rec, setRec] = useState<Rec>({ state: 'idle', seconds: 0, message: '' });
  const [listing, setListing] = useState<Listing | null>(null);
  const [ready, setReady] = useState(Platform.OS !== 'android');
  const [session, setSession] = useState(0); // a fresh recorder page for each person / attempt
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

  const minS = listing?.min_seconds ?? 10;
  const maxS = listing?.max_seconds ?? 30;
  const busy = rec.state === 'recording' || rec.state === 'uploading';
  const have = listing?.samples[person];
  const canStart = ready && agreed && name.trim().length > 0 && !busy;

  const choose = (p: Person) => { if (!busy) { setPerson(p); setAgreed(false); setRec({ state: 'idle', seconds: 0, message: '' }); setSession((n) => n + 1); } };

  return (
    <Screen>
      {ready && (
        <AudioBridge key={`${person}-${name}-${session}`} ref={bridge} onMessage={onMessage} uri={voiceRecorderUrl(settings, person, name.trim())} />
      )}
      <Title title="My voice" subtitle="So Kavach can speak in your voice when you ask it to." />

      <View style={{ flexDirection: 'row' }}>
        <View style={{ flex: 1, marginRight: 6 }}><Btn label="I am Papa" kind={person === 'papa' ? 'primary' : 'plain'} onPress={() => choose('papa')} /></View>
        <View style={{ flex: 1, marginLeft: 6 }}><Btn label="I am the son" kind={person === 'son' ? 'primary' : 'plain'} onPress={() => choose('son')} /></View>
      </View>

      <Panel>
        <Text style={T.body}>Your name</Text>
        <TextInput value={name} onChangeText={setName} placeholder="Name" placeholderTextColor={C.muted}
          style={input} />
      </Panel>

      <Panel>
        <Text style={T.h2}>Your agreement</Text>
        <Text style={[T.muted, { marginVertical: 6 }]}>{listing?.consent_text ?? 'Loading…'}</Text>
        <View style={{ flexDirection: 'row', alignItems: 'center' }}>
          <Switch value={agreed} onValueChange={setAgreed} disabled={busy} />
          <Text style={[T.body, { flex: 1, marginLeft: 10 }]}>I agree, and this is my own voice.</Text>
        </View>
      </Panel>

      <Panel>
        <Text style={T.h2}>Read this aloud, calmly ({minS}–{maxS} seconds)</Text>
        <Text style={[T.body, { marginTop: 6 }]}>{READ_ALOUD}</Text>
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
          <Text style={[T.h2, { color: C.accent }]}>Saved ({rec.seconds} s)</Text>
          <Text style={T.muted}>The owner now adds this voice in the AssemblyAI dashboard and sends the voice id to Kavach.</Text>
        </Panel>
      )}
      {rec.state === 'error' && <Panel style={{ borderColor: C.danger }}><Text style={{ color: C.danger }}>{rec.message}</Text></Panel>}
      {have && rec.state !== 'uploaded' && (
        <Panel><Text style={T.muted}>A sample from {have.speaker_name} ({have.seconds} s, {have.recorded_at}) is already saved. Recording again replaces it.</Text></Panel>
      )}

      {rec.state === 'recording'
        ? <Btn label="Stop and save" kind="primary" disabled={rec.seconds < minS} onPress={() => bridge.current?.send({ type: 'rec_stop' })} />
        : <Btn label={have ? 'Record again' : 'Start recording'} kind="primary" disabled={!canStart}
            onPress={() => { setRec({ state: 'ready', seconds: 0, message: '' }); bridge.current?.send({ type: 'rec_start' }); }} />}
      {!canStart && !busy && <Text style={T.muted}>Enter your name and agree to start.</Text>}
      <Btn label="Back" onPress={() => { bridge.current?.send({ type: 'rec_cancel' }); onBack(); }} />
    </Screen>
  );
}
