// After a flagged call: the complaint draft, plus the two questions only the person can answer.
import React, { useState } from 'react';
import { Linking, Text, TextInput, View } from 'react-native';
import { Btn, C, Panel, T } from './ui';
import { Settings, api } from './config';

type Ans = boolean | null;

function Choice({ label, value, onChange }: { label: string; value: Ans; onChange: (v: Ans) => void }) {
  return (
    <View style={{ marginBottom: 8 }}>
      <Text style={T.body}>{label}</Text>
      <View style={{ flexDirection: 'row', gap: 8, marginTop: 6 }}>
        {([['Not answered', null], ['Yes', true], ['No', false]] as [string, Ans][]).map(([t, v]) => (
          <View key={t} style={{ flex: 1 }}>
            <Btn label={t} kind={value === v ? 'primary' : 'plain'} onPress={() => onChange(v)} />
          </View>
        ))}
      </View>
    </View>
  );
}

export function ReportPanel({ settings, callId, report }: { settings: Settings; callId: string; report: { md: string; pdf: string } }) {
  const [money, setMoney] = useState<Ans>(null);
  const [otp, setOtp] = useState<Ans>(null);
  const [notes, setNotes] = useState('');
  const [msg, setMsg] = useState('');
  const { base, headers } = api(settings);
  const open = (path: string) => Linking.openURL(`${base}${path}${path.includes('?') ? '&' : '?'}key=${encodeURIComponent(settings.accessKey)}`);

  async function save() {
    try {
      const r = await fetch(`${base}/api/calls/${callId}/report`, {
        method: 'POST', headers, body: JSON.stringify({ money_shared: money, otp_shared: otp, notes }),
      });
      const d = await r.json();
      setMsg(r.ok ? `Draft updated. ${(d.missing || []).join(' ')}` : 'Could not update the draft.');
    } catch { setMsg('Could not reach the server.'); }
  }

  return (
    <Panel>
      <Text style={T.h2}>Complaint draft ready</Text>
      <Text style={[T.muted, { marginVertical: 6 }]}>
        A draft for you to review. Kavach never submits anything: file it yourself at cybercrime.gov.in or call 1930.
        Your family also gets it on Telegram.
      </Text>
      <Choice label="Did you send any money?" value={money} onChange={setMoney} />
      <Choice label="Did you share an OTP, PIN or card details?" value={otp} onChange={setOtp} />
      <TextInput value={notes} onChangeText={setNotes} placeholder="Anything to add (optional)" placeholderTextColor={C.muted}
        style={{ color: C.ink, borderColor: C.line, borderWidth: 1, borderRadius: 8, padding: 10, marginBottom: 8 }} />
      <Btn label="Save answers and update draft" kind="primary" onPress={save} />
      <Btn label="Open the PDF" onPress={() => open(report.pdf)} />
      {msg ? <Text style={T.muted}>{msg}</Text> : null}
    </Panel>
  );
}
