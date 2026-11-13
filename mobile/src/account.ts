// Sign-up, log-in and pairing, and what this phone remembers about who is signed in.
// Sign-in itself is done by Supabase Auth (email + password, confirmed by a link). The app then shows Supabase's token to
// the Kavach server once and gets back a Kavach token, which is used exactly like the old access code (the x-kavach-key
// header) and is also written to a small file that the background call service reads.
// A server that has no Supabase set up still works: the app falls back to the server's own sign-up and log-in.
import AsyncStorage from '@react-native-async-storage/async-storage';
import * as FileSystem from 'expo-file-system/legacy';
import { Settings, normalizeUrl, saveSettings, clearSettings } from './config';

export type Role = 'son' | 'parent';
export type Account = { role: Role; familyId: string; language: string; parentAddress: string };
export type Language = { code: string; label: string; native: string };
const KEY = 'kavach.account.v1';
const PENDING = 'kavach.pending.v1';

// The public server this build talks to (set when the app is built)
export const SERVER = normalizeUrl(process.env.EXPO_PUBLIC_KAVACH_SERVER ?? '');
export const FALLBACK_LANGUAGES: Language[] = [
  { code: 'en', label: 'English', native: 'English' }, { code: 'es', label: 'Spanish', native: 'Español' }, { code: 'pt', label: 'Portuguese', native: 'Português' },
  { code: 'de', label: 'German', native: 'Deutsch' }, { code: 'fr', label: 'French', native: 'Français' }, { code: 'it', label: 'Italian', native: 'Italiano' },
];
export const deviceTimeZone = () => { try { return Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC'; } catch { return 'UTC'; } };

export async function loadAccount(): Promise<Account | null> {
  try { const raw = await AsyncStorage.getItem(KEY); return raw ? (JSON.parse(raw) as Account) : null; } catch { return null; }
}

// An error that starts with "@" is the name of a text in the app's own language files (see lang.tsx, te())
type Result<T> = { ok: true; data: T } | { ok: false; error: string };
export async function call<T = any>(s: { serverUrl: string; accessKey?: string }, path: string, method = 'GET', body?: unknown): Promise<Result<T>> {
  try {
    const r = await fetch(`${normalizeUrl(s.serverUrl)}${path}`, {
      method, headers: { 'content-type': 'application/json', ...(s.accessKey ? { 'x-kavach-key': s.accessKey } : {}) },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    const data = await r.json().catch(() => ({}));
    if (!r.ok) return { ok: false, error: (typeof data?.detail === 'string' && data.detail) || data?.error || '@e_generic' };
    return { ok: true, data };
  } catch {
    return { ok: false, error: '@offline' };
  }
}

// Hands the account, and the call card's texts in the app's language, to the Android call service (files/kavach-config.json)
let nativeStrings: Record<string, string> = {};
let nativeSettings: Settings | null = null;
export async function writeNativeConfig(s: Settings | null): Promise<void> {
  nativeSettings = s;
  try {
    if (!FileSystem.documentDirectory) return;
    await FileSystem.writeAsStringAsync(FileSystem.documentDirectory + 'kavach-config.json',
      JSON.stringify(s ? { server: normalizeUrl(s.serverUrl), key: s.accessKey, strings: nativeStrings } : { strings: nativeStrings }));
  } catch { /* the service falls back to its built-in values */ }
}
export function setNativeStrings(strings: Record<string, string>): void {
  nativeStrings = strings;
  writeNativeConfig(nativeSettings);
}

export async function saveSession(token: string, role: Role, family: any, server = SERVER): Promise<{ settings: Settings; account: Account }> {
  const settings = { serverUrl: server, accessKey: token };
  const account: Account = { role, familyId: family.id, language: family.language, parentAddress: family.parent_address };
  await saveSettings(settings);
  await AsyncStorage.setItem(KEY, JSON.stringify(account));
  await writeNativeConfig(settings);
  return { settings, account };
}

export async function signOut(): Promise<void> {
  await clearSettings();
  try { await AsyncStorage.removeItem(KEY); } catch { /* nothing to forget */ }
  await writeNativeConfig(null);
}

export const pair = (server: string, code: string) => call({ serverUrl: server }, '/api/pair', 'POST', { code: code.replace(/\D/g, '') });
export const languages = (server: string) => call<{ languages: Language[] }>({ serverUrl: server }, '/api/languages');

// ---- Sign-in ----
export type Session = { token: string; role: Role; family: any };
export type Family = { language: string; parent_address: string };
export type AuthResult = { kind: 'session'; session: Session } | { kind: 'confirm' } | { kind: 'error'; error: string };
type AuthConfig = { supabase: boolean; url?: string; anon_key?: string };

async function authConfig(server: string): Promise<AuthConfig> {
  const r = await call<AuthConfig>({ serverUrl: server }, '/api/auth-config');
  return r.ok && r.data.supabase && r.data.url && r.data.anon_key ? r.data : { supabase: false };
}

// What Supabase said went wrong, as the name of one of the app's own texts
export function supabaseError(status: number, d: any): string {
  const code = String(d?.error_code ?? d?.code ?? d?.error ?? '');
  const msg = String(d?.msg ?? d?.error_description ?? d?.message ?? '').toLowerCase();
  if (code === 'email_not_confirmed' || msg.includes('not confirmed')) return '@e_notConfirmed';
  if (code === 'invalid_credentials' || code === 'invalid_grant' || msg.includes('invalid login')) return '@e_badLogin';
  if (code === 'user_already_exists' || code === 'email_exists' || msg.includes('already registered')) return '@e_exists';
  if (code === 'weak_password' || msg.includes('password should')) return '@e_weak';
  if (status === 429 || code.includes('rate_limit')) return '@e_rate';
  return '@e_generic';
}

async function supabase(cfg: AuthConfig, path: string, body: unknown): Promise<Result<any>> {
  try {
    const r = await fetch(`${normalizeUrl(cfg.url!)}/auth/v1/${path}`, {
      method: 'POST', headers: { 'content-type': 'application/json', apikey: cfg.anon_key! }, body: JSON.stringify(body),
    });
    const d = await r.json().catch(() => ({}));
    return r.ok ? { ok: true, data: d } : { ok: false, error: supabaseError(r.status, d) };
  } catch {
    return { ok: false, error: '@offline' };
  }
}

// The page Supabase's emails open (it lives on the Kavach server)
const landing = (server: string) => encodeURIComponent(`${normalizeUrl(server)}/web/account.html`);

// What the person chose at sign-up is kept until their family exists, so confirming the email later (even after the app
// was closed) still makes the family in the right language and with the right name.
async function pendingFor(email: string): Promise<Partial<Family>> {
  try {
    const p = JSON.parse((await AsyncStorage.getItem(PENDING)) ?? 'null');
    return p && p.email === email.trim().toLowerCase() ? { language: p.language, parent_address: p.parent_address } : {};
  } catch { return {}; }
}

async function exchange(server: string, accessToken: string, family: Partial<Family>): Promise<AuthResult> {
  const r = await call<Session>({ serverUrl: server }, '/api/account/session', 'POST', { access_token: accessToken, timezone: deviceTimeZone(), ...family });
  if (!r.ok) return { kind: 'error', error: r.error };
  AsyncStorage.removeItem(PENDING).catch(() => {});
  return { kind: 'session', session: r.data };
}

export async function signUp(server: string, email: string, password: string, family: Family): Promise<AuthResult> {
  const cfg = await authConfig(server);
  if (!cfg.supabase) {
    const r = await call<Session>({ serverUrl: server }, '/api/account/signup', 'POST', { email, password, ...family, timezone: deviceTimeZone() });
    return r.ok ? { kind: 'session', session: r.data } : { kind: 'error', error: r.error };
  }
  await AsyncStorage.setItem(PENDING, JSON.stringify({ email: email.trim().toLowerCase(), ...family })).catch(() => {});
  const r = await supabase(cfg, `signup?redirect_to=${landing(server)}`, { email: email.trim(), password });
  if (!r.ok) return { kind: 'error', error: r.error };
  if (r.data.access_token) return exchange(server, r.data.access_token, family); // the project does not ask for confirmation
  // Supabase answers a sign-up for an email that already has an account with a user that has no identities
  const user = r.data.user ?? r.data;
  if (Array.isArray(user?.identities) && user.identities.length === 0) return { kind: 'error', error: '@e_exists' };
  return { kind: 'confirm' };
}

export async function signIn(server: string, email: string, password: string): Promise<AuthResult> {
  const cfg = await authConfig(server);
  if (!cfg.supabase) {
    const r = await call<Session>({ serverUrl: server }, '/api/account/login', 'POST', { email, password });
    return r.ok ? { kind: 'session', session: r.data } : { kind: 'error', error: r.error };
  }
  const r = await supabase(cfg, 'token?grant_type=password', { email: email.trim(), password });
  if (!r.ok) return { kind: 'error', error: r.error };
  return exchange(server, r.data.access_token, await pendingFor(email));
}

// Sends the "choose a new password" email. False means this server cannot do it (no Supabase).
export async function resetPassword(server: string, email: string): Promise<Result<boolean>> {
  const cfg = await authConfig(server);
  if (!cfg.supabase) return { ok: true, data: false };
  const r = await supabase(cfg, `recover?redirect_to=${landing(server)}`, { email: email.trim() });
  return r.ok ? { ok: true, data: true } : r;
}
