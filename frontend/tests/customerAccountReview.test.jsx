/**
 * The Staff Portal's Customer Account approval screens.
 *
 * Three groups of assertion:
 *
 * * **the order** — no approve control until a preview has been taken and acknowledged,
 *   and a stale fingerprint withdraws the acknowledgement rather than being worked around;
 * * **the preview's contents** — the six things OD-29 and OD-28 require it to state
 *   visibly, each checked by name rather than by "the preview renders";
 * * **what is absent** — no credential, no session, no captured mail, no shipment
 *   reference, no money, planted as sentinels in the responses.
 */

import { describe, expect, it, beforeEach, vi } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders, stubFetch } from './utils.jsx';
import { SessionProvider } from '../src/app/SessionContext.jsx';
import { CustomerAccountQueuePage } from '../src/features/customer_accounts/CustomerAccountQueuePage.jsx';
import { CustomerAccountReviewPage } from '../src/features/customer_accounts/CustomerAccountReviewPage.jsx';
import { Route, Routes } from 'react-router-dom';

const REVIEW = 'customer_account:review';
const APPROVE = 'customer_account:approve';

function session(permissions) {
  return {
    path: '/auth/me',
    body: {
      user: { id: 1, full_name: 'Ops Person', email: 'ops@demo.example.com', role: 'operations' },
      permissions,
      environment: 'test',
      is_demo_environment: false,
    },
  };
}

function queuePage(overrides = {}) {
  return {
    items: [
      {
        account_reference: 'CA-7K9D2M4R',
        status: 'pending_approval',
        submitted_at: '2026-09-18T10:00:00',
        email_verified_at: '2026-09-18T10:05:00',
        proposal_id: 12,
        field_count: 9,
      },
    ],
    total: 1,
    limit: 25,
    offset: 0,
    ...overrides,
  };
}

function registration(overrides = {}) {
  return {
    account_reference: 'CA-7K9D2M4R',
    status: 'pending_approval',
    account_email_entered: 'Hanh.Nguyen@example.com',
    account_email_normalized: 'hanh.nguyen@example.com',
    email_verified_at: '2026-09-18T10:05:00',
    preferred_language: 'en',
    submitted_at: '2026-09-18T10:00:00',
    proposal_id: 12,
    proposal_status: 'pending',
    fields: [
      {
        field_key: 'legal_name',
        value_type: 'string',
        proposed_value: 'Hanh Nguyen',
        proposed_value_normalized: 'hanh nguyen',
        applied: false,
      },
    ],
    has_active_link: false,
    ...overrides,
  };
}

function duplicates(overrides = {}) {
  return {
    account_reference: 'CA-7K9D2M4R',
    duplicate_classification: 'none',
    candidates: [],
    ...overrides,
  };
}

function preview(overrides = {}) {
  return {
    account_reference: 'CA-7K9D2M4R',
    action: 'create_new',
    proposal_id: 12,
    proposed: { legal_name: 'Hanh Nguyen' },
    current: null,
    differences: [],
    duplicate_classification: 'none',
    candidate_references: [],
    target_customer_public_id: null,
    disclosure: {
      shipment_count: 7,
      oldest_booked_at: '2025-02-03T00:00:00',
      newest_booked_at: '2026-09-01T00:00:00',
      includes_cancelled: true,
      includes_rebooked: false,
      definition_version: 'od29-v1',
    },
    fingerprint: 'fingerprint-one',
    mapping_refusal: null,
    ...overrides,
  };
}

function renderReview(routes) {
  stubFetch(routes);
  return renderWithProviders(
    <SessionProvider>
      <Routes>
        <Route path="/customer-accounts/:accountReference" element={<CustomerAccountReviewPage />} />
      </Routes>
    </SessionProvider>,
    { route: '/customer-accounts/CA-7K9D2M4R' },
  );
}

