// First screen for everyone: pick a language, then create a family account, log in, or join a family from the
// protected phone with a code. Sign-up may need the email confirmed first; the screen waits for that and carries on.
import React, { useEffect, useState } from 'react';
import { Pressable, Text, TextInput, View } from 'react-native';
import { BackLink, Btn, C, Choices, ErrorText, Logo, Panel, Screen, SectionLabel, T, input } from './ui';
import { Account, AuthResult, FALLBACK_LANGUAGES, Language, SERVER, languages, pair, resetPassword, saveSession, signIn, signUp } from './account';
import { LANGS } from './i18n/core';
import { useT } from './lang';
import type { Settings } from './config';

type Mode = 'welcome' | 'signup' | 'login' | 'join' | 'confirm' | 'reset';
type Done = (s: Settings, a: Account) => void;

export function AuthScreen({ onDone, onAdvanced }: { onDone: Done; onAdvanced: () => void }) {
  const { t, te, lang, setLang } = useT();
  const [mode, setMode] = useState<Mode>('welcome');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [parent, setParent] = useState('');
  const [callLang, setCallLang] = useState<string | null>(null); // until picked, the calls use the app's language
  const [langs, setLangs] = useState<Language[]>(FALLBACK_LANGUAGES);
  const [code, setCode] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [sent, setSent] = useState(false);

  useEffect(() => { languages(SERVER).then((r) => { if (r.ok && r.data.languages?.length) setLangs(r.data.languages); }); }, []);
  const callLanguage = callLang ?? (langs.some((l) => l.code === lang) ? lang : 'en');
  const go = (m: Mode) => { setMode(m); setError(''); setSent(false); };

  async function finish(r: AuthResult) {
    if (r.kind === 'error') { setError(te(r.error)); setBusy(false); return; }
    if (r.kind === 'confirm') { setBusy(false); go('confirm'); return; }
    const { settings, account } = await saveSession(r.session.token, r.session.role, r.session.family);
    if (account.role === 'parent') setLang(account.language); // the protected phone speaks the family's language
    onDone(settings, account);
  }

  async function submit() {
    setBusy(true); setError('');
    if (mode === 'signup') return finish(await signUp(SERVER, email, password, { language: callLanguage, parent_address: parent.trim() || t('a_parentPlaceholder').split(',')[0] }));
    if (mode === 'login' || mode === 'confirm') return finish(await signIn(SERVER, email, password));
    if (mode === 'reset') {
      const r = await resetPassword(SERVER, email);
      setBusy(false);
      if (!r.ok) setError(te(r.error)); else if (!r.data) setError(t('e_generic')); else setSent(true);
      return;
    }
    const r = await pair(SERVER, code);
    return finish(r.ok ? { kind: 'session', session: r.data } : { kind: 'error', error: r.error });
  }

  if (mode === 'welcome') {
    return (
      <Screen top={56}>
        <View style={{ flexDirection: 'row', alignItems: 'center', marginBottom: 28 }}>
          <Logo size={40} /><Text style={[T.h2, { marginLeft: 12, fontSize: 22 }]}>Kavach</Text>
        </View>
        <Text style={[T.h1, { fontSize: 32, lineHeight: 38 }]}>{t('w_title')}</Text>
        <Text style={[T.muted, { fontSize: 17, lineHeight: 24, marginTop: 12, marginBottom: 22 }]}>{t('w_body')}</Text>
        <Choices items={LANGS} value={lang} onPick={setLang} />
        <View style={{ height: 14 }} />
        <Btn label={t('w_carer')} sub={t('w_carerSub')} kind="primary" onPress={() => go('signup')} />
        <Btn label={t('w_parent')} sub={t('w_parentSub')} onPress={() => go('join')} />
        <Pressable onPress={() => go('login')} accessibilityRole="button" style={{ minHeight: 48, justifyContent: 'center', alignItems: 'center' }}>
          <Text style={{ color: C.accent, fontSize: 16, fontWeight: '700' }}>{t('w_login')}</Text>
        </Pressable>

        <SectionLabel>{t('w_how')}</SectionLabel>
        <Panel>
          {([['how1', 'how1b'], ['how2', 'how2b'], ['how3', 'how3b']] as const).map(([a, b], k) => (
            <View key={a} style={{ flexDirection: 'row', marginTop: k ? 16 : 0 }}>
              <View style={{ width: 30, height: 30, borderRadius: 15, backgroundColor: C.accentSoft, alignItems: 'center', justifyContent: 'center', marginRight: 12 }}>
                <Text style={{ color: C.accent, fontWeight: '700' }}>{k + 1}</Text>
              </View>
              <View style={{ flex: 1 }}><Text style={[T.body, { fontWeight: '600' }]}>{t(a)}</Text><Text style={[T.muted, { marginTop: 2 }]}>{t(b)}</Text></View>
            </View>
          ))}
        </Panel>
        {process.env.EXPO_PUBLIC_KAVACH_PUBLIC === '1' ? null
          : <Pressable onPress={onAdvanced} style={{ padding: 14, alignItems: 'center' }}><Text style={T.muted}>{t('w_testers')}</Text></Pressable>}
      </Screen>
    );
  }

  if (mode === 'confirm') {
    return (
      <Screen top={64}>
        <BackLink label={t('back')} onPress={() => go('signup')} />
        <Text style={T.h1}>{t('a_checkTitle')}</Text>
        <Text style={[T.muted, { fontSize: 17, lineHeight: 24, marginTop: 10, marginBottom: 22 }]}>{t('a_checkBody', { email: email.trim() })}</Text>
        {error ? <ErrorText>{error}</ErrorText> : null}
        <Btn label={busy ? t('wait') : t('a_checkBtn')} kind="primary" disabled={busy} onPress={submit} />
      </Screen>
    );
  }

  const emailOk = /^\S+@\S+\.\S+$/.test(email.trim());
  const ready = mode === 'join' ? code.replace(/\D/g, '').length === 6 : mode === 'reset' ? emailOk : emailOk && password.length >= 8;
  const title = mode === 'signup' ? t('a_create') : mode === 'login' ? t('a_welcomeBack') : mode === 'reset' ? t('a_resetTitle') : t('a_join');
  const action = mode === 'signup' ? t('a_createBtn') : mode === 'login' ? t('a_loginBtn') : mode === 'reset' ? t('a_resetBtn') : t('a_joinBtn');
  return (
    <Screen top={64}>
      <BackLink label={t('back')} onPress={() => go(mode === 'reset' ? 'login' : 'welcome')} />
      <Text style={[T.h1, { marginBottom: 8 }]}>{title}</Text>
      {mode === 'join' ? (
        <>
          <Text style={[T.muted, { marginBottom: 16 }]}>{t('a_joinBody')}</Text>
          <Panel><TextInput value={code} onChangeText={setCode} keyboardType="number-pad" maxLength={7} placeholder="000000" placeholderTextColor={C.line}
            autoFocus style={[input, { marginTop: 0, fontSize: 34, fontWeight: '700', letterSpacing: 10, textAlign: 'center' }]} /></Panel>
        </>
      ) : (
        <>
          {mode === 'reset' ? <Text style={[T.muted, { marginBottom: 8 }]}>{t('a_resetBody')}</Text> : null}
          <Panel style={{ marginTop: 8 }}>
            <Text style={T.body}>{t('a_email')}</Text>
            <TextInput value={email} onChangeText={setEmail} autoCapitalize="none" autoCorrect={false} keyboardType="email-address" autoComplete="email"
              style={input} placeholder="you@example.com" placeholderTextColor={C.muted} />
            {mode !== 'reset' && (
              <>
                <Text style={[T.body, { marginTop: 14 }]}>{t('a_password')}</Text>
                <TextInput value={password} onChangeText={setPassword} secureTextEntry autoCapitalize="none" style={input}
                  placeholder={t('a_passwordHint')} placeholderTextColor={C.muted} />
              </>
            )}
          </Panel>
          {mode === 'signup' && (
            <Panel>
              <Text style={T.body}>{t('a_parentName')}</Text>
              <TextInput value={parent} onChangeText={setParent} style={input} placeholder={t('a_parentPlaceholder')} placeholderTextColor={C.muted} maxLength={24} />
              <Text style={[T.body, { marginTop: 16, marginBottom: 10 }]}>{t('a_callLang')}</Text>
              <Choices items={langs} value={callLanguage} onPick={setCallLang} />
            </Panel>
          )}
        </>
      )}
      {error ? <ErrorText>{error}</ErrorText> : null}
      {sent ? <Panel style={{ borderColor: C.accent, backgroundColor: C.accentSoft }}><Text style={T.body}>{t('a_resetSent', { email: email.trim() })}</Text></Panel> : null}
      <Btn label={busy ? t('wait') : action} kind="primary" disabled={!ready || busy} onPress={submit} />
      {mode === 'login' && (
        <Pressable onPress={() => go('reset')} accessibilityRole="button" style={{ minHeight: 48, justifyContent: 'center', alignItems: 'center' }}>
          <Text style={{ color: C.accent, fontSize: 16, fontWeight: '600' }}>{t('a_forgot')}</Text>
        </Pressable>
      )}
      {mode === 'signup' && <Text style={[T.muted, { marginTop: 4 }]}>{t('a_terms')}</Text>}
    </Screen>
  );
}
