/**
 * UAT round 10 (the owner's real-phone feedback of 2026-10-18): the shipment list's exact
 * "Solaris Shipment ID" filter becomes a keyword search (DEC-0156).
 *
 * The box is "Search shipments", its hint lists what it searches, its value travels as
 * `q`, and it is sent together with the status, route and date filters. Partial and
 * case-insensitive matching, and the ownership rule, are the server's:
 * `backend/tests/test_account_shipment_search.py`.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {
  clearBrowserStorage,
  listPageFixture,
  meFixture,
  renderAccount,
  requestedUrls,
  stubAccountFetch,
} from './accountUtils.jsx';

const ME = '/api/v1/account/me';
const LIST = '/api/v1/account/shipments';

beforeEach(clearBrowserStorage);
afterEach(() => {
  vi.unstubAllGlobals();
});

function listCalls(calls) {
  return requestedUrls(calls).filter((url) => url.includes('/shipments?'));
}

function lastListQuery(calls) {
  const urls = listCalls(calls);
  return new URL(urls[urls.length - 1], 'http://localhost').searchParams;
}

async function renderList(path = '/account/shipments', listRoute = { body: listPageFixture() }) {
  const stub = stubAccountFetch([{ path: ME, body: meFixture() }, { path: LIST, ...listRoute }]);
  renderAccount(path);
  await screen.findByRole('heading', { name: 'My shipments', level: 1 });
  return stub;
}

describe('UAT round 10: the shipment keyword search', () => {
  it('replaces the exact Solaris Shipment ID filter with "Search shipments"', async () => {
    await renderList();

    const box = screen.getByLabelText(/Search shipments/);
    expect(box).toHaveAttribute('type', 'search');
    expect(box).toHaveAttribute('name', 'q');
    expect(box).toHaveAttribute('maxlength', '64');
    expect(box).toHaveAttribute('enterkeyhint', 'search');
    // Round 11 added package IDs to what it searches (DEC-0161).
    expect(box).toHaveAccessibleDescription(
      /Solaris Shipment ID, a package ID, your booking reference, and the city it was sent from or to/,
    );
    expect(box).toHaveAccessibleDescription(/Part of a word is enough/);

    // The old box, and its "Part of an ID will not match", are gone.
    expect(screen.queryByLabelText(/^Solaris Shipment ID/)).not.toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(/Part of an ID will not match/);
  });

  it('sends a partial keyword as q, trimmed, and puts it in the URL', async () => {
    const user = userEvent.setup();
    const { calls } = await renderList();

    await user.type(screen.getByLabelText(/Search shipments/), '  ha noi  ');
    await user.click(screen.getByRole('button', { name: 'Apply filters' }));

    await waitFor(() => expect(new URLSearchParams(window.location.search).get('q')).toBe('ha noi'));
    expect(lastListQuery(calls).get('q')).toBe('ha noi');
    expect(lastListQuery(calls).has('reference')).toBe(false);
  });

  it('does not send a request per keystroke', async () => {
    const user = userEvent.setup();
    const { calls } = await renderList();
    const before = listCalls(calls).length;

    await user.type(screen.getByLabelText(/Search shipments/), 'toronto');
    expect(listCalls(calls).length).toBe(before);

    await user.keyboard('{Enter}');
    await waitFor(() => expect(listCalls(calls).length).toBe(before + 1));
    expect(lastListQuery(calls).get('q')).toBe('toronto');
  });

  it('keeps the dates, status and route when a keyword is added', async () => {
    const user = userEvent.setup();
    const { calls } = await renderList(
      '/account/shipments?status_group=delivered&route_group=CAV&booked_from=2026-09-01&booked_to=2026-09-30',
    );

    await user.type(screen.getByLabelText(/Search shipments/), 'SX-CAV');
    await user.click(screen.getByRole('button', { name: 'Apply filters' }));

    await waitFor(() => expect(lastListQuery(calls).get('q')).toBe('SX-CAV'));
    const sent = lastListQuery(calls);
    expect(sent.get('status_group')).toBe('delivered');
    expect(sent.get('route_group')).toBe('CAV');
    expect(sent.get('booked_from')).toBe('2026-09-01');
    expect(sent.get('booked_to')).toBe('2026-09-30');
    expect(screen.getByLabelText(/^Booked from/)).toHaveValue('2026-09-01');
  });

  it('opens a pre-round-10 ?reference= link as the keyword', async () => {
    const { calls } = await renderList('/account/shipments?reference=SX-VCA-CCCCCCCCCCCC');

    expect(screen.getByLabelText(/Search shipments/)).toHaveValue('SX-VCA-CCCCCCCCCCCC');
    const sent = lastListQuery(calls);
    expect(sent.get('q')).toBe('SX-VCA-CCCCCCCCCCCC');
    expect(sent.has('reference')).toBe(false);
  });

  it('clears the keyword with the other filters', async () => {
    const user = userEvent.setup();
    await renderList('/account/shipments?q=toronto&status_group=delivered');

    await user.click(screen.getAllByRole('button', { name: 'Clear filters' })[0]);
    await waitFor(() => expect(window.location.search).toBe(''));
    expect(screen.getByLabelText(/Search shipments/)).toHaveValue('');
  });

  it('shows the filtered empty state for a keyword that matches nothing', async () => {
    await renderList('/account/shipments?q=nowhere', { body: listPageFixture([]) });
    expect(await screen.findByText('No shipments match those filters')).toBeInTheDocument();
  });

  it("shows the server's refusal of an over-long keyword", async () => {
    await renderList('/account/shipments?q=x', {
      status: 422,
      body: { code: 'validation_error', message: 'Search for 64 characters or fewer.', field: 'q' },
    });
    expect(await screen.findByText('We could not use those filters.')).toBeInTheDocument();
    expect(screen.getByText('Search for 64 characters or fewer.')).toBeInTheDocument();
  });
});
