/**
 * RC-20 (owner, 2026-10-23): Settings > Tariffs shows each version's import warnings -- the
 * count, the full list a page at a time -- and the owner-confirmed price steps apart (DEC-0222),
 * never counted as warnings. Mocked API; demo data only.
 */

import { describe, expect, it } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { SessionProvider } from '../src/app/SessionContext.jsx';
import { TariffBrowserPanel, WARNINGS_PAGE } from '../src/features/settings/TariffBrowserPanel.jsx';
import { renderWithProviders, stubFetch } from './utils.jsx';

function version(overrides) {
  return {
    vendor_key: 'kango',
    label: 'Demo rates',
    source_file_name: 'rates.xlsx',
    source_sha256: 'a'.repeat(64),
    effective_from: '2026-10-12',
    effective_to: null,
    imported_at: '2026-10-12T09:00:00',
    activated_at: '2026-10-12T10:00:00',
    dim_divisor_default: 6000,
    fixed_fx_vnd_per_cad: null,
    cost_currency: 'VND',
    review_decision: null,
    ...overrides,
  };
}

const VERSIONS = [
  version({ id: 4, public_id: 'TRF-000004', status: 'active' }),
  version({ id: 7, public_id: 'TRF-000007', status: 'superseded' }),
];

const ALL = Array.from({ length: 39 }, (_, i) => ({
  code: i < 35 ? 'express_zone_below_ground' : 'duplicate_fsa',
  message: `Demo warning ${i + 1}`,
  sheet: 'HCM-AIR-CAD',
  cell: `C${i + 10}`,
}));

const STEPS = [
  { sheet: 'HCM-AIR-CAD', cell: 'F39', product_code: 'AIR-CAD-EXP', zone: 2, label: '16', reference: 'DEC-0222', message: '', price_vnd: '1000000.00' },
  { sheet: 'HN-AIR-CAD', cell: 'F38', product_code: 'AIR-CAD-EXP', zone: 2, label: '16', reference: 'DEC-0222', message: '', price_vnd: '1100000.00' },
  { sheet: 'HN-AIR-CAD', cell: 'G38', product_code: 'AIR-CAD-EXP', zone: 3, label: '16', reference: 'DEC-0222', message: '', price_vnd: '1200000.00' },
];

function page(versionId, url, all, steps) {
  const params = new URL(url, 'http://test').searchParams;
  const limit = Number(params.get('limit'));
  const offset = Number(params.get('offset'));
  return {
    version_id: versionId,
    version_public_id: `TRF-00000${versionId}`,
    count: all.length,
    counts_by_code: all.reduce((acc, row) => ({ ...acc, [row.code]: (acc[row.code] || 0) + 1 }), {}),
    limit,
    offset,
    items: all.slice(offset, offset + limit),
    confirmed_price_steps: steps,
  };
}

function render() {
  const requested = [];
  const fetchMock = stubFetch([
    {
      path: '/auth/me',
      body: {
        user: { id: 2, full_name: 'Demo Ops', email: 'ops@demo.example.com', role: 'operations' },
        permissions: ['tariff:read'],
        environment: 'test',
        is_demo_environment: false,
      },
    },
    { path: '/products', body: [] },
    { path: '/accessorials', body: [] },
    { path: '/beyond-rates', body: [] },
    { path: '/tariffs/versions', body: { items: VERSIONS, total: VERSIONS.length } },
    { path: '/fx/history', body: { snapshots: [], attempts: [] } },
  ]);
  const original = fetchMock.getMockImplementation();
  fetchMock.mockImplementation(async (input, init) => {
    const url = typeof input === 'string' ? input : input.url;
    requested.push(url);
    const warnings = url.match(/\/tariffs\/versions\/(\d+)\/warnings/);
    if (warnings) {
      const id = Number(warnings[1]);
      const body = id === 4 ? page(4, url, ALL, STEPS) : page(id, url, [], []);
      return { ok: true, status: 200, headers: { get: () => 'application/json' }, json: async () => body };
    }
    return original(input, init);
  });
  renderWithProviders(
    <SessionProvider>
      <TariffBrowserPanel />
    </SessionProvider>,
  );
  return { requested };
}

describe('RC-20 tariff import warnings', () => {
  it('shows the count, the kinds and the first page of warnings of the active version', async () => {
    render();
    expect(await screen.findByRole('heading', { name: 'Import warnings (39) · TRF-000004' })).toBeInTheDocument();
    const list = await screen.findByRole('list', { name: 'Import warnings of TRF-000004' });
    expect(within(list).getAllByRole('listitem')).toHaveLength(WARNINGS_PAGE);
    expect(list).toHaveTextContent('Demo warning 1');
    expect(list).toHaveTextContent('HCM-AIR-CAD!C10');
    expect(screen.getByRole('list', { name: 'Warnings by kind' })).toHaveTextContent('express_zone_below_ground: 35');
    expect(screen.getByText('Showing 1-25 of 39.')).toBeInTheDocument();
  });

  it('pages through the full list', async () => {
    const user = userEvent.setup();
    const { requested } = render();
    await screen.findByRole('list', { name: 'Import warnings of TRF-000004' });
    expect(screen.getByRole('button', { name: 'Previous warnings' })).toBeDisabled();
    await user.click(screen.getByRole('button', { name: 'Next warnings' }));
    await screen.findByText('Showing 26-39 of 39.');
    const list = screen.getByRole('list', { name: 'Import warnings of TRF-000004' });
    expect(within(list).getAllByRole('listitem')).toHaveLength(14);
    expect(list).toHaveTextContent('Demo warning 39');
    expect(list).not.toHaveTextContent('Demo warning 1 ');
    expect(screen.getByRole('button', { name: 'Next warnings' })).toBeDisabled();
    expect(requested.some((url) => url.includes('/warnings') && url.includes('offset=25'))).toBe(true);
  });

  it('lists the three confirmed price steps apart, not as warnings', async () => {
    render();
    const steps = await screen.findByRole('list', { name: 'Confirmed price steps (3)' });
    expect(within(steps).getAllByRole('listitem')).toHaveLength(3);
    expect(steps).toHaveTextContent('HCM-AIR-CAD!F39');
    expect(steps).toHaveTextContent('HN-AIR-CAD!F38');
    expect(steps).toHaveTextContent('HN-AIR-CAD!G38');
    expect(within(steps).getAllByText('Confirmed')).toHaveLength(3);
    const warnings = await screen.findByRole('list', { name: 'Import warnings of TRF-000004' });
    expect(warnings).not.toHaveTextContent('F39');
  });

  it('shows each version its own warnings, none for a clean one', async () => {
    const user = userEvent.setup();
    render();
    await screen.findByRole('list', { name: 'Import warnings of TRF-000004' });
    await user.click(screen.getByRole('button', { name: 'View TRF-000007' }));
    expect(await screen.findByRole('heading', { name: 'Import warnings (0) · TRF-000007' })).toBeInTheDocument();
    expect(screen.getByText('The importer reported no warning for this version.')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Next warnings' })).toBeNull();
    await waitFor(() => expect(screen.getByRole('heading', { name: 'Confirmed price steps (0)' })).toBeInTheDocument());
  });
});
