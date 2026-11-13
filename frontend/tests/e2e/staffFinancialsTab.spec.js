/**
 * RC-UAT-25 items 7 and 8 (Ben 2026-10-25), end to end through the screens: the shipment
 * page's Financials tab after financial info is added, and invoicing the client from it.
 *
 * Ben added financial info to a shipment and `/shipments/<id>?tab=financials` went blank.
 * Here a seeded Vietnam → Canada shipment joins a new air master; its Financials tab first
 * says "No quote yet" and links to the master; the quote is priced, confirmed and finalised
 * there; back on the tab the quoted revenue and the vendor cost show (the staff session is an
 * Admin), the recorded amounts are entered (a two-letter currency is refused before saving),
 * the invoice is issued from the tab, and the tab -- reloaded by its URL -- shows the invoice.
 *
 * Every step is a click or a keystroke; the API is only listened to. Test data only.
 */

import { expect, test } from './diagnostics.js';
import { addMemberBySearch, createMaster } from './workspaceHelpers.js';

/** The recorded selling amount's row (the declared value may show the same figure). */
function sellingRow(page) {
  return page.locator('.detail-row', { hasText: 'Selling amount' });
}

test.describe('Shipment Financials tab', () => {
  test('loads after financial info is added, and invoices the client from the shipment page', async ({
    page,
  }) => {
    test.setTimeout(180_000);
    const { consolidationId } = await createMaster(page, 'FINTAB');
    expect(await addMemberBySearch(page, consolidationId, 'SX-VCA')).toBe(true);
    const card = page.locator('section.ws-customers').locator('section.card').first();
    await expect(card.getByRole('heading', { level: 3 })).toBeVisible();
    const shipmentHref = await card.getByRole('link', { name: /^Open shipment/ }).getAttribute('href');
    const shipmentId = shipmentHref.split('/').pop();
    const tabUrl = `/shipments/${shipmentId}?tab=financials`;

    // --- Booked, in a master, not priced: an explicit next step, never a blank tab ------
    await page.goto(tabUrl);
    const panel = page.getByRole('tabpanel');
    await expect(panel).toBeVisible();
    const next = panel.getByTestId('fin-next-step');
    await expect(next).toHaveAttribute('data-step', 'price');
    await expect(next.getByText('No quote yet: price this shipment.')).toBeVisible();
    await expect(next.getByRole('button', { name: 'Issue invoice' })).toBeDisabled();
    await expect(next.getByText(/Finalise the shipment's quote before issuing an invoice\./)).toBeVisible();
    await next.getByRole('link', { name: 'Price this shipment' }).click();
    await expect(page).toHaveURL(new RegExp(`/workspace/${consolidationId}$`));

    // --- Price, confirm and finalise in the master's workspace --------------------------
    const priced = page.locator('section.ws-customers').locator('section.card').first();
    await priced.getByRole('button', { name: /Price quote/ }).click();
    await expect(priced.getByText(/v1 · Draft/)).toBeVisible();

    // A draft quote: the tab asks to finalise it.
    await page.goto(tabUrl);
    await expect(page.getByTestId('fin-next-step')).toHaveAttribute('data-step', 'finalise_quote');
    await page.goto(`/workspace/${consolidationId}`);

    const again = page.locator('section.ws-customers').locator('section.card').first();
    await again.getByRole('button', { name: 'Confirm selling rate' }).click();
    await expect(again.getByText('Rate confirmed', { exact: true })).toBeVisible();
    await again.getByRole('button', { name: 'Finalise quote' }).click();
    const finalised = again.getByText(/v1 · Finalised/);
    const refused = again.getByText('This quote cannot be finalised yet.');
    await expect(finalised.or(refused)).toBeVisible();
    if (await refused.isVisible()) {
      await again
        .getByRole('textbox', { name: /Reason for billing a surcharge below cost/ })
        .fill('Surcharge absorbed for this customer (e2e financials tab test).');
      await again.getByRole('button', { name: 'Finalise quote' }).click();
    }
    await expect(finalised).toBeVisible();

    // --- Back on the shipment: revenue, cost, and ready to invoice ----------------------
    await page.goto(tabUrl);
    const ready = page.getByTestId('fin-next-step');
    await expect(ready).toHaveAttribute('data-step', 'issue_invoice');
    await expect(ready.getByText('Ready to invoice: issue the invoice.')).toBeVisible();
    const summary = page.getByTestId('fin-summary');
    await expect(summary.getByText('Quoted revenue')).toBeVisible();
    await expect(summary.getByText('Vendor cost')).toBeVisible();
    await expect(summary.getByText(/^v1 · Finalised/)).toBeVisible();

    // --- The recorded amounts, as Ben entered financial info -----------------------------
    const currency = page.getByRole('textbox', { name: 'Currency' });
    await currency.fill('CA');
    await page.getByRole('textbox', { name: 'Selling amount' }).fill('120.00');
    await page.getByRole('button', { name: 'Save amounts' }).click();
    await expect(page.getByText('Use a three-letter currency code such as CAD.')).toBeVisible();
    await currency.fill('CAD');
    const saved = page.waitForResponse(
      (item) =>
        item.url().includes(`/api/v1/shipments/${shipmentId}/financials`) &&
        item.request().method() === 'PATCH',
    );
    await page.getByRole('button', { name: 'Save amounts' }).click();
    expect((await saved).ok()).toBe(true);
    await expect(sellingRow(page)).toContainText('CAD 120.00');

    // --- Issue the invoice from the tab ------------------------------------------------
    await ready.getByRole('button', { name: 'Issue invoice' }).click();
    const open = page.getByTestId('fin-next-step').getByRole('link', { name: /^Open invoice INV-\d+$/ });
    await expect(open).toBeVisible();
    const label = (await open.textContent()).trim();
    const invoiceNumber = label.replace('Open invoice ', '');

    // --- Reloaded by its URL, the tab is still there with content ------------------------
    await page.goto(tabUrl);
    await expect(page.getByRole('tabpanel')).toBeVisible();
    await expect(page.getByText('Recorded amounts')).toBeVisible();
    await expect(sellingRow(page)).toContainText('CAD 120.00');
    await expect(page.getByTestId('fin-next-step')).toHaveAttribute('data-step', 'open_invoice');
    await expect(page.getByTestId('fin-summary').getByText(invoiceNumber, { exact: true })).toBeVisible();
    await expect(page.getByText('This section could not be shown')).toHaveCount(0);

    await page.getByRole('link', { name: `Open invoice ${invoiceNumber}` }).click();
    await expect(page).toHaveURL(/\/finance\/invoices\/\d+$/);
    await expect(page.getByRole('heading', { level: 1 })).toContainText(invoiceNumber);

    // --- From another tab, the header goes straight to it -------------------------------
    await page.goto(`/shipments/${shipmentId}?tab=details`);
    await page.getByRole('button', { name: 'Quote & invoice' }).click();
    await expect(page).toHaveURL(/tab=financials/);
    await expect(page.getByTestId('fin-next-step')).toHaveAttribute('data-step', 'open_invoice');
  });
});
