/**
 * The Customer Account notifications page (OD-72), against a mocked API.
 *
 * The contract: `GET /api/v1/account/notifications` and
 * `POST /api/v1/account/notifications/preferences` with `{ preferences: { <milestone>: bool } }`,
 * both answering `{ channel, preferences, history }`.
 */

import { beforeEach, describe, expect, it } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { clearBrowserStorage, meFixture, renderAccount, stubAccountFetch } from './accountUtils.jsx';

const NOTIFICATIONS = '/api/v1/account/notifications';
const PREFERENCES = '/api/v1/account/notifications/preferences';

function notificationsFixture(overrides = {}) {
  return {
    channel: 'email',
    preferences: { received: true, in_transit: false, out_for_delivery: true, delivered: true },
    history: [
      {
        milestone: 'delivered',
        shipment_reference: 'SX-CAV-7K9D2M4R8T6W',
        created_at: '2026-10-18T15:30:00+00:00',
        state: 'sent',
      },
      {
        milestone: 'in_transit',
        shipment_reference: null,
        created_at: '2026-10-17T09:00:00+00:00',
        state: 'not_sent',
      },
    ],
    ...overrides,
  };
}

const ME = { path: '/api/v1/account/me', body: meFixture() };

/** Matched by exact suffix so the GET route does not also answer the POST path. */
function getRoute(body, status) {
  return { path: NOTIFICATIONS, method: 'GET', body, status };
}

