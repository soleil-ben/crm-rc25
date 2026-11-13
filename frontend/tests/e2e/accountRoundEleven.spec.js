/**
 * UAT round 11 in a real browser (the owner's decisions of 2026-10-18 on the RC-UAT-13 and
 * RC-UAT-14 questions).
 *
 * Registration: the billing box starts ticked, so an empty form shows no billing errors
 * (DEC-0158); the country starts on Canada (DEC-0157); the postal code is optional, and
 * an address without one registers (DEC-0159).
 *
 * My shipments: each row shows its booking reference (DEC-0160); a package reference finds
 * its shipment, never another customer's (DEC-0161); accents are still ignored (DEC-0157).
 *
 * The phone-width layout of the same screens is in `accountMobile.spec.js`.
 */

import { expect, test } from './diagnostics.js';
import { bookShipment } from './accountBooking.js';
import {
  CUSTOMER_PASSWORD,
  activatedCustomer,
  closeStaffContext,
  freshAddress,
  signIn,
  staffContext,
} from './accountHelpers.js';

const SAME = 'Billing address is the same as the address above';

/** A seeded customer no spec ever approves (`accountSeeded.js`), so nobody can read it. */
const STRANGER_EMAIL = 'minh.khoi.demo@demo.example.com';

function group(page, name) {
  return page.getByRole('group', { name, exact: true });
}

async function customerIdByEmail(staffPage, email) {
  const response = await staffPage.request.get('/api/v1/customers', {
    params: { search: email, limit: 5 },
  });
  expect(response.ok(), `customer lookup failed: ${response.status()}`).toBe(true);
  const body = await response.json();
  const match = body.items.find((item) => (item.email_entered || '').toLowerCase() === email);
  expect(match, `no customer with ${email} in this run's database`).toBeTruthy();
  return match.id;
}

/** Distinct references on screen (each row is in the DOM twice: table and cards). */
async function listed(page) {
  const hrefs = await page
    .locator('a[href^="/account/shipments/SX-"]')
    .evaluateAll((nodes) => nodes.map((node) => node.getAttribute('href')));
  return [...new Set(hrefs)].map((href) => decodeURIComponent(href.split('/').pop())).sort();
}

async function search(page, keyword) {
  await page.getByLabel(/Search shipments/).fill(keyword);
  await page.getByRole('button', { name: 'Apply filters' }).click();
  await expect.poll(() => new URL(page.url()).searchParams.get('q')).toBe(keyword.trim());
}

test.describe('Registration (UAT round 11)', () => {
  test('the billing box starts ticked, and an empty form has no billing errors', async ({
    page,
  }) => {
    await page.goto('/account/register');
    await expect(page.getByLabel(SAME)).toBeChecked();
    await expect(group(page, 'Billing address').getByLabel(/^Address line 1/)).toHaveCount(0);
    await expect(group(page, 'Address').getByLabel('Country', { exact: true })).toHaveValue('CA');
    await expect(group(page, 'Address').getByLabel('Postal code', { exact: true })).toBeVisible();

    await page.getByRole('button', { name: 'Create account' }).click();
    const summary = page.getByRole('alert').first();
    await expect(summary.getByRole('link', { name: 'Enter the city.' })).toBeVisible();
    await expect(summary).not.toContainText(/billing/i);
    await expect(summary).not.toContainText(/postal code/i);

    // Unticked, the billing parts are required; still no postal code error.
    await page.getByLabel(SAME).uncheck();
    await expect(group(page, 'Billing address').getByLabel('Country', { exact: true })).toHaveValue('CA');
    await page.getByRole('button', { name: 'Create account' }).click();
    await expect(summary.getByRole('link', { name: 'Enter the billing city.' })).toBeVisible();
    await expect(summary).not.toContainText(/postal code/i);
  });

  test('a Vietnamese address without a postal code registers', async ({ page }) => {
    const email = freshAddress('r11-nopostal');
    await page.goto('/account/register');
    await page.getByLabel('Email address', { exact: true }).fill(email);
    await page.getByLabel('Password', { exact: true }).fill(CUSTOMER_PASSWORD);
    await page.getByLabel('Confirm password', { exact: true }).fill(CUSTOMER_PASSWORD);
    await page.getByLabel('Full legal name', { exact: true }).fill(`E2E ${email.split('@')[0]}`);
    await page.getByLabel(/I accept the Solaris Express terms/).check();
    const address = group(page, 'Address');
    await address.getByLabel('Country', { exact: true }).selectOption('VN');
    await address.getByLabel('Address line 1', { exact: true }).fill('125 Nguyễn Huệ');
    await address.getByLabel('City', { exact: true }).fill('Thành phố Hồ Chí Minh');
    await address.getByLabel('Province or state', { exact: true }).fill('Hồ Chí Minh');

    const sent = page.waitForRequest(
      (request) => request.url().endsWith('/api/v1/account/register') && request.method() === 'POST',
    );
    const answered = page.waitForResponse(
      (response) => response.url().endsWith('/api/v1/account/register'),
    );
    await page.getByRole('button', { name: 'Create account' }).click();
    const body = (await sent).postDataJSON();
    expect(body.billing_same_as_shipping).toBe(true);
    expect(body.customer['pickup_address.1.country_code']).toBe('VN');
    expect(body.customer['pickup_address.1.postal_code']).toBeUndefined();
    expect((await answered).status()).toBe(200);
    await expect(page.getByRole('heading', { name: 'Check your email', level: 1 })).toBeVisible();
  });
});

