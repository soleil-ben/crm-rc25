/**
 * RC-UAT-22 (B-13, DEC-0234 draft): the Admin list of Customer Accounts that lost their
 * customer, on the account queue page. Re-link (preview -> read -> acknowledge -> reason ->
 * confirm, carrying the preview's fingerprint) and close (reason -> confirm). Admin only.
 */

import { afterEach, describe, expect, it, vi } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { SessionProvider } from '../src/app/SessionContext.jsx';
import { CustomerAccountQueuePage } from '../src/features/customer_accounts/CustomerAccountQueuePage.jsx';
import { renderWithProviders, stubFetch } from './utils.jsx';

afterEach(() => {
  vi.unstubAllGlobals();
});

const REVIEW = 'customer_account:review';
const APPROVE = 'customer_account:approve';
const DEACTIVATE = 'customer_account:deactivate';
const REFERENCE = 'CA-7K9D2M4R';
const OTHER = 'CA-3P8Q5W2Z';
const BASE = `/customer-account/identities/${REFERENCE}`;

function session(role, permissions) {
  return {
    path: '/auth/me',
    body: {
      user: {
        id: 1,
        full_name: 'Test Person',
        email: 'person@demo.example.com',
        role,
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

function orphanRow(overrides = {}) {
  return {
    account_reference: REFERENCE,
    account_email_entered: 'Hanh.Nguyen@example.com',
    approved_at: '2026-09-20T10:00:00',
    last_customer_public_id: 'STCA-000012',
    last_link_end_reason: 'merged_since_deactivation',
    last_link_ended_at: '2026-10-22T10:00:00',
    last_customer_merged: true,
    suggested_customer_public_id: 'STCA-000044',
    ...overrides,
  };
}

function orphanList(items) {
  return {
    items,
    relink_reason_codes: ['merge_survivor', 'correct_customer', 'other'],
    close_reason_codes: ['no_customer', 'duplicate', 'other'],
  };
}

const PREVIEW = {
  account_reference: REFERENCE,
  target_customer_public_id: 'STCA-000044',
  disclosure: {
    shipment_count: 7,
    oldest_booked_at: '2025-03-01T10:00:00',
    newest_booked_at: '2026-10-01T10:00:00',
    includes_cancelled: true,
    includes_rebooked: false,
    definition_version: 1,
  },
  email_change: { current: null, new: 'Hanh.Nguyen@example.com' },
  fingerprint: 'f'.repeat(64),
};

const STATUS_OUT = {
  account_reference: REFERENCE,
  status: 'active',
  status_reason_code: 'merge_survivor',
  account_email_entered: 'Hanh.Nguyen@example.com',
  email_verified: true,
  approved_at: '2026-09-20T10:00:00',
  suspended_at: null,
  deactivated_at: null,
  linked_customer_public_id: 'STCA-000044',
  can_suspend: true,
  can_reinstate: false,
  can_deactivate: true,
  can_reactivate: false,
};

/** The queue page with empty upper lists; `orphans` is read on every list fetch. */
function renderQueue({ role = 'admin', permissions = [REVIEW, APPROVE, DEACTIVATE], orphans, extra = [] }) {
  const state = { orphans };
  const fetchMock = stubFetch([
    session(role, permissions),
    ...extra,
    { path: '/customer-account/registrations', body: { items: [], total: 0, limit: 25, offset: 0 } },
    { path: '/customer-account/profile-proposals', body: { items: [], total: 0 } },
    { path: '/customer-account/identities-deactivated', body: { items: [] } },
    { path: '/customer-account/identities-orphaned', body: () => orphanList(state.orphans) },
  ]);
  renderWithProviders(
    <SessionProvider>
      <CustomerAccountQueuePage />
    </SessionProvider>,
    { route: '/customer-accounts' },
  );
  return { fetchMock, state };
}

function callsTo(fetchMock, fragment, method = 'GET') {
  return fetchMock.mock.calls.filter(
    ([url, init = {}]) => String(url).includes(fragment) && (init.method || 'GET') === method,
  );
}

async function orphanTable() {
  return screen.findByTestId('orphaned-accounts');
}

describe('Staff › accounts needing a customer › list', () => {
  it('lists each orphan with its last customer, why the link ended and the suggestion', async () => {
    renderQueue({ orphans: [orphanRow(), orphanRow({ account_reference: OTHER, suggested_customer_public_id: null, last_customer_merged: false, last_link_end_reason: 'archived_since_deactivation' })] });
    const table = await orphanTable();
    const first = within(table).getByRole('row', { name: new RegExp(REFERENCE) });
    expect(within(first).getByText(/STCA-000012/)).toHaveTextContent('STCA-000012 (merged)');
    expect(within(first).getByText('Customer merged while deactivated')).toBeInTheDocument();
    expect(within(first).getByText('STCA-000044')).toBeInTheDocument();
    const second = within(table).getByRole('row', { name: new RegExp(OTHER) });
    expect(within(second).getByText('No suggestion')).toBeInTheDocument();
    expect(within(second).getByText('Customer archived while deactivated')).toBeInTheDocument();
  });

  it('says so when no account is waiting', async () => {
    renderQueue({ orphans: [] });
    expect(await screen.findByText('No account is waiting for a customer.')).toBeInTheDocument();
  });

  it('is not shown, nor read, for a role without the reinstatement permission', async () => {
    const { fetchMock } = renderQueue({ role: 'operations', permissions: [REVIEW, APPROVE], orphans: [orphanRow()] });
    await waitFor(() => expect(callsTo(fetchMock, '/customer-account/profile-proposals')).toHaveLength(1));
    expect(screen.queryByText('Accounts needing a customer')).toBeNull();
    expect(screen.queryByRole('button', { name: 'Re-link' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Close' })).toBeNull();
    expect(callsTo(fetchMock, '/identities-orphaned')).toHaveLength(0);
  });
});

describe('Staff › accounts needing a customer › re-link', () => {
  it('prefills the survivor, and needs the preview, the acknowledgement and a reason before it sends the fingerprint', async () => {
    const user = userEvent.setup();
    const { fetchMock, state } = renderQueue({
      orphans: [orphanRow()],
      extra: [
        { path: `${BASE}/relink-preview`, body: PREVIEW },
        { path: `${BASE}/relink`, method: 'POST', body: STATUS_OUT },
      ],
    });
    const table = await orphanTable();
    await user.click(within(table).getByRole('button', { name: 'Re-link' }));
    const dialog = screen.getByRole('dialog', { name: `Re-link ${REFERENCE} to a customer` });
    const customer = within(dialog).getByLabelText('Customer reference');
    expect(customer).toHaveValue('STCA-000044');

    const confirm = within(dialog).getByRole('button', { name: 'Re-link and activate' });
    expect(confirm).toBeDisabled();
    // No acknowledgement before the history has been shown.
    expect(within(dialog).queryByLabelText(/I have read the history above/)).toBeNull();

    await user.click(within(dialog).getByRole('button', { name: /Show this customer/ }));
    const history = await within(dialog).findByTestId('relink-history');
    expect(within(history).getByText('7')).toBeInTheDocument();
    expect(within(dialog).getByText(/Hanh\.Nguyen@example\.com/)).toBeInTheDocument();
    const preview = callsTo(fetchMock, '/relink-preview');
    expect(preview).toHaveLength(1);
    expect(String(preview[0][0])).toContain('customer_public_id=STCA-000044');

    expect(confirm).toBeDisabled();
    await user.click(within(dialog).getByLabelText(/I have read the history above/));
    expect(confirm).toBeDisabled();
    await user.selectOptions(within(dialog).getByLabelText('Why this customer'), 'merge_survivor');
    expect(confirm).toBeEnabled();
    await user.type(within(dialog).getByLabelText(/Note \(optional/), '  Merged on 2026-10-24.  ');

    state.orphans = [];
    await user.click(confirm);
    expect(
      await screen.findByText('The account is linked and active again. The customer was emailed that it is ready.'),
    ).toBeInTheDocument();
    expect(screen.queryByRole('dialog')).toBeNull();
    const [post] = callsTo(fetchMock, `${BASE}/relink`, 'POST');
    expect(JSON.parse(post[1].body)).toEqual({
      customer_public_id: 'STCA-000044',
      reason_code: 'merge_survivor',
      note: 'Merged on 2026-10-24.',
      history_acknowledged: true,
      preview_fingerprint: PREVIEW.fingerprint,
    });
    expect(await screen.findByText('No account is waiting for a customer.')).toBeInTheDocument();
  });

  it('editing the customer discards the preview and the acknowledgement', async () => {
    const user = userEvent.setup();
    renderQueue({ orphans: [orphanRow()], extra: [{ path: `${BASE}/relink-preview`, body: PREVIEW }] });
    await user.click(within(await orphanTable()).getByRole('button', { name: 'Re-link' }));
    const dialog = screen.getByRole('dialog');
    await user.click(within(dialog).getByRole('button', { name: /Show this customer/ }));
    await user.click(await within(dialog).findByLabelText(/I have read the history above/));
    await user.type(within(dialog).getByLabelText('Customer reference'), '9');
    expect(within(dialog).queryByTestId('relink-history')).toBeNull();
    expect(within(dialog).getByRole('button', { name: 'Re-link and activate' })).toBeDisabled();
  });

  it('a 409 preview_stale discards the acknowledgement and asks for a fresh look', async () => {
    const user = userEvent.setup();
    const { fetchMock } = renderQueue({
      orphans: [orphanRow()],
      extra: [
        { path: `${BASE}/relink-preview`, body: PREVIEW },
        {
          path: `${BASE}/relink`,
          method: 'POST',
          status: 409,
          body: {
            code: 'conflict',
            message: 'The customer or the account changed since the preview. Check it again, read it, and confirm that.',
            field: 'preview_fingerprint',
            detail: { code: 'preview_stale' },
          },
        },
      ],
    });
    await user.click(within(await orphanTable()).getByRole('button', { name: 'Re-link' }));
    const dialog = screen.getByRole('dialog');
    await user.click(within(dialog).getByRole('button', { name: /Show this customer/ }));
    await user.click(await within(dialog).findByLabelText(/I have read the history above/));
    await user.selectOptions(within(dialog).getByLabelText('Why this customer'), 'merge_survivor');
    await user.click(within(dialog).getByRole('button', { name: 'Re-link and activate' }));

    expect(
      await within(dialog).findByText('The customer or the account changed since you checked. Check the history again.'),
    ).toBeInTheDocument();
    expect(within(dialog).queryByTestId('relink-history')).toBeNull();
    expect(within(dialog).getByRole('button', { name: 'Re-link and activate' })).toBeDisabled();
    // Not retried behind the Admin's back.
    expect(callsTo(fetchMock, `${BASE}/relink`, 'POST')).toHaveLength(1);

    // A fresh look clears the warning, and the old refusal does not come back as an error.
    await user.click(within(dialog).getByRole('button', { name: /Show this customer/ }));
    expect(await within(dialog).findByTestId('relink-history')).toBeInTheDocument();
    expect(within(dialog).queryByText(/changed since/)).toBeNull();
    expect(within(dialog).getByLabelText(/I have read the history above/)).not.toBeChecked();
  });

  it('shows a refused preview (an already-linked customer) in the dialog', async () => {
    const user = userEvent.setup();
    renderQueue({
      orphans: [orphanRow()],
      extra: [
        {
          path: `${BASE}/relink-preview`,
          status: 409,
          body: {
            code: 'conflict',
            message: 'STCA-000044 already has a Customer Account linked. Release 1 allows one.',
            field: 'customer_public_id',
            detail: {},
          },
        },
      ],
    });
    await user.click(within(await orphanTable()).getByRole('button', { name: 'Re-link' }));
    const dialog = screen.getByRole('dialog');
    await user.click(within(dialog).getByRole('button', { name: /Show this customer/ }));
    expect(await within(dialog).findByText(/already has a Customer Account linked/)).toBeInTheDocument();
    expect(within(dialog).getByRole('button', { name: 'Re-link and activate' })).toBeDisabled();
  });
});

describe('Staff › accounts needing a customer › close', () => {
  it('needs a reason, then the confirmation, and sends the reason and note', async () => {
    const user = userEvent.setup();
    const { fetchMock, state } = renderQueue({
      orphans: [orphanRow()],
      extra: [
        {
          path: `${BASE}/close-orphan`,
          method: 'POST',
          body: { ...STATUS_OUT, status: 'deactivated', status_reason_code: 'orphan_closed' },
        },
      ],
    });
    await user.click(within(await orphanTable()).getByRole('button', { name: 'Close' }));
    const dialog = screen.getByRole('dialog', { name: `Close ${REFERENCE}?` });
    expect(within(dialog).getByText(/nothing is emailed to the customer/)).toBeInTheDocument();
    const confirm = within(dialog).getByRole('button', { name: 'Yes, close the account' });
    expect(confirm).toBeDisabled();

    // Cancelling sends nothing.
    await user.click(within(dialog).getByRole('button', { name: 'Cancel' }));
    expect(screen.queryByRole('dialog')).toBeNull();
    expect(callsTo(fetchMock, '/close-orphan', 'POST')).toHaveLength(0);

    await user.click(within(await orphanTable()).getByRole('button', { name: 'Close' }));
    const again = screen.getByRole('dialog', { name: `Close ${REFERENCE}?` });
    await user.selectOptions(within(again).getByLabelText('Why close it'), 'no_customer');
    await user.type(within(again).getByLabelText(/Note \(optional/), 'No record to link.');
    state.orphans = [];
    await user.click(within(again).getByRole('button', { name: 'Yes, close the account' }));

    expect(await screen.findByText('The account has been closed.')).toBeInTheDocument();
    const [post] = callsTo(fetchMock, '/close-orphan', 'POST');
    expect(JSON.parse(post[1].body)).toEqual({ reason_code: 'no_customer', note: 'No record to link.' });
    expect(await screen.findByText('No account is waiting for a customer.')).toBeInTheDocument();
  });

  it('shows the server refusal in the dialog', async () => {
    const user = userEvent.setup();
    renderQueue({
      orphans: [orphanRow()],
      extra: [
        {
          path: `${BASE}/close-orphan`,
          method: 'POST',
          status: 409,
          body: {
            code: 'conflict',
            message: 'This account has a link or a pending proposal. Use the approval queue instead.',
            field: null,
            detail: {},
          },
        },
      ],
    });
    await user.click(within(await orphanTable()).getByRole('button', { name: 'Close' }));
    const dialog = screen.getByRole('dialog');
    await user.selectOptions(within(dialog).getByLabelText('Why close it'), 'duplicate');
    await user.click(within(dialog).getByRole('button', { name: 'Yes, close the account' }));
    expect(await within(dialog).findByText(/Use the approval queue instead/)).toBeInTheDocument();
  });
});

describe('Vietnamese strings for the orphan list', () => {
  it('carry their diacritics', async () => {
    const { default: messages } = await import('../src/i18n/vi.js');
    const strings = messages.customerAccounts;
    expect(strings.orphanedTitle).toBe('Tài khoản cần liên kết khách hàng');
    expect(strings.relinkAction).toBe('Liên kết lại');
    expect(strings.closeConfirm).toBe('Đồng ý, đóng tài khoản');
    expect(strings.statusReasonCode.orphan_closed).toBe('Đã đóng: không có khách hàng để liên kết');
  });
});
