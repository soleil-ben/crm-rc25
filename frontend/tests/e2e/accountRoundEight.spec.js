/**
 * UAT round 8 in a real browser (the owner's real-phone feedback of 2026-10-17, and the
 * staff-side gaps found the same day).
 *
 * 1–2. Registration asks for the shipping address first, and "Billing address is the same
 *      as shipping address" hides the billing fields while ticked.
 * 3.   The password is typed twice at registration and at reset; a mismatch is an inline
 *      error and nothing is sent.
 * 4.   An approved change request does not show its own values as "Changed since".
 * 5.   Audit access lists the old and new value of each field the approval applied.
 * 6.   A customer's marketing withdrawal names their account as the actor, in the audit
 *      and in the consent history.
 *
 * The phone-width layout of the same form is in `accountMobile.spec.js`.
 */

import { expect, test } from './diagnostics.js';
import {
  ADMIN_EMAIL,
  CUSTOMER_PASSWORD,
  activatedCustomer,
  closeStaffContext,
  fillRegistrationAddress,
  freshAddress,
  register,
  signIn,
  staffContext,
  verify,
} from './accountHelpers.js';
import { messageCountFor, resetLinkFor } from './mailCapture.js';

// Reworded in UAT round 9 ("Address", "the same as the address above"), which also made
// the address required; the cases below fill it.
const SAME = 'Billing address is the same as the address above';
const ADDRESS = 'Address';

function group(page, name) {
  return page.getByRole('group', { name, exact: true });
}

test.describe('Registration (UAT round 8)', () => {
  test('shipping comes first, and the billing box hides billing while ticked', async ({ page }) => {
    const email = freshAddress('r8-billing');
    await page.goto('/account/register');

    await expect(group(page, ADDRESS)).toBeVisible();
    await expect(group(page, 'Billing address')).toBeVisible();
    const shippingTop = (await group(page, ADDRESS).boundingBox()).y;
    const billingTop = (await group(page, 'Billing address').boundingBox()).y;
    expect(shippingTop).toBeLessThan(billingTop);

    await page.getByLabel('Email address', { exact: true }).fill(email);
    await page.getByLabel('Password', { exact: true }).fill(CUSTOMER_PASSWORD);
    await page.getByLabel('Confirm password', { exact: true }).fill(CUSTOMER_PASSWORD);
    await page.getByLabel('Full legal name', { exact: true }).fill(`E2E ${email.split('@')[0]}`);

    // Round 8 ticked the box once a street was typed; since round 11 it starts ticked.
    const box = page.getByLabel(SAME);
    await expect(box).toBeChecked();
    await group(page, ADDRESS).getByLabel(/^Address line 1/).fill('4120 Dixie Road');
    await group(page, ADDRESS).getByLabel(/^City/).fill('Mississauga');
    await group(page, ADDRESS).getByLabel(/^Province or state/).fill('ON');
    await group(page, ADDRESS).getByLabel(/^Postal code/).fill('L4W 1V2');
    await expect(box).toBeChecked();
    await expect(group(page, 'Billing address').getByLabel(/^Address line 1/)).toHaveCount(0);

    // Unticking shows empty billing fields; ticking again hides them.
    await box.uncheck();
    const billingLine1 = group(page, 'Billing address').getByLabel('Address line 1', { exact: true });
    await expect(billingLine1).toBeVisible();
    await expect(billingLine1).toHaveValue('');
    await box.check();
    await expect(group(page, 'Billing address').getByLabel(/^Address line 1/)).toHaveCount(0);

    await page.getByLabel(/I accept the Solaris Express terms/).check();
    const sent = page.waitForRequest(
      (request) => request.url().endsWith('/api/v1/account/register') && request.method() === 'POST',
    );
    await page.getByRole('button', { name: 'Create account' }).click();
    const body = (await sent).postDataJSON();
    expect(body.billing_same_as_shipping).toBe(true);
    expect(Object.keys(body.customer).some((key) => key.startsWith('billing_address.'))).toBe(false);
    await expect(page.getByRole('heading', { name: 'Check your email', level: 1 })).toBeVisible();
  });

  test('a different confirmation is an inline error and nothing is sent', async ({ page }) => {
    const email = freshAddress('r8-confirm');
    await page.goto('/account/register');
    await page.getByLabel('Email address', { exact: true }).fill(email);
    await page.getByLabel('Password', { exact: true }).fill(CUSTOMER_PASSWORD);
    await page.getByLabel('Confirm password', { exact: true }).fill(`${CUSTOMER_PASSWORD}-typo`);
    await page.getByLabel('Full legal name', { exact: true }).fill(`E2E ${email.split('@')[0]}`);
    await fillRegistrationAddress(page);
    await page.getByLabel(/I accept the Solaris Express terms/).check();
    await page.getByRole('button', { name: 'Create account' }).click();

    const confirm = page.getByLabel('Confirm password', { exact: true });
    await expect(confirm).toHaveAttribute('aria-invalid', 'true');
    await expect(confirm).toHaveAccessibleDescription(/The two passwords do not match\./);
    expect(messageCountFor(email)).toBe(0);

    await confirm.fill(CUSTOMER_PASSWORD);
    await page.getByRole('button', { name: 'Create account' }).click();
    await expect(page.getByRole('heading', { name: 'Check your email', level: 1 })).toBeVisible();
  });

  test('reset password shows a mismatch beside the second box, then works', async ({ page }) => {
    const email = freshAddress('r8-reset');
    await register(page, email);
    await verify(page, email);
    await page.goto('/account/forgot-password');
    await page.getByLabel('Email address', { exact: true }).fill(email);
    await page.getByRole('button', { name: 'Send the reset link' }).click();
    await expect(page.getByRole('heading', { name: 'Check your email', level: 1 })).toBeVisible();

    await page.goto(await resetLinkFor(email));
    const replacement = 'a-replacement-passphrase-2026';
    await page.getByLabel('New password', { exact: true }).fill(replacement);
    await page.getByLabel('New password again', { exact: true }).fill('not-the-same-passphrase-2026');
    await page.getByRole('button', { name: 'Change password' }).click();
    const again = page.getByLabel('New password again', { exact: true });
    await expect(again).toHaveAttribute('aria-invalid', 'true');
    await expect(again).toHaveAccessibleDescription(/The two passwords do not match\./);

    await again.fill(replacement);
    await page.getByRole('button', { name: 'Change password' }).click();
    await expect(page.getByRole('heading', { name: 'Password updated', level: 1 })).toBeVisible();
  });
});

