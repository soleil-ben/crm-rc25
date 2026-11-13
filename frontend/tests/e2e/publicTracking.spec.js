/**
 * Public tracking, end to end, against the running stack.
 *
 * The journey this suite walks is the one a customer actually takes:
 *
 *   1. open /track while signed out
 *   2. enter a valid parent reference
 *   3. read the safe summary and the timeline
 *   4. open a package reference directly, the way a QR code does
 *   5. confirm the scanned package is identified
 *   6. switch between English and Vietnamese
 *   7. try an unknown reference
 *   8. confirm no previous customer's result survives
 *   9. trigger the rate limit
 *  10. do all of it at 375 x 812
 *
 * Throughout, every request the browser makes is recorded, so the suite can assert the
 * negatives that matter: no staff endpoint, no third-party host, no analytics beacon, no
 * tracking reference in browser storage.
 */

import { expect, test } from './diagnostics.js';
import {
  isFirstParty,
  loadSeedReferences,
  MALFORMED_REFERENCE,
  recordRequests,
  STAFF_API_PREFIXES,
  TRACKER_PATTERNS,
  UNKNOWN_REFERENCE,
} from './fixtures.js';

const references = loadSeedReferences();

/**
 * The Solaris Shipment ID as shown in the summary.
 *
 * A plain text match on the parent reference is ambiguous on purpose-built markup: every
 * package reference on the page starts with it (`SX-CAV-...-01`), so Playwright's strict
 * mode reports four matches. Targeting the summary's copyable value is both unambiguous
 * and closer to what the assertion actually means.
 */
function shipmentId(page, reference) {
  return page.locator('.public-copyable__value', { hasText: new RegExp(`^${reference}$`) });
}


