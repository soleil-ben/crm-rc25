/**
 * Automated accessibility audit of the staff application.
 *
 * Separate from `accessibility.spec.js` because these screens need a session, and the
 * staff projects carry one. Between the two files every screen the Phase 5B brief names
 * is audited, at both 1280 x 800 and 375 x 812.
 *
 * The import flow is walked rather than deep-linked. Its later steps -- mapping,
 * validation preview, duplicate decisions, confirmation, result -- exist only as states
 * of a page that has been given a file, so auditing them means driving the flow. Each
 * upload uses a run-unique file, for the reason `staffImportExport.spec.js` documents at
 * length: a re-run against a database an earlier run wrote to finds the previous run's
 * person, classifies the row as a duplicate, and quietly stops the spec proving anything.
 *
 * See `accessibility.spec.js` for what an automated audit does and does not establish.
 */

import { expect, test } from './diagnostics.js';

import { auditAndAssert, settle } from './axeHelpers.js';

const HEADER = 'full_name,email,phone,country_code,city,preferred_language,source_record_id\r\n';

function runId() {
  return `A11Y${Date.now().toString(36).toUpperCase()}`;
}

function csv(run, rows) {
  const body = rows
    .map(
      (row) =>
        `${row.name} ${run},${row.email},${row.phone || ''},CA,` +
        `${row.city || 'Mississauga'},vi,${run}-${row.key}`,
    )
    .join('\r\n');
  return {
    name: 'customers.csv',
    mimeType: 'text/csv',
    buffer: Buffer.from(HEADER + body + '\r\n', 'utf8'),
  };
}

// --- Core screens ---------------------------------------------------------------------

