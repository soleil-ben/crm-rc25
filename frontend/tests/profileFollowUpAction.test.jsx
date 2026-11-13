/**
 * The profile's "Add follow-up" shortcut (UAT round 3).
 *
 * For a read-only manager it switched to a tab with no create control -- a button that
 * did nothing. It is now shown only to a role holding task:write.
 */

import { describe, expect, it } from 'vitest';
import { screen } from '@testing-library/react';
import { Route, Routes } from 'react-router-dom';
import { SessionProvider } from '../src/app/SessionContext.jsx';
import { CustomerProfilePage } from '../src/features/customers/CustomerProfilePage.jsx';
import { customerFixture, renderWithProviders, stubFetch } from './utils.jsx';

const PROFILE = {
  ...customerFixture,
  additional_route_interests: [],
  former_public_ids: [],
  merged_into_customer_id: null,
  is_demo_record: false,
  notes: null,
  primary_shipping_purpose: 'family_parcels',
  shipping_frequency: 'monthly',
  preferred_contact_channel: 'phone',
  best_contact_time: null,
  estimated_monthly_shipments: null,
  service_restriction_note: null,
  activity: {
    total_bookings: 3,
    total_qualifying_shipments: 3,
    delivered_shipments: 2,
    first_shipment_at: '2026-02-01T10:00:00',
    last_shipment_at: '2026-08-20T10:00:00',
    is_repeat_customer: true,
    observed_primary_route_group: 'CAV',
    has_service_issue: false,
    unresolved_issue_count: 0,
    open_task_count: 0,
    overdue_task_count: 0,
    next_follow_up_at: null,
    last_follow_up_at: null,
    referral_count: 0,
    qualified_referral_count: 0,
  },
};

function renderProfile({ role, permissions }) {
  stubFetch([
    {
      path: '/auth/me',
      body: {
        user: { id: 1, full_name: 'Test User', email: 'user@demo.example.com', role },
        permissions,
        environment: 'test',
        is_demo_environment: false,
      },
    },
    { path: '/customers/1/interactions', body: { items: [], total: 0, limit: 5, offset: 0 } },
    { path: '/customers/1', body: PROFILE },
  ]);
  return renderWithProviders(
    <SessionProvider>
      <Routes>
        <Route path="/customers/:customerId" element={<CustomerProfilePage />} />
      </Routes>
    </SessionProvider>,
    { route: '/customers/1' },
  );
}

describe('CustomerProfilePage — Add follow-up', () => {
  it('is hidden from a read-only manager, who cannot create a follow-up', async () => {
    renderProfile({
      role: 'read_only_manager',
      permissions: ['customer:read', 'shipment:read', 'task:read', 'interaction:read'],
    });
    // The card the shortcut lived in has rendered, so its absence is meaningful.
    await screen.findByText(/Last completed follow-up/);
    expect(screen.queryByRole('button', { name: 'Add follow-up' })).toBeNull();
  });

  it('is shown to a role that can create one', async () => {
    renderProfile({
      role: 'operations',
      permissions: ['customer:read', 'shipment:read', 'task:read', 'task:write', 'interaction:read'],
    });
    expect(await screen.findByRole('button', { name: 'Add follow-up' })).toBeInTheDocument();
  });
});
