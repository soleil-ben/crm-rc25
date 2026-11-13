/**
 * Phase 13E finance UI: navigation gate, cost tabs behind tariff:read, the invoice page's
 * permission-gated actions, the CAD-only payment note, the print page's draft label and
 * pending tax, and the workspace's "Issue invoice" link. Independent tester's suite;
 * written from the requirements, not the code.
 */

import { describe, expect, it } from 'vitest';
import { screen } from '@testing-library/react';
import { Route, Routes } from 'react-router-dom';
import { SessionProvider } from '../src/app/SessionContext.jsx';
import { AppShell } from '../src/components/layout/AppShell.jsx';
import { FinancePage } from '../src/features/finance/FinancePage.jsx';
import { InvoicePage } from '../src/features/finance/InvoicePage.jsx';
import { InvoicePrintPage } from '../src/features/finance/PrintPages.jsx';
import { InvoiceLink } from '../src/features/workspace/InvoiceLink.jsx';
import { renderWithProviders, stubFetch } from './utils.jsx';

function sessionRoute(role, permissions) {
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

const READ = ['dashboard:read', 'shipment:read', 'financial:read'];
// A writer without financial:adjust (no shipped role is one since OD-69 gave it to
// Operations, but the screen must still hide refund and void from such a role).
const WRITER = [...READ, 'financial:write', 'tariff:read'];
const OPS = [...WRITER, 'financial:adjust'];
const ADMIN = [...OPS, 'export:reports'];

function withSession(permissions, ui, { route = '/', routes = [] } = {}) {
  const fetchMock = stubFetch([...routes, sessionRoute('operations', permissions)]);
  const rendered = renderWithProviders(<SessionProvider>{ui}</SessionProvider>, { route });
  return { fetchMock, ...rendered };
}

/* --- Navigation ----------------------------------------------------------------------- */

function renderShell(permissions) {
  return withSession(
    permissions,
    <Routes>
      <Route path="/" element={<AppShell />}>
        <Route index element={<p>Home</p>} />
      </Route>
    </Routes>,
  );
}

describe('Finance navigation', () => {
  it('shows Finance to a role holding financial:read', async () => {
    renderShell(READ);
    const link = await screen.findByRole('link', { name: 'Finance' });
    expect(link).toHaveAttribute('href', '/finance');
  });

  it('hides Finance from a role without financial:read', async () => {
    renderShell(['dashboard:read', 'shipment:read']);
    expect(await screen.findByRole('link', { name: 'Shipments' })).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: 'Finance' })).not.toBeInTheDocument();
  });
});

/* --- Finance page tabs ---------------------------------------------------------------- */

const EMPTY_LIST = { path: '/invoices', body: { items: [], total: 0 } };

describe('FinancePage', () => {
  it('shows Payables and Profitability only with tariff:read', async () => {
    withSession(OPS, <FinancePage />, { route: '/finance', routes: [EMPTY_LIST] });
    expect(await screen.findByRole('tab', { name: 'Payables' })).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: 'Profitability' })).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: 'Invoices' })).toBeInTheDocument();
  });

  it('hides the cost tabs from a revenue-only reader', async () => {
    withSession(READ, <FinancePage />, { route: '/finance?tab=profitability', routes: [EMPTY_LIST] });
    expect(await screen.findByRole('tab', { name: 'Receivables' })).toBeInTheDocument();
    expect(screen.queryByRole('tab', { name: 'Payables' })).not.toBeInTheDocument();
    expect(screen.queryByRole('tab', { name: 'Profitability' })).not.toBeInTheDocument();
  });
});

/* --- Invoice page --------------------------------------------------------------------- */

const INVOICE = {
  id: 7,
  public_id: 'INV-000007',
  shipment_id: 5,
  shipment_reference: 'SX-VCA-TESTREF00001',
  customer_id: 2,
  customer_name: 'Trần Văn Minh',
  customer_reference: 'STCA-000002',
  quote_version_id: 11,
  consolidation_id: 3,
  status: 'partially_paid',
  currency: 'CAD',
  subtotal_cad: '54.00',
  tax_cad: null,
  tax_status: 'review_pending',
  total_cad: '54.00',
  paid_cad: '20.00',
  balance_cad: '34.00',
  period_month: '2026-10',
  is_adjustment: false,
  issued_at: '2026-10-20T10:00:00',
  due_at: '2026-10-20T10:00:00',
  voided_at: null,
  void_reason: null,
  lines: [{ sequence: 1, description: 'Air Standard, 3 kg', quantity: '3.000', unit: 'kg', amount_cad: '54.00' }],
  payments: [
    {
      id: 41,
      kind: 'payment',
      receipt_public_id: 'RCT-000041',
      refund_of_payment_id: null,
      amount_cad: '20.00',
      currency: 'CAD',
      method: 'e_transfer',
      reference: null,
      note: null,
      received_at: '2026-10-20T00:00:00',
      recorded_at: '2026-10-20T10:05:00',
    },
  ],
};

