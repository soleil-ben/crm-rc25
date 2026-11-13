/**
 * My profile, on the Customer Account (fix pack 2; CA-PRF-01 … CA-PRF-04).
 *
 * The behaviours a tester checks: the nav link, the values on file, the language setting
 * that changes at once, the change request that changes nothing until review, the explicit
 * marketing choice, and that nothing staff-only appears.
 */

import { beforeEach, describe, expect, it } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { clearBrowserStorage, meFixture, renderAccount, stubAccountFetch } from './accountUtils.jsx';

const ME = '/api/v1/account/me';
const PROFILE = '/api/v1/account/profile';

function profileFixture(overrides = {}) {
  return {
    account_reference: 'CA-7K9D2M4R',
    details: {
      customer_reference: 'STCA-000012',
      legal_name: 'Nguyễn Thị Bích Hạnh',
      display_name: 'Hạnh',
      email: 'hanh@demo.example.com',
      phone: '+1 416 555 0111',
      preferred_language: 'en',
      pickup_address: {
        contact_name: 'Hạnh',
        address_line1: '4120 Dixie Road',
        address_line2: null,
        city: 'Mississauga',
        province_state: 'ON',
        postal_code: 'L4W 1V2',
        country_code: 'CA',
        phone: null,
        delivery_note: null,
      },
    },
    marketing: { status: 'not_given', changed_at: null, delivery_blocked: false },
    marketing_history: [],
    proposals: [],
    proposable_fields: ['display_name', 'legal_name', 'phone'],
    languages: ['en', 'vi', 'fr', 'other'],
    timezone: 'America/Toronto',
    ...overrides,
  };
}

beforeEach(clearBrowserStorage);

