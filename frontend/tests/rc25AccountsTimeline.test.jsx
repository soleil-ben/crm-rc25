/**
 * RC-UAT-25, Ben 2026-10-25:
 *
 * - item 2: the Customer Account shows the sign-in email read only and says only Solaris
 *   Express changes it; an old confirmation link lands on a page that says it no longer works;
 *   an Admin changes the sign-in email on the staff account screen (Operations does not see it).
 * - item 5: "Received at Solaris" reads "Received at warehouse" / "Đã nhận hàng tại kho", and
 *   the standard update is the warehouse sentence.
 * - item 6: a published timeline event has an Edit control with a clear warning; the
 *   correction is posted with its reason; the edit history is shown.
 */

import { afterEach, describe, expect, it, vi } from 'vitest';
import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Route, Routes } from 'react-router-dom';
import { SessionProvider } from '../src/app/SessionContext.jsx';
import { CustomerAccountReviewPage } from '../src/features/customer_accounts/CustomerAccountReviewPage.jsx';
import { TrackingTab } from '../src/features/shipments/shipmentTabs.jsx';
import { renderTemplate, templatesFor } from '../src/shared/publicUpdateTemplates.js';
import en from '../src/i18n/en.js';
import vi_ from '../src/i18n/vi.js';
import publicEn from '../src/public/locales/en.js';
import publicVi from '../src/public/locales/vi.js';
import accountEn from '../src/account/i18n/en.js';
import accountVi from '../src/account/i18n/vi.js';
import { renderWithProviders, stubFetch } from './utils.jsx';
import { meFixture, renderAccount, stubAccountFetch } from './accountUtils.jsx';

afterEach(() => {
  vi.unstubAllGlobals();
  document.cookie = 'solaris_account_csrf=; expires=Thu, 01 Jan 1970 00:00:00 GMT; path=/';
});

function session(role, permissions) {
  return {
    path: '/auth/me',
    body: {
      user: {
        id: 1,
        full_name: 'Test Person',
        email: 'person@demo.example.com',
        role,
        initials: 'TP',
        timezone: 'America/Toronto',
        locale: 'en',
      },
      permissions,
      environment: 'test',
      is_demo_environment: false,
    },
  };
}

/* --- Item 2: the customer's side ------------------------------------------------------- */

const SECURITY = {
  email: 'hanh@demo.example.com',
  pending_email_change: null,
  min_password_length: 12,
  message: null,
};

describe('Account › Sign-in and security › the email is read only', () => {
  it('shows the sign-in email, says Solaris Express changes it, and offers no form', async () => {
    stubAccountFetch([
      { path: '/api/v1/account/me', body: meFixture() },
      { path: '/api/v1/account/security', body: SECURITY },
    ]);
    renderAccount('/account/security');
    await screen.findByRole('heading', { name: 'Sign-in and security', level: 1 });
    expect(screen.getByRole('heading', { name: 'Your sign-in email' })).toBeInTheDocument();
    expect(screen.getByText('hanh@demo.example.com')).toBeInTheDocument();
    expect(
      screen.getByText(
        'Only Solaris Express can change your sign-in email. Contact us and we will change it for you.',
      ),
    ).toBeInTheDocument();
    expect(screen.queryByLabelText(/New email/)).toBeNull();
    expect(screen.queryByRole('button', { name: 'Send confirmation link' })).toBeNull();
    // The password change stays.
    expect(screen.getByRole('button', { name: 'Change password' })).toBeInTheDocument();
  });

  it('says the same in Vietnamese', async () => {
    stubAccountFetch([
      { path: '/api/v1/account/me', body: meFixture({ preferred_language: 'vi' }) },
      { path: '/api/v1/account/security', body: SECURITY },
    ]);
    renderAccount('/account/security', { locale: 'vi' });
    await screen.findByRole('heading', { name: 'Đăng nhập và bảo mật', level: 1 });
    expect(screen.getByRole('heading', { name: 'Email đăng nhập của bạn' })).toBeInTheDocument();
    expect(
      screen.getByText(/Chỉ Solaris Express mới có thể đổi email đăng nhập của bạn/),
    ).toBeInTheDocument();
  });
});

