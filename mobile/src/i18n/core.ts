// The six languages the app speaks, and the two small helpers every screen uses. No imports, so tests can load it alone.
export type Lang = 'en' | 'es' | 'pt' | 'de' | 'fr' | 'it';
export const LANGS: { code: Lang; native: string }[] = [
  { code: 'en', native: 'English' }, { code: 'es', native: 'Español' }, { code: 'pt', native: 'Português' },
  { code: 'de', native: 'Deutsch' }, { code: 'fr', native: 'Français' }, { code: 'it', native: 'Italiano' },
];

// "Hello {name}" + { name: 'Ana' } -> "Hello Ana"
export function fill(text: string, vars?: Record<string, string | number>): string {
  if (!vars) return text;
  return text.replace(/\{(\w+)\}/g, (whole, k) => (k in vars ? String(vars[k]) : whole));
}

// The first candidate we support wins: "pt-BR" -> pt, "de_AT" -> de. Nothing matches -> English.
export function pickLang(candidates: (string | null | undefined)[]): Lang {
  for (const c of candidates) {
    const two = (c ?? '').toLowerCase().slice(0, 2);
    const hit = LANGS.find((l) => l.code === two);
    if (hit) return hit.code;
  }
  return 'en';
}
