/**
 * The staff approval interface, driven through the screens.
 *
 * Workflows 4, 11, 12, 13, 14 and 15. Every one of these was reachable over the API after
 * Phase 10 and is being executed against a screen for the first time here.
 */

import { expect, test } from './diagnostics.js';
import {
  MANAGER_EMAIL,
  MARKETING_EMAIL,
  acknowledge,
  approveByCreating,
  closeStaffContext,
  freshAddress,
  pendingReferenceFor,
  openApplication,
  register,
  reject,
  signIn,
  signInStaff,
  staffContext,
  verify,
} from './accountHelpers.js';

/** A verified application waiting in the queue, and its account reference. */
async function pendingApplication(page, browser, label) {
  const email = freshAddress(label);
  await register(page, email);
  await verify(page, email);
  const { context, page: staffPage } = await staffContext(browser);
  const reference = await pendingReferenceFor(staffPage, email);
  return { email, reference, context, staffPage };
}

test.describe('approval', () => {
  test('Operations approves by creating a new customer, and the account activates', async ({
    page,
    browser,
  }) => {
    const { email, reference, context, staffPage } = await pendingApplication(
      page,
      browser,
      'approve',
    );
    try {
      await openApplication(staffPage, reference);

      // The approve control does not work until the disclosure is acknowledged.
      const approve = staffPage.getByRole('button', {
        name: 'Approve and create the customer',
      });
      await expect(approve).toBeDisabled();

      // Everything OD-29 requires a reviewer to see, on screen before they can act.
      await expect(staffPage.getByText('What this approval discloses')).toBeVisible();
      await expect(staffPage.getByText('Shipments that become visible')).toBeVisible();
      await expect(staffPage.getByText('Oldest shipment')).toBeVisible();
      await expect(staffPage.getByText('Newest shipment')).toBeVisible();
      await expect(staffPage.getByText('Includes cancelled shipments')).toBeVisible();
      await expect(staffPage.getByText('Includes rebooked shipments')).toBeVisible();
      await expect(
        staffPage.getByText('Customer this account will be linked to'),
      ).toBeVisible();
      await expect(staffPage.getByText('Duplicate check')).toBeVisible();
      await expect(
        staffPage.getByText('Submitted values written to the customer record'),
      ).toBeVisible();

      await approveByCreating(staffPage);
    } finally {
      await closeStaffContext({ context, page: staffPage });
    }

    // The customer can now sign in and reach their history.
    await signIn(page, email);
    await expect(page.getByRole('heading', { name: 'My shipments', level: 1 })).toBeVisible();
  });

  test('a decided application cannot be decided again, and says so calmly', async ({
    page,
    browser,
  }) => {
    const { reference, context, staffPage } = await pendingApplication(page, browser, 'replay');
    try {
      await openApplication(staffPage, reference);
      await approveByCreating(staffPage);

      // The completion state: the decision is reported, and the controls that would
      // produce a second one are no longer offered -- gone, not just disabled (UAT round 4).
      await expect(
        staffPage.getByRole('button', { name: 'Approve and create the customer' }),
      ).toHaveCount(0);
      await expect(
        staffPage.getByRole('button', { name: 'Decline the application' }),
      ).toHaveCount(0);

      // Re-opening it — from a bookmark, from history, or by pressing Back — is a state
      // rather than a fault. The server refuses with a 409 because there is no pending
      // proposal, and the screen reads as an answer rather than as an apology.
      await staffPage.goto(`/customer-accounts/${reference}`);
      await expect(
        staffPage.getByText('This application has already been decided'),
      ).toBeVisible();
      await expect(staffPage.getByText('Something went wrong')).toHaveCount(0);
    } finally {
      await closeStaffContext({ context, page: staffPage });
    }
  });
});

