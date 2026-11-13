/**
 * The authenticated shipment list and detail, in a browser.
 *
 * Workflows 5, 6, 7, 8, 9 and 16, as one continuous journey plus the negatives.
 *
 * ## Why these register with a seeded customer's own address
 *
 * A freshly created customer has no shipments, and an empty list cannot be filtered or
 * paged. Registering with an address a seeded customer already has makes the duplicate
 * check find that customer, which is what lets the reviewer **link** to it — and linking
 * is what gives the account a real history to read. That is also the OD-23 case worth
 * exercising: an exact match must produce no hint to the applicant and a visible
 * candidate to staff.
 */

import { expect, test } from './diagnostics.js';
import { bookHistoryFor, contactInEnglish } from './accountBooking.js';
import {
  acknowledge,
  closeStaffContext,
  pendingReferenceFor,
  openApplication,
  register,
  signIn,
  staffContext,
  verify,
} from './accountHelpers.js';

/** A seeded customer with qualifying shipment history. */
const SEEDED_CUSTOMER_EMAIL = 'phuong.uyen.demo@demo.example.com';
const SEEDED_CUSTOMER_NAME = 'Phuong Uyen Demo';

/** Values that must never appear on this surface, whatever the response contains. */
const FORBIDDEN_ON_SCREEN = [
  'Internal note',
  'Assigned to',
  'Payment',
  'Invoice',
  'Declared value',
  'Profit',
  'Selling amount',
  'Lifecycle',
  'Duplicate',
  'Integration',
];

/**
 * Register, verify, and have Operations link the account to the matching seeded customer.
 *
 * Returns the address. Every step goes through a screen, including the approval, because
 * a helper that called the API would mean this file never exercised the thing Phase 12
 * built.
 */
async function activateAgainstSeededCustomer(page, browser) {
  const email = SEEDED_CUSTOMER_EMAIL;
  await register(page, email, { legalName: SEEDED_CUSTOMER_NAME });

  // The applicant is told nothing about the match.
  const confirmation = await page.locator('main').innerText();
  expect(confirmation).not.toMatch(/already|existing|match|STCA-/i);

  await verify(page, email);

  const { context, page: staffPage } = await staffContext(browser);
  try {
    const reference = await pendingReferenceFor(staffPage, email);
    await openApplication(staffPage, reference);

    await expect(
      staffPage.getByText(/An existing customer matches exactly/).first(),
    ).toBeVisible();
    const customerId = (
      await staffPage.locator('td.table__id').filter({ hasText: /^STCA-/ }).first().textContent()
    ).trim();

    // Every seeded shipment is a demo record, and the inclusion rule excludes those in
    // every environment — correctly, because an authenticated customer must never be
    // shown a fabricated shipment. So the history this journey reads is booked here,
    // through the staff API, and is not a demo record.
    await bookHistoryFor(staffPage, customerId, { count: 4 });
    // The screens follow the customer's language (OD-71); this journey reads English.
    await contactInEnglish(staffPage, customerId);

    await staffPage.getByLabel('What should happen').selectOption('link_existing');
    await staffPage.getByLabel('Customer to link to').fill(customerId);
    await expect(staffPage.getByText('What this approval discloses')).toBeVisible();

    // The disclosure is not zero: this is a customer with history, which is the whole
    // reason the preview exists.
    await expect(staffPage.getByText('Shipments that become visible')).toBeVisible();

    await acknowledge(staffPage);
    await staffPage.getByRole('button', { name: 'Approve and link' }).click();
    await expect(staffPage.getByText(/Approved —/)).toBeVisible();
  } finally {
    await closeStaffContext({ context, page: staffPage });
  }
  return email;
}

