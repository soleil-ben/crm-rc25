/**
 * UAT round 4 (findings on RC-UAT-7):
 *
 * * the audit access screen marks an Admin override (CA-APR-05);
 * * an import whose every possible duplicate is skipped can be finished;
 * * Marketing and Admin can suppress an address from the Consent tab, with evidence and a
 *   reason; a role without `suppression:add` sees no such control;
 * * the registration error summary links to each field; a cancelled booking's empty
 *   timeline does not invite a milestone; the decision forms are gone once decided;
 *   saving internal notes says so;
 * * Admin alone is offered deactivation, behind a reason and a confirmation; the
 *   forgot-password 429 goes to the same confirmation as an accepted request.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Route, Routes } from 'react-router-dom';
import { SessionProvider } from '../src/app/SessionContext.jsx';
import { CustomerAccountReviewPage } from '../src/features/customer_accounts/CustomerAccountReviewPage.jsx';
import { ConsentTab } from '../src/features/customers/tabs/ConsentTab.jsx';
import { CustomerImportPage } from '../src/features/imports/CustomerImportPage.jsx';
import { SettingsPage } from '../src/features/settings/SettingsPage.jsx';
import { NotesTab, TrackingTab } from '../src/features/shipments/shipmentTabs.jsx';
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

/* --- 1. Audit access marks an Admin override ---------------------------------------- */

