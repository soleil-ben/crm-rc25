/**
 * UAT round 6 (findings on RC-UAT-9, and the owner's decisions of 2026-10-15):
 *
 * * one email per customer: a link-existing preview shows the record's email changing to
 *   the account's sign-in email, and says that is the only value written;
 * * a deactivated account's link can be taken over: the preview says whose link ends;
 * * both evidence-reference fields say "Ticket or reference number only, no names".
 *
 * (Suppression no longer blocking account email is a server rule; see
 * `backend/tests/test_uat_round_6.py`.)
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Route, Routes } from 'react-router-dom';
import { SessionProvider } from '../src/app/SessionContext.jsx';
import { CustomerAccountReviewPage } from '../src/features/customer_accounts/CustomerAccountReviewPage.jsx';
import { ConsentTab } from '../src/features/customers/tabs/ConsentTab.jsx';
import { renderWithProviders, stubFetch } from './utils.jsx';

const HINT = 'Ticket or reference number only, no names';

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

beforeEach(() => {
  window.localStorage.clear();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

/* --- 1 and 3. The link-existing preview ------------------------------------------------- */

const REF = 'CA-7K9D2M4R';
const REGISTRATIONS = `/customer-account/registrations/${REF}`;

function preview(overrides = {}) {
  return {
    account_reference: REF,
    action: 'link_existing',
    proposal_id: 12,
    proposed: { legal_name: 'Hanh Nguyen' },
    current: { legal_name: 'Hanh Nguyen' },
    differences: [],
    duplicate_classification: 'none',
    candidate_references: [],
    target_customer_public_id: 'STCA-000123',
    disclosure: {
      shipment_count: 3,
      oldest_booked_at: '2025-02-03T00:00:00',
      newest_booked_at: '2026-09-01T00:00:00',
      includes_cancelled: false,
      includes_rebooked: false,
      definition_version: 'od29-v1',
    },
    fingerprint: 'fingerprint-one',
    mapping_refusal: null,
    email_change: null,
    ends_link_of: null,
    ...overrides,
  };
}

async function renderLinkPreview(previewBody) {
  const user = userEvent.setup();
  stubFetch([
    session('operations', ['customer_account:review', 'customer_account:approve']),
    { path: `${REGISTRATIONS}/preview`, body: previewBody },
    {
      path: `${REGISTRATIONS}/duplicate-candidates`,
      body: { account_reference: REF, duplicate_classification: 'none', candidates: [] },
    },
    {
      path: REGISTRATIONS,
      body: {
        account_reference: REF,
        status: 'pending_approval',
        account_email_entered: 'hanh@demo.example.com',
        account_email_normalized: 'hanh@demo.example.com',
        email_verified_at: '2026-10-15T10:05:00',
        preferred_language: 'en',
        submitted_at: '2026-10-15T10:00:00',
        proposal_id: 12,
        proposal_status: 'pending',
        fields: [],
        has_active_link: false,
      },
    },
    {
      path: `/customer-account/identities/${REF}`,
      body: {
        account_reference: REF,
        status: 'pending_approval',
        status_reason_code: null,
        account_email_entered: 'hanh@demo.example.com',
        email_verified: true,
        approved_at: null,
        suspended_at: null,
        linked_customer_public_id: null,
        can_suspend: true,
        can_reinstate: false,
      },
    },
  ]);
  renderWithProviders(
    <SessionProvider>
      <Routes>
        <Route path="/customer-accounts/:accountReference" element={<CustomerAccountReviewPage />} />
      </Routes>
    </SessionProvider>,
    { route: `/customer-accounts/${REF}` },
  );
  await screen.findByText('What this approval discloses');
  await user.selectOptions(screen.getByLabelText('What should happen'), 'link_existing');
  await user.type(screen.getByLabelText('Customer to link to'), 'STCA-000123');
  return screen.getByText('What this approval discloses').closest('.ca-preview');
}

