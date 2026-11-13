/**
 * Phase 13D, the unified workspace: navigation gate, master list and new-master form,
 * the fee picker's accent-insensitive search and status filter, the quote panel's
 * override-reason and refusal handling, the pending-defaults banner, and the number
 * helpers. Independent tester's suite; written from the requirements, not the code.
 */

import { describe, expect, it } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Route, Routes } from 'react-router-dom';
import { SessionProvider } from '../src/app/SessionContext.jsx';
import { AppShell } from '../src/components/layout/AppShell.jsx';
import { WorkspaceListPage } from '../src/features/workspace/WorkspaceListPage.jsx';
import { WorkspacePage } from '../src/features/workspace/WorkspacePage.jsx';
import { FeePicker, fold } from '../src/features/workspace/FeePicker.jsx';
import { QuotePanel } from '../src/features/workspace/QuotePanel.jsx';
import { CartonsPanel } from '../src/features/workspace/MasterPanels.jsx';
import {
  SECTION_BY_ORIGIN,
  formatCad,
  formatKg,
  formatVnd,
  sumOf,
} from '../src/features/workspace/workspaceFormat.js';
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

const OPS_PERMISSIONS = [
  'dashboard:read',
  'shipment:read',
  'shipment:write',
  'financial:read',
  'financial_cost:read',
  'tariff:read',
];

/* --- Navigation ----------------------------------------------------------------------- */

function renderShell(permissions) {
  stubFetch([sessionRoute('operations', permissions)]);
  return renderWithProviders(
    <SessionProvider>
      <Routes>
        <Route path="/" element={<AppShell />}>
          <Route index element={<p>Home</p>} />
        </Route>
      </Routes>
    </SessionProvider>,
  );
}

describe('Workspace navigation', () => {
  it('shows the Workspace entry to a role holding tariff:read', async () => {
    renderShell(OPS_PERMISSIONS);
    const link = await screen.findByRole('link', { name: 'Workspace' });
    expect(link).toHaveAttribute('href', '/workspace');
  });

  it('hides the Workspace entry from a role without tariff:read', async () => {
    renderShell(OPS_PERMISSIONS.filter((p) => p !== 'tariff:read'));
    // Wait for the session to load (the Shipments entry is gated too).
    expect(await screen.findByRole('link', { name: 'Shipments' })).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: 'Workspace' })).not.toBeInTheDocument();
  });
});

/* --- Master list ---------------------------------------------------------------------- */

const MASTER_ROW = {
  id: 3,
  public_id: 'CON-000003',
  vendor_key: 'kango',
  solaris_service: 'air_standard',
  solaris_service_label: 'Air Standard',
  origin: 'HCM',
  state: 'open',
  vendor_reference: 'AWB-TEST-1',
  tariff_version_public_id: null,
  vendor_product_code: null,
  actual_weight_kg: '21.000',
  length_cm: null,
  width_cm: null,
  height_cm: null,
  carton_count: 1,
  dim_divisor: null,
  volumetric_weight_kg: null,
  chargeable_weight_kg: '21.000',
  handed_over_at: null,
  cutoff_at: null,
  booked_at: null,
  completed_at: null,
  cancelled_at: null,
  cancellation_reason: null,
  internal_notes: null,
  member_count: 2,
  created_at: '2026-10-19T10:00:00',
  updated_at: '2026-10-19T10:00:00',
};

