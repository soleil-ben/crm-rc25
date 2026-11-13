/**
 * Phase 15 staff workflow: resend a failed quote email, the "issue the invoice" prompt for an
 * accepted quote (workspace and Finance), and the approver's tariff badge.
 */

import { describe, expect, it } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Route, Routes } from 'react-router-dom';
import { SessionProvider } from '../src/app/SessionContext.jsx';
import { AppShell } from '../src/components/layout/AppShell.jsx';
import { AcceptedNotInvoiced } from '../src/features/finance/FinancePage.jsx';
import { InvoiceLink } from '../src/features/workspace/InvoiceLink.jsx';
import { OfferPanel } from '../src/features/workspace/OfferPanel.jsx';
import { renderWithProviders, stubFetch } from './utils.jsx';

function sessionRoute(permissions) {
  return {
    path: '/auth/me',
    body: {
      user: {
        id: 1,
        full_name: 'Test Person',
        email: 'person@demo.example.com',
        role: 'operations',
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

const OPS = [
  'dashboard:read',
  'shipment:read',
  'financial:read',
  'financial:write',
  'tariff:read',
  'settings:read',
];

function withSession(permissions, ui, routes = []) {
  const fetchMock = stubFetch([...routes, sessionRoute(permissions)]);
  const rendered = renderWithProviders(<SessionProvider>{ui}</SessionProvider>);
  return { fetchMock, ...rendered };
}

function offer(overrides = {}) {
  return {
    id: 41,
    shipment_id: 5,
    quote_version_id: 9,
    version: 2,
    status: 'sent',
    is_current: true,
    customer_view: {},
    sent_at: '2026-10-20T10:00:00',
    sent_by_user_id: 1,
    responded_at: null,
    responded_by: null,
    decline_reason: null,
    withdrawn_reason: null,
    withdrawn_at: null,
    withdrawn_code: null,
    superseded_by_version: null,
    superseded_at: null,
    email_status: 'failed',
    ...overrides,
  };
}

const FINALIZED = { id: 9, version: 2, status: 'finalized' };

function panel() {
  return (
    <>
      <InvoiceLink consolidationId={3} shipmentId={5} customerLabel="Lan Tran" refresh={() => {}} />
      <OfferPanel
        consolidationId={3}
        shipmentId={5}
        finalized={FINALIZED}
        canSend
        customerLabel="Lan Tran"
        refresh={() => {}}
      />
    </>
  );
}

describe('Resend a quote email', () => {
  it('offers Resend for a failed email and reports the new outcome', async () => {
    const user = userEvent.setup();
    const { fetchMock } = withSession(OPS, panel(), [
      { path: '/shipments/5/quote-offers', body: [offer()] },
      { path: '/shipments/5/invoice', body: null },
      {
        path: '/quote-offers/41/resend-email',
        method: 'POST',
        body: offer({ email_status: 'sent' }),
      },
    ]);
    const button = await screen.findByRole('button', { name: 'Resend email — Lan Tran' });
    expect(screen.getByText(/did not go out/)).toBeInTheDocument();
    await user.click(button);
    await waitFor(() =>
      expect(
        fetchMock.mock.calls.some(
          ([url, init]) => url.includes('/quote-offers/41/resend-email') && init?.method === 'POST',
        ),
      ).toBe(true),
    );
    expect(await screen.findByText('Email sent again: captured')).toBeInTheDocument();
  });

  it('explains what to do when the customer had no address', async () => {
    withSession(OPS, panel(), [
      { path: '/shipments/5/quote-offers', body: [offer({ email_status: 'no_email' })] },
      { path: '/shipments/5/invoice', body: null },
    ]);
    expect(await screen.findByRole('button', { name: 'Resend email — Lan Tran' })).toBeInTheDocument();
    expect(screen.getByText(/Add one to the customer record/)).toBeInTheDocument();
  });

  it('is not offered when the email went out, or without financial:write', async () => {
    withSession(OPS, panel(), [
      { path: '/shipments/5/quote-offers', body: [offer({ email_status: 'recorded' })] },
      { path: '/shipments/5/invoice', body: null },
    ]);
    await screen.findByText(/Sent — waiting for the customer/);
    expect(screen.queryByRole('button', { name: /Resend email/ })).toBeNull();
  });

  it('is hidden from a reader', async () => {
    withSession(
      ['dashboard:read', 'shipment:read', 'financial:read', 'tariff:read'],
      panel(),
      [
        { path: '/shipments/5/quote-offers', body: [offer()] },
        { path: '/shipments/5/invoice', body: null },
      ],
    );
    await screen.findByText(/Sent — waiting for the customer/);
    expect(screen.queryByRole('button', { name: /Resend email/ })).toBeNull();
  });
});

describe('An accepted quote prompts staff to issue the invoice', () => {
  it('shows the prompt and moves focus to the Issue invoice button', async () => {
    const user = userEvent.setup();
    withSession(OPS, panel(), [
      {
        path: '/shipments/5/quote-offers',
        body: [offer({ status: 'accepted', email_status: 'sent', responded_at: '2026-10-20T12:00:00' })],
      },
      { path: '/shipments/5/invoice', body: null },
    ]);
    expect(await screen.findByText('Customer accepted v2 — issue the invoice')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Go to Issue invoice — Lan Tran' }));
    expect(screen.getByRole('button', { name: 'Issue invoice — Lan Tran' })).toHaveFocus();
  });

  it('asks to agree the price first when a newer version was finalised after', async () => {
    withSession(OPS, panel(), [
      {
        path: '/shipments/5/quote-offers',
        body: [offer({ status: 'accepted', email_status: 'sent', superseded_by_version: 3 })],
      },
      { path: '/shipments/5/invoice', body: null },
    ]);
    expect(
      await screen.findByText(/Customer accepted v2; v3 was finalised after — agree the price first/),
    ).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Go to Issue invoice/ })).toBeNull();
  });

  it('says why when there is no Issue invoice button to go to', async () => {
    const user = userEvent.setup();
    // A reader without financial:write: no Issue invoice control is rendered.
    withSession(
      ['dashboard:read', 'shipment:read', 'financial:read', 'tariff:read'],
      panel(),
      [
        {
          path: '/shipments/5/quote-offers',
          body: [offer({ status: 'accepted', email_status: 'sent' })],
        },
        { path: '/shipments/5/invoice', body: null },
      ],
    );
    await user.click(await screen.findByRole('button', { name: 'Go to Issue invoice — Lan Tran' }));
    expect(await screen.findByText(/You cannot issue invoices/)).toBeInTheDocument();
  });

  it('says the invoice control is not available when it is absent', async () => {
    const user = userEvent.setup();
    withSession(
      OPS,
      <OfferPanel
        consolidationId={3}
        shipmentId={5}
        finalized={FINALIZED}
        canSend
        customerLabel="Lan Tran"
        refresh={() => {}}
      />,
      [
        {
          path: '/shipments/5/quote-offers',
          body: [offer({ status: 'accepted', email_status: 'sent' })],
        },
        { path: '/shipments/5/invoice', body: null },
      ],
    );
    await user.click(await screen.findByRole('button', { name: 'Go to Issue invoice — Lan Tran' }));
    expect(await screen.findByText(/The Issue invoice button is not available here yet/)).toBeInTheDocument();
  });

  it('says nothing once the shipment has an invoice', async () => {
    withSession(OPS, panel(), [
      { path: '/shipments/5/quote-offers', body: [offer({ status: 'accepted', email_status: 'sent' })] },
      {
        path: '/shipments/5/invoice',
        body: { id: 8, public_id: 'INV-000008', status: 'issued', balance_cad: '100.00' },
      },
    ]);
    expect(await screen.findByText('INV-000008')).toBeInTheDocument();
    expect(screen.queryByText(/issue the invoice/)).toBeNull();
  });

  it('lists accepted quotes without an invoice in Finance, linking to the master', async () => {
    withSession(OPS, <AcceptedNotInvoiced />, [
      {
        path: '/finance/accepted-not-invoiced',
        body: {
          items: [
            {
              offer_id: 41,
              shipment_id: 5,
              shipment_reference: 'SX-VCA-0000005',
              customer_name: 'Lan Tran',
              version: 2,
              accepted_at: '2026-10-20T12:00:00',
              total_cad: '216.00',
              consolidation_id: 3,
              superseded_by_version: null,
            },
          ],
          total: 1,
        },
      },
    ]);
    const card = (await screen.findByRole('heading', { name: 'Accepted, not invoiced' })).closest(
      'section, div',
    );
    expect(within(card.parentElement).getByText('Customer accepted v2 — issue the invoice')).toBeInTheDocument();
    const link = screen.getByRole('link', { name: 'Issue the invoice — SX-VCA-0000005' });
    expect(link).toHaveAttribute('href', '/workspace/3');
  });

  it('shows nothing in Finance when every accepted quote is invoiced', async () => {
    const { fetchMock } = withSession(OPS, <AcceptedNotInvoiced />, [
      { path: '/finance/accepted-not-invoiced', body: { items: [], total: 0 } },
    ]);
    await waitFor(() =>
      expect(fetchMock.mock.calls.some(([url]) => url.includes('accepted-not-invoiced'))).toBe(true),
    );
    expect(screen.queryByText('Accepted, not invoiced')).toBeNull();
  });
});

describe('The tariff approver badge', () => {
  function shell(permissions, pending) {
    return withSession(
      permissions,
      <Routes>
        <Route path="/" element={<AppShell />}>
          <Route index element={<p>Home</p>} />
        </Route>
      </Routes>,
      [{ path: '/tariffs/intake/pending-count', body: pending }],
    );
  }

  const MANAGER = [...OPS, 'tariff:manage'];

  it('shows an approver how many drafts and held senders wait', async () => {
    shell(MANAGER, { viewer_is_approver: true, drafts_awaiting: 1, held_senders: 2, total: 3 });
    expect(
      await screen.findByRole('link', { name: /Settings\s*3 tariff item\(s\) awaiting your review/ }),
    ).toHaveAttribute('href', '/settings');
  });

  it('shows no badge to a non-approver or when nothing waits', async () => {
    const { fetchMock } = shell(MANAGER, {
      viewer_is_approver: false,
      drafts_awaiting: 1,
      held_senders: 0,
      total: 1,
    });
    await waitFor(() =>
      expect(fetchMock.mock.calls.some(([url]) => url.includes('pending-count'))).toBe(true),
    );
    expect(await screen.findByRole('link', { name: 'Settings' })).toBeInTheDocument();
    expect(screen.queryByText(/awaiting your review/)).toBeNull();
  });

  it('does not ask without tariff:manage', async () => {
    const { fetchMock } = shell(OPS, { viewer_is_approver: true, drafts_awaiting: 1, held_senders: 0, total: 1 });
    expect(await screen.findByRole('link', { name: 'Settings' })).toBeInTheDocument();
    expect(fetchMock.mock.calls.some(([url]) => url.includes('pending-count'))).toBe(false);
  });
});
