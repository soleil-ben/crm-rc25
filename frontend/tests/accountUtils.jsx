/**
 * Test helpers for the Customer Account shell.
 *
 * `renderAccount` mounts the **real `App`** at an `/account/...` URL rather than a
 * stripped-down harness. That is the whole point of these tests: they have to prove that
 * the Customer Account routes render *outside* the staff providers, and a harness that
 * never had those providers proves nothing about the application that does.
 *
 * `stubAccountFetch` records every request so a test can assert what was **not** called —
 * `/auth/me`, any `/api/v1` staff path, any public-tracking path, any third-party host.
 * That negative is most of what the boundary requirements are about.
 */

import { render, screen, within } from '@testing-library/react';
import { vi } from 'vitest';
import { App } from '../src/app/App.jsx';
import { AccountI18nProvider } from '../src/account/i18n.jsx';

/**
 * Drive the real application at a URL, the way a browser would arrive at one.
 *
 * In English by default: these suites predate OD-71 and assert the English copy. The outer
 * provider pins the language and the one `AccountApp` mounts defers to it. Pass
 * `{ locale: null }` to get the application's own default (Vietnamese), or `'vi'`.
 */
export function renderAccount(path = '/account/sign-in', { locale = 'en' } = {}) {
  window.history.pushState({}, '', path);
  if (!locale) return render(<App />);
  return render(
    <AccountI18nProvider initialLocale={locale}>
      <App />
    </AccountI18nProvider>,
  );
}

/**
 * Stub `fetch` and record every call.
 *
 * An unmatched request throws a `TypeError`, which is what a real network failure looks
 * like to `fetch`, so an unexpected call surfaces as a visible error state in the page
 * *and* in `calls` rather than as an unhandled rejection.
 */
export function stubAccountFetch(routes = []) {
  const calls = [];
  const handler = vi.fn(async (input, init = {}) => {
    const url = typeof input === 'string' ? input : input.url;
    const method = (init.method || 'GET').toUpperCase();
    calls.push({ url, method, init, headers: init.headers || {} });
    const match = routes.find(
      (route) => url.includes(route.path) && (route.method || 'GET') === method,
    );
    if (!match) {
      throw new TypeError(`Unexpected request: ${method} ${url}`);
    }
    const status = match.status ?? 200;
    return {
      ok: status >= 200 && status < 300,
      status,
      headers: new Headers(match.headers || {}),
      json: async () => (typeof match.body === 'function' ? match.body(init) : match.body),
      text: async () => JSON.stringify(match.body),
    };
  });
  vi.stubGlobal('fetch', handler);
  return { handler, calls };
}

export function requestedUrls(calls) {
  return calls.map((call) => call.url);
}

/** A `/account/me` body. Override any field; the defaults are an approved, linked account. */
export function meFixture(overrides = {}) {
  return {
    account_reference: 'CA-7K9D2M4R',
    status: 'active',
    email_verified: true,
    linked: true,
    shipment_history_available: true,
    preferred_language: 'en',
    status_reason_code: null,
    has_pending_proposal: false,
    ...overrides,
  };
}

/** One `AccountShipmentListItem`. Exactly the 18 allowlisted fields, and no more. */
export function listItemFixture(overrides = {}) {
  return {
    shipment_reference: 'SX-CAV-7K9D2M4R8T6W',
    booking_reference: null,
    booked_at: '2026-09-01T14:30:00+00:00',
    route_group: 'CAV',
    route_label: 'Canada to Vietnam',
    origin_city: 'Mississauga',
    origin_country_code: 'CA',
    destination_city: 'Ho Chi Minh City',
    destination_country_code: 'VN',
    status: 'in_transit',
    status_label: 'In transit',
    package_count_active: 2,
    package_count_cancelled: 0,
    delivered_at: null,
    cancelled_at: null,
    last_public_update_at: '2026-09-10T09:00:00+00:00',
    is_cancelled: false,
    is_rebooked: false,
    ...overrides,
  };
}

export function listPageFixture(items = [listItemFixture()], overrides = {}) {
  return {
    items,
    total: items.length,
    limit: 20,
    offset: 0,
    timezone: 'America/Toronto',
    ...overrides,
  };
}

/** One `AccountShipmentDetail`. Exactly the 25 allowlisted fields (DEC-0163). */
export function detailFixture(overrides = {}) {
  return {
    shipment_reference: 'SX-CAV-7K9D2M4R8T6W',
    booking_reference: null,
    matched_reference_type: 'shipment',
    selected_package_reference: null,
    route_group: 'CAV',
    route_label: 'Canada to Vietnam',
    origin: { city: 'Mississauga', country_code: 'CA', country_label: 'Canada' },
    destination: { city: 'Ho Chi Minh City', country_code: 'VN', country_label: 'Vietnam' },
    status: 'in_transit',
    status_label: 'In transit',
    package_count_active: 2,
    package_count_cancelled: 0,
    package_count_delivered: 0,
    progress_summary: '0 of 2 packages delivered',
    packages: [
      {
        package_reference: 'SX-CAV-7K9D2M4R8T6W-01',
        status: 'in_transit',
        status_label: 'In transit',
        is_selected: false,
        is_cancelled: false,
        delivered_at: null,
      },
    ],
    estimated_delivery_at: '2026-09-25T00:00:00+00:00',
    delivered_at: null,
    cancelled_at: null,
    timeline: [
      {
        status: 'in_transit',
        status_label: 'In transit',
        event_type: 'departed_origin',
        scope: 'shipment',
        message: 'Your shipment has left the Solaris Express facility.',
        message_template_key: 'departed_origin',
        occurred_at: '2026-09-05T11:00:00+00:00',
        location: { city: 'Mississauga', country_code: 'CA', country_label: 'Canada' },
        package_references: [],
        source_label: 'manual_update',
      },
    ],
    tracking_state: 'manual_updates',
    last_public_update_at: '2026-09-10T09:00:00+00:00',
    carrier_link: null,
    data_mode: 'live',
    help_url: null,
    timezone: 'America/Toronto',
    ...overrides,
  };
}

/** Clear both browser stores so a test starts clean and can assert they stay empty. */
export function clearBrowserStorage() {
  try {
    window.localStorage.clear();
    window.sessionStorage.clear();
  } catch {
    // A jsdom without storage is fine: nothing on this surface uses it.
  }
}

/**
 * Fill the registration address's required parts (UAT round 9). The country stays Canada;
 * the billing box ticks itself once the street is typed, so no billing part is needed.
 */
export async function fillRegistrationAddress(user) {
  const address = within(screen.getByRole('group', { name: 'Address' }));
  await user.type(address.getByLabelText(/^Address line 1/), '4120 Dixie Road');
  await user.type(address.getByLabelText(/^City/), 'Mississauga');
  await user.type(address.getByLabelText(/^Province or state/), 'ON');
  await user.type(address.getByLabelText(/^Postal code/), 'L4W 1V2');
}
