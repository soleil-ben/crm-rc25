/**
 * Playwright configuration for the public tracking end-to-end suite.
 *
 * This is an **assertion** suite, deliberately separate from
 * `scripts/capture_screenshots.mjs`. The screenshot script drives the staff workflow and
 * fails loudly if a step cannot be found, but it asserts reachability rather than
 * behaviour. This suite asserts behaviour, and it inspects network traffic, which a
 * screenshot cannot.
 *
 * ## Do not run this with `playwright test`
 *
 * The one command is:
 *
 *     npm run e2e --prefix frontend
 *
 * which is `scripts/run_e2e.mjs`. It builds an isolated `.e2e.db`, starts a backend and a
 * dev server that belong to that database alone, passes both origins explicitly, applies
 * the documented E2E rate limits, and removes everything it created when the run passes.
 *
 * Running `playwright test` by hand instead is what caused the 2026-09-20 incident: the
 * base URL defaulted to `http://localhost:5173`, a development backend was already
 * listening there, and the staff specs wrote forty customers, thirty-two import batches
 * and a hundred and ninety-five audit rows into `data/solaris_crm.db`. `globalSetup.js`
 * now refuses to start without proof that the backend belongs to this run, so the mistake
 * fails loudly instead of silently succeeding — but the working command is the one above.
 *
 * A `webServer` block is still deliberately not used. Playwright's would start a server
 * and wait for a port to answer, and "a port answered" is precisely the check that was not
 * enough: it is satisfied by a server Playwright did not start. `run_e2e.mjs` owns the
 * processes so that it can also own the database, the run identifier and the cleanup.
 */

import { defineConfig, devices } from '@playwright/test';

const BASE_URL = process.env.E2E_BASE_URL || 'http://localhost:5173';

/**
 * Traces, screenshots and per-test diagnostics go into this run's own directory, under
 * `data/e2e/run-<id>/artifacts/`, which `.gitignore` excludes at any depth. A passing run
 * deletes the whole directory; a failing one keeps it, and it holds synthetic data only.
 *
 * The fallback is for the case where somebody runs Playwright directly — `globalSetup.js`
 * stops that run before any test, so nothing is written there beyond the refusal.
 */
const OUTPUT_DIR = process.env.E2E_ARTIFACTS_DIR || 'test-results';

/** The spec that deliberately exhausts the shared rate limiter. */
const RATE_LIMIT_SPEC = '**/zzRateLimit.spec.js';

/** Staff workflows. They need a session, so they run in their own project. */
const STAFF_SPECS = '**/staff*.spec.js';
const STAFF_SETUP = '**/staffAuth.setup.js';
const STAFF_STATE = 'tests/e2e/.auth/staff.json';

/** Drains the shared public rate limiter between the two public projects. */
const LIMITER_DRAIN = '**/limiterDrain.setup.js';

/**
 * Customer Account journeys (Phase 12).
 *
 * Their own projects rather than a share of `desktop`, for two reasons. They sign in as a
 * customer, so they must not inherit the empty-state assumption the public projects rely
 * on; and several of them drive a **second** context signed in as staff, so they have to
 * run after the staff projects have taken their own session rather than racing them for
 * the login allowance.
 */
const ACCOUNT_SPECS = '**/account*.spec.js';

/**
 * The layout assertions, which only mean anything at phone width, so they run **only** in
 * `account-mobile`.
 *
 * The accessibility spec is deliberately *not* here: §13 asks for every state audited at
 * both viewports, so it runs in both projects. It was in this list once, which quietly
 * meant the Customer Account was never audited at 1280 — the run was green and half the
 * requirement was missing.
 */
const ACCOUNT_MOBILE_ONLY_SPECS = ['**/accountMobile.spec.js'];

