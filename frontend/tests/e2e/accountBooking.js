/**
 * Booking real shipments for a Customer Account journey to read.
 *
 * ## Why the seeded shipments are no use here
 *
 * `app.seed` flags **every** record it creates `is_demo_record`, and
 * `customer_account_disclosure_service.qualifying_conditions` excludes demo records
 * outright, in every environment. That is correct — an authenticated customer must never
 * be shown a fabricated shipment — and it means the seeded database contains **zero**
 * shipments any account may read. A journey that linked to a seeded customer and expected
 * rows was asserting against an empty list, which the first run of this suite duly found.
 *
 * So the shipments these journeys read are booked here, during the run, and are not demo
 * records.
 *
 * ## Why through the staff API rather than the database
 *
 * Booking has a screen and a guarded route, and a shipment assembled by a test would be a
 * shipment shaped the way the test imagined rather than the way the application builds
 * one. These calls go through `POST /shipments`, `POST /shipments/{id}/packages` and
 * `POST /shipments/{id}/confirm` with the reviewer's own session and CSRF token — the
 * permission checks run, the audit rows are written, and the row that results is the row
 * the Staff Portal would have produced.
 *
 * The staff booking wizard itself is exercised by `staffKeyboard.spec.js`; repeating it
 * through the UI here would make every history journey a booking test.
 */

import { expect } from '@playwright/test';

/** Read the staff CSRF cookie out of a signed-in context. */
async function staffCsrf(staffPage) {
  const cookies = await staffPage.context().cookies();
  const csrf = cookies.find((cookie) => cookie.name === 'solaris_csrf');
  expect(csrf, 'the staff context has no CSRF cookie; is it signed in?').toBeTruthy();
  return csrf.value;
}

/** The staff customer id (the integer) for a public reference such as `STCA-000004`. */
export async function customerIdFor(staffPage, customerPublicId) {
  const response = await staffPage.request.get('/api/v1/customers', {
    params: { search: customerPublicId, limit: 5 },
  });
  expect(response.ok(), `customer lookup failed: ${response.status()}`).toBe(true);
  const body = await response.json();
  const match = body.items.find((item) => item.public_id === customerPublicId);
  expect(match, `no customer ${customerPublicId} in this run's database`).toBeTruthy();
  return match.id;
}

/**
 * Where each route group's shipments start and end.
 *
 * A route group implies a direction and the booking service checks the sender's country
 * against it: booking `VCA` with a Canadian sender is refused with "Direction 'vn_to_ca'
 * requires an origin in VN". That refusal is the service working, and a test helper that
 * sent the same pair of addresses whatever the route was asking for it.
 */
const ENDPOINTS = {
  CAV: {
    sender: {
      name: 'E2E Sender',
      address_line1: '1 Test Way',
      city: 'Mississauga',
      province_state: 'ON',
      postal_code: 'L5B 1M2',
      country_code: 'CA',
    },
    recipient: {
      name: 'E2E Recipient',
      address_line1: '2 Test Street',
      city: 'Ho Chi Minh City',
      country_code: 'VN',
    },
  },
  VCA: {
    sender: {
      name: 'E2E Sender',
      address_line1: '3 Test Lane',
      city: 'Ho Chi Minh City',
      country_code: 'VN',
    },
    recipient: {
      name: 'E2E Recipient',
      address_line1: '4 Test Road',
      city: 'Toronto',
      province_state: 'ON',
      postal_code: 'M5V 2T6',
      country_code: 'CA',
    },
  },
};

/**
 * Book and confirm one shipment for a customer, and return its Solaris Shipment ID.
 *
 * `routeGroup` is a parameter because the filter journeys need rows that differ: a route
 * filter over a single route proves nothing. `bookingReference` is for the keyword search
 * (UAT round 10), which matches part of one. `packageCount` is for a journey that cancels
 * one of several packages (UAT round 12).
 */
