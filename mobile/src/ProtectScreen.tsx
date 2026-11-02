// The protected person's screen: warning in the earpiece, risk, hand over / take back, evidence, complaint.
import React, { useEffect, useReducer, useRef, useState } from 'react';
import { PermissionsAndroid, Platform, ScrollView, Text, View } from 'react-native';
import { useKeepAwake } from 'expo-keep-awake';
import { AudioBridge, BridgeHandle } from './AudioBridge';
import { STAGE_LABELS, bridgeUrl, initialState, reduce } from './bridge';
import { Btn, C, Chip, Meter, Panel, T } from './ui';
import { ReportPanel } from './ReportPanel';
import type { Settings } from './config';

export function ProtectScreen({ settings, code, rehearsal, onBack }: {
  settings: Settings; code: string; rehearsal: boolean; onBack: () => void;
}) {
  useKeepAwake();
  const callId = `app-${code.toLowerCase()}`;
  const [s, dispatch] = useReducer(reduce, initialState);
  const bridge = useRef<BridgeHandle>(null);
  const [ready, setReady] = useState(Platform.OS !== 'android');

  useEffect(() => { // Android asks for the microphone itself; iOS asks inside the audio page
    if (Platform.OS !== 'android') return;
    PermissionsAndroid.request(PermissionsAndroid.PERMISSIONS.RECORD_AUDIO).finally(() => setReady(true));
  }, []);

  const speaking = s.warning?.state === 'speaking';
  const status = s.rejected ? s.rejected : s.ended ? 'Call ended' : s.closed ? s.closed
    : !s.connected ? 'Connecting…' : s.sttOk.caller ? 'Listening' : 'Connected, starting speech recognition…';
  const riskColor = s.risk >= 60 ? C.danger : s.risk >= 40 ? C.warn : C.accent;

  return (
    <ScrollView style={{ flex: 1, backgroundColor: C.bg }} contentContainerStyle={{ padding: 14, paddingTop: 50 }}>
      {ready && (
        <AudioBridge ref={bridge} onMessage={dispatch}
          uri={bridgeUrl(settings, { call: callId, role: 'receiver', mode: rehearsal ? 'eval' : 'live' })} />
      )}
      <Text style={T.h1}>Protected call</Text>
      <Text style={T.muted}>Code {code}{rehearsal ? ' · rehearsal (no Telegram alerts)' : ''} · {status}</Text>
      <View style={{ height: 12 }} />

      {s.micError ? <Panel style={{ borderColor: C.danger }}><Text style={{ color: C.danger }}>{s.micError}</Text></Panel> : null}

      {speaking && (
        <Panel style={{ backgroundColor: C.danger, borderColor: C.danger }}>
          <Text style={[T.h2, { color: '#fff' }]}>Kavach is speaking to you</Text>
          <Text style={{ color: '#fff', marginTop: 4 }}>{s.warning?.text}</Text>
          <Text style={{ color: '#fff', marginTop: 6, fontSize: 13 }}>
            Your microphone is muted to the caller while this plays. Speak to stop it.
          </Text>
        </Panel>
      )}
      {!speaking && s.warning && (
        <Panel>
          <Text style={T.h2}>{s.warning.state === 'interrupted' ? 'Warning stopped: you spoke' : 'Warning finished'}</Text>
          <Text style={T.muted}>{s.warning.text}</Text>
        </Panel>
      )}

      <Panel>
        <Text style={T.h2}>Scam risk {s.risk}{s.triggered ? '  ·  WARNING' : ''}</Text>
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
          <Text style={T.h2}>Kavach is on the call (the caller cannot hear you)</Text>
          {s.personaText ? <Text style={T.muted}>Kavach says: {s.personaText}</Text> : null}
        </Panel>
      )}

      {!s.ended ? (
        <View>
          {!s.takeover
            ? <Btn label="Hand over to Kavach" onPress={() => bridge.current?.send({ type: 'takeover' })} />
            : <Btn label="Take back" kind="primary" onPress={() => bridge.current?.send({ type: 'takeback' })} />}
          <Btn label="Hang up" kind="danger" onPress={() => bridge.current?.send({ type: 'end_call' })} />
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
    </ScrollView>
  );
}
