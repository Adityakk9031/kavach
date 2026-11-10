// Home, for the two kinds of user: the person being protected, and the family member looking after them.
// Each sees only their own part: the protected person sets the phone up once, the family member records the warning voice.
import React, { useEffect, useState } from 'react';
import { Linking, PermissionsAndroid, Platform, Pressable, Text, View } from 'react-native';
import { Btn, C, Logo, Panel, Pill, Screen, SectionLabel, T, Toggle } from './ui';
import { api, type Settings } from './config';
import type { Role } from './prefs';

const P = PermissionsAndroid.PERMISSIONS;
const rand = () => Array.from({ length: 4 }, () => 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'[Math.floor(Math.random() * 32)]).join('');

function Step({ n, title, body, done, children }: { n: number; title: string; body: string; done?: boolean; children?: React.ReactNode }) {
  return (
    <View style={{ flexDirection: 'row', marginTop: n > 1 ? 18 : 0 }}>
      <View style={{ width: 30, height: 30, borderRadius: 15, borderWidth: 2, borderColor: done ? C.accent : C.line,
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

export function HomeScreen({ role, settings, onProtect, onCaller, onSettings, onVoice, onReset, onSwitch, signedIn }: {
  role: Role; settings: Settings; signedIn?: boolean;
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
  const [linked, setLinked] = useState<boolean | null>(null);
  const papa = role === 'papa';
  const [allowed, setAllowed] = useState(false);
  const wanted = () => [P.RECORD_AUDIO, P.READ_PHONE_STATE, P.ANSWER_PHONE_CALLS, ...(Number(Platform.Version) >= 33 ? [P.POST_NOTIFICATIONS] : [])].filter(Boolean) as any[];
  useEffect(() => {
    if (Platform.OS !== 'android' || !papa) return;
    Promise.all(wanted().map((x) => PermissionsAndroid.check(x))).then((r) => setAllowed(r.every(Boolean))).catch(() => {});
  }, [papa]);
  async function allow() {
    const r = await PermissionsAndroid.requestMultiple(wanted());
    setAllowed(Object.values(r).every((v) => v === 'granted'));
  }

  useEffect(() => {
    const { base, headers } = api(settings);
    fetch(`${base}/api/voices`, { headers }).then((r) => r.json())
      .then((d) => setVoice(d.samples?.[papa ? 'papa' : 'son'] ? 'yes' : 'no')).catch(() => setVoice('unknown'));
    if (papa) return;
    // The family's app and Papa's phone share this Kavach server; this says whether Papa's phone is on the line to it
    const check = () => fetch(`${base}/api/phone`, { headers }).then((r) => r.json())
      .then((d) => setLinked(typeof d.connected === 'boolean' ? d.connected : null)).catch(() => setLinked(null));
    check();
    const timer = setInterval(check, 10000);
    return () => clearInterval(timer);
  }, [settings, papa]);

  const voicePill = voice === 'yes' ? <Pill label="Recorded" tone="good" /> : voice === 'no' ? <Pill label="Not yet" tone="warn" /> : null;

  return (
    <Screen>
      <View style={{ flexDirection: 'row', alignItems: 'center', marginBottom: 24 }}>
        <Logo size={32} />
        <Text style={[T.h2, { marginLeft: 12, flex: 1 }]}>Kavach</Text>
        <Pressable onPress={onSettings} hitSlop={12} accessibilityRole="button"><Text style={{ color: C.muted, fontSize: 15 }}>Settings</Text></Pressable>
      </View>

      {papa ? (
        <View>
          <Text style={T.h1}>Your calls are protected</Text>
          <Text style={[T.muted, { marginTop: 8, marginBottom: 20 }]}>
            On every call, Kavach listens for a scam. If it hears one, it warns you quietly in your family's voice.
            A small Kavach button stays on the screen during the call: tap it to turn Kavach off for that call, tap again to turn it back on.
          </Text>

          <SectionLabel>Set up once</SectionLabel>
          <Panel>
            <Step n={1} title="Allow Kavach" done={allowed} body="Kavach needs the microphone, to know when a call is on, and to end a scam call when your family asks.">
              {Platform.OS === 'android' && !allowed ? <Btn label="Allow" kind="primary" onPress={allow} /> : null}
            </Step>
            <Step n={2} title="Turn on Kavach" body={'In Accessibility, open "Kavach call protection" and switch it on.'}>
              {Platform.OS === 'android' ? <Btn label="Open Accessibility" kind="primary" onPress={() => Linking.sendIntent('android.settings.ACCESSIBILITY_SETTINGS')} /> : null}
            </Step>
            <Step n={3} title="Record your voice" done={voice === 'yes'}
              body="Up to three short takes. If you hand a call over, Kavach talks to the caller in your own voice, so the caller does not know.">
              <Btn label={voice === 'yes' ? 'Record again' : 'Record my voice'} onPress={onVoice} />
            </Step>
            <Step n={4} title="During a call" body="Tap Speaker on the call screen so Kavach can hear the caller. A small Kavach card shows it is listening." />
          </Panel>
        </View>
      ) : (
        <View>
          <Text style={T.h1}>You look after Papa</Text>
          <Text style={[T.muted, { marginTop: 8, marginBottom: 20 }]}>
            If a call to Papa looks like a scam, you get a Telegram message within seconds.
          </Text>

          <Panel>
            <View style={{ flexDirection: 'row', alignItems: 'center' }}>
              <Text style={[T.body, { flex: 1, fontWeight: '600' }]}>Papa's phone</Text>
              {linked === null ? null : <Pill label={linked ? 'Connected' : 'Not connected'} tone={linked ? 'good' : 'warn'} />}
            </View>
            <Text style={[T.muted, { marginTop: 6 }]}>
              {linked === false ? 'Kavach is not running on Papa\'s phone right now. Check that it is on in Accessibility there.'
                : 'Both phones use the same Kavach server, so your voice and messages reach Papa.'}
            </Text>
          </Panel>

          <Panel>
            <View style={{ flexDirection: 'row', alignItems: 'center', marginBottom: 6 }}>
              <Text style={[T.body, { flex: 1, fontWeight: '600' }]}>Your voice for the warning</Text>
              {voicePill}
            </View>
            <Text style={[T.muted, { marginBottom: 12 }]}>Record 20 seconds. Papa hears the scam warning in your voice, so he trusts it.</Text>
            <Btn label={voice === 'yes' ? 'Record again' : 'Record my voice'} kind={voice === 'yes' ? 'plain' : 'primary'} onPress={onVoice} />
          </Panel>

          <SectionLabel>From the Telegram alert you can</SectionLabel>
          <Panel>
            {[['End the call', 'Tap the button under the alert. The call on Papa\'s phone is cut.'],
              ['Send a voice note', 'It plays on Papa\'s phone straight away, during the call or after it.'],
              ['Get the report draft', 'A PDF arrives after the call, for you to check and file.']].map(([t, b], k) => (
              <View key={t} style={{ marginTop: k ? 14 : 0 }}>
                <Text style={[T.body, { fontWeight: '600' }]}>{t}</Text>
                <Text style={T.muted}>{b}</Text>
              </View>
            ))}
          </Panel>
        </View>
      )}

      <View style={{ flexDirection: 'row', justifyContent: 'center', flexWrap: 'wrap', marginTop: 8 }}>
        <Pressable onPress={onSwitch} style={{ padding: 12 }} accessibilityRole="button">
          <Text style={T.muted}>{signedIn ? 'Leave this family' : papa ? 'Not Papa? Switch to family' : 'Switch to the protected phone'}</Text>
        </Pressable>
        <Pressable onPress={() => setTools(!tools)} style={{ padding: 12 }} accessibilityRole="button">
          <Text style={T.muted}>{tools ? 'Hide tester tools' : 'Tester tools'}</Text>
        </Pressable>
      </View>
      {tools && (
        <Panel>
          {papa && <Btn label="Protect a call on speaker" sub="Without Shizuku: put the call on speaker first" onPress={() => onProtect(rand(), false, true)} />}
          <Text style={T.muted}>Two-phone test code (both phones use the same one)</Text>
          <View style={{ flexDirection: 'row', justifyContent: 'center', marginVertical: 12 }}>
            {code.split('').map((ch, i) => (
              <View key={i} style={{ width: 50, height: 60, marginHorizontal: 4, borderRadius: 10, backgroundColor: C.raised,
                borderWidth: 1, borderColor: C.line, alignItems: 'center', justifyContent: 'center' }}>
                <Text style={{ color: C.ink, fontSize: 28, fontWeight: '700' }}>{ch}</Text>
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
