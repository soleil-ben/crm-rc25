/**
 * Owner decision 8 (Louis Tong, 2026-10-21), end to end through the screens: once a master is
 * booked its items and fees are locked. The lock badge shows, the item and fee controls are
 * disabled with the reason, an Admin unlocks it with a reason, an edit is then possible,
 * and Lock again restores the lock. The staff session of this project is an Admin.
 *
 * Every step is a click or a keystroke; the API is only listened to. Test data only.
 */

import { expect, test } from './diagnostics.js';
import { addMemberBySearch, createMaster } from './workspaceHelpers.js';

test.describe('Master edit lock', () => {
  test('a booked master locks items and fees; Admin unlocks with a reason and locks again', async ({
    page,
  }) => {
    test.setTimeout(120_000);
    const { consolidationId } = await createMaster(page, 'LOCK');
    expect(await addMemberBySearch(page, consolidationId, 'SX-VCA')).toBe(true);
    const card = page.locator('section.ws-customers').locator('section.card').first();
    await expect(card.getByRole('heading', { level: 3 })).toBeVisible();

    // An item while the master is open: no lock yet.
    await card.getByRole('button', { name: 'Add item' }).click();
    await card.getByRole('textbox', { name: /Description/ }).fill('Giày thể thao');
    await card.getByRole('button', { name: 'Add item' }).click();
    await expect(card.getByText('Giày thể thao')).toBeVisible();
    await expect(page.getByText('Items and fees locked')).toHaveCount(0);

    // Booked: the badge, the banner, and disabled controls with the reason.
    await page.getByRole('button', { name: 'Book with vendor' }).click();
    await expect(page.getByText('Items and fees locked')).toBeVisible();
    await expect(page.getByText('Items and fees are locked')).toBeVisible();
    await expect(card.getByText(/Locked: this master is booked/)).toBeVisible();
    await expect(card.getByRole('button', { name: /^Edit item — Giày thể thao/ })).toBeDisabled();
    await expect(card.getByRole('button', { name: /^Add fee — Giày thể thao/ })).toBeDisabled();
    await expect(card.getByRole('button', { name: 'Add item' })).toBeDisabled();

    // Admin unlocks: the reason is required.
    await page.getByRole('button', { name: 'Unlock for edits' }).click();
    const dialog = page.getByRole('dialog', { name: 'Unlock this master for edits' });
    const confirm = dialog.getByRole('button', { name: 'Unlock for edits' });
    await expect(confirm).toBeDisabled();
    await dialog.getByRole('textbox', { name: /Reason/ }).fill('Customer added a second pair (e2e).');
    const unlocked = page.waitForResponse(
      (item) =>
        item.url().includes(`/api/v1/consolidations/${consolidationId}/unlock`) &&
        item.request().method() === 'POST',
    );
    await confirm.click();
    expect((await unlocked).ok()).toBe(true);
    await expect(page.getByText('Unlocked for edits').first()).toBeVisible();
    await expect(page.getByText(/Customer added a second pair \(e2e\)/)).toBeVisible();

    // While unlocked, an edit goes through.
    const edit = card.getByRole('button', { name: /^Edit item — Giày thể thao/ });
    await expect(edit).toBeEnabled();
    await edit.click();
    await card.getByRole('textbox', { name: /Quantity/ }).fill('2');
    const saved = page.waitForResponse(
      (item) => /\/api\/v1\/shipments\/\d+\/items\/\d+$/.test(item.url()) && item.request().method() === 'PATCH',
    );
    await card.getByRole('button', { name: 'Save item' }).click();
    expect((await saved).ok()).toBe(true);

    // Lock again: the lock is back.
    const relocked = page.waitForResponse(
      (item) =>
        item.url().includes(`/api/v1/consolidations/${consolidationId}/relock`) &&
        item.request().method() === 'POST',
    );
    await page.getByRole('button', { name: 'Lock again' }).click();
    expect((await relocked).ok()).toBe(true);
    await expect(page.getByText('Items and fees locked')).toBeVisible();
    await expect(card.getByRole('button', { name: 'Add item' })).toBeDisabled();
  });
});
