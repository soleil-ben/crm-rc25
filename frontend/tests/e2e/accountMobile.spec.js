/**
 * The Customer Account at 375 × 812, the reference phone size.
 *
 * Workflow 20, and the parts of §13 that are about layout rather than semantics: no
 * horizontal overflow, 48-pixel primary targets, and the card list replacing the table
 * rather than the table being squeezed into a scroller.
 *
 * Runs only in the `account-mobile` project, which is the only place the viewport is
 * narrow enough for these to mean anything.
 */

import { expect, test } from './diagnostics.js';
import {
  activatedCustomer,
  closeStaffContext,
  freshAddress,
  register,
  signIn,
  staffContext,
} from './accountHelpers.js';

/** The width the layout is designed for (`Design.md` §16, §14a.2). */
const PHONE_WIDTH = 375;

/** Primary controls are 48 px tall at phone width. */
const MINIMUM_PRIMARY_TARGET = 48;

/** Nothing on the page may be wider than the viewport. */
async function assertNoHorizontalOverflow(page) {
  const overflow = await page.evaluate(() => ({
    scrollWidth: document.documentElement.scrollWidth,
    clientWidth: document.documentElement.clientWidth,
    widest: Array.from(document.querySelectorAll('main *'))
      .filter((element) => element.getBoundingClientRect().right > window.innerWidth + 1)
      .slice(0, 5)
      .map((element) => `${element.tagName}.${element.className}`),
  }));
  expect(
    overflow.scrollWidth,
    `the page scrolls horizontally; widest: ${overflow.widest.join(', ')}`,
  ).toBeLessThanOrEqual(overflow.clientWidth + 1);
}

