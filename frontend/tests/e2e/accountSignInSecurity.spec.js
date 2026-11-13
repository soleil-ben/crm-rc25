/**
 * RC-UAT-21 Phase B (DEC-0231): Sign-in and security, in a real browser.
 *
 * An account is created fresh through the screens and approved by staff. The customer then
 * changes their password (and signs in with the new one) and finds the sign-in email read
 * only; an Admin changes it on the staff account screen (RC-UAT-25 item 2, Ben 2026-10-25:
 * the old address is told, the new one is told how to sign in, every session ends); and an
 * Admin deactivates and reinstates the account through the staff screens. Mail is the capture
 * transport; nothing leaves the machine.
 */

import { expect, test } from './diagnostics.js';
import { auditAndAssert } from './axeHelpers.js';
import {
  ADMIN_EMAIL,
  CUSTOMER_PASSWORD,
  activatedCustomer,
  closeStaffContext,
  freshAddress,
  signIn,
  staffContext,
} from './accountHelpers.js';
import { messageCountFor, waitForMessage } from './mailCapture.js';

const NEW_PASSWORD = 'a-new-horse-battery-staple-2027';

function card(page, title) {
  return page.locator('.ca-card', { has: page.getByRole('heading', { name: title }) });
}

test.describe('Sign-in and security', () => {
  test('password change, then an Admin changes the sign-in email', async ({
    page,
    browser,
  }, testInfo) => {
    test.setTimeout(180_000);
    const { email, accountReference } = await activatedCustomer(page, browser, {
      label: 'sec-change',
    });
    await signIn(page, email);
    await page.getByRole('link', { name: 'Sign-in and security' }).click();
    await expect(page.getByRole('heading', { name: 'Sign-in and security', level: 1 })).toBeVisible();
    await auditAndAssert(page, 'account-sign-in-security', testInfo);

    // --- Password -------------------------------------------------------------------------
    const password = card(page, 'Change your password');
    await password.getByLabel(/^Current password/).fill(CUSTOMER_PASSWORD);
    await password.getByLabel('New password', { exact: true }).fill(NEW_PASSWORD);
    await password.getByLabel(/^New password again/).fill(NEW_PASSWORD);
    await password.getByRole('button', { name: 'Change password' }).click();
    await expect(page.getByText('Password changed.', { exact: true })).toBeVisible();
    await waitForMessage(email, { templateKey: 'account.password_changed_here' });

    // Still signed in here; the new password is the one that works.
    await page.reload();
    await expect(page.getByRole('heading', { name: 'Sign-in and security', level: 1 })).toBeVisible();
    await page.getByRole('button', { name: 'Sign out' }).click();
    await signIn(page, email, CUSTOMER_PASSWORD);
    await expect(page.getByText('Email or password is incorrect.')).toBeVisible();
    await signIn(page, email, NEW_PASSWORD);
    await expect(page).not.toHaveURL(/\/account\/sign-in$/);

    // --- Email: read only for the customer (RC-UAT-25 item 2, Ben 2026-10-25) --------------
    await page.goto('/account/security');
    const emailCard = card(page, 'Your sign-in email');
    await expect(emailCard.getByText(email, { exact: true })).toBeVisible();
    await expect(
      emailCard.getByText(/Only Solaris Express can change your sign-in email/),
    ).toBeVisible();
    await expect(page.getByLabel(/^New email/)).toHaveCount(0);
    await expect(page.getByRole('button', { name: 'Send confirmation link' })).toHaveCount(0);

    // --- An Admin changes it on the staff account screen ----------------------------------
    const newAddress = freshAddress('sec-new');
    const admin = await staffContext(browser, ADMIN_EMAIL);
    try {
      const staffPage = admin.page;
      await staffPage.goto(`/customer-accounts/${accountReference}`);
      await staffPage.getByLabel('New sign-in email').fill(newAddress);
      await staffPage.getByLabel('Grounds for the change').selectOption('customer_request');
      await staffPage.getByRole('button', { name: 'Change sign-in email' }).click();
      await staffPage.getByRole('dialog').getByRole('button', { name: 'Yes, change it' }).click();
      await expect(
        staffPage.getByText(
          'The sign-in email has been changed. The customer must sign in again with the new address.',
        ),
      ).toBeVisible();
    } finally {
      await closeStaffContext(admin);
    }
    await waitForMessage(email, { templateKey: 'account.email_changed_notice' });
    await waitForMessage(newAddress, { templateKey: 'account.sign_in_email_set_by_staff' });

    // The customer was signed out everywhere; the old address no longer signs in.
    await page.goto('/account/security');
    await expect(page).toHaveURL(/\/account\/sign-in/);
    await signIn(page, email, NEW_PASSWORD);
    await expect(page.getByText('Email or password is incorrect.')).toBeVisible();
    await signIn(page, newAddress, NEW_PASSWORD);
    await expect(page).not.toHaveURL(/\/account\/sign-in$/);
    await page.goto('/account/security');
    await expect(card(page, 'Your sign-in email').getByText(newAddress)).toBeVisible();
  });

  test('an Admin deactivates and reinstates the account; the customer signs in again', async ({
    page,
    browser,
  }) => {
    test.setTimeout(180_000);
    const { email, accountReference } = await activatedCustomer(page, browser, {
      label: 'sec-reinstate',
    });
    const admin = await staffContext(browser, ADMIN_EMAIL);
    try {
      const staffPage = admin.page;
      await staffPage.goto(`/customer-accounts/${accountReference}`);
      await staffPage.getByLabel('Grounds for deactivating').selectOption('customer_request');
      await staffPage.getByRole('button', { name: 'Deactivate account' }).click();
      await staffPage
        .getByRole('dialog')
        .getByRole('button', { name: 'Yes, deactivate' })
        .click();
      await expect(staffPage.getByRole('heading', { name: 'Reinstate account' })).toBeVisible();

      await signIn(page, email);
      await expect(page.getByText('Email or password is incorrect.')).toBeVisible();

      const before = messageCountFor(email, { templateKey: 'account.reinstated' });
      await staffPage.getByLabel('Grounds for reinstating').selectOption('deactivated_in_error');
      await staffPage.getByRole('button', { name: 'Reinstate account' }).click();
      await expect(
        staffPage.getByText('The account has been reinstated. The customer must sign in again.'),
      ).toBeVisible();
      await waitForMessage(email, { templateKey: 'account.reinstated' });
      expect(messageCountFor(email, { templateKey: 'account.reinstated' })).toBe(before + 1);
    } finally {
      await closeStaffContext(admin);
    }

    await signIn(page, email);
    await expect(page).not.toHaveURL(/\/account\/sign-in$/);
  });
});