describe('WorkspaceListPage', () => {
  it('renders the masters the API returned', async () => {
    stubFetch([{ path: '/consolidations', body: { items: [MASTER_ROW], total: 1 } }]);
    renderWithProviders(<WorkspaceListPage />, { route: '/workspace' });
    const link = await screen.findByRole('link', { name: 'CON-000003' });
    expect(link).toHaveAttribute('href', '/workspace/3');
    const row = link.closest('tr');
    expect(within(row).getByText('Air Standard')).toBeInTheDocument();
    expect(within(row).getByText('AWB-TEST-1')).toBeInTheDocument();
    expect(within(row).getByText('21 kg')).toBeInTheDocument();
    expect(within(row).getByText('Open')).toBeInTheDocument();
  });

  it('offers the five services and SGN / HAN on the new-master form', async () => {
    const user = userEvent.setup();
    stubFetch([{ path: '/consolidations', body: { items: [], total: 0 } }]);
    renderWithProviders(<WorkspaceListPage />, { route: '/workspace' });
    expect(await screen.findByText('No masters yet')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'New master' }));

    const service = screen.getByRole('combobox', { name: /Service/ });
    const serviceOptions = within(service).getAllByRole('option').map((o) => o.textContent);
    expect(serviceOptions).toEqual([
      'Kango Air Standard',
      'Kango Air Express',
      'UPS',
      'Air Cargo',
      'Sea',
    ]);
    expect(within(service).getAllByRole('option').map((o) => o.value)).toEqual([
      'air_standard',
      'air_express',
      'ups',
      'air_cargo',
      'sea',
    ]);

    const origin = screen.getByRole('combobox', { name: /Origin/ });
    expect(within(origin).getAllByRole('option').map((o) => o.value)).toEqual(['HCM', 'HAN']);
  });

  it('creates an air master with the form values', async () => {
    const user = userEvent.setup();
    const fetchMock = stubFetch([
      { path: '/consolidations/3/cartons', method: 'PATCH', body: [] },
      { path: '/consolidations', method: 'POST', status: 201, body: { ...MASTER_ROW, members: [] } },
      { path: '/consolidations', body: { items: [], total: 0 } },
    ]);
    renderWithProviders(
      <Routes>
        <Route path="/workspace" element={<WorkspaceListPage />} />
        <Route path="/workspace/:consolidationId" element={<p>Opened master</p>} />
      </Routes>,
      { route: '/workspace' },
    );
    await user.click(await screen.findByRole('button', { name: 'New master' }));
    await user.type(screen.getByRole('textbox', { name: /Gross weight/ }), '21');
    await user.click(screen.getByRole('button', { name: 'Create master' }));
    expect(await screen.findByText('Opened master')).toBeInTheDocument();

    const post = fetchMock.mock.calls.find(([, init]) => init?.method === 'POST');
    const body = JSON.parse(post[1].body);
    expect(body).toMatchObject({
      solaris_service: 'air_standard',
      origin: 'HCM',
      actual_weight_kg: '21',
      carton_count: 1,
    });
    // Blank fields are left out, not sent as empty strings.
    expect(body).not.toHaveProperty('vendor_reference');
    // Master piece #1 is saved as the master's first carton.
    const cartons = fetchMock.mock.calls.find(([url, init]) => init?.method === 'PATCH' && String(url).includes('/cartons'));
    expect(JSON.parse(cartons[1].body)).toEqual({ cartons: [{ weight_kg: '21' }] });
  });
});

/* --- Fee picker ----------------------------------------------------------------------- */

function rule(stt, name, pricing_status, extra = {}) {
  return {
    id: stt,
    section: 'hcm_air',
    section_label: '1/ Phụ Phí HQ Đường Bay - HCM.',
    stt,
    name,
    raw_price_text: '50.000/Cái',
    raw_note: null,
    basis: 'per_unit',
    scope: 'item',
    pricing_status,
    unit_price_vnd: '50000',
    per_unit_price_vnd: null,
    per_unit_label: null,
    min_charge_kg: null,
    max_kg_per_shipment: null,
    applies_to_canada: true,
    semantics_source: 'parser',
    semantics_note: null,
    source_sheet: 'PHỤ THU',
    source_row: 10 + stt,
    tiers: [],
    ...extra,
  };
}

const RULES = [
  rule(18, 'Đồng hồ thường', 'priced'),
  rule(19, 'Đồng hồ Fake', 'unpriced_vendor_review'),
  rule(20, 'Hộp đồng hồ fake', 'conflict'),
  rule(21, 'Đồng hồ hàng hiệu', 'manual_quote', { raw_price_text: 'Báo giá' }),
  rule(22, 'Nước hoa', 'tiered', {
    basis: 'per_piece',
    tiers: [{ weight_from_kg: '0', weight_to_kg: '22', price_vnd: '500000' }],
  }),
  rule(23, 'Sách vở', 'free'),
  rule(24, 'Pin rời', 'not_applicable_canada'),
];

