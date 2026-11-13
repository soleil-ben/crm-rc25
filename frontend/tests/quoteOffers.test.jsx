/**
 * Phase 13G (OD-77, D-08): staff send a finalised quote from the workspace; the customer
 * reads it in the Customer Account and accepts (after a confirmation) or declines (with an
 * optional reason). Against mocked APIs.
 *
 * Contracts: staff `GET /shipments/{id}/quote-offers`, `POST /shipments/{id}/quotes/send`,
 * `POST /quote-offers/{id}/withdraw {reason}`; account `GET /account/quotes`,
 * `GET /account/quotes/{id}`, `POST /account/quotes/{id}/accept`,
 * `POST /account/quotes/{id}/decline {reason?}`.
 */

import { beforeEach, describe, expect, it } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { SessionProvider } from '../src/app/SessionContext.jsx';
import { QuotePanel } from '../src/features/workspace/QuotePanel.jsx';
import { renderWithProviders, stubFetch } from './utils.jsx';
import { clearBrowserStorage, meFixture, renderAccount, stubAccountFetch } from './accountUtils.jsx';

/* --- Staff workspace -------------------------------------------------------------------- */

function staffSession(permissions) {
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

const WRITER = ['shipment:read', 'tariff:read', 'financial:read', 'financial:write'];

const FINAL = {
  id: 41,
  shipment_id: 5,
  version: 1,
  status: 'finalized',
  solaris_service: 'air_standard',
  consolidation_id: 3,
  tariff_version_id: 7,
  fx_snapshot_id: 1,
  default_rate_cad: '18.00',
  selling_rate_cad: '18.00',
  override_reason: null,
  rate_confirmed: true,
  rate_confirmed_at: '2026-10-19T10:00:00',
  negative_margin_reason: null,
  billable_weight_kg: '12.000',
  base_revenue_cad: '216.00',
  surcharge_revenue_cad: '0.00',
  total_revenue_cad: '216.00',
  allocated_cost_cad: '120.00',
  gross_profit_cad: '96.00',
  blocking: [],
  provisional: [],
  lines: [],
  finalized_at: '2026-10-19T10:00:00',
  created_at: '2026-10-19T10:00:00',
};

function offer(overrides = {}) {
  return {
    id: 9,
    shipment_id: 5,
    quote_version_id: 41,
    version: 1,
    status: 'sent',
    is_current: true,
    customer_view: {},
    sent_at: '2026-10-20T14:00:00',
    sent_by_user_id: 1,
    responded_at: null,
    responded_by: null,
    decline_reason: null,
    withdrawn_reason: null,
    withdrawn_at: null,
    email_status: 'recorded',
    ...overrides,
  };
}

function renderStaff(permissions, routes) {
  const fetchMock = stubFetch([
    staffSession(permissions),
    { path: '/shipments/5/invoice', body: null },
    ...routes,
    { path: '/shipments/5/quotes', body: [FINAL] },
  ]);
  renderWithProviders(
    <SessionProvider>
      <QuotePanel consolidationId={3} shipmentId={5} refresh={() => {}} editable customerLabel="Hạnh" />
    </SessionProvider>,
  );
  return fetchMock;
}

describe('the workspace quote offer', () => {
  it('sends a finalised quote to the customer', async () => {
    const user = userEvent.setup();
    const fetchMock = renderStaff(WRITER, [
      { path: '/shipments/5/quotes/send', method: 'POST', status: 201, body: offer() },
      { path: '/shipments/5/quote-offers', body: [] },
    ]);
    expect(
      await screen.findByText('This quote has not been sent to the customer.'),
    ).toBeInTheDocument();
    await user.click(await screen.findByRole('button', { name: 'Send to customer — Hạnh' }));
    await waitFor(() =>
      expect(
        fetchMock.mock.calls.some(
          ([url, init]) => url.includes('/shipments/5/quotes/send') && init?.method === 'POST',
        ),
      ).toBe(true),
    );
  });

  it('shows a decline with its reason and offers no second send', async () => {
    renderStaff(WRITER, [
      {
        path: '/shipments/5/quote-offers',
        body: [
          offer({
            status: 'declined',
            responded_at: '2026-10-20T15:00:00',
            responded_by: 'CA-7K9D2M4R',
            decline_reason: 'Too expensive',
          }),
        ],
      },
    ]);
    expect(await screen.findByText('Reason given: Too expensive')).toBeInTheDocument();
    expect(screen.getByText(/v1 · Declined/)).toBeInTheDocument();
    expect(screen.getByText(/by CA-7K9D2M4R/)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Send to customer/ })).toBeNull();
  });

  it('withdraws a sent offer with a reason', async () => {
    const user = userEvent.setup();
    const fetchMock = renderStaff(WRITER, [
      {
        path: '/quote-offers/9/withdraw',
        method: 'POST',
        body: offer({ status: 'withdrawn', withdrawn_reason: 'Wrong weight' }),
      },
      { path: '/shipments/5/quote-offers', body: [offer()] },
    ]);
    expect(await screen.findByText(/Sent — waiting for the customer/)).toBeInTheDocument();
    expect(screen.getByText(/recorded, not sent/)).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Withdraw — Hạnh' }));
    const confirm = screen.getByRole('button', { name: 'Withdraw quote — Hạnh' });
    expect(confirm).toBeDisabled();
    await user.type(screen.getByRole('textbox', { name: /Reason for withdrawing/ }), 'Wrong weight');
    await user.click(confirm);
    await waitFor(() => {
      const call = fetchMock.mock.calls.find(([url]) => url.includes('/quote-offers/9/withdraw'));
      expect(JSON.parse(call[1].body)).toEqual({ reason: 'Wrong weight' });
    });
  });

  it('warns staff when the customer accepted an earlier price', async () => {
    renderStaff(WRITER, [
      {
        path: '/shipments/5/quote-offers',
        body: [
          offer({
            status: 'accepted',
            responded_at: '2026-10-20T15:00:00',
            responded_by: 'CA-7K9D2M4R',
            superseded_by_version: 2,
          }),
        ],
      },
    ]);
    expect(
      await screen.findByText(/The customer accepted v1 at an earlier price; v2 was finalised after/),
    ).toBeInTheDocument();
  });

  it('hides send and withdraw from a role without financial:write', async () => {
    renderStaff(['shipment:read', 'tariff:read', 'financial:read'], [
      { path: '/shipments/5/quote-offers', body: [offer()] },
    ]);
    expect(await screen.findByText(/Sent — waiting for the customer/)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Withdraw/ })).toBeNull();
    expect(screen.queryByRole('button', { name: /Send to customer/ })).toBeNull();
  });
});

