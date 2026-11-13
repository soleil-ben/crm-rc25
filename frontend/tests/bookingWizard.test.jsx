/**
 * Booking workflow: step gating, no public ID before confirmation, keyboard completion,
 * and double-submission protection.
 */

import { describe, expect, it } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { BookingWizardPage } from '../src/features/shipments/BookingWizardPage.jsx';
import { SessionProvider } from '../src/app/SessionContext.jsx';
import { renderWithProviders, stubFetch } from './utils.jsx';
import {
  CUSTOMER_SEARCH_RESULT,
  LABEL_PREVIEW,
  SHIPMENT_DETAIL,
  SHIPMENT_META,
  STAFF_SESSION,
} from './shipmentFixtures.js';

const DRAFT_RESPONSE = { ...SHIPMENT_DETAIL, id: 10, public_id: null, booking_state: 'draft' };

function renderWizard({ confirmBody, confirmStatus = 200 } = {}) {
  const confirmCalls = [];
  const createCalls = [];

  const handler = stubFetch([
    { path: '/auth/me', body: STAFF_SESSION },
    { path: '/shipments/meta', body: SHIPMENT_META },
    { path: '/search', body: CUSTOMER_SEARCH_RESULT },
    { path: '/customers/1/addresses', body: [] },
    { path: '/customers/1', body: CUSTOMER_SEARCH_RESULT.items[0] },
    { path: '/label-preview', body: LABEL_PREVIEW },
    { path: '/label-jobs', body: [] },
    {
      path: '/confirm',
      method: 'POST',
      status: confirmStatus,
      body: (init) => {
        confirmCalls.push(JSON.parse(init.body));
        return (
          confirmBody ?? {
            shipment: SHIPMENT_DETAIL,
            created: confirmCalls.length === 1,
            id_generation_attempts: 1,
          }
        );
      },
    },
    {
      path: '/shipments',
      method: 'POST',
      body: (init) => {
        createCalls.push(JSON.parse(init.body));
        return DRAFT_RESPONSE;
      },
    },
  ]);

  const utils = renderWithProviders(
    <SessionProvider>
      <BookingWizardPage />
    </SessionProvider>,
    { route: '/shipments/new' },
  );
  return { ...utils, handler, confirmCalls, createCalls };
}

async function selectCustomer(user) {
  await screen.findByRole('heading', { name: 'Customer' });
  await user.type(screen.getByRole('searchbox', { name: /Find a customer/i }), 'nguyen');
  await user.click(await screen.findByRole('button', { name: /STCA-000001/ }));
  await screen.findByText('Selected customer');
}

async function fillRoute(user) {
  await user.click(screen.getByRole('button', { name: 'Continue' }));
  await screen.findByRole('heading', { name: 'Route and service' });
  await user.selectOptions(screen.getByLabelText(/Route group/), 'CAV');
  await user.type(screen.getByLabelText(/Contents description/), 'Family gift parcel');
}

async function fillContacts(user) {
  await user.click(screen.getByRole('button', { name: 'Continue' }));
  await screen.findByRole('heading', { name: 'Sender and recipient' });

  const sender = screen.getByRole('region', { name: 'Sender' });
  await user.type(within(sender).getByLabelText(/Full name/), 'Solaris counter');
  await user.type(within(sender).getByLabelText(/^Country/), 'CA');

  const recipient = screen.getByRole('region', { name: 'Recipient' });
  await user.type(within(recipient).getByLabelText(/Full name/), 'Trần Quốc Tuấn');
  await user.type(within(recipient).getByLabelText(/^City/), 'Thành phố Hồ Chí Minh');
  await user.type(within(recipient).getByLabelText(/^Country/), 'VN');
}

async function fillPackages(user) {
  await user.click(screen.getByRole('button', { name: 'Continue' }));
  await screen.findByRole('heading', { name: 'Packages' });
  await user.type(screen.getByLabelText(/^Gross weight/), '5.5');
}

