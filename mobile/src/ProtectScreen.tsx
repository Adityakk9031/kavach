// The protected person's screen: warning in the earpiece, risk, hand over / take back, evidence, complaint.
import React, { useEffect, useReducer, useRef, useState } from 'react';
import { PermissionsAndroid, Platform, Pressable, Text, View } from 'react-native';
import { useKeepAwake } from 'expo-keep-awake';
import { AudioBridge, BridgeHandle } from './AudioBridge';
import { STAGE_LABELS, bridgeUrl, initialState, reduce } from './bridge';
import { Btn, C, Chip, Meter, Panel, Pill, Screen, SectionLabel, T, Title } from './ui';
import { ReportPanel } from './ReportPanel';
import { api, type Settings } from './config';

export function ProtectScreen({ settings, code, rehearsal, listen = false, watchCall, onBack }: {
  settings: Settings; code: string; rehearsal: boolean; listen?: boolean; watchCall?: string; onBack: () => void;
}) {
  useKeepAwake();
  const callId = watchCall ?? `app-${code.toLowerCase()}`;
  const [s, dispatch] = useReducer(reduce, initialState);
  const bridge = useRef<BridgeHandle>(null);
  const [ready, setReady] = useState(Platform.OS !== 'android');
  // The background listener streams this call, so here the app only shows it and sends commands
  const command = (type: 'takeover' | 'takeback' | 'end_call') => {
    if (!watchCall) { bridge.current?.send({ type }); return; }
    const { base, headers } = api(settings);
    fetch(`${base}/api/calls/${watchCall}/control`, { method: 'POST', headers, body: JSON.stringify({ type }) }).catch(() => {});
  };

  useEffect(() => {
    if (!watchCall) return;
    const { base } = api(settings);
    const ws = new WebSocket(`${base.replace(/^http/, 'ws')}/ws/events/${watchCall}?key=${encodeURIComponent(settings.accessKey)}`);
    ws.onopen = () => {
      dispatch({ type: 'bridge', state: 'connected' });
      dispatch({ type: 'stt_status', channel: 'caller', ok: true });
    };
    ws.onmessage = (e) => { try { dispatch(JSON.parse(e.data)); } catch { /* not an event */ } };
    ws.onerror = () => dispatch({ type: 'bridge', state: 'socket_error' });
    return () => ws.close();
  }, [watchCall, settings]);

  useEffect(() => { // Android asks for the microphone itself; iOS asks inside the audio page
    if (Platform.OS !== 'android' || watchCall) return;
    PermissionsAndroid.request(PermissionsAndroid.PERMISSIONS.RECORD_AUDIO).finally(() => setReady(true));
  }, []);

  const speaking = s.warning?.state === 'speaking';
  const status = s.rejected ? s.rejected : s.ended ? 'Call ended' : s.closed ? s.closed
    : !s.connected ? 'Connecting…' : s.sttOk.caller ? 'Listening' : 'Getting ready…';
  const riskColor = s.risk >= 60 ? C.danger : s.risk >= 40 ? C.warn : C.accent;

  // After the warning, a big card floats over everything so a scared person can hand the call over with one tap
  const offerTakeover = s.triggered && !s.takeover && !s.ended;

  return (
    <View style={{ flex: 1, backgroundColor: C.bg }}>
    <Screen bottom={offerTakeover ? 220 : 32}>
      {!s.ended && (
        <Pressable onPress={() => { bridge.current?.send({ type: 'stop' }); onBack(); }} hitSlop={12} style={{ paddingBottom: 14 }}>
          <Text style={{ color: C.accent, fontSize: 16, fontWeight: '600' }}>‹ Home</Text>
        </Pressable>
      )}
      {ready && !watchCall && (
        <AudioBridge ref={bridge} onMessage={dispatch}
          uri={bridgeUrl(settings, { call: callId, role: listen ? 'listen' : 'receiver', mode: rehearsal ? 'eval' : 'live' })} />
      )}
      <Title title="Protecting your call" subtitle={rehearsal ? `Test code ${code} · no Telegram alerts` : undefined} />
      <View style={{ flexDirection: 'row', marginTop: -6, marginBottom: 16 }}>
        <Pill label={s.takeover ? 'Kavach on the call' : s.triggered ? 'Scam warning' : status}
          tone={s.takeover ? 'good' : s.triggered ? 'bad' : s.sttOk.caller ? 'good' : 'neutral'} />
      </View>

      {s.connected && !s.ended && s.transcript.length === 0 && !s.triggered && (
        <Panel>
          <Text style={T.h2}>{watchCall ? 'Listening to your call' : listen ? 'Put your call on speaker' : 'Kavach is ready'}</Text>
          <Text style={T.muted}>{watchCall ? 'The caller\'s words and the scam meter will appear here.' : listen
            ? 'Hold the phone where Kavach can hear the caller. When they talk, the bar below moves and their words appear here.'
            : 'Waiting for the call. When someone talks, you will see the words here and the scam meter will move.'}</Text>
          {listen ? <Meter value={s.level * 100} color={C.accent} /> : null}
        </Panel>
      )}
      {s.micError ? <Panel style={{ borderColor: C.danger }}><Text style={{ color: C.danger }}>{s.micError}</Text></Panel> : null}

      {s.family && (
        <Panel style={{ backgroundColor: C.accent, borderColor: C.accent }}>
          <Text style={[T.h2, { color: '#fff' }]}>A message from your family is playing</Text>
          <Text style={{ color: '#fff', marginTop: 4 }}>{s.family.seconds} seconds. Listen to it now.</Text>
        </Panel>
      )}

      {speaking && (
        <Panel style={{ backgroundColor: C.danger, borderColor: C.danger }}>
          <Text style={[T.h2, { color: '#fff' }]}>Kavach is speaking to you</Text>
          <Text style={{ color: '#fff', marginTop: 4 }}>{s.warning?.text}</Text>
          <Text style={{ color: '#fff', marginTop: 6, fontSize: 13 }}>
            {listen ? 'Press MUTE on your phone call now, so the caller cannot hear this.' : 'Your microphone is muted to the caller while this plays. Speak to stop it.'}
          </Text>
        </Panel>
      )}
      {!speaking && s.warning && (
        <Panel>
          <Text style={T.h2}>{s.warning.state === 'interrupted' ? 'Warning stopped: you spoke' : 'Warning finished'}</Text>
          <Text style={T.muted}>{s.warning.text}</Text>
        </Panel>
      )}

      <SectionLabel>Scam risk</SectionLabel>
      <Panel>
        <View style={{ flexDirection: 'row', alignItems: 'baseline' }}>
          <Text style={{ color: riskColor, fontSize: 48, fontWeight: '800' }}>{s.risk}</Text>
          <Text style={[T.muted, { marginLeft: 6 }]}>/ 100{s.triggered ? '  ·  warning given' : ''}</Text>
        </View>
        <Meter value={s.risk} color={riskColor} />
        <View style={{ flexDirection: 'row', flexWrap: 'wrap' }}>
          {Object.entries(STAGE_LABELS).map(([k, label]) => (
            <Chip key={k} label={label} on={s.stages.includes(k)} now={s.stagesNow.includes(k)} />
          ))}
        </View>
        {s.rationale ? <Text style={[T.muted, { marginTop: 4 }]}>{s.rationale}</Text> : null}
      </Panel>

      {s.takeover && (
        <Panel style={{ borderColor: C.accent }}>
          <Text style={T.h2}>{watchCall ? 'Kavach is talking to the caller. Stay quiet.' : listen ? 'Kavach is talking to the caller through your speaker' : 'Kavach is on the call (the caller cannot hear you)'}</Text>
          {s.personaText ? <Text style={T.muted}>Kavach says: {s.personaText}</Text> : null}
        </Panel>
      )}

      {!s.ended ? (
        <View>
          {!s.takeover
            ? <Btn label="Hand over to Kavach" onPress={() => command('takeover')} />
            : <Btn label="Take back" kind="primary" onPress={() => command('takeback')} />}
          <Btn label={listen || watchCall ? 'Stop listening' : 'Hang up'} kind="danger" onPress={() => command('end_call')} />
        </View>
      ) : (
        <View>
          {s.report ? <ReportPanel settings={settings} callId={callId} report={s.report} />
            : <Panel><Text style={T.muted}>Call ended. Preparing your complaint draft if the call was flagged…</Text></Panel>}
          <Btn label="Back to home" onPress={() => { bridge.current?.send({ type: 'stop' }); onBack(); }} />
        </View>
      )}

      {s.evidence.length > 0 && (
        <Panel>
          <Text style={T.h2}>Evidence collected</Text>
          {s.evidence.map((e, i) => (
            <View key={i} style={{ marginTop: 6 }}>
              <Text style={T.muted}>{e.type.replace(/_/g, ' ')}</Text>
              <Text style={T.body}>{e.value}</Text>
            </View>
          ))}
        </Panel>
      )}

      <Panel>
        <Text style={T.h2}>What was said</Text>
        {s.transcript.slice(-8).map((t, i) => (
          <Text key={i} style={{ marginTop: 6, color: t.channel === 'caller' ? C.caller : C.receiver, opacity: t.final ? 1 : 0.6 }}>
            {t.channel === 'caller' ? 'Caller' : 'You'}: <Text style={{ color: C.ink }}>{t.text}</Text>
          </Text>
        ))}
        {s.transcript.length === 0 ? <Text style={T.muted}>Nothing yet.</Text> : null}
      </Panel>
    </Screen>
    {offerTakeover && (
      <View style={{ position: 'absolute', left: 12, right: 12, bottom: 24, padding: 14, borderRadius: 16,
                     backgroundColor: C.danger, elevation: 10, shadowColor: '#000', shadowOpacity: 0.3, shadowRadius: 10 }}>
        <Text style={[T.h2, { color: '#fff' }]}>This looks like a scam</Text>
        <Text style={{ color: '#fff', marginTop: 4, marginBottom: 8 }}>
          {listen ? 'Scared? Un-mute your call and stay quiet. Kavach will talk to the caller through your speaker.' : 'Scared? Let Kavach talk to the caller for you. The caller cannot hear you.'}
        </Text>
        <Btn label="Let Kavach take over" kind="primary" onPress={() => command('takeover')} />
      </View>
    )}
    </View>
  );
}