/* --- Customer Account ------------------------------------------------------------------- */

const ME = { path: '/api/v1/account/me', body: meFixture() };

function detail(overrides = {}) {
  return {
    id: 9,
    shipment_reference: 'SX-VCA-7K9D2M4R8T6W',
    version: 1,
    service: 'Air Standard',
    status: 'sent',
    sent_at: '2026-10-20T14:00:00',
    total_cad: '223.38',
    currency: 'CAD',
    billable_weight_kg: '12.000',
    rate_per_kg_cad: '18.00',
    base_charge_cad: '216.00',
    surcharges: [{ name: 'Đồng hồ thường', amount_cad: '7.38' }],
    tax_included: false,
    // RC-UAT-21 (P-9 stand-in): the invoice's GST/HST rule; this one is domestic, Ontario.
    tax: { band: 'domestic', label: 'HST', rate_percent: 13 },
    responded_at: null,
    decline_reason: null,
    can_answer: true,
    closed_reason: null,
    ...overrides,
  };
}

const LIST = {
  path: '/api/v1/account/quotes',
  method: 'GET',
  body: {
    items: [
      {
        id: 9,
        shipment_reference: 'SX-VCA-7K9D2M4R8T6W',
        version: 1,
        service: 'Air Standard',
        status: 'sent',
        sent_at: '2026-10-20T14:00:00',
        total_cad: '223.38',
        currency: 'CAD',
      },
    ],
  },
};

