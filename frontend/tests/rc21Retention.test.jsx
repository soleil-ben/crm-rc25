/**
 * RC-UAT-21 Phase D (DEC-0233). Mocked API; demo data only.
 *
 * * Quote history (Admin): the workspace lists every version with Delete (reason dialog) or
 *   the server's refusal; "Show deleted" lists deleted ones with Restore. Hidden for others.
 * * Settings → Retention (Admin): states plainly that periods are undecided (OD-01, OD-36)
 *   and that deletion is off; turning it on needs the typed phrase; a class cannot be enabled
 *   without the switch and a period; a dry run reports counts per class.
 */

import { describe, expect, it } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { SessionProvider } from '../src/app/SessionContext.jsx';
import { QuoteHistoryAdmin } from '../src/features/workspace/QuoteHistoryAdmin.jsx';
import { RetentionPanel, periodError } from '../src/features/settings/RetentionPanel.jsx';
import { renderWithProviders, stubFetch } from './utils.jsx';

const OPS = ['shipment:read', 'shipment:write', 'tariff:read', 'financial:read', 'financial:write'];
const ADMIN = [...OPS, 'settings:manage', 'quote:delete', 'retention:manage'];

function sessionRoute(permissions) {
  return {
    path: '/auth/me',
    body: {
      user: {
        id: 1,
        full_name: 'Test Person',
        email: 'person@demo.example.com',
        role: 'admin',
        initials: 'TP',
        timezone: 'America/Toronto',
        locale: 'en',
      },
      permissions,
      environment: 'test',
      is_demo_environment: false,
    },
  };
}

function row(overrides = {}) {
  return {
    quote_version_id: 11,
    version: 1,
    status: 'superseded',
    created_at: '2026-10-01T10:00:00Z',
    finalized_at: '2026-10-01T10:00:00Z',
    total_revenue_cad: '114.00',
    offer_status: 'withdrawn',
    expired: false,
    deletable: true,
    refusal: null,
    refusal_message: null,
    deleted: null,
    ...overrides,
  };
}

const HISTORY = {
  shipment_id: 5,
  include_deleted: false,
  min_age_days: 0,
  items: [
    row({
      quote_version_id: 12,
      version: 2,
      status: 'finalized',
      offer_status: 'sent',
      deletable: false,
      refusal: 'open_offer',
      refusal_message: 'This quote is waiting for the customer\'s answer.',
    }),
    row(),
  ],
};