test.describe('linking to an existing customer', () => {
  test('a registration matching an existing customer is offered for linking, never merged', async ({
    page,
    browser,
  }) => {
    // Registering with a seeded customer's own address is the case OD-23 is about: the
    // response must say nothing, and staff must see the match.
    const email = 'bich.hanh.demo@demo.example.com';
    await register(page, email, { legalName: 'Bich Hanh Demo' });

    // The customer-facing response says nothing about the match.
    const confirmation = await page.locator('main').innerText();
    expect(confirmation).not.toMatch(/already|existing|match|STCA-/i);

    // And the application reaches the queue only once the address is confirmed: the
    // queue lists `pending_approval`, and an unverified identity is `pending_verification`.
    await verify(page, email);

    const { context, page: staffPage } = await staffContext(browser);
    try {
      const reference = await pendingReferenceFor(staffPage, email);
      await openApplication(staffPage, reference);

      // The duplicate check found the customer, and the reviewer is shown it.
      await expect(staffPage.getByText(/An existing customer matches exactly/).first()).toBeVisible();
      const candidate = staffPage.locator('a, td').filter({ hasText: /^STCA-/ }).first();
      const customerId = (await candidate.textContent()).trim();

      // Linking writes nothing to the customer record, and the preview says so **before**
      // the decision is taken -- which is the only moment saying it is any use.
      await staffPage.getByLabel('What should happen').selectOption('link_existing');
      await staffPage.getByLabel('Customer to link to').fill(customerId);
      await expect(
        staffPage.getByText(/linking writes nothing to the existing customer record/),
      ).toBeVisible();

      await acknowledge(staffPage);
      const approve = staffPage.getByRole('button', { name: 'Approve and link' });
      await expect(approve).toBeEnabled();
      await approve.click();
      await expect(staffPage.getByText(/Approved —/)).toBeVisible();
    } finally {
      await closeStaffContext({ context, page: staffPage });
    }
  });

  test('creating a separate customer despite a match needs a bounded reason', async ({
    page,
    browser,
  }) => {
    const email = 'minh.khoi.demo@demo.example.com';
    await register(page, email, { legalName: 'Minh Khoi Demo' });
    await verify(page, email);

    const { context, page: staffPage } = await staffContext(browser);
    try {
      const reference = await pendingReferenceFor(staffPage, email);
      await openApplication(staffPage, reference);

      await expect(staffPage.getByText('What this approval discloses')).toBeVisible();
      await acknowledge(staffPage);

      // Acknowledged, and still refused: the duplicate makes the reason mandatory.
      const approve = staffPage.getByRole('button', {
        name: 'Approve and create the customer',
      });
      await expect(approve).toBeDisabled();
      await expect(staffPage.getByLabel('Why create a separate customer')).toBeVisible();

      await staffPage
        .getByLabel('Why create a separate customer')
        .selectOption({ label: 'A different person or business with a similar name' });
      await expect(approve).toBeEnabled();
    } finally {
      await closeStaffContext({ context, page: staffPage });
    }
  });
});

test.describe('rejection', () => {
  test('declining ends the account, and the applicant is given no reason', async ({
    page,
    browser,
  }) => {
    const { email, reference, context, staffPage } = await pendingApplication(
      page,
      browser,
      'reject',
    );
    try {
      await openApplication(staffPage, reference);
      await reject(staffPage);
    } finally {
      await closeStaffContext({ context, page: staffPage });
    }

    // Sign-in is refused, with the ordinary failure sentence and nothing about why.
    await signIn(page, email);
    await expect(page.getByText('Email or password is incorrect.')).toBeVisible();
    const body = await page.locator('main').innerText();
    expect(body).not.toMatch(/declin|reject|identity|duplicate|restrict/i);
  });
});

