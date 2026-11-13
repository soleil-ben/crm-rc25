/**
 * Single documented access layer for the FastAPI REST API (Design.md section 18).
 *
 * The staff session lives in an HTTP-only cookie the browser sends automatically. The
 * readable CSRF cookie is echoed in a header on every state-changing request. No staff
 * token is ever written to localStorage (CRM.md section 3).
 */

const API_BASE = '/api/v1';
const CSRF_COOKIE = 'solaris_csrf';
const CSRF_HEADER = 'X-CSRF-Token';

export class ApiError extends Error {
  constructor({ status, code, message, field, detail }) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
    this.field = field ?? null;
    this.detail = detail ?? {};
  }

  get isUnauthenticated() {
    return this.status === 401;
  }

  get isPermissionDenied() {
    return this.status === 403;
  }

  get isNotFound() {
    return this.status === 404;
  }

  get isRateLimited() {
    return this.status === 429;
  }

  /**
   * The fields a FastAPI request-validation 422 names, by the last segment of each `loc`.
   * Empty for a domain error, whose message is already written for a person. A form uses
   * this to put its own wording beside the field instead of pydantic's
   * "String should have at least 1 character".
   */
  get invalidFields() {
    if (this.status !== 422 || !Array.isArray(this.detail)) return [];
    return this.detail
      .map((item) => (Array.isArray(item?.loc) ? item.loc[item.loc.length - 1] : null))
      .filter((name) => typeof name === 'string');
  }
}

function readCsrfToken() {
  const match = document.cookie
    .split('; ')
    .find((entry) => entry.startsWith(`${CSRF_COOKIE}=`));
  return match ? decodeURIComponent(match.slice(CSRF_COOKIE.length + 1)) : null;
}

function buildUrl(path, params) {
  const url = path.startsWith('http') ? path : `${API_BASE}${path}`;
  if (!params) return url;
  const search = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value === undefined || value === null || value === '') return;
    if (Array.isArray(value)) {
      value.forEach((item) => {
        if (item !== undefined && item !== null && item !== '') search.append(key, item);
      });
    } else {
      search.append(key, value);
    }
  });
  const query = search.toString();
  return query ? `${url}?${query}` : url;
}

async function toApiError(response) {
  let payload = {};
  try {
    payload = await response.json();
  } catch {
    payload = {};
  }
  // FastAPI request-validation failures use `detail`; domain errors use our envelope.
  let message = payload.message;
  if (!message && Array.isArray(payload.detail)) {
    message = payload.detail.map((item) => item.msg).join('; ');
  }
  return new ApiError({
    status: response.status,
    code: payload.code || 'request_failed',
    message: message || defaultMessageFor(response.status),
    field: payload.field,
    detail: payload.detail,
  });
}

function defaultMessageFor(status) {
  switch (status) {
    case 401:
      return 'Your session has ended. Sign in again to continue.';
    case 403:
      return 'Your role does not allow this action.';
    case 404:
      return 'That record could not be found.';
    case 429:
      return 'Too many attempts. Wait a moment and try again.';
    case 503:
      return 'The service is temporarily unavailable.';
    default:
      return 'Something went wrong. Try again, or contact an administrator if it continues.';
  }
}

export async function request(path, { method = 'GET', params, body, signal } = {}) {
  const headers = { Accept: 'application/json' };
  if (body !== undefined) headers['Content-Type'] = 'application/json';

  if (method !== 'GET' && method !== 'HEAD') {
    const token = readCsrfToken();
    if (token) headers[CSRF_HEADER] = token;
  }

  let response;
  try {
    response = await fetch(buildUrl(path, params), {
      method,
      headers,
      credentials: 'same-origin',
      body: body === undefined ? undefined : JSON.stringify(body),
      signal,
    });
  } catch (error) {
    if (error.name === 'AbortError') throw error;
    throw new ApiError({
      status: 0,
      code: 'network_error',
      message: 'Could not reach the Solaris CRM server. Check your connection and try again.',
    });
  }

  if (!response.ok) throw await toApiError(response);
  if (response.status === 204) return null;

  const contentType = response.headers.get('content-type') || '';
  if (contentType.includes('application/json')) return response.json();
  return response.text();
}

export const api = {
  get: (path, params, options) => request(path, { ...options, method: 'GET', params }),
  post: (path, body, options) => request(path, { ...options, method: 'POST', body }),
  patch: (path, body, options) => request(path, { ...options, method: 'PATCH', body }),
  delete: (path, options) => request(path, { ...options, method: 'DELETE' }),
};

/**
 * Multipart upload, for the CSV import.
 *
 * `Content-Type` is deliberately not set: the browser has to generate it so it can append
 * the multipart boundary. Setting it by hand produces a body the server cannot parse.
 * Everything else matches `request` — same-origin credentials, the CSRF header, and the
 * same error envelope.
 */
export async function upload(path, formData, { signal } = {}) {
  const headers = { Accept: 'application/json' };
  const token = readCsrfToken();
  if (token) headers[CSRF_HEADER] = token;

  let response;
  try {
    response = await fetch(buildUrl(path), {
      method: 'POST',
      headers,
      credentials: 'same-origin',
      body: formData,
      signal,
    });
  } catch (error) {
    if (error.name === 'AbortError') throw error;
    throw new ApiError({
      status: 0,
      code: 'network_error',
      message: 'Could not reach the Solaris CRM server. Check your connection and try again.',
    });
  }

  if (!response.ok) throw await toApiError(response);
  return response.json();
}

/**
 * Fetch a file (a PDF) as a blob, with the same credentials and error envelope as `request`,
 * so a refusal (a stale draft revision, 409) reaches the screen as a message rather than as
 * a JSON page in a new tab. Returns `{ blob, filename }`.
 */
export async function downloadBlob(path, params) {
  let response;
  try {
    response = await fetch(buildUrl(path, params), { credentials: 'same-origin' });
  } catch {
    throw new ApiError({
      status: 0,
      code: 'network_error',
      message: 'Could not reach the Solaris CRM server. Check your connection and try again.',
    });
  }
  if (!response.ok) throw await toApiError(response);
  const disposition = response.headers.get('content-disposition') || '';
  const match = disposition.match(/filename="?([^";]+)"?/);
  return { blob: await response.blob(), filename: match ? match[1] : 'document.pdf' };
}

/** Hand a downloaded blob to the browser as a file. */
export function saveBlob({ blob, filename }) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

/** Absolute URL for a download the browser should open directly (CSV export). */
export function downloadUrl(path, params) {
  return buildUrl(path, params);
}
