/**
 * Turn a timestamp from the API into a `Date`, reading a naive value as UTC.
 *
 * The backend stores UTC and serializes it **without** a zone designator
 * (`2026-10-14T05:19:00`). `new Date()` reads such a string as the *browser's local* time,
 * so a value formatted afterwards in `America/Toronto` showed the raw UTC clock under a
 * Toronto label: 05:19 where 01:19 was right (UAT round 2, fix pack 2 item 2). This is the
 * one place that decides, for all three shells, that a missing designator means UTC.
 *
 * A value that already carries a designator -- `Z`, `+00:00`, `-04:00`, `+0530` -- is
 * left alone. The earlier per-file checks each missed one of those shapes: the public
 * page appended `Z` to a value ending `+00:00`, and the staff formatter mistook a negative
 * offset for a naive value.
 *
 * Shared by the staff portal, Public Tracking and the Customer Account. It imports nothing,
 * which is what lets the Customer Account boundary allow it.
 */

const HAS_ZONE = /(?:Z|[+-]\d{2}(?::?\d{2})?)$/i;
const HAS_TIME = /T\d{2}:\d{2}/;

/** `Date` or `null`. A date-only string (`2026-10-14`) is left to the platform. */
export function parseServerDate(value) {
  if (value === null || value === undefined || value === '') return null;
  if (value instanceof Date) return Number.isNaN(value.getTime()) ? null : value;
  const text = String(value).trim();
  const iso = HAS_TIME.test(text) && !HAS_ZONE.test(text) ? `${text}Z` : text;
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? null : date;
}
