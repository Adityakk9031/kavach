import React, { useEffect, useRef, useState } from 'react';
import { Text, View } from 'react-native';
import { Btn, C, Logo, Panel, Pill, Screen, SectionLabel, T, Toggle } from './ui';
import { api, type Settings } from './config';

const rand = () => Array.from({ length: 4 }, () => 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'[Math.floor(Math.random() * 32)]).join('');
type Line = { who: string; text: string };

export function HomeScreen({ settings, onProtect, onCaller, onSettings, onVoice }: {
  settings: Settings;
  onProtect: (code: string, rehearsal: boolean) => void;
  onCaller: (code: string, rehearsal: boolean) => void;
  onSettings: () => void;
  onVoice: () => void;
}) {
  const [code, setCode] = useState(rand());
  const [rehearsal, setRehearsal] = useState(true);
  const [tools, setTools] = useState(false);
  const [calling, setCalling] = useState<'idle' | 'ringing' | 'live' | 'error'>('idle');
  const [note, setNote] = useState('');
  const [lines, setLines] = useState<Line[]>([]);
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);
  const { base, headers } = api(settings);

  useEffect(() => () => { if (timer.current) clearInterval(timer.current); }, []);

  function watch() {
    if (timer.current) clearInterval(timer.current);
    let waited = 0;
    timer.current = setInterval(async () => {
      try {
        const st = await (await fetch(`${base}/api/twilio/status`, { headers })).json();
        setLines(st.in_call ? st.live : st.last?.transcript?.slice(-6) ?? []);
        if (st.in_call) setCalling('live');
        else if (waited > 6 || st.last?.transcript?.length) { setCalling('idle'); setNote('The call has ended.'); if (timer.current) clearInterval(timer.current); }
      } catch { /* try again on the next tick */ }
      waited += 1;
    }, 2000);
  }

  async function callMe() {
    setCalling('ringing'); setNote('Calling your phone…'); setLines([]);
    try {
      const r = await fetch(`${base}/api/twilio/call`, { method: 'POST', headers });
      const d = await r.json();
      if (!r.ok) { setCalling('error'); setNote(d.detail ?? 'The call could not be started.'); return; }
      setNote('Your phone is ringing. Pick up and talk to the caller.');
      watch();
    } catch { setCalling('error'); setNote('Could not reach the Kavach server.'); }
  }

  return (
    <Screen>
      <View style={{ flexDirection: 'row', alignItems: 'center', marginBottom: 18 }}>
        <Logo size={40} />
        <View style={{ marginLeft: 14, flex: 1 }}>
          <Text style={T.h1}>Kavach</Text>
          <Text style={T.muted}>A shield for the people we love</Text>
        </View>
      </View>

      <SectionLabel>Try it</SectionLabel>
      <Panel>
        <Text style={T.h2}>Experience a scam call, safely</Text>
        <Text style={[T.muted, { marginTop: 6, marginBottom: 14 }]}>
          Kavach rings your phone and plays a pretend scammer. Talk to it like you would to a real caller.
          Nothing is real: every name and number is made up.
        </Text>
        <Btn label={calling === 'ringing' || calling === 'live' ? 'Call in progress…' : 'Call my phone'} kind="primary"
          onPress={callMe} disabled={calling === 'ringing' || calling === 'live'} />
        {note ? <Text style={[T.muted, { color: calling === 'error' ? C.danger : C.muted }]}>{note}</Text> : null}
        {lines.length > 0 && (
          <View style={{ marginTop: 10 }}>
            {lines.map((l, i) => (
              <Text key={i} style={{ marginTop: 6, color: l.who === 'scammer' ? C.caller : C.receiver }}>
                {l.who === 'scammer' ? 'Caller' : 'You'}: <Text style={{ color: C.ink }}>{l.text}</Text>
              </Text>
            ))}
          </View>
        )}
      </Panel>

      <SectionLabel>Protection</SectionLabel>
      <Btn label="Protect my call" sub="Kavach listens and warns you" onPress={() => onProtect(code, rehearsal)} />
      <Btn label="My voice" sub="Record a consented sample so Kavach can speak as you" onPress={onVoice} />

      <View style={{ height: 8 }} />
      <Btn label={tools ? 'Hide developer tools' : 'Developer tools'} onPress={() => setTools(!tools)} />
      {tools && (
        <Panel>
          <Text style={T.muted}>Two-phone test code (both phones use the same one)</Text>
          <View style={{ flexDirection: 'row', justifyContent: 'center', marginVertical: 12 }}>
            {code.split('').map((ch, i) => (
              <View key={i} style={{ width: 50, height: 60, marginHorizontal: 4, borderRadius: 12, backgroundColor: C.raised,
                borderWidth: 1, borderColor: C.line, alignItems: 'center', justifyContent: 'center' }}>
                <Text style={{ color: C.ink, fontSize: 28, fontWeight: '800' }}>{ch}</Text>
              </View>
            ))}
          </View>
          <Btn label="New code" onPress={() => setCode(rand())} />
          <View style={{ flexDirection: 'row', alignItems: 'center', marginVertical: 8 }}>
            <View style={{ flex: 1, paddingRight: 12 }}>
              <Text style={T.body}>Rehearsal mode</Text>
              <Text style={T.muted}>On: no Telegram messages are sent.</Text>
            </View>
            <Toggle value={rehearsal} onChange={setRehearsal} />
          </View>
          <Btn label="Be the test caller" onPress={() => onCaller(code, rehearsal)} />
          <Btn label="Server and access code" onPress={onSettings} />
          <Pill label={rehearsal ? 'Rehearsal' : 'Live alerts on'} tone={rehearsal ? 'neutral' : 'warn'} />
        </Panel>
      )}
    </Screen>
  );
}
