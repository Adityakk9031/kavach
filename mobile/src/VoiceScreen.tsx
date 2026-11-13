// Each person records 10-30 seconds of their own voice on their own phone, after agreeing: Papa on the protected phone
// (Kavach speaks in it when he hands a call over), the son or daughter on the family phone (the warning Papa hears).
// The sample goes to the Kavach server, which keeps it so a cloned voice can be made from it.
import React, { useCallback, useEffect, useRef, useState } from 'react';
import { PermissionsAndroid, Platform, Switch, Text, TextInput, View } from 'react-native';
import { AudioBridge, BridgeHandle } from './AudioBridge';
import { voiceRecorderUrl } from './bridge';
import { BackLink, Btn, C, Panel, Screen, T, Title, input } from './ui';
import { normalizeUrl, type Settings } from './config';
import { call, loadAccount } from './account';
import { useT } from './lang';

export type Person = 'papa' | 'son';
type Rec = { state: 'idle' | 'ready' | 'recording' | 'uploading' | 'uploaded' | 'error'; seconds: number; message: string };
type Job = { state: 'working' | 'ready' | 'failed'; error?: string | null };
type Listing = { samples: Record<string, { seconds: number; recorded_at: string; speaker_name: string }>; consent_text: string; min_seconds: number; max_seconds: number;
  jobs?: Record<string, Job>; state?: Record<string, { cloned: boolean }> };

export function VoiceScreen({ settings, person, onBack }: { settings: Settings; person: Person; onBack: () => void }) {
  const { t, te } = useT();
  const [parent, setParent] = useState('');
  useEffect(() => { loadAccount().then((a) => setParent(a?.parentAddress ?? '')); }, []);
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
    setJob({ state: 'failed', error: '@vs_slow' });
  }

  return (
    <Screen>
      {ready && (
        <AudioBridge key={`${person}-${name}-${take}`} ref={bridge} onMessage={onMessage} uri={voiceRecorderUrl(settings, person, name.trim(), take)} />
      )}
      <BackLink label={t('back')} onPress={() => { bridge.current?.send({ type: 'rec_cancel' }); onBack(); }} />
      <Title title={person === 'papa' ? t('vs_titleP') : t('vs_titleS')}
        subtitle={person === 'papa' ? t('vs_subP') : t('vs_subS', { p: parent || '…' })} />

      <Panel>
        <Text style={T.body}>{t('vs_name')}</Text>
        <TextInput value={name} onChangeText={setName} placeholder={t('vs_name')} placeholderTextColor={C.muted}
          style={input} />
      </Panel>

      <Panel>
        <Text style={T.h2}>{t('vs_agreeTitle')}</Text>
        <Text style={[T.muted, { marginVertical: 6 }]}>{t('vs_consent')}</Text>
        <View style={{ flexDirection: 'row', alignItems: 'center' }}>
          <Switch value={agreed} onValueChange={setAgreed} disabled={busy} trackColor={{ true: C.accent, false: C.line }} thumbColor={C.onDark} />
          <Text style={[T.body, { flex: 1, marginLeft: 10 }]}>{t('vs_agree')}</Text>
        </View>
      </Panel>

      <Panel>
        <Text style={T.h2}>{t('vs_take', { n: take, min: minS, max: maxS })}</Text>
        <Text style={[T.body, { marginTop: 6 }]}>{t((['read1', 'read2', 'read3'] as const)[take - 1])}</Text>
        <Text style={[T.muted, { marginTop: 6 }]}>{t('vs_tip')}</Text>
      </Panel>

      {rec.state === 'recording' && (
        <Panel style={{ borderColor: C.danger }}>
          <Text style={[T.h2, { color: C.danger }]}>{t('vs_recording', { s: rec.seconds.toFixed(0) })}</Text>
          <Text style={T.muted}>{rec.seconds < minS ? t('vs_keep', { min: minS }) : t('vs_canStop')}</Text>
        </Panel>
      )}
      {rec.state === 'uploading' && <Panel><Text style={T.body}>{t('vs_saving')}</Text></Panel>}
      {rec.state === 'uploaded' && (
        <Panel style={{ borderColor: C.accent }}>
          <Text style={[T.h2, { color: C.accent }]}>{t('vs_saved', { n: take, s: rec.seconds })}</Text>
          <Text style={T.muted}>{t('vs_more')}</Text>
        </Panel>
      )}
      {rec.state === 'error' && <Panel style={{ borderColor: C.danger }}><Text style={{ color: C.danger }}>{rec.message}</Text></Panel>}
      {have && rec.state !== 'uploaded' && (
        <Panel><Text style={T.muted}>{t('vs_have', { name: have.speaker_name, s: have.seconds })}</Text></Panel>
      )}

      {job?.state === 'working' && <Panel><Text style={T.body}>{t('vs_making')}</Text></Panel>}
      {job?.state === 'ready' && <Panel style={{ borderColor: C.accent }}><Text style={[T.h2, { color: C.accent }]}>{t('vs_readyT')}</Text><Text style={T.muted}>{t('vs_readyB')}</Text></Panel>}
      {job?.state === 'failed' && <Panel style={{ borderColor: C.danger }}><Text style={{ color: C.danger }}>{job.error ? te(job.error) : t('vs_failed')}</Text></Panel>}
      {taken && take < 3 && <Btn label={t('vs_nextTake', { n: take + 1 })} onPress={() => { setTake(take + 1); setRec({ state: 'idle', seconds: 0, message: '' }); }} />}
      {taken && job?.state !== 'working' && <Btn label={t('vs_make')} kind="primary" onPress={makeVoice} />}
      {rec.state === 'recording'
        ? <Btn label={t('vs_stop')} kind="primary" disabled={rec.seconds < minS} onPress={() => bridge.current?.send({ type: 'rec_stop' })} />
        : taken ? null : <Btn label={have ? t('v_again') : t('vs_start')} kind="primary" disabled={!canStart}
            onPress={() => { setRec({ state: 'ready', seconds: 0, message: '' }); bridge.current?.send({ type: 'rec_start' }); }} />}
      {!canStart && !busy && <Text style={T.muted}>{t('vs_need')}</Text>}
    </Screen>
  );
}
