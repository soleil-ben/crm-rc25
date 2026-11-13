/**
 * RC-UAT-19 (owner, Louis Tong, 2026-10-22): customer-facing tracking names are generic.
 *
 * A last-mile carrier link whose staff-typed label names the vendor stays visible on the
 * Customer Account shipment page, under "Last Mile Tracking" ("Theo dõi chặng cuối" in
 * Vietnamese, proposed), and no vendor name reaches the page. Set-up through the staff API
 * with the reviewer's own session; test data only, in this run's scratch database.
 */

import { expect, test } from './diagnostics.js';
import { bookShipment } from './accountBooking.js';
import { activatedCustomer, closeStaffContext, signIn, staffContext } from './accountHelpers.js';

const UPS_URL = 'https://www.ups.com/track?loc=en_CA&tracknum=1Z999AA10123456784';

async function ok(response, what) {
  expect(response.ok(), `${what} failed: ${response.status()} ${await response.text()}`).toBe(true);
  return response.json();
}

async function shipmentWithVendorLabelledLink(staffPage, email) {
  const cookies = await staffPage.context().cookies();
  const headers = { 'X-CSRF-Token': cookies.find((c) => c.name === 'solaris_csrf').value };
  const customers = await ok(
    await staffPage.request.get('/api/v1/customers', { params: { search: email, limit: 5 } }),
    'customer lookup',
  );
  const customer = customers.items.find((item) => item.email_entered === email) || customers.items[0];
  const reference = await bookShipment(staffPage, customer.id, {
    routeGroup: 'VCA',
    contents: 'Synthetic E2E tracking-name contents',
  });
  const shipments = await ok(
    await staffPage.request.get('/api/v1/shipments', { params: { search: reference, limit: 5 } }),
    'shipment lookup',
  );
  const shipment = shipments.items.find((item) => item.public_id === reference);
  const leg = await ok(
    await staffPage.request.post(`/api/v1/shipments/${shipment.id}/legs`, {
      headers,
      data: {
        leg_type: 'final_delivery',
        provider_name: 'Kango Logistics',
        is_final_recipient_delivery: true,
      },
    }),
    'leg creation',
  );
  await ok(
    await staffPage.request.post(`/api/v1/legs/${leg.id}/tracking-references`, {
      headers,
      data: {
        carrier_name: 'Kango Express last mile',
        tracking_number: '1Z999AA10123456784',
        public_url: UPS_URL,
        source_mode: 'external_link',
      },
    }),
    'tracking link',
  );
  return reference;
}

test.describe('Customer-facing tracking names', () => {
  test('a vendor-labelled last-mile link shows as Last Mile Tracking, in English and Vietnamese', async ({
    page,
    browser,
  }) => {
    test.setTimeout(150_000);
    const { email } = await activatedCustomer(page, browser, { label: 'trackingnames' });
    const staff = await staffContext(browser);
    let reference;
    try {
      reference = await shipmentWithVendorLabelledLink(staff.page, email);
    } finally {
      await closeStaffContext(staff);
    }

    await signIn(page, email);
    await page.goto(`/account/shipments/${reference}`);
    await expect(page.getByRole('heading', { name: reference, level: 1 })).toBeVisible();
    const link = page.getByRole('link', { name: /^Last Mile Tracking: open the carrier’s tracking page/ });
    await expect(link).toBeVisible();
    await expect(link).toHaveAttribute('href', UPS_URL);
    expect((await page.locator('main').innerText()).toLowerCase()).not.toContain('kango');

    await page.getByRole('button', { name: 'Tiếng Việt' }).click();
    const vietnamese = page.getByRole('link', { name: /^Theo dõi chặng cuối: mở trang theo dõi/ });
    await expect(vietnamese).toBeVisible();
    await expect(vietnamese).toHaveAttribute('href', UPS_URL);
    expect((await page.locator('main').innerText()).toLowerCase()).not.toContain('kango');
  });
});
