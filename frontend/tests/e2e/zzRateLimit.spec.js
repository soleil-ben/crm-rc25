/**
 * Public tracking rate limiting, end to end.
 *
 * In its own file, named to sort **last**, because these tests deliberately exhaust a
 * limiter the whole application shares. Run in the middle of the suite they would fail
 * every lookup that came after them -- which would be a property of the limiter working,
 * not of anything being broken.
 *
 * Order inside the file matters too. The forged-header test runs **first**, against a
 * drained window, because that is the only way it proves anything: if the limiter had
 * been exhausted already, its first request would return 429 regardless of what the
 * header said.
 */

import { expect, test } from './diagnostics.js';
import { loadSeedReferences, UNKNOWN_REFERENCE } from './fixtures.js';

const references = loadSeedReferences();

const BASE_URL = process.env.E2E_BASE_URL || 'http://localhost:5173';

/**
 * Enough requests to exhaust whatever allowance the server under test is configured
 * with, plus headroom. The validation run raises the limit so the rest of the suite is
 * not throttled by it, so this cannot be pinned to the 30 the application defaults to.
 */
const MAX_ATTEMPTS = Number(process.env.E2E_RATE_LIMIT_ATTEMPTS || 400);

/**
 * How long `drainLimiter` allows itself before giving up and returning false.
 */
const DRAIN_BUDGET_MS = 120_000;

/**
 * The public limiter's window, in seconds, as the application is configured.
 *
 * The harness cannot read the backend's `public_tracking_rate_limit_window_seconds`, and
 * nothing in a response carries it -- `Retry-After` appears only on a 429. This mirrors
 * the application default so the drain can wait a full window out. It does **not** change
 * the limiter: overriding it makes the test wait longer or shorter, never the server.
 */
const PUBLIC_WINDOW_SECONDS = Number(process.env.E2E_PUBLIC_LIMIT_WINDOW_SECONDS || 60);

/**
 * The timeout the two drain hooks claim for themselves.
 *
 * `drainLimiter` is bounded, but its bound is not `DRAIN_BUDGET_MS`. The deadline is
 * checked *before* each request, so the final iteration can begin at 119.9 s and then
 * sleep `Retry-After + 1` -- up to the full 60-second public window plus one. The real
 * worst case is therefore about 181 s, plus request round trips and context disposal.
 *
 * A Playwright hook does **not** inherit the `test.setTimeout(300_000)` below: that call
 * sets the timeout for tests, and a `beforeAll`/`afterAll` hook falls back to the 30 s
 * `timeout` in `playwright.config.js`. A 30-second budget cannot contain a 181-second
 * bounded wait, so the hook failed whenever the window happened to be full when it ran --
 * which, since the two page-rendering tests were changed to an intercepted 429 and now
 * finish in under a second, is every run rather than an occasional one.
 *
 * Set on the hooks themselves rather than raising the global timeout, so one slow cleanup
 * cannot quietly buy every test in the suite five extra minutes to fail in.
 *
 * The arithmetic, worst case: the 120 s deadline loop, plus a final `Retry-After + 1`
 * sleep of up to 61 s begun just inside it, plus the one-window settle of 62 s the drain
 * now performs when it saw a 429 -- about 243 s. The remaining margin covers request
 * round trips, context disposal, and a loaded machine.
 */
const DRAIN_HOOK_TIMEOUT_MS =
  DRAIN_BUDGET_MS + (PUBLIC_WINDOW_SECONDS + 2) * 1000 + 61_000 + 120_000;

/**
 * Wait until the sliding window has genuinely emptied.
 *
 * Polling until *one* request succeeds is not enough and was the first thing tried: a
 * sliding window frees its oldest slot first, so the very next test immediately refills
 * it and trips the limit again. `Retry-After` says how long until the window has rolled
 * past its oldest hit, so honouring it is both correct and the fastest correct option.
 */
