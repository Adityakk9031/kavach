// Home, for the two kinds of user: the person being protected, and the family member looking after them.
import React, { useEffect, useState } from 'react';
import { Pressable, Text, View } from 'react-native';
import { Btn, C, Logo, Panel, Pill, Screen, SectionLabel, T, Toggle } from './ui';
import { api, type Settings } from './config';
import type { Role } from './prefs';

const rand = () => Array.from({ length: 4 }, () => 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'[Math.floor(Math.random() * 32)]).join('');

const HOW = [
  ['Listens', 'Kavach hears the call and spots pressure about money, police or your bank.'],
  ['Warns you privately', 'A trusted voice speaks only to you. The caller hears nothing.'],
  ['Takes over if you are scared', 'One tap, and Kavach talks to the caller in your voice and keeps the evidence.'],
  ['Tells your family', 'They get a message, can end the call, or send you a voice note.'],
  ['Prepares your complaint', 'A draft for 1930 for you to check and file yourself.'],
];

export function HomeScreen({ role, settings, onProtect, onCaller, onSettings, onVoice, onReset, onSwitch }: {
  role: Role; settings: Settings;
  onProtect: (code: string, rehearsal: boolean, listen?: boolean) => void;
  onCaller: (code: string, rehearsal: boolean) => void;
  onSettings: () => void;
  onVoice: () => void;
  onReset: () => void;
  onSwitch: () => void;
}) {
  const [code, setCode] = useState(rand());
  const [rehearsal, setRehearsal] = useState(true);
  const [tools, setTools] = useState(false);
  const [voice, setVoice] = useState<'unknown' | 'yes' | 'no'>('unknown');
  const person = role === 'papa' ? 'papa' : 'son';

  useEffect(() => {
    const { base, headers } = api(settings);
    fetch(`${base}/api/voices`, { headers }).then((r) => r.json())
      .then((d) => setVoice(d.samples?.[person] ? 'yes' : 'no')).catch(() => setVoice('unknown'));
  }, [settings, person]);

  const voiceCard = (
    <Panel>
      <View style={{ flexDirection: 'row', alignItems: 'center', marginBottom: 6 }}>
        <Text style={[T.h2, { flex: 1 }]}>{role === 'papa' ? 'Your voice' : 'Your voice for Papa'}</Text>
        {voice === 'yes' ? <Pill label="Recorded" tone="good" /> : voice === 'no' ? <Pill label="Not yet" tone="warn" /> : null}
      </View>
      <Text style={[T.muted, { marginBottom: 12 }]}>
        {role === 'papa'
          ? 'Record 20 seconds so Kavach can sound like you when it talks to a caller for you.'
          : 'Record 20 seconds. Kavach can use your voice for the warning Papa hears, so it sounds like you.'}
      </Text>
      <Btn label={voice === 'yes' ? 'Record again' : 'Record my voice'} kind={voice === 'yes' ? 'plain' : 'primary'} onPress={onVoice} />
    </Panel>
  );

  return (
    <Screen>
      <View style={{ flexDirection: 'row', alignItems: 'center', marginBottom: 20 }}>
        <Logo size={36} />
        <Text style={[T.h2, { marginLeft: 12, flex: 1 }]}>Kavach</Text>
        <Pressable onPress={onSwitch} hitSlop={12} accessibilityRole="button" style={{ marginRight: 16 }}>
          <Text style={{ color: C.accent, fontWeight: '600' }}>{role === 'papa' ? 'Protected ▾' : 'Family ▾'}</Text>
        </Pressable>
        <Pressable onPress={onSettings} hitSlop={12}><Text style={{ color: C.muted }}>Settings</Text></Pressable>
      </View>

      {role === 'papa' ? (
        <View>
          <View style={{ backgroundColor: C.accentDeep, borderRadius: 22, padding: 22, marginBottom: 16 }}>
            <Text style={{ color: '#fff', fontSize: 28, fontWeight: '800' }}>You are protected</Text>
            <Text style={{ color: '#d6f5ec', marginTop: 8, fontSize: 16, lineHeight: 22 }}>
              When a call worries you, put it on speaker, open Kavach and tap the button below. It listens and warns you if it sounds like a scam.
            </Text>
          </View>
          <Btn label="Protect my call" sub="Put the call on speaker first" kind="primary" onPress={() => onProtect(rand(), false, true)} />
          {voiceCard}
          <SectionLabel>How Kavach helps</SectionLabel>
          <Panel>
            {HOW.map(([t, b], k) => (
              <View key={t} style={{ flexDirection: 'row', marginTop: k ? 14 : 0 }}>
                <View style={{ width: 28, height: 28, borderRadius: 14, backgroundColor: C.accent + '22', alignItems: 'center', justifyContent: 'center', marginRight: 12 }}>
                  <Text style={{ color: C.accent, fontWeight: '800' }}>{k + 1}</Text>
                </View>
                <View style={{ flex: 1 }}>
                  <Text style={T.body}>{t}</Text>
                  <Text style={T.muted}>{b}</Text>
                </View>
              </View>
            ))}
          </Panel>
        </View>
      ) : (
        <View>
          <View style={{ backgroundColor: C.accentDeep, borderRadius: 22, padding: 22, marginBottom: 16 }}>
            <Text style={{ color: '#fff', fontSize: 28, fontWeight: '800' }}>You look after Papa</Text>
            <Text style={{ color: '#d6f5ec', marginTop: 8, fontSize: 16, lineHeight: 22 }}>
              If a call to Papa looks like a scam, you get a message on Telegram within seconds.
            </Text>
          </View>
          {voiceCard}
          <SectionLabel>What you can do from Telegram</SectionLabel>
          <Panel>
            {[['End the call', 'Tap the button in the alert and the call is cut.'],
              ['Send a voice note', 'Record one in the bot chat. It plays on Papa\'s phone at once, even after the call ended.'],
              ['Answer two questions', 'Did money or an OTP go out? That fills in the complaint draft.'],
              ['Get the complaint', 'A PDF draft for 1930 arrives after the call.']].map(([t, b], k) => (
              <View key={t} style={{ marginTop: k ? 14 : 0 }}>
                <Text style={T.body}>{t}</Text>
                <Text style={T.muted}>{b}</Text>
              </View>
            ))}
          </Panel>
        </View>
      )}

      <Pressable onPress={() => setTools(!tools)} style={{ padding: 14 }}>
        <Text style={[T.muted, { textAlign: 'center' }]}>{tools ? 'Hide tester tools' : 'Tester tools'}</Text>
      </Pressable>
      {tools && (
        <Panel>
          <Text style={T.muted}>Two-phone test code (both phones use the same one)</Text>
          <View style={{ flexDirection: 'row', justifyContent: 'center', marginVertical: 12 }}>
            {code.split('').map((ch, i) => (
              <View key={i} style={{ width: 50, height: 60, marginHorizontal: 4, borderRadius: 12, backgroundColor: C.raised,
                borderWidth: 1, borderColor: C.line, alignItems: 'center', justifyContent: 'center' }}>
                <Text style={{ color: C.ink, fontSize: 28, fontWeight: '800' }}>{ch}</Text>
              </View>
            ))}
          </View>
          <Btn label="New code" onPress={() => setCode(rand())} />
          <View style={{ flexDirection: 'row', alignItems: 'center', marginVertical: 8 }}>
            <View style={{ flex: 1, paddingRight: 12 }}>
              <Text style={T.body}>Rehearsal mode</Text>
              <Text style={T.muted}>On: no Telegram messages are sent.</Text>
            </View>
            <Toggle value={rehearsal} onChange={setRehearsal} />
          </View>
          <Btn label="Protect with this code" onPress={() => onProtect(code, rehearsal)} />
          <Btn label="Be the test caller" onPress={() => onCaller(code, rehearsal)} />
          <Btn label="Show the welcome again" onPress={onReset} />
        </Panel>
      )}
    </Screen>
  );
}
