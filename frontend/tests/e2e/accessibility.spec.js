/**
 * Automated accessibility audit of the public and staff applications.
 *
 * Runs axe-core against every screen `Design.md` section 15 and section 19 cover, at both
 * reference viewports: 1280 x 800 for internal pages and 375 x 812 for the public one.
 * Each screen is audited at both sizes regardless, because a staff member on a phone is
 * not a hypothetical and a reflow failure only appears at the narrow size.
 *
 * **The build fails on a new serious or critical violation.** Moderate and minor findings
 * are reported but do not fail, because axe's own severity scale is the right place to
 * draw that line and because failing on every minor would make the suite something people
 * disable.
 *
 * **No external network request is made.** axe-core is injected from `node_modules` by
 * `@axe-core/playwright`; the application self-hosts its fonts (DEC-0046); and a route
 * guard installed on every page fails the test if anything is requested off-origin. That
 * guard is the assertion -- an audit that quietly reached a CDN would be measuring
 * somebody else's page.
 *
 * **Nothing is suppressed globally.** `EXPECTED_FINDINGS` holds per-screen, per-rule
 * exceptions, each with a written justification, and the test asserts that an exception
 * which stops matching is removed rather than left behind. There is no blanket
 * `disableRules`.
 *
 * An automated audit is not an accessibility certification. axe checks what a machine can
 * check -- roughly a third to a half of WCAG criteria in practice. It cannot tell whether
 * a label is *meaningful*, whether an error message is *useful*, whether reading order
 * makes sense, or whether a Vietnamese sentence says what it should. The keyboard
 * walkthroughs in `docs/ACCESSIBILITY.md` cover what this cannot, and even together they
 * are not a substitute for testing with disabled users.
 */

import { expect, test } from './diagnostics.js';

import { auditAndAssert, settle, staleExceptions } from './axeHelpers.js';

import { loadSeedReferences } from './fixtures.js';

// --- The public application ---------------------------------------------------------

test.describe('public tracking', () => {
  let references;

  test.beforeAll(() => {
    references = loadSeedReferences();
  });

  test('the lookup form', async ({ page }, testInfo) => {
    await page.goto('/track');
    await settle(page);
    await auditAndAssert(page, 'public-lookup', testInfo);
  });

  test('a successful result', async ({ page }, testInfo) => {
    await page.goto(`/track/${references.partial}`);
    // Exact, because the reference is also a prefix of every package reference on the
    // page and of the "Applies to" line: five matches, and a strict-mode violation.
    await expect(page.getByText(references.partial, { exact: true }).first()).toBeVisible();
    await settle(page);
    await auditAndAssert(page, 'public-result-success', testInfo);
  });

  test('a failed lookup', async ({ page }, testInfo) => {
    await page.goto('/track/SX-CAV-ABCDEFGHJKLM');
    await settle(page);
    await auditAndAssert(page, 'public-result-failure', testInfo);
  });

  test('a result in Vietnamese', async ({ page }, testInfo) => {
    await page.goto(`/track/${references.partial}`);
    await settle(page);
    const vietnamese = page.getByRole('button', { name: /Tiếng Việt/i });
    if (await vietnamese.count()) {
      await vietnamese.first().click();
      await settle(page);
    }
    await auditAndAssert(page, 'public-result-vietnamese', testInfo);
  });

  test('an exception result', async ({ page }, testInfo) => {
    test.skip(!references.exception, 'the demo data has no exception shipment');
    await page.goto(`/track/${references.exception}`);
    await settle(page);
    await auditAndAssert(page, 'public-result-exception', testInfo);
  });

  test('a cancelled result', async ({ page }, testInfo) => {
    test.skip(!references.cancelled, 'the demo data has no cancelled shipment');
    await page.goto(`/track/${references.cancelled}`);
    await settle(page);
    await auditAndAssert(page, 'public-result-cancelled', testInfo);
  });
});

// --- The staff application ------------------------------------------------------------

test.describe('staff login', () => {
  test('the sign-in form', async ({ page }, testInfo) => {
    await page.goto('/');
    await expect(page.getByLabel('Email address')).toBeVisible();
    await settle(page);
    await auditAndAssert(page, 'staff-login', testInfo);
  });
});


// --- The exception list must not rot ---------------------------------------------------

test('every recorded accessibility exception is still necessary', async () => {
  // Runs last by file order. A suppression that no longer matches anything is one
  // nobody has re-read, and leaving it behind is how a blanket disable begins.
  expect(staleExceptions(), 'remove these from EXPECTED_FINDINGS').toEqual([]);
});