/**
 * @param {object} playwright
 * @param {{windowWasFull?: boolean}} [options]
 *   `windowWasFull` says the caller *knows* the window was driven to its limit, rather
 *   than leaving the drain to infer it from a probe. The inference has a hole the comment
 *   below describes but the code could not close on its own: if the oldest hit happens to
 *   age out between the burst and the first probe, that probe answers 404, `sawLimit`
 *   stays false, and the drain returns with essentially the whole burst still counted.
 *
 *   That is what made the second of two consecutive complete suites fail -- not
 *   intermittently, but whenever the timing fell that way. This spec exhausts the limiter
 *   on purpose, so it is the one caller that never has to guess.
 */
async function drainLimiter(playwright, { windowWasFull = false } = {}) {
  const context = await playwright.request.newContext({ baseURL: BASE_URL });
  try {
    const deadline = Date.now() + DRAIN_BUDGET_MS;
    let sawLimit = windowWasFull;

    while (Date.now() < deadline) {
      const response = await context.get(`/api/v1/public/track/${references.partial}`);

      if (response.status() === 429) {
        sawLimit = true;
        const retryAfter = Number(response.headers()['retry-after'] || 5);
        await new Promise((resolve) => setTimeout(resolve, (retryAfter + 1) * 1000));
        continue;
      }

      // Below the limit -- which is not the same as an empty window.
      //
      // This is the correction. The loop used to return here, and the comment beneath it
      // claimed it did the opposite: "one success means one slot, not an empty window."
      // The code returned on the first non-429 anyway, so a drain that had just waited out
      // a full window handed back control the instant its *oldest* slot expired, with
      // essentially the whole burst still counted. The next run's first lookups then met
      // "Too many lookups" and failed as if the page were broken.
      //
      // Probing more cannot detect this: the limiter answers 404 for anything under the
      // limit, so 199 of 200 slots consumed looks exactly like an empty window, and each
      // probe consumes another slot. The only honest signal is time. When the window was
      // full, wait one whole window from now, after which every hit counted above has
      // aged out by construction.
      if (!sawLimit) return true;
      await new Promise((resolve) => setTimeout(resolve, (PUBLIC_WINDOW_SECONDS + 2) * 1000));
      return true;
    }
    return false;
  } finally {
    await context.dispose();
  }
}


/**
 * Fill the window with *fresh* hits and return the response that was refused.
 *
 * Stopping at the first 429 is not enough, and this is the subtlety that made an earlier
 * version of these tests flaky. A sliding window refuses as soon as the count is reached,
 * so the first refusal can come from hits left by the previous test -- hits that are
 * already almost a minute old and about to expire. The page would then load a second
 * later against a window that had just freed slots, and the rate-limited screen would
 * never appear.
 *
 * Draining first and then filling in a concurrent burst means every hit in the window is
 * about a second old, so the state holds for the rest of the window rather than for an
 * unpredictable fraction of it.
 */
async function exhaust(request, playwright) {
  const BATCH = 25;
  let lastRefusal = null;
  // How long a refusal must be guaranteed to hold for the browser work that follows --
  // a page load, a render, and a language switch -- to happen inside it with room spare.
  const REQUIRED_HOLD_SECONDS = 20;

  for (let pass = 0; pass < 4; pass += 1) {
    let refused = null;

    for (let sent = 0; sent < MAX_ATTEMPTS && !refused; sent += BATCH) {
      const batch = await Promise.all(
        Array.from({ length: BATCH }, () =>
          request.get(`/api/v1/public/track/${UNKNOWN_REFERENCE}`),
        ),
      );
      refused = batch.find((response) => response.status() === 429) || null;
    }

    if (!refused) return null;

    // `Retry-After` is the server telling us exactly how long this refusal holds: it is
    // computed from the oldest hit still in the window. That makes it the right thing to
    // gate on, and it needs no knowledge of the configured limit.
    //
    // The subtlety this replaced: the limiter does not record a refused request --
    // `SlidingWindowRateLimiter.check` returns early when the count is reached, without
    // appending. So hammering it after the first 429 adds nothing, and an earlier version
    // that sent "one more batch to keep the window fresh" was a no-op. If the window
    // still held hits from a previous test, its oldest entry expired while the browser
    // was loading and the rate-limited screen never rendered.
    const holdsFor = Number(refused.headers()['retry-after'] || 0);
    if (holdsFor >= REQUIRED_HOLD_SECONDS) return refused;

    // The window is mostly somebody else's older hits and is about to start freeing
    // slots. Remember the refusal -- the limiter *did* engage, which is what the API
    // assertions care about -- then wait for the window to empty and fill one we own.
    lastRefusal = refused;
    await new Promise((resolve) => setTimeout(resolve, (holdsFor + 1) * 1000));
    if (playwright) await drainLimiter(playwright);
  }
  // Every pass engaged the limiter; none of them owned the window for long enough. That
  // is a timing property of a shared window, not a failure to rate limit, so return the
  // refusal rather than null -- returning null here reported "the limit never engaged"
  // for a run in which it had engaged four times.
  return lastRefusal;
}

