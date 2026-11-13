// Home for the son or daughter: pair the parent's phone, connect Telegram, record the warning voice, pick the language.
import React, { useCallback, useEffect, useState } from 'react';
import { Linking, Pressable, Text, TextInput, View } from 'react-native';
import { Btn, C, Choices, ErrorText, Hero, Logo, Meter, Panel, Pill, Screen, SectionLabel, T, Toggle, input } from './ui';
import { Account, FALLBACK_LANGUAGES, Language, call } from './account';
import { useT } from './lang';
import type { Settings } from './config';

type Me = { role: string; family: { language: string; parent_address: string; telegram_linked: boolean; person_gender?: string; person_age?: string;
  style_note?: string; learn_style?: boolean; learned?: { turns: number; summary: string; phrases: string[] } }; voices: { son: { cloned: boolean }; papa: { cloned: boolean } };
  phone_connected: boolean; telegram_bot_ready: boolean; languages: Language[] };

function Card({ n, title, pill, good, body, children }: { n: number; title: string; pill: string | null; good: boolean; body: string; children: React.ReactNode }) {
  return (
    <Panel style={good ? { borderColor: C.accent + '55' } : undefined}>
      <View style={{ flexDirection: 'row', alignItems: 'center', marginBottom: 8 }}>
        <View style={{ width: 30, height: 30, borderRadius: 15, backgroundColor: good ? C.accent : C.raised, alignItems: 'center', justifyContent: 'center', marginRight: 10 }}>
          <Text style={{ color: good ? C.onDark : C.muted, fontWeight: '700' }}>{good ? '✓' : n}</Text>
        </View>
        <Text style={[T.body, { flex: 1, fontWeight: '600' }]}>{title}</Text>
        {pill ? <Pill label={pill} tone={good ? 'good' : 'warn'} /> : null}
      </View>
      <Text style={[T.muted, { marginBottom: 12 }]}>{body}</Text>
      {children}
    </Panel>
  );
}