describe('the notifications page', () => {
  beforeEach(clearBrowserStorage);

  it('is linked from the navigation and shows each milestone with its saved choice', async () => {
    stubAccountFetch([ME, getRoute(notificationsFixture())]);
    renderAccount('/account/notifications');

    expect(
      await screen.findByRole('heading', { name: 'Notifications', level: 1 }),
    ).toBeInTheDocument();
    const nav = screen.getByRole('navigation', { name: 'Customer Account' });
    expect(within(nav).getByRole('link', { name: 'Notifications' })).toHaveAttribute(
      'href',
      '/account/notifications',
    );

    expect(screen.getByLabelText('Received')).toBeChecked();
    expect(screen.getByLabelText('In transit')).not.toBeChecked();
    expect(screen.getByLabelText('Out for delivery')).toBeChecked();
    expect(screen.getByLabelText('Delivered')).toBeChecked();
    expect(
      screen.getByText(/to the email address Solaris Express has on file for you/),
    ).toBeInTheDocument();
    // The boxes are one group, named by its legend.
    const group = screen.getByRole('group', { name: 'Email me when a shipment is' });
    expect(within(group).getAllByRole('checkbox')).toHaveLength(4);
    // The heading has focus once the settings are on screen.
    await waitFor(() =>
      expect(screen.getByRole('heading', { name: 'Notifications', level: 1 })).toHaveFocus(),
    );
    expect(screen.getByText('Times are shown in America/Toronto.')).toBeInTheDocument();
    expect(screen.getByText(/mobile app is planned/)).toBeInTheDocument();
  });

  it('posts only the milestone that changed', async () => {
    const user = userEvent.setup();
    const saved = notificationsFixture({
      preferences: { received: true, in_transit: true, out_for_delivery: true, delivered: true },
    });
    const { calls } = stubAccountFetch([
      ME,
      { path: PREFERENCES, method: 'POST', body: saved },
      getRoute(notificationsFixture()),
    ]);
    renderAccount('/account/notifications');
    await user.click(await screen.findByLabelText('In transit'));

    await waitFor(() => expect(screen.getByLabelText('In transit')).toBeChecked());
    const post = calls.find((call) => call.method === 'POST' && call.url.endsWith(PREFERENCES));
    expect(JSON.parse(post.init.body)).toEqual({ preferences: { in_transit: true } });
    expect(post.headers['Content-Type']).toBe('application/json');
    const announced = await screen.findByText(
      'Saved. We will email you when a shipment is: In transit.',
    );
    expect(announced).toHaveAttribute('role', 'status');
  });

  it('renders the history: milestone, shipment, date and state', async () => {
    stubAccountFetch([ME, getRoute(notificationsFixture())]);
    renderAccount('/account/notifications');

    const history = await screen.findByRole('list', {
      name: 'Notifications for your shipments, newest first.',
    });
    const items = within(history).getAllByRole('listitem');
    expect(items).toHaveLength(2);
    expect(within(items[0]).getByText('Delivered')).toBeInTheDocument();
    expect(within(items[0]).getByText('SX-CAV-7K9D2M4R8T6W')).toBeInTheDocument();
    expect(within(items[0]).getByText('Sent')).toBeInTheDocument();
    expect(within(items[0]).getByText(/2026/)).toBeInTheDocument();
    expect(within(items[1]).getByText('In transit')).toBeInTheDocument();
    expect(within(items[1]).getByText('Not recorded')).toBeInTheDocument();
    expect(within(items[1]).getByText('Not sent')).toBeInTheDocument();
  });

  it('says so when there is no history yet', async () => {
    stubAccountFetch([ME, getRoute(notificationsFixture({ history: [] }))]);
    renderAccount('/account/notifications');
    expect(await screen.findByText('No notifications yet.')).toBeInTheDocument();
  });

  it('shows a load failure in words, with a retry', async () => {
    const user = userEvent.setup();
    const failing = getRoute(
      { code: 'server_error', message: 'The notification service is down.', field: null },
      500,
    );
    const routes = [ME, failing];
    stubAccountFetch(routes);
    renderAccount('/account/notifications');
    expect(
      await screen.findByText('We could not load your notification settings.'),
    ).toBeInTheDocument();
    expect(screen.getByText('The notification service is down.')).toBeInTheDocument();

    // The service recovers; Try again reads it again.
    failing.status = 200;
    failing.body = notificationsFixture();
    await user.click(screen.getByRole('button', { name: 'Try again' }));
    expect(await screen.findByLabelText('Received')).toBeChecked();
  });

  it('says the session has ended, and offers sign-in, on a 401', async () => {
    stubAccountFetch([
      ME,
      getRoute({ code: 'not_authenticated', message: 'Sign in to continue.', field: null }, 401),
    ]);
    renderAccount('/account/notifications');
    expect(await screen.findByText('Your session has ended.')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Sign in' })).toHaveAttribute(
      'href',
      '/account/sign-in',
    );
    expect(screen.queryByRole('button', { name: 'Try again' })).toBeNull();
  });

  it('never drops a change made while another is saving', async () => {
    const user = userEvent.setup();
    let release;
    const gate = new Promise((resolve) => {
      release = resolve;
    });
    let current = { ...notificationsFixture().preferences };
    const { calls } = stubAccountFetch([
      ME,
      {
        path: PREFERENCES,
        method: 'POST',
        body: (init) => {
          current = { ...current, ...JSON.parse(init.body).preferences };
          return notificationsFixture({ preferences: { ...current } });
        },
      },
      getRoute(notificationsFixture()),
    ]);
    // Hold the first save open so the next clicks land while it is in flight.
    const handler = globalThis.fetch;
    let first = true;
    globalThis.fetch = async (input, init = {}) => {
      if (first && (init.method || 'GET') === 'POST') {
        first = false;
        await gate;
      }
      return handler(input, init);
    };

    renderAccount('/account/notifications');
    await user.click(await screen.findByLabelText('In transit'));
    await user.click(screen.getByLabelText('Received'));
    await user.click(screen.getByLabelText('Delivered'));
    // The boxes show what was asked for straight away.
    expect(screen.getByLabelText('In transit')).toBeChecked();
    expect(screen.getByLabelText('Received')).not.toBeChecked();
    expect(screen.getByLabelText('Delivered')).not.toBeChecked();

    release();
    await waitFor(() =>
      expect(calls.filter((call) => call.method === 'POST')).toHaveLength(3),
    );
    const bodies = calls
      .filter((call) => call.method === 'POST')
      .map((call) => JSON.parse(call.init.body).preferences);
    expect(bodies).toEqual([{ in_transit: true }, { received: false }, { delivered: false }]);
    await waitFor(() =>
      expect(
        screen.getByText('Saved. We will not email you when a shipment is: Delivered.'),
      ).toBeInTheDocument(),
    );
    expect(screen.getByLabelText('Delivered')).not.toBeChecked();
    expect(screen.getByLabelText('Received')).not.toBeChecked();
    expect(screen.getByLabelText('In transit')).toBeChecked();
  });

  it('shows a save failure and keeps the saved value', async () => {
    const user = userEvent.setup();
    stubAccountFetch([
      ME,
      {
        path: PREFERENCES,
        method: 'POST',
        status: 422,
        body: { code: 'invalid', message: 'That milestone is not recognised.', field: null },
      },
      getRoute(notificationsFixture()),
    ]);
    renderAccount('/account/notifications');
    await user.click(await screen.findByLabelText('Received'));

    expect(await screen.findByText('That milestone is not recognised.')).toBeInTheDocument();
    expect(screen.getByText('We could not save that.')).toBeInTheDocument();
    expect(screen.getByText('Not saved: Received.')).toBeInTheDocument();
    await waitFor(() => expect(screen.getByLabelText('Received')).toBeChecked());
  });

  it('is behind the same guard as the profile', async () => {
    stubAccountFetch([
      { path: '/api/v1/account/me', body: meFixture({ status: 'pending_approval', linked: false, shipment_history_available: false }) },
    ]);
    renderAccount('/account/notifications');
    expect(
      await screen.findByRole('heading', { name: 'Your account is being reviewed', level: 1 }),
    ).toBeInTheDocument();
  });

  it('reads in Vietnamese', async () => {
    stubAccountFetch([ME, getRoute(notificationsFixture())]);
    renderAccount('/account/notifications', { locale: 'vi' });
    // `meFixture` prefers English, which wins over the starting language; switch back.
    const user = userEvent.setup();
    await screen.findByRole('heading', { name: 'Notifications', level: 1 });
    await user.click(screen.getByRole('button', { name: 'Tiếng Việt' }));

    expect(await screen.findByRole('heading', { name: 'Thông báo', level: 1 })).toBeInTheDocument();
    expect(
      screen.getByRole('group', { name: 'Gửi email cho tôi khi lô hàng đạt mốc:' }),
    ).toBeInTheDocument();
    expect(screen.getByLabelText('Đã nhận hàng tại kho')).toBeChecked();
    expect(screen.getByLabelText('Đang vận chuyển')).not.toBeChecked();
    expect(screen.getByLabelText('Đang giao hàng')).toBeChecked();
    expect(screen.getAllByText('Đã giao').length).toBeGreaterThan(0);
    expect(screen.getByText('Đã gửi')).toBeInTheDocument();
    expect(screen.getByText(/địa chỉ email mà Solaris Express đang lưu/)).toBeInTheDocument();
  });

  it('words a server refusal in Vietnamese, not in the English it arrived in', async () => {
    const user = userEvent.setup();
    stubAccountFetch([
      { path: '/api/v1/account/me', body: meFixture({ preferred_language: 'vi' }) },
      {
        path: PREFERENCES,
        method: 'POST',
        status: 429,
        headers: { 'Retry-After': '30' },
        body: { code: 'rate_limited', message: 'Too many requests.', field: null },
      },
      getRoute(notificationsFixture()),
    ]);
    renderAccount('/account/notifications', { locale: null });
    await user.click(await screen.findByLabelText('Đã nhận hàng tại kho'));
    expect(
      await screen.findByText('Quá nhiều yêu cầu. Vui lòng đợi khoảng 30 giây rồi thử lại.'),
    ).toBeInTheDocument();
    expect(screen.queryByText('Too many requests.')).toBeNull();
  });
});
