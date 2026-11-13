/**
 * The unified workspace (Phase 13D), end to end, through the screens only.
 *
 * The scratch database carries the sanitized demo tariff and a fixed demo exchange rate
 * (`app.seed_pricing`, run by `scripts/e2e_env.py`), so a master built here prices for
 * real: base freight from the rate sheet, the watch surcharge from the HCM air section,
 * and a quote that finalises once the rate is confirmed (the surcharge converts at the buy
 * rate and carries the 2 % default markup, OD-73/OD-74). Air only: nothing touches Sea.
 *
 * Every step is a click or a keystroke. The API is only read (never written) to learn
 * which shipment the search offered.
 */

import { expect, test } from './diagnostics.js';

test.describe('Workspace', () => {
  test('builds an air master, prices a watch surcharge and finalises the quote', async ({ page }) => {
    test.setTimeout(120_000);

    // --- The nav entry and the list --------------------------------------------------
    await page.goto('/');
    await page.getByRole('link', { name: 'Workspace' }).click();
    await expect(page.getByRole('heading', { name: 'Workspace', level: 1 })).toBeVisible();

    // --- A new air master: HCM, 21 kg -------------------------------------------------
    await page.getByRole('button', { name: 'New master' }).click();
    const service = page.getByRole('combobox', { name: /Service/ });
    await expect(service.locator('option')).toHaveText(['Kango Air Standard', 'Kango Air Express', 'UPS', 'Air Cargo', 'Sea']);
    await page.getByRole('combobox', { name: /Origin/ }).selectOption('HCM');
    await page.getByRole('textbox', { name: /Gross weight/ }).fill('21');
    await page.getByRole('button', { name: 'Create master' }).click();
    await expect(page).toHaveURL(/\/workspace\/\d+$/);
    const consolidationId = page.url().split('/').pop();
    await expect(page.getByText('No customers on this master yet', { exact: false })).toBeVisible();

    // --- Add a seeded confirmed Vietnam → Canada shipment ------------------------------
    // The search may offer shipments the server will not accept (a draft, a cancelled
    // one); try each in turn until one is added.
    await page.getByRole('button', { name: 'Attach an existing booking' }).first().click();
    await page.getByRole('searchbox', { name: /Find a confirmed booking/ }).fill('SX-VCA');
    const results = page.getByRole('list', { name: 'Matching shipments' });
    await expect(results.getByRole('listitem').first()).toBeVisible();
    const offered = await results.getByRole('listitem').count();
    let added = false;
    for (let index = 0; index < offered && !added; index += 1) {
      const response = page.waitForResponse(
        (item) =>
          item.url().includes(`/api/v1/consolidations/${consolidationId}/members`) &&
          item.request().method() === 'POST',
      );
      await results.getByRole('listitem').nth(index).getByRole('button', { name: 'Add' }).click();
      added = (await response).ok();
    }
    expect(added, 'no seeded VCA shipment offered by the search could join the master').toBe(true);

    const customers = page.locator('section.ws-customers');
    const card = customers.locator('section.card').first();
    await expect(card.getByRole('heading', { level: 3 })).toBeVisible();

    // --- An item, then the watch fee on it ---------------------------------------------
    await card.getByRole('button', { name: 'Add item' }).click();
    await card.getByRole('textbox', { name: /Description/ }).fill('Đồng hồ đeo tay');
    await card.getByRole('textbox', { name: /Weight \(kg\)/ }).fill('0.4');
    await card.getByRole('button', { name: 'Add item' }).click();
    await expect(card.getByText('Đồng hồ đeo tay')).toBeVisible();

    await card.getByRole('button', { name: 'Add fee' }).click();
    await card.getByRole('searchbox', { name: /Search the vendor/ }).fill('dong ho');
    const fees = card.getByRole('list', { name: 'Matching surcharges' });
    // Accent-insensitive: the unaccented query finds the vendor's accented name.
    await fees.getByRole('button', { name: /Đồng hồ thường/ }).click();
    await card.getByRole('textbox', { name: /Quantity/ }).fill('1');
    await card.getByRole('button', { name: 'Add fee' }).click();
    const feeList = card.getByRole('list', { name: 'Fees on this item' });
    await expect(feeList).toContainText('Đồng hồ thường');

    // --- Vendor cost panel ---------------------------------------------------------------
    const cost = page.getByRole('complementary', { name: 'Vendor cost' });
    const surcharges = cost.locator('.ws-detail', { hasText: 'Surcharges' }).locator('dd');
    await expect(surcharges).toHaveText('50,000 VND');
    await expect(cost.locator('.ws-detail', { hasText: 'Base freight' }).locator('dd')).toHaveText(
      /^[\d,.]+ VND$/,
    );
    await expect(cost.locator('.ws-detail', { hasText: 'Total vendor cost' }).locator('dd')).toHaveText(
      /^[\d,.]+ VND$/,
    );
    await expect(cost).toContainText('Vietcombank: cash buying');

    // --- Quote: price, confirm, finalise -------------------------------------------------
    await card.getByRole('button', { name: 'Price quote' }).click();
    await expect(card.getByText(/v1 · Draft/)).toBeVisible();
    await expect(card.getByText('Rate not confirmed')).toBeVisible();

    await card.getByRole('button', { name: 'Confirm selling rate' }).click();
    await expect(card.getByText('Rate confirmed', { exact: true })).toBeVisible();

    // The surcharge converts at the buy rate like its cost and carries the 2 % default markup
    // (OD-73, OD-74), so it no longer bills below cost: no reason is asked for.
    await card.getByRole('button', { name: 'Finalise quote' }).click();
    await expect(card.getByText(/v1 · Finalised/)).toBeVisible();
    await expect(card.getByText('This quote cannot be finalised yet.')).toHaveCount(0);
  });
});
