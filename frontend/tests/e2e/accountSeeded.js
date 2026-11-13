/**
 * Activating an account against a **seeded customer that already has shipments**.
 *
 * A freshly created customer has no history, which is fine for most journeys and useless
 * for the ones that need rows to filter, page, open, or fail to reach from another
 * account. Registering with an address a seeded customer already holds makes the
 * duplicate check find that customer, and linking to it gives the account that customer's
 * history — through the approval screen, with the disclosure acknowledged, exactly as a
 * reviewer would.
 *
 * ## One address per seeded customer, once per run
 *
 * Release 1 permits **one approved active identity per canonical customer** (OD-25), and
 * an address can hold one identity. So each seeded address here belongs to one spec, and
 * the list below is the register of which. Reusing one across two specs produces a
 * refusal at approval time that reads like a bug in the screen.
 *
 * | Seeded address | Used by |
 * |---|---|
 * | `phuong.uyen.demo@demo.example.com` | `accountShipments.spec.js` |
 * | `bich.hanh.demo@demo.example.com` | `accountApproval.spec.js`, the linking journey |
 * | `minh.khoi.demo@demo.example.com` | `accountApproval.spec.js`, the override check (never approved) |
 * | `daniel.demo@demo.example.com` | `accountSecurity.spec.js`, as the other customer |
 * | `anh.thu.demo@demo.example.com` | `accountAccessibility.spec.js`, the `account` project |
 * | `kim.ngan.demo@demo.example.com` | `accountAccessibility.spec.js`, the `account-mobile` project |
 * | `marie.claude.demo@demo.example.com` | `accountMobile.spec.js` |
 */

import { expect } from '@playwright/test';
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

/** The other customer, for the horizontal-access assertions. */
export const OTHER_CUSTOMER_EMAIL = 'daniel.demo@demo.example.com';
export const OTHER_CUSTOMER_NAME = 'Daniel Demo';

/**
 * The accessibility suite's account, **one per project**.
 *
 * That spec runs twice — once at 1280 and once at 375 — and each run registers, verifies
 * and links. Release 1 permits one approved active identity per canonical customer
 * (OD-25) and one identity per address, so the second run against the same seeded
 * customer would meet a refusal at approval: correct behaviour, reported as a broken
 * screen. A customer each.
 */
const AUDIT_CUSTOMERS = {
  account: { email: 'anh.thu.demo@demo.example.com', legalName: 'Anh Thu Demo' },
  'account-mobile': { email: 'kim.ngan.demo@demo.example.com', legalName: 'Kim Ngan Demo' },
};

/** The seeded customer this project's accessibility run should link to. */
export function auditCustomerFor(projectName) {
  const chosen = AUDIT_CUSTOMERS[projectName];
  if (!chosen) {
    throw new Error(
      `No audit customer is reserved for the "${projectName}" project. Add one to ` +
        'AUDIT_CUSTOMERS, and to the register at the top of this file, rather than ' +
        'sharing one — two projects linking the same customer is a refusal, not a bug.',
    );
  }
  return chosen;
}

/**
 * Register, verify and link to the matching seeded customer, all through the screens.
 *
 * Returns the address, the account reference, and the first shipment reference the
 * account can now see — which is the value a caller usually wants, because it is the one
 * that must be invisible to everybody else.
 */
export async function activateAgainstSeeded(
  page,
  browser,
  { email, legalName } = { email: OTHER_CUSTOMER_EMAIL, legalName: OTHER_CUSTOMER_NAME },
) {
  await register(page, email, { legalName });
  await verify(page, email);

  const { context, page: staffPage } = await staffContext(browser);
  let accountReference;
  try {
    accountReference = await pendingReferenceFor(staffPage, email);
    await openApplication(staffPage, accountReference);

    await expect(
      staffPage.getByText(/An existing customer matches exactly/).first(),
    ).toBeVisible();
    const customerId = (
      await staffPage.locator('td.table__id').filter({ hasText: /^STCA-/ }).first().textContent()
    ).trim();

    // Give the customer a history to disclose. Every seeded shipment is a demo record
    // and the inclusion rule excludes those outright, so a seeded customer has **no**
    // qualifying shipments and the preview would honestly read zero. These are booked
    // through the staff API, so they are the rows the application builds.
    await bookHistoryFor(staffPage, customerId, { count: 3 });
    // The screens follow the customer's language (OD-71); these journeys read English.
    await contactInEnglish(staffPage, customerId);

    await staffPage.getByLabel('What should happen').selectOption('link_existing');
    await staffPage.getByLabel('Customer to link to').fill(customerId);
    await expect(staffPage.getByText('What this approval discloses')).toBeVisible();
    await acknowledge(staffPage);
    await staffPage.getByRole('button', { name: 'Approve and link' }).click();
    await expect(staffPage.getByText(/Approved —/)).toBeVisible();
  } finally {
    await closeStaffContext({ context, page: staffPage });
  }

  await signIn(page, email);
  await expect(page.getByRole('heading', { name: 'My shipments', level: 1 })).toBeVisible();

  // The reference is read from an **href**, not from a visible element. Every row is in
  // the DOM twice — the wide table and the narrow cards — and CSS hides one of them, so
  // "the first anchor" is visible at 1280 and hidden at 375. Which layout is showing is
  // not what this helper is about.
  const anchors = page.locator('a[href^="/account/shipments/SX-"]');
  await expect.poll(async () => anchors.count()).toBeGreaterThan(0);
  const href = await anchors.first().getAttribute('href');
  const shipmentReference = decodeURIComponent(href.split('/').pop());

  return { email, accountReference, shipmentReference };
}

/** The shorthand `accountSecurity.spec.js` uses: activate and return one reference. */
export async function activateAgainst(page, browser) {
  const { shipmentReference } = await activateAgainstSeeded(page, browser);
  return shipmentReference;
}
