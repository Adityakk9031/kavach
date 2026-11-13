// The language the app's own screens use. It starts as the phone's language (when Kavach has it), the person can change
// it on the first screen, and the choice is remembered. The small card the call service draws gets the same language.
import React, { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { Lang, LANGS, fill, pickLang } from './i18n/core';
import { en, type Dict } from './i18n/en';
import { es } from './i18n/es';
import { pt } from './i18n/pt';
import { de } from './i18n/de';
import { fr } from './i18n/fr';
import { it } from './i18n/it';
import { setNativeStrings } from './account';

export const DICTS: Record<Lang, Dict> = { en, es, pt, de, fr, it };
export type Key = keyof Dict;
export type TFn = (key: Key, vars?: Record<string, string | number>) => string;
const KEY = 'kavach.lang.v1';

function deviceLang(): Lang {
  try { return pickLang([Intl.DateTimeFormat().resolvedOptions().locale]); } catch { return 'en'; }
}

// The texts the Android call card shows (every key that starts with k_)
function cardStrings(d: Dict): Record<string, string> {
  const out: Record<string, string> = {};
  for (const k of Object.keys(d) as Key[]) if (k.startsWith('k_')) out[k] = d[k];
  return out;
}

type Ctx = { lang: Lang; setLang: (l: string) => void; t: TFn; te: (message: string) => string };
const LangContext = createContext<Ctx>({ lang: 'en', setLang: () => {}, t: (k, v) => fill(en[k], v), te: (m) => m });

export function LangProvider({ children }: { children: React.ReactNode }) {
  const [lang, setLangState] = useState<Lang>(deviceLang());
  useEffect(() => {
    AsyncStorage.getItem(KEY).then((v) => { if (v && LANGS.some((l) => l.code === v)) setLangState(v as Lang); }).catch(() => {});
  }, []);
  useEffect(() => { setNativeStrings(cardStrings(DICTS[lang])); }, [lang]);

  const setLang = useCallback((l: string) => {
    const next = pickLang([l]);
    setLangState(next);
    AsyncStorage.setItem(KEY, next).catch(() => {});
  }, []);
  const value = useMemo<Ctx>(() => {
    const t: TFn = (key, vars) => fill(DICTS[lang][key] ?? en[key] ?? String(key), vars);
    // Errors from account.ts arrive as "@key" when the app has its own words for them; server text passes through
    const te = (m: string) => (m.startsWith('@') && m.slice(1) in en ? t(m.slice(1) as Key) : m);
    return { lang, setLang, t, te };
  }, [lang, setLang]);
  return <LangContext.Provider value={value}>{children}</LangContext.Provider>;
}

export const useT = () => useContext(LangContext);
