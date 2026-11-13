/**
 * Shipment detail and the label drawer: header, tabs, snapshot display, permission-gated
 * financials, and the exact-ratio 4 × 6 preview.
 */

import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Route, Routes } from 'react-router-dom';
import { ShipmentDetailPage } from '../src/features/shipments/ShipmentDetailPage.jsx';
import { LabelPrintDrawer } from '../src/features/shipments/LabelPrintDrawer.jsx';
import { SessionProvider } from '../src/app/SessionContext.jsx';
import { renderWithProviders, stubFetch } from './utils.jsx';
import {
  LABEL_PREVIEW,
  SHIPMENT_DETAIL,
  SHIPMENT_META,
  STAFF_SESSION,
  packageFixture,
} from './shipmentFixtures.js';

const LEGS = [
  {
    id: 1,
    shipment_id: 10,
    sequence: 1,
    leg_type: 'origin_pickup',
    leg_type_label: 'Origin pickup',
    provider_name: 'Purolator',
    service_display: 'Ground pickup',
    origin_label: 'Customer address',
    origin_country_code: 'CA',
    destination_label: 'Solaris Mississauga warehouse',
    destination_country_code: 'CA',
    is_final_recipient_delivery: false,
    consolidation_reference: null,
    status: 'completed',
    scheduled_at: null,
    completed_at: '2026-08-03T10:00:00',
    internal_notes: null,
    package_ids: [1, 2, 3],
    package_references: ['SX-CAV-7K9D2M4R8T6W-01'],
    tracking_references: [
      {
        id: 5,
        leg_id: 1,
        package_id: null,
        package_reference: null,
        carrier_name: 'Purolator',
        tracking_number: 'PURO-4471902',
        public_url: null,
        source_mode: 'manual',
        source_mode_label: 'Manual',
        is_active: true,
        retired_at: null,
        retired_reason: null,
        created_at: '2026-08-03T10:00:00',
      },
    ],
  },
];

function renderDetail({
  shipment = SHIPMENT_DETAIL,
  session = STAFF_SESSION,
  events = [],
  route = '/shipments/10',
  extraRoutes = [],
} = {}) {
  const fetchMock = stubFetch([
    ...extraRoutes,
    { path: '/auth/me', body: session },
    { path: '/shipments/meta', body: SHIPMENT_META },
    { path: '/shipments/10/legs', body: LEGS },
    { path: '/shipments/10/events', body: events },
    { path: '/shipments/10/label-preview', body: LABEL_PREVIEW },
    { path: '/shipments/10/label-jobs', body: [] },
    { path: '/audit', body: { items: [], total: 0, limit: 50, offset: 0 } },
    { path: '/shipments/10', body: shipment },
  ]);
  // The page reads :shipmentId from the route, so the test mounts a real route.
  const utils = renderWithProviders(
    <SessionProvider>
      <Routes>
        <Route path="/shipments/:shipmentId" element={<ShipmentDetailPage />} />
      </Routes>
    </SessionProvider>,
    { route },
  );
  return { ...utils, fetchMock };
}

