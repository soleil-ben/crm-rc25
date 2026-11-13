/**
 * UAT round 7 (the owner's decisions of 2026-10-16):
 *
 * * staff cannot change the email of a customer whose Customer Account is active or
 *   suspended; the edit form shows the rule and the field is read-only until the account
 *   is deactivated.
 *
 * (Suppression blocking marketing email only, and a takeover sending nothing to the former
 * holder, are server rules; see `backend/tests/test_uat_round_7.py`.)
 */

import { afterEach, describe, expect, it, vi } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { CustomerFormDrawer } from '../src/features/customers/CustomerFormDrawer.jsx';
import { customerFixture, renderWithProviders, stubFetch } from './utils.jsx';

const RULE =
  "This is the sign-in email of the customer's account, which is active or suspended. To change it, deactivate the account first.";
const SERVER_MESSAGE =
  "This email is the sign-in email of the customer's account, so it cannot be changed while the account is active or suspended. Deactivate the account first.";

afterEach(() => {
  vi.unstubAllGlobals();
});

function setup(customer, { patchStatus = 200 } = {}) {
  const fetchMock = stubFetch([
    { path: '/staff/assignable', body: [] },
    { path: '/customers/duplicate-check', method: 'POST', body: { candidates: [], guidance: '' } },
    {
      path: '/customers/1',
      method: 'PATCH',
      status: patchStatus,
      body:
        patchStatus === 200
          ? (init) => ({ ...customer, ...JSON.parse(init.body) })
          : { code: 'conflict', message: SERVER_MESSAGE, field: 'email' },
    },
  ]);
  renderWithProviders(<CustomerFormDrawer open onClose={vi.fn()} customer={customer} />);
  return { fetchMock };
}

describe('A held email (owner decision, 2026-10-16)', () => {
  it('shows the rule and makes the email read-only while an account holds it', async () => {
    setup({ ...customerFixture, email_held_by_account: true });
    const email = await screen.findByLabelText('Email address');
    expect(email).toHaveAttribute('readonly');
    expect(email).toHaveAccessibleDescription(RULE);
    expect(screen.getByText(RULE)).toBeInTheDocument();
  });

  it('typing does not change a held email, and the rest of the form still saves', async () => {
    const user = userEvent.setup();
    const { fetchMock } = setup({ ...customerFixture, email_held_by_account: true });
    const email = await screen.findByLabelText('Email address');
    await user.type(email, 'x');
    expect(email).toHaveValue(customerFixture.email_entered);

    await user.type(screen.getByLabelText('City'), 'Hue');
    await user.click(screen.getByRole('button', { name: 'Save' }));
    await waitFor(() => {
      const call = fetchMock.mock.calls.find(([, init]) => init?.method === 'PATCH');
      expect(call).toBeTruthy();
      expect(JSON.parse(call[1].body).email).toBe(customerFixture.email_entered);
    });
  });

  it('says nothing and leaves the email editable when no account holds it', async () => {
    setup({ ...customerFixture, email_held_by_account: false });
    const email = await screen.findByLabelText('Email address');
    expect(email).not.toHaveAttribute('readonly');
    expect(screen.queryByText(RULE)).not.toBeInTheDocument();
  });

  it('a new customer has no rule to show', async () => {
    stubFetch([
      { path: '/staff/assignable', body: [] },
      { path: '/customers/duplicate-check', method: 'POST', body: { candidates: [], guidance: '' } },
    ]);
    renderWithProviders(<CustomerFormDrawer open onClose={vi.fn()} />);
    const email = await screen.findByLabelText('Email address');
    expect(email).not.toHaveAttribute('readonly');
    expect(screen.queryByText(RULE)).not.toBeInTheDocument();
  });

  it("the server's refusal names the way out, on the email field", async () => {
    // A stale form (opened before the account was approved) still meets the server rule.
    const user = userEvent.setup();
    setup({ ...customerFixture, email_held_by_account: false }, { patchStatus: 409 });
    const email = await screen.findByLabelText('Email address');
    await user.clear(email);
    await user.type(email, 'other@demo.example.com');
    await user.click(screen.getByRole('button', { name: 'Save' }));
    expect(await screen.findAllByText(SERVER_MESSAGE)).not.toHaveLength(0);
  });
});
