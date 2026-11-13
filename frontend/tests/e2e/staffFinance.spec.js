/**
 * Finance (Phase 13E), end to end, through the screens only: an air master is built and
 * quoted, the customer is invoiced and pays part, the receipt and the printable invoice are
 * checked, the master is booked, the vendor's bill is entered from the estimate and
 * approved, and the master shows in the month's profitability. Air only.
 *
 * Every step is a click or a keystroke. The API is only listened to (never called) to learn
 * whether the server accepted a shipment the search offered.
 */

import { expect, test } from './diagnostics.js';

test.describe('Finance', () => {
  test('quote → invoice → partial payment → receipt → vendor bill → profitability', async ({ page }) => {
    test.setTimeout(180_000);

    // --- A new HCM air master, 21 kg ---------------------------------------------------
    await page.goto('/workspace');
    await expect(page.getByRole('heading', { name: 'Workspace', level: 1 })).toBeVisible();
    await page.getByRole('button', { name: 'New master' }).click();
    await page.getByRole('combobox', { name: /Origin/ }).selectOption('HCM');
    await page.getByRole('textbox', { name: /Master tracking/ }).fill(`AWB-FIN-${Date.now().toString(36)}`);
    await page.getByRole('textbox', { name: /Gross weight/ }).fill('21');
    await page.getByRole('button', { name: 'Create master' }).click();
    await expect(page).toHaveURL(/\/workspace\/\d+$/);
    const workspaceUrl = page.url();
    const consolidationId = workspaceUrl.split('/').pop();
    const heading = page.getByRole('heading', { level: 1 });
    await expect(heading).toContainText('Air Standard');
    const masterReference = (await heading.textContent()).split('·')[0].trim();
    expect(masterReference.length).toBeGreaterThan(0);

    // --- A seeded confirmed Vietnam → Canada shipment ---------------------------------
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

    const card = page.locator('section.ws-customers').locator('section.card').first();
    await expect(card.getByRole('heading', { level: 3 })).toBeVisible();

    // --- Quote: price, confirm, finalise -----------------------------------------------
    await card.getByRole('button', { name: /Price quote/ }).click();
    await expect(card.getByText(/v1 · Draft/)).toBeVisible();
    await card.getByRole('button', { name: 'Confirm selling rate' }).click();
    await expect(card.getByText('Rate confirmed', { exact: true })).toBeVisible();
    await card.getByRole('button', { name: 'Finalise quote' }).click();
    const finalised = card.getByText(/v1 · Finalised/);
    const refused = card.getByText('This quote cannot be finalised yet.');
    await expect(finalised.or(refused)).toBeVisible();
    if (await refused.isVisible()) {
      await card
        .getByRole('textbox', { name: /Reason for billing a surcharge below cost/ })
        .fill('Surcharge absorbed for this customer (e2e finance test).');
      await card.getByRole('button', { name: 'Finalise quote' }).click();
    }
    await expect(finalised).toBeVisible();

    // --- Issue the invoice and open it -------------------------------------------------
    await card.getByRole('button', { name: /Issue invoice/ }).click();
    const invoiceLink = card.getByRole('link', { name: /^INV-\d+$/ });
    await expect(invoiceLink).toBeVisible();
    const invoiceNumber = (await invoiceLink.textContent()).trim();
    await invoiceLink.click();
    await expect(page).toHaveURL(/\/finance\/invoices\/\d+$/);
    const invoiceUrl = page.url();
    await expect(page.getByRole('heading', { level: 1 })).toContainText(invoiceNumber);
    await expect(page.getByText(/selling rate on the invoice date/)).toBeVisible();

    // --- A partial payment and its receipt ---------------------------------------------
    await page.getByRole('textbox', { name: /Amount received \(CAD\)/ }).fill('1.00');
    await page.getByRole('button', { name: 'Record payment' }).click();
    const receiptLink = page.getByRole('link', { name: /Print receipt RCT-\d+/ });
    await expect(receiptLink).toBeVisible();
    await expect(page.getByRole('cell', { name: /^RCT-\d+$/ })).toBeVisible();
    await expect(page.getByText('Partly paid').first()).toBeVisible();
    await receiptLink.click();
    await expect(page).toHaveURL(/\/finance\/receipts\/\d+\/print$/);
    await expect(page.getByRole('heading', { level: 1 })).toContainText(/RCT-\d+/);
    await expect(page.getByText(/795093756RT0001/)).toBeVisible();

    // --- The printable invoice ---------------------------------------------------------
    await page.goto(`${invoiceUrl}/print`);
    await expect(page.getByRole('heading', { level: 1 })).toContainText(invoiceNumber);
    // OD-64: the company and the GST/HST rate chosen at issue (0 % by default). DEC-0235
    // (owner Ben, 2026-10-24): the Solaris Invoicing layout -- each line's Tax column reads
    // "Zero-rated" and the summary row "GST @ 0%", in English for every customer.
    await expect(page.getByText(/795093756RT0001/)).toBeVisible();
    await expect(page.getByRole('cell', { name: 'Zero-rated' }).first()).toBeVisible();
    await expect(page.getByText(/^GST @ 0%$/)).toBeVisible();
    const printed = await page.locator('article.fin-document').innerText();
    expect(printed).not.toMatch(/cost|margin|vendor|cash buying|exchange rate/i);
    expect(printed).not.toContain(masterReference);

    // --- Book the master, then enter and approve the vendor's bill --------------------
    await page.goto(workspaceUrl);
    await page.getByRole('button', { name: 'Book with vendor' }).click();
    const startBill = page.getByRole('button', { name: 'Enter bill (start from the estimate)' });
    await expect(startBill).toBeVisible();
    await startBill.click();
    await expect(page.getByRole('textbox', { name: 'Amount 1' })).not.toHaveValue('');
    await page.getByRole('button', { name: 'Save bill' }).click();
    const approve = page.getByRole('button', { name: 'Approve and split the cost' });
    await expect(approve).toBeVisible();
    const approval = page.waitForResponse(
      (item) => /\/api\/v1\/vendor-invoices\/\d+\/approve$/.test(item.url()) && item.request().method() === 'POST',
    );
    await approve.click();
    if (!(await approval).ok()) {
      await page
        .getByRole('textbox', { name: /Reason for the difference/ })
        .fill('Rounding between the bill and the estimate (e2e finance test).');
      await approve.click();
    }
    await expect(page.getByRole('list', { name: 'Actual cost by customer' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Mark paid' })).toBeVisible();

    // --- Finance › Profitability shows the master --------------------------------------
    await page.getByRole('link', { name: 'Finance' }).click();
    await expect(page.getByRole('heading', { name: 'Finance', level: 1 })).toBeVisible();
    await page.getByRole('tab', { name: 'Profitability' }).click();
    const row = page.getByRole('row').filter({ hasText: masterReference });
    await expect(row).toBeVisible();
  });
});