function renderPicker() {
  const fetchMock = stubFetch([
    { path: '/tariffs/versions/7/surcharges', body: { items: RULES, total: RULES.length } },
    { path: '/shipments/5/fee-lines', method: 'POST', status: 201, body: { id: 1 } },
  ]);
  renderWithProviders(
    <FeePicker
      shipmentId={5}
      item={{ id: 11, weight_kg: '0.400', description: 'Watch' }}
      section="hcm_air"
      versionId={7}
      onAdded={() => {}}
      onCancel={() => {}}
    />,
  );
  return fetchMock;
}

async function resultNames() {
  const list = await screen.findByRole('list', { name: 'Matching surcharges' });
  return within(list)
    .queryAllByRole('button')
    .map((b) => b.querySelector('.ws-rule__name').textContent);
}

describe('fold()', () => {
  it('is accent-insensitive and folds đ/Đ to d', () => {
    expect(fold('Đồng hồ thường')).toBe('dong ho thuong');
    expect(fold('Đồng hồ thường').includes(fold('dong ho'))).toBe(true);
    expect(fold('NƯỚC HOA')).toBe('nuoc hoa');
    expect(fold('đ')).toBe('d');
    expect(fold(null)).toBe('');
    expect(fold(undefined)).toBe('');
  });

  it('lets a search typed with diacritics match a name written without', () => {
    expect(fold('dong ho fake').includes(fold('Đồng hồ'))).toBe(true);
  });
});

describe('FeePicker', () => {
  it('asks only for the master’s own section', async () => {
    const fetchMock = renderPicker();
    await resultNames();
    const urls = fetchMock.mock.calls.map(([url]) => url);
    const call = urls.find((u) => u.includes('/surcharges'));
    expect(call).toContain('section=hcm_air');
    expect(SECTION_BY_ORIGIN).toEqual({ HCM: 'hcm_air', HAN: 'han_air' });
  });

  it('lists only pickable statuses', async () => {
    renderPicker();
    await waitFor(async () => expect((await resultNames()).length).toBeGreaterThan(0));
    const names = await resultNames();
    expect(names).toEqual(['Đồng hồ thường', 'Đồng hồ hàng hiệu', 'Nước hoa', 'Sách vở']);
    expect(names).not.toContain('Đồng hồ Fake'); // unpriced_vendor_review
    expect(names).not.toContain('Hộp đồng hồ fake'); // conflict
    expect(names).not.toContain('Pin rời'); // not_applicable_canada
  });

  it('finds "Đồng hồ thường" when "dong ho" is typed', async () => {
    const user = userEvent.setup();
    renderPicker();
    await screen.findByText('Nước hoa');
    await user.type(screen.getByRole('searchbox', { name: /Search the vendor/ }), 'dong ho');
    await waitFor(async () =>
      expect(await resultNames()).toEqual(['Đồng hồ thường', 'Đồng hồ hàng hiệu']),
    );
  });

  it('shows "No surcharge matches." for a search with no hit', async () => {
    const user = userEvent.setup();
    renderPicker();
    await screen.findByText('Nước hoa');
    await user.type(screen.getByRole('searchbox', { name: /Search the vendor/ }), 'zzzz');
    expect(await screen.findByText('No surcharge matches.')).toBeInTheDocument();
  });

  it('shows the vendor price field for a manual-quote rule, not for a priced one', async () => {
    const user = userEvent.setup();
    renderPicker();
    await user.click(await screen.findByRole('button', { name: /Đồng hồ thường/ }));
    expect(screen.queryByRole('textbox', { name: /Vendor’s price/ })).not.toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Choose another' }));
    await user.click(await screen.findByRole('button', { name: /Đồng hồ hàng hiệu/ }));
    expect(screen.getByRole('textbox', { name: /Vendor’s price/ })).toBeInTheDocument();
    expect(screen.getByText(/Manual quote: the file’s minimum 50,000 VND/)).toBeInTheDocument();
  });

  it('sends the picked rule, quantity and vendor price to the server', async () => {
    const user = userEvent.setup();
    const fetchMock = renderPicker();
    await user.click(await screen.findByRole('button', { name: /Đồng hồ hàng hiệu/ }));
    await user.type(screen.getByRole('textbox', { name: /Vendor’s price/ }), '75000');
    await user.click(screen.getByRole('button', { name: 'Add fee' }));
    await waitFor(() =>
      expect(fetchMock.mock.calls.some(([, init]) => init?.method === 'POST')).toBe(true),
    );
    const post = fetchMock.mock.calls.find(([, init]) => init?.method === 'POST');
    expect(post[0]).toContain('/shipments/5/fee-lines');
    expect(JSON.parse(post[1].body)).toMatchObject({
      item_id: 11,
      section: 'hcm_air',
      stt: 21,
      quantity: '1',
      manual_unit_price_vnd: '75000',
    });
  });
});