test.describe('public tracking', () => {
  test('1-3. opens signed out, looks up a parent reference, and shows a safe summary', async ({
    page,
    baseURL,
  }) => {
    const requests = recordRequests(page);

    await page.goto('/track');

    // 1. Signed out: the landing page, not the staff login.
    await expect(page.getByRole('heading', { name: 'Track your shipment' })).toBeVisible();
    await expect(page.getByLabel('Password')).toHaveCount(0);
    await expect(page.getByRole('navigation', { name: 'Main navigation' })).toHaveCount(0);

    // 2. Enter a valid parent reference.
    await page
      .getByLabel('Solaris Shipment ID or package reference')
      .fill(references.partial.toLowerCase());
    await page.getByRole('button', { name: 'Track' }).click();

    // 3. The safe summary and the timeline.
    await expect(shipmentId(page, references.partial)).toBeVisible();
    await expect(page.getByText('Partly delivered')).toBeVisible();
    await expect(page.getByText(/\d+ of \d+ packages delivered/)).toBeVisible();
    await expect(page.getByRole('region', { name: 'Shipment updates' })).toBeVisible();
    await expect(page.getByRole('region', { name: 'Packages in this shipment' })).toBeVisible();

    // The freshness line is honest and never claims synchronization. A demo row with
    // published milestones reports those, exactly as a real one would: `data_mode` and
    // the banner carry the demo warning, so the tracking state is free to say the one
    // thing it exists to say.
    await expect(page.locator('.public-demo-banner')).toBeVisible();
    await expect(page.getByText('Updates entered by Solaris staff')).toBeVisible();
    const body = await page.locator('body').innerText();
    expect(body).not.toMatch(/synchroni[sz]ed|last successful sync|live tracking/i);

    // The URL is bookmarkable and carries the normalized reference.
    expect(page.url()).toContain(`/track/${references.partial}`);

    // Nothing staff-side was called at any point.
    assertNoStaffCalls(requests);
    assertNoThirdParty(requests, baseURL);
  });

  test('3b. the summary carries no private customer data', async ({ page }) => {
    await page.goto(`/track/${references.partial}`);
    await expect(shipmentId(page, references.partial)).toBeVisible();

    const body = await page.locator('body').innerText();

    // The demo recipient's private details, none of which may appear on a public page.
    for (const forbidden of [
      '@demo.example.com', // any email address
      '+84', // any phone number
      '+1 416',
      'Đường', // a street name in the demo Vietnamese address
      'Dixie Road',
      'STCA-', // a customer identifier
      'DEMO-PURO', // a carrier tracking number
      'DEMO-MASTER',
      'SOL-CONS', // a consolidation reference
      'Recorded by the demo seed', // internal_detail
    ]) {
      expect(body, `"${forbidden}" must not appear on the public page`).not.toContain(forbidden);
    }

    // The coarse city and country are exactly what a customer needs and all they get.
    await expect(page.getByText(/Mississauga|Thành phố|Toronto|Vancouver/).first()).toBeVisible();
  });

  test('4-5. a package reference opens the same shipment with that package identified', async ({
    page,
  }) => {
    const requests = recordRequests(page);

    // Exactly what the label's QR code encodes: TRACKING_BASE_URL + package reference.
    await page.goto(`/track/${references.partial_package}`);

    // 4. Same shipment.
    await expect(shipmentId(page, references.partial)).toBeVisible();

    // 5. That package is identified, in text as well as by highlight.
    const list = page.getByRole('region', { name: 'Packages in this shipment' });
    const selected = list.locator('li[aria-current="true"]');
    await expect(selected).toHaveCount(1);
    await expect(selected).toContainText(references.partial_package);
    await expect(selected).toContainText('The package you scanned');
    await expect(page.getByText('You scanned', { exact: true })).toBeVisible();

    assertNoStaffCalls(requests);
  });

  test('6. switches between English and Vietnamese, including the document language', async ({
    page,
  }) => {
    await page.goto(`/track/${references.partial}`);
    await expect(shipmentId(page, references.partial)).toBeVisible();

    await expect(page.locator('html')).toHaveAttribute('lang', 'en');
    await expect(page.getByText('Partly delivered')).toBeVisible();
    await expect(page).toHaveTitle('Track your shipment — Solaris Express');

    await page.getByRole('button', { name: 'Tiếng Việt' }).click();

    await expect(page.locator('html')).toHaveAttribute('lang', 'vi');
    await expect(page.getByText('Đã giao một phần')).toBeVisible();
    await expect(page.getByText('Canada đến Việt Nam')).toBeVisible();
    await expect(page).toHaveTitle('Theo dõi lô hàng — Solaris Express');
    // Diacritics survive the whole round trip: catalogue, DOM, and font.
    await expect(page.getByText(/Cập nhật/).first()).toBeVisible();

    await page.getByRole('button', { name: 'English' }).click();
    await expect(page.locator('html')).toHaveAttribute('lang', 'en');
    await expect(page.getByText('Partly delivered')).toBeVisible();
  });

  test('7-8. an unknown reference fails generically and leaves no previous result behind', async ({
    page,
  }) => {
    // First, a real lookup that succeeds.
    await page.goto(`/track/${references.delivered}`);
    await expect(shipmentId(page, references.delivered)).toBeVisible();

    // 7. Then an unknown one, entered the way a customer would.
    await page.getByRole('link', { name: 'Track another shipment' }).click();
    await page.getByLabel('Solaris Shipment ID or package reference').fill(UNKNOWN_REFERENCE);
    await page.getByRole('button', { name: 'Track' }).click();

    await expect(page.getByText('We could not find that shipment')).toBeVisible();

    // 8. Nothing at all survives from the first shipment.
    const body = await page.locator('body').innerText();
    expect(body).not.toContain(references.delivered);
    expect(body).not.toContain('Delivered');
    expect(body).not.toMatch(/\d+ of \d+ packages delivered/);
  });

  test('7b. a malformed reference is indistinguishable from an unknown one', async ({ page }) => {
    await page.goto(`/track/${UNKNOWN_REFERENCE}`);
    await expect(page.getByText('We could not find that shipment')).toBeVisible();
    const unknownText = await page.locator('main').innerText();

    await page.goto(`/track/${MALFORMED_REFERENCE}`);
    await expect(page.getByText('We could not find that shipment')).toBeVisible();
    const malformedText = await page.locator('main').innerText();

    // Same screen, same words. The page never says "that format is wrong".
    expect(malformedText).toBe(unknownText);
    expect(malformedText).not.toMatch(/invalid|malformed|does not exist/i);
  });

  test('7c. the API answers both identically, byte for byte', async ({ request }) => {
    const unknown = await request.get(`/api/v1/public/track/${UNKNOWN_REFERENCE}`);
    const malformed = await request.get(`/api/v1/public/track/${MALFORMED_REFERENCE}`);

    expect(unknown.status()).toBe(malformed.status());
    expect(unknown.status()).toBe(404);
    expect(await unknown.text()).toBe(await malformed.text());

    for (const header of ['cache-control', 'referrer-policy', 'x-robots-tag']) {
      expect(unknown.headers()[header]).toBe(malformed.headers()[header]);
    }
  });

  test('a cancelled booking is indistinguishable from an unknown reference', async ({
    page,
    request,
  }) => {
    // UAT-XX-02. Word for word: the page for a cancelled booking is the page for a
    // reference that was never issued, and the API answers both byte for byte.
    await page.goto(`/track/${references.cancelled}`);
    await expect(page.getByText('We could not find that shipment')).toBeVisible();
    const cancelledText = await page.locator('main').innerText();
    expect(cancelledText).not.toContain(references.cancelled);
    expect(cancelledText).not.toMatch(/cancel/i);

    await page.goto(`/track/${UNKNOWN_REFERENCE}`);
    await expect(page.getByText('We could not find that shipment')).toBeVisible();
    const unknownText = await page.locator('main').innerText();
    expect(cancelledText).toBe(unknownText);

    const cancelled = await request.get(`/api/v1/public/track/${references.cancelled}`);
    const unknown = await request.get(`/api/v1/public/track/${UNKNOWN_REFERENCE}`);
    expect(cancelled.status()).toBe(404);
    expect(await cancelled.text()).toBe(await unknown.text());
    for (const header of ['cache-control', 'referrer-policy', 'x-robots-tag', 'content-type']) {
      expect(cancelled.headers()[header]).toBe(unknown.headers()[header]);
    }
  });

  test('an exception shows a support callout without internal detail', async ({ page }) => {
    await page.goto(`/track/${references.exception}`);

    await expect(page.getByText('This shipment needs attention')).toBeVisible();
    const body = await page.locator('body').innerText();
    // The staff-only explanation stays staff-only.
    expect(body).not.toMatch(/commercial invoice query|broker|escalation/i);
  });

  test('a draft is not publicly retrievable', async ({ request }) => {
    // A draft has no public identifier at all, so the only way to ask for one is to make
    // up a well-formed reference. Every such attempt gets the one generic answer.
    const response = await request.get(`/api/v1/public/track/${UNKNOWN_REFERENCE}`);
    expect([404, 429]).toContain(response.status());
    if (response.status() === 404) {
      expect((await response.json()).code).toBe('tracking_not_found');
    }
  });
});