describe('My profile', () => {
  it('is linked from the navigation for an account with shipment access', async () => {
    stubAccountFetch([
      { path: ME, body: meFixture() },
      { path: PROFILE, body: profileFixture() },
    ]);
    renderAccount('/account/profile');
    const nav = await screen.findByRole('navigation', { name: 'Customer Account' });
    expect(within(nav).getByRole('link', { name: 'My profile' })).toHaveAttribute(
      'href',
      '/account/profile',
    );
  });

  it('is not offered to a pending account, and the route sends it away', async () => {
    stubAccountFetch([
      { path: ME, body: meFixture({ status: 'pending_approval', shipment_history_available: false, linked: false }) },
    ]);
    renderAccount('/account/profile');
    await screen.findByRole('heading', { name: 'Your account is being reviewed', level: 1 });
    expect(screen.queryByRole('link', { name: 'My profile' })).toBeNull();
  });

  it('shows the values on file and nothing staff-only', async () => {
    stubAccountFetch([
      { path: ME, body: meFixture() },
      // A contaminated response: the screen must render none of it.
      {
        path: PROFILE,
        body: { ...profileFixture(), tags: ['SENTINEL-TAG'], notes: 'SENTINEL-NOTE', owner: 'SENTINEL-OWNER' },
      },
    ]);
    renderAccount('/account/profile');
    await screen.findByRole('heading', { name: 'My profile', level: 1 });
    expect(screen.getByText('STCA-000012')).toBeInTheDocument();
    expect(screen.getByText('Nguyễn Thị Bích Hạnh')).toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(/SENTINEL-/);
  });

  it('saves the preferred language at once, and says the screens stay English', async () => {
    const user = userEvent.setup();
    const { calls } = stubAccountFetch([
      { path: ME, body: meFixture() },
      {
        path: '/api/v1/account/profile/direct',
        method: 'POST',
        body: profileFixture({ details: { ...profileFixture().details, preferred_language: 'vi' } }),
      },
      { path: PROFILE, body: profileFixture() },
    ]);
    renderAccount('/account/profile');
    await screen.findByRole('heading', { name: 'My profile', level: 1 });
    // OD-71: the screens' language is the header switch, and the card says where it is.
    expect(screen.getByText(/use the switch at the top of the page/)).toBeInTheDocument();

    await user.selectOptions(screen.getByLabelText(/Contact me in/), 'vi');
    await user.click(screen.getByRole('button', { name: 'Save language' }));

    await screen.findByText('Your preferred language is saved.');
    const post = calls.find((call) => call.url.endsWith('/profile/direct'));
    expect(JSON.parse(post.init.body)).toEqual({ preferred_language: 'vi' });
  });

  it('sends a name and address change for review, and says nothing changes yet', async () => {
    const user = userEvent.setup();
    const { calls } = stubAccountFetch([
      { path: ME, body: meFixture() },
      {
        path: '/api/v1/account/profile/proposals',
        method: 'POST',
        body: {
          message: 'Thank you. A member of staff will review this change. Your details stay as they are until then.',
          proposal: { status: 'pending', submitted_at: '2026-10-14T05:19:00', reviewed_at: null, fields: [] },
        },
      },
      { path: PROFILE, body: profileFixture() },
    ]);
    renderAccount('/account/profile');
    await screen.findByRole('heading', { name: 'My profile', level: 1 });
    expect(screen.getByText(/What we have on file stays the same until then/)).toBeInTheDocument();

    await user.type(screen.getByLabelText(/^Legal name/), 'Hạnh Nguyễn');
    await user.type(screen.getByLabelText(/^Street address/), '88 Queen Street East');
    await user.type(screen.getByLabelText(/^City/), 'Toronto');
    await user.type(screen.getByLabelText(/^Country code/), 'CA');
    await user.click(screen.getByRole('button', { name: 'Send for review' }));

    await screen.findByText(/A member of staff will review this change/);
    const post = calls.find((call) => call.url.endsWith('/profile/proposals'));
    expect(JSON.parse(post.init.body)).toEqual({
      fields: {
        legal_name: 'Hạnh Nguyễn',
        'pickup_address.1.address_line1': '88 Queen Street East',
        'pickup_address.1.city': 'Toronto',
        'pickup_address.1.country_code': 'CA',
      },
    });
  });

  it('lists each request with its state and lets a pending one be withdrawn', async () => {
    const user = userEvent.setup();
    const pending = {
      status: 'pending',
      submitted_at: '2026-10-14T05:19:00',
      reviewed_at: null,
      fields: [{ field_key: 'legal_name', proposed_value: 'Hạnh Nguyễn', applied: false }],
    };
    const { calls } = stubAccountFetch([
      { path: ME, body: meFixture() },
      {
        path: '/api/v1/account/profile/proposals/withdraw',
        method: 'POST',
        body: profileFixture({ proposals: [{ ...pending, status: 'withdrawn' }] }),
      },
      { path: PROFILE, body: profileFixture({ proposals: [pending] }) },
    ]);
    renderAccount('/account/profile');
    await screen.findByText('Waiting for review');
    // Sent at 05:19 UTC is 01:19 in Toronto (fix pack 2 item 2).
    expect(screen.getByText(/01:19/)).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Withdraw this request' }));
    await screen.findByText('Withdrawn by you');
    expect(calls.some((call) => call.url.endsWith('/withdraw'))).toBe(true);
  });

  it('records an explicit marketing choice, never pre-selected', async () => {
    const user = userEvent.setup();
    const { calls } = stubAccountFetch([
      { path: ME, body: meFixture() },
      {
        path: '/api/v1/account/consent/marketing',
        method: 'POST',
        body: {
          marketing: {
            status: 'granted',
            changed_at: '2026-10-14T05:19:00',
            delivery_blocked: false,
          },
        },
      },
      { path: PROFILE, body: profileFixture() },
    ]);
    renderAccount('/account/profile');
    await screen.findByText('You have not agreed to receive marketing messages.');
    expect(screen.queryByRole('checkbox', { checked: true })).toBeNull();

    await user.click(screen.getByRole('button', { name: 'Yes, send me marketing messages' }));
    await waitFor(() => {
      const post = calls.find((call) => call.url.endsWith('/consent/marketing'));
      expect(JSON.parse(post.init.body)).toEqual({ granted: true });
    });
  });

  it('says plainly, after an opt-in, when marketing email cannot reach the address', async () => {
    const user = userEvent.setup();
    let optedIn = false;
    const granted = {
      status: 'granted',
      changed_at: '2026-10-14T05:19:00',
      delivery_blocked: true,
    };
    stubAccountFetch([
      { path: ME, body: meFixture() },
      {
        path: '/api/v1/account/consent/marketing',
        method: 'POST',
        body: () => {
          optedIn = true;
          return { marketing: granted };
        },
      },
      {
        path: PROFILE,
        body: () => profileFixture(optedIn ? { marketing: granted } : {}),
      },
    ]);
    renderAccount('/account/profile');
    await screen.findByText('You have not agreed to receive marketing messages.');
    expect(screen.queryByText(/cannot currently send marketing email/)).toBeNull();

    await user.click(screen.getByRole('button', { name: 'Yes, send me marketing messages' }));

    expect(
      await screen.findByText(
        'You are opted in, but we cannot currently send marketing email to this address. Contact Solaris Express if you think this is wrong.',
      ),
    ).toBeInTheDocument();
    // The note names no cause: the response carries none to name.
    expect(document.body.textContent).not.toMatch(/suppress|bounce|complain|unsubscrib/i);
  });

  it('shows no such note for an opt-in that can be delivered, or without an opt-in', async () => {
    stubAccountFetch([
      { path: ME, body: meFixture() },
      {
        path: PROFILE,
        body: profileFixture({
          marketing: { status: 'granted', changed_at: '2026-10-14T05:19:00', delivery_blocked: false },
        }),
      },
    ]);
    renderAccount('/account/profile');
    await screen.findByText('You have agreed to receive marketing messages.');
    expect(screen.queryByText(/cannot currently send marketing email/)).toBeNull();
  });
});
