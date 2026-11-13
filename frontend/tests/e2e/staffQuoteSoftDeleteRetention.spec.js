/**
 * RC-UAT-21 Phase D (DEC-0233), end to end through the screens. The staff session of this
 * project is an Admin.
 *
 * * A customer's quote is finalised twice (v1 superseded by v2). In the workspace's Admin
 *   quote history, v1 is deleted with a reason: it disappears, "Show deleted" brings it back
 *   with who deleted it and why, and Restore (with a reason) restores it.
 * * Settings → Retention says plainly that retention periods are undecided and that deletion
 *   is off; the switch cannot be turned on without the typed phrase; a dry run reports counts
 *   per record class and changes nothing.
 *
 * Every step is a click or a keystroke; the API is only listened to. Test data only.
 */

import { expect, test } from './diagnostics.js';
import { addMemberBySearch, createMaster } from './workspaceHelpers.js';

async function finalise(card, version) {
  await card.getByRole('button', { name: /Confirm selling rate/ }).click();
  await expect(card.getByText('Rate confirmed', { exact: true })).toBeVisible();
  await card.getByRole('button', { name: /Finalise quote/ }).click();
  const finalised = card.getByText(new RegExp(`v${version} · Finalised`));
  const refused = card.getByText('This quote cannot be finalised yet.');
  await expect(finalised.or(refused)).toBeVisible();
  if (await refused.isVisible()) {
    await card
      .getByRole('textbox', { name: /Reason for billing a surcharge below cost/ })
      .fill('Surcharge absorbed for this customer (e2e soft delete test).');
    await card.getByRole('button', { name: /Finalise quote/ }).click();
  }
  await expect(finalised).toBeVisible();
}

test.describe('Admin quote soft delete and retention', () => {
  test('deletes and restores an old quote version with reasons', async ({ page }) => {
    test.setTimeout(180_000);
    const { consolidationId } = await createMaster(page, 'QDEL');
    expect(await addMemberBySearch(page, consolidationId, 'SX-VCA')).toBe(true);
    const card = page.locator('section.ws-customers').locator('section.card').first();
    await expect(card.getByRole('heading', { level: 3 })).toBeVisible();

    await card.getByRole('button', { name: /Price quote/ }).click();
    await expect(card.getByText(/v1 · Draft/)).toBeVisible();
    await finalise(card, 1);
    await card.getByRole('button', { name: /Price quote/ }).click();
    await expect(card.getByText(/v2 · Draft/)).toBeVisible();
    await finalise(card, 2);

    await card.locator('summary', { hasText: 'Quote history (Admin)' }).click();
    const v1 = card.getByRole('row', { name: /^v1 / });
    await expect(v1).toContainText('Superseded');
    await v1.getByRole('button', { name: /^Delete quote v1/ }).click();
    const dialog = page.getByRole('dialog', { name: 'Delete quote v1' });
    const confirm = dialog.getByRole('button', { name: 'Delete the quote version' });
    await expect(confirm).toBeDisabled();
    await dialog.getByRole('textbox', { name: /Reason/ }).fill('Old superseded quote (e2e).');
    const deleted = page.waitForResponse(
      (item) => /\/api\/v1\/quote-versions\/\d+\/delete$/.test(item.url()) && item.request().method() === 'POST',
    );
    await confirm.click();
    expect((await deleted).ok()).toBe(true);
    await expect(dialog).toHaveCount(0);
    await expect(card.getByRole('row', { name: /^v1 / })).toHaveCount(0);
    await expect(card.getByRole('row', { name: /^v2 / })).toBeVisible();

    await card.getByLabel('Show deleted versions').check();
    const shown = card.getByRole('row', { name: /^v1 / });
    await expect(shown).toContainText('Deleted by');
    await expect(shown).toContainText('Old superseded quote (e2e).');
    await shown.getByRole('button', { name: /^Restore quote v1/ }).click();
    const restore = page.getByRole('dialog', { name: 'Restore quote v1' });
    await restore.getByRole('textbox', { name: /Reason/ }).fill('Needed after all (e2e).');
    const restored = page.waitForResponse(
      (item) => /\/api\/v1\/quote-versions\/\d+\/restore$/.test(item.url()) && item.request().method() === 'POST',
    );
    await restore.getByRole('button', { name: 'Restore the quote version' }).click();
    expect((await restored).ok()).toBe(true);
    await expect(card.getByRole('row', { name: /^v1 / })).not.toContainText('Deleted by');
  });

  test('Settings → Retention is off, undecided, and runs only a dry run', async ({ page }) => {
    await page.goto('/settings');
    await page.getByRole('tab', { name: 'Retention' }).click();
    await expect(page.getByText('Retention periods are not decided')).toBeVisible();
    await expect(page.getByText('Retention deletion is off.')).toBeVisible();
    const turnOn = page.getByRole('button', { name: 'Turn retention deletion on' });
    await expect(turnOn).toBeDisabled();
    await page.getByLabel(/To turn it on, type/).fill('please');
    await expect(turnOn).toBeDisabled();
    await expect(page.getByRole('row', { name: /Soft-deleted quotes/ })).toContainText('Disabled');
    await expect(page.getByRole('button', { name: 'Enable Soft-deleted quotes' })).toBeDisabled();

    const dry = page.waitForResponse(
      (item) => item.url().endsWith('/api/v1/admin/data-retention/dry-run') && item.request().method() === 'POST',
    );
    await page.getByRole('button', { name: 'Run a dry run' }).click();
    expect((await dry).ok()).toBe(true);
    await expect(page.getByRole('table', { name: /Dry run of/ })).toBeVisible();
    await expect(page.getByRole('row', { name: /Ended staff sessions No period set/ })).toBeVisible();
  });
});