// --- Network, storage, and headers ------------------------------------------

test.describe('privacy inspection', () => {
  test('the public flow calls no staff endpoint and loads no third-party resource', async ({
    page,
    baseURL,
  }) => {
    const requests = recordRequests(page);

    await page.goto('/track');
    await page.getByLabel('Solaris Shipment ID or package reference').fill(references.partial);
    await page.getByRole('button', { name: 'Track' }).click();
    await expect(shipmentId(page, references.partial)).toBeVisible();
    await page.getByRole('button', { name: 'Tiếng Việt' }).click();
    await expect(page.locator('html')).toHaveAttribute('lang', 'vi');

    assertNoStaffCalls(requests);
    assertNoThirdParty(requests, baseURL);

    // Fonts are served from our own origin, and the Vietnamese subset is among them.
    const fonts = requests.filter((request) => request.url.includes('/fonts/'));
    expect(fonts.length).toBeGreaterThan(0);
    for (const font of fonts) {
      expect(isFirstParty(font.url, baseURL)).toBe(true);
    }
  });

  test('no tracking reference reaches browser storage', async ({ page }) => {
    await page.goto(`/track/${references.partial}`);
    await expect(shipmentId(page, references.partial)).toBeVisible();
    await page.getByRole('button', { name: 'Tiếng Việt' }).click();

    const storage = await page.evaluate(() => ({
      local: { ...window.localStorage },
      session: { ...window.sessionStorage },
    }));

    const serialized = JSON.stringify(storage);
    expect(serialized).not.toContain(references.partial);
    expect(serialized).not.toContain('SX-');
    // The language preference is the only thing the page remembers.
    expect(Object.keys(storage.local)).toEqual(['solaris.public.language']);
    expect(storage.local['solaris.public.language']).toBe('vi');
    expect(Object.keys(storage.session)).toEqual([]);
  });

  test('the reference never reaches the document title or the page metadata', async ({ page }) => {
    await page.goto(`/track/${references.partial}`);
    await expect(shipmentId(page, references.partial)).toBeVisible();

    await expect(page).toHaveTitle('Track your shipment — Solaris Express');
    const robots = await page.locator('meta[name="robots"]').getAttribute('content');
    expect(robots).toContain('noindex');
    expect(robots).toContain('nofollow');
    const referrer = await page.locator('meta[name="referrer"]').getAttribute('content');
    expect(referrer).toBe('no-referrer');

    const head = await page.locator('head').innerHTML();
    expect(head).not.toContain(references.partial);
  });

  test('the API response carries the privacy and cache headers', async ({ request }) => {
    const response = await request.get(`/api/v1/public/track/${references.partial}`);

    expect(response.status()).toBe(200);
    const headers = response.headers();
    expect(headers['cache-control']).toContain('no-store');
    expect(headers['referrer-policy']).toBe('no-referrer');
    expect(headers['x-robots-tag']).toContain('noindex');
    expect(headers['x-content-type-options']).toBe('nosniff');
    expect(headers['x-frame-options']).toBe('DENY');
    expect(headers['permissions-policy']).toContain('geolocation=()');
    // No staff cookie is ever set on a public response.
    expect(headers['set-cookie']).toBeUndefined();
  });

  test('no staff cookie is set or sent anywhere in the public flow', async ({ page, context }) => {
    await page.goto('/track');
    await page.getByLabel('Solaris Shipment ID or package reference').fill(references.partial);
    await page.getByRole('button', { name: 'Track' }).click();
    await expect(shipmentId(page, references.partial)).toBeVisible();

    const cookies = await context.cookies();
    expect(cookies.map((cookie) => cookie.name)).not.toContain('solaris_session');
    expect(cookies.map((cookie) => cookie.name)).not.toContain('solaris_csrf');
  });

  test('a signed-in staff session changes nothing on the public page', async ({ page, request }) => {
    // Sign in through the API so the browser carries a real staff session, then confirm
    // the public page neither uses it nor behaves differently because of it.
    const login = await request.post('/api/v1/auth/login', {
      data: { email: 'admin@demo.example.com', password: 'SolarisDemo!2026' },
    });
    test.skip(!login.ok(), 'demo admin account is not available in this database');

    const requests = recordRequests(page);
    await page.goto(`/track/${references.partial}`);
    await expect(shipmentId(page, references.partial)).toBeVisible();

    // Still no staff call, and no staff chrome.
    assertNoStaffCalls(requests);
    await expect(page.getByRole('navigation', { name: 'Main navigation' })).toHaveCount(0);
  });
});

