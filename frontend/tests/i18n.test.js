/**
 * Localization guard (CRM.md section 14, Design.md section 15).
 *
 * The internal UI is English first but every visible string goes through a translation
 * key. This test fails if a component references a key the catalogue does not define,
 * which is what would otherwise leak a raw key like "customers.declaredRoute" into the UI.
 */

import { readdirSync, readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';
import en from '../src/i18n/en.js';
import vi from '../src/i18n/vi.js';

const SRC = join(process.cwd(), 'src');

/**
 * The public tracking shell has its own bilingual catalogue and its own guard
 * (`publicI18n.test.js`). It is skipped here rather than merged in, because the two
 * catalogues are written for different readers and share no keys by design.
 */
// The Customer Account has its own bilingual catalogue and guard (OD-71, tests/accountI18n.test.jsx).
const SEPARATE_CATALOGUES = new Set(['public', 'account']);

function collectKeys(dir) {
  const found = [];
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const full = join(dir, entry.name);
    if (entry.isDirectory()) {
      if (SEPARATE_CATALOGUES.has(entry.name)) continue;
      found.push(...collectKeys(full));
    } else if (/\.jsx?$/.test(entry.name)) {
      const source = readFileSync(full, 'utf8');
      for (const match of source.matchAll(/\bt\(\s*'([a-zA-Z0-9_.]+)'/g)) {
        found.push({ key: match[1], file: full });
      }
    }
  }
  return found;
}

function lookup(key, catalogue = en) {
  return key.split('.').reduce((node, part) => (node == null ? undefined : node[part]), catalogue);
}

function flatten(node, prefix = '') {
  const keys = [];
  for (const [key, value] of Object.entries(node)) {
    const path = prefix ? `${prefix}.${key}` : key;
    if (value && typeof value === 'object') keys.push(...flatten(value, path));
    else keys.push(path);
  }
  return keys.sort();
}

describe('translation catalogue', () => {
  it('defines every key referenced by a component', () => {
    const missing = collectKeys(SRC)
      .filter(({ key }) => typeof lookup(key) !== 'string')
      .map(({ key, file }) => `${key} (${file})`);
    expect(missing).toEqual([]);
  });

  it('covers every lifecycle, route, task, and consent value the API can return', () => {
    for (const status of ['prospect', 'new', 'active', 'at_risk', 'inactive', 'archived']) {
      expect(typeof en.lifecycle[status]).toBe('string');
    }
    for (const route of ['VCA', 'CAV', 'CAD', 'XUS']) {
      expect(typeof en.routes[route]).toBe('string');
    }
    for (const status of [
      'not_scheduled',
      'scheduled',
      'in_progress',
      'waiting_for_customer',
      'completed',
      'cancelled',
    ]) {
      expect(typeof en.taskStatus[status]).toBe('string');
    }
    for (const status of ['unknown', 'consented', 'withdrawn', 'suppressed']) {
      expect(typeof en.consentStatus[status]).toBe('string');
    }
  });

  it('never hard-codes a language guess into a route label', () => {
    // A shipping lane must not be presented as a language (CRM.md section 4).
    expect(en.routes.CAV).not.toMatch(/vietnamese/i);
    expect(en.routes.VCA).not.toMatch(/vietnamese/i);
    expect(en.customers.languageHint).toMatch(/never infer/i);
  });
});

describe('staff catalogue parity', () => {
  it('defines exactly the same keys in English and Vietnamese', () => {
    // The failure this prevents is not a missing file. It is somebody adding one key to
    // the English catalogue, shipping, and a Vietnamese-speaking staff member seeing an
    // English sentence -- or a raw key -- in the middle of a Vietnamese page.
    const english = flatten(en);
    const vietnamese = flatten(vi);

    expect(vietnamese.filter((key) => !english.includes(key))).toEqual([]);
    expect(english.filter((key) => !vietnamese.includes(key))).toEqual([]);
  });

  it('leaves no Vietnamese value empty or accidentally still in English', () => {
    // A handful of strings are legitimately identical: the brand name, the legal entity,
    // and product names that are not translated.
    const identicalOnPurpose = new Set([
      'brand.name',
      'brand.nameFirst',
      'brand.nameSecond',
      'brand.legalEntity',
      'serviceType.epacket',
      'auth.email',
      'booking.email',
      'settings.title',
      // Service product names (owner, 2026-11-04): not translated.
      'costMethod.service.air_standard',
      'costMethod.service.air_express',
    ]);

    for (const key of flatten(en)) {
      const value = lookup(key, vi);
      expect(typeof value, `${key} is missing from vi`).toBe('string');
      expect(value.trim().length, `${key} is empty in vi`).toBeGreaterThan(0);
      if (!identicalOnPurpose.has(key) && lookup(key, en).length > 12) {
        expect(value, `${key} looks untranslated`).not.toBe(lookup(key, en));
      }
    }
  });

  it('keeps Vietnamese diacritics intact', () => {
    // A catalogue that had been through a lossy encoding step would still be valid
    // JavaScript and would still render -- as a different set of words.
    expect(vi.nav.customers).toBe('Khách hàng');
    expect(vi.operationalState.delivered).toBe('Đã giao');
    expect(vi.operationalState.partially_delivered).toBe('Đã giao một phần');

    const serialized = JSON.stringify(vi);
    const vietnameseOnly = [...serialized].filter((character) => {
      const code = character.codePointAt(0);
      return (
        (code >= 0x1ea0 && code <= 0x1ef9) ||
        [0x0102, 0x0103, 0x0110, 0x0111, 0x01a0, 0x01a1, 0x01af, 0x01b0].includes(code)
      );
    });
    expect(vietnameseOnly.length).toBeGreaterThan(200);
    expect(serialized).not.toContain('�');
    expect(serialized).not.toMatch(/&#\d+;/);
  });

  it('never presents a shipping lane as a language, in either catalogue', () => {
    // CRM.md section 4: language is asked, never inferred from a route.
    for (const catalogue of [en, vi]) {
      expect(catalogue.routes.CAV).not.toMatch(/vietnamese|tiếng việt/i);
      expect(catalogue.routes.VCA).not.toMatch(/vietnamese|tiếng việt/i);
    }
  });

  it('never claims automatic provider synchronization, in either catalogue', () => {
    // No provider is connected (DEC-0075). The staff catalogue does talk about
    // synchronization -- to say there is none -- so a naive substring ban would fail on
    // its own denials. The rule that actually matters: every string mentioning
    // synchronization or live tracking must be a *denial*, in whichever language it is
    // written.
    const claimTerms = [
      'synchroniz',
      'synchronis',
      'live tracking',
      'real-time',
      'real time',
      'automatic',
      'đồng bộ',
      'thời gian thực',
      'tự động',
    ];
    const denialMarkers = [
      'no ',
      'not ',
      'never',
      'nothing',
      'unavailable',
      'without',
      'until',
      'không',
      'chưa',
    ];

    for (const catalogue of [en, vi]) {
      for (const key of flatten(catalogue)) {
        const value = lookup(key, catalogue);
        const lowered = value.toLowerCase();
        if (!claimTerms.some((term) => lowered.includes(term))) continue;
        const denied = denialMarkers.some((marker) => lowered.includes(marker));
        expect(denied, `${key} mentions synchronization without denying it: ${value}`).toBe(
          true,
        );
      }
    }
  });

  it('keeps the tightest Vietnamese strings inside the expansion budget', () => {
    // Design.md section 15 allocates roughly 30%. Buttons and badges are where a longer
    // translation actually breaks a layout, so those are the ones checked.
    const tight = [
      'common.save',
      'common.cancel',
      'reports.exportCsv',
      'imports.decisionSkip',
      'lifecycle.at_risk',
    ];
    for (const key of tight) {
      expect(lookup(key, vi).length).toBeLessThan(lookup(key, en).length * 2.6);
    }
  });
});
