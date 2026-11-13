/**
 * Phase 13G (OD-77, D-08): staff send a finalised quote; the customer accepts it in the
 * Customer Account.
 *
 * Set-up goes through the staff API with the reviewer's own session and CSRF token, as
 * `accountBooking.js` does for shipments: a fresh customer is approved, one Vietnam →
 * Canada shipment is booked for them, put on an air master, priced, its rate confirmed and
 * the quote finalised. Then the journey is all screens: staff press "Send to customer" in
 * the workspace; the customer opens Quotes from the account navigation, reads the charges,
 * accepts after the confirmation, and staff see "Accepted" in the workspace. Nothing about
 * cost reaches the customer's pages. Phase 15: with no invoice yet, staff see "Customer
 * accepted v1 — issue the invoice" in the workspace and under Finance, follow it to the
 * draft invoice prepared on acceptance (owner decision 9a) and send it; the prompt then
 * goes. Test data only, in this run's scratch database; the quote-sent email goes to the
 * run's capture directory.
 */

import { expect, test } from './diagnostics.js';
import { auditAndAssert, settle } from './axeHelpers.js';
import { bookShipment } from './accountBooking.js';
import { activatedCustomer, closeStaffContext, signIn, staffContext } from './accountHelpers.js';

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

/** A finalised quote for one new VCA shipment of `email`'s customer. */
async function finalisedQuoteFor(staffPage, email) {
  const headers = await staffHeaders(staffPage);
  const customers = await ok(
    await staffPage.request.get('/api/v1/customers', { params: { search: email, limit: 5 } }),
    'customer lookup',
  );
  const customer = customers.items.find((item) => item.email_entered === email) || customers.items[0];
  expect(customer, `no customer for ${email}`).toBeTruthy();

  const reference = await bookShipment(staffPage, customer.id, {
    routeGroup: 'VCA',
    contents: 'Synthetic E2E quote contents',
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
  await ok(
    await staffPage.request.post(`/api/v1/consolidations/${master.id}/members`, {
      headers,
      data: { shipment_id: shipment.id },
    }),
    'adding the shipment to the master',
  );
  await ok(
    await staffPage.request.post(`/api/v1/shipments/${shipment.id}/quotes`, { headers }),
    'pricing',
  );
  await ok(
    await staffPage.request.post(`/api/v1/shipments/${shipment.id}/quotes/confirm-rate`, {
      headers,
      data: {},
    }),
    'rate confirmation',
  );
  await ok(
    await staffPage.request.post(`/api/v1/shipments/${shipment.id}/quotes/finalize`, {
      headers,
      data: {},
    }),
    'finalisation',
  );
  return { masterId: master.id, reference };
}

test.describe('Customer quote acceptance', () => {
  test('staff send a finalised quote and the customer accepts it', async ({
    page,
    browser,
  }, testInfo) => {
    test.setTimeout(180_000);
    const { email } = await activatedCustomer(page, browser, { label: 'quotes' });

    // --- Staff: a finalised quote, sent from the workspace -----------------------------
    let staff = await staffContext(browser);
    let masterId;
    let reference;
    try {
      ({ masterId, reference } = await finalisedQuoteFor(staff.page, email));
      await staff.page.goto(`/workspace/${masterId}`);
      await expect(staff.page.getByText(/v1 · Finalised/)).toBeVisible();
      await expect(staff.page.getByText('This quote has not been sent to the customer.')).toBeVisible();
      await staff.page.getByRole('button', { name: /^Send to customer/ }).click();
      await expect(staff.page.getByText(/Sent — waiting for the customer/)).toBeVisible();
    } finally {
      await closeStaffContext(staff);
    }

    // --- Customer: Quotes, open it, accept after confirming -----------------------------
    await signIn(page, email);
    await page
      .getByRole('navigation', { name: 'Customer Account' })
      .getByRole('link', { name: 'Quotes' })
      .click();
    await expect(page.getByRole('heading', { name: 'Quotes', level: 1 })).toBeVisible();
    await page.getByRole('link', { name: `Open the quote for shipment ${reference}` }).click();
    await expect(
      page.getByRole('heading', { name: `Quote for shipment ${reference}`, level: 1 }),
    ).toBeVisible();
    await expect(page.getByText('Air Standard freight')).toBeVisible();
    const text = (await page.locator('main').innerText()).toLowerCase();
    for (const word of ['cost', 'vendor', 'markup', 'margin', 'kango', 'tariff']) {
      expect(text, `"${word}" on the customer's quote page`).not.toContain(word);
    }

    await settle(page);
    await auditAndAssert(page, 'account-quote-detail', testInfo);

    await page.getByRole('button', { name: 'Accept quote' }).click();
    const confirmation = page.getByRole('region', { name: 'Accept this quote?' });
    await expect(confirmation).toBeFocused();
    await page.getByRole('button', { name: 'Yes, accept the quote' }).click();
    await expect(page.getByText('Quote accepted.')).toBeVisible();
    await expect(page.getByText('You accepted this quote.')).toBeVisible();
    await expect(page.getByRole('button', { name: 'Accept quote' })).toHaveCount(0);

    const stored = await page.evaluate(() => ({
      local: window.localStorage.length,
      session: window.sessionStorage.length,
    }));
    expect(stored).toEqual({ local: 0, session: 0 });

    // --- Staff see the answer -----------------------------------------------------------
    staff = await staffContext(browser);
    try {
      await staff.page.goto(`/workspace/${masterId}`);
      await expect(staff.page.getByText(/v1 · Accepted/)).toBeVisible();

      // Phase 15: no invoice yet, so staff are prompted to issue it (nothing is automatic).
      const prompt = staff.page.getByText('Customer accepted v1 — issue the invoice');
      await expect(prompt).toBeVisible();

      // Finance lists it too, with a way back to the master.
      await staff.page.goto('/finance');
      const accepted = staff.page.getByRole('region', { name: 'Accepted, not invoiced' });
      await expect(accepted.getByText(reference)).toBeVisible();
      await settle(staff.page);
      await auditAndAssert(staff.page, 'staff-finance-accepted-not-invoiced', testInfo);
      await accepted.getByRole('link', { name: `Issue the invoice — ${reference}` }).click();
      await expect(staff.page).toHaveURL(new RegExp(`/workspace/${masterId}$`));

      // Owner decision 9a (2026-10-21): acceptance prepared the invoice as a draft. The
      // prompt's button moves to it; sending the draft issues the invoice and clears it.
      await staff.page.getByRole('button', { name: /^Go to Issue invoice/ }).click();
      const draftLink = staff.page.getByRole('link', { name: /^Review draft invoice — / });
      await expect(draftLink).toBeFocused();
      await draftLink.click();
      // RC-UAT-19 (OD-94): the GST/HST must be confirmed and saved before Send.
      await staff.page.getByLabel('I have checked the GST/HST on this invoice').check();
      await staff.page.getByRole('button', { name: 'Save draft' }).click();
      await expect(staff.page.getByText('Draft saved.')).toBeVisible();
      await staff.page.getByRole('button', { name: 'Send invoice' }).click();
      // Sending asks for confirmation first (RC-UAT-18 review fix M6).
      const sendDialog = staff.page.getByRole('dialog', { name: 'Send this invoice?' });
      await sendDialog.getByRole('button', { name: 'Send the invoice now' }).click();
      await expect(staff.page.getByRole('link', { name: /^INV-/ })).toBeVisible();
      await staff.page.goto(`/workspace/${masterId}`);
      await expect(staff.page.getByRole('link', { name: /^INV-/ })).toBeVisible();
      await expect(prompt).toHaveCount(0);
      await staff.page.goto('/finance');
      await expect(staff.page.getByRole('tab', { name: 'Invoices' })).toBeVisible();
      await expect(staff.page.getByRole('link', { name: /^INV-/ }).first()).toBeVisible();
      await expect(staff.page.getByText('Accepted, not invoiced')).toHaveCount(0);
    } finally {
      await closeStaffContext(staff);
    }
  });
});
