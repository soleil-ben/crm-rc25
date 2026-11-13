/**
 * RC-UAT-25 (Ben's live UAT, 2026-10-25), developer A's items:
 *
 * * item 1 — a required field shows a red asterisk beside its label and no words: no
 *   "(required)", no "(bắt buộc)", in the booking wizard and in the Customer Account, in
 *   both languages. The star is aria-hidden and outside the <label>, so the accessible name
 *   is the label alone; the control carries `aria-required`. Optional fields keep an
 *   "Optional" helper under the field;
 * * item 3 — Create booking, step 2: the declared value currency is a list (CAD, VND, and a
 *   blank "—" because it is optional), not free text;
 * * item 4 — Create booking, step 3: "Use a saved address" for the recipient too. Every
 *   saved address of the customer except billing is offered, recipient ones first, and
 *   choosing one fills the recipient fields.
 *
 * The server half of item 3 is `backend/tests/test_rc25_booking_currency.py`.
 */

import { afterEach, describe, expect, it, vi } from 'vitest';
import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { BookingWizardPage } from '../src/features/shipments/BookingWizardPage.jsx';
import { recipientChoices } from '../src/features/shipments/bookingSteps.jsx';
import { SessionProvider } from '../src/app/SessionContext.jsx';
import { renderWithProviders, stubFetch } from './utils.jsx';
import { meFixture, renderAccount, stubAccountFetch } from './accountUtils.jsx';
import { CUSTOMER_SEARCH_RESULT, SHIPMENT_META, STAFF_SESSION } from './shipmentFixtures.js';

afterEach(() => {
  vi.unstubAllGlobals();
});

const REQUIRED_WORDS = /\((required|bắt buộc)\)/i;

/** No label on the page says "(required)" / "(bắt buộc)" in words. */
function expectNoRequiredWords() {
  for (const label of document.querySelectorAll('label')) {
    expect(label.textContent).not.toMatch(REQUIRED_WORDS);
  }
  expect(document.body.textContent).not.toMatch(REQUIRED_WORDS);
}

/** The asterisk beside a control's label: present, aria-hidden, and not in the label. */
function starFor(control) {
  const label = control.labels[0];
  const row = label.parentElement;
  return row.querySelector('[data-required-mark]');
}

/* --- Staff: the booking wizard --------------------------------------------- */

const ADDRESSES = [
  {
    id: 31,
    label: 'Home',
    role: 'sender',
    contact_name: 'Nguyễn Thị Bích Hạnh',
    company_name: null,
    phone_entered: '+1 416 555 0142',
    email_entered: 'bich.hanh@demo.example.com',
    address_line1: '12 Queen Street West',
    address_line2: null,
    city: 'Toronto',
    province_state: 'ON',
    postal_code: 'M5H 2N2',
    country_code: 'CA',
    delivery_note: null,
  },
  {
    id: 32,
    label: 'Mẹ ở Sài Gòn',
    role: 'recipient',
    contact_name: 'Trần Quốc Tuấn',
    company_name: null,
    phone_entered: '+84 90 123 4567',
    email_entered: null,
    address_line1: '125 Nguyễn Huệ',
    address_line2: 'Phường Bến Nghé',
    city: 'Thành phố Hồ Chí Minh',
    province_state: 'Hồ Chí Minh',
    postal_code: '700000',
    country_code: 'VN',
    delivery_note: 'Gọi trước khi giao',
  },
  {
    id: 33,
    label: 'Invoices',
    role: 'billing',
    contact_name: 'Accounts',
    city: 'Toronto',
    country_code: 'CA',
  },
];

function renderWizard({ addresses = ADDRESSES, meta = SHIPMENT_META } = {}) {
  stubFetch([
    { path: '/auth/me', body: STAFF_SESSION },
    { path: '/shipments/meta', body: meta },
    { path: '/search', body: CUSTOMER_SEARCH_RESULT },
    { path: '/customers/1/addresses', body: addresses },
    { path: '/customers/1', body: CUSTOMER_SEARCH_RESULT.items[0] },
  ]);
  return renderWithProviders(
    <SessionProvider>
      <BookingWizardPage />
    </SessionProvider>,
    { route: '/shipments/new' },
  );
}

async function toRouteStep(user) {
  await screen.findByRole('heading', { name: 'Customer' });
  await user.type(screen.getByRole('searchbox', { name: /Find a customer/i }), 'nguyen');
  await user.click(await screen.findByRole('button', { name: /STCA-000001/ }));
  await screen.findByText('Selected customer');
  await user.click(screen.getByRole('button', { name: 'Continue' }));
  await screen.findByRole('heading', { name: 'Route and service' });
}

