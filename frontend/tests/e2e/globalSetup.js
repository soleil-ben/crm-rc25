/**
 * Global setup: prove whose backend this is, then start from a limiter with room.
 *
 * Runs once, before any project, and therefore before any test can sign in, import a CSV,
 * or create a customer. That ordering is the whole point of doing the check here: the
 * failure this guards against is not a wrong assertion, it is a *write*, and a write that
 * has already happened cannot be un-asserted.
 *
 * ## 1. The handshake
 *
 * On 2026-09-20 this suite ran against `data/solaris_crm.db` and added forty customers,
 * thirty-two import batches and a hundred and ninety-five audit rows to it. Nothing in the
 * harness was in a position to notice: it opened `http://localhost:5173`, something
 * answered, and the staff specs wrote to whatever database that something was serving.
 *
 * `scripts/e2e_env.py` now builds a scratch database that no other run shares, and
 * `scripts/run_e2e.mjs` starts a backend for it. But a launcher checking its own arguments
 * proves nothing about what the *browser* reached, so the run proves the connection
 * instead: `run_e2e.mjs` mints a random identifier, gives it to the backend's environment
 * and to a marker row inside that backend's database, and this setup presents it **over
 * the same proxy the browser will use** and requires the server to confirm both.
 *
 * Every wrong answer is a stop, not a warning:
 *
 * | What answered | What happens |
 * |---|---|
 * | a development or production backend | the route does not exist there — 404 — and the run stops |
 * | a stale E2E backend from a previous run | its identifier differs — 409 — and the run stops |
 * | the right process serving the wrong database | the marker differs — 409 — and the run stops |
 * | nothing at all | connection refused, and the run stops |
 * | Playwright started outside `run_e2e.mjs` | no identifier to present, and the run stops |
 *
 * The identifier is not a credential: presenting the right one returns `{"status":"ok"}`
 * and grants nothing. It answers "are you the process this run created?", and that is all
 * it can be used for.
 *
 * ## 2. The limiter
 *
 * The public limiter lives in the backend process and is keyed by client address, so a
 * suite that began against a partly consumed window would fail lookups for a reason that
 * has nothing to do with the code under test. Waiting here rather than retrying inside
 * each test keeps the failure honest.
 */

import { request } from '@playwright/test';

const PROBE_REFERENCE = 'SX-CAV-ABCDEFGHJKLM';

/** See `zzRateLimit.spec.js`: the configured window, mirrored so a drain can wait it out. */
const PUBLIC_WINDOW_SECONDS = Number(process.env.E2E_PUBLIC_LIMIT_WINDOW_SECONDS || 60);

/** Must match `app.api.e2e.RUN_ID_HEADER` and `app.main.E2E_PREFIX`. */
const RUN_ID_HEADER = 'X-E2E-Run-Id';
const HANDSHAKE_PATH = '/api/v1/e2e/handshake';

const START_COMMAND = 'npm run e2e --prefix frontend';

/**
 * Confirm the backend behind this base URL was created by this run.
 *
 * Deliberately requested through `baseURL` — the Vite dev server — rather than straight at
 * the backend port. The browser's requests are proxied, and it is the proxied destination
 * that receives every write the suite performs; checking the backend directly would prove
 * something true about a connection no test uses.
 */
async function verifyRunOwnership(baseURL) {
  const runId = process.env.E2E_RUN_ID;
  if (!runId) {
    throw new Error(
      'E2E_RUN_ID is not set, so this suite cannot tell which backend it is about to ' +
        'write to.\n' +
        `Start it with: ${START_COMMAND}\n` +
        'That command builds an isolated .e2e.db, starts a backend for it, and passes ' +
        'the identifier this check needs. Running `playwright test` directly reaches ' +
        'whatever happens to be listening, which is how the development database was ' +
        'written to on 2026-09-20.',
    );
  }

  const context = await request.newContext({ baseURL });
  try {
    let response;
    try {
      response = await context.get(HANDSHAKE_PATH, { headers: { [RUN_ID_HEADER]: runId } });
    } catch (error) {
      throw new Error(
        `Nothing answered ${baseURL}${HANDSHAKE_PATH} (${error.message}).\n` +
          `Start the suite with: ${START_COMMAND}`,
      );
    }

    if (response.status() === 404) {
      throw new Error(
        `The server behind ${baseURL} has no end-to-end handshake, so it is not a ` +
          'backend this run started — it is a development, UAT or production process ' +
          'that was already listening.\n' +
          'Refusing to run: the staff specs write customers, imports and audit rows, ' +
          'and they would be written into that process’s database.\n' +
          `Start the suite with: ${START_COMMAND}`,
      );
    }
    if (response.status() !== 200) {
      throw new Error(
        `The server behind ${baseURL} answered the handshake with ${response.status()}, ` +
          'which means it belongs to a different run — a stale backend from an earlier ' +
          'suite, or the right process serving a database this run did not create.\n' +
          'Refusing to run.\n' +
          `Start the suite with: ${START_COMMAND}`,
      );
    }
  } finally {
    await context.dispose();
  }
}

export default async function globalSetup(config) {
  const baseURL =
    process.env.E2E_BASE_URL || config.projects[0]?.use?.baseURL || 'http://localhost:5173';

  await verifyRunOwnership(baseURL);
  console.log('[e2e] handshake ok: backend and database belong to this run');

  const context = await request.newContext({ baseURL });

  try {
    // Budget: the wait loop, a final `Retry-After + 1`, and one settle window.
    const deadline = Date.now() + 150_000;
    let lastStatus = 0;
    let sawLimit = false;

    while (Date.now() < deadline) {
      const response = await context.get(`/api/v1/public/track/${PROBE_REFERENCE}`);
      lastStatus = response.status();

      if (lastStatus === 404) {
        // The endpoint is up and the window is below the limit -- which is not the same
        // as an empty window. The limiter answers 404 for anything under the limit, so
        // 199 of 200 slots consumed is indistinguishable from none. If this loop ever saw
        // a 429, the window had been full, and returning now would hand the suite a
        // window still holding most of that burst. Wait one whole window instead, after
        // which every hit counted above has aged out. See `zzRateLimit.spec.js`.
        if (!sawLimit) return;
        console.log(`[e2e] limiter window settling for ${PUBLIC_WINDOW_SECONDS + 2}s`);
        await new Promise((resolve) => setTimeout(resolve, (PUBLIC_WINDOW_SECONDS + 2) * 1000));
        return;
      }
      if (lastStatus !== 429) {
        throw new Error(
          `The public tracking endpoint answered ${lastStatus} at ${baseURL}. ` +
            `Start the suite with: ${START_COMMAND}`,
        );
      }

      sawLimit = true;
      const retryAfter = Number(response.headers()['retry-after'] || 5);
      console.log(`[e2e] rate limiter is full; waiting ${retryAfter + 1}s for the window`);
      await new Promise((resolve) => setTimeout(resolve, (retryAfter + 1) * 1000));
    }

    throw new Error(
      'The public rate limiter did not drain within 150 seconds. ' +
        'Another client is probably hammering the endpoint.',
    );
  } finally {
    await context.dispose();
  }
}
