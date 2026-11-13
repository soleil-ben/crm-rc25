/** Shipment list: package progress text, filters, states, and the Design.md columns. */

import { describe, expect, it } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ShipmentListPage } from '../src/features/shipments/ShipmentListPage.jsx';
import { SessionProvider } from '../src/app/SessionContext.jsx';
import { renderWithProviders, stubFetch } from './utils.jsx';
import { SHIPMENT_LIST_ITEM, STAFF_SESSION } from './shipmentFixtures.js';

function renderList({ items = [SHIPMENT_LIST_ITEM], total = 1, status = 200, session = STAFF_SESSION } = {}) {
  stubFetch([
    { path: '/auth/me', body: session },
    { path: '/staff/assignable', body: [] },
    {
      path: '/shipments',
      status,
      body:
        status === 200
          ? { items, total, limit: 25, offset: 0 }
          : { code: 'permission_denied', message: 'Your role does not allow this action.' },
    },
  ]);
  return renderWithProviders(
    <SessionProvider>
      <ShipmentListPage />
    </SessionProvider>,
  );
}

describe('ShipmentListPage', () => {
  it('shows the Solaris ID, customer, and route with accents intact', async () => {
    renderList();
    expect(await screen.findByText('SX-CAV-7K9D2M4R8T6W')).toBeInTheDocument();
    expect(screen.getByText('Nguyễn Thị Bích Hạnh')).toBeInTheDocument();
    const table = screen.getByRole('table', { name: 'Shipments' });
    // The route badge and the direction line both say it; both belong in the row.
    expect(within(table).getAllByText('Canada to Vietnam').length).toBeGreaterThan(0);
  });

  it('renders package progress as "1 of 3 packages delivered", not a bare count', async () => {
    renderList();
    expect(await screen.findByText('1 of 3 packages delivered')).toBeInTheDocument();
  });

  it('distinguishes partially delivered from delivered', async () => {
    renderList();
    const table = await screen.findByRole('table', { name: 'Shipments' });
    expect(within(table).getByText('Partially delivered')).toBeInTheDocument();
    expect(within(table).queryByText('Delivered')).not.toBeInTheDocument();
  });

  it('shows a draft without a customer-facing identifier', async () => {
    renderList({
      items: [
        {
          ...SHIPMENT_LIST_ITEM,
          id: 11,
          public_id: null,
          booking_state: 'draft',
          operational_state: 'booked',
          package_progress: { total: 1, active: 1, cancelled: 0, delivered: 0, summary: '0 of 1 package delivered' },
        },
      ],
    });
    expect(await screen.findByText('Draft — no ID yet')).toBeInTheDocument();
    expect(screen.queryByText(/^SX-/)).not.toBeInTheDocument();
  });

  it('renders the default Design.md columns', async () => {
    renderList();
    const table = await screen.findByRole('table', { name: 'Shipments' });
    for (const heading of [
      'Solaris Shipment ID',
      'Customer',
      'Route',
      'Packages',
      'Operational status',
      'Carrier / provider',
      'Latest update',
      'Owner',
      'Booking date',
    ]) {
      expect(within(table).getByRole('columnheader', { name: heading })).toBeInTheDocument();
    }
  });

  it('keeps route and exception filters in the URL as removable chips', async () => {
    const user = userEvent.setup();
    renderList();
    await screen.findByRole('table', { name: 'Shipments' });

    await user.selectOptions(screen.getByLabelText('Route'), 'CAV');
    await waitFor(() => expect(screen.getByLabelText('Active filters')).toBeInTheDocument());
    const chips = screen.getByLabelText('Active filters');
    expect(within(chips).getByText('Canada to Vietnam')).toBeInTheDocument();

    await user.click(screen.getByLabelText('Exceptions only'));
    await waitFor(() =>
      expect(within(screen.getByLabelText('Active filters')).getByText('Exceptions only')).toBeInTheDocument(),
    );
  });

  it('explains an empty result rather than showing a blank table', async () => {
    const user = userEvent.setup();
    renderList({ items: [], total: 0 });
    await screen.findByRole('heading', { name: 'Shipments' });
    await user.type(screen.getByPlaceholderText(/Search Solaris ID/i), 'zzz');
    await waitFor(() =>
      expect(screen.getByText('No shipments match these filters')).toBeInTheDocument(),
    );
    expect(screen.getByRole('button', { name: 'Clear filters' })).toBeInTheDocument();
  });

  it('renders a permission-denied state rather than a generic error', async () => {
    renderList({ status: 403 });
    expect(await screen.findByText('You do not have access to this')).toBeInTheDocument();
  });

  it('hides the create-booking action from a role without shipment write', async () => {
    renderList({
      session: { ...STAFF_SESSION, permissions: ['shipment:read'] },
    });
    await screen.findByText('SX-CAV-7K9D2M4R8T6W');
    expect(screen.queryByRole('link', { name: 'Create booking' })).not.toBeInTheDocument();
  });
});
