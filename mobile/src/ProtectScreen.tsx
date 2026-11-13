// The protected person's screen: warning in the earpiece, risk, hand over / take back, evidence, complaint.
import React, { useEffect, useReducer, useRef, useState } from 'react';
import { PermissionsAndroid, Platform, Pressable, Text, View } from 'react-native';
import { useKeepAwake } from 'expo-keep-awake';
import { AudioBridge, BridgeHandle } from './AudioBridge';
import { STAGE_LABELS, bridgeUrl, initialState, reduce } from './bridge';
import { useT, type Key } from './lang';
import { Btn, C, Chip, Meter, Panel, Pill, Screen, SectionLabel, T, Title } from './ui';
import { ReportPanel } from './ReportPanel';
import { api, type Settings } from './config';

export function ProtectScreen({ settings, code, rehearsal, listen = false, watchCall, onBack }: {
  settings: Settings; code: string; rehearsal: boolean; listen?: boolean; watchCall?: string; onBack: () => void;
}) {
  useKeepAwake();
  const { t } = useT();
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
  const status = s.rejected ? s.rejected : s.ended ? t('c_ended') : s.closed ? s.closed
    : !s.connected ? t('c_connecting') : s.sttOk.caller ? t('c_listening') : t('c_gettingReady');
  const riskColor = s.risk >= 60 ? C.danger : s.risk >= 40 ? C.warn : C.accent;

  // After the warning, a big card floats over everything so a scared person can hand the call over with one tap
  const offerTakeover = s.triggered && !s.takeover && !s.ended;

  return (
    <View style={{ flex: 1, backgroundColor: C.bg }}>
    <Screen bottom={offerTakeover ? 220 : 32}>
      {!s.ended && (
        <Pressable onPress={() => { bridge.current?.send({ type: 'stop' }); onBack(); }} hitSlop={12} style={{ paddingBottom: 14 }}>
          <Text style={{ color: C.ink, fontSize: 16, fontWeight: '600' }}>‹ {t('home')}</Text>
        </Pressable>
      )}
      {ready && !watchCall && (
        <AudioBridge ref={bridge} onMessage={dispatch}
          uri={bridgeUrl(settings, { call: callId, role: listen ? 'listen' : 'receiver', mode: rehearsal ? 'eval' : 'live' })} />
      )}
      <Title title={t('c_title')} subtitle={rehearsal ? `Test code ${code} · no Telegram alerts` : undefined} />
      <View style={{ flexDirection: 'row', marginTop: -6, marginBottom: 16 }}>
        <Pill label={s.takeover ? t('c_onCall') : s.triggered ? t('c_warning') : status}
          tone={s.takeover ? 'good' : s.triggered ? 'bad' : s.sttOk.caller ? 'good' : 'neutral'} />
      </View>

      {s.connected && !s.ended && s.transcript.length === 0 && !s.triggered && (
        <Panel>
          <Text style={T.h2}>{watchCall ? t('c_listenT') : listen ? t('c_speakerT') : t('c_readyT')}</Text>
          <Text style={T.muted}>{watchCall ? t('c_listenB') : listen ? t('c_speakerB') : t('c_readyB')}</Text>
          {listen ? <Meter value={s.level * 100} color={C.accent} /> : null}
        </Panel>
      )}
      {s.micError ? <Panel style={{ borderColor: C.danger }}><Text style={{ color: C.danger }}>{s.micError}</Text></Panel> : null}

      {s.family && (
        <Panel style={{ backgroundColor: C.accent, borderColor: C.accent }}>
          <Text style={[T.h2, { color: C.onDark }]}>{t('c_familyT')}</Text>
          <Text style={{ color: C.onDark, marginTop: 4 }}>{t('c_familyB', { s: s.family.seconds })}</Text>
        </Panel>
      )}

      {speaking && (
        <Panel style={{ backgroundColor: C.danger, borderColor: C.danger }}>
          <Text style={[T.h2, { color: C.onDark }]}>{t('c_speakT')}</Text>
          <Text style={{ color: C.onDark, marginTop: 4 }}>{s.warning?.text}</Text>
          <Text style={{ color: C.onDark, marginTop: 6, fontSize: 13 }}>
            {listen ? t('c_muteHint') : t('c_micHint')}
          </Text>
        </Panel>
      )}
      {!speaking && s.warning && (
        <Panel>
          <Text style={T.h2}>{s.warning.state === 'interrupted' ? t('c_warnStopped') : t('c_warnDone')}</Text>
          <Text style={T.muted}>{s.warning.text}</Text>
        </Panel>
      )}

      <SectionLabel>{t('c_risk')}</SectionLabel>
      <Panel>
        <View style={{ flexDirection: 'row', alignItems: 'baseline' }}>
          <Text style={{ color: riskColor, fontSize: 48, fontWeight: '800' }}>{s.risk}</Text>
          <Text style={[T.muted, { marginLeft: 6 }]}>/ 100{s.triggered ? `  ·  ${t('c_warned')}` : ''}</Text>
        </View>
        <Meter value={s.risk} color={riskColor} />
        <View style={{ flexDirection: 'row', flexWrap: 'wrap' }}>
          {Object.keys(STAGE_LABELS).map((k) => (
            <Chip key={k} label={t(('st_' + k) as Key)} on={s.stages.includes(k)} now={s.stagesNow.includes(k)} />
          ))}
        </View>
        {s.rationale ? <Text style={[T.muted, { marginTop: 4 }]}>{s.rationale}</Text> : null}
      </Panel>

      {s.takeover && (
        <Panel style={{ borderColor: C.accent }}>
          <Text style={T.h2}>{watchCall ? t('c_takeWatch') : listen ? t('c_takeSpeaker') : t('c_takeDirect')}</Text>
          {s.personaText ? <Text style={T.muted}>{t('c_says', { text: s.personaText })}</Text> : null}
        </Panel>
      )}

      {!s.ended ? (
        <View>
          {!s.takeover
            ? <Btn label={t('c_hand')} onPress={() => command('takeover')} />
            : <Btn label={t('c_takeBack')} kind="primary" onPress={() => command('takeback')} />}
          <Btn label={listen || watchCall ? t('c_stop') : t('c_hang')} kind="danger" onPress={() => command('end_call')} />
        </View>
      ) : (
        <View>
          {s.report ? <ReportPanel settings={settings} callId={callId} report={s.report} />
            : <Panel><Text style={T.muted}>{t('c_preparing')}</Text></Panel>}
          <Btn label={t('c_backHome')} onPress={() => { bridge.current?.send({ type: 'stop' }); onBack(); }} />
        </View>
      )}

      {s.evidence.length > 0 && (
        <Panel>
          <Text style={T.h2}>{t('c_evidence')}</Text>
          {s.evidence.map((e, i) => (
            <View key={i} style={{ marginTop: 6 }}>
              <Text style={T.muted}>{e.type.replace(/_/g, ' ')}</Text>
              <Text style={T.body}>{e.value}</Text>
            </View>
          ))}
        </Panel>
      )}

      <Panel>
        <Text style={T.h2}>{t('c_said')}</Text>
        {s.transcript.slice(-8).map((line, i) => (
          <Text key={i} style={{ marginTop: 6, color: line.channel === 'caller' ? C.caller : C.receiver, opacity: line.final ? 1 : 0.6 }}>
            {line.channel === 'caller' ? t('c_caller') : line.channel === 'kavach' ? 'Kavach' : t('c_you')}: <Text style={{ color: C.ink }}>{line.text}</Text>
          </Text>
        ))}
        {s.transcript.length === 0 ? <Text style={T.muted}>{t('c_nothing')}</Text> : null}
      </Panel>
    </Screen>
    {offerTakeover && (
      <View style={{ position: 'absolute', left: 12, right: 12, bottom: 24, padding: 14, borderRadius: 16,
                     backgroundColor: C.danger, elevation: 10, shadowColor: '#000', shadowOpacity: 0.3, shadowRadius: 10 }}>
        <Text style={[T.h2, { color: C.onDark }]}>{t('c_scamT')}</Text>
        <Text style={{ color: C.onDark, marginTop: 4, marginBottom: 8 }}>
          {listen ? t('c_scamSpeaker') : t('c_scamDirect')}
        </Text>
        <Btn label={t('c_take')} kind="primary" onPress={() => command('takeover')} />
      </View>
    )}
    </View>
  );
}
