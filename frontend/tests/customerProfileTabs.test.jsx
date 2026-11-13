/**
 * The two profile tabs the 2026-10-14 fix pack touched.
 *
 * * Duplicates (item 9; UAT-AD-04): a comparison is shown **before** anything merges, the
 *   merge needs the retiring ID typed exactly, and the survivor is where the page goes.
 * * Referrals (item 6): a referral says who recorded it and when.
 */

import { describe, expect, it, vi } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Route, Routes, useLocation } from 'react-router-dom';
import { SessionProvider } from '../src/app/SessionContext.jsx';
import { DuplicatesTab } from '../src/features/customers/tabs/DuplicatesTab.jsx';
import { ReferralsTab } from '../src/features/customers/tabs/ReferralsTab.jsx';
import { ShipmentsTab } from '../src/features/customers/tabs/ShipmentsTab.jsx';
import { customerFixture, renderWithProviders, stubFetch } from './utils.jsx';

function session(permissions) {
  return {
    path: '/auth/me',
    body: {
      user: { id: 1, full_name: 'Test Admin', email: 'admin@demo.example.com', role: 'admin' },
      permissions,
      environment: 'test',
      is_demo_environment: false,
    },
  };
}

const CANDIDATE = {
  ...customerFixture,
  id: 4,
  public_id: 'STCA-000004',
  full_name: 'Nguyen Thi Bich Hanh',
  email_entered: 'hanh.dup@example.com',
  lifecycle_status: 'prospect',
  total_qualifying_shipments: 0,
  last_shipment_at: null,
};

function LocationProbe() {
  const location = useLocation();
  return <p data-testid="location">{location.pathname}</p>;
}

function renderDuplicates(permissions, candidates = [CANDIDATE]) {
  const fetchMock = stubFetch([
    session(permissions),
    {
      path: '/customers/1/duplicate-candidates',
      body: {
        candidates: candidates.map((customer) => ({
          customer,
          matched_on: ['phone', 'name'],
          confidence: 80,
          requires_review: true,
        })),
        guidance: 'Review each candidate before deciding.',
      },
    },
    { path: '/customers/merge', method: 'POST', body: { ...customerFixture, id: 1 } },
  ]);
  const utils = renderWithProviders(
    <SessionProvider>
      <LocationProbe />
      <Routes>
        <Route path="/customers/:id" element={<DuplicatesTab customer={customerFixture} />} />
      </Routes>
    </SessionProvider>,
    { route: '/customers/1' },
  );
  return { ...utils, fetchMock };
}

describe('DuplicatesTab', () => {
  it('lays the two records out field by field before anything merges', async () => {
    renderDuplicates(['customer:read', 'duplicate:review', 'customer:merge']);

    const table = await screen.findByRole('table', { name: /Compare with Nguyen Thi Bich Hanh/ });
    expect(within(table).getByText('STCA-000001')).toBeInTheDocument();
    expect(within(table).getByText('STCA-000004')).toBeInTheDocument();
    expect(within(table).getByText('hanh.dup@example.com')).toBeInTheDocument();
    expect(within(table).getByText(/phone, name/)).toBeInTheDocument();
    // Nothing has been merged: no request beyond the candidate read went out.
    expect(window.fetch.mock.calls.some(([url]) => String(url).includes('/merge'))).toBe(false);
  });

  it('hides the merge control from a role that may review but not merge', async () => {
    renderDuplicates(['customer:read', 'duplicate:review']);
    await screen.findByRole('table', { name: /Compare with/ });
    expect(screen.queryByRole('button', { name: 'Merge' })).toBeNull();
    expect(screen.getByText(/Merging is restricted to administrators/)).toBeInTheDocument();
  });

  it('merges only after the retiring ID is typed exactly, then opens the survivor', async () => {
    const user = userEvent.setup();
    const { fetchMock } = renderDuplicates(['customer:read', 'duplicate:review', 'customer:merge']);
    await screen.findByRole('table', { name: /Compare with/ });

    await user.click(screen.getByRole('button', { name: 'Merge' }));
    const dialog = await screen.findByRole('dialog', { name: 'Merge these two customers' });
    const confirm = within(dialog).getByRole('button', { name: 'Merge' });
    expect(confirm).toBeDisabled();

    // Keeping this record retires the candidate, so the candidate's ID is what to type.
    expect(within(dialog).getByText(/STCA-000004 will be merged into STCA-000001/)).toBeInTheDocument();
    await user.type(within(dialog).getByLabelText(/Type STCA-000004 to confirm/), 'STCA-000003');
    expect(confirm).toBeDisabled();
    await user.clear(within(dialog).getByLabelText(/Type STCA-000004 to confirm/));
    await user.type(within(dialog).getByLabelText(/Type STCA-000004 to confirm/), 'stca-000004');
    expect(confirm).toBeEnabled();

    await user.click(confirm);

    await waitFor(() => {
      const call = fetchMock.mock.calls.find(([url]) => String(url).includes('/customers/merge'));
      expect(call).toBeTruthy();
      expect(JSON.parse(call[1].body)).toEqual({
        source_customer_id: 4,
        target_customer_id: 1,
        confirmation: 'STCA-000004',
      });
    });
    await waitFor(() => expect(screen.getByTestId('location')).toHaveTextContent('/customers/1'));
  });

  it('lets the reviewer keep the other record instead', async () => {
    const user = userEvent.setup();
    const { fetchMock } = renderDuplicates(['customer:read', 'duplicate:review', 'customer:merge']);
    await screen.findByRole('table', { name: /Compare with/ });
    await user.click(screen.getByRole('button', { name: 'Merge' }));
    const dialog = await screen.findByRole('dialog', { name: 'Merge these two customers' });

    await user.click(within(dialog).getByLabelText(/Keep the other record/));
    expect(within(dialog).getByText(/STCA-000001 will be merged into STCA-000004/)).toBeInTheDocument();
    await user.type(within(dialog).getByLabelText(/Type STCA-000001 to confirm/), 'STCA-000001');
    await user.click(within(dialog).getByRole('button', { name: 'Merge' }));

    await waitFor(() => {
      const call = fetchMock.mock.calls.find(([url]) => String(url).includes('/customers/merge'));
      expect(JSON.parse(call[1].body)).toMatchObject({
        source_customer_id: 1,
        target_customer_id: 4,
      });
    });
  });

  it('says plainly when there is nothing to compare', async () => {
    renderDuplicates(['customer:read', 'duplicate:review'], []);
    expect(await screen.findByText('No possible duplicates')).toBeInTheDocument();
  });
});

