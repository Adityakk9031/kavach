// Home on the protected phone: is Kavach on, and the few steps that turn it on. Every permission is asked for by itself,
// with a plain reason, and a blocked one gets a way out (the app's settings page).
// Testers who use an access code instead of an account also get the old family view and the tester tools (English only).
import React, { useCallback, useEffect, useState } from 'react';
import { AppState, Linking, PermissionsAndroid, Platform, Pressable, Text, View } from 'react-native';
import { Btn, C, Hero, Logo, Panel, Pill, Screen, SectionLabel, Step, T, Toggle } from './ui';
import { api, type Settings } from './config';
import { NONE, ProStatus, readPro } from './pro';
import { useT } from './lang';
import type { Role } from './prefs';

const P = PermissionsAndroid?.PERMISSIONS ?? ({} as typeof PermissionsAndroid.PERMISSIONS); // undefined in a web browser
const ANDROID = Platform.OS === 'android';
const rand = () => Array.from({ length: 4 }, () => 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'[Math.floor(Math.random() * 32)]).join('');

type Group = 'mic' | 'calls' | 'notify';
const GROUPS: Record<Group, string[]> = {
  mic: [P.RECORD_AUDIO],
  calls: [P.READ_PHONE_STATE, P.ANSWER_PHONE_CALLS],
  notify: Number(Platform.Version) >= 33 ? [P.POST_NOTIFICATIONS] : [],
};
type Grant = 'yes' | 'no' | 'blocked';

export function HomeScreen({ role, settings, onProtect, onCaller, onSettings, onVoice, onReset, onSwitch, onPro, signedIn }: {
  role: Role; settings: Settings; signedIn?: boolean;
  onProtect: (code: string, rehearsal: boolean, listen?: boolean) => void;
  onCaller: (code: string, rehearsal: boolean) => void;
  onSettings: () => void;
  onVoice: () => void;
  onReset: () => void;
  onSwitch: () => void;
  onPro?: () => void;
}) {
  const { t } = useT();
  const [code, setCode] = useState(rand());
  const [rehearsal, setRehearsal] = useState(true);
  const [tools, setTools] = useState(false);
  const [voice, setVoice] = useState<'unknown' | 'yes' | 'no'>('unknown');
  const [linked, setLinked] = useState<boolean | null>(null);
  const [grants, setGrants] = useState<Record<Group, Grant>>({ mic: 'no', calls: 'no', notify: 'no' });
  const [help, setHelp] = useState(false);
  const [pro, setPro] = useState<ProStatus>(NONE);
  const papa = role === 'papa';

  // The protected phone's call service writes its state to a file; this says if Full protection (Shizuku) is live
  useEffect(() => {
    if (!ANDROID || !papa) return;
    const read = () => readPro().then(setPro).catch(() => {});
    read();
    const timer = setInterval(read, 4000);
    return () => clearInterval(timer);
  }, [papa]);
  const fullOn = pro.running && pro.secure;

  // Permissions are read again whenever the person comes back from the settings app
  const checkGrants = useCallback(async () => {
    if (!ANDROID || !papa) return;
    const next = {} as Record<Group, Grant>;
    for (const g of Object.keys(GROUPS) as Group[]) {
      const ok = (await Promise.all(GROUPS[g].filter(Boolean).map((x) => PermissionsAndroid.check(x as any)))).every(Boolean);
      next[g] = ok ? 'yes' : 'no';
    }
    setGrants((old) => ({ mic: next.mic === 'yes' ? 'yes' : old.mic, calls: next.calls === 'yes' ? 'yes' : old.calls, notify: next.notify === 'yes' ? 'yes' : old.notify }));
  }, [papa]);
  useEffect(() => {
    checkGrants();
    const sub = AppState.addEventListener('change', (s) => { if (s === 'active') checkGrants(); });
    return () => sub.remove();
  }, [checkGrants]);

  async function allow(g: Group) {
    try {
      const r = await PermissionsAndroid.requestMultiple(GROUPS[g].filter(Boolean) as any);
      const v = Object.values(r);
      setGrants((old) => ({ ...old, [g]: v.every((x) => x === 'granted') ? 'yes' : v.some((x) => x === 'never_ask_again') ? 'blocked' : 'no' }));
    } catch { /* the row stays as it was */ }
  }

  useEffect(() => {
    const { base, headers } = api(settings);
    fetch(`${base}/api/voices`, { headers }).then((r) => r.json())
      .then((d) => setVoice(d.samples?.[papa ? 'papa' : 'son'] ? 'yes' : 'no')).catch(() => setVoice('unknown'));
    // Says whether the protected phone's call service is on the line to the Kavach server
    const check = () => fetch(`${base}/api/phone`, { headers }).then((r) => r.json())
      .then((d) => setLinked(typeof d.connected === 'boolean' ? d.connected : null)).catch(() => setLinked(null));
    check();
    const timer = setInterval(check, papa ? 5000 : 10000);
    return () => clearInterval(timer);
  }, [settings, papa]);

  const voicePill = voice === 'yes' ? <Pill label="Recorded" tone="good" /> : voice === 'no' ? <Pill label="Not yet" tone="warn" /> : null;
  const on = linked === true;
  const perm = (n: number, g: Group, title: string, body: string) => (
    <Step n={n} first={n === 1} title={title} body={grants[g] === 'blocked' ? t('p_blocked') : body} done={grants[g] === 'yes'}>
      {!ANDROID || grants[g] === 'yes' ? null
        : grants[g] === 'blocked' ? <Btn label={t('p_openSettings')} onPress={() => Linking.openSettings()} />
        : <Btn label={t('p_allow')} kind="primary" onPress={() => allow(g)} />}
    </Step>
  );

  return (
    <Screen>
      <View style={{ flexDirection: 'row', alignItems: 'center', marginBottom: 20 }}>
        <Logo size={32} />
        <Text style={[T.h2, { marginLeft: 12, flex: 1 }]}>Kavach</Text>
        {signedIn ? null
          : <Pressable onPress={onSettings} hitSlop={12} accessibilityRole="button"><Text style={{ color: C.muted, fontSize: 15 }}>{t('p_settings')}</Text></Pressable>}
      </View>

      {papa ? (
        <View>
          <Hero good={on} pill={on ? t('p_statusOn') : t('p_statusOff')} title={on ? t('p_on') : t('p_off')} body={on ? t('p_onBody') : t('p_offBody')} />

          {ANDROID && onPro ? (
            <Panel style={{ borderColor: (fullOn ? C.accent : C.warn) + '66' }}>
              <View style={{ flexDirection: 'row', alignItems: 'center', marginBottom: 6 }}>
                <Text style={[T.body, { flex: 1, fontWeight: '600' }]}>{fullOn ? t('p_lvlFull') : on ? t('p_lvlStd') : t('p_lvlOff')}</Text>
                <Pill label={fullOn ? t('ready') : on ? t('connected') : t('notYet')} tone={fullOn ? 'good' : 'warn'} />
              </View>
              <Text style={[T.muted, { marginBottom: fullOn ? 0 : 12 }]}>{fullOn ? t('p_lvlFullB') : on ? t('p_lvlStdB') : t('p_lvlOffB')}</Text>
              {!fullOn ? <Btn label={t('pro_open')} onPress={onPro} /> : null}
            </Panel>
          ) : null}

          <SectionLabel>{t('p_setup')}</SectionLabel>
          <Panel>
            {perm(1, 'mic', t('p_s1'), t('p_s1b'))}
            {perm(2, 'calls', t('p_s2'), t('p_s2b'))}
            {perm(3, 'notify', t('p_s3'), t('p_s3b'))}
            <Step n={4} title={t('p_s4')} body={t('p_s4b')} done={on}>
              {ANDROID && !on ? (
                <>
                  <Btn label={t('p_openAcc')} kind="primary" onPress={() => Linking.sendIntent('android.settings.ACCESSIBILITY_SETTINGS').catch(() => Linking.openSettings())} />
                  <Pressable onPress={() => setHelp(!help)} accessibilityRole="button" style={{ minHeight: 44, justifyContent: 'center' }}>
                    <Text style={{ color: C.accent, fontSize: 15, fontWeight: '600' }}>{t('p_restricted')}</Text>
                  </Pressable>
                  {help ? (
                    <View>
                      <Text style={[T.muted, { marginBottom: 10 }]}>{t('p_restrictedBody')}</Text>
                      <Btn label={t('p_appInfo')} onPress={() => Linking.openSettings()} />
                    </View>
                  ) : null}
                </>
              ) : null}
            </Step>
            <Step n={5} title={t('p_s5')} body={t('p_s5b')} done={voice === 'yes'}>
              <Btn label={voice === 'yes' ? t('v_again') : t('v_record')} onPress={onVoice} />
            </Step>
          </Panel>

          <SectionLabel>{t('p_during')}</SectionLabel>
          <Panel>
            {(fullOn ? (['p_during2', 'p_during3'] as const) : (['p_during1', 'p_during2', 'p_during3'] as const)).map((k, i) => (
              <View key={k} style={{ flexDirection: 'row', marginTop: i ? 12 : 0 }}>
                <Text style={{ color: C.accent, fontSize: 17, fontWeight: '700', width: 24 }}>{i + 1}</Text>
                <Text style={[T.body, { flex: 1 }]}>{t(k)}</Text>
              </View>
            ))}
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
        </View>
      )}

      <View style={{ flexDirection: 'row', justifyContent: 'center', flexWrap: 'wrap', marginTop: 8 }}>
        <Pressable onPress={onSwitch} style={{ padding: 12 }} accessibilityRole="button">
          <Text style={T.muted}>{signedIn ? t('p_leave') : papa ? 'Not Papa? Switch to family' : 'Switch to the protected phone'}</Text>
        </Pressable>
        {signedIn && process.env.EXPO_PUBLIC_KAVACH_PUBLIC === '1' ? null : (
          <Pressable onPress={() => setTools(!tools)} style={{ padding: 12 }} accessibilityRole="button">
            <Text style={T.muted}>{tools ? t('p_hideTools') : t('p_tools')}</Text>
          </Pressable>
        )}
      </View>
      {tools && (
        <Panel>
          {papa && <Btn label="Protect a call on speaker" sub="Opens the live screen: put the call on speaker first" onPress={() => onProtect(rand(), false, true)} />}
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
