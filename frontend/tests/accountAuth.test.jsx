/**
 * Registration, verification, recovery, and the authentication shell.
 *
 * The recurring assertion in this file is about what is *not* said. A registration that
 * finds an existing address and one that does not must produce the same screen; a
 * rejection must produce no reason; a suspended account and a deactivated one must
 * produce the same page. Each of those is one sentence of code away from being wrong, and
 * none of them is visible in review as a bug.
 */

import { describe, expect, it, beforeEach } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {
  clearBrowserStorage,
  fillRegistrationAddress,
  listPageFixture,
  meFixture,
  renderAccount,
  requestedUrls,
  stubAccountFetch,
} from './accountUtils.jsx';
import { SUBMITTED_FIELD_KEYS } from '../src/account/pages/RegisterPage.jsx';
import { captureLinkToken, takeLinkToken } from '../src/account/linkToken.js';

const ME = '/api/v1/account/me';
const SIGNED_OUT = {
  path: ME,
  status: 401,
  body: { code: 'unauthenticated', message: 'Sign in to continue.', field: null },
};
const GENERIC = 'If that address can be registered, we have sent a message to it.';

beforeEach(() => {
  clearBrowserStorage();
  // A token a previous test captured but never consumed must not leak into this one.
  takeLinkToken();
});