test.describe('My shipments (UAT round 11)', () => {
  test('booking reference on each row; package references and accents find own shipments only', async ({
    page,
    browser,
  }) => {
    test.setTimeout(120_000);
    const { email } = await activatedCustomer(page, browser, { label: 'r11-list' });
    const tag = Date.now().toString(36).slice(-5).toUpperCase();
    const { context, page: staffPage } = await staffContext(browser);
    let withRef;
    let withoutRef;
    let theirs;
    try {
      const mine = await customerIdByEmail(staffPage, email);
      withRef = await bookShipment(staffPage, mine, {
        routeGroup: 'CAV',
        bookingReference: `PO-${tag}-Bakery`,
      });
      withoutRef = await bookShipment(staffPage, mine, { routeGroup: 'VCA' });
      const stranger = await customerIdByEmail(staffPage, STRANGER_EMAIL);
      theirs = await bookShipment(staffPage, stranger, {
        routeGroup: 'CAV',
        bookingReference: `PO-${tag}-Theirs`,
      });
    } finally {
      await closeStaffContext({ context, page: staffPage });
    }

    await signIn(page, email);
    await expect(page.getByRole('heading', { name: 'My shipments', level: 1 })).toBeVisible();
    await expect.poll(() => listed(page)).toEqual([withRef, withoutRef].sort());

    // The wide table shows the booking reference under each Solaris Shipment ID.
    const table = page.locator('.ca-table');
    await expect(table).toBeVisible();
    const rowFor = (reference) =>
      table.locator('tbody tr').filter({ has: page.locator(`a[href$="${reference}"]`) });
    await expect(rowFor(withRef)).toContainText(`Booking reference: PO-${tag}-Bakery`);
    await expect(rowFor(withoutRef)).toContainText('Booking reference: Not recorded');
    await expect(page.locator('main')).not.toContainText(`PO-${tag}-Theirs`);

    // A whole package reference finds its shipment, in any case.
    await search(page, `${withRef}-01`.toLowerCase());
    await expect.poll(() => listed(page)).toEqual([withRef]);
    await search(page, `${withoutRef}-01`);
    await expect.poll(() => listed(page)).toEqual([withoutRef]);

    // Another customer's package reference: the same page as a keyword matching nothing.
    await search(page, `${theirs}-01`);
    await expect(page.getByText('No shipments match those filters')).toBeVisible();
    const strangerText = (await page.locator('main').innerText()).replaceAll(`${theirs}-01`, '');
    await search(page, 'ZZ-NOTHING-ANYWHERE-01');
    await expect(page.getByText('No shipments match those filters')).toBeVisible();
    expect(
      (await page.locator('main').innerText()).replaceAll('ZZ-NOTHING-ANYWHERE-01', ''),
    ).toBe(strangerText);

    // Accents are still ignored, on the keyword as on the column: "Hồ Chí Minh" finds
    // both ("Ho Chi Minh City" is at one end of each route), "tòrônto" only the VCA one.
    await search(page, 'Hồ Chí Minh');
    await expect.poll(() => listed(page)).toEqual([withRef, withoutRef].sort());
    await search(page, 'tòrônto');
    await expect.poll(() => listed(page)).toEqual([withoutRef]);
  });
});
