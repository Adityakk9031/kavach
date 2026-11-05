import React, { useEffect, useRef, useState } from 'react';
import { ActivityIndicator, BackHandler, View } from 'react-native';
import { StatusBar } from 'expo-status-bar';
import { Settings, api, loadSettings } from './src/config';
import { SetupScreen } from './src/SetupScreen';
import { HomeScreen } from './src/HomeScreen';
import { ProtectScreen } from './src/ProtectScreen';
import { CallerScreen } from './src/CallerScreen';
import { VoiceScreen } from './src/VoiceScreen';
import { Onboarding } from './src/Onboarding';
import { EMPTY, Prefs, loadPrefs, savePrefs } from './src/prefs';
import { C } from './src/ui';

type Screen = { name: 'home' } | { name: 'setup' } | { name: 'voice' } | { name: 'protect' | 'caller'; code: string; rehearsal: boolean; listen?: boolean; watchCall?: string };

export default function App() {
  const [settings, setSettings] = useState<Settings | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [prefs, setPrefs] = useState<Prefs>(EMPTY);
  const [switching, setSwitching] = useState(false);
  const [screen, setScreen] = useState<Screen>({ name: 'home' });

  useEffect(() => {
    Promise.all([loadSettings(), loadPrefs()]).then(([s, p]) => { setSettings(s); setPrefs(p); setLoaded(true); if (!s) setScreen({ name: 'setup' }); });
  }, []);

  // A call the background listener is streaming opens here by itself. One the user left stays closed.
  const seenLive = useRef<string | null>(null);
  useEffect(() => {
    if (!settings || screen.name !== 'home') return;
    const { base, headers } = api(settings);
    const check = () => fetch(`${base}/api/calls/live`, { headers }).then((r) => r.json()).then((d) => {
      if (d.call_id && d.call_id !== seenLive.current) {
        seenLive.current = d.call_id;
        setScreen({ name: 'protect', code: d.call_id, rehearsal: false, watchCall: d.call_id });
      }
    }).catch(() => {});
    check();
    const timer = setInterval(check, 3000);
    return () => clearInterval(timer);
  }, [settings, screen.name]);

  // Android's back button: leave a sub-screen for Home, or cancel a user switch, instead of closing the app
  useEffect(() => {
    const sub = BackHandler.addEventListener('hardwareBackPress', () => {
      if (switching) { setSwitching(false); return true; }
      if (screen.name !== 'home') { setScreen({ name: 'home' }); return true; }
      return false;
    });
    return () => sub.remove();
  }, [screen, switching]);

  if (!loaded) return <View style={{ flex: 1, backgroundColor: C.bg, justifyContent: 'center' }}><ActivityIndicator color={C.accent} /></View>;

  const home = () => setScreen({ name: 'home' });
  const choose = (role: 'papa' | 'family') => { const p = { onboarded: true, role }; setPrefs(p); savePrefs(p); setSwitching(false); };
  let body: React.ReactNode;
  if (settings && screen.name === 'home' && switching) {
    body = <Onboarding startAtRoles onDone={choose} onCancel={() => setSwitching(false)} />;
  } else if (settings && !prefs.onboarded && screen.name === 'home') {
    body = <Onboarding onDone={choose} />;
  } else if (screen.name === 'setup' || !settings) {
    body = <SetupScreen initial={settings} onSaved={(s) => { setSettings(s); home(); }} onBack={settings ? home : undefined} />;
  } else if (screen.name === 'voice') {
    body = <VoiceScreen settings={settings} onBack={home} />;
  } else if (screen.name === 'protect') {
    body = <ProtectScreen key={screen.code} settings={settings} code={screen.code} rehearsal={screen.rehearsal} listen={screen.listen} watchCall={screen.watchCall} onBack={home} />;
  } else if (screen.name === 'caller') {
    body = <CallerScreen key={screen.code} settings={settings} code={screen.code} rehearsal={screen.rehearsal} onBack={home} />;
  } else {
    body = <HomeScreen role={prefs.role ?? 'papa'} settings={settings} onSwitch={() => setSwitching(true)} onReset={() => { const p = EMPTY; setPrefs(p); savePrefs(p); }} onProtect={(code, rehearsal, listen) => setScreen({ name: 'protect', code, rehearsal, listen })}
      onCaller={(code, rehearsal) => setScreen({ name: 'caller', code, rehearsal })} onSettings={() => setScreen({ name: 'setup' })}
      onVoice={() => setScreen({ name: 'voice' })} />;
  }
  return <View style={{ flex: 1, backgroundColor: C.bg }}><StatusBar style="light" />{body}</View>;
}
