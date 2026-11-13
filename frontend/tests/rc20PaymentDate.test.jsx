/**
 * RC-20 (owner, 2026-10-23): a payment received on 20 September was shown as 19 September.
 *
 * The received date is a plain calendar date. The API sends it as midnight of that day
 * (`2026-09-20T00:00:00`); read as a UTC instant and shown in Toronto that is 19 September
 * 20:00. These tests run in a UTC-negative zone (America/Toronto, set before any `Date` is
 * made; the first test proves the zone took effect) so the off-by-one would show.
 *
 * Rows recorded before the fix hold a real naive-UTC instant (`2026-09-20T02:30:00`); they
 * keep the Toronto date they always showed (`formatReceivedDate`).
 */

process.env.TZ = 'America/Toronto';

import { afterEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, screen, waitFor } from '@testing-library/react';
import { Route, Routes } from 'react-router-dom';
import { SessionProvider } from '../src/app/SessionContext.jsx';
import { InvoicePage } from '../src/features/finance/InvoicePage.jsx';
import { ReceiptPrintPage } from '../src/features/finance/PrintPages.jsx';
import { formatDate, formatPlainDate, formatReceivedDate, localToday } from '../src/utils/format.js';
import { renderWithProviders, stubFetch } from './utils.jsx';

const SESSION = {
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
    permissions: ['dashboard:read', 'shipment:read', 'financial:read', 'financial:write'],
    environment: 'test',
    is_demo_environment: false,
  },
};

const PAYMENT = {
  id: 41,
  kind: 'payment',
  receipt_public_id: 'RCT-000041',
  refund_of_payment_id: null,
  amount_cad: '20.00',
  currency: 'CAD',
  method: 'e_transfer',
  reference: null,
  note: null,
  received_at: '2026-09-20T00:00:00',
  recorded_at: '2026-09-21T01:05:00',
};

const INVOICE = {
  id: 7,
  public_id: 'INV-000007',
  shipment_id: 5,
  shipment_reference: 'SX-VCA-TESTREF00001',
  customer_id: 2,
  customer_name: 'Test Customer',
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
  period_month: '2026-09',
  is_adjustment: false,
  issued_at: '2026-09-15T14:00:00',
  due_at: '2026-09-15T14:00:00',
  voided_at: null,
  void_reason: null,
  lines: [{ sequence: 1, description: 'Air Standard, 3 kg', quantity: '3.000', unit: 'kg', amount_cad: '54.00' }],
  payments: [PAYMENT],
};

const RECEIPT = {
  company_name: 'Solaris Express Inc.',
  company_trade_name: 'Solaris Express',
  company_business_number: '000000000RT0001',
  company_address: 'Test address',
  amount_received_vnd: null,
  conversion_vnd_per_cad: null,
  receipt_number: 'RCT-000041',
  invoice_number: 'INV-000007',
  received_at: '2026-09-20T00:00:00',
  amount_cad: '20.00',
  method: 'e_transfer',
  reference: null,
  customer_name: 'Test Customer',
  customer_reference: 'STCA-000002',
  shipment_reference: 'SX-VCA-TESTREF00001',
  invoice_total_cad: '54.00',
  balance_cad: '34.00',
};

afterEach(() => {
  vi.useRealTimers();
});

