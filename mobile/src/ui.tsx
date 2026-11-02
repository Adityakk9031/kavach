import React from 'react';
import { Pressable, StyleSheet, Text, View, ViewStyle } from 'react-native';

export const C = {
  bg: '#15171a', panel: '#1e2125', line: '#2e3238', ink: '#e8e6e1', muted: '#9a9ea6',
  accent: '#4fb39a', danger: '#ef6b62', warn: '#e3a23b', caller: '#c08ae0', receiver: '#74a9e3',
};

export function Panel({ children, style }: { children: React.ReactNode; style?: ViewStyle }) {
  return <View style={[s.panel, style]}>{children}</View>;
}

export function Btn({ label, onPress, kind = 'plain', disabled }: {
  label: string; onPress: () => void; kind?: 'plain' | 'primary' | 'danger'; disabled?: boolean;
}) {
  const bg = kind === 'primary' ? C.accent : kind === 'danger' ? C.danger : C.panel;
  return (
    <Pressable onPress={onPress} disabled={disabled} accessibilityRole="button"
      style={({ pressed }) => [s.btn, { backgroundColor: bg, opacity: disabled ? 0.4 : pressed ? 0.8 : 1 }]}>
      <Text style={[s.btnText, { color: kind === 'plain' ? C.ink : '#fff' }]}>{label}</Text>
    </Pressable>
  );
}

export function Chip({ label, on, now }: { label: string; on: boolean; now?: boolean }) {
  return (
    <View style={[s.chip, on && { backgroundColor: C.warn, borderColor: C.warn }, now && { borderColor: C.danger, borderWidth: 2 }]}>
      <Text style={{ color: on ? '#fff' : C.muted, fontSize: 13 }}>{label}</Text>
    </View>
  );
}

export function Meter({ value, color }: { value: number; color: string }) {
  return (
    <View style={s.meter}>
      <View style={{ width: `${Math.max(0, Math.min(100, value))}%`, height: '100%', backgroundColor: color }} />
    </View>
  );
}

export const T = {
  h1: { color: C.ink, fontSize: 24, fontWeight: '700' as const },
  h2: { color: C.ink, fontSize: 17, fontWeight: '600' as const },
  body: { color: C.ink, fontSize: 15 },
  muted: { color: C.muted, fontSize: 13 },
};

const s = StyleSheet.create({
  panel: { backgroundColor: C.panel, borderColor: C.line, borderWidth: 1, borderRadius: 12, padding: 14, marginBottom: 12 },
  btn: { borderRadius: 10, borderWidth: 1, borderColor: C.line, minHeight: 48, justifyContent: 'center', paddingHorizontal: 14, marginBottom: 8 },
  btnText: { fontSize: 16, fontWeight: '600', textAlign: 'center' },
  chip: { borderRadius: 999, borderWidth: 1, borderColor: C.line, paddingHorizontal: 10, paddingVertical: 4, marginRight: 6, marginBottom: 6 },
  meter: { height: 12, backgroundColor: C.line, borderRadius: 6, overflow: 'hidden', marginVertical: 8 },
});
