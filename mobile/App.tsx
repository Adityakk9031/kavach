import React, { useEffect, useState } from 'react';
import { ActivityIndicator, View } from 'react-native';
import { StatusBar } from 'expo-status-bar';
import { Settings, loadSettings } from './src/config';
import { SetupScreen } from './src/SetupScreen';
import { HomeScreen } from './src/HomeScreen';
import { ProtectScreen } from './src/ProtectScreen';
import { CallerScreen } from './src/CallerScreen';
import { VoiceScreen } from './src/VoiceScreen';
import { Onboarding } from './src/Onboarding';
import { EMPTY, Prefs, loadPrefs, savePrefs } from './src/prefs';
import { C } from './src/ui';

type Screen = { name: 'home' } | { name: 'setup' } | { name: 'voice' } | { name: 'protect' | 'caller'; code: string; rehearsal: boolean };

export default function App() {
  const [settings, setSettings] = useState<Settings | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [prefs, setPrefs] = useState<Prefs>(EMPTY);
  const [screen, setScreen] = useState<Screen>({ name: 'home' });

  useEffect(() => {
    Promise.all([loadSettings(), loadPrefs()]).then(([s, p]) => { setSettings(s); setPrefs(p); setLoaded(true); if (!s) setScreen({ name: 'setup' }); });
  }, []);

  if (!loaded) return <View style={{ flex: 1, backgroundColor: C.bg, justifyContent: 'center' }}><ActivityIndicator color={C.accent} /></View>;

  const home = () => setScreen({ name: 'home' });
  const choose = (role: 'papa' | 'family') => { const p = { onboarded: true, role }; setPrefs(p); savePrefs(p); };
  let body: React.ReactNode;
  if (settings && !prefs.onboarded && screen.name === 'home') {
    body = <Onboarding onDone={choose} />;
  } else if (screen.name === 'setup' || !settings) {
    body = <SetupScreen initial={settings} onSaved={(s) => { setSettings(s); home(); }} />;
  } else if (screen.name === 'voice') {
    body = <VoiceScreen settings={settings} onBack={home} />;
  } else if (screen.name === 'protect') {
    body = <ProtectScreen key={screen.code} settings={settings} code={screen.code} rehearsal={screen.rehearsal} onBack={home} />;
  } else if (screen.name === 'caller') {
    body = <CallerScreen key={screen.code} settings={settings} code={screen.code} rehearsal={screen.rehearsal} onBack={home} />;
  } else {
    body = <HomeScreen role={prefs.role ?? 'papa'} settings={settings} onReset={() => { const p = EMPTY; setPrefs(p); savePrefs(p); }} onProtect={(code, rehearsal) => setScreen({ name: 'protect', code, rehearsal })}
      onCaller={(code, rehearsal) => setScreen({ name: 'caller', code, rehearsal })} onSettings={() => setScreen({ name: 'setup' })}
      onVoice={() => setScreen({ name: 'voice' })} />;
  }
  return <View style={{ flex: 1, backgroundColor: C.bg }}><StatusBar style="light" />{body}</View>;
}