describe('RC-20: a payment received date is a plain date', () => {
  it('runs in a UTC-negative zone', () => {
    // 20 September 2026 is daylight time in Toronto: UTC-4.
    expect(new Date(2026, 8, 20).getTimezoneOffset()).toBe(240);
  });

  it('formatDate shows the stored midnight a day early; formatPlainDate does not', () => {
    // The bug, reproduced: midnight read as UTC, shown in Toronto.
    expect(formatDate('2026-09-20T00:00:00')).toBe('Sep 19, 2026');
    expect(formatPlainDate('2026-09-20T00:00:00')).toBe('Sep 20, 2026');
    expect(formatPlainDate('2026-09-20')).toBe('Sep 20, 2026');
    expect(formatPlainDate('2026-09-20T00:00:00-04:00')).toBe('Sep 20, 2026');
    expect(formatPlainDate(null)).toBe('—');
  });

  it('formatReceivedDate: plain or midnight as written; a legacy instant as before the fix', () => {
    expect(formatReceivedDate('2026-09-20T00:00:00')).toBe('Sep 20, 2026');
    expect(formatReceivedDate('2026-09-20')).toBe('Sep 20, 2026');
    expect(formatReceivedDate('2026-09-20T00:00')).toBe('Sep 20, 2026');
    expect(formatReceivedDate('2026-09-20T00:00:00.000000')).toBe('Sep 20, 2026');
    expect(formatReceivedDate('2026-09-20T00:00:00Z')).toBe('Sep 20, 2026');
    expect(formatReceivedDate('2026-09-20T00:00:00+00:00')).toBe('Sep 20, 2026');
    // Recorded before the fix: 02:30 UTC is 19 September 22:30 in Toronto, as it always showed.
    expect(formatReceivedDate('2026-09-20T02:30:00')).toBe('Sep 19, 2026');
    expect(formatReceivedDate('2026-09-20T02:30:00')).toBe(formatDate('2026-09-20T02:30:00'));
    expect(formatReceivedDate('2026-09-20T00:00:01')).toBe('Sep 19, 2026');
    expect(formatReceivedDate('2026-09-20T15:00:00')).toBe('Sep 20, 2026');
    expect(formatReceivedDate(null)).toBe('—');
    expect(formatReceivedDate('')).toBe('—');
  });

  it('the payment table shows a legacy row on its old date and a plain row as written', async () => {
    const legacy = { ...PAYMENT, id: 42, receipt_public_id: 'RCT-000042', received_at: '2026-09-11T02:30:00' };
    const afternoon = { ...PAYMENT, id: 43, receipt_public_id: 'RCT-000043', received_at: '2026-09-12T15:00:00' };
    stubFetch([{ path: '/invoices/7', body: { ...INVOICE, payments: [PAYMENT, legacy, afternoon] } }, SESSION]);
    renderWithProviders(
      <SessionProvider>
        <Routes>
          <Route path="/finance/invoices/:invoiceId" element={<InvoicePage />} />
        </Routes>
      </SessionProvider>,
      { route: '/finance/invoices/7' },
    );
    expect(await screen.findByText('Sep 20, 2026')).toBeInTheDocument();
    expect(screen.getByText('Sep 10, 2026')).toBeInTheDocument();
    expect(screen.queryByText('Sep 11, 2026')).not.toBeInTheDocument();
    expect(screen.getByText('Sep 12, 2026')).toBeInTheDocument();
  });

  it("today is the local date on a Toronto evening, not tomorrow's UTC date", () => {
    // 21:30 on 23 October in Toronto is 01:30 on 24 October UTC.
    const evening = new Date('2026-10-24T01:30:00Z');
    expect(evening.toISOString().slice(0, 10)).toBe('2026-10-24');
    expect(localToday(evening)).toBe('2026-10-23');
  });

  it('the invoice page lists the payment on 20 September and sends a plain date', async () => {
    vi.useFakeTimers({ toFake: ['Date'] });
    vi.setSystemTime(new Date('2026-10-24T01:30:00Z'));
    const fetchMock = stubFetch([
      { path: '/invoices/7/payments', method: 'POST', body: INVOICE },
      { path: '/invoices/7', body: INVOICE },
      SESSION,
    ]);
    renderWithProviders(
      <SessionProvider>
        <Routes>
          <Route path="/finance/invoices/:invoiceId" element={<InvoicePage />} />
        </Routes>
      </SessionProvider>,
      { route: '/finance/invoices/7' },
    );
    expect(await screen.findByText('Sep 20, 2026')).toBeInTheDocument();
    expect(screen.queryByText('Sep 19, 2026')).not.toBeInTheDocument();
    const received = screen.getByLabelText('Received on');
    expect(received).toHaveValue('2026-10-23');
    fireEvent.change(received, { target: { value: '2026-09-20' } });
    fireEvent.change(screen.getByLabelText(/Amount received \(CAD\)/), { target: { value: '5.00' } });
    fireEvent.click(screen.getByRole('button', { name: 'Record payment' }));
    await waitFor(() =>
      expect(fetchMock.mock.calls.some(([, init]) => (init?.method || 'GET').toUpperCase() === 'POST')).toBe(true),
    );
    const [, init] = fetchMock.mock.calls.find(([, call]) => (call?.method || 'GET').toUpperCase() === 'POST');
    expect(JSON.parse(init.body).received_at).toBe('2026-09-20');
  });

  it('the receipt of a payment recorded before the fix prints its old (Toronto) date', async () => {
    stubFetch([{ path: '/payments/41/receipt', body: { ...RECEIPT, received_at: '2026-09-20T02:30:00' } }, SESSION]);
    renderWithProviders(
      <SessionProvider>
        <Routes>
          <Route path="/finance/receipts/:paymentId/print" element={<ReceiptPrintPage />} />
        </Routes>
      </SessionProvider>,
      { route: '/finance/receipts/41/print' },
    );
    expect(await screen.findByText('Sep 19, 2026')).toBeInTheDocument();
    expect(screen.queryByText('Sep 20, 2026')).not.toBeInTheDocument();
  });

  it('the receipt prints 20 September', async () => {
    stubFetch([{ path: '/payments/41/receipt', body: RECEIPT }, SESSION]);
    renderWithProviders(
      <SessionProvider>
        <Routes>
          <Route path="/finance/receipts/:paymentId/print" element={<ReceiptPrintPage />} />
        </Routes>
      </SessionProvider>,
      { route: '/finance/receipts/41/print' },
    );
    expect(await screen.findByText('Sep 20, 2026')).toBeInTheDocument();
    expect(screen.queryByText('Sep 19, 2026')).not.toBeInTheDocument();
  });
});