function identity(overrides = {}) {
  return {
    account_reference: 'CA-7K9D2M4R',
    status: 'pending_approval',
    status_reason_code: null,
    account_email_entered: 'Hanh.Nguyen@example.com',
    email_verified: true,
    approved_at: null,
    suspended_at: null,
    linked_customer_public_id: null,
    can_suspend: true,
    can_reinstate: false,
    ...overrides,
  };
}

const IDENTITY = '/customer-account/identities/CA-7K9D2M4R';

const BASE = (permissions = [REVIEW, APPROVE]) => [
  session(permissions),
  { path: '/customer-account/registrations/CA-7K9D2M4R/duplicate-candidates', body: duplicates() },
  { path: '/customer-account/registrations/CA-7K9D2M4R/preview', body: preview() },
  { path: '/customer-account/registrations/CA-7K9D2M4R', body: registration() },
  { path: IDENTITY, body: identity() },
];

beforeEach(() => {
  window.localStorage.clear();
});

describe('the pending queue', () => {
  it('lists an application without any contact detail', async () => {
    stubFetch([session([REVIEW]), { path: '/customer-account/registrations', body: queuePage() }]);
    renderWithProviders(
      <SessionProvider>
        <CustomerAccountQueuePage />
      </SessionProvider>,
      { route: '/customer-accounts' },
    );

    expect(await screen.findByText('CA-7K9D2M4R')).toBeInTheDocument();
    // The row model carries no name, email, phone or address, and the screen must not
    // invent one from anywhere else.
    expect(document.body.textContent).not.toMatch(/@|Nguyen|\+1/);
  });

  it('says so plainly when nothing is waiting', async () => {
    stubFetch([
      session([REVIEW]),
      { path: '/customer-account/registrations', body: queuePage({ items: [], total: 0 }) },
    ]);
    renderWithProviders(
      <SessionProvider>
        <CustomerAccountQueuePage />
      </SessionProvider>,
      { route: '/customer-accounts' },
    );

    expect(await screen.findByText('Nothing waiting for review')).toBeInTheDocument();
  });
});

describe('the approval preview', () => {
  it('states all six things a reviewer has to see before approving', async () => {
    renderReview(BASE());
    await screen.findByText('What this approval discloses');

    const block = screen.getByText('What this approval discloses').closest('.ca-preview');
    // 1. how many historical shipments become visible
    expect(within(block).getByText('7')).toBeInTheDocument();
    // 2 and 3. the oldest and newest dates
    expect(within(block).getByText('Oldest shipment')).toBeInTheDocument();
    expect(within(block).getByText('Newest shipment')).toBeInTheDocument();
    // 4. whether cancelled and rebooked are included, each answered
    const cancelled = within(block).getByText('Includes cancelled shipments').closest('div');
    expect(within(cancelled).getByText('Yes')).toBeInTheDocument();
    const rebooked = within(block).getByText('Includes rebooked shipments').closest('div');
    expect(within(rebooked).getByText('No')).toBeInTheDocument();
    // 5. the intended canonical customer
    expect(
      within(block).getByText('A new customer record will be created'),
    ).toBeInTheDocument();
    // 6. the duplicate classification
    expect(within(block).getByText('No similar customer found')).toBeInTheDocument();
    // and whether proposal data will overwrite an existing customer
    expect(
      within(block).getByText(/a new customer record is created from this application/),
    ).toBeInTheDocument();
  });

  it('says a link-existing approval writes nothing to the customer record', async () => {
    const user = userEvent.setup();
    renderReview([
      ...BASE(),
      {
        path: '/customer-account/registrations/CA-7K9D2M4R/preview',
        body: preview({ action: 'link_existing', target_customer_public_id: 'STCA-000123' }),
      },
    ]);
    await screen.findByText('What this approval discloses');

    await user.selectOptions(
      screen.getByLabelText('What should happen'),
      'link_existing',
    );
    await user.type(screen.getByLabelText('Customer to link to'), 'STCA-000123');

    await waitFor(() => {
      expect(
        screen.getByText(/linking writes nothing to the existing customer record/),
      ).toBeInTheDocument();
    });
  });
});

