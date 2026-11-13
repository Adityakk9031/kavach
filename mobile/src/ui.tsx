// Kavach design system: a warm, light, high-contrast theme that older eyes read easily. Green means protected, red means
// danger, near-black is for the main action. Large touch targets, a centred column that also looks right on iPad and Mac.
import React from 'react';
import { Platform, Pressable, ScrollView, StyleProp, StyleSheet, Text, TextStyle, View, ViewStyle } from 'react-native';

export const C = {
  bg: '#f4f1eb', panel: '#ffffff', raised: '#ebe6dd', line: '#ddd5c8', ink: '#1c1a17', muted: '#68625a',
  accent: '#1f6b43', accentSoft: '#e3efe6', danger: '#b3261e', warn: '#94600a', caller: '#9a3d12', receiver: '#1f4e8c',
  onDark: '#ffffff',
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
      <View style={{ width: size * 0.26, height: size * 0.46, borderColor: C.onDark, borderRightWidth: size * 0.1, borderBottomWidth: size * 0.1,
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
      backgroundColor: col + '14', borderWidth: 1, borderColor: col + '40' }}>
      <View style={{ width: 8, height: 8, borderRadius: 4, backgroundColor: col, marginRight: 8 }} />
      <Text style={{ color: col, fontSize: 13, fontWeight: '700', fontFamily: FONT }}>{label}</Text>
    </View>
  );
}

export function Btn({ label, onPress, kind = 'plain', disabled, sub }: {
  label: string; onPress: () => void; kind?: 'plain' | 'primary' | 'danger'; disabled?: boolean; sub?: string;
}) {
  const bg = kind === 'primary' ? C.ink : kind === 'danger' ? C.danger : C.panel;
  const fg = kind === 'plain' ? C.ink : C.onDark;
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
      <View style={{ width: 26, height: 26, borderRadius: 13, backgroundColor: C.onDark, alignSelf: value ? 'flex-end' : 'flex-start' }} />
    </Pressable>
  );
}

