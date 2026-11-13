/**
 * RC-UAT-25 items 7 and 8 (Ben 2026-10-25): the shipment page's Financials tab.
 *
 * 7. Ben added financial info and `/shipments/<id>?tab=financials` went blank. The recorded
 *    currency was stored as typed ("CA", "$"); `formatMoney` passed it to Intl.NumberFormat,
 *    which throws a RangeError for it, and with no error boundary the page unmounted. Here the
 *    tab renders against every shape the backend produces (captured from the real API by
 *    `backend/tests/test_rc25_financials_tab.py` with RC25_FIXTURE_OUT), a stored bad code, and
 *    a panel that throws anyway.
 * 8. The quote / cost summary and the next step: price, finalise, issue, review the draft, open
 *    the invoice; cost only for a role allowed vendor cost; Issue invoice disabled with the
 *    server's refusal when blocked.
 */

import { describe, expect, it, vi } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Route, Routes } from 'react-router-dom';
import { ShipmentDetailPage } from '../src/features/shipments/ShipmentDetailPage.jsx';
import { SessionProvider } from '../src/app/SessionContext.jsx';
import { PanelErrorBoundary } from '../src/components/state/PanelErrorBoundary.jsx';
import { formatMoney, isFormattableCurrency } from '../src/utils/format.js';
import { renderWithProviders, stubFetch } from './utils.jsx';
import { SHIPMENT_META, STAFF_SESSION } from './shipmentFixtures.js';
import SHAPES from './fixtures/rc25Financials.json';

const ADMIN = {
  ...STAFF_SESSION,
  permissions: [...STAFF_SESSION.permissions, 'tariff:read'],
};
const READ_ONLY_MANAGER = {
  ...STAFF_SESSION,
  user: { ...STAFF_SESSION.user, role: 'read_only_manager' },
  permissions: ['shipment:read', 'financial:read', 'customer:read'],
};

function renderTab(shape, { session = ADMIN, summary, shipment, extraRoutes = [] } = {}) {
  const ship = shipment ?? shape.shipment;
  const id = ship.id;
  const fetchMock = stubFetch([
    ...extraRoutes,
    { path: '/auth/me', body: session },
    { path: '/shipments/meta', body: SHIPMENT_META },
    { path: `/shipments/${id}/legs`, body: [] },
    { path: `/shipments/${id}/events`, body: [] },
    { path: `/shipments/${id}/financial-summary`, body: summary ?? shape.summary },
    { path: '/audit', body: { items: [], total: 0, limit: 50, offset: 0 } },
    { path: `/shipments/${id}`, body: ship },
  ]);
  const utils = renderWithProviders(
    <SessionProvider>
      <Routes>
        <Route path="/shipments/:shipmentId" element={<ShipmentDetailPage />} />
      </Routes>
    </SessionProvider>,
    { route: `/shipments/${id}?tab=financials` },
  );
  return { ...utils, fetchMock };
}

async function nextStep() {
  return screen.findByTestId('fin-next-step');
}

describe('formatMoney never throws (the blank page)', () => {
  it('formats a code Intl refuses as the amount with the code as stored', () => {
    const plain = (text) => text.replace(/\u00a0/g, ' ');
    expect(() => formatMoney('120', 'CA')).not.toThrow();
    expect(plain(formatMoney('120', 'CA'))).toBe('CA 120.00');
    expect(plain(formatMoney('5', '$'))).toBe('$ 5.00');
    expect(plain(formatMoney('120', 'CAD'))).toBe('CAD 120.00');
    expect(formatMoney(null, 'CA')).toBe('Unknown');
    expect(isFormattableCurrency('CA')).toBe(false);
    expect(isFormattableCurrency('VND')).toBe(true);
    expect(isFormattableCurrency(null)).toBe(true);
  });
});

