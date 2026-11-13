/**
 * Localization for the public tracking shell.
 *
 * Separate from the staff provider (`src/i18n/index.jsx`) because the two have different
 * jobs. The staff one is English-first with a catalogue ready for a second locale; this
 * one is genuinely bilingual from the first render, with a visible switch, and it owns
 * the document's `lang` attribute.
 *
 * There is exactly one set of components. English and Vietnamese are two catalogues, not
 * two page implementations (`Design.md` section 15), so a copy change happens once.
 *
 * **What is stored, and what is not.** The chosen language is remembered in
 * `localStorage`, because a Vietnamese speaker should not have to switch every visit and
 * a language preference is not sensitive. A tracking reference and a tracking result are
 * *never* written to any browser storage (CRM.md section 10) -- the reference lives in
 * the URL, where the customer put it, and the result lives in memory for as long as the
 * page is open.
 */

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import en from './locales/en.js';
import vi from './locales/vi.js';

export const CATALOGUES = { en, vi };
export const LOCALES = ['en', 'vi'];

/** The only key this page is allowed to write. Never a reference, never a result. */
const LANGUAGE_STORAGE_KEY = 'solaris.public.language';

const PublicI18nContext = createContext(null);

function lookup(catalogue, key) {
  return key.split('.').reduce((node, part) => (node == null ? undefined : node[part]), catalogue);
}

/** Replace `{{name}}` placeholders. Kept deliberately small; no formatting library. */
function interpolate(template, values) {
  if (!values) return template;
  return template.replace(/\{\{(\w+)\}\}/g, (match, name) =>
    values[name] === undefined || values[name] === null ? match : String(values[name]),
  );
}

function readStoredLanguage() {
  try {
    const stored = window.localStorage.getItem(LANGUAGE_STORAGE_KEY);
    return LOCALES.includes(stored) ? stored : null;
  } catch {
    // Private browsing, blocked storage, or a test environment without it. The page
    // works without a remembered preference; it just starts in the default language.
    return null;
  }
}

/** Honour the browser's language on a first visit, before anything is stored. */
function detectLanguage() {
  const languages = typeof navigator === 'undefined' ? [] : navigator.languages || [];
  for (const tag of [...languages, typeof navigator === 'undefined' ? '' : navigator.language]) {
    if (typeof tag === 'string' && tag.toLowerCase().startsWith('vi')) return 'vi';
  }
  return 'en';
}

export function PublicI18nProvider({ children, initialLanguage }) {
  const [language, setLanguageState] = useState(
    () => initialLanguage || readStoredLanguage() || detectLanguage(),
  );

  const setLanguage = useCallback((next) => {
    if (!LOCALES.includes(next)) return;
    setLanguageState(next);
    try {
      window.localStorage.setItem(LANGUAGE_STORAGE_KEY, next);
    } catch {
      // A preference we could not remember is a small loss; it must never break the page.
    }
  }, []);

  // The document language drives screen-reader pronunciation and the browser's own
  // offer to translate. Getting this wrong makes a screen reader read Vietnamese with
  // English phonetics, which is unusable rather than merely imperfect.
  useEffect(() => {
    document.documentElement.lang = CATALOGUES[language].meta.languageCode;
  }, [language]);

  // A constant, reference-free title. Set here rather than in the HTML so it follows the
  // chosen language, and never derived from the lookup (CRM.md section 10).
  useEffect(() => {
    document.title = CATALOGUES[language].meta.documentTitle;
  }, [language]);

  const t = useCallback(
    (key, values) => {
      const catalogue = CATALOGUES[language] || en;
      const value = lookup(catalogue, key);
      if (typeof value === 'string') return interpolate(value, values);
      // Fall back to English rather than rendering a raw key at a customer: a missing
      // Vietnamese string should degrade to readable English, not to "landing.title".
      const fallback = lookup(en, key);
      return typeof fallback === 'string' ? interpolate(fallback, values) : key;
    },
    [language],
  );

  const value = useMemo(
    () => ({
      language,
      setLanguage,
      t,
      locale: CATALOGUES[language].meta.locale,
      languages: LOCALES.map((code) => ({
        code,
        name: CATALOGUES[code].meta.languageName,
      })),
    }),
    [language, setLanguage, t],
  );

  return <PublicI18nContext.Provider value={value}>{children}</PublicI18nContext.Provider>;
}

export function usePublicI18n() {
  const context = useContext(PublicI18nContext);
  if (!context) throw new Error('usePublicI18n must be used inside PublicI18nProvider');
  return context;
}

export { LANGUAGE_STORAGE_KEY };