describe('the acknowledgement gate', () => {
  it('disables approval until the disclosure has been acknowledged', async () => {
    renderReview(BASE());
    await screen.findByText('What this approval discloses');

    const approve = screen.getByRole('button', { name: 'Approve and create the customer' });
    expect(approve).toBeDisabled();
  });

  it('enables approval once the acknowledgement is recorded', async () => {
    const user = userEvent.setup();
    renderReview([
      ...BASE(),
      {
        path: '/customer-account/registrations/CA-7K9D2M4R/disclosure-acknowledgement',
        method: 'POST',
        body: {
          account_reference: 'CA-7K9D2M4R',
          action: 'create_new',
          target_customer_public_id: null,
          disclosure: preview().disclosure,
          fingerprint: 'fingerprint-one',
          acknowledged_at: '2026-09-21T12:00:00',
        },
      },
    ]);
    await screen.findByText('What this approval discloses');

    await user.click(screen.getByLabelText(/I have read the figures above/));

    await waitFor(() => {
      expect(
        screen.getByRole('button', { name: 'Approve and create the customer' }),
      ).toBeEnabled();
    });
  });

  it('trusts the fingerprint the server confirmed, not the one the client sent', async () => {
    const user = userEvent.setup();
    renderReview([
      ...BASE(),
      {
        path: '/customer-account/registrations/CA-7K9D2M4R/disclosure-acknowledgement',
        method: 'POST',
        body: {
          account_reference: 'CA-7K9D2M4R',
          action: 'create_new',
          target_customer_public_id: null,
          disclosure: preview().disclosure,
          fingerprint: 'a-different-fingerprint',
          acknowledged_at: '2026-09-21T12:00:00',
        },
      },
    ]);
    await screen.findByText('What this approval discloses');

    await user.click(screen.getByLabelText(/I have read the figures above/));

    // The server acknowledged a different preview from the one on screen. That is not an
    // acknowledgement of what the reviewer read, so approval stays closed.
    await waitFor(() => {
      expect(
        screen.getByRole('button', { name: 'Approve and create the customer' }),
      ).toBeDisabled();
    });
  });
});

describe('conflicts', () => {
  it('withdraws the acknowledgement and refreshes on a stale preview', async () => {
    const user = userEvent.setup();
    renderReview([
      ...BASE(),
      {
        path: '/customer-account/registrations/CA-7K9D2M4R/disclosure-acknowledgement',
        method: 'POST',
        body: {
          account_reference: 'CA-7K9D2M4R',
          action: 'create_new',
          target_customer_public_id: null,
          disclosure: preview().disclosure,
          fingerprint: 'fingerprint-one',
          acknowledged_at: '2026-09-21T12:00:00',
        },
      },
      {
        path: '/customer-account/registrations/CA-7K9D2M4R/approve/create-new',
        method: 'POST',
        status: 409,
        body: {
          code: 'conflict',
          message:
            'This registration has changed since the preview was taken. Take a new preview, read it, and acknowledge it again.',
        },
      },
    ]);
    await screen.findByText('What this approval discloses');

    await user.click(screen.getByLabelText(/I have read the figures above/));
    await waitFor(() => {
      expect(
        screen.getByRole('button', { name: 'Approve and create the customer' }),
      ).toBeEnabled();
    });

    await user.click(screen.getByRole('button', { name: 'Approve and create the customer' }));

    expect(
      await screen.findByText('Something changed while you were reading'),
    ).toBeInTheDocument();
    // The acknowledgement is gone and approval is closed again. It is not retried with
    // the new fingerprint: the reviewer read different figures.
    expect(screen.getByLabelText(/I have read the figures above/)).not.toBeChecked();
    await waitFor(() => {
      expect(
        screen.getByRole('button', { name: 'Approve and create the customer' }),
      ).toBeDisabled();
    });
  });

  it('withdraws the acknowledgement when the reviewer changes the intended action', async () => {
    const user = userEvent.setup();
    let previewCall = 0;
    stubFetch([
      session([REVIEW, APPROVE]),
      {
        path: '/customer-account/registrations/CA-7K9D2M4R/duplicate-candidates',
        body: duplicates(),
      },
      {
        path: '/customer-account/registrations/CA-7K9D2M4R/preview',
        body: () => {
          previewCall += 1;
          return previewCall === 1
            ? preview()
            : preview({ action: 'link_existing', fingerprint: 'fingerprint-two' });
        },
      },
      { path: '/customer-account/registrations/CA-7K9D2M4R', body: registration() },
      {
        path: '/customer-account/registrations/CA-7K9D2M4R/disclosure-acknowledgement',
        method: 'POST',
        body: {
          account_reference: 'CA-7K9D2M4R',
          action: 'create_new',
          target_customer_public_id: null,
          disclosure: preview().disclosure,
          fingerprint: 'fingerprint-one',
          acknowledged_at: '2026-09-21T12:00:00',
        },
      },
    ]);
    renderWithProviders(
      <SessionProvider>
        <Routes>
          <Route
            path="/customer-accounts/:accountReference"
            element={<CustomerAccountReviewPage />}
          />
        </Routes>
      </SessionProvider>,
      { route: '/customer-accounts/CA-7K9D2M4R' },
    );

    await screen.findByText('What this approval discloses');
    await user.click(screen.getByLabelText(/I have read the figures above/));
    await waitFor(() => {
      expect(
        screen.getByRole('button', { name: 'Approve and create the customer' }),
      ).toBeEnabled();
    });

    await user.selectOptions(screen.getByLabelText('What should happen'), 'link_existing');
    await user.type(screen.getByLabelText('Customer to link to'), 'STCA-000123');

    await waitFor(() => {
      expect(screen.getByLabelText(/I have read the figures above/)).not.toBeChecked();
    });
  });
});