test.describe.configure({ mode: 'serial' });
// Draining a 60-second window plus two exhaustion loops needs more than the default.
//
// Raised with the drain correction: `exhaust` calls `drainLimiter` once per pass, and the
// drain now waits a full window out after it has seen a 429 rather than returning at the
// first freed slot. Four passes of "wait the window, refill it" is the bound, so the
// budget has to hold roughly four of them. This is the file's own timeout, not the global
// one in `playwright.config.js`, which stays at 30 s for every other spec.
test.setTimeout(600_000);

test.describe('public rate limiting', () => {
  test.beforeAll(async ({ playwright }) => {
    // Same bounded wait as the cleanup hook, so the same explicit budget. This one
    // usually returns on its first request -- the `public-drain` project has already run
    // -- but "usually" is exactly the kind of ordering assumption that produced the
    // failure this hook timeout fixes. A run started straight after another one, or a
    // run of this project alone, meets a full window here.
    test.setTimeout(DRAIN_HOOK_TIMEOUT_MS);

    // Start from a window with room, so the first test's result means something.
    await drainLimiter(playwright);
  });

  test('9b. a forged X-Forwarded-For does not win a fresh allowance', async ({ request }) => {
    let limited = false;
    for (let attempt = 0; attempt < MAX_ATTEMPTS; attempt += 1) {
      const response = await request.get(`/api/v1/public/track/${UNKNOWN_REFERENCE}`, {
        headers: {
          'X-Forwarded-For': `203.0.113.${attempt % 250}`,
          'X-Real-IP': `198.51.100.${attempt % 250}`,
          Forwarded: `for=203.0.113.${attempt % 250}`,
        },
      });
      if (response.status() === 429) {
        limited = true;
        break;
      }
    }

    // A new forwarded address per request would have produced a new bucket per request,
    // and the limit would never have engaged. It does, so the header is not trusted
    // (DEC-0007).
    expect(limited, 'a forged forwarded header bypassed the public rate limit').toBe(true);
  });

  test('9. rate limiting engages, returns Retry-After, and explains the wait', async ({
    request,
    playwright,
  }) => {
    // Exhaust the allowance explicitly rather than inheriting it from the test above.
    const limited = await exhaust(request, playwright);

    expect(limited, `the public rate limit never engaged in ${MAX_ATTEMPTS} attempts`).not.toBeNull();
    expect(Number(limited.headers()['retry-after'])).toBeGreaterThan(0);

    const body = await limited.json();
    expect(Object.keys(body).sort()).toEqual(['code', 'message']);
    expect(body.code).toBe('rate_limited');
    expect(body.message).toMatch(/wait/i);

    // The privacy headers are on the rejection too, not only on the success path.
    expect(limited.headers()['cache-control']).toContain('no-store');
    expect(limited.headers()['x-robots-tag']).toContain('noindex');

  });

  /**
   * How the page renders a refusal, proven deterministically.
   *
   * Everything above uses the real limiter and must: that the limit engages at all, and
   * that a forged header cannot win a fresh allowance, are security properties and are
   * worth nothing if simulated.
   *
   * What the next two tests check is different -- that React renders the refusal as a
   * designed screen, in both languages. That is a property of the page, not of the
   * limiter, and coupling it to a shared sliding window made it flaky: the window frees
   * its oldest slot while the browser is still loading, the lookup succeeds, and the
   * rate-limited screen never appears. Three consecutive runs failed that way.
   *
   * The refusal is therefore served by intercepting the API call, with the exact status,
   * body and headers the application itself returns -- asserted against the live one in
   * the test above, so the fixture cannot drift away from the real response.
   *
   * The limiter's own behaviour is covered at the API level here and by eight backend
   * tests: engagement and Retry-After, malformed references, bucket separation, bucket
   * pruning, privacy headers on a 429, and that a refused request performs no database
   * query at all.
   */
  async function serveRateLimited(page) {
    await page.route('**/api/v1/public/track/**', (route) =>
      route.fulfill({
        status: 429,
        contentType: 'application/json',
        headers: {
          'retry-after': '42',
          'cache-control': 'no-store, no-cache, must-revalidate, private',
          'x-robots-tag': 'noindex, nofollow, noarchive',
          'referrer-policy': 'no-referrer',
        },
        body: JSON.stringify({
          code: 'rate_limited',
          message: 'Too many lookups from this connection. Please wait and try again.',
        }),
      }),
    );
  }

  test('the refusal renders as a designed screen, not a raw failure', async ({ page }) => {
    await serveRateLimited(page);

    await page.goto(`/track/${references.partial}`);
    await expect(page.getByText('Too many lookups')).toBeVisible();
    await expect(page.getByText(/wait/i).first()).toBeVisible();

    const text = await page.locator('main').innerText();
    // A customer-friendly message with no internals in it.
    expect(text).not.toMatch(/bucket|limiter|429|X-Forwarded|sliding window/i);
    // And no personal information on a failure screen.
    expect(text).not.toContain('@');
  });

  test('the rate-limit screen is translated', async ({ page }) => {
    await serveRateLimited(page);

    await page.goto(`/track/${references.partial}`);
    await expect(page.getByText('Too many lookups')).toBeVisible();

    // Click and assert together, retried.
    //
    // A click is a single action, and Playwright's actionability checks say the button is
    // visible and stable -- not that React has attached its handler. On a cold dev server
    // the first page of a run compiles on demand, and a click that lands before hydration
    // is silently dropped: the button is there, the press does nothing, and the assertion
    // that follows waits ten seconds for a language change nobody asked for. That is what
    // failed on the first of three consecutive runs and passed on the other two.
    //
    // `toPass` retries the click *and* the assertion, so a dropped first press costs a
    // retry rather than the run. It cannot mask a real failure: if the switch never works,
    // every attempt fails and the test still does.
    await expect(async () => {
      await page.getByRole('button', { name: 'Tiếng Việt' }).click();
      await expect(page.getByText('Bạn đã tra cứu quá nhiều lần')).toBeVisible({
        timeout: 2000,
      });
    }).toPass({ timeout: 20_000 });
  });

  test.afterAll(async ({ playwright }) => {
    // The cleanup runs unconditionally and stays blocking. This file sorts last *today*,
    // but "nothing runs after us" is a property of the current file list, not a guarantee
    // -- and a suite that leaves a shared limiter exhausted is a trap for whatever is
    // added next. Draining is cheap; rediscovering why an unrelated spec returns 429 is
    // not. See DRAIN_HOOK_TIMEOUT_MS for why the hook needs its own budget.
    test.setTimeout(DRAIN_HOOK_TIMEOUT_MS);

    // Leave the limiter with room, so the next Playwright project -- or the next complete
    // run of this suite -- does not begin against an exhausted window.
    //
    // `windowWasFull` is not a hint, it is a fact: every test in this file has just spent
    // the allowance on purpose. Letting the drain re-derive it from one probe is what made
    // a second consecutive suite fail its first public lookups, because a 404 on that
    // probe means one slot freed, not a free window.
    await drainLimiter(playwright, { windowWasFull: true });
  });
});
