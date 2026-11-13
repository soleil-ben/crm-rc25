/**
 * Phase 14: Settings → Pricing, end to end, as the administrator, through the screens only.
 *
 * The Air Express default rate is set, survives a reload, and is cleared again (empty is the
 * stand-in: Operations enter the rate per quote); an impossible share (4/3) is named beside
 * its field and not saved; a surcharge policy's note is saved while its markup stays Default,
 * so the other specs' prices are unchanged. Air only; test data only.
 */

import { expect, test } from './diagnostics.js';
import { auditAndAssert, settle } from './axeHelpers.js';

async function openPricing(page) {
  await page.goto('/settings');
  await page.getByRole('tab', { name: 'Pricing' }).click();
  const standard = page.getByRole('textbox', { name: /Air Standard default rate/ });
  await expect(standard).toBeVisible();
  return standard;
}

test.describe('Pricing settings', () => {
  test('edits the default rates, refuses a bad share, and saves a surcharge policy', async ({ page }, testInfo) => {
    test.setTimeout(90_000);
    const tag = Date.now().toString(36);

    const standard = await openPricing(page);
    await expect(standard).toHaveValue('18');
    await expect(page.getByRole('textbox', { name: 'Numerator' })).toHaveValue('2');
    await expect(page.getByRole('textbox', { name: 'Denominator' })).toHaveValue('3');
    await settle(page);
    await auditAndAssert(page, 'staff-settings-pricing', testInfo);

    // --- Air Express default rate: set, persist, clear --------------------------------
    const express = page.getByRole('textbox', { name: /Air Express default rate/ });
    await express.fill('21.5');
    await page.getByRole('button', { name: 'Save pricing settings' }).click();
    await expect(page.getByText('Pricing settings saved.')).toBeVisible();

    await openPricing(page);
    await expect(page.getByRole('textbox', { name: /Air Express default rate/ })).toHaveValue('21.5');

    // --- A share above one is named beside its field and never sent ---------------------
    const numerator = page.getByRole('textbox', { name: 'Numerator' });
    await numerator.fill('4');
    let patched = false;
    page.on('request', (request) => {
      if (request.url().includes('/api/v1/pricing/settings') && request.method() === 'PATCH') patched = true;
    });
    await page.getByRole('button', { name: 'Save pricing settings' }).click();
    await expect(page.getByText('The numerator cannot be larger than the denominator.')).toBeVisible();
    await expect(numerator).toHaveAttribute('aria-invalid', 'true');
    await expect(numerator).toBeFocused();
    expect(patched).toBe(false);
    await numerator.fill('2');

    await page.getByRole('textbox', { name: /Air Express default rate/ }).fill('');
    await page.getByRole('button', { name: 'Save pricing settings' }).click();
    await expect(page.getByText('Pricing settings saved.')).toBeVisible();
    await openPricing(page);
    await expect(page.getByRole('textbox', { name: /Air Express default rate/ })).toHaveValue('');

    // --- A surcharge policy: found without accents, note saved, markup left Default -----
    await page.getByRole('searchbox', { name: /Search surcharges/ }).fill('dong ho thuong');
    const table = page.getByRole('region', { name: 'Surcharges and their policies' });
    const row = table.getByRole('row', { name: /Đồng hồ thường/ }).first();
    await expect(row).toBeVisible();
    await row.getByRole('button', { name: /Edit policy/ }).click();
    const editor = page.getByRole('form', { name: /Edit policy: \d+\. Đồng hồ thường/ });
    await expect(editor.getByRole('combobox', { name: 'Markup' })).toBeFocused();
    await expect(editor.getByRole('combobox', { name: 'Markup' })).toHaveValue('default');
    await editor.getByRole('textbox', { name: /Note/ }).fill(`E2E note ${tag}`);
    await editor.getByRole('button', { name: 'Save policy' }).click();
    await expect(page.getByText(/Policy saved for \d+\. Đồng hồ thường\./)).toBeVisible();
    await expect(table.getByRole('row', { name: /Đồng hồ thường/ }).first()).toContainText(`E2E note ${tag}`);
    await expect(table.getByRole('row', { name: /Đồng hồ thường/ }).first()).toContainText('Default (Percent 2 %)');
  });
});