describe('Account › an old confirmation link', () => {
  it('says the link no longer works, never "confirmed", and sends the token once', async () => {
    const { calls } = stubAccountFetch([
      {
        path: '/api/v1/account/me',
        status: 401,
        body: { code: 'authentication_required', message: 'Sign in to continue.', field: null },
      },
      {
        path: '/api/v1/account/email/change/confirm',
        method: 'POST',
        status: 422,
        body: { code: 'validation_error', message: 'That link is no longer valid. Request a new one.', field: 'token' },
      },
    ]);
    renderAccount('/account/confirm-email-change#token=abc123');
    expect(await screen.findByRole('heading', { name: 'This link no longer works' })).toBeInTheDocument();
    expect(screen.getByText(/Sign-in emails are now changed by Solaris Express/)).toBeInTheDocument();
    expect(screen.queryByText('Your new email is confirmed.')).toBeNull();
    const posts = calls.filter((c) => c.url.endsWith('/email/change/confirm'));
    expect(posts).toHaveLength(1);
    expect(window.location.hash).toBe('');
  });
});

/* --- Item 2: the Admin's side ---------------------------------------------------------- */

const IDENTITY = '/customer-account/identities/CA-7K9D2M4R';
const REVIEW = 'customer_account:review';
const APPROVE = 'customer_account:approve';
const DEACTIVATE = 'customer_account:deactivate';
const DECIDED = {
  path: '/customer-account/registrations/CA-7K9D2M4R',
  status: 409,
  body: { code: 'conflict', message: 'This registration has already been decided.', field: null, detail: null },
};

function activeIdentity(overrides = {}) {
  return {
    account_reference: 'CA-7K9D2M4R',
    status: 'active',
    status_reason_code: null,
    account_email_entered: 'Hanh.Nguyen@example.com',
    email_verified: true,
    approved_at: '2026-09-20T10:00:00',
    suspended_at: null,
    deactivated_at: null,
    linked_customer_public_id: 'STCA-000012',
    can_suspend: true,
    can_reinstate: false,
    can_deactivate: true,
    can_reactivate: false,
    can_change_sign_in_email: true,
    ...overrides,
  };
}

function renderReview(routes) {
  const fetchMock = stubFetch(routes);
  renderWithProviders(
    <SessionProvider>
      <Routes>
        <Route path="/customer-accounts/:accountReference" element={<CustomerAccountReviewPage />} />
      </Routes>
    </SessionProvider>,
    { route: '/customer-accounts/CA-7K9D2M4R' },
  );
  return fetchMock;
}

