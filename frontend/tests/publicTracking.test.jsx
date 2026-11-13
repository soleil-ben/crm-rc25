/**
 * The public tracking shell: routing, lookup, bilingual copy, privacy, accessibility.
 *
 * Every test here mounts the real `App`, so what is proved is proved about the shipped
 * routing rather than about a convenient harness.
 */

import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {
  clearPublicStorage,
  renderPublic,
  requestedUrls,
  stubPublicFetch,
} from './publicUtils.jsx';
import {
  demoFixture,
  exceptionFixture,
  externalLinkFixture,
  notFoundBody,
  otherShipmentFixture,
  packageScanFixture,
  trackingResultFixture,
  unavailableFixture,
} from './publicFixtures.js';

const REFERENCE = trackingResultFixture.shipment_reference;
const TRACK_PATH = '/api/v1/public/track';

beforeEach(() => {
  clearPublicStorage();
  document.documentElement.lang = 'en';
});

function trackRoute(body, { status = 200, headers } = {}) {
  return { path: TRACK_PATH, body, status, headers };
}

// --- Unauthenticated routing ----------------------------------------------

describe('unauthenticated routing', () => {
  it('renders the landing page without ever asking who is signed in', async () => {
    const { calls } = stubPublicFetch([]);

    renderPublic('/track');

    expect(await screen.findByRole('heading', { name: 'Track your shipment' })).toBeVisible();
    // The staff session query is what would render the login screen. It must never run.
    expect(requestedUrls(calls).some((url) => url.includes('/auth/me'))).toBe(false);
    expect(screen.queryByText('Sign in to the Solaris CRM')).not.toBeInTheDocument();
    expect(screen.queryByLabelText('Password')).not.toBeInTheDocument();
  });

  it('shows no staff navigation, search, or session chrome', async () => {
    stubPublicFetch([]);

    renderPublic('/track');
    await screen.findByRole('heading', { name: 'Track your shipment' });

    expect(screen.queryByRole('navigation', { name: 'Main navigation' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Account menu' })).not.toBeInTheDocument();
    for (const label of ['Dashboard', 'Customers', 'Segments', 'Follow-ups', 'Settings']) {
      expect(screen.queryByRole('link', { name: label })).not.toBeInTheDocument();
    }
  });

  it('opens a package reference directly, the way a label QR code does', async () => {
    const { calls } = stubPublicFetch([trackRoute(packageScanFixture)]);

    renderPublic(`/track/${packageScanFixture.selected_package_reference}`);

    await screen.findByText(REFERENCE);
    expect(requestedUrls(calls)).toEqual([
      `${TRACK_PATH}/${packageScanFixture.selected_package_reference}`,
    ]);
    expect(requestedUrls(calls).some((url) => url.includes('/auth/me'))).toBe(false);
  });

  it('calls no staff endpoint at any point in the flow', async () => {
    const { calls } = stubPublicFetch([trackRoute(trackingResultFixture)]);

    renderPublic(`/track/${REFERENCE}`);
    await screen.findByText(REFERENCE);

    const staffPrefixes = [
      '/api/v1/auth',
      '/api/v1/customers',
      '/api/v1/shipments',
      '/api/v1/segments',
      '/api/v1/tasks',
      '/api/v1/admin',
      '/api/v1/search',
    ];
    for (const url of requestedUrls(calls)) {
      for (const prefix of staffPrefixes) {
        expect(url.startsWith(prefix)).toBe(false);
      }
      expect(url.startsWith('/api/v1/public/')).toBe(true);
    }
  });

  it('makes no request to a third-party host', async () => {
    const { calls } = stubPublicFetch([trackRoute(trackingResultFixture)]);

    renderPublic(`/track/${REFERENCE}`);
    await screen.findByText(REFERENCE);

    for (const url of requestedUrls(calls)) {
      expect(url).not.toMatch(/^https?:\/\//);
      expect(url).not.toMatch(/google|gstatic|analytics|sentry|facebook|doubleclick|hotjar/i);
    }
  });

  it('sends no cookies with the public request', async () => {
    const { calls } = stubPublicFetch([trackRoute(trackingResultFixture)]);

    renderPublic(`/track/${REFERENCE}`);
    await screen.findByText(REFERENCE);

    expect(calls[0].init.credentials).toBe('omit');
  });
});

// --- Normalization and submission -----------------------------------------

describe('reference entry', () => {
  it('normalizes a pasted, lowercase, space-padded reference before looking it up', async () => {
    const user = userEvent.setup();
    const { calls } = stubPublicFetch([trackRoute(trackingResultFixture)]);
    renderPublic('/track');

    const field = await screen.findByLabelText('Solaris Shipment ID or package reference');
    await user.type(field, '  sx-cav-7k9d2m4r8t6w.  ');
    await user.click(screen.getByRole('button', { name: 'Track' }));

    await screen.findByText(REFERENCE);
    expect(requestedUrls(calls)).toEqual([`${TRACK_PATH}/${REFERENCE}`]);
    expect(window.location.pathname).toBe(`/track/${REFERENCE}`);
  });

  it('refuses an empty submission without contacting the server', async () => {
    const user = userEvent.setup();
    const { calls } = stubPublicFetch([]);
    renderPublic('/track');

    await user.click(await screen.findByRole('button', { name: 'Track' }));

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Enter a Solaris Shipment ID or package reference.',
    );
    expect(calls).toHaveLength(0);
  });

  it('does not tell the customer whether the format was valid', async () => {
    const user = userEvent.setup();
    stubPublicFetch([trackRoute(notFoundBody, { status: 404 })]);
    renderPublic('/track');

    const field = await screen.findByLabelText('Solaris Shipment ID or package reference');
    await user.type(field, 'not-a-reference-at-all');
    await user.click(screen.getByRole('button', { name: 'Track' }));

    // The server decides, and it gives one answer. The page must not add a client-side
    // "invalid format" message that the server works to avoid giving.
    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('We could not find that shipment');
    expect(alert.textContent).not.toMatch(/invalid|format/i);
  });
});

// --- The result -------------------------------------------------------------

describe('tracking result', () => {
  it('shows the summary, package progress, and timeline', async () => {
    stubPublicFetch([trackRoute(trackingResultFixture)]);

    renderPublic(`/track/${REFERENCE}`);

    expect(await screen.findByText(REFERENCE)).toBeVisible();
    expect(screen.getByText('Partly delivered')).toBeVisible();
    expect(screen.getByText('Canada to Vietnam')).toBeVisible();
    expect(screen.getByText('1 of 3 packages delivered')).toBeVisible();
    expect(screen.getByText('Mississauga, Canada')).toBeVisible();
    expect(screen.getByText('Thành phố Hồ Chí Minh, Vietnam')).toBeVisible();
    expect(screen.getByText('Your parcels have left Canada.')).toBeVisible();
    expect(screen.getByText('One of your three parcels has been delivered.')).toBeVisible();
  });

  it('highlights the package that was scanned, in text as well as colour', async () => {
    stubPublicFetch([trackRoute(packageScanFixture)]);

    renderPublic(`/track/${packageScanFixture.selected_package_reference}`);
    await screen.findByText(REFERENCE);

    // The scanned reference appears twice on purpose -- once in the summary, once in
    // the package list -- so the assertion is scoped to the list.
    const list = screen.getByRole('region', { name: 'Packages in this shipment' });
    const selected = within(list).getByText('SX-CAV-7K9D2M4R8T6W-02').closest('li');
    expect(selected).toHaveAttribute('aria-current', 'true');
    expect(within(selected).getByText('The package you scanned')).toBeVisible();

    const other = within(list).getByText('SX-CAV-7K9D2M4R8T6W-01').closest('li');
    expect(other).not.toHaveAttribute('aria-current');

    // And it is named in the summary too, so somebody who scanned a parcel sees which
    // one they scanned without hunting through the list.
    expect(screen.getByText('You scanned')).toBeVisible();
  });

  it('names the tracking state honestly and never claims synchronization', async () => {
    stubPublicFetch([trackRoute(trackingResultFixture)]);

    renderPublic(`/track/${REFERENCE}`);
    await screen.findByText(REFERENCE);

    expect(screen.getByText('Updates entered by Solaris staff')).toBeVisible();
    expect(document.body.textContent).not.toMatch(/synchroni[sz]ed|last sync|live tracking/i);
    expect(document.body.textContent).toMatch(/does not refresh by itself/i);
  });

  it('offers a carrier link with the caveat that Solaris does not read it', async () => {
    stubPublicFetch([trackRoute(externalLinkFixture)]);

    renderPublic(`/track/${REFERENCE}`);
    await screen.findByText(REFERENCE);

    // Named by the leg's generic name (owner, 2026-10-22), never the carrier's.
    const link = screen.getByRole('link', { name: 'Last Mile Tracking: open the tracking page' });
    expect(link).toHaveAttribute('href', externalLinkFixture.carrier_link.url);
    expect(link).toHaveAttribute('rel', expect.stringContaining('noopener'));
    expect(screen.getByText(/Solaris does not read that page/)).toBeVisible();
  });

  it('shows Master Tracking and Last Mile Tracking when both links exist (2026-10-22)', async () => {
    const master = {
      carrier_name: 'Master Tracking',
      tracking_name_key: 'master_tracking',
      url: 'https://www.dhl.com/ca-en/home/tracking.html?tracking-id=1',
    };
    stubPublicFetch([
      trackRoute({
        ...externalLinkFixture,
        carrier_link: master,
        carrier_links: [master, externalLinkFixture.carrier_link],
      }),
    ]);
    renderPublic(`/track/${REFERENCE}`);
    await screen.findByText(REFERENCE);
    expect(screen.getByRole('link', { name: 'Master Tracking: open the tracking page' })).toHaveAttribute(
      'href',
      master.url,
    );
    expect(
      screen.getByRole('link', { name: 'Last Mile Tracking: open the tracking page' }),
    ).toHaveAttribute('href', externalLinkFixture.carrier_link.url);
    expect(screen.getAllByText(/Solaris does not read that page/)).toHaveLength(1);
  });

  it('shows a support callout for an exception', async () => {
    stubPublicFetch([trackRoute(exceptionFixture)]);

    renderPublic(`/track/${exceptionFixture.shipment_reference}`);
    await screen.findByText(exceptionFixture.shipment_reference);

    expect(await screen.findByText('This shipment needs attention')).toBeVisible();
    expect(screen.getAllByRole('link', { name: 'Contact Solaris Express' }).length).toBeGreaterThan(
      0,
    );
  });

  it('shows a support callout when tracking is unavailable', async () => {
    stubPublicFetch([trackRoute(unavailableFixture)]);

    renderPublic(`/track/${unavailableFixture.shipment_reference}`);

    expect(
      await screen.findByText('We cannot show tracking for this shipment'),
    ).toBeVisible();
  });

  it('shows a persistent demo warning for a synthetic record', async () => {
    stubPublicFetch([trackRoute(demoFixture)]);

    renderPublic(`/track/${REFERENCE}`);
    await screen.findByText(REFERENCE);

    // "Demo data" appears twice on purpose: once as the persistent banner at the top of
    // the page and once as the tracking state in the freshness note. A synthetic record
    // should be hard to mistake for a real one.
    const banner = document.querySelector('.public-demo-banner');
    expect(banner).toHaveAttribute('role', 'status');
    expect(banner).toHaveTextContent('Demo data');
    expect(banner).toHaveTextContent(/not a real shipment/i);
    expect(screen.getAllByText('Demo data').length).toBeGreaterThanOrEqual(2);
  });

  it('omits estimated delivery entirely when none was supplied', async () => {
    stubPublicFetch([trackRoute(trackingResultFixture)]);

    renderPublic(`/track/${REFERENCE}`);
    await screen.findByText(REFERENCE);

    expect(screen.queryByText('Estimated delivery')).not.toBeInTheDocument();
    expect(screen.queryByText('Estimated')).not.toBeInTheDocument();
  });

  it('labels an estimate as an estimate when one exists', async () => {
    stubPublicFetch([
      trackRoute({ ...trackingResultFixture, estimated_delivery_at: '2026-09-20T00:00:00' }),
    ]);

    renderPublic(`/track/${REFERENCE}`);
    await screen.findByText(REFERENCE);

    expect(screen.getByText('Estimated delivery')).toBeVisible();
    expect(screen.getByText('Estimated')).toBeVisible();
    expect(screen.getByText(/not a guarantee/i)).toBeVisible();
  });

  it('says so plainly when nothing has been published yet', async () => {
    stubPublicFetch([
      trackRoute({
        ...trackingResultFixture,
        timeline: [],
        tracking_state: 'no_public_milestones',
        last_public_update_at: null,
      }),
    ]);

    renderPublic(`/track/${REFERENCE}`);
    await screen.findByText(REFERENCE);

    expect(screen.getByText('No updates have been published for this shipment yet.')).toBeVisible();
    // No invented milestone fills the gap.
    expect(screen.queryByText(/customs/i)).not.toBeInTheDocument();
  });
});

// --- Failure states ---------------------------------------------------------

describe('failure states', () => {
  it('shows one generic message for an unknown reference', async () => {
    stubPublicFetch([trackRoute(notFoundBody, { status: 404 })]);

    renderPublic('/track/SX-CAV-ABCDEFGHJKLM');

    expect(await screen.findByText('We could not find that shipment')).toBeVisible();
    expect(document.body.textContent).not.toMatch(/does not exist|no such shipment/i);
  });

  it('explains a rate limit with the wait the server asked for', async () => {
    stubPublicFetch([
      trackRoute(
        { code: 'rate_limited', message: 'Too many tracking lookups.' },
        { status: 429, headers: { 'Retry-After': '42' } },
      ),
    ]);

    renderPublic(`/track/${REFERENCE}`);

    expect(await screen.findByText('Too many lookups')).toBeVisible();
    expect(screen.getByText(/wait about 42 seconds/i)).toBeVisible();
  });

  it('falls back to a generic wait when the server sent no Retry-After', async () => {
    stubPublicFetch([
      trackRoute({ code: 'rate_limited', message: 'Too many.' }, { status: 429 }),
    ]);

    renderPublic(`/track/${REFERENCE}`);

    expect(await screen.findByText('Too many lookups')).toBeVisible();
    expect(screen.getByText(/wait a moment/i)).toBeVisible();
  });

  it('leaves no trace of a previous result after a second lookup fails', async () => {
    const user = userEvent.setup();
    // First lookup succeeds, every later one fails. Two people sharing a phone, or one
    // person checking two parcels, must never see the first result under the second
    // reference.
    let call = 0;
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => {
        call += 1;
        const found = call === 1;
        return {
          ok: found,
          status: found ? 200 : 404,
          headers: new Headers(),
          json: async () => (found ? otherShipmentFixture : notFoundBody),
          text: async () => '',
        };
      }),
    );

    renderPublic(`/track/${otherShipmentFixture.shipment_reference}`);
    await screen.findByText(otherShipmentFixture.shipment_reference);
    expect(screen.getByText('Delivered to the recipient in Toronto.')).toBeVisible();

    await user.click(screen.getByRole('link', { name: 'Track another shipment' }));
    const field = await screen.findByLabelText('Solaris Shipment ID or package reference');
    await user.type(field, 'SX-CAV-ABCDEFGHJKLM');
    await user.click(screen.getByRole('button', { name: 'Track' }));

    await screen.findByText('We could not find that shipment');
    // Nothing at all survives from the first customer's shipment.
    expect(screen.queryByText(otherShipmentFixture.shipment_reference)).not.toBeInTheDocument();
    expect(screen.queryByText('Delivered to the recipient in Toronto.')).not.toBeInTheDocument();
    expect(screen.queryByText('Delivered')).not.toBeInTheDocument();
    expect(screen.queryByText('Vietnam to Canada')).not.toBeInTheDocument();
  });
});

// --- Privacy ----------------------------------------------------------------

describe('browser privacy', () => {
  it('stores no tracking reference or result in localStorage', async () => {
    stubPublicFetch([trackRoute(trackingResultFixture)]);

    renderPublic(`/track/${REFERENCE}`);
    await screen.findByText(REFERENCE);

    const stored = Object.entries({ ...window.localStorage });
    const serialized = JSON.stringify(stored);
    expect(serialized).not.toContain(REFERENCE);
    expect(serialized).not.toContain('SX-');
    expect(serialized).not.toContain('Thành phố');
    // The only key the page writes is the language preference.
    const keys = Object.keys({ ...window.localStorage });
    expect(keys.every((key) => key === 'solaris.public.language')).toBe(true);
  });

  it('stores nothing in sessionStorage either', async () => {
    stubPublicFetch([trackRoute(trackingResultFixture)]);

    renderPublic(`/track/${REFERENCE}`);
    await screen.findByText(REFERENCE);

    expect(Object.keys({ ...window.sessionStorage })).toEqual([]);
  });

  it('keeps the tracking reference out of the document title', async () => {
    stubPublicFetch([trackRoute(trackingResultFixture)]);

    renderPublic(`/track/${REFERENCE}`);
    await screen.findByText(REFERENCE);

    expect(document.title).toBe('Track your shipment — Solaris Express');
    expect(document.title).not.toContain(REFERENCE);
    expect(document.title).not.toContain('SX-');
  });

  it('keeps the page out of search indexes', () => {
    // Asserted against the shipped HTML rather than the rendered DOM, because the meta
    // tag lives in index.html and jsdom does not evaluate it here.
    const html = readIndexHtml();
    expect(html).toMatch(/<meta name="robots" content="noindex, nofollow, noarchive"/);
    expect(html).toMatch(/<meta name="referrer" content="no-referrer"/);
  });

  it('loads no third-party font, script, or stylesheet', () => {
    const html = readIndexHtml();
    expect(html).not.toContain('fonts.googleapis.com');
    expect(html).not.toContain('fonts.gstatic.com');
    // Nothing external at all: no preconnect, no CDN, no analytics.
    expect(html).not.toMatch(/(?:href|src)="https?:\/\//);
  });

  it('has a generic document title in the shipped HTML too', () => {
    expect(readIndexHtml()).toMatch(/<title>Solaris Express<\/title>/);
  });
});

function readIndexHtml() {
  return readFileSync(join(process.cwd(), 'index.html'), 'utf8');
}

// --- Localization ------------------------------------------------------------

describe('English and Vietnamese', () => {
  it('switches the whole page and the document language', async () => {
    const user = userEvent.setup();
    stubPublicFetch([trackRoute(trackingResultFixture)]);

    renderPublic(`/track/${REFERENCE}`);
    await screen.findByText(REFERENCE);
    expect(document.documentElement.lang).toBe('en');
    expect(screen.getByText('Partly delivered')).toBeVisible();

    await user.click(screen.getByRole('button', { name: 'Tiếng Việt' }));

    await waitFor(() => expect(document.documentElement.lang).toBe('vi'));
    expect(screen.getByText('Đã giao một phần')).toBeVisible();
    expect(screen.getByText('Canada đến Việt Nam')).toBeVisible();
    expect(screen.getByText('Đã giao 1 trên 3 kiện')).toBeVisible();
    expect(document.title).toBe('Theo dõi lô hàng — Solaris Express');
  });

  it('translates the landing page and preserves diacritics', async () => {
    const user = userEvent.setup();
    stubPublicFetch([]);

    renderPublic('/track');
    await user.click(await screen.findByRole('button', { name: 'Tiếng Việt' }));

    expect(await screen.findByRole('heading', { name: 'Theo dõi lô hàng của bạn' })).toBeVisible();
    expect(screen.getByRole('button', { name: 'Theo dõi' })).toBeVisible();
    // Diacritics survive the round trip through the catalogue and the DOM.
    expect(screen.getByText(/Nhập mã lô hàng Solaris/)).toBeVisible();
  });

  it('translates the failure state', async () => {
    const user = userEvent.setup();
    stubPublicFetch([trackRoute(notFoundBody, { status: 404 })]);

    renderPublic('/track/SX-CAV-ABCDEFGHJKLM');
    await screen.findByText('We could not find that shipment');
    await user.click(screen.getByRole('button', { name: 'Tiếng Việt' }));

    expect(await screen.findByText('Không tìm thấy lô hàng')).toBeVisible();
  });

  it('remembers the language but never the reference', async () => {
    const user = userEvent.setup();
    stubPublicFetch([trackRoute(trackingResultFixture)]);

    renderPublic(`/track/${REFERENCE}`);
    await screen.findByText(REFERENCE);
    await user.click(screen.getByRole('button', { name: 'Tiếng Việt' }));

    await waitFor(() =>
      expect(window.localStorage.getItem('solaris.public.language')).toBe('vi'),
    );
    expect(JSON.stringify({ ...window.localStorage })).not.toContain('SX-');
  });

  it('keeps the language switch visible on every screen', async () => {
    stubPublicFetch([trackRoute(notFoundBody, { status: 404 })]);

    renderPublic('/track/SX-CAV-ABCDEFGHJKLM');
    await screen.findByText('We could not find that shipment');

    expect(screen.getByRole('group', { name: 'Language' })).toBeVisible();
    expect(screen.getByRole('button', { name: 'English' })).toBeVisible();
    expect(screen.getByRole('button', { name: 'Tiếng Việt' })).toBeVisible();
  });
});

// --- Accessibility ------------------------------------------------------------

describe('accessibility', () => {
  it('provides a skip link and semantic landmarks', async () => {
    stubPublicFetch([]);

    renderPublic('/track');
    await screen.findByRole('heading', { name: 'Track your shipment' });

    expect(screen.getByRole('link', { name: 'Skip to main content' })).toHaveAttribute(
      'href',
      '#public-main',
    );
    expect(screen.getByRole('main')).toBeInTheDocument();
    expect(screen.getByRole('banner')).toBeInTheDocument();
    expect(screen.getByRole('contentinfo')).toBeInTheDocument();
  });

  it('can be driven from the keyboard alone', async () => {
    const user = userEvent.setup();
    const { calls } = stubPublicFetch([trackRoute(trackingResultFixture)]);
    renderPublic('/track');
    await screen.findByRole('heading', { name: 'Track your shipment' });

    const field = screen.getByLabelText('Solaris Shipment ID or package reference');
    field.focus();
    await user.keyboard(REFERENCE.toLowerCase());
    await user.keyboard('{Enter}');

    await screen.findByText(REFERENCE);
    expect(requestedUrls(calls)).toEqual([`${TRACK_PATH}/${REFERENCE}`]);
  });

  it('reaches the language switch and the Track button by tabbing', async () => {
    const user = userEvent.setup();
    stubPublicFetch([]);
    renderPublic('/track');
    await screen.findByRole('heading', { name: 'Track your shipment' });

    const reachable = [];
    for (let step = 0; step < 10; step += 1) {
      await user.tab();
      if (document.activeElement) reachable.push(document.activeElement);
    }

    expect(reachable).toContain(screen.getByRole('button', { name: 'Tiếng Việt' }));
    expect(reachable).toContain(screen.getByLabelText('Solaris Shipment ID or package reference'));
    expect(reachable).toContain(screen.getByRole('button', { name: 'Track' }));
  });

  it('labels the field, describes it, and marks it invalid on error', async () => {
    const user = userEvent.setup();
    stubPublicFetch([]);
    renderPublic('/track');

    const field = await screen.findByLabelText('Solaris Shipment ID or package reference');
    expect(field).toHaveAccessibleDescription(/SX-CAV-7K9D2M4R8T6W/);

    await user.click(screen.getByRole('button', { name: 'Track' }));

    expect(field).toHaveAttribute('aria-invalid', 'true');
    expect(await screen.findByRole('alert')).toBeVisible();
  });

  it('announces a failed lookup rather than silently swapping the screen', async () => {
    stubPublicFetch([trackRoute(notFoundBody, { status: 404 })]);

    renderPublic('/track/SX-CAV-ABCDEFGHJKLM');

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('We could not find that shipment');
  });

  it('names the timeline and package regions', async () => {
    stubPublicFetch([trackRoute(trackingResultFixture)]);

    renderPublic(`/track/${REFERENCE}`);
    await screen.findByText(REFERENCE);

    expect(screen.getByRole('region', { name: 'Shipment updates' })).toBeInTheDocument();
    expect(screen.getByRole('region', { name: 'Packages in this shipment' })).toBeInTheDocument();
    expect(screen.getByRole('region', { name: 'Tracking result' })).toBeInTheDocument();
  });

  it('gives every status a text label, not only a colour', async () => {
    stubPublicFetch([trackRoute(trackingResultFixture)]);

    renderPublic(`/track/${REFERENCE}`);
    await screen.findByText(REFERENCE);

    for (const badge of document.querySelectorAll('.public-badge')) {
      expect(badge.textContent.trim().length).toBeGreaterThan(0);
    }
  });
});
