import React, { useEffect, useState } from 'react';
import { ActivityIndicator, View } from 'react-native';
import { StatusBar } from 'expo-status-bar';
import { Settings, loadSettings } from './src/config';
import { SetupScreen } from './src/SetupScreen';
import { HomeScreen } from './src/HomeScreen';
import { ProtectScreen } from './src/ProtectScreen';
import { CallerScreen } from './src/CallerScreen';
import { VoiceScreen } from './src/VoiceScreen';
import { C } from './src/ui';

type Screen = { name: 'home' } | { name: 'setup' } | { name: 'voice' } | { name: 'protect' | 'caller'; code: string; rehearsal: boolean };

export default function App() {
  const [settings, setSettings] = useState<Settings | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [screen, setScreen] = useState<Screen>({ name: 'home' });

  useEffect(() => {
    loadSettings().then((s) => { setSettings(s); setLoaded(true); if (!s) setScreen({ name: 'setup' }); });
  }, []);

  if (!loaded) return <View style={{ flex: 1, backgroundColor: C.bg, justifyContent: 'center' }}><ActivityIndicator color={C.accent} /></View>;

  const home = () => setScreen({ name: 'home' });
  let body: React.ReactNode;
  if (screen.name === 'setup' || !settings) {
    body = <SetupScreen initial={settings} onSaved={(s) => { setSettings(s); home(); }} />;
  } else if (screen.name === 'voice') {
    body = <VoiceScreen settings={settings} onBack={home} />;
  } else if (screen.name === 'protect') {
    body = <ProtectScreen key={screen.code} settings={settings} code={screen.code} rehearsal={screen.rehearsal} onBack={home} />;
  } else if (screen.name === 'caller') {
    body = <CallerScreen key={screen.code} settings={settings} code={screen.code} rehearsal={screen.rehearsal} onBack={home} />;
  } else {
    body = <HomeScreen onProtect={(code, rehearsal) => setScreen({ name: 'protect', code, rehearsal })}
      onCaller={(code, rehearsal) => setScreen({ name: 'caller', code, rehearsal })} onSettings={() => setScreen({ name: 'setup' })}
      onVoice={() => setScreen({ name: 'voice' })} />;
  }
  return <View style={{ flex: 1, backgroundColor: C.bg }}><StatusBar style="light" />{body}</View>;
}
