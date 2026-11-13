/**
 * UAT-AD-01, in a real browser: after a staff member signs out, the Back button must not
 * show customer data, and nothing the staff portal served may come back from a cache.
 *
 * This spec signs in on its **own** context rather than using the shared staff storage
 * state, because signing out revokes the session server-side and every later staff spec
 * would otherwise find itself signed out. The E2E login allowance (`scripts/e2e_env.py`,
 * `LOGIN_RATE_LIMIT_ATTEMPTS=100`) makes one more form sign-in free.
 */

import { expect, test } from './diagnostics.js';
import { OPERATIONS_EMAIL, signInStaff } from './accountHelpers.js';

test.describe('Staff sign-out and the cache', () => {
  test('the document and the API answers are served uncacheable', async ({ request }) => {
    const document = await request.get('/', { headers: { Accept: 'text/html' } });
    expect(document.status()).toBe(200);
    expect(document.headers()['cache-control']).toContain('no-store');

    // The staff project's `request` carries the shared signed-in state, so this is the
    // signed-in answer -- the one with a person's name in it -- and it must be uncacheable.
    // An anonymous 401 carries the same headers; either way the assertion is the headers.
    const me = await request.get('/api/v1/auth/me');
    expect([200, 401]).toContain(me.status());
    expect(me.headers()['cache-control']).toBe('no-store');
    expect(me.headers()['pragma']).toBe('no-cache');

    const customers = await request.get('/api/v1/customers?limit=1');
    expect([200, 401]).toContain(customers.status());
    expect(customers.headers()['cache-control']).toBe('no-store');
    expect(customers.headers()['pragma']).toBe('no-cache');
  });

  test('Back after sign-out shows the sign-in screen and no customer names', async ({
    browser,
  }) => {
    const context = await browser.newContext({ storageState: { cookies: [], origins: [] } });
    const page = await context.newPage();
    try {
      await signInStaff(page, OPERATIONS_EMAIL);

      // A screen full of customer names, so there is something a cache could leak.
      await page.goto('/customers');
      const table = page.getByRole('table', { name: 'Customers' });
      await expect(table).toBeVisible();
      const firstName = (await table.locator('tbody tr').first().locator('td').nth(1).innerText())
        .split('\n')[0]
        .trim();
      expect(firstName.length).toBeGreaterThan(0);

      // Sign out from the account menu, as the case says.
      await page.getByRole('button', { name: 'Account menu' }).click();
      await page.getByRole('menuitem', { name: 'Sign out' }).click();
      await expect(page.getByRole('heading', { name: 'Sign in to the Solaris CRM' })).toBeVisible();
      expect(new URL(page.url()).pathname).toBe('/');

      // Back. Whatever the browser restores, the person is asked to sign in again and
      // the name that was on screen a moment ago is not.
      await page.goBack();
      await expect(page.getByRole('heading', { name: 'Sign in to the Solaris CRM' })).toBeVisible();
      await expect(page.getByRole('table', { name: 'Customers' })).toHaveCount(0);
      expect(await page.locator('body').innerText()).not.toContain(firstName);

      // And the server agrees: the session is gone, not merely the cookie.
      const me = await page.request.get('/api/v1/auth/me');
      expect(me.status()).toBe(401);
    } finally {
      await context.close();
    }
  });

  test('signing in lands on the dashboard, not on the previous person’s last page', async ({
    browser,
  }) => {
    const context = await browser.newContext({ storageState: { cookies: [], origins: [] } });
    const page = await context.newPage();
    try {
      // The browser was left on a customer record.
      await page.goto('/customers?lifecycle_status=active');
      await expect(page.getByRole('heading', { name: 'Sign in to the Solaris CRM' })).toBeVisible();

      await page.getByLabel('Email address').fill(OPERATIONS_EMAIL);
      await page.getByLabel('Password').fill(process.env.E2E_STAFF_PASSWORD || 'SolarisDemo!2026');
      await page.getByRole('button', { name: 'Sign in' }).click();

      await expect(
        page.getByRole('heading', { name: /Good (morning|afternoon|evening)/ }),
      ).toBeVisible({ timeout: 15_000 });
      expect(new URL(page.url()).pathname).toBe('/');
      expect(new URL(page.url()).search).toBe('');
    } finally {
      await context.close();
    }
  });
});