/* --- Quote panel ---------------------------------------------------------------------- */

const DRAFT = {
  id: 40,
  shipment_id: 5,
  version: 1,
  status: 'draft',
  solaris_service: 'air_standard',
  consolidation_id: 3,
  tariff_version_id: 7,
  fx_snapshot_id: 1,
  default_rate_cad: '18.00',
  selling_rate_cad: '18.00',
  override_reason: null,
  rate_confirmed: false,
  rate_confirmed_at: null,
  negative_margin_reason: null,
  billable_weight_kg: '10.000',
  base_revenue_cad: '180.00',
  surcharge_revenue_cad: '1.79',
  total_revenue_cad: '181.79',
  allocated_cost_cad: '120.00',
  gross_profit_cad: '61.79',
  blocking: [],
  provisional: [],
  lines: [
    {
      sequence: 1,
      kind: 'base',
      description: 'Air Standard freight',
      section: null,
      stt: null,
      quantity: '10',
      unit: 'kg',
      revenue_cad: '180.00',
      cost_vnd: null,
      cost_cad: '100.00',
      is_trigger: true,
      markup_kind: null,
      markup_value: null,
    },
  ],
  finalized_at: null,
  created_at: '2026-10-19T10:00:00',
};

const REFUSAL = {
  code: 'conflict',
  message: 'This quote cannot be finalised yet.',
  detail: {
    problems: [
      {
        code: 'negative_margin',
        message:
          'These surcharges bill below their cost; give a reason to finalise: Đồng hồ thường',
      },
      { code: 'rate_not_confirmed', message: 'Confirm the selling rate before finalising.' },
    ],
  },
};

function renderQuote(extraRoutes = []) {
  const fetchMock = stubFetch([
    ...extraRoutes,
    { path: '/shipments/5/quotes', body: [DRAFT] },
  ]);
  renderWithProviders(
    <QuotePanel consolidationId={3} shipmentId={5} refresh={() => {}} editable />,
  );
  return fetchMock;
}