describe('registration', () => {
  it('declares its submitted keys once, with no duplicates', () => {
    // The cross-check against the *backend* allowlist lives in
    // `backend/tests/test_account_registration_form.py`, because that is where both lists
    // can be read: `app.core.account_fields.ALLOWED_FIELD_KEYS` is the authority and it is
    // Python. What this test guards is the list's own shape.
    expect(new Set(SUBMITTED_FIELD_KEYS).size).toBe(SUBMITTED_FIELD_KEYS.length);
    expect(SUBMITTED_FIELD_KEYS).toContain('marketing_consent');
  });

  it('starts with both consent controls unchecked', async () => {
    stubAccountFetch([SIGNED_OUT]);
    renderAccount('/account/register');

    const terms = await screen.findByLabelText(/I accept the Solaris Express terms/);
    const marketing = screen.getByLabelText(/may email me about services/);
    expect(terms).not.toBeChecked();
    expect(marketing).not.toBeChecked();
  });

  it('keeps the terms acknowledgement and the marketing choice separate', async () => {
    const user = userEvent.setup();
    stubAccountFetch([SIGNED_OUT]);
    renderAccount('/account/register');

    const terms = await screen.findByLabelText(/I accept the Solaris Express terms/);
    const marketing = screen.getByLabelText(/may email me about services/);

    await user.click(terms);
    expect(terms).toBeChecked();
    expect(marketing).not.toBeChecked();
  });

  it('refuses to submit without the terms acknowledgement, and says which field', async () => {
    const user = userEvent.setup();
    const { calls } = stubAccountFetch([SIGNED_OUT]);
    renderAccount('/account/register');

    await user.type(await screen.findByLabelText(/^Email address/), 'someone@example.com');
    await user.type(screen.getByLabelText(/^Password/), 'a-long-enough-password');
    await user.type(screen.getByLabelText(/^Confirm password/), 'a-long-enough-password');
    await user.type(screen.getByLabelText(/Full legal name/), 'Someone Real');
    await user.click(screen.getByRole('button', { name: 'Create account' }));

    // Twice: once in the summary at the top of the form and once beside the control.
    // Both are wanted — the summary is what a keyboard user reaches first, the inline
    // message is what somebody scrolling the form sees.
    expect(
      await screen.findAllByText('Accept the terms and the privacy notice to continue.'),
    ).toHaveLength(2);
    expect(requestedUrls(calls).some((url) => url.includes('/register'))).toBe(false);
  });

  it('summarises the problems and moves focus to the summary', async () => {
    const user = userEvent.setup();
    stubAccountFetch([SIGNED_OUT]);
    renderAccount('/account/register');

    await user.click(await screen.findByRole('button', { name: 'Create account' }));

    const summary = await screen.findByRole('alert');
    expect(summary).toHaveTextContent(/problems with this form/);
    expect(summary).toHaveFocus();
  });

  it('sends only allowlisted keys, with the marketing answer stated either way', async () => {
    const user = userEvent.setup();
    const { calls } = stubAccountFetch([
      SIGNED_OUT,
      { path: '/api/v1/account/register', method: 'POST', body: { message: GENERIC } },
    ]);
    renderAccount('/account/register');

    await user.type(await screen.findByLabelText(/^Email address/), 'someone@example.com');
    await user.type(screen.getByLabelText(/^Password/), 'a-long-enough-password');
    await user.type(screen.getByLabelText(/^Confirm password/), 'a-long-enough-password');
    await user.type(screen.getByLabelText(/Full legal name/), 'Someone Real');
    await user.click(screen.getByLabelText(/I accept the Solaris Express terms/));
    await fillRegistrationAddress(user);
    await user.click(screen.getByRole('button', { name: 'Create account' }));

    await waitFor(() => {
      expect(calls.some((call) => call.url.includes('/register'))).toBe(true);
    });
    const body = JSON.parse(calls.find((call) => call.url.includes('/register')).init.body);
    expect(body.accept_terms).toBe(true);
    expect(body.accept_privacy).toBe(true);
    expect(body.customer.marketing_consent).toBe('false');
    expect(body.customer.preferred_language).toBe('en');

    // Nothing is sent that the form did not declare. The declared list is checked against
    // the backend allowlist by `backend/tests/test_account_registration_form.py`.
    Object.keys(body.customer).forEach((key) => {
      expect(SUBMITTED_FIELD_KEYS).toContain(key);
    });
  });

  it('carries the same idempotency key across a retry', async () => {
    const user = userEvent.setup();
    const { calls } = stubAccountFetch([
      SIGNED_OUT,
      {
        path: '/api/v1/account/register',
        method: 'POST',
        status: 500,
        body: { code: 'error', message: 'Something went wrong.', field: null },
      },
    ]);
    renderAccount('/account/register');

    await user.type(await screen.findByLabelText(/^Email address/), 'someone@example.com');
    await user.type(screen.getByLabelText(/^Password/), 'a-long-enough-password');
    await user.type(screen.getByLabelText(/^Confirm password/), 'a-long-enough-password');
    await user.type(screen.getByLabelText(/Full legal name/), 'Someone Real');
    await user.click(screen.getByLabelText(/I accept the Solaris Express terms/));
    await fillRegistrationAddress(user);

    await user.click(screen.getByRole('button', { name: 'Create account' }));
    await screen.findAllByText('Something went wrong.');
    await user.click(screen.getByRole('button', { name: 'Create account' }));

    const attempts = calls.filter((call) => call.url.includes('/register'));
    expect(attempts).toHaveLength(2);
    const keys = attempts.map((call) => JSON.parse(call.init.body).idempotency_key);
    expect(keys[0]).toBe(keys[1]);
  });

  it('shows the generic confirmation and does not sign the person in', async () => {
    const user = userEvent.setup();
    const { calls } = stubAccountFetch([
      SIGNED_OUT,
      { path: '/api/v1/account/register', method: 'POST', body: { message: GENERIC } },
    ]);
    renderAccount('/account/register');

    await user.type(await screen.findByLabelText(/^Email address/), 'someone@example.com');
    await user.type(screen.getByLabelText(/^Password/), 'a-long-enough-password');
    await user.type(screen.getByLabelText(/^Confirm password/), 'a-long-enough-password');
    await user.type(screen.getByLabelText(/Full legal name/), 'Someone Real');
    await user.click(screen.getByLabelText(/I accept the Solaris Express terms/));
    await fillRegistrationAddress(user);
    await user.click(screen.getByRole('button', { name: 'Create account' }));

    await screen.findByRole('heading', { name: 'Check your email', level: 1 });
    // No sign-in call, and therefore no session that would imply approval.
    expect(requestedUrls(calls).some((url) => url.includes('/sign-in'))).toBe(false);
    // Nothing about a match, a duplicate, or a canonical customer.
    expect(document.body.textContent).not.toMatch(/already (registered|exists)|duplicate|STCA-/i);
  });

  it('sends a rate-limited registration to the same confirmation, with no "too many"', async () => {
    const user = userEvent.setup();
    stubAccountFetch([
      SIGNED_OUT,
      {
        path: '/api/v1/account/register',
        method: 'POST',
        status: 429,
        headers: { 'Retry-After': '1800' },
        body: { code: 'rate_limited', message: GENERIC, field: null },
      },
    ]);
    renderAccount('/account/register');

    await user.type(await screen.findByLabelText(/^Email address/), 'someone@example.com');
    await user.type(screen.getByLabelText(/^Password/), 'a-long-enough-password');
    await user.type(screen.getByLabelText(/^Confirm password/), 'a-long-enough-password');
    await user.type(screen.getByLabelText(/Full legal name/), 'Someone Real');
    await user.click(screen.getByLabelText(/I accept the Solaris Express terms/));
    await fillRegistrationAddress(user);
    await user.click(screen.getByRole('button', { name: 'Create account' }));

    // UAT round 3: the same page an accepted registration reaches, word for word.
    await screen.findByRole('heading', { name: 'Check your email', level: 1 });
    expect(document.body.textContent).not.toMatch(/too many|wait a moment|try again in/i);
  });

  it('says plainly that staff approval is required before shipment access', async () => {
    stubAccountFetch([SIGNED_OUT]);
    renderAccount('/account/register');
    expect(
      await screen.findByText(/A member of staff reviews every application\./),
    ).toBeInTheDocument();
  });

  it('handles the production registration gate without exposing configuration', async () => {
    const user = userEvent.setup();
    stubAccountFetch([
      SIGNED_OUT,
      {
        path: '/api/v1/account/register',
        method: 'POST',
        status: 503,
        body: {
          code: 'account_unavailable',
          message: 'Customer accounts are not available yet. Please contact Solaris Express.',
          field: null,
        },
      },
    ]);
    renderAccount('/account/register');

    await user.type(await screen.findByLabelText(/^Email address/), 'someone@example.com');
    await user.type(screen.getByLabelText(/^Password/), 'a-long-enough-password');
    await user.type(screen.getByLabelText(/^Confirm password/), 'a-long-enough-password');
    await user.type(screen.getByLabelText(/Full legal name/), 'Someone Real');
    await user.click(screen.getByLabelText(/I accept the Solaris Express terms/));
    await fillRegistrationAddress(user);
    await user.click(screen.getByRole('button', { name: 'Create account' }));

    await screen.findByRole('heading', { name: 'Accounts are not open yet', level: 1 });
    // Nothing about the transport, the provider, the terms version, or any setting name.
    expect(document.body.textContent).not.toMatch(
      /ACCOUNT_EMAIL_TRANSPORT|provider|SMTP|PLACEHOLDER|terms_version|capture/i,
    );
  });
});

