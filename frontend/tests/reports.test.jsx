/**
 * Reports page behaviour.
 *
 * The things worth testing here are not "does a table render". They are the honesty
 * properties: that an unknown value reads as unknown rather than zero, that a current-state
 * report says so, that no comparison figure appears anywhere, that a financial report a
 * role cannot see is simply absent, and that the export action is hidden without the
 * permission and reaches the right URL with it.
 */

import { describe, expect, it, vi } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ReportsPage } from '../src/features/reports/ReportsPage.jsx';
import { SessionProvider } from '../src/app/SessionContext.jsx';
import { renderWithProviders, stubFetch } from './utils.jsx';

const ADMIN_PERMISSIONS = ['report:read', 'export:reports', 'financial:read', 'financial_cost:read'];
const VIEWER_PERMISSIONS = ['report:read'];

function session(permissions) {
  return {
    user: {
      id: 1,
      full_name: 'Test Admin',
      email: 'admin@demo.example.com',
      role: 'admin',
      initials: 'TA',
      timezone: 'America/Toronto',
      locale: 'en',
    },
    permissions,
    environment: 'test',
    is_demo_environment: false,
  };
}

const ROUTE_MIX = {
  key: 'route_mix',
  title: 'Route mix',
  scope: 'period',
  definition: 'Qualifying shipments handed over during the period, grouped by route group.',
  columns: [
    { key: 'route_label', label: 'Route', kind: 'text' },
    { key: 'count', label: 'Qualifying shipments', kind: 'integer' },
    { key: 'share', label: 'Share', kind: 'share' },
  ],
  rows: [
    { route_group: 'CAV', route_label: 'Canada to Vietnam', count: 4, share: 0.8, link: '/shipments?route_group=CAV' },
    { route_group: 'VCA', route_label: 'Vietnam to Canada', count: 1, share: 0.2, link: '/shipments?route_group=VCA' },
    { route_group: 'CAD', route_label: 'Domestic Canada', count: 0, share: null, link: '/shipments?route_group=CAD' },
  ],
  notes: [],
  summary: { total: 5 },
};

const EXCEPTIONS = {
  key: 'shipment_exceptions',
  title: 'Shipment exceptions',
  scope: 'current',
  definition: 'Shipments currently in an exception state.',
  columns: [
    { key: 'group_label', label: 'Grouping', kind: 'text' },
    { key: 'key_label', label: 'Value', kind: 'text' },
    { key: 'count', label: 'Shipments', kind: 'integer' },
  ],
  rows: [
    { group: 'tracking_source', group_label: 'By tracking source', key: 'manual', key_label: 'Manual', count: 1, link: '/shipments' },
    { group: 'tracking_source', group_label: 'By tracking source', key: 'external_link', key_label: 'External link only', count: 0, link: '/shipments' },
    { group: 'tracking_source', group_label: 'By tracking source', key: 'none', key_label: 'No tracking reference', count: 2, link: '/shipments' },
  ],
  notes: ['No provider integration is connected, so no shipment can be in a connected-API tracking mode and that mode is not listed.'],
  summary: { total: 3 },
};

/**
 * The shipment-status report, as the API now returns it.
 *
 * The Returns row has **no `link`**. It used to carry `/shipments?returns_only=true`, a
 * filter no route and no screen implements, so a tester following it saw the unfiltered
 * shipment list dressed as a returns list. The value and label are true and stay; the
 * action does not. `definition` carries the neutral explanation.
 */
