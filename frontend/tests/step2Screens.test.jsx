/**
 * Step 2 screens (DEC-0270), mocked API throughout, demo data only:
 * cost vs quote per master / package / customer, the package note and packed flag, manual
 * Express / UPS pricing, Settings → Pricing method (only changed fields sent; read-only
 * without settings:manage), the dated sea cost, the "RC25 method only" markup label and
 * Settings → Kango rate sheets (upload → diff → confirm, history rollback, approvers).
 */

import { describe, expect, it } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { SessionProvider } from '../src/app/SessionContext.jsx';
import {
  CostQuotePanel,
  ManualPricingPanel,
  PackagesPanel,
  packageRows,
} from '../src/features/workspace/CostQuotePanel.jsx';
import {
  MethodSettingsPanel,
  changedFields,
} from '../src/features/settings/MethodSettingsPanel.jsx';
import { RateSheetPanel, RateSheetDiff } from '../src/features/settings/RateSheetPanel.jsx';
import { PricingSettingsPanel } from '../src/features/settings/PricingSettingsPanel.jsx';
import { renderWithProviders, stubFetch } from './utils.jsx';

const ADMIN = [
  'settings:read',
  'settings:manage',
  'tariff:read',
  'tariff:manage',
  'staff:read',
  'staff:manage',
];
const OPS = ['settings:read', 'tariff:read'];

function session(permissions, role = 'admin') {
  return {
    path: '/auth/me',
    body: {
      user: { id: 1, full_name: 'Demo Admin', email: 'admin@demo.example.com', role },
      permissions,
      environment: 'test',
      is_demo_environment: false,
    },
  };
}

/* --- Cost vs quote ------------------------------------------------------------------------ */

const DETAIL = {
  method: 'confirmed',
  method_version: 'v0.7',
  fx: { cost_rate_vnd: '19500', cost_source: 'kango_fixed' },
  bill_kg: '30',
  base_basis: 'HCM zone 2 per-kg',
  bill_vnd: '3900000',
  packages_known: true,
  reconciled: true,
  packages: [
    { sequence: 1, raw_kg: '18', billed_kg: '18', members: [11, 12], packed_as_one_box: false },
    { sequence: 2, raw_kg: '12', billed_kg: '12', members: [13], packed_as_one_box: false },
  ],
  members: {
    11: {
      public_id: 'STCA-000201',
      cw_kg: '10',
      cost_vnd: '1300000',
      cost_cad: '66.67',
      quote_cad: '160.00',
      profit_cad: '93.33',
      surcharge_margin_cad: '0.00',
      rate_cad_kg: '16.00',
      rules: ['Base split by weight'],
    },
    12: {
      public_id: 'STCA-000202',
      cw_kg: '8',
      cost_vnd: '1040000',
      cost_cad: '53.33',
      quote_cad: '128.00',
      profit_cad: '74.67',
      surcharge_margin_cad: '0.00',
      rate_cad_kg: '16.00',
      rules: [],
    },
    13: {
      public_id: 'STCA-000203',
      cw_kg: '12',
      cost_vnd: '1560000',
      cost_cad: '80.00',
      quote_cad: '70.00',
      profit_cad: '-10.00',
      surcharge_margin_cad: '0.00',
      rate_cad_kg: '16.00',
      rules: [],
    },
  },
  totals: { cost_cad: '200.00', quote_cad: '358.00', profit_cad: '158.00', surcharge_margin_cad: '0.00' },
};

const MASTER = {
  id: 7,
  public_id: 'CON-000007',
  solaris_service: 'air_standard',
  state: 'open',
  members: [
    { shipment_id: 11, public_id: 'STCA-000201', customer_name: 'Demo Anh' },
    { shipment_id: 12, public_id: 'STCA-000202', customer_name: 'Demo Binh' },
    { shipment_id: 13, public_id: 'STCA-000203', customer_name: 'Demo Chau' },
  ],
};

const ESTIMATE = { method: 'confirmed', method_detail: DETAIL, blocking: [], provisional: [{ code: 'demo', message: 'Demo warning' }] };

