/**
 * Nothing this run does leaves the machine.
 *
 * The public tracking page already has this assertion (`publicTracking.spec.js` checks
 * every request against `isFirstParty`). The staff application did not, and it is the
 * larger surface: it renders customer names, addresses, shipment values and imported CSV
 * contents, and a single font, icon, map tile or analytics beacon loaded from a third
 * party would carry a referrer from a page displaying them.
 *
 * So this walks the staff screens with a session and asserts, of every request the browser
 * made — document, script, stylesheet, font, image, XHR and beacon alike — that it went to
 * loopback. Not "no known tracker": loopback. A blocklist is a guess about which hosts are
 * bad, and the question here is not whether a host is bad but whether it is ours.
 *
 * It also pins the run itself. `E2E_BASE_URL` and `E2E_BACKEND_URL` are set by
 * `scripts/run_e2e.mjs` and are loopback by construction; asserting it here means a future
 * change that pointed the suite at a deployed environment fails a test rather than quietly
 * sending a staging server a few dozen writes.
 */

import { expect, test } from './diagnostics.js';
import { recordRequests } from './fixtures.js';

/** Every staff screen that loads data, in one pass. */
const SCREENS = [
  '/',
  '/customers',
  '/customers/import',
  '/shipments',
  '/segments',
  '/follow-ups',
  '/reports',
  '/settings',
];

/** The only hosts a request may go to. */
const LOOPBACK_HOSTNAMES = new Set(['localhost', '127.0.0.1', '::1', '[::1]', '0.0.0.0']);

/** Schemes that never reach the network: the browser resolves them in the page. */
const LOCAL_SCHEMES = new Set(['data:', 'blob:', 'about:', 'chrome-error:']);

function isLoopback(rawUrl) {
  try {
    const parsed = new URL(rawUrl);
    if (LOCAL_SCHEMES.has(parsed.protocol)) return true;
    return LOOPBACK_HOSTNAMES.has(parsed.hostname);
  } catch {
    // An unparseable URL is not something to wave through.
    return false;
  }
}

test.describe('Network boundary', () => {
  test('every request the staff application makes goes to loopback', async ({ page }) => {
    const requests = recordRequests(page);

    for (const screen of SCREENS) {
      await page.goto(screen);
      // `networkidle` rather than `load`: a late analytics beacon or font fetch is
      // exactly the thing this test exists to catch, and `load` fires before one.
      await page.waitForLoadState('networkidle');
    }

    const offsite = requests.filter((request) => !isLoopback(request.url));
    expect(
      offsite.map((request) => `${request.method} ${new URL(request.url).origin}`),
      'a staff screen requested something off this machine',
    ).toEqual([]);

    // A guard on the guard: if navigation silently failed, the list would be empty and
    // the assertion above would pass having proved nothing.
    expect(requests.length).toBeGreaterThan(SCREENS.length);
  });

  test('the run is pointed at loopback origins', async () => {
    for (const name of ['E2E_BASE_URL', 'E2E_BACKEND_URL']) {
      const value = process.env[name];
      expect(value, `${name} is not set; the suite was not started by run_e2e.mjs`).toBeTruthy();
      expect(isLoopback(value), `${name} is not a loopback origin: ${value}`).toBe(true);
    }
  });

  test('the database this run writes to is an isolated scratch file', async () => {
    // The backend refuses anything else at startup (`app.core.e2e_guard`), and the
    // handshake in `globalSetup.js` proves the backend answering is this run's. This is
    // the third leg: what the harness *believes* it configured, asserted from inside the
    // suite, so all three have to agree.
    const url = process.env.E2E_DATABASE_URL;
    expect(url, 'E2E_DATABASE_URL is not set; the suite was not started by run_e2e.mjs').toBeTruthy();
    expect(url.endsWith('.e2e.db'), `not a scratch database: ${url}`).toBe(true);
    // `data/e2e/<first 8 of the run id>/`. Short on purpose: see `RUN_DIRECTORY_CHARS` in
    // `scripts/e2e_env.py` — the full artifact path has to stay inside Windows MAX_PATH.
    expect(url).toMatch(/\/data\/e2e\/[0-9a-f]{8}\//);
    expect(url).not.toMatch(/solaris_crm\.db|\.uat\.db/);
  });
});
