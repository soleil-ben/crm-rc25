/**
 * The public tracking page's only network call.
 *
 * Deliberately not `src/api/client.js`. That client reads the CSRF cookie, sends the
 * session cookie, and knows about staff error envelopes -- none of which belongs on a
 * page a stranger loads. This module talks to exactly one endpoint and does nothing else.
 *
 * `credentials: 'omit'` is the important line: the public request must not carry a staff
 * session cookie even when a signed-in staff member happens to open the tracking page in
 * the same browser. The response is identical either way (the backend test asserts it),
 * but not sending the cookie means the server never has the option of behaving
 * differently.
 */

const PUBLIC_API_BASE = '/api/v1/public';

export class PublicTrackingError extends Error {
  constructor({ kind, status, retryAfterSeconds }) {
    super(kind);
    this.name = 'PublicTrackingError';
    /** 'not_found' | 'rate_limited' | 'network' | 'server' */
    this.kind = kind;
    this.status = status ?? 0;
    this.retryAfterSeconds = retryAfterSeconds ?? null;
  }
}

function retryAfterFrom(response) {
  const header = response.headers?.get?.('Retry-After');
  if (!header) return null;
  const seconds = Number.parseInt(header, 10);
  return Number.isFinite(seconds) && seconds > 0 ? seconds : null;
}

/**
 * Look up one reference.
 *
 * The reference goes in the path because that is what the label's QR code encodes and
 * what a customer can bookmark. It is URL-encoded rather than interpolated raw, so a
 * pasted `#` or `?` cannot silently truncate the lookup or turn part of it into a query
 * string.
 */
export async function fetchPublicTracking(reference, { signal } = {}) {
  let response;
  try {
    response = await fetch(`${PUBLIC_API_BASE}/track/${encodeURIComponent(reference)}`, {
      method: 'GET',
      headers: { Accept: 'application/json' },
      // No cookies out, no cookies in. This page has no session and never gains one.
      credentials: 'omit',
      cache: 'no-store',
      referrerPolicy: 'no-referrer',
      signal,
    });
  } catch (error) {
    if (error?.name === 'AbortError') throw error;
    throw new PublicTrackingError({ kind: 'network' });
  }

  if (response.status === 429) {
    throw new PublicTrackingError({
      kind: 'rate_limited',
      status: 429,
      retryAfterSeconds: retryAfterFrom(response),
    });
  }
  if (response.status === 404) {
    // The server returns one generic failure for an invalid reference, an unknown one, a
    // draft, and a demo record in production. The page must not try to be cleverer than
    // that: one message, whatever the cause.
    throw new PublicTrackingError({ kind: 'not_found', status: 404 });
  }
  if (!response.ok) {
    throw new PublicTrackingError({ kind: 'server', status: response.status });
  }

  return response.json();
}