export function FamilyHome({ settings, account, onVoice, onPersonVoice, onSignOut, onPickLanguage }: {
  settings: Settings; account: Account; onVoice: () => void; onPersonVoice: () => void; onSignOut: () => void; onPickLanguage: (code: string) => void;
}) {
  const { t, te } = useT();
  const [me, setMe] = useState<Me | null>(null);
  const [code, setCode] = useState<{ code: string; expires_in_s: number } | null>(null);
  const [note, setNote] = useState('');
  const load = useCallback(() => call<Me>(settings, '/api/me').then((r) => { if (r.ok) setMe(r.data); }), [settings]);
  useEffect(() => { load(); const timer = setInterval(load, 6000); return () => clearInterval(timer); }, [load]);

  const p = me?.family.parent_address ?? account.parentAddress;
  const phone = !!me?.phone_connected, tg = !!me?.family.telegram_linked, voice = !!me?.voices.son.cloned;
  const done = [phone, tg, voice].filter(Boolean).length;

  async function connectTelegram() {
    setNote('');
    const r = await call<{ url: string }>(settings, '/api/family/telegram-link', 'POST');
    if (!r.ok) { setNote(te(r.error)); return; }
    Linking.openURL(r.data.url).catch(() => setNote(t('f_tgFail')));
  }
  async function pairCode() {
    setNote('');
    const r = await call<{ code: string; expires_in_s: number }>(settings, '/api/family/pair-code', 'POST');
    if (r.ok) setCode(r.data); else setNote(te(r.error));
  }
  // Who the takeover voice plays: saved at once, so there is no form to submit
  const [style, setStyle] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  async function setPerson(body: Record<string, unknown>) {
    setNote('');
    const r = await call(settings, '/api/family', 'PUT', body);
    if (r.ok) load(); else setNote(te(r.error));
    return r.ok;
  }
  async function forget() {
    const r = await call(settings, '/api/family/style', 'DELETE');
    if (r.ok) load(); else setNote(te(r.error));
  }
  async function setLanguage(l: string) {
    const r = await call(settings, '/api/family', 'PUT', { language: l });
    if (r.ok) { onPickLanguage(l); load(); } else setNote(te(r.error));
  }

  return (
    <Screen>
      <View style={{ flexDirection: 'row', alignItems: 'center', marginBottom: 20 }}>
        <Logo size={32} /><Text style={[T.h2, { marginLeft: 12, flex: 1 }]}>Kavach</Text>
        <Pressable onPress={onSignOut} hitSlop={12} accessibilityRole="button"><Text style={{ color: C.muted, fontSize: 15 }}>{t('logOut')}</Text></Pressable>
      </View>

      <Hero good={done === 3} pill={done === 3 ? t('f_allDone') : t('f_progress', { n: done })} title={t('f_title', { p })} body={t('f_body', { p })}>
        {me && done < 3 ? <View style={{ marginTop: 6 }}><Meter value={(done / 3) * 100} color={C.accent} /></View> : null}
      </Hero>
      {note ? <ErrorText>{note}</ErrorText> : null}

      <Card n={1} title={t('f_phone', { p })} pill={me ? (phone ? t('connected') : t('notConnected')) : null} good={phone} body={t('f_phoneBody', { p })}>
        {code ? (
          <View style={{ alignItems: 'center', marginBottom: 12, paddingVertical: 14, borderRadius: 12, backgroundColor: C.raised }}>
            <Text selectable style={{ color: C.ink, fontSize: 44, fontWeight: '800', letterSpacing: 8 }}>{code.code}</Text>
            <Text style={T.muted}>{t('f_codeValid', { m: Math.round(code.expires_in_s / 60) })}</Text>
          </View>
        ) : null}
        <Btn label={code ? t('f_newCode') : t('f_showCode')} kind={code || phone ? 'plain' : 'primary'} onPress={pairCode} />
      </Card>

      <Card n={2} title={t('f_tg')} pill={me ? (tg ? t('connected') : t('notYet')) : null} good={tg} body={t('f_tgBody', { p })}>
        <Btn label={tg ? t('f_tgAgain') : t('f_tgBtn')} kind={tg ? 'plain' : 'primary'} disabled={me ? !me.telegram_bot_ready : false} onPress={connectTelegram} />
      </Card>

      <Card n={3} title={t('f_voice')} pill={me ? (voice ? t('ready') : t('notYet')) : null} good={voice} body={t('f_voiceBody', { p })}>
        <Btn label={voice ? t('v_again') : t('v_record')} kind={voice ? 'plain' : 'primary'} onPress={onVoice} />
      </Card>

      <SectionLabel>{t('f_lang')}</SectionLabel>
      <Panel>
        <Choices items={me?.languages ?? FALLBACK_LANGUAGES} value={me?.family.language ?? account.language} onPick={setLanguage} />
        <Text style={T.muted}>{t('f_langBody')}</Text>
      </Panel>

      <SectionLabel>{t('f_who')}</SectionLabel>
      <Panel>
        <View style={{ flexDirection: 'row', alignItems: 'center', marginBottom: 6 }}>
          <Text style={[T.body, { flex: 1, fontWeight: '600' }]}>{t('f_ownVoice', { p })}</Text>
          {me ? <Pill label={me.voices.papa.cloned ? t('ready') : t('notYet')} tone={me.voices.papa.cloned ? 'good' : 'warn'} /> : null}
        </View>
        <Text style={T.muted}>{me?.voices.papa.cloned ? t('f_ownVoiceReady', { p }) : t('f_ownVoiceNot', { p })}</Text>
        <Btn label={me?.voices.papa.cloned ? t('v_again') : t('f_ownVoiceBtn', { p })} kind={me?.voices.papa.cloned ? 'plain' : 'primary'} onPress={onPersonVoice} />
        <View style={{ height: 1, backgroundColor: C.line, marginVertical: 14 }} />
        <Text style={[T.muted, { marginBottom: 10 }]}>{t('f_whoBody', { p })}</Text>
        <Choices items={[{ code: 'man', native: t('f_man') }, { code: 'woman', native: t('f_woman') }, { code: '', native: t('f_anyone') }]}
          value={me?.family.person_gender ?? ''} onPick={(v) => setPerson({ person_gender: v })} />
        <Choices items={[{ code: 'young', native: t('f_ageYoung') }, { code: 'middle', native: t('f_ageMiddle') }, { code: 'senior', native: t('f_ageSenior') }]}
          value={me?.family.person_age ?? 'senior'} onPick={(v) => setPerson({ person_age: v })} />
        <Text style={[T.body, { fontWeight: '600', marginTop: 6 }]}>{t('f_styleLabel', { p })}</Text>
        <TextInput style={input} value={style ?? me?.family.style_note ?? ''} onChangeText={(v) => { setStyle(v); setSaved(false); }}
          placeholder={t('f_stylePh')} placeholderTextColor={C.muted} maxLength={200} multiline />
        {style !== null && style !== (me?.family.style_note ?? '') ? (
          <Btn label={t('f_styleSave')} kind="primary" onPress={async () => { if (await setPerson({ style_note: style })) { setSaved(true); setStyle(null); } }} />
        ) : saved ? <Text style={[T.muted, { marginTop: 6 }]}>{t('f_styleSaved')}</Text> : null}
        <View style={{ flexDirection: 'row', alignItems: 'center', marginTop: 16 }}>
          <Text style={[T.body, { flex: 1, fontWeight: '600' }]}>{t('f_learn', { p })}</Text>
          <Toggle value={me?.family.learn_style ?? true} onChange={(v) => setPerson({ learn_style: v })} />
        </View>
        <Text style={[T.muted, { marginTop: 4 }]}>{t('f_learnBody', { p })}</Text>
        {(me?.family.learn_style ?? true) ? (
          me?.family.learned?.turns ? (
            <View style={{ marginTop: 10 }}>
              <Text style={T.body}>{t('f_learned', { n: me.family.learned.turns, p })}</Text>
              {me.family.learned.phrases.length ? <Text style={[T.muted, { marginTop: 2 }]}>{me.family.learned.phrases.map((x) => `“${x}”`).join('  ')}</Text> : null}
              <Btn label={t('f_forget')} onPress={forget} />
            </View>
          ) : <Text style={[T.muted, { marginTop: 10 }]}>{t('f_learnedNone', { p })}</Text>
        ) : null}
      </Panel>

      <SectionLabel>{t('f_can')}</SectionLabel>
      <Panel>
        {([['f_end', 'f_endBody'], ['f_note', 'f_noteBody'], ['f_report', 'f_reportBody']] as const).map(([a, b], k) => (
          <View key={a} style={{ marginTop: k ? 14 : 0 }}><Text style={[T.body, { fontWeight: '600' }]}>{t(a)}</Text><Text style={[T.muted, { marginTop: 2 }]}>{t(b, { p })}</Text></View>
        ))}
      </Panel>
    </Screen>
  );
}
