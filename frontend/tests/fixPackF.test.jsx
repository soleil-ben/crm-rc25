/**
 * Fix pack F (owner answers 8, 9a, 2026-10-21): the booked master's edit lock and the draft
 * invoice screen. Mocked API; demo data only.
 *
 * * The draft: unsaved edits disable Send and Download with "Save your changes first";
 *   saving enables them again; a stale revision says someone else changed the draft; a
 *   background refetch never overwrites unsaved edits; Send asks for confirmation (number,
 *   total, email address); a newer quote version needs "Send at the accepted price (vN)".
 * * The lock: a booked master shows the lock; Admin unlocks with a reason (required), other
 *   roles are told who can; an unlocked master offers Lock again; item and fee controls are
 *   disabled with the reason while locked.
 */

import { describe, expect, it, vi } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Route, Routes } from 'react-router-dom';
import { SessionProvider } from '../src/app/SessionContext.jsx';
import { InvoiceDraftPage } from '../src/features/finance/InvoiceDraftPage.jsx';
import { MasterLockBadge, MasterLockPanel } from '../src/features/workspace/MasterLockPanel.jsx';
import { CustomerCard } from '../src/features/workspace/CustomerCard.jsx';
import { renderWithProviders, stubFetch } from './utils.jsx';

function sessionRoute(permissions, role = 'operations') {
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

const OPS = ['shipment:read', 'shipment:write', 'tariff:read', 'financial:read', 'financial:write'];
const ADMIN = [...OPS, 'master:unlock'];

function draft(overrides = {}) {
  return {
    id: 7,
    shipment_id: 5,
    shipment_reference: 'SX-VCA-AAAA05',
    consolidation_id: 3,
    customer_id: 2,
    customer_name: 'Lan Tran',
    quote_version_id: 9,
    quote_version: 1,
    offer_id: 4,
    status: 'draft',
    bill_to_name: 'Lan Tran',
    bill_to_address: '12 Main St',
    customer_reference: null,
    notes: null,
    tax_rate_percent: 0,
    // RC-UAT-19 (owner, 2026-10-22): Send needs the saved revision's GST/HST confirmed; these
    // tests are about unsaved edits and revisions, so their draft is a confirmed one.
    tax_mode: 'added',
    tax_confirmed: true,
    lines: [
      { description: 'Air Standard freight', amount_cad: '216.00' },
      { description: 'Phụ phí', amount_cad: '12.00' },
    ],
    subtotal_cad: '228.00',
    tax_cad: '0.00',
    total_cad: '228.00',
    quote_total_cad: '228.00',
    total_change_reason: null,
    revision: 1,
    created_at: '2026-10-21T10:00:00',
    updated_at: '2026-10-21T10:00:00',
    issued_invoice_id: null,
    issued_invoice_public_id: null,
    issued_at: null,
    discarded_at: null,
    discard_reason: null,
    email_status: null,
    quote_expired: false,
    language: 'vi',
    ...overrides,
  };
}

function renderDraft(routes) {
  const fetchMock = stubFetch([...routes, sessionRoute(OPS)]);
  const { queryClient } = renderWithProviders(
    <SessionProvider>
      <Routes>
        <Route path="/finance/invoice-drafts/:draftId" element={<InvoiceDraftPage />} />
      </Routes>
    </SessionProvider>,
    { route: '/finance/invoice-drafts/7' },
  );
  return { fetchMock, queryClient };
}

describe('Draft invoice: unsaved edits', () => {
  it('blocks Send and Download until the edit is saved, then enables them', async () => {
    const user = userEvent.setup();
    let patched = null;
    let current = draft();
    renderDraft([
      {
        path: '/invoice-drafts/7',
        method: 'PATCH',
        body: (init) => {
          patched = JSON.parse(init.body);
          current = draft({ revision: 2, customer_reference: 'PO-778' });
          return current;
        },
      },
      { path: '/invoice-drafts/7', body: () => current },
    ]);
    const send = await screen.findByRole('button', { name: 'Send invoice' });
    const download = screen.getByRole('button', { name: 'Download PDF (draft)' });
    expect(send).toBeEnabled();
    expect(download).toBeEnabled();
    expect(screen.getByText(/No invoice number yet/)).toBeInTheDocument();

    await user.type(screen.getByLabelText('Customer reference / PO'), 'PO-778');
    expect(screen.getByText(/Save your changes first/)).toBeInTheDocument();
    expect(send).toBeDisabled();
    expect(download).toBeDisabled();

    await user.click(screen.getByRole('button', { name: 'Save draft' }));
    await screen.findByText('Draft saved.');
    expect(patched.expected_revision).toBe(1);
    expect(patched.customer_reference).toBe('PO-778');
    expect(screen.queryByText(/Save your changes first/)).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Send invoice' })).toBeEnabled();
    expect(screen.getByRole('button', { name: 'Download PDF (draft)' })).toBeEnabled();
    expect(screen.getByText(/Revision 2/)).toBeInTheDocument();
  });

  it('says someone else changed the draft when the revision is stale', async () => {
    const user = userEvent.setup();
    renderDraft([
      {
        path: '/invoice-drafts/7',
        method: 'PATCH',
        status: 409,
        body: {
          code: 'conflict',
          message: 'This draft invoice was changed since you opened it.',
          detail: { code: 'stale_revision', current_revision: 2 },
        },
      },
      { path: '/invoice-drafts/7', body: draft() },
    ]);
    await user.type(await screen.findByLabelText('Notes printed on the invoice'), 'Fragile');
    await user.click(screen.getByRole('button', { name: 'Save draft' }));
    expect(await screen.findByText('Someone else changed this draft')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Reload the draft' })).toBeInTheDocument();
    // Still unsaved: Send stays blocked.
    expect(screen.getByRole('button', { name: 'Send invoice' })).toBeDisabled();
  });

  it('asks before leaving through a link while edits are unsaved', async () => {
    const user = userEvent.setup();
    renderDraft([{ path: '/invoice-drafts/7', body: draft() }]);
    await user.type(await screen.findByLabelText('Bill to (name)'), ' Jr');
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false);
    await user.click(screen.getByRole('link', { name: 'Finance' }));
    expect(confirm).toHaveBeenCalledWith(
      'You have unsaved changes to this draft invoice. Leave without saving?',
    );
    // Stayed on the page.
    expect(screen.getByRole('button', { name: 'Save draft' })).toBeInTheDocument();
    confirm.mockRestore();
  });

  it('shows a sent draft read-only with its invoice number', async () => {
    renderDraft([
      {
        path: '/invoice-drafts/7',
        body: draft({
          status: 'issued',
          issued_invoice_id: 31,
          issued_invoice_public_id: 'INV-000031',
          email_status: 'sent',
        }),
      },
    ]);
    expect(await screen.findByRole('link', { name: 'INV-000031' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Send invoice' })).not.toBeInTheDocument();
    expect(screen.getByLabelText('Bill to (name)')).toBeDisabled();
  });

  it('keeps unsaved edits when the draft is refetched in the background', async () => {
    const user = userEvent.setup();
    const { queryClient } = renderDraft([{ path: '/invoice-drafts/7', body: () => draft() }]);
    const notes = await screen.findByLabelText('Notes printed on the invoice');
    await user.type(notes, 'Fragile');
    await queryClient.refetchQueries({ queryKey: ['finance', 'invoice-draft', '7'] });
    await waitFor(() => expect(queryClient.isFetching()).toBe(0));
    expect(screen.getByLabelText('Notes printed on the invoice')).toHaveValue('Fragile');
    expect(screen.getByText(/Save your changes first/)).toBeInTheDocument();
  });

  it('asks before sending: number assigned, total and the customer email', async () => {
    const user = userEvent.setup();
    let sent = null;
    renderDraft([
      {
        path: '/invoice-drafts/7/send',
        method: 'POST',
        body: (init) => {
          sent = JSON.parse(init.body);
          return {
            draft: draft({
              status: 'issued',
              revision: 2,
              issued_invoice_id: 31,
              issued_invoice_public_id: 'INV-000031',
            }),
            invoice_id: 31,
            invoice_public_id: 'INV-000031',
            email_status: 'sent',
          };
        },
      },
      { path: '/invoice-drafts/7', body: draft({ customer_email: 'lan@demo.example.com' }) },
    ]);
    expect(screen.queryByText(/test capture only/)).not.toBeInTheDocument();
    await user.click(await screen.findByRole('button', { name: 'Send invoice' }));
    const dialog = screen.getByRole('dialog', { name: 'Send this invoice?' });
    expect(within(dialog).getByText(/An invoice number will be assigned/)).toBeInTheDocument();
    expect(within(dialog).getByText(/Total: .*228\.00/)).toBeInTheDocument();
    expect(within(dialog).getByText(/emailed to lan@demo\.example\.com/)).toBeInTheDocument();
    expect(sent).toBeNull();
    await user.click(within(dialog).getByRole('button', { name: 'Send the invoice now' }));
    await waitFor(() =>
      expect(sent).toEqual({ expected_revision: 1, acknowledge_superseded: false }),
    );
    expect(await screen.findByText('Invoice INV-000031 issued.')).toBeInTheDocument();
  });

  it('names both versions when a newer quote was finalised and needs the price confirmed', async () => {
    const user = userEvent.setup();
    let sent = null;
    renderDraft([
      {
        path: '/invoice-drafts/7/send',
        method: 'POST',
        body: (init) => {
          sent = JSON.parse(init.body);
          return {
            draft: draft({ status: 'issued', revision: 2 }),
            invoice_id: 31,
            invoice_public_id: 'INV-000031',
            email_status: 'sent',
          };
        },
      },
      { path: '/invoice-drafts/7', body: draft({ superseded_by_version: 2 }) },
    ]);
    expect(
      await screen.findByText(/from accepted quote v1, but quote v2 was finalised after it/),
    ).toBeInTheDocument();
    const send = screen.getByRole('button', { name: 'Send invoice' });
    expect(send).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Withdraw draft' })).toBeEnabled();
    await user.click(screen.getByLabelText('Send at the accepted price (v1)'));
    expect(send).toBeEnabled();
    await user.click(send);
    await user.click(screen.getByRole('button', { name: 'Send the invoice now' }));
    await waitFor(() =>
      expect(sent).toEqual({ expected_revision: 1, acknowledge_superseded: true }),
    );
  });

  it('withdraws a draft with a required reason', async () => {
    const user = userEvent.setup();
    let body = null;
    let current = draft({ superseded_by_version: 2 });
    renderDraft([
      {
        path: '/invoice-drafts/7/withdraw',
        method: 'POST',
        body: (init) => {
          body = JSON.parse(init.body);
          current = draft({
            status: 'discarded',
            revision: 2,
            discard_reason: 'withdrawn by staff: re-priced',
          });
          return current;
        },
      },
      { path: '/invoice-drafts/7', body: () => current },
    ]);
    await user.click(await screen.findByRole('button', { name: 'Withdraw draft' }));
    const dialog = screen.getByRole('dialog', { name: 'Withdraw this draft invoice' });
    const confirm = within(dialog).getByRole('button', { name: 'Withdraw the draft' });
    expect(confirm).toBeDisabled();
    await user.type(within(dialog).getByLabelText(/Reason/), 're-priced');
    await user.click(confirm);
    await waitFor(() => expect(body).toEqual({ reason: 're-priced' }));
    expect(await screen.findByText('This draft was withdrawn')).toBeInTheDocument();
  });
});

function master(lock, overrides = {}) {
  return { id: 3, public_id: 'MST-000003', state: 'booked', members: [], edit_lock: lock, ...overrides };
}

const LOCKED = { locked: true, lockable: true, unlock: null };
const UNLOCKED = {
  locked: false,
  lockable: true,
  unlock: { id: 1, reason: 'Customer added shoes', unlocked_at: '2026-10-21T10:00:00', unlocked_by_user_id: 1 },
};

function renderLock(lock, permissions, routes = []) {
  const fetchMock = stubFetch([...routes, sessionRoute(permissions)]);
  renderWithProviders(
    <SessionProvider>
      <MasterLockBadge master={master(lock)} />
      <MasterLockPanel master={master(lock)} />
    </SessionProvider>,
  );
  return fetchMock;
}

describe('Master edit lock', () => {
  it('lets an Admin unlock with a required reason', async () => {
    const user = userEvent.setup();
    let sent = null;
    renderLock(LOCKED, ADMIN, [
      {
        path: '/consolidations/3/unlock',
        method: 'POST',
        body: (init) => {
          sent = JSON.parse(init.body);
          return master(UNLOCKED);
        },
      },
    ]);
    expect(screen.getByText('Items and fees locked')).toBeInTheDocument();
    await user.click(await screen.findByRole('button', { name: 'Unlock for edits' }));
    const dialog = screen.getByRole('dialog', { name: 'Unlock this master for edits' });
    const confirm = within(dialog).getByRole('button', { name: 'Unlock for edits' });
    expect(confirm).toBeDisabled();
    await user.type(within(dialog).getByLabelText(/Reason/), 'Customer added shoes');
    expect(confirm).toBeEnabled();
    await user.click(confirm);
    await waitFor(() => expect(sent).toEqual({ reason: 'Customer added shoes' }));
  });

  it('tells Operations that an Admin can unlock, and offers no unlock button', async () => {
    renderLock(LOCKED, OPS);
    expect(await screen.findByText(/An Admin can unlock it for edits/)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Unlock for edits' })).not.toBeInTheDocument();
  });

  it('offers Lock again on an unlocked master and shows the reason', async () => {
    const user = userEvent.setup();
    let relocked = false;
    renderLock(UNLOCKED, OPS, [
      {
        path: '/consolidations/3/relock',
        method: 'POST',
        body: () => {
          relocked = true;
          return master(LOCKED);
        },
      },
    ]);
    expect(screen.getAllByText('Unlocked for edits').length).toBeGreaterThan(0);
    expect(screen.getByText(/Customer added shoes/)).toBeInTheDocument();
    await user.click(await screen.findByRole('button', { name: 'Lock again' }));
    await waitFor(() => expect(relocked).toBe(true));
  });

  it('shows nothing for an open master', () => {
    stubFetch([sessionRoute(ADMIN)]);
    renderWithProviders(
      <SessionProvider>
        <MasterLockPanel master={master({ locked: false, lockable: false, unlock: null }, { state: 'open' })} />
      </SessionProvider>,
    );
    expect(screen.queryByText(/locked/i)).not.toBeInTheDocument();
  });

  it('disables item and fee controls with the reason while locked', async () => {
    stubFetch([
      {
        path: '/shipments/11/items',
        body: [{ id: 1, description: 'Shoes', quantity: '1', unit: 'pair', is_active: true }],
      },
      { path: '/shipments/11/fee-lines', body: [] },
      { path: '/shipments/11/quotes', body: [] },
      sessionRoute(OPS),
    ]);
    renderWithProviders(
      <SessionProvider>
        <CustomerCard
          consolidationId={3}
          member={{ shipment_id: 11, public_id: 'SX-VCA-AAAA11', customer_name: 'Lan Tran' }}
          estimate={null}
          section="hcm_air"
          versionId={1}
          editable
          itemsLocked
          removable={false}
        />
      </SessionProvider>,
    );
    expect(await screen.findByText(/Locked: this master is booked/)).toBeInTheDocument();
    expect(await screen.findByRole('button', { name: 'Edit item — Shoes' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Add fee — Shoes' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Add item' })).toBeDisabled();
  });
});