describe('Cost and quote panel', () => {
  it('adds up each package from its customers and lists who is inside', () => {
    const rows = packageRows(DETAIL);
    expect(rows).toHaveLength(2);
    expect(rows[0].publicIds).toEqual(['STCA-000201', 'STCA-000202']);
    expect(rows[0].costVnd).toBe(2340000);
    expect(rows[0].quoteCad).toBeCloseTo(288);
    expect(rows[1].profitCad).toBeCloseTo(-10);
  });

  it('shows the master totals, the vendor cost, the quote by customer and the pieces', () => {
    renderWithProviders(
      <CostQuotePanel master={MASTER} estimateQuery={{ data: { estimate: ESTIMATE } }} />,
    );
    // Headline figures for the whole master.
    expect(screen.getAllByText('3,900,000 VND').length).toBeGreaterThan(0);
    expect(screen.getAllByText('CAD 358.00').length).toBeGreaterThan(0);
    // Quote by customer: weight, rate and quote -- no per-customer cost (DEC-0274).
    const customers = screen.getByRole('table', { name: 'Quote by customer' });
    const row = within(customers).getByText('STCA-000203').closest('tr');
    expect(row).toHaveTextContent('CAD 70.00');
    expect(within(customers).queryByText('1,560,000 VND')).toBeNull();
    expect(within(customers).queryByText(/Cost/)).toBeNull();
    // Two pieces: weights and quote per piece, customers listed by name.
    const pieces = screen.getByRole('table', { name: 'By master piece' });
    expect(within(pieces).getByText('Demo Anh, Demo Binh')).toBeInTheDocument();
    expect(within(pieces).getByText('Master piece #2')).toBeInTheDocument();
    expect(screen.getByText('Demo warning')).toBeInTheDocument();
  });

  it('says the RC25 method prices the master when there is no method detail', () => {
    renderWithProviders(
      <CostQuotePanel master={MASTER} estimateQuery={{ data: { estimate: { blocking: [] } } }} />,
    );
    expect(screen.getByText(/RC25 method/)).toBeInTheDocument();
    expect(screen.queryByRole('table')).toBeNull();
  });

  it('warns when the customers do not add up to the vendor bill', () => {
    const estimate = { ...ESTIMATE, method_detail: { ...DETAIL, reconciled: false } };
    renderWithProviders(<CostQuotePanel master={MASTER} estimateQuery={{ data: { estimate } }} />);
    expect(screen.getByText(/do not add up to the vendor bill/)).toBeInTheDocument();
  });
});

describe('Packages panel', () => {
  it('saves a package note and allows "packed as one box" only on a one-package master', async () => {
    const user = userEvent.setup();
    let sent = null;
    const fetchMock = stubFetch([
      { path: '/consolidations/7/packages/1/note', method: 'PATCH', body: (init) => {
        sent = JSON.parse(init.body);
        return { notes: { 1: sent.customer_note }, members: {}, packed: {} };
      } },
      { path: '/consolidations/7/packages', body: { notes: {}, members: { 11: 1, 12: 1, 13: 2 }, packed: {} } },
      { path: '/consolidations/7', body: {} },
    ]);
    renderWithProviders(<PackagesPanel master={MASTER} estimate={ESTIMATE} editable />);
    const box = await screen.findByRole('checkbox', { name: /Packed as one box/ });
    expect(box).toBeDisabled();
    expect(screen.getByText('Only on a master with one package.')).toBeInTheDocument();
    expect(screen.getByText('Which package is each customer in?')).toBeInTheDocument();

    await user.type(screen.getByLabelText(/Package 1: customers inside/), 'STCA-000201, -202');
    await user.click(screen.getAllByRole('button', { name: 'Save note' })[0]);
    await waitFor(() => expect(sent).toEqual({ customer_note: 'STCA-000201, -202' }));
    expect(fetchMock).toHaveBeenCalled();
  });

  it('sends the packed flag on a single-package master', async () => {
    const user = userEvent.setup();
    let sent = null;
    stubFetch([
      { path: '/consolidations/7/packages/1/packed', method: 'PATCH', body: (init) => {
        sent = JSON.parse(init.body);
        return { notes: {}, members: {}, packed: { 1: true } };
      } },
      { path: '/consolidations/7/packages', body: { notes: {}, members: {}, packed: {} } },
      { path: '/consolidations/7', body: {} },
    ]);
    const single = { ...ESTIMATE, method_detail: { ...DETAIL, packages: [DETAIL.packages[0]] } };
    renderWithProviders(<PackagesPanel master={MASTER} estimate={single} editable />);
    const box = await screen.findByRole('checkbox', { name: /Packed as one box/ });
    expect(box).toBeEnabled();
    await user.click(box);
    await waitFor(() => expect(sent).toEqual({ packed_as_one_box: true }));
  });
});

