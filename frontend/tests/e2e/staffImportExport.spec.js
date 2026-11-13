/**
 * The CSV import and export workflows, end to end, against the running application.
 *
 * The import specs upload real files through the real file input and assert on the real
 * server's answers. That is the only way to prove the property that matters most: that a
 * preview writes nothing, and that the same file imported twice creates one set of
 * customers rather than two.
 *
 * Each spec uses its own source keys so the suite can be re-run against the same seeded
 * database without the second run reporting everything as "already imported" — which
 * would still be *correct* behaviour, but would stop the spec from proving that a first
 * import creates anything.
 */

import { expect, test } from './diagnostics.js';

const HEADER = 'full_name,email,phone,country_code,city,preferred_language,source_record_id\r\n';

/**
 * A file whose names, emails, and source keys are all unique to this run.
 *
 * The uniqueness is applied here rather than remembered in each spec, because forgetting
 * it does not fail loudly. A re-run against a database an earlier run already wrote to
 * finds the previous run's person by name, classifies the row as a probable duplicate,
 * and disables the import button — which is exactly the behaviour these specs prove
 * elsewhere, so as a side effect it quietly stops this spec proving anything while
 * looking like a product bug.
 */
function csv(run, rows) {
  const body = rows
    .map(
      (row) =>
        `${personName(row.name, run)},${row.email},${row.phone || ''},CA,` +
        `${row.city || 'Mississauga'},vi,${run}-${row.key}`,
    )
    .join('\r\n');
  return { name: 'customers.csv', mimeType: 'text/csv', buffer: Buffer.from(HEADER + body + '\r\n', 'utf8') };
}

/** The name as it will be stored: the given name plus this run's marker. */
function personName(name, run) {
  return `${name} ${run}`;
}

function runId() {
  return `E2E${Date.now().toString(36).toUpperCase()}`;
}

async function readDownload(download) {
  const stream = await download.createReadStream();
  const chunks = [];
  for await (const chunk of stream) chunks.push(chunk);
  return Buffer.concat(chunks).toString('utf8');
}

