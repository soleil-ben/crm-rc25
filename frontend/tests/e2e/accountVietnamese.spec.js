/**
 * The Customer Account in Vietnamese (OD-71: Vietnamese first, English as an option).
 *
 * The run's dev server starts the account in English (`VITE_ACCOUNT_DEFAULT_LOCALE=en`, set
 * by `scripts/run_e2e.mjs`) so the other account specs can assert the English copy. This
 * spec takes the path a customer takes instead: the header switch. It needs no account and
 * no backend route beyond `/account/me`, which answers 401 for a stranger.
 *
 * The axe audit runs on the Vietnamese page because the Vietnamese strings are longer and
 * carry a different `lang`; a page that passed in English has not been shown to pass here.
 */

import { expect, test } from './diagnostics.js';
import { auditAndAssert, settle } from './axeHelpers.js';

test.describe('the Customer Account in Vietnamese', () => {
  test('sign in switches to Tiếng Việt and passes the accessibility audit', async ({
    page,
  }, testInfo) => {
    await page.goto('/account/sign-in');
    await expect(page.getByRole('heading', { name: 'Sign in', level: 1 })).toBeVisible();

    await page.getByRole('button', { name: 'Tiếng Việt' }).click();

    await expect(page.locator('html')).toHaveAttribute('lang', 'vi');
    await expect(page.getByRole('heading', { name: 'Đăng nhập', level: 1 })).toBeVisible();
    await expect(page.getByLabel('Địa chỉ email', { exact: true })).toBeVisible();
    await expect(page.getByLabel('Mật khẩu', { exact: true })).toBeVisible();
    await expect(page.getByRole('link', { name: 'Quên mật khẩu?' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Tiếng Việt' })).toHaveAttribute(
      'aria-pressed',
      'true',
    );
    await expect(page).toHaveTitle('Tài khoản khách hàng — Solaris Express');

    // Nothing about the choice is written to the browser.
    const stored = await page.evaluate(() => ({
      local: window.localStorage.length,
      session: window.sessionStorage.length,
    }));
    expect(stored).toEqual({ local: 0, session: 0 });

    await settle(page);
    await auditAndAssert(page, 'account-sign-in-vi', testInfo);
  });

  test('the choice survives navigation inside the account', async ({ page }) => {
    await page.goto('/account/sign-in');
    await page.getByRole('button', { name: 'Tiếng Việt' }).click();
    await page.getByRole('link', { name: 'Tạo tài khoản' }).click();
    await expect(page.getByRole('heading', { name: 'Tạo tài khoản', level: 1 })).toBeVisible();
    await expect(page.locator('html')).toHaveAttribute('lang', 'vi');
  });
});
