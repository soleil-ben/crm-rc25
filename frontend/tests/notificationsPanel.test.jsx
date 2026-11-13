/**
 * Settings → Customer notifications (Phase 13F, OD-72) -- independent tester's suite.
 *
 * The tab is offered only to a role holding both shipment:read and customer:read; it lists
 * each outbox row with its status and, for a skipped one, why; and Retry appears only on a
 * failed row and only for a role holding tracking:write. Mocked API throughout.
 */

import { describe, expect, it } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { SessionProvider } from '../src/app/SessionContext.jsx';
import { SettingsPage } from '../src/features/settings/SettingsPage.jsx';
import { renderWithProviders, stubFetch } from './utils.jsx';

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

function session(permissions) {
  return {
    user: { id: 3, full_name: 'Demo Staff', email: 'staff@demo.example.com', role: 'operations' },
    permissions: ['settings:read', ...permissions],
    environment: 'test',
    is_demo_environment: false,
  };
}

function row(overrides = {}) {
  return {
    id: 1,
    shipment_id: 11,
    shipment_reference: 'SE-VCA-000011',
    customer_id: 5,
    customer_reference: 'STCA-000005',
    customer_name: 'Nguyễn Văn An',
    milestone: 'received',
    channel: 'email',
    language: 'vi',
    template_key: 'notify.received.vi',
    status: 'sent',
    skip_reason: null,
    transport: 'capture',
    attempts: 1,
    last_error: null,
    created_at: '2026-10-20T09:00:00',
    processed_at: '2026-10-20T09:00:01',
    ...overrides,
  };
}

const ROWS = [
  row({ id: 1, status: 'sent' }),
  row({ id: 2, shipment_id: 12, shipment_reference: 'SE-VCA-000012', milestone: 'in_transit', status: 'skipped', skip_reason: 'opted_out', transport: null }),
  row({ id: 3, shipment_id: 13, shipment_reference: 'SE-VCA-000013', milestone: 'out_for_delivery', status: 'skipped', skip_reason: 'suppressed', transport: null }),
  row({ id: 4, shipment_id: 14, shipment_reference: 'SE-VCA-000014', milestone: 'delivered', status: 'skipped', skip_reason: 'no_email', transport: null, language: 'en' }),
  row({ id: 5, shipment_id: 15, shipment_reference: 'SE-VCA-000015', milestone: 'received', status: 'skipped', skip_reason: 'voided', transport: null }),
  row({ id: 6, shipment_id: 16, shipment_reference: 'SE-VCA-000016', milestone: 'in_transit', status: 'failed', attempts: 3, last_error: 'OSError', transport: null }),
  row({ id: 7, shipment_id: 17, shipment_reference: 'SE-VCA-000017', milestone: 'received', status: 'recorded', transport: 'null' }),
  row({ id: 8, shipment_id: 18, shipment_reference: 'SE-VCA-000018', milestone: 'delivered', status: 'queued', attempts: 0, transport: null, processed_at: null }),
];

function renderSettings(permissions, { rows = ROWS } = {}) {
  let retried = null;
  const fetchMock = stubFetch([
    { path: '/auth/me', body: session(permissions) },
    { path: '/settings', body: SETTINGS },
    {
      path: '/notifications/6/retry',
      method: 'POST',
      body: () => {
        retried = 6;
        return { ...ROWS[5], status: 'sent', attempts: 1, transport: 'capture', last_error: null };
      },
    },
    { path: '/notifications', body: { items: rows, total: rows.length } },
  ]);
  const utils = renderWithProviders(
    <SessionProvider>
      <SettingsPage />
    </SessionProvider>,
  );
  return { ...utils, fetchMock, wasRetried: () => retried };
}

async function openTab(user) {
  await screen.findByRole('heading', { name: 'Settings' });
  await user.click(screen.getByRole('tab', { name: 'Customer notifications' }));
  return screen.findByRole('table');
}

function rowFor(table, reference) {
  return within(table).getByRole('link', { name: reference }).closest('tr');
}

describe('Settings › Customer notifications: who sees the tab', () => {
  it.each([
    [['shipment:read']],
    [['customer:read']],
    [['tracking:write']],
    [[]],
  ])('is hidden without both shipment:read and customer:read (%j)', async (permissions) => {
    const { fetchMock } = renderSettings(permissions);
    await screen.findByRole('heading', { name: 'Settings' });
    await waitFor(() => expect(screen.getAllByRole('tab').length).toBeGreaterThan(0));
    expect(screen.queryByRole('tab', { name: 'Customer notifications' })).toBeNull();
    const asked = fetchMock.mock.calls.map(([url]) => String(url));
    expect(asked.some((url) => url.includes('/notifications'))).toBe(false);
  });

  it('is offered with shipment:read and customer:read', async () => {
    renderSettings(['shipment:read', 'customer:read']);
    await screen.findByRole('heading', { name: 'Settings' });
    expect(await screen.findByRole('tab', { name: 'Customer notifications' })).toBeInTheDocument();
  });
});

