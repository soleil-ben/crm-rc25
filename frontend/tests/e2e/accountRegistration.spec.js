/**
 * Registration, verification and the pending state, in a browser.
 *
 * Workflows 1, 2, 3 and 19 of the Phase 12 instruction. Every address is minted per run;
 * no fixture contains one, and no test prints a token.
 */

import { expect, test } from './diagnostics.js';
import {
  CUSTOMER_PASSWORD,
  fillRegistrationAddress,
  freshAddress,
  register,
  signIn,
  verify,
} from './accountHelpers.js';
import { TEMPLATE, messageCountFor, waitForMessage } from './mailCapture.js';

test.describe('registration', () => {
  test('a new account registers, verifies, and waits for approval', async ({ page }) => {
    const email = freshAddress('journey');

    await register(page, email);

    // The confirmation says the same thing for every outcome. Nothing on it names the
    // address, says an account was created, or reports a match.
    const confirmation = await page.locator('main').innerText();
    expect(confirmation).toContain('If that address can be used, we have sent a message to it.');
    expect(confirmation).not.toContain(email);
    expect(confirmation).not.toMatch(/already|duplicate|STCA-/i);

    // Exactly one verification message, and no "somebody tried to register" notice: this
    // address was new.
    expect(messageCountFor(email, { templateKey: TEMPLATE.VERIFY_EMAIL })).toBe(1);
    expect(messageCountFor(email, { templateKey: TEMPLATE.REGISTRATION_ATTEMPT_NOTICE })).toBe(0);

    await verify(page, email);
    // Confirming an address is not approval, and the page says so.
    await expect(page.getByText(/This is not approval/)).toBeVisible();

    await signIn(page, email);
    await expect(
      page.getByRole('heading', { name: 'Your account is being reviewed', level: 1 }),
    ).toBeVisible();

    // A pending account reaches no shipment data, and there is no navigation offering it.
    await expect(page.getByRole('link', { name: 'My shipments' })).toHaveCount(0);
    expect(await page.locator('main').innerText()).not.toContain('SX-');

    // Typing the URL does not help: the guard sends them back.
    await page.goto('/account/shipments');
    await expect(
      page.getByRole('heading', { name: 'Your account is being reviewed', level: 1 }),
    ).toBeVisible();
    expect(new URL(page.url()).pathname).toBe('/account/pending');
  });

  test('registering an address that already has an account looks identical', async ({ page }) => {
    const email = freshAddress('twice');
    await register(page, email);
    const first = await page.locator('main').innerText();

    await register(page, email);
    const second = await page.locator('main').innerText();

    // Word for word. A single differing sentence would be the enumeration oracle.
    expect(second).toBe(first);

    // And no second verification message: the attempt notice goes to the existing
    // address instead, at most one per window.
    expect(messageCountFor(email, { templateKey: TEMPLATE.VERIFY_EMAIL })).toBe(1);
  });

  test('a resend invalidates the previous link, and says so before it happens', async ({
    page,
  }) => {
    const email = freshAddress('resend');
    await register(page, email);
    const firstMessage = await waitForMessage(email, { templateKey: TEMPLATE.VERIFY_EMAIL });

    await page.goto('/account/verification/resend');
    await expect(page.getByText('A new link cancels the old one.')).toBeVisible();
    await page.getByLabel('Email address', { exact: true }).fill(email);
    await page.getByRole('button', { name: 'Send it again' }).click();
    await expect(page.getByRole('heading', { name: 'Check your email', level: 1 })).toBeVisible();

    await expect
      .poll(() => messageCountFor(email, { templateKey: TEMPLATE.VERIFY_EMAIL }))
      .toBe(2);

    // The first link now fails, with the one generic sentence.
    const { accountLinkFrom } = await import('./mailCapture.js');
    await page.goto(accountLinkFrom(firstMessage));
    await expect(
      page.getByRole('heading', { name: 'That link did not work', level: 1 }),
    ).toBeVisible();
    await expect(page.getByText('That link is no longer valid. Request a new one.')).toBeVisible();
  });

  test('a consumed verification link fails the same way a made-up one does', async ({ page }) => {
    const email = freshAddress('replay');
    await register(page, email);
    const { accountLinkFrom } = await import('./mailCapture.js');
    const link = accountLinkFrom(
      await waitForMessage(email, { templateKey: TEMPLATE.VERIFY_EMAIL }),
    );

    await page.goto(link);
    await expect(page.getByRole('heading', { name: 'Email confirmed', level: 1 })).toBeVisible();

    // Each outcome is read **after** it has settled. Reading straight after `goto`
    // captures "Confirming your email address", which is the loading state and is the
    // same on both paths for an uninteresting reason.
    await page.goto(link);
    await expect(
      page.getByRole('heading', { name: 'That link did not work', level: 1 }),
    ).toBeVisible();
    const replayed = await page.locator('main').innerText();

    await page.goto('/account/verify-email?token=this-token-was-never-issued');
    await expect(
      page.getByRole('heading', { name: 'That link did not work', level: 1 }),
    ).toBeVisible();
    const invented = await page.locator('main').innerText();

    expect(replayed).toBe(invented);
  });

  test('neither consent control is pre-checked, and they are separate', async ({ page }) => {
    await page.goto('/account/register');
    const terms = page.getByLabel(/I accept the Solaris Express terms/);
    const marketing = page.getByLabel(/may email me about services/);

    await expect(terms).not.toBeChecked();
    await expect(marketing).not.toBeChecked();

    await terms.check();
    await expect(marketing).not.toBeChecked();
  });

  test('the form says approval is required before shipments are visible', async ({ page }) => {
    await page.goto('/account/register');
    await expect(page.getByText(/A member of staff reviews every application/)).toBeVisible();
  });

  test('registration is refused without the terms acknowledgement', async ({ page }) => {
    const email = freshAddress('noterms');
    await page.goto('/account/register');
    await page.getByLabel('Email address', { exact: true }).fill(email);
    await page.getByLabel('Password', { exact: true }).fill(CUSTOMER_PASSWORD);
    await page.getByLabel('Confirm password', { exact: true }).fill(CUSTOMER_PASSWORD);
    await page.getByLabel('Full legal name', { exact: true }).fill(`E2E ${email.split('@')[0]}`);
    // The address is required too (UAT round 9); filled so the terms are the one problem.
    await fillRegistrationAddress(page);
    await page.getByRole('button', { name: 'Create account' }).click();

    // The summary is the first alert on the page; the inline message beside the
    // control is the second, and both are wanted.
    await expect(page.getByRole('alert').first()).toContainText('problem with this form');
    // Nothing was sent, so nothing was captured.
    expect(messageCountFor(email)).toBe(0);
  });

  test('the password field takes a pasted value', async ({ page }) => {
    // Password managers paste. A page that blocks paste pushes people toward short
    // memorable passwords, which is the opposite of the intent.
    await page.goto('/account/register');
    const field = page.getByLabel('Password', { exact: true });
    await field.focus();
    await page.evaluate(async (value) => {
      await navigator.clipboard.writeText(value);
    }, CUSTOMER_PASSWORD).catch(() => {});
    await field.fill(CUSTOMER_PASSWORD);
    await expect(field).toHaveValue(CUSTOMER_PASSWORD);
  });
});