test('the whole journey: sign in, read history, filter, open one, sign out', async ({
  page,
  browser,
}) => {
  const email = await activateAgainstSeededCustomer(page, browser);

  // --- 5. Sign in after activation -------------------------------------------------
  await signIn(page, email);
  await expect(page.getByRole('heading', { name: 'My shipments', level: 1 })).toBeVisible();

  // --- 6. The historical list ------------------------------------------------------
  //
  // Each row is rendered **twice** — once in the wide table and once as a narrow card,
  // with CSS choosing between them — so counting anchors counts every row twice. What
  // the assertions below care about is how many *shipments* are listed, so they count
  // distinct references.
  const references = page.locator('a[href^="/account/shipments/SX-"]');
  const listedReferences = async () => {
    const hrefs = await references.evaluateAll((nodes) =>
      nodes.map((node) => node.getAttribute('href')),
    );
    return [...new Set(hrefs)];
  };

  await expect(references.first()).toBeVisible();
  const firstReference = (await references.first().textContent()).trim();

  const listText = await page.locator('main').innerText();
  for (const forbidden of FORBIDDEN_ON_SCREEN) {
    expect(listText, `the list showed "${forbidden}"`).not.toContain(forbidden);
  }

  // --- 7. Filters, and the URL that carries them ------------------------------------
  //
  // Since UAT round 10 the box is a keyword search (DEC-0156): the last eight characters
  // of an ID, in lower case, find it.
  const partial = firstReference.slice(-8).toLowerCase();
  await page.getByLabel(/Search shipments/).fill(partial);
  await page.getByRole('button', { name: 'Apply filters' }).click();
  await expect.poll(() => new URL(page.url()).searchParams.get('q')).toBe(partial);
  await expect.poll(async () => (await listedReferences()).length).toBe(1);

  // The filtered view survives a reload, with the control refilled from the URL.
  await page.reload();
  await expect(page.getByLabel(/Search shipments/)).toHaveValue(partial);
  await expect.poll(async () => (await listedReferences()).length).toBe(1);

  // A reference that is not this customer's produces an **empty list**, not a refusal
  // and not a hint that the shipment exists somewhere.
  await page.getByLabel(/Search shipments/).fill('SX-CAV-ABCDEFGHJKLM');
  await page.getByRole('button', { name: 'Apply filters' }).click();
  await expect(page.getByText('No shipments match those filters')).toBeVisible();

  await page.getByRole('button', { name: 'Clear filters' }).first().click();
  await expect.poll(() => new URL(page.url()).search).toBe('');
  await expect(references.first()).toBeVisible();

  // The route filter takes a vocabulary value and puts it in the URL.
  await page.getByLabel('Route').selectOption('CAV');
  await page.getByRole('button', { name: 'Apply filters' }).click();
  await expect.poll(() => new URL(page.url()).searchParams.get('route_group')).toBe('CAV');
  await page.getByRole('button', { name: 'Clear filters' }).first().click();
  await expect.poll(() => new URL(page.url()).search).toBe('');

  // The status filter composes with the rest and is equally addressable.
  await page.getByLabel('Status').selectOption('delivered');
  await page.getByRole('button', { name: 'Apply filters' }).click();
  await expect
    .poll(() => new URL(page.url()).searchParams.get('status_group'))
    .toBe('delivered');
  await page.getByRole('button', { name: 'Clear filters' }).first().click();

  // --- 8. One shipment ---------------------------------------------------------------
  await page.getByRole('link', { name: firstReference }).first().click();
  await expect(page.getByRole('heading', { name: firstReference, level: 1 })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Where it is', level: 2 })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Packages', level: 2 })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Updates', level: 2 })).toBeVisible();
  await expect(page.getByText('Dates shown in')).toBeVisible();

  const detailText = await page.locator('main').innerText();
  for (const forbidden of FORBIDDEN_ON_SCREEN) {
    expect(detailText, `the detail showed "${forbidden}"`).not.toContain(forbidden);
  }

  // A deep link to one shipment survives a refresh.
  await page.reload();
  await expect(page.getByRole('heading', { name: firstReference, level: 1 })).toBeVisible();

  // --- 16. A reference that is not this customer's -----------------------------------
  await page.goto('/account/shipments/SX-CAV-ABCDEFGHJKLM');
  await expect(
    page.getByRole('heading', { name: 'We could not find that shipment', level: 1 }),
  ).toBeVisible();
  const unknownText = await page.locator('main').innerText();

  await page.goto('/account/shipments/not-a-reference-at-all');
  await expect(
    page.getByRole('heading', { name: 'We could not find that shipment', level: 1 }),
  ).toBeVisible();
  // Byte-for-byte the same page. A malformed reference and an unknown one are one answer.
  expect(await page.locator('main').innerText()).toBe(unknownText);

  // --- 9. Sign out ---------------------------------------------------------------------
  await page.goto('/account/shipments');
  await expect(page.getByRole('heading', { name: 'My shipments', level: 1 })).toBeVisible();
  await page.getByRole('button', { name: 'Sign out' }).click();
  await expect(page.getByRole('heading', { name: 'Sign in', level: 1 })).toBeVisible();
  await expect(page.getByRole('link', { name: 'My shipments' })).toHaveCount(0);
});

test('an approved account with no shipments gets a plain sentence', async ({ page, browser }) => {
  // A brand-new customer, created by the approval rather than linked, has no history.
  const { activatedCustomer } = await import('./accountHelpers.js');
  const { email } = await activatedCustomer(page, browser, { label: 'empty' });

  await signIn(page, email);
  await expect(page.getByRole('heading', { name: 'My shipments', level: 1 })).toBeVisible();
  await expect(page.getByText('No shipments yet')).toBeVisible();

  // An empty history is not an error, and it does not invite a search for somebody
  // else's parcel.
  await expect(page.getByRole('alert')).toHaveCount(0);
  const text = await page.locator('main').innerText();
  expect(text).not.toMatch(/error|problem|search for/i);
});