test.describe('the stale preview', () => {
  test('a preview taken before a change cannot be used to approve', async ({ page, browser }) => {
    const { reference, context, staffPage } = await pendingApplication(page, browser, 'stale');
    try {
      await openApplication(staffPage, reference);
      await expect(staffPage.getByText('What this approval discloses')).toBeVisible();
      await acknowledge(staffPage);
      await expect(
        staffPage.getByRole('button', { name: 'Approve and create the customer' }),
      ).toBeEnabled();

      // The server answers the decision with the 409 it answers a moved fingerprint
      // with. Intercepting it is how a browser test reaches a race it cannot otherwise
      // schedule; what is being asserted is the screen's response to that answer.
      await staffPage.route('**/approve/create-new', (route) =>
        route.fulfill({
          status: 409,
          contentType: 'application/json',
          body: JSON.stringify({
            code: 'conflict',
            message:
              'This registration has changed since the preview was taken. Take a new preview, read it, and acknowledge it again.',
          }),
        }),
      );

      await staffPage
        .getByRole('button', { name: 'Approve and create the customer' })
        .click();

      await expect(
        staffPage.getByText('Something changed while you were reading'),
      ).toBeVisible();
      // The acknowledgement is withdrawn and approval is closed again. It is not retried.
      await expect(staffPage.getByLabel(/I have read the figures above/)).not.toBeChecked();
      await expect(
        staffPage.getByRole('button', { name: 'Approve and create the customer' }),
      ).toBeDisabled();
    } finally {
      await closeStaffContext({ context, page: staffPage });
    }
  });

  test('changing the intended action withdraws the acknowledgement', async ({ page, browser }) => {
    const { reference, context, staffPage } = await pendingApplication(page, browser, 'switch');
    try {
      await openApplication(staffPage, reference);
      await expect(staffPage.getByText('What this approval discloses')).toBeVisible();
      await acknowledge(staffPage);
      await expect(
        staffPage.getByRole('button', { name: 'Approve and create the customer' }),
      ).toBeEnabled();

      await staffPage.getByLabel('What should happen').selectOption('link_existing');

      // The acknowledgement goes with the preview. A link-existing preview needs a
      // customer, so until one is named there is no preview and therefore no
      // acknowledgement to give — the control is gone, not merely unticked.
      await expect(staffPage.getByLabel(/I have read the figures above/)).toHaveCount(0);

      // And when a customer is named and a fresh preview arrives, it comes back
      // **unticked**: the reviewer is being asked about different figures.
      await staffPage.getByLabel('Customer to link to').fill('STCA-000001');
      await expect(staffPage.getByText('What this approval discloses')).toBeVisible();
      await expect(staffPage.getByLabel(/I have read the figures above/)).not.toBeChecked();
    } finally {
      await closeStaffContext({ context, page: staffPage });
    }
  });
});

test.describe('concurrent approval', () => {
  test('two reviewers deciding the same application produce one decision', async ({
    page,
    browser,
  }) => {
    const { reference, context, staffPage } = await pendingApplication(
      page,
      browser,
      'concurrent',
    );
    const second = await staffContext(browser);
    try {
      // Both reviewers open the same application and both acknowledge.
      await openApplication(staffPage, reference);
      await expect(staffPage.getByText('What this approval discloses')).toBeVisible();
      await acknowledge(staffPage);

      await openApplication(second.page, reference);
      await expect(second.page.getByText('What this approval discloses')).toBeVisible();
      await acknowledge(second.page);

      // The first one wins.
      await staffPage.getByRole('button', { name: 'Approve and create the customer' }).click();
      await expect(staffPage.getByText(/Approved —/)).toBeVisible();

      // The second is refused, and the screen says what happened rather than appearing
      // to succeed. Whichever refusal the server chose — a stale fingerprint or an
      // already-linked account — it is a conflict and the acknowledgement is withdrawn.
      await second.page
        .getByRole('button', { name: 'Approve and create the customer' })
        .click();
      await expect(
        second.page.getByText('Something changed while you were reading'),
      ).toBeVisible();
      await expect(second.page.getByLabel(/I have read the figures above/)).not.toBeChecked();
    } finally {
      await closeStaffContext(second);
      await closeStaffContext({ context, page: staffPage });
    }
  });
});

test.describe('who may see these screens', () => {
  for (const [role, email] of [
    ['Marketing', MARKETING_EMAIL],
    ['the read-only manager', MANAGER_EMAIL],
  ]) {
    test(`${role} sees no navigation entry and cannot open the queue`, async ({ browser }) => {
      const context = await browser.newContext();
      const staffPage = await context.newPage();
      try {
        await signInStaff(staffPage, email);

        // No entry in the sidebar.
        await expect(
          staffPage.getByRole('link', { name: 'Customer accounts' }),
        ).toHaveCount(0);

        // And the route itself refuses: hiding a link is never the boundary.
        await staffPage.goto('/customer-accounts');
        await expect(
          staffPage.getByRole('heading', { name: 'Customer account applications', level: 1 }),
        ).toHaveCount(0);
        const body = await staffPage.locator('body').innerText();
        expect(body).not.toContain('CA-');
      } finally {
        await closeStaffContext({ context, page: staffPage });
      }
    });
  }
});
