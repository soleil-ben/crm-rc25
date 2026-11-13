/**
 * UAT round 11 (the owner's decisions of 2026-10-18 on the RC-UAT-13 and RC-UAT-14
 * questions), the screen half:
 *
 * 2. "Billing address is the same as the address above" starts ticked, so an empty form
 *    shows no billing errors; unticking still requires the billing parts (DEC-0158);
 * 3. the country lists still start on Canada (DEC-0157);
 * 4. the postal code is optional for the address and for billing, in every country
 *    (DEC-0159); since round 12 a typed Canadian or United States one is shape-checked
 *    (DEC-0165, `uatRound12.test.jsx`);
 * 5. each shipment row and card shows the booking reference (DEC-0160);
 * 7. the search hint names package IDs, which the server now searches (DEC-0161).
 *
 * The server half is `backend/tests/test_uat_round_11.py` and
 * `backend/tests/test_account_shipment_search.py`.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { BILLING_SAME_LABEL, REQUIRED_ADDRESS_PARTS } from '../src/account/pages/RegisterPage.jsx';
import {
  BOOKING_REFERENCE_LABEL,
  SEARCH_HINT,
} from '../src/account/pages/ShipmentListPage.jsx';
import {
  clearBrowserStorage,
  listItemFixture,
  listPageFixture,
  meFixture,
  renderAccount,
  requestedUrls,
  stubAccountFetch,
} from './accountUtils.jsx';

const SIGNED_OUT = {
  path: '/api/v1/account/me',
  status: 401,
  body: { code: 'unauthenticated', message: 'Sign in to continue.', field: null },
};
const GENERIC = 'If that address can be registered, we have sent a message to it.';
const PASSWORD = 'a-long-enough-password';

beforeEach(clearBrowserStorage);
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

async function fillAddress(user, group, { line1, city, province, postal }) {
  const scope = within(group);
  if (line1) await user.type(scope.getByLabelText(/^Address line 1/), line1);
  if (city) await user.type(scope.getByLabelText(/^City/), city);
  if (province) await user.type(scope.getByLabelText(/^Province or state/), province);
  if (postal) await user.type(scope.getByLabelText(/^(Postal|ZIP) code/), postal);
}

const addressGroup = () => screen.getByRole('group', { name: 'Address' });
const billingGroup = () => screen.getByRole('group', { name: 'Billing address' });
const submit = (user) => user.click(screen.getByRole('button', { name: 'Create account' }));
const registerSent = (calls) => requestedUrls(calls).some((url) => url.includes('/register'));
const registerBody = (calls) =>
  JSON.parse(calls.find((call) => call.url.includes('/register')).init.body);

const SAIGON = { line1: '125 Nguyen Hue', city: 'Ho Chi Minh City', province: 'HCM' };

describe('UAT round 11 › the billing box starts ticked', () => {
  it('is ticked when the form opens, with the billing fields hidden', async () => {
    renderRegister();
    const box = await screen.findByLabelText(BILLING_SAME_LABEL);
    expect(box).toBeChecked();
    expect(within(billingGroup()).queryByLabelText(/^Address line 1/)).not.toBeInTheDocument();
    // It is not a consent box: those still start unchecked.
    expect(screen.getByLabelText(/I accept the Solaris Express terms/)).not.toBeChecked();
    expect(screen.getByLabelText(/may email me about services and offers/)).not.toBeChecked();
  });

  it('an empty form lists the address errors and no billing error', async () => {
    const user = userEvent.setup();
    const { calls } = renderRegister();
    await screen.findByRole('heading', { name: 'Create an account', level: 1 });
    await submit(user);

    const summary = await screen.findByRole('alert');
    for (const message of [
      'Enter the street address (address line 1).',
      'Enter the city.',
      'Enter the province or state.',
    ]) {
      expect(within(summary).getByRole('link', { name: message })).toBeInTheDocument();
    }
    expect(within(summary).queryByText(/billing/i)).not.toBeInTheDocument();
    expect(within(summary).queryByText(/postal code|ZIP code/)).not.toBeInTheDocument();
    expect(registerSent(calls)).toBe(false);
  });

  it('unticked, the four billing parts are required and the postal code is not', async () => {
    const user = userEvent.setup();
    const { calls } = renderRegister();
    await fillAccountDetails(user);
    await fillAddress(user, addressGroup(), SAIGON);
    await user.click(screen.getByLabelText(BILLING_SAME_LABEL));
    await submit(user);

    const summary = await screen.findByRole('alert');
    for (const message of [
      'Enter the billing street address (address line 1).',
      'Enter the billing city.',
      'Enter the billing province or state.',
    ]) {
      expect(within(summary).getByRole('link', { name: message })).toBeInTheDocument();
    }
    expect(within(summary).queryByText(/postal code/)).not.toBeInTheDocument();
    expect(registerSent(calls)).toBe(false);

    await fillAddress(user, billingGroup(), SAIGON);
    await submit(user);
    await screen.findByRole('heading', { name: 'Check your email', level: 1 });
    const body = registerBody(calls);
    expect(body.billing_same_as_shipping).toBe(false);
    expect(body.customer['billing_address.city']).toBe('Ho Chi Minh City');
    expect(body.customer['billing_address.postal_code']).toBeUndefined();
  });

  it('always sends the box explicitly', async () => {
    const user = userEvent.setup();
    const { calls } = renderRegister();
    await fillAccountDetails(user);
    await fillAddress(user, addressGroup(), SAIGON);
    await submit(user);
    await screen.findByRole('heading', { name: 'Check your email', level: 1 });
    expect(registerBody(calls).billing_same_as_shipping).toBe(true);
  });
});

describe('UAT round 11 › the country lists start on Canada', () => {
  it('for the address, the phone and an unticked billing address', async () => {
    const user = userEvent.setup();
    renderRegister();
    await screen.findByRole('heading', { name: 'Create an account', level: 1 });
    expect(within(addressGroup()).getByLabelText('Country')).toHaveValue('CA');
    expect(screen.getByLabelText('Phone country')).toHaveValue('CA');
    await user.click(screen.getByLabelText(BILLING_SAME_LABEL));
    expect(within(billingGroup()).getByLabelText('Country')).toHaveValue('CA');
    expect(screen.queryByRole('option', { name: /Choose a country/ })).not.toBeInTheDocument();
  });
});

describe('UAT round 11 › the postal code is optional', () => {
  it('lists four required parts', () => {
    expect(REQUIRED_ADDRESS_PARTS).toEqual(['country_code', 'address_line1', 'city', 'province_state']);
  });

  it.each([
    ['CA', 'Postal code'],
    ['VN', 'Postal code'],
    ['US', 'ZIP code'],
  ])('%s: marked optional, and registration is sent without one', async (country, label) => {
    const user = userEvent.setup();
    const { calls } = renderRegister();
    await fillAccountDetails(user);
    await user.selectOptions(within(addressGroup()).getByLabelText('Country'), country);
    expect(within(addressGroup()).getByLabelText(label)).not.toHaveAttribute('aria-invalid');
    await fillAddress(user, addressGroup(), SAIGON);
    await submit(user);
    await screen.findByRole('heading', { name: 'Check your email', level: 1 });
    const body = registerBody(calls);
    expect(body.customer['pickup_address.1.country_code']).toBe(country);
    expect(body.customer['pickup_address.1.postal_code']).toBeUndefined();
  });

  it('a postal code of spaces is not sent and is not an error', async () => {
    const user = userEvent.setup();
    const { calls } = renderRegister();
    await fillAccountDetails(user);
    await fillAddress(user, addressGroup(), { ...SAIGON, postal: '   ' });
    await submit(user);
    await screen.findByRole('heading', { name: 'Check your email', level: 1 });
    expect(registerBody(calls).customer['pickup_address.1.postal_code']).toBeUndefined();
  });

  it('a typed postal code is sent as typed', async () => {
    // Any format until round 12; a Vietnamese code is still not checked (DEC-0165).
    const user = userEvent.setup();
    const { calls } = renderRegister();
    await fillAccountDetails(user);
    await user.selectOptions(within(addressGroup()).getByLabelText('Country'), 'VN');
    await fillAddress(user, addressGroup(), { ...SAIGON, postal: 'abc 12' });
    await submit(user);
    await screen.findByRole('heading', { name: 'Check your email', level: 1 });
    expect(registerBody(calls).customer['pickup_address.1.postal_code']).toBe('abc 12');
  });

  it('shows a server refusal of the postal code beside it', async () => {
    const user = userEvent.setup();
    renderRegister({
      status: 422,
      body: {
        code: 'validation_error',
        message: 'That value is too long.',
        field: 'pickup_address.1.postal_code',
      },
    });
    await fillAccountDetails(user);
    await fillAddress(user, addressGroup(), { ...SAIGON, postal: 'L4W 1V2' });
    await submit(user);
    const postal = within(addressGroup()).getByLabelText('Postal code');
    await waitFor(() => expect(postal).toHaveAttribute('aria-invalid', 'true'));
    expect(postal).toHaveAccessibleDescription(/That value is too long\./);
  });
});

describe('UAT round 11 › the shipment list', () => {
  const ME = '/api/v1/account/me';
  const LIST = '/api/v1/account/shipments';

  async function renderList(items) {
    const stub = stubAccountFetch([
      { path: ME, body: meFixture() },
      { path: LIST, body: listPageFixture(items) },
    ]);
    renderAccount('/account/shipments');
    await screen.findByRole('heading', { name: 'My shipments', level: 1 });
    return stub;
  }

  it('shows the booking reference on each table row and each card', async () => {
    await renderList([
      listItemFixture({ booking_reference: 'PO-BAKERY-4471' }),
      listItemFixture({ shipment_reference: 'SX-CAV-AAAABBBBCCCC', booking_reference: null }),
    ]);

    const table = screen.getByRole('table');
    const rows = within(table).getAllByRole('row').slice(1);
    expect(within(rows[0]).getByText(`${BOOKING_REFERENCE_LABEL}: PO-BAKERY-4471`)).toBeInTheDocument();
    expect(within(rows[1]).getByText(`${BOOKING_REFERENCE_LABEL}: Not recorded`)).toBeInTheDocument();

    const cards = document.querySelectorAll('.ca-shipment-card');
    expect(cards).toHaveLength(2);
    const first = within(cards[0]);
    expect(first.getByText(BOOKING_REFERENCE_LABEL).tagName).toBe('DT');
    expect(first.getByText('PO-BAKERY-4471').tagName).toBe('DD');
    expect(within(cards[1]).getByText('Not recorded')).toBeInTheDocument();
  });

  it('the search hint names package IDs', async () => {
    await renderList([listItemFixture()]);
    expect(SEARCH_HINT).toMatch(/a package ID/);
    // "Optional" follows the hint since RC-UAT-25 item 1 (it was "(optional)" in the label).
    expect(screen.getByLabelText(/Search shipments/)).toHaveAccessibleDescription(
      `${SEARCH_HINT} Optional`,
    );
  });

  it('sends a package reference as the keyword', async () => {
    const user = userEvent.setup();
    const { calls } = await renderList([listItemFixture()]);
    await user.type(screen.getByLabelText(/Search shipments/), 'SX-CAV-7K9D2M4R8T6W-01');
    await user.click(screen.getByRole('button', { name: 'Apply filters' }));
    await waitFor(() =>
      expect(
        requestedUrls(calls).some((url) => url.includes('q=SX-CAV-7K9D2M4R8T6W-01')),
      ).toBe(true),
    );
  });
});
