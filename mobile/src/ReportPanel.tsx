// After a flagged call: the report draft, plus the two questions only the person can answer.
import React, { useState } from 'react';
import { Linking, Text, TextInput, View } from 'react-native';
import { Btn, C, Panel, T, input } from './ui';
import { Settings, api } from './config';
import { useT } from './lang';

type Ans = boolean | null;

function Choice({ label, value, onChange }: { label: string; value: Ans; onChange: (v: Ans) => void }) {
  const { t } = useT();
  return (
    <View style={{ marginBottom: 8 }}>
      <Text style={T.body}>{label}</Text>
      <View style={{ flexDirection: 'row', gap: 8, marginTop: 6 }}>
        {([[t('r_na'), null], [t('r_yes'), true], [t('r_no'), false]] as [string, Ans][]).map(([text, v]) => (
          <View key={String(v)} style={{ flex: 1 }}>
            <Btn label={text} kind={value === v ? 'primary' : 'plain'} onPress={() => onChange(v)} />
          </View>
        ))}
      </View>
    </View>
  );
}

export function ReportPanel({ settings, callId, report }: { settings: Settings; callId: string; report: { md: string; pdf: string } }) {
  const { t } = useT();
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
      setMsg(r.ok ? t('r_updated') : t('r_fail'));
    } catch { setMsg(t('offline')); }
  }

  return (
    <Panel>
      <Text style={T.h2}>{t('r_title')}</Text>
      <Text style={[T.muted, { marginVertical: 6 }]}>{t('r_body')}</Text>
      <Choice label={t('r_money')} value={money} onChange={setMoney} />
      <Choice label={t('r_otp')} value={otp} onChange={setOtp} />
      <TextInput value={notes} onChangeText={setNotes} placeholder={t('r_notes')} placeholderTextColor={C.muted}
        style={[input, { marginBottom: 12 }]} />
      <Btn label={t('r_save')} kind="primary" onPress={save} />
      <Btn label={t('r_pdf')} onPress={() => open(report.pdf)} />
      {msg ? <Text style={T.muted}>{msg}</Text> : null}
    </Panel>
  );
}