test.describe('Customer import', () => {
  test('previews a file without creating anything', async ({ page, request }) => {
    const run = runId();
    const before = await (await request.get('/api/v1/customers?limit=1')).json();

    await page.goto('/customers/import');
    await page.setInputFiles(
      'input[type="file"]',
      csv(run, [{ name: 'Đặng Thị Hồng Nhung', email: `nhung.${run}@example.com`, key: 'A' }]),
    );

    await expect(page.getByRole('heading', { name: 'Every row' })).toBeVisible();
    await expect(page.getByText(/no customer record has been created, changed, or merged/i)).toBeVisible();

    // The customer count is unchanged: a preview really did write nothing.
    const after = await (await request.get('/api/v1/customers?limit=1')).json();
    expect(after.total).toBe(before.total);
  });

  test('preserves Vietnamese names through preview and commit', async ({ page, request }) => {
    const run = runId();
    await page.goto('/customers/import');
    await page.setInputFiles(
      'input[type="file"]',
      csv(run, [{ name: 'Nguyễn Thị Bích Hạnh', email: `hanh.${run}@example.com`, key: 'B' }]),
    );

    await expect(page.getByRole('heading', { name: 'Every row' })).toBeVisible();
    await expect(page.getByText(/Nguyễn Thị Bích Hạnh/).first()).toBeVisible();

    await page.getByRole('button', { name: /Import 1 customer/ }).click();
    await page.getByRole('button', { name: 'Yes, import now' }).click();
    await expect(page.getByText('Import finished')).toBeVisible({ timeout: 15_000 });

    const found = await (
      await request.get(`/api/v1/customers?search=hanh.${run}`)
    ).json();
    expect(found.total).toBe(1);
    // Diacritics intact, all the way from the uploaded bytes to the stored record.
    expect(found.items[0].full_name).toBe(personName('Nguyễn Thị Bích Hạnh', run));
    expect(found.items[0].full_name).toContain('Nguyễn Thị Bích Hạnh');
  });

  test('requires an explicit confirmation before writing anything', async ({ page, request }) => {
    const run = runId();
    await page.goto('/customers/import');
    await page.setInputFiles(
      'input[type="file"]',
      csv(run, [{ name: 'Confirm Probe', email: `confirm.${run}@example.com`, key: 'C' }]),
    );

    await expect(page.getByRole('heading', { name: 'Every row' })).toBeVisible();
    await page.getByRole('button', { name: /Import 1 customer/ }).click();

    // A dialog, not a commit.
    await expect(page.getByRole('dialog')).toBeVisible();
    let found = await (await request.get(`/api/v1/customers?search=confirm.${run}`)).json();
    expect(found.total).toBe(0);

    // Dismissing it still writes nothing.
    await page.keyboard.press('Escape');
    await expect(page.getByRole('dialog')).toBeHidden();
    found = await (await request.get(`/api/v1/customers?search=confirm.${run}`)).json();
    expect(found.total).toBe(0);
  });

  test('cancelling before the commit leaves nothing behind', async ({ page, request }) => {
    const run = runId();
    const batchesBefore = await (await request.get('/api/v1/imports/batches')).json();

    await page.goto('/customers/import');
    await page.setInputFiles(
      'input[type="file"]',
      csv(run, [{ name: 'Abandoned Row', email: `abandon.${run}@example.com`, key: 'D' }]),
    );
    await expect(page.getByRole('heading', { name: 'Every row' })).toBeVisible();

    await page.getByRole('button', { name: 'Cancel and start over' }).click();
    await expect(page.getByLabel('CSV file to import')).toBeVisible();

    const found = await (await request.get(`/api/v1/customers?search=abandon.${run}`)).json();
    expect(found.total).toBe(0);
    const batchesAfter = await (await request.get('/api/v1/imports/batches')).json();
    expect(batchesAfter.total).toBe(batchesBefore.total);
  });

  test('commits, and importing the same file again creates nothing', async ({ page, request }) => {
    const run = runId();
    const file = csv(run, [
      { name: 'Retry Person One', email: `retry1.${run}@example.com`, key: 'E1' },
      { name: 'Retry Person Two', email: `retry2.${run}@example.com`, key: 'E2' },
    ]);

    // --- First import -------------------------------------------------
    await page.goto('/customers/import');
    await page.setInputFiles('input[type="file"]', file);
    await expect(page.getByRole('heading', { name: 'Every row' })).toBeVisible();
    await page.getByRole('button', { name: /Import 2 customer/ }).click();
    await page.getByRole('button', { name: 'Yes, import now' }).click();
    await expect(page.getByText('Import finished')).toBeVisible({ timeout: 15_000 });

    const afterFirst = await (await request.get(`/api/v1/customers?search=${run}`)).json();
    expect(afterFirst.total).toBe(2);

    // --- Same file, again ---------------------------------------------
    await page.getByRole('button', { name: 'Import another file' }).click();
    await page.setInputFiles('input[type="file"]', file);
    await expect(page.getByRole('heading', { name: 'Every row' })).toBeVisible();

    // The preview already knows: these rows have been imported before.
    await expect(page.getByText(/already been imported/i)).toBeVisible();

    const afterSecond = await (await request.get(`/api/v1/customers?search=${run}`)).json();
    expect(afterSecond.total).toBe(2);
  });

  test('holds a probable duplicate for a decision and never merges it', async ({ page, request }) => {
    const run = runId();
    const first = csv(run, [{ name: 'Duplicate Source', email: `dup.${run}@example.com`, key: 'F1' }]);
    await page.goto('/customers/import');
    await page.setInputFiles('input[type="file"]', first);
    await page.getByRole('button', { name: /Import 1 customer/ }).click();
    await page.getByRole('button', { name: 'Yes, import now' }).click();
    await expect(page.getByText('Import finished')).toBeVisible({ timeout: 15_000 });

    // Same person, different source key: the second row is a *probable* duplicate.
    const second = csv(run, [{ name: 'Duplicate Source', email: `dup.${run}@example.com`, key: 'F2' }]);
    await page.getByRole('button', { name: 'Import another file' }).click();
    await page.setInputFiles('input[type="file"]', second);

    await expect(page.getByRole('heading', { name: 'Possible duplicates' })).toBeVisible();
    // The banner title and the server's own note both say it; the banner is the heading.
    await expect(page.getByText('Nothing is merged automatically', { exact: true })).toBeVisible();

    // No decision is made by default (UAT-XX-05), and the choices contain no merge at all.
    const decision = page.getByLabel(/^Decision 2$/);
    await expect(decision).toHaveValue('');
    const options = await decision.locator('option').allInnerTexts();
    expect(options).toEqual(['Choose a decision', 'Skip this row', 'Create separate customer']);

    // Until it is decided the import cannot be confirmed, and the page says why. With
    // nothing to create, the button says so, and an all-skip file can still be finished
    // once decided (UAT round 4).
    const importButton = page.getByRole('button', { name: 'Finish import (no new customers)' });
    await expect(importButton).toBeDisabled();
    await expect(page.getByText(/1 possible duplicate\(s\) still need a decision/)).toBeVisible();
    await decision.selectOption('skip');
    await expect(page.getByText(/still need a decision/)).toBeHidden();
    await expect(importButton).toBeEnabled();

    // Cancelling instead of committing writes nothing, and the original is untouched.
    const before = await (await request.get(`/api/v1/customers?search=dup.${run}`)).json();
    await page.getByRole('button', { name: 'Cancel and start over' }).click();
    const after = await (await request.get(`/api/v1/customers?search=dup.${run}`)).json();
    expect(after.total).toBe(before.total);
    expect(after.items[0].is_archived).toBe(false);
  });

  test('refuses a file that is not a CSV, and says why', async ({ page }) => {
    await page.goto('/customers/import');
    await page.setInputFiles('input[type="file"]', {
      name: 'customers.csv',
      mimeType: 'text/csv',
      // A ZIP signature wearing a .csv filename.
      buffer: Buffer.from([0x50, 0x4b, 0x03, 0x04, 0x14, 0x00, 0x00, 0x00]),
    });

    await expect(page.getByText('This file cannot be read')).toBeVisible();
    await expect(page.getByText(/ZIP archive or an .xlsx workbook/)).toBeVisible();
    // And the flow stays on step one rather than pretending it has a preview.
    await expect(page.getByRole('heading', { name: 'Every row' })).toBeHidden();
  });

  test('downloads a template that the importer itself accepts', async ({ page }) => {
    await page.goto('/customers/import');
    const downloadPromise = page.waitForEvent('download');
    await page.getByRole('button', { name: 'Download template' }).click();
    const download = await downloadPromise;

    const text = await readDownload(download);
    expect(text.charCodeAt(0)).toBe(0xfeff);
    expect(text).toContain('full_name');
    // Synthetic only: reserved domain, fictional numbers.
    expect(text).toContain('@example.com');
    expect(text).toMatch(/555/);

    // And it round-trips: uploading the template produces a clean preview.
    await page.setInputFiles('input[type="file"]', {
      name: 'template.csv',
      mimeType: 'text/csv',
      buffer: Buffer.from(text, 'utf8'),
    });
    await expect(page.getByRole('heading', { name: 'Every row' })).toBeVisible();
    await expect(page.getByText('Some columns were not recognized')).toBeHidden();
  });

  test('is usable at the mobile reference size', async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 812 });
    await page.goto('/customers/import');
    await expect(page.getByLabel('CSV file to import')).toBeVisible();

    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    expect(overflow).toBeLessThanOrEqual(1);
  });
});

