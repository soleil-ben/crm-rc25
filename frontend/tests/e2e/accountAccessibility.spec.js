/**
 * Automated accessibility for every new Customer Account and staff-approval state.
 *
 * Runs in two projects — `account` at 1280×800 and `account-mobile` at 375×812 — so every
 * screen below is audited at both viewports. Zero serious or critical violations is the
 * bar, `EXPECTED_FINDINGS` is empty, and nothing is suppressed to make a screen pass.
 *
 * **This is not a human accessibility review.** axe finds a subset of WCAG failures and
 * cannot tell whether a page makes sense read aloud, whether a focus order is logical, or
 * whether an error message helps. OD-19 — no reviewer assigned — is still open, and a
 * green run here does not close it.
 */

import { expect, test } from './diagnostics.js';
import { auditAndAssert, settle, staleExceptions } from './axeHelpers.js';
import {
  CUSTOMER_PASSWORD,
  acknowledge,
  activatedCustomer,
  closeStaffContext,
  freshAddress,
  pendingReferenceFor,
  openApplication,
  register,
  signIn,
  staffContext,
  verify,
} from './accountHelpers.js';
import { activateAgainstSeeded, auditCustomerFor } from './accountSeeded.js';
import { verificationLinkFor } from './mailCapture.js';

/**
 * The viewport this project audits at.
 *
 * A staff context is opened with `browser.newContext()`, which does **not** inherit the
 * project's viewport, so the staff screens would otherwise be audited at the default size
 * in both projects — and the 375 px run would be measuring nothing.
 */
function viewportFor(testInfo) {
  return testInfo.project.name === 'account-mobile'
    ? { width: 375, height: 812 }
    : { width: 1280, height: 800 };
}

test.describe.configure({ mode: 'serial' });

/** Shared across the file so the populated screens are audited against real rows. */
const audited = { email: null, shipmentReference: null };

test.describe('the unauthenticated screens', () => {
  test('sign in', async ({ page }, testInfo) => {
    await page.goto('/account/sign-in');
    await settle(page);
    await auditAndAssert(page, 'account-sign-in', testInfo);
  });

  test('sign in, showing a failure', async ({ page }, testInfo) => {
    await page.goto('/account/sign-in');
    await page.getByLabel('Email address', { exact: true }).fill('nobody@example.com');
    await page.getByLabel('Password', { exact: true }).fill('not-the-right-password');
    await page.getByRole('button', { name: 'Sign in' }).click();
    await expect(page.getByText('Email or password is incorrect.')).toBeVisible();
    await settle(page);
    await auditAndAssert(page, 'account-sign-in-failed', testInfo);
  });

  test('register, empty', async ({ page }, testInfo) => {
    await page.goto('/account/register');
    await settle(page);
    await auditAndAssert(page, 'account-register', testInfo);
  });

  test('register, showing the validation summary', async ({ page }, testInfo) => {
    await page.goto('/account/register');
    await page.getByRole('button', { name: 'Create account' }).click();
    await expect(page.getByRole('alert')).toBeVisible();
    await settle(page);
    await auditAndAssert(page, 'account-register-invalid', testInfo);
  });

  test('register, with the business fields shown', async ({ page }, testInfo) => {
    await page.goto('/account/register');
    await page.getByLabel('Are you shipping as', { exact: true }).selectOption('business');
    await expect(page.getByLabel('Kind of business', { exact: true })).toBeVisible();
    await settle(page);
    await auditAndAssert(page, 'account-register-business', testInfo);
  });

  test('check your email', async ({ page }, testInfo) => {
    const email = freshAddress('a11y-checkmail');
    await register(page, email);
    await settle(page);
    await auditAndAssert(page, 'account-check-your-email', testInfo);
  });

  test('verification succeeded', async ({ page }, testInfo) => {
    const email = freshAddress('a11y-verify-ok');
    await register(page, email);
    await page.goto(await verificationLinkFor(email));
    await expect(page.getByRole('heading', { name: 'Email confirmed', level: 1 })).toBeVisible();
    await settle(page);
    await auditAndAssert(page, 'account-verify-success', testInfo);
  });

  test('verification failed', async ({ page }, testInfo) => {
    await page.goto('/account/verify-email?token=never-issued');
    await expect(
      page.getByRole('heading', { name: 'That link did not work', level: 1 }),
    ).toBeVisible();
    await settle(page);
    await auditAndAssert(page, 'account-verify-failed', testInfo);
  });

  test('resend verification', async ({ page }, testInfo) => {
    await page.goto('/account/verification/resend');
    await settle(page);
    await auditAndAssert(page, 'account-resend', testInfo);
  });

  test('forgot password', async ({ page }, testInfo) => {
    await page.goto('/account/forgot-password');
    await settle(page);
    await auditAndAssert(page, 'account-forgot-password', testInfo);
  });

  test('reset password, the form', async ({ page }, testInfo) => {
    await page.goto('/account/reset-password?token=anything');
    await expect(
      page.getByRole('heading', { name: 'Choose a new password', level: 1 }),
    ).toBeVisible();
    await settle(page);
    await auditAndAssert(page, 'account-reset-password', testInfo);
  });

  test('reset password, refused', async ({ page }, testInfo) => {
    await page.goto('/account/reset-password?token=never-issued');
    await page.getByLabel('New password', { exact: true }).fill(CUSTOMER_PASSWORD);
    await page.getByLabel('New password again', { exact: true }).fill(CUSTOMER_PASSWORD);
    await page.getByRole('button', { name: 'Change password' }).click();
    await expect(page.getByText('That link is no longer valid. Request a new one.')).toBeVisible();
    await settle(page);
    await auditAndAssert(page, 'account-reset-password-failed', testInfo);
  });

  test('the declined state', async ({ page }, testInfo) => {
    await page.goto('/account/rejected');
    await settle(page);
    await auditAndAssert(page, 'account-rejected', testInfo);
  });

  test('the unavailable state', async ({ page }, testInfo) => {
    await page.goto('/account/unavailable');
    await settle(page);
    await auditAndAssert(page, 'account-unavailable', testInfo);
  });

  test('not found, inside the Customer Account', async ({ page }, testInfo) => {
    await page.goto('/account/no-such-page');
    await expect(page.getByRole('heading', { name: 'Page not found', level: 1 })).toBeVisible();
    await settle(page);
    await auditAndAssert(page, 'account-not-found', testInfo);
  });
});