describe('QuotePanel', () => {
  it('shows the override reason only when the typed rate differs from the default', async () => {
    const user = userEvent.setup();
    renderQuote();
    const rate = await screen.findByRole('textbox', { name: /Selling rate \(CAD\/kg\)/ });
    expect(screen.queryByRole('textbox', { name: /Reason for this rate/ })).not.toBeInTheDocument();

    await user.type(rate, '18');
    expect(screen.queryByRole('textbox', { name: /Reason for this rate/ })).not.toBeInTheDocument();
    await user.clear(rate);
    await user.type(rate, '18.00');
    expect(screen.queryByRole('textbox', { name: /Reason for this rate/ })).not.toBeInTheDocument();

    await user.clear(rate);
    await user.type(rate, '20');
    // Marked as a required field: aria-required, with a red asterisk beside the label
    // rather than "(Required)" in its name (RC-UAT-25 item 1, Ben 2026-10-25).
    expect(screen.getByRole('textbox', { name: 'Reason for this rate' })).toHaveAttribute(
      'aria-required',
      'true',
    );

    await user.clear(rate);
    expect(screen.queryByRole('textbox', { name: /Reason for this rate/ })).not.toBeInTheDocument();
  });

  it('a blank box confirms the rate shown on a draft carrying an earlier override', async () => {
    const user = userEvent.setup();
    const overridden = { ...DRAFT, selling_rate_cad: '20.00', override_reason: 'Loyal customer' };
    const fetchMock = stubFetch([
      {
        path: '/shipments/5/quotes/confirm-rate',
        method: 'POST',
        body: { ...overridden, rate_confirmed: true },
      },
      { path: '/shipments/5/quotes', body: [overridden] },
    ]);
    renderWithProviders(
      <QuotePanel consolidationId={3} shipmentId={5} refresh={() => {}} editable />,
    );
    const rate = await screen.findByRole('textbox', { name: /Selling rate \(CAD\/kg\)/ });
    expect(rate).toHaveAttribute('placeholder', '20');
    // The shown rate is not the default, so the reason field is offered.
    expect(screen.getByRole('textbox', { name: /Reason for this rate/ })).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Confirm selling rate' }));
    await waitFor(() =>
      expect(fetchMock.mock.calls.some(([, init]) => init?.method === 'POST')).toBe(true),
    );
    const post = fetchMock.mock.calls.find(([, init]) => init?.method === 'POST');
    // Never silently falls back to the 18.00 default.
    expect(JSON.parse(post[1].body)).toEqual({ rate: '20.00', reason: 'Loyal customer' });
  });

  it('a blank box confirms the shown (default) rate with no reason', async () => {
    const user = userEvent.setup();
    const fetchMock = renderQuote([
      {
        path: '/shipments/5/quotes/confirm-rate',
        method: 'POST',
        body: { ...DRAFT, rate_confirmed: true },
      },
    ]);
    await user.click(await screen.findByRole('button', { name: 'Confirm selling rate' }));
    await waitFor(() =>
      expect(fetchMock.mock.calls.some(([, init]) => init?.method === 'POST')).toBe(true),
    );
    const post = fetchMock.mock.calls.find(([, init]) => init?.method === 'POST');
    const body = JSON.parse(post[1].body);
    // Either no rate (server uses the default) or exactly the shown rate; never a reason.
    expect(body.rate === undefined || Number(body.rate) === 18).toBe(true);
    expect(body).not.toHaveProperty('reason');
  });

  it('sends the override rate and its reason', async () => {
    const user = userEvent.setup();
    const fetchMock = renderQuote([
      {
        path: '/shipments/5/quotes/confirm-rate',
        method: 'POST',
        body: { ...DRAFT, rate_confirmed: true, selling_rate_cad: '20.00' },
      },
    ]);
    await user.type(await screen.findByRole('textbox', { name: /Selling rate \(CAD\/kg\)/ }), '20');
    await user.type(screen.getByRole('textbox', { name: /Reason for this rate/ }), 'Loyal customer');
    await user.click(screen.getByRole('button', { name: 'Confirm selling rate' }));
    await waitFor(() =>
      expect(fetchMock.mock.calls.some(([, init]) => init?.method === 'POST')).toBe(true),
    );
    const post = fetchMock.mock.calls.find(([, init]) => init?.method === 'POST');
    expect(JSON.parse(post[1].body)).toEqual({ rate: '20', reason: 'Loyal customer' });
  });

  it('renders the server’s problems on a refused finalise', async () => {
    const user = userEvent.setup();
    renderQuote([
      { path: '/shipments/5/quotes/finalize', method: 'POST', status: 409, body: REFUSAL },
    ]);
    await user.click(await screen.findByRole('button', { name: 'Finalise quote' }));
    expect(await screen.findByText('This quote cannot be finalised yet.')).toBeInTheDocument();
    expect(
      screen.getByText(/bill below their cost; give a reason to finalise: Đồng hồ thường/),
    ).toBeInTheDocument();
    expect(screen.getByText('Confirm the selling rate before finalising.')).toBeInTheDocument();
  });

  it('sends the negative-margin reason with the finalise', async () => {
    const user = userEvent.setup();
    const fetchMock = renderQuote([
      {
        path: '/shipments/5/quotes/finalize',
        method: 'POST',
        body: { ...DRAFT, status: 'finalized', rate_confirmed: true },
      },
    ]);
    await user.type(
      await screen.findByRole('textbox', { name: /Reason for billing a surcharge below cost/ }),
      'Promotional',
    );
    await user.click(screen.getByRole('button', { name: 'Finalise quote' }));
    await waitFor(() =>
      expect(fetchMock.mock.calls.some(([, init]) => init?.method === 'POST')).toBe(true),
    );
    const post = fetchMock.mock.calls.find(([, init]) => init?.method === 'POST');
    expect(JSON.parse(post[1].body)).toEqual({ negative_margin_reason: 'Promotional' });
  });

  it('offers Price quote when there is no quote yet', async () => {
    stubFetch([{ path: '/shipments/5/quotes', body: [] }]);
    renderWithProviders(
      <QuotePanel consolidationId={3} shipmentId={5} refresh={() => {}} editable />,
    );
    expect(await screen.findByText('Not priced yet.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Price quote' })).toBeInTheDocument();
  });
});

