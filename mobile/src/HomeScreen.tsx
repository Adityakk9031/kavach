import React, { useState } from 'react';
import { Switch, Text, View } from 'react-native';
import { Btn, C, Logo, Panel, Pill, Screen, SectionLabel, T } from './ui';

const rand = () => Array.from({ length: 4 }, () => 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'[Math.floor(Math.random() * 32)]).join('');

export function HomeScreen({ onProtect, onCaller, onSettings, onVoice }: {
  onProtect: (code: string, rehearsal: boolean) => void;
  onCaller: (code: string, rehearsal: boolean) => void;
  onSettings: () => void;
  onVoice: () => void;
}) {
  const [code, setCode] = useState(rand());
  const [rehearsal, setRehearsal] = useState(true);

  return (
    <Screen>
      <View style={{ flexDirection: 'row', alignItems: 'center', marginBottom: 6 }}>
        <Logo size={40} />
        <View style={{ marginLeft: 14, flex: 1 }}>
          <Text style={T.h1}>Kavach</Text>
          <Text style={T.muted}>A shield for the people we love</Text>
        </View>
        <Pill label={rehearsal ? 'Rehearsal' : 'Live alerts on'} tone={rehearsal ? 'neutral' : 'warn'} />
      </View>

      <View style={{ height: 14 }} />
      <SectionLabel>This call</SectionLabel>
      <Panel style={{ alignItems: 'center', paddingVertical: 22 }}>
        <Text style={T.muted}>Both phones use this code</Text>
        <View style={{ flexDirection: 'row', marginVertical: 14 }}>
          {code.split('').map((ch, i) => (
            <View key={i} style={{ width: 56, height: 68, marginHorizontal: 5, borderRadius: 14, backgroundColor: C.raised,
              borderWidth: 1, borderColor: C.line, alignItems: 'center', justifyContent: 'center' }}>
              <Text style={{ color: C.ink, fontSize: 32, fontWeight: '800' }}>{ch}</Text>
            </View>
          ))}
        </View>
        <Text style={[T.muted, { textAlign: 'center' }]}>A code works for one call only.</Text>
        <View style={{ height: 12, width: '100%' }} />
        <View style={{ width: '100%' }}><Btn label="New code" onPress={() => setCode(rand())} /></View>
      </Panel>

      <Panel>
        <View style={{ flexDirection: 'row', alignItems: 'center' }}>
          <View style={{ flex: 1, paddingRight: 12 }}>
            <Text style={T.h2}>Rehearsal mode</Text>
            <Text style={T.muted}>On: no Telegram messages are sent. Turn it off for the real demo.</Text>
          </View>
          <Switch value={rehearsal} onValueChange={setRehearsal} trackColor={{ true: C.accent, false: C.line }} />
        </View>
      </Panel>

      <SectionLabel>Start</SectionLabel>
      <Btn label="I am being called: protect me" sub="Kavach listens and warns you" kind="primary" onPress={() => onProtect(code, rehearsal)} />
      <Btn label="I am the test caller" sub="On a friend's phone, plays the scammer" onPress={() => onCaller(code, rehearsal)} />

      <SectionLabel>Set up</SectionLabel>
      <Btn label="My voice" sub="Record a consented sample so Kavach can speak as you" onPress={onVoice} />
      <Btn label="Server and access code" onPress={onSettings} />

      <Text style={[T.muted, { marginTop: 10, textAlign: 'center' }]}>
        Kavach carries the call itself, between the two phones, so it can whisper the warning and mute you toward the caller.
        It cannot hear ordinary phone-network calls: no app can.
      </Text>
    </Screen>
  );
}
