/**
 * Test helpers for the public tracking shell.
 *
 * `renderPublic` mounts the real `App` at a public route, which is the point: the tests
 * then prove that the public routes render *outside* the staff providers rather than
 * proving it about a stripped-down harness that never had them.
 *
 * `stubPublicFetch` records every request so a test can assert what was *not* called --
 * `/auth/me`, any staff endpoint, any third-party host -- which is most of what the
 * privacy requirements are about.
 */

import { render } from '@testing-library/react';
import { vi } from 'vitest';
import { App } from '../src/app/App.jsx';

/**
 * Drive the real application at a URL.
 *
 * `App` uses `BrowserRouter`, so the route comes from `window.history` rather than from a
 * `MemoryRouter` prop. That is deliberate: a QR code arrives as a real URL, and this is
 * the closest a unit test gets to reproducing it.
 */
export function renderPublic(path = '/track') {
  window.history.pushState({}, '', path);
  return render(<App />);
}

/**
 * Stub `fetch` and record every call.
 *
 * Any request the routes list does not cover resolves as a network failure rather than
 * throwing, so an unexpected call surfaces as a visible error state in the page *and* in
 * `calls`, instead of as an unhandled rejection somewhere in a promise.
 */
export function stubPublicFetch(routes = []) {
  const calls = [];
  const handler = vi.fn(async (input, init = {}) => {
    const url = typeof input === 'string' ? input : input.url;
    calls.push({ url, method: (init.method || 'GET').toUpperCase(), init });
    const match = routes.find((route) => url.includes(route.path));
    if (!match) {
      throw new TypeError(`Unexpected request: ${url}`);
    }
    const status = match.status ?? 200;
    const headers = new Headers(match.headers || {});
    return {
      ok: status >= 200 && status < 300,
      status,
      headers,
      json: async () => match.body,
      text: async () => JSON.stringify(match.body),
    };
  });
  vi.stubGlobal('fetch', handler);
  return { handler, calls };
}

/** Every URL requested during the test, for the "what was not called" assertions. */
export function requestedUrls(calls) {
  return calls.map((call) => call.url);
}

/** Clear the language preference so a test starts in a known language. */
export function clearPublicStorage() {
  try {
    window.localStorage.clear();
  } catch {
    // A jsdom without storage is fine; the provider handles it.
  }
}