describe('ShipmentDetailPage', () => {
  it('shows a copyable monospace Solaris ID in the header', async () => {
    renderDetail();
    // The ID appears in the breadcrumb, the page title, and the copyable header block.
    expect(await screen.findByRole('heading', { name: 'SX-CAV-7K9D2M4R8T6W' })).toBeInTheDocument();
    expect(
      screen.getByRole('button', { name: /Copy SX-CAV-7K9D2M4R8T6W/ }),
    ).toBeInTheDocument();
  });

  it('shows package progress and the route lock in the header', async () => {
    renderDetail();
    expect(await screen.findByText('1 of 3 packages delivered')).toBeInTheDocument();
    expect(screen.getByText('Route locked')).toBeInTheDocument();
  });

  it('renders the Design.md tab structure', async () => {
    renderDetail();
    await screen.findAllByText('SX-CAV-7K9D2M4R8T6W');
    const tabs = screen.getByRole('tablist', { name: 'Shipments' });
    for (const label of [
      'Tracking',
      'Details',
      'Packages',
      'Transport legs',
      'Financials',
      'Notes & audit',
    ]) {
      expect(within(tabs).getByRole('tab', { name: new RegExp(`^${label}`) })).toBeInTheDocument();
    }
  });

  it('opens the tab named in the URL, so a filtered view is shareable', async () => {
    renderDetail({ route: '/shipments/10?tab=legs' });
    await screen.findAllByText('SX-CAV-7K9D2M4R8T6W');
    expect(screen.getByRole('tab', { name: /^Transport legs/ })).toHaveAttribute(
      'aria-selected',
      'true',
    );
    expect(await screen.findByText('Origin pickup')).toBeInTheDocument();
  });

  it('moves the selected tab when a different tab is chosen', async () => {
    const user = userEvent.setup();
    renderDetail();
    await screen.findAllByText('SX-CAV-7K9D2M4R8T6W');
    await user.click(screen.getByRole('tab', { name: /^Packages/ }));
    await waitFor(() =>
      expect(screen.getByRole('tab', { name: /^Packages/ })).toHaveAttribute(
        'aria-selected',
        'true',
      ),
    );
  });

  it('shows the address snapshots with a note that they are copies', async () => {
    const user = userEvent.setup();
    renderDetail();
    await screen.findAllByText('SX-CAV-7K9D2M4R8T6W');
    await user.click(screen.getByRole('tab', { name: 'Details' }));

    expect(await screen.findByText('Recipient (snapshot at booking)')).toBeInTheDocument();
    expect(screen.getByText('125 Đường Nguyễn Huệ')).toBeInTheDocument();
    expect(
      screen.getAllByText(/copied at booking time and are never rewritten/).length,
    ).toBeGreaterThan(0);
  });

  it('shows package references, both measurement systems, and a cancelled package', async () => {
    const user = userEvent.setup();
    renderDetail({
      shipment: {
        ...SHIPMENT_DETAIL,
        packages: [
          packageFixture(1),
          packageFixture(2, {
            is_active: false,
            cancellation_reason: 'Withdrawn by the customer',
            operational_state: 'cancelled',
            position_label: 'Package 2 (cancelled)',
          }),
          packageFixture(3, {
            weight_value: '12.500',
            weight_unit: 'lb',
            weight_kg: '5.670',
          }),
        ],
      },
    });
    await screen.findAllByText('SX-CAV-7K9D2M4R8T6W');
    await user.click(screen.getByRole('tab', { name: /^Packages/ }));

    expect(await screen.findByText('SX-CAV-7K9D2M4R8T6W-01')).toBeInTheDocument();
    expect(screen.getByText('Package 2 (cancelled)')).toBeInTheDocument();
    expect(screen.getByText('Withdrawn by the customer')).toBeInTheDocument();
    // Entered imperial weight and its canonical kilogram value both appear.
    expect(screen.getByText('12.5 lb (5.67 kg)')).toBeInTheDocument();
  });

  it('shows revenue and cost to an admin', async () => {
    const user = userEvent.setup();
    renderDetail();
    await screen.findAllByText('SX-CAV-7K9D2M4R8T6W');
    await user.click(screen.getByRole('tab', { name: 'Financials' }));
    expect(await screen.findByText('CAD 220.00')).toBeInTheDocument();
    expect(screen.getByText('CAD 140.00')).toBeInTheDocument();
  });

  it('shows gross profit beside the cost, and Unknown when the API sends null', async () => {
    const user = userEvent.setup();
    renderDetail({
      shipment: {
        ...SHIPMENT_DETAIL,
        financials: {
          ...SHIPMENT_DETAIL.financials,
          costs: { ...SHIPMENT_DETAIL.financials.costs, gross_profit: '68.00' },
        },
      },
    });
    await screen.findAllByText('SX-CAV-7K9D2M4R8T6W');
    await user.click(screen.getByRole('tab', { name: 'Financials' }));
    expect(await screen.findByText('Gross profit')).toBeInTheDocument();
    expect(screen.getByText('CAD 68.00')).toBeInTheDocument();
  });

  it('renders an unrecorded profit as Unknown rather than zero', async () => {
    const user = userEvent.setup();
    renderDetail({
      shipment: {
        ...SHIPMENT_DETAIL,
        financials: {
          ...SHIPMENT_DETAIL.financials,
          costs: { shipping_cost: null, surcharges_amount: null, gross_profit: null },
        },
      },
    });
    await screen.findAllByText('SX-CAV-7K9D2M4R8T6W');
    await user.click(screen.getByRole('tab', { name: 'Financials' }));
    await screen.findByText('Gross profit');
    expect(screen.queryByText('CAD 0.00')).toBeNull();
    expect(screen.getAllByText('Unknown').length).toBeGreaterThan(0);
  });

  it('omits the cost figures when the API sends no cost block', async () => {
    const user = userEvent.setup();
    // UAT round 3: the key is absent for a role without cost access, not `null`.
    const { costs: _omitted, ...withoutCosts } = SHIPMENT_DETAIL.financials;
    renderDetail({
      shipment: { ...SHIPMENT_DETAIL, financials: withoutCosts },
      session: {
        ...STAFF_SESSION,
        permissions: STAFF_SESSION.permissions.filter((item) => item !== 'financial_cost:read'),
      },
    });
    await screen.findAllByText('SX-CAV-7K9D2M4R8T6W');
    await user.click(screen.getByRole('tab', { name: 'Financials' }));
    expect(await screen.findByText('CAD 220.00')).toBeInTheDocument();
    expect(
      screen.getByText('Carrier and direct costs are restricted to administrators.'),
    ).toBeInTheDocument();
    expect(screen.queryByText('CAD 140.00')).not.toBeInTheDocument();
  });

  it('shows no financial panel at all when the API omits the block', async () => {
    const user = userEvent.setup();
    renderDetail({
      shipment: { ...SHIPMENT_DETAIL, financials: null },
      session: { ...STAFF_SESSION, permissions: ['shipment:read'] },
    });
    await screen.findAllByText('SX-CAV-7K9D2M4R8T6W');
    await user.click(screen.getByRole('tab', { name: 'Financials' }));
    expect(
      await screen.findByText('Your role does not include financial data.'),
    ).toBeInTheDocument();
  });

  it('states that no provider is connected on the transport legs tab', async () => {
    const user = userEvent.setup();
    renderDetail();
    await screen.findAllByText('SX-CAV-7K9D2M4R8T6W');
    await user.click(screen.getByRole('tab', { name: /^Transport legs/ }));

    expect(await screen.findByText('Origin pickup')).toBeInTheDocument();
    expect(screen.getByText('PURO-4471902')).toBeInTheDocument();
    expect(
      screen.getAllByText(/No provider account is connected/).length,
    ).toBeGreaterThan(0);
  });

  it('marks a manual event as internal and never promotes it to a public update', async () => {
    renderDetail({
      events: [
        {
          id: 1,
          shipment_id: 10,
          package_id: 1,
          package_reference: 'SX-CAV-7K9D2M4R8T6W-01',
          leg_id: null,
          event_type: 'in_transit',
          event_type_label: 'In transit',
          operational_state: 'in_transit',
          occurred_at: '2026-08-10T10:00:00',
          recorded_at: '2026-08-11T09:00:00',
          location_label: 'Toronto Pearson',
          location_country_code: 'CA',
          internal_detail: 'Customer owes a balance.',
          is_public_update: false,
          public_update_text: null,
          is_final_recipient_delivery: false,
          source: 'manual',
          is_voided: false,
          voided_reason: null,
          recorded_by: { id: 1, full_name: 'Test Admin', email: 'a@demo.example.com', role: 'admin' },
        },
      ],
    });
    expect(await screen.findByText('Customer owes a balance.')).toBeInTheDocument();
    expect(screen.getAllByText('Internal only').length).toBeGreaterThan(0);
    expect(screen.queryByText('Public update')).not.toBeInTheDocument();
  });

  it('hides cancel and rebook from a role without the cancel permission', async () => {
    renderDetail({
      session: { ...STAFF_SESSION, permissions: ['shipment:read', 'shipment:write'] },
    });
    await screen.findAllByText('SX-CAV-7K9D2M4R8T6W');
    expect(screen.queryByRole('button', { name: 'Cancel booking' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Cancel and rebook' })).not.toBeInTheDocument();
  });
});

describe('ShipmentDetailPage — UAT round 3', () => {
  async function openReferenceForm(user, extraRoutes = []) {
    const rendered = renderDetail({ route: '/shipments/10?tab=legs', extraRoutes });
    await screen.findByText('Origin pickup');
    await user.click(screen.getByRole('button', { name: 'Add carrier reference' }));
    // The form's submit button carries the same name as the button that opened it.
    const submit = await screen.findByRole('button', { name: 'Add carrier reference' });
    return { ...rendered, submit };
  }

  it('asks for the carrier before sending a reference with a blank one', async () => {
    const user = userEvent.setup();
    const { fetchMock, submit } = await openReferenceForm(user);

    await user.click(submit);

    expect(await screen.findByText('Choose a carrier.')).toBeInTheDocument();
    expect(screen.getByText('Enter the carrier tracking number.')).toBeInTheDocument();
    expect(screen.getByLabelText(/^Carrier/)).toHaveAttribute('aria-invalid', 'true');
    expect(
      fetchMock.mock.calls.some(([url]) => String(url).includes('/tracking-references')),
    ).toBe(false);
  });

  it('puts friendly wording beside the field, never the raw pydantic message', async () => {
    const user = userEvent.setup();
    await openReferenceForm(user, [
      {
        path: '/legs/1/tracking-references',
        method: 'POST',
        status: 422,
        body: {
          detail: [
            {
              type: 'string_too_short',
              loc: ['body', 'carrier_name'],
              msg: 'String should have at least 1 character',
            },
          ],
        },
      },
    ]);
    // A value the client accepts but the server refuses, so the 422 path is exercised.
    await user.selectOptions(screen.getByLabelText(/^Carrier/), 'UPS');
    await user.type(screen.getByLabelText(/^Tracking number/), '1Z999');
    await user.click(screen.getAllByRole('button', { name: 'Add carrier reference' }).at(-1));

    expect(await screen.findByText('Choose a carrier.')).toBeInTheDocument();
    expect(screen.queryByText(/String should have at least 1 character/)).toBeNull();
  });

  it('offers no Record event on a cancelled booking, and says why', async () => {
    renderDetail({
      shipment: { ...SHIPMENT_DETAIL, booking_state: 'cancelled', operational_state: 'cancelled' },
    });
    expect(
      await screen.findByText('This booking is cancelled, so no new events can be recorded.'),
    ).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Record event' })).toBeNull();
  });

  it('still offers Record event on a live booking', async () => {
    renderDetail();
    expect(await screen.findByRole('button', { name: 'Record event' })).toBeInTheDocument();
    expect(screen.queryByText(/no new events can be recorded/)).toBeNull();
  });

  it('moves focus into the Record event form, on its first field', async () => {
    const user = userEvent.setup();
    renderDetail();
    await user.click(await screen.findByRole('button', { name: 'Record event' }));

    const eventType = await screen.findByLabelText(/^Event type/);
    await waitFor(() => expect(eventType).toHaveFocus());
  });

  it('asks why the booking, not a package, is being cancelled or rebooked', async () => {
    const user = userEvent.setup();
    renderDetail();
    await screen.findAllByText('SX-CAV-7K9D2M4R8T6W');

    await user.click(screen.getByRole('button', { name: 'Cancel and rebook' }));
    const rebook = await screen.findByRole('dialog', { name: 'Cancel and rebook' });
    expect(within(rebook).getByLabelText(/Why is this booking being cancelled\?/)).toBeInTheDocument();
    expect(within(rebook).queryByText(/package/i)).toBeNull();
  });
});

describe('LabelPrintDrawer', () => {
  function renderDrawer(session = STAFF_SESSION, jobs = []) {
    stubFetch([
      { path: '/auth/me', body: session },
      { path: '/label-preview', body: LABEL_PREVIEW },
      { path: '/label-jobs', body: jobs },
    ]);
    return renderWithProviders(
      <SessionProvider>
        <LabelPrintDrawer open onClose={() => {}} shipmentId={10} />
      </SessionProvider>,
    );
  }

  it('previews one 4 × 6 page per active package at the exact ratio', async () => {
    renderDrawer();
    const previews = await screen.findAllByRole('img', { name: /label preview/ });
    expect(previews).toHaveLength(1); // one shown at a time; three are selectable
    expect(previews[0]).toHaveClass('label-preview');
    // Vitest does not load CSS, so the ratio is asserted against the stylesheet itself.
    const css = readFileSync(join(process.cwd(), 'src/features/shipments/shipments.css'), 'utf8');
    expect(css).toMatch(/\.label-preview\s*\{[^}]*aspect-ratio:\s*4\s*\/\s*6/);
    expect(screen.getAllByText(/SX-CAV-7K9D2M4R8T6W-0\d/).length).toBeGreaterThanOrEqual(3);
  });

  it('carries the exact internal-label warning', async () => {
    renderDrawer();
    expect(
      await screen.findByText('SOLARIS INTERNAL LABEL — NOT CARRIER POSTAGE.'),
    ).toBeInTheDocument();
  });

  it('gives actual-size printing instructions', async () => {
    renderDrawer();
    expect(await screen.findByText('Print at actual size')).toBeInTheDocument();
    expect(
      screen.getByText(/4 × 6 in, portrait, 100% scale, browser headers and footers off/),
    ).toBeInTheDocument();
  });

  it('does not claim a physical printer produced anything', async () => {
    renderDrawer();
    await screen.findByText('Print at actual size');
    expect(
      screen.getByText(/does not know whether a physical printer produced a label/),
    ).toBeInTheDocument();
  });

  it('shows the configured tracking base, not an assumed production domain', async () => {
    renderDrawer();
    await screen.findByText('Print at actual size');
    expect(screen.getByText('https://track.example.test/t')).toBeInTheDocument();
    expect(screen.queryByText(/track\.solarisexpress\.ca/)).not.toBeInTheDocument();
  });

  it('selects all active packages by default and allows a subset', async () => {
    const user = userEvent.setup();
    renderDrawer();
    await screen.findByText('Print at actual size');
    const selectAll = screen.getByRole('checkbox', { name: 'All active packages' });
    expect(selectAll).toBeChecked();

    await user.click(screen.getByRole('checkbox', { name: /SX-CAV-7K9D2M4R8T6W-02/ }));
    await waitFor(() => expect(selectAll).not.toBeChecked());
    expect(screen.getByRole('button', { name: 'Download PDF' })).toBeEnabled();
  });

  it('labels the action Reprint once labels have been generated before', async () => {
    renderDrawer(STAFF_SESSION, [
      {
        id: 1,
        shipment_id: 10,
        kind: 'all_active',
        is_reprint: false,
        page_count: 3,
        document_sha256: 'abc',
        generated_at: '2026-09-01T12:00:00',
        generated_by: { id: 1, full_name: 'Test Admin', email: 'a@demo.example.com', role: 'admin' },
        package_references: ['SX-CAV-7K9D2M4R8T6W-01'],
      },
    ]);
    expect(await screen.findByRole('button', { name: 'Reprint' })).toBeInTheDocument();
  });
});