async function auditRows(browser, filterText) {
  const { context, page } = await staffContext(browser, ADMIN_EMAIL);
  await page.goto('/settings');
  await page.getByRole('tab', { name: 'Audit access' }).click();
  const table = page.getByRole('table', { name: 'Audit access' });
  await expect(table).toBeVisible();
  return { context, page, rows: table.getByRole('row').filter({ hasText: filterText }) };
}

test.describe('Staff side (UAT round 8)', () => {
  test('an approved change request is not drift, and the audit shows old and new', async ({
    page,
    browser,
  }) => {
    const { email, accountReference } = await activatedCustomer(page, browser, {
      label: 'r8-approve',
    });
    await signIn(page, email);
    await page.goto('/account/profile');
    await page.getByLabel(/^Name you prefer to be called/).fill('Round Eight Tester');
    await page.getByRole('button', { name: 'Send for review' }).click();
    await expect(page.getByText('Waiting for review', { exact: true })).toBeVisible();

    const ops = await staffContext(browser);
    try {
      await ops.page.goto('/customer-accounts');
      await ops.page
        .getByRole('table', { name: 'Profile change requests' })
        .getByRole('link', { name: accountReference })
        .click();
      await ops.page.getByRole('radio', { name: 'Approve' }).first().check();
      await ops.page.getByRole('button', { name: 'Record decision' }).click();
      await expect(ops.page.getByText('This change request has been decided')).toBeVisible();
      await expect(ops.page.getByText('Applied', { exact: true })).toBeVisible();
      // The value now on file is the one just approved, so it is not "changed since".
      await expect(ops.page.getByText('Changed since')).toHaveCount(0);
      await ops.page.reload();
      await expect(ops.page.getByText('Applied', { exact: true })).toBeVisible();
      await expect(ops.page.getByText('Changed since')).toHaveCount(0);
    } finally {
      await closeStaffContext(ops);
    }

    const admin = await auditRows(browser, 'from an approved change request');
    try {
      const row = admin.rows.first();
      await expect(row).toContainText('Changes');
      await expect(row).toContainText('display_name: (blank) → Round Eight Tester');
      await expect(row).not.toContainText(/Fields changed\s*contact/);
    } finally {
      await closeStaffContext(admin);
    }
  });

  test('a marketing withdrawal names the customer account as the actor', async ({
    page,
    browser,
  }) => {
    const { email, accountReference } = await activatedCustomer(page, browser, {
      label: 'r8-consent',
    });
    const actor = `customer_account:${accountReference}`;
    await signIn(page, email);
    await page.goto('/account/profile');
    const marketing = page.locator('.ca-card', {
      has: page.getByRole('heading', { name: 'Marketing messages' }),
    });
    await marketing.getByRole('button', { name: 'Yes, send me marketing messages' }).click();
    await expect(marketing.getByText('You have agreed to receive marketing messages.')).toBeVisible();
    await marketing.getByRole('button', { name: 'Stop marketing messages' }).click();
    await expect(
      marketing.getByText('You have chosen not to receive marketing messages.'),
    ).toBeVisible();

    const admin = await auditRows(browser, 'Customer recorded marketing consent: withdrawn');
    try {
      const row = admin.rows.first();
      await expect(row).toContainText(actor);
      await expect(row).not.toContainText(/\bsystem\b/);

      // The consent history on the customer record says the same.
      const lookup = await admin.page.request.get('/api/v1/customers', {
        params: { search: email, limit: 5 },
      });
      expect(lookup.ok()).toBe(true);
      const customerId = (await lookup.json()).items[0].id;
      await admin.page.goto(`/customers/${customerId}`);
      await admin.page.getByRole('tab', { name: 'Consent' }).click();
      const history = admin.page.getByRole('table', { name: 'Consent history' });
      const withdrawn = history.getByRole('row').filter({ hasText: 'Withdrawn' }).first();
      await expect(withdrawn.getByRole('cell').last()).toHaveText(actor);
    } finally {
      await closeStaffContext(admin);
    }
  });
});
