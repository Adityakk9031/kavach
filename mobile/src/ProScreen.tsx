// Full protection, set up once by a family member on the protected phone: Kavach hears the caller without the speaker and
// can warn privately. It needs Shizuku (a free helper app) running. After a restart, one tap here gets it going again.
import React, { useCallback, useEffect, useRef, useState } from 'react';
import { Linking, Text } from 'react-native';
import { BackLink, Btn, C, ErrorText, Hero, Panel, Screen, Step, T } from './ui';
import { NONE, ProCmd, ProStatus, proMessage, readPro, sendPro } from './pro';
import { useT, type Key } from './lang';

export function ProScreen({ onBack }: { onBack: () => void }) {
  const { t } = useT();
  const [st, setSt] = useState<ProStatus>(NONE);
  const [busy, setBusy] = useState<string | null>(null); // the command waiting for an answer
  const waiting = useRef<string | null>(null);

  const refresh = useCallback(async () => {
    const s = await readPro();
    setSt(s);
    if (waiting.current && s.cmdId === waiting.current && s.cmdResult !== 'working') { waiting.current = null; setBusy(null); }
  }, []);
  useEffect(() => { refresh(); const timer = setInterval(refresh, 1500); return () => clearInterval(timer); }, [refresh]);

  async function run(cmd: ProCmd) {
    setBusy(cmd);
    waiting.current = await sendPro(cmd);
    setTimeout(() => { if (waiting.current) { waiting.current = null; setBusy(null); } }, 8000); // no answer: the service is off
  }

  const on = st.running && st.secure;
  const message = st.cmdResult && !busy ? proMessage(st.cmdResult) : '';
  const failed = message === 'pro_r_shizuku' || message === 'pro_r_allow' || message === 'pro_r_fail';

  return (
    <Screen>
      <BackLink label={t('back')} onPress={onBack} />
      <Hero good={on} pill={on ? t('pro_ready') : t('pro_off')} title={t('pro_title')} body={t('pro_sub')} />

      {st.secure && !st.running ? (
        <Panel>
          <Text style={[T.muted, { marginBottom: 12 }]}>{t('pro_wakeB')}</Text>
          <Btn label={busy === 'pro_wake' ? t('pro_working') : t('pro_wake')} kind="primary" disabled={!!busy} onPress={() => run('pro_wake')} />
        </Panel>
      ) : null}

      <Panel>
        <Step n={1} first title={t('pro_s1')} body={t('pro_s1b')} done={st.alive} />
        <Step n={2} title={t('pro_s2')} body={t('pro_s2b')} done={st.installed}>
          {st.installed ? null : <Btn label={t('pro_get')} kind="primary" onPress={() => Linking.openURL('https://shizuku.rikka.app/download/')} />}
        </Step>
        <Step n={3} title={t('pro_s3')} body={t('pro_s3b')} done={st.running}>
          {st.running ? null : (
            <>
              <Btn label={t('pro_dev')} onPress={() => Linking.sendIntent('android.settings.APPLICATION_DEVELOPMENT_SETTINGS').catch(() => Linking.openSettings())} />
              <Btn label={t('pro_openShizuku')} kind="primary" disabled={!st.alive || !st.installed} onPress={() => run('open_shizuku')} />
            </>
          )}
        </Step>
        <Step n={4} title={t('pro_s4')} body={t('pro_s4b')} done={st.secure}>
          {st.secure ? null : <Btn label={busy === 'pro_setup' ? t('pro_working') : t('pro_finish')} kind="primary" disabled={!!busy || !st.alive} onPress={() => run('pro_setup')} />}
        </Step>
      </Panel>

      {message ? (failed ? <ErrorText>{t(message as Key)}</ErrorText> : <Text style={[T.body, { color: C.accent, marginBottom: 12 }]}>{t(message as Key)}</Text>) : null}
      <Text style={[T.muted, { marginBottom: 12 }]}>{t('pro_note')}</Text>
    </Screen>
  );
}