test.describe('the signed-in screens', () => {
  test('pending approval', async ({ page }, testInfo) => {
    const email = freshAddress('a11y-pending');
    await register(page, email);
    await verify(page, email);
    await signIn(page, email);
    await expect(
      page.getByRole('heading', { name: 'Your account is being reviewed', level: 1 }),
    ).toBeVisible();
    await settle(page);
    await auditAndAssert(page, 'account-pending', testInfo);
  });

  test('an empty shipment list', async ({ page, browser }, testInfo) => {
    const { email } = await activatedCustomer(page, browser, { label: 'a11y-empty' });
    await signIn(page, email);
    await expect(page.getByText('No shipments yet')).toBeVisible();
    await settle(page);
    await auditAndAssert(page, 'account-shipments-empty', testInfo);
  });

  test('a populated shipment list', async ({ page, browser }, testInfo) => {
    const result = await activateAgainstSeeded(
      page,
      browser,
      auditCustomerFor(testInfo.project.name),
    );
    audited.email = result.email;
    audited.shipmentReference = result.shipmentReference;
    await settle(page);
    await auditAndAssert(page, 'account-shipments-list', testInfo);
  });

  test('the list with filters applied', async ({ page }, testInfo) => {
    await signIn(page, audited.email);
    await expect(page.getByRole('heading', { name: 'My shipments', level: 1 })).toBeVisible();
    await page.getByLabel('Status').selectOption('delivered');
    await page.getByLabel('Route').selectOption('CAV');
    await page.getByRole('button', { name: 'Apply filters' }).click();
    await settle(page);
    await auditAndAssert(page, 'account-shipments-filtered', testInfo);
  });

  test('an empty filtered result', async ({ page }, testInfo) => {
    await signIn(page, audited.email);
    await page.goto('/account/shipments?q=SX-CAV-ABCDEFGHJKLM');
    await expect(page.getByText('No shipments match those filters')).toBeVisible();
    await settle(page);
    await auditAndAssert(page, 'account-shipments-no-match', testInfo);
  });

  test('one shipment', async ({ page }, testInfo) => {
    await signIn(page, audited.email);
    await page.goto(`/account/shipments/${audited.shipmentReference}`);
    await expect(
      page.getByRole('heading', { name: audited.shipmentReference, level: 1 }),
    ).toBeVisible();
    await settle(page);
    await auditAndAssert(page, 'account-shipment-detail', testInfo);
  });

  test('a shipment that cannot be shown', async ({ page }, testInfo) => {
    await signIn(page, audited.email);
    await page.goto('/account/shipments/SX-CAV-ABCDEFGHJKLM');
    await expect(
      page.getByRole('heading', { name: 'We could not find that shipment', level: 1 }),
    ).toBeVisible();
    await settle(page);
    await auditAndAssert(page, 'account-shipment-not-found', testInfo);
  });

  test('the rate-limited state', async ({ page }, testInfo) => {
    await signIn(page, audited.email);
    // The limiter is 300 reads in five minutes and this suite will not reach it, so the
    // *response* is produced by interception. What is audited is the screen: a warning
    // region with a retry time, which is a state a customer really can see.
    await page.route('**/api/v1/account/shipments?**', (route) =>
      route.fulfill({
        status: 429,
        headers: { 'Retry-After': '45' },
        contentType: 'application/json',
        body: JSON.stringify({
          code: 'rate_limited',
          message: 'Too many requests. Wait a moment and try again.',
          field: null,
        }),
      }),
    );
    await page.goto('/account/shipments?status_group=delivered');
    await expect(page.getByText('Too many requests.')).toBeVisible();
    await settle(page);
    await auditAndAssert(page, 'account-shipments-rate-limited', testInfo);
  });

  test('the session-expired state', async ({ page }, testInfo) => {
    await signIn(page, audited.email);
    await expect(page.getByRole('heading', { name: 'My shipments', level: 1 })).toBeVisible();
    await page.route('**/api/v1/account/shipments?**', (route) =>
      route.fulfill({
        status: 401,
        contentType: 'application/json',
        body: JSON.stringify({
          code: 'not_authenticated',
          message: 'Sign in to continue.',
          field: null,
        }),
      }),
    );
    await page.goto('/account/shipments?status_group=delivered');
    await expect(page.getByText('Your session has ended.')).toBeVisible();
    await settle(page);
    await auditAndAssert(page, 'account-session-expired', testInfo);
  });
});