describe('Vendor base cost (DEC-0271)', () => {
  it('shows the rate-sheet cost and asks a reason to enter a different one', async () => {
    const user = userEvent.setup();
    let sent = null;
    stubFetch([
      { path: '/consolidations/7/manual-pricing', method: 'PATCH', body: (init) => {
        sent = JSON.parse(init.body);
        return sent;
      } },
      { path: '/consolidations/7/manual-pricing', body: {} },
      { path: '/consolidations/7', body: {} },
    ]);
    const estimate = { ...ESTIMATE, method_detail: { ...DETAIL, base_vnd: '3900000' } };
    renderWithProviders(<ManualPricingPanel master={MASTER} estimate={estimate} editable />);
    expect(await screen.findByText(/from the rate sheet/)).toBeInTheDocument();
    expect(screen.getByText('3,900,000 VND')).toBeInTheDocument();
    // Air Standard takes no selling rate here and shows no cost fields until asked.
    expect(screen.queryByLabelText('Vendor cost (VND total)')).toBeNull();
    await user.click(screen.getByRole('button', { name: 'Enter a different base cost' }));
    await user.type(screen.getByLabelText('Vendor cost (VND total)'), '4100000');
    await user.click(screen.getByRole('button', { name: 'Save base cost' }));
    expect(screen.getByText('Give a reason for the different base cost.')).toBeInTheDocument();
    expect(sent).toBeNull();
    await user.type(screen.getByLabelText(/^Reason/), 'Kango bill differs');
    await user.click(screen.getByRole('button', { name: 'Save base cost' }));
    await waitFor(() =>
      expect(sent).toEqual({
        manual_cost_vnd_per_kg: null,
        manual_cost_vnd_total: '4100000',
        manual_sell_cad_per_kg: null,
        reason: 'Kango bill differs',
      }),
    );
  });

  it('flags an overridden cost and offers the rate sheet back', async () => {
    stubFetch([
      {
        path: '/consolidations/7/manual-pricing',
        body: { manual_cost_vnd_total: '4100000', manual_cost_vnd_per_kg: null, reason: 'Kango bill differs' },
      },
    ]);
    renderWithProviders(<ManualPricingPanel master={MASTER} estimate={ESTIMATE} editable />);
    expect(await screen.findByText('Base cost entered by staff')).toBeInTheDocument();
    expect(screen.getByText(/Reason: Kango bill differs/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Use the rate sheet again' })).toBeInTheDocument();
  });

  it('refuses a cost per kg and a total together on UPS, then saves one of them', async () => {
    const user = userEvent.setup();
    let sent = null;
    stubFetch([
      { path: '/consolidations/7/manual-pricing', method: 'PATCH', body: (init) => {
        sent = JSON.parse(init.body);
        return sent;
      } },
      { path: '/consolidations/7/manual-pricing', body: {} },
      { path: '/consolidations/7', body: {} },
    ]);
    const master = { ...MASTER, solaris_service: 'ups' };
    renderWithProviders(<ManualPricingPanel master={master} estimate={ESTIMATE} editable />);
    expect(await screen.findByText(/UPS has no rate sheet/)).toBeInTheDocument();
    await user.type(screen.getByLabelText('Vendor cost (VND per kg)'), '250000');
    await user.type(screen.getByLabelText('Vendor cost (VND total)'), '5000000');
    await user.click(screen.getByRole('button', { name: 'Save manual pricing' }));
    expect(screen.getByText('Enter the vendor cost per kg or as a total, not both.')).toBeInTheDocument();
    expect(sent).toBeNull();

    await user.clear(screen.getByLabelText('Vendor cost (VND total)'));
    await user.type(screen.getByLabelText('Selling rate (CAD per kg)'), '24');
    await user.click(screen.getByRole('button', { name: 'Save manual pricing' }));
    await waitFor(() =>
      expect(sent).toEqual({
        manual_cost_vnd_per_kg: '250000',
        manual_cost_vnd_total: null,
        manual_sell_cad_per_kg: '24',
        reason: null,
      }),
    );
  });

  it('asks a selling rate for Kango Air Express, defaulting to Settings', async () => {
    stubFetch([{ path: '/consolidations/7/manual-pricing', body: {} }]);
    const master = { ...MASTER, solaris_service: 'air_express' };
    renderWithProviders(<ManualPricingPanel master={master} estimate={ESTIMATE} editable />);
    expect(await screen.findByLabelText('Selling rate (CAD per kg)')).toBeInTheDocument();
    expect(screen.getByText(/Air Express default rate/)).toBeInTheDocument();
    expect(screen.queryByLabelText('Vendor cost (VND total)')).toBeNull();
  });
});

/* --- Settings → Pricing method ------------------------------------------------------------ */

const METHOD = {
  pricing_method: 'confirmed',
  threshold_basis: 'customer',
  markup_kind: 'none',
  fx_source_cost: 'kango_fixed',
  fx_source_quote: 'kango_fixed',
  residual_mode: 'prorata',
  pkg_surcharge_billing: 'same_as_cost',
  parcel_band_cost_basis: 'box',
  parcel_quote_mode: 'each',
  vendor_bill_rounding: 'kango',
  air_std_rate_low_cad: '16.00',
  air_std_rate_high_cad: '18.00',
  air_std_threshold_kg: '21',
  sea_rate_cad: '9.00',
  markup_value: '0',
  kango_fixed_rate_vnd: '19500',
  sea_cost_vnd_per_kg: '120000',
  sea_cost_history: [{ effective_from: '2026-10-01', sea_cost_vnd_per_kg: '120000', source: 'owner' }],
};

describe('Settings → Pricing method', () => {
  it('sends only the fields that changed', () => {
    const base = { pricing_method: 'confirmed', sea_rate_cad: '9' };
    expect(changedFields({ ...base, sea_rate_cad: ' 9.5 ' }, base)).toEqual({ sea_rate_cad: '9.5' });
  });

  it('saves a changed rate and adds a dated sea cost', async () => {
    const user = userEvent.setup();
    const calls = { patch: null, sea: null };
    stubFetch([
      session(ADMIN),
      { path: '/pricing/method-settings', method: 'PATCH', body: (init) => {
        calls.patch = JSON.parse(init.body);
        return { ...METHOD, ...calls.patch };
      } },
      { path: '/pricing/method-settings', body: METHOD },
      { path: '/pricing/sea-cost', method: 'POST', status: 201, body: (init) => {
        calls.sea = JSON.parse(init.body);
        return METHOD;
      } },
    ]);
    renderWithProviders(
      <SessionProvider>
        <MethodSettingsPanel />
      </SessionProvider>,
    );
    const rate = await screen.findByLabelText(/Sea selling rate/);
    await user.clear(rate);
    await user.type(rate, '9.5');
    await user.click(screen.getByRole('button', { name: 'Save pricing method' }));
    await waitFor(() => expect(calls.patch).toEqual({ sea_rate_cad: '9.5' }));
    expect(await screen.findByText('Saved.')).toBeInTheDocument();

    expect(screen.getByRole('table', { name: 'Sea vendor cost history' })).toBeInTheDocument();
    await user.type(screen.getByLabelText(/^Cost \(VND per kg\)/), '125000');
    await user.type(screen.getByLabelText(/^Effective from/), '2026-11-01');
    await user.click(screen.getByRole('button', { name: 'Add sea cost' }));
    await waitFor(() =>
      expect(calls.sea).toEqual({ sea_cost_vnd_per_kg: '125000', effective_from: '2026-11-01' }),
    );
  });

  it('is read-only without settings:manage', async () => {
    stubFetch([session(OPS, 'operations'), { path: '/pricing/method-settings', body: METHOD }]);
    renderWithProviders(
      <SessionProvider>
        <MethodSettingsPanel />
      </SessionProvider>,
    );
    expect(await screen.findByLabelText(/Sea selling rate/)).toHaveAttribute('readonly');
    expect(screen.queryByRole('button', { name: 'Save pricing method' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Add sea cost' })).toBeNull();
  });
});

/* --- Settings → Pricing: the old markup is labelled RC25 only ----------------------------- */

describe('Settings → Pricing', () => {
  it('labels the old default markup "RC25 method only"', async () => {
    stubFetch([
      session(ADMIN),
      {
        path: '/pricing/settings',
        body: {
          air_standard_default_rate_cad: '18.00',
          air_express_default_rate_cad: '25.00',
          trigger_share_numerator: 2,
          trigger_share_denominator: 3,
          defaults_owner_confirmed: true,
          vendor_delivery_postal_code: 'L5A3K6',
          updated_at: '2026-10-20T10:00:00',
          default_markup_kind: 'percent',
          default_markup_value: '2.00',
          default_markup_in_effect: false,
        },
      },
      { path: '/pricing/policies', body: { items: [] } },
      { path: '/tariffs/versions', body: { items: [], total: 0 } },
    ]);
    renderWithProviders(
      <SessionProvider>
        <PricingSettingsPanel />
      </SessionProvider>,
    );
    expect(await screen.findByText('RC25 method only')).toBeInTheDocument();
    expect(screen.getByText(/has no effect under the confirmed method/)).toBeInTheDocument();
  });
});

/* --- Settings → Kango rate sheets --------------------------------------------------------- */

const DIFF = {
  version_public_id: 'TRF-000009',
  version_status: 'draft',
  against_version_public_id: 'TRF-000008',
  effective_from: '2026-11-01',
  source_file_name: 'kango_nov.xlsx',
  source_sha256: 'abcdef0123456789',
  fx: { old_vnd_per_cad: '19500', new_vnd_per_cad: '19600', changed: true },
  warehouse_zone: { fsa: 'L5A', ground_zone: 2, express_zone: 3 },
  piece_fees_changed: [],
  zones_summary: { changed: 1, added: 0, removed: 0 },
  summary: { surcharges_changed: 1, surcharges_added: 0, surcharges_removed: 0 },
  bracket_groups: [
    { origin: 'HCM', product_code: 'AIR_STD', zone: 2, kind: 'per_kg', changed: 3, added: 0, removed: 0, delta_min_vnd: '1000', delta_max_vnd: '2000' },
  ],
  surcharges_changed: [{ section: 'hcm_air', stt: 4, name: 'Pin', fields: ['amount'] }],
  surcharges_added: [],
  surcharges_removed: [],
  surcharges_excluded_non_canada: [{ section: 'hcm_air', stt: 40, name: 'US only' }],
  truncated: false,
};

const HISTORY = {
  versions: [
    { id: 9, public_id: 'TRF-000009', status: 'draft', effective_from: '2026-11-01', source_file_name: 'kango_nov.xlsx', source_sha256: 'abcdef0123456789', imported_at: '2026-11-01T10:00:00' },
    { id: 8, public_id: 'TRF-000008', status: 'active', effective_from: '2026-10-01', imported_at: '2026-10-01T10:00:00', activated_at: '2026-10-01T11:00:00' },
    { id: 7, public_id: 'TRF-000007', status: 'superseded', effective_from: '2026-09-01', imported_at: '2026-09-01T10:00:00', activated_at: '2026-09-01T11:00:00' },
  ],
};

const GRANTS = {
  'tariff:approve': [
    { user_id: 1, full_name: 'Demo Admin', email: 'admin@demo.example.com', role: 'admin', is_active: true },
  ],
};

function rateSheetRoutes({ approver, calls }) {
  return [
    { path: '/tariffs/intake/pending-count', body: { drafts: 1, held_intakes: 0, viewer_is_approver: approver } },
    { path: '/tariffs/rate-sheet/history', body: HISTORY },
    { path: '/tariffs/versions/9/rate-sheet-diff', body: DIFF },
    { path: '/tariffs/rate-sheet/import', method: 'POST', status: 201, body: () => {
      calls.imported = true;
      return { version: { id: 9, public_id: 'TRF-000009' }, diff: DIFF, next_step: 'confirm' };
    } },
    { path: '/tariffs/versions/9/approve', method: 'POST', body: () => {
      calls.approved = true;
      return { id: 9, status: 'active' };
    } },
    { path: '/tariffs/versions/7/rollback', method: 'POST', body: () => {
      calls.rolledBack = true;
      return { id: 7, status: 'active' };
    } },
    { path: '/staff/permission-grants', body: GRANTS },
    { path: '/staff/2/grants/tariff:approve', method: 'POST', body: () => {
      calls.granted = true;
      return GRANTS;
    } },
    { path: '/staff', body: [
      { id: 1, full_name: 'Demo Admin', email: 'admin@demo.example.com', role: 'admin', is_active: true },
      { id: 2, full_name: 'Demo Second', email: 'second@demo.example.com', role: 'admin', is_active: true },
      { id: 3, full_name: 'Demo Ops', email: 'ops@demo.example.com', role: 'operations', is_active: true },
    ] },
  ];
}

function renderRateSheets(permissions, approver) {
  const calls = {};
  stubFetch([session(permissions), ...rateSheetRoutes({ approver, calls })]);
  renderWithProviders(
    <SessionProvider>
      <RateSheetPanel />
    </SessionProvider>,
  );
  return calls;
}

describe('Settings → Kango rate sheets', () => {
  it('renders the diff the server computed', () => {
    renderWithProviders(<RateSheetDiff diff={DIFF} />);
    expect(screen.getByText(/Compared with the active version TRF-000008/)).toBeInTheDocument();
    expect(screen.getByText('Standard zone 2, Express zone 3')).toBeInTheDocument();
    expect(screen.getByRole('table', { name: /Air rates/ })).toHaveTextContent('AIR_STD');
    expect(screen.getByText(/Pin: amount/)).toBeInTheDocument();
    expect(screen.getByText(/Rows for other routes, excluded .*: 1/)).toBeInTheDocument();
  });

  it('uploads a sheet, shows its diff and lets an approver confirm it', async () => {
    const user = userEvent.setup();
    const calls = renderRateSheets(ADMIN, true);
    const file = new File(['demo'], 'kango_nov.xlsx', {
      type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    });
    await user.upload(await screen.findByLabelText(/Rate sheet \(.xlsx\)/), file);
    const upload = screen.getByRole('button', { name: 'Upload and compare' });
    expect(upload).toBeDisabled();
    await user.type(screen.getAllByLabelText(/Effective from/)[0], '2026-11-01');
    await user.click(upload);
    expect(await screen.findByText('Changes in TRF-000009')).toBeInTheDocument();
    expect(calls.imported).toBe(true);
    await user.click(screen.getByRole('button', { name: 'Confirm and activate' }));
    expect(await screen.findByText(/Confirmed. New masters now price on this sheet./)).toBeInTheDocument();
    expect(calls.approved).toBe(true);
  });

  it('offers rollback on a superseded version to an approver only', async () => {
    const user = userEvent.setup();
    const calls = renderRateSheets(ADMIN, true);
    const history = await screen.findByRole('table', { name: 'Version history' });
    const rows = within(history).getAllByRole('row');
    expect(within(rows[3]).getByRole('button', { name: 'Roll back to this' })).toBeInTheDocument();
    expect(within(rows[2]).queryByRole('button', { name: 'Roll back to this' })).toBeNull();
    await user.click(within(rows[3]).getByRole('button', { name: 'Roll back to this' }));
    await waitFor(() => expect(calls.rolledBack).toBe(true));
  });

  it('hides confirm and rollback from someone without the approver permission', async () => {
    const user = userEvent.setup();
    renderRateSheets(['settings:read', 'tariff:read', 'tariff:manage'], false);
    const history = await screen.findByRole('table', { name: 'Version history' });
    expect(within(history).queryByRole('button', { name: 'Roll back to this' })).toBeNull();
    await user.click(within(history).getAllByRole('button', { name: 'View changes' })[0]);
    expect(await screen.findByText('Only a rate-sheet approver can confirm or roll back.')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Confirm and activate' })).toBeNull();
    // Without staff:manage the approvers are listed but cannot be changed.
    expect(await screen.findByText('Demo Admin')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Give permission' })).toBeNull();
  });

  it('lets an Admin give the approver permission to another Admin only', async () => {
    const user = userEvent.setup();
    const calls = renderRateSheets(ADMIN, true);
    const select = await screen.findByLabelText('Give the permission to');
    await waitFor(() =>
      expect(within(select).getAllByRole('option').map((o) => o.textContent)).toContain(
        'Demo Second (second@demo.example.com)',
      ),
    );
    const labels = within(select).getAllByRole('option').map((o) => o.textContent);
    expect(labels.join(' ')).not.toMatch(/Demo Ops/);
    await user.selectOptions(select, '2');
    await user.click(screen.getByRole('button', { name: 'Give permission' }));
    await waitFor(() => expect(calls.granted).toBe(true));
  });
});
