/**
 * RC-UAT-20, owner Ben, 2026-10-23. Mocked API; demo data only.
 *
 * * GST/HST by route (DEC-0227): the draft invoice names the route its rate came from, offers
 *   the server's rates (0, 5, 13, 14, 15 and the table's), and -- when a domestic shipment's
 *   province is unknown -- has no rate until staff choose one (Save stays disabled).
 * * Download (DEC-0229) is disabled with the same message as Send until the saved revision's
 *   GST/HST is confirmed.
 * * Settings → GST/HST rates: everyone with financial:read reads the table; Admin edits it.
 */

import { describe, expect, it } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Route, Routes } from 'react-router-dom';
import { SessionProvider } from '../src/app/SessionContext.jsx';
import { InvoiceDraftPage, taxPreview } from '../src/features/finance/InvoiceDraftPage.jsx';
import { TaxRatesPanel, rateError } from '../src/features/settings/TaxRatesPanel.jsx';
import { renderWithProviders, stubFetch } from './utils.jsx';

const OPS = ['shipment:read', 'shipment:write', 'tariff:read', 'financial:read', 'financial:write'];
const ADMIN = [...OPS, 'settings:manage'];

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
    tax_mode: 'included',
    tax_rate_required: false,
    allowed_tax_rates: [0, 5, 13, 14, 15],
    tax_route: {
      route_band: 'international',
      origin_country_code: 'VN',
      destination_country_code: 'CA',
      destination_province: null,
      suggested_rate_percent: 0,
      suggested_mode: 'included',
    },
    tax_confirmed: false,
    tax_confirmed_at: null,
    tax_confirmed_by: null,
    lines: [{ description: 'Air Standard freight', amount_cad: '114.00' }],
    lines_total_cad: '114.00',
    subtotal_cad: '114.00',
    tax_cad: '0.00',
    total_cad: '114.00',
    quote_total_cad: '114.00',
    total_change_reason: null,
    revision: 1,
    created_at: '2026-10-23T10:00:00',
    updated_at: '2026-10-23T10:00:00',
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

function renderDraft(routes, permissions = OPS) {
  stubFetch([...routes, sessionRoute(permissions)]);
  renderWithProviders(
    <SessionProvider>
      <Routes>
        <Route path="/finance/invoice-drafts/:draftId" element={<InvoiceDraftPage />} />
      </Routes>
    </SessionProvider>,
    { route: '/finance/invoice-drafts/7' },
  );
}

const CONFIRM = 'I have checked the GST/HST on this invoice';
const UNCONFIRMED = /GST\/HST of the saved draft is not confirmed: tick the check and save before sending or downloading/;

describe('taxPreview at the new rates', () => {
  it('backs 14 % and 15 % out, half up, and previews nothing without a rate', () => {
    expect(taxPreview([{ amount_cad: '114.00' }], '14', 'included')).toEqual({
      subtotal_cad: '100.00',
      tax_cad: '14.00',
      total_cad: '114.00',
    });
    expect(taxPreview([{ amount_cad: '100.00' }], 15, 'included').tax_cad).toBe('13.04');
    expect(taxPreview([{ amount_cad: '0.07' }], 15, 'included').tax_cad).toBe('0.01');
    // DEC-0235 (per line): net 0.04 -> tax 0.01, the net nudged to 0.03 (the whole-total
    // rule of DEC-0223 read tax 0.00).
    expect(taxPreview([{ amount_cad: '0.04' }], 14, 'included').tax_cad).toBe('0.01');
    expect(taxPreview([{ amount_cad: '10.00' }], '', 'included')).toBeNull();
  });
});

