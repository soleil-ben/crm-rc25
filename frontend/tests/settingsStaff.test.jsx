/**
 * Staff administration on the Settings screen (UAT-AD-03; fix pack of 2026-10-14).
 *
 * Creating and deactivating were API-only. The screen now offers both to an administrator,
 * asks before deactivating, never offers to deactivate the signed-in person, and reports
 * what the server did.
 */

import { describe, expect, it } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { SessionProvider } from '../src/app/SessionContext.jsx';
import { SettingsPage } from '../src/features/settings/SettingsPage.jsx';
import { renderWithProviders, stubFetch } from './utils.jsx';

const ADMIN = {
  user: { id: 1, full_name: 'Demo Admin', email: 'admin@demo.example.com', role: 'admin' },
  permissions: ['settings:read', 'settings:manage', 'staff:manage', 'audit:read'],
  environment: 'test',
  is_demo_environment: false,
};

const SETTINGS = {
  brand_name: 'Solaris Express',
  legal_entity_name: 'Solaris Express Inc.',
  office_timezone: 'America/Toronto',
  default_currency: 'CAD',
  tracking_base_url: 'http://localhost:5173/track',
  lifecycle_new_days: 30,
  lifecycle_active_days: 90,
  lifecycle_at_risk_days: 180,
  rule_first_delivery_follow_up_enabled: true,
  rule_first_delivery_follow_up_days: 3,
  rule_at_risk_task_enabled: true,
  rule_exception_task_enabled: true,
  is_demo_environment: false,
  lifecycle_definitions: {},
};

function member(overrides = {}) {
  return {
    id: 2,
    email: 'ops@demo.example.com',
    full_name: 'Demo Operations',
    role: 'operations',
    is_active: true,
    timezone: 'America/Toronto',
    last_login_at: '2026-10-01T09:00:00',
    created_at: '2026-01-01T09:00:00',
    ...overrides,
  };
}

function renderStaffTab({ staff = [member({ id: 1, email: 'admin@demo.example.com', full_name: 'Demo Admin', role: 'admin' }), member()] } = {}) {
  const fetchMock = stubFetch([
    { path: '/auth/me', body: ADMIN },
    { path: '/settings', body: SETTINGS },
    { path: '/staff/2', method: 'PATCH', body: (init) => ({ ...member(), ...JSON.parse(init.body) }) },
    {
      path: '/staff',
      method: 'POST',
      body: (init) => ({ ...member({ id: 9 }), ...JSON.parse(init.body), password: undefined }),
    },
    { path: '/staff', body: staff },
  ]);
  const utils = renderWithProviders(
    <SessionProvider>
      <SettingsPage />
    </SessionProvider>,
  );
  return { ...utils, fetchMock };
}

async function openStaffTab(user) {
  await screen.findByRole('heading', { name: 'Settings' });
  await user.click(screen.getByRole('tab', { name: 'Staff and permissions' }));
  return screen.findByRole('table', { name: 'Staff and permissions' });
}

describe('Settings › Staff and permissions', () => {
  it('creates a staff account through the drawer and reports it', async () => {
    const user = userEvent.setup();
    const { fetchMock } = renderStaffTab();
    await openStaffTab(user);

    await user.click(screen.getByRole('button', { name: 'Add staff account' }));
    const drawer = await screen.findByRole('dialog', { name: 'Add staff account' });
    const create = within(drawer).getByRole('button', { name: 'Create account' });
    expect(create).toBeDisabled();

    await user.type(within(drawer).getByLabelText(/^Name/), 'UAT Temp');
    await user.type(within(drawer).getByLabelText(/^Email/), 'uat.temp@example.com');
    await user.type(within(drawer).getByLabelText(/Temporary password/), 'short');
    expect(create).toBeDisabled();
    await user.clear(within(drawer).getByLabelText(/Temporary password/));
    await user.type(within(drawer).getByLabelText(/Temporary password/), 'a-long-enough-password');
    await user.selectOptions(within(drawer).getByLabelText(/^Role/), 'operations');
    expect(create).toBeEnabled();

    await user.click(create);

    await waitFor(() => {
      const call = fetchMock.mock.calls.find(
        ([url, init]) => String(url).endsWith('/api/v1/staff') && init?.method === 'POST',
      );
      expect(call).toBeTruthy();
      expect(JSON.parse(call[1].body)).toEqual({
        full_name: 'UAT Temp',
        email: 'uat.temp@example.com',
        password: 'a-long-enough-password',
        role: 'operations',
      });
    });
    expect(
      await screen.findByText('Staff account created for uat.temp@example.com.'),
    ).toBeInTheDocument();
  });

  it('deactivates another account after a confirmation, never the signed-in one', async () => {
    const user = userEvent.setup();
    const { fetchMock } = renderStaffTab();
    const table = await openStaffTab(user);

    const rows = within(table).getAllByRole('row').slice(1);
    const [adminRow, opsRow] = rows;
    expect(within(adminRow).getByText(/you/)).toBeInTheDocument();
    expect(within(adminRow).queryByRole('button', { name: 'Deactivate' })).toBeNull();

    await user.click(within(opsRow).getByRole('button', { name: 'Deactivate' }));
    const dialog = await screen.findByRole('dialog', { name: 'Deactivate this staff account?' });
    expect(within(dialog).getByText(/Every session this account holds ends immediately/)).toBeInTheDocument();
    await user.click(within(dialog).getByRole('button', { name: 'Deactivate' }));

    await waitFor(() => {
      const call = fetchMock.mock.calls.find(
        ([url, init]) => String(url).includes('/staff/2') && init?.method === 'PATCH',
      );
      expect(call).toBeTruthy();
      expect(JSON.parse(call[1].body)).toEqual({ is_active: false });
    });
    expect(
      await screen.findByText('ops@demo.example.com has been deactivated and signed out everywhere.'),
    ).toBeInTheDocument();
  });

  it('offers to reactivate a deactivated account', async () => {
    const user = userEvent.setup();
    renderStaffTab({
      staff: [
        member({ id: 1, email: 'admin@demo.example.com', full_name: 'Demo Admin', role: 'admin' }),
        member({ is_active: false }),
      ],
    });
    const table = await openStaffTab(user);
    expect(within(table).getByText('Deactivated')).toBeInTheDocument();
    expect(within(table).getByRole('button', { name: 'Reactivate' })).toBeInTheDocument();
  });
});