describe('Quote history (Admin soft delete)', () => {
  it('is not shown without quote:delete', async () => {
    const fetch = stubFetch([sessionRoute(OPS)]);
    renderWithProviders(
      <SessionProvider>
        <QuoteHistoryAdmin shipmentId={5} />
      </SessionProvider>,
    );
    await waitFor(() => expect(fetch).toHaveBeenCalled());
    expect(screen.queryByText('Quote history (Admin)')).toBeNull();
    expect(fetch.mock.calls.some(([url]) => String(url).includes('quote-history'))).toBe(false);
  });

  it('deletes an eligible version with a reason and words a refusal', async () => {
    const user = userEvent.setup();
    let posted = null;
    stubFetch([
      {
        path: '/quote-versions/11/delete',
        method: 'POST',
        body: (init) => {
          posted = JSON.parse(init.body);
          return { ...HISTORY, include_deleted: true };
        },
      },
      { path: '/shipments/5/quote-history', body: HISTORY },
      sessionRoute(ADMIN),
    ]);
    renderWithProviders(
      <SessionProvider>
        <QuoteHistoryAdmin shipmentId={5} customerLabel="Lan Tran" />
      </SessionProvider>,
    );
    await user.click(await screen.findByText('Quote history (Admin) — Lan Tran'));
    const v2 = await screen.findByRole('row', { name: /v2/ });
    expect(within(v2).getByText('Waiting for the customer’s answer.')).toBeInTheDocument();
    expect(within(v2).queryByRole('button')).toBeNull();
    await user.click(screen.getByRole('button', { name: 'Delete quote v1 — Lan Tran' }));
    const dialog = await screen.findByRole('dialog', { name: 'Delete quote v1' });
    const confirm = within(dialog).getByRole('button', { name: 'Delete the quote version' });
    expect(confirm).toBeDisabled();
    await user.type(within(dialog).getByLabelText(/Reason/), 'Old superseded quote');
    await user.click(confirm);
    await waitFor(() => expect(posted).toEqual({ reason: 'Old superseded quote' }));
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
  });

  it('shows deleted versions on request and restores one with a reason', async () => {
    const user = userEvent.setup();
    let posted = null;
    const deleted = {
      ...HISTORY,
      include_deleted: true,
      items: [
        ...HISTORY.items.slice(0, 1),
        row({
          deletable: false,
          deleted: {
            deleted_at: '2026-10-20T10:00:00Z',
            deleted_by: 'admin@demo.example.com',
            reason: 'Old superseded quote',
          },
        }),
      ],
    };
    stubFetch([
      {
        path: '/quote-versions/11/restore',
        method: 'POST',
        body: (init) => {
          posted = JSON.parse(init.body);
          return HISTORY;
        },
      },
      { path: 'include_deleted=true', body: deleted },
      { path: '/shipments/5/quote-history', body: { ...HISTORY, items: HISTORY.items.slice(0, 1) } },
      sessionRoute(ADMIN),
    ]);
    renderWithProviders(
      <SessionProvider>
        <QuoteHistoryAdmin shipmentId={5} />
      </SessionProvider>,
    );
    await user.click(await screen.findByText('Quote history (Admin)'));
    await screen.findByRole('row', { name: /v2/ });
    expect(screen.queryByRole('row', { name: /v1/ })).toBeNull();
    await user.click(screen.getByLabelText('Show deleted versions'));
    const v1 = await screen.findByRole('row', { name: /v1/ });
    expect(v1).toHaveTextContent('Deleted by admin@demo.example.com');
    expect(v1).toHaveTextContent('Old superseded quote');
    await user.click(within(v1).getByRole('button', { name: 'Restore quote v1' }));
    const dialog = await screen.findByRole('dialog', { name: 'Restore quote v1' });
    await user.type(within(dialog).getByLabelText(/Reason/), 'Needed after all');
    await user.click(within(dialog).getByRole('button', { name: 'Restore the quote version' }));
    await waitFor(() => expect(posted).toEqual({ reason: 'Needed after all' }));
  });
});

const CLASSES = [
  ['soft_deleted_quotes', 'delete'],
  ['closed_quote_offers', 'anonymise'],
  ['staff_sessions_ended', 'delete'],
];

function overview({ enabled = false, runs = [] } = {}) {
  return {
    settings: {
      enabled,
      enabled_at: enabled ? '2026-10-24T10:00:00Z' : null,
      enabled_by: enabled ? 'admin@demo.example.com' : null,
      quote_delete_min_age_days: 0,
      batch_size: 200,
      confirmation_phrase: 'ENABLE RETENTION',
      updated_at: '2026-10-24T00:00:00Z',
      updated_by: null,
    },
    policies: CLASSES.map(([key, action]) => ({
      record_class: key,
      label: key,
      description: `About ${key}`,
      enabled: false,
      period_days: null,
      action,
      allowed_actions: [action],
      last_run_at: null,
      last_run_affected: null,
      updated_at: '2026-10-24T00:00:00Z',
      updated_by: null,
    })),
    runs,
  };
}