describe('verification', () => {
  it('removes the token from the URL before redeeming it', async () => {
    const { calls } = stubAccountFetch([
      SIGNED_OUT,
      {
        path: '/api/v1/account/verify-email',
        method: 'POST',
        body: { message: 'Email confirmed. Your account is waiting for review.' },
      },
    ]);

    renderAccount('/account/verify-email?token=SECRET-VERIFICATION-TOKEN');
    await screen.findByRole('heading', { name: 'Email confirmed', level: 1 });

    expect(window.location.search).toBe('');
    expect(window.location.href).not.toContain('SECRET-VERIFICATION-TOKEN');
    // The token went in the body, where it belongs, and never in a URL we built.
    requestedUrls(calls).forEach((url) => {
      expect(url).not.toContain('SECRET-VERIFICATION-TOKEN');
    });
    const post = calls.find((call) => call.url.includes('/verify-email'));
    expect(JSON.parse(post.init.body).token).toBe('SECRET-VERIFICATION-TOKEN');
  });

  it('redeems a fragment token and leaves no trace of it in the address bar', async () => {
    const { calls } = stubAccountFetch([
      SIGNED_OUT,
      { path: '/api/v1/account/verify-email', method: 'POST', body: { message: 'Email confirmed.' } },
    ]);

    window.history.pushState({}, '', '/account/verify-email#token=FRAGMENT-VERIFY-TOKEN');
    captureLinkToken();
    expect(window.location.hash).toBe('');

    renderAccount('/account/verify-email');
    await screen.findByRole('heading', { name: 'Email confirmed', level: 1 });

    const post = calls.find((call) => call.url.includes('/verify-email'));
    expect(JSON.parse(post.init.body).token).toBe('FRAGMENT-VERIFY-TOKEN');
    expect(window.location.href).not.toContain('FRAGMENT-VERIFY-TOKEN');
    expect(document.body.innerHTML).not.toContain('FRAGMENT-VERIFY-TOKEN');
  });

  it('never renders the token', async () => {
    stubAccountFetch([
      SIGNED_OUT,
      { path: '/api/v1/account/verify-email', method: 'POST', body: { message: 'Email confirmed.' } },
    ]);

    renderAccount('/account/verify-email?token=SECRET-VERIFICATION-TOKEN');
    await screen.findByRole('heading', { name: 'Email confirmed', level: 1 });
    expect(document.body.innerHTML).not.toContain('SECRET-VERIFICATION-TOKEN');
  });

  it('says that confirming is not approval', async () => {
    stubAccountFetch([
      SIGNED_OUT,
      { path: '/api/v1/account/verify-email', method: 'POST', body: { message: 'Email confirmed.' } },
    ]);

    renderAccount('/account/verify-email?token=T');
    await screen.findByRole('heading', { name: 'Email confirmed', level: 1 });
    expect(screen.getByText(/This is not approval/)).toBeInTheDocument();
  });

  it('gives one safe state for every bad token, and offers a resend', async () => {
    stubAccountFetch([
      SIGNED_OUT,
      {
        path: '/api/v1/account/verify-email',
        method: 'POST',
        status: 422,
        body: {
          code: 'validation_error',
          message: 'That link is no longer valid. Request a new one.',
          field: 'token',
        },
      },
    ]);

    renderAccount('/account/verify-email?token=CONSUMED');
    await screen.findByRole('heading', { name: 'That link did not work', level: 1 });
    expect(
      screen.getByText('That link is no longer valid. Request a new one.'),
    ).toBeInTheDocument();
    expect(
      screen.getByRole('link', { name: 'Send the confirmation email again' }),
    ).toBeInTheDocument();
  });

  it('treats an absent token as the same failure', async () => {
    stubAccountFetch([SIGNED_OUT]);
    renderAccount('/account/verify-email');
    await screen.findByRole('heading', { name: 'That link did not work', level: 1 });
  });
});

