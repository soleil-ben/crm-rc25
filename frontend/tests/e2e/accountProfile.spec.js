/**
 * My profile, in a real browser (fix pack 2; CA-PRF-01 … CA-PRF-04).
 *
 * One journey per case the UAT round 2 run found blocked: a direct language change, a
 * change request that a staff member approves in part, and a marketing choice. Every
 * account is created fresh through the screens, so nothing depends on seed state.
 */

import { expect, test } from './diagnostics.js';
import { auditAndAssert } from './axeHelpers.js';
import {
  activatedCustomer,
  closeStaffContext,
  signIn,
  staffContext,
} from './accountHelpers.js';

/** One account card, found by its heading. */
function card(page, title) {
  return page.locator('.ca-card', { has: page.getByRole('heading', { name: title }) });
}

test.describe('My profile', () => {
  test('preferred language applies at once, and the screens follow it on the next visit', async ({
    page,
    browser,
  }) => {
    const { email } = await activatedCustomer(page, browser, { label: 'prf-lang' });
    await signIn(page, email);
    await page.getByRole('link', { name: 'My profile' }).click();
    await expect(page.getByRole('heading', { name: 'My profile', level: 1 })).toBeVisible();
    await expect(
      page.getByText('use the switch at the top of the page', { exact: false }),
    ).toBeVisible();

    await page.getByLabel(/Contact me in/).selectOption('vi');
    await page.getByRole('button', { name: 'Save language' }).click();
    await expect(page.getByText('Your preferred language is saved.')).toBeVisible();
    // Saving does not flip the screen under the person (OD-71).
    await expect(page.locator('html')).toHaveAttribute('lang', 'en');

    // Reloaded from the server, not from the form: the screens now follow the preference.
    await page.reload();
    await expect(page.locator('html')).toHaveAttribute('lang', 'vi');
    await expect(page.getByRole('heading', { name: 'Hồ sơ của tôi', level: 1 })).toBeVisible();
    await expect(page.getByLabel(/Liên lạc với tôi bằng/)).toHaveValue('vi');

    // And the header switch still wins for this page view.
    await page.getByRole('button', { name: 'English' }).click();
    await expect(page.locator('html')).toHaveAttribute('lang', 'en');
    await expect(page.getByLabel(/Contact me in/)).toHaveValue('vi');
  });

  test('a change request changes nothing until staff approve it, field by field', async ({
    page,
    browser,
  }) => {
    const { email, accountReference } = await activatedCustomer(page, browser, {
      label: 'prf-prop',
    });
    await signIn(page, email);
    await page.goto('/account/profile');
    await expect(page.getByRole('heading', { name: 'My profile', level: 1 })).toBeVisible();

    await page.getByLabel(/^Name you prefer to be called/).fill('Profile Tester');
    await page.getByLabel(/^Street address/).fill('88 Queen Street East');
    await page.getByLabel(/^City/).fill('Toronto');
    await page.getByLabel(/^Country code/).fill('CA');
    await page.getByRole('button', { name: 'Send for review' }).click();
    await expect(page.getByText(/A member of staff will review this change/)).toBeVisible();
    await expect(page.getByText('Waiting for review', { exact: true })).toBeVisible();
    // Still the value on file.
    const onFile = card(page, 'What we have on file');
    await expect(page.getByText('Profile Tester').first()).toBeVisible();
    await expect(onFile.getByText('Profile Tester')).toHaveCount(0);

    const { context, page: staffPage } = await staffContext(browser);
    try {
      await staffPage.goto('/customer-accounts');
      await staffPage
        .getByRole('table', { name: 'Profile change requests' })
        .getByRole('link', { name: accountReference })
        .click();
      await expect(staffPage.getByRole('table', { name: 'Preferred name' })).toBeVisible();
      await staffPage.getByRole('radio', { name: 'Approve' }).first().check();
      await staffPage.getByRole('radio', { name: 'Decline' }).nth(1).check();
      await staffPage.getByLabel('Reason for the declined changes').selectOption('could_not_verify');
      await staffPage.getByRole('button', { name: 'Record decision' }).click();
      await expect(staffPage.getByText('This change request has been decided')).toBeVisible();
    } finally {
      await closeStaffContext({ context, page: staffPage });
    }

    await page.reload();
    await expect(page.getByText('Reviewed', { exact: true })).toBeVisible();
    await expect(page.getByText(/Preferred name: Profile Tester — changed/)).toBeVisible();
    await expect(page.getByText(/Pickup address: city: Toronto — not changed/)).toBeVisible();
  });

  test('marketing consent is an explicit choice that can be withdrawn', async ({
    page,
    browser,
  }) => {
    const { email } = await activatedCustomer(page, browser, { label: 'prf-mkt' });
    await signIn(page, email);
    await page.goto('/account/profile');
    const marketing = card(page, 'Marketing messages');

    await marketing.getByRole('button', { name: 'Yes, send me marketing messages' }).click();
    await expect(
      marketing.getByText('You have agreed to receive marketing messages.'),
    ).toBeVisible();
    await marketing.getByRole('button', { name: 'Stop marketing messages' }).click();
    await expect(
      marketing.getByText('You have chosen not to receive marketing messages.'),
    ).toBeVisible();
    expect((await page.locator('body').innerText()).toLowerCase()).not.toContain('suppress');
  });

  test('the profile screen passes the accessibility audit', async ({ page, browser }, testInfo) => {
    const { email } = await activatedCustomer(page, browser, { label: 'prf-axe' });
    await signIn(page, email);
    await page.goto('/account/profile');
    await expect(page.getByRole('heading', { name: 'My profile', level: 1 })).toBeVisible();
    await auditAndAssert(page, 'account-profile', testInfo);
  });
});
