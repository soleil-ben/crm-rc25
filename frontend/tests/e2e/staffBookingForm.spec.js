/**
 * RC-UAT-25 (Ben's live UAT, 2026-10-25), the Create booking form end to end:
 *
 * * item 1 — required fields carry a red asterisk beside the label, and no "(Required)"
 *   words; the asterisk is aria-hidden and the control is aria-required;
 * * item 3 — step 2's Currency is a list: blank, CAD, VND; the draft stores the choice;
 * * item 4 — step 3's recipient has "Use a saved address", and it offers the customer's
 *   sender-only address (the shape a Customer Account registration leaves), which fills
 *   the recipient fields and is accepted by the server.
 *
 * The customer and its one saved address are made here through the staff API, with this
 * project's own session and CSRF token. Test data only, in this run's scratch database.
 */

import { expect, test } from './diagnostics.js';

async function staffHeaders(page) {
  const cookies = await page.context().cookies();
  const csrf = cookies.find((cookie) => cookie.name === 'solaris_csrf');
  expect(csrf, 'the staff context has no CSRF cookie').toBeTruthy();
  return { 'X-CSRF-Token': csrf.value };
}

async function ok(response, what) {
  expect(response.ok(), `${what} failed: ${response.status()} ${await response.text()}`).toBe(true);
  return response.json();
}

/** A customer whose only saved address is a *sender* address in Vietnam. */
async function customerWithSenderAddress(page, tag) {
  const headers = await staffHeaders(page);
  const customer = await ok(
    await page.request.post('/api/v1/customers', {
      headers,
      data: {
        full_name: `E2E Booking ${tag}`,
        email: `e2e.booking.${tag.toLowerCase()}@example.com`,
        country_code: 'CA',
        acknowledge_duplicates: true,
      },
    }),
    'customer creation',
  );
  await ok(
    await page.request.post(`/api/v1/customers/${customer.id}/addresses`, {
      headers,
      data: {
        label: 'Nhà ở Sài Gòn',
        role: 'sender',
        contact_name: 'Trần Thị Thử',
        phone_entered: '+84 90 555 0101',
        address_line1: '125 Nguyễn Huệ',
        city: 'Thành phố Hồ Chí Minh',
        province_state: 'Hồ Chí Minh',
        country_code: 'VN',
      },
    }),
    'address creation',
  );
  return customer;
}

test('Create booking: red asterisks, a currency list, and a saved recipient address', async ({
  page,
}) => {
  const tag = `RC25${Date.now().toString(36).toUpperCase()}`;
  const customer = await customerWithSenderAddress(page, tag);

  await page.goto('/shipments/new');
  await page.getByRole('searchbox', { name: /Find a customer/i }).fill(`E2E Booking ${tag}`);
  await page.getByRole('button', { name: new RegExp(customer.public_id) }).click();
  await expect(page.getByText('Selected customer')).toBeVisible();
  await page.getByRole('button', { name: 'Continue' }).click();
  await expect(page.getByRole('heading', { name: 'Route and service' })).toBeVisible();

  // Item 1: the label alone is the name; the star is beside it, red, and hidden from AT.
  const route = page.getByLabel('Route group', { exact: true });
  await expect(route).toHaveAttribute('aria-required', 'true');
  const star = page.locator('.field-label-row', { has: page.locator('label', { hasText: /^Route group$/ }) }).locator('.required-mark');
  await expect(star).toBeVisible();
  await expect(star).toHaveText('*');
  await expect(star).toHaveAttribute('aria-hidden', 'true');
  await expect(star).toHaveCSS('color', 'rgb(180, 35, 24)');
  await expect(page.getByText(/\((required|bắt buộc)\)/i)).toHaveCount(0);

  // Item 3: a list, optional, with no default.
  const currency = page.getByLabel('Currency', { exact: true });
  await expect(currency).toHaveJSProperty('tagName', 'SELECT');
  await expect(currency).toHaveValue('');
  await expect(currency.locator('option')).toHaveText([
    '—',
    'CAD — Canadian dollar',
    'VND — Vietnamese dong',
  ]);
  await route.selectOption('CAV');
  await page.getByLabel('Contents description', { exact: true }).fill('Quà tặng gia đình (E2E)');
  await page.getByLabel('Declared value', { exact: true }).fill('150');
  await currency.selectOption('VND');
  await page.getByRole('button', { name: 'Continue' }).click();
  await expect(page.getByRole('heading', { name: 'Sender and recipient' })).toBeVisible();

  // Item 4: the recipient picker offers the sender-only address, and it fills the fields.
  const recipient = page.getByRole('region', { name: 'Recipient' });
  const picker = recipient.getByLabel('Use a saved address', { exact: true });
  await expect(picker.locator('option')).toHaveText([
    'Enter details manually',
    'Nhà ở Sài Gòn — Trần Thị Thử, Thành phố Hồ Chí Minh (saved as sender)',
  ]);
  await picker.selectOption({ label: 'Nhà ở Sài Gòn — Trần Thị Thử, Thành phố Hồ Chí Minh (saved as sender)' });
  await expect(recipient.getByLabel('Full name', { exact: true })).toHaveValue('Trần Thị Thử');
  await expect(recipient.getByLabel('City', { exact: true })).toHaveValue('Thành phố Hồ Chí Minh');
  await expect(recipient.getByLabel('Country', { exact: true })).toHaveValue('VN');

  const sender = page.getByRole('region', { name: 'Sender' });
  await sender.getByLabel('Full name', { exact: true }).fill('E2E Counter');
  await sender.getByLabel('Country', { exact: true }).fill('CA');

  // The server accepts the draft: the currency and the recipient snapshot are stored.
  const saved = page.waitForResponse(
    (response) =>
      response.url().endsWith('/api/v1/shipments') && response.request().method() === 'POST',
  );
  await page.getByRole('button', { name: 'Save draft' }).click();
  const draft = await ok(await saved, 'draft save');
  const detail = await ok(await page.request.get(`/api/v1/shipments/${draft.id}`), 'draft read');
  // This project's staff session is an Admin, who reads the financials block.
  expect(detail.financials.declared_value_currency).toBe('VND');
  expect(detail.recipient.city).toBe('Thành phố Hồ Chí Minh');
  expect(detail.recipient.name).toBe('Trần Thị Thử');
});
