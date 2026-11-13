/**
 * UAT round 12 (the owner's decisions of 2026-10-19 on the RC-UAT-15 questions), the
 * screen half:
 *
 * 1. the shipment's own page shows the booking reference, or "Not recorded" (DEC-0163);
 * 2. a cancelled package's ID is still a keyword like any other (DEC-0164; the server
 *    decides what it finds);
 * 3. a typed Canadian or United States postal code must have a lenient shape, checked
 *    before anything is sent, beside the field and in the summary; blank is always fine
 *    and other countries are not checked (DEC-0165);
 * 4. the form still sends the billing box explicitly, ticked or not (DEC-0166).
 *
 * The server half is `backend/tests/test_uat_round_12.py`.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {
  BILLING_SAME_LABEL,
  POSTAL_CODE_SHAPES,
  postalCodeError,
  postalCodeFormatMessage,
} from '../src/account/pages/RegisterPage.jsx';
import { BOOKING_REFERENCE_LABEL } from '../src/account/format.js';
import {
  clearBrowserStorage,
  detailFixture,
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
const ME = '/api/v1/account/me';
const REFERENCE = 'SX-CAV-7K9D2M4R8T6W';
const DETAIL = `/api/v1/account/shipments/${REFERENCE}`;

beforeEach(clearBrowserStorage);
afterEach(() => {
  vi.unstubAllGlobals();
});

describe('UAT round 12 › the booking reference on the shipment page', () => {
  async function renderDetail(overrides) {
    stubAccountFetch([
      { path: ME, body: meFixture() },
      { path: DETAIL, body: detailFixture(overrides) },
    ]);
    renderAccount(`/account/shipments/${REFERENCE}`);
    await screen.findByRole('heading', { name: REFERENCE, level: 1 });
  }

  it('shows it as the first fact under "Where it is"', async () => {
    await renderDetail({ booking_reference: 'PO-BAKERY-4471' });
    const label = screen.getByText(BOOKING_REFERENCE_LABEL);
    expect(label.tagName).toBe('DT');
    expect(label.nextElementSibling).toHaveTextContent('PO-BAKERY-4471');
    const grid = label.closest('dl');
    expect(grid.querySelector('dt')).toBe(label);
  });

  it('says "Not recorded" when there is none', async () => {
    await renderDetail({ booking_reference: null });
    expect(screen.getByText(BOOKING_REFERENCE_LABEL).nextElementSibling).toHaveTextContent(
      'Not recorded',
    );
  });

  it('shows it on a cancelled shipment too', async () => {
    await renderDetail({
      booking_reference: 'PO-CANCELLED-9',
      cancelled_at: '2026-09-06T12:00:00+00:00',
      timeline: [],
    });
    expect(screen.getByText('This shipment was cancelled.')).toBeInTheDocument();
    expect(screen.getByText('PO-CANCELLED-9')).toBeInTheDocument();
  });

  it('uses the same label as the list', async () => {
    const list = await import('../src/account/pages/ShipmentListPage.jsx');
    expect(list.BOOKING_REFERENCE_LABEL).toBe(BOOKING_REFERENCE_LABEL);
  });
});

describe('UAT round 12 › a cancelled package ID is an ordinary keyword', () => {
  it('is sent as the search keyword, unchanged', async () => {
    const user = userEvent.setup();
    const { calls } = stubAccountFetch([
      { path: ME, body: meFixture() },
      { path: '/api/v1/account/shipments', body: listPageFixture([listItemFixture()]) },
    ]);
    renderAccount('/account/shipments');
    await screen.findByRole('heading', { name: 'My shipments', level: 1 });
    await user.type(screen.getByLabelText(/Search shipments/), `${REFERENCE}-02`);
    await user.click(screen.getByRole('button', { name: 'Apply filters' }));
    await waitFor(() =>
      expect(requestedUrls(calls).some((url) => url.includes(`q=${REFERENCE}-02`))).toBe(true),
    );
  });
});

describe('UAT round 12 › the postal code shape', () => {
  it.each([
    ['CA', 'L4W 1V2'],
    ['CA', 'L4W1V2'],
    ['CA', 'l4w 1v2'],
    ['CA', '  k1a0b1  '],
    ['CA', 'K1A  0B1'],
    ['US', '98101'],
    ['US', '98101-1234'],
    ['US', ' 98101 '],
    ['VN', 'Not a real code'],
    ['CA', ''],
    ['US', '   '],
  ])('%s %j is fine', (country, value) => {
    expect(postalCodeError(country, value)).toBeNull();
  });

  it.each([
    ['CA', 'L4W 1V'],
    ['CA', 'L4W-1V2'],
    ['CA', '4LW 1V2'],
    ['CA', '98101'],
    ['US', '9810'],
    ['US', '981011'],
    ['US', '98101-123'],
    ['US', '981011234'],
    ['US', 'L4W 1V2'],
  ])('%s %j is refused with the server sentence', (country, value) => {
    expect(postalCodeError(country, value)).toBe(postalCodeFormatMessage(country));
  });

  it('checks the same two countries as the server, with the same sentences', () => {
    expect(Object.keys(POSTAL_CODE_SHAPES).sort()).toEqual(['CA', 'US']);
    expect(postalCodeFormatMessage('CA')).toBe(
      'Enter the postal code as A1A 1A1, or leave it blank.',
    );
    expect(postalCodeFormatMessage('US', { billing: true })).toBe(
      'Enter the billing ZIP code as 12345 or 12345-6789, or leave it blank.',
    );
  });
});

describe('UAT round 12 › the postal code on the form', () => {
  function renderRegister() {
    const stub = stubAccountFetch([
      SIGNED_OUT,
      { path: '/api/v1/account/register', method: 'POST', body: { message: GENERIC } },
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

  async function fillAddress(user, group, { country, postal }) {
    const scope = within(group);
    if (country) await user.selectOptions(scope.getByLabelText('Country'), country);
    await user.type(scope.getByLabelText(/^Address line 1/), '4120 Dixie Road');
    await user.type(scope.getByLabelText(/^City/), 'Mississauga');
    await user.type(scope.getByLabelText(/^Province or state/), 'ON');
    if (postal) await user.type(scope.getByLabelText(/^(Postal|ZIP) code/), postal);
  }

  const addressGroup = () => screen.getByRole('group', { name: 'Address' });
  const billingGroup = () => screen.getByRole('group', { name: 'Billing address' });
  const submit = (user) => user.click(screen.getByRole('button', { name: 'Create account' }));
  const registerSent = (calls) => requestedUrls(calls).some((url) => url.includes('/register'));
  const registerBody = (calls) =>
    JSON.parse(calls.find((call) => call.url.includes('/register')).init.body);

  it('a misshapen Canadian code is an inline error and a summary link, and nothing is sent', async () => {
    const user = userEvent.setup();
    const { calls } = renderRegister();
    await fillAccountDetails(user);
    await fillAddress(user, addressGroup(), { postal: '12345' });
    await submit(user);

    const message = 'Enter the postal code as A1A 1A1, or leave it blank.';
    const summary = await screen.findByRole('alert');
    expect(within(summary).getByRole('link', { name: message })).toBeInTheDocument();
    const postal = within(addressGroup()).getByLabelText('Postal code');
    expect(postal).toHaveAttribute('aria-invalid', 'true');
    expect(postal).toHaveAccessibleDescription(new RegExp(message.replace(/\./g, '\\.')));
    expect(registerSent(calls)).toBe(false);
  });

  it('a misshapen ZIP code says ZIP code', async () => {
    const user = userEvent.setup();
    const { calls } = renderRegister();
    await fillAccountDetails(user);
    await fillAddress(user, addressGroup(), { country: 'US', postal: '9810' });
    await submit(user);

    const summary = await screen.findByRole('alert');
    expect(
      within(summary).getByRole('link', {
        name: 'Enter the ZIP code as 12345 or 12345-6789, or leave it blank.',
      }),
    ).toBeInTheDocument();
    expect(within(addressGroup()).getByLabelText('ZIP code')).toHaveAttribute(
      'aria-invalid',
      'true',
    );
    expect(registerSent(calls)).toBe(false);
  });

  it('an unticked billing code is checked against the billing country, and says billing', async () => {
    const user = userEvent.setup();
    const { calls } = renderRegister();
    await fillAccountDetails(user);
    await fillAddress(user, addressGroup(), { postal: 'L4W 1V2' });
    await user.click(screen.getByLabelText(BILLING_SAME_LABEL));
    await fillAddress(user, billingGroup(), { country: 'US', postal: 'L4W 1V2' });
    await submit(user);

    const summary = await screen.findByRole('alert');
    expect(
      within(summary).getByRole('link', {
        name: 'Enter the billing ZIP code as 12345 or 12345-6789, or leave it blank.',
      }),
    ).toBeInTheDocument();
    // The address's own code, which is Canadian and well formed, is not in the summary.
    expect(within(summary).queryByText(/A1A 1A1/)).not.toBeInTheDocument();
    expect(registerSent(calls)).toBe(false);
  });

  it('a well-formed code is sent as typed, and the box is sent explicitly', async () => {
    const user = userEvent.setup();
    const { calls } = renderRegister();
    await fillAccountDetails(user);
    await fillAddress(user, addressGroup(), { postal: 'l4w1v2' });
    await submit(user);
    await screen.findByRole('heading', { name: 'Check your email', level: 1 });
    const body = registerBody(calls);
    expect(body.customer['pickup_address.1.postal_code']).toBe('l4w1v2');
    expect(body.billing_same_as_shipping).toBe(true);
  });

  it('a blank code is still no error', async () => {
    const user = userEvent.setup();
    const { calls } = renderRegister();
    await fillAccountDetails(user);
    await fillAddress(user, addressGroup(), { country: 'US' });
    await submit(user);
    await screen.findByRole('heading', { name: 'Check your email', level: 1 });
    expect(registerBody(calls).customer['pickup_address.1.postal_code']).toBeUndefined();
  });

  it('changing the country to Vietnam lifts the check', async () => {
    const user = userEvent.setup();
    const { calls } = renderRegister();
    await fillAccountDetails(user);
    await fillAddress(user, addressGroup(), { country: 'VN', postal: '12345' });
    await submit(user);
    await screen.findByRole('heading', { name: 'Check your email', level: 1 });
    expect(registerBody(calls).customer['pickup_address.1.postal_code']).toBe('12345');
  });
});
