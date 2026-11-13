/**
 * Dashboard honesty checks (CRM.md section 12, Design.md section 6).
 *
 * No fabricated percent change, queue cards labelled as current state, every card links
 * to its records, and empty data reads as empty rather than zero.
 */

import { describe, expect, it } from 'vitest';
import { screen } from '@testing-library/react';
import { DashboardPage } from '../src/features/dashboard/DashboardPage.jsx';
import { SessionProvider } from '../src/app/SessionContext.jsx';
import { renderWithProviders, stubFetch } from './utils.jsx';

const SESSION = {
  user: { id: 1, full_name: 'Test Admin', email: 'a@demo.example.com', role: 'admin', initials: 'TA', timezone: 'America/Toronto', locale: 'en' },
  permissions: ['dashboard:read'],
  environment: 'test',
  is_demo_environment: false,
};

const SUMMARY = {
  period_start: '2026-08-09T00:00:00',
  period_end: '2026-09-08T00:00:00',
  previous_period_available: false,
  kpis: [
    {
      key: 'new_customers',
      label: 'New customers',
      value: 4,
      definition: 'Customer records created in the selected period.',
      link: '/customers?created_from=2026-08-09',
      scope: 'period',
      comparison_value: null,
      comparison_label: null,
      tone: 'neutral',
    },
    {
      key: 'delivery_exceptions',
      label: 'Delivery exceptions',
      value: 2,
      definition: 'Shipments in an exception state. Current state.',
      link: '/shipments?exceptions_only=true',
      scope: 'current',
      comparison_value: null,
      comparison_label: null,
      tone: 'danger',
    },
  ],
  queues: [],
  shipment_trend: [],
  route_mix: [],
  lifecycle_mix: [
    { status: 'at_risk', count: 3, definition: 'Last shipment 61-90 days ago.', link: '/customers?lifecycle_status=at_risk' },
  ],
  follow_up_queue: [],
  recent_customers: [],
  repeat_shipper_share: null,
  data_notes: [
    'There is not enough history before this period to show a comparison, so change figures are omitted.',
  ],
};

function renderDashboard(summary = SUMMARY) {
  stubFetch([
    { path: '/auth/me', body: SESSION },
    { path: '/dashboard/summary', body: summary },
  ]);
  return renderWithProviders(
    <SessionProvider>
      <DashboardPage />
    </SessionProvider>,
  );
}

describe('DashboardPage', () => {
  it('omits a comparison line when the API supplies no prior-period figure', async () => {
    renderDashboard();
    expect(await screen.findByText('New customers')).toBeInTheDocument();
    expect(screen.getByText('No comparison available')).toBeInTheDocument();
    // Nothing invents a percentage.
    expect(screen.queryByText(/%\s*vs\./)).toBeNull();
  });

  it('labels queue cards as current state rather than period figures', async () => {
    renderDashboard();
    await screen.findByText('Delivery exceptions');
    expect(screen.getByText('Current state')).toBeInTheDocument();
  });

  it('links every KPI card to the records behind it', async () => {
    renderDashboard();
    const card = await screen.findByText('Delivery exceptions');
    const link = card.closest('a');
    expect(link).toHaveAttribute('href', '/shipments?exceptions_only=true');
  });

  it('shows charts as empty rather than drawing a zero line', async () => {
    renderDashboard();
    // The same honest title appears on the trend chart and the repeat-share card.
    expect((await screen.findAllByText('No qualifying shipments in this period')).length).toBeGreaterThan(0);
    expect(
      screen.getByText(/stays empty rather than drawing a flat zero line/i),
    ).toBeInTheDocument();
  });

  it('explains data limitations from the API notes', async () => {
    renderDashboard();
    expect(
      await screen.findByText(/not enough history before this period to show a comparison/i),
    ).toBeInTheDocument();
  });

  it('renders the repeat-shipper share as blank when there is nothing to divide', async () => {
    renderDashboard();
    expect(
      await screen.findByText(/left blank rather than shown as zero/i),
    ).toBeInTheDocument();
  });
});
