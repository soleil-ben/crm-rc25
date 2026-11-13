/**
 * The bilingual guard for the public shell.
 *
 * A bilingual page does not usually fail by losing a translation file. It fails when
 * somebody adds one key to the English catalogue, ships it, and a Vietnamese customer
 * sees an English sentence in the middle of a Vietnamese page -- or, worse, sees a raw
 * key. These tests make that a build failure.
 */

import { readdirSync, readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';
import en from '../src/public/locales/en.js';
import vi from '../src/public/locales/vi.js';

const PUBLIC_SRC = join(process.cwd(), 'src', 'public');

function flatten(node, prefix = '') {
  const keys = [];
  for (const [key, value] of Object.entries(node)) {
    const path = prefix ? `${prefix}.${key}` : key;
    if (value && typeof value === 'object') keys.push(...flatten(value, path));
    else keys.push(path);
  }
  return keys.sort();
}

function lookup(catalogue, key) {
  return key.split('.').reduce((node, part) => (node == null ? undefined : node[part]), catalogue);
}

function collectReferencedKeys(dir) {
  const found = [];
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const full = join(dir, entry.name);
    if (entry.isDirectory()) {
      if (entry.name === 'locales') continue;
      found.push(...collectReferencedKeys(full));
    } else if (/\.jsx?$/.test(entry.name)) {
      const source = readFileSync(full, 'utf8');
      for (const match of source.matchAll(/\bt\(\s*'([a-zA-Z0-9_.]+)'/g)) {
        found.push({ key: match[1], file: entry.name });
      }
    }
  }
  return found;
}

describe('public translation catalogues', () => {
  it('define exactly the same keys in both languages', () => {
    const english = flatten(en);
    const vietnamese = flatten(vi);

    expect(vietnamese.filter((key) => !english.includes(key))).toEqual([]);
    expect(english.filter((key) => !vietnamese.includes(key))).toEqual([]);
  });

  it('define every key a public component references', () => {
    const missing = collectReferencedKeys(PUBLIC_SRC)
      .filter(({ key }) => typeof lookup(en, key) !== 'string')
      .map(({ key, file }) => `${key} (${file})`);

    expect(missing).toEqual([]);
  });

  it('translate every normalized operational status', () => {
    // The seventeen states from CRM.md section 10. A status the API can return but the
    // catalogue cannot name would render as a raw key at a customer.
    const statuses = [
      'booked',
      'awaiting_parcel',
      'received_at_solaris',
      'processing',
      'departed_origin',
      'in_transit',
      'customs_processing',
      'arrived_destination',
      'out_for_delivery',
      'partially_delivered',
      'delivered',
      'delivery_attempted',
      'exception',
      'return_in_progress',
      'returned',
      'cancelled',
      'tracking_unavailable',
    ];
    for (const status of statuses) {
      expect(typeof en.status[status]).toBe('string');
      expect(typeof vi.status[status]).toBe('string');
    }
  });

  it('translate every route group and every honest tracking state', () => {
    for (const route of ['VCA', 'CAV', 'CAD', 'XUS']) {
      expect(typeof en.routes[route]).toBe('string');
      expect(typeof vi.routes[route]).toBe('string');
    }
    for (const state of [
      'manual_updates',
      'external_link_only',
      'no_public_milestones',
      'tracking_unavailable',
      'demo',
      'cancelled',
    ]) {
      expect(typeof en.freshness[state]).toBe('string');
      expect(typeof en.freshness[`${state}_detail`]).toBe('string');
      expect(typeof vi.freshness[state]).toBe('string');
      expect(typeof vi.freshness[`${state}_detail`]).toBe('string');
    }
  });

  it('never claim the page synchronizes with a carrier', () => {
    // Phase 4 does not exist. No copy in either language may suggest otherwise.
    const all = [...Object.values(flatten(en)), ...flatten(vi)]
      .map((key) => `${lookup(en, key) || ''} ${lookup(vi, key) || ''}`)
      .join(' ')
      .toLowerCase();

    for (const claim of [
      'synchronized',
      'synchronised',
      'live tracking',
      'real-time',
      'real time',
      'automatically updated',
      'tự động cập nhật',
      'theo thời gian thực',
    ]) {
      expect(all).not.toContain(claim);
    }
  });

  it('keep Vietnamese diacritics intact', () => {
    // A catalogue that lost its diacritics would still be valid JavaScript and would
    // still render -- as a different set of words.
    expect(vi.landing.title).toBe('Theo dõi lô hàng của bạn');
    expect(vi.status.delivered).toBe('Đã giao');
    expect(vi.status.partially_delivered).toBe('Đã giao một phần');
    expect(vi.meta.languageName).toBe('Tiếng Việt');
    // The Vietnamese-specific letters live in U+1EA0-1EF9 and a handful of single codepoints
    // outside Latin-1. A catalogue that had been through a lossy encoding step would
    // lose them, so their presence is the check rather than any one word.
    const serialized = JSON.stringify(vi);
    const vietnameseOnly = [...serialized].filter((character) => {
      const code = character.codePointAt(0);
      return (
        (code >= 0x1ea0 && code <= 0x1ef9) ||
        [0x0102, 0x0103, 0x0110, 0x0111, 0x01a0, 0x01a1, 0x01af, 0x01b0].includes(code)
      );
    });
    expect(vietnameseOnly.length).toBeGreaterThan(100);
    // And no replacement character, which is what a broken encoding actually produces.
    expect(serialized).not.toContain('�');
    expect(serialized).not.toMatch(/&#\d+;/);
  });

  it('leave room for Vietnamese text expansion', () => {
    // Design.md section 15 allocates roughly 30%. This checks the assumption still holds
    // for the strings that sit in the tightest places -- buttons and badges.
    const tight = ['landing.submit', 'result.trackAnother', 'errors.tryAgain'];
    for (const key of tight) {
      const english = lookup(en, key);
      const vietnamese = lookup(vi, key);
      expect(vietnamese.length).toBeLessThan(english.length * 2.2);
    }
  });

  it('never put a tracking reference in a document title', () => {
    for (const catalogue of [en, vi]) {
      expect(catalogue.meta.documentTitle).not.toMatch(/\{\{/);
      expect(catalogue.meta.documentTitle).not.toContain('SX-');
    }
  });
});
