/**
 * Minimal translation layer.
 *
 * Components call `t('customers.title')` rather than embedding English, so adding a
 * second internal locale is a catalogue change (Design.md section 15). Layouts are
 * built to absorb roughly 30% text expansion.
 */

import { createContext, useCallback, useContext, useMemo, useState } from 'react';
import en from './en.js';
import vi from './vi.js';

// Vietnamese is at key parity with English and enforced by `tests/i18n.test.js`. The
// wording is a working translation awaiting owner confirmation, not approved business
// copy (see the note at the top of `vi.js`).
const catalogues = { en, vi };

const I18nContext = createContext(null);

function lookup(catalogue, key) {
  return key.split('.').reduce((node, part) => (node == null ? undefined : node[part]), catalogue);
}

export function I18nProvider({ children, initialLocale = 'en' }) {
  const [locale, setLocale] = useState(initialLocale);

  const t = useCallback(
    (key, fallback) => {
      const catalogue = catalogues[locale] || en;
      const value = lookup(catalogue, key);
      if (typeof value === 'string') return value;
      // Fall back to English for a key the active catalogue is missing, so a gap shows as
      // an English sentence rather than a raw key in front of a user. The parity test
      // means this should never fire; it is here for the moment somebody adds a key and
      // ships before the test runs.
      const english = lookup(en, key);
      if (typeof english === 'string') return english;
      return fallback ?? key;
    },
    [locale],
  );

  const value = useMemo(
    () => ({ locale, setLocale, t, availableLocales: Object.keys(catalogues) }),
    [locale, t],
  );

  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

export function useI18n() {
  const context = useContext(I18nContext);
  if (!context) throw new Error('useI18n must be used inside I18nProvider');
  return context;
}

export function useT() {
  return useI18n().t;
}
