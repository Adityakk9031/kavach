import React, { useState } from 'react';
import { Text, TextInput, View } from 'react-native';
import { Btn, C, Logo, Panel, Screen, T, input } from './ui';
import { Settings, saveSettings, testConnection } from './config';

export function SetupScreen({ initial, onSaved }: { initial: Settings | null; onSaved: (s: Settings) => void }) {
  const [url, setUrl] = useState(initial?.serverUrl ?? '');
  const [key, setKey] = useState(initial?.accessKey ?? '');
  const [result, setResult] = useState<{ ok: boolean; message: string } | null>(null);
  const [busy, setBusy] = useState(false);

  async function test() {
    setBusy(true);
    setResult(await testConnection({ serverUrl: url, accessKey: key }));
    setBusy(false);
  }
  async function save() {
    const s = { serverUrl: url, accessKey: key };
    await saveSettings(s);
    onSaved({ serverUrl: url.trim().replace(/\/+$/, ''), accessKey: key.trim() });
  }

  return (
    <Screen>
      <View style={{ marginBottom: 20 }}><Logo size={52} /></View>
      <Text style={T.h1}>Connect to Kavach</Text>
      <Text style={[T.muted, { marginTop: 6, marginBottom: 18 }]}>
        Kavach's brain runs on a secure server. Enter its address and your access code once. The AssemblyAI keys stay on the server, never on this device.
      </Text>
      <Panel>
        <Text style={T.body}>Server address (https)</Text>
        <TextInput value={url} onChangeText={setUrl} autoCapitalize="none" autoCorrect={false} keyboardType="url"
          placeholder="https://your-kavach-server" placeholderTextColor={C.muted} style={input} />
        <View style={{ height: 12 }} />
        <Text style={T.body}>Access code</Text>
        <TextInput value={key} onChangeText={setKey} autoCapitalize="none" autoCorrect={false} secureTextEntry
          placeholder="the code you set on the server" placeholderTextColor={C.muted} style={input} />
      </Panel>
      <Btn label={busy ? 'Testing…' : 'Test connection'} onPress={test} disabled={busy || !url} />
      {result && <Text style={{ color: result.ok ? C.accent : C.danger, marginBottom: 10 }}>{result.message}</Text>}
      <Btn label="Save" kind="primary" onPress={save} disabled={!url} />
    </Screen>
  );
}
