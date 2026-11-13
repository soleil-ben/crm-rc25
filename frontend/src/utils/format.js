/**
 * Display formatting.
 *
 * Timestamps arrive from the API in UTC and are rendered in the configured office
 * timezone with the zone shown when it matters operationally (CRM.md section 3,
 * Design.md section 15). Missing values render as an explicit dash, never as zero.
 */

import { parseServerDate } from '../shared/serverDate.js';

const OFFICE_TIMEZONE = 'America/Toronto';

function toDate(value) {
  // The API sends naive UTC timestamps. One parser decides that for every shell
  // (`src/shared/serverDate.js`); the earlier inline check read a negative offset as naive.
  return parseServerDate(value);
}

export function formatDate(value, { locale = 'en-CA' } = {}) {
  const date = toDate(value);
  if (!date) return '—';
  return new Intl.DateTimeFormat(locale, {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    timeZone: OFFICE_TIMEZONE,
  }).format(date);
}

const PLAIN_DATE = /^(\d{4})-(\d{2})-(\d{2})/;

/**
 * A calendar date with no time zone (RC-20): a payment's received date.
 *
 * The API sends such a date as midnight of the day (`2026-09-20T00:00:00`) or as
 * `2026-09-20`. Read through `formatDate` that is midnight UTC, i.e. 19 September 20:00 in
 * Toronto: the payment showed a day early. Here the `YYYY-MM-DD` part is taken as written
 * and formatted in UTC, so no zone, the browser's or the office's, can move it.
 */
export function formatPlainDate(value, { locale = 'en-CA' } = {}) {
  const match = PLAIN_DATE.exec(String(value ?? '').trim());
  if (!match) return '—';
  const [, year, month, day] = match.map(Number);
  return new Intl.DateTimeFormat(locale, {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    timeZone: 'UTC',
  }).format(new Date(Date.UTC(year, month - 1, day)));
}

// `2026-09-20`, or that date at exactly midnight: `T00:00`, `T00:00:00`, `T00:00:00.000000`,
// with or without a zone designator (`Z`, `+00:00`, `-04:00`).
const PLAIN_OR_MIDNIGHT = /^\d{4}-\d{2}-\d{2}(?:[T ]00:00(?::00(?:\.0+)?)?(?:Z|[+-]\d{2}(?::?\d{2})?)?)?$/i;

/**
 * A payment's (or refund's, or receipt's) received date, RC-20 (DEC-0229 §1).
 *
 * Since the fix the backend stores the date as written, as naive midnight
 * (`2026-09-20T00:00:00`): shown as a plain date, no zone can move it.
 *
 * Rows recorded **before** the fix hold a real naive-UTC instant (`2026-09-20T02:30:00` is
 * 19 September 22:30 in Toronto). They keep the date they always showed: read as UTC, shown
 * in the office zone, exactly as `formatDate` did.
 *
 * Ambiguity, decided on purpose: a legacy row recorded at exactly 00:00:00 UTC cannot be
 * told apart from a post-fix plain date. Midnight is read as a plain date (the stored
 * convention), so such a row shows one day later than it did before the fix.
 */
export function formatReceivedDate(value, { locale = 'en-CA' } = {}) {
  if (value === null || value === undefined || value === '') return '—';
  if (value instanceof Date) return formatDate(value, { locale });
  const text = String(value).trim();
  if (PLAIN_OR_MIDNIGHT.test(text)) return formatPlainDate(text, { locale });
  return formatDate(text, { locale });
}

/** Today's calendar date in the browser's own zone as `YYYY-MM-DD` (never `toISOString`, which is UTC). */
export function localToday(now = new Date()) {
  const pad = (n) => String(n).padStart(2, '0');
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
}

export function formatDateTime(value, { locale = 'en-CA', showZone = true } = {}) {
  const date = toDate(value);
  if (!date) return '—';
  return new Intl.DateTimeFormat(locale, {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
    timeZone: OFFICE_TIMEZONE,
    timeZoneName: showZone ? 'short' : undefined,
  }).format(date);
}

/** Relative day count, used next to an absolute date rather than replacing it. */
export function relativeDays(value) {
  const date = toDate(value);
  if (!date) return null;
  const days = Math.round((Date.now() - date.getTime()) / 86_400_000);
  if (days === 0) return 'today';
  if (days === 1) return 'yesterday';
  if (days > 0) return `${days} days ago`;
  if (days === -1) return 'tomorrow';
  return `in ${Math.abs(days)} days`;
}

export function formatNumber(value, { locale = 'en-CA' } = {}) {
  if (value === null || value === undefined) return '—';
  return new Intl.NumberFormat(locale).format(value);
}

/** Currencies are always rendered with their own code; totals are never merged. */
export function formatMoney(amount, currency, { locale = 'en-CA' } = {}) {
  if (amount === null || amount === undefined) return 'Unknown';
  const value = Number(amount);
  if (!Number.isFinite(value)) return `${String(amount)} ${currency || ''}`.trim();
  try {
    return new Intl.NumberFormat(locale, {
      style: 'currency',
      currency: currency || 'CAD',
      currencyDisplay: 'code',
    }).format(value);
  } catch {
    // RC-UAT-25 item 7 (Ben 2026-10-25): a stored code Intl refuses ("CA", "$") threw a
    // RangeError here and blanked the shipment page. Show the amount with the code as stored.
    const number = new Intl.NumberFormat(locale, {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    }).format(value);
    // A no-break space, as Intl puts between a code and the amount.
    return `${String(currency).trim()}\u00a0${number}`.trim();
  }
}

/** True when `formatMoney` can format `currency` as a real currency code (blank counts). */
export function isFormattableCurrency(currency) {
  if (!currency) return true;
  try {
    new Intl.NumberFormat('en-CA', { style: 'currency', currency });
    return /^[A-Za-z]{3}$/.test(String(currency));
  } catch {
    return false;
  }
}

export function formatPercent(share, { locale = 'en-CA', digits = 0 } = {}) {
  if (share === null || share === undefined) return '—';
  return new Intl.NumberFormat(locale, {
    style: 'percent',
    maximumFractionDigits: digits,
  }).format(share);
}

/** A datetime-local input needs a local wall-clock string, not a UTC ISO string. */
export function toLocalInputValue(value) {
  const date = toDate(value) || new Date();
  const offsetMs = date.getTimezoneOffset() * 60_000;
  return new Date(date.getTime() - offsetMs).toISOString().slice(0, 16);
}

/** Convert a datetime-local input value back to an ISO string for the API. */
export function fromLocalInputValue(value) {
  if (!value) return null;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date.toISOString();
}

export function contactSummary(customer) {
  return [customer.phone_entered, customer.email_entered].filter(Boolean);
}

export function locationSummary(record) {
  return [record.city, record.province_state, record.country_code].filter(Boolean).join(', ') || '—';
}

/**
 * Fill every `{name}` placeholder in a catalogue sentence.
 *
 * `String.prototype.replace` with a string pattern replaces the **first** occurrence only,
 * so a sentence naming `{source}` twice kept its second placeholder on screen ("move to
 * {target}; {source} is retired", fix pack 2 item 4). A placeholder with no value is left
 * as written rather than turned into "undefined", so a missing argument is visible in a
 * test instead of silently wrong.
 */
export function interpolate(text, values = {}) {
  return String(text).replace(/\{(\w+)\}/g, (match, key) =>
    Object.prototype.hasOwnProperty.call(values, key) ? String(values[key]) : match,
  );
}
