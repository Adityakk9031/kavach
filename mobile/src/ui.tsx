// Kavach design system: one calm dark theme, large touch targets, a centred column that also looks right on iPad and Mac.
import React from 'react';
import { Platform, Pressable, ScrollView, StyleProp, StyleSheet, Text, TextStyle, View, ViewStyle } from 'react-native';

export const C = {
  bg: '#0b1117', panel: '#121a22', raised: '#18232d', line: '#22313d', ink: '#eaf1f5', muted: '#8a9aa7',
  accent: '#2fd6a6', accentDeep: '#0f6f5a', danger: '#ff6b6b', warn: '#ffb547', caller: '#c08ae0', receiver: '#6fb1ff',
};
export const COLUMN = 560; // widest the content gets: phones fill the screen, iPad and Mac windows get a tidy column
const FONT = Platform.select({ ios: 'System', default: undefined });

export function Screen({ children, top = 64, bottom = 32, scroll = true }: { children: React.ReactNode; top?: number; bottom?: number; scroll?: boolean }) {
  const inner = <View style={{ width: '100%', maxWidth: COLUMN, paddingHorizontal: 18, paddingTop: top, paddingBottom: bottom }}>{children}</View>;
  if (!scroll) return <View style={{ flex: 1, backgroundColor: C.bg, alignItems: 'center' }}>{inner}</View>;
  return (
    <ScrollView style={{ flex: 1, backgroundColor: C.bg }} contentContainerStyle={{ alignItems: 'center' }}
      keyboardShouldPersistTaps="handled" showsVerticalScrollIndicator={false}>
      {inner}
    </ScrollView>
  );
}

// The Kavach mark: a shield drawn with plain views (no image to load, sharp at any size)
export function Logo({ size = 44 }: { size?: number }) {
  return (
    <View style={{ width: size, height: size * 1.15, backgroundColor: C.accent, alignItems: 'center', justifyContent: 'center',
      borderTopLeftRadius: size * 0.16, borderTopRightRadius: size * 0.16, borderBottomLeftRadius: size * 0.6, borderBottomRightRadius: size * 0.6 }}>
      <View style={{ width: size * 0.26, height: size * 0.46, borderColor: C.bg, borderRightWidth: size * 0.1, borderBottomWidth: size * 0.1,
        transform: [{ rotate: '40deg' }], marginTop: -size * 0.06 }} />
    </View>
  );
}

export function Title({ title, subtitle, right }: { title: string; subtitle?: string; right?: React.ReactNode }) {
  return (
    <View style={{ flexDirection: 'row', alignItems: 'center', marginBottom: 18 }}>
      <View style={{ flex: 1 }}>
        <Text style={T.h1}>{title}</Text>
        {subtitle ? <Text style={[T.muted, { marginTop: 4 }]}>{subtitle}</Text> : null}
      </View>
      {right}
    </View>
  );
}

export function SectionLabel({ children }: { children: string }) {
  return <Text style={T.label}>{children}</Text>;
}

export function Panel({ children, style }: { children: React.ReactNode; style?: StyleProp<ViewStyle> }) {
  return <View style={[s.panel, style]}>{children}</View>;
}

export function Pill({ label, tone = 'neutral' }: { label: string; tone?: 'neutral' | 'good' | 'warn' | 'bad' }) {
  const col = tone === 'good' ? C.accent : tone === 'warn' ? C.warn : tone === 'bad' ? C.danger : C.muted;
  return (
    <View style={{ flexDirection: 'row', alignItems: 'center', borderRadius: 999, paddingHorizontal: 12, paddingVertical: 6,
      backgroundColor: col + '22', borderWidth: 1, borderColor: col + '55' }}>
      <View style={{ width: 8, height: 8, borderRadius: 4, backgroundColor: col, marginRight: 8 }} />
      <Text style={{ color: col, fontSize: 13, fontWeight: '700', fontFamily: FONT }}>{label}</Text>
    </View>
  );
}

