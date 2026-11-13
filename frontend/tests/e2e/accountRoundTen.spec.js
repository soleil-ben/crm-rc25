/**
 * UAT round 10 in a real browser (the owner's real-phone feedback of 2026-10-18).
 *
 * The shipment list's "Solaris Shipment ID" filter, which needed the whole ID, is a
 * "Search shipments" keyword box (DEC-0156): part of the Solaris Shipment ID, the booking
 * reference, or the origin or destination city, in any case, together with the status,
 * route and date filters, and never another customer's shipment.
 *
 * The phone-width layout of the same box is in `accountMobile.spec.js`.
 */

import { expect, test } from './diagnostics.js';
import { bookShipment } from './accountBooking.js';
import { activatedCustomer, closeStaffContext, signIn, staffContext } from './accountHelpers.js';

/** A seeded customer no spec ever approves (`accountSeeded.js`), so nobody can read it. */
const STRANGER_EMAIL = 'minh.khoi.demo@demo.example.com';

/** The staff row id of the customer holding this email address. */
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

/**
 * An approved account with three shipments of its own, and one shipment on somebody
 * else's account whose booking reference shares this run's tag.
 */
async function accountWithHistory(page, browser) {
  const { email } = await activatedCustomer(page, browser, { label: 'r10-search' });
  const tag = Date.now().toString(36).slice(-5).toUpperCase();
  const { context, page: staffPage } = await staffContext(browser);
  try {
    const mine = await customerIdByEmail(staffPage, email);
    const bakery = await bookShipment(staffPage, mine, {
      routeGroup: 'CAV',
      bookingReference: `PO-${tag}-Bakery`,
    });
    const florist = await bookShipment(staffPage, mine, {
      routeGroup: 'VCA',
      bookingReference: `PO-${tag}-Florist`,
    });
    const plain = await bookShipment(staffPage, mine, { routeGroup: 'CAV' });
    const stranger = await customerIdByEmail(staffPage, STRANGER_EMAIL);
    const theirs = await bookShipment(staffPage, stranger, {
      routeGroup: 'CAV',
      bookingReference: `PO-${tag}-Theirs`,
    });
    return { email, tag, bakery, florist, plain, theirs };
  } finally {
    await closeStaffContext({ context, page: staffPage });
  }
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

test.describe('My shipments: keyword search (UAT round 10)', () => {
  test('partial, any case, four fields, combined with filters, own rows only', async ({
    page,
    browser,
  }) => {
    test.setTimeout(120_000);
    const history = await accountWithHistory(page, browser);
    const { tag, bakery, florist, plain, theirs } = history;

    await signIn(page, history.email);
    await expect(page.getByRole('heading', { name: 'My shipments', level: 1 })).toBeVisible();
    await expect.poll(() => listed(page)).toEqual([bakery, florist, plain].sort());

    // The box, its hint, and no exact-ID box.
    const box = page.getByLabel(/Search shipments/);
    await expect(box).toHaveAccessibleDescription(
      /Solaris Shipment ID, a package ID, your booking reference, and the city it was sent from or to/,
    );
    await expect(page.getByLabel(/^Solaris Shipment ID/)).toHaveCount(0);

    // Part of a Solaris Shipment ID, in lower case.
    await search(page, bakery.slice(-7).toLowerCase());
    await expect.poll(() => listed(page)).toEqual([bakery]);

    // Part of a booking reference. Since UAT round 11 the row shows it (DEC-0160), and
    // only this row's: the florist's and the stranger's are not on the page.
    await search(page, 'bakery');
    await expect.poll(() => listed(page)).toEqual([bakery]);
    await expect(page.locator('main')).toContainText(`PO-${tag}-Bakery`);
    await expect(page.locator('main')).not.toContainText(`PO-${tag}-Florist`);
    await expect(page.locator('main')).not.toContainText(`PO-${tag}-Theirs`);

    // The run's tag is in both of this account's booking references and in the
    // stranger's. Only the two of this account's come back.
    await search(page, `po-${tag.toLowerCase()}`);
    await expect.poll(() => listed(page)).toEqual([bakery, florist].sort());

    // The stranger's own booking reference and Solaris Shipment ID find nothing, and the
    // page says so exactly as it does for a keyword that matches nothing anywhere.
    await search(page, `${tag}-Theirs`);
    await expect(page.getByText('No shipments match those filters')).toBeVisible();
    const strangerText = await page.locator('main').innerText();
    await search(page, theirs);
    await expect(page.getByText('No shipments match those filters')).toBeVisible();
    await search(page, 'ZZ-NOTHING-ANYWHERE');
    await expect(page.getByText('No shipments match those filters')).toBeVisible();
    expect(
      (await page.locator('main').innerText()).replace(/ZZ-NOTHING-ANYWHERE/g, ''),
    ).toBe(strangerText.replace(new RegExp(`${tag}-Theirs`, 'g'), ''));

    // Cities: VCA runs Ho Chi Minh City to Toronto, CAV Mississauga to Ho Chi Minh City.
    await search(page, 'TORON');
    await expect.poll(() => listed(page)).toEqual([florist]);
    await search(page, 'chi minh');
    await expect.poll(() => listed(page)).toEqual([bakery, florist, plain].sort());

    // With the route filter: the keyword matches all three, the route narrows to CAV.
    await page.getByLabel('Route').selectOption('CAV');
    await page.getByRole('button', { name: 'Apply filters' }).click();
    await expect.poll(() => new URL(page.url()).searchParams.get('route_group')).toBe('CAV');
    expect(new URL(page.url()).searchParams.get('q')).toBe('chi minh');
    await expect.poll(() => listed(page)).toEqual([bakery, plain].sort());

    // With today's dates: still the same two. With a range that ended last year: none.
    const today = new Date().toLocaleDateString('en-CA', { timeZone: 'America/Toronto' });
    await page.getByLabel('Booked from').fill(today);
    await page.getByLabel('Booked to').fill(today);
    await page.getByRole('button', { name: 'Apply filters' }).click();
    await expect.poll(() => new URL(page.url()).searchParams.get('booked_from')).toBe(today);
    await expect.poll(() => listed(page)).toEqual([bakery, plain].sort());

    await page.getByLabel('Booked from').fill('2025-01-01');
    await page.getByLabel('Booked to').fill('2025-01-31');
    await page.getByRole('button', { name: 'Apply filters' }).click();
    await expect(page.getByText('No shipments match those filters')).toBeVisible();

    // The search survives a reload, and Clear filters clears it with the rest.
    await page.reload();
    await expect(page.getByLabel(/Search shipments/)).toHaveValue('chi minh');
    await page.getByRole('button', { name: 'Clear filters' }).first().click();
    await expect.poll(() => new URL(page.url()).search).toBe('');
    await expect(page.getByLabel(/Search shipments/)).toHaveValue('');
    await expect.poll(() => listed(page)).toEqual([bakery, florist, plain].sort());
  });
});