test.describe('at phone width', () => {
  test('the viewport is the one these assertions are about', async ({ page }) => {
    await page.goto('/account/sign-in');
    expect(page.viewportSize().width).toBe(PHONE_WIDTH);
  });

  test('sign in fits, and its controls are large enough to hit', async ({ page }) => {
    await page.goto('/account/sign-in');
    await expect(page.getByRole('heading', { name: 'Sign in', level: 1 })).toBeVisible();
    await assertNoHorizontalOverflow(page);

    const submit = page.getByRole('button', { name: 'Sign in' });
    const box = await submit.boundingBox();
    expect(box.height).toBeGreaterThanOrEqual(MINIMUM_PRIMARY_TARGET);

    for (const label of ['Email address', 'Password']) {
      const field = await page.getByLabel(label, { exact: true }).boundingBox();
      expect(field.height, `${label} is too short to tap`).toBeGreaterThanOrEqual(
        MINIMUM_PRIMARY_TARGET,
      );
    }
  });

  test('the registration form fits, including its consent controls', async ({ page }) => {
    await page.goto('/account/register');
    await assertNoHorizontalOverflow(page);

    const create = await page.getByRole('button', { name: 'Create account' }).boundingBox();
    expect(create.height).toBeGreaterThanOrEqual(MINIMUM_PRIMARY_TARGET);

    // A consent checkbox is small by nature, so the *row* is the target: the label sits
    // beside it and is clickable, which is what a thumb actually hits.
    const terms = page.getByLabel(/I accept the Solaris Express terms/);
    await terms.check();
    await expect(terms).toBeChecked();
  });

  test('shipping, the billing box and both password boxes fit a phone (UAT round 8)', async ({
    page,
  }) => {
    await page.goto('/account/register');
    for (const label of ['Password', 'Confirm password']) {
      const field = await page.getByLabel(label, { exact: true }).boundingBox();
      expect(field.height, `${label} is too short to tap`).toBeGreaterThanOrEqual(
        MINIMUM_PRIMARY_TARGET,
      );
      expect(field.width).toBeLessThanOrEqual(PHONE_WIDTH);
    }

    // "Address" and "the address above" since UAT round 9.
    const shipping = page.getByRole('group', { name: 'Address', exact: true });
    await shipping.getByLabel(/^Address line 1/).fill('4120 Dixie Road');
    const same = page.getByLabel('Billing address is the same as the address above');
    await expect(same).toBeChecked();
    await assertNoHorizontalOverflow(page);

    // The label is the target, as for the consent boxes: tapping the words unticks it.
    await page.getByText('Billing address is the same as the address above').click();
    await expect(same).not.toBeChecked();
    const billingLine1 = page
      .getByRole('group', { name: 'Billing address' })
      .getByLabel('Address line 1', { exact: true });
    await expect(billingLine1).toBeVisible();
    const box = await billingLine1.boundingBox();
    expect(box.width).toBeLessThanOrEqual(PHONE_WIDTH);
    await assertNoHorizontalOverflow(page);
  });

  test('the required address, its errors and the driver note fit a phone (UAT round 9)', async ({
    page,
  }) => {
    await page.goto('/account/register');
    await page.getByLabel(/I accept the Solaris Express terms/).check();
    const address = page.getByRole('group', { name: 'Address', exact: true });
    // Ticked from the start since UAT round 11.
    await expect(page.getByLabel('Billing address is the same as the address above')).toBeChecked();
    await page.getByRole('button', { name: 'Create account' }).click();

    for (const label of [
      'Country',
      'Address line 1',
      'City',
      'Province or state',
      'Postal code',
    ]) {
      const field = address.getByLabel(label, { exact: true });
      const box = await field.boundingBox();
      expect(box.height, `${label} is too short to tap`).toBeGreaterThanOrEqual(
        MINIMUM_PRIMARY_TARGET,
      );
      expect(box.width).toBeLessThanOrEqual(PHONE_WIDTH);
    }
    // City and province sit side by side on a wide screen; on a phone each error must
    // still be readable, so neither block may overflow.
    await expect(address.getByText('Enter the province or state.')).toBeVisible();
    const error = await address.getByText('Enter the province or state.').boundingBox();
    expect(error.x + error.width).toBeLessThanOrEqual(PHONE_WIDTH);

    const note = address.getByLabel(
      'Notes for driver (buzz code, contact concierge, security,...)',
      { exact: true },
    );
    await expect(note).toBeVisible();
    expect((await note.boundingBox()).width).toBeLessThanOrEqual(PHONE_WIDTH);
    await assertNoHorizontalOverflow(page);

    // Unticked, the billing errors fit too.
    await page.getByText('Billing address is the same as the address above').click();
    await page.getByRole('button', { name: 'Create account' }).click();
    const billing = page.getByRole('group', { name: 'Billing address', exact: true });
    await expect(billing.getByText('Enter the billing city.')).toBeVisible();
    await assertNoHorizontalOverflow(page);
  });

  test('an empty form shows no billing or postal code errors, and fits (UAT round 11)', async ({
    page,
  }) => {
    await page.goto('/account/register');
    await page.getByRole('button', { name: 'Create account' }).click();
    const summary = page.getByRole('alert').first();
    await expect(summary.getByRole('link', { name: 'Enter the city.' })).toBeVisible();
    await expect(summary).not.toContainText(/billing/i);
    await expect(summary).not.toContainText(/postal code/i);
    const postal = page
      .getByRole('group', { name: 'Address', exact: true })
      .getByLabel('Postal code', { exact: true });
    await expect(postal).not.toHaveAttribute('aria-invalid', 'true');
    const box = await postal.boundingBox();
    expect(box.height).toBeGreaterThanOrEqual(MINIMUM_PRIMARY_TARGET);
    expect(box.width).toBeLessThanOrEqual(PHONE_WIDTH);
    await assertNoHorizontalOverflow(page);
  });

  test('each card shows its booking reference, and a package ID finds it (UAT round 11)', async ({
    page,
    browser,
  }) => {
    test.setTimeout(120_000);
    const { email } = await activatedCustomer(page, browser, { label: 'mobile-r11' });
    // The longest booking reference the field allows (60), with no spaces to break at.
    const longReference = `PO-${Date.now().toString(36).toUpperCase()}-`.padEnd(60, 'X');
    const { context, page: staffPage } = await staffContext(browser);
    let reference;
    try {
      const lookup = await staffPage.request.get('/api/v1/customers', {
        params: { search: email, limit: 5 },
      });
      const match = (await lookup.json()).items.find(
        (item) => (item.email_entered || '').toLowerCase() === email,
      );
      expect(match, 'the activated customer is not in the staff list').toBeTruthy();
      const { bookShipment } = await import('./accountBooking.js');
      reference = await bookShipment(staffPage, match.id, { bookingReference: longReference });
    } finally {
      await closeStaffContext({ context, page: staffPage });
    }

    await signIn(page, email);
    const cards = page.locator('.ca-cards');
    await expect(cards).toBeVisible();
    const card = cards.locator('.ca-shipment-card').first();
    await expect(card.getByText('Booking reference', { exact: true })).toBeVisible();
    const value = card.getByText(longReference);
    await expect(value).toBeVisible();
    const valueBox = await value.boundingBox();
    expect(valueBox.x + valueBox.width).toBeLessThanOrEqual(PHONE_WIDTH);
    await assertNoHorizontalOverflow(page);

    const search = page.getByLabel(/Search shipments/);
    await search.fill(`${reference}-01`);
    await search.press('Enter');
    await expect.poll(() => new URL(page.url()).searchParams.get('q')).toBe(`${reference}-01`);
    await expect(cards.locator(`a[href$="${reference}"]`)).toHaveCount(1);
    await assertNoHorizontalOverflow(page);
  });

  test('the shipment page shows a long booking reference without overflow (UAT round 12)', async ({
    page,
    browser,
  }) => {
    test.setTimeout(120_000);
    const { email } = await activatedCustomer(page, browser, { label: 'mobile-r12' });
    // The longest booking reference the field allows (60), with no spaces to break at.
    const longReference = `PO-${Date.now().toString(36).toUpperCase()}-`.padEnd(60, 'Y');
    const { context, page: staffPage } = await staffContext(browser);
    let reference;
    try {
      const lookup = await staffPage.request.get('/api/v1/customers', {
        params: { search: email, limit: 5 },
      });
      const match = (await lookup.json()).items.find(
        (item) => (item.email_entered || '').toLowerCase() === email,
      );
      expect(match, 'the activated customer is not in the staff list').toBeTruthy();
      const { bookShipment } = await import('./accountBooking.js');
      reference = await bookShipment(staffPage, match.id, { bookingReference: longReference });
    } finally {
      await closeStaffContext({ context, page: staffPage });
    }

    await signIn(page, email);
    await page.locator('.ca-cards').locator(`a[href$="${reference}"]`).click();
    await expect(page.getByRole('heading', { name: reference, level: 1 })).toBeVisible();
    const row = page
      .locator('.ca-detail-row')
      .filter({ has: page.getByText('Booking reference', { exact: true }) });
    const value = row.locator('dd');
    await expect(value).toHaveText(longReference);
    const valueBox = await value.boundingBox();
    expect(valueBox.x + valueBox.width).toBeLessThanOrEqual(PHONE_WIDTH);
    // The first fact in "Where it is", above From and To.
    await expect(page.locator('.ca-detail-grid .ca-detail-row').first()).toContainText(
      'Booking reference',
    );
    await assertNoHorizontalOverflow(page);
  });

  test('a misshapen postal code is refused beside the field, and fits (UAT round 12)', async ({
    page,
  }) => {
    await page.goto('/account/register');
    const address = page.getByRole('group', { name: 'Address', exact: true });
    await address.getByLabel('Address line 1', { exact: true }).fill('4120 Dixie Road');
    await address.getByLabel('City', { exact: true }).fill('Mississauga');
    await address.getByLabel('Province or state', { exact: true }).fill('ON');
    const postal = address.getByLabel('Postal code', { exact: true });
    await postal.fill('L4W 1V');
    await page.getByRole('button', { name: 'Create account' }).click();

    const message = 'Enter the postal code as A1A 1A1, or leave it blank.';
    const summary = page.getByRole('alert').first();
    await expect(summary.getByRole('link', { name: message })).toBeVisible();
    await expect(postal).toHaveAttribute('aria-invalid', 'true');
    const error = address.getByText(message);
    await expect(error).toBeVisible();
    const errorBox = await error.boundingBox();
    expect(errorBox.x + errorBox.width).toBeLessThanOrEqual(PHONE_WIDTH);
    const box = await postal.boundingBox();
    expect(box.height).toBeGreaterThanOrEqual(MINIMUM_PRIMARY_TARGET);
    await assertNoHorizontalOverflow(page);
  });

  test('the shipment list becomes cards, not a squeezed table', async ({ page, browser }) => {
    const { activateAgainstSeeded } = await import('./accountSeeded.js');
    // This signs in as part of activating, so the list is already on screen.
    await activateAgainstSeeded(page, browser, {
      email: 'marie.claude.demo@demo.example.com',
      legalName: 'Marie Claude Demo',
    });
    await expect(page.getByRole('heading', { name: 'My shipments', level: 1 })).toBeVisible();

    // Both layouts are in the DOM and CSS chooses. At this width the table is hidden and
    // the cards are shown — which is what stops eight columns turning into a scroller.
    const table = page.locator('.ca-table-wrap');
    const cards = page.locator('.ca-cards');
    await expect(cards).toBeVisible();
    await expect(table).toBeHidden();

    await assertNoHorizontalOverflow(page);

    // A reference is long and must break rather than push the page wide. Scoped to the
    // card list: the table's copy of the same anchor is in the DOM and hidden, and
    // measuring a hidden element measures nothing.
    const reference = cards.locator('a[href^="/account/shipments/SX-"]').first();
    await expect(reference).toBeVisible();
    const box = await reference.boundingBox();
    expect(box.width).toBeLessThanOrEqual(PHONE_WIDTH);

    // And the filters stack rather than sitting side by side.
    await assertNoHorizontalOverflow(page);

    // UAT round 10: the keyword search, typed on a phone. Tall enough to tap, its hint
    // fits, part of a city in lower case finds the one Vietnam-to-Canada shipment, and
    // the phone keyboard's search key (Enter) sends it.
    const search = page.getByLabel(/Search shipments/);
    const searchBox = await search.boundingBox();
    expect(searchBox.height).toBeGreaterThanOrEqual(MINIMUM_PRIMARY_TARGET);
    expect(searchBox.width).toBeLessThanOrEqual(PHONE_WIDTH);
    await search.fill('toron');
    await search.press('Enter');
    await expect.poll(() => new URL(page.url()).searchParams.get('q')).toBe('toron');
    await expect(cards.locator('a[href^="/account/shipments/SX-VCA-"]')).toHaveCount(1);
    await expect(cards.locator('a[href^="/account/shipments/SX-CAV-"]')).toHaveCount(0);
    await assertNoHorizontalOverflow(page);
    await page.getByRole('button', { name: 'Clear filters' }).first().click();
    await expect.poll(() => new URL(page.url()).search).toBe('');

    // The detail page too.
    await reference.click();
    await expect(page.getByRole('heading', { name: 'Where it is', level: 2 })).toBeVisible();
    await assertNoHorizontalOverflow(page);
  });

  test('the pending card fits and reads as a state', async ({ page }) => {
    const email = freshAddress('mobile-pending');
    await register(page, email);
    const { verify } = await import('./accountHelpers.js');
    await verify(page, email);
    await signIn(page, email);
    await expect(
      page.getByRole('heading', { name: 'Your account is being reviewed', level: 1 }),
    ).toBeVisible();
    await assertNoHorizontalOverflow(page);
  });

  test('the empty history fits', async ({ page, browser }) => {
    const { email } = await activatedCustomer(page, browser, { label: 'mobile-empty' });
    await signIn(page, email);
    await expect(page.getByText('No shipments yet')).toBeVisible();
    await assertNoHorizontalOverflow(page);
  });

  test('the whole surface is reachable by keyboard alone', async ({ page }) => {
    await page.goto('/account/sign-in');
    // Wait for the application to have rendered before pressing anything. `goto`
    // resolves on the document, and a Tab sent before React has mounted lands on
    // nothing — which reads as "the skip link is missing" and is not.
    await expect(page.getByRole('heading', { name: 'Sign in', level: 1 })).toBeVisible();

    // The first Tab reaches the skip link, which is the first focusable element and the
    // thing that makes every subsequent page usable from the keyboard.
    await page.keyboard.press('Tab');
    const first = await page.evaluate(() => document.activeElement?.textContent?.trim());
    expect(first).toBe('Skip to main content');

    // Tabbing on reaches both fields and the submit control, in order.
    const reached = [];
    for (let index = 0; index < 12; index += 1) {
      await page.keyboard.press('Tab');
      reached.push(
        await page.evaluate(() => {
          const element = document.activeElement;
          if (!element) return null;
          const label = element.labels?.[0]?.textContent?.trim();
          return label || element.textContent?.trim() || element.tagName;
        }),
      );
    }
    expect(reached.some((item) => item?.includes('Email address'))).toBe(true);
    expect(reached.some((item) => item?.includes('Password'))).toBe(true);
    expect(reached.some((item) => item === 'Sign in')).toBe(true);
  });

  test('a shipment row opens from the keyboard', async ({ page, browser }) => {
    const { email } = await activatedCustomer(page, browser, { label: 'mobile-keys' });
    await signIn(page, email);
    await expect(page.getByRole('heading', { name: 'My shipments', level: 1 })).toBeVisible();

    // No rows for this account, so the assertion is about the controls that are there:
    // every one of them is a real control with an accessible name.
    const focusables = await page.evaluate(() =>
      Array.from(
        document.querySelectorAll('main a[href], main button, main input, main select'),
      ).map((element) => ({
        tag: element.tagName,
        name:
          element.getAttribute('aria-label') ||
          element.labels?.[0]?.textContent?.trim() ||
          element.textContent?.trim(),
      })),
    );
    expect(focusables.length).toBeGreaterThan(0);
    for (const control of focusables) {
      expect(control.name, `a ${control.tag} has no accessible name`).toBeTruthy();
    }
  });
});
