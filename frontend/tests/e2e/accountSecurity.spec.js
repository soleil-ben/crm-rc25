/**
 * Browser-level security and privacy for the Customer Account.
 *
 * Section 14 of the Phase 12 instruction, and workflow 18. Everything here is a negative
 * — what a cookie does *not* authenticate, what a page does *not* request, what the back
 * button does *not* reveal — and a negative is only provable by watching the whole
 * conversation rather than one request.
 */

import { expect, test } from './diagnostics.js';
import {
  PUBLIC_API_PREFIX,
  STAFF_API_PREFIXES,
  activatedCustomer,
  freshAddress,
  recordRequests,
  register,
  signIn,
  signInStaff,
} from './accountHelpers.js';

/** A replacement password for the reset-token journey. Synthetic. */
const NEW_PASSWORD = 'a-replacement-passphrase-for-history-2026';

const TRACKERS = [
  /google-analytics/i,
  /googletagmanager/i,
  /doubleclick/i,
  /facebook\.(net|com)/i,
  /sentry\.io/i,
  /hotjar/i,
  /segment\.(io|com)/i,
  /mixpanel/i,
  /fullstory/i,
  /clarity\.ms/i,
  /fonts\.(googleapis|gstatic)\.com/i,
  /cdn\.jsdelivr/i,
  /unpkg\.com/i,
];

function isFirstParty(url, baseUrl) {
  try {
    const parsed = new URL(url, baseUrl);
    const base = new URL(baseUrl);
    return (
      parsed.host === base.host ||
      parsed.protocol === 'data:' ||
      parsed.protocol === 'blob:' ||
      parsed.protocol === 'about:'
    );
  } catch {
    return false;
  }
}

test.describe('realm separation', () => {
  test('a staff cookie authenticates nothing on the Customer Account', async ({ browser }) => {
    // One context, signed in as staff, then sent to the Customer Account. This is the
    // realm-cookie substitution case: the browser holds a valid staff session and offers
    // it to every same-origin request it makes.
    const context = await browser.newContext();
    const page = await context.newPage();
    try {
      await signInStaff(page);

      const cookies = await context.cookies();
      expect(cookies.map((cookie) => cookie.name)).toContain('solaris_session');
      expect(cookies.map((cookie) => cookie.name)).not.toContain('solaris_account_session');

      await page.goto('/account/shipments');
      // The Customer Account does not recognise the staff session, so the guard sends
      // this browser to sign in — it does not serve a shipment list.
      await expect(page.getByRole('heading', { name: 'Sign in', level: 1 })).toBeVisible();
      expect(await page.locator('main').innerText()).not.toContain('SX-');

      // Nor does the API. Asked directly, with the staff cookies attached, it answers 401.
      const response = await page.request.get('/api/v1/account/shipments');
      expect(response.status()).toBe(401);
    } finally {
      await page.waitForLoadState('networkidle', { timeout: 10_000 }).catch(() => {});
      await context.close();
    }
  });

  test('a Customer Account cookie authenticates nothing on the Staff Portal', async ({
    page,
    browser,
  }) => {
    const { email } = await activatedCustomer(page, browser, { label: 'realm' });
    await signIn(page, email);
    await expect(page.getByRole('heading', { name: 'My shipments', level: 1 })).toBeVisible();

    const cookies = await page.context().cookies();
    const names = cookies.map((cookie) => cookie.name);
    expect(names).toContain('solaris_account_session');
    expect(names).not.toContain('solaris_session');

    // The staff portal, in the same browser, offers its sign-in form rather than a
    // dashboard.
    await page.goto('/');
    await expect(page.getByRole('heading', { name: /Good (morning|afternoon|evening)/ })).toHaveCount(
      0,
    );

    // And every staff API the customer cookie is offered to answers 401 — never 403,
    // which would imply the caller had been authenticated (T-12).
    for (const path of ['/api/v1/auth/me', '/api/v1/customers', '/api/v1/shipments']) {
      const response = await page.request.get(path);
      expect(response.status(), `${path} answered ${response.status()}`).toBe(401);
    }

    // The staff approval API is a staff API too, and a customer must not reach it.
    const review = await page.request.get('/api/v1/customer-account/registrations');
    expect(review.status()).toBe(401);
  });

  test('Public Tracking mounts neither authenticated provider', async ({ page, browser }) => {
    const { email } = await activatedCustomer(page, browser, { label: 'public' });
    await signIn(page, email);
    await expect(page.getByRole('heading', { name: 'My shipments', level: 1 })).toBeVisible();

    const requests = recordRequests(page);
    await page.goto('/track');
    await page.waitForLoadState('networkidle', { timeout: 5000 }).catch(() => {});

    // With a live Customer Account session in the browser, the public page still asks for
    // neither `/auth/me` nor `/account/me`.
    const urls = requests.map((request) => request.url);
    expect(urls.filter((url) => url.includes('/api/v1/auth/'))).toEqual([]);
    expect(urls.filter((url) => url.includes('/api/v1/account/'))).toEqual([]);
  });
});

