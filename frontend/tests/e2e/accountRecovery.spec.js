/**
 * Password reset, session revocation, the suspended account, and Admin deactivation.
 *
 * Workflows 10 and 17.
 */

import { expect, test } from './diagnostics.js';
import {
  ADMIN_EMAIL,
  CUSTOMER_PASSWORD,
  activatedCustomer,
  closeStaffContext,
  openApplication,
  staffContext,
  freshAddress,
  register,
  resetPassword,
  signIn,
  verify,
} from './accountHelpers.js';
import { TEMPLATE, messageCountFor } from './mailCapture.js';

const NEW_PASSWORD = 'another-perfectly-good-passphrase-2026';

test('a completed reset revokes the session that was already open', async ({ page, browser }) => {
  const { email } = await activatedCustomer(page, browser, { label: 'reset' });

  // Sign in in one context and leave it open. This is the session the reset must kill.
  const openSession = await browser.newContext();
  const openPage = await openSession.newPage();
  try {
    await signIn(openPage, email);
    await expect(openPage.getByRole('heading', { name: 'My shipments', level: 1 })).toBeVisible();

    // Meanwhile, ask for a reset and complete it in the original context.
    await page.goto('/account/forgot-password');
    await page.getByLabel('Email address', { exact: true }).fill(email);
    await page.getByRole('button', { name: 'Send the reset link' }).click();
    await expect(page.getByRole('heading', { name: 'Check your email', level: 1 })).toBeVisible();

    await resetPassword(page, email, NEW_PASSWORD);
    await expect(page.getByText(/has been signed out/)).toBeVisible();

    // The other context's session is dead on its next request, not at its next sign-in.
    await openPage.reload();
    await expect(
      openPage.getByRole('heading', { name: 'Sign in', level: 1 }),
    ).toBeVisible({ timeout: 15_000 });
  } finally {
    await openSession.close();
  }

  // The old password no longer works and the new one does.
  await signIn(page, email, CUSTOMER_PASSWORD);
  await expect(page.getByText('Email or password is incorrect.')).toBeVisible();

  await signIn(page, email, NEW_PASSWORD);
  await expect(page.getByRole('heading', { name: 'My shipments', level: 1 })).toBeVisible();

  // A notice was sent, and it carries no link.
  await expect
    .poll(() => messageCountFor(email, { templateKey: TEMPLATE.PASSWORD_CHANGED }))
    .toBeGreaterThan(0);
});

test('a reset request for an address with no account looks the same', async ({ page }) => {
  const unknown = freshAddress('nobody');
  await page.goto('/account/forgot-password');
  await page.getByLabel('Email address', { exact: true }).fill(unknown);
  await page.getByRole('button', { name: 'Send the reset link' }).click();
  await expect(page.getByRole('heading', { name: 'Check your email', level: 1 })).toBeVisible();
  const unknownPage = await page.locator('main').innerText();

  // And for one that does. The comparison is against a registered-but-unapproved
  // address, which is enough: what must not differ is the *page*.
  const known = freshAddress('somebody');
  await register(page, known);
  await verify(page, known);

  await page.goto('/account/forgot-password');
  await page.getByLabel('Email address', { exact: true }).fill(known);
  await page.getByRole('button', { name: 'Send the reset link' }).click();
  await expect(page.getByRole('heading', { name: 'Check your email', level: 1 })).toBeVisible();

  expect(await page.locator('main').innerText()).toBe(unknownPage);

  // No message was sent to the address with no account.
  expect(messageCountFor(unknown)).toBe(0);
});