describe('Draft invoice: GST/HST by route', () => {
  it('names an international route, zero-rated, and offers the server rates', async () => {
    renderDraft([
      {
        path: '/invoice-drafts/7',
        body: draft({ allowed_tax_rates: [0, 5, 7, 13, 14, 15] }),
      },
    ]);
    expect(await screen.findByTestId('draft-tax-route')).toHaveTextContent(
      'Route VN → CA: international, zero-rated (0 %).',
    );
    expect(screen.getByTestId('draft-tax-summary')).toHaveTextContent(
      /GST\/HST 0 % \(zero-rated\): no tax, total .*114\.00/,
    );
    const select = screen.getByLabelText('GST/HST');
    expect(select).toHaveValue('0');
    const options = within(select)
      .getAllByRole('option')
      .map((option) => option.value);
    expect(options).toEqual(['0', '5', '7', '13', '14', '15']);
  });

  it('names a domestic route and its province', async () => {
    renderDraft([
      {
        path: '/invoice-drafts/7',
        body: draft({
          tax_rate_percent: 14,
          tax_label: 'HST',
          subtotal_cad: '100.00',
          tax_cad: '14.00',
          tax_route: {
            route_band: 'domestic',
            origin_country_code: 'CA',
            destination_country_code: 'CA',
            destination_province: 'NS',
            suggested_rate_percent: 14,
            suggested_mode: 'included',
          },
        }),
      },
    ]);
    expect(await screen.findByTestId('draft-tax-route')).toHaveTextContent(
      'Route CA → CA: domestic, delivered in NS; 14 % included in the price.',
    );
    // The province table's label (review, 2026-10-24).
    expect(screen.getByTestId('draft-tax-summary')).toHaveTextContent(
      /Tax included in the price: subtotal before tax .*100\.00, HST @ 14% .*14\.00/,
    );
  });

  it('has no rate when the province is unknown: choose one before saving', async () => {
    const user = userEvent.setup();
    let patched = null;
    renderDraft([
      {
        path: '/invoice-drafts/7',
        method: 'PATCH',
        body: (init) => {
          patched = JSON.parse(init.body);
          return draft({
            tax_rate_percent: 13,
            tax_confirmed: true,
            subtotal_cad: '100.88',
            tax_cad: '13.12',
          });
        },
      },
      {
        path: '/invoice-drafts/7',
        body: draft({
          tax_rate_percent: null,
          tax_rate_required: true,
          subtotal_cad: null,
          tax_cad: null,
          total_cad: null,
          tax_route: {
            route_band: 'domestic',
            origin_country_code: 'CA',
            destination_country_code: 'CA',
            destination_province: null,
            suggested_rate_percent: null,
            suggested_mode: 'included',
          },
        }),
      },
    ]);
    expect(await screen.findByTestId('draft-tax-route')).toHaveTextContent(
      'domestic, destination province unknown',
    );
    expect(screen.getByText(/destination province of this domestic shipment is unknown/)).toBeInTheDocument();
    const select = screen.getByLabelText('GST/HST');
    expect(select).toHaveValue('');
    expect(within(select).getByRole('option', { name: 'Choose a rate' })).toBeInTheDocument();
    expect(screen.queryByTestId('draft-tax-summary')).toBeNull();
    expect(screen.getByText(/No rate chosen yet/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Download PDF (draft)' })).toBeDisabled();

    // Ticking alone does not allow a save: a rate must be chosen.
    await user.click(screen.getByLabelText(CONFIRM));
    expect(screen.getByRole('button', { name: 'Save draft' })).toBeDisabled();
    await user.selectOptions(select, '13');
    expect(screen.getByTestId('draft-tax-summary')).toHaveTextContent(/HST ON @ 13%/);
    await user.click(screen.getByLabelText(CONFIRM));
    const save = screen.getByRole('button', { name: 'Save draft' });
    expect(save).toBeEnabled();
    await user.click(save);
    await screen.findByText('Draft saved.');
    expect(patched).toMatchObject({
      tax_rate_percent: 13,
      tax_confirmed: true,
      confirmed_tax_rate_percent: 13,
      confirmed_total_cad: '114.00',
    });
  });
});

describe('Draft invoice: Download needs the GST/HST confirmed (DEC-0229)', () => {
  it('disables Download with the same message as Send until confirmed', async () => {
    renderDraft([{ path: '/invoice-drafts/7', body: draft() }]);
    const download = await screen.findByRole('button', { name: 'Download PDF (draft)' });
    expect(download).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Send invoice' })).toBeDisabled();
    const note = screen.getByText(UNCONFIRMED);
    expect(download).toHaveAttribute('aria-describedby', note.id);
  });

  it('tells a reader neutrally, without asking them to tick and save', async () => {
    renderDraft([{ path: '/invoice-drafts/7', body: draft() }], ['financial:read']);
    const download = await screen.findByRole('button', { name: 'Download PDF (draft)' });
    expect(download).toBeDisabled();
    const note = screen.getByText(/not yet confirmed by finance staff/);
    expect(download).toHaveAttribute('aria-describedby', note.id);
    expect(screen.queryByText(/tick the check/)).toBeNull();
  });

  it('enables Download once the saved revision is confirmed', async () => {
    renderDraft([{ path: '/invoice-drafts/7', body: draft({ tax_confirmed: true }) }]);
    expect(await screen.findByRole('button', { name: 'Download PDF (draft)' })).toBeEnabled();
    expect(screen.queryByText(UNCONFIRMED)).toBeNull();
  });
});

const RATES = {
  items: [
    {
      province_code: 'ON',
      province_name: 'Ontario',
      rate_percent: 13,
      tax_label: 'HST',
      updated_at: null,
      updated_by: null,
    },
    {
      province_code: 'NS',
      province_name: 'Nova Scotia',
      rate_percent: 14,
      tax_label: 'HST',
      updated_at: null,
      updated_by: null,
    },
  ],
  allowed_rates: [0, 5, 13, 14, 15],
};

describe('Settings → GST/HST rates', () => {
  it('rateError accepts a whole percent from 0 to 30 only', () => {
    expect(rateError('13')).toBeNull();
    expect(rateError('0')).toBeNull();
    expect(rateError('30')).toBeNull();
    for (const bad of ['31', '-1', '13.5', '', 'x']) expect(rateError(bad)).toBe('taxRates.rateError');
  });

  it('shows the table read-only without settings:manage', async () => {
    stubFetch([{ path: '/finance/tax-rates', body: RATES }, sessionRoute(OPS)]);
    renderWithProviders(
      <SessionProvider>
        <TaxRatesPanel />
      </SessionProvider>,
    );
    expect(await screen.findByText('Only Admin can change these rates.')).toBeInTheDocument();
    const row = screen.getByRole('row', { name: /Nova Scotia/ });
    expect(row).toHaveTextContent('14 %');
    expect(screen.queryByRole('button', { name: /^Save/ })).toBeNull();
    expect(screen.getByText(/Rates staff can choose on a draft invoice: 0 %, 5 %, 13 %, 14 %, 15 %/)).toBeInTheDocument();
  });

  it('lets Admin change a rate and sends it to the server', async () => {
    const user = userEvent.setup();
    let patched = null;
    stubFetch([
      {
        path: '/finance/tax-rates/ON',
        method: 'PATCH',
        body: (init) => {
          patched = JSON.parse(init.body);
          return {
            ...RATES,
            items: [{ ...RATES.items[0], rate_percent: 15, updated_by: 'admin@demo.example.com' }, RATES.items[1]],
          };
        },
      },
      { path: '/finance/tax-rates', body: RATES },
      sessionRoute(ADMIN),
    ]);
    renderWithProviders(
      <SessionProvider>
        <TaxRatesPanel />
      </SessionProvider>,
    );
    const input = await screen.findByLabelText('Rate for Ontario (percent)');
    const row = screen.getByRole('row', { name: /Ontario/ });
    const save = within(row).getByRole('button', { name: 'Save the rate for Ontario' });
    expect(save).toBeDisabled();
    await user.clear(input);
    await user.type(input, '31');
    await user.click(save);
    const error = screen.getByText('Enter a whole percent from 0 to 30.');
    expect(input).toHaveAttribute('aria-describedby', error.id);
    expect(input).toHaveAttribute('aria-invalid', 'true');
    expect(patched).toBeNull();
    await user.clear(input);
    await user.type(input, '15');
    await user.click(screen.getByRole('button', { name: 'Save the rate for Ontario' }));
    await waitFor(() => expect(patched).toEqual({ rate_percent: 15, tax_label: 'HST' }));
    await waitFor(() =>
      expect(screen.getByRole('row', { name: /Ontario/ })).toHaveTextContent('admin@demo.example.com'),
    );
  });
});