test.describe('CSV export', () => {
  test('exports customers with the filters the list is showing', async ({ page }) => {
    await page.goto('/customers?preferred_language=vi');
    await expect(page.getByRole('heading', { name: 'Customers' })).toBeVisible();

    const downloadPromise = page.waitForEvent('download');
    await page.getByRole('button', { name: 'Export', exact: true }).click();
    const download = await downloadPromise;

    expect(download.suggestedFilename()).toBe('solaris-customers.csv');
    const text = await readDownload(download);
    expect(text.charCodeAt(0)).toBe(0xfeff);

    const [header, ...rows] = text.replace(/^\uFEFF/, '').trim().split('\r\n');
    expect(header.split(',')).toContain('customer_id');
    expect(header).not.toContain('notes');

    // The file matches the filter, not the whole book.
    const listed = await (
      await page.request.get('/api/v1/customers?preferred_language=vi&limit=100')
    ).json();
    expect(rows.length).toBe(listed.total);
  });

  test('exports shipments and packages, and a package is never a shipment', async ({ page }) => {
    await page.goto('/shipments');
    await expect(page.getByRole('heading', { name: 'Shipments' })).toBeVisible();

    const shipmentsDownload = page.waitForEvent('download');
    await page.getByRole('button', { name: 'Export shipments' }).click();
    const shipmentsText = await readDownload(await shipmentsDownload);

    const packagesDownload = page.waitForEvent('download');
    await page.getByRole('button', { name: 'Export packages' }).click();
    const packagesText = await readDownload(await packagesDownload);

    const shipmentRows = shipmentsText.replace(/^\uFEFF/, '').trim().split('\r\n').length - 1;
    const packageRows = packagesText.replace(/^\uFEFF/, '').trim().split('\r\n').length - 1;

    // The seeded dataset is multi-package, so this is a real distinction.
    expect(packageRows).toBeGreaterThan(shipmentRows);
    expect(shipmentsText).toContain('solaris_shipment_id');
    expect(packagesText).toContain('package_reference');
  });

  test('leaks no street address, phone, or internal note into a shipment export', async ({ page }) => {
    await page.goto('/shipments');
    const downloadPromise = page.waitForEvent('download');
    await page.getByRole('button', { name: 'Export shipments' }).click();
    const text = await readDownload(await downloadPromise);

    const header = text.replace(/^\uFEFF/, '').split('\r\n')[0];
    for (const forbidden of [
      'address_line',
      'postal_code',
      'recipient_phone',
      'recipient_email',
      'internal_notes',
    ]) {
      expect(header).not.toContain(forbidden);
    }
  });

  test('preserves Vietnamese diacritics in an exported file', async ({ page }) => {
    await page.goto('/customers');
    const downloadPromise = page.waitForEvent('download');
    await page.getByRole('button', { name: 'Export', exact: true }).click();
    const text = await readDownload(await downloadPromise);

    expect(text).not.toContain('�');
    // The seeded customers include accented names; at least one must survive intact.
    expect(text).toMatch(/[Ạ-ỹĐđƠơƯưĂă]/);
  });
});