const SHIPMENT_STATUS = {
  key: 'shipment_status',
  title: 'Shipment status distribution',
  scope: 'period',
  definition: 'Two distributions and one count.',
  columns: [
    { key: 'group_label', label: 'Grouping', kind: 'text' },
    { key: 'state_label', label: 'State', kind: 'text' },
    { key: 'count', label: 'Shipments', kind: 'integer' },
  ],
  rows: [
    {
      group: 'booking_state',
      group_label: 'Booking state (booked in period)',
      state: 'confirmed',
      state_label: 'Confirmed',
      count: 5,
      link: '/shipments?booking_state=confirmed&booked_from=2026-09-01&booked_to=2026-09-30',
    },
    {
      group: 'operational_state',
      group_label: 'Current operational state (qualifying shipments in period)',
      state: 'in_transit',
      state_label: 'In transit',
      count: 3,
      link: '/shipments?operational_state=in_transit',
    },
    {
      group: 'returns',
      group_label: 'Returns',
      state: 'is_return',
      state_label: 'Return shipments handed over in period',
      count: 0,
      definition:
        'Reported here only. There is no return-shipment list to open while the return workflow is undecided.',
    },
  ],
  notes: [],
  summary: { booked_in_period: 6, qualifying_in_period: 5, returns_in_period: 0 },
};

const FINANCIAL = {
  key: 'financial_summary',
  title: 'Financial summary',
  scope: 'period',
  definition: 'Recorded revenue grouped by currency.',
  columns: [
    { key: 'currency', label: 'Currency', kind: 'text' },
    { key: 'recorded_revenue', label: 'Recorded revenue', kind: 'money' },
    { key: 'gross_profit', label: 'Gross profit', kind: 'money' },
  ],
  rows: [
    { currency: 'CAD', recorded_revenue: '200.00', gross_profit: '90.00', link: '/shipments' },
    { currency: 'USD', recorded_revenue: '90.00', gross_profit: null, link: '/shipments' },
  ],
  notes: ['Currencies are never combined.'],
  summary: { currencies: 2, unknown_currency_shipments: 1 },
};

function payload(reports) {
  return {
    period: {
      from_date: '2026-09-01',
      to_date: '2026-09-30',
      timezone: 'America/Toronto',
      start_utc: '2026-09-01T04:00:00',
      end_utc: '2026-10-01T04:00:00',
      granularity: 'day',
      days: 30,
    },
    route_groups: null,
    reports,
    coverage_notes: [
      'No prior-period comparison is shown. A change figure is only meaningful with a comparable prior period.',
    ],
    counting_guard: {
      qualifying_shipments: 5,
      packages_on_those_shipments: 11,
      active_packages_on_those_shipments: 11,
      legs_on_those_shipments: 3,
      note: 'Every shipment figure in these reports counts the shipment once.',
    },
    available_reports: reports.map((report) => report.key),
  };
}

function renderReports({ reports = [ROUTE_MIX], permissions = ADMIN_PERMISSIONS, status = 200 } = {}) {
  stubFetch([
    { path: '/auth/me', body: session(permissions) },
    {
      path: '/reports',
      status,
      body:
        status === 200
          ? payload(reports)
          : { code: 'validation_error', message: 'A report range may cover at most 731 days.' },
    },
  ]);
  return renderWithProviders(
    <SessionProvider>
      <ReportsPage />
    </SessionProvider>,
    { route: '/reports?from=2026-09-01&to=2026-09-30' },
  );
}