describe('Review › one email per customer (owner decision, 2026-10-15)', () => {
  it('shows the record email changing to the sign-in email before acknowledging', async () => {
    const block = await renderLinkPreview(
      preview({
        email_change: { current: 'existing@demo.example.com', new: 'hanh@demo.example.com' },
      }),
    );
    expect(within(block).getByText("The customer's email will change")).toBeInTheDocument();
    expect(
      within(block).getByText(/Approving replaces STCA-000123's email with this account's verified/),
    ).toBeInTheDocument();
    const from = within(block).getByText('Email on the record now').closest('div');
    expect(within(from).getByText('existing@demo.example.com')).toBeInTheDocument();
    const to = within(block).getByText('Email after approval').closest('div');
    expect(within(to).getByText('hanh@demo.example.com')).toBeInTheDocument();
    await waitFor(() =>
      expect(within(block).getByText(/Only the email — it becomes the account's sign-in email/))
        .toBeInTheDocument(),
    );
    // The notice comes before the acknowledgement the reviewer ticks.
    const acknowledge = screen.getByLabelText(/I have read the figures above/);
    expect(
      within(block)
        .getByText("The customer's email will change")
        .compareDocumentPosition(acknowledge) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
  });

  it('says so when the record has no email yet', async () => {
    const block = await renderLinkPreview(
      preview({ email_change: { current: null, new: 'hanh@demo.example.com' } }),
    );
    expect(within(block).getByText('No email on the record')).toBeInTheDocument();
  });

  it('shows no notice, and "writes nothing", when the emails already agree', async () => {
    const block = await renderLinkPreview(preview());
    expect(within(block).queryByText("The customer's email will change")).not.toBeInTheDocument();
    await waitFor(() =>
      expect(
        within(block).getByText(/linking writes nothing to the existing customer record/),
      ).toBeInTheDocument(),
    );
  });
});

describe("Review › taking over a deactivated account's customer (owner decision, 2026-10-15)", () => {
  it('names the deactivated account whose link the approval ends', async () => {
    const block = await renderLinkPreview(preview({ ends_link_of: 'CA-OLD00001' }));
    expect(
      within(block).getByText("Approving ends a deactivated account's link"),
    ).toBeInTheDocument();
    expect(
      within(block).getByText(
        'STCA-000123 is linked to Customer Account CA-OLD00001, which is deactivated. Approving ends that link, records it in the audit log, and links this account instead.',
      ),
    ).toBeInTheDocument();
  });
});

/* --- 4. Evidence reference helper text --------------------------------------------------- */

const CONSENT = {
  states: [],
  history: [],
  do_not_contact: false,
  note: 'Operational messages are separate from promotional consent.',
};

async function openConsentTab() {
  const user = userEvent.setup();
  stubFetch([
    session('marketing', ['consent:read', 'consent:write', 'suppression:add']),
    { path: '/customers/1/consent', body: CONSENT },
  ]);
  renderWithProviders(
    <SessionProvider>
      <ConsentTab customer={{ id: 1, public_id: 'STCA-000001' }} />
    </SessionProvider>,
  );
  return user;
}

describe('Consent › evidence reference helper text (owner decision, 2026-10-15)', () => {
  it('is on the consent form, tied to the field', async () => {
    const user = await openConsentTab();
    await user.click(await screen.findByRole('button', { name: 'Record consent change' }));
    const dialog = await screen.findByRole('dialog');
    const input = within(dialog).getByLabelText('Evidence reference');
    expect(input).toHaveAccessibleDescription(HINT);
  });

  it('is on the suppression form, tied to the field', async () => {
    const user = await openConsentTab();
    await user.click(await screen.findByRole('button', { name: 'Suppress address' }));
    const dialog = await screen.findByRole('dialog');
    const input = within(dialog).getByLabelText(/Evidence reference/);
    expect(input).toHaveAccessibleDescription(HINT);
  });
});
