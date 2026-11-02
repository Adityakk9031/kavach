import React, { useState } from 'react';
import { ScrollView, Switch, Text, View } from 'react-native';
import { Btn, C, Panel, T } from './ui';

const rand = () => Array.from({ length: 4 }, () => 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'[Math.floor(Math.random() * 32)]).join('');

export function HomeScreen({ onProtect, onCaller, onSettings }: {
  onProtect: (code: string, rehearsal: boolean) => void;
  onCaller: (code: string, rehearsal: boolean) => void;
  onSettings: () => void;
}) {
  const [code, setCode] = useState(rand());
  const [rehearsal, setRehearsal] = useState(true);

  return (
    <ScrollView style={{ flex: 1, backgroundColor: C.bg }} contentContainerStyle={{ padding: 14, paddingTop: 60 }}>
      <Text style={T.h1}>Kavach</Text>
      <Text style={[T.muted, { marginBottom: 12 }]}>Scam-call protector</Text>

      <Panel>
        <Text style={T.body}>Call code</Text>
        <Text style={{ color: C.ink, fontSize: 38, letterSpacing: 6, textAlign: 'center', marginVertical: 8 }}>{code}</Text>
        <Text style={T.muted}>Both phones use the same code. A code works for one call only.</Text>
        <View style={{ height: 8 }} />
        <Btn label="New code" onPress={() => setCode(rand())} />
      </Panel>

      <Panel>
        <View style={{ flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' }}>
          <View style={{ flex: 1, paddingRight: 10 }}>
            <Text style={T.body}>Rehearsal</Text>
            <Text style={T.muted}>On: no Telegram messages are sent. Turn off for the real demo.</Text>
          </View>
          <Switch value={rehearsal} onValueChange={setRehearsal} />
        </View>
      </Panel>

      <Btn label="I am being called (protect me)" kind="primary" onPress={() => onProtect(code, rehearsal)} />
      <Btn label="I am the test caller (friend's phone)" onPress={() => onCaller(code, rehearsal)} />
      <Btn label="Settings" onPress={onSettings} />
      <Text style={[T.muted, { marginTop: 12 }]}>
        Kavach carries the call itself, between the two phones, so it can whisper the warning and mute the person. It does not
        listen to ordinary phone-network calls: no phone app can.
      </Text>
    </ScrollView>
  );
}
