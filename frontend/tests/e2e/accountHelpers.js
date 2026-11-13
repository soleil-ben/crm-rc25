/**
 * Shared machinery for the Customer Account end-to-end journeys.
 *
 * Every address is minted per run and per test. Nothing here reuses a fixed one, for two
 * reasons: an address that already has an account produces a *deliberately identical*
 * response to one that does not (T-02), so a reused address makes a registration test
 * silently assert nothing; and the per-address rate limits are the ones this suite leaves
 * at production values, so a reused address exhausts them.
 *
 * Nothing here logs a token, a password or a captured message body.
 */

import { expect } from '@playwright/test';
import { resetLinkFor, verificationLinkFor } from './mailCapture.js';

/** The seeded staff password. Synthetic, and the same one the staff suite uses. */
export const STAFF_PASSWORD = process.env.E2E_STAFF_PASSWORD || 'SolarisDemo!2026';
export const OPERATIONS_EMAIL = 'ops@demo.example.com';
export const ADMIN_EMAIL = 'admin@demo.example.com';
export const MARKETING_EMAIL = 'marketing@demo.example.com';
export const MANAGER_EMAIL = 'manager@demo.example.com';

/**
 * A password long enough for the policy and not in the refused-common list.
 *
 * A constant rather than a random string, because a failing test that printed a generated
 * password would put one in a report, and this one is synthetic and public in this file.
 */
export const CUSTOMER_PASSWORD = 'correct-horse-battery-staple-2026';

let sequence = 0;

/**
 * A fresh synthetic address, in `example.com`, unique within a run.
 *
 * Deliberately **short**. The capture transport names a file after the address, this
 * repository sits 151 characters deep, and a long address plus a long template key
 * produced a path Windows refused — which surfaced as a 500 on the registration route
 * (`account_email_service.MAX_FILENAME_LENGTH`). The transport now bounds its own
 * filename, and these addresses stay short so the captures are still readable by eye.
 *
 * The label is truncated rather than dropped: it is what tells a person reading the
 * capture directory which journey a message belongs to.
 */
export function freshAddress(label = 'customer') {
  sequence += 1;
  const suffix = `${Date.now().toString(36).slice(-5)}${sequence}`;
  return `ca-${label.slice(0, 8)}-${suffix}@example.com`;
}

/**
 * Register through the real form.
 *
 * Fills only the required fields unless `extra` asks for more, because the form's optional
 * sections are long and a journey test is about the journey.
 */
/**
 * Fill the registration address (UAT rounds 9 and 11): the four required parts and a
 * postal code, which is optional since round 11. The country stays Canada, and the billing
 * box starts ticked, so billing needs nothing.
 * `exact` on the group: Playwright's name match is a substring, and "Billing address"
 * contains "address".
 */
export async function fillRegistrationAddress(page) {
  const address = page.getByRole('group', { name: 'Address', exact: true });
  await address.getByLabel('Address line 1', { exact: true }).fill('4120 Dixie Road');
  await address.getByLabel('City', { exact: true }).fill('Mississauga');
  await address.getByLabel('Province or state', { exact: true }).fill('ON');
  await address.getByLabel('Postal code', { exact: true }).fill('L4W 1V2');
}

export async function register(page, email, { legalName, extra } = {}) {
  // A **unique** name by default, derived from the address.
  //
  // The duplicate check matches on name as well as on address, so a run that registered
  // six accounts all called "E2E Test Person" produced a *probable* duplicate from the
  // second one onwards — which correctly makes creating a separate customer require an
  // override reason, and incorrectly made six unrelated journeys fail at the approve
  // button. The override path has its own test; these journeys should not stumble into
  // it. Callers that want a specific name, such as the seeded-customer journeys, pass one.
  const name = legalName || `E2E ${email.split('@')[0]}`;
  await page.goto('/account/register');
  await page.getByLabel('Email address', { exact: true }).fill(email);
  // Exact: "Confirm password" below also contains "password" (UAT round 8).
  await page.getByLabel('Password', { exact: true }).fill(CUSTOMER_PASSWORD);
  await page.getByLabel('Confirm password', { exact: true }).fill(CUSTOMER_PASSWORD);
  await page.getByLabel('Full legal name', { exact: true }).fill(name);
  await fillRegistrationAddress(page);
  if (extra) await extra(page);
  await page.getByLabel(/I accept the Solaris Express terms/).check();
  await page.getByRole('button', { name: 'Create account' }).click();
  await expect(page.getByRole('heading', { name: 'Check your email', level: 1 })).toBeVisible();
}

/** Follow the captured verification link and confirm the outcome. */
export async function verify(page, email) {
  const link = await verificationLinkFor(email);
  await page.goto(link);
  await expect(page.getByRole('heading', { name: 'Email confirmed', level: 1 })).toBeVisible();
  // The token must be gone from the address bar by the time the outcome is on screen --
  // from the query string and from the fragment, which is where it now arrives.
  expect(new URL(page.url()).search).toBe('');
  expect(new URL(page.url()).hash).toBe('');
}