describe('Staff › an Admin changes the sign-in email', () => {
  it('needs an address and a reason, confirms both addresses, and posts the change', async () => {
    const user = userEvent.setup();
    const fetchMock = renderReview([
      session('admin', [REVIEW, APPROVE, DEACTIVATE]),
      {
        path: `${IDENTITY}/sign-in-email`,
        method: 'POST',
        body: activeIdentity({ account_email_entered: 'hanh.moi@example.com' }),
      },
      DECIDED,
      { path: IDENTITY, body: activeIdentity() },
    ]);
    const action = await screen.findByRole('button', { name: 'Change sign-in email' });
    expect(action).toBeDisabled();
    await user.type(screen.getByLabelText('New sign-in email'), 'hanh.moi@example.com');
    await user.selectOptions(screen.getByLabelText('Grounds for the change'), 'mailbox_lost');
    await user.type(screen.getAllByLabelText(/Note \(optional/)[0], 'Phoned in.');
    await user.click(action);
    const dialog = await screen.findByRole('dialog');
    expect(within(dialog).getByText(/From Hanh\.Nguyen@example\.com to hanh\.moi@example\.com/)).toBeInTheDocument();
    await user.click(within(dialog).getByRole('button', { name: 'Yes, change it' }));
    expect(
      await screen.findByText('The sign-in email has been changed. The customer must sign in again with the new address.'),
    ).toBeInTheDocument();
    const call = fetchMock.mock.calls.find(([url]) => String(url).includes('/sign-in-email'));
    expect(JSON.parse(call[1].body)).toEqual({
      new_email: 'hanh.moi@example.com',
      reason_code: 'mailbox_lost',
      note: 'Phoned in.',
    });
  });

  it('is not offered to Operations', async () => {
    renderReview([session('operations', [REVIEW, APPROVE]), DECIDED, { path: IDENTITY, body: activeIdentity() }]);
    await screen.findByText('Active');
    expect(screen.queryByRole('button', { name: 'Change sign-in email' })).toBeNull();
  });

  it('says why when the account cannot change', async () => {
    renderReview([
      session('admin', [REVIEW, APPROVE, DEACTIVATE]),
      DECIDED,
      {
        path: IDENTITY,
        body: activeIdentity({ status: 'deactivated', can_change_sign_in_email: false, can_reactivate: true }),
      },
    ]);
    expect(await screen.findByText(/Reinstate a deactivated account first/)).toBeInTheDocument();
    expect(screen.queryByLabelText('New sign-in email')).toBeNull();
  });
});

/* --- Item 5: the warehouse wording ----------------------------------------------------- */

describe('"Received at Solaris" reads "Received at warehouse"', () => {
  it('in every catalogue, with the stored code unchanged', () => {
    expect(en.eventType.received_at_solaris).toBe('Received at warehouse');
    expect(vi_.eventType.received_at_solaris).toBe('Đã nhận hàng tại kho');
    expect(publicEn.status.received_at_solaris).toBe('Received at warehouse');
    expect(publicVi.status.received_at_solaris).toBe('Đã nhận hàng tại kho');
    expect(accountEn['status.received_at_solaris']).toBe('Received at warehouse');
    expect(accountVi['status.received_at_solaris']).toBe('Đã nhận hàng tại kho');
    for (const catalogue of [en, vi_, publicEn, publicVi, accountEn, accountVi]) {
      expect(JSON.stringify(catalogue)).not.toMatch(/Received at Solaris|nhận tại Solaris|tại kho Solaris/);
    }
  });

  it('offers the warehouse sentence as the standard update', () => {
    expect(templatesFor('received_at_solaris')).toEqual(['received_at_solaris.v2']);
    expect(renderTemplate('received_at_solaris.v2', 'en')).toBe('We have received your shipment at our warehouse.');
    expect(renderTemplate('received_at_solaris.v2', 'vi')).toBe('Chúng tôi đã nhận lô hàng của bạn tại kho.');
    // An event that carries the retired key still renders what the customer was told.
    expect(renderTemplate('received_at_solaris.v1', 'en')).toBe('We have received your shipment at our facility.');
  });
});

/* --- Item 6: editing a published event ------------------------------------------------- */

const PACKAGES = [
  { id: 1, package_reference: 'SX-VCA-1-1', position_label: '1 of 2', is_active: true, operational_state: 'received_at_solaris' },
  { id: 2, package_reference: 'SX-VCA-1-2', position_label: '2 of 2', is_active: true, operational_state: 'received_at_solaris' },
];

function eventRow(id, packageId) {
  return {
    id,
    shipment_id: 10,
    package_id: packageId,
    package_reference: `SX-VCA-1-${packageId}`,
    leg_id: null,
    event_type: 'received_at_solaris',
    event_type_label: 'Received at warehouse',
    operational_state: 'received_at_solaris',
    occurred_at: '2026-10-24T10:00:00',
    recorded_at: '2026-10-24T10:05:00',
    location_label: 'Ho Chi Minh City',
    location_country_code: 'VN',
    internal_detail: null,
    is_public_update: true,
    public_update_text: null,
    public_update_template_key: 'received_at_solaris.v2',
    public_update_template_text: 'We have received your shipment at our warehouse.',
    is_final_recipient_delivery: false,
    source: 'manual',
    is_voided: false,
    voided_reason: null,
    recorded_by: { id: 2, full_name: 'Ops Person', email: 'ops@demo.example.com', role: 'operations' },
  };
}

const REVISION = {
  id: 5,
  shipment_id: 10,
  event_ids_before: [11, 12],
  event_ids_after: [11, 12],
  before: { event_type: 'received_at_solaris', location_label: 'Hanoi', public_update_template_key: 'received_at_solaris.v2' },
  after: { event_type: 'received_at_solaris', location_label: 'Ho Chi Minh City', public_update_template_key: 'received_at_solaris.v2' },
  reason: 'Wrong warehouse entered.',
  was_published: true,
  public_wording_changed: false,
  edited_at: '2026-10-25T09:00:00',
  edited_by: { id: 1, full_name: 'Test Person', email: 'person@demo.example.com', role: 'admin' },
};

function renderTracking(role, permissions, revisions = []) {
  const fetchMock = stubFetch([
    session(role, permissions),
    { path: '/shipments/10/events/edit', method: 'POST', body: [eventRow(11, 1), eventRow(12, 2)] },
    { path: '/shipments/10/event-revisions', body: revisions },
    { path: '/shipments/10/events', body: [eventRow(11, 1), eventRow(12, 2)] },
  ]);
  renderWithProviders(
    <SessionProvider>
      <TrackingTab
        shipment={{ id: 10, booking_state: 'confirmed', public_id: 'SX-VCA-1' }}
        packages={PACKAGES}
        legs={[]}
        onPrint={() => {}}
      />
    </SessionProvider>,
  );
  return fetchMock;
}

describe('Shipment › Tracking › editing a published event', () => {
  it('warns that the event is published and posts the correction with its reason', async () => {
    const user = userEvent.setup();
    const fetchMock = renderTracking('operations', ['shipment:read', 'tracking:write']);
    await user.click(await screen.findByRole('button', { name: /^Edit: Received at warehouse/ }));
    const form = screen.getByRole('form', { name: 'Edit this event' });
    expect(within(form).getByText(/This event is already published to the customer/)).toBeInTheDocument();
    expect(within(form).getByText(/No email is sent about it/)).toBeInTheDocument();

    const save = within(form).getByRole('button', { name: 'Save correction' });
    expect(save).toBeDisabled(); // a reason is required
    const location = within(form).getByLabelText(/^Location/);
    await user.clear(location);
    await user.type(location, 'Hanoi');
    await user.type(within(form).getByLabelText(/^Reason for the correction/), 'Wrong warehouse entered.');
    await user.click(save);

    const call = fetchMock.mock.calls.find(([url]) => String(url).includes('/events/edit'));
    expect(call).toBeTruthy();
    const sent = JSON.parse(call[1].body);
    expect(sent).toMatchObject({
      event_ids: [11, 12],
      event_type: 'received_at_solaris',
      package_ids: [],
      location_label: 'Hanoi',
      public_update_template_key: 'received_at_solaris.v2',
      public_update_text: null,
      reason: 'Wrong warehouse entered.',
    });
    expect(sent.occurred_at).toBeUndefined(); // unchanged, so not sent
  });

  it('switching the type to one the standard update does not cover picks that type’s update', async () => {
    const user = userEvent.setup();
    const fetchMock = renderTracking('admin', ['shipment:read', 'tracking:write']);
    await user.click(await screen.findByRole('button', { name: /^Edit: / }));
    const form = screen.getByRole('form', { name: 'Edit this event' });
    await user.selectOptions(within(form).getByLabelText(/^Event type/), 'in_transit');
    // The new type's standard update is chosen and previewed (EN and VI).
    expect(within(form).getByLabelText(/^Customer-visible update/)).toHaveValue('in_transit.v1');
    expect(within(form).getAllByText('Your shipment is on its way.').length).toBeGreaterThan(1);
    await user.type(within(form).getByLabelText(/^Reason for the correction/), 'It had left already.');
    await user.click(within(form).getByRole('button', { name: 'Save correction' }));
    const call = fetchMock.mock.calls.find(([url]) => String(url).includes('/events/edit'));
    expect(JSON.parse(call[1].body)).toMatchObject({
      event_type: 'in_transit',
      public_update_template_key: 'in_transit.v1',
    });
  });

  it('offers no edit without the tracking permission, and shows the edit history', async () => {
    renderTracking('marketing', ['shipment:read'], [REVISION]);
    expect(await screen.findByText('Edit history')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /^Edit: / })).toBeNull();
    expect(screen.getAllByText('Edited').length).toBeGreaterThan(0);
    expect(screen.getByText('Changed: location')).toBeInTheDocument();
    expect(screen.getByText('Wrong warehouse entered.')).toBeInTheDocument();
  });
});
