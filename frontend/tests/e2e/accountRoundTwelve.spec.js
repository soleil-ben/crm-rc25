/**
 * UAT round 12 in a real browser (the owner's decisions of 2026-10-19 on the RC-UAT-15
 * questions).
 *
 * My shipments: the shipment's own page shows the booking reference, or "Not recorded"
 * (DEC-0163); a cancelled package's reference still finds its shipment, never another
 * customer's (DEC-0164).
 *
 * Registration: a typed Canadian or United States postal code must have a lenient shape,
 * refused beside the field and in the summary before anything is sent; blank is fine and
 * Vietnam is not checked (DEC-0165). A registration that omits `billing_same_as_shipping`
 * is treated as ticked by the server (DEC-0166).
 *
 * The phone-width layout of the same screens is in `accountMobile.spec.js`.
 */

import { expect, test } from './diagnostics.js';
import { bookShipment, cancelPackage } from './accountBooking.js';
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

/** The value beside "Booking reference" on the shipment's own page. */
function bookingReferenceValue(page) {
  return page
    .locator('.ca-detail-row')
    .filter({ has: page.getByText('Booking reference', { exact: true }) })
    .locator('dd');
}

async function startRegistration(page, email) {
  await page.goto('/account/register');
  await page.getByLabel('Email address', { exact: true }).fill(email);
  await page.getByLabel('Password', { exact: true }).fill(CUSTOMER_PASSWORD);
  await page.getByLabel('Confirm password', { exact: true }).fill(CUSTOMER_PASSWORD);
  await page.getByLabel('Full legal name', { exact: true }).fill(`E2E ${email.split('@')[0]}`);
  await page.getByLabel(/I accept the Solaris Express terms/).check();
}

async function fillAddress(scope, { country, postal }) {
  if (country) await scope.getByLabel('Country', { exact: true }).selectOption(country);
  await scope.getByLabel('Address line 1', { exact: true }).fill('1 Pike Street');
  await scope.getByLabel('City', { exact: true }).fill('Seattle');
  await scope.getByLabel('Province or state', { exact: true }).fill('WA');
  if (postal !== undefined) await scope.getByLabel(/^(Postal|ZIP) code$/).fill(postal);
}

test.describe('My shipments (UAT round 12)', () => {
  test('the shipment page shows the booking reference; a cancelled package finds its own shipment only', async ({
    page,
    browser,
  }) => {
    test.setTimeout(150_000);
    const { email } = await activatedCustomer(page, browser, { label: 'r12-detail' });
    const tag = Date.now().toString(36).slice(-5).toUpperCase();
    const { context, page: staffPage } = await staffContext(browser);
    let withRef;
    let withoutRef;
    let theirs;
    try {
      const mine = await customerIdByEmail(staffPage, email);
      withRef = await bookShipment(staffPage, mine, {
        routeGroup: 'CAV',
        bookingReference: `PO-${tag}-Detail`,
        packageCount: 2,
      });
      await cancelPackage(staffPage, withRef, `${withRef}-02`);
      withoutRef = await bookShipment(staffPage, mine, { routeGroup: 'VCA' });
      const stranger = await customerIdByEmail(staffPage, STRANGER_EMAIL);
      theirs = await bookShipment(staffPage, stranger, {
        routeGroup: 'CAV',
        bookingReference: `PO-${tag}-Theirs`,
        packageCount: 2,
      });
      await cancelPackage(staffPage, theirs, `${theirs}-02`);
    } finally {
      await closeStaffContext({ context, page: staffPage });
    }

    await signIn(page, email);
    await expect(page.getByRole('heading', { name: 'My shipments', level: 1 })).toBeVisible();
    await expect.poll(() => listed(page)).toEqual([withRef, withoutRef].sort());

    // A cancelled package's reference still finds its shipment (DEC-0164), in any case.
    await search(page, `${withRef}-02`.toLowerCase());
    await expect.poll(() => listed(page)).toEqual([withRef]);

    // Another customer's cancelled package: the same page as a keyword matching nothing.
    await search(page, `${theirs}-02`);
    await expect(page.getByText('No shipments match those filters')).toBeVisible();
    const strangerText = (await page.locator('main').innerText()).replaceAll(`${theirs}-02`, '');
    await search(page, 'ZZ-NOTHING-ANYWHERE-02');
    await expect(page.getByText('No shipments match those filters')).toBeVisible();
    expect(
      (await page.locator('main').innerText()).replaceAll('ZZ-NOTHING-ANYWHERE-02', ''),
    ).toBe(strangerText);

    // The shipment's own page shows its booking reference (DEC-0163) ...
    await page.goto(`/account/shipments/${encodeURIComponent(withRef)}`);
    await expect(page.getByRole('heading', { name: withRef, level: 1 })).toBeVisible();
    await expect(bookingReferenceValue(page)).toHaveText(`PO-${tag}-Detail`);
    // ... and the cancelled package is still listed, as cancelled.
    const cancelledPackage = page.locator('.ca-package').filter({ hasText: `${withRef}-02` });
    // The flag, not the status pill, which also reads "Cancelled".
    await expect(cancelledPackage.locator('.ca-flag')).toHaveText('Cancelled');

    // A shipment without one says so.
    await page.goto(`/account/shipments/${encodeURIComponent(withoutRef)}`);
    await expect(page.getByRole('heading', { name: withoutRef, level: 1 })).toBeVisible();
    await expect(bookingReferenceValue(page)).toHaveText('Not recorded');

    // Another customer's shipment is the ordinary not-found page, with no reference on it.
    await page.goto(`/account/shipments/${encodeURIComponent(theirs)}`);
    await expect(
      page.getByRole('heading', { name: 'We could not find that shipment', level: 1 }),
    ).toBeVisible();
    await expect(page.locator('main')).not.toContainText(`PO-${tag}-Theirs`);
  });
});