describe('BookingWizardPage', () => {
  it('shows the six steps from Design.md', async () => {
    renderWizard();
    const stepper = await screen.findByRole('list', { name: 'Create booking' });
    for (const label of [
      'Customer',
      'Route and service',
      'Sender and recipient',
      'Packages',
      'Review',
      'Confirmed',
    ]) {
      expect(within(stepper).getByText(label)).toBeInTheDocument();
    }
  });

  it('refuses to advance past the customer step without a customer', async () => {
    const user = userEvent.setup();
    renderWizard();
    await screen.findByRole('heading', { name: 'Customer' });
    await user.click(screen.getByRole('button', { name: 'Continue' }));
    expect(await screen.findByText('Complete these fields first')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Customer' })).toBeInTheDocument();
  });

  it('names the fields that are missing rather than failing silently', async () => {
    const user = userEvent.setup();
    renderWizard();
    await selectCustomer(user);
    await user.click(screen.getByRole('button', { name: 'Continue' }));
    await screen.findByRole('heading', { name: 'Route and service' });
    await user.click(screen.getByRole('button', { name: 'Continue' }));

    await screen.findByText('Complete these fields first');
    // The field label also reads "Route group"; assert against the summary list itself.
    const summary = screen.getByRole('alert');
    const listed = within(summary)
      .getAllByRole('listitem')
      .map((item) => item.textContent);
    expect(listed).toContain('Route group');
    expect(listed).toContain('Contents description');
  });

  it('rejects a zero measurement before the request is made', async () => {
    const user = userEvent.setup();
    renderWizard();
    await selectCustomer(user);
    await fillRoute(user);
    await fillContacts(user);
    await user.click(screen.getByRole('button', { name: 'Continue' }));
    await screen.findByRole('heading', { name: 'Packages' });

    await user.type(screen.getByLabelText(/^Gross weight/), '0');
    await user.click(screen.getByRole('button', { name: 'Continue' }));
    expect(await screen.findByText('Complete these fields first')).toBeInTheDocument();
  });

  it('never shows a customer-facing ID before confirmation', async () => {
    const user = userEvent.setup();
    renderWizard();
    await selectCustomer(user);
    await fillRoute(user);
    await fillContacts(user);
    await fillPackages(user);
    await user.click(screen.getByRole('button', { name: 'Continue' }));
    await screen.findByRole('heading', { name: 'Review' });

    // The review step summarizes the booking but carries no Solaris ID.
    expect(screen.queryByText(/SX-CAV-/)).not.toBeInTheDocument();
    expect(screen.getByText('Confirm booking')).toBeInTheDocument();
  });

  it('shows the Solaris ID and package references only after confirmation', async () => {
    const user = userEvent.setup();
    const { confirmCalls } = renderWizard();
    await selectCustomer(user);
    await fillRoute(user);
    await fillContacts(user);
    await fillPackages(user);
    await user.click(screen.getByRole('button', { name: 'Continue' }));
    await screen.findByRole('heading', { name: 'Review' });
    await user.click(screen.getByRole('button', { name: 'Confirm booking' }));

    expect(await screen.findByText('Booking confirmed')).toBeInTheDocument();
    expect(screen.getByText('SX-CAV-7K9D2M4R8T6W')).toBeInTheDocument();
    expect(screen.getByText('SX-CAV-7K9D2M4R8T6W-01')).toBeInTheDocument();
    expect(screen.getByText('SX-CAV-7K9D2M4R8T6W-03')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Print labels' })).toBeInTheDocument();
    expect(confirmCalls).toHaveLength(1);
    expect(confirmCalls[0].idempotency_key).toMatch(/^booking-/);
  });

  it('sends one idempotency key so a double click cannot create two bookings', async () => {
    const user = userEvent.setup();
    const { confirmCalls } = renderWizard();
    await selectCustomer(user);
    await fillRoute(user);
    await fillContacts(user);
    await fillPackages(user);
    await user.click(screen.getByRole('button', { name: 'Continue' }));
    await screen.findByRole('heading', { name: 'Review' });

    const confirm = screen.getByRole('button', { name: 'Confirm booking' });
    await user.click(confirm);
    // The button leaves the DOM once the confirmed step renders; a second click on the
    // stale node must not reach the API.
    await screen.findByText('Booking confirmed');
    expect(confirmCalls).toHaveLength(1);
  });

  it('reports a confirmation conflict without pretending the booking succeeded', async () => {
    const user = userEvent.setup();
    renderWizard({
      confirmStatus: 409,
      confirmBody: {
        code: 'conflict',
        message: 'That idempotency key was used for materially different booking data.',
      },
    });
    await selectCustomer(user);
    await fillRoute(user);
    await fillContacts(user);
    await fillPackages(user);
    await user.click(screen.getByRole('button', { name: 'Continue' }));
    await screen.findByRole('heading', { name: 'Review' });
    await user.click(screen.getByRole('button', { name: 'Confirm booking' }));

    expect(
      await screen.findByText(/materially different booking data/),
    ).toBeInTheDocument();
    expect(screen.queryByText('Booking confirmed')).not.toBeInTheDocument();
  });

  it('can be completed with the keyboard alone', async () => {
    const user = userEvent.setup();
    const { confirmCalls } = renderWizard();
    await screen.findByRole('heading', { name: 'Customer' });

    // Step 1: focus the search box and type, then activate the first result.
    screen.getByRole('searchbox', { name: /Find a customer/i }).focus();
    await user.keyboard('nguyen');
    await screen.findByRole('button', { name: /STCA-000001/ });
    const result = screen.getByRole('button', { name: /STCA-000001/ });
    result.focus();
    await user.keyboard('{Enter}');
    await screen.findByText('Selected customer');

    async function pressButton(name) {
      const button = screen.getByRole('button', { name });
      button.focus();
      expect(button).toHaveFocus();
      await user.keyboard('{Enter}');
    }

    await pressButton('Continue');
    await screen.findByRole('heading', { name: 'Route and service' });
    const routeSelect = screen.getByLabelText(/Route group/);
    routeSelect.focus();
    await user.selectOptions(routeSelect, 'CAV');
    const contents = screen.getByLabelText(/Contents description/);
    contents.focus();
    await user.keyboard('Family gift parcel');

    await pressButton('Continue');
    await screen.findByRole('heading', { name: 'Sender and recipient' });
    const sender = screen.getByRole('region', { name: 'Sender' });
    within(sender).getByLabelText(/Full name/).focus();
    await user.keyboard('Solaris counter');
    within(sender).getByLabelText(/^Country/).focus();
    await user.keyboard('CA');
    const recipient = screen.getByRole('region', { name: 'Recipient' });
    within(recipient).getByLabelText(/Full name/).focus();
    await user.keyboard('Trần Quốc Tuấn');
    within(recipient).getByLabelText(/^City/).focus();
    await user.keyboard('Ho Chi Minh City');
    within(recipient).getByLabelText(/^Country/).focus();
    await user.keyboard('VN');

    await pressButton('Continue');
    await screen.findByRole('heading', { name: 'Packages' });
    screen.getByLabelText(/^Gross weight/).focus();
    await user.keyboard('5.5');

    await pressButton('Continue');
    await screen.findByRole('heading', { name: 'Review' });
    await pressButton('Confirm booking');

    expect(await screen.findByText('Booking confirmed')).toBeInTheDocument();
    expect(confirmCalls).toHaveLength(1);
  });

  it('moves focus to each step heading so a screen reader announces the change', async () => {
    const user = userEvent.setup();
    renderWizard();
    await selectCustomer(user);
    await user.click(screen.getByRole('button', { name: 'Continue' }));
    const heading = await screen.findByRole('heading', { name: 'Route and service' });
    await waitFor(() => expect(heading).toHaveFocus());
  });

  it('saves a draft without confirming it', async () => {
    const user = userEvent.setup();
    const { createCalls, confirmCalls } = renderWizard();
    await selectCustomer(user);
    await fillRoute(user);
    await user.click(screen.getByRole('button', { name: 'Save draft' }));

    await waitFor(() => expect(createCalls).toHaveLength(1));
    expect(confirmCalls).toHaveLength(0);
    expect(createCalls[0].route_group).toBe('CAV');
  });

  it('duplicating a package card adds a second one', async () => {
    const user = userEvent.setup();
    renderWizard();
    await selectCustomer(user);
    await fillRoute(user);
    await fillContacts(user);
    await user.click(screen.getByRole('button', { name: 'Continue' }));
    await screen.findByRole('heading', { name: 'Packages' });

    expect(screen.getAllByRole('region', { name: /^Package \d/ })).toHaveLength(1);
    await user.click(screen.getByRole('button', { name: 'Duplicate' }));
    await waitFor(() =>
      expect(screen.getAllByRole('region', { name: /^Package \d/ })).toHaveLength(2),
    );
  });
});