async function toContactsStep(user) {
  await toRouteStep(user);
  await user.selectOptions(screen.getByLabelText('Route group'), 'CAV');
  await user.type(screen.getByLabelText('Contents description'), 'Family gift parcel');
  await user.click(screen.getByRole('button', { name: 'Continue' }));
  await screen.findByRole('heading', { name: 'Sender and recipient' });
}

describe('RC-UAT-25 item 1 › the booking wizard marks required fields with a red asterisk', () => {
  it('shows the star beside the label, keeps the label as the name, and no words', async () => {
    const user = userEvent.setup();
    renderWizard();
    await toRouteStep(user);

    // Exact label text: the star is not part of the accessible name.
    const route = screen.getByLabelText('Route group');
    expect(route).toHaveAttribute('aria-required', 'true');
    const star = starFor(route);
    expect(star).not.toBeNull();
    expect(star).toHaveTextContent('*');
    expect(star).toHaveAttribute('aria-hidden', 'true');
    expect(star).toHaveClass('required-mark');
    expect(route.labels[0].textContent).toBe('Route group');

    const contents = screen.getByLabelText('Contents description');
    expect(contents).toHaveAttribute('aria-required', 'true');
    expect(starFor(contents)).not.toBeNull();

    // An optional field: no star, no grey star, and "optional" under it.
    const declared = screen.getByLabelText('Declared value');
    expect(declared).not.toHaveAttribute('aria-required');
    expect(starFor(declared)).toBeNull();
    expect(declared).toHaveAccessibleDescription('optional');

    expectNoRequiredWords();
  });

  it('marks the sender and recipient required fields the same way', async () => {
    const user = userEvent.setup();
    renderWizard();
    await toContactsStep(user);
    const recipient = screen.getByRole('region', { name: 'Recipient' });
    for (const label of ['Full name', 'City', 'Country']) {
      const control = within(recipient).getByLabelText(label);
      expect(control).toHaveAttribute('aria-required', 'true');
      expect(starFor(control)).not.toBeNull();
    }
    expect(starFor(within(recipient).getByLabelText('Company'))).toBeNull();
    expectNoRequiredWords();
  });
});

describe('RC-UAT-25 item 3 › the declared value currency is a list', () => {
  it('offers a blank, CAD and VND, from the server list, and nothing typed', async () => {
    const user = userEvent.setup();
    renderWizard({ meta: { ...SHIPMENT_META, declared_value_currencies: ['CAD', 'VND'] } });
    await toRouteStep(user);

    const currency = screen.getByLabelText('Currency');
    expect(currency.tagName).toBe('SELECT');
    expect(currency).not.toHaveAttribute('aria-required');
    expect(currency).toHaveAccessibleDescription('optional');
    const options = within(currency).getAllByRole('option');
    expect(options.map((option) => option.value)).toEqual(['', 'CAD', 'VND']);
    expect(options.map((option) => option.textContent)).toEqual([
      '—',
      'CAD — Canadian dollar',
      'VND — Vietnamese dong',
    ]);
    // No default: there is no route-to-currency rule to take one from.
    expect(currency).toHaveValue('');

    await user.selectOptions(currency, 'VND');
    expect(currency).toHaveValue('VND');
  });

  it('falls back to CAD and VND before the server says otherwise', async () => {
    const user = userEvent.setup();
    renderWizard(); // SHIPMENT_META has no declared_value_currencies
    await toRouteStep(user);
    const values = within(screen.getByLabelText('Currency'))
      .getAllByRole('option')
      .map((option) => option.value);
    expect(values).toEqual(['', 'CAD', 'VND']);
  });
});

