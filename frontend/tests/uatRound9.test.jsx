/**
 * UAT round 9 (the owner's decisions of 2026-10-18), registration only:
 *
 * 1. the first address section is "Address", and the billing box reads "Billing address
 *    is the same as the address above";
 * 2. the address's country, line 1, city, province or state and postal code are required,
 *    each with its own inline error and summary entry, and nothing is sent until they are
 *    filled;
 * 3. the driver note reads "Notes for driver (buzz code, contact concierge, security,...)";
 * 4. with the billing box unticked, the same five billing parts are required.
 *
 * UAT round 11 made the postal code optional (four required parts) and starts the billing
 * box ticked; the cases below say so, and `uatRound11.test.jsx` covers both in full.
 *
 * The server half of each, and the sign-in and sign-out audit actor (item 5), is
 * `backend/tests/test_uat_round_9.py`.
 */

import { afterEach, describe, expect, it, vi } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {
  addressPartMissingMessage,
  ADDRESS_LEGEND,
  BILLING_SAME_LABEL,
  DRIVER_NOTE_LABEL,
  REQUIRED_ADDRESS_PARTS,
} from '../src/account/pages/RegisterPage.jsx';
import { renderAccount, requestedUrls, stubAccountFetch } from './accountUtils.jsx';

const SIGNED_OUT = {
  path: '/api/v1/account/me',
  status: 401,
  body: { code: 'unauthenticated', message: 'Sign in to continue.', field: null },
};
const GENERIC = 'If that address can be registered, we have sent a message to it.';
const PASSWORD = 'a-long-enough-password';

afterEach(() => {
  vi.unstubAllGlobals();
});

function renderRegister(registerRoute = { body: { message: GENERIC } }) {
  const stub = stubAccountFetch([
    SIGNED_OUT,
    { path: '/api/v1/account/register', method: 'POST', ...registerRoute },
  ]);
  renderAccount('/account/register');
  return stub;
}

async function fillAccountDetails(user) {
  await user.type(await screen.findByLabelText(/^Email address/), 'someone@example.com');
  await user.type(screen.getByLabelText('Password'), PASSWORD);
  await user.type(screen.getByLabelText('Confirm password'), PASSWORD);
  await user.type(screen.getByLabelText(/Full legal name/), 'Someone Real');
  await user.click(screen.getByLabelText(/I accept the Solaris Express terms/));
}

const addressGroup = () => screen.getByRole('group', { name: 'Address' });
const billingGroup = () => screen.getByRole('group', { name: 'Billing address' });
const submit = (user) => user.click(screen.getByRole('button', { name: 'Create account' }));
const registerSent = (calls) => requestedUrls(calls).some((url) => url.includes('/register'));
const registerBody = (calls) =>
  JSON.parse(calls.find((call) => call.url.includes('/register')).init.body);

async function fillAddress(user, group, { line1, city, province, postal }) {
  const scope = within(group);
  if (line1) await user.type(scope.getByLabelText(/^Address line 1/), line1);
  if (city) await user.type(scope.getByLabelText(/^City/), city);
  if (province) await user.type(scope.getByLabelText(/^Province or state/), province);
  if (postal) await user.type(scope.getByLabelText(/^(Postal|ZIP) code/), postal);
}

const DIXIE = { line1: '4120 Dixie Road', city: 'Mississauga', province: 'ON', postal: 'L4W 1V2' };
const SAIGON = { line1: '125 Nguyen Hue', city: 'Ho Chi Minh City', province: 'HCM', postal: '700000' };

