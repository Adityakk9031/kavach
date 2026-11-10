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
import { AuthScreen } from './src/AuthScreen';
import { FamilyHome } from './src/FamilyHome';
import { Account, loadAccount, signOut, writeNativeConfig } from './src/account';
import { EMPTY, Prefs, loadPrefs, savePrefs } from './src/prefs';
import { C } from './src/ui';

type Screen = { name: 'home' } | { name: 'setup' } | { name: 'voice' } | { name: 'protect' | 'caller'; code: string; rehearsal: boolean; listen?: boolean; watchCall?: string };

export default function App() {
  const [settings, setSettings] = useState<Settings | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [prefs, setPrefs] = useState<Prefs>(EMPTY);
  const [account, setAccount] = useState<Account | null>(null);
  const [switching, setSwitching] = useState(false);
  const [screen, setScreen] = useState<Screen>({ name: 'home' });

  useEffect(() => {
    Promise.all([loadSettings(), loadPrefs(), loadAccount()]).then(([s, p, a]) => {
      setSettings(s); setPrefs(p); setAccount(a); setLoaded(true);
      if (s && a) writeNativeConfig(s); // the background call service protects calls as this account
    });
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
  const signedOut = async () => { await signOut(); setSettings(null); setAccount(null); setScreen({ name: 'home' }); };
  let body: React.ReactNode;
  if (!settings && screen.name !== 'setup') {
    body = <AuthScreen onDone={(s, a) => { setSettings(s); setAccount(a); const p = { onboarded: true, role: a.role === 'son' ? 'family' as const : 'papa' as const }; setPrefs(p); savePrefs(p); home(); }}
      onAdvanced={() => setScreen({ name: 'setup' })} />;
  } else if (settings && account && screen.name === 'home' && account.role === 'son') {
    body = <FamilyHome settings={settings} account={account} onVoice={() => setScreen({ name: 'voice' })} onSignOut={signedOut}
      onPickLanguage={(code) => setAccount({ ...account, language: code })} />;
  } else if (settings && account && screen.name === 'home') {
    body = <HomeScreen role="papa" settings={settings} onSwitch={signedOut} signedIn onReset={() => {}} onProtect={(code, rehearsal, listen) => setScreen({ name: 'protect', code, rehearsal, listen })}
      onCaller={(code, rehearsal) => setScreen({ name: 'caller', code, rehearsal })} onSettings={() => setScreen({ name: 'setup' })} onVoice={() => setScreen({ name: 'voice' })} />;
  } else if (settings && screen.name === 'home' && switching) {
    body = <Onboarding startAtRoles onDone={choose} onCancel={() => setSwitching(false)} />;
  } else if (settings && !prefs.onboarded && screen.name === 'home') {
    body = <Onboarding onDone={choose} />;
  } else if (screen.name === 'setup' || !settings) {
    body = <SetupScreen initial={settings} onSaved={(s) => { setSettings(s); home(); }} onBack={settings ? home : undefined} />;
  } else if (screen.name === 'voice') {
    body = <VoiceScreen settings={settings} person={(account ? account.role === 'son' : prefs.role === 'family') ? 'son' : 'papa'} onBack={home} />;
  } else if (screen.name === 'protect') {
    body = <ProtectScreen key={screen.code} settings={settings} code={screen.code} rehearsal={screen.rehearsal} listen={screen.listen} watchCall={screen.watchCall} onBack={home} />;
  } else if (screen.name === 'caller') {
    body = <CallerScreen key={screen.code} settings={settings} code={screen.code} rehearsal={screen.rehearsal} onBack={home} />;
  } else {
    body = <HomeScreen role={prefs.role ?? 'papa'} settings={settings} onSwitch={() => setSwitching(true)} onReset={() => { const p = EMPTY; setPrefs(p); savePrefs(p); }} onProtect={(code, rehearsal, listen) => setScreen({ name: 'protect', code, rehearsal, listen })}
      onCaller={(code, rehearsal) => setScreen({ name: 'caller', code, rehearsal })} onSettings={() => setScreen({ name: 'setup' })}
      onVoice={() => setScreen({ name: 'voice' })} />;
  }
  return <View style={{ flex: 1, backgroundColor: C.bg }}><StatusBar style="dark" />{body}</View>;
}