describe('Settings → Retention', () => {
  it('validates a period', () => {
    expect(periodError('')).toBeNull();
    expect(periodError('90')).toBeNull();
    expect(periodError('0')).toBe('retention.periodError');
    expect(periodError('1.5')).toBe('retention.periodError');
  });

  it('says periods are undecided and everything is off', async () => {
    stubFetch([{ path: '/admin/data-retention', body: overview() }, sessionRoute(ADMIN)]);
    renderWithProviders(
      <SessionProvider>
        <RetentionPanel />
      </SessionProvider>,
    );
    expect(await screen.findByText('Retention periods are not decided')).toBeInTheDocument();
    expect(screen.getByText(/OD-01, OD-36/)).toBeInTheDocument();
    expect(screen.getByText('Retention deletion is off.')).toBeInTheDocument();
    const quotes = screen.getByRole('row', { name: /Soft-deleted quotes/ });
    expect(quotes).toHaveTextContent('Disabled');
    expect(within(quotes).getByRole('button', { name: 'Enable Soft-deleted quotes' })).toBeDisabled();
    expect(screen.getByText(/not record classes/)).toBeInTheDocument();
  });

  it('turns deletion on only with the typed phrase', async () => {
    const user = userEvent.setup();
    let patched = null;
    stubFetch([
      {
        path: '/admin/data-retention/settings',
        method: 'PATCH',
        body: (init) => {
          patched = JSON.parse(init.body);
          return overview({ enabled: true });
        },
      },
      { path: '/admin/data-retention', body: overview() },
      sessionRoute(ADMIN),
    ]);
    renderWithProviders(
      <SessionProvider>
        <RetentionPanel />
      </SessionProvider>,
    );
    const turnOn = await screen.findByRole('button', { name: 'Turn retention deletion on' });
    expect(turnOn).toBeDisabled();
    await user.type(screen.getByLabelText(/To turn it on, type ENABLE RETENTION/), 'enable');
    expect(turnOn).toBeDisabled();
    await user.clear(screen.getByLabelText(/To turn it on/));
    await user.type(screen.getByLabelText(/To turn it on/), 'ENABLE RETENTION');
    await user.click(turnOn);
    await waitFor(() => expect(patched).toEqual({ enabled: true, confirmation: 'ENABLE RETENTION' }));
    expect(await screen.findByText('Retention deletion is on')).toBeInTheDocument();
  });

  it('saves a period and shows a dry run report', async () => {
    const user = userEvent.setup();
    let policy = null;
    const dry = {
      id: 3,
      dry_run: true,
      trigger: 'admin',
      status: 'completed',
      counts: {
        soft_deleted_quotes: { eligible: null, would_run: false },
        staff_sessions_ended: { eligible: 6, would_run: false },
      },
      error: null,
      started_at: '2026-10-24T10:00:00Z',
      finished_at: '2026-10-24T10:00:01Z',
    };
    stubFetch([
      {
        path: '/admin/data-retention/policies/staff_sessions_ended',
        method: 'PATCH',
        body: (init) => {
          policy = JSON.parse(init.body);
          return overview().policies[2];
        },
      },
      { path: '/admin/data-retention/dry-run', method: 'POST', body: dry },
      { path: '/admin/data-retention', body: overview() },
      sessionRoute(ADMIN),
    ]);
    renderWithProviders(
      <SessionProvider>
        <RetentionPanel />
      </SessionProvider>,
    );
    const input = await screen.findByLabelText('Retention period in days for Ended staff sessions');
    await user.type(input, '0');
    await user.click(screen.getByRole('button', { name: 'Save the policy for Ended staff sessions' }));
    expect(screen.getByText(/Enter a whole number of days from 1 to 36500/)).toBeInTheDocument();
    expect(policy).toBeNull();
    await user.clear(input);
    await user.type(input, '90');
    await user.click(screen.getByRole('button', { name: 'Save the policy for Ended staff sessions' }));
    await waitFor(() => expect(policy).toEqual({ period_days: 90, action: 'delete' }));
    expect(screen.getByText('No dry run yet.')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Run a dry run' }));
    const staff = await screen.findByRole('row', { name: /Ended staff sessions 6/ });
    expect(staff).toHaveTextContent('No');
    expect(screen.getByRole('row', { name: /Soft-deleted quotes No period set/ })).toBeInTheDocument();
  });

  it('tells a non-Admin it is Admin only', async () => {
    stubFetch([sessionRoute(OPS)]);
    renderWithProviders(
      <SessionProvider>
        <RetentionPanel />
      </SessionProvider>,
    );
    expect(await screen.findByText('Only Admin can see or change retention.')).toBeInTheDocument();
  });
});
