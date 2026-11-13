import { test } from 'node:test';
import assert from 'node:assert/strict';
import { fill, pickLang, LANGS } from '../src/i18n/core.ts';
import { en } from '../src/i18n/en.ts';
import { es } from '../src/i18n/es.ts';
import { pt } from '../src/i18n/pt.ts';
import { de } from '../src/i18n/de.ts';
import { fr } from '../src/i18n/fr.ts';
import { it } from '../src/i18n/it.ts';

const all: Record<string, Record<string, string>> = { en, es, pt, de, fr, it };
const holes = (s: string) => (s.match(/\{\w+\}/g) ?? []).sort().join(',');

test('every language has the same texts and the same blanks as English', () => {
  assert.deepEqual(LANGS.map((l) => l.code).sort(), Object.keys(all).sort());
  for (const [code, d] of Object.entries(all)) {
    assert.deepEqual(Object.keys(d).sort(), Object.keys(en).sort(), code);
    for (const k of Object.keys(en)) {
      assert.ok(d[k].trim().length > 0, `${code}.${k} is empty`);
      assert.equal(holes(d[k]), holes((en as Record<string, string>)[k]), `${code}.${k}`);
    }
  }
});

test('fill puts values in the blanks and leaves unknown ones', () => {
  assert.equal(fill('Hi {p}, {n} of 3', { p: 'Mom', n: 2 }), 'Hi Mom, 2 of 3');
  assert.equal(fill('Hi {p}'), 'Hi {p}');
});

test('pickLang takes the first language Kavach has, else English', () => {
  assert.equal(pickLang(['pt-BR']), 'pt');
  assert.equal(pickLang(['hi-IN', 'de-DE']), 'de');
  assert.equal(pickLang(['ja']), 'en');
  assert.equal(pickLang([]), 'en');
});
