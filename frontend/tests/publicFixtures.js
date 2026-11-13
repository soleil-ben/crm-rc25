/**
 * Fixtures for the public tracking tests.
 *
 * These mirror the shape `PublicTrackingResult` actually returns. They are kept in one
 * place so a change to the public allowlist shows up as one edit here rather than as a
 * dozen quietly diverging inline objects.
 *
 * Note what is *not* in them: no customer, no addresses, no phone, no money, no carrier
 * number, no internal detail. A fixture that carried those would let a component start
 * rendering them without any test noticing.
 */

export const trackingResultFixture = {
  shipment_reference: 'SX-CAV-7K9D2M4R8T6W',
  matched_reference_type: 'shipment',
  selected_package_reference: null,
  route_group: 'CAV',
  route_label: 'Canada to Vietnam',
  origin: { city: 'Mississauga', country_code: 'CA', country_label: 'Canada' },
  destination: {
    city: 'Thành phố Hồ Chí Minh',
    country_code: 'VN',
    country_label: 'Vietnam',
  },
  status: 'partially_delivered',
  status_label: 'Partially delivered',
  package_count_active: 3,
  package_count_cancelled: 0,
  package_count_delivered: 1,
  progress_summary: '1 of 3 packages delivered',
  packages: [
    {
      package_reference: 'SX-CAV-7K9D2M4R8T6W-01',
      status: 'delivered',
      status_label: 'Delivered',
      is_selected: false,
      is_cancelled: false,
      delivered_at: '2026-09-03T14:20:00',
    },
    {
      package_reference: 'SX-CAV-7K9D2M4R8T6W-02',
      status: 'arrived_destination',
      status_label: 'Arrived destination',
      is_selected: false,
      is_cancelled: false,
      delivered_at: null,
    },
    {
      package_reference: 'SX-CAV-7K9D2M4R8T6W-03',
      status: 'arrived_destination',
      status_label: 'Arrived destination',
      is_selected: false,
      is_cancelled: false,
      delivered_at: null,
    },
  ],
  estimated_delivery_at: null,
  delivered_at: null,
  cancelled_at: null,
  timeline: [
    {
      status: 'delivered',
      status_label: 'Delivered',
      message: 'One of your three parcels has been delivered.',
      occurred_at: '2026-09-03T14:20:00',
      location: { city: 'Quận 1', country_code: 'VN', country_label: 'Vietnam' },
      package_references: ['SX-CAV-7K9D2M4R8T6W-01'],
      source_label: 'manual_update',
    },
    {
      status: 'departed_origin',
      status_label: 'Departed origin',
      message: 'Your parcels have left Canada.',
      occurred_at: '2026-08-25T09:00:00',
      location: { city: 'Toronto Pearson', country_code: 'CA', country_label: 'Canada' },
      package_references: [
        'SX-CAV-7K9D2M4R8T6W-01',
        'SX-CAV-7K9D2M4R8T6W-02',
        'SX-CAV-7K9D2M4R8T6W-03',
      ],
      source_label: 'manual_update',
    },
  ],
  tracking_state: 'manual_updates',
  last_public_update_at: '2026-09-03T14:20:00',
  carrier_link: null,
  data_mode: 'live',
  help_url: null,
  timezone: 'America/Toronto',
};

/** The same shipment opened from a package QR code: one package is selected. */
export const packageScanFixture = {
  ...trackingResultFixture,
  matched_reference_type: 'package',
  selected_package_reference: 'SX-CAV-7K9D2M4R8T6W-02',
  packages: trackingResultFixture.packages.map((item) => ({
    ...item,
    is_selected: item.package_reference === 'SX-CAV-7K9D2M4R8T6W-02',
  })),
};

/** A different customer's shipment, used to prove one result never bleeds into another. */
export const otherShipmentFixture = {
  ...trackingResultFixture,
  shipment_reference: 'SX-VCA-4M8P2Q6S9T3W',
  route_group: 'VCA',
  route_label: 'Vietnam to Canada',
  status: 'delivered',
  status_label: 'Delivered',
  package_count_active: 1,
  package_count_delivered: 1,
  progress_summary: '1 of 1 packages delivered',
  packages: [
    {
      package_reference: 'SX-VCA-4M8P2Q6S9T3W-01',
      status: 'delivered',
      status_label: 'Delivered',
      is_selected: false,
      is_cancelled: false,
      delivered_at: '2026-09-01T10:00:00',
    },
  ],
  timeline: [
    {
      status: 'delivered',
      status_label: 'Delivered',
      message: 'Delivered to the recipient in Toronto.',
      occurred_at: '2026-09-01T10:00:00',
      location: { city: 'Toronto', country_code: 'CA', country_label: 'Canada' },
      package_references: ['SX-VCA-4M8P2Q6S9T3W-01'],
      source_label: 'manual_update',
    },
  ],
};

export const exceptionFixture = {
  ...trackingResultFixture,
  shipment_reference: 'SX-XUS-9V4X7P2Q6S8T',
  route_group: 'XUS',
  status: 'exception',
  status_label: 'Exception',
  package_count_active: 1,
  package_count_delivered: 0,
  progress_summary: '0 of 1 packages delivered',
  packages: [
    {
      package_reference: 'SX-XUS-9V4X7P2Q6S8T-01',
      status: 'exception',
      status_label: 'Exception',
      is_selected: false,
      is_cancelled: false,
      delivered_at: null,
    },
  ],
  timeline: [
    {
      status: 'exception',
      status_label: 'Exception',
      message: 'Your shipment is held pending paperwork.',
      occurred_at: '2026-09-05T11:00:00',
      location: { city: 'Buffalo', country_code: 'US', country_label: 'United States' },
      package_references: [],
      source_label: 'manual_update',
    },
  ],
  help_url: 'https://solarisexpress.ca/contact',
};

export const unavailableFixture = {
  ...trackingResultFixture,
  shipment_reference: 'SX-CAD-5R8T2W6K9M3N',
  route_group: 'CAD',
  status: 'tracking_unavailable',
  status_label: 'Tracking unavailable',
  package_count_active: 1,
  package_count_delivered: 0,
  progress_summary: '0 of 1 packages delivered',
  packages: [],
  timeline: [],
  tracking_state: 'tracking_unavailable',
  last_public_update_at: null,
  help_url: 'https://solarisexpress.ca/contact',
};

export const demoFixture = {
  ...trackingResultFixture,
  data_mode: 'demo',
  tracking_state: 'demo',
};

export const externalLinkFixture = {
  ...trackingResultFixture,
  timeline: [],
  tracking_state: 'external_link_only',
  last_public_update_at: null,
  carrier_link: {
    // The leg's generic name (owner, 2026-10-22), never the carrier's.
    carrier_name: 'Last Mile Tracking',
    tracking_name_key: 'last_mile_tracking',
    url: 'https://www.canadapost-postescanada.ca/track-reperage/en?id=DEMO1',
  },
};

export const notFoundBody = {
  code: 'tracking_not_found',
  message:
    'We could not find tracking information for that reference. Check the Solaris ' +
    'Shipment ID or package reference on your label or receipt and try again.',
};
