// First launch: three short pages on what Kavach does, then who will use this phone.
import React, { useState } from 'react';
import { Pressable, Text, View } from 'react-native';
import { Btn, C, Logo, Screen, T } from './ui';
import type { Role } from './prefs';

const PAGES = [
  { n: '1', title: 'Kavach listens, so you are never alone on a call', body: 'When someone pressures you about money, police or your bank, Kavach notices the signs of a scam as the call happens. Normal calls are left alone.' },
  { n: '2', title: 'It speaks up in a voice you trust', body: 'If a call sounds like a scam, Kavach quietly warns you in your family\'s voice. The caller cannot hear it. Scared? Tap once and Kavach talks to the caller for you, in your own voice, and keeps the evidence.' },
  { n: '3', title: 'Your family is told at once', body: 'Your family gets a message straight away. They can end the call, or send you a voice note that plays on your phone. Kavach also prepares the complaint for 1930, for you to check and file.' },
];

export function Onboarding({ onDone }: { onDone: (role: Role) => void }) {
  const [i, setI] = useState(0);
  const last = i === PAGES.length;

  return (
    <Screen top={72}>
      {!last ? (
        <View>
          <View style={{ marginBottom: 28 }}><Logo size={56} /></View>
          <View style={{ width: 44, height: 44, borderRadius: 22, backgroundColor: C.accent + '22', alignItems: 'center', justifyContent: 'center', marginBottom: 16 }}>
            <Text style={{ color: C.accent, fontSize: 20, fontWeight: '800' }}>{PAGES[i].n}</Text>
          </View>
          <Text style={T.h1}>{PAGES[i].title}</Text>
          <Text style={[T.body, { color: C.muted, marginTop: 14, marginBottom: 30 }]}>{PAGES[i].body}</Text>
          <View style={{ flexDirection: 'row', marginBottom: 20 }}>
            {PAGES.map((_, k) => (
              <View key={k} style={{ height: 6, borderRadius: 3, marginRight: 6, width: k === i ? 28 : 8, backgroundColor: k === i ? C.accent : C.line }} />
            ))}
          </View>
          <Btn label="Next" kind="primary" onPress={() => setI(i + 1)} />
          <Pressable onPress={() => setI(PAGES.length)} style={{ padding: 12 }}>
            <Text style={[T.muted, { textAlign: 'center' }]}>Skip</Text>
          </Pressable>
        </View>
      ) : (
        <View>
          <Text style={T.h1}>Who will use this phone?</Text>
          <Text style={[T.muted, { marginTop: 8, marginBottom: 22 }]}>We will show you only what you need.</Text>
          <Pressable onPress={() => onDone('papa')} accessibilityRole="button">
            <View style={{ backgroundColor: C.accent, borderRadius: 18, padding: 20, marginBottom: 14 }}>
              <Text style={{ color: '#04251d', fontSize: 20, fontWeight: '800' }}>I want to be protected</Text>
              <Text style={{ color: '#04251d', opacity: 0.75, marginTop: 4 }}>For a parent or anyone who gets scam calls.</Text>
            </View>
          </Pressable>
          <Pressable onPress={() => onDone('family')} accessibilityRole="button">
            <View style={{ backgroundColor: C.panel, borderColor: C.line, borderWidth: 1, borderRadius: 18, padding: 20 }}>
              <Text style={{ color: C.ink, fontSize: 20, fontWeight: '800' }}>I look after someone</Text>
              <Text style={{ color: C.muted, marginTop: 4 }}>For a son, daughter or relative who wants to help from far away.</Text>
            </View>
          </Pressable>
        </View>
      )}
    </Screen>
  );
}
