/**
 * UAT round 5 (findings on RC-UAT-8, and the owner's decisions of 2026-10-15):
 *
 * * the Add customer dialog lists every problem in an error summary whose entries focus
 *   their field, maps the server's request-validation 422 to its fields in plain words,
 *   and never falls back to "Something went wrong" for a field problem;
 * * registration flags a malformed email in its summary, with the server's sentence;
 * * Audit access shows a suppression's evidence reference;
 * * reloading a decided application does not retry its 409;
 * * Operations is not offered "Suppressed" in the consent form;
 * * the resend-verification 429 goes to the same confirmation as an accepted request.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { ApiError } from '../src/api/client.js';
import { shouldRetryQuery } from '../src/api/retry.js';
import { SessionProvider } from '../src/app/SessionContext.jsx';
import { CustomerAccountReviewPage } from '../src/features/customer_accounts/CustomerAccountReviewPage.jsx';
import { CustomerFormDrawer } from '../src/features/customers/CustomerFormDrawer.jsx';
import { ConsentTab } from '../src/features/customers/tabs/ConsentTab.jsx';
import { SettingsPage } from '../src/features/settings/SettingsPage.jsx';
import { I18nProvider } from '../src/i18n/index.jsx';
import { INVALID_EMAIL_MESSAGE, isValidEmail } from '../src/shared/email.js';
import { renderWithProviders, stubFetch } from './utils.jsx';
import { clearBrowserStorage, renderAccount, stubAccountFetch } from './accountUtils.jsx';

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

afterEach(() => {
  vi.unstubAllGlobals();
});

/* --- 1. The Add customer dialog ------------------------------------------------------ */

function renderCustomerForm(createResponse) {
  const fetchMock = stubFetch([
    { path: '/staff/assignable', body: [] },
    {
      path: '/customers/duplicate-check',
      method: 'POST',
      body: { candidates: [], guidance: '' },
    },
    { path: '/customers', method: 'POST', ...createResponse },
  ]);
  renderWithProviders(<CustomerFormDrawer open onClose={vi.fn()} />);
  return fetchMock;
}

const creates = (fetchMock) =>
  fetchMock.mock.calls.filter(
    ([url, init]) => String(url).endsWith('/customers') && init?.method === 'POST',
  );

describe('Add customer › error summary', () => {
  it('lists a bad email and a negative estimate, links each to its field, and sends nothing', async () => {
    const user = userEvent.setup();
    const fetchMock = renderCustomerForm({ status: 201, body: {} });

    await user.type(screen.getByLabelText(/Full name/), 'Trần Văn Bình');
    await user.type(screen.getByLabelText(/Email address/), 'bad');
    await user.type(screen.getByLabelText(/Estimated monthly shipments/), '-3');
    await user.click(screen.getByRole('button', { name: 'Add customer' }));

    const summary = await screen.findByRole('alert', { name: /There are 2 problems/ });
    await waitFor(() => expect(summary).toHaveFocus());
    expect(creates(fetchMock)).toHaveLength(0);

    const email = within(summary).getByRole('link', { name: INVALID_EMAIL_MESSAGE });
    expect(email).toHaveAttribute('href', '#customer-field-email');
    await user.click(email);
    expect(screen.getByLabelText(/Email address/)).toHaveFocus();
    expect(screen.getByLabelText(/Email address/)).toHaveAttribute('aria-invalid', 'true');

    await user.click(
      within(summary).getByRole('link', {
        name: 'Enter estimated monthly shipments as a whole number, 0 or more.',
      }),
    );
    expect(screen.getByLabelText(/Estimated monthly shipments/)).toHaveFocus();
  });

  it("maps the server's request-validation 422 to its field in the form's own words", async () => {
    const user = userEvent.setup();
    renderCustomerForm({
      status: 422,
      body: {
        detail: [
          {
            type: 'greater_than_equal',
            loc: ['body', 'estimated_monthly_shipments'],
            msg: 'Input should be greater than or equal to 0',
            input: -1,
          },
        ],
      },
    });

    await user.type(screen.getByLabelText(/Full name/), 'Trần Văn Bình');
    await user.type(screen.getByLabelText(/Phone number/), '+1 416 555 0101');
    await user.type(screen.getByLabelText(/Estimated monthly shipments/), '4');
    await user.click(screen.getByRole('button', { name: 'Add customer' }));

    const summary = await screen.findByRole('alert', { name: /There is 1 problem/ });
    expect(
      within(summary).getByRole('link', {
        name: 'Enter estimated monthly shipments as a whole number, 0 or more.',
      }),
    ).toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(/Something went wrong/);
    expect(document.body.textContent).not.toMatch(/Input should be/);
  });

  it('puts a server field error in the summary and beside the field', async () => {
    const user = userEvent.setup();
    renderCustomerForm({
      status: 422,
      body: {
        code: 'validation_error',
        message: INVALID_EMAIL_MESSAGE,
        field: 'email',
        detail: {},
      },
    });

    // A shape the browser accepts and the server still refuses.
    await user.type(screen.getByLabelText(/Full name/), 'Trần Văn Bình');
    await user.type(screen.getByLabelText(/Email address/), 'binh@example.com');
    await user.click(screen.getByRole('button', { name: 'Add customer' }));

    const summary = await screen.findByRole('alert', { name: /There is 1 problem/ });
    expect(within(summary).getByRole('link', { name: INVALID_EMAIL_MESSAGE })).toBeInTheDocument();
    expect(screen.getAllByText(INVALID_EMAIL_MESSAGE)).toHaveLength(2);

    // Editing the field withdraws its error.
    await user.type(screen.getByLabelText(/Email address/), 'x');
    await waitFor(() => expect(screen.queryByText(INVALID_EMAIL_MESSAGE)).toBeNull());
  }, 15_000);
});