describe('ReferralsTab', () => {
  it('shows who recorded each referral and when', async () => {
    stubFetch([
      session(['customer:read', 'referral:read', 'referral:write']),
      {
        path: '/customers/1/referrals',
        body: [
          {
            id: 7,
            referrer: customerFixture,
            referred: CANDIDATE,
            note: 'Told us at the counter',
            created_at: '2026-09-12T10:00:00',
            referred_has_qualifying_shipment: false,
            recorded_by: { id: 3, full_name: 'Demo Operations', email: 'ops@demo.example.com', role: 'operations' },
          },
          {
            id: 8,
            referrer: { ...CANDIDATE, id: 9, public_id: 'STCA-000009', full_name: 'Lê Thị Mai Anh' },
            referred: customerFixture,
            note: null,
            created_at: '2026-08-01T10:00:00',
            referred_has_qualifying_shipment: true,
            recorded_by: null,
          },
        ],
      },
    ]);
    renderWithProviders(
      <SessionProvider>
        <ReferralsTab customer={customerFixture} />
      </SessionProvider>,
    );

    const table = await screen.findByRole('table', { name: /Customers referred by this customer/ });
    expect(within(table).getByText('Demo Operations')).toBeInTheDocument();
    expect(within(table).getByRole('columnheader', { name: 'Recorded by' })).toBeInTheDocument();
    // The "referred by" entry whose recorder is unknown says so instead of breaking.
    expect(screen.getByText(/Recorded by Unknown/)).toBeInTheDocument();
  });
});

describe('ReferralsTab refreshes both ends of a referral (fix pack 2 item 3)', () => {
  it('invalidates every referrals list and every customer record, not just this one', async () => {
    const user = userEvent.setup();
    stubFetch([
      session(['customer:read', 'referral:read', 'referral:write']),
      { path: '/customers/1/referrals', method: 'POST', body: { id: 9 } },
      { path: '/customers/1/referrals', body: [] },
      { path: '/search', body: { items: [CANDIDATE], total: 1, limit: 6, offset: 0 } },
    ]);
    const { queryClient } = renderWithProviders(
      <SessionProvider>
        <ReferralsTab customer={customerFixture} />
      </SessionProvider>,
    );
    const invalidate = vi.spyOn(queryClient, 'invalidateQueries');

    await screen.findByRole('button', { name: 'Record referral' });
    await user.click(screen.getByRole('button', { name: 'Record referral' }));
    await user.type(screen.getByPlaceholderText(/Search name/i), 'Nguyen');
    await user.click(await screen.findByRole('button', { name: /STCA-000004/ }));
    await user.click(screen.getByRole('button', { name: 'Save' }));

    // The prefixes, so the referred customer's cached tab and both customers' records
    // (and referral counts) refetch -- not only this customer's list.
    await waitFor(() => {
      expect(invalidate).toHaveBeenCalledWith({ queryKey: ['referrals'] });
    });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ['customer'] });
    expect(invalidate).not.toHaveBeenCalledWith({ queryKey: ['referrals', customerFixture.id] });
  });
});

describe('ShipmentsTab (UAT round 3 item a)', () => {
  const ACTIVITY = {
    total_qualifying_shipments: 0,
    total_bookings: 0,
    delivered_shipments: 0,
    first_shipment_at: null,
    last_shipment_at: null,
    route_counts: {},
  };

  function renderShipments(activity) {
    stubFetch([session(['customer:read'])]);
    renderWithProviders(
      <SessionProvider>
        <ShipmentsTab customer={{ ...customerFixture, activity }} />
      </SessionProvider>,
    );
  }

  it('carries no stale build-phase copy, and says plainly when nothing is recorded', async () => {
    renderShipments(ACTIVITY);

    expect(await screen.findByText('No bookings or shipments yet')).toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(/build phase|arrive in the next/i);
  });

  it('names where the figures come from once something is recorded', async () => {
    renderShipments({
      ...ACTIVITY,
      total_qualifying_shipments: 2,
      total_bookings: 3,
      route_counts: { CA_VN: 2 },
    });

    expect(
      await screen.findByText(
        'These figures come from the bookings and shipments recorded for this customer.',
      ),
    ).toBeInTheDocument();
    expect(screen.queryByText('No bookings or shipments yet')).not.toBeInTheDocument();
  });
});
