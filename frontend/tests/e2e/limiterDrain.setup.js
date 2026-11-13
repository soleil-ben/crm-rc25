/**
 * Wait for the public rate limiter to have room, between projects.
 *
 * `globalSetup` drains the limiter once, before the run starts. That was enough while the
 * suite had one public project. With two — desktop and mobile-375, both replaying the
 * same lookups from the same loopback address — the first project consumes the allowance
 * and the second begins against an exhausted window. The result is a scatter of
 * "Too many lookups" failures in the second project that look like layout bugs and are
 * nothing of the kind.
 *
 * This is a *harness* fix, not a weakening of the test. The limiter still applies, and
 * `zzRateLimit.spec.js` still proves it works by deliberately exhausting it. All this does
 * is stop one project's traffic from being charged to the next one's assertions.
 */

import { expect, test as setup } from '@playwright/test';

const PROBE_REFERENCE = 'SX-CAV-ABCDEFGHJKLM';
const DEADLINE_MS = 150_000;

/** See `zzRateLimit.spec.js`: the configured window, mirrored so a drain can wait it out. */
const PUBLIC_WINDOW_SECONDS = Number(process.env.E2E_PUBLIC_LIMIT_WINDOW_SECONDS || 60);

setup('wait for the public rate-limit window to reopen', async ({ request }) => {
  // This setup is a *test*, so without this it runs on the 30 s timeout in
  // `playwright.config.js` -- and it is a step whose whole job is to wait out a window
  // that can be 60 s long. It passed only because it has so far always met a window with
  // room; the first time it met a full one it would fail on the timeout rather than wait,
  // which is the same defect the drain hooks in `zzRateLimit.spec.js` carried. Its own
  // deadline plus a final `Retry-After + 1` plus one settle window, with margin.
  setup.setTimeout(DEADLINE_MS + (PUBLIC_WINDOW_SECONDS + 2) * 1000 + 61_000 + 60_000);

  const deadline = Date.now() + DEADLINE_MS;
  let lastStatus = 0;
  let sawLimit = false;

  while (Date.now() < deadline) {
    const response = await request.get(`/api/v1/public/track/${PROBE_REFERENCE}`);
    lastStatus = response.status();

    // A generic 404 means the endpoint is up and the window is *below the limit*. It is
    // deliberately the same answer an unknown-but-valid reference gets (DEC-0051) -- and
    // it is not proof of an empty window, because the limiter answers 404 for anything
    // under the limit. If this loop saw a 429, the window had been full, so wait one whole
    // window out rather than letting the next project inherit most of that burst.
    if (lastStatus === 404) {
      if (!sawLimit) return;
      console.log(`[e2e] limiter window settling for ${PUBLIC_WINDOW_SECONDS + 2}s`);
      await new Promise((resolve) => setTimeout(resolve, (PUBLIC_WINDOW_SECONDS + 2) * 1000));
      return;
    }

    if (lastStatus !== 429) {
      throw new Error(
        `The public tracking endpoint answered ${lastStatus}. Expected 404 (window open) ` +
          'or 429 (window full).',
      );
    }

    sawLimit = true;
    const retryAfter = Number(response.headers()['retry-after'] || 5);
    console.log(`[e2e] public limiter full; waiting ${retryAfter + 1}s before the next project`);
    await new Promise((resolve) => setTimeout(resolve, (retryAfter + 1) * 1000));
  }

  expect(lastStatus, 'the public rate limiter did not reopen in time').toBe(404);
});
