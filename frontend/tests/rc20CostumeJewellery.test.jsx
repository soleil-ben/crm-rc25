/**
 * Costume jewellery (HCM air row 27, quoted case by case): owner Ben, 2026-10-23 (DEC-0228).
 * Mocked API; demo data only.
 *
 * Staff enter both the vendor's cost (VND) and the customer price (CAD); both fields start
 * empty (no default); the line says what is still missing; Save sends only what changed.
 */

import { describe, expect, it } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { SessionProvider } from '../src/app/SessionContext.jsx';
import { CustomerCard, manualNeededKey } from '../src/features/workspace/CustomerCard.jsx';
import { FeePicker } from '../src/features/workspace/FeePicker.jsx';
import { renderWithProviders, stubFetch } from './utils.jsx';

const OPS = ['shipment:read', 'shipment:write', 'tariff:read', 'financial:read', 'financial:write'];

function sessionRoute() {
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

const JEWELLERY = {
  id: 27,
  section: 'hcm_air',
  stt: 27,
  name: 'Hàng mỹ ký (trang sức giả)',
  raw_price_text: '100-300.000/Kg',
  pricing_status: 'manual_quote',
  basis: 'manual_amount',
  scope: 'per_unit',
  unit_price_vnd: null,
  tiers: [],
};

function feeLine(extra = {}) {
  return {
    id: 5,
    item_id: 1,
    section: 'hcm_air',
    stt: 27,
    quantity: '1.00',
    weight_kg: null,
    manual_unit_price_vnd: null,
    customer_price_cad: null,
    created_at: '2026-10-23T10:00:00',
    removed_at: null,
    ...extra,
  };
}

function renderCard(line, onPatch) {
  stubFetch([
    {
      path: '/shipments/11/items',
      body: [{ id: 1, description: 'Earrings', quantity: '1', unit: 'piece', is_active: true }],
    },
    {
      path: '/shipments/11/fee-lines/5',
      method: 'PATCH',
      body: (init) => {
        onPatch?.(JSON.parse(init.body));
        return feeLine();
      },
    },
    { path: '/shipments/11/fee-lines', body: [line] },
    { path: '/tariffs/versions/1/surcharges', body: { items: [JEWELLERY], total: 1 } },
    { path: '/shipments/11/quotes', body: [] },
    sessionRoute(),
  ]);
  renderWithProviders(
    <SessionProvider>
      <CustomerCard
        consolidationId={3}
        member={{ shipment_id: 11, public_id: 'SX-VCA-AAAA11', customer_name: 'Lan Tran' }}
        estimate={null}
        section="hcm_air"
        versionId={1}
        editable
        removable={false}
      />
    </SessionProvider>,
  );
}

const COST = /Vendor cost \(VND\) — Hàng mỹ ký/;
const PRICE = /Customer price \(CAD\) — Hàng mỹ ký/;
const SAVE = /^Save — Hàng mỹ ký/;

describe('Costume jewellery: the vendor cost and the customer price', () => {
  it('names what is missing', () => {
    expect(manualNeededKey(feeLine())).toBe('workspace.manualNeededBoth');
    expect(manualNeededKey(feeLine({ customer_price_cad: '40.00' }))).toBe('workspace.manualNeededCost');
    expect(manualNeededKey(feeLine({ manual_unit_price_vnd: '450000.00' }))).toBe(
      'workspace.manualNeededPrice',
    );
    expect(
      manualNeededKey(feeLine({ manual_unit_price_vnd: '450000.00', customer_price_cad: '40.00' })),
    ).toBeNull();
  });

  it('shows two empty fields and saves both in one request', async () => {
    const user = userEvent.setup();
    let patched = null;
    renderCard(feeLine(), (body) => {
      patched = body;
    });
    expect(
      await screen.findByText(/Vendor cost \(VND\) and customer price \(CAD\) needed/),
    ).toBeInTheDocument();
    expect(screen.getByLabelText(COST)).toHaveValue('');
    expect(screen.getByLabelText(PRICE)).toHaveValue('');
    expect(screen.getByRole('button', { name: SAVE })).toBeDisabled();
    await user.type(screen.getByLabelText(COST), '450000');
    await user.type(screen.getByLabelText(PRICE), '49.99');
    await user.click(screen.getByRole('button', { name: SAVE }));
    await waitFor(() =>
      expect(patched).toEqual({ manual_unit_price_vnd: '450000', customer_price_cad: '49.99' }),
    );
  });

  it('names the customer price when only the vendor cost is stored, and sends only the price', async () => {
    const user = userEvent.setup();
    let patched = null;
    renderCard(feeLine({ manual_unit_price_vnd: '450000.00' }), (body) => {
      patched = body;
    });
    expect(await screen.findByText(/Customer price \(CAD\) needed/)).toBeInTheDocument();
    expect(screen.queryByText(/Vendor cost \(VND\) needed/)).not.toBeInTheDocument();
    expect(screen.getByLabelText(PRICE)).toHaveValue('');
    await user.type(screen.getByLabelText(PRICE), '40');
    await user.click(screen.getByRole('button', { name: SAVE }));
    await waitFor(() => expect(patched).toEqual({ customer_price_cad: '40' }));
  });

  it('names the vendor cost when only the customer price is stored', async () => {
    renderCard(feeLine({ customer_price_cad: '40.00' }));
    expect(await screen.findByText(/Vendor cost \(VND\) needed/)).toBeInTheDocument();
  });

  it('shows both values once entered', async () => {
    renderCard(feeLine({ manual_unit_price_vnd: '450000.00', customer_price_cad: '49.99' }));
    expect(await screen.findByText(/Customer price \(CAD\) CAD\s49\.99/)).toBeInTheDocument();
    expect(screen.queryByText(/needed/)).not.toBeInTheDocument();
  });

  it('Add fee offers both fields, empty, and sends the customer price', async () => {
    const user = userEvent.setup();
    let body = null;
    stubFetch([
      { path: '/tariffs/versions/1/surcharges', body: { items: [JEWELLERY], total: 1 } },
      {
        path: '/shipments/11/fee-lines',
        method: 'POST',
        status: 201,
        body: (init) => {
          body = JSON.parse(init.body);
          return { id: 5 };
        },
      },
      sessionRoute(),
    ]);
    renderWithProviders(
      <SessionProvider>
        <FeePicker
          shipmentId={11}
          item={{ id: 1, description: 'Earrings', weight_kg: '2.000' }}
          section="hcm_air"
          versionId={1}
          onAdded={() => {}}
          onCancel={() => {}}
        />
      </SessionProvider>,
    );
    await user.click(await screen.findByRole('button', { name: /mỹ ký/ }));
    expect(screen.getByLabelText(/Vendor cost \(VND\)/)).toHaveValue('');
    expect(screen.getByLabelText(/Customer price \(CAD\)/)).toHaveValue('');
    await user.type(screen.getByLabelText(/Customer price \(CAD\)/), '25.50');
    await user.click(screen.getByRole('button', { name: 'Add fee' }));
    await waitFor(() => expect(body).not.toBeNull());
    expect(body).toMatchObject({ section: 'hcm_air', stt: 27, customer_price_cad: '25.50' });
    expect(body.manual_unit_price_vnd).toBeUndefined();
  });
});
