/**
 * RC-UAT-22 (B-13, DEC-0234 draft), end to end: an Admin re-links an orphaned Customer
 * Account to the merge survivor, and closes a second one. The staff session of this project
 * is an Admin.
 *
 * Each orphan is made the way production makes one: an applicant registers, confirms the address
 * and is approved through the screens, then -- through the staff API, with the Admin's
 * own session and CSRF token -- the account is deactivated, its customer is merged into a new
 * record, and the account is reinstated, which ends the link and leaves it waiting for a
 * customer. The re-link and the close are then clicks. Test data only, in this run's scratch
 * database.
 */

import { expect, test } from './diagnostics.js';
import {
  approveByCreating,
  freshAddress,
  openApplication,
  pendingReferenceFor,
  register,
  verify,
} from './accountHelpers.js';

const REVIEW = '/api/v1/customer-account/identities';
const LIST_TITLE = 'Accounts needing a customer';

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

/**
 * Approve an account in a customer-only context, then orphan it as the Admin: deactivate,
 * merge its customer into a fresh record, reinstate. Returns the account and survivor.
 */
async function orphanedAccount(page, browser, label) {
  // The applicant registers in a context of their own. A context made here inherits the
  // project's stored staff session unless told otherwise, so it is started empty.
  const customerContext = await browser.newContext({ storageState: { cookies: [], origins: [] } });
  const email = freshAddress(label);
  try {
    const customerPage = await customerContext.newPage();
    await register(customerPage, email);
    await verify(customerPage, email);
  } finally {
    await customerContext.close();
  }

  // Approved through the queue screens by this project's Admin, who also holds the review
  // and approve permissions (no second staff sign-in, so no extra login allowance spent).
  const accountReference = await pendingReferenceFor(page, email);
  await openApplication(page, accountReference);
  await approveByCreating(page);

  const headers = await staffHeaders(page);
  await ok(
    await page.request.post(`${REVIEW}/${accountReference}/deactivate`, {
      headers,
      data: { reason_code: 'customer_request' },
    }),
    'deactivation',
  );
  const customers = await ok(
    await page.request.get('/api/v1/customers', { params: { search: email, limit: 5 } }),
    'customer lookup',
  );
  const owner = customers.items.find((item) => item.email_entered === email);
  expect(owner, `no customer record for ${label}`).toBeTruthy();
  const survivor = await ok(
    await page.request.post('/api/v1/customers', {
      headers,
      data: {
        full_name: `E2E survivor ${accountReference}`,
        // A record needs a phone or an email; no email, so the re-link sets the account's.
        phone: `+1 416 555 ${String(Date.now()).slice(-4)}`,
        acknowledge_duplicates: true,
      },
    }),
    'survivor creation',
  );
  await ok(
    await page.request.post('/api/v1/customers/merge', {
      headers,
      data: {
        source_customer_id: owner.id,
        target_customer_id: survivor.id,
        confirmation: owner.public_id,
      },
    }),
    'merge',
  );
  const reinstated = await ok(
    await page.request.post(`${REVIEW}/${accountReference}/reactivate`, {
      headers,
      data: { reason_code: 'customer_request' },
    }),
    'reinstatement',
  );
  expect(reinstated.status).toBe('pending_approval');
  return { accountReference, ownerId: owner.public_id, survivorId: survivor.public_id };
}

test.describe('Accounts needing a customer', () => {
  test('re-links one orphan to the merge survivor and closes another', async ({ page, browser }) => {
    test.setTimeout(180_000);
    const first = await orphanedAccount(page, browser, 'relink');
    const second = await orphanedAccount(page, browser, 'orphclose');

    await page.goto('/customer-accounts');
    const list = page.getByRole('region', { name: LIST_TITLE });
    const firstRow = list.getByRole('row', { name: new RegExp(first.accountReference) });
    await expect(firstRow).toBeVisible();
    await expect(firstRow).toContainText(`${first.ownerId} (merged)`);
    await expect(firstRow).toContainText('Customer merged while deactivated');
    await expect(firstRow).toContainText(first.survivorId);

    // --- Re-link: the survivor is prefilled; preview, read, acknowledge, reason, confirm ----
    await firstRow.getByRole('button', { name: 'Re-link' }).click();
    const relink = page.getByRole('dialog', { name: `Re-link ${first.accountReference} to a customer` });
    await expect(relink.getByLabel('Customer reference')).toHaveValue(first.survivorId);
    const confirm = relink.getByRole('button', { name: 'Re-link and activate' });
    await expect(confirm).toBeDisabled();

    const previewed = page.waitForResponse(
      (item) => item.url().includes(`/identities/${first.accountReference}/relink-preview`),
    );
    await relink.getByRole('button', { name: /Show this customer/ }).click();
    const preview = await ok(await previewed, 'preview');
    await expect(relink.getByText('What this link will open')).toBeVisible();
    await expect(relink.getByTestId('relink-history')).toContainText(first.survivorId);
    await expect(confirm).toBeDisabled();

    await relink.getByLabel(/I have read the history above/).check();
    await relink.getByLabel('Why this customer').selectOption('merge_survivor');
    await relink.getByLabel(/Note \(optional/).fill('Merged into the survivor (e2e).');
    await expect(confirm).toBeEnabled();

    const linked = page.waitForResponse(
      (item) =>
        item.url().endsWith(`/identities/${first.accountReference}/relink`) &&
        item.request().method() === 'POST',
    );
    await confirm.click();
    const response = await linked;
    expect(response.ok(), await response.text()).toBe(true);
    expect(response.request().postDataJSON()).toMatchObject({
      customer_public_id: first.survivorId,
      reason_code: 'merge_survivor',
      history_acknowledged: true,
      preview_fingerprint: preview.fingerprint,
    });
    expect((await response.json()).status).toBe('active');
    await expect(relink).toHaveCount(0);
    await expect(
      page.getByText('The account is linked and active again. The customer was emailed that it is ready.'),
    ).toBeVisible();
    await expect(list.getByRole('row', { name: new RegExp(first.accountReference) })).toHaveCount(0);

    // --- Close: reason, then the confirmation ----------------------------------------------
    const secondRow = list.getByRole('row', { name: new RegExp(second.accountReference) });
    await secondRow.getByRole('button', { name: 'Close' }).click();
    const close = page.getByRole('dialog', { name: `Close ${second.accountReference}?` });
    const yes = close.getByRole('button', { name: 'Yes, close the account' });
    await expect(yes).toBeDisabled();
    await close.getByLabel('Why close it').selectOption('no_customer');
    await expect(yes).toBeEnabled();
    const closed = page.waitForResponse(
      (item) =>
        item.url().endsWith(`/identities/${second.accountReference}/close-orphan`) &&
        item.request().method() === 'POST',
    );
    await yes.click();
    const closeResponse = await closed;
    expect(closeResponse.ok(), await closeResponse.text()).toBe(true);
    expect((await closeResponse.json()).status).toBe('deactivated');
    await expect(close).toHaveCount(0);
    await expect(page.getByText('The account has been closed.')).toBeVisible();
    await expect(list.getByRole('row', { name: new RegExp(second.accountReference) })).toHaveCount(0);
  });
});
