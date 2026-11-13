/**
 * The Customer Account's own network layer. Nothing here is shared with another surface.
 *
 * Deliberately **not** `src/api/client.js`. That client reads `solaris_csrf`, sends
 * `X-CSRF-Token`, and knows the staff error envelope — every one of which is the wrong
 * realm here. A customer route presented with a staff CSRF token gets a 403, because the
 * token was never hashed onto a `customer_sessions` row
 * (`docs/customer_account/SESSION_COOKIES_AND_CSRF.md` §5), so sharing the client would
 * not even be a *working* mistake; it would be a mistake that looks like a session bug.
 *
 * Deliberately not `src/public/publicApi.js` either. That module sends `credentials:
 * 'omit'` because the public page has no session and must never gain one. This one has a
 * session and has to send it.
 *
 * ## What this module will not do
 *
 * * **It never reads or writes `localStorage` or `sessionStorage`.** There is no token to
 *   put there: the session lives in an `HttpOnly` cookie the browser sends on its own, and
 *   the CSRF value is read out of its readable cookie at the moment a request is built and
 *   is not retained afterwards. `tests/accountBoundary.test.jsx` asserts the absence by
 *   reading this file's source, which is crude and exactly right for a rule of the form
 *   "this string must not appear".
 * * **It never keeps the CSRF value in a variable that outlives the call.** Copying a
 *   cookie into React state is how a value that the browser scopes and expires becomes a
 *   value the application scopes and forgets to expire.
 * * **It never sends a staff header.** The two header names are different constants in two
 *   different files, and no import crosses between them.
 */

/** The Customer Account API prefix. Every call in this file is under it. */
const ACCOUNT_API_BASE = '/api/v1/account';

/** Read by the browser and echoed by us. Not the session cookie, which is `HttpOnly`. */
const ACCOUNT_CSRF_COOKIE = 'solaris_account_csrf';
const ACCOUNT_CSRF_HEADER = 'X-Account-CSRF-Token';

/**
 * One error type for the whole surface, matching the one body shape the server sends:
 * `{code, message, field}` and nothing else (`app/schemas/account.py`,
 * `AccountErrorResponse`).
 *
 * `field` is present and null on every failure that is not a format error, so a form can
 * ask for it without checking whether it exists.
 */
export class AccountApiError extends Error {
  constructor({ status, code, message, field, retryAfterSeconds }) {
    super(message);
    this.name = 'AccountApiError';
    this.status = status;
    this.code = code || 'request_failed';
    this.field = field ?? null;
    this.retryAfterSeconds = retryAfterSeconds ?? null;
  }

  /** No session, or one the server has revoked. The shell signs the page out. */
  get isSignedOut() {
    return this.status === 401;
  }

  /** A live session that may not do this — pending approval, no link, stale CSRF. */
  get isRefused() {
    return this.status === 403;
  }

  get isNotFound() {
    return this.status === 404;
  }

  /** A format problem the form can point at. Never an existence problem. */
  get isValidation() {
    return this.status === 422 || this.status === 400;
  }

  get isRateLimited() {
    return this.status === 429;
  }
}

/**
 * The readable CSRF cookie, or null.
 *
 * Read at call time rather than at mount. A sign-in rotates the session and issues a new
 * CSRF cookie, and a value captured before that is stale — which the server answers with
 * a 403 that reads, to a user, like being signed out.
 */
function readAccountCsrfToken() {
  const prefix = `${ACCOUNT_CSRF_COOKIE}=`;
  const match = document.cookie.split('; ').find((entry) => entry.startsWith(prefix));
  return match ? decodeURIComponent(match.slice(prefix.length)) : null;
}

/**
 * Build the URL, dropping empty parameters.
 *
 * Empty means *absent*: a cleared filter box must not become `?reference=`, which the
 * server would have to decide about. It is dropped here so the request says what the
 * screen means.
 */
