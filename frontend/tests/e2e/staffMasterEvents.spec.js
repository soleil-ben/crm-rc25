/**
 * Phase 14: a master milestone fans out to its member shipments (v2.1 Test 2), through the
 * screens only. An air master is created, a free early-journey Vietnam → Canada shipment is
 * added by search, an "In transit" milestone is recorded once on the master with the staff's
 * own customer-facing wording, and the member shipment's own timeline then shows it. The
 * master is then cancelled (behind its confirmation, with a reason), which releases the
 * shipment again. Air only; test data only; no email reaches anyone (capture transport).
 */

import { expect, test } from './diagnostics.js';
import { auditAndAssert, settle } from './axeHelpers.js';
import { addMemberBySearch, createMaster, pickFreeShipment } from './workspaceHelpers.js';

test.describe('Master milestones', () => {
  test('a milestone recorded on the master appears on the member shipment', async ({ page }, testInfo) => {
    test.setTimeout(120_000);
    const tag = Date.now().toString(36);
    const shipment = pickFreeShipment();

    const { consolidationId, reference } = await createMaster(page, 'EVT');
    expect(await addMemberBySearch(page, consolidationId, shipment.public_id)).toBe(true);
    const card = page.locator('section.ws-customers').locator('section.card').first();
    await expect(card.getByRole('heading', { level: 3 })).toContainText(shipment.public_id);

    // --- Record the milestone once, for the whole master --------------------------------
    await page.getByRole('button', { name: 'Record a milestone' }).click();
    const form = page.getByRole('form', { name: 'Record a milestone for the whole master' });
    await expect(form.getByRole('combobox', { name: /Event type/ })).toBeFocused();
    await form.getByRole('combobox', { name: /Event type/ }).selectOption('in_transit');
    await expect(form.getByRole('checkbox', { name: /Show this update to each customer/ })).toBeChecked();
    await form.getByRole('combobox', { name: /Standard update/ }).selectOption('');
    const wording = `Your parcel is on its way to Canada (${tag}).`;
    await form.getByRole('textbox', { name: /Public wording/ }).fill(wording);
    await settle(page);
    await auditAndAssert(page, 'staff-workspace-master-event', testInfo);
    await form.getByRole('button', { name: 'Record for all shipments' }).click();

    const outcome = page.getByRole('list', { name: 'What each shipment received' });
    await expect(outcome).toContainText(`Updated: ${shipment.public_id}`);

    // --- The member shipment's own timeline carries it ---------------------------------
    await page.goto(`/shipments/${shipment.id}`);
    await expect(page.getByRole('heading', { level: 1 })).toContainText(shipment.public_id);
    await expect(page.getByText(wording)).toBeVisible();

    // --- Cancel the master: confirmation, reason, then the members are released -------
    await page.goto(`/workspace/${consolidationId}`);
    await page.getByRole('button', { name: 'Cancel master' }).click();
    const dialog = page.getByRole('dialog', { name: `Cancel ${reference}` });
    await dialog.getByRole('button', { name: 'Cancel the master' }).click();
    await expect(dialog.getByText('Say why the master is being cancelled.')).toBeVisible();
    await dialog.getByRole('textbox', { name: /Why is the master/ }).fill(`E2E clean-up ${tag}`);
    await dialog.getByRole('button', { name: 'Cancel the master' }).click();
    await expect(page.getByText('The master is cancelled and its shipments are released.')).toBeVisible();
    await expect(page.getByText('Cancelled', { exact: true }).first()).toBeVisible();
    await expect(page.getByRole('button', { name: 'Record a milestone' })).toHaveCount(0);
  });
});