/** Follow the captured reset link, set a new password, and confirm. */
export async function resetPassword(page, email, newPassword) {
  const link = await resetLinkFor(email);
  await page.goto(link);
  await expect(page.getByRole('heading', { name: 'Choose a new password', level: 1 })).toBeVisible();
  expect(new URL(page.url()).search).toBe('');
  expect(new URL(page.url()).hash).toBe('');
  await page.getByLabel('New password', { exact: true }).fill(newPassword);
  await page.getByLabel('New password again', { exact: true }).fill(newPassword);
  await page.getByRole('button', { name: 'Change password' }).click();
  await expect(page.getByRole('heading', { name: 'Password updated', level: 1 })).toBeVisible();
}

/**
 * Sign in as a customer, and **wait for the attempt to finish**.
 *
 * Two things the first version got wrong, both found by the mobile suite.
 *
 * It returned as soon as it had clicked, so a caller that navigated next raced its own
 * sign-in: the POST was still in flight when `goto` replaced the page, and the next
 * assertion met the sign-in form again. Most callers happened to assert something first
 * and so happened to wait; the ones that did not failed intermittently.
 *
 * And it assumed the browser was signed out. `/account/sign-in` **redirects** a live
 * session to wherever that account belongs, so calling this twice — which
 * `activateAgainstSeeded` and its callers between them did — waited thirty seconds for
 * an email field that had correctly been replaced by a shipment list.
 *
 * So: go to the form, return early if there is no form because the session already
 * exists, and otherwise wait until the page is no longer the sign-in page or the failure
 * message has appeared. The caller still asserts *where* they landed.
 */
export async function signIn(page, email, password = CUSTOMER_PASSWORD) {
  await page.goto('/account/sign-in');

  const emailField = page.getByLabel('Email address', { exact: true });
  const form = page.getByRole('button', { name: 'Sign in' });
  // A live session is redirected away from this page; give that redirect a moment to
  // happen before deciding there is a form to fill.
  await Promise.race([
    emailField.waitFor({ state: 'visible', timeout: 10_000 }).catch(() => {}),
    page.waitForURL((url) => !url.pathname.endsWith('/account/sign-in'), {
      timeout: 10_000,
    }).catch(() => {}),
  ]);
  if (!(await emailField.count())) return;

  await emailField.fill(email);
  await page.getByLabel('Password', { exact: true }).fill(password);
  await form.click();

  // Either the sign-in succeeded and the shell moved, or it failed and said so. Both are
  // outcomes; neither is "still submitting".
  await Promise.race([
    page.waitForURL((url) => !url.pathname.endsWith('/account/sign-in'), {
      timeout: 15_000,
    }).catch(() => {}),
    page
      .getByText('Email or password is incorrect.')
      .waitFor({ state: 'visible', timeout: 15_000 })
      .catch(() => {}),
  ]);
}

/** Sign in a staff member through the real staff form, in whatever context is given. */
export async function signInStaff(page, email = OPERATIONS_EMAIL) {
  await page.goto('/');
  await page.getByLabel('Email address').fill(email);
  await page.getByLabel('Password').fill(STAFF_PASSWORD);
  await page.getByRole('button', { name: 'Sign in' }).click();
  await expect(
    page.getByRole('heading', { name: /Good (morning|afternoon|evening)/ }),
  ).toBeVisible({ timeout: 15_000 });
}

/**
 * A second browser context, signed in as staff.
 *
 * A separate context rather than a second tab: the two realms have different cookies, and
 * sharing a context would make every "does a staff cookie authenticate a customer route"
 * assertion accidental rather than designed.
 *
 * Close it with `closeStaffContext`, not `context.close()`.
 */
export async function staffContext(browser, email = OPERATIONS_EMAIL) {
  const context = await browser.newContext();
  const page = await context.newPage();
  await signInStaff(page, email);
  return { context, page };
}

/**
 * Close a staff context **after its requests have finished**.
 *
 * Closing a context abandons whatever the browser had in flight; it does not stop the
 * server finishing it. The staff review screens write an audit row on every read, so an
 * abandoned queue load can still be committing while the customer's next request starts
 * — and on SQLite a transaction that has read cannot then take the write lock, so one of
 * the two gets `database is locked` (`docs/OPERATIONS.md` §5, DEC-0006).
 *
 * That contention is real and is a documented property of running this application on
 * SQLite with more than one concurrent caller. What is *not* real is a test creating it
 * by walking away mid-request, so the helper waits first. A spec that wants to prove
 * something about genuine concurrency — `accountApproval.spec.js`'s two reviewers — does
 * it deliberately and in the open.
 */
export async function closeStaffContext({ context, page }) {
  await page.waitForLoadState('networkidle', { timeout: 10_000 }).catch(() => {});
  await context.close();
}

/** Open one application in the staff approval queue. */
export async function openApplication(staffPage, accountReference) {
  await staffPage.goto(`/customer-accounts/${accountReference}`);
  await expect(
    staffPage.getByRole('heading', { name: accountReference, level: 1 }),
  ).toBeVisible();
}

