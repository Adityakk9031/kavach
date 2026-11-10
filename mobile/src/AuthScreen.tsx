// First screen for everyone: create a family account, sign in, or join a family from the protected phone with a code.
import React, { useEffect, useState } from 'react';
import { Pressable, Text, TextInput, View } from 'react-native';
import { Btn, C, Logo, Panel, Screen, T, input } from './ui';
import { Account, FALLBACK_LANGUAGES, Language, SERVER, languages, login, pair, saveSession, signup } from './account';
import type { Settings } from './config';

type Mode = 'welcome' | 'signup' | 'login' | 'join';
type Done = (s: Settings, a: Account) => void;

export function AuthScreen({ onDone, onAdvanced }: { onDone: Done; onAdvanced: () => void }) {
  const [mode, setMode] = useState<Mode>('welcome');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [parent, setParent] = useState('Mom');
  const [lang, setLang] = useState('en');
  const [langs, setLangs] = useState<Language[]>(FALLBACK_LANGUAGES);
  const [code, setCode] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => { languages(SERVER).then((r) => { if (r.ok && r.data.languages?.length) setLangs(r.data.languages); }); }, []);

  async function submit() {
    setBusy(true); setError('');
    const r = mode === 'signup' ? await signup(SERVER, { email, password, language: lang, parent_address: parent })
      : mode === 'login' ? await login(SERVER, email, password) : await pair(SERVER, code);
    if (!r.ok) { setError(r.error); setBusy(false); return; }
    const { settings, account } = await saveSession(r.data.token, r.data.role, r.data.family);
    onDone(settings, account);
  }

  const back = <Pressable onPress={() => { setMode('welcome'); setError(''); }} hitSlop={12} style={{ paddingBottom: 18 }}><Text style={{ color: C.ink, fontSize: 16, fontWeight: '600' }}>‹ Back</Text></Pressable>;

  if (mode === 'welcome') {
    return (
      <Screen top={72}>
        <View style={{ marginBottom: 26 }}><Logo size={52} /></View>
        <Text style={T.h1}>Protect your family from scam calls</Text>
        <Text style={[T.muted, { marginTop: 10, marginBottom: 30 }]}>
          Kavach listens for scams on a parent's phone, warns them in your voice, and tells you at once. Beta: English, Spanish and Portuguese.
        </Text>
        <Btn label="I look after someone" sub="Create your account" kind="primary" onPress={() => setMode('signup')} />
        <Btn label="This phone needs protection" sub="Join with the code from your family" onPress={() => setMode('join')} />
        <Btn label="I already have an account" onPress={() => setMode('login')} />
        <Pressable onPress={onAdvanced} style={{ padding: 14, alignItems: 'center' }}><Text style={T.muted}>Server settings (testers)</Text></Pressable>
      </Screen>
    );
  }

  const ready = mode === 'join' ? code.replace(/\D/g, '').length === 6 : email.includes('@') && password.length >= 8;
  return (
    <Screen top={64}>
      {back}
      <Text style={T.h1}>{mode === 'signup' ? 'Create your account' : mode === 'login' ? 'Welcome back' : 'Join your family'}</Text>
      {mode === 'join' ? (
        <>
          <Text style={[T.muted, { marginTop: 8, marginBottom: 16 }]}>Ask your family to open Kavach on their phone and show you the 6-digit code. It works for 10 minutes.</Text>
          <Panel><TextInput value={code} onChangeText={setCode} keyboardType="number-pad" maxLength={7} placeholder="000000" placeholderTextColor={C.muted}
            style={[input, { fontSize: 30, letterSpacing: 8, textAlign: 'center' }]} /></Panel>
        </>
      ) : (
        <>
          <Panel>
            <Text style={T.body}>Email</Text>
            <TextInput value={email} onChangeText={setEmail} autoCapitalize="none" autoCorrect={false} keyboardType="email-address" style={input} placeholder="you@example.com" placeholderTextColor={C.muted} />
            <View style={{ height: 10 }} />
            <Text style={T.body}>Password</Text>
            <TextInput value={password} onChangeText={setPassword} secureTextEntry autoCapitalize="none" style={input} placeholder="at least 8 characters" placeholderTextColor={C.muted} />
          </Panel>
          {mode === 'signup' && (
            <Panel>
              <Text style={T.body}>What do you call the person you protect?</Text>
              <TextInput value={parent} onChangeText={setParent} style={input} placeholder="Mom, Dad, Grandma…" placeholderTextColor={C.muted} />
              <Text style={[T.body, { marginTop: 14 }]}>Language of their calls</Text>
              <View style={{ flexDirection: 'row', flexWrap: 'wrap', marginTop: 8 }}>
                {langs.map((l) => (
                  <Pressable key={l.code} onPress={() => setLang(l.code)} style={{ borderRadius: 999, borderWidth: 1, borderColor: lang === l.code ? C.accent : C.line,
                    backgroundColor: lang === l.code ? C.accentSoft : C.panel, paddingHorizontal: 14, paddingVertical: 8, marginRight: 8, marginBottom: 8 }}>
                    <Text style={{ color: C.ink, fontWeight: lang === l.code ? '700' : '500' }}>{l.native}</Text>
                  </Pressable>
                ))}
              </View>
              <Text style={T.muted}>More languages are coming.</Text>
            </Panel>
          )}
        </>
      )}
      {error ? <Text style={{ color: C.danger, marginBottom: 10 }}>{error}</Text> : null}
      <Btn label={busy ? 'Please wait…' : mode === 'signup' ? 'Create account' : mode === 'login' ? 'Log in' : 'Join'} kind="primary" disabled={!ready || busy} onPress={submit} />
      {mode === 'signup' && <Text style={T.muted}>By continuing you agree that Kavach processes call audio and the voice recordings you choose to share, only to protect your family. You can delete them at any time.</Text>}
    </Screen>
  );
}
