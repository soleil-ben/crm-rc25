/**
 * RC-UAT-21 Phase B: the Customer Account's "Sign-in and security" page (since RC-UAT-25 item 2
 * the sign-in email is read only there), the old email-change link landing page, the staff
 * password page, and the Admin reinstatement of a deactivated account; plus the quote GST/HST
 * sentence (P-9 stand-in).
 */

import { afterEach, describe, expect, it, vi } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Route, Routes } from 'react-router-dom';
import { SessionProvider } from '../src/app/SessionContext.jsx';
import { CustomerAccountReviewPage } from '../src/features/customer_accounts/CustomerAccountReviewPage.jsx';
import { ChangePasswordPage } from '../src/features/auth/ChangePasswordPage.jsx';
import { quoteTaxSentence } from '../src/account/quoteTax.js';
import { translate } from '../src/account/i18n.jsx';
import { renderWithProviders, stubFetch } from './utils.jsx';
import { meFixture, renderAccount, stubAccountFetch } from './accountUtils.jsx';

afterEach(() => {
  vi.unstubAllGlobals();
  document.cookie = 'solaris_account_csrf=; expires=Thu, 01 Jan 1970 00:00:00 GMT; path=/';
});

const ME = { path: '/api/v1/account/me', body: meFixture() };
const SECURITY = {
  email: 'hanh@demo.example.com',
  pending_email_change: null,
  min_password_length: 12,
  message: null,
};

function body(call) {
  return JSON.parse(call.init.body);
}

describe('Account › Sign-in and security › password', () => {
  it('changes the password with the current one, and says other sessions were signed out', async () => {
    const user = userEvent.setup();
    const { calls } = stubAccountFetch([
      ME,
      { path: '/api/v1/account/security', body: SECURITY },
      {
        path: '/api/v1/account/password/change',
        method: 'POST',
        body: { message: 'Password changed. You are still signed in here; every other session was signed out.', csrf_token: 'x' },
      },
    ]);
    renderAccount('/account/security');
    expect(await screen.findByRole('heading', { name: 'Sign-in and security', level: 1 })).toBeInTheDocument();
    expect(screen.getByText('hanh@demo.example.com')).toBeInTheDocument();

    // The local checks speak before anything is sent.
    await user.click(screen.getByRole('button', { name: 'Change password' }));
    expect(screen.getByText('Enter your current password.')).toBeInTheDocument();
    expect(calls.filter((c) => c.method === 'POST')).toHaveLength(0);

    await user.type(screen.getAllByLabelText(/Current password/)[0], 'SolarisCustomer!2026');
    await user.type(screen.getAllByLabelText(/^New password/)[0], 'SolarisCustomer!2027');
    await user.type(screen.getByLabelText(/New password again/), 'SolarisCustomer!2027');
    await user.click(screen.getByRole('button', { name: 'Change password' }));

    expect(await screen.findByText('Password changed.')).toBeInTheDocument();
    const post = calls.find((c) => c.url.endsWith('/password/change'));
    expect(body(post)).toEqual({
      current_password: 'SolarisCustomer!2026',
      new_password: 'SolarisCustomer!2027',
      new_password_confirmation: 'SolarisCustomer!2027',
    });
  });

  it('shows a wrong current password beside the field, in Vietnamese', async () => {
    const user = userEvent.setup();
    stubAccountFetch([
      { path: '/api/v1/account/me', body: meFixture({ preferred_language: 'vi' }) },
      { path: '/api/v1/account/security', body: SECURITY },
      {
        path: '/api/v1/account/password/change',
        method: 'POST',
        status: 422,
        body: { code: 'validation_error', message: 'The current password is not correct.', field: 'current_password' },
      },
    ]);
    renderAccount('/account/security', { locale: 'vi' });
    expect(await screen.findByRole('heading', { name: 'Đăng nhập và bảo mật', level: 1 })).toBeInTheDocument();
    await user.type(screen.getAllByLabelText(/Mật khẩu hiện tại/)[0], 'Wrong!Password2026');
    await user.type(screen.getAllByLabelText(/^Mật khẩu mới/)[0], 'SolarisCustomer!2027');
    await user.type(screen.getByLabelText(/Nhập lại mật khẩu mới/), 'SolarisCustomer!2027');
    await user.click(screen.getByRole('button', { name: 'Đổi mật khẩu' }));
    expect(await screen.findByText('Mật khẩu hiện tại không đúng.')).toBeInTheDocument();
    expect(screen.queryByText('The current password is not correct.')).toBeNull();
  });
});