describe('Settings › Customer notifications: the list', () => {
  it('shows every row with its milestone, language, status and skip reason', async () => {
    const user = userEvent.setup();
    renderSettings(['shipment:read', 'customer:read']);
    const table = await openTab(user);
    expect(screen.getByText(/Test capture only/)).toBeInTheDocument();

    const sent = rowFor(table, 'SE-VCA-000011');
    expect(within(sent).getByText('Captured (test)')).toBeInTheDocument();
    expect(within(sent).getByText('Received')).toBeInTheDocument();
    expect(within(sent).getByText('VI')).toBeInTheDocument();
    expect(within(sent).getByText('Nguyễn Văn An')).toBeInTheDocument();
    expect(within(sent).getByRole('link', { name: 'SE-VCA-000011' })).toHaveAttribute('href', '/shipments/11');

    const reasons = {
      'SE-VCA-000012': 'customer turned it off',
      'SE-VCA-000013': 'address suppressed',
      'SE-VCA-000014': 'no email address',
      'SE-VCA-000015': 'withdrawn (event voided)',
    };
    for (const [reference, reason] of Object.entries(reasons)) {
      const tr = rowFor(table, reference);
      expect(within(tr).getByText('Skipped')).toBeInTheDocument();
      expect(within(tr).getByText(new RegExp(reason.replace(/[()]/g, '\\$&')))).toBeInTheDocument();
    }
    expect(within(rowFor(table, 'SE-VCA-000014')).getByText('EN')).toBeInTheDocument();
    expect(within(rowFor(table, 'SE-VCA-000016')).getByText('Failed')).toBeInTheDocument();
    expect(within(rowFor(table, 'SE-VCA-000017')).getByText('Recorded, not sent')).toBeInTheDocument();
    expect(within(rowFor(table, 'SE-VCA-000018')).getByText('Queued')).toBeInTheDocument();
    // Milestone names, translated.
    expect(within(rowFor(table, 'SE-VCA-000013')).getByText('Out for delivery')).toBeInTheDocument();
    expect(within(rowFor(table, 'SE-VCA-000014')).getByText('Delivered')).toBeInTheDocument();
    expect(within(rowFor(table, 'SE-VCA-000012')).getByText('In transit')).toBeInTheDocument();
    // No raw internal keys on screen.
    expect(table.textContent).not.toMatch(/opted_out|no_email|notify\.|OSError/);
  });

  it('shows an empty state when nothing is queued', async () => {
    const user = userEvent.setup();
    renderSettings(['shipment:read', 'customer:read'], { rows: [] });
    await screen.findByRole('heading', { name: 'Settings' });
    await user.click(screen.getByRole('tab', { name: 'Customer notifications' }));
    expect(await screen.findByText('No notifications yet')).toBeInTheDocument();
  });
});

describe('Settings › Customer notifications: retry', () => {
  it('offers Retry on the failed row only, to a tracking writer, and sends it', async () => {
    const user = userEvent.setup();
    const { fetchMock, wasRetried } = renderSettings(['shipment:read', 'customer:read', 'tracking:write']);
    const table = await openTab(user);
    const buttons = within(table).getAllByRole('button', { name: /Retry/ });
    expect(buttons).toHaveLength(1);
    const failed = rowFor(table, 'SE-VCA-000016');
    const retry = within(failed).getByRole('button', { name: /Retry/ });
    for (const reference of ['SE-VCA-000011', 'SE-VCA-000012', 'SE-VCA-000017', 'SE-VCA-000018']) {
      expect(within(rowFor(table, reference)).queryByRole('button', { name: /Retry/ })).toBeNull();
    }
    await user.click(retry);
    await waitFor(() => expect(wasRetried()).toBe(6));
    const post = fetchMock.mock.calls.find(
      ([url, init]) => String(url).includes('/notifications/6/retry') && (init?.method || 'GET') === 'POST',
    );
    expect(post).toBeTruthy();
  });

  it('offers no Retry at all without tracking:write', async () => {
    const user = userEvent.setup();
    renderSettings(['shipment:read', 'customer:read']);
    const table = await openTab(user);
    expect(within(rowFor(table, 'SE-VCA-000016')).getByText('Failed')).toBeInTheDocument();
    expect(within(table).queryByRole('button', { name: /Retry/ })).toBeNull();
  });
});