test.describe('one customer cannot reach another', () => {
  test('customer A cannot display customer B’s shipment', async ({ page, browser }) => {
    // B is linked to a seeded customer with history; A is a fresh account with none.
    const bContext = await browser.newContext();
    const bPage = await bContext.newPage();
    let bReference;
    try {
      const { activateAgainst } = await import('./accountSeeded.js');
      bReference = await activateAgainst(bPage, browser);
    } finally {
      // Settle before closing: an abandoned request is still a request the server is
      // finishing, and SQLite takes one writer at a time (`accountHelpers.closeStaffContext`).
      await bPage.waitForLoadState('networkidle', { timeout: 10_000 }).catch(() => {});
      await bContext.close();
    }

    const { email: aEmail } = await activatedCustomer(page, browser, { label: 'other' });
    await signIn(page, aEmail);
    await expect(page.getByRole('heading', { name: 'My shipments', level: 1 })).toBeVisible();

    // The list contains none of B's references.
    expect(await page.locator('main').innerText()).not.toContain(bReference);

    // Asking for one by hand is the generic not-found, identical to an unknown one.
    await page.goto(`/account/shipments/${bReference}`);
    await expect(
      page.getByRole('heading', { name: 'We could not find that shipment', level: 1 }),
    ).toBeVisible();
    const foreign = await page.locator('main').innerText();

    await page.goto('/account/shipments/SX-CAV-ABCDEFGHJKLM');
    await expect(
      page.getByRole('heading', { name: 'We could not find that shipment', level: 1 }),
    ).toBeVisible();
    expect(await page.locator('main').innerText()).toBe(foreign);

    // Filtering by it is an empty list, not a hint that it exists: the old exact-ID link,
    // and the keyword search (UAT round 10) with the whole ID or part of it.
    for (const query of [
      `reference=${bReference}`,
      `q=${bReference}`,
      `q=${bReference.slice(-8).toLowerCase()}`,
    ]) {
      await page.goto(`/account/shipments?${query}`);
      await expect(page.getByText('No shipments match those filters')).toBeVisible();
    }

    // And the API, asked directly with A's session, says the same thing.
    const response = await page.request.get(`/api/v1/account/shipments/${bReference}`);
    expect(response.status()).toBe(404);
  });

  test('changing the path, the query or the cached state grants nothing', async ({
    page,
    browser,
  }) => {
    const { email } = await activatedCustomer(page, browser, { label: 'tamper' });
    await signIn(page, email);
    await expect(page.getByRole('heading', { name: 'My shipments', level: 1 })).toBeVisible();

    // A customer id in the query string is not an authorization input (OD-29).
    for (const query of [
      '?customer_id=1',
      '?customer_public_id=STCA-000001',
      '?customer=1&all=true',
      '?limit=9999',
      '?offset=-1',
    ]) {
      await page.goto(`/account/shipments${query}`);
      // Either the page renders this account's own rows, or it says the filter was not
      // acceptable. What it never does is render somebody else's history.
      const text = await page.locator('main').innerText();
      expect(text).not.toContain('Internal note');
    }

    // Rewriting the cached session in the page's own JavaScript changes nothing: the
    // server re-reads the identity on every request and the cache holds no grant.
    await page.goto('/account/shipments');
    await page.evaluate(() => {
      window.__tampered = true;
      try {
        window.localStorage.setItem('solaris_account_session', 'forged');
        window.sessionStorage.setItem('account', JSON.stringify({ status: 'active' }));
      } catch {
        // A storage-less context is fine; nothing reads these.
      }
    });
    await page.reload();
    await expect(page.getByRole('heading', { name: 'My shipments', level: 1 })).toBeVisible();
    const afterTamper = await page.locator('main').innerText();
    expect(afterTamper).not.toContain('Internal note');
  });
});