describe('UAT round 9 › wording', () => {
  it('calls the first section "Address", not "Shipping address"', async () => {
    renderRegister();
    await screen.findByRole('heading', { name: 'Create an account', level: 1 });
    expect(ADDRESS_LEGEND).toBe('Address');
    expect(addressGroup()).toBeInTheDocument();
    expect(screen.queryByRole('group', { name: 'Shipping address' })).not.toBeInTheDocument();
    expect(screen.queryByText(/shipping address/i)).not.toBeInTheDocument();
    // Address comes before billing.
    expect(
      addressGroup().compareDocumentPosition(billingGroup()) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
  });

  it('labels the billing box "the same as the address above"', async () => {
    renderRegister();
    expect(BILLING_SAME_LABEL).toBe('Billing address is the same as the address above');
    expect(await screen.findByLabelText(BILLING_SAME_LABEL)).toBeInTheDocument();
  });

  it('renames the driver note', async () => {
    renderRegister();
    await screen.findByRole('heading', { name: 'Create an account', level: 1 });
    expect(DRIVER_NOTE_LABEL).toBe('Notes for driver (buzz code, contact concierge, security,...)');
    expect(
      within(addressGroup()).getByLabelText(DRIVER_NOTE_LABEL),
    ).toBeInTheDocument();
    expect(screen.queryByText(/Anything the driver should know/)).not.toBeInTheDocument();
  });
});

describe('UAT round 9 › the address is required', () => {
  // RC-UAT-25 item 1, Ben 2026-10-25: required is a red asterisk (and aria-required), not
  // the words "(required)"; optional is "Optional" under the field.
  it('marks the four parts required with an asterisk and leaves line 2 and the postal code optional', async () => {
    renderRegister();
    await screen.findByRole('heading', { name: 'Create an account', level: 1 });
    const scope = within(addressGroup());
    for (const label of ['Country', 'Address line 1', 'City', 'Province or state']) {
      expect(scope.getByLabelText(label)).toHaveAttribute('aria-required', 'true');
    }
    expect(scope.getByLabelText('Address line 2')).not.toHaveAttribute('aria-required');
    expect(scope.getByLabelText('Address line 2')).toHaveAccessibleDescription(/Optional/);
    expect(scope.getByLabelText('Postal code')).toHaveAccessibleDescription(/Optional/);
  });

  it('shows an inline error beside each missing part and sends nothing', async () => {
    const user = userEvent.setup();
    const { calls } = renderRegister();
    await fillAccountDetails(user);
    // The box starts ticked (round 11), so only the address is checked.
    expect(screen.getByLabelText(BILLING_SAME_LABEL)).toBeChecked();
    await submit(user);

    const scope = within(addressGroup());
    await waitFor(() =>
      expect(scope.getByLabelText('Address line 1')).toHaveAttribute(
        'aria-invalid',
        'true',
      ),
    );
    for (const [label, part] of [
      ['Address line 1', 'address_line1'],
      ['City', 'city'],
      ['Province or state', 'province_state'],
    ]) {
      const message = addressPartMissingMessage(part);
      expect(scope.getByLabelText(label)).toHaveAccessibleDescription(new RegExp(message.replace(/[()]/g, '\\$&')));
    }
    // The summary lists each and links to it.
    const summary = screen.getByRole('alert');
    expect(within(summary).getByRole('link', { name: 'Enter the city.' })).toHaveAttribute(
      'href',
      expect.stringContaining('pickup_address.1.city'),
    );
    expect(within(summary).queryByText(/billing/)).not.toBeInTheDocument();
    expect(registerSent(calls)).toBe(false);
  });

  it('says ZIP code for the United States, and an empty one is no error', async () => {
    const user = userEvent.setup();
    const { calls } = renderRegister();
    await fillAccountDetails(user);
    await user.selectOptions(within(addressGroup()).getByLabelText('Country'), 'US');
    expect(within(addressGroup()).getByLabelText('ZIP code')).toBeInTheDocument();
    await fillAddress(user, addressGroup(), { ...DIXIE, postal: '' });
    await submit(user);
    await screen.findByRole('heading', { name: 'Check your email', level: 1 });
    expect(screen.queryByText('Enter the ZIP code.')).not.toBeInTheDocument();
    expect(registerBody(calls).customer['pickup_address.1.postal_code']).toBeUndefined();
  });

  it('a blank of spaces counts as missing', async () => {
    const user = userEvent.setup();
    const { calls } = renderRegister();
    await fillAccountDetails(user);
    await fillAddress(user, addressGroup(), { ...DIXIE, city: '   ' });
    await submit(user);
    expect(await screen.findAllByText('Enter the city.')).toHaveLength(2);
    expect(registerSent(calls)).toBe(false);
  });

  it('sends the five parts once they are filled', async () => {
    const user = userEvent.setup();
    const { calls } = renderRegister();
    await fillAccountDetails(user);
    await fillAddress(user, addressGroup(), DIXIE);
    expect(screen.getByLabelText(BILLING_SAME_LABEL)).toBeChecked();
    await submit(user);
    await screen.findByRole('heading', { name: 'Check your email', level: 1 });
    const body = registerBody(calls);
    expect(body.billing_same_as_shipping).toBe(true);
    // A typed postal code is still sent.
    expect(body.customer['pickup_address.1.postal_code']).toBe('L4W 1V2');
    for (const part of REQUIRED_ADDRESS_PARTS) {
      expect(body.customer[`pickup_address.1.${part}`]).toBeTruthy();
    }
  });

  it('shows a server refusal of an address part beside that field', async () => {
    const user = userEvent.setup();
    renderRegister({
      status: 422,
      body: {
        code: 'validation_error',
        message: 'Enter the province or state.',
        field: 'pickup_address.1.province_state',
      },
    });
    await fillAccountDetails(user);
    await fillAddress(user, addressGroup(), DIXIE);
    await submit(user);
    const province = within(addressGroup()).getByLabelText('Province or state');
    await waitFor(() => expect(province).toHaveAttribute('aria-invalid', 'true'));
    expect(province).toHaveAccessibleDescription(/Enter the province or state\./);
  });
});

describe('UAT round 9 › billing is required when unticked', () => {
  it('requires the four billing parts, each inline, and sends nothing', async () => {
    const user = userEvent.setup();
    const { calls } = renderRegister();
    await fillAccountDetails(user);
    await fillAddress(user, addressGroup(), DIXIE);
    await user.click(screen.getByLabelText(BILLING_SAME_LABEL));
    expect(screen.getByLabelText(BILLING_SAME_LABEL)).not.toBeChecked();

    const scope = within(billingGroup());
    for (const label of ['Country', 'Address line 1', 'City', 'Province or state']) {
      expect(scope.getByLabelText(label)).toHaveAttribute('aria-required', 'true');
    }
    expect(scope.getByLabelText('Postal code')).toHaveAccessibleDescription(/Optional/);
    await submit(user);
    for (const message of [
      'Enter the billing street address (address line 1).',
      'Enter the billing city.',
      'Enter the billing province or state.',
    ]) {
      expect(await screen.findAllByText(message)).toHaveLength(2);
    }
    expect(screen.queryByText(/postal code\./)).not.toBeInTheDocument();
    expect(registerSent(calls)).toBe(false);
  });

  it('sends a complete, different billing address', async () => {
    const user = userEvent.setup();
    const { calls } = renderRegister();
    await fillAccountDetails(user);
    await fillAddress(user, addressGroup(), DIXIE);
    await user.click(screen.getByLabelText(BILLING_SAME_LABEL));
    await user.selectOptions(within(billingGroup()).getByLabelText('Country'), 'VN');
    await fillAddress(user, billingGroup(), SAIGON);
    await submit(user);
    await screen.findByRole('heading', { name: 'Check your email', level: 1 });
    const body = registerBody(calls);
    expect(body.billing_same_as_shipping).toBe(false);
    expect(body.customer['billing_address.country_code']).toBe('VN');
    expect(body.customer['billing_address.postal_code']).toBe('700000');
    expect(body.customer['billing_address.province_state']).toBe('HCM');
  });

  it('ticked again, billing is not required and not sent', async () => {
    const user = userEvent.setup();
    const { calls } = renderRegister();
    await fillAccountDetails(user);
    await fillAddress(user, addressGroup(), DIXIE);
    await user.click(screen.getByLabelText(BILLING_SAME_LABEL));
    await user.click(screen.getByLabelText(BILLING_SAME_LABEL));
    await submit(user);
    await screen.findByRole('heading', { name: 'Check your email', level: 1 });
    const keys = Object.keys(registerBody(calls).customer);
    expect(keys.some((key) => key.startsWith('billing_address.'))).toBe(false);
  });
});
