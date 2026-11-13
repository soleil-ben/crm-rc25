/**
 * Phase 14: staff edit a customer's milestone email choices (13F) and the invoice due days
 * (13E finance settings). Mocked API; demo data only.
 */

import { describe, expect, it } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { SessionProvider } from '../src/app/SessionContext.jsx';
import { NotificationChoicesCard } from '../src/features/customers/NotificationChoicesCard.jsx';
import { FinanceSettingsCard } from '../src/features/finance/FinancePage.jsx';
import { renderWithProviders, stubFetch } from './utils.jsx';

function session(permissions) {
  return {
    path: '/auth/me',
    body: {
      user: { id: 1, full_name: 'Demo Ops', email: 'ops@demo.example.com', role: 'operations' },
      permissions,
      environment: 'test',
      is_demo_environment: false,
    },
  };
}

const CUSTOMER = { id: 101, public_id: 'CUS-000101', full_name: 'Demo Customer', merged_into_customer_id: null };
const PREFS = { preferences: { received: true, in_transit: true, out_for_delivery: false, delivered: true } };

function renderChoices(permissions, server = { preferences: { ...PREFS.preferences } }) {
  const calls = { sent: null };
  stubFetch([
    session(permissions),
    {
      path: '/customers/101/notification-preferences',
      method: 'PATCH',
      body: (init) => {
        calls.sent = JSON.parse(init.body);
        return { preferences: { ...PREFS.preferences, ...calls.sent.preferences } };
      },
    },
    { path: '/customers/101/notification-preferences', body: () => structuredClone(server) },
  ]);
  const { queryClient } = renderWithProviders(
    <SessionProvider>
      <NotificationChoicesCard customer={CUSTOMER} />
    </SessionProvider>,
  );
  calls.queryClient = queryClient;
  return calls;
}

describe('Customer milestone email choices', () => {
  it('shows the four choices and saves them on the customer’s behalf', async () => {
    const user = userEvent.setup();
    const calls = renderChoices(['shipment:read', 'customer:read', 'tracking:write']);
    const outForDelivery = await screen.findByRole('checkbox', { name: 'Out for delivery' });
    expect(outForDelivery).not.toBeChecked();
    // RC-UAT-25 item 5 (Ben, 2026-10-25): "Received at Solaris" now reads "Received at warehouse".
    expect(screen.getByRole('checkbox', { name: 'Received at warehouse' })).toBeChecked();
    await user.click(outForDelivery);
    await user.click(screen.getByRole('checkbox', { name: 'Delivered' }));
    await user.click(screen.getByRole('button', { name: 'Save email choices' }));
    // Only the two choices that changed are sent (Phase 14 review).
    await waitFor(() =>
      expect(calls.sent).toEqual({ preferences: { out_for_delivery: true, delivered: false } }),
    );
    const saved = await screen.findByText('Email choices saved.');
    await waitFor(() => expect(saved.closest('[tabindex="-1"]')).toHaveFocus());
  });

  it('keeps Save disabled until something changes, and again after saving', async () => {
    const user = userEvent.setup();
    renderChoices(['shipment:read', 'customer:read', 'tracking:write']);
    const box = await screen.findByRole('checkbox', { name: 'In transit' });
    const save = screen.getByRole('button', { name: 'Save email choices' });
    expect(save).toBeDisabled();
    await user.click(box);
    expect(save).toBeEnabled();
    await user.click(box);
    expect(save).toBeDisabled();
  });

  it('a refetch refreshes untouched choices and keeps an unsaved edit', async () => {
    const user = userEvent.setup();
    const server = { preferences: { ...PREFS.preferences } };
    const calls = renderChoices(['shipment:read', 'customer:read', 'tracking:write'], server);
    const inTransit = await screen.findByRole('checkbox', { name: 'In transit' });
    await user.click(inTransit); // now off, unsaved
    server.preferences = { ...server.preferences, delivered: false };
    calls.queryClient.invalidateQueries({ queryKey: ['customer-notification-preferences'] });
    await waitFor(() => expect(screen.getByRole('checkbox', { name: 'Delivered' })).not.toBeChecked());
    expect(inTransit).not.toBeChecked();
    await user.click(screen.getByRole('button', { name: 'Save email choices' }));
    await waitFor(() => expect(calls.sent).toEqual({ preferences: { in_transit: false } }));
  });

  it('is read-only without tracking:write', async () => {
    renderChoices(['shipment:read', 'customer:read']);
    const box = await screen.findByRole('checkbox', { name: 'In transit' });
    expect(box).toBeDisabled();
    expect(screen.queryByRole('button', { name: 'Save email choices' })).toBeNull();
    expect(screen.getByText('Changing these needs the tracking permission.')).toBeInTheDocument();
  });
});

const FINANCE = { invoice_due_days: 14, tax_status: 'review_pending', updated_at: '2026-10-20T10:00:00' };

function renderFinance(permissions) {
  const calls = { sent: null };
  stubFetch([
    session(permissions),
    {
      path: '/finance/settings',
      method: 'PATCH',
      body: (init) => {
        calls.sent = JSON.parse(init.body);
        return { ...FINANCE, ...calls.sent };
      },
    },
    { path: '/finance/settings', body: FINANCE },
  ]);
  renderWithProviders(
    <SessionProvider>
      <FinanceSettingsCard />
    </SessionProvider>,
  );
  return calls;
}

describe('Invoice terms', () => {
  it('saves the due days, refusing a number out of range first', async () => {
    const user = userEvent.setup();
    const calls = renderFinance(['financial:read', 'settings:manage']);
    const days = await screen.findByRole('textbox', { name: /Invoice due after/ });
    await waitFor(() => expect(days).toHaveValue('14'));
    await user.clear(days);
    await user.type(days, '400');
    await user.click(screen.getByRole('button', { name: 'Save invoice terms' }));
    expect(screen.getByText('Enter a whole number of days from 0 to 365.')).toBeInTheDocument();
    expect(days).toHaveFocus();
    expect(calls.sent).toBeNull();
    await user.clear(days);
    await user.type(days, '30');
    await user.click(screen.getByRole('button', { name: 'Save invoice terms' }));
    await waitFor(() => expect(calls.sent).toEqual({ invoice_due_days: 30 }));
    expect(await screen.findByText('Invoice terms saved.')).toBeInTheDocument();
  });

  it('words the tax setting instead of showing its code', async () => {
    renderFinance(['financial:read']);
    await screen.findByRole('textbox', { name: /Invoice due after/ });
    expect(await screen.findByText(/Tax: Chosen on each invoice/)).toBeInTheDocument();
    expect(screen.queryByText(/per_invoice|review_pending/)).toBeNull();
  });

  it('is read-only without settings:manage', async () => {
    renderFinance(['financial:read']);
    const days = await screen.findByRole('textbox', { name: /Invoice due after/ });
    expect(days).toHaveAttribute('readonly');
    expect(screen.queryByRole('button', { name: 'Save invoice terms' })).toBeNull();
  });
});
