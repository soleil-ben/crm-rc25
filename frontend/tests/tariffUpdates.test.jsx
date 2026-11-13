/**
 * Settings → Tariff updates (Phase 13H, OD-76). Mocked API throughout.
 *
 * The tab is offered only with tariff:manage; the intake list shows each rate email with
 * its status; a draft version shows its diff; Approve, Reject and Release are enabled only
 * for an approver (the server decides; the screen only reflects it); the intake settings
 * save as lists. Demo addresses only.
 */

import { describe, expect, it } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { SessionProvider } from '../src/app/SessionContext.jsx';
import { SettingsPage } from '../src/features/settings/SettingsPage.jsx';
import { render } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { I18nProvider } from '../src/i18n/index.jsx';
import { TariffUpdatesPanel } from '../src/features/settings/TariffUpdatesPanel.jsx';
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
    user: { id: 1, full_name: 'Demo Admin', email: 'admin@demo.example.com', role: 'admin' },
    permissions: ['settings:read', ...permissions],
    environment: 'test',
    is_demo_environment: false,
  };
}

function intake(overrides = {}) {
  return {
    id: 1,
    message_id: '<rates-1@vendor.example.com>',
    sender: 'rates@vendor.example.com',
    subject: 'Kango Canada rates',
    received_at: '2026-10-20T09:00:00',
    source: 'upload',
    attachment_name: 'rates.xlsx',
    attachment_sha256: 'a'.repeat(64),
    status: 'imported',
    tariff_version_id: 7,
    tariff_version_public_id: 'TRF-000007',
    tariff_version_status: 'draft',
    error: null,
    reviewed_at: null,
    review_note: null,
    created_at: '2026-10-20T09:00:01',
    ...overrides,
  };
}

const ROWS = [
  intake(),
  intake({
    id: 2,
    message_id: '<other@unknown.example.com>',
    sender: 'someone@unknown.example.com',
    subject: 'New prices',
    status: 'held_sender',
    tariff_version_id: null,
    tariff_version_public_id: null,
    tariff_version_status: null,
    error: 'The sender is not on the allowed list.',
  }),
];

const DIFF = {
  version_id: 7,
  version_public_id: 'TRF-000007',
  version_status: 'draft',
  against_version_id: 3,
  against_version_public_id: 'TRF-000003',
  mode: 'air',
  products_added: [],
  products_removed: [],
  summary: {
    brackets_changed: 1,
    brackets_added: 0,
    brackets_removed: 0,
    surcharges_changed: 0,
    surcharges_added: 0,
    surcharges_removed: 0,
  },
  truncated: false,
  max_entries: 300,
  counts: { version: {}, against: {} },
  brackets_changed: [
    {
      origin: 'HCM',
      product_code: 'AIR-CAD',
      kind: 'per_kg',
      zone: 2,
      label: '21-44',
      old_price_vnd: '250000.00',
      new_price_vnd: '251000.00',
    },
  ],
  brackets_added: [],
  brackets_removed: [],
  surcharges_changed: [],
  surcharges_added: [],
  surcharges_removed: [],
};

const INTAKE_SETTINGS = {
  mailbox_address: 'intake@demo.example.com',
  approver_emails: ['admin@demo.example.com'],
  allowed_sender_domains: [],
  updated_at: null,
  is_default: true,
};

function renderSettings(permissions, { approver = true } = {}) {
  const calls = { approved: false, rejected: null, released: null, saved: null };
  const fetchMock = stubFetch([
    { path: '/auth/me', body: session(permissions) },
    {
      path: '/tariffs/intake/settings',
      method: 'PATCH',
      body: (init) => {
        calls.saved = JSON.parse(init.body);
        return { ...INTAKE_SETTINGS, ...calls.saved, is_default: false };
      },
    },
    { path: '/tariffs/intake/settings', body: INTAKE_SETTINGS },
    {
      path: '/tariffs/intake/2/release',
      method: 'POST',
      body: () => {
        calls.released = 2;
        return { ...ROWS[1], status: 'imported' };
      },
    },
    {
      path: '/tariffs/versions/7/approve',
      method: 'POST',
      body: () => {
        calls.approved = true;
        return { id: 7, status: 'active' };
      },
    },
    {
      path: '/tariffs/versions/7/reject',
      method: 'POST',
      body: (init) => {
        calls.rejected = JSON.parse(init.body).reason;
        return { id: 7, status: 'draft' };
      },
    },
    { path: '/tariffs/versions/7/diff', body: DIFF },
    { path: '/tariffs/intake', body: { items: ROWS, total: ROWS.length, viewer_is_approver: approver } },
    // Last: '/settings' is also a substring of the intake settings path.
    { path: '/settings', body: SETTINGS },
  ]);
  renderWithProviders(
    <SessionProvider>
      <SettingsPage />
    </SessionProvider>,
  );
  return { fetchMock, calls };
}

