// The messages the hidden audio page (web/bridge.html) posts to the app, and the commands the app sends back.
import type { Settings } from './config';

const normalizeUrl = (u: string) => u.trim().replace(/\/+$/, '');

export type Role = 'receiver' | 'caller' | 'listen';

export function bridgeUrl(s: Settings, opts: { call: string; role: Role; mode: 'live' | 'eval'; callerNumber?: string }): string {
  const q = new URLSearchParams({ call: opts.call, role: opts.role, mode: opts.mode });
  if (s.accessKey) q.set('key', s.accessKey);
  if (opts.callerNumber) q.set('caller_number', opts.callerNumber);
  return `${normalizeUrl(s.serverUrl)}/web/bridge.html?${q.toString()}`;
}

export type Command = { type: 'takeover' | 'takeback' | 'end_call' | 'barge_in' | 'sample' | 'stop' | 'rec_start' | 'rec_stop' | 'rec_cancel' };

// The hidden recorder page that records a voice sample and uploads it with the speaker's consent.
export function voiceRecorderUrl(s: Settings, person: 'papa' | 'son', speakerName: string): string {
  const q = new URLSearchParams({ person, name: speakerName });
  if (s.accessKey) q.set('key', s.accessKey);
  return `${normalizeUrl(s.serverUrl)}/web/voicerec.html?${q.toString()}`;
}

export type Evidence = { type: string; value: string; quote: string; normalized?: string };
export type TranscriptLine = { channel: string; text: string; final: boolean; latency?: number };

export type CallState = {
  connected: boolean;
  micOn: boolean;
  micError: string | null;
  sttOk: Record<string, boolean>;
  level: number;
  risk: number;
  stages: string[];
  stagesNow: string[];
  rationale: string;
  triggered: boolean;
  warning: { state: string; text: string; cloned: boolean } | null;
  takeover: boolean;
  personaText: string;
  evidence: Evidence[];
  transcript: TranscriptLine[];
  ended: boolean;
  rejected: string | null;
  report: { md: string; pdf: string } | null;
  closed: string | null;
  family: { seconds: number; at: number } | null;
};

export const initialState: CallState = {
  connected: false, micOn: false, micError: null, sttOk: {}, level: 0, risk: 0, stages: [], stagesNow: [], rationale: '',
  triggered: false, warning: null, takeover: false, personaText: '', evidence: [], transcript: [], ended: false,
  rejected: null, report: null, closed: null, family: null,
};

// One reducer for every message from the page. Pure, so it is easy to test.
export function reduce(s: CallState, m: any): CallState {
  switch (m.type) {
    case 'bridge':
      if (m.state === 'connected') return { ...s, connected: true, closed: null };
      if (m.state === 'mic_on') return { ...s, micOn: true, micError: null };
      if (m.state === 'level') return { ...s, level: m.level ?? 0 };
      if (m.state === 'closed') return { ...s, closed: `Connection closed (${m.code ?? ''} ${m.reason ?? ''})`.trim() };
      if (m.state === 'socket_error') return { ...s, closed: 'Could not connect to the server.' };
      if (m.state === 'start_failed') return { ...s, closed: m.message ?? 'The audio page failed to start.' };
      return s;
    case 'mic_error':
      return { ...s, micError: m.name === 'InsecureContext'
        ? 'The microphone needs a secure (https) server address.'
        : `Microphone unavailable (${m.name}). Allow the microphone for Kavach in your phone settings.` };
    case 'stt_status':
      return { ...s, sttOk: { ...s.sttOk, [m.channel]: !!m.ok } };
    case 'transcript': {
      const line: TranscriptLine = { channel: m.channel, text: m.text, final: !!m.final, latency: m.stt_latency_ms };
      const rest = s.transcript.filter((t) => t.final || t.channel !== m.channel); // a newer partial replaces the old one
      return { ...s, transcript: [...rest, line].slice(-60) };
    }
    case 'detection':
      if (m.error) return s;
      return { ...s, risk: Math.round(m.risk_cum), stages: m.stages_all ?? [], stagesNow: m.stages_now ?? [],
        rationale: m.rationale ?? '', triggered: s.triggered || !!m.trigger };
    case 'warning':
      return { ...s, warning: { state: m.state, text: m.text ?? s.warning?.text ?? m.error ?? '', cloned: m.cloned !== false } };
    case 'takeover':
      return { ...s, takeover: m.state === 'on' };
    case 'persona':
      return m.text ? { ...s, personaText: m.text } : s;
    case 'evidence': {
      const have = new Set(s.evidence.map((e) => `${e.type}|${e.normalized ?? e.value}`));
      const fresh = (m.items as Evidence[]).filter((e) => !have.has(`${e.type}|${e.normalized ?? e.value}`));
      return fresh.length ? { ...s, evidence: [...s.evidence, ...fresh] } : s;
    }
    case 'family':
      return { ...s, family: { seconds: m.seconds ?? 0, at: Date.now() } };
    case 'call_ended':
      return { ...s, ended: true, level: 0 };
    case 'report_ready':
      return { ...s, report: m.report };
    case 'call_rejected':
      return { ...s, rejected: m.reason, ended: true };
    default:
      return s;
  }
}

export const STAGE_LABELS: Record<string, string> = {
  S1: 'Authority', S2: 'Threat', S3: 'Secrecy', S4: 'Urgency', S5: 'Credentials', S6: 'Payment', S7: 'Remote access',
};
