/**
 * RC-20 (owner, 2026-10-23): the staff shipment view's transport legs.
 *
 * - Each leg shows its generic tracking name as customers read it: "Master Tracking" for
 *   origin pickup and consolidation / linehaul, "Last Mile Tracking" for every other leg
 *   (DEC-0224), in English and Vietnamese. Staff still see the stored provider.
 * - The final delivery leg's provider picker offers the vendor, like the other legs.
 */
import { describe, expect, it } from 'vitest';
import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Route, Routes } from 'react-router-dom';
import { ShipmentDetailPage } from '../src/features/shipments/ShipmentDetailPage.jsx';
import { SessionProvider } from '../src/app/SessionContext.jsx';
import { I18nProvider } from '../src/i18n/index.jsx';
import { renderWithProviders, stubFetch } from './utils.jsx';
import { SHIPMENT_DETAIL, SHIPMENT_META, STAFF_SESSION } from './shipmentFixtures.js';

const VENDOR = 'Kango Logistics';
const LEG_TYPES = ['origin_pickup', 'consolidation_linehaul', 'destination_handling', 'final_delivery'];
const PROVIDERS = [VENDOR, 'UPS', 'Vietnam Post', 'Other'];

const META = {
  ...SHIPMENT_META,
  leg_types: [
    { value: 'origin_pickup', label: 'Origin pickup' },
    { value: 'consolidation_linehaul', label: 'Consolidation linehaul' },
    { value: 'destination_handling', label: 'Destination handling' },
    { value: 'final_delivery', label: 'Final delivery' },
  ],
  leg_providers: Object.fromEntries(LEG_TYPES.map((legType) => [legType, PROVIDERS])),
};

const KEYS = {
  origin_pickup: 'master_tracking',
  consolidation_linehaul: 'master_tracking',
  destination_handling: 'last_mile_tracking',
  final_delivery: 'last_mile_tracking',
};

const LEGS = LEG_TYPES.map((legType, index) => ({
  id: index + 1,
  shipment_id: 10,
  sequence: index + 1,
  leg_type: legType,
  leg_type_label: legType,
  tracking_name_key: KEYS[legType],
  provider_name: index === 3 ? VENDOR : 'UPS',
  service_display: null,
  origin_label: null,
  origin_country_code: null,
  destination_label: null,
  destination_country_code: null,
  is_final_recipient_delivery: legType === 'final_delivery',
  consolidation_reference: null,
  status: 'planned',
  scheduled_at: null,
  completed_at: null,
  internal_notes: null,
  package_ids: [],
  package_references: [],
  tracking_references: [],
}));

function renderLegs(locale = 'en') {
  stubFetch([
    { path: '/auth/me', body: STAFF_SESSION },
    { path: '/shipments/meta', body: META },
    { path: '/shipments/10/legs', body: LEGS },
    { path: '/shipments/10/events', body: [] },
    { path: '/shipments/10/label-preview', body: {} },
    { path: '/shipments/10/label-jobs', body: [] },
    { path: '/audit', body: { items: [], total: 0, limit: 50, offset: 0 } },
    { path: '/shipments/10', body: SHIPMENT_DETAIL },
  ]);
  return renderWithProviders(
    <I18nProvider initialLocale={locale}>
      <SessionProvider>
        <Routes>
          <Route path="/shipments/:shipmentId" element={<ShipmentDetailPage />} />
        </Routes>
      </SessionProvider>
    </I18nProvider>,
    { route: '/shipments/10?tab=legs' },
  );
}

async function legItems() {
  const labels = await screen.findAllByTestId('leg-tracking-name');
  return labels.map((label) => label.closest('li'));
}

describe('RC-20 staff legs: generic tracking name per leg', () => {
  it('shows Master Tracking and Last Mile Tracking per leg type, with the stored provider', async () => {
    renderLegs();
    const items = await legItems();
    expect(items).toHaveLength(4);
    const names = (await screen.findAllByTestId('leg-tracking-name')).map((node) => node.textContent);
    expect(names).toEqual(['Master Tracking', 'Master Tracking', 'Last Mile Tracking', 'Last Mile Tracking']);
    expect(within(items[0]).getByText('Origin pickup')).toBeInTheDocument();
    expect(within(items[3]).getByText('Final delivery', { selector: 'strong' })).toBeInTheDocument();
    // Staff still read the provider as stored.
    expect(within(items[3]).getByText(VENDOR)).toBeInTheDocument();
    // The generic name itself never carries a vendor or carrier name.
    for (const name of names) {
      expect(name).not.toMatch(/Kango|UPS|Vietnam Post/);
    }
  });

  it('shows the Vietnamese names in Vietnamese', async () => {
    renderLegs('vi');
    const names = (await screen.findAllByTestId('leg-tracking-name')).map((node) => node.textContent);
    expect(names).toEqual([
      'Theo dõi chặng chính',
      'Theo dõi chặng chính',
      'Theo dõi chặng cuối',
      'Theo dõi chặng cuối',
    ]);
  });

  it('derives the name from the leg type when the key is absent', async () => {
    const legTypeless = LEGS.map((leg) => {
      const copy = { ...leg };
      delete copy.tracking_name_key;
      return copy;
    });
    stubFetch([
      { path: '/auth/me', body: STAFF_SESSION },
      { path: '/shipments/meta', body: META },
      { path: '/shipments/10/legs', body: legTypeless },
      { path: '/shipments/10/events', body: [] },
      { path: '/shipments/10/label-preview', body: {} },
      { path: '/shipments/10/label-jobs', body: [] },
      { path: '/audit', body: { items: [], total: 0, limit: 50, offset: 0 } },
      { path: '/shipments/10', body: SHIPMENT_DETAIL },
    ]);
    renderWithProviders(
      <SessionProvider>
        <Routes>
          <Route path="/shipments/:shipmentId" element={<ShipmentDetailPage />} />
        </Routes>
      </SessionProvider>,
      { route: '/shipments/10?tab=legs' },
    );
    const names = (await screen.findAllByTestId('leg-tracking-name')).map((node) => node.textContent);
    expect(names).toEqual(['Master Tracking', 'Master Tracking', 'Last Mile Tracking', 'Last Mile Tracking']);
  });
});

describe('RC-20 staff legs: the final delivery leg offers the vendor', () => {
  it('lists the vendor in the provider picker for a final delivery leg', async () => {
    const user = userEvent.setup();
    renderLegs();
    await legItems();
    await user.click(screen.getByRole('button', { name: 'Add leg' }));
    await user.selectOptions(await screen.findByLabelText(/^Leg type/), 'final_delivery');
    const provider = screen.getByLabelText(/^Provider \/ carrier/);
    const offered = within(provider)
      .getAllByRole('option')
      .map((option) => option.value);
    expect(offered).toContain(VENDOR);
    await user.selectOptions(provider, VENDOR);
    expect(provider).toHaveValue(VENDOR);
  });

  it('offers the same vendor on the other leg types', async () => {
    const user = userEvent.setup();
    renderLegs();
    await legItems();
    await user.click(screen.getByRole('button', { name: 'Add leg' }));
    for (const legType of LEG_TYPES) {
      await user.selectOptions(await screen.findByLabelText(/^Leg type/), legType);
      const provider = screen.getByLabelText(/^Provider \/ carrier/);
      expect(within(provider).getAllByRole('option').map((option) => option.value)).toContain(VENDOR);
    }
  });
});