test.describe('the staff approval screens', () => {
  test('the queue', async ({ browser }, testInfo) => {
    const { context, page: staffPage } = await staffContext(browser);
    try {
      await staffPage.setViewportSize(viewportFor(testInfo));
      await staffPage.goto('/customer-accounts');
      await expect(
        staffPage.getByRole('heading', { name: 'Customer account applications', level: 1 }),
      ).toBeVisible();
      await settle(staffPage);
      await auditAndAssert(staffPage, 'staff-customer-account-queue', testInfo);
    } finally {
      await closeStaffContext({ context, page: staffPage });
    }
  });

  test('one application, with its preview and duplicates', async ({ page, browser }, testInfo) => {
    const email = freshAddress('a11y-review');
    await register(page, email);
    await verify(page, email);

    const { context, page: staffPage } = await staffContext(browser);
    try {
      await staffPage.setViewportSize(viewportFor(testInfo));
      const reference = await pendingReferenceFor(staffPage, email);
      await openApplication(staffPage, reference);
      await expect(staffPage.getByText('What this approval discloses')).toBeVisible();
      await settle(staffPage);
      await auditAndAssert(staffPage, 'staff-customer-account-review', testInfo);

      // Acknowledged: the approve controls become operable, which is a different screen.
      await acknowledge(staffPage);
      await expect(
        staffPage.getByRole('button', { name: 'Approve and create the customer' }),
      ).toBeEnabled();
      await settle(staffPage);
      await auditAndAssert(staffPage, 'staff-customer-account-acknowledged', testInfo);

      // The conflict state.
      await staffPage.route('**/approve/create-new', (route) =>
        route.fulfill({
          status: 409,
          contentType: 'application/json',
          body: JSON.stringify({
            code: 'conflict',
            message: 'This registration has changed since the preview was taken.',
          }),
        }),
      );
      await staffPage.getByRole('button', { name: 'Approve and create the customer' }).click();
      await expect(
        staffPage.getByText('Something changed while you were reading'),
      ).toBeVisible();
      await settle(staffPage);
      await auditAndAssert(staffPage, 'staff-customer-account-conflict', testInfo);
    } finally {
      await closeStaffContext({ context, page: staffPage });
    }
  });

  test('a completed decision', async ({ page, browser }, testInfo) => {
    const email = freshAddress('a11y-decided');
    await register(page, email);
    await verify(page, email);

    const { context, page: staffPage } = await staffContext(browser);
    try {
      await staffPage.setViewportSize(viewportFor(testInfo));
      const reference = await pendingReferenceFor(staffPage, email);
      await openApplication(staffPage, reference);
      await expect(staffPage.getByText('What this approval discloses')).toBeVisible();
      await acknowledge(staffPage);
      await staffPage.getByRole('button', { name: 'Approve and create the customer' }).click();
      await expect(staffPage.getByText(/Approved —/)).toBeVisible();
      await settle(staffPage);
      await auditAndAssert(staffPage, 'staff-customer-account-approved', testInfo);
    } finally {
      await closeStaffContext({ context, page: staffPage });
    }
  });

  test('a declined decision', async ({ page, browser }, testInfo) => {
    const email = freshAddress('a11y-declined');
    await register(page, email);
    await verify(page, email);

    const { context, page: staffPage } = await staffContext(browser);
    try {
      await staffPage.setViewportSize(viewportFor(testInfo));
      const reference = await pendingReferenceFor(staffPage, email);
      await openApplication(staffPage, reference);
      await staffPage
        .getByLabel('Reason')
        .selectOption({ label: 'Identity could not be established' });
      await staffPage.getByRole('button', { name: 'Decline the application' }).click();
      await expect(staffPage.locator('.banner__title', { hasText: 'Declined' })).toBeVisible();
      await settle(staffPage);
      await auditAndAssert(staffPage, 'staff-customer-account-declined', testInfo);
    } finally {
      await closeStaffContext({ context, page: staffPage });
    }
  });
});

test('no accessibility suppression is stale', async () => {
  // `EXPECTED_FINDINGS` is empty and this asserts it stays that way: a suppression that
  // matches nothing is one nobody has re-read.
  expect(staleExceptions()).toEqual([]);
});
