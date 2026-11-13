/**
 * Owner answers of 2026-10-22 (Louis Tong): RC-UAT-19. Mocked API; demo data only.
 *
 * * The draft invoice's GST/HST: 13 %, included in the price, shown with its amounts; the box
 *   "I have checked the GST/HST on this invoice" is needed to Save, and Send waits for the
 *   saved revision to be confirmed; changing the rate, the mode or a line clears the box.
 * * HCM air row 27 (costume jewellery, quoted case by case): an amount field for the line,
 *   no quantity and no weight; a line without its amount says so and takes it in place.
 */

import { describe, expect, it } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Route, Routes } from 'react-router-dom';
import { SessionProvider } from '../src/app/SessionContext.jsx';
import { InvoiceDraftPage, taxPreview } from '../src/features/finance/InvoiceDraftPage.jsx';
import { CustomerCard } from '../src/features/workspace/CustomerCard.jsx';
import { FeePicker } from '../src/features/workspace/FeePicker.jsx';
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
    tax_rate_percent: 13,
    tax_mode: 'included',
    tax_confirmed: false,
    tax_confirmed_at: null,
    tax_confirmed_by: null,
    lines: [
      { description: 'Air Standard freight', amount_cad: '101.00' },
      { description: 'Phụ phí', amount_cad: '12.00' },
    ],
    lines_total_cad: '113.00',
    subtotal_cad: '100.00',
    tax_cad: '13.00',
    total_cad: '113.00',
    quote_total_cad: '113.00',
    total_change_reason: null,
    revision: 1,
    created_at: '2026-10-22T10:00:00',
    updated_at: '2026-10-22T10:00:00',
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
  stubFetch([...routes, sessionRoute()]);
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

describe('taxPreview: the server rule in whole cents', () => {
  it('backs the tax out of an all-in total, rounding half up', () => {
    expect(taxPreview([{ amount_cad: '113.00' }], '13', 'included')).toEqual({
      subtotal_cad: '100.00',
      tax_cad: '13.00',
      total_cad: '113.00',
    });
    // DEC-0235 (per line): net 88.50 + tax 11.51 is a cent over, so the net is nudged to
    // 88.49 (the whole-total rule of DEC-0223 read 88.50 / 11.50).
    expect(taxPreview([{ amount_cad: '100' }], 13, 'included')).toEqual({
      subtotal_cad: '88.49',
      tax_cad: '11.51',
      total_cad: '100.00',
    });
    expect(taxPreview([{ amount_cad: '0.05' }], 13, 'included').tax_cad).toBe('0.01');
    expect(taxPreview([{ amount_cad: '10.00' }], 5, 'included').tax_cad).toBe('0.48');
  });

  it('adds the tax on top in mode added, and gives up on a non-number', () => {
    expect(taxPreview([{ amount_cad: '100.00' }], 13, 'added')).toEqual({
      subtotal_cad: '100.00',
      tax_cad: '13.00',
      total_cad: '113.00',
    });
    expect(taxPreview([{ amount_cad: 'abc' }], 13, 'added')).toBeNull();
  });
});

