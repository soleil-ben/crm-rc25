/**
 * RC-UAT-20 tester note: with a Master Tracking and a Last Mile Tracking link on a shipment,
 * both must render on the public tracking page and on the Customer Account shipment page.
 *
 * The payloads are the ones `backend/tests/test_rc20_carrier_links.py` proves the server
 * returns (UPS on the master leg, Canada Post on the last mile; DEC-0224).
 */

import { beforeEach, describe, expect, it } from 'vitest';
import { screen } from '@testing-library/react';
import { clearPublicStorage, renderPublic, stubPublicFetch } from './publicUtils.jsx';
import { trackingResultFixture } from './publicFixtures.js';
import {
  clearBrowserStorage,
  detailFixture,
  meFixture,
  renderAccount,
  stubAccountFetch,
} from './accountUtils.jsx';

const UPS = 'https://www.ups.com/track?tracknum=1Z999AA10123456784';
const CANADA_POST =
  'https://www.canadapost-postescanada.ca/track-reperage/en?pin=7023210039414604';
const MASTER = { carrier_name: 'Master Tracking', tracking_name_key: 'master_tracking', url: UPS };
const LAST_MILE = {
  carrier_name: 'Last Mile Tracking',
  tracking_name_key: 'last_mile_tracking',
  url: CANADA_POST,
};

const REFERENCE = trackingResultFixture.shipment_reference;
const TRACK_PATH = '/api/v1/public/track';
const ME = '/api/v1/account/me';
const DETAIL = '/api/v1/account/shipments/SX-CAV-7K9D2M4R8T6W';

function publicBody(links) {
  return {
    ...trackingResultFixture,
    timeline: [],
    tracking_state: 'external_link_only',
    last_public_update_at: null,
    carrier_link: links[0] ?? null,
    carrier_links: links,
  };
}

function follows(first, second) {
  return Boolean(first.compareDocumentPosition(second) & Node.DOCUMENT_POSITION_FOLLOWING);
}

describe('public tracking page', () => {
  beforeEach(() => {
    clearPublicStorage();
    document.documentElement.lang = 'en';
  });

  it('renders both the Master Tracking (UPS) and Last Mile Tracking (Canada Post) links', async () => {
    stubPublicFetch([{ path: TRACK_PATH, body: publicBody([MASTER, LAST_MILE]) }]);
    renderPublic(`/track/${REFERENCE}`);
    await screen.findByText(REFERENCE);

    const master = screen.getByRole('link', { name: 'Master Tracking: open the tracking page' });
    const lastMile = screen.getByRole('link', {
      name: 'Last Mile Tracking: open the tracking page',
    });
    expect(master).toHaveAttribute('href', UPS);
    expect(lastMile).toHaveAttribute('href', CANADA_POST);
    expect(follows(master, lastMile)).toBe(true);
    // The "Solaris does not read that page" note is said once, under the last link.
    expect(screen.getAllByText(/Solaris does not read that page/)).toHaveLength(1);
  });

  it('keeps the server order when the last-mile leg comes first', async () => {
    stubPublicFetch([{ path: TRACK_PATH, body: publicBody([LAST_MILE, MASTER]) }]);
    renderPublic(`/track/${REFERENCE}`);
    await screen.findByText(REFERENCE);

    const links = screen.getAllByRole('link', { name: /Tracking: open the tracking page$/ });
    expect(links.map((link) => link.getAttribute('href'))).toEqual([CANADA_POST, UPS]);
  });

  it('falls back to carrier_link alone when carrier_links is absent', async () => {
    const body = publicBody([MASTER]);
    delete body.carrier_links;
    stubPublicFetch([{ path: TRACK_PATH, body }]);
    renderPublic(`/track/${REFERENCE}`);
    await screen.findByText(REFERENCE);

    expect(screen.getAllByRole('link', { name: /Tracking: open the tracking page$/ })).toHaveLength(1);
  });
});

describe('Customer Account shipment page', () => {
  beforeEach(clearBrowserStorage);

  it('renders both the Master Tracking (UPS) and Last Mile Tracking (Canada Post) links', async () => {
    stubAccountFetch([
      { path: ME, body: meFixture() },
      {
        path: DETAIL,
        body: detailFixture({
          tracking_state: 'external_link_only',
          carrier_link: MASTER,
          carrier_links: [MASTER, LAST_MILE],
        }),
      },
    ]);
    renderAccount('/account/shipments/SX-CAV-7K9D2M4R8T6W');

    const master = await screen.findByRole('link', { name: /^Master Tracking: open/ });
    const lastMile = screen.getByRole('link', { name: /^Last Mile Tracking: open/ });
    expect(master).toHaveAttribute('href', UPS);
    expect(lastMile).toHaveAttribute('href', CANADA_POST);
    expect(follows(master, lastMile)).toBe(true);
    for (const link of [master, lastMile]) {
      expect(link).toHaveAttribute('target', '_blank');
      expect(link.getAttribute('rel')).toContain('noopener');
    }
    // Generic names only: the carriers are never named on the page.
    expect(document.body.textContent).not.toMatch(/\bUPS\b|Canada Post/);
  });

  it('keeps the server order when the last-mile leg comes first', async () => {
    stubAccountFetch([
      { path: ME, body: meFixture() },
      {
        path: DETAIL,
        body: detailFixture({ carrier_link: LAST_MILE, carrier_links: [LAST_MILE, MASTER] }),
      },
    ]);
    renderAccount('/account/shipments/SX-CAV-7K9D2M4R8T6W');

    const lastMile = await screen.findByRole('link', { name: /^Last Mile Tracking: open/ });
    const master = screen.getByRole('link', { name: /^Master Tracking: open/ });
    expect(follows(lastMile, master)).toBe(true);
  });
});
