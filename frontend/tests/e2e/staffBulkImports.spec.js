/**
 * RC-UAT-21 Phase A: shipment import and legacy history baseline, end to end (DEC-0230).
 *
 * Real files through the real file input against the running application, synthetic data
 * only. What these prove: a dry run writes nothing; the import happens only after the
 * confirmation; a second import of the same references is refused; legacy history never
 * becomes an operational shipment; a baseline is voided as a whole.
 *
 * Every reference carries this run's marker so the spec can be re-run against the same
 * seeded database.
 */

import { expect, test } from './diagnostics.js';

function runId() {
  return `E2E${Date.now().toString(36).toUpperCase()}`;
}

function file(name, text) {
  return { name, mimeType: 'text/csv', buffer: Buffer.from(text, 'utf8') };
}

async function anyCustomer(request) {
  const page = await (await request.get('/api/v1/customers?limit=25')).json();
  const customer = page.items.find((item) => !item.is_archived) || page.items[0];
  expect(customer, 'the seeded database has a customer').toBeTruthy();
  return customer.public_id;
}

async function shipmentTotal(request) {
  return (await (await request.get('/api/v1/shipments?limit=1')).json()).total;
}

test.describe('Shipment import', () => {
  test('dry-runs without writing, imports on confirmation, refuses a duplicate', async ({
    page,
    request,
  }) => {
    const run = runId();
    const customer = await anyCustomer(request);
    const csv = file(
      'shipments.csv',
      'external_reference,customer_ref,recipient_name,recipient_city,recipient_country_code,' +
        'contents_description,package_weights_kg,transport_mode\r\n' +
        `${run}-S1,${customer},Trần Thị Thử,Toronto,CA,Quà tặng,3.5;2,air\r\n` +
        `${run}-S2,${customer},Lê Văn Thử,Toronto,CA,Quà tặng,1,ocean\r\n`,
    );
    const before = await shipmentTotal(request);

    await page.goto('/customers/import/shipments');
    await expect(page.getByRole('navigation', { name: 'Import type' })).toBeVisible();
    await page.setInputFiles('input[type="file"]', csv);
    await expect(page.getByText('Dry run only. Nothing has been imported.')).toBeVisible();
    await expect(page.getByText(/Only air shipments are imported in this release/)).toBeVisible();
    expect(await shipmentTotal(request)).toBe(before);

    await page.getByRole('button', { name: 'Import 1 row(s)' }).click();
    const dialog = page.getByRole('dialog');
    await expect(dialog.getByText(/No quote, invoice, email or milestone notification/)).toBeVisible();
    expect(await shipmentTotal(request)).toBe(before);
    await dialog.getByRole('button', { name: 'Import now' }).click();
    await expect(page.getByText('Import complete')).toBeVisible();
    expect(await shipmentTotal(request)).toBe(before + 1);

    // The same file again: the reference is refused as a duplicate, nothing to import.
    await page.getByRole('button', { name: 'Import another file' }).click();
    await page.setInputFiles('input[type="file"]', csv);
    await expect(page.getByText(/Already imported\. Duplicates are refused/)).toBeVisible();
    await expect(page.getByRole('button', { name: 'Nothing to import' })).toBeDisabled();
  });
});

test.describe('Legacy history baseline', () => {
  test('imports read-only history that never becomes operational, then voids it', async ({
    page,
    request,
  }) => {
    const run = runId();
    const customer = await anyCustomer(request);
    const csv = file(
      'history.csv',
      'legacy_reference,customer_ref,booked_on,final_status,recipient_name,recipient_city,' +
        'recipient_country_code,departed_on,delivered_on\r\n' +
        `${run}-L1,${customer},2024-03-01,delivered,Trần Thị Cũ,Toronto,CA,2024-03-05,2024-03-12\r\n`,
    );
    const before = await shipmentTotal(request);

    await page.goto('/customers/import/legacy');
    await page.setInputFiles('input[type="file"]', csv);
    await expect(page.getByText('Dry run only. Nothing has been imported.')).toBeVisible();
    await page.getByRole('button', { name: 'Import 1 row(s)' }).click();
    await page.getByRole('dialog').getByRole('button', { name: 'Import now' }).click();
    await expect(page.getByText('Import complete')).toBeVisible();

    // History, not an operational shipment.
    expect(await shipmentTotal(request)).toBe(before);
    await page.getByLabel('Search reference, customer or recipient').fill(`${run}-L1`);
    const row = page.getByRole('row', { name: new RegExp(`${run}-L1`) });
    await expect(row).toBeVisible();
    await expect(row.getByText('Legacy')).toBeVisible();

    // Void the baseline this run created, with a reason.
    const batch = (await page.getByText(/Batch IMP-\d+ is recorded/).textContent()).match(
      /IMP-\d+/,
    )[0];
    await page.getByRole('button', { name: `Void baseline ${batch}` }).click();
    const dialog = page.getByRole('dialog');
    await dialog.getByLabel(/Reason/).fill('E2E synthetic baseline');
    await dialog.getByRole('button', { name: 'Void baseline' }).click();
    await expect(dialog).toBeHidden();
    await expect(page.getByText('No legacy shipments')).toBeVisible();
  });
});