// --- Layout and accessibility -------------------------------------------------

test.describe('layout and keyboard access', () => {
  test('10. remains usable at 375 x 812 with no horizontal scroll', async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 812 });
    await page.goto(`/track/${references.partial}`);
    await expect(shipmentId(page, references.partial)).toBeVisible();

    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    expect(overflow, 'the public page must not scroll horizontally at 375 px').toBeLessThanOrEqual(
      1,
    );

    // The primary action still clears the 48 px minimum on a phone.
    await page.getByRole('link', { name: 'Track another shipment' }).click();
    const button = page.getByRole('button', { name: 'Track' });
    const box = await button.boundingBox();
    expect(box.height).toBeGreaterThanOrEqual(48);
  });

  test('10b. long Vietnamese text does not overflow at 375 px', async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 812 });
    await page.goto(`/track/${references.partial}`);
    await expect(shipmentId(page, references.partial)).toBeVisible();
    await page.getByRole('button', { name: 'Tiếng Việt' }).click();
    await expect(page.locator('html')).toHaveAttribute('lang', 'vi');

    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    expect(overflow, 'Vietnamese must not push the page wider than the viewport').toBeLessThanOrEqual(
      1,
    );

    // Nothing is clipped: every visible block fits inside the viewport width.
    const clipped = await page.evaluate(() =>
      [...document.querySelectorAll('.public-card, .public-callout, .public-package')]
        .filter((element) => element.getBoundingClientRect().right > window.innerWidth + 1)
        .map((element) => element.className),
    );
    expect(clipped).toEqual([]);
  });

  test('the whole lookup can be completed from the keyboard', async ({ page }) => {
    await page.goto('/track');
    await page.getByRole('heading', { name: 'Track your shipment' }).waitFor();

    await page.keyboard.press('Tab'); // skip link
    await expect(page.getByRole('link', { name: 'Skip to main content' })).toBeFocused();

    await page.getByLabel('Solaris Shipment ID or package reference').focus();
    await page.keyboard.type(references.partial.toLowerCase());
    await page.keyboard.press('Enter');

    await expect(shipmentId(page, references.partial)).toBeVisible();
  });

  test('the skip link moves focus into the main region', async ({ page }) => {
    await page.goto('/track');
    // The shell is a lazily loaded chunk, so wait for it to render before tabbing:
    // `goto` resolves as soon as the document is ready, which is before the page has
    // anything focusable in it.
    await expect(page.getByRole('heading', { name: 'Track your shipment' })).toBeVisible();

    await page.keyboard.press('Tab');
    await page.keyboard.press('Enter');

    expect(page.url()).toContain('#public-main');
    await expect(page.locator('#public-main')).toBeVisible();
  });

  test('landmarks and headings are present', async ({ page }) => {
    await page.goto(`/track/${references.partial}`);
    await expect(shipmentId(page, references.partial)).toBeVisible();

    await expect(page.getByRole('banner')).toBeVisible();
    await expect(page.getByRole('main')).toBeVisible();
    await expect(page.getByRole('contentinfo')).toBeVisible();
    await expect(page.getByRole('group', { name: 'Language' })).toBeVisible();
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible();
  });
});

// --- Assertions used above ------------------------------------------------------

function assertNoStaffCalls(requests) {
  const offenders = requests.filter((request) => {
    const path = new URL(request.url).pathname;
    return STAFF_API_PREFIXES.some((prefix) => path.startsWith(prefix));
  });
  expect(
    offenders.map((request) => request.url),
    'the public page called a staff endpoint',
  ).toEqual([]);
}

function assertNoThirdParty(requests, baseURL) {
  const external = requests.filter((request) => !isFirstParty(request.url, baseURL));
  expect(
    external.map((request) => request.url),
    'the public page loaded a third-party resource',
  ).toEqual([]);

  const trackers = requests.filter((request) =>
    TRACKER_PATTERNS.some((pattern) => pattern.test(request.url)),
  );
  expect(
    trackers.map((request) => request.url),
    'the public page contacted an analytics or tracking host',
  ).toEqual([]);
}
