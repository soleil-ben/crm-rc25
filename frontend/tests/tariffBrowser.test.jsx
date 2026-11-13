/**
 * Phase 14, Settings → Tariffs: the read-only tariff browser. Mocked API; demo data only.
 *
 * Versions with their status (a rejected draft reads as rejected, 13H); a version's air
 * products (sea hidden) and their brackets, air accessorials, beyond-area rates; the FX
 * history with the demo label; the manual import (tariff:manage) whose result is a draft;
 * a draft's review where Approve and Reject appear only for a designated approver.
 */

import { describe, expect, it } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { SessionProvider } from '../src/app/SessionContext.jsx';
import { TariffBrowserPanel, versionState } from '../src/features/settings/TariffBrowserPanel.jsx';
import { renderWithProviders, stubFetch } from './utils.jsx';

function session(permissions) {
  return {
    path: '/auth/me',
    body: {
      user: { id: 1, full_name: 'Demo Admin', email: 'admin@demo.example.com', role: 'admin' },
      permissions,
      environment: 'test',
      is_demo_environment: false,
    },
  };
}

function version(overrides) {
  return {
    vendor_key: 'kango',
    label: 'Demo rates',
    source_file_name: 'rates.xlsx',
    source_sha256: 'a'.repeat(64),
    effective_from: '2026-10-12',
    effective_to: null,
    imported_at: '2026-10-12T09:00:00',
    activated_at: null,
    dim_divisor_default: 6000,
    fixed_fx_vnd_per_cad: null,
    cost_currency: 'VND',
    review_decision: null,
    ...overrides,
  };
}

const VERSIONS = [
  version({ id: 5, public_id: 'TRF-000005', status: 'draft', effective_from: '2026-10-19' }),
  version({ id: 4, public_id: 'TRF-000004', status: 'active', activated_at: '2026-10-12T10:00:00' }),
  version({ id: 3, public_id: 'TRF-000003', status: 'draft', review_decision: 'rejected' }),
];

const PRODUCTS = [
  {
    id: 41,
    code: 'AIR-CAD',
    origin: 'HCM',
    mode: 'air',
    last_mile: 'purolator_ground',
    dim_divisor: 6000,
    min_chargeable_kg: '1.000',
    transit_text: '7-10 days',
  },
  { id: 42, code: 'SEA-CAD', origin: 'HCM', mode: 'sea', last_mile: 'purolator_ground', dim_divisor: 6000 },
];

const DIFF = {
  version_id: 5,
  version_public_id: 'TRF-000005',
  against_version_public_id: 'TRF-000004',
  summary: {
    brackets_changed: 0,
    brackets_added: 0,
    brackets_removed: 0,
    surcharges_changed: 0,
    surcharges_added: 0,
    surcharges_removed: 0,
  },
  truncated: false,
  brackets_changed: [],
  brackets_added: [],
  brackets_removed: [],
  surcharges_changed: [],
  surcharges_added: [],
  surcharges_removed: [],
};

