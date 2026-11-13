/**
 * The token a verification or password-reset link carries, taken out of the URL at the
 * earliest possible moment and held in memory until the landing page asks for it.
 *
 * ## The contract with the backend
 *
 * `customer_identity_service.verification_url` and `password_reset_url` put the token in
 * the URL **fragment** — `/account/reset-password#token=…` — rather than the query string
 * (CA-SEC-07, fix pack of 2026-10-14). A fragment is never sent to a server, so the token
 * reaches neither the application's access log, nor the reverse proxy's, nor the
 * `Referer` of anything the page loads. Older `?token=` links are still accepted by the
 * landing pages themselves; this module only handles the fragment.
 *
 * ## Why this runs from `main.jsx` and not from a page effect
 *
 * A page effect runs after React has mounted, after the router has read the location,
 * and after any navigation React Router recorded. `captureLinkToken` runs as the first
 * statement of the entry module, before `createRoot`: it copies the token into a
 * module-level variable and rewrites the address bar with `history.replaceState`, so the
 * address bar, the session history entry and the Back button never hold the token, and
 * React Router never sees it.
 *
 * ## What this cannot do
 *
 * It cannot keep the committed URL out of the browser's global history database.
 * Chromium records the URL at navigation commit, fragment included, before any script
 * runs. The bound on that exposure is the token itself: single-use, short-lived,
 * purpose-bound, and invalidated by the next one issued.
 *
 * Nothing here touches `localStorage` or `sessionStorage` — `tests/accountBoundary.test.jsx`
 * reads this directory's source to assert that, and the value lives only in this
 * closure, read once and then dropped.
 */

const FRAGMENT_PREFIX = '#token=';

let stashed = null;

/**
 * Read `#token=…` out of the current location, keep it in memory, and strip it from the
 * address bar in place. Safe to call when there is no fragment: it does nothing.
 */
export function captureLinkToken(win = typeof window === 'undefined' ? null : window) {
  if (!win || !win.location) return;
  const { hash, pathname, search } = win.location;
  if (typeof hash !== 'string' || !hash.startsWith(FRAGMENT_PREFIX)) return;
  const raw = hash.slice(FRAGMENT_PREFIX.length).split('&')[0];
  if (!raw) return;
  let token = raw;
  try {
    token = decodeURIComponent(raw);
  } catch {
    token = raw;
  }
  stashed = token;
  // `replaceState`, never `pushState`: the entry that carried the token is overwritten
  // rather than left behind one step back.
  win.history.replaceState(win.history.state, '', `${pathname}${search}`);
}

/** The captured token, once. A second call returns null. */
export function takeLinkToken() {
  const token = stashed;
  stashed = null;
  return token;
}

/**
 * The token out of a router location, for the landing pages: the fragment first (for a
 * page rendered without `main.jsx` having run, such as a unit test or a hash that
 * arrived by client-side navigation), then the query string a pre-fix link still uses.
 */
export function tokenFromLocation(location) {
  const hash = location?.hash ?? '';
  if (hash.startsWith(FRAGMENT_PREFIX)) {
    const raw = hash.slice(FRAGMENT_PREFIX.length).split('&')[0];
    try {
      return raw ? decodeURIComponent(raw) : null;
    } catch {
      return raw || null;
    }
  }
  const search = location?.search ?? '';
  return new URLSearchParams(search).get('token');
}

/** Whether a location still carries a token in either shape. */
export function locationCarriesToken(location) {
  return tokenFromLocation(location) !== null;
}