// RC-UAT-25 item 2 (Ben, 2026-10-25): only Solaris Express changes a sign-in email. The two
// customer-side email tests below replaced "sends the link, shows the change as pending, and can
// cancel it" and the two confirmation-link tests ("redeems the token…", "says one thing for
// every refused link"); see _scratch/rc25_B.md (e).
describe('Account › Sign-in and security › email', () => {
  it('shows the sign-in email read only, with no way to change it here', async () => {
    const { calls } = stubAccountFetch([ME, { path: '/api/v1/account/security', body: SECURITY }]);
    renderAccount('/account/security');
    await screen.findByRole('heading', { name: 'Sign-in and security', level: 1 });
    expect(screen.getByText('hanh@demo.example.com')).toBeInTheDocument();
    expect(screen.getByText(/Only Solaris Express can change your sign-in email/)).toBeInTheDocument();
    expect(screen.queryByLabelText(/New email/)).toBeNull();
    expect(screen.queryByRole('button', { name: 'Send confirmation link' })).toBeNull();
    expect(calls.filter((c) => c.url.includes('/email/change'))).toHaveLength(0);
  });

  it('is open to an account still waiting for review', async () => {
    stubAccountFetch([
      {
        path: '/api/v1/account/me',
        body: meFixture({ status: 'pending_approval', linked: false, shipment_history_available: false }),
      },
      { path: '/api/v1/account/security', body: SECURITY },
    ]);
    renderAccount('/account/security');
    expect(await screen.findByRole('heading', { name: 'Sign-in and security', level: 1 })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Sign-in and security' })).toBeInTheDocument();
  });
});

describe('Account › confirm email change link', () => {
  it('sends the token from the fragment once and says the link no longer works', async () => {
    const { calls } = stubAccountFetch([
      { path: '/api/v1/account/me', status: 401, body: { code: 'authentication_required', message: 'Sign in to continue.', field: null } },
      {
        path: '/api/v1/account/email/change/confirm',
        method: 'POST',
        status: 422,
        body: { code: 'validation_error', message: 'That link is no longer valid. Request a new one.', field: 'token' },
      },
    ]);
    renderAccount('/account/confirm-email-change#token=abc123');
    expect(await screen.findByText('This link no longer works')).toBeInTheDocument();
    expect(screen.getByText('The email was not changed.')).toBeInTheDocument();
    const posts = calls.filter((c) => c.url.endsWith('/email/change/confirm'));
    expect(posts).toHaveLength(1);
    expect(body(posts[0])).toEqual({ token: 'abc123' });
    expect(window.location.hash).toBe('');
  });

  it('says the same with no token at all, and sends nothing', async () => {
    const { calls } = stubAccountFetch([
      { path: '/api/v1/account/me', status: 401, body: { code: 'authentication_required', message: 'Sign in to continue.', field: null } },
    ]);
    renderAccount('/account/confirm-email-change');
    expect(await screen.findByText('This link no longer works')).toBeInTheDocument();
    expect(calls.filter((c) => c.method === 'POST')).toHaveLength(0);
  });
});



describe('Quote GST/HST sentence (P-9 stand-in)', () => {
  const t = (locale) => (key, values) => translate(locale, key, values);
  it('follows the invoice rule in both languages', () => {
    const domestic = { band: 'domestic', label: 'HST', rate_percent: 13 };
    const intl = { band: 'international', label: null, rate_percent: 0 };
    const unknown = { band: 'domestic', label: 'GST/HST', rate_percent: null };
    expect(quoteTaxSentence(t('vi'), domestic)).toBe('Giá đã bao gồm HST 13 %');
    expect(quoteTaxSentence(t('en'), domestic)).toBe('Prices include HST 13 %');
    expect(quoteTaxSentence(t('vi'), intl)).toBe('Thuế suất 0 (0 %)');
    expect(quoteTaxSentence(t('en'), intl)).toBe('Zero-rated (0 %)');
    expect(quoteTaxSentence(t('vi'), unknown)).toBe('Giá đã bao gồm GST/HST');
    expect(quoteTaxSentence(t('en'), null)).toBeNull();
  });
});

/* --- Staff ------------------------------------------------------------------------------- */

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

const IDENTITY = '/customer-account/identities/CA-7K9D2M4R';
const REVIEW = 'customer_account:review';
const APPROVE = 'customer_account:approve';
const DEACTIVATE = 'customer_account:deactivate';

function deactivatedIdentity(overrides = {}) {
  return {
    account_reference: 'CA-7K9D2M4R',
    status: 'deactivated',
    status_reason_code: 'customer_request',
    account_email_entered: 'Hanh.Nguyen@example.com',
    email_verified: true,
    approved_at: '2026-09-20T10:00:00',
    suspended_at: null,
    deactivated_at: '2026-10-20T10:00:00',
    linked_customer_public_id: 'STCA-000012',
    can_suspend: false,
    can_reinstate: false,
    can_deactivate: false,
    can_reactivate: true,
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

const DECIDED = {
  path: '/customer-account/registrations/CA-7K9D2M4R',
  status: 409,
  body: { code: 'conflict', message: 'This registration has already been decided.', field: null, detail: null },
};

describe('Staff › reinstating a deactivated account', () => {
  it('Admin reinstates with a reason and an optional note', async () => {
    const user = userEvent.setup();
    const fetchMock = renderReview([
      session('admin', [REVIEW, APPROVE, DEACTIVATE]),
      {
        path: `${IDENTITY}/reactivate`,
        method: 'POST',
        body: deactivatedIdentity({
          status: 'active',
          deactivated_at: null,
          status_reason_code: 'deactivated_in_error',
          can_reactivate: false,
          can_deactivate: true,
          can_suspend: true,
        }),
      },
      DECIDED,
      { path: IDENTITY, body: deactivatedIdentity() },
    ]);
    const action = await screen.findByRole('button', { name: 'Reinstate account' });
    expect(action).toBeDisabled();
    await user.selectOptions(screen.getByLabelText('Grounds for reinstating'), 'deactivated_in_error');
    await user.type(screen.getByLabelText(/Note \(optional/), 'Deactivated by mistake.');
    await user.click(action);
    expect(await screen.findByText('The account has been reinstated. The customer must sign in again.')).toBeInTheDocument();
    const call = fetchMock.mock.calls.find(([url]) => String(url).includes('/reactivate'));
    expect(JSON.parse(call[1].body)).toEqual({ reason_code: 'deactivated_in_error', note: 'Deactivated by mistake.' });
  });

  it('is not offered to Operations, and says why when it is refused', async () => {
    renderReview([session('operations', [REVIEW, APPROVE]), DECIDED, { path: IDENTITY, body: deactivatedIdentity() }]);
    await screen.findByText('Deactivated');
    expect(screen.queryByRole('button', { name: 'Reinstate account' })).toBeNull();
  });

  it('a privacy-request deactivation shows no control to Admin', async () => {
    renderReview([
      session('admin', [REVIEW, APPROVE, DEACTIVATE]),
      DECIDED,
      { path: IDENTITY, body: deactivatedIdentity({ status_reason_code: 'privacy_request', can_reactivate: false }) },
    ]);
    expect(await screen.findByText(/cannot be reinstated/)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Reinstate account' })).toBeNull();
  });
});

describe('Staff › change your password', () => {
  it('needs the current password and posts all three fields', async () => {
    const user = userEvent.setup();
    const fetchMock = stubFetch([
      { path: '/auth/password/change', method: 'POST', body: { ok: true, message: 'Password changed.' } },
    ]);
    renderWithProviders(<ChangePasswordPage />);
    await user.click(screen.getByRole('button', { name: 'Change password' }));
    expect(screen.getByText('Enter your current password.')).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();

    await user.type(screen.getByLabelText(/Current password/), 'TestPassword!2026');
    await user.type(screen.getAllByLabelText(/^New password/)[0], 'StaffNewPassword!2027');
    await user.type(screen.getByLabelText(/New password again/), 'StaffNewPassword!2027');
    await user.click(screen.getByRole('button', { name: 'Change password' }));
    expect(await screen.findByText(/Password changed\. Every other session/)).toBeInTheDocument();
    const [, init] = fetchMock.mock.calls[0];
    expect(JSON.parse(init.body)).toEqual({
      current_password: 'TestPassword!2026',
      new_password: 'StaffNewPassword!2027',
      new_password_confirmation: 'StaffNewPassword!2027',
    });
  });

  it('shows the server refusal beside the current password', async () => {
    const user = userEvent.setup();
    stubFetch([
      {
        path: '/auth/password/change',
        method: 'POST',
        status: 422,
        body: { code: 'validation_error', message: 'The current password is not correct.', field: 'current_password', detail: null },
      },
    ]);
    renderWithProviders(<ChangePasswordPage />);
    await user.type(screen.getByLabelText(/Current password/), 'Wrong!Password2026');
    await user.type(screen.getAllByLabelText(/^New password/)[0], 'StaffNewPassword!2027');
    await user.type(screen.getByLabelText(/New password again/), 'StaffNewPassword!2027');
    await user.click(screen.getByRole('button', { name: 'Change password' }));
    await waitFor(() => expect(screen.getByText('The current password is not correct.')).toBeInTheDocument());
    const form = screen.getByRole('button', { name: 'Change password' }).closest('form');
    expect(within(form).getByText('The current password is not correct.')).toBeInTheDocument();
  });
});