test.describe('after signing out', () => {
  test('the back button reveals no protected content', async ({ page, browser }) => {
    const { email } = await activatedCustomer(page, browser, { label: 'back' });
    await signIn(page, email);
    await expect(page.getByRole('heading', { name: 'My shipments', level: 1 })).toBeVisible();

    await page.getByRole('button', { name: 'Sign out' }).click();
    await expect(page.getByRole('heading', { name: 'Sign in', level: 1 })).toBeVisible();

    await page.goBack();
    // Whatever the browser restores, it is not the shipment list: the cache was cleared
    // and the server answers 401.
    await expect(page.getByRole('heading', { name: 'My shipments', level: 1 })).toHaveCount(0);
    expect(await page.locator('body').innerText()).not.toContain('SX-');

    await page.goForward();
    await page.goto('/account/shipments');
    await expect(page.getByRole('heading', { name: 'Sign in', level: 1 })).toBeVisible();
  });

  test('protected responses are not cached', async ({ page, browser }) => {
    const { email } = await activatedCustomer(page, browser, { label: 'cache' });

    // Waited for by name rather than collected from an event listener. A listener that
    // found nothing is indistinguishable from a listener attached too late, and the first
    // version of this test failed that way — reporting "no responses" about a page that
    // had plainly loaded.
    const sessionRead = page.waitForResponse(
      (response) => response.url().includes('/api/v1/account/me'),
    );
    const listRead = page.waitForResponse(
      (response) => response.url().includes('/api/v1/account/shipments'),
    );

    await signIn(page, email);
    await expect(page.getByRole('heading', { name: 'My shipments', level: 1 })).toBeVisible();

    for (const response of [await sessionRead, await listRead]) {
      expect(
        response.headers()['cache-control'],
        `${response.url()} was cacheable`,
      ).toContain('no-store');
    }

    // The shipment routes additionally refuse indexing and archiving.
    const list = await listRead;
    expect(list.headers()['x-robots-tag']).toContain('noindex');
    expect(list.headers()['referrer-policy']).toBe('no-referrer');
  });
});

