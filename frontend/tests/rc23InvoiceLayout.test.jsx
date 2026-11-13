/**
 * RC-UAT-23: invoices follow the Solaris Invoicing desk rules (owner Ben, 2026-10-24;
 * DEC-0235). Mocked API; demo data only.
 *
 * * The draft invoice editor keeps the all-in amounts in included mode, and shows the saved
 *   draft as the issued invoice will: per line Qty, Rate, the amount before tax, the tax code
 *   and the tax, then Subtotal, the tax row(s) and Total -- all from the server's breakdown.
 * * The form's preview (what the confirmation echoes) works the tax out line by line.
 * * The staff invoice detail shows the new columns for an `invoicing_v1` invoice and the old
 *   ones for an invoice issued before; the print page follows.
 */

import { describe, expect, it } from 'vitest';
import { screen, within } from '@testing-library/react';
import { Route, Routes } from 'react-router-dom';
import { SessionProvider } from '../src/app/SessionContext.jsx';
import { InvoiceDraftPage, taxPreview } from '../src/features/finance/InvoiceDraftPage.jsx';
import { InvoicePage } from '../src/features/finance/InvoicePage.jsx';
import { InvoicePrintPage } from '../src/features/finance/PrintPages.jsx';
import { renderWithProviders, stubFetch } from './utils.jsx';

const OPS = ['shipment:read', 'shipment:write', 'tariff:read', 'financial:read', 'financial:write'];

