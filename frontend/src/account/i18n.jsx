/**
 * Localization for the Customer Account (OD-71, 2026-10-20: Vietnamese first, English as
 * an option). Supersedes OD-39, under which this surface was English only.
 *
 * Its own provider, not the staff one (`src/i18n`) and not Public Tracking's
 * (`src/public/i18n.jsx`): this surface imports nothing from either, and
 * `tests/accountBoundary.test.jsx` asserts that by reading the imports.
 *
 * ## Which language
 *
 * 1. The build default: `VITE_ACCOUNT_DEFAULT_LOCALE` when it is `en` or `vi`, otherwise
 *    Vietnamese. The end-to-end runner sets it to `en` so the English assertions read
 *    English; nothing else should.
 * 2. When an identity is signed in and `/account/me` reports `preferred_language` `en` or
 *    `vi`, that — once per signed-in identity, so a language saved on the profile page does
 *    not flip the screen under the person mid-task.
 * 3. A choice made with the switch in the header beats both, for the rest of this page
 *    view.
 *
 * ## What is stored
 *
 * **Nothing.** The choice lives in React state and is gone on reload. This surface never
 * writes `localStorage`, `sessionStorage` or IndexedDB (`tests/e2e/accountSecurity.spec.js`
 * asserts it), and a signed-in person's preference comes back from the server anyway.
 */

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import { AccountApiError } from './accountApi.js';
import en from './i18n/en.js';
import vi from './i18n/vi.js';
import {
  NOT_RECORDED,
  cityCountryLine,
  formatDate,
  formatDateTime,
  formatKg,
  formatMoney,
  packageSummary,
  placeLine,
} from './format.js';

export const ACCOUNT_CATALOGUES = { en, vi };
export const ACCOUNT_LOCALES = ['vi', 'en'];

/** The `Intl` locale each language formats dates in. */
const INTL_LOCALES = { en: 'en-CA', vi: 'vi-VN' };

const AccountI18nContext = createContext(null);

function isLocale(value) {
  return ACCOUNT_LOCALES.includes(value);
}

/** The build default: the env var when it names a supported language, else Vietnamese. */
export function defaultAccountLocale(env = import.meta.env) {
  const configured = env?.VITE_ACCOUNT_DEFAULT_LOCALE;
  return isLocale(configured) ? configured : 'vi';
}

/** Replace `{name}` placeholders. A missing value leaves the placeholder visible. */
function interpolate(template, values) {
  if (!values) return template;
  return template.replace(/\{(\w+)\}/g, (match, name) =>
    values[name] === undefined || values[name] === null ? match : String(values[name]),
  );
}

/** Look a key up in the active catalogue, then English, then give the key back. */
export function translate(locale, key, values) {
  const catalogue = ACCOUNT_CATALOGUES[locale] || en;
  const value = catalogue[key];
  if (typeof value === 'string') return interpolate(value, values);
  const fallback = en[key];
  return typeof fallback === 'string' ? interpolate(fallback, values) : key;
}

/**
 * The English translator, for code that runs outside React and for the exported English
 * constants the older tests compare against.
 */
export function englishT(key, values) {
  return translate('en', key, values);
}

function LocaleState({ initialLocale, children }) {
  const [state, setState] = useState(() => ({
    locale: isLocale(initialLocale) ? initialLocale : defaultAccountLocale(),
    chosen: false,
  }));

  const setLocale = useCallback((next) => {
    if (!isLocale(next)) return;
    setState({ locale: next, chosen: true });
  }, []);

  // A preference from the server, applied only if the person has not used the switch.
  const adoptPreferredLocale = useCallback((preferred) => {
    if (!isLocale(preferred)) return;
    setState((current) =>
      current.chosen || current.locale === preferred ? current : { ...current, locale: preferred },
    );
  }, []);

  const { locale } = state;

  // The document language drives screen-reader pronunciation. Restored on unmount so the
  // staff and public shells get back whatever they had set.
  useEffect(() => {
    const root = document.documentElement;
    const previous = root.getAttribute('lang');
    root.setAttribute('lang', locale);
    return () => {
      if (previous === null) root.removeAttribute('lang');
      else root.setAttribute('lang', previous);
    };
  }, [locale]);

  // A constant title: never a reference, never a name.
  useEffect(() => {
    const previous = document.title;
    document.title = translate(locale, 'meta.documentTitle');
    return () => {
      document.title = previous;
    };
  }, [locale]);

  const t = useCallback((key, values) => translate(locale, key, values), [locale]);

  const value = useMemo(
    () => ({ locale, setLocale, adoptPreferredLocale, t, intlLocale: INTL_LOCALES[locale] }),
    [locale, setLocale, adoptPreferredLocale, t],
  );

  return <AccountI18nContext.Provider value={value}>{children}</AccountI18nContext.Provider>;
}

/**
 * The provider. A second one inside an existing one passes through, so a test can pin the
 * language above `App` and the provider `AccountApp` mounts defers to it.
 */
export function AccountI18nProvider({ initialLocale, children }) {
  const outer = useContext(AccountI18nContext);
  if (outer) return children;
  return <LocaleState initialLocale={initialLocale}>{children}</LocaleState>;
}