describe('password reset', () => {
  it('strips the token from the URL on arrival and still redeems it on submit', async () => {
    const user = userEvent.setup();
    const { calls } = stubAccountFetch([
      SIGNED_OUT,
      {
        path: '/api/v1/account/password/reset',
        method: 'POST',
        body: { message: 'Password updated. Sign in with your new password.' },
      },
    ]);

    renderAccount('/account/reset-password?token=SECRET-RESET-TOKEN');
    await screen.findByRole('heading', { name: 'Choose a new password', level: 1 });
    expect(window.location.search).toBe('');

    await user.type(screen.getByLabelText('New password'), 'a-long-enough-password');
    await user.type(screen.getByLabelText(/New password again/), 'a-long-enough-password');
    await user.click(screen.getByRole('button', { name: 'Change password' }));

    await screen.findByRole('heading', { name: 'Password updated', level: 1 });
    const post = calls.find((call) => call.url.includes('/password/reset'));
    expect(JSON.parse(post.init.body).token).toBe('SECRET-RESET-TOKEN');
    expect(document.body.innerHTML).not.toContain('SECRET-RESET-TOKEN');
  });

  it('takes a fragment token out of the address bar before React mounts and redeems it', async () => {
    // CA-SEC-07: the link the backend now sends is `/account/reset-password#token=…`.
    // `main.jsx` runs `captureLinkToken()` before rendering; this mirrors that order.
    const user = userEvent.setup();
    const { calls } = stubAccountFetch([
      SIGNED_OUT,
      {
        path: '/api/v1/account/password/reset',
        method: 'POST',
        body: { message: 'Password updated. Sign in with your new password.' },
      },
    ]);

    window.history.pushState({}, '', '/account/reset-password#token=FRAGMENT-RESET-TOKEN');
    const depth = window.history.length;
    captureLinkToken();
    // Gone before a single component rendered, and replaced in place.
    expect(window.location.hash).toBe('');
    expect(window.location.href).not.toContain('FRAGMENT-RESET-TOKEN');
    expect(window.history.length).toBe(depth);

    renderAccount('/account/reset-password');
    await screen.findByRole('heading', { name: 'Choose a new password', level: 1 });

    await user.type(screen.getByLabelText('New password'), 'a-long-enough-password');
    await user.type(screen.getByLabelText(/New password again/), 'a-long-enough-password');
    await user.click(screen.getByRole('button', { name: 'Change password' }));

    await screen.findByRole('heading', { name: 'Password updated', level: 1 });
    const post = calls.find((call) => call.url.includes('/password/reset'));
    expect(JSON.parse(post.init.body).token).toBe('FRAGMENT-RESET-TOKEN');
    expect(document.body.innerHTML).not.toContain('FRAGMENT-RESET-TOKEN');
    // No request this page made carried the token in its URL.
    expect(calls.some((call) => call.url.includes('FRAGMENT-RESET-TOKEN'))).toBe(false);
  });

  it('still strips a fragment token the router sees, when the entry module did not run', async () => {
    stubAccountFetch([SIGNED_OUT]);
    renderAccount('/account/reset-password#token=LATE-FRAGMENT');
    await screen.findByRole('heading', { name: 'Choose a new password', level: 1 });
    await waitFor(() => expect(window.location.hash).toBe(''));
    expect(document.body.innerHTML).not.toContain('LATE-FRAGMENT');
  });

  it('says every session was revoked and does not sign the person in', async () => {
    const user = userEvent.setup();
    const { calls } = stubAccountFetch([
      SIGNED_OUT,
      {
        path: '/api/v1/account/password/reset',
        method: 'POST',
        body: { message: 'Password updated.' },
      },
    ]);

    renderAccount('/account/reset-password?token=T');
    await user.type(await screen.findByLabelText('New password'), 'a-long-enough-password');
    await user.type(screen.getByLabelText(/New password again/), 'a-long-enough-password');
    await user.click(screen.getByRole('button', { name: 'Change password' }));

    await screen.findByRole('heading', { name: 'Password updated', level: 1 });
    expect(screen.getByText(/has been signed out/)).toBeInTheDocument();
    expect(requestedUrls(calls).some((url) => url.includes('/sign-in'))).toBe(false);
  });

  it('refuses two different passwords before making a request', async () => {
    const user = userEvent.setup();
    const { calls } = stubAccountFetch([SIGNED_OUT]);

    renderAccount('/account/reset-password?token=T');
    await user.type(await screen.findByLabelText('New password'), 'a-long-enough-password');
    await user.type(screen.getByLabelText(/New password again/), 'a-different-password');
    await user.click(screen.getByRole('button', { name: 'Change password' }));

    expect(await screen.findByText('The two passwords do not match.')).toBeInTheDocument();
    expect(requestedUrls(calls).some((url) => url.includes('/password/reset'))).toBe(false);
  });
});