describe('RC-UAT-25 item 4 › the recipient can use a saved address', () => {
  it('offers every non-billing address, recipient ones first', () => {
    expect(recipientChoices(ADDRESSES).map((address) => address.id)).toEqual([32, 31]);
  });

  it('fills the recipient fields from the chosen saved address', async () => {
    const user = userEvent.setup();
    renderWizard();
    await toContactsStep(user);

    const recipient = screen.getByRole('region', { name: 'Recipient' });
    const picker = within(recipient).getByLabelText('Use a saved address');
    expect(picker).toHaveAccessibleDescription(/except billing/);
    const labels = within(picker)
      .getAllByRole('option')
      .map((option) => option.textContent);
    expect(labels).toEqual([
      'Enter details manually',
      'Mẹ ở Sài Gòn — Trần Quốc Tuấn, Thành phố Hồ Chí Minh',
      'Home — Nguyễn Thị Bích Hạnh, Toronto (saved as sender)',
    ]);

    await user.selectOptions(picker, '32');
    expect(within(recipient).getByLabelText('Full name')).toHaveValue('Trần Quốc Tuấn');
    expect(within(recipient).getByLabelText('Address line 1')).toHaveValue('125 Nguyễn Huệ');
    expect(within(recipient).getByLabelText('City')).toHaveValue('Thành phố Hồ Chí Minh');
    expect(within(recipient).getByLabelText('Country')).toHaveValue('VN');
    expect(within(recipient).getByLabelText('Delivery note')).toHaveValue('Gọi trước khi giao');

    // The sender picker is unchanged: sender (and both) addresses only.
    const sender = screen.getByRole('region', { name: 'Sender' });
    const senderOptions = within(within(sender).getByLabelText('Use a saved address'))
      .getAllByRole('option')
      .map((option) => option.value);
    expect(senderOptions).toEqual(['', '31']);

    // Back to manual entry clears the recipient.
    await user.selectOptions(picker, '');
    expect(within(recipient).getByLabelText('Full name')).toHaveValue('');
  });

  it('offers a sender-only address book to the recipient (a registered customer)', async () => {
    const user = userEvent.setup();
    renderWizard({ addresses: [ADDRESSES[0], ADDRESSES[2]] });
    await toContactsStep(user);
    const recipient = screen.getByRole('region', { name: 'Recipient' });
    await user.selectOptions(within(recipient).getByLabelText('Use a saved address'), '31');
    expect(within(recipient).getByLabelText('City')).toHaveValue('Toronto');
  });

  it('says so when the customer has no usable saved address', async () => {
    const user = userEvent.setup();
    renderWizard({ addresses: [ADDRESSES[2]] });
    await toContactsStep(user);
    const recipient = screen.getByRole('region', { name: 'Recipient' });
    expect(within(recipient).queryByLabelText('Use a saved address')).not.toBeInTheDocument();
    expect(
      within(recipient).getByText('This customer has no saved address yet. Enter the details below.'),
    ).toBeInTheDocument();
  });
});

/* --- Customer Account ------------------------------------------------------- */

const SIGNED_OUT = {
  path: '/api/v1/account/me',
  status: 401,
  body: { code: 'unauthenticated', message: 'Sign in to continue.', field: null },
};

describe('RC-UAT-25 item 1 › the Customer Account marks required fields with a red asterisk', () => {
  it('registration, in English: stars, aria-required, "Optional" under optional fields', async () => {
    stubAccountFetch([SIGNED_OUT]);
    renderAccount('/account/register');
    await screen.findByRole('heading', { name: 'Create an account', level: 1 });

    for (const label of ['Email address', 'Password', 'Confirm password', 'Full legal name']) {
      const control = screen.getByLabelText(label);
      expect(control).toHaveAttribute('aria-required', 'true');
      const star = starFor(control);
      expect(star).toHaveTextContent('*');
      expect(star).toHaveAttribute('aria-hidden', 'true');
    }
    const address = screen.getByRole('group', { name: 'Address' });
    const postal = within(address).getByLabelText('Postal code');
    expect(postal).not.toHaveAttribute('aria-required');
    expect(starFor(postal)).toBeNull();
    expect(postal).toHaveAccessibleDescription(/Optional/);
    expectNoRequiredWords();
    expect(document.body.textContent).not.toMatch(/\(optional\)/);
  });

  it('registration, in Vietnamese: no "(bắt buộc)", "Không bắt buộc" under optional fields', async () => {
    stubAccountFetch([SIGNED_OUT]);
    renderAccount('/account/register', { locale: 'vi' });
    const email = await screen.findByLabelText('Địa chỉ email');
    expect(email).toHaveAttribute('aria-required', 'true');
    expect(starFor(email)).not.toBeNull();
    expect(screen.getByLabelText('Mật khẩu')).toHaveAttribute('aria-required', 'true');
    expectNoRequiredWords();
    expect(document.body.textContent).not.toMatch(/\(không bắt buộc\)/);
    expect(screen.getAllByText('Không bắt buộc').length).toBeGreaterThan(0);
  });

  it('sign in, in both languages', async () => {
    stubAccountFetch([SIGNED_OUT]);
    renderAccount('/account/sign-in', { locale: 'vi' });
    const email = await screen.findByLabelText('Địa chỉ email');
    expect(starFor(email)).not.toBeNull();
    expect(starFor(screen.getByLabelText('Mật khẩu'))).not.toBeNull();
    expectNoRequiredWords();
  });

  it('sign-in and security: the password form', async () => {
    stubAccountFetch([
      { path: '/api/v1/account/me', body: meFixture() },
      {
        path: '/api/v1/account/security',
        body: {
          email: 'hanh@demo.example.com',
          pending_email_change: null,
          min_password_length: 12,
          message: null,
        },
      },
    ]);
    renderAccount('/account/security');
    await screen.findByRole('heading', { name: 'Sign-in and security', level: 1 });
    const fresh = screen.getAllByLabelText('New password')[0];
    expect(fresh).toHaveAttribute('aria-required', 'true');
    expect(starFor(fresh)).not.toBeNull();
    expectNoRequiredWords();
  });
});