/* --- Workspace page ------------------------------------------------------------------- */

const ESTIMATE = {
  consolidation_id: 3,
  estimate: {
    product_code: 'KG-AIR-STD',
    zone: 3,
    delivery_postal_code: 'L5T 1A1',
    master_chargeable_kg: '21.000',
    base_freight_vnd: '1500000',
    base_freight_cad: '83.86',
    total_cost_vnd: '1550000.50',
    piece_fee_vnd: '0.50',
    fx_snapshot_id: 1,
    fees: [
      {
        key: 'hcm_air-18-1',
        section: 'hcm_air',
        stt: 18,
        name: 'Đồng hồ thường',
        scope: 'item',
        master_wide: false,
        vendor_fee_vnd: '50000',
        triggers: { 5: [1] },
        cost_alloc_vnd: {},
        cost_alloc_cad: {},
        customer_base_cad: null,
      },
    ],
    members: [],
    blocking: [],
    provisional: [],
  },
};

function renderWorkspace({ confirmed, route = '/workspace/3?sel=cost' }) {
  stubFetch([
    { path: '/consolidations/3/pricing', body: ESTIMATE },
    { path: '/consolidations/3/cartons', body: [] },
    { path: '/consolidations/3', body: { ...MASTER_ROW, member_count: 0, members: [] } },
    {
      path: '/pricing/settings',
      body: {
        air_standard_default_rate_cad: '18.00',
        air_express_default_rate_cad: null,
        trigger_share_numerator: 2,
        trigger_share_denominator: 3,
        defaults_owner_confirmed: confirmed,
        vendor_delivery_postal_code: 'L5T 1A1',
        updated_at: '2026-10-19T10:00:00',
      },
    },
    {
      path: '/tariffs/versions',
      body: { items: [{ id: 7, status: 'active' }], total: 1 },
    },
    {
      path: '/fx/latest',
      body: {
        freshness: 'live',
        stale_after_minutes: 1440,
        snapshot: {
          id: 1,
          bank: 'vietcombank',
          currency: 'CAD',
          cash_buy_vnd: '17886.61',
          transfer_buy_vnd: '18067.28',
          sell_vnd: '18645.39',
          bank_published_raw: null,
          bank_published_at: null,
          retrieved_at: '2026-10-19T10:00:00',
        },
        last_attempt: null,
      },
    },
  ]);
  return renderWithProviders(
    <Routes>
      <Route path="/workspace/:consolidationId" element={<WorkspacePage />} />
    </Routes>,
    { route },
  );
}

describe('WorkspacePage', () => {
  it('shows the pending-defaults banner while the owner has not confirmed them', async () => {
    renderWorkspace({ confirmed: false });
    expect(
      await screen.findByText('Pricing defaults awaiting owner confirmation'),
    ).toBeInTheDocument();
  });

  it('shows no pending-defaults banner once the owner has confirmed them', async () => {
    renderWorkspace({ confirmed: true });
    expect(await screen.findByText('Total vendor cost')).toBeInTheDocument();
    // Settings resolve independently of the master; wait for them before asserting absence.
    await waitFor(() =>
      expect(screen.queryByText('Pricing defaults awaiting owner confirmation')).not.toBeInTheDocument(),
    );
  });

  it('summarises vendor cost, surcharges, cents and the FX reading', async () => {
    renderWorkspace({ confirmed: true });
    // DEC-0274: one "Cost and quote" card; DEC-0277: opened from the tree (?sel=cost).
    const panel = await screen.findByRole('region', { name: 'Cost and quote' });
    await within(panel).findByText('Total vendor cost');
    const value = (label) => within(panel).getByText(label).closest('.ws-cost-line').querySelector('dd');
    expect(value('Base freight')).toHaveTextContent('1,500,000 VND');
    expect(value('Surcharges')).toHaveTextContent('50,000 VND');
    expect(value('Total vendor cost')).toHaveTextContent('1,550,000.5 VND');
    expect(await within(panel).findByText(/cash buying 17,886.61 VND, selling 18,645.39 VND/)).toBeInTheDocument();
  });
});