describe('the separate-customer override', () => {
  it('is required when a duplicate candidate exists, and blocks approval until given', async () => {
    const user = userEvent.setup();
    renderReview([
      session([REVIEW, APPROVE]),
      {
        path: '/customer-account/registrations/CA-7K9D2M4R/duplicate-candidates',
        body: duplicates({
          duplicate_classification: 'exact',
          candidates: [
            {
              customer_public_id: 'STCA-000123',
              full_name: 'Hanh Nguyen',
              display_name: null,
              city: 'Toronto',
              country_code: 'CA',
              matched_on: ['email'],
              confidence: 95,
              is_archived: false,
              is_merged: false,
              has_active_identity_link: false,
              linkable: true,
            },
          ],
        }),
      },
      {
        path: '/customer-account/registrations/CA-7K9D2M4R/preview',
        body: preview({ duplicate_classification: 'exact', candidate_references: ['STCA-000123'] }),
      },
      { path: '/customer-account/registrations/CA-7K9D2M4R', body: registration() },
      {
        path: '/customer-account/registrations/CA-7K9D2M4R/disclosure-acknowledgement',
        method: 'POST',
        body: {
          account_reference: 'CA-7K9D2M4R',
          action: 'create_new',
          target_customer_public_id: null,
          disclosure: preview().disclosure,
          fingerprint: 'fingerprint-one',
          acknowledged_at: '2026-09-21T12:00:00',
        },
      },
    ]);

    // Twice: the badge beside the duplicate list, and the preview's own restatement.
    // Both are wanted -- the preview has to state the classification itself, because
    // it is one of the things a reviewer acknowledges.
    await screen.findAllByText('An existing customer matches exactly');
    // The three reads are chained, so the preview arrives after the duplicates do.
    await screen.findByText('What this approval discloses');
    await user.click(screen.getByLabelText(/I have read the figures above/));

    const approve = screen.getByRole('button', { name: 'Approve and create the customer' });
    await waitFor(() => expect(approve).toBeDisabled());

    await user.selectOptions(
      screen.getByLabelText('Why create a separate customer'),
      'different_party',
    );
    await waitFor(() => expect(approve).toBeEnabled());
  });
});