describe('the Customer Account quotes', () => {
  beforeEach(clearBrowserStorage);

  it('lists quotes, linked from the navigation', async () => {
    stubAccountFetch([ME, LIST]);
    renderAccount('/account/quotes');
    expect(await screen.findByRole('heading', { name: 'Quotes', level: 1 })).toBeInTheDocument();
    const nav = screen.getByRole('navigation', { name: 'Customer Account' });
    expect(within(nav).getByRole('link', { name: 'Quotes' })).toHaveAttribute(
      'href',
      '/account/quotes',
    );
    const link = screen.getByRole('link', {
      name: 'Open the quote for shipment SX-VCA-7K9D2M4R8T6W',
    });
    expect(link).toHaveAttribute('href', '/account/quotes/9');
    expect(screen.getByText('Waiting for your answer')).toBeInTheDocument();
    expect(screen.getByText('Air Standard')).toBeInTheDocument();
    expect(screen.getByText(/223\.38/)).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.getByRole('heading', { name: 'Quotes', level: 1 })).toHaveFocus(),
    );
    expect(window.localStorage.length).toBe(0);
    expect(window.sessionStorage.length).toBe(0);
  });

  it('says so when there is no quote', async () => {
    stubAccountFetch([ME, { ...LIST, body: { items: [] } }]);
    renderAccount('/account/quotes');
    expect(await screen.findByText('No quotes yet')).toBeInTheDocument();
  });

  it('asks for confirmation before accepting, then announces the answer', async () => {
    const user = userEvent.setup();
    const { calls } = stubAccountFetch([
      ME,
      {
        path: '/api/v1/account/quotes/9/accept',
        method: 'POST',
        body: detail({
          status: 'accepted',
          can_answer: false,
          closed_reason: 'accepted',
          responded_at: '2026-10-20T15:00:00',
        }),
      },
      { path: '/api/v1/account/quotes/9', method: 'GET', body: detail() },
    ]);
    renderAccount('/account/quotes/9');
    expect(
      await screen.findByRole('heading', { name: 'Quote for shipment SX-VCA-7K9D2M4R8T6W', level: 1 }),
    ).toBeInTheDocument();
    expect(screen.getByText('Đồng hồ thường')).toBeInTheDocument();
    expect(screen.getByText('Air Standard freight')).toBeInTheDocument();
    expect(screen.getByText('Prices include HST 13 %')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Accept quote' }));
    // Nothing is sent until the confirmation is answered.
    expect(calls.filter((call) => call.method === 'POST')).toHaveLength(0);
    const confirmation = screen.getByRole('region', { name: 'Accept this quote?' });
    await waitFor(() => expect(confirmation).toHaveFocus());
    expect(within(confirmation).getByText(/223\.38/)).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Yes, accept the quote' }));

    expect(await screen.findByText('Quote accepted.')).toBeInTheDocument();
    const post = calls.find((call) => call.method === 'POST');
    expect(post.url).toContain('/api/v1/account/quotes/9/accept');
    expect(post.headers['X-Account-CSRF-Token']).toBeUndefined(); // no cookie in jsdom
    expect(screen.getByText('You accepted this quote.')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Accept quote' })).toBeNull();
    expect(window.localStorage.length).toBe(0);
    expect(window.sessionStorage.length).toBe(0);
  });

  it('cancelling the confirmation sends nothing', async () => {
    const user = userEvent.setup();
    const { calls } = stubAccountFetch([
      ME,
      { path: '/api/v1/account/quotes/9', method: 'GET', body: detail() },
    ]);
    renderAccount('/account/quotes/9');
    await user.click(await screen.findByRole('button', { name: 'Accept quote' }));
    await user.click(screen.getByRole('button', { name: 'Cancel' }));
    // Focus goes back to the button that opened the confirmation.
    await waitFor(() => expect(screen.getByRole('button', { name: 'Accept quote' })).toHaveFocus());
    expect(calls.filter((call) => call.method === 'POST')).toHaveLength(0);
  });

  it('declines with an optional reason', async () => {
    const user = userEvent.setup();
    const { calls } = stubAccountFetch([
      ME,
      {
        path: '/api/v1/account/quotes/9/decline',
        method: 'POST',
        body: detail({ status: 'declined', can_answer: false, decline_reason: 'Too expensive' }),
      },
      { path: '/api/v1/account/quotes/9', method: 'GET', body: detail() },
    ]);
    renderAccount('/account/quotes/9');
    await user.click(await screen.findByRole('button', { name: 'Decline quote' }));
    await user.type(screen.getByRole('textbox', { name: /Reason/ }), 'Too expensive');
    await user.click(screen.getByRole('button', { name: 'Decline the quote' }));
    expect(await screen.findByText('Quote declined.')).toBeInTheDocument();
    const post = calls.find((call) => call.method === 'POST');
    expect(JSON.parse(post.init.body)).toEqual({ reason: 'Too expensive' });
    expect(screen.getByText('Your reason: Too expensive')).toBeInTheDocument();
  });

  it('declining without a reason sends an empty body', async () => {
    const user = userEvent.setup();
    const { calls } = stubAccountFetch([
      ME,
      {
        path: '/api/v1/account/quotes/9/decline',
        method: 'POST',
        body: detail({ status: 'declined', can_answer: false }),
      },
      { path: '/api/v1/account/quotes/9', method: 'GET', body: detail() },
    ]);
    renderAccount('/account/quotes/9');
    await user.click(await screen.findByRole('button', { name: 'Decline quote' }));
    await user.click(screen.getByRole('button', { name: 'Decline the quote' }));
    await screen.findByText('Quote declined.');
    expect(JSON.parse(calls.find((call) => call.method === 'POST').init.body)).toEqual({});
  });

  it('a replaced quote offers no buttons, and a conflict is said in words', async () => {
    stubAccountFetch([
      ME,
      {
        path: '/api/v1/account/quotes/9',
        method: 'GET',
        body: detail({ status: 'withdrawn', can_answer: false, closed_reason: 'withdrawn' }),
      },
    ]);
    renderAccount('/account/quotes/9');
    expect(await screen.findByText(/Solaris Express withdrew this quote/)).toBeInTheDocument();
    expect(screen.getByText('No longer valid')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Accept quote' })).toBeNull();
  });

  it('an unknown or foreign quote is one not-found page', async () => {
    stubAccountFetch([
      ME,
      {
        path: '/api/v1/account/quotes/77',
        method: 'GET',
        status: 404,
        body: { code: 'not_found', message: 'That quote does not exist.', field: null },
      },
    ]);
    renderAccount('/account/quotes/77');
    expect(await screen.findByText('We could not find that quote.')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Back to all quotes' })).toHaveAttribute(
      'href',
      '/account/quotes',
    );
  });

  it('reads in Vietnamese first', async () => {
    stubAccountFetch([
      { path: '/api/v1/account/me', body: meFixture({ preferred_language: 'vi' }) },
      { path: '/api/v1/account/quotes/9', method: 'GET', body: detail() },
    ]);
    renderAccount('/account/quotes/9', { locale: null });
    expect(
      await screen.findByRole('heading', { name: 'Báo giá cho lô hàng SX-VCA-7K9D2M4R8T6W', level: 1 }),
    ).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Chấp nhận báo giá' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Từ chối báo giá' })).toBeInTheDocument();
    expect(screen.getByText('Cước vận chuyển Air Standard')).toBeInTheDocument();
  });

  it('is behind the same guard as the profile', async () => {
    stubAccountFetch([
      {
        path: '/api/v1/account/me',
        body: meFixture({ status: 'pending_approval', linked: false, shipment_history_available: false }),
      },
    ]);
    renderAccount('/account/quotes');
    expect(
      await screen.findByRole('heading', { name: 'Your account is being reviewed', level: 1 }),
    ).toBeInTheDocument();
  });

  it('says the quote is being updated while staff re-price it', async () => {
    stubAccountFetch([
      ME,
      {
        path: '/api/v1/account/quotes/9',
        method: 'GET',
        body: detail({ can_answer: false, closed_reason: 'updating' }),
      },
    ]);
    renderAccount('/account/quotes/9');
    expect(await screen.findByText(/Solaris Express is updating this quote/)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Accept quote' })).toBeNull();
  });

  it('says a replaced quote was replaced, and words the weight per locale', async () => {
    stubAccountFetch([
      ME,
      {
        path: '/api/v1/account/quotes/9',
        method: 'GET',
        body: detail({ status: 'withdrawn', can_answer: false, closed_reason: 'replaced', billable_weight_kg: '12.500' }),
      },
    ]);
    renderAccount('/account/quotes/9');
    expect(await screen.findByText(/replaced by a newer one/)).toBeInTheDocument();
    expect(screen.queryByText(/withdrew this quote/)).toBeNull();
    expect(screen.getByText('12.5 kg')).toBeInTheDocument();
  });
});