test.describe('staff screens', () => {
  test('dashboard', async ({ page }, testInfo) => {
    await page.goto('/');
    await expect(page.getByRole('heading', { name: /Good (morning|afternoon|evening)/ })).toBeVisible();
    await settle(page);
    await auditAndAssert(page, 'staff-dashboard', testInfo);
  });

  test('customer list', async ({ page }, testInfo) => {
    await page.goto('/customers');
    await expect(page.getByRole('heading', { name: 'Customers' })).toBeVisible();
    await settle(page);
    await auditAndAssert(page, 'staff-customer-list', testInfo);
  });

  test('customer detail', async ({ page, request }, testInfo) => {
    const list = await (await request.get('/api/v1/customers?limit=1')).json();
    const customer = list.items[0];
    await page.goto(`/customers/${customer.id}`);
    await settle(page);
    await auditAndAssert(page, 'staff-customer-detail', testInfo);
  });

  test('customer creation', async ({ page }, testInfo) => {
    await page.goto('/customers');
    await page.getByRole('button', { name: /New customer|Add customer/i }).first().click();
    await settle(page);
    await auditAndAssert(page, 'staff-customer-create', testInfo);
  });

  test('customer creation showing validation errors', async ({ page }, testInfo) => {
    await page.goto('/customers');
    await page.getByRole('button', { name: /New customer|Add customer/i }).first().click();
    await settle(page);
    // Submitting an empty form is the state in which error identification and the
    // association between a message and its field actually matter.
    const save = page.getByRole('button', { name: /^(Save|Create)/ }).first();
    if (await save.count()) {
      await save.click();
      await settle(page);
    }
    await auditAndAssert(page, 'staff-customer-create-errors', testInfo);
  });

  test('customer creation showing the error summary', async ({ page }, testInfo) => {
    // UAT round 5: a bad email and a negative estimate are listed at the top of the
    // dialog, each entry a link that moves focus to its field.
    await page.goto('/customers');
    await page.getByRole('button', { name: /Add customer/i }).first().click();
    const dialog = page.getByRole('dialog');
    await dialog.getByLabel(/Full name/i).fill('Trần Văn Bình');
    await dialog.getByLabel(/Email address/i).fill('bad');
    await dialog.getByLabel(/Estimated monthly shipments/i).fill('-3');
    await dialog.getByRole('button', { name: 'Add customer' }).click();
    const summary = dialog.getByRole('alert', { name: /There are 2 problems/ });
    await expect(summary).toBeFocused();
    await summary.getByRole('link', { name: /valid email address/ }).click();
    await expect(dialog.getByLabel(/Email address/i)).toBeFocused();
    await settle(page);
    await auditAndAssert(page, 'staff-customer-create-error-summary', testInfo);
  });

  test('shipment list', async ({ page }, testInfo) => {
    await page.goto('/shipments');
    await expect(page.getByRole('heading', { name: 'Shipments' })).toBeVisible();
    await settle(page);
    await auditAndAssert(page, 'staff-shipment-list', testInfo);
  });

  test('shipment detail', async ({ page, request }, testInfo) => {
    const list = await (await request.get('/api/v1/shipments?limit=1')).json();
    const shipment = list.items[0];
    await page.goto(`/shipments/${shipment.id}`);
    await settle(page);
    await auditAndAssert(page, 'staff-shipment-detail', testInfo);
  });

  test('booking workflow', async ({ page }, testInfo) => {
    await page.goto('/shipments/new');
    await settle(page);
    await auditAndAssert(page, 'staff-booking-wizard', testInfo);
  });

  test('label preview', async ({ page, request }, testInfo) => {
    const list = await (await request.get('/api/v1/shipments?limit=20')).json();
    const shipment = list.items.find((item) => item.public_id) || list.items[0];
    await page.goto(`/shipments/${shipment.id}`);
    await settle(page);
    const labels = page.getByRole('tab', { name: /Labels?/i });
    if (await labels.count()) {
      await labels.first().click();
      await settle(page);
    }
    await auditAndAssert(page, 'staff-label-preview', testInfo);
  });

  test('follow-ups', async ({ page }, testInfo) => {
    await page.goto('/follow-ups');
    await settle(page);
    await auditAndAssert(page, 'staff-follow-ups', testInfo);
  });

  test('segments', async ({ page }, testInfo) => {
    await page.goto('/segments');
    await settle(page);
    await auditAndAssert(page, 'staff-segments', testInfo);
  });

  test('workspace', async ({ page }, testInfo) => {
    await page.goto('/workspace');
    await expect(page.getByRole('heading', { name: 'Workspace', level: 1 })).toBeVisible();
    await settle(page);
    await auditAndAssert(page, 'staff-workspace', testInfo);
  });

  test('workspace, new master form', async ({ page }, testInfo) => {
    await page.goto('/workspace');
    await page.getByRole('button', { name: 'New master' }).click();
    await expect(page.getByRole('button', { name: 'Create master' })).toBeVisible();
    await settle(page);
    await auditAndAssert(page, 'staff-workspace-new-master', testInfo);
  });

  test('finance', async ({ page }, testInfo) => {
    await page.goto('/finance');
    await expect(page.getByRole('heading', { name: 'Finance', level: 1 })).toBeVisible();
    await settle(page);
    await auditAndAssert(page, 'staff-finance', testInfo);
  });

  test('finance, profitability', async ({ page }, testInfo) => {
    await page.goto('/finance?tab=profitability');
    await expect(page.getByRole('heading', { name: 'Finance', level: 1 })).toBeVisible();
    await expect(page.getByRole('tab', { name: 'Profitability', selected: true })).toBeVisible();
    await settle(page);
    await auditAndAssert(page, 'staff-finance-profitability', testInfo);
  });

  test('finance, periods', async ({ page }, testInfo) => {
    await page.goto('/finance?tab=periods');
    await expect(page.getByRole('heading', { name: 'Finance', level: 1 })).toBeVisible();
    await settle(page);
    await auditAndAssert(page, 'staff-finance-periods', testInfo);
  });

  test('settings and integration infrastructure', async ({ page }, testInfo) => {
    await page.goto('/settings');
    await settle(page);
    await auditAndAssert(page, 'staff-settings', testInfo);
  });

  test('settings, integration infrastructure panel', async ({ page }, testInfo) => {
    await page.goto('/settings');
    await settle(page);
    const panel = page.getByRole('tab', { name: /Integration/i });
    if (await panel.count()) {
      await panel.first().click();
      await settle(page);
    }
    await expect(page.getByText(/not configured/i).first()).toBeVisible();
    await auditAndAssert(page, 'staff-integration-status', testInfo);
  });
});