test.describe('tokens and storage', () => {
  test('a verification token does not survive in usable browser history', async ({ page }) => {
    const email = freshAddress('history-token');
    await register(page, email);

    const { verificationLinkFor, tokenFromLink } = await import('./mailCapture.js');
    const link = await verificationLinkFor(email);
    const token = tokenFromLink(link);
    expect(token).toBeTruthy();
    // The link carries the token in the fragment, which a browser never sends to a
    // server (CA-SEC-07). Not in the path, not in the query string.
    expect(new URL(link, 'http://localhost').hash).toContain('token=');
    expect(new URL(link, 'http://localhost').search).toBe('');

    const depth = await page.evaluate(() => window.history.length);
    await page.goto(link);
    await expect(page.getByRole('heading', { name: 'Email confirmed', level: 1 })).toBeVisible();

    // Gone from the address bar: no query string and no fragment.
    expect(page.url()).not.toContain(token);
    expect(new URL(page.url()).search).toBe('');
    expect(new URL(page.url()).hash).toBe('');

    // Gone from the page, including its markup and its title.
    expect(await page.content()).not.toContain(token);
    expect(await page.title()).not.toContain(token);

    // One new history entry for the landing, and it is the stripped one: the token was
    // removed with `replaceState`, not with a push.
    expect(await page.evaluate(() => window.history.length)).toBe(depth + 1);

    // And going back does not return to it: the landing replaced its history entry.
    await page.goBack();
    expect(page.url()).not.toContain(token);
  });

  test('a password-reset token does not survive in usable browser history', async ({
    page,
    browser,
  }) => {
    const { email } = await activatedCustomer(page, browser, { label: 'history-reset' });
    await page.goto('/account/forgot-password');
    await page.getByLabel('Email address', { exact: true }).fill(email);
    await page.getByRole('button', { name: 'Send the reset link' }).click();
    await expect(page.getByRole('heading', { name: 'Check your email', level: 1 })).toBeVisible();

    const { resetLinkFor, tokenFromLink } = await import('./mailCapture.js');
    const link = await resetLinkFor(email);
    const token = tokenFromLink(link);
    expect(token).toBeTruthy();
    expect(new URL(link, 'http://localhost').hash).toContain('token=');

    const requests = [];
    page.on('request', (request) => requests.push(request.url()));

    const depth = await page.evaluate(() => window.history.length);
    await page.goto(link);
    await expect(
      page.getByRole('heading', { name: 'Choose a new password', level: 1 }),
    ).toBeVisible();

    // Stripped before the form is on screen, and in neither shape.
    expect(new URL(page.url()).search).toBe('');
    expect(new URL(page.url()).hash).toBe('');
    expect(page.url()).not.toContain(token);
    expect(await page.content()).not.toContain(token);
    expect(await page.evaluate(() => window.history.length)).toBe(depth + 1);

    // The fragment never left the browser: no request the page made carried the token.
    expect(requests.some((url) => url.includes(token))).toBe(false);

    // The token still works once, from memory, when the form is submitted.
    await page.getByLabel('New password', { exact: true }).fill(NEW_PASSWORD);
    await page.getByLabel('New password again', { exact: true }).fill(NEW_PASSWORD);
    await page.getByRole('button', { name: 'Change password' }).click();
    await expect(page.getByRole('heading', { name: 'Password updated', level: 1 })).toBeVisible();

    // And only once.
    await page.goto(link);
    await page.getByLabel('New password', { exact: true }).fill(NEW_PASSWORD);
    await page.getByLabel('New password again', { exact: true }).fill(NEW_PASSWORD);
    await page.getByRole('button', { name: 'Change password' }).click();
    await expect(page.getByText('That link is no longer valid. Request a new one.')).toBeVisible();
  });

  test('nothing is written to localStorage or sessionStorage', async ({ page, browser }) => {
    const { email } = await activatedCustomer(page, browser, { label: 'storage' });
    await signIn(page, email);
    await expect(page.getByRole('heading', { name: 'My shipments', level: 1 })).toBeVisible();
    await page.goto('/account/shipments');

    const stored = await page.evaluate(() => ({
      local: Object.entries({ ...window.localStorage }),
      session: Object.entries({ ...window.sessionStorage }),
    }));
    expect(stored.local).toEqual([]);
    expect(stored.session).toEqual([]);
  });

  test('no secret reaches the console', async ({ page, browser }) => {
    const lines = [];
    page.on('console', (message) => lines.push(message.text()));
    page.on('pageerror', (error) => lines.push(String(error)));

    const { email } = await activatedCustomer(page, browser, { label: 'console' });
    await signIn(page, email);
    await expect(page.getByRole('heading', { name: 'My shipments', level: 1 })).toBeVisible();

    const joined = lines.join('\n');
    expect(joined).not.toContain('correct-horse-battery-staple');
    expect(joined).not.toMatch(/solaris_account_session/);
    expect(joined).not.toMatch(/token=/);
  });
});