describe('Draft invoice: GST/HST confirmation', () => {
  it('shows 13 % included and needs the check before Save, and a confirmed save before Send', async () => {
    const user = userEvent.setup();
    let patched = null;
    let current = draft();
    renderDraft([
      {
        path: '/invoice-drafts/7',
        method: 'PATCH',
        body: (init) => {
          patched = JSON.parse(init.body);
          current = draft({ tax_confirmed: true, tax_confirmed_by: 'person@demo.example.com' });
          return current;
        },
      },
      { path: '/invoice-drafts/7', body: () => current },
    ]);
    const summary = await screen.findByTestId('draft-tax-summary');
    expect(summary).toHaveTextContent(/Tax included in the price: subtotal before tax .*100\.00, HST ON @ 13% .*13\.00, total .*113\.00/);
    expect(screen.getByLabelText('GST/HST is')).toHaveValue('included');
    const send = screen.getByRole('button', { name: 'Send invoice' });
    expect(send).toBeDisabled();
    expect(screen.getByText(/GST\/HST of the saved draft is not confirmed/)).toBeInTheDocument();

    const save = screen.getByRole('button', { name: 'Save draft' });
    expect(save).toBeDisabled();
    await user.click(screen.getByLabelText(CONFIRM));
    expect(save).toBeEnabled();
    await user.click(save);
    await screen.findByText('Draft saved.');
    expect(patched).toMatchObject({
      expected_revision: 1,
      tax_rate_percent: 13,
      tax_mode: 'included',
      tax_confirmed: true,
      // The figures the tax box showed beside the tick (review, 2026-10-22).
      confirmed_total_cad: '113.00',
      confirmed_tax_mode: 'included',
      confirmed_tax_rate_percent: 13,
    });
    await waitFor(() => expect(screen.getByRole('button', { name: 'Send invoice' })).toBeEnabled());
    expect(screen.getByText(/GST\/HST checked for this revision by person@demo/)).toBeInTheDocument();
  });

  it('clears the check when the rate, the mode or a line changes', async () => {
    const user = userEvent.setup();
    renderDraft([{ path: '/invoice-drafts/7', body: draft({ tax_confirmed: true }) }]);
    const box = await screen.findByLabelText(CONFIRM);
    expect(box).toBeChecked();
    expect(screen.getByRole('button', { name: 'Send invoice' })).toBeEnabled();

    await user.selectOptions(screen.getByLabelText('GST/HST'), '5');
    expect(box).not.toBeChecked();
    expect(screen.getByRole('button', { name: 'Save draft' })).toBeDisabled();
    expect(screen.getByText(/before saving/)).toBeInTheDocument();
    expect(screen.getByTestId('draft-tax-summary')).toHaveTextContent(/GST @ 5%/);
    expect(screen.getByRole('button', { name: 'Send invoice' })).toBeDisabled();

    await user.click(box);
    await user.selectOptions(screen.getByLabelText('GST/HST is'), 'added');
    expect(box).not.toBeChecked();
    expect(screen.getByTestId('draft-tax-summary')).toHaveTextContent(
      /GST\/HST 5 % added on top: subtotal .*113\.00, GST\/HST .*5\.65, total .*118\.65/,
    );

    await user.click(box);
    const amount = screen.getByLabelText('Amount (CAD), line 2');
    await user.clear(amount);
    await user.type(amount, '20.00');
    expect(box).not.toBeChecked();
  });

  it('a notes-only edit keeps the check of a confirmed draft', async () => {
    const user = userEvent.setup();
    let patched = null;
    renderDraft([
      {
        path: '/invoice-drafts/7',
        method: 'PATCH',
        body: (init) => {
          patched = JSON.parse(init.body);
          return draft({ tax_confirmed: true, revision: 2, notes: 'Fragile' });
        },
      },
      { path: '/invoice-drafts/7', body: draft({ tax_confirmed: true }) },
    ]);
    await user.type(await screen.findByLabelText('Notes printed on the invoice'), 'Fragile');
    expect(screen.getByLabelText(CONFIRM)).toBeChecked();
    await user.click(screen.getByRole('button', { name: 'Save draft' }));
    await waitFor(() => expect(patched?.tax_confirmed).toBe(true));
  });
});

const JEWELLERY = {
  id: 27,
  section: 'hcm_air',
  stt: 27,
  name: 'Hàng mỹ ký (trang sức giả)',
  raw_price_text: '100-300.000/Kg',
  pricing_status: 'manual_quote',
  basis: 'manual_amount',
  scope: 'per_unit',
  unit_price_vnd: null,
  tiers: [],
};

function lineRoutes() {
  return [
    {
      path: '/shipments/11/items',
      body: [{ id: 1, description: 'Earrings', quantity: '1', unit: 'piece', is_active: true }],
    },
    {
      path: '/shipments/11/fee-lines',
      body: [
        {
          id: 5,
          item_id: 1,
          section: 'hcm_air',
          stt: 27,
          quantity: '1.00',
          weight_kg: null,
          manual_unit_price_vnd: null,
          created_at: '2026-10-22T10:00:00',
          removed_at: null,
        },
      ],
    },
    { path: '/tariffs/versions/1/surcharges', body: { items: [JEWELLERY], total: 1 } },
    { path: '/shipments/11/quotes', body: [] },
    sessionRoute(),
  ];
}