export function buildAccountUrl(path, params) {
  const url = `${ACCOUNT_API_BASE}${path}`;
  if (!params) return url;
  const search = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value === undefined || value === null || value === '') return;
    search.append(key, String(value));
  });
  const query = search.toString();
  return query ? `${url}?${query}` : url;
}

function retryAfterFrom(response) {
  const header = response.headers?.get?.('Retry-After');
  if (!header) return null;
  const seconds = Number.parseInt(header, 10);
  return Number.isFinite(seconds) && seconds > 0 ? seconds : null;
}

/**
 * The client's own English sentences, used only when the server sent none. `message` on an
 * `AccountApiError` is always English (the server's reviewed sentence, or one of these);
 * a Vietnamese screen does not show it but a translation chosen by status, code and field
 * (`localizeAccountError` in `i18n.jsx`).
 */
const FALLBACK_MESSAGES = {
  401: 'Your session has ended. Sign in again to continue.',
  403: 'That is not available on this account.',
  404: 'We could not find that.',
  422: 'Check the details and try again.',
  429: 'Too many requests. Wait a moment and try again.',
};

const GENERIC_FAILURE = 'Something went wrong. Try again in a moment.';
const NETWORK_FAILURE = 'Could not reach Solaris Express. Check your connection and try again.';

async function toAccountError(response) {
  let payload = {};
  try {
    payload = await response.json();
  } catch {
    payload = {};
  }
  return new AccountApiError({
    status: response.status,
    code: payload.code,
    // The server's sentence is preferred because it is the reviewed copy. The fallback is
    // for a failure that produced no body at all — a proxy error page, say — and is
    // deliberately as uninformative as the server's own.
    message:
      payload.message || FALLBACK_MESSAGES[response.status] || GENERIC_FAILURE,
    field: payload.field,
    retryAfterSeconds: retryAfterFrom(response),
  });
}

async function accountRequest(path, { method = 'GET', params, body, signal } = {}) {
  const headers = { Accept: 'application/json' };
  if (body !== undefined) headers['Content-Type'] = 'application/json';

  if (method !== 'GET' && method !== 'HEAD') {
    const token = readAccountCsrfToken();
    // Sent when present and omitted when not. A missing header is a 403 from the server,
    // which is the right answer: inventing a value here would turn a real CSRF failure
    // into a confusing one.
    if (token) headers[ACCOUNT_CSRF_HEADER] = token;
  }

  let response;
  try {
    response = await fetch(buildAccountUrl(path, params), {
      method,
      headers,
      // Same-origin only. The API is proxied onto this origin in development and served
      // from it in production, so there is no cross-origin case to allow.
      credentials: 'same-origin',
      // An authenticated response must not sit in a cache. The server sends `no-store`;
      // this says the same thing from the other end so a `fetch` cannot serve a stale
      // shipment list out of the HTTP cache after a sign-out.
      cache: 'no-store',
      referrerPolicy: 'no-referrer',
      body: body === undefined ? undefined : JSON.stringify(body),
      signal,
    });
  } catch (error) {
    if (error?.name === 'AbortError') throw error;
    throw new AccountApiError({
      status: 0,
      code: 'network_error',
      message: NETWORK_FAILURE,
    });
  }

  if (!response.ok) throw await toAccountError(response);
  if (response.status === 204) return null;
  return response.json();
}

/**
 * Every call this surface makes, named. There is no generic escape hatch on purpose: a
 * screen that needs an endpoint not listed here is a screen that needs a decision, and
 * `tests/accountBoundary.test.jsx` asserts that the paths below are the whole set.
 *
 * All of them are under `/api/v1/account`. **None** is a staff path: there is no
 * `/auth/me`, no `/shipments/{id}` from `/api/v1`, and no `/api/v1/public/track`
 * fallback. A Customer Account screen that cannot get a value from these responses is a
 * documentation change first (`SHIPMENT_ALLOWLISTS.md`).
 */
