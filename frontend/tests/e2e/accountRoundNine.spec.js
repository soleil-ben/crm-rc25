/**
 * UAT round 9 in a real browser (the owner's decisions of 2026-10-18).
 *
 * 1. The first registration section is "Address", and the billing box reads "Billing
 *    address is the same as the address above".
 * 2. The address's country, line 1, city, province or state and postal code are required,
 *    each with an inline error, and nothing is sent until they are filled.
 * 3. The driver note reads "Notes for driver (buzz code, contact concierge, security,...)".
 * 4. With the billing box unticked, the same five billing parts are required.
 * 5. A customer's sign-in and sign-out name their account as the actor in Audit access.
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
  signIn,
  staffContext,
} from './accountHelpers.js';
import { messageCountFor } from './mailCapture.js';

const SAME = 'Billing address is the same as the address above';
const DRIVER_NOTE = 'Notes for driver (buzz code, contact concierge, security,...)';
// The postal code was a fifth required part until UAT round 11 made it optional.
const REQUIRED = ['Country', 'Address line 1', 'City', 'Province or state'];

function group(page, name) {
  return page.getByRole('group', { name, exact: true });
}

async function fillAccountDetails(page, email) {
  await page.goto('/account/register');
  await page.getByLabel('Email address', { exact: true }).fill(email);
  await page.getByLabel('Password', { exact: true }).fill(CUSTOMER_PASSWORD);
  await page.getByLabel('Confirm password', { exact: true }).fill(CUSTOMER_PASSWORD);
  await page.getByLabel('Full legal name', { exact: true }).fill(`E2E ${email.split('@')[0]}`);
  await page.getByLabel(/I accept the Solaris Express terms/).check();
}

test.describe('Registration (UAT round 9)', () => {
  test('the wording: Address, the address above, and the driver note', async ({ page }) => {
    await page.goto('/account/register');
    await expect(group(page, 'Address')).toBeVisible();
    await expect(page.getByRole('group', { name: 'Shipping address' })).toHaveCount(0);
    await expect(page.getByText(/shipping address/i)).toHaveCount(0);
    await expect(page.getByLabel(SAME)).toBeVisible();
    await expect(group(page, 'Address').getByLabel(DRIVER_NOTE, { exact: true })).toBeVisible();
    await expect(page.getByText('Anything the driver should know')).toHaveCount(0);
  });

  test('the address parts are required, inline, and nothing is sent', async ({ page }) => {
    const email = freshAddress('r9-address');
    await fillAccountDetails(page, email);
    const address = group(page, 'Address');
    // RC-UAT-25 item 1: required is an asterisk and aria-required, not "(required)".
    for (const label of REQUIRED) {
      await expect(address.getByLabel(label, { exact: true })).toHaveAttribute('aria-required', 'true');
    }
    await expect(address.getByLabel('Address line 2', { exact: true })).toBeVisible();
    await expect(address.getByLabel('Postal code', { exact: true })).toBeVisible();

    // The box starts ticked (round 11), so only the address is in question.
    await expect(page.getByLabel(SAME)).toBeChecked();
    await page.getByRole('button', { name: 'Create account' }).click();
    for (const [label, message] of [
      ['Address line 1', /Enter the street address \(address line 1\)\./],
      ['City', /Enter the city\./],
      ['Province or state', /Enter the province or state\./],
    ]) {
      const field = address.getByLabel(label, { exact: true });
      await expect(field).toHaveAttribute('aria-invalid', 'true');
      await expect(field).toHaveAccessibleDescription(message);
    }
    expect(messageCountFor(email)).toBe(0);

    // The summary links to the field.
    await page.getByRole('alert').first().getByRole('link', { name: 'Enter the city.' }).click();
    await expect(address.getByLabel('City', { exact: true })).toBeFocused();

    await fillRegistrationAddress(page);
    const sent = page.waitForRequest(
      (request) => request.url().endsWith('/api/v1/account/register') && request.method() === 'POST',
    );
    await page.getByRole('button', { name: 'Create account' }).click();
    const body = (await sent).postDataJSON();
    expect(body.customer['pickup_address.1.province_state']).toBe('ON');
    expect(body.customer['pickup_address.1.postal_code']).toBe('L4W 1V2');
    await expect(page.getByRole('heading', { name: 'Check your email', level: 1 })).toBeVisible();
  });

  test('unticked, the billing parts are required, then sent', async ({ page }) => {
    const email = freshAddress('r9-billing');
    await fillAccountDetails(page, email);
    await fillRegistrationAddress(page);
    const box = page.getByLabel(SAME);
    await expect(box).toBeChecked();
    await box.uncheck();

    const billing = group(page, 'Billing address');
    for (const label of REQUIRED) {
      await expect(billing.getByLabel(label, { exact: true })).toHaveAttribute('aria-required', 'true');
    }
    await page.getByRole('button', { name: 'Create account' }).click();
    for (const [label, message] of [
      ['Address line 1', /Enter the billing street address/],
      ['City', /Enter the billing city\./],
      ['Province or state', /Enter the billing province or state\./],
    ]) {
      await expect(billing.getByLabel(label, { exact: true })).toHaveAccessibleDescription(message);
    }
    expect(messageCountFor(email)).toBe(0);

    await billing.getByLabel('Country', { exact: true }).selectOption('VN');
    await billing.getByLabel('Address line 1', { exact: true }).fill('125 Nguyen Hue');
    await billing.getByLabel('City', { exact: true }).fill('Ho Chi Minh City');
    await billing.getByLabel('Province or state', { exact: true }).fill('Ho Chi Minh');
    await billing.getByLabel('Postal code', { exact: true }).fill('700000');
    const sent = page.waitForRequest(
      (request) => request.url().endsWith('/api/v1/account/register') && request.method() === 'POST',
    );
    await page.getByRole('button', { name: 'Create account' }).click();
    const body = (await sent).postDataJSON();
    expect(body.billing_same_as_shipping).toBe(false);
    expect(body.customer['billing_address.country_code']).toBe('VN');
    expect(body.customer['billing_address.postal_code']).toBe('700000');
    await expect(page.getByRole('heading', { name: 'Check your email', level: 1 })).toBeVisible();
  });
});

test.describe('Audit (UAT round 9)', () => {
  test('sign-in and sign-out name the customer account as the actor', async ({
    page,
    browser,
  }) => {
    const { email, accountReference } = await activatedCustomer(page, browser, {
      label: 'r9-signin',
    });
    const actor = `customer_account:${accountReference}`;
    await signIn(page, email);
    const signedOut = page.waitForResponse(
      (response) =>
        response.url().endsWith('/api/v1/account/sign-out') && response.request().method() === 'POST',
    );
    await page.getByRole('button', { name: 'Sign out' }).click();
    expect((await signedOut).ok()).toBe(true);

    const admin = await staffContext(browser, ADMIN_EMAIL);
    try {
      await admin.page.goto('/settings');
      await admin.page.getByRole('tab', { name: 'Audit access' }).click();
      const table = admin.page.getByRole('table', { name: 'Audit access' });
      await expect(table).toBeVisible();
      for (const summary of ['Customer signed in', 'Customer signed out']) {
        const rows = table.getByRole('row').filter({ hasText: summary });
        await expect(rows.filter({ hasText: actor }).first()).toBeVisible();
        // No customer sign-in or sign-out in this run is attributed to "system".
        await expect(rows.filter({ hasText: /\bsystem\b/ })).toHaveCount(0);
      }
    } finally {
      await closeStaffContext(admin);
    }
  });
});