test.describe('Registration (UAT round 12)', () => {
  test('a misshapen Canadian or US postal code is refused inline before anything is sent', async ({
    page,
  }) => {
    const email = freshAddress('r12-postal');
    const registerRequests = [];
    page.on('request', (request) => {
      if (request.url().endsWith('/api/v1/account/register')) registerRequests.push(request);
    });
    await startRegistration(page, email);
    const address = group(page, 'Address');
    await fillAddress(address, { postal: '12345' });
    await page.getByRole('button', { name: 'Create account' }).click();

    const canadian = 'Enter the postal code as A1A 1A1, or leave it blank.';
    const summary = page.getByRole('alert').first();
    await expect(summary.getByRole('link', { name: canadian })).toBeVisible();
    const postal = address.getByLabel('Postal code', { exact: true });
    await expect(postal).toHaveAttribute('aria-invalid', 'true');
    await expect(postal).toHaveAccessibleDescription(new RegExp(canadian.replace(/\./g, '\\.')));

    // The summary link takes the person to the field.
    await summary.getByRole('link', { name: canadian }).click();
    await expect(postal).toBeFocused();

    // The United States wants a ZIP code, and says so.
    await address.getByLabel('Country', { exact: true }).selectOption('US');
    await address.getByLabel('ZIP code', { exact: true }).fill('9810');
    await page.getByRole('button', { name: 'Create account' }).click();
    await expect(
      summary.getByRole('link', {
        name: 'Enter the ZIP code as 12345 or 12345-6789, or leave it blank.',
      }),
    ).toBeVisible();

    // An unticked billing address is checked against its own country, and says billing.
    await address.getByLabel('ZIP code', { exact: true }).fill('98101-1234');
    await page.getByLabel(SAME).uncheck();
    const billing = group(page, 'Billing address');
    await fillAddress(billing, { postal: '98101' });
    await page.getByRole('button', { name: 'Create account' }).click();
    await expect(
      summary.getByRole('link', {
        name: 'Enter the billing postal code as A1A 1A1, or leave it blank.',
      }),
    ).toBeVisible();
    await expect(summary).not.toContainText('Enter the ZIP code');
    expect(registerRequests).toHaveLength(0);

    // Corrected, in lower case without the space: sent as typed, and registered.
    await billing.getByLabel('Postal code', { exact: true }).fill('k1a0b1');
    const sent = page.waitForRequest(
      (request) => request.url().endsWith('/api/v1/account/register') && request.method() === 'POST',
    );
    await page.getByRole('button', { name: 'Create account' }).click();
    const body = (await sent).postDataJSON();
    expect(body.customer['pickup_address.1.postal_code']).toBe('98101-1234');
    expect(body.customer['billing_address.postal_code']).toBe('k1a0b1');
    expect(body.billing_same_as_shipping).toBe(false);
    await expect(page.getByRole('heading', { name: 'Check your email', level: 1 })).toBeVisible();
  });

  test('a Vietnamese code is not checked, and a blank one is fine', async ({ page }) => {
    const email = freshAddress('r12-vn');
    await startRegistration(page, email);
    await fillAddress(group(page, 'Address'), { country: 'VN', postal: '12345 ABC' });
    const sent = page.waitForRequest(
      (request) => request.url().endsWith('/api/v1/account/register') && request.method() === 'POST',
    );
    await page.getByRole('button', { name: 'Create account' }).click();
    expect((await sent).postDataJSON().customer['pickup_address.1.postal_code']).toBe('12345 ABC');
    await expect(page.getByRole('heading', { name: 'Check your email', level: 1 })).toBeVisible();
  });

  test('a registration that omits the billing flag is treated as ticked by the server', async ({
    page,
  }) => {
    const email = freshAddress('r12-noflag');
    await startRegistration(page, email);
    await fillAddress(group(page, 'Address'), { country: 'US' });

    // Strip the flag from what the form sends, as another client might (DEC-0166).
    await page.route('**/api/v1/account/register', async (route) => {
      const body = route.request().postDataJSON();
      delete body.billing_same_as_shipping;
      await route.continue({ postData: JSON.stringify(body) });
    });
    const answered = page.waitForResponse((response) =>
      response.url().endsWith('/api/v1/account/register'),
    );
    await page.getByRole('button', { name: 'Create account' }).click();
    expect((await answered).status()).toBe(200);
    await expect(page.getByRole('heading', { name: 'Check your email', level: 1 })).toBeVisible();
  });
});