function sessionRoute(permissions = OPS) {
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

function render(ui, route, routes) {
  stubFetch([...routes, sessionRoute()]);
  return renderWithProviders(<SessionProvider>{ui}</SessionProvider>, { route });
}

/** A Nova Scotia draft: two all-in lines at 14 %, the second one needs the cent nudge. */
function draft(overrides = {}) {
  return {
    id: 7,
    shipment_id: 5,
    shipment_reference: 'SX-CAD-AAAA05',
    consolidation_id: 3,
    customer_id: 2,
    customer_name: 'Lan Tran',
    quote_version_id: 9,
    quote_version: 1,
    offer_id: 4,
    status: 'draft',
    bill_to_name: 'Lan Tran',
    bill_to_address: '12 Main St, Halifax NS',
    customer_reference: null,
    notes: null,
    tax_rate_percent: 14,
    tax_mode: 'included',
    tax_rate_required: false,
    tax_label: 'HST',
    allowed_tax_rates: [0, 5, 13, 14, 15],
    tax_route: {
      route_band: 'domestic',
      origin_country_code: 'CA',
      destination_country_code: 'CA',
      destination_province: 'NS',
      suggested_rate_percent: 14,
      suggested_mode: 'included',
    },
    tax_confirmed: true,
    tax_confirmed_at: '2026-10-24T10:00:00',
    tax_confirmed_by: 'ops@demo.example.com',
    lines: [
      { description: 'Courier freight', amount_cad: '114.00' },
      { description: 'Fuel surcharge', amount_cad: '0.12' },
    ],
    tax_layout: 'invoicing_v1',
    tax_lines: [
      {
        description: 'Courier freight',
        quantity: '1',
        unit_price_cad: '100.0000',
        net_cad: '100.00',
        tax_cad: '14.00',
        gross_cad: '114.00',
        tax_code: 'HST 14%',
      },
      {
        description: 'Fuel surcharge',
        quantity: '1',
        unit_price_cad: '0.1000',
        net_cad: '0.10',
        tax_cad: '0.02',
        gross_cad: '0.12',
        tax_code: 'HST 14%',
      },
    ],
    tax_rows: [{ label: 'HST @ 14%', tax_cad: '14.02' }],
    lines_total_cad: '114.12',
    subtotal_cad: '100.10',
    tax_cad: '14.02',
    total_cad: '114.12',
    quote_total_cad: '114.12',
    total_change_reason: null,
    revision: 2,
    created_at: '2026-10-24T09:00:00',
    updated_at: '2026-10-24T10:00:00',
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

function renderDraft(body) {
  return render(
    <Routes>
      <Route path="/finance/invoice-drafts/:draftId" element={<InvoiceDraftPage />} />
    </Routes>,
    '/finance/invoice-drafts/7',
    [{ path: '/invoice-drafts/7', body }],
  );
}

describe('taxPreview: line by line (DEC-0235)', () => {
  it('backs each line out and sums, nudging a line by the cent', () => {
    // 0.12 at 14 %: net 0.11 + tax 0.02 = 0.13, nudged to net 0.10.
    expect(
      taxPreview([{ amount_cad: '114.00' }, { amount_cad: '0.12' }], 14, 'included'),
    ).toEqual({ subtotal_cad: '100.10', tax_cad: '14.02', total_cad: '114.12' });
    // The owner's example: 60 x 2.00 = 120.00 at 5 %.
    expect(taxPreview([{ amount_cad: '120.00' }], '5', 'included')).toEqual({
      subtotal_cad: '114.29',
      tax_cad: '5.71',
      total_cad: '120.00',
    });
  });

  it('adds the tax per line on top, and nothing when zero-rated', () => {
    // 0.10 + 0.10 at 5 %: 0.01 per line (the whole total would give 0.01).
    expect(taxPreview([{ amount_cad: '0.10' }, { amount_cad: '0.10' }], 5, 'added')).toEqual({
      subtotal_cad: '0.20',
      tax_cad: '0.02',
      total_cad: '0.22',
    });
    expect(taxPreview([{ amount_cad: '50.00' }, { amount_cad: '3.33' }], 0, 'included')).toEqual({
      subtotal_cad: '53.33',
      tax_cad: '0.00',
      total_cad: '53.33',
    });
  });
});

describe('Draft invoice: the invoice as it will be issued', () => {
  it('shows the server breakdown per line and the summary rows', async () => {
    renderDraft(draft());
    const preview = await screen.findByTestId('draft-invoice-preview');
    expect(within(preview).getByText('As the invoice will show it')).toBeInTheDocument();
    const headers = within(preview)
      .getAllByRole('columnheader')
      .map((cell) => cell.textContent);
    expect(headers).toEqual(['Description', 'Quantity', 'Rate', 'Amount before tax', 'Tax', 'Tax (CAD)']);
    const rows = within(preview).getAllByRole('row').slice(1);
    expect(rows).toHaveLength(2);
    const second = within(rows[1])
      .getAllByRole('cell')
      .map((cell) => cell.textContent);
    expect(second[0]).toBe('Fuel surcharge');
    expect(second[1]).toBe('1');
    expect(second[2]).toBe('0.1000');
    expect(second[3]).toMatch(/0\.10/);
    expect(second[4]).toBe('HST 14%');
    expect(second[5]).toMatch(/0\.02/);
    const summary = screen.getByTestId('draft-invoice-preview-summary');
    expect(summary).toHaveTextContent(/Subtotal.*100\.10/);
    expect(summary).toHaveTextContent(/HST @ 14%.*14\.02/);
    expect(summary).toHaveTextContent(/Total \(CAD\).*114\.12/);
    // The editor keeps the all-in amounts.
    expect(screen.getByLabelText('Amount (CAD), line 1')).toHaveValue('114.00');
    expect(preview.textContent).not.toMatch(/included/i);
  });

  it('shows no preview while no rate is chosen', async () => {
    renderDraft(
      draft({
        tax_rate_percent: null,
        tax_rate_required: true,
        tax_confirmed: false,
        tax_lines: null,
        tax_rows: null,
        subtotal_cad: null,
        tax_cad: null,
        total_cad: null,
      }),
    );
    expect(await screen.findByLabelText('Amount (CAD), line 1')).toBeInTheDocument();
    expect(screen.queryByTestId('draft-invoice-preview')).not.toBeInTheDocument();
  });
});

/* --- The issued invoice ------------------------------------------------------------------ */

const INVOICE = {
  id: 9,
  public_id: 'INV-000009',
  shipment_id: 5,
  shipment_reference: 'SX-CAD-AAAA05',
  customer_id: 2,
  customer_name: 'Lan Tran',
  customer_reference: 'STCA-000002',
  quote_version_id: 11,
  consolidation_id: 3,
  status: 'issued',
  currency: 'CAD',
  subtotal_cad: '114.29',
  tax_cad: '5.71',
  tax_status: 'gst_hst_5',
  total_cad: '120.00',
  paid_cad: '0.00',
  balance_cad: '120.00',
  period_month: '2026-10',
  is_adjustment: false,
  issued_at: '2026-10-24T10:00:00',
  due_at: '2026-10-24T10:00:00',
  voided_at: null,
  void_reason: null,
  tax_layout: 'invoicing_v1',
  tax_rows: [{ label: 'GST @ 5%', tax_cad: '5.71' }],
  lines: [
    {
      sequence: 1,
      description: 'Courier, 60 boxes',
      quantity: '60.000',
      unit: 'box',
      amount_cad: '114.29',
      unit_price_cad: '1.9048',
      tax_cad: '5.71',
      gross_cad: '120.00',
      tax_code: 'GST',
    },
  ],
  payments: [],
};

function renderInvoice(body) {
  return render(
    <Routes>
      <Route path="/finance/invoices/:invoiceId" element={<InvoicePage />} />
    </Routes>,
    '/finance/invoices/9',
    [{ path: '/invoices/9', body }],
  );
}

describe('Invoice detail: the Solaris Invoicing columns', () => {
  it('shows Qty, Rate, the amount before tax and the tax code, then the summary rows', async () => {
    renderInvoice(INVOICE);
    const lines = await screen.findByTestId('invoice-invoicing-lines');
    const headers = within(lines)
      .getAllByRole('columnheader')
      .map((cell) => cell.textContent);
    expect(headers).toEqual(['Description', 'Quantity', 'Rate', 'Amount', 'Tax']);
    const cells = within(within(lines).getAllByRole('row')[1])
      .getAllByRole('cell')
      .map((cell) => cell.textContent);
    expect(cells[1]).toBe('60 box');
    expect(cells[2]).toBe('1.9048');
    expect(cells[3]).toMatch(/114\.29/);
    expect(cells[4]).toBe('GST');
    const summary = screen.getByTestId('invoice-invoicing-summary');
    expect(summary).toHaveTextContent(/Subtotal.*114\.29/);
    expect(summary).toHaveTextContent(/GST @ 5%.*5\.71/);
  });

  it('shows an invoice issued before as it always did', async () => {
    renderInvoice({
      ...INVOICE,
      tax_layout: null,
      tax_rows: null,
      lines: [
        {
          sequence: 1,
          description: 'Courier, 60 boxes',
          quantity: null,
          unit: null,
          amount_cad: '120.00',
          unit_price_cad: null,
          tax_cad: null,
          gross_cad: null,
          tax_code: null,
        },
      ],
    });
    expect(await screen.findByText('Courier, 60 boxes')).toBeInTheDocument();
    expect(screen.queryByTestId('invoice-invoicing-lines')).not.toBeInTheDocument();
    const headers = screen.getAllByRole('columnheader').map((cell) => cell.textContent);
    expect(headers.slice(0, 3)).toEqual(['Description', 'Quantity', 'Amount']);
    expect(headers).not.toContain('Rate');
  });
});

describe('Invoice print page: the Solaris Invoicing layout', () => {
  it('prints the columns, the summary rows, the terms and how to pay', async () => {
    const { container } = render(
      <Routes>
        <Route path="/finance/invoices/:invoiceId/print" element={<InvoicePrintPage />} />
      </Routes>,
      '/finance/invoices/9/print',
      [
        {
          path: '/invoices/9/document',
          body: {
            company_name: 'Solaris Express Inc.',
            company_trade_name: 'Solaris Express',
            company_business_number: '795093756RT0001',
            company_address: '2446 Cawthra Rd Building 1 Unit 8, Mississauga ON L5A 3K6',
            company_email: 'solarisexpressinc@gmail.com',
            invoice_number: 'INV-000009',
            status: 'issued',
            issued_at: '2026-10-24T10:00:00',
            due_at: '2026-10-24T10:00:00',
            customer_name: 'Lan Tran',
            customer_reference: 'STCA-000002',
            shipment_reference: 'SX-CAD-AAAA05',
            service: 'Courier',
            currency: 'CAD',
            lines: [
              {
                description: 'Courier, 60 boxes',
                quantity: '60',
                unit: 'box',
                amount_cad: '114.29',
                unit_price_cad: '1.9048',
                tax_cad: '5.71',
                gross_cad: '120.00',
                tax_code: 'GST',
              },
            ],
            subtotal_cad: '114.29',
            tax_cad: '5.71',
            tax_status: 'gst_hst_5',
            tax_mode: 'included',
            tax_included_note: null,
            tax_label: 'GST',
            tax_line_label: 'GST @ 5%',
            total_cad: '120.00',
            paid_cad: '0.00',
            balance_cad: '120.00',
            tax_layout: 'invoicing_v1',
            tax_rows: [{ label: 'GST @ 5%', tax_cad: '5.71' }],
            payment_terms: 'Due on receipt',
            payment_etransfer: 'info@solarisexpress.ca',
            payment_wire: 'Bank of Montreal · SWIFT BOFMCAM2 · Account 1969380',
          },
        },
      ],
    );
    expect(await screen.findByText('solarisexpressinc@gmail.com')).toBeInTheDocument();
    expect(screen.getByText('GST @ 5%')).toBeInTheDocument();
    expect(screen.getByText('1.9048')).toBeInTheDocument();
    expect(screen.getByText('Terms: Due on receipt')).toBeInTheDocument();
    expect(screen.getByText('Payment: E-transfer to info@solarisexpress.ca')).toBeInTheDocument();
    expect(container.textContent).not.toMatch(/Prices include|Subtotal before/);
  });
});
