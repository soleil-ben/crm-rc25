/**
 * Owner decision 9a (Louis Tong, 2026-10-21), end to end: the customer accepts a quote in the
 * Customer Account, and its invoice is waiting for staff as a **draft**. Staff open it from
 * the workspace, edit the customer's reference, find Send and Download blocked until they
 * save, save, download the draft PDF (a real PDF from the server), and send it after a
 * confirmation naming the number, total and email address: the
 * numbered invoice is issued and the invoice email lands in this run's capture directory.
 *
 * RC-UAT-19 (owner, 2026-10-22): Send and Save wait for "I have checked the GST/HST on this
 * invoice", and changing the rate clears it; the issued invoice's total is the accepted all-in
 * total. RC-UAT-20 (owner, 2026-10-23): the rate follows the route -- this VN-CA shipment
 * starts zero-rated (0 %, DEC-0227) -- and Download, like Send, waits for a confirmed save
 * (DEC-0229). Staff still choose 13 % here, included in the price.
 *
 * Set-up goes through the staff API with the reviewer's own session and CSRF token, as
 * `accountQuotes.spec.js` does. Test data only, in this run's scratch database.
 */

import { readFileSync } from 'node:fs';
import { expect, test } from './diagnostics.js';
import { bookShipment } from './accountBooking.js';
import { activatedCustomer, closeStaffContext, signIn, staffContext } from './accountHelpers.js';
import { messagesFor } from './mailCapture.js';

async function staffHeaders(staffPage) {
  const cookies = await staffPage.context().cookies();
  const csrf = cookies.find((cookie) => cookie.name === 'solaris_csrf');
  expect(csrf, 'the staff context has no CSRF cookie').toBeTruthy();
  return { 'X-CSRF-Token': csrf.value };
}

async function ok(response, what) {
  expect(response.ok(), `${what} failed: ${response.status()} ${await response.text()}`).toBe(true);
  return response.json();
}

/** A sent quote for one new VCA shipment of `email`'s customer. */
async function sentQuoteFor(staffPage, email) {
  const headers = await staffHeaders(staffPage);
  const customers = await ok(
    await staffPage.request.get('/api/v1/customers', { params: { search: email, limit: 5 } }),
    'customer lookup',
  );
  const customer = customers.items.find((item) => item.email_entered === email) || customers.items[0];
  const reference = await bookShipment(staffPage, customer.id, {
    routeGroup: 'VCA',
    contents: 'Synthetic E2E draft-invoice contents',
  });
  const shipments = await ok(
    await staffPage.request.get('/api/v1/shipments', { params: { search: reference, limit: 5 } }),
    'shipment lookup',
  );
  const shipment = shipments.items.find((item) => item.public_id === reference);
  const master = await ok(
    await staffPage.request.post('/api/v1/consolidations', {
      headers,
      data: { solaris_service: 'air_standard', origin: 'HCM', actual_weight_kg: '21' },
    }),
    'master creation',
  );
  const base = `/api/v1/shipments/${shipment.id}`;
  await ok(
    await staffPage.request.post(`/api/v1/consolidations/${master.id}/members`, {
      headers,
      data: { shipment_id: shipment.id },
    }),
    'adding the shipment to the master',
  );
  await ok(await staffPage.request.post(`${base}/quotes`, { headers }), 'pricing');
  await ok(
    await staffPage.request.post(`${base}/quotes/confirm-rate`, { headers, data: {} }),
    'rate confirmation',
  );
  await ok(
    await staffPage.request.post(`${base}/quotes/finalize`, { headers, data: {} }),
    'finalisation',
  );
  await ok(await staffPage.request.post(`${base}/quotes/send`, { headers }), 'sending');
  return { masterId: master.id, reference };
}

