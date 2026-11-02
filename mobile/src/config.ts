// Settings kept on the phone: where the Kavach server is, and its access key. No AssemblyAI key lives in the app:
// the server holds it, so a lost phone or a shared app never leaks it.
import AsyncStorage from '@react-native-async-storage/async-storage';

export type Settings = { serverUrl: string; accessKey: string };
const KEY = 'kavach.settings.v1';

export const normalizeUrl = (u: string) => u.trim().replace(/\/+$/, '');

export async function loadSettings(): Promise<Settings | null> {
  try {
    const raw = await AsyncStorage.getItem(KEY);
    return raw ? (JSON.parse(raw) as Settings) : null;
  } catch {
    return null;
  }
}

export async function saveSettings(s: Settings): Promise<void> {
  await AsyncStorage.setItem(KEY, JSON.stringify({ serverUrl: normalizeUrl(s.serverUrl), accessKey: s.accessKey.trim() }));
}

export async function clearSettings(): Promise<void> {
  await AsyncStorage.removeItem(KEY);
}

// Calls the server's /health to check the address and (if set) the access key.
export async function testConnection(s: Settings): Promise<{ ok: boolean; message: string }> {
  try {
    const base = normalizeUrl(s.serverUrl);
    const health = await fetch(`${base}/health`);
    if (!health.ok) return { ok: false, message: `Server answered ${health.status}.` };
    const h = await health.json();
    const cfg = await fetch(`${base}/api/config`, { headers: { 'x-kavach-key': s.accessKey.trim() } });
    if (cfg.status === 401) return { ok: false, message: 'The server is there, but the access key is wrong.' };
    if (!h.ready) return { ok: true, message: `Connected, but the server is missing: ${(h.missing_secrets || []).join(', ')}` };
    return { ok: true, message: 'Connected. Kavach server is ready.' };
  } catch (e: any) {
    return { ok: false, message: `Could not reach the server (${e?.message ?? 'network error'}). Check the address.` };
  }
}

export const api = (s: Settings) => ({
  base: normalizeUrl(s.serverUrl),
  headers: { 'x-kavach-key': s.accessKey, 'content-type': 'application/json' },
});