describe('Settings › Audit access › Admin override (CA-APR-05)', () => {
  it('shows the marker on an Admin decision and not on an Operations one', async () => {
    const user = userEvent.setup();
    const row = (id, actor, override) => ({
      id,
      occurred_at: '2026-10-15T14:00:00Z',
      actor_label: actor,
      action: 'customer_account.approve',
      entity_type: 'customer_identity',
      entity_id: `CA-00000${id}`,
      summary: `Customer Account CA-00000${id} approved`,
      detail_json: null,
      reason_code: 'no_duplicate_candidate',
      changed_fields: [],
      admin_override: override,
    });
    stubFetch([
      session('admin', ['settings:read', 'audit:read']),
      { path: '/settings', body: { lifecycle_definitions: {} } },
      {
        path: '/audit',
        body: {
          items: [row(2, 'admin@demo.example.com', true), row(1, 'ops@demo.example.com', false)],
          total: 2,
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
    const [, adminRow, opsRow] = within(table).getAllByRole('row');
    expect(within(adminRow).getAllByText('Admin override').length).toBeGreaterThan(0);
    expect(within(opsRow).queryByText('Admin override')).toBeNull();
  });
});

/* --- 2. An all-skip import can be finished ------------------------------------------ */

const IMPORT_PERMISSIONS = ['import:template', 'import:preview', 'import:commit', 'customer:read'];

const ALL_DUPLICATES_PREVIEW = {
  content_sha256: 'all-skip-digest',
  file_name: 'customers.csv',
  row_count: 1,
  headers: ['full_name', 'email'],
  raw_headers: ['full_name', 'email'],
  unmapped_headers: [],
  counts: { new: 0, exact_match: 0, duplicate_review: 1, rejected: 0 },
  notes: ['Nothing has been imported. This is a preview.'],
  rows: [
    {
      row_number: 2,
      classification: 'duplicate_review',
      values: { full_name: 'Nguyễn Thị Bích Hạnh', email: 'hanh@example.com', phone: null },
      issues: [],
      matched_customer_id: null,
      matched_customer_public_id: null,
      duplicate_candidates: [
        {
          customer_id: 7,
          public_id: 'STCA-000007',
          full_name: 'Nguyễn Thị Bích Hạnh',
          city: 'Toronto',
          country_code: 'CA',
          matched_on: ['email', 'name'],
          confidence: 85,
        },
      ],
      source_record_id: 'row:bbb',
      default_action: 'skipped',
    },
  ],
};

describe('Import › every duplicate skipped', () => {
  it('can be finished, creating nobody, once every row is decided', async () => {
    const user = userEvent.setup();
    const fetchMock = stubFetch([
      session('admin', IMPORT_PERMISSIONS),
      {
        path: '/imports/customers/fields',
        body: { fields: [], template_headers: [], conflict_policies: ['skip'], limits: {}, notes: [] },
      },
      { path: '/imports/batches', body: { items: [], total: 0, limit: 5, offset: 0 } },
      { path: '/imports/customers/preview', method: 'POST', body: ALL_DUPLICATES_PREVIEW },
      {
        path: '/imports/customers/commit',
        method: 'POST',
        body: {
          batch_public_id: 'IMP-000002',
          created: 0,
          matched: 0,
          skipped: 1,
          rejected: 0,
          row_count: 1,
          conflict_policy: 'skip',
          rows: [
            {
              row_number: 2,
              outcome: 'skipped',
              reason_code: 'duplicate_skipped',
              customer_id: null,
              customer_public_id: null,
            },
          ],
        },
      },
    ]);
    const { container } = renderWithProviders(
      <SessionProvider>
        <CustomerImportPage />
      </SessionProvider>,
      { route: '/customers/import' },
    );
    await screen.findByLabelText('CSV file to import');
    await user.upload(
      container.querySelector('input[type="file"]'),
      new File(['full_name,email\r\nA,a@example.com\r\n'], 'customers.csv', { type: 'text/csv' }),
    );

    const finish = await screen.findByRole('button', { name: 'Finish import (no new customers)' });
    expect(finish).toBeDisabled();
    await user.selectOptions(screen.getByLabelText('Decision 2'), 'skip');
    expect(finish).toBeEnabled();

    await user.click(finish);
    const dialog = await screen.findByRole('dialog');
    expect(within(dialog).getByText(/No customer record will be created/)).toBeInTheDocument();
    await user.click(within(dialog).getByRole('button', { name: 'Yes, import now' }));

    expect(await screen.findByText('Import finished')).toBeInTheDocument();
    const commit = fetchMock.mock.calls.find(([url]) => String(url).includes('/commit'));
    expect(commit).toBeTruthy();
  });
});

/* --- 3. Suppress an address from the Consent tab ------------------------------------ */

const CONSENT = {
  states: [
    {
      channel: 'email',
      address_value: 'lan@example.com',
      status: 'consented',
      basis: 'express',
      obtained_at: null,
      withdrawn_at: null,
      expires_at: null,
      recorded_at: '2026-10-01T10:00:00Z',
      source: null,
      is_suppressed: false,
      suppression_reason: null,
      is_marketing_eligible: true,
    },
  ],
  history: [],
  do_not_contact: false,
  note: 'Operational messages are separate from promotional consent.',
};

function renderConsent(permissions, extra = []) {
  const fetchMock = stubFetch([
    session('marketing', permissions),
    ...extra,
    { path: '/customers/1/consent', body: CONSENT },
  ]);
  renderWithProviders(
    <SessionProvider>
      <ConsentTab customer={{ id: 1, public_id: 'STCA-000001' }} />
    </SessionProvider>,
  );
  return fetchMock;
}

describe('Consent › Suppress address', () => {
  it('needs an evidence reference and a reason, then sends both', async () => {
    const user = userEvent.setup();
    const suppressed = {
      ...CONSENT,
      states: [
        {
          ...CONSENT.states[0],
          is_suppressed: true,
          suppression_reason: 'Asked by phone',
          is_marketing_eligible: false,
        },
      ],
    };
    const fetchMock = renderConsent(['consent:read', 'consent:write', 'suppression:add'], [
      { path: '/customers/1/consent/suppressions', method: 'POST', body: suppressed },
    ]);

    await user.click(await screen.findByRole('button', { name: 'Suppress address' }));
    const dialog = await screen.findByRole('dialog');
    const submit = within(dialog).getByRole('button', { name: 'Suppress' });
    expect(submit).toBeDisabled();

    await user.type(within(dialog).getByLabelText(/Evidence reference/), 'TICKET-4417');
    expect(submit).toBeDisabled();
    await user.type(within(dialog).getByLabelText(/^Reason/), 'Asked by phone');
    expect(submit).toBeEnabled();
    await user.click(submit);

    await waitFor(() => {
      const call = fetchMock.mock.calls.find(([url]) => String(url).includes('/suppressions'));
      expect(call).toBeTruthy();
      expect(JSON.parse(call[1].body)).toEqual({
        channel: 'email',
        evidence_reference: 'TICKET-4417',
        reason: 'Asked by phone',
      });
    });
    expect(
      await screen.findByText(
        'The address is suppressed and the change is recorded in the audit log.',
      ),
    ).toBeInTheDocument();
  });

  it('is not offered without suppression:add', async () => {
    renderConsent(['consent:read', 'consent:write']);
    await screen.findByRole('button', { name: 'Record consent change' });
    expect(screen.queryByRole('button', { name: 'Suppress address' })).toBeNull();
  });
});

/* --- 4a. The registration error summary links to its fields ------------------------- */

describe('Registration › error summary', () => {
  beforeEach(() => clearBrowserStorage());

  it('links each problem to its field and moves focus there', async () => {
    const user = userEvent.setup();
    stubAccountFetch([
      {
        path: '/api/v1/account/me',
        status: 401,
        body: { code: 'unauthenticated', message: 'Sign in to continue.', field: null },
      },
    ]);
    renderAccount('/account/register');

    await user.click(await screen.findByRole('button', { name: 'Create account' }));
    const summary = await screen.findByRole('alert');

    const emailLink = within(summary).getByRole('link', { name: 'Enter your email address.' });
    expect(emailLink).toHaveAttribute('href', '#ca-field-email');
    await user.click(emailLink);
    expect(screen.getByLabelText(/^Email address/)).toHaveFocus();

    await user.click(
      within(summary).getByRole('link', {
        name: 'Accept the terms and the privacy notice to continue.',
      }),
    );
    expect(screen.getByLabelText(/I accept the Solaris Express terms/)).toHaveFocus();
  });
});

/* --- 4b. A cancelled booking's empty timeline --------------------------------------- */

describe('Tracking › cancelled booking with no events', () => {
  function renderTracking(bookingState) {
    stubFetch([
      session('operations', ['shipment:read', 'tracking:write']),
      { path: '/shipments/10/events', body: [] },
    ]);
    renderWithProviders(
      <SessionProvider>
        <TrackingTab
          shipment={{ id: 10, booking_state: bookingState, public_id: 'SX-CAV-1' }}
          packages={[]}
          legs={[]}
          onPrint={() => {}}
        />
      </SessionProvider>,
    );
  }

  it('does not invite a manual milestone', async () => {
    renderTracking('cancelled');
    expect(await screen.findByText('No operational events recorded yet.')).toBeInTheDocument();
    expect(screen.queryByText('Record a manual milestone to start the timeline.')).toBeNull();
  });

  it('still does on a live booking', async () => {
    renderTracking('confirmed');
    expect(
      await screen.findByText('Record a manual milestone to start the timeline.'),
    ).toBeInTheDocument();
  });
});

/* --- 4c. Internal notes confirm the save --------------------------------------------- */

describe('Shipment › Internal notes', () => {
  it('says the notes were saved and re-reads the audit list', async () => {
    const user = userEvent.setup();
    const shipment = { id: 10, internal_notes: null };
    const fetchMock = stubFetch([
      session('admin', ['shipment:read', 'shipment:write', 'audit:read']),
      {
        path: '/shipments/10',
        method: 'PATCH',
        body: (init) => ({ ...shipment, internal_notes: JSON.parse(init.body).internal_notes }),
      },
      { path: '/shipments/10', body: shipment },
      { path: '/audit', body: { items: [], total: 0, limit: 50, offset: 0 } },
    ]);
    renderWithProviders(
      <SessionProvider>
        <NotesTab shipment={shipment} />
      </SessionProvider>,
    );
    const save = await screen.findByRole('button', { name: 'Save' });
    await waitFor(() => {
      expect(fetchMock.mock.calls.some(([url]) => String(url).includes('/audit'))).toBe(true);
    });
    const auditReads = () =>
      fetchMock.mock.calls.filter(([url]) => String(url).includes('/audit')).length;
    const before = auditReads();

    await user.type(screen.getByRole('textbox', { name: 'Internal notes' }), 'Shelf B2');
    await user.click(save);

    expect(
      await screen.findByText('Internal notes saved. The change is recorded in the audit log.'),
    ).toBeInTheDocument();
    await waitFor(() => expect(auditReads()).toBeGreaterThan(before));
  });
});

/* --- 4d and 5a. The review screen ---------------------------------------------------- */

const REVIEW = 'customer_account:review';
const APPROVE = 'customer_account:approve';
const DEACTIVATE = 'customer_account:deactivate';
const REGISTRATION = '/customer-account/registrations/CA-7K9D2M4R';
const IDENTITY = '/customer-account/identities/CA-7K9D2M4R';

function identity(overrides = {}) {
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
    ...overrides,
  };
}

const PREVIEW = {
  account_reference: 'CA-7K9D2M4R',
  action: 'create_new',
  proposal_id: 41,
  proposed: { legal_name: 'Nguyễn Thị Bích Hạnh' },
  current: null,
  differences: [],
  duplicate_classification: 'none',
  candidate_references: [],
  target_customer_public_id: null,
  disclosure: {
    shipment_count: 0,
    oldest_booked_at: null,
    newest_booked_at: null,
    includes_cancelled: false,
    includes_rebooked: false,
    definition_version: 'v1',
  },
  fingerprint: 'fingerprint-one',
  mapping_refusal: null,
};

const PENDING_REGISTRATION = {
  account_reference: 'CA-7K9D2M4R',
  status: 'pending_approval',
  submitted_at: '2026-09-20T09:00:00',
  email_verified_at: '2026-09-20T09:05:00',
  account_email_entered: 'Hanh.Nguyen@example.com',
  account_email_normalized: 'hanh.nguyen@example.com',
  has_active_link: false,
  fields: [{ field_key: 'legal_name', proposed_value: 'Nguyễn Thị Bích Hạnh', proposed_value_normalized: 'Nguyễn Thị Bích Hạnh' }],
};

function renderReviewPage(routes) {
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

describe('Review › once decided', () => {
  it('hides the approval and decline forms below the outcome', async () => {
    const user = userEvent.setup();
    renderReviewPage([
      session('operations', [REVIEW, APPROVE]),
      {
        path: `${REGISTRATION}/disclosure-acknowledgement`,
        method: 'POST',
        body: {
          account_reference: 'CA-7K9D2M4R',
          action: 'create_new',
          target_customer_public_id: null,
          disclosure: PREVIEW.disclosure,
          fingerprint: 'fingerprint-one',
          acknowledged_at: '2026-09-21T12:00:00',
        },
      },
      {
        path: `${REGISTRATION}/approve/create-new`,
        method: 'POST',
        body: {
          account_reference: 'CA-7K9D2M4R',
          status: 'active',
          customer_public_id: 'STCA-000900',
          outcome: 'approved_created',
          replayed: false,
        },
      },
      {
        path: `${REGISTRATION}/duplicate-candidates`,
        body: { duplicate_classification: 'none', candidates: [] },
      },
      { path: `${REGISTRATION}/preview`, body: PREVIEW },
      { path: REGISTRATION, body: PENDING_REGISTRATION },
      { path: IDENTITY, body: identity({ status: 'pending_approval', can_deactivate: true }) },
    ]);

    await user.click(await screen.findByLabelText(/I have read the figures above/));
    const approve = screen.getByRole('button', { name: 'Approve and create the customer' });
    await waitFor(() => expect(approve).toBeEnabled());
    expect(screen.getByText('Decline this application')).toBeInTheDocument();
    await user.click(approve);

    expect(await screen.findByText('The decision has been recorded.')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Approve and create the customer' })).toBeNull();
    expect(screen.queryByText('Decline this application')).toBeNull();
    expect(screen.queryByRole('button', { name: 'Decline the application' })).toBeNull();
  });
});

describe('Review › deactivation (DEC-0126)', () => {
  const decided = (permissions, account = identity()) => [
    session('admin', permissions),
    {
      path: REGISTRATION,
      status: 409,
      body: {
        code: 'conflict',
        message: 'This registration has already been decided: it is active.',
        field: null,
        detail: null,
      },
    },
    { path: IDENTITY, body: account },
  ];

  it('is offered to Admin behind a reason and a confirmation', async () => {
    const user = userEvent.setup();
    const fetchMock = renderReviewPage([
      {
        path: `${IDENTITY}/deactivate`,
        method: 'POST',
        body: identity({
          status: 'deactivated',
          deactivated_at: '2026-10-15T10:00:00',
          status_reason_code: 'privacy_request',
          can_suspend: false,
          can_deactivate: false,
        }),
      },
      ...decided([REVIEW, APPROVE, DEACTIVATE]),
    ]);

    await screen.findByText('Deactivate this account');
    const action = screen.getByRole('button', { name: 'Deactivate account' });
    expect(action).toBeDisabled();
    await user.selectOptions(screen.getByLabelText('Grounds for deactivating'), 'privacy_request');
    await user.click(action);

    const dialog = await screen.findByRole('dialog');
    expect(fetchMock.mock.calls.some(([url]) => String(url).includes('/deactivate'))).toBe(false);
    await user.click(within(dialog).getByRole('button', { name: 'Yes, deactivate' }));

    await waitFor(() => {
      const call = fetchMock.mock.calls.find(([url]) => String(url).includes('/deactivate'));
      expect(call).toBeTruthy();
      expect(JSON.parse(call[1].body)).toEqual({ reason_code: 'privacy_request' });
    });
    expect(
      await screen.findByText('The account has been deactivated and signed out everywhere.'),
    ).toBeInTheDocument();
    expect(screen.getByText('Privacy request')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Deactivate account' })).toBeNull();
  });

  it('is not offered to Operations', async () => {
    renderReviewPage(decided([REVIEW, APPROVE]));
    await screen.findByText('Account status');
    expect(screen.getByRole('button', { name: 'Suspend account' })).toBeInTheDocument();
    expect(screen.queryByText('Deactivate this account')).toBeNull();
    expect(screen.queryByRole('button', { name: 'Deactivate account' })).toBeNull();
  });
});

/* --- 5b. The forgot-password 429 ----------------------------------------------------- */

describe('Forgot password › rate limited', () => {
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
        path: '/api/v1/account/password/forgot',
        method: 'POST',
        status: 429,
        headers: { 'Retry-After': '45' },
        body: {
          code: 'rate_limited',
          message: 'If that address has an account, we have sent a message to it.',
          field: null,
        },
      },
    ]);
    renderAccount('/account/forgot-password');

    await user.type(await screen.findByLabelText(/Email address/), 'someone@example.com');
    await user.click(screen.getByRole('button', { name: 'Send the reset link' }));

    await screen.findByRole('heading', { name: 'Check your email', level: 1 });
    expect(document.body.textContent).not.toMatch(/too many/i);
  });
});