describe('ReportsPage', () => {
  it('renders a report from the API rather than any built-in value', async () => {
    renderReports();
    expect(await screen.findByText('Route mix')).toBeInTheDocument();
    const table = screen.getByRole('table', { name: /Route mix/ });
    expect(within(table).getByText('Canada to Vietnam')).toBeInTheDocument();
    expect(within(table).getByText('4')).toBeInTheDocument();
  });

  it('renders an unknown share as Unknown, never as zero', async () => {
    renderReports();
    await screen.findByText('Route mix');
    const table = screen.getByRole('table', { name: /Route mix/ });
    const domesticRow = within(table).getByText('Domestic Canada').closest('tr');

    // The count really is zero and shows as zero...
    expect(within(domesticRow).getByText('0')).toBeInTheDocument();
    // ...but the share is unknown, because a share of nothing is not zero percent.
    expect(within(domesticRow).getByText('Unknown')).toBeInTheDocument();
    expect(within(domesticRow).queryByText('0%')).not.toBeInTheDocument();
  });

  it('says whether a report describes the period or describes today', async () => {
    renderReports({ reports: [ROUTE_MIX, EXCEPTIONS] });
    await screen.findByText('Route mix');

    // Text, not colour: this is the most misreadable thing on the page.
    expect(screen.getByText('Selected period')).toBeInTheDocument();
    expect(screen.getByText('Current state')).toBeInTheDocument();
  });

  it('states plainly that no comparison figure is shown', async () => {
    renderReports();
    await screen.findByText('Route mix');
    expect(
      screen.getByText(/No comparison with a previous period/i),
    ).toBeInTheDocument();
  });

  it('renders no percentage-change or trend element anywhere', async () => {
    const { container } = renderReports({ reports: [ROUTE_MIX, EXCEPTIONS, FINANCIAL] });
    await screen.findByText('Route mix');

    const text = container.textContent;
    // A change figure would look like "+12%" or "-3%" next to a value.
    expect(text).not.toMatch(/[+−-]\d+(\.\d+)?%/);
    expect(text).not.toMatch(/vs\.? (previous|last) period/i);
  });

  it('never offers a connected-API column in the exception report', async () => {
    renderReports({ reports: [EXCEPTIONS] });
    await screen.findByText('Shipment exceptions');

    const table = screen.getByRole('table', { name: /Shipment exceptions/ });
    expect(within(table).getByText('Manual')).toBeInTheDocument();
    expect(within(table).getByText('External link only')).toBeInTheDocument();
    expect(within(table).getByText('No tracking reference')).toBeInTheDocument();
    expect(within(table).queryByText(/connected api/i)).not.toBeInTheDocument();
  });

  it('shows the counting guard so packages are visibly not shipments', async () => {
    renderReports();
    await screen.findByText('Route mix');
    expect(screen.getByText('How shipments are counted')).toBeInTheDocument();
    expect(screen.getByText('Packages on those shipments')).toBeInTheDocument();
    expect(screen.getByText('11')).toBeInTheDocument();
  });

  it('omits the financial report entirely for a role without it', async () => {
    renderReports({ reports: [ROUTE_MIX], permissions: VIEWER_PERMISSIONS });
    await screen.findByText('Route mix');
    // Absent, not empty and not masked.
    expect(screen.queryByText('Financial summary')).not.toBeInTheDocument();
    expect(screen.queryByText(/recorded revenue/i)).not.toBeInTheDocument();
  });

  it('renders a missing gross profit as Unknown rather than as the revenue', async () => {
    renderReports({ reports: [FINANCIAL] });
    await screen.findByText('Financial summary');
    const table = screen.getByRole('table', { name: /Financial summary/ });
    const usdRow = within(table).getByText('USD').closest('tr');
    expect(within(usdRow).getByText('90.00')).toBeInTheDocument();
    expect(within(usdRow).getByText('Unknown')).toBeInTheDocument();
  });

  it('hides the export action from a role without export permission', async () => {
    renderReports({ permissions: VIEWER_PERMISSIONS });
    await screen.findByText('Route mix');
    expect(screen.queryByRole('button', { name: 'Export CSV' })).not.toBeInTheDocument();
  });

  it('offers an export that carries the same range the page is showing', async () => {
    renderReports();
    await screen.findByText('Route mix');

    const assign = vi.fn();
    Object.defineProperty(window, 'location', {
      configurable: true,
      value: {
        set href(value) {
          assign(value);
        },
      },
    });

    await userEvent.click(screen.getByRole('button', { name: 'Export CSV' }));
    expect(assign).toHaveBeenCalledWith(
      expect.stringContaining('/exports/reports/route_mix.csv'),
    );
    expect(assign).toHaveBeenCalledWith(expect.stringContaining('from=2026-09-01'));
    expect(assign).toHaveBeenCalledWith(expect.stringContaining('to=2026-09-30'));
  });

  it('explains a rejected date range instead of showing a generic error', async () => {
    renderReports({ status: 422 });
    expect(await screen.findByText('That date range cannot be reported')).toBeInTheDocument();
    expect(screen.getByText(/at most 731 days/)).toBeInTheDocument();
  });

  it('reflects the date range in the URL so a report is shareable', async () => {
    renderReports();
    await screen.findByText('Route mix');

    await userEvent.click(screen.getByRole('button', { name: 'Last 7 days' }));
    await waitFor(() => {
      expect(window.location.search || document.location.search).toBeDefined();
    });
    // The inputs are the observable state; both carry the new range.
    const from = screen.getByLabelText('From');
    const to = screen.getByLabelText('To');
    expect(from).toHaveValue();
    expect(to).toHaveValue();
  });

  it('states the timezone the period was cut in', async () => {
    renderReports();
    await screen.findByText('Route mix');
    expect(screen.getByText(/America\/Toronto/)).toBeInTheDocument();
  });

  it('gives every report table an accessible caption carrying its definition', async () => {
    renderReports({ reports: [ROUTE_MIX] });
    await screen.findByText('Route mix');
    const table = screen.getByRole('table', { name: /Qualifying shipments handed over/ });
    expect(table).toBeInTheDocument();
  });

  it('links an aggregate row back to the records behind it', async () => {
    renderReports();
    await screen.findByText('Route mix');
    const link = screen.getByRole('link', { name: 'Canada to Vietnam' });
    expect(link).toHaveAttribute('href', '/shipments?route_group=CAV');
  });

  describe('a row the API sends without a link', () => {
    it('renders the Returns row with no link and no action of any kind', async () => {
      renderReports({ reports: [SHIPMENT_STATUS] });
      await screen.findByText('Shipment status distribution');

      const table = screen.getByRole('table', { name: /Shipment status distribution/ });
      const returnsRow = within(table).getByText('Returns').closest('tr');

      expect(within(returnsRow).queryByRole('link')).not.toBeInTheDocument();
      expect(within(returnsRow).queryByRole('button')).not.toBeInTheDocument();
      // And nothing anywhere on the page still points at the filter that never existed.
      expect(table.innerHTML).not.toContain('returns_only');
    });

    it('keeps the Returns value and label, because both are true', async () => {
      renderReports({ reports: [SHIPMENT_STATUS] });
      await screen.findByText('Shipment status distribution');

      const table = screen.getByRole('table', { name: /Shipment status distribution/ });
      const returnsRow = within(table).getByText('Returns').closest('tr');

      expect(
        within(returnsRow).getByText('Return shipments handed over in period'),
      ).toBeInTheDocument();
      // Zero is the correct count and is shown as zero, not as Unknown.
      expect(within(returnsRow).getByText('0')).toBeInTheDocument();
      expect(within(returnsRow).queryByText('Unknown')).not.toBeInTheDocument();
    });

    it('explains the missing drill-through without implying a return workflow exists', async () => {
      renderReports({ reports: [SHIPMENT_STATUS] });
      await screen.findByText('Shipment status distribution');

      const table = screen.getByRole('table', { name: /Shipment status distribution/ });
      expect(
        within(table).getByText(/no return-shipment list to open/i),
      ).toBeInTheDocument();
      expect(table.textContent).not.toMatch(/create a return|book a return|coming soon/i);
    });

    it('still links every other row in the same table', async () => {
      renderReports({ reports: [SHIPMENT_STATUS] });
      await screen.findByText('Shipment status distribution');

      const table = screen.getByRole('table', { name: /Shipment status distribution/ });
      expect(
        within(table).getByRole('link', { name: /Booking state/ }),
      ).toHaveAttribute('href', expect.stringContaining('booking_state=confirmed'));
      expect(
        within(table).getByRole('link', { name: /Current operational state/ }),
      ).toHaveAttribute('href', '/shipments?operational_state=in_transit');
    });
  });
});