function renderBrowser(permissions, { approver = false } = {}) {
  const calls = { imported: null, approved: false };
  const fetchMock = stubFetch([
    session(permissions),
    {
      path: '/tariffs/versions/import',
      method: 'POST',
      status: 201,
      body: (init) => {
        calls.imported = init.body;
        return {
          ...version({ id: 6, public_id: 'TRF-000006', status: 'draft' }),
          counts: { products: 4, surcharge_rules: 120 },
          report: {
            anomalies: [
              { code: 'price_range', message: 'Row 31 has a price range; it needs the vendor.', sheet: 'PHU PHI', cell: 'D31' },
            ],
          },
        };
      },
    },
    {
      path: '/tariffs/versions/5/approve',
      method: 'POST',
      body: () => {
        calls.approved = true;
        return version({ id: 5, public_id: 'TRF-000005', status: 'active' });
      },
    },
    { path: '/tariffs/versions/5/diff', body: DIFF },
    { path: '/tariffs/versions/4/products/41', body: { ...PRODUCTS[0], brackets: [
      { kind: 'per_kg', zone: 2, label: '21-44', weight_from_kg: '21', weight_to_kg: '44', price_vnd: '250000' },
    ] } },
    { path: '/products', body: PRODUCTS },
    {
      path: '/accessorials',
      body: [
        { key: 'fuel', description: 'Fuel surcharge', amount: '5', currency: 'CAD', basis: 'per_shipment', applies_to_modes: 'air,sea' },
        { key: 'port', description: 'Port handling', amount: '40', currency: 'CAD', basis: 'per_shipment', applies_to_modes: 'sea' },
      ],
    },
    { path: '/beyond-rates', body: [{ beyond_code: 'B1', status: 'priced', base_cad: '12.50', per_lb_cad: '0.25' }] },
    // RC-20: each version's import warnings (rc20TariffWarnings.test.jsx covers the card).
    { path: '/warnings', body: { count: 0, counts_by_code: {}, items: [], confirmed_price_steps: [] } },
    { path: '/tariffs/versions', body: { items: VERSIONS, total: VERSIONS.length } },
    { path: '/tariffs/intake', body: { items: [], total: 0, viewer_is_approver: approver } },
    {
      path: '/fx/history',
      body: {
        snapshots: [
          {
            id: 1,
            bank: 'vietcombank',
            currency: 'CAD',
            cash_buy_vnd: '18000.00',
            transfer_buy_vnd: '18200.00',
            sell_vnd: '18900.00',
            bank_published_raw: '20/10/2026 08:00',
            bank_published_at: null,
            retrieved_at: '2026-10-20T08:05:00',
            is_demo: true,
          },
        ],
        attempts: [{ id: 9, attempted_at: '2026-10-20T08:05:00', outcome: 'success', error_summary: null, worker_name: 'fx' }],
      },
    },
  ]);
  renderWithProviders(
    <SessionProvider>
      <TariffBrowserPanel />
    </SessionProvider>,
  );
  return { calls, fetchMock };
}

/** The scrollable table region (the card around it carries the same name). */
async function tableRegion(name) {
  let found = null;
  await waitFor(() => {
    found = screen.getAllByRole('region', { name }).find((node) => node.querySelector(':scope > table'));
    expect(found).toBeTruthy();
  });
  return found;
}

const READER = ['tariff:read'];
const MANAGER = ['tariff:read', 'tariff:manage', 'settings:manage'];

