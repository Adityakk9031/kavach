// Home for the son or daughter: connect Telegram, pair the parent's phone, record the warning voice, pick the language.
import React, { useCallback, useEffect, useState } from 'react';
import { Linking, Pressable, Text, View } from 'react-native';
import { Btn, C, Logo, Panel, Pill, Screen, SectionLabel, T } from './ui';
import { Account, Language, call } from './account';
import type { Settings } from './config';

type Me = { role: string; family: { language: string; parent_address: string; telegram_linked: boolean }; voices: { son: { cloned: boolean }; papa: { cloned: boolean } };
  phone_connected: boolean; telegram_bot_ready: boolean; languages: Language[] };

export function FamilyHome({ settings, account, onVoice, onSignOut, onPickLanguage }: {
  settings: Settings; account: Account; onVoice: () => void; onSignOut: () => void; onPickLanguage: (code: string) => void;
}) {
  const [me, setMe] = useState<Me | null>(null);
  const [code, setCode] = useState<{ code: string; expires_in_s: number } | null>(null);
  const [note, setNote] = useState('');
  const load = useCallback(() => call<Me>(settings, '/api/me').then((r) => { if (r.ok) setMe(r.data); }), [settings]);
  useEffect(() => { load(); const t = setInterval(load, 6000); return () => clearInterval(t); }, [load]);

  const p = me?.family.parent_address ?? account.parentAddress;
  async function connectTelegram() {
    setNote('');
    const r = await call<{ url: string }>(settings, '/api/family/telegram-link', 'POST');
    if (!r.ok) { setNote(r.error); return; }
    Linking.openURL(r.data.url).catch(() => setNote('Could not open Telegram. Is it installed?'));
  }
  async function pairCode() {
    setNote('');
    const r = await call<{ code: string; expires_in_s: number }>(settings, '/api/family/pair-code', 'POST');
    if (r.ok) setCode(r.data); else setNote(r.error);
  }
  async function setLanguage(l: string) {
    const r = await call(settings, '/api/family', 'PUT', { language: l });
    if (r.ok) { onPickLanguage(l); load(); } else setNote(r.error);
  }

  return (
    <Screen>
      <View style={{ flexDirection: 'row', alignItems: 'center', marginBottom: 24 }}>
        <Logo size={32} /><Text style={[T.h2, { marginLeft: 12, flex: 1 }]}>Kavach</Text>
        <Pressable onPress={onSignOut} hitSlop={12}><Text style={{ color: C.muted, fontSize: 15 }}>Log out</Text></Pressable>
      </View>
      <Text style={T.h1}>You look after {p}</Text>
      <Text style={[T.muted, { marginTop: 8, marginBottom: 20 }]}>If a call to {p} looks like a scam, you get a Telegram message within seconds.</Text>
      {note ? <Text style={{ color: C.danger, marginBottom: 10 }}>{note}</Text> : null}

      <Panel>
        <View style={{ flexDirection: 'row', alignItems: 'center', marginBottom: 6 }}>
          <Text style={[T.body, { flex: 1, fontWeight: '600' }]}>1 · {p}'s phone</Text>
          {me ? <Pill label={me.phone_connected ? 'Connected' : 'Not connected'} tone={me.phone_connected ? 'good' : 'warn'} /> : null}
        </View>
        <Text style={[T.muted, { marginBottom: 12 }]}>Install Kavach on {p}'s phone, choose "This phone needs protection" and type this code.</Text>
        {code ? (
          <View style={{ alignItems: 'center', marginBottom: 10 }}>
            <Text style={{ color: C.ink, fontSize: 44, fontWeight: '800', letterSpacing: 8 }}>{code.code}</Text>
            <Text style={T.muted}>Works for {Math.round(code.expires_in_s / 60)} minutes, once.</Text>
          </View>
        ) : null}
        <Btn label={code ? 'New code' : `Show the code for ${p}'s phone`} kind={code ? 'plain' : 'primary'} onPress={pairCode} />
      </Panel>

      <Panel>
        <View style={{ flexDirection: 'row', alignItems: 'center', marginBottom: 6 }}>
          <Text style={[T.body, { flex: 1, fontWeight: '600' }]}>2 · Telegram alerts</Text>
          {me ? <Pill label={me.family.telegram_linked ? 'Connected' : 'Not yet'} tone={me.family.telegram_linked ? 'good' : 'warn'} /> : null}
        </View>
        <Text style={[T.muted, { marginBottom: 12 }]}>Alerts, the End call button and voice notes to {p} all come through the Kavach bot on Telegram. Tap, then press Start in Telegram.</Text>
        <Btn label={me?.family.telegram_linked ? 'Connect another Telegram chat' : 'Connect Telegram'} kind={me?.family.telegram_linked ? 'plain' : 'primary'}
          disabled={me ? !me.telegram_bot_ready : false} onPress={connectTelegram} />
      </Panel>

      <Panel>
        <View style={{ flexDirection: 'row', alignItems: 'center', marginBottom: 6 }}>
          <Text style={[T.body, { flex: 1, fontWeight: '600' }]}>3 · Your voice for the warning</Text>
          {me ? <Pill label={me.voices.son.cloned ? 'Ready' : 'Not yet'} tone={me.voices.son.cloned ? 'good' : 'warn'} /> : null}
        </View>
        <Text style={[T.muted, { marginBottom: 12 }]}>{p} hears the scam warning in your voice, because a worried parent trusts family. Record up to three short takes for a clearer voice.</Text>
        <Btn label={me?.voices.son.cloned ? 'Record again' : 'Record my voice'} kind={me?.voices.son.cloned ? 'plain' : 'primary'} onPress={onVoice} />
      </Panel>

      <SectionLabel>Language of the calls</SectionLabel>
      <Panel>
        <View style={{ flexDirection: 'row', flexWrap: 'wrap' }}>
          {(me?.languages ?? []).map((l) => {
            const on = (me?.family.language ?? account.language) === l.code;
            return (
              <Pressable key={l.code} onPress={() => setLanguage(l.code)} style={{ borderRadius: 999, borderWidth: 1, borderColor: on ? C.accent : C.line,
                backgroundColor: on ? C.accentSoft : C.panel, paddingHorizontal: 14, paddingVertical: 8, marginRight: 8, marginBottom: 8 }}>
                <Text style={{ color: C.ink, fontWeight: on ? '700' : '500' }}>{l.native}</Text>
              </Pressable>
            );
          })}
        </View>
        <Text style={T.muted}>The warning, the takeover voice and the Telegram messages use this language.</Text>
      </Panel>

      <SectionLabel>From the Telegram alert you can</SectionLabel>
      <Panel>
        {[['End the call', `Tap the button under the alert. The call on ${p}'s phone is cut.`],
          ['Send a voice note', `It plays on ${p}'s phone straight away, during the call or after it.`],
          ['Get the report draft', 'A PDF with everything the scammer said arrives after the call, for you to check and file.']].map(([t, b], k) => (
          <View key={t} style={{ marginTop: k ? 14 : 0 }}><Text style={[T.body, { fontWeight: '600' }]}>{t}</Text><Text style={T.muted}>{b}</Text></View>
        ))}
      </Panel>
    </Screen>
  );
}
