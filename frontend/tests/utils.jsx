/** Shared test helpers: providers plus a stubbed fetch layer. */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { render } from '@testing-library/react';
import { vi } from 'vitest';
import { I18nProvider } from '../src/i18n/index.jsx';

export function makeQueryClient() {
  return new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 }, mutations: { retry: false } },
  });
}

export function renderWithProviders(ui, { route = '/' } = {}) {
  const queryClient = makeQueryClient();
  return {
    queryClient,
    ...render(
      <QueryClientProvider client={queryClient}>
        <I18nProvider>
          {/* The same v7 future flag `App.jsx` sets on its `BrowserRouter`, so a unit
              test routes exactly as the application does. `v7_startTransition` is left
              off for the reason given there. */}
          <MemoryRouter initialEntries={[route]} future={{ v7_relativeSplatPath: true }}>
            {ui}
          </MemoryRouter>
        </I18nProvider>
      </QueryClientProvider>,
    ),
  };
}

/**
 * Route stubbed responses by URL substring so a test declares only what it needs.
 * Anything unmatched fails loudly rather than silently returning undefined.
 */
export function stubFetch(routes) {
  const handler = vi.fn(async (input, init = {}) => {
    const url = typeof input === 'string' ? input : input.url;
    const method = (init.method || 'GET').toUpperCase();
    const match = routes.find(
      (route) => url.includes(route.path) && (route.method || 'GET') === method,
    );
    if (!match) {
      throw new Error(`No stub for ${method} ${url}`);
    }
    const status = match.status ?? 200;
    return {
      ok: status >= 200 && status < 300,
      status,
      headers: { get: () => 'application/json' },
      json: async () => (typeof match.body === 'function' ? match.body(init) : match.body),
      text: async () => JSON.stringify(match.body),
    };
  });
  vi.stubGlobal('fetch', handler);
  return handler;
}

export const customerFixture = {
  id: 1,
  public_id: 'STCA-000001',
  full_name: 'Nguyễn Thị Bích Hạnh',
  phone_entered: '+1 416 555 0142',
  email_entered: 'bich.hanh@demo.example.com',
  city: 'Toronto',
  province_state: 'ON',
  country_code: 'CA',
  preferred_language: 'vi',
  category: 'individual',
  primary_route_group: 'CAV',
  owner: { id: 2, full_name: 'Test Owner', email: 'owner@demo.example.com', role: 'operations' },
  tags: [],
  is_archived: false,
  do_not_contact: false,
  created_at: '2026-01-05T10:00:00',
  lifecycle_status: 'active',
  total_qualifying_shipments: 3,
  last_shipment_at: '2026-08-20T10:00:00',
  next_follow_up_at: null,
  has_overdue_task: false,
  has_service_issue: false,
  has_duplicate_candidates: false,
};