describe('completion', () => {
  it('reports a replayed decision as a replay rather than as a second approval', async () => {
    const user = userEvent.setup();
    renderReview([
      ...BASE(),
      {
        path: '/customer-account/registrations/CA-7K9D2M4R/disclosure-acknowledgement',
        method: 'POST',
        body: {
          account_reference: 'CA-7K9D2M4R',
          action: 'create_new',
          target_customer_public_id: null,
          disclosure: preview().disclosure,
          fingerprint: 'fingerprint-one',
          acknowledged_at: '2026-09-21T12:00:00',
        },
      },
      {
        path: '/customer-account/registrations/CA-7K9D2M4R/approve/create-new',
        method: 'POST',
        body: {
          account_reference: 'CA-7K9D2M4R',
          status: 'active',
          customer_public_id: 'STCA-000900',
          outcome: 'approved_created',
          replayed: true,
        },
      },
    ]);

    await screen.findByText('What this approval discloses');
    await user.click(screen.getByLabelText(/I have read the figures above/));
    await waitFor(() => {
      expect(
        screen.getByRole('button', { name: 'Approve and create the customer' }),
      ).toBeEnabled();
    });
    await user.click(screen.getByRole('button', { name: 'Approve and create the customer' }));

    expect(
      await screen.findByText('This decision had already been recorded. Nothing was written a second time.'),
    ).toBeInTheDocument();
    expect(screen.getByText('STCA-000900')).toBeInTheDocument();
  });

  it('declines with a bounded reason and no free text reaching the applicant', async () => {
    const user = userEvent.setup();
    renderReview([
      ...BASE(),
      {
        path: '/customer-account/registrations/CA-7K9D2M4R/reject',
        method: 'POST',
        body: {
          account_reference: 'CA-7K9D2M4R',
          status: 'rejected',
          customer_public_id: null,
          outcome: 'rejected',
          replayed: false,
        },
      },
    ]);

    await screen.findByText('Decline this application');
    await user.selectOptions(
      screen.getByLabelText('Reason'),
      'duplicate_application',
    );
    await user.click(screen.getByRole('button', { name: 'Decline the application' }));

    // Twice: the outcome banner and the application's own state line, which now agrees.
    expect((await screen.findAllByText('Declined')).length).toBeGreaterThan(0);
  });
});