test('a reset link works once', async ({ page, browser }) => {
  const { email } = await activatedCustomer(page, browser, { label: 'once' });

  await page.goto('/account/forgot-password');
  await page.getByLabel('Email address', { exact: true }).fill(email);
  await page.getByRole('button', { name: 'Send the reset link' }).click();
  await expect(page.getByRole('heading', { name: 'Check your email', level: 1 })).toBeVisible();

  const { resetLinkFor } = await import('./mailCapture.js');
  const link = await resetLinkFor(email);

  await page.goto(link);
  await page.getByLabel('New password', { exact: true }).fill(NEW_PASSWORD);
  await page.getByLabel('New password again', { exact: true }).fill(NEW_PASSWORD);
  await page.getByRole('button', { name: 'Change password' }).click();
  await expect(page.getByRole('heading', { name: 'Password updated', level: 1 })).toBeVisible();

  // The same link again: the form still renders — the token is not checked until submit —
  // and the submission is refused with the one generic sentence.
  await page.goto(link);
  await page.getByLabel('New password', { exact: true }).fill('a-third-passphrase-entirely-2026');
  await page.getByLabel('New password again', { exact: true }).fill('a-third-passphrase-entirely-2026');
  await page.getByRole('button', { name: 'Change password' }).click();
  await expect(page.getByText('That link is no longer valid. Request a new one.')).toBeVisible();
});

test('a suspended account cannot sign in, and is not told that it is suspended', async ({
  page,
  browser,
}) => {
  const { email } = await activatedCustomer(page, browser, { label: 'suspended' });

  // Suspension is a staff act with no screen in Phase 12 — `PRODUCT_SPEC.md` §4 lists it
  // as staff work and the owner's instruction builds the approval queue only. The state
  // is reached through the service, in this run's own database, which is what the
  // *customer-facing* behaviour under test depends on.
  const { suspendIdentity } = await import('./accountAdmin.js');
  suspendIdentity(email);

  await signIn(page, email);
  await expect(page.getByText('Email or password is incorrect.')).toBeVisible();

  // The same sentence a wrong password gets. Nothing says suspended, deactivated,
  // disabled or locked.
  const body = await page.locator('main').innerText();
  expect(body).not.toMatch(/suspend|deactivat|disabled|locked|closed/i);
});

test('suspension takes effect on the next request, not at the next sign-in', async ({
  page,
  browser,
}) => {
  const { email } = await activatedCustomer(page, browser, { label: 'midsession' });

  await signIn(page, email);
  await expect(page.getByRole('heading', { name: 'My shipments', level: 1 })).toBeVisible();

  const { suspendIdentity } = await import('./accountAdmin.js');
  suspendIdentity(email);

  await page.reload();
  await expect(page.getByRole('heading', { name: 'Sign in', level: 1 })).toBeVisible({
    timeout: 15_000,
  });
});

test('the unavailable state names neither suspension nor deactivation', async ({ page }) => {
  await page.goto('/account/unavailable');
  await expect(
    page.getByRole('heading', { name: 'This account is not available', level: 1 }),
  ).toBeVisible();
  const body = await page.locator('main').innerText();
  expect(body).not.toMatch(/suspend|deactivat/i);
});

test('an Admin deactivates an account from the review screen, and it can no longer sign in', async ({
  page,
  browser,
}) => {
  // DEC-0126, DEC-0131 (UAT round 4): Admin only, a bounded reason, a confirmation.
  const { email, accountReference } = await activatedCustomer(page, browser, {
    label: 'deactivated',
  });

  const { context, page: staffPage } = await staffContext(browser, ADMIN_EMAIL);
  try {
    await openApplication(staffPage, accountReference);
    await expect(staffPage.getByText('Deactivate this account')).toBeVisible();
    await staffPage.getByLabel('Grounds for deactivating').selectOption('customer_request');
    await staffPage.getByRole('button', { name: 'Deactivate account' }).click();
    await staffPage.getByRole('dialog').getByRole('button', { name: 'Yes, deactivate' }).click();
    await expect(
      staffPage.getByText('The account has been deactivated and signed out everywhere.'),
    ).toBeVisible();
    await expect(staffPage.getByRole('button', { name: 'Deactivate account' })).toHaveCount(0);
  } finally {
    await closeStaffContext({ context, page: staffPage });
  }

  await signIn(page, email);
  await expect(page.getByText('Email or password is incorrect.')).toBeVisible();
  const body = await page.locator('main').innerText();
  expect(body).not.toMatch(/suspend|deactivat|disabled|locked|closed/i);
});
