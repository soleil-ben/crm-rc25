/**
 * Reports, end to end, against the running application and a seeded database.
 *
 * The unit tests already prove the arithmetic. What this suite proves is different: that
 * the page assembles from a real API response, that its figures agree with the API's own
 * numbers, that a drill-through link actually opens the records behind an aggregate, and
 * that the export downloads a real file with the right shape.
 */

import { expect, test } from './diagnostics.js';

const RANGE = '?from=2026-08-01&to=2026-09-10';

test.describe('Reports', () => {
  test('renders every report the API returned, with its definition', async ({ page }) => {
    const response = page.waitForResponse(
      (item) => item.url().includes('/api/v1/reports?') && item.status() === 200,
    );
    await page.goto(`/reports${RANGE}`);
    const payload = await (await response).json();

    expect(payload.reports.length).toBeGreaterThan(0);
    for (const report of payload.reports) {
      await expect(page.getByRole('heading', { name: report.title })).toBeVisible();
      // The definition is rendered, not just carried in the payload.
      await expect(page.getByText(report.definition, { exact: false }).first()).toBeVisible();
    }
  });

  test('shows figures that match the API response exactly', async ({ page }) => {
    const response = page.waitForResponse(
      (item) => item.url().includes('/api/v1/reports?') && item.status() === 200,
    );
    await page.goto(`/reports${RANGE}`);
    const payload = await (await response).json();

    const routeMix = payload.reports.find((report) => report.key === 'route_mix');
    const table = page.getByRole('table', { name: /Route mix/ });
    for (const row of routeMix.rows.filter((item) => item.count > 0)) {
      const line = table.locator('tr', { hasText: row.route_label });
      await expect(line).toContainText(String(row.count));
    }
  });

  test('says which reports describe the period and which describe today', async ({ page }) => {
    await page.goto(`/reports${RANGE}`);
    await expect(page.getByText('Selected period').first()).toBeVisible();
    await expect(page.getByText('Current state').first()).toBeVisible();
  });

  test('shows no comparison, trend, or percentage-change figure anywhere', async ({ page }) => {
    await page.goto(`/reports${RANGE}`);
    await expect(page.getByRole('heading', { name: 'Route mix' })).toBeVisible();

    const body = await page.locator('main').innerText();
    expect(body).not.toMatch(/[+−-]\d+(\.\d+)?%/);
    expect(body).not.toMatch(/vs\.? (previous|last) period/i);
    expect(body).toMatch(/No comparison with a previous period/i);
  });

  test('reports no carrier freshness, because none exists', async ({ page }) => {
    await page.goto(`/reports${RANGE}`);
    await expect(page.getByRole('heading', { name: 'Shipment exceptions' })).toBeVisible();

    const body = (await page.locator('main').innerText()).toLowerCase();
    expect(body).toContain('no provider integration is connected');
    expect(body).not.toContain('last successful sync');
    // The exception report lists only the modes a shipment can actually be in.
    const exceptions = page.getByRole('table', { name: /Shipment exceptions/ });
    await expect(exceptions).toContainText('No tracking reference');
    await expect(exceptions).not.toContainText('Connected API');
  });

  test('makes the shipment-versus-package difference visible', async ({ page }) => {
    const response = page.waitForResponse(
      (item) => item.url().includes('/api/v1/reports?') && item.status() === 200,
    );
    await page.goto(`/reports${RANGE}`);
    const payload = await (await response).json();
    const guard = payload.counting_guard;

    await expect(page.getByRole('heading', { name: 'How shipments are counted' })).toBeVisible();
    const card = page.getByRole('region', { name: 'How shipments are counted' });
    await expect(card).toContainText(String(guard.qualifying_shipments));
    await expect(card).toContainText(String(guard.packages_on_those_shipments));
    // A multi-package dataset is the only one that proves anything here.
    expect(guard.packages_on_those_shipments).toBeGreaterThan(guard.qualifying_shipments);
  });

  test('opens the records behind an aggregate', async ({ page }) => {
    await page.goto(`/reports${RANGE}`);
    const table = page.getByRole('table', { name: /Route mix/ });
    const firstLink = table.getByRole('link').first();
    const href = await firstLink.getAttribute('href');
    expect(href).toContain('/shipments?');

    await firstLink.click();
    await expect(page).toHaveURL(/\/shipments\?/);
    await expect(page.getByRole('heading', { name: 'Shipments' })).toBeVisible();
  });

  test('keeps the range in the URL so a report is a shareable link', async ({ page }) => {
    await page.goto(`/reports${RANGE}`);
    await page.getByRole('button', { name: 'Last 7 days' }).click();

    await expect(page).toHaveURL(/from=\d{4}-\d{2}-\d{2}/);
    await expect(page).toHaveURL(/to=\d{4}-\d{2}-\d{2}/);

    // And the state survives a reload, which is the point of putting it in the URL.
    const url = page.url();
    await page.reload();
    expect(page.url()).toBe(url);
  });

  test('applies a route filter to every report on the page', async ({ page }) => {
    await page.goto(`/reports${RANGE}`);
    await page.getByRole('checkbox', { name: 'Domestic Canada' }).check();

    await expect(page).toHaveURL(/route_group=CAD/);
    const table = page.getByRole('table', { name: /Route mix/ });
    await expect(table.locator('tbody tr')).toHaveCount(1);
    await expect(table).toContainText('Domestic Canada');
  });

  test('refuses an impossible range with an explanation, not a generic error', async ({ page }) => {
    await page.goto('/reports?from=2019-01-01&to=2026-12-31');
    await expect(page.getByText('That date range cannot be reported')).toBeVisible();
    await expect(page.getByText(/at most 731 days/)).toBeVisible();
  });

  test('downloads a report as CSV with the columns the screen showed', async ({ page }) => {
    await page.goto(`/reports${RANGE}`);
    await expect(page.getByRole('heading', { name: 'Route mix' })).toBeVisible();

    // Each report is a landmark region named by its own heading, so the export button
    // can be addressed unambiguously rather than by position.
    const card = page.getByRole('region', { name: /^Route mix/ });

    const downloadPromise = page.waitForEvent('download');
    await card.getByRole('button', { name: 'Export CSV' }).click();
    const download = await downloadPromise;

    expect(download.suggestedFilename()).toContain('route-mix');
    const stream = await download.createReadStream();
    const chunks = [];
    for await (const chunk of stream) chunks.push(chunk);
    const text = Buffer.concat(chunks).toString('utf8');

    expect(text.charCodeAt(0)).toBe(0xfeff); // UTF-8 BOM, so Excel reads it as UTF-8
    expect(text).toContain('Route,Qualifying shipments,Share');
    expect(text).toContain('Domestic Canada');
  });

  test('is usable at the mobile reference size', async ({ page }) => {
    // Design.md section 16: 375 x 812. Internal pages are supported for lookup.
    await page.setViewportSize({ width: 375, height: 812 });
    await page.goto(`/reports${RANGE}`);

    await expect(page.getByRole('heading', { name: 'Route mix' })).toBeVisible();
    // The page must not scroll sideways; wide tables scroll inside their own container.
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    expect(overflow).toBeLessThanOrEqual(1);
  });
});
