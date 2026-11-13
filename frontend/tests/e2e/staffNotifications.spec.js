/**
 * Milestone notifications (Phase 13F, OD-72), staff side, end to end.
 *
 * An administrator records a published "Received at warehouse" milestone (RC-UAT-25 item 5:
 * formerly "Received at Solaris"; the stored code is unchanged) on a seeded confirmed shipment
 * through the shipment detail screen, corrects it (RC-UAT-25 item 6: an edit of a published
 * event is warned about, needs a reason, is kept in the edit history and emails nobody), then
 * opens Settings → Customer notifications and finds that shipment's row with a status. The run's transport is the test capture one,
 * so nothing reaches anybody (test capture only).
 *
 * The shipment is picked from those not yet received (booked or awaiting the parcel), because
 * a step behind the shipment's status rightly notifies nothing. The API is only read, to
 * choose the shipment and to confirm the row the screen shows.
 */

import { expect, test } from './diagnostics.js';

const STATUS_LABELS = /Captured \(test\)|Recorded, not sent|Queued|Sending|Skipped|Failed/;

async function notYetReceivedShipment(request) {
  const params = new URLSearchParams({ limit: '100', sort: 'booking_date', direction: 'asc' });
  params.append('booking_state', 'confirmed');
  params.append('operational_state', 'booked');
  params.append('operational_state', 'awaiting_parcel');
  const response = await request.get(`/api/v1/shipments?${params}`);
  expect(response.ok()).toBe(true);
  const list = await response.json();
  return list.items.find((item) => item.public_id);
}

test.describe('Customer notifications', () => {
  test('a published milestone recorded on the shipment shows in Settings with a status', async ({
    page,
  }) => {
    test.setTimeout(90_000);
    const shipment = await notYetReceivedShipment(page.request);
    expect(shipment, 'the seed has no confirmed shipment that is not yet received').toBeTruthy();

    // --- Record the milestone through the shipment screen ---------------------------------
    await page.goto(`/shipments/${shipment.id}`);
    await expect(page.getByRole('heading', { name: new RegExp(shipment.public_id) })).toBeVisible();
    await page.getByRole('button', { name: 'Record event' }).click();
    await page.getByLabel('Event type').selectOption('received_at_solaris');
    const publish = page.getByLabel('Publish this update to the customer');
    await publish.check();
    await expect(publish).toBeChecked();
    // A milestone with no approved template needs wording of its own.
    const ownWording = page.getByRole('textbox', { name: /Public wording/ });
    if (await ownWording.isVisible().catch(() => false)) {
      await ownWording.fill('Your parcel has arrived at our warehouse.');
    }
    const recorded = page.waitForResponse(
      (response) =>
        response.url().includes(`/api/v1/shipments/${shipment.id}/events`) &&
        response.request().method() === 'POST',
    );
    await page.getByRole('button', { name: 'Record event' }).click();
    expect((await recorded).status()).toBe(201);
    await expect(page.getByText('Received at warehouse').first()).toBeVisible();

    // --- Correct the published milestone: warned, reasoned, recorded, no new email --------
    await page.getByRole('button', { name: 'Edit: Received at warehouse' }).first().click();
    const editForm = page.getByRole('form', { name: 'Edit this event' });
    await expect(editForm.getByText(/already published to the customer/)).toBeVisible();
    await editForm.getByLabel('Location').fill('Mississauga warehouse');
    await editForm.getByLabel('Reason for the correction').fill('The parcel came in at Mississauga.');
    const edited = page.waitForResponse(
      (response) =>
        response.url().includes(`/api/v1/shipments/${shipment.id}/events/edit`) &&
        response.request().method() === 'POST',
    );
    await editForm.getByRole('button', { name: 'Save correction' }).click();
    expect((await edited).status()).toBe(200);
    await expect(page.getByText(/Mississauga warehouse/).first()).toBeVisible();
    await page.getByText('Edit history').click();
    await expect(page.getByText('The parcel came in at Mississauga.')).toBeVisible();

    // --- The server queued exactly one notification for it -------------------------------
    const api = await page.request.get(`/api/v1/notifications?shipment_id=${shipment.id}`);
    expect(api.ok()).toBe(true);
    const outbox = await api.json();
    expect(outbox.items.map((item) => item.milestone)).toEqual(['received']);
    expect(JSON.stringify(outbox)).not.toContain('@');

    // --- Settings → Customer notifications shows the row with a status --------------------
    await page.goto('/settings');
    await expect(page.getByRole('heading', { name: 'Settings', level: 1 })).toBeVisible();
    await page.getByRole('tab', { name: 'Customer notifications' }).click();
    await expect(page.getByText(/Test capture only/)).toBeVisible();
    const row = page
      .getByRole('row')
      .filter({ has: page.getByRole('link', { name: shipment.public_id }) });
    await expect(row).toHaveCount(1);
    await expect(row).toContainText('Received');
    await expect(row).toContainText(STATUS_LABELS);
    await expect(row.getByRole('link', { name: shipment.public_id })).toHaveAttribute(
      'href',
      `/shipments/${shipment.id}`,
    );
  });
});