describe('the authentication shell', () => {
  it('renders no protected content before authorization resolves', async () => {
    let resolveMe;
    const pending = new Promise((resolve) => {
      resolveMe = resolve;
    });
    stubAccountFetch([
      { path: ME, body: async () => pending },
      { path: '/api/v1/account/shipments', body: listPageFixture() },
    ]);

    renderAccount('/account/shipments');

    // While `/account/me` is in flight the guard shows a status and nothing else. This is
    // the "no flash of protected content" assertion, and it is checked *before* the
    // session resolves rather than after, which is the only moment it could fail.
    expect(await screen.findByText('Checking your account')).toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: 'My shipments' })).toBeNull();
    expect(document.body.textContent).not.toContain('SX-');

    resolveMe(meFixture());
    await screen.findByRole('heading', { name: 'My shipments', level: 1 });
  });

  it('sends a signed-out visitor to sign in, and back to the deep link afterwards', async () => {
    const user = userEvent.setup();
    stubAccountFetch([
      SIGNED_OUT,
      {
        path: '/api/v1/account/sign-in',
        method: 'POST',
        body: {
          account_reference: 'CA-7K9D2M4R',
          status: 'active',
          email_verified: true,
          csrf_token: 'a-csrf-value',
        },
      },
      { path: '/api/v1/account/shipments', body: listPageFixture() },
    ]);

    renderAccount('/account/shipments');
    await screen.findByRole('heading', { name: 'Sign in', level: 1 });

    // The session read is re-stubbed as signed in for the post-sign-in refetch.
    stubAccountFetch([
      { path: ME, body: meFixture() },
      {
        path: '/api/v1/account/sign-in',
        method: 'POST',
        body: {
          account_reference: 'CA-7K9D2M4R',
          status: 'active',
          email_verified: true,
          csrf_token: 'a-csrf-value',
        },
      },
      { path: '/api/v1/account/shipments', body: listPageFixture() },
    ]);

    await user.type(screen.getByLabelText(/Email address/), 'someone@example.com');
    await user.type(screen.getByLabelText(/Password/), 'a-long-enough-password');
    await user.click(screen.getByRole('button', { name: 'Sign in' }));

    await screen.findByRole('heading', { name: 'My shipments', level: 1 });
  });

  it('shows one failure message for every sign-in refusal', async () => {
    const user = userEvent.setup();
    stubAccountFetch([
      SIGNED_OUT,
      {
        path: '/api/v1/account/sign-in',
        method: 'POST',
        status: 401,
        body: {
          code: 'authentication_failed',
          message: 'Email or password is incorrect.',
          field: null,
        },
      },
    ]);

    renderAccount('/account/sign-in');
    await user.type(await screen.findByLabelText(/Email address/), 'someone@example.com');
    await user.type(screen.getByLabelText(/Password/), 'wrong-password-here');
    await user.click(screen.getByRole('button', { name: 'Sign in' }));

    expect(await screen.findByText('Email or password is incorrect.')).toBeInTheDocument();
    // Nothing that separates one refusal from another.
    expect(document.body.textContent).not.toMatch(
      /unverified|not confirmed|suspended|rejected|deactivated|locked/i,
    );
  });

  it('shows the pending state and no shipment data', async () => {
    stubAccountFetch([
      {
        path: ME,
        body: meFixture({
          status: 'pending_approval',
          linked: false,
          shipment_history_available: false,
        }),
      },
    ]);

    renderAccount('/account/pending');
    await screen.findByRole('heading', { name: 'Your account is being reviewed', level: 1 });
    expect(screen.getByText('CA-7K9D2M4R')).toBeInTheDocument();
    expect(document.body.textContent).not.toContain('SX-');
    // The card reads as a state, not as a failure: nothing is in the error tone.
    expect(screen.queryByText('Problem')).toBeNull();
  });

  it('redirects a pending account away from the shipment list', async () => {
    stubAccountFetch([
      {
        path: ME,
        body: meFixture({
          status: 'pending_approval',
          linked: false,
          shipment_history_available: false,
        }),
      },
    ]);

    renderAccount('/account/shipments');
    await screen.findByRole('heading', { name: 'Your account is being reviewed', level: 1 });
    await waitFor(() => expect(window.location.pathname).toBe('/account/pending'));
  });

  it('redirects an active-but-unlinked account to the same pending card', async () => {
    stubAccountFetch([
      {
        path: ME,
        body: meFixture({ status: 'active', linked: false, shipment_history_available: false }),
      },
    ]);

    renderAccount('/account/shipments');
    await screen.findByRole('heading', { name: 'Your account is being reviewed', level: 1 });
  });

  it('gives a rejected account no reason', async () => {
    stubAccountFetch([
      {
        path: ME,
        body: meFixture({
          status: 'rejected',
          linked: false,
          shipment_history_available: false,
          status_reason_code: 'duplicate_application',
        }),
      },
    ]);

    renderAccount('/account/rejected');
    await screen.findByRole('heading', { name: 'We cannot set up this account', level: 1 });
    // The code is on the session object and must not reach the page.
    expect(document.body.textContent).not.toMatch(/duplicate_application|duplicate/i);
  });

  it('gives suspended and deactivated the same page', async () => {
    stubAccountFetch([
      { path: ME, body: meFixture({ status: 'suspended', shipment_history_available: false }) },
    ]);
    renderAccount('/account/unavailable');
    await screen.findByRole('heading', { name: 'This account is not available', level: 1 });
    expect(document.body.textContent).not.toMatch(/suspend|deactivat/i);
  });

  it('signs out, and the navigation goes with it', async () => {
    const user = userEvent.setup();
    stubAccountFetch([
      { path: ME, body: meFixture() },
      { path: '/api/v1/account/shipments', body: listPageFixture() },
      { path: '/api/v1/account/sign-out', method: 'POST', body: { message: 'Signed out.' } },
    ]);

    renderAccount('/account/shipments');
    await screen.findByRole('heading', { name: 'My shipments', level: 1 });

    // After sign-out the session read answers 401.
    stubAccountFetch([
      SIGNED_OUT,
      { path: '/api/v1/account/sign-out', method: 'POST', body: { message: 'Signed out.' } },
    ]);
    await user.click(screen.getByRole('button', { name: 'Sign out' }));

    await waitFor(() => {
      expect(screen.queryByRole('link', { name: 'My shipments' })).toBeNull();
    });
  });

  it('says so when the account cannot be read, rather than bouncing to sign in', async () => {
    stubAccountFetch([
      { path: ME, status: 500, body: { code: 'error', message: 'Server error.', field: null } },
    ]);

    renderAccount('/account/shipments');
    await screen.findByRole('heading', { name: 'We could not load your account', level: 1 });
  });

  it('keeps a mistyped account URL inside the Customer Account shell', async () => {
    stubAccountFetch([SIGNED_OUT]);
    renderAccount('/account/does-not-exist');
    await screen.findByRole('heading', { name: 'Page not found', level: 1 });
    // The staff not-found page would be inside the staff shell, which has this nav.
    expect(screen.queryByRole('link', { name: 'Dashboard' })).toBeNull();
  });
});