function useAccountI18n() {
  const context = useContext(AccountI18nContext);
  if (!context) throw new Error('Customer Account i18n used outside AccountI18nProvider');
  return context;
}

/** `t(key, values?)`. */
export function useAccountT() {
  return useAccountI18n().t;
}

/** `{ locale, setLocale }`, plus `adoptPreferredLocale` for the session bridge. */
export function useAccountLocale() {
  const { locale, setLocale, adoptPreferredLocale } = useAccountI18n();
  return { locale, setLocale, adoptPreferredLocale };
}

/**
 * Labels the server sends in English (`status_label`, `route_label`, `country_label`).
 *
 * In English the server's own word is shown, unchanged. In Vietnamese the code is looked
 * up and the server's word is the fallback for a code this build does not know.
 */
export function useServerLabel() {
  const { locale } = useAccountI18n();
  return useCallback(
    (prefix, code, serverLabel) => {
      if (locale === 'en' || !code) return serverLabel ?? code ?? '';
      const value = ACCOUNT_CATALOGUES[locale]?.[`${prefix}.${code}`];
      return typeof value === 'string' ? value : serverLabel ?? code;
    },
    [locale],
  );
}

/** The formatting helpers, bound to the active language. */
export function useAccountFormat() {
  const { t, intlLocale, locale } = useAccountI18n();
  const serverLabel = useServerLabel();
  return useMemo(() => {
    const notRecorded = t('format.notRecorded');
    const countryLabel = (place) =>
      place ? serverLabel('country', place.country_code, place.country_label) : null;
    return {
      locale,
      notRecorded,
      formatDate: (value, timeZone) => formatDate(value, timeZone, intlLocale),
      formatDateTime: (value, timeZone) => formatDateTime(value, timeZone, intlLocale),
      formatMoney: (value, currency) => formatMoney(value, currency, intlLocale),
      formatKg: (value) => formatKg(value, intlLocale),
      placeLine: (place) =>
        placeLine(place, {
          notRecorded,
          countryLabel: place ? countryLabel(place) || place.country_code : null,
        }),
      cityCountryLine: (city, countryCode) => cityCountryLine(city, countryCode, { notRecorded }),
      packageSummary: (counts) => packageSummary(counts, t),
    };
  }, [t, intlLocale, locale, serverLabel]);
}

/**
 * The sentence to show for a failed request, in the active language.
 *
 * In English it is the error's own `message`: the server's reviewed sentence, or the
 * client's English fallback. In any other language the server's English is **not** shown;
 * a translation is chosen from what the error carries — the HTTP status, the code and the
 * field — never from the English text:
 *
 * * network failure → `api.network`;
 * * 400/422 with a field → `fieldMessage(field)` from the page when it maps that field to
 *   its own sentence, `common.linkInvalid` for the single-answer token field, otherwise
 *   `api.field`; without a field → `api.422`;
 * * 401, 403, 404, 409 → `api.401` … `api.409`;
 * * 429 → `api.429seconds` with the Retry-After count, or `api.429`;
 * * 503 → `api.503`; any other 5xx, or anything unrecognised → `api.generic`.
 *
 * `context: 'signIn'` keeps sign-in failures deliberately generic: whatever the status, a
 * refusal reads as "email or password is incorrect" — only a throttle and a network failure
 * are said as themselves, as the server does in English (`STATE_MACHINES.md` §7).
 */
export function localizeAccountError(locale, error, { fieldMessage, context } = {}) {
  if (!error) return '';
  if (locale === 'en') return error.message || translate('en', 'api.generic');
  const say = (key, values) => translate(locale, key, values);
  if (!(error instanceof AccountApiError)) return say('api.generic');

  const { status } = error;
  if (status === 0 || error.code === 'network_error') return say('api.network');
  if (status === 429) {
    return error.retryAfterSeconds
      ? say('api.429seconds', { seconds: error.retryAfterSeconds })
      : say('api.429');
  }
  if (context === 'signIn') return say('signIn.genericFailure');
  if (status === 400 || status === 422) {
    if (error.field) {
      if (error.field === 'token') return say('common.linkInvalid');
      const mapped = fieldMessage?.(error.field);
      return mapped || say('api.field');
    }
    return say('api.422');
  }
  if (status === 401) return say('api.401');
  if (status === 403) return say('api.403');
  if (status === 404) return say('api.404');
  if (status === 409) return say('api.409');
  if (status === 503) return say('api.503');
  return say('api.generic');
}

/** `errorText(error, { fieldMessage?, context? })` for the active language. */
export function useAccountErrorText() {
  const { locale } = useAccountI18n();
  return useCallback(
    (error, options) => localizeAccountError(locale, error, options),
    [locale],
  );
}

/**
 * A server **success** sentence (`message` on a 2xx body), in the active language: the
 * server's own words in English, the catalogue's `key` otherwise.
 */
export function useServerSentence() {
  const { locale, t } = useAccountI18n();
  return useCallback(
    (serverMessage, key) => (locale === 'en' ? serverMessage ?? t(key) : t(key)),
    [locale, t],
  );
}

export { NOT_RECORDED };
