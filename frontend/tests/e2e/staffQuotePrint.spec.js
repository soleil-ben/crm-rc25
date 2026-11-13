/**
 * Phase 14: the printable customer quote, end to end, through the screens only.
 *
 * An air master is built, a Vietnam → Canada customer added by search and quoted (price,
 * confirm the rate, finalise), and "Print customer quote" opens the document: the company's
 * details as on invoices (OD-64), the customer, the Solaris service name, the charges and the
 * total with its GST/HST sentence (RC-UAT-21: zero-rated for VN -> CA) -- and no vendor cost, exchange rate, markup, margin,
 * vendor name or product code anywhere on the page. Nothing is sent to the customer.
 */

import { expect, test } from './diagnostics.js';
import { auditAndAssert, settle } from './axeHelpers.js';
import { addMemberBySearch, createMaster } from './workspaceHelpers.js';

const FORBIDDEN = [/cost/i, /\bVND\b/, /markup/i, /\bFX\b/, /exchange/i, /vendor/i, /kango/i, /margin/i, /AIR-CAD/i, /TRF-\d/];

test.describe('Printable quote', () => {
  test('shows the customer charges and company details, never a cost', async ({ page }, testInfo) => {
    test.setTimeout(150_000);
    const { consolidationId } = await createMaster(page, 'QDOC');
    expect(await addMemberBySearch(page, consolidationId, 'SX-VCA')).toBe(true);
    const card = page.locator('section.ws-customers').locator('section.card').first();
    await expect(card.getByRole('heading', { level: 3 })).toBeVisible();

    await card.getByRole('button', { name: /Price quote/ }).click();
    await expect(card.getByText(/v1 · Draft/)).toBeVisible();
    await card.getByRole('button', { name: /Confirm selling rate/ }).click();
    await expect(card.getByText('Rate confirmed', { exact: true })).toBeVisible();
    await card.getByRole('button', { name: /Finalise quote/ }).click();
    const finalised = card.getByText(/v1 · Finalised/);
    const refused = card.getByText('This quote cannot be finalised yet.');
    await expect(finalised.or(refused)).toBeVisible();
    if (await refused.isVisible()) {
      await card
        .getByRole('textbox', { name: /Reason for billing a surcharge below cost/ })
        .fill('Surcharge absorbed for this customer (e2e quote print test).');
      await card.getByRole('button', { name: /Finalise quote/ }).click();
    }
    await expect(finalised).toBeVisible();

    await card.getByRole('link', { name: /Print customer quote v1/ }).click();
    await expect(page).toHaveURL(new RegExp(`/workspace/quotes/\\d+/1/print\\?from=${consolidationId}$`));
    const doc = page.getByRole('article', { name: 'Quote' });
    await expect(doc).toBeVisible();
    // DEC-0235 (owner Ben, 2026-10-24): the Solaris Invoicing desk's company details.
    await expect(doc).toContainText('Solaris Express Inc.');
    await expect(doc).toContainText('795093756RT0001');
    await expect(doc).toContainText('2446 Cawthra Rd Building 1 Unit 8, Mississauga ON L5A 3K6');
    await expect(doc).toContainText('solarisexpressinc@gmail.com');
    await expect(doc).toContainText('Air Standard');
    await expect(doc).toContainText('Air freight');
    // RC-UAT-21 (P-9 stand-in): a Vietnam -> Canada quote is zero-rated, as its invoice.
    await expect(doc).toContainText('Total');
    await expect(doc).toContainText('Zero-rated (0 %)');

    const text = await page.locator('main').innerText();
    for (const word of FORBIDDEN) expect(text, String(word)).not.toMatch(word);

    await settle(page);
    await auditAndAssert(page, 'staff-quote-print', testInfo);
    await page.getByRole('link', { name: 'Back to the workspace' }).click();
    await expect(page).toHaveURL(new RegExp(`/workspace/${consolidationId}$`));
  });
});
