/**
 * Client-side reference tidying.
 *
 * This mirrors the *forgiving* half of `backend/app/core/public_reference.py` and
 * deliberately not the strict half. Normalizing in the browser means a pasted
 * `  sx-cav-7k9d2m4r8t6w-01.  ` becomes a clean URL the customer can bookmark, and a
 * barcode scanner's trailing whitespace does not produce a puzzling failure.
 *
 * Validation stays on the server, and only on the server. If the browser rejected a
 * malformed reference before sending it, three things would go wrong: the rate limit
 * would never see the attempt, the page would be telling the customer that their input
 * is well formed or not -- which is exactly the distinction the server works to hide --
 * and the two implementations would eventually disagree about what a reference is.
 *
 * So: tidy here, decide there.
 */

/** Dash variants a mail client, word processor, or phone keyboard substitutes. */
const DASH_VARIANTS = /[‐‑‒–—―−－_]/g;

/**
 * Whitespace, plus the invisible characters a copy-paste drags along: zero-width space,
 * zero-width non-joiner and joiner, and the byte-order mark. Written as escapes rather
 * than literals so they are visible to anyone reading this file.
 */
const WHITESPACE = /(?:\s|\u200B|\u200C|\u200D|\uFEFF)+/gu;

/** Quotes and punctuation a customer's message app wraps around a pasted code. */
const EDGE_NOISE = /^[\s"'`<>[\](){}.,;:!?|\\/«»]+|[\s"'`<>[\](){}.,;:!?|\\/«»]+$/g;

/** Longest input worth tidying. Matches the server's limit. */
export const MAX_REFERENCE_LENGTH = 120;

export function normalizeReference(raw) {
  if (!raw) return '';
  return String(raw)
    .slice(0, MAX_REFERENCE_LENGTH)
    .replace(DASH_VARIANTS, '-')
    .replace(WHITESPACE, '')
    .toUpperCase()
    .replace(EDGE_NOISE, '');
}