describe('after a decision, the application stops saying "Waiting for review" (UAT round 3)', () => {
  const REGISTRATION = '/customer-account/registrations/CA-7K9D2M4R';
  const ACK = {
    path: `${REGISTRATION}/disclosure-acknowledgement`,
    method: 'POST',
    body: {
      account_reference: 'CA-7K9D2M4R',
      action: 'create_new',
      target_customer_public_id: null,
      disclosure: preview().disclosure,
      fingerprint: 'fingerprint-one',
      acknowledged_at: '2026-09-21T12:00:00',
    },
  };

  /**
   * The real server: once decided, every read of this registration is a 409. The stub
   * answers the same way, so a screen that tried to refetch its way to the new state
   * would land on the "already decided" page and lose the outcome banner.
   */
  function decidedAfterwards(decision) {
    let decided = false;
    const conflict = {
      code: 'conflict',
      message: 'This registration has already been decided: it is active.',
      detail: null,
    };
    const routes = [
      session([REVIEW, APPROVE]),
      { ...ACK },
      {
        ...decision,
        body: () => {
          decided = true;
          return decision.body;
        },
      },
      {
        path: `${REGISTRATION}/duplicate-candidates`,
        body: () => duplicates(),
      },
      { path: `${REGISTRATION}/preview`, body: () => preview() },
      { path: IDENTITY, body: identity() },
    ];
    const fetchMock = stubFetch([
      ...routes,
      {
        path: REGISTRATION,
        get status() {
          return decided ? 409 : 200;
        },
        body: () => (decided ? conflict : registration()),
      },
    ]);
    const utils = renderWithProviders(
      <SessionProvider>
        <Routes>
          <Route
            path="/customer-accounts/:accountReference"
            element={<CustomerAccountReviewPage />}
          />
        </Routes>
      </SessionProvider>,
      { route: '/customer-accounts/CA-7K9D2M4R' },
    );
    const invalidate = vi.spyOn(utils.queryClient, 'invalidateQueries');
    return { ...utils, fetchMock, invalidate };
  }

  function registrationReads(fetchMock) {
    return fetchMock.mock.calls.filter(([url, init = {}]) => {
      const path = String(url).split('?')[0];
      return path.endsWith(REGISTRATION) && (init.method || 'GET') === 'GET';
    }).length;
  }

  it('shows the approved state from the decision, and refreshes the customer side', async () => {
    const user = userEvent.setup();
    const { fetchMock, invalidate } = decidedAfterwards({
      path: `${REGISTRATION}/approve/create-new`,
      method: 'POST',
      body: {
        account_reference: 'CA-7K9D2M4R',
        status: 'active',
        customer_public_id: 'STCA-000900',
        outcome: 'approved_created',
        replayed: false,
      },
    });

    await screen.findByText('What this approval discloses');
    expect(screen.getAllByText('Waiting for review').length).toBeGreaterThan(0);
    await user.click(screen.getByLabelText(/I have read the figures above/));
    await waitFor(() => {
      expect(
        screen.getByRole('button', { name: 'Approve and create the customer' }),
      ).toBeEnabled();
    });
    const readsBefore = registrationReads(fetchMock);
    await user.click(screen.getByRole('button', { name: 'Approve and create the customer' }));

    expect(await screen.findByText('The decision has been recorded.')).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.queryByText('Waiting for review')).toBeNull();
    });
    // The state line of "The application" card, from the decision's own answer.
    expect(screen.getByText('Active')).toBeInTheDocument();
    expect(screen.queryByText('This application has already been decided')).toBeNull();

    // Every cached Customer Account read is marked stale, without refetching this
    // account's reads into a 409; the customer list and records are re-read.
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ['customer-account'], refetchType: 'none' });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ['customer'] });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ['customers'] });
    expect(registrationReads(fetchMock)).toBe(readsBefore);
  });

  it('shows the declined state from the decision, and leaves customer records alone', async () => {
    const user = userEvent.setup();
    const { invalidate } = decidedAfterwards({
      path: `${REGISTRATION}/reject`,
      method: 'POST',
      body: {
        account_reference: 'CA-7K9D2M4R',
        status: 'rejected',
        customer_public_id: null,
        outcome: 'rejected',
        replayed: false,
      },
    });

    await screen.findByText('Decline this application');
    await user.selectOptions(screen.getByLabelText('Reason'), 'duplicate_application');
    await user.click(screen.getByRole('button', { name: 'Decline the application' }));

    expect(await screen.findByText('The decision has been recorded.')).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.queryByText('Waiting for review')).toBeNull();
    });
    expect(screen.getAllByText('Declined').length).toBe(2);
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ['customer-account'], refetchType: 'none' });
    expect(invalidate).not.toHaveBeenCalledWith({ queryKey: ['customer'] });
  });
});

describe('what the screens never show', () => {
  it('renders no credential, session, captured mail, shipment reference or money', async () => {
    const contaminated = registration({
      password_hash: 'SENTINEL-HASH',
      session_token: 'SENTINEL-SESSION',
      verification_token: 'SENTINEL-TOKEN',
      captured_message: 'SENTINEL-MAIL',
      shipment_references: ['SENTINEL-SHIPMENT'],
      selling_amount: 'SENTINEL-MONEY',
    });
    renderReview([
      session([REVIEW, APPROVE]),
      {
        path: '/customer-account/registrations/CA-7K9D2M4R/duplicate-candidates',
        body: duplicates(),
      },
      { path: '/customer-account/registrations/CA-7K9D2M4R/preview', body: preview() },
      { path: '/customer-account/registrations/CA-7K9D2M4R', body: contaminated },
      { path: IDENTITY, body: identity({ password_hash: 'SENTINEL-HASH' }) },
    ]);

    await screen.findByText('What this approval discloses');
    await screen.findByText('Account status');
    expect(document.body.textContent).not.toMatch(/SENTINEL-/);
  });
});