/* --- 2. Registration flags a malformed email ------------------------------------------ */

describe('Registration › malformed email', () => {
  beforeEach(() => clearBrowserStorage());

  it('is in the error summary, linked to the field, before anything is sent', async () => {
    const user = userEvent.setup();
    const { calls } = stubAccountFetch([
      {
        path: '/api/v1/account/me',
        status: 401,
        body: { code: 'unauthenticated', message: 'Sign in to continue.', field: null },
      },
    ]);
    renderAccount('/account/register');

    await user.type(await screen.findByLabelText(/^Email address/), 'bad');
    await user.click(screen.getByRole('button', { name: 'Create account' }));

    const summary = await screen.findByRole('alert');
    const link = within(summary).getByRole('link', { name: INVALID_EMAIL_MESSAGE });
    await user.click(link);
    expect(screen.getByLabelText(/^Email address/)).toHaveFocus();
    expect(calls.some((call) => call.url.includes('/register'))).toBe(false);
  });
});

describe('isValidEmail', () => {
  it('agrees with the server on the cases UAT and the probe used', () => {
    ['bad', 'a@b', 'name@localhost', 'a..b@example.com', '.a@example.com', 'a b@example.com', 'a@-x.com', 'a@example.123', ''].forEach(
      (value) => expect(isValidEmail(value), value).toBe(false),
    );
    ['name@example.com', 'a.b@sub.example.co', "o'brien+tag@example.com", 'người@ví-dụ.vn', 'x@xn--p1ai.com', 'a@example.c'].forEach(
      (value) => expect(isValidEmail(value), value).toBe(true),
    );
  });
});

/* --- 4. Audit access shows the evidence reference -------------------------------------- */

describe('Settings › Audit access › suppression evidence', () => {
  it('shows the reference the suppression was recorded against', async () => {
    const user = userEvent.setup();
    stubFetch([
      session('admin', ['settings:read', 'audit:read']),
      { path: '/settings', body: { lifecycle_definitions: {} } },
      {
        path: '/audit',
        body: {
          items: [
            {
              id: 9,
              occurred_at: '2026-10-15T14:00:00Z',
              actor_label: 'marketing@demo.example.com',
              action: 'suppression.add',
              entity_type: 'customer',
              entity_id: 'STCA-000012',
              summary: 'Suppressed the email address of STCA-000012',
              detail_json: null,
              reason_code: null,
              changed_fields: [],
              admin_override: false,
              evidence_reference: 'TICKET-5120',
            },
          ],
          total: 1,
          limit: 50,
          offset: 0,
        },
      },
    ]);
    renderWithProviders(
      <SessionProvider>
        <SettingsPage />
      </SessionProvider>,
    );
    await screen.findByRole('heading', { name: 'Settings' });
    await user.click(screen.getByRole('tab', { name: 'Audit access' }));
    const table = await screen.findByRole('table', { name: 'Audit access' });
    const [, row] = within(table).getAllByRole('row');
    expect(within(row).getByText('Evidence reference')).toBeInTheDocument();
    expect(within(row).getByText('TICKET-5120')).toBeInTheDocument();
  });
});

/* --- 5. A decided application's 409 is final ------------------------------------------ */

