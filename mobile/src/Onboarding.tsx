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

export function Onboarding({ onDone, startAtRoles = false, onCancel }: { onDone: (role: Role) => void; startAtRoles?: boolean; onCancel?: () => void }) {
  const [i, setI] = useState(startAtRoles ? PAGES.length : 0);
  const last = i === PAGES.length;

  return (
    <Screen top={72}>
      {!last ? (
        <View>
          <View style={{ marginBottom: 28 }}><Logo size={48} /></View>
          <Text style={[T.muted, { marginBottom: 8 }]}>{PAGES[i].n} of {PAGES.length}</Text>
          <Text style={T.h1}>{PAGES[i].title}</Text>
          <Text style={[T.body, { color: C.muted, marginTop: 14, marginBottom: 30 }]}>{PAGES[i].body}</Text>
          <View style={{ flexDirection: 'row', marginBottom: 20 }}>
            {PAGES.map((_, k) => (
              <View key={k} style={{ height: 4, borderRadius: 2, marginRight: 6, width: k === i ? 24 : 8, backgroundColor: k === i ? C.ink : C.line }} />
            ))}
          </View>
          <Btn label="Next" kind="primary" onPress={() => setI(i + 1)} />
          <View style={{ flexDirection: 'row', justifyContent: 'space-between' }}>
            {i > 0 ? <Pressable onPress={() => setI(i - 1)} style={{ padding: 12 }}><Text style={T.muted}>‹ Back</Text></Pressable> : <View />}
            <Pressable onPress={() => setI(PAGES.length)} style={{ padding: 12 }}><Text style={T.muted}>Skip</Text></Pressable>
          </View>
        </View>
      ) : (
        <View>
          <Pressable onPress={() => (onCancel ? onCancel() : setI(PAGES.length - 1))} style={{ paddingBottom: 18 }} hitSlop={12}>
            <Text style={{ color: C.ink, fontSize: 16, fontWeight: '600' }}>‹ {onCancel ? 'Cancel' : 'Back'}</Text>
          </Pressable>
          <Text style={T.h1}>Whose phone is this?</Text>
          <Text style={[T.muted, { marginTop: 8, marginBottom: 22 }]}>You will see only what you need. You can change this later.</Text>
          <Pressable onPress={() => onDone('papa')} accessibilityRole="button">
            <View style={{ backgroundColor: C.panel, borderColor: C.line, borderWidth: 1, borderRadius: 14, padding: 20, marginBottom: 12 }}>
              <Text style={{ color: C.ink, fontSize: 20, fontWeight: '700' }}>This phone is the one to protect</Text>
              <Text style={{ color: C.muted, marginTop: 4, fontSize: 15 }}>For Papa, Mummy or anyone who gets scam calls. Kavach runs on this phone.</Text>
            </View>
          </Pressable>
          <Pressable onPress={() => onDone('family')} accessibilityRole="button">
            <View style={{ backgroundColor: C.panel, borderColor: C.line, borderWidth: 1, borderRadius: 14, padding: 20 }}>
              <Text style={{ color: C.ink, fontSize: 20, fontWeight: '700' }}>I look after someone</Text>
              <Text style={{ color: C.muted, marginTop: 4, fontSize: 15 }}>For the son or daughter. Record your voice for the warning and get the alerts.</Text>
            </View>
          </Pressable>
        </View>
      )}
    </Screen>
  );
}