describe('the account status card (Sprint 13 Lane A, A-1)', () => {
  it('suspends a pending account with a bounded reason and reports it', async () => {
    const user = userEvent.setup();
    const fetchMock = stubFetch([
      ...BASE(),
      {
        path: `${IDENTITY}/suspend`,
        method: 'POST',
        body: identity({ status: 'suspended', can_suspend: false, can_reinstate: true, suspended_at: '2026-10-14T10:00:00', status_reason_code: 'staff_review' }),
      },
    ]);
    renderWithProviders(
      <SessionProvider>
        <Routes>
          <Route path="/customer-accounts/:accountReference" element={<CustomerAccountReviewPage />} />
        </Routes>
      </SessionProvider>,
      { route: '/customer-accounts/CA-7K9D2M4R' },
    );
    await screen.findByText('Account status');
    const suspend = screen.getByRole('button', { name: 'Suspend account' });
    expect(suspend).toBeDisabled();

    await user.selectOptions(screen.getByLabelText('Grounds for suspending'), 'staff_review');
    expect(suspend).toBeEnabled();
    await user.click(suspend);

    await waitFor(() => {
      const call = fetchMock.mock.calls.find(([url]) => String(url).includes('/suspend'));
      expect(call).toBeTruthy();
      expect(JSON.parse(call[1].body)).toEqual({ reason_code: 'staff_review' });
    });
    expect(
      await screen.findByText('The account has been suspended and signed out everywhere.'),
    ).toBeInTheDocument();
    // The card now offers the way back, and names the recorded reason.
    expect(await screen.findByRole('button', { name: 'Reinstate account' })).toBeInTheDocument();
    expect(screen.getByText('Under staff review')).toBeInTheDocument();
  });

  it('reaches an already-decided account through the same screen', async () => {
    stubFetch([
      session([REVIEW, APPROVE]),
      {
        path: '/customer-account/registrations/CA-7K9D2M4R',
        status: 409,
        body: { code: 'conflict', message: 'This registration has already been decided: it is active.', field: null, detail: null },
      },
      { path: IDENTITY, body: identity({ status: 'active', linked_customer_public_id: 'STCA-000012', approved_at: '2026-09-20T10:00:00' }) },
    ]);
    renderWithProviders(
      <SessionProvider>
        <Routes>
          <Route path="/customer-accounts/:accountReference" element={<CustomerAccountReviewPage />} />
        </Routes>
      </SessionProvider>,
      { route: '/customer-accounts/CA-7K9D2M4R' },
    );
    await screen.findByText('This application has already been decided');
    await screen.findByText('Account status');
    expect(screen.getByText('STCA-000012')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Suspend account' })).toBeInTheDocument();
  });

  it('shows the state to a review-only reviewer with no control', async () => {
    renderReview(BASE([REVIEW]));
    await screen.findByText('Account status');
    expect(screen.queryByRole('button', { name: 'Suspend account' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Reinstate account' })).toBeNull();
  });
});

describe('permission', () => {
  it('lets a review-only reviewer read but not decide', async () => {
    renderReview(BASE([REVIEW]));
    await screen.findByText('What this approval discloses');

    expect(screen.getByText('You can read this application but not decide on it.')).toBeInTheDocument();
    expect(screen.queryByText('Decline this application')).toBeNull();
    expect(screen.getByLabelText(/I have read the figures above/)).toBeDisabled();
  });
});

describe('a role without the review permission', () => {
  it('sees a refusal, not the queue, and requests no queue data', async () => {
    const fetchMock = stubFetch([session(['customer:read', 'duplicate:review'])]);
    renderWithProviders(
      <SessionProvider>
        <CustomerAccountQueuePage />
      </SessionProvider>,
    );
    expect(await screen.findByText('You do not have access to this')).toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: 'Customer account applications' })).toBeNull();
    expect(
      fetchMock.mock.calls.some(([url]) => String(url).includes('/customer-account/')),
    ).toBe(false);
  });
});