async function openTab(user) {
  await screen.findByRole('heading', { name: 'Settings' });
  await user.click(screen.getByRole('tab', { name: 'Tariff updates' }));
  return screen.findByRole('region', { name: 'Rate emails' });
}

describe('Settings › Tariff updates', () => {
  it('is hidden without tariff:manage and asks nothing of the intake API', async () => {
    const { fetchMock } = renderSettings(['tariff:read']);
    await screen.findByRole('heading', { name: 'Settings' });
    await waitFor(() => expect(screen.getAllByRole('tab').length).toBeGreaterThan(0));
    expect(screen.queryByRole('tab', { name: 'Tariff updates' })).toBeNull();
    expect(fetchMock.mock.calls.some(([url]) => String(url).includes('/tariffs/intake'))).toBe(false);
  });

  it('lists rate emails with their status and shows the pending version diff', async () => {
    const user = userEvent.setup();
    renderSettings(['tariff:read', 'tariff:manage', 'settings:manage']);
    const region = await openTab(user);
    expect(screen.getByText(/No mailbox is connected/)).toBeInTheDocument();
    const rows = within(region).getAllByRole('row');
    expect(within(rows[1]).getByText('Imported (draft)')).toBeInTheDocument();
    expect(within(rows[1]).getByText('TRF-000007 (draft)')).toBeInTheDocument();
    expect(within(rows[2]).getByText('Held: unknown sender')).toBeInTheDocument();
    expect(region.textContent).not.toMatch(/held_sender|imported\b/);

    expect(await screen.findByText(/Compared with the active version TRF-000003/)).toBeInTheDocument();
    const diff = screen.getByRole('region', { name: 'Prices changed' });
    expect(within(diff).getByText('21-44 (per_kg)')).toBeInTheDocument();
    expect(within(diff).getByText('250,000')).toBeInTheDocument();
    expect(within(diff).getByText('251,000')).toBeInTheDocument();
  });

  it('lets an approver approve, reject with a reason, and release a held email', async () => {
    const user = userEvent.setup();
    const { calls } = renderSettings(['tariff:read', 'tariff:manage', 'settings:manage']);
    const region = await openTab(user);
    await screen.findByText(/Compared with the active version/);

    const reject = screen.getByRole('button', { name: 'Reject' });
    expect(reject).toBeDisabled(); // a reason is required first
    await user.type(screen.getByLabelText(/Reason for rejecting/), 'Prices look wrong');
    await user.click(reject);
    await waitFor(() => expect(calls.rejected).toBe('Prices look wrong'));
    expect(await screen.findByText(/stays a draft/)).toBeInTheDocument();

    await user.click(within(region).getByRole('button', { name: 'Release: New prices' }));
    await waitFor(() => expect(calls.released).toBe(2));
  });

  it('approves and reports the activation', async () => {
    const user = userEvent.setup();
    const { calls } = renderSettings(['tariff:read', 'tariff:manage', 'settings:manage']);
    await openTab(user);
    await screen.findByText(/Compared with the active version/);
    await user.click(screen.getByRole('button', { name: 'Approve and activate' }));
    // A confirmation names the version and the change counts before anything is sent.
    const dialog = await screen.findByRole('dialog', { name: 'Approve and activate TRF-000007' });
    expect(within(dialog).getByText(/replaces the active version TRF-000003/)).toBeInTheDocument();
    expect(within(dialog).getByText('Prices changed: 1')).toBeInTheDocument();
    expect(calls.approved).toBe(false);
    await user.click(within(dialog).getByRole('button', { name: 'Yes, approve and activate' }));
    await waitFor(() => expect(calls.approved).toBe(true));
    expect(await screen.findByText(/now active/)).toBeInTheDocument();
  });

  it('disables every decision for a user who is not an approver', async () => {
    const user = userEvent.setup();
    renderSettings(['tariff:read', 'tariff:manage', 'settings:manage'], { approver: false });
    const region = await openTab(user);
    await screen.findByText(/Compared with the active version/);
    expect(screen.getByText(/Only a designated approver/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Approve and activate' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Reject' })).toBeDisabled();
    expect(within(region).getByRole('button', { name: 'Release: New prices' })).toBeDisabled();
  });

  it('saves the approvers and sender domains as lists', async () => {
    const user = userEvent.setup();
    const { calls } = renderSettings(['tariff:read', 'tariff:manage', 'settings:manage']);
    await openTab(user);
    const approvers = await screen.findByLabelText(/^Approvers/);
    expect(approvers).toHaveValue('admin@demo.example.com');
    await user.clear(approvers);
    await user.type(approvers, 'admin@demo.example.com{enter}approver@demo.example.com');
    await user.type(screen.getByLabelText(/Senders imported without review/), 'vendor.example.com');
    await user.click(screen.getByRole('button', { name: 'Save intake settings' }));
    await waitFor(() =>
      expect(calls.saved).toEqual({
        approver_emails: ['admin@demo.example.com', 'approver@demo.example.com'],
        allowed_sender_domains: ['vendor.example.com'],
      }),
    );
  });
});