export async function bookShipment(
  staffPage,
  customerId,
  {
    routeGroup = 'CAV',
    contents = 'Synthetic E2E contents',
    bookingReference,
    packageCount = 1,
  } = {},
) {
  const headers = { 'X-CSRF-Token': await staffCsrf(staffPage) };
  const endpoints = ENDPOINTS[routeGroup];
  expect(endpoints, `no sender/recipient pair defined for ${routeGroup}`).toBeTruthy();

  const draft = await staffPage.request.post('/api/v1/shipments', {
    headers,
    data: {
      customer_id: customerId,
      route_group: routeGroup,
      contents_description: contents,
      ...(bookingReference ? { booking_reference: bookingReference } : {}),
      sender: endpoints.sender,
      recipient: endpoints.recipient,
      packages: Array.from({ length: packageCount }, () => ({
        weight_value: '2.5',
        contents_summary: contents,
      })),
    },
  });
  expect(draft.status(), `draft creation failed: ${await draft.text()}`).toBe(201);
  const created = await draft.json();

  const confirmed = await staffPage.request.post(
    `/api/v1/shipments/${created.id}/confirm`,
    {
      headers,
      data: { idempotency_key: `e2e-${created.id}-${Date.now()}` },
    },
  );
  expect(confirmed.ok(), `confirmation failed: ${await confirmed.text()}`).toBe(true);
  const booking = await confirmed.json();

  const reference = booking.shipment?.public_id || booking.public_id;
  expect(reference, 'the confirmation returned no Solaris Shipment ID').toBeTruthy();
  return reference;
}

/**
 * Cancel one package of a confirmed shipment, through the staff route a person would use
 * (`POST /packages/{id}/cancel`), and return the package reference. The reference is
 * retained and the shipment's other packages are untouched.
 */
export async function cancelPackage(staffPage, shipmentReference, packageReference) {
  const headers = { 'X-CSRF-Token': await staffCsrf(staffPage) };
  const found = await staffPage.request.get('/api/v1/shipments', {
    params: { search: shipmentReference, limit: 5 },
  });
  expect(found.ok(), `shipment lookup failed: ${found.status()}`).toBe(true);
  const shipment = (await found.json()).items.find((item) => item.public_id === shipmentReference);
  expect(shipment, `no shipment ${shipmentReference} in this run's database`).toBeTruthy();

  const listed = await staffPage.request.get(`/api/v1/shipments/${shipment.id}/packages`);
  expect(listed.ok(), `package lookup failed: ${listed.status()}`).toBe(true);
  const target = (await listed.json()).find((item) => item.package_reference === packageReference);
  expect(target, `no package ${packageReference} on ${shipmentReference}`).toBeTruthy();

  const cancelled = await staffPage.request.post(`/api/v1/packages/${target.id}/cancel`, {
    headers,
    data: { reason: 'E2E: package withdrawn' },
  });
  expect(cancelled.ok(), `package cancellation failed: ${await cancelled.text()}`).toBe(true);
  return packageReference;
}

/**
 * Book several shipments across two route groups, so the route filter has something to
 * narrow and the list has more than one row.
 */
export async function bookHistoryFor(staffPage, customerPublicId, { count = 3 } = {}) {
  const customerId = await customerIdFor(staffPage, customerPublicId);
  const references = [];
  for (let index = 0; index < count; index += 1) {
    // Sequential on purpose: SQLite takes one writer at a time, and concurrent
    // bookings contend for it.
    references.push(
      await bookShipment(staffPage, customerId, {
        routeGroup: index === 0 ? 'VCA' : 'CAV',
        contents: `Synthetic E2E contents ${index + 1}`,
      }),
    );
  }
  return references;
}

/**
 * Set a seeded customer's contact language to English, through the staff API.
 *
 * Since OD-71 the Customer Account follows a signed-in identity's `preferred_language`,
 * and most seeded customers prefer Vietnamese. The journeys that link to one assert the
 * English copy, so they make the customer English first; that is test data in this run's
 * scratch database, and the Vietnamese path is covered by `accountVietnamese.spec.js`
 * and `accountProfile.spec.js`.
 */
export async function contactInEnglish(staffPage, customerPublicId) {
  const customerId = await customerIdFor(staffPage, customerPublicId);
  const response = await staffPage.request.patch(`/api/v1/customers/${customerId}`, {
    headers: { 'X-CSRF-Token': await staffCsrf(staffPage) },
    data: { preferred_language: 'en' },
  });
  expect(response.ok(), `language update failed: ${await response.text()}`).toBe(true);
}