export function Btn({ label, onPress, kind = 'plain', disabled, sub }: {
  label: string; onPress: () => void; kind?: 'plain' | 'primary' | 'danger'; disabled?: boolean; sub?: string;
}) {
  const bg = kind === 'primary' ? C.accent : kind === 'danger' ? C.danger : C.raised;
  const fg = kind === 'primary' ? '#04251d' : kind === 'danger' ? '#2b0707' : C.ink;
  return (
    <Pressable onPress={onPress} disabled={disabled} accessibilityRole="button" accessibilityLabel={label}
      style={({ pressed }) => [s.btn, { backgroundColor: bg, borderColor: kind === 'plain' ? C.line : bg, opacity: disabled ? 0.4 : 1,
        transform: [{ scale: pressed ? 0.98 : 1 }] }]}>
      <Text style={[s.btnText, { color: fg }]}>{label}</Text>
      {sub ? <Text style={{ color: fg, opacity: 0.7, fontSize: 12, textAlign: 'center', marginTop: 2 }}>{sub}</Text> : null}
    </Pressable>
  );
}

export function Toggle({ value, onChange }: { value: boolean; onChange: (v: boolean) => void }) {
  return (
    <Pressable onPress={() => onChange(!value)} accessibilityRole="switch" accessibilityState={{ checked: value }} hitSlop={10}
      style={{ width: 54, height: 32, borderRadius: 16, backgroundColor: value ? C.accent : C.line, justifyContent: 'center', paddingHorizontal: 3 }}>
      <View style={{ width: 26, height: 26, borderRadius: 13, backgroundColor: '#fff', alignSelf: value ? 'flex-end' : 'flex-start' }} />
    </Pressable>
  );
}

export function Chip({ label, on, now }: { label: string; on: boolean; now?: boolean }) {
  return (
    <View style={[s.chip, on && { backgroundColor: C.warn + '33', borderColor: C.warn }, now && { backgroundColor: C.danger + '33', borderColor: C.danger }]}>
      <Text style={{ color: now ? C.danger : on ? C.warn : C.muted, fontSize: 13, fontWeight: on ? '700' : '500' }}>{label}</Text>
    </View>
  );
}

export function Meter({ value, color }: { value: number; color: string }) {
  return (
    <View style={s.meter}>
      <View style={{ width: `${Math.max(0, Math.min(100, value))}%`, height: '100%', backgroundColor: color, borderRadius: 7 }} />
    </View>
  );
}

export const T = {
  h1: { color: C.ink, fontSize: 30, fontWeight: '800' as const, letterSpacing: -0.5 } as TextStyle,
  h2: { color: C.ink, fontSize: 18, fontWeight: '700' as const } as TextStyle,
  body: { color: C.ink, fontSize: 16, lineHeight: 22 } as TextStyle,
  muted: { color: C.muted, fontSize: 14, lineHeight: 20 } as TextStyle,
  label: { color: C.muted, fontSize: 12, fontWeight: '700' as const, letterSpacing: 1.2, textTransform: 'uppercase' as const, marginBottom: 8, marginTop: 8 } as TextStyle,
};
export const input: TextStyle = { color: C.ink, backgroundColor: C.bg, borderColor: C.line, borderWidth: 1, borderRadius: 12, padding: 14, marginTop: 8, fontSize: 16 };

const s = StyleSheet.create({
  panel: { backgroundColor: C.panel, borderColor: C.line, borderWidth: 1, borderRadius: 18, padding: 16, marginBottom: 14 },
  btn: { borderRadius: 14, borderWidth: 1, minHeight: 54, justifyContent: 'center', paddingHorizontal: 16, paddingVertical: 10, marginBottom: 10 },
  btnText: { fontSize: 17, fontWeight: '700', textAlign: 'center' },
  chip: { borderRadius: 999, borderWidth: 1, borderColor: C.line, paddingHorizontal: 12, paddingVertical: 6, marginRight: 8, marginBottom: 8 },
  meter: { height: 14, backgroundColor: C.line, borderRadius: 7, overflow: 'hidden', marginVertical: 10 },
});