describe('Settings › Tariff updates: wording and review details', () => {
  const REFUSED = intake({
    id: 3,
    message_id: '<two@vendor.example.com>',
    subject: 'Two workbooks',
    status: 'rejected',
    tariff_version_id: null,
    tariff_version_public_id: null,
    tariff_version_status: null,
    error: '2 .xlsx attachments; exactly one workbook per email is imported.',
  });
  const REJECTED = intake({
    id: 4,
    message_id: '<old@vendor.example.com>',
    subject: 'Old prices',
    status: 'rejected',
    tariff_version_id: 9,
    tariff_version_public_id: 'TRF-000009',
    reviewed_at: '2026-10-20T10:00:00',
    review_note: 'Wrong prices',
  });
  const RICH_DIFF = {
    ...DIFF,
    summary: { ...DIFF.summary, brackets_added: 1, surcharges_changed: 1 },
    brackets_added: [{ ...DIFF.brackets_changed[0], label: '300+', old_price_vnd: null, new_price_vnd: '228000.00' }],
    surcharges_changed: [
      {
        section: 'hcm_air',
        stt: 4,
        name: 'Pin',
        fields: ['unit_price_vnd'],
        old: { unit_price_vnd: '50000.00' },
        new: { unit_price_vnd: '60000.00' },
      },
    ],
  };

  function stub(rows, diff = RICH_DIFF) {
    stubFetch([
      { path: '/auth/me', body: session(['tariff:read', 'tariff:manage', 'settings:manage']) },
      { path: '/tariffs/intake/settings', body: INTAKE_SETTINGS },
      { path: '/tariffs/versions/7/diff', body: diff },
      { path: '/tariffs/intake', body: { items: rows, total: rows.length, viewer_is_approver: true } },
      { path: '/settings', body: SETTINGS },
    ]);
  }

  function renderIn(locale) {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <I18nProvider initialLocale={locale}>
          <MemoryRouter>
            <SessionProvider>
              <TariffUpdatesPanel />
            </SessionProvider>
          </MemoryRouter>
        </I18nProvider>
      </QueryClientProvider>,
    );
  }

  it('tells a refusal by rule from a rejection by the approver', async () => {
    stub([intake(), REFUSED, REJECTED]);
    renderIn('en');
    const region = await screen.findByRole('region', { name: 'Rate emails' });
    expect(within(region).getByText('Refused')).toBeInTheDocument();
    expect(within(region).getByText('Rejected by approver')).toBeInTheDocument();
  });

  it('uses distinct Vietnamese words and labels server text as English', async () => {
    stub([intake(), REFUSED, REJECTED]);
    renderIn('vi');
    const region = await screen.findByRole('region', { name: 'Email báo giá' });
    expect(within(region).getByText('Không hợp lệ')).toBeInTheDocument();
    expect(within(region).getByText('Đã từ chối')).toBeInTheDocument();
    expect(within(region).getByText(/thông báo của máy chủ \(tiếng Anh\): 2 \.xlsx attachments/)).toBeInTheDocument();
  });

  it('lists added rates and the old and new value of a changed surcharge', async () => {
    stub([intake()]);
    renderIn('en');
    const added = await screen.findByRole('region', { name: 'Prices added' });
    expect(within(added).getByText('228,000')).toBeInTheDocument();
    const rules = screen.getByRole('list', { name: 'Surcharges changed' });
    expect(within(rules).getByText('unit_price_vnd: 50000.00 → 60000.00')).toBeInTheDocument();
  });

  it('keeps Approve disabled while the diff cannot be read', async () => {
    stubFetch([
      { path: '/auth/me', body: session(['tariff:read', 'tariff:manage', 'settings:manage']) },
      { path: '/tariffs/intake/settings', body: INTAKE_SETTINGS },
      { path: '/tariffs/versions/7/diff', status: 500, body: { message: 'boom' } },
      { path: '/tariffs/intake', body: { items: [intake()], total: 1, viewer_is_approver: true } },
    ]);
    renderIn('en');
    const approve = await screen.findByRole('button', { name: 'Approve and activate' });
    expect(approve).toBeDisabled();
  });
});
