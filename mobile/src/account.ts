// Sign-up, log-in and pairing against the Kavach server, and what this phone remembers about who is signed in.
// The token the server gives back is used exactly like the old access code (the x-kavach-key header), and is also written
// to a small file that the background call service reads, so the service protects calls as this family.
import AsyncStorage from '@react-native-async-storage/async-storage';
import * as FileSystem from 'expo-file-system/legacy';
import { Settings, normalizeUrl, saveSettings, clearSettings } from './config';

export type Role = 'son' | 'parent';
export type Account = { role: Role; familyId: string; language: string; parentAddress: string };
export type Language = { code: string; label: string; native: string };
const KEY = 'kavach.account.v1';

// The public server this build talks to (set when the app is built)
export const SERVER = normalizeUrl(process.env.EXPO_PUBLIC_KAVACH_SERVER ?? '');
export const FALLBACK_LANGUAGES: Language[] = [
  { code: 'en', label: 'English', native: 'English' }, { code: 'es', label: 'Spanish', native: 'Español' }, { code: 'pt', label: 'Portuguese', native: 'Português' },
];
export const deviceTimeZone = () => { try { return Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC'; } catch { return 'UTC'; } };

export async function loadAccount(): Promise<Account | null> {
  try { const raw = await AsyncStorage.getItem(KEY); return raw ? (JSON.parse(raw) as Account) : null; } catch { return null; }
}

type Result<T> = { ok: true; data: T } | { ok: false; error: string };
export async function call<T = any>(s: { serverUrl: string; accessKey?: string }, path: string, method = 'GET', body?: unknown): Promise<Result<T>> {
  try {
    const r = await fetch(`${normalizeUrl(s.serverUrl)}${path}`, {
      method, headers: { 'content-type': 'application/json', ...(s.accessKey ? { 'x-kavach-key': s.accessKey } : {}) },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    const data = await r.json().catch(() => ({}));
    if (!r.ok) return { ok: false, error: data?.detail || data?.error || `The server answered ${r.status}.` };
    return { ok: true, data };
  } catch (e: any) {
    return { ok: false, error: 'Could not reach Kavach. Check your internet connection and try again.' };
  }
}

// Hands the account to the Android call service (it reads files/kavach-config.json)
export async function writeNativeConfig(s: Settings | null): Promise<void> {
  try {
    if (!FileSystem.documentDirectory) return;
    await FileSystem.writeAsStringAsync(FileSystem.documentDirectory + 'kavach-config.json',
      JSON.stringify(s ? { server: normalizeUrl(s.serverUrl), key: s.accessKey } : {}));
  } catch { /* the service falls back to its built-in values */ }
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

export const signup = (server: string, b: { email: string; password: string; language: string; parent_address: string }) =>
  call(({ serverUrl: server }), '/api/account/signup', 'POST', { ...b, timezone: deviceTimeZone() });
export const login = (server: string, email: string, password: string) => call({ serverUrl: server }, '/api/account/login', 'POST', { email, password });
export const pair = (server: string, code: string) => call({ serverUrl: server }, '/api/pair', 'POST', { code: code.replace(/\D/g, '') });
export const languages = (server: string) => call<{ languages: Language[] }>({ serverUrl: server }, '/api/languages');
