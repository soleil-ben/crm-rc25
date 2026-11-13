/**
 * Sign in once for the whole staff end-to-end suite.
 *
 * Login is rate limited (eight attempts in five minutes, by client address), and every
 * test here arrives from the same loopback address. Signing in inside each spec would
 * consume that allowance and produce failures that look like authentication bugs. A
 * setup project runs first, signs in through the real form, and saves the resulting
 * cookies for the staff project to reuse.
 *
 * The session cookie is HTTP-only and the CSRF cookie is readable — both are captured by
 * `storageState`, which is what lets the saved state perform state-changing requests the
 * same way the browser does.
 */

import { expect, test as setup } from './diagnostics.js';

export const STAFF_STATE = 'tests/e2e/.auth/staff.json';

const EMAIL = process.env.E2E_STAFF_EMAIL || 'admin@demo.example.com';
const PASSWORD = process.env.E2E_STAFF_PASSWORD || 'SolarisDemo!2026';

setup('sign in as an administrator', async ({ page }) => {
  await page.goto('/');

  await page.getByLabel('Email address').fill(EMAIL);
  await page.getByLabel('Password').fill(PASSWORD);
  await page.getByRole('button', { name: 'Sign in' }).click();

  // The dashboard greeting is the first thing that proves the session resolved, rather
  // than a URL change that would also happen on a failed redirect.
  await expect(page.getByRole('heading', { name: /Good (morning|afternoon|evening)/ })).toBeVisible(
    { timeout: 15_000 },
  );

  await page.context().storageState({ path: STAFF_STATE });
});