describe('Financials tab against every captured API shape', () => {
  for (const [name, shape] of Object.entries(SHAPES)) {
    it(`renders "${name}" with the summary and the recorded amounts`, async () => {
      renderTab(shape);
      const step = await nextStep();
      expect(step).toHaveAttribute('data-step', shape.summary.next_step);
      expect(screen.getByText('Recorded amounts')).toBeInTheDocument();
      expect(screen.getAllByText('Quote and invoice').length).toBeGreaterThan(0);
      expect(screen.queryByText('This section could not be shown')).toBeNull();
      if (shape.summary.quote) {
        expect(screen.getByText('Quoted revenue')).toBeInTheDocument();
        expect(screen.getByText('Vendor cost')).toBeInTheDocument();
      }
    });
  }

  it('a shipment in no master points to the Workspace', async () => {
    renderTab(SHAPES.no_master);
    const step = await nextStep();
    expect(within(step).getByText(/Not in a master yet/)).toBeInTheDocument();
    expect(within(step).getByRole('link', { name: 'Open the Workspace' })).toHaveAttribute(
      'href',
      '/workspace',
    );
    // Issue invoice is shown, disabled, with the server's own refusal.
    expect(within(step).getByRole('button', { name: 'Issue invoice' })).toBeDisabled();
    expect(
      within(step).getByText(/Finalise the shipment's quote before issuing an invoice\./),
    ).toBeInTheDocument();
  });

  it('an unpriced shipment in a master offers Price this shipment in its master', async () => {
    const shape = SHAPES.unpriced;
    renderTab(shape);
    const step = await nextStep();
    expect(within(step).getByRole('link', { name: 'Price this shipment' })).toHaveAttribute(
      'href',
      `/workspace/${shape.summary.master.id}`,
    );
    expect(screen.getByText('No quote yet')).toBeInTheDocument();
  });

  it('a draft quote asks to finalise it', async () => {
    renderTab(SHAPES.draft_quote);
    const step = await nextStep();
    expect(within(step).getByRole('link', { name: 'Finalise quote' })).toBeInTheDocument();
    expect(screen.getByText(/v1 · Draft \(not finalised\)/)).toBeInTheDocument();
  });

  it('a finalised quote shows revenue and cost and issues the invoice', async () => {
    const user = userEvent.setup();
    const shape = SHAPES.finalised;
    const issued = vi.fn(() => ({ id: 99, public_id: 'INV-000099' }));
    const { fetchMock } = renderTab(shape, {
      extraRoutes: [
        {
          path: `/shipments/${shape.shipment.id}/invoice`,
          method: 'POST',
          status: 201,
          body: issued,
        },
      ],
    });
    const step = await nextStep();
    expect(screen.getByText('CAD 54.00')).toBeInTheDocument();
    await user.selectOptions(within(step).getByLabelText('GST/HST'), '5');
    await user.click(within(step).getByRole('button', { name: 'Issue invoice' }));
    await waitFor(() => expect(issued).toHaveBeenCalled());
    const call = fetchMock.mock.calls.find(
      ([url, init]) => String(url).includes('/invoice') && init?.method === 'POST',
    );
    expect(JSON.parse(call[1].body)).toEqual({ tax_rate_percent: 5 });
  });

  it('an accepted quote leads to its draft invoice', async () => {
    const shape = SHAPES.accepted_draft_included_tax;
    renderTab(shape);
    const step = await nextStep();
    expect(within(step).getByRole('link', { name: 'Review draft invoice' })).toHaveAttribute(
      'href',
      `/finance/invoice-drafts/${shape.summary.draft_invoice.id}`,
    );
  });

  it('an issued invoice opens by its number with its balance', async () => {
    const shape = SHAPES.issued_paid_refunded;
    renderTab(shape);
    const step = await nextStep();
    const number = shape.summary.invoice.public_id;
    expect(within(step).getByRole('link', { name: `Open invoice ${number}` })).toHaveAttribute(
      'href',
      `/finance/invoices/${shape.summary.invoice.id}`,
    );
    expect(screen.getByText(/Balance CAD 4\.00/)).toBeInTheDocument();
  });

  it('a blocked invoice (expired quote) is disabled with the refusal', async () => {
    const shape = SHAPES.finalised;
    const reason =
      'Quote v1 expired when a new tariff became active: re-quote on the new rate before invoicing.';
    renderTab(shape, {
      summary: {
        ...shape.summary,
        next_step: 'requote',
        invoice_blocked_reason: reason,
        invoice_blocked_code: 'quote_expired',
        quote: { ...shape.summary.quote, expired: true },
      },
    });
    const step = await nextStep();
    expect(within(step).getByRole('button', { name: 'Issue invoice' })).toBeDisabled();
    expect(within(step).getByText(new RegExp(reason.slice(0, 40)))).toBeInTheDocument();
    expect(within(step).getByRole('link', { name: 'Re-quote in the master' })).toBeInTheDocument();
  });
});

describe('roles', () => {
  it('the read-only manager sees revenue, no vendor cost and no invoice action', async () => {
    const shape = SHAPES.finalised;
    const summary = {
      ...shape.summary,
      cost_visible: false,
      can_issue_invoice: false,
      can_price: false,
      quote: { ...shape.summary.quote, allocated_cost_cad: null, gross_profit_cad: null },
    };
    const { costs: _hidden, ...financials } = shape.shipment.financials;
    renderTab(shape, {
      session: READ_ONLY_MANAGER,
      summary,
      shipment: { ...shape.shipment, financials },
    });
    const step = await nextStep();
    expect(screen.getByText('Quoted revenue')).toBeInTheDocument();
    expect(screen.queryByText('Vendor cost')).toBeNull();
    expect(screen.getByText('Vendor cost is not shown for your role.')).toBeInTheDocument();
    expect(within(step).getByRole('button', { name: 'Issue invoice' })).toBeDisabled();
    expect(within(step).getByText(/Your role cannot issue invoices/)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Save amounts' })).toBeNull();
  });
});

describe('the recorded currency (the root cause)', () => {
  it('a currency stored before the fix ("CA") no longer blanks the page', async () => {
    const shape = SHAPES.no_master_amount_only;
    const shipment = {
      ...shape.shipment,
      financials: {
        ...shape.shipment.financials,
        currency: 'CA',
        selling_amount: '120.00',
        costs: { shipping_cost: '70.00', surcharges_amount: null, gross_profit: '50.00' },
      },
    };
    renderTab(shape, { shipment });
    await nextStep();
    expect(screen.getByText('CA 120.00')).toBeInTheDocument();
    expect(screen.getByText('CA 50.00')).toBeInTheDocument();
    expect(screen.getByText(/The recorded currency "CA" is not a three-letter code/)).toBeVisible();
    // The page header is still there.
    expect(screen.getByRole('tablist', { name: 'Shipments' })).toBeInTheDocument();
  });

  it('refuses a two-letter code before saving', async () => {
    const user = userEvent.setup();
    const shape = SHAPES.no_master;
    const { fetchMock } = renderTab(shape);
    await nextStep();
    const input = screen.getByLabelText('Currency');
    await user.clear(input);
    await user.type(input, 'ca');
    await user.click(screen.getByRole('button', { name: 'Save amounts' }));
    expect(
      await screen.findByText('Use a three-letter currency code such as CAD.'),
    ).toBeInTheDocument();
    expect(fetchMock.mock.calls.some(([, init]) => init?.method === 'PATCH')).toBe(false);
  });
});

describe('error boundary', () => {
  it('a panel that throws shows a message and Try again, not a blank page', async () => {
    const user = userEvent.setup();
    const spy = vi.spyOn(console, 'error').mockImplementation(() => {});
    let fail = true;
    function Fragile() {
      if (fail) throw new Error('boom');
      return <p>Recovered</p>;
    }
    renderWithProviders(
      <div>
        <h1>Header stays</h1>
        <PanelErrorBoundary>
          <Fragile />
        </PanelErrorBoundary>
      </div>,
    );
    expect(screen.getByText('This section could not be shown')).toBeInTheDocument();
    expect(screen.getByText('Header stays')).toBeInTheDocument();
    fail = false;
    await user.click(screen.getByRole('button', { name: 'Try again' }));
    expect(screen.getByText('Recovered')).toBeInTheDocument();
    spy.mockRestore();
  });

  it('an unexpected summary payload degrades to a message inside the card', async () => {
    const shape = SHAPES.no_master;
    renderTab(shape, { summary: { unexpected: true } });
    expect(
      await screen.findByText(/The quote and invoice summary could not be loaded\./),
    ).toBeInTheDocument();
    expect(screen.getByText('Recorded amounts')).toBeInTheDocument();
  });
});
