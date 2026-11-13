/**
 * Tariff updates (Phase 13H, OD-76), staff side, end to end, through the screens.
 *
 * The administrator makes themself the tariff approver and allows the demo vendor domain in
 * Settings → Tariff updates, uploads a rate email (`.eml`) built here from the **sanitized**
 * fixture workbook, sees it imported as a draft with its diff against the active version, and
 * rejects it with a reason. Rejecting (not approving) keeps the seeded active tariff that the
 * other staff specs price against. No mailbox is involved: the email is an upload.
 *
 * The workbook is the fixture's bytes with a zip comment naming this run, so its SHA-256 is
 * new on every run while its content -- and so the diff -- is the fixture's own.
 */

import { readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { expect, test } from './diagnostics.js';

const FIXTURE = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  '../../../backend/tests/fixtures/kango_canada_rates_2026-10-12_sanitized.xlsx',
);

function workbookCopy(tag) {
  const bytes = readFileSync(FIXTURE);
  // The fixture's end-of-central-directory record is its last 22 bytes, with no comment.
  expect(bytes.readUInt32LE(bytes.length - 22)).toBe(0x06054b50);
  expect(bytes.readUInt16LE(bytes.length - 2)).toBe(0);
  const comment = Buffer.from(tag, 'ascii');
  const copy = Buffer.concat([bytes, comment]);
  copy.writeUInt16LE(comment.length, bytes.length - 2);
  return copy;
}

function rateEmail(tag) {
  const attachment = workbookCopy(tag).toString('base64').replace(/.{76}/g, '$&\r\n');
  const boundary = `boundary-${tag}`;
  return Buffer.from(
    [
      'From: Vendor Rates <rates@vendor.example.com>',
      'To: intake@demo.example.com',
      `Subject: E2E rates ${tag}`,
      `Message-ID: <${tag}@vendor.example.com>`,
      'Date: Tue, 20 Oct 2026 09:00:00 -0400',
      'MIME-Version: 1.0',
      `Content-Type: multipart/mixed; boundary="${boundary}"`,
      '',
      `--${boundary}`,
      'Content-Type: text/plain; charset=utf-8',
      '',
      'New rates attached.',
      '',
      `--${boundary}`,
      'Content-Type: application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
      'Content-Transfer-Encoding: base64',
      `Content-Disposition: attachment; filename="rates-${tag}.xlsx"`,
      '',
      attachment,
      `--${boundary}--`,
      '',
    ].join('\r\n'),
    'utf-8',
  );
}

test.describe('Tariff updates', () => {
  test('a rate email becomes a draft with its diff, and the approver rejects it', async ({ page }) => {
    test.setTimeout(120_000);
    const tag = `e2e-${Date.now().toString(36)}`;

    await page.goto('/settings');
    await expect(page.getByRole('heading', { name: 'Settings', level: 1 })).toBeVisible();
    await page.getByRole('tab', { name: 'Tariff updates' }).click();
    await expect(page.getByText(/No mailbox is connected/)).toBeVisible();

    // --- The administrator is the approver; the demo vendor's domain is allowed ----------
    const approvers = page.getByRole('textbox', { name: /^Approvers/ });
    await expect(approvers).toBeVisible();
    await approvers.fill('admin@demo.example.com');
    await page.getByRole('textbox', { name: /Senders imported without review/ }).fill('vendor.example.com');
    const saved = page.waitForResponse(
      (response) => response.url().includes('/api/v1/tariffs/intake/settings') && response.request().method() === 'PATCH',
    );
    await page.getByRole('button', { name: 'Save intake settings' }).click();
    expect((await saved).status()).toBe(200);

    // --- Upload the rate email ------------------------------------------------------------
    const uploaded = page.waitForResponse(
      (response) => response.url().includes('/api/v1/tariffs/intake/upload') && response.request().method() === 'POST',
    );
    await page.getByLabel('Upload a rate email (.eml)').setInputFiles({
      name: `${tag}.eml`,
      mimeType: 'message/rfc822',
      buffer: rateEmail(tag),
    });
    const response = await uploaded;
    expect(response.status()).toBe(201);
    const intake = await response.json();
    expect(intake.status).toBe('imported');

    const list = page.getByRole('region', { name: 'Rate emails' });
    const row = list.getByRole('row').filter({ hasText: `E2E rates ${tag}` });
    await expect(row.getByText('Imported (draft)')).toBeVisible();
    await expect(row.getByText(`${intake.tariff_version_public_id} (draft)`)).toBeVisible();

    // --- The pending version and its diff -----------------------------------------------
    await expect(page.getByRole('heading', { name: `Tariff version ${intake.tariff_version_public_id}` })).toBeVisible();
    await expect(page.getByText(/Compared with the active version/)).toBeVisible();
    await expect(page.getByText('No air price or surcharge changed.')).toBeVisible();
    await expect(page.getByRole('button', { name: 'Approve and activate' })).toBeEnabled();

    // --- Reject with a reason --------------------------------------------------------------
    await page.getByRole('textbox', { name: /Reason for rejecting/ }).fill('E2E: same prices as the active tariff');
    const rejected = page.waitForResponse(
      (r) => r.url().includes(`/api/v1/tariffs/versions/${intake.tariff_version_id}/reject`),
    );
    await page.getByRole('button', { name: 'Reject' }).click();
    expect((await rejected).status()).toBe(200);
    await expect(page.getByText(/stays a draft and will not be used/)).toBeVisible();
    await expect(row.getByText('Rejected by approver')).toBeVisible();
  });
});