// --- Reports --------------------------------------------------------------------------

test.describe('reports', () => {
  test('the report set', async ({ page }, testInfo) => {
    await page.goto('/reports?from=2026-08-01&to=2026-09-10');
    await expect(page.getByRole('heading', { name: 'Route mix' })).toBeVisible();
    await settle(page);
    await auditAndAssert(page, 'staff-reports', testInfo);
  });

  test('after filtering', async ({ page }, testInfo) => {
    await page.goto('/reports?from=2026-09-01&to=2026-09-10&route_group=CAV');
    await expect(page.getByRole('heading', { name: 'Route mix' })).toBeVisible();
    await settle(page);
    await auditAndAssert(page, 'staff-reports-filtered', testInfo);
  });

  test('with an invalid range, showing the error', async ({ page }, testInfo) => {
    // Beyond the 731-day limit. The refusal is a screen a person has to read.
    await page.goto('/reports?from=2020-01-01&to=2026-09-10');
    await settle(page);
    await auditAndAssert(page, 'staff-reports-range-error', testInfo);
  });

  test('the export control', async ({ page }, testInfo) => {
    await page.goto('/reports?from=2026-08-01&to=2026-09-10');
    await expect(page.getByRole('heading', { name: 'Route mix' })).toBeVisible();
    await settle(page);
    await auditAndAssert(page, 'staff-report-export', testInfo);
  });

  test('CSV export controls on the customer list', async ({ page }, testInfo) => {
    await page.goto('/customers');
    await expect(page.getByRole('button', { name: 'Export', exact: true })).toBeVisible();
    await settle(page);
    await auditAndAssert(page, 'staff-csv-export', testInfo);
  });
});

// --- The import flow, walked step by step ---------------------------------------------

