/**
 * Shared machinery for the two accessibility specs.
 *
 * **The build fails on a new serious or critical violation.** Moderate and minor findings
 * are reported but do not fail: axe's own severity scale is the right place to draw that
 * line, and a suite that fails on every minor finding is a suite people switch off.
 *
 * **No external network request is made.** axe-core is injected from `node_modules` by
 * `@axe-core/playwright`, and the application self-hosts its fonts (DEC-0046). A route
 * guard on every audited page fails the test if anything is requested off-origin -- an
 * audit that quietly reached a CDN would be measuring somebody else's page.
 *
 * **Nothing is suppressed globally.** There is no blanket `disableRules`. Exceptions live
 * in `EXPECTED_FINDINGS`, per screen and per rule, each with a written justification, and
 * `assertNoStaleExceptions` fails if one stops matching anything -- so a suppression
 * cannot outlive the finding it was written for.
 */

import AxeBuilder from '@axe-core/playwright';
import { expect } from '@playwright/test';

/** WCAG 2.2 AA, which is what `Design.md` section 15 requires. */
export const TAGS = ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa'];

/** Severities that fail the build. */
export const BLOCKING = ['serious', 'critical'];

/**
 * Per-screen, per-rule exceptions.
 *
 * Format:
 *   'screen-name': { 'rule-id': 'why this is a genuine false positive' }
 *
 * Empty is the goal, and where this starts. An entry here is a claim that axe is wrong
 * about a specific screen, and it should read like one.
 */
export const EXPECTED_FINDINGS = {};

/** Which exceptions were actually used, so a stale one can be spotted. */
const usedExceptions = new Set();

/**
 * The origin under test.
 *
 * This used to be the literal `http://localhost:5173`, which made the check wrong on any
 * other port. `docs/UAT/ENVIRONMENT.md` section 3 tells an operator to move the stack to
 * 5183/8010 when the default ports are busy, and `playwright.config.js` honours
 * `E2E_BASE_URL` for exactly that -- so the suite could be pointed somewhere it then
 * refused to pass, because every **same-origin** font request looked off-origin. The
 * failure named a self-hosted font as an external resource, which is the opposite of what
 * it means.
 */
const BASE_ORIGIN = (() => {
  try {
    return new URL(process.env.E2E_BASE_URL || 'http://localhost:5173').origin;
  } catch {
    return 'http://localhost:5173';
  }
})();

/**
 * Fail the test if the page reaches any origin but its own.
 *
 * Deriving the origin rather than hard-coding it does not weaken the assertion: anything
 * that is not the origin under test, loopback, or an inline scheme is still a finding.
 * A third-party font, script, or beacon fails here exactly as before.
 */
export async function forbidExternalRequests(page) {
  const offOrigin = [];
  await page.route('**/*', (route) => {
    const url = route.request().url();
    const allowed =
      url.startsWith(BASE_ORIGIN) ||
      url.startsWith('http://localhost:8000') ||
      url.startsWith('http://127.0.0.1:') ||
      url.startsWith('data:') ||
      url.startsWith('blob:') ||
      url.startsWith('about:');
    if (!allowed) offOrigin.push(url);
    return route.continue();
  });
  return offOrigin;
}

/**
 * Wait for the page to settle so axe does not audit a loading skeleton.
 *
 * The explicit timeout matters. `networkidle` defaults to the 30 s navigation timeout,
 * which is the whole test budget -- so on a page that never goes idle the wait consumed
 * the entire test and it failed as a timeout rather than reaching the audit at all. A
 * page that is still chattering after two seconds is one axe should look at anyway.
 */
export async function settle(page) {
  await page.waitForLoadState('networkidle', { timeout: 2000 }).catch(() => {});
  await page.waitForTimeout(300);
}

/**
 * Audit the current page, attach the full result, and assert on the blocking findings.
 */
export async function auditAndAssert(page, screenName, testInfo) {
  const offOrigin = await forbidExternalRequests(page);
  const results = await new AxeBuilder({ page }).withTags(TAGS).analyze();

  const expected = EXPECTED_FINDINGS[screenName] || {};
  const blocking = [];
  const advisory = [];

  for (const violation of results.violations) {
    if (expected[violation.id]) {
      usedExceptions.add(`${screenName}:${violation.id}`);
      continue;
    }
    const record = {
      rule: violation.id,
      impact: violation.impact,
      help: violation.help,
      nodes: violation.nodes.slice(0, 4).map((node) => node.target.join(' ')),
    };
    if (BLOCKING.includes(violation.impact)) blocking.push(record);
    else advisory.push(record);
  }

  await testInfo.attach(`axe-${screenName}-${testInfo.project.name}`, {
    body: JSON.stringify(
      {
        screen: screenName,
        project: testInfo.project.name,
        viewport: page.viewportSize(),
        url: page.url(),
        passes: results.passes.length,
        incomplete: results.incomplete.map((item) => item.id),
        violations: results.violations.map((violation) => ({
          rule: violation.id,
          impact: violation.impact,
          help: violation.help,
          nodes: violation.nodes.map((node) => node.target.join(' ')),
        })),
      },
      null,
      2,
    ),
    contentType: 'application/json',
  });

  expect(offOrigin, `${screenName} requested an off-origin URL: ${offOrigin.join(', ')}`).toEqual(
    [],
  );

  const detail = blocking
    .map((item) => `  [${item.impact}] ${item.rule}: ${item.help}\n    ${item.nodes.join('\n    ')}`)
    .join('\n');
  expect(
    blocking,
    `${screenName} (${testInfo.project.name}): ${blocking.length} serious/critical violation(s)\n${detail}`,
  ).toEqual([]);

  if (advisory.length) {
    const lines = advisory.map((item) => `    [${item.impact}] ${item.rule}: ${item.help}`);
    console.log(`  ${screenName} (${testInfo.project.name}) advisory:\n${lines.join('\n')}`);
  }

  return { blocking, advisory, results };
}

/**
 * A suppression that no longer matches anything is a suppression nobody has re-read.
 * Called from a final test so the list cannot silently rot.
 */
export function staleExceptions() {
  const stale = [];
  for (const [screen, rules] of Object.entries(EXPECTED_FINDINGS)) {
    for (const rule of Object.keys(rules)) {
      if (!usedExceptions.has(`${screen}:${rule}`)) stale.push(`${screen}:${rule}`);
    }
  }
  return stale;
}