export const accountApi = {
  me: (options) => accountRequest('/me', options),
  register: (payload, options) => accountRequest('/register', { ...options, method: 'POST', body: payload }),
  signIn: (email, password, options) =>
    accountRequest('/sign-in', { ...options, method: 'POST', body: { email, password } }),
  signOut: (options) => accountRequest('/sign-out', { ...options, method: 'POST', body: {} }),
  verifyEmail: (token, options) =>
    accountRequest('/verify-email', { ...options, method: 'POST', body: { token } }),
  resendVerification: (email, options) =>
    accountRequest('/verification/resend', { ...options, method: 'POST', body: { email } }),
  forgotPassword: (email, options) =>
    accountRequest('/password/forgot', { ...options, method: 'POST', body: { email } }),
  // The password typed twice; the server refuses a missing or different second copy.
  resetPassword: (token, password, passwordConfirmation, options) =>
    accountRequest('/password/reset', {
      ...options,
      method: 'POST',
      body: { token, password, password_confirmation: passwordConfirmation },
    }),
  shipments: (params, options) => accountRequest('/shipments', { ...options, params }),
  shipment: (reference, options) =>
    accountRequest(`/shipments/${encodeURIComponent(reference)}`, options),
  // Fix pack 2: the profile (FIELD_MATRIX §3) and marketing consent (§4).
  profile: (options) => accountRequest('/profile', options),
  updateProfileDirect: (fields, options) =>
    accountRequest('/profile/direct', { ...options, method: 'POST', body: fields }),
  proposeProfileChange: (fields, options) =>
    accountRequest('/profile/proposals', { ...options, method: 'POST', body: { fields } }),
  withdrawProfileChange: (options) =>
    accountRequest('/profile/proposals/withdraw', { ...options, method: 'POST', body: {} }),
  recordMarketingChoice: (granted, options) =>
    accountRequest('/consent/marketing', { ...options, method: 'POST', body: { granted } }),
  // OD-72: which milestones are emailed, and the history of what was (or was not) sent.
  // `preferences` is any subset of `{received, in_transit, out_for_delivery, delivered}`.
  notifications: (options) => accountRequest('/notifications', options),
  updateNotificationPreferences: (preferences, options) =>
    accountRequest('/notifications/preferences', {
      ...options,
      method: 'POST',
      body: { preferences },
    }),
  // Phase 13G (OD-77): quotes Solaris Express sent, and the customer's answer. The figures
  // are the frozen customer view only; nothing about cost ever arrives here.
  quotes: (options) => accountRequest('/quotes', options),
  quote: (id, options) => accountRequest(`/quotes/${encodeURIComponent(id)}`, options),
  acceptQuote: (id, options) =>
    accountRequest(`/quotes/${encodeURIComponent(id)}/accept`, { ...options, method: 'POST', body: {} }),
  declineQuote: (id, reason, options) =>
    accountRequest(`/quotes/${encodeURIComponent(id)}/decline`, {
      ...options,
      method: 'POST',
      body: reason ? { reason } : {},
    }),
  // RC-UAT-21 Phase B (DEC-0231): the sign-in email and password. Any signed-in account.
  security: (options) => accountRequest('/security', options),
  changePassword: (currentPassword, newPassword, newPasswordConfirmation, options) =>
    accountRequest('/password/change', {
      ...options,
      method: 'POST',
      body: {
        current_password: currentPassword,
        new_password: newPassword,
        new_password_confirmation: newPasswordConfirmation,
      },
    }),
  // RC-UAT-25 item 2 (Ben, 2026-10-25): no request or cancel any more -- only Solaris Express
  // changes a sign-in email. An old link is still sent once so the server closes it.
  confirmEmailChange: (token, options) =>
    accountRequest('/email/change/confirm', { ...options, method: 'POST', body: { token } }),
};

export const ACCOUNT_API_PREFIX = ACCOUNT_API_BASE;
export const ACCOUNT_CSRF_COOKIE_NAME = ACCOUNT_CSRF_COOKIE;
export const ACCOUNT_CSRF_HEADER_NAME = ACCOUNT_CSRF_HEADER;