describe('Review › reloading a decided application', () => {
  it('treats 409 as final in the retry rule', () => {
    const conflict = new ApiError({ status: 409, code: 'conflict', message: 'decided' });
    expect(shouldRetryQuery(0, conflict)).toBe(false);
    [401, 403, 404, 422].forEach((status) =>
      expect(shouldRetryQuery(0, new ApiError({ status, message: 'x' }))).toBe(false),
    );
    expect(shouldRetryQuery(0, new ApiError({ status: 503, message: 'x' }))).toBe(true);
    expect(shouldRetryQuery(2, new ApiError({ status: 503, message: 'x' }))).toBe(false);
  });

  it('asks once and shows the decided page, with the application retry rule', async () => {
    const fetchMock = stubFetch([
      session('operations', ['customer_account:review', 'customer_account:approve']),
      {
        path: '/customer-account/registrations/CA-7K9D2M4R',
        status: 409,
        body: {
          code: 'conflict',
          message: 'This registration has already been decided: it is active.',
          field: null,
          detail: null,
        },
      },
      {
        path: '/customer-account/identities/CA-7K9D2M4R',
        body: {
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
          can_deactivate: false,
        },
      },
    ]);
    // The application's own client, not the tests' retry-free one: the point is the rule.
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: shouldRetryQuery, gcTime: 0 } },
    });
    render(
      <QueryClientProvider client={queryClient}>
        <I18nProvider>
          <MemoryRouter
            initialEntries={['/customer-accounts/CA-7K9D2M4R']}
            future={{ v7_relativeSplatPath: true }}
          >
            <SessionProvider>
              <Routes>
                <Route
                  path="/customer-accounts/:accountReference"
                  element={<CustomerAccountReviewPage />}
                />
              </Routes>
            </SessionProvider>
          </MemoryRouter>
        </I18nProvider>
      </QueryClientProvider>,
    );

    expect(
      await screen.findByText('This application has already been decided', {}, { timeout: 900 }),
    ).toBeInTheDocument();
    const registrationReads = fetchMock.mock.calls.filter(([url]) =>
      String(url).endsWith('/customer-account/registrations/CA-7K9D2M4R'),
    );
    expect(registrationReads).toHaveLength(1);
  });
});

/* --- 6a. Operations is not offered "Suppressed" ---------------------------------------- */

const CONSENT = {
  states: [],
  history: [],
  do_not_contact: false,
  note: 'Operational messages are separate from promotional consent.',
};

async function consentStatusOptions(role, permissions) {
  const user = userEvent.setup();
  stubFetch([session(role, permissions), { path: '/customers/1/consent', body: CONSENT }]);
  renderWithProviders(
    <SessionProvider>
      <ConsentTab customer={{ id: 1, public_id: 'STCA-000001' }} />
    </SessionProvider>,
  );
  await user.click(await screen.findByRole('button', { name: 'Record consent change' }));
  const dialog = await screen.findByRole('dialog');
  const select = within(dialog).getByLabelText('Status');
  return within(select)
    .getAllByRole('option')
    .map((option) => option.textContent);
}

describe('Consent › who may suppress (owner decision, 2026-10-15)', () => {
  it('does not offer "Suppressed" to Operations', async () => {
    const options = await consentStatusOptions('operations', ['consent:read', 'consent:write']);
    expect(options).toEqual(['Unknown', 'Consented', 'Withdrawn']);
  });

  it('still offers it to Marketing', async () => {
    const options = await consentStatusOptions('marketing', [
      'consent:read',
      'consent:write',
      'suppression:add',
    ]);
    expect(options).toContain('Suppressed');
  });
});

/* --- 6c. The resend 429 ----------------------------------------------------------------- */

describe('Resend verification › rate limited', () => {
  beforeEach(() => clearBrowserStorage());

  it('goes to the same confirmation as an accepted request, with no "too many"', async () => {
    const user = userEvent.setup();
    stubAccountFetch([
      {
        path: '/api/v1/account/me',
        status: 401,
        body: { code: 'unauthenticated', message: 'Sign in to continue.', field: null },
      },
      {
        path: '/api/v1/account/verification/resend',
        method: 'POST',
        status: 429,
        headers: { 'Retry-After': '45' },
        body: {
          code: 'rate_limited',
          message: 'If that address can be registered, we have sent a message to it.',
          field: null,
        },
      },
    ]);
    renderAccount('/account/verification/resend');

    await user.type(await screen.findByLabelText(/Email address/), 'someone@example.com');
    await user.click(screen.getByRole('button', { name: 'Send it again' }));

    await screen.findByRole('heading', { name: 'Check your email', level: 1 });
    expect(document.body.textContent).not.toMatch(/too many/i);
  });
});
