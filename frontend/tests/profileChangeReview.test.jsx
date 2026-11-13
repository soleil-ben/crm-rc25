/**
 * The staff review of a linked customer's profile change (fix pack 2; CA-PRF-02 step 3).
 */

import { describe, expect, it } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Route, Routes } from 'react-router-dom';
import { SessionProvider } from '../src/app/SessionContext.jsx';
import { ProfileChangeReviewPage } from '../src/features/customer_accounts/ProfileChangeReviewPage.jsx';
import { renderWithProviders, stubFetch } from './utils.jsx';

const REVIEW = 'customer_account:review';
const APPROVE = 'customer_account:approve';
const URL_BASE = '/customer-account/identities/CA-7K9D2M4R/profile-proposal';

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

function reviewFixture(overrides = {}) {
  return {
    account_reference: 'CA-7K9D2M4R',
    customer_public_id: 'STCA-000012',
    status: 'pending',
    submitted_at: '2026-10-14T05:19:00',
    reviewed_at: null,
    decision_reason_code: null,
    groups: ['legal_name', 'pickup_address'],
    fields: [
      {
        field_key: 'legal_name',
        group: 'legal_name',
        proposed_value: 'Hạnh Nguyễn',
        proposed_value_normalized: 'hanh nguyen',
        current_value_at_submission: 'Nguyễn Thị Bích Hạnh',
        current_value_now: 'Nguyễn Thị Bích Hạnh',
        drifted: false,
        applied: false,
      },
      {
        field_key: 'pickup_address.1.city',
        group: 'pickup_address',
        proposed_value: 'Toronto',
        proposed_value_normalized: 'toronto',
        current_value_at_submission: 'Mississauga',
        current_value_now: 'Brampton',
        drifted: true,
        applied: false,
      },
    ],
    decline_reason_codes: ['could_not_verify', 'incomplete', 'not_a_correction', 'customer_request'],
    ...overrides,
  };
}

function renderReview(routes) {
  const fetchMock = stubFetch(routes);
  renderWithProviders(
    <SessionProvider>
      <Routes>
        <Route path="/customer-accounts/:accountReference/profile-change" element={<ProfileChangeReviewPage />} />
      </Routes>
    </SessionProvider>,
    { route: '/customer-accounts/CA-7K9D2M4R/profile-change' },
  );
  return fetchMock;
}

describe('ProfileChangeReviewPage', () => {
  it('shows proposed, on-file-then, on-file-now and normalized values, and flags drift', async () => {
    renderReview([session([REVIEW, APPROVE]), { path: URL_BASE, body: reviewFixture() }]);
    const legal = await screen.findByRole('table', { name: 'Legal name' });
    expect(within(legal).getByText('Hạnh Nguyễn')).toBeInTheDocument();
    expect(within(legal).getAllByText('Nguyễn Thị Bích Hạnh')).toHaveLength(2);
    expect(within(legal).getByText('hanh nguyen')).toBeInTheDocument();

    const address = screen.getByRole('table', { name: 'Pickup address' });
    expect(within(address).getByText('Changed since')).toBeInTheDocument();
    expect(screen.getByText('The record changed after this was sent')).toBeInTheDocument();
  });

  it('records a per-group decision, asking for a reason only when something is declined', async () => {
    const user = userEvent.setup();
    const fetchMock = renderReview([
      session([REVIEW, APPROVE]),
      {
        path: `${URL_BASE}/decide`,
        method: 'POST',
        body: reviewFixture({ status: 'approved', reviewed_at: '2026-10-14T06:00:00' }),
      },
      { path: URL_BASE, body: reviewFixture() },
    ]);
    await screen.findByRole('table', { name: 'Legal name' });
    const record = screen.getByRole('button', { name: 'Record decision' });
    expect(record).toBeDisabled();

    await user.click(screen.getAllByLabelText('Approve')[0]);
    await user.click(screen.getAllByLabelText('Decline')[1]);
    expect(record).toBeDisabled();
    await user.selectOptions(
      screen.getByLabelText('Reason for the declined changes'),
      'could_not_verify',
    );
    expect(record).toBeEnabled();
    await user.click(record);

    await waitFor(() => {
      const call = fetchMock.mock.calls.find(([url]) => String(url).includes('/decide'));
      expect(JSON.parse(call[1].body)).toEqual({
        decisions: { legal_name: 'approve', pickup_address: 'decline' },
        reason_code: 'could_not_verify',
      });
    });
    expect(await screen.findByText('This change request has been decided')).toBeInTheDocument();
  });

  it('offers no decision to a review-only role', async () => {
    renderReview([session([REVIEW]), { path: URL_BASE, body: reviewFixture() }]);
    await screen.findByRole('table', { name: 'Legal name' });
    expect(screen.queryByRole('button', { name: 'Record decision' })).toBeNull();
    expect(screen.queryByLabelText('Approve')).toBeNull();
  });
});