function renderInvoice(permissions) {
  return withSession(
    permissions,
    <Routes>
      <Route path="/finance/invoices/:invoiceId" element={<InvoicePage />} />
    </Routes>,
    { route: '/finance/invoices/7', routes: [{ path: '/invoices/7', body: INVOICE }] },
  );
}

describe('InvoicePage', () => {
  it('offers the payment form with financial:write, in CAD or VND', async () => {
    renderInvoice(WRITER);
    expect(await screen.findByRole('button', { name: 'Record payment' })).toBeInTheDocument();
    expect(screen.getByText(/selling rate on the invoice date/)).toBeInTheDocument();
    // Without financial:adjust there is no refund or void.
    expect(screen.queryByRole('button', { name: /Refund/ })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Void invoice' })).not.toBeInTheDocument();
  });

  it('has no payment form for a reader without financial:write', async () => {
    renderInvoice(READ);
    expect(await screen.findByText('RCT-000041')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Record payment' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Refund/ })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Void invoice' })).not.toBeInTheDocument();
  });

  it('offers refund and void only with financial:adjust', async () => {
    renderInvoice(ADMIN);
    expect(await screen.findByRole('button', { name: /Refund RCT-000041/ })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Void invoice' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Record payment' })).toBeInTheDocument();
  });
});

/* --- Print page ----------------------------------------------------------------------- */

const DOCUMENT = {
  invoice_number: 'INV-000007',
  status: 'issued',
  issued_at: '2026-10-20T10:00:00',
  due_at: '2026-10-20T10:00:00',
  customer_name: 'Trần Văn Minh',
  customer_reference: 'STCA-000002',
  shipment_reference: 'SX-VCA-TESTREF00001',
  service: 'Air Standard',
  currency: 'CAD',
  lines: [{ description: 'Air Standard, 3 kg', quantity: '3.000', unit: 'kg', amount_cad: '54.00' }],
  subtotal_cad: '54.00',
  tax_cad: '0.00',
  tax_status: 'gst_hst_0',
  company_name: 'Solaris Express Inc.',
  company_trade_name: 'Solaris Express',
  company_business_number: '795093756RT0001',
  company_address: '2446 Cawthra Road B1U8, Mississauga ON L5A 3K6',
  total_cad: '54.00',
  paid_cad: '0.00',
  balance_cad: '54.00',
  // Should a cost field ever leak into the payload, the page must still not show it.
  allocated_cost_cad: '77.77',
  vendor_name: 'Kango Express',
  fx_cash_buy_vnd: '17886.61',
};

describe('InvoicePrintPage', () => {
  it('shows the company, the chosen GST/HST rate, and no cost field', async () => {
    const { container } = withSession(
      READ,
      <Routes>
        <Route path="/finance/invoices/:invoiceId/print" element={<InvoicePrintPage />} />
      </Routes>,
      { route: '/finance/invoices/7/print', routes: [{ path: '/invoices/7/document', body: DOCUMENT }] },
    );
    expect(await screen.findByText(/795093756RT0001/)).toBeInTheDocument();
    expect(screen.getByText(/2446 Cawthra Road/)).toBeInTheDocument();
    expect(screen.getByText('GST/HST 0 %')).toBeInTheDocument();
    expect(screen.queryByText(/Draft for review/)).not.toBeInTheDocument();
    expect(screen.getAllByText(/INV-000007/).length).toBeGreaterThan(0);
    const text = container.textContent;
    for (const leak of ['77.77', 'Kango', '17886', '17,886']) {
      expect(text).not.toContain(leak);
    }
    expect(text).not.toMatch(/cost|margin|exchange rate|vendor/i);
  });
});

/* --- Workspace link ------------------------------------------------------------------- */

describe('InvoiceLink', () => {
  it('offers Issue invoice for a finalised quote with no invoice yet', async () => {
    withSession(
      OPS,
      <InvoiceLink consolidationId={3} shipmentId={5} customerLabel="Trần Văn Minh" refresh={() => {}} />,
      { routes: [{ path: '/shipments/5/invoice', body: null }] },
    );
    expect(await screen.findByRole('button', { name: /Issue invoice/ })).toBeInTheDocument();
  });

  it('links to the invoice once it exists', async () => {
    withSession(
      OPS,
      <InvoiceLink consolidationId={3} shipmentId={5} customerLabel="Trần Văn Minh" refresh={() => {}} />,
      { routes: [{ path: '/shipments/5/invoice', body: INVOICE }] },
    );
    const link = await screen.findByRole('link', { name: 'INV-000007' });
    expect(link).toHaveAttribute('href', '/finance/invoices/7');
    expect(screen.queryByRole('button', { name: /Issue invoice/ })).not.toBeInTheDocument();
  });
});