describe('CartonsPanel', () => {
  it('saves the cartons with PATCH, leaving out rows with no weight', async () => {
    const user = userEvent.setup();
    const fetchMock = stubFetch([
      {
        path: '/consolidations/3/cartons',
        method: 'PATCH',
        body: [{ sequence: 1, weight_kg: '8.000', length_cm: null, width_cm: null, height_cm: null }],
      },
      { path: '/consolidations/3/cartons', body: [] },
    ]);
    renderWithProviders(<CartonsPanel master={MASTER_ROW} estimate={null} editable />);
    expect(await screen.findByText('No cartons recorded.')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Edit cartons' }));
    await user.type(screen.getByRole('textbox', { name: 'Weight of carton 1' }), '8');
    await user.click(screen.getByRole('button', { name: 'Add carton' }));
    await user.click(screen.getByRole('button', { name: 'Save cartons' }));
    await waitFor(() =>
      expect(fetchMock.mock.calls.some(([, init]) => init?.method === 'PATCH')).toBe(true),
    );
    const patch = fetchMock.mock.calls.find(([, init]) => init?.method === 'PATCH');
    expect(JSON.parse(patch[1].body)).toEqual({ cartons: [{ weight_kg: '8' }] });
  });

  it('offers no editing on a master that is not editable', async () => {
    stubFetch([{ path: '/consolidations/3/cartons', body: [] }]);
    renderWithProviders(<CartonsPanel master={MASTER_ROW} estimate={null} editable={false} />);
    expect(await screen.findByText('No cartons recorded.')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Edit cartons' })).not.toBeInTheDocument();
  });
});

/* --- Number helpers ------------------------------------------------------------------- */

describe('workspaceFormat', () => {
  it('formatVnd keeps cents and never rounds them away', () => {
    expect(formatVnd('1234567.89')).toBe('1,234,567.89 VND');
    expect(formatVnd('50000.25')).toBe('50,000.25 VND');
    expect(formatVnd('50000')).toBe('50,000 VND');
    expect(formatVnd('0.5')).toBe('0.5 VND');
    expect(formatVnd(0)).toBe('0 VND');
    expect(formatVnd(null)).toBe('—');
    expect(formatVnd(undefined)).toBe('—');
    expect(formatVnd('')).toBe('—');
  });

  it('formatCad always shows two decimals and the CAD code', () => {
    expect(formatCad('12.5')).toMatch(/^CAD\s12\.50$/);
    expect(formatCad('1234')).toMatch(/^CAD\s1,234\.00$/);
    expect(formatCad('-3.1')).toMatch(/CAD\s?3\.10/);
    expect(formatCad('-3.1')).toMatch(/-/);
    expect(formatCad(null)).toBe('—');
  });

  it('formatKg shows up to three decimals', () => {
    expect(formatKg('21.000')).toBe('21 kg');
    expect(formatKg('0.405')).toBe('0.405 kg');
    expect(formatKg(null)).toBe('—');
  });

  it('sumOf adds decimal strings and is null when any value is missing', () => {
    expect(sumOf(['1.5', '2', '0.25'])).toBe(3.75);
    expect(sumOf([])).toBe(0);
    expect(sumOf(['1', null])).toBeNull();
    expect(sumOf(['1', undefined])).toBeNull();
    expect(sumOf(['1', ''])).toBeNull();
    expect(sumOf(['0', '0'])).toBe(0);
  });
});