test.describe('Draft invoice on acceptance', () => {
  test('accept → draft for staff → edit → Send blocked until Save → Download PDF → Send', async ({
    page,
    browser,
  }) => {
    test.setTimeout(180_000);
    const { email } = await activatedCustomer(page, browser, { label: 'draftinvoice' });

    let staff = await staffContext(browser);
    let masterId;
    let reference;
    try {
      ({ masterId, reference } = await sentQuoteFor(staff.page, email));
    } finally {
      await closeStaffContext(staff);
    }

    // --- The customer accepts -------------------------------------------------------------
    await signIn(page, email);
    await page.goto('/account/quotes');
    await page.getByRole('link', { name: `Open the quote for shipment ${reference}` }).click();
    await page.getByRole('button', { name: 'Accept quote' }).click();
    await page.getByRole('button', { name: 'Yes, accept the quote' }).click();
    await expect(page.getByText('Quote accepted.')).toBeVisible();

    // --- Staff: the draft is waiting in the workspace --------------------------------------
    staff = await staffContext(browser);
    try {
      const staffPage = staff.page;
      await staffPage.goto(`/workspace/${masterId}`);
      await expect(
        staffPage.getByText('The customer accepted this quote; its invoice is ready as a draft.'),
      ).toBeVisible();
      await staffPage.getByRole('link', { name: /^Review draft invoice — / }).click();
      await expect(staffPage).toHaveURL(/\/finance\/invoice-drafts\/\d+$/);
      const draftId = staffPage.url().split('/').pop();
      await expect(staffPage.getByText(/No invoice number yet/)).toBeVisible();

      const send = staffPage.getByRole('button', { name: 'Send invoice' });
      const download = staffPage.getByRole('button', { name: 'Download PDF (draft)' });
      const save = staffPage.getByRole('button', { name: 'Save draft' });
      const taxBox = staffPage.getByLabel('I have checked the GST/HST on this invoice');

      // GST/HST by route: VN-CA is zero-rated, not yet confirmed -- Send and Download wait.
      await expect(staffPage.getByTestId('draft-tax-route')).toContainText(
        'international, zero-rated (0 %)',
      );
      await expect(staffPage.getByTestId('draft-tax-summary')).toContainText(
        'GST/HST 0 % (zero-rated)',
      );
      await expect(taxBox).not.toBeChecked();
      await expect(send).toBeDisabled();
      await expect(download).toBeDisabled();
      await expect(staffPage.getByText(/GST\/HST of the saved draft is not confirmed/)).toBeVisible();

      // Changing the rate clears the box; Save needs it again.
      await taxBox.check();
      await staffPage.getByLabel('GST/HST', { exact: true }).selectOption('5');
      await expect(taxBox).not.toBeChecked();
      await expect(save).toBeDisabled();
      await staffPage.getByLabel('GST/HST', { exact: true }).selectOption('13');
      await expect(staffPage.getByTestId('draft-tax-summary')).toContainText(
        'Tax included in the price',
      );
      await taxBox.check();
      await save.click();
      await expect(staffPage.getByText('Draft saved.')).toBeVisible();
      await expect(send).toBeEnabled();

      // An unsaved edit blocks Send and Download.
      await staffPage.getByRole('textbox', { name: /Customer reference \/ PO/ }).fill('PO-E2E-9A');
      await expect(staffPage.getByText(/Save your changes first/)).toBeVisible();
      await expect(send).toBeDisabled();
      await expect(download).toBeDisabled();

      // Save (the confirmed box stays ticked on a reference-only edit): both come back.
      await expect(taxBox).toBeChecked();
      await save.click();
      await expect(staffPage.getByText('Draft saved.')).toBeVisible();
      await expect(staffPage.getByText(/Save your changes first/)).toHaveCount(0);
      await expect(send).toBeEnabled();
      await expect(download).toBeEnabled();

      // Download: the server's PDF of the saved draft.
      const pdfResponse = staffPage.waitForResponse(
        (item) => item.url().includes(`/api/v1/invoice-drafts/${draftId}/pdf`),
      );
      const fileEvent = staffPage.waitForEvent('download');
      await download.click();
      const pdf = await pdfResponse;
      expect(pdf.status()).toBe(200);
      expect(pdf.headers()['content-type']).toContain('application/pdf');
      // Chromium keeps no body for an attachment response; read the downloaded file instead.
      const file = await fileEvent;
      expect(file.suggestedFilename()).toMatch(/\.pdf$/);
      expect(readFileSync(await file.path()).subarray(0, 4).toString()).toBe('%PDF');

      // Send: the numbered invoice, and the invoice email in the capture directory.
      const sent = staffPage.waitForResponse(
        (item) =>
          item.url().includes(`/api/v1/invoice-drafts/${draftId}/send`) &&
          item.request().method() === 'POST',
      );
      await send.click();
      // The confirmation names what happens, the total and where the email goes.
      const dialog = staffPage.getByRole('dialog', { name: 'Send this invoice?' });
      await expect(dialog.getByText(/An invoice number will be assigned/)).toBeVisible();
      await expect(dialog.getByText(`The invoice will be emailed to ${email}.`)).toBeVisible();
      await dialog.getByRole('button', { name: 'Send the invoice now' }).click();
      const body = await (await sent).json();
      expect(body.invoice_public_id).toMatch(/^INV-/);
      // Included in the price: the total is the lines' all-in sum, the tax backed out of it.
      expect(body.draft.tax_mode).toBe('included');
      expect(body.draft.total_cad).toBe(body.draft.lines_total_cad);
      expect(
        (Number(body.draft.subtotal_cad) + Number(body.draft.tax_cad)).toFixed(2),
      ).toBe(body.draft.total_cad);
      await expect(staffPage.getByRole('link', { name: body.invoice_public_id })).toBeVisible();
      await expect.poll(() => messagesFor(email).filter((m) => m.template_key.startsWith('invoice.sent.')).length).toBe(1);
      const message = messagesFor(email).find((m) => m.template_key.startsWith('invoice.sent.'));
      expect(message.body).toContain(body.invoice_public_id);
      expect(message.body.toLowerCase()).not.toContain('kango');
    } finally {
      await closeStaffContext(staff);
    }
  });
});