test.describe('the network conversation', () => {
  test('the Customer Account calls no staff endpoint and no public one', async ({
    page,
    browser,
  }) => {
    const { email } = await activatedCustomer(page, browser, { label: 'network' });

    const requests = recordRequests(page);
    await signIn(page, email);
    await expect(page.getByRole('heading', { name: 'My shipments', level: 1 })).toBeVisible();
    await page.goto('/account/shipments');
    await page.waitForLoadState('networkidle', { timeout: 5000 }).catch(() => {});

    const apiCalls = requests
      .map((request) => new URL(request.url).pathname)
      .filter((path) => path.startsWith('/api/'));

    expect(apiCalls.length).toBeGreaterThan(0);
    for (const path of apiCalls) {
      expect(path.startsWith('/api/v1/account/'), `called ${path}`).toBe(true);
    }
    for (const prefix of STAFF_API_PREFIXES) {
      expect(apiCalls.filter((path) => path.startsWith(prefix))).toEqual([]);
    }
    expect(apiCalls.filter((path) => path.startsWith(PUBLIC_API_PREFIX))).toEqual([]);
  });

  test('no external request, and no third-party analytics, font or asset', async ({
    page,
    browser,
    baseURL,
  }) => {
    const { email } = await activatedCustomer(page, browser, { label: 'external' });

    const requests = recordRequests(page);
    await signIn(page, email);
    await expect(page.getByRole('heading', { name: 'My shipments', level: 1 })).toBeVisible();
    await page.goto('/account/register');
    await page.goto('/account/sign-in');
    await page.waitForLoadState('networkidle', { timeout: 5000 }).catch(() => {});

    const offOrigin = requests
      .map((request) => request.url)
      .filter((url) => !isFirstParty(url, baseURL) && !url.startsWith('http://127.0.0.1:'));
    expect(offOrigin, `off-origin: ${offOrigin.join(', ')}`).toEqual([]);

    for (const pattern of TRACKERS) {
      const matches = requests.map((request) => request.url).filter((url) => pattern.test(url));
      expect(matches, `${pattern} matched ${matches.join(', ')}`).toEqual([]);
    }
  });
});

test.describe('the Customer Account carries no staff chrome', () => {
  test('no staff navigation, no staff terminology, no "portal"', async ({ page, browser }) => {
    const { email } = await activatedCustomer(page, browser, { label: 'chrome' });
    await signIn(page, email);
    await expect(page.getByRole('heading', { name: 'My shipments', level: 1 })).toBeVisible();

    for (const label of ['Dashboard', 'Customers', 'Segments', 'Follow-ups', 'Reports', 'Settings']) {
      await expect(page.getByRole('link', { name: label })).toHaveCount(0);
    }
    const body = await page.locator('body').innerText();
    expect(body).not.toMatch(/\bPortal\b/);
    // Staff vocabulary a customer should never read.
    expect(body).not.toMatch(/booking state|operational state|lifecycle/i);
  });

  // OD-71 (2026-10-20) supersedes OD-39: Vietnamese first, English as an option, with the
  // switch in the header. The choice is kept in memory, never in browser storage.
  test('offers a language switch, and switching changes the page language', async ({ page }) => {
    await page.goto('/account/sign-in');
    const switcher = page.getByRole('group', { name: /language|ngôn ngữ/i });
    await expect(switcher).toHaveCount(1);
    await expect(switcher.getByRole('button', { name: 'English' })).toHaveAttribute(
      'aria-pressed',
      'true',
    );

    await switcher.getByRole('button', { name: 'Tiếng Việt' }).click();
    await expect(page.locator('html')).toHaveAttribute('lang', 'vi');
    await expect(page.getByRole('heading', { name: 'Đăng nhập', level: 1 })).toBeVisible();

    await page.getByRole('button', { name: 'English' }).click();
    await expect(page.locator('html')).toHaveAttribute('lang', 'en');
    await expect(page.getByRole('heading', { name: 'Sign in', level: 1 })).toBeVisible();

    const stored = await page.evaluate(() => ({
      local: window.localStorage.length,
      session: window.sessionStorage.length,
    }));
    expect(stored).toEqual({ local: 0, session: 0 });
  });
});