describe('Tariff browser', () => {
  it('lists versions with their status, a rejected draft as rejected', async () => {
    renderBrowser(READER);
    const table = await tableRegion('Tariff versions');
    const rows = within(table).getAllByRole('row');
    expect(within(rows[1]).getByText('Draft')).toBeInTheDocument();
    expect(within(rows[2]).getByText('Active')).toBeInTheDocument();
    expect(within(rows[3]).getByText('Rejected by approver')).toBeInTheDocument();
  });

  it('opens the active version: air products only, brackets, air accessorials, beyond rates', async () => {
    const user = userEvent.setup();
    renderBrowser(READER);
    const products = await tableRegion('Air products');
    expect(within(products).getByText('AIR-CAD')).toBeInTheDocument();
    expect(within(products).queryByText('SEA-CAD')).toBeNull();
    await user.click(within(products).getByRole('button', { name: 'Rates AIR-CAD (HCM)' }));
    const brackets = await screen.findByRole('region', { name: 'Rate brackets of AIR-CAD (HCM)' });
    expect(within(brackets).getByText('21-44')).toBeInTheDocument();
    expect(within(brackets).getByText('250,000 VND')).toBeInTheDocument();
    const accessorials = await tableRegion('Accessorial charges');
    expect(within(accessorials).getByText('Fuel surcharge')).toBeInTheDocument();
    expect(within(accessorials).queryByText('Port handling')).toBeNull();
    const beyond = await tableRegion('Beyond-area rates');
    expect(within(beyond).getByText('B1')).toBeInTheDocument();
    expect(within(beyond).getByText('12.5')).toBeInTheDocument();
  });

  it('shows the exchange-rate history with the demo label', async () => {
    renderBrowser(READER);
    const fx = await tableRegion('Exchange-rate history (Vietcombank, CAD)');
    expect(within(fx).getByText('18,000 VND')).toBeInTheDocument();
    expect(within(fx).getByText('Demo rate')).toBeInTheDocument();
  });

  it('offers no import and no approval to a reader, and never asks the intake API', async () => {
    const user = userEvent.setup();
    const { fetchMock } = renderBrowser(READER);
    await tableRegion('Tariff versions');
    expect(screen.queryByRole('heading', { name: 'Import a workbook by hand' })).toBeNull();
    await user.click(screen.getByRole('button', { name: 'View TRF-000005' }));
    expect(await screen.findByText(/Compared with the active version TRF-000004/)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Approve and activate' })).toBeNull();
    expect(screen.getByText(/Only a designated approver/)).toBeInTheDocument();
    expect(fetchMock.mock.calls.some(([url]) => String(url).includes('/tariffs/intake'))).toBe(false);
  });

  it('shows Approve only to an approver, behind a confirmation', async () => {
    const user = userEvent.setup();
    const { calls } = renderBrowser(MANAGER, { approver: true });
    await tableRegion('Tariff versions');
    await user.click(screen.getByRole('button', { name: 'View TRF-000005' }));
    const approve = await screen.findByRole('button', { name: 'Approve and activate' });
    await waitFor(() => expect(approve).toBeEnabled());
    await user.click(approve);
    expect(calls.approved).toBe(false);
    await user.click(await screen.findByRole('button', { name: 'Yes, approve and activate' }));
    await waitFor(() => expect(calls.approved).toBe(true));
  });

  it('hides Approve from a manager who is not an approver; a rejected draft has no review', async () => {
    const user = userEvent.setup();
    renderBrowser(MANAGER, { approver: false });
    await tableRegion('Tariff versions');
    await user.click(screen.getByRole('button', { name: 'View TRF-000005' }));
    expect(await screen.findByText(/Only a designated approver/)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Approve and activate' })).toBeNull();
    await user.click(screen.getByRole('button', { name: 'View TRF-000003' }));
    await screen.findByRole('heading', { name: /TRF-000003 · Rejected by approver/ });
    expect(screen.getByText(/Rejected: this version stays a draft/)).toBeInTheDocument();
    expect(screen.queryByText(/Only a designated approver/)).toBeNull();
    expect(screen.queryByRole('button', { name: 'Reject' })).toBeNull();
  });

  it('imports a workbook by hand as a draft, after checking the form', async () => {
    const user = userEvent.setup();
    const { calls } = renderBrowser(MANAGER, { approver: true });
    await screen.findByRole('heading', { name: 'Import a workbook by hand' });
    await user.click(screen.getByRole('button', { name: 'Import as draft' }));
    expect(screen.getByText("Choose the vendor's .xlsx workbook.")).toBeInTheDocument();
    expect(screen.getByText('Enter the date the rates take effect.')).toBeInTheDocument();
    expect(calls.imported).toBeNull();

    const file = new File([new Uint8Array([0x50, 0x4b, 3, 4])], 'rates.xlsx', {
      type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    });
    await user.upload(screen.getByLabelText(/Vendor workbook/), file);
    await user.type(screen.getByLabelText(/Effective from/), '2026-10-26');
    await user.click(screen.getByRole('button', { name: 'Import as draft' }));
    expect(await screen.findByText(/Imported as draft TRF-000006/)).toBeInTheDocument();
    expect(calls.imported.get('effective_from')).toBe('2026-10-26');
    expect(calls.imported.get('file').name).toBe('rates.xlsx');
    // The importer's report: what was imported, and its warnings.
    expect(screen.getByRole('list', { name: 'What was imported' })).toHaveTextContent('Products: 4');
    const warnings = screen.getByRole('list', { name: 'Import warnings' });
    expect(warnings).toHaveTextContent('Row 31 has a price range; it needs the vendor. (PHU PHI!D31)');
  });

  it('refuses a workbook over 4 MB beside the file field, before any upload', async () => {
    const user = userEvent.setup();
    const { calls } = renderBrowser(MANAGER, { approver: true });
    await screen.findByRole('heading', { name: 'Import a workbook by hand' });
    const big = new File([new Uint8Array(4 * 1024 * 1024 + 1)], 'big.xlsx', {
      type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    });
    const input = screen.getByLabelText(/Vendor workbook/);
    await user.upload(input, big);
    expect(screen.getByText(/larger than 4 MB/)).toBeInTheDocument();
    expect(input).toHaveAttribute('aria-invalid', 'true');
    await user.type(screen.getByLabelText(/Effective from/), '2026-10-26');
    await user.click(screen.getByRole('button', { name: 'Import as draft' }));
    expect(calls.imported).toBeNull();
  });
});

describe('versionState', () => {
  it('reads a rejected draft as rejected and leaves the rest alone', () => {
    expect(versionState({ status: 'draft', review_decision: 'rejected' })).toBe('rejected');
    expect(versionState({ status: 'draft', review_decision: null })).toBe('draft');
    expect(versionState({ status: 'active', review_decision: 'approved' })).toBe('active');
  });
});
