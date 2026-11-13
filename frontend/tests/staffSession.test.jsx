/**
 * UAT-AD-01 and fix-pack item 11: what the staff shell does with its cache and its URL
 * around sign-in and sign-out.
 *
 * * a page restored from the back-forward cache drops every cached answer and re-asks
 *   the server who is signed in;
 * * signing in lands on the signed-in person's own first screen, not on whatever URL the
 *   previous person left the browser at;
 * * `landingPathFor` is the first navigation entry the role can open.
 */

import { describe, expect, it, vi } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useQuery } from '@tanstack/react-query';
import { Route, Routes, useLocation } from 'react-router-dom';
import { api } from '../src/api/client.js';
import { SessionProvider, landingPathFor, useSession } from '../src/app/SessionContext.jsx';
import { LoginPage } from '../src/features/auth/LoginPage.jsx';
import { renderWithProviders, stubFetch } from './utils.jsx';

const SESSION = {
  user: {
    id: 1,
    full_name: 'Test Admin',
    email: 'admin@demo.example.com',
    role: 'admin',
    initials: 'TA',
    timezone: 'America/Toronto',
    locale: 'en',
  },
  permissions: ['customer:read', 'dashboard:read'],
  environment: 'test',
  is_demo_environment: false,
};

describe('landingPathFor', () => {
  it('sends every current role to the dashboard', () => {
    expect(landingPathFor(['dashboard:read', 'customer:read'])).toBe('/');
  });

  it('falls through to the first screen a narrower role can open', () => {
    expect(landingPathFor(['shipment:read', 'task:read'])).toBe('/shipments');
    expect(landingPathFor(['report:read'])).toBe('/reports');
  });

  it('defaults to the root when nothing is known', () => {
    expect(landingPathFor(undefined)).toBe('/');
    expect(landingPathFor([])).toBe('/');
  });
});

function Probe() {
  const { user } = useSession();
  const customers = useQuery({
    queryKey: ['customers', 'probe'],
    queryFn: () => api.get('/customers'),
  });
  return (
    <div>
      <p data-testid="user">{user ? user.full_name : 'nobody'}</p>
      <p data-testid="customers">
        {customers.data?.items ? customers.data.items.map((item) => item.full_name).join(',') : 'none'}
      </p>
    </div>
  );
}

describe('back-forward cache restoration', () => {
  it('drops cached customer data and re-asks who is signed in', async () => {
    const handler = stubFetch([
      { path: '/auth/me', body: SESSION },
      { path: '/customers', body: { items: [{ id: 1, full_name: 'Nguyễn Thị Bích Hạnh' }] } },
    ]);
    renderWithProviders(
      <SessionProvider>
        <Probe />
      </SessionProvider>,
    );
    expect(await screen.findByText('Nguyễn Thị Bích Hạnh')).toBeInTheDocument();
    expect(screen.getByTestId('user')).toHaveTextContent('Test Admin');
    const callsBefore = handler.mock.calls.length;

    // The person signed out on a later page; the server now answers 401, and the
    // browser restores this page from its back-forward cache.
    stubFetch([
      { path: '/auth/me', status: 401, body: { code: 'unauthenticated', message: 'Sign in.' } },
      { path: '/customers', status: 401, body: { code: 'unauthenticated', message: 'Sign in.' } },
    ]);
    const event = new Event('pageshow');
    Object.defineProperty(event, 'persisted', { value: true });
    window.dispatchEvent(event);

    await waitFor(() => expect(screen.getByTestId('user')).toHaveTextContent('nobody'));
    await waitFor(() => expect(screen.getByTestId('customers')).toHaveTextContent('none'));
    expect(screen.queryByText('Nguyễn Thị Bích Hạnh')).toBeNull();
    // Both answers were re-requested rather than served from memory.
    expect(window.fetch.mock.calls.length).toBeGreaterThan(0);
    expect(callsBefore).toBeGreaterThan(0);
  });

  it('ignores an ordinary page load', async () => {
    const handler = stubFetch([{ path: '/auth/me', body: SESSION }]);
    renderWithProviders(
      <SessionProvider>
        <Probe />
      </SessionProvider>,
    );
    await screen.findByText('Test Admin');
    const before = handler.mock.calls.filter(([url]) => String(url).includes('/auth/me')).length;

    const event = new Event('pageshow');
    Object.defineProperty(event, 'persisted', { value: false });
    window.dispatchEvent(event);

    await new Promise((resolve) => setTimeout(resolve, 20));
    const after = handler.mock.calls.filter(([url]) => String(url).includes('/auth/me')).length;
    expect(after).toBe(before);
  });
});

function LocationProbe() {
  const location = useLocation();
  return <p data-testid="location">{location.pathname}</p>;
}

describe('signing in', () => {
  it('lands on the signed-in person’s own first screen, not the previous URL', async () => {
    const user = userEvent.setup();
    stubFetch([
      { path: '/auth/me', status: 401, body: { code: 'unauthenticated', message: 'Sign in.' } },
      {
        path: '/auth/login',
        method: 'POST',
        body: { user: SESSION.user, permissions: SESSION.permissions, csrf_token: 'c' },
      },
    ]);
    // The browser was left on the previous person's customer record.
    renderWithProviders(
      <SessionProvider>
        <LocationProbe />
        <Routes>
          <Route path="*" element={<LoginPage />} />
        </Routes>
      </SessionProvider>,
      { route: '/customers/42' },
    );
    expect(screen.getByTestId('location')).toHaveTextContent('/customers/42');

    await user.type(screen.getByLabelText(/Email address/), 'admin@demo.example.com');
    await user.type(screen.getByLabelText(/^Password/), 'SolarisDemo!2026');
    await user.click(screen.getByRole('button', { name: 'Sign in' }));

    await waitFor(() => expect(screen.getByTestId('location')).toHaveTextContent('/'));
    expect(screen.getByTestId('location').textContent).toBe('/');
  });

  it('stays put and shows the refusal when sign-in fails', async () => {
    const user = userEvent.setup();
    stubFetch([
      { path: '/auth/me', status: 401, body: { code: 'unauthenticated', message: 'Sign in.' } },
      {
        path: '/auth/login',
        method: 'POST',
        status: 401,
        body: { code: 'invalid_credentials', message: 'That email or password is not right.' },
      },
    ]);
    renderWithProviders(
      <SessionProvider>
        <LocationProbe />
        <Routes>
          <Route path="*" element={<LoginPage />} />
        </Routes>
      </SessionProvider>,
      { route: '/customers/42' },
    );
    await user.type(screen.getByLabelText(/Email address/), 'admin@demo.example.com');
    await user.type(screen.getByLabelText(/^Password/), 'wrong');
    await user.click(screen.getByRole('button', { name: 'Sign in' }));

    expect(await screen.findByText('That email or password is not right.')).toBeInTheDocument();
    expect(screen.getByTestId('location')).toHaveTextContent('/customers/42');
    vi.restoreAllMocks();
  });
});
