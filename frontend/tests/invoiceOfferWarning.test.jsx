/**
 * Phase 17 (UAT dry run): Issue invoice stays allowed for a quote version whose offer staff
 * withdrew or the customer declined, but warns first, naming the offer's state.
 */

import { describe, expect, it } from 'vitest';
import { screen } from '@testing-library/react';
import { SessionProvider } from '../src/app/SessionContext.jsx';
import { InvoiceLink } from '../src/features/workspace/InvoiceLink.jsx';
import { renderWithProviders, stubFetch } from './utils.jsx';

const OPS = ['shipment:read', 'financial:read', 'financial:write', 'tariff:read'];

function session() {
  return {
    path: '/auth/me',
    body: {
      user: {
        id: 1,
        full_name: 'Test Person',
        email: 'person@demo.example.com',
        role: 'operations',
        initials: 'TP',
        timezone: 'America/Toronto',
        locale: 'en',
      },
      permissions: OPS,
      environment: 'test',
      is_demo_environment: false,
    },
  };
}

const FINALIZED = { id: 9, version: 2, status: 'finalized' };

function render(offers) {
  stubFetch([
    { path: '/shipments/5/quote-offers', body: offers },
    { path: '/shipments/5/invoice', body: null },
    session(),
  ]);
  renderWithProviders(
    <SessionProvider>
      <InvoiceLink
        consolidationId={3}
        shipmentId={5}
        customerLabel="Lan Tran"
        refresh={() => {}}
        finalized={FINALIZED}
      />
    </SessionProvider>,
  );
}

describe('Issue invoice after a withdrawn or declined quote', () => {
  it('warns, naming the state, and still offers the button', async () => {
    render([{ id: 41, quote_version_id: 9, version: 2, status: 'withdrawn' }]);
    expect(
      await screen.findByText(/Quote v2 was sent to the customer and is now Withdrawn/),
    ).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Issue invoice — Lan Tran' })).toBeInTheDocument();
  });

  it('warns for a declined quote', async () => {
    render([{ id: 41, quote_version_id: 9, version: 2, status: 'declined' }]);
    expect(await screen.findByText(/is now Declined/)).toBeInTheDocument();
  });

  it('says nothing for an accepted quote or an earlier version', async () => {
    render([
      { id: 42, quote_version_id: 9, version: 2, status: 'accepted' },
      { id: 40, quote_version_id: 8, version: 1, status: 'withdrawn' },
    ]);
    expect(await screen.findByRole('button', { name: 'Issue invoice — Lan Tran' })).toBeInTheDocument();
    expect(screen.queryByText(/was sent to the customer and is now/)).not.toBeInTheDocument();
  });
});