export function Chip({ label, on, now }: { label: string; on: boolean; now?: boolean }) {
  return (
    <View style={[s.chip, on && { backgroundColor: C.warn + '18', borderColor: C.warn }, now && { backgroundColor: C.danger + '18', borderColor: C.danger }]}>
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

export function BackLink({ label, onPress }: { label: string; onPress: () => void }) {
  return (
    <Pressable onPress={onPress} hitSlop={12} accessibilityRole="button" style={{ paddingBottom: 18, alignSelf: 'flex-start' }}>
      <Text style={{ color: C.ink, fontSize: 16, fontWeight: '600' }}>‹ {label}</Text>
    </Pressable>
  );
}

// A row of rounded choices where one is picked (languages)
export function Choices({ items, value, onPick }: { items: { code: string; native: string }[]; value: string; onPick: (code: string) => void }) {
  return (
    <View style={{ flexDirection: 'row', flexWrap: 'wrap' }}>
      {items.map((l) => {
        const on = value === l.code;
        return (
          <Pressable key={l.code} onPress={() => onPick(l.code)} accessibilityRole="button" accessibilityState={{ selected: on }}
            style={{ borderRadius: 999, borderWidth: 1, borderColor: on ? C.accent : C.line, backgroundColor: on ? C.accentSoft : C.panel,
              paddingHorizontal: 16, minHeight: 44, justifyContent: 'center', marginRight: 8, marginBottom: 8 }}>
            <Text style={{ color: C.ink, fontSize: 15, fontWeight: on ? '700' : '500' }}>{l.native}</Text>
          </Pressable>
        );
      })}
    </View>
  );
}

// The big card at the top of a home screen: green when everything is working, amber while something is still to do
export function Hero({ good, pill, title, body, children }: { good: boolean; pill: string; title: string; body: string; children?: React.ReactNode }) {
  const col = good ? C.accent : C.warn;
  return (
    <View style={{ borderRadius: 20, padding: 20, marginBottom: 18, backgroundColor: good ? C.accent : C.panel, borderWidth: 1, borderColor: good ? C.accent : col + '66' }}>
      <View style={{ flexDirection: 'row', alignItems: 'center', alignSelf: 'flex-start', borderRadius: 999, paddingHorizontal: 12, paddingVertical: 6,
        backgroundColor: good ? '#ffffff26' : col + '18', marginBottom: 14 }}>
        <View style={{ width: 8, height: 8, borderRadius: 4, backgroundColor: good ? C.onDark : col, marginRight: 8 }} />
        <Text style={{ color: good ? C.onDark : col, fontSize: 13, fontWeight: '700' }}>{pill}</Text>
      </View>
      <Text style={[T.h1, { color: good ? C.onDark : C.ink }]}>{title}</Text>
      <Text style={{ color: good ? C.onDark : C.muted, opacity: good ? 0.9 : 1, fontSize: 16, lineHeight: 23, marginTop: 8 }}>{body}</Text>
      {children}
    </View>
  );
}

// One numbered step: a round badge (a tick when done), a title, a line of help and whatever the step needs
export function Step({ n, title, body, done, first, children }: { n: number; title: string; body: string; done?: boolean; first?: boolean; children?: React.ReactNode }) {
  return (
    <View style={{ flexDirection: 'row', marginTop: first ? 0 : 20 }}>
      <View style={{ width: 32, height: 32, borderRadius: 16, borderWidth: 2, borderColor: done ? C.accent : C.line,
        backgroundColor: done ? C.accent : C.panel, alignItems: 'center', justifyContent: 'center', marginRight: 12 }}>
        <Text style={{ color: done ? C.onDark : C.muted, fontWeight: '700' }}>{done ? '✓' : n}</Text>
      </View>
      <View style={{ flex: 1 }}>
        <Text style={[T.body, { fontWeight: '600' }]}>{title}</Text>
        <Text style={[T.muted, { marginTop: 2, marginBottom: children ? 10 : 0 }]}>{body}</Text>
        {children}
      </View>
    </View>
  );
}

export function ErrorText({ children }: { children: string }) {
  return <Text accessibilityRole="alert" style={{ color: C.danger, fontSize: 15, lineHeight: 21, marginBottom: 12 }}>{children}</Text>;
}

export const T = {
  h1: { color: C.ink, fontSize: 28, fontWeight: '700' as const, letterSpacing: -0.4, lineHeight: 34 } as TextStyle,
  h2: { color: C.ink, fontSize: 18, fontWeight: '700' as const } as TextStyle,
  body: { color: C.ink, fontSize: 17, lineHeight: 24 } as TextStyle,
  muted: { color: C.muted, fontSize: 15, lineHeight: 21 } as TextStyle,
  label: { color: C.muted, fontSize: 13, fontWeight: '600' as const, marginBottom: 8, marginTop: 10 } as TextStyle,
};
export const input: TextStyle = { color: C.ink, backgroundColor: C.panel, borderColor: C.line, borderWidth: 1, borderRadius: 12, padding: 14, marginTop: 8, fontSize: 16 };

const s = StyleSheet.create({
  panel: { backgroundColor: C.panel, borderColor: C.line, borderWidth: 1, borderRadius: 14, padding: 16, marginBottom: 14 },
  btn: { borderRadius: 12, borderWidth: 1, minHeight: 56, justifyContent: 'center', paddingHorizontal: 16, paddingVertical: 10, marginBottom: 10 },
  btnText: { fontSize: 17, fontWeight: '700', textAlign: 'center' },
  chip: { borderRadius: 999, borderWidth: 1, borderColor: C.line, paddingHorizontal: 12, paddingVertical: 6, marginRight: 8, marginBottom: 8 },
  meter: { height: 14, backgroundColor: C.line, borderRadius: 7, overflow: 'hidden', marginVertical: 10 },
});