test.describe('customer import', () => {
  test('upload step', async ({ page }, testInfo) => {
    await page.goto('/customers/import');
    await expect(page.getByLabel('CSV file to import')).toBeVisible();
    await settle(page);
    await auditAndAssert(page, 'staff-import-upload', testInfo);
  });

  test('mapping and validation preview', async ({ page }, testInfo) => {
    const run = runId();
    await page.goto('/customers/import');
    await page.setInputFiles(
      'input[type="file"]',
      csv(run, [
        { name: 'Nguyễn Thị Bích Hạnh', email: `hanh.${run}@example.com`, key: 'A' },
        { name: 'Trần Quốc Tuấn', email: `tuan.${run}@example.com`, key: 'B' },
      ]),
    );
    await expect(page.getByRole('heading', { name: 'Every row' })).toBeVisible();
    await settle(page);
    await auditAndAssert(page, 'staff-import-preview', testInfo);
  });

  test('duplicate decisions', async ({ page }, testInfo) => {
    const run = runId();
    const person = { name: 'Phạm Văn Khánh', email: `khanh.${run}@example.com`, key: 'C' };

    // Import once, then present the same person again so the duplicate review appears.
    await page.goto('/customers/import');
    await page.setInputFiles('input[type="file"]', csv(run, [person]));
    await expect(page.getByRole('heading', { name: 'Every row' })).toBeVisible();
    await page.getByRole('button', { name: /Import 1 customer/ }).click();
    await page.getByRole('button', { name: 'Yes, import now' }).click();
    await expect(page.getByRole('button', { name: 'Import another file' })).toBeVisible();

    await page.getByRole('button', { name: 'Import another file' }).click();
    await page.setInputFiles(
      'input[type="file"]',
      csv(run, [{ ...person, key: 'D', email: `khanh.second.${run}@example.com` }]),
    );
    await settle(page);
    await auditAndAssert(page, 'staff-import-duplicate-decisions', testInfo);
  });

  test('confirmation dialog', async ({ page }, testInfo) => {
    const run = runId();
    await page.goto('/customers/import');
    await page.setInputFiles(
      'input[type="file"]',
      csv(run, [{ name: 'Lê Thị Mai Anh', email: `maianh.${run}@example.com`, key: 'E' }]),
    );
    await expect(page.getByRole('heading', { name: 'Every row' })).toBeVisible();
    await page.getByRole('button', { name: /Import 1 customer/ }).click();
    // The confirmation is a focus-trapped dialog: exactly the thing an audit should see.
    await expect(page.getByRole('button', { name: 'Yes, import now' })).toBeVisible();
    await settle(page);
    await auditAndAssert(page, 'staff-import-confirm', testInfo);
  });

  test('result screen', async ({ page }, testInfo) => {
    const run = runId();
    await page.goto('/customers/import');
    await page.setInputFiles(
      'input[type="file"]',
      csv(run, [{ name: 'Hoàng Minh Đức', email: `duc.${run}@example.com`, key: 'F' }]),
    );
    await expect(page.getByRole('heading', { name: 'Every row' })).toBeVisible();
    await page.getByRole('button', { name: /Import 1 customer/ }).click();
    await page.getByRole('button', { name: 'Yes, import now' }).click();
    await expect(page.getByRole('button', { name: 'Import another file' })).toBeVisible();
    await settle(page);
    await auditAndAssert(page, 'staff-import-result', testInfo);
  });

  test('a rejected file, showing the error state', async ({ page }, testInfo) => {
    await page.goto('/customers/import');
    await page.setInputFiles('input[type="file"]', {
      name: 'not-a-csv.csv',
      mimeType: 'text/csv',
      buffer: Buffer.from('\x00\x01\x02 this is not a csv at all', 'utf8'),
    });
    await settle(page);
    await auditAndAssert(page, 'staff-import-rejected', testInfo);
  });
});

// --- Duplicate review outside the import flow ------------------------------------------

test.describe('duplicate review', () => {
  /**
   * The duplicate panel inside the customer form, which is where duplicate review
   * actually happens outside the import flow.
   *
   * An earlier version of this test looked for a "Duplicate" **tab** on the customer
   * record and skipped when it found none. There is no such tab and there never was, so
   * the skip condition was permanently true: it read as conditional coverage and was
   * really no coverage at all, of a screen the Phase 5B brief names explicitly. Replaced
   * with the real surface, which is driven rather than looked for.
   */
  test('the duplicate panel in the customer form', async ({ page, request }, testInfo) => {
    // Match an existing customer on the strongest signal the checker has: the phone
    // number. Reading it from the API rather than assuming one keeps the test working
    // against a reseeded database.
    const list = await (await request.get('/api/v1/customers?limit=50')).json();
    const existing = list.items.find((item) => item.phone_entered || item.email_entered);
    expect(existing, 'the demo database has no contactable customer to duplicate').toBeTruthy();

    await page.goto('/customers');
    await page.getByRole('button', { name: /Add customer/i }).first().click();
    await expect(page.getByRole('dialog')).toBeVisible();

    // Typing a matching name and phone is what asks the server for candidates.
    await page.getByLabel(/Full name/i).fill(existing.full_name);
    if (existing.phone_entered) {
      await page.getByLabel(/Phone/i).first().fill(existing.phone_entered);
    } else {
      await page.getByLabel(/Email/i).first().fill(existing.email_entered);
    }

    // The panel is the assertion: if it never appears the test fails rather than skips.
    await expect(page.getByText('Possible duplicate records')).toBeVisible({ timeout: 15_000 });
    await settle(page);

    await auditAndAssert(page, 'staff-duplicate-review', testInfo);
  });
});
