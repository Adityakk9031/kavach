// The test caller's screen (the friend's phone, playing the scammer). Everything the microphone hears reaches the other phone.
import React, { useReducer, useRef, useState, useEffect } from 'react';
import { PermissionsAndroid, Platform, Text, View } from 'react-native';
import { useKeepAwake } from 'expo-keep-awake';
import { AudioBridge, BridgeHandle } from './AudioBridge';
import { bridgeUrl, initialState, reduce } from './bridge';
import { Btn, C, Meter, Panel, Pill, Screen, Title } from './ui';
import { T } from './ui';
import type { Settings } from './config';

export function CallerScreen({ settings, code, rehearsal, onBack }: {
  settings: Settings; code: string; rehearsal: boolean; onBack: () => void;
}) {
  useKeepAwake();
  const [s, dispatch] = useReducer(reduce, initialState);
  const bridge = useRef<BridgeHandle>(null);
  const [ready, setReady] = useState(Platform.OS !== 'android');
  const [number, setNumber] = useState('+91 98201 33456');
  useEffect(() => {
    if (Platform.OS !== 'android') return;
    PermissionsAndroid.request(PermissionsAndroid.PERMISSIONS.RECORD_AUDIO).finally(() => setReady(true));
  }, []);
  const status = s.rejected ?? (s.ended ? 'Call ended' : s.closed ?? (!s.connected ? 'Connecting…' : 'On the line'));

  return (
    <Screen>
      {ready && (
        <AudioBridge ref={bridge} onMessage={dispatch}
          uri={bridgeUrl(settings, { call: `app-${code.toLowerCase()}`, role: 'caller', mode: rehearsal ? 'eval' : 'live', callerNumber: number })} />
      )}
      <Title title="Test caller" subtitle={`Code ${code}`} right={<Pill label={status} tone={s.connected && !s.ended ? 'good' : 'neutral'} />} />
      {s.micError ? <Panel style={{ borderColor: C.danger }}><Text style={{ color: C.danger }}>{s.micError}</Text></Panel> : null}
      <Panel>
        <Text style={T.body}>You are playing the scammer. Talk into the phone (read docs/demo/scam_call_script.txt), or play the sample.</Text>
        <Meter value={s.level * 100} color={C.accent} />
      </Panel>
      <Btn label="Play a sample scammer call (94 s)" onPress={() => bridge.current?.send({ type: 'sample' })} disabled={!s.connected || s.ended} />
      <Btn label="End the call" kind="danger" onPress={() => bridge.current?.send({ type: 'end_call' })} disabled={!s.connected || s.ended} />
      <Btn label="Back to home" onPress={() => { bridge.current?.send({ type: 'stop' }); onBack(); }} />
    </Screen>
  );
}
