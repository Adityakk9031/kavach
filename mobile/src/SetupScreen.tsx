import React, { useState } from 'react';
import { ScrollView, Text, TextInput, View } from 'react-native';
import { Btn, C, Panel, T } from './ui';
import { Settings, saveSettings, testConnection } from './config';

export function SetupScreen({ initial, onSaved }: { initial: Settings | null; onSaved: (s: Settings) => void }) {
  const [url, setUrl] = useState(initial?.serverUrl ?? '');
  const [key, setKey] = useState(initial?.accessKey ?? '');
  const [result, setResult] = useState<{ ok: boolean; message: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const input = { color: C.ink, borderColor: C.line, borderWidth: 1, borderRadius: 8, padding: 12, marginTop: 6, fontSize: 16 };

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
    <ScrollView style={{ flex: 1, backgroundColor: C.bg }} contentContainerStyle={{ padding: 14, paddingTop: 60 }}>
      <Text style={T.h1}>Kavach setup</Text>
      <Text style={[T.muted, { marginVertical: 8 }]}>
        Kavach's brain runs on a server. Enter its address and your access code once. The AssemblyAI keys stay on the server, never on this phone.
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
    </ScrollView>
  );
}
