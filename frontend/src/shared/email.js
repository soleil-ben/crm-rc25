/**
 * Whether a typed value has the shape of an email address (UAT round 5).
 *
 * The same rules the server's `email-validator` applies before it would accept the value,
 * so a form flags "bad" before sending it rather than after: one `@`, a local part, and a
 * domain of at least two dot-separated labels whose last is letters. No spaces.
 * The server stays the authority and answers with the same sentence
 * (`app/core/normalization.py`, `INVALID_EMAIL_MESSAGE`); this only saves a round trip.
 * Deliverability is not checked, on either side.
 */

// Permissive on the local part (the server accepts internationalized ones) and strict only
// where "bad" and "name@localhost" fail, so the browser never refuses what the server takes.
const LOCAL = /^[^\s@."]+(\.[^\s@."]+)*$/u;
const LABEL = /^[\p{L}\p{N}](?:[\p{L}\p{N}-]{0,61}[\p{L}\p{N}])?$/u;
const TOP_LEVEL = /^(?:\p{L}{1,63}|xn--[a-z0-9-]{1,59})$/iu;

export function isValidEmail(value) {
  const text = String(value ?? '').trim();
  if (!text || text.length > 320 || /\s/.test(text)) return false;
  const at = text.lastIndexOf('@');
  if (at <= 0 || at !== text.indexOf('@')) return false;
  const local = text.slice(0, at);
  const domain = text.slice(at + 1);
  if (local.length > 64 || !LOCAL.test(local)) return false;
  const labels = domain.split('.');
  if (labels.length < 2) return false;
  if (!labels.every((label) => LABEL.test(label))) return false;
  return TOP_LEVEL.test(labels[labels.length - 1]);
}

/** The sentence both sides use. Kept identical to the server's `INVALID_EMAIL_MESSAGE`. */
export const INVALID_EMAIL_MESSAGE = 'Enter a valid email address, like name@example.com.';
