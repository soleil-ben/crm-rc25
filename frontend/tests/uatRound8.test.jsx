/**
 * UAT round 8 (the owner's real-phone feedback of 2026-10-17, and the staff-side gaps):
 *
 * 1. registration asks for the shipping (pickup) address first and billing second;
 * 2. "Billing address is the same as shipping address" ticks itself once a shipping street
 *    is typed, hides and omits the billing fields while ticked, and unticking shows empty
 *    billing fields;
 * 3. the password is typed twice at registration and at reset, and a mismatch is an inline
 *    error before anything is sent;
 * 4. an approved, applied value is not shown as "Changed since";
 * 5. Audit access shows the old and new value of each field an approved change request
 *    applied;
 * 6. the consent history names the customer's own account, not "system".
 *
 * The server half of each is `backend/tests/test_uat_round_8.py`.
 */

import { afterEach, describe, expect, it, vi } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Route, Routes } from 'react-router-dom';
import { SessionProvider } from '../src/app/SessionContext.jsx';
import { ProfileChangeReviewPage } from '../src/features/customer_accounts/ProfileChangeReviewPage.jsx';
import { ConsentTab } from '../src/features/customers/tabs/ConsentTab.jsx';
import { SettingsPage } from '../src/features/settings/SettingsPage.jsx';
import { renderWithProviders, stubFetch } from './utils.jsx';
import { renderAccount, requestedUrls, stubAccountFetch } from './accountUtils.jsx';

const SIGNED_OUT = {
  path: '/api/v1/account/me',
  status: 401,
  body: { code: 'unauthenticated', message: 'Sign in to continue.', field: null },
};
const GENERIC = 'If that address can be registered, we have sent a message to it.';
const PASSWORD = 'a-long-enough-password';
// Reworded in UAT round 9, which also made the address and an unticked billing address
// required; the cases below fill them.
const SAME_LABEL = 'Billing address is the same as the address above';