test.describe('the production registration gate', () => {
  /**
   * Workflow 19.
   *
   * The E2E backend runs with the capture transport, so the real 503 cannot be produced
   * without reconfiguring the run — and a run that could be reconfigured mid-suite is a
   * run whose other assertions mean less. The gate's *response* is asserted by
   * `backend/tests/test_uat_production_refusals.py`; what is asserted here is the
   * **screen**: given that response, what does a stranger see?
   */
  test('shows a plain sentence and names no configuration', async ({ page }) => {
    await page.route('**/api/v1/account/register', (route) =>
      route.fulfill({
        status: 503,
        contentType: 'application/json',
        body: JSON.stringify({
          code: 'account_unavailable',
          message: 'Customer accounts are not available yet. Please contact Solaris Express.',
          field: null,
        }),
      }),
    );

    const email = freshAddress('gated');
    await page.goto('/account/register');
    await page.getByLabel('Email address', { exact: true }).fill(email);
    await page.getByLabel('Password', { exact: true }).fill(CUSTOMER_PASSWORD);
    await page.getByLabel('Confirm password', { exact: true }).fill(CUSTOMER_PASSWORD);
    await page.getByLabel('Full legal name', { exact: true }).fill(`E2E ${email.split('@')[0]}`);
    await fillRegistrationAddress(page);
    await page.getByLabel(/I accept the Solaris Express terms/).check();
    await page.getByRole('button', { name: 'Create account' }).click();

    await expect(
      page.getByRole('heading', { name: 'Accounts are not open yet', level: 1 }),
    ).toBeVisible();

    const body = await page.locator('main').innerText();
    for (const secret of [
      'ACCOUNT_EMAIL_TRANSPORT',
      'PLACEHOLDER',
      'provider',
      'SMTP',
      'capture',
      'terms_version',
      'OD-34',
      'OD-37',
    ]) {
      expect(body).not.toContain(secret);
    }
    // It offers the thing that does work.
    // Scoped to the main region: the footer carries the same link on every screen.
    await expect(
      page.locator('main').getByRole('link', { name: 'public tracking' }),
    ).toBeVisible();
  });
});
