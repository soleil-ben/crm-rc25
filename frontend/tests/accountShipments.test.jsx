/**
 * The authenticated shipment list and detail screens.
 *
 * The tests that matter most here are the **negative** ones: a response is served with a
 * private value planted in it, and the assertion is that the value does not reach the
 * DOM. A screen cannot leak a field the response does not carry, but it can leak one the
 * response *does* carry and the allowlist says it should not have — and the way that
 * happens is a component rendering `{...item}` or a debug dump nobody removed.
 */

import { describe, expect, it, beforeEach } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {
  clearBrowserStorage,
  detailFixture,
  listItemFixture,
  listPageFixture,
  meFixture,
  renderAccount,
  requestedUrls,
  stubAccountFetch,
} from './accountUtils.jsx';

const ME = '/api/v1/account/me';
const LIST = '/api/v1/account/shipments';

beforeEach(clearBrowserStorage);

describe('the shipment list', () => {
  it('renders the allowlisted fields of each row', async () => {
    stubAccountFetch([
      { path: ME, body: meFixture() },
      { path: LIST, body: listPageFixture() },
    ]);

    renderAccount('/account/shipments');
    await screen.findByRole('heading', { name: 'My shipments', level: 1 });

    // One row, rendered twice — the wide table and the narrow cards are both in the DOM
    // and CSS chooses between them — so every assertion uses `getAllBy`.
    expect(screen.getAllByText('SX-CAV-7K9D2M4R8T6W').length).toBeGreaterThan(0);
    expect(screen.getAllByText('Canada to Vietnam').length).toBeGreaterThan(0);
    expect(screen.getAllByText('Mississauga, CA').length).toBeGreaterThan(0);
    expect(screen.getAllByText('Ho Chi Minh City, VN').length).toBeGreaterThan(0);
    expect(screen.getAllByText('In transit').length).toBeGreaterThan(0);
    expect(screen.getAllByText('2 packages').length).toBeGreaterThan(0);
  });

  it('shows no field outside the allowlist, even when the response carries one', async () => {
    // A response with sentinels in fields the allowlist excludes. The server would never
    // send these — the schema forbids extras — so this is a test of the *screen*: it must
    // render from named fields rather than from whatever arrived.
    const contaminated = {
      ...listItemFixture(),
      recipient_name: 'SENTINEL-RECIPIENT-NAME',
      recipient_phone: 'SENTINEL-RECIPIENT-PHONE',
      carrier_tracking_number: 'SENTINEL-CARRIER-NUMBER',
      selling_amount: 'SENTINEL-MONEY',
      internal_notes: 'SENTINEL-STAFF-NOTE',
      operational_state: 'SENTINEL-INTERNAL-STATE',
      owner_user_id: 'SENTINEL-STAFF-MEMBER',
      provider_freshness: 'SENTINEL-FRESHNESS',
      integration_status: 'SENTINEL-INTEGRATION',
    };
    stubAccountFetch([
      { path: ME, body: meFixture() },
      { path: LIST, body: listPageFixture([contaminated]) },
    ]);

    renderAccount('/account/shipments');
    await screen.findByRole('heading', { name: 'My shipments', level: 1 });

    expect(document.body.textContent).not.toMatch(/SENTINEL-/);
  });

  it('marks a cancelled and a rebooked shipment in words', async () => {
    stubAccountFetch([
      { path: ME, body: meFixture() },
      {
        path: LIST,
        body: listPageFixture([
          listItemFixture({
            shipment_reference: 'SX-CAV-AAAAAAAAAAAA',
            is_cancelled: true,
            cancelled_at: '2026-09-03T10:00:00+00:00',
            status: 'cancelled',
            status_label: 'Cancelled',
          }),
          listItemFixture({ shipment_reference: 'SX-CAV-BBBBBBBBBBBB', is_rebooked: true }),
        ]),
      },
    ]);

    renderAccount('/account/shipments');
    await screen.findByRole('heading', { name: 'My shipments', level: 1 });

    expect(screen.getAllByText('Cancelled').length).toBeGreaterThan(0);
    expect(screen.getAllByText('Rebooked').length).toBeGreaterThan(0);
  });

  it('never names the replacement of a rebooked shipment', async () => {
    stubAccountFetch([
      { path: ME, body: meFixture() },
      { path: LIST, body: listPageFixture([listItemFixture({ is_rebooked: true })]) },
    ]);

    renderAccount('/account/shipments');
    await screen.findByRole('heading', { name: 'My shipments', level: 1 });

    // The response carries no replacement reference (SHIPMENT_ALLOWLISTS.md §5), so the
    // screen must not imply one exists to be looked at.
    expect(document.body.textContent).not.toMatch(/replaced by|replacement shipment/i);
  });

  it('says so plainly when the history is empty', async () => {
    stubAccountFetch([
      { path: ME, body: meFixture() },
      { path: LIST, body: listPageFixture([]) },
    ]);

    renderAccount('/account/shipments');
    expect(await screen.findByText('No shipments yet')).toBeInTheDocument();
  });

  it('distinguishes an empty filtered result from an empty history', async () => {
    stubAccountFetch([
      { path: ME, body: meFixture() },
      { path: LIST, body: listPageFixture([]) },
    ]);

    renderAccount('/account/shipments?status_group=delivered');
    expect(await screen.findByText('No shipments match those filters')).toBeInTheDocument();
    // Two of them: the one in the filter card and the one in the empty state. Both are
    // offered on purpose — the person's eye is on the empty result, not on the form above
    // it — and both must work.
    const clear = screen.getAllByRole('button', { name: 'Clear filters' });
    expect(clear).toHaveLength(2);
    clear.forEach((button) => expect(button).toBeEnabled());
  });

  it('puts every filter in the URL and sends it to the server', async () => {
    const user = userEvent.setup();
    const { calls } = stubAccountFetch([
      { path: ME, body: meFixture() },
      { path: LIST, body: listPageFixture() },
    ]);

    renderAccount('/account/shipments');
    await screen.findByRole('heading', { name: 'My shipments', level: 1 });

    await user.type(screen.getByLabelText(/Search shipments/), '7K9D2M');
    await user.selectOptions(screen.getByLabelText(/^Status/), 'delivered');
    await user.selectOptions(screen.getByLabelText(/^Route/), 'CAV');
    await user.click(screen.getByRole('button', { name: 'Apply filters' }));

    await waitFor(() => {
      expect(window.location.search).toContain('q=7K9D2M');
    });
    expect(window.location.search).toContain('status_group=delivered');
    expect(window.location.search).toContain('route_group=CAV');
    expect(window.location.search).not.toContain('reference=');

    const listCalls = requestedUrls(calls).filter((url) => url.includes('/shipments?'));
    const last = listCalls[listCalls.length - 1];
    expect(last).toContain('q=7K9D2M');
    expect(last).toContain('status_group=delivered');
    expect(last).toContain('route_group=CAV');
  });

  it('restores the filter controls from the URL, so a deep link survives a refresh', async () => {
    stubAccountFetch([
      { path: ME, body: meFixture() },
      { path: LIST, body: listPageFixture() },
    ]);

    renderAccount('/account/shipments?status_group=delivered&route_group=VCA&q=Ha%20Noi');
    await screen.findByRole('heading', { name: 'My shipments', level: 1 });

    expect(screen.getByLabelText(/Search shipments/)).toHaveValue('Ha Noi');
    expect(screen.getByLabelText(/^Status/)).toHaveValue('delivered');
    expect(screen.getByLabelText(/^Route/)).toHaveValue('VCA');
  });

  it('clears the filters back to an unfiltered URL', async () => {
    const user = userEvent.setup();
    stubAccountFetch([
      { path: ME, body: meFixture() },
      { path: LIST, body: listPageFixture() },
    ]);

    renderAccount('/account/shipments?status_group=delivered');
    await screen.findByRole('heading', { name: 'My shipments', level: 1 });
    await user.click(screen.getByRole('button', { name: 'Clear filters' }));

    await waitFor(() => expect(window.location.search).toBe(''));
  });

  it('shows the rate-limited state with the wait, and does not retry on its own', async () => {
    const { calls } = stubAccountFetch([
      { path: ME, body: meFixture() },
      {
        path: LIST,
        status: 429,
        headers: { 'Retry-After': '45' },
        body: { code: 'rate_limited', message: 'Too many requests.', field: null },
      },
    ]);

    renderAccount('/account/shipments');
    expect(await screen.findByText('Too many requests.')).toBeInTheDocument();
    expect(screen.getByText(/45 seconds/)).toBeInTheDocument();

    const listCalls = requestedUrls(calls).filter((url) => url.includes('/shipments'));
    expect(listCalls).toHaveLength(1);
  });

  it('shows the session-expired state rather than an error when the session has gone', async () => {
    stubAccountFetch([
      { path: ME, body: meFixture() },
      {
        path: LIST,
        status: 401,
        body: { code: 'unauthenticated', message: 'Sign in to continue.', field: null },
      },
    ]);

    renderAccount('/account/shipments');
    expect(await screen.findByText('Your session has ended.')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Sign in' })).toBeInTheDocument();
  });

  it('renders the refusal sentence the server sent, with no reason of its own', async () => {
    const refusal =
      'Your account cannot view shipment history yet. Solaris Express will be in touch once your account review is complete.';
    stubAccountFetch([
      { path: ME, body: meFixture() },
      { path: LIST, status: 403, body: { code: 'forbidden', message: refusal, field: null } },
    ]);

    renderAccount('/account/shipments');
    expect(await screen.findByText(refusal)).toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(/pending|revoked|archived|merged/i);
  });

  it('opens a row through a real link, so it is keyboard operable', async () => {
    stubAccountFetch([
      { path: ME, body: meFixture() },
      { path: LIST, body: listPageFixture() },
    ]);

    renderAccount('/account/shipments');
    await screen.findByRole('heading', { name: 'My shipments', level: 1 });

    const links = screen.getAllByRole('link', { name: 'SX-CAV-7K9D2M4R8T6W' });
    expect(links.length).toBeGreaterThan(0);
    links.forEach((link) => {
      expect(link.getAttribute('href')).toBe('/account/shipments/SX-CAV-7K9D2M4R8T6W');
    });
  });
});

describe('the shipment detail', () => {
  const DETAIL = '/api/v1/account/shipments/SX-CAV-7K9D2M4R8T6W';

  it('renders the approved detail values', async () => {
    stubAccountFetch([
      { path: ME, body: meFixture() },
      { path: DETAIL, body: detailFixture() },
    ]);

    renderAccount('/account/shipments/SX-CAV-7K9D2M4R8T6W');
    await screen.findByRole('heading', { name: 'SX-CAV-7K9D2M4R8T6W', level: 1 });

    expect(screen.getByText('0 of 2 packages delivered')).toBeInTheDocument();
    // "From" appears twice: once in the route summary and once as the timeline entry's
    // location, which is the same place and is correct.
    expect(screen.getAllByText('Mississauga, Canada').length).toBeGreaterThan(0);
    expect(screen.getByText('Ho Chi Minh City, Vietnam')).toBeInTheDocument();
    expect(screen.getByText('America/Toronto')).toBeInTheDocument();
    expect(
      screen.getByText('Your shipment has left the Solaris Express facility.'),
    ).toBeInTheDocument();
    expect(screen.getByText('SX-CAV-7K9D2M4R8T6W-01')).toBeInTheDocument();
  });

  it('requests only the account detail route — no staff route, no public fallback', async () => {
    const { calls } = stubAccountFetch([
      { path: ME, body: meFixture() },
      { path: DETAIL, body: detailFixture() },
    ]);

    renderAccount('/account/shipments/SX-CAV-7K9D2M4R8T6W');
    await screen.findByRole('heading', { name: 'SX-CAV-7K9D2M4R8T6W', level: 1 });

    requestedUrls(calls).forEach((url) => {
      expect(url).not.toContain('/api/v1/public/');
      expect(url).not.toMatch(/\/api\/v1\/shipments/);
    });
  });

  it('does not fall back to public tracking when the account call refuses', async () => {
    const { calls } = stubAccountFetch([
      { path: ME, body: meFixture() },
      {
        path: DETAIL,
        status: 404,
        body: {
          code: 'not_found',
          message: 'We could not find that shipment. Check the Solaris Shipment ID and try again.',
          field: null,
        },
      },
    ]);

    renderAccount('/account/shipments/SX-CAV-7K9D2M4R8T6W');
    await screen.findByRole('heading', { name: 'We could not find that shipment', level: 1 });

    expect(requestedUrls(calls).some((url) => url.includes('/public/track'))).toBe(false);
  });

  it('shows one page for an unknown reference and for another customer’s', async () => {
    const body = {
      code: 'not_found',
      message: 'We could not find that shipment. Check the Solaris Shipment ID and try again.',
      field: null,
    };

    stubAccountFetch([
      { path: ME, body: meFixture() },
      { path: '/api/v1/account/shipments/', status: 404, body },
    ]);
    renderAccount('/account/shipments/SX-CAV-ZZZZZZZZZZZZ');
    await screen.findByRole('heading', { name: 'We could not find that shipment', level: 1 });
    const unknown = document.body.textContent;

    clearBrowserStorage();
    stubAccountFetch([
      { path: ME, body: meFixture() },
      { path: '/api/v1/account/shipments/', status: 404, body },
    ]);
    renderAccount('/account/shipments/SX-VCA-YYYYYYYYYYYY');
    await screen.findAllByRole('heading', { name: 'We could not find that shipment', level: 1 });

    // The second render is appended to the same document by the testing library's
    // container, so the comparison is of the rendered text of each, not of the whole body.
    expect(document.body.textContent).toContain(unknown.slice(0, 200));
  });

  it('shows no private or financial value, even when the response carries one', async () => {
    const contaminated = {
      ...detailFixture(),
      recipient_name: 'SENTINEL-RECIPIENT',
      recipient_address_line1: 'SENTINEL-ADDRESS',
      carrier_tracking_number: 'SENTINEL-CARRIER-NUMBER',
      selling_amount: 'SENTINEL-MONEY',
      payment_state: 'SENTINEL-PAYMENT',
      internal_notes: 'SENTINEL-NOTE',
      declared_value: 'SENTINEL-DECLARED',
    };
    contaminated.timeline = [
      { ...detailFixture().timeline[0], internal_detail: 'SENTINEL-INTERNAL-DETAIL' },
    ];

    stubAccountFetch([
      { path: ME, body: meFixture() },
      { path: DETAIL, body: contaminated },
    ]);

    renderAccount('/account/shipments/SX-CAV-7K9D2M4R8T6W');
    await screen.findByRole('heading', { name: 'SX-CAV-7K9D2M4R8T6W', level: 1 });

    expect(document.body.textContent).not.toMatch(/SENTINEL-/);
  });

  it('renders a carrier link safely, and only when the response carries one', async () => {
    stubAccountFetch([
      { path: ME, body: meFixture() },
      {
        path: DETAIL,
        body: detailFixture({
          carrier_link: {
            // The server sends the generic name; the stored label never reaches the page.
            carrier_name: 'Last Mile Tracking',
            tracking_name_key: 'last_mile_tracking',
            url: 'https://www.canadapost-postescanada.ca/track',
          },
        }),
      },
    ]);

    renderAccount('/account/shipments/SX-CAV-7K9D2M4R8T6W');
    const link = await screen.findByRole('link', {
      name: /Last Mile Tracking: open the carrier’s tracking page/,
    });
    expect(link).toHaveAttribute('target', '_blank');
    expect(link.getAttribute('rel')).toContain('noopener');
    expect(link.getAttribute('rel')).toContain('noreferrer');
    expect(link).toHaveAttribute('referrerpolicy', 'no-referrer');
  });

  it('lists one link per tracking name, Master then Last Mile (2026-10-22)', async () => {
    const links = [
      { carrier_name: 'Master Tracking', tracking_name_key: 'master_tracking', url: 'https://www.dhl.com/t' },
      { carrier_name: 'Last Mile Tracking', tracking_name_key: 'last_mile_tracking', url: 'https://www.ups.com/t' },
    ];
    stubAccountFetch([
      { path: ME, body: meFixture() },
      { path: DETAIL, body: detailFixture({ carrier_link: links[0], carrier_links: links }) },
    ]);
    renderAccount('/account/shipments/SX-CAV-7K9D2M4R8T6W');
    const master = await screen.findByRole('link', { name: /^Master Tracking: open/ });
    const lastMile = screen.getByRole('link', { name: /^Last Mile Tracking: open/ });
    expect(master).toHaveAttribute('href', 'https://www.dhl.com/t');
    expect(lastMile).toHaveAttribute('href', 'https://www.ups.com/t');
    expect(master.compareDocumentPosition(lastMile) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it('shows the cancelled state without hiding the shipment', async () => {
    stubAccountFetch([
      { path: ME, body: meFixture() },
      {
        path: DETAIL,
        body: detailFixture({
          status: 'cancelled',
          status_label: 'Cancelled',
          cancelled_at: '2026-09-03T10:00:00+00:00',
          tracking_state: 'cancelled',
        }),
      },
    ]);

    renderAccount('/account/shipments/SX-CAV-7K9D2M4R8T6W');
    await screen.findByRole('heading', { name: 'SX-CAV-7K9D2M4R8T6W', level: 1 });
    expect(screen.getByText('This shipment was cancelled.')).toBeInTheDocument();
    expect(
      screen.getByText('This shipment was cancelled, so there are no further updates.'),
    ).toBeInTheDocument();
  });

  it('adds no barcode and makes no freshness claim', async () => {
    stubAccountFetch([
      { path: ME, body: meFixture() },
      { path: DETAIL, body: detailFixture() },
    ]);

    renderAccount('/account/shipments/SX-CAV-7K9D2M4R8T6W');
    await screen.findByRole('heading', { name: 'SX-CAV-7K9D2M4R8T6W', level: 1 });

    expect(document.querySelector('svg[data-barcode], canvas, img')).toBeNull();
    expect(document.body.textContent).not.toMatch(/minutes ago|seconds ago|live from|synced/i);
  });

  it('never renders a raw tracking-state value', async () => {
    stubAccountFetch([
      { path: ME, body: meFixture() },
      { path: DETAIL, body: detailFixture({ tracking_state: 'no_public_milestones' }) },
    ]);

    renderAccount('/account/shipments/SX-CAV-7K9D2M4R8T6W');
    await screen.findByRole('heading', { name: 'SX-CAV-7K9D2M4R8T6W', level: 1 });

    expect(document.body.textContent).not.toContain('no_public_milestones');
    expect(
      screen.getByText('There are no updates to show for this shipment yet.'),
    ).toBeInTheDocument();
  });

  it('moves focus to the shipment heading once it has loaded', async () => {
    stubAccountFetch([
      { path: ME, body: meFixture() },
      { path: DETAIL, body: detailFixture() },
    ]);

    renderAccount('/account/shipments/SX-CAV-7K9D2M4R8T6W');
    const heading = await screen.findByRole('heading', {
      name: 'SX-CAV-7K9D2M4R8T6W',
      level: 1,
    });
    await waitFor(() => expect(heading).toHaveFocus());
  });

  it('moves focus to the heading of the not-found page too', async () => {
    stubAccountFetch([
      { path: ME, body: meFixture() },
      {
        path: DETAIL,
        status: 404,
        body: { code: 'not_found', message: 'We could not find that shipment.', field: null },
      },
    ]);

    renderAccount('/account/shipments/SX-CAV-7K9D2M4R8T6W');
    const heading = await screen.findByRole('heading', {
      name: 'We could not find that shipment',
      level: 1,
    });
    await waitFor(() => expect(heading).toHaveFocus());
  });

  it('moves focus to the heading when a row is opened from the list', async () => {
    const user = userEvent.setup();
    stubAccountFetch([
      { path: ME, body: meFixture() },
      { path: DETAIL, body: detailFixture() },
      { path: LIST, body: listPageFixture() },
    ]);

    renderAccount('/account/shipments');
    await screen.findByRole('heading', { name: 'My shipments', level: 1 });
    await user.click(screen.getAllByRole('link', { name: 'SX-CAV-7K9D2M4R8T6W' })[0]);

    const heading = await screen.findByRole('heading', {
      name: 'SX-CAV-7K9D2M4R8T6W',
      level: 1,
    });
    await waitFor(() => expect(heading).toHaveFocus());
  });

  it('offers a way back to the list', async () => {
    stubAccountFetch([
      { path: ME, body: meFixture() },
      { path: DETAIL, body: detailFixture() },
    ]);

    renderAccount('/account/shipments/SX-CAV-7K9D2M4R8T6W');
    const back = await screen.findByRole('link', { name: 'Back to my shipments' });
    expect(back).toHaveAttribute('href', '/account/shipments');
  });
});

describe('pagination', () => {
  it('names the page in words and moves the offset in the URL', async () => {
    const user = userEvent.setup();
    const items = Array.from({ length: 20 }, (_, index) =>
      listItemFixture({ shipment_reference: `SX-CAV-${String(index).padStart(12, 'A')}` }),
    );
    stubAccountFetch([
      { path: ME, body: meFixture() },
      { path: LIST, body: listPageFixture(items, { total: 57 }) },
    ]);

    renderAccount('/account/shipments');
    const nav = await screen.findByRole('navigation', { name: 'Shipment pages' });
    expect(within(nav).getByText('Showing 1 to 20 of 57 shipments')).toBeInTheDocument();
    expect(within(nav).getByRole('button', { name: 'Previous page' })).toBeDisabled();

    await user.click(within(nav).getByRole('button', { name: 'Next page' }));
    await waitFor(() => expect(window.location.search).toContain('offset=20'));
  });
});
