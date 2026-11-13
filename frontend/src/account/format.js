/**
 * Date and number formatting for the Customer Account.
 *
 * **The response's own timezone is used, never the browser's.** Both the list and the
 * detail carry a `timezone` field, which is the organization's configured zone and the
 * one every staff screen, every report boundary and Public Tracking already use
 * (DEC-0076). A customer in Vancouver and a staff member in Mississauga looking at the
 * same shipment must read the same date, or a support call becomes an argument about
 * which of the two is wrong.
 *
 * The locale follows the Customer Account's chosen language (OD-71) — `en-CA` or `vi-VN` —
 * and never the browser's, for the same reason: a date that reorders itself by visitor is
 * a date two people cannot discuss. Called without a locale, as the older tests do, it is
 * `en-CA`. `useAccountFormat()` in `i18n.jsx` binds these to the active language.
 */

import { parseServerDate } from '../shared/serverDate.js';

const DEFAULT_LOCALE = 'en-CA';

/** Falls back to the configured default only if a response somehow omits the field. */
export const FALLBACK_TIMEZONE = 'America/Toronto';

function formatter(timeZone, options, locale = DEFAULT_LOCALE) {
  try {
    return new Intl.DateTimeFormat(locale, { ...options, timeZone: timeZone || FALLBACK_TIMEZONE });
  } catch {
    // An unknown zone string would throw on every render. Falling back keeps the page
    // readable; the value is the server's, so this should never fire.
    return new Intl.DateTimeFormat(locale, { ...options, timeZone: FALLBACK_TIMEZONE });
  }
}

/** `2026-09-21`. Used where a day is the whole answer. */
export function formatDate(value, timeZone, locale = DEFAULT_LOCALE) {
  // Naive API timestamps are UTC; read them as UTC before formatting in the response's
  // zone, or the Toronto label sits over the raw UTC clock (fix pack 2, item 2).
  const date = parseServerDate(value);
  if (!date) return null;
  return formatter(timeZone, { year: 'numeric', month: 'short', day: '2-digit' }, locale).format(
    date,
  );
}

/** `21 Sep 2026, 14:05`. Used where the time of day matters — a timeline entry. */
export function formatDateTime(value, timeZone, locale = DEFAULT_LOCALE) {
  // Naive API timestamps are UTC; read them as UTC before formatting in the response's
  // zone, or the Toronto label sits over the raw UTC clock (fix pack 2, item 2).
  const date = parseServerDate(value);
  if (!date) return null;
  return formatter(timeZone, {
    year: 'numeric',
    month: 'short',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }, locale).format(date);
}

/**
 * What to render where a date is absent.
 *
 * A dash would be ambiguous — unknown, or not applicable? — and an empty cell reads as a
 * rendering bug. The word is stated, and it is the same word everywhere. This is the
 * English word; screens use `format.notRecorded` from the catalogue.
 */
export const NOT_RECORDED = 'Not recorded';

/**
 * The customer's own booking reference, on the list row (UAT round 11, DEC-0160) and on the
 * shipment's own page (UAT round 12, DEC-0163). One label, so the two screens agree.
 */
export const BOOKING_REFERENCE_LABEL = 'Booking reference';

/** `YYYY-MM-DD` for a date input's value, from a `Date`. */
export function toDateInputValue(date) {
  const pad = (n) => String(n).padStart(2, '0');
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}

/**
 * A place, as one line.
 *
 * City and country only — the coarse granularity the allowlist carries. There is no
 * street, no postal code and no recipient name in the response to render even by
 * accident.
 */
export function placeLine(place, { notRecorded = NOT_RECORDED, countryLabel } = {}) {
  if (!place) return notRecorded;
  const country = countryLabel || place.country_label || place.country_code;
  const parts = [place.city, country].filter(Boolean);
  return parts.length ? parts.join(', ') : notRecorded;
}

/** `Mississauga, CA` from the list item's flat pair of columns. */
export function cityCountryLine(city, countryCode, { notRecorded = NOT_RECORDED } = {}) {
  const parts = [city, countryCode].filter(Boolean);
  return parts.length ? parts.join(', ') : notRecorded;
}

/**
 * How a shipment's packages read as a sentence.
 *
 * The counts are in the response as numbers; this is the text equivalent required for a
 * progress indication that is not carried by a bar alone (`Design.md` §14a.5).
 */
export function packageSummary({ active = 0, cancelled = 0, delivered = null }, t = englishWords) {
  const bits = [t(active === 1 ? 'format.packageOne' : 'format.packageMany', { count: active })];
  if (delivered !== null && delivered !== undefined) {
    bits.push(t('format.deliveredCount', { count: delivered }));
  }
  if (cancelled > 0) bits.push(t('format.cancelledCount', { count: cancelled }));
  return bits.join(', ');
}

/** The English words `packageSummary` uses when no translator is given. */
const ENGLISH_PACKAGE_WORDS = {
  'format.packageOne': '{count} package',
  'format.packageMany': '{count} packages',
  'format.deliveredCount': '{count} delivered',
  'format.cancelledCount': '{count} cancelled',
};

function englishWords(key, values) {
  return ENGLISH_PACKAGE_WORDS[key].replace('{count}', String(values.count));
}

/**
 * `CAD 1,234.50` (English) or `1.234,50 CAD` (Vietnamese). Quotes (Phase 13G) are in
 * Canadian dollars; the amount is the server's decimal string, shown with the currency code
 * rather than a bare `$` that could be read as US dollars.
 */
export function formatMoney(value, currency = 'CAD', locale = DEFAULT_LOCALE) {
  if (value === null || value === undefined || value === '') return null;
  const number = Number(value);
  if (!Number.isFinite(number)) return null;
  try {
    return new Intl.NumberFormat(locale, {
      style: 'currency',
      currency,
      currencyDisplay: 'code',
    }).format(number);
  } catch {
    return `${currency} ${number.toFixed(2)}`;
  }
}

/** `12` / `12.5` kg in the reader's number format (`12,5` in Vietnamese), up to grams. */
export function formatKg(value, locale = DEFAULT_LOCALE) {
  if (value === null || value === undefined || value === '') return null;
  const number = Number(value);
  if (!Number.isFinite(number)) return null;
  return `${new Intl.NumberFormat(locale, { maximumFractionDigits: 3 }).format(number)} kg`;
}