describe('Costume jewellery (HCM air row 27): an amount for the line', () => {
  it('asks the vendor’s amount for the line, with no quantity and no weight', async () => {
    const user = userEvent.setup();
    let body = null;
    stubFetch([
      { path: '/tariffs/versions/1/surcharges', body: { items: [JEWELLERY], total: 1 } },
      {
        path: '/shipments/11/fee-lines',
        method: 'POST',
        status: 201,
        body: (init) => {
          body = JSON.parse(init.body);
          return { id: 5 };
        },
      },
      sessionRoute(),
    ]);
    renderWithProviders(
      <SessionProvider>
        <FeePicker
          shipmentId={11}
          item={{ id: 1, description: 'Earrings', weight_kg: '2.000' }}
          section="hcm_air"
          versionId={1}
          onAdded={() => {}}
          onCancel={() => {}}
        />
      </SessionProvider>,
    );
    await user.click(await screen.findByRole('button', { name: /mỹ ký/ }));
    expect(screen.queryByLabelText('Quantity')).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/Weight \(kg\)/)).not.toBeInTheDocument();
    expect(screen.getByText('One amount for the line, quoted case by case')).toBeInTheDocument();
    // RC-UAT-20 (DEC-0228): the amount is now the vendor's cost, beside a customer price.
    await user.type(screen.getByLabelText(/Vendor cost \(VND\)/), '450000');
    await user.click(screen.getByRole('button', { name: 'Add fee' }));
    await waitFor(() => expect(body).not.toBeNull());
    expect(body).toMatchObject({ section: 'hcm_air', stt: 27, manual_unit_price_vnd: '450000' });
    expect(body.customer_price_cad).toBeUndefined();
    expect(body.weight_kg).toBeUndefined();
    // Not marked required: a blank amount is allowed and its consequence is explained.
    expect(screen.queryByText('Required')).not.toBeInTheDocument();
  });

  it('says why the amount field is disabled on a locked master', async () => {
    stubFetch(lineRoutes());
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
    expect(
      await screen.findByText('Locked: this master is booked. An Admin can unlock it to change the amount.'),
    ).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /^Save — / })).toBeDisabled();
  });

  it('shows "Amount needed" on a line without its amount and saves one in place', async () => {
    const user = userEvent.setup();
    let patched = null;
    stubFetch([
      {
        path: '/shipments/11/items',
        body: [{ id: 1, description: 'Earrings', quantity: '1', unit: 'piece', is_active: true }],
      },
      {
        path: '/shipments/11/fee-lines/5',
        method: 'PATCH',
        body: (init) => {
          patched = JSON.parse(init.body);
          return { id: 5 };
        },
      },
      {
        path: '/shipments/11/fee-lines',
        body: [
          {
            id: 5,
            item_id: 1,
            section: 'hcm_air',
            stt: 27,
            quantity: '1.00',
            weight_kg: null,
            manual_unit_price_vnd: null,
            created_at: '2026-10-22T10:00:00',
            removed_at: null,
          },
        ],
      },
      { path: '/tariffs/versions/1/surcharges', body: { items: [JEWELLERY], total: 1 } },
      { path: '/shipments/11/quotes', body: [] },
      sessionRoute(),
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
          removable={false}
        />
      </SessionProvider>,
    );
    // RC-UAT-20 (DEC-0228): both values are needed; the VND cost alone can still be saved.
    expect(
      await screen.findByText(/Vendor cost \(VND\) and customer price \(CAD\) needed/),
    ).toBeInTheDocument();
    await user.type(screen.getByLabelText(/Vendor cost \(VND\) — Hàng mỹ ký/), '450000');
    await user.click(screen.getByRole('button', { name: /^Save — Hàng mỹ ký/ }));
    await waitFor(() => expect(patched).toEqual({ manual_unit_price_vnd: '450000' }));
  });
});
