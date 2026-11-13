/**
 * Fix pack 2, staff side, in a real browser: tags on the customer list (UAT-OP-17) and the
 * merge confirmation text (item 4). Read-only: the merge dialog is opened and cancelled.
 */

import { expect, test } from './diagnostics.js';

test.describe('Customer list tags', () => {
  test('shows a Tags column and filters by tag from More filters', async ({ page }) => {
    await page.goto('/customers');
    const table = page.getByRole('table', { name: 'Customers' });
    await expect(table.getByRole('columnheader', { name: 'Tags' })).toBeVisible();
    await expect(table.getByText('Frequent shipper').first()).toBeVisible();

    await page.getByRole('button', { name: 'More filters' }).click();
    const listed = page.waitForResponse(
      (response) =>
        response.url().includes('/api/v1/customers?') &&
        response.url().includes('tag_id=') &&
        response.status() === 200,
    );
    await page.getByLabel('Tag', { exact: true }).selectOption({ label: 'Needs documents' });
    const payload = await (await listed).json();

    await expect(page.getByText('Tag: Needs documents')).toBeVisible();
    expect(payload.items.length).toBeGreaterThan(0);
    for (const customer of payload.items) {
      expect(customer.tags.map((tag) => tag.name)).toContain('Needs documents');
    }
  });
});

test.describe('Merge confirmation', () => {
  test('names both customers, with no placeholder left in the sentence', async ({ page, request }) => {
    const found = await (
      await request.get('/api/v1/customers', { params: { q: 'hanh.uat@example.com' } })
    ).json();
    expect(found.items.length).toBe(1);
    const p1 = found.items[0];

    await page.goto(`/customers/${p1.id}?tab=duplicates`);
    await expect(page.getByRole('table', { name: /Compare with/ }).first()).toBeVisible();
    await page.getByRole('button', { name: 'Merge' }).first().click();
    const dialog = page.getByRole('dialog', { name: 'Merge these two customers' });
    const text = await dialog.innerText();

    expect(text).not.toMatch(/\{source\}|\{target\}/);
    expect(text).toContain(`move to ${p1.public_id};`);
    await dialog.getByRole('button', { name: 'Cancel' }).click();
    await expect(dialog).toHaveCount(0);
  });
});