export default defineConfig({
  testDir: './tests/e2e',
  testMatch: ['**/*.spec.js', '**/*.setup.js'],
  // Wait for the shared rate limiter to have room before the first test runs. The
  // limiter lives in the backend process and survives between runs, so a suite started
  // soon after a previous one would otherwise begin against a consumed window.
  globalSetup: './tests/e2e/globalSetup.js',
  // The suite shares one seeded database and one in-process rate limiter, and one of the
  // specs deliberately exhausts that limiter. Running serially keeps a rate-limit test
  // from failing an unrelated lookup in a parallel worker.
  fullyParallel: false,
  workers: 1,
  forbidOnly: Boolean(process.env.CI),
  retries: 0,
  reporter: process.env.CI ? [['list'], ['html', { open: 'never' }]] : [['list']],
  outputDir: OUTPUT_DIR,
  timeout: 30_000,
  expect: { timeout: 10_000 },
  use: {
    baseURL: BASE_URL,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'off',
    // No stored state: every test starts as a stranger with an empty browser, which is
    // how a customer arrives at a tracking page.
    storageState: { cookies: [], origins: [] },
  },
  projects: [
    {
      name: 'desktop',
      testIgnore: [RATE_LIMIT_SPEC, STAFF_SPECS, STAFF_SETUP, LIMITER_DRAIN, ACCOUNT_SPECS],
      use: { ...devices['Desktop Chrome'], viewport: { width: 1280, height: 800 } },
    },
    {
      // The two public projects replay the same lookups from the same loopback address,
      // so the first exhausts the shared limiter and the second would begin against a
      // consumed window. This waits for the window to reopen. It weakens nothing:
      // zzRateLimit.spec.js still proves the limiter works.
      name: 'public-drain',
      testMatch: LIMITER_DRAIN,
      dependencies: ['desktop'],
      use: { ...devices['Desktop Chrome'] },
    },
    {
      // Design.md section 16's reference phone size. Public tracking is designed for it.
      name: 'mobile-375',
      testIgnore: [RATE_LIMIT_SPEC, STAFF_SPECS, STAFF_SETUP, LIMITER_DRAIN, ACCOUNT_SPECS],
      dependencies: ['public-drain'],
      use: { ...devices['Desktop Chrome'], viewport: { width: 375, height: 812 } },
    },
    {
      // Signs in once for the whole staff suite. Login is rate limited by client
      // address, and every test here arrives from loopback, so signing in per spec
      // would consume the allowance and fail for a reason unrelated to the code.
      name: 'staff-setup',
      testMatch: STAFF_SETUP,
      use: { ...devices['Desktop Chrome'], viewport: { width: 1280, height: 800 } },
    },
    {
      // Staff workflows: reports, export, import preview, import commit, and retry.
      // Unlike the public projects these carry a session, so they declare their own
      // storage state rather than inheriting the empty one above.
      name: 'staff',
      testMatch: STAFF_SPECS,
      dependencies: ['staff-setup'],
      use: {
        ...devices['Desktop Chrome'],
        viewport: { width: 1280, height: 800 },
        storageState: STAFF_STATE,
      },
    },
    {
      // The staff screens again at the reference phone size, so the accessibility audit
      // sees both viewports the Phase 5B brief requires. Reflow, horizontal overflow, and
      // target size are the failures that only appear when the window is narrow, and
      // auditing staff pages solely at 1280 would have missed every one of them.
      //
      // Only the accessibility spec runs here. The behavioural staff specs are viewport-
      // independent and running them twice would double the suite for nothing -- and the
      // import specs write rows, so a second pass would also double the data they create.
      name: 'staff-mobile',
      testMatch: '**/staffAccessibility.spec.js',
      dependencies: ['staff'],
      use: {
        ...devices['Desktop Chrome'],
        viewport: { width: 375, height: 812 },
        storageState: STAFF_STATE,
      },
    },
    {
      // The Customer Account, at desktop width. No stored state: every one of these
      // journeys begins as a stranger, because that is how a customer arrives, and
      // several of them are *about* what an unauthenticated visitor can reach.
      name: 'account',
      testMatch: ACCOUNT_SPECS,
      testIgnore: ACCOUNT_MOBILE_ONLY_SPECS,
      dependencies: ['staff-mobile'],
      use: { ...devices['Desktop Chrome'], viewport: { width: 1280, height: 800 } },
    },
    {
      // The same surface at the reference phone size. `Design.md` §14a.2 designs the
      // Customer Account for a phone, so the accessibility audit and the layout
      // assertions both run here -- reflow, horizontal overflow and target size are the
      // failures that only appear when the window is narrow.
      name: 'account-mobile',
      testMatch: ['**/accountAccessibility.spec.js', ...ACCOUNT_MOBILE_ONLY_SPECS],
      dependencies: ['account'],
      use: { ...devices['Desktop Chrome'], viewport: { width: 375, height: 812 } },
    },
    {
      // Rate limiting gets its own project, and runs after the others.
      //
      // The limiter is per-process and keyed by client address, and every test in this
      // suite arrives from the same loopback address, so a spec that deliberately
      // exhausts the allowance shares it with everything else. Isolating it here -- and
      // declaring the dependency so Playwright orders it last -- means the exhaustion
      // happens once, at the end, instead of throttling unrelated assertions and
      // producing failures that look like bugs in the page.
      name: 'rate-limit',
      testMatch: RATE_LIMIT_SPEC,
      dependencies: ['desktop', 'mobile-375', 'staff-mobile', 'account-mobile'],
      use: { ...devices['Desktop Chrome'], viewport: { width: 1280, height: 800 } },
    },
  ],
});