afterEach(() => {
  vi.unstubAllGlobals();
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

/* --- 1 to 3. Registration ------------------------------------------------------------- */

function renderRegister() {
  const stub = stubAccountFetch([
    SIGNED_OUT,
    { path: '/api/v1/account/register', method: 'POST', body: { message: GENERIC } },
  ]);
  renderAccount('/account/register');
  return stub;
}

async function fillAddressRest(user) {
  await user.type(within(shippingGroup()).getByLabelText(/^City/), 'Mississauga');
  await user.type(within(shippingGroup()).getByLabelText(/^Province or state/), 'ON');
  await user.type(within(shippingGroup()).getByLabelText(/^Postal code/), 'L4W 1V2');
}

async function fillRequired(user, { confirmation = PASSWORD, address = true } = {}) {
  await user.type(await screen.findByLabelText(/^Email address/), 'someone@example.com');
  await user.type(screen.getByLabelText('Password'), PASSWORD);
  if (confirmation) {
    await user.type(screen.getByLabelText('Confirm password'), confirmation);
  }
  await user.type(screen.getByLabelText(/Full legal name/), 'Someone Real');
  await user.click(screen.getByLabelText(/I accept the Solaris Express terms/));
  if (address) {
    await user.type(within(shippingGroup()).getByLabelText(/^Address line 1/), '4120 Dixie Road');
    await fillAddressRest(user);
  }
}

const shippingGroup = () => screen.getByRole('group', { name: 'Address' });
const billingGroup = () => screen.getByRole('group', { name: 'Billing address' });
const registerBody = (calls) =>
  JSON.parse(calls.find((call) => call.url.includes('/register')).init.body);

describe('Registration › address order and billing', () => {
  it('asks for the shipping address before the billing address', async () => {
    renderRegister();
    await screen.findByRole('heading', { name: 'Create an account', level: 1 });
    const shipping = shippingGroup();
    const billing = billingGroup();
    // DOCUMENT_POSITION_FOLLOWING: billing comes after shipping in the page.
    expect(shipping.compareDocumentPosition(billing) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it('the box is ticked (since round 11, from the start), hides billing and sends none', async () => {
    const user = userEvent.setup();
    const { calls } = renderRegister();
    await fillRequired(user, { address: false });

    // Round 8 ticked it once a street was typed; round 11 starts it ticked (DEC-0158).
    expect(screen.getByLabelText(SAME_LABEL)).toBeChecked();
    expect(within(billingGroup()).queryByLabelText(/Address line 1/)).not.toBeInTheDocument();

    await user.type(within(shippingGroup()).getByLabelText(/Address line 1/), '4120 Dixie Road');
    await fillAddressRest(user);
    expect(screen.getByLabelText(SAME_LABEL)).toBeChecked();
    expect(within(billingGroup()).queryByLabelText(/Address line 1/)).not.toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Create account' }));
    await screen.findByRole('heading', { name: 'Check your email', level: 1 });
    const body = registerBody(calls);
    expect(body.billing_same_as_shipping).toBe(true);
    expect(body.customer['pickup_address.1.address_line1']).toBe('4120 Dixie Road');
    expect(Object.keys(body.customer).some((key) => key.startsWith('billing_address.'))).toBe(false);
  });

  it('unticking shows empty billing fields, which are then required and sent', async () => {
    const user = userEvent.setup();
    const { calls } = renderRegister();
    await fillRequired(user);

    await user.click(screen.getByLabelText(SAME_LABEL));
    expect(screen.getByLabelText(SAME_LABEL)).not.toBeChecked();
    const billingLine1 = within(billingGroup()).getByLabelText('Address line 1');
    expect(billingLine1).toHaveValue('');

    // Unticked with an address and no billing street: refused inline, nothing sent.
    await user.click(screen.getByRole('button', { name: 'Create account' }));
    expect(
      (await screen.findAllByText('Enter the billing street address (address line 1).')).length,
    ).toBeGreaterThan(0);
    expect(requestedUrls(calls).some((url) => url.includes('/register'))).toBe(false);

    // A Vietnamese address: since UAT round 12 a Canadian code is shape-checked (DEC-0165).
    await user.selectOptions(within(billingGroup()).getByLabelText('Country'), 'VN');
    await user.type(billingLine1, '125 Nguyen Hue');
    await user.type(within(billingGroup()).getByLabelText(/^City/), 'Ho Chi Minh City');
    await user.type(within(billingGroup()).getByLabelText(/^Province or state/), 'HCM');
    await user.type(within(billingGroup()).getByLabelText(/^Postal code/), '700000');
    await user.click(screen.getByRole('button', { name: 'Create account' }));
    await screen.findByRole('heading', { name: 'Check your email', level: 1 });
    const body = registerBody(calls);
    expect(body.billing_same_as_shipping).toBe(false);
    expect(body.customer['billing_address.address_line1']).toBe('125 Nguyen Hue');
    expect(body.customer['pickup_address.1.address_line1']).toBe('4120 Dixie Road');
  });

  it('ticking the box with no shipping address is refused inline', async () => {
    const user = userEvent.setup();
    const { calls } = renderRegister();
    await fillRequired(user, { address: false });
    await user.click(screen.getByLabelText(SAME_LABEL));
    await user.click(screen.getByRole('button', { name: 'Create account' }));
    // Since UAT round 9 the address's own parts are refused, beside each field.
    expect(
      (await screen.findAllByText('Enter the street address (address line 1).')).length,
    ).toBeGreaterThan(0);
    expect(requestedUrls(calls).some((url) => url.includes('/register'))).toBe(false);
  });
});

describe('Registration › confirm password', () => {
  it('blocks a mismatch with an inline error beside the second box', async () => {
    const user = userEvent.setup();
    const { calls } = renderRegister();
    await fillRequired(user, { confirmation: 'a-different-password' });
    await user.click(screen.getByRole('button', { name: 'Create account' }));

    const confirm = screen.getByLabelText('Confirm password');
    await waitFor(() => expect(confirm).toHaveAttribute('aria-invalid', 'true'));
    expect(confirm).toHaveAccessibleDescription(/The two passwords do not match\./);
    expect(requestedUrls(calls).some((url) => url.includes('/register'))).toBe(false);
  });

  it('blocks an empty confirmation, and sends the confirmation once it matches', async () => {
    const user = userEvent.setup();
    const { calls } = renderRegister();
    await fillRequired(user, { confirmation: '' });
    await user.click(screen.getByRole('button', { name: 'Create account' }));
    const confirm = screen.getByLabelText('Confirm password');
    await waitFor(() =>
      expect(confirm).toHaveAccessibleDescription(/Type the password again to confirm it\./),
    );

    await user.type(confirm, PASSWORD);
    await user.click(screen.getByRole('button', { name: 'Create account' }));
    await screen.findByRole('heading', { name: 'Check your email', level: 1 });
    expect(registerBody(calls).password_confirmation).toBe(PASSWORD);
  });

  it('shows a server refusal of the confirmation beside the field', async () => {
    const user = userEvent.setup();
    stubAccountFetch([
      SIGNED_OUT,
      {
        path: '/api/v1/account/register',
        method: 'POST',
        status: 422,
        body: {
          code: 'validation_error',
          message: 'The two passwords do not match.',
          field: 'password_confirmation',
        },
      },
    ]);
    renderAccount('/account/register');
    await fillRequired(user);
    await user.click(screen.getByRole('button', { name: 'Create account' }));
    const confirm = screen.getByLabelText('Confirm password');
    await waitFor(() =>
      expect(confirm).toHaveAccessibleDescription(/The two passwords do not match\./),
    );
  });
});

describe('Reset password › confirm password', () => {
  it('shows a mismatch beside the second box and sends nothing', async () => {
    const user = userEvent.setup();
    const { calls } = stubAccountFetch([SIGNED_OUT]);
    renderAccount('/account/reset-password?token=T');
    await user.type(await screen.findByLabelText('New password'), PASSWORD);
    await user.type(screen.getByLabelText('New password again'), 'something-else-entirely');
    await user.click(screen.getByRole('button', { name: 'Change password' }));

    const again = screen.getByLabelText('New password again');
    await waitFor(() => expect(again).toHaveAttribute('aria-invalid', 'true'));
    expect(again).toHaveAccessibleDescription(/The two passwords do not match\./);
    expect(requestedUrls(calls).some((url) => url.includes('/password/reset'))).toBe(false);
  });

  it('sends the confirmation with the new password', async () => {
    const user = userEvent.setup();
    const { calls } = stubAccountFetch([
      SIGNED_OUT,
      { path: '/api/v1/account/password/reset', method: 'POST', body: { message: 'Password updated.' } },
    ]);
    renderAccount('/account/reset-password?token=T');
    await user.type(await screen.findByLabelText('New password'), PASSWORD);
    await user.type(screen.getByLabelText('New password again'), PASSWORD);
    await user.click(screen.getByRole('button', { name: 'Change password' }));
    await screen.findByRole('heading', { name: 'Password updated', level: 1 });
    const post = calls.find((call) => call.url.includes('/password/reset'));
    expect(JSON.parse(post.init.body).password_confirmation).toBe(PASSWORD);
  });
});

/* --- 4. Approved values are not drift ------------------------------------------------- */

const REVIEW_URL = '/customer-account/identities/CA-7K9D2M4R/profile-proposal';

function approvedReview(fields) {
  return {
    account_reference: 'CA-7K9D2M4R',
    customer_public_id: 'STCA-000012',
    status: 'approved',
    submitted_at: '2026-10-17T05:19:00',
    reviewed_at: '2026-10-17T06:00:00',
    decision_reason_code: null,
    groups: ['display_name'],
    fields,
    decline_reason_codes: ['could_not_verify'],
  };
}

function renderReview(review) {
  stubFetch([
    session('operations', ['customer_account:review', 'customer_account:approve']),
    { path: REVIEW_URL, body: review },
  ]);
  renderWithProviders(
    <SessionProvider>
      <Routes>
        <Route path="/customer-accounts/:accountReference/profile-change" element={<ProfileChangeReviewPage />} />
      </Routes>
    </SessionProvider>,
    { route: '/customer-accounts/CA-7K9D2M4R/profile-change' },
  );
}

const displayRow = (overrides) => ({
  field_key: 'display_name',
  group: 'display_name',
  proposed_value: 'Chị Hạnh',
  proposed_value_normalized: 'chị hạnh',
  current_value_at_submission: 'Hạnh',
  current_value_now: 'Chị Hạnh',
  drifted: false,
  applied: true,
  ...overrides,
});

describe('Profile change review › after approval', () => {
  it('shows an applied value without "Changed since"', async () => {
    renderReview(approvedReview([displayRow()]));
    expect(await screen.findByText('Applied')).toBeInTheDocument();
    expect(screen.queryByText('Changed since')).not.toBeInTheDocument();
  });

  it('still flags a later change by someone else', async () => {
    renderReview(
      approvedReview([displayRow({ current_value_now: 'Edited by staff', drifted: true })]),
    );
    expect(await screen.findByText('Changed since')).toBeInTheDocument();
  });
});

/* --- 5. Audit access shows old and new values ----------------------------------------- */

function auditRow(overrides) {
  return {
    id: 21,
    occurred_at: '2026-10-17T14:00:00Z',
    actor_label: 'ops@demo.example.com',
    action: 'customer.update',
    entity_type: 'customer',
    entity_id: 'STCA-000012',
    summary: 'Updated customer STCA-000012 from an approved change request',
    detail_json: null,
    reason_code: null,
    changed_fields: ['display_name', 'phone'],
    admin_override: false,
    evidence_reference: null,
    changes: [
      { field: 'display_name', old: 'Hạnh', new: 'Chị Hạnh' },
      { field: 'phone', old: null, new: '416 555 0199' },
    ],
    ...overrides,
  };
}

async function auditTable(items) {
  const user = userEvent.setup();
  stubFetch([
    session('admin', ['settings:read', 'audit:read']),
    { path: '/settings', body: { lifecycle_definitions: {} } },
    { path: '/audit', body: { items, total: items.length, limit: 50, offset: 0 } },
  ]);
  renderWithProviders(
    <SessionProvider>
      <SettingsPage />
    </SessionProvider>,
  );
  await screen.findByRole('heading', { name: 'Settings' });
  await user.click(screen.getByRole('tab', { name: 'Audit access' }));
  return screen.findByRole('table', { name: 'Audit access' });
}

describe('Settings › Audit access › an approved change request', () => {
  it('lists each field with its old and new value', async () => {
    const table = await auditTable([auditRow()]);
    const [, row] = within(table).getAllByRole('row');
    expect(within(row).getByText('Changes')).toBeInTheDocument();
    expect(within(row).getByText('display_name: Hạnh → Chị Hạnh')).toBeInTheDocument();
    expect(within(row).getByText('phone: (blank) → 416 555 0199')).toBeInTheDocument();
    expect(within(row).getByText('display_name, phone')).toBeInTheDocument();
  });

  it('shows no Changes entry on a row without values', async () => {
    const table = await auditTable([auditRow({ changes: [], changed_fields: ['city'] })]);
    const [, row] = within(table).getAllByRole('row');
    expect(within(row).queryByText('Changes')).not.toBeInTheDocument();
    expect(within(row).getByText('city')).toBeInTheDocument();
  });

  it('shows the customer account as the actor of a customer event', async () => {
    const table = await auditTable([
      auditRow({
        action: 'customer_account.marketing_choice',
        actor_label: 'customer_account:CA-7K9D2M4R',
        summary: 'Customer recorded marketing consent: withdrawn',
        changes: [],
        changed_fields: [],
      }),
    ]);
    const [, row] = within(table).getAllByRole('row');
    expect(within(row).getByText('customer_account:CA-7K9D2M4R')).toBeInTheDocument();
    expect(within(row).queryByText('system')).not.toBeInTheDocument();
  });
});

/* --- 6. The consent history names the customer's account ------------------------------ */

function consentEvent(overrides) {
  return {
    id: 5,
    channel: 'email',
    address_value: 'hanh@demo.example.com',
    status: 'withdrawn',
    basis: 'not_recorded',
    obtained_at: null,
    withdrawn_at: '2026-10-17T14:00:00Z',
    expires_at: null,
    source: 'customer_account',
    evidence_reference: 'customer_account:CA-7K9D2M4R',
    note: null,
    recorded_at: '2026-10-17T14:00:00Z',
    recorded_by: null,
    recorded_by_account: 'customer_account:CA-7K9D2M4R',
    ...overrides,
  };
}

async function consentHistory(history) {
  stubFetch([
    session('admin', ['customer:read', 'consent:write']),
    {
      path: '/customers/1/consent',
      body: { states: [], history, do_not_contact: false, note: '' },
    },
  ]);
  renderWithProviders(
    <SessionProvider>
      <ConsentTab customer={{ id: 1, public_id: 'STCA-000001' }} />
    </SessionProvider>,
  );
  return screen.findByRole('table', { name: 'Consent history' });
}

describe('Consent history › who recorded it', () => {
  it('names the customer account for a withdrawal made in the portal', async () => {
    const table = await consentHistory([consentEvent()]);
    const [, row] = within(table).getAllByRole('row');
    const by = within(row).getAllByText('customer_account:CA-7K9D2M4R');
    // Once as the evidence reference, once in the By column.
    expect(by).toHaveLength(2);
    expect(within(row).queryByText('System')).not.toBeInTheDocument();
  });

  it('names a staff member, and the system only when there is neither', async () => {
    const table = await consentHistory([
      consentEvent({
        id: 6,
        source: 'phone_call',
        evidence_reference: 'TICKET-1',
        recorded_by: { id: 2, full_name: 'Ops Person' },
        recorded_by_account: null,
      }),
      consentEvent({ id: 7, source: 'import', evidence_reference: null, recorded_by_account: null }),
    ]);
    const [, staffRow, systemRow] = within(table).getAllByRole('row');
    expect(within(staffRow).getByText('Ops Person')).toBeInTheDocument();
    expect(within(systemRow).getByText('System')).toBeInTheDocument();
  });
});
