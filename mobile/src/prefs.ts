// What this phone remembers about its user: whether the welcome was seen, and who uses the phone.
import AsyncStorage from '@react-native-async-storage/async-storage';

export type Role = 'papa' | 'family';
export type Prefs = { onboarded: boolean; role: Role | null };
const KEY = 'kavach.prefs.v1';
export const EMPTY: Prefs = { onboarded: false, role: null };

export async function loadPrefs(): Promise<Prefs> {
  try {
    const raw = await AsyncStorage.getItem(KEY);
    return raw ? { ...EMPTY, ...JSON.parse(raw) } : EMPTY;
  } catch {
    return EMPTY;
  }
}

export async function savePrefs(p: Prefs): Promise<void> {
  try { await AsyncStorage.setItem(KEY, JSON.stringify(p)); } catch { /* the app still works, it just asks again next time */ }
}