/**
 * The account reference for an address, and a check that it is in the queue.
 *
 * Reading the reference off the queue screen was the first attempt and it was wrong: the
 * queue is ordered by submission **ascending**, so "the first row" is the oldest pending
 * application, not the one the test just created. A run with several pending applications
 * therefore had every journey open somebody else's — which produced failures that looked
 * like the approve button being broken and were a test picking the wrong row.
 *
 * So the reference comes from this run's own database, by address, and the **queue screen
 * is still exercised**: this navigates to it and asserts the row is there before handing
 * the reference back. What is not exercised is "find my row among many by eye", which is
 * a test-harness problem rather than a thing a reviewer does.
 */
export async function pendingReferenceFor(staffPage, email) {
  const { accountReferenceFor } = await import('./accountAdmin.js');
  const reference = accountReferenceFor(email);

  await staffPage.goto(`/customer-accounts?account_reference=${reference}`);
  await expect(
    staffPage.getByRole('heading', { name: 'Customer account applications', level: 1 }),
  ).toBeVisible();
  await expect(staffPage.getByRole('link', { name: reference })).toBeVisible();

  return reference;
}

/**
 * Tick the disclosure acknowledgement, and wait for the server to record it.
 *
 * `.check()` is wrong here and Playwright says so: it clicks and then asserts the box is
 * checked *immediately*, and this box is not controlled by the click. The click posts the
 * acknowledgement, and the box reflects the fingerprint the **server** confirmed — which
 * is the whole point of the control (a box that ticked itself would be a claim the
 * reviewer made rather than a record the server holds). So: click, then wait.
 */
export async function acknowledge(staffPage) {
  await staffPage.getByLabel(/I have read the figures above/).click();
  await expect(staffPage.getByLabel(/I have read the figures above/)).toBeChecked();
}

/**
 * Take a preview, acknowledge it, and approve by creating a new customer.
 *
 * The order is the server's, and this helper follows it rather than shortcutting it,
 * because a helper that called the API directly would mean the journey specs never
 * exercised the screen the acknowledgement lives on.
 */
export async function approveByCreating(staffPage) {
  await expect(staffPage.getByText('What this approval discloses')).toBeVisible();
  await acknowledge(staffPage);
  const approve = staffPage.getByRole('button', { name: 'Approve and create the customer' });
  await expect(approve).toBeEnabled();
  await approve.click();
  await expect(staffPage.getByText(/Approved —/)).toBeVisible();
}

/** Approve by linking to a customer the reviewer names. */
export async function approveByLinking(staffPage, customerPublicId) {
  await staffPage.getByLabel('What should happen').selectOption('link_existing');
  await staffPage.getByLabel('Customer to link to').fill(customerPublicId);
  await expect(staffPage.getByText('What this approval discloses')).toBeVisible();
  await acknowledge(staffPage);
  const approve = staffPage.getByRole('button', { name: 'Approve and link' });
  await expect(approve).toBeEnabled();
  await approve.click();
  await expect(staffPage.getByText(/Approved —/)).toBeVisible();
}

/** Decline an application with a bounded reason. */
export async function reject(staffPage, reasonLabel = 'Identity could not be established') {
  await staffPage.getByLabel('Reason').selectOption({ label: reasonLabel });
  await staffPage.getByRole('button', { name: 'Decline the application' }).click();
  // The outcome banner, and the application's own state line, which since UAT round 3 says
  // the same instead of a stale "Waiting for review".
  await expect(staffPage.locator('.banner__title', { hasText: 'Declined' })).toBeVisible();
  await expect(staffPage.getByRole('definition').filter({ hasText: /^Declined$/ })).toBeVisible();
  await expect(staffPage.getByText('Waiting for review')).toHaveCount(0);
}

/**
 * Register, verify, and have Operations approve, in one call.
 *
 * Returns the account reference and the customer reference the approval created. Used by
 * the specs whose subject is what happens *after* activation, so they do not each
 * re-implement five steps.
 */
export async function activatedCustomer(page, browser, { label = 'active' } = {}) {
  const email = freshAddress(label);
  await register(page, email);
  await verify(page, email);

  const { context, page: staffPage } = await staffContext(browser);
  try {
    const reference = await pendingReferenceFor(staffPage, email);
    await openApplication(staffPage, reference);
    await approveByCreating(staffPage);
    return { email, accountReference: reference };
  } finally {
    await closeStaffContext({ context, page: staffPage });
  }
}

/**
 * Record every request a page makes, so a test can assert what was **not** called.
 *
 * The Customer Account's boundary requirements are almost all negative, and a negative is
 * only provable by watching the whole conversation.
 */
export function recordRequests(page) {
  const requests = [];
  page.on('request', (request) => {
    requests.push({ url: request.url(), method: request.method() });
  });
  return requests;
}

/** Staff API prefixes the Customer Account must never request. */
export const STAFF_API_PREFIXES = [
  '/api/v1/auth',
  '/api/v1/customers',
  '/api/v1/shipments',
  '/api/v1/packages',
  '/api/v1/segments',
  '/api/v1/tasks',
  '/api/v1/admin',
  '/api/v1/reports',
  '/api/v1/customer-account',
];

/** The public tracking API, which is not a fallback for a refused authenticated read. */
export const PUBLIC_API_PREFIX = '/api/v1/public';
