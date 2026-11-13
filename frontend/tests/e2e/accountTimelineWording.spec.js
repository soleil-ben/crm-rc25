/**
 * Phase 15: the Customer Account timeline shows the standard wording for each published
 * event type in the customer's language, with the staff's published text beneath it.
 *
 * Set-up goes through the staff API with a separate staff session, as `accountQuotes.spec.js`
 * does: a fresh customer is approved and one Canada → Vietnam shipment is booked for them;
 * staff record a published collection-point handover with their own sentence **and** an
 * internal note, plus an unpublished event. Then the customer reads the shipment in English
 * and in Vietnamese. The internal note and the unpublished event never appear. Test data
 * only, in this run's scratch database.
 */

import { expect, test } from './diagnostics.js';
import { auditAndAssert, settle } from './axeHelpers.js';
import { bookShipment } from './accountBooking.js';
import { activatedCustomer, closeStaffContext, signIn, staffContext } from './accountHelpers.js';

const STAFF_TEXT = 'Pick it up at the District 1 office, Monday to Saturday.';
const INTERNAL = 'E2E-INTERNAL-NOTE: recipient owes a storage fee';
const UNPUBLISHED = 'E2E-UNPUBLISHED-NOTE';

async function ok(response, what) {
  expect(response.ok(), `${what} failed: ${response.status()} ${await response.text()}`).toBe(true);
  return response.json();
}

async function shipmentWithEvents(staffPage, email) {
  const cookies = await staffPage.context().cookies();
  const headers = { 'X-CSRF-Token': cookies.find((c) => c.name === 'solaris_csrf').value };
  const customers = await ok(
    await staffPage.request.get('/api/v1/customers', { params: { search: email, limit: 5 } }),
    'customer lookup',
  );
  const customer = customers.items.find((item) => item.email_entered === email) || customers.items[0];
  const reference = await bookShipment(staffPage, customer.id, { routeGroup: 'CAV' });
  const shipments = await ok(
    await staffPage.request.get('/api/v1/shipments', { params: { search: reference, limit: 5 } }),
    'shipment lookup',
  );
  const shipment = shipments.items.find((item) => item.public_id === reference);
  const record = (data, what) =>
    staffPage.request
      .post(`/api/v1/shipments/${shipment.id}/events`, { headers, data })
      .then((response) => ok(response, what));
  await record(
    {
      event_type: 'in_transit',
      is_public_update: true,
      public_update_template_key: 'in_transit.v1',
    },
    'the in-transit event',
  );
  await record(
    { event_type: 'customs_processing', is_public_update: false, internal_detail: UNPUBLISHED },
    'the unpublished event',
  );
  await record(
    {
      event_type: 'delivered_to_collection_point',
      is_public_update: true,
      public_update_text: STAFF_TEXT,
      internal_detail: INTERNAL,
    },
    'the collection-point event',
  );
  return reference;
}

test.describe('Customer timeline wording', () => {
  test('standard wording in the customer language, the staff text beneath, no internal note', async ({
    page,
    browser,
  }, testInfo) => {
    test.setTimeout(180_000);
    const { email } = await activatedCustomer(page, browser, { label: 'timeline' });

    const staff = await staffContext(browser);
    let reference;
    try {
      reference = await shipmentWithEvents(staff.page, email);
    } finally {
      await closeStaffContext(staff);
    }

    await signIn(page, email);
    await page.goto(`/account/shipments/${reference}`);
    await expect(page.getByRole('heading', { name: reference, level: 1 })).toBeVisible();

    const timeline = page.locator('.ca-timeline');
    await expect(
      timeline.getByText('Your shipment is ready to collect at the pickup point.'),
    ).toBeVisible();
    await expect(timeline.getByText(STAFF_TEXT)).toBeVisible();
    // The standard update the staff chose says what the standard sentence says: once only.
    await expect(timeline.getByText('Your shipment is on its way.')).toHaveCount(1);

    const text = await page.locator('main').innerText();
    expect(text).not.toContain(INTERNAL);
    expect(text).not.toContain(UNPUBLISHED);
    expect(text).not.toContain('E2E-');

    await settle(page);
    await auditAndAssert(page, 'account-timeline-wording', testInfo);

    // The same timeline in Vietnamese: the standard sentence follows the language; what the
    // staff typed is shown as they wrote it.
    await page.getByRole('button', { name: 'Tiếng Việt' }).click();
    await expect(page.locator('html')).toHaveAttribute('lang', 'vi');
    await expect(
      timeline.getByText('Lô hàng của bạn đã sẵn sàng để nhận tại điểm giao nhận.'),
    ).toBeVisible();
    await expect(timeline.getByText('Lô hàng của bạn đang trên đường vận chuyển.')).toHaveCount(1);
    await expect(timeline.getByText(STAFF_TEXT)).toBeVisible();
    expect(await page.locator('main').innerText()).not.toContain(INTERNAL);
  });
});
