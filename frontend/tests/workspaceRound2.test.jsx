/**
 * Workspace, owner review of 2026-11-05 (DEC-0273). Mocked API; demo data only.
 *
 * New master in two parts with a list of pieces; "Shipment" card; Save and Book at the
 * bottom; collapsible sections with expand / collapse all; every surcharge listed; better
 * suggestions ("mỹ phẩm"); remove an item (its fees first); edit a customer; the surcharge
 * list follows an origin change.
 */

import { describe, expect, it } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Route, Routes } from 'react-router-dom';
import { WorkspaceListPage } from '../src/features/workspace/WorkspaceListPage.jsx';
import { WorkspacePage } from '../src/features/workspace/WorkspacePage.jsx';
import { CustomerCard, EditCustomerForm } from '../src/features/workspace/CustomerCard.jsx';
import { FeePicker, suggestRules } from '../src/features/workspace/FeePicker.jsx';
import { renderWithProviders, stubFetch } from './utils.jsx';

function rule(stt, name, extra = {}) {
  return {
    id: stt,
    section: 'hcm_air',
    stt,
    name,
    raw_price_text: '30.000/kg',
    raw_note: null,
    basis: 'per_kg',
    scope: 'item',
    pricing_status: 'priced',
    unit_price_vnd: '30000',
    tiers: [],
    ...extra,
  };
}

const KANGO_LIKE = [
  rule(2, 'Pin Kèm thiết bị nhỏ 1-3 Kg', { pricing_status: 'tiered' }),
  rule(3, 'Pin Kèm thiết bị nhỏ 4-8 Kg', { pricing_status: 'tiered' }),
  rule(4, 'Pin kèm thiết bị lớn hoặc Sạc dự phòng', { pricing_status: 'manual_quote' }),
  rule(11, 'Nước hoa', { pricing_status: 'tiered' }),
  rule(43, 'Hàng Mỹ phẩm, TPCN ( nước ngoài )'),
  rule(44, 'Cây xanh', { pricing_status: 'not_applicable_canada' }),
];

describe('surcharge suggestions, after the review', () => {
  it('finds the cosmetics row from “mỹ phẩm” alone', () => {
    const [hit] = suggestRules('mỹ phẩm', KANGO_LIKE);
    expect(hit.rule.stt).toBe(43);
  });

  it('finds the battery rows from “pin”', () => {
    expect(suggestRules('pin', KANGO_LIKE).map((s) => s.rule.stt)).toEqual([2, 3, 4]);
  });

  it('finds perfume from a longer item name, never a rule that does not apply to Canada', () => {
    expect(suggestRules('Nuoc hoa Chanel 50ml', KANGO_LIKE).map((s) => s.rule.stt)).toEqual([11]);
    expect(suggestRules('cây xanh', KANGO_LIKE)).toEqual([]);
  });
});

describe('the surcharge list', () => {
  it('lists every surcharge of the section, with a count, not just twelve', async () => {
    const many = Array.from({ length: 30 }, (_, i) => rule(i + 1, `Demo surcharge ${i + 1}`));
    stubFetch([{ path: '/surcharges', body: { items: many } }]);
    renderWithProviders(
      <FeePicker shipmentId={1} item={{ id: 5 }} section="hcm_air" versionId={8} onAdded={() => {}} onCancel={() => {}} />,
    );
    expect(await screen.findByText('30 of 30 surcharges for SGN (Hồ Chí Minh City)')).toBeInTheDocument();
    const list = screen.getByRole('list', { name: /./ });
    expect(within(list).getAllByRole('listitem')).toHaveLength(30);
  });
});

describe('new master in two parts', () => {
  it('creates the shipment and every master piece of the list', async () => {
    const user = userEvent.setup();
    let created = null;
    let cartons = null;
    stubFetch([
      {
        path: '/consolidations/3/cartons',
        method: 'PATCH',
        body: (init) => {
          cartons = JSON.parse(init.body);
          return [];
        },
      },
      {
        path: '/consolidations',
        method: 'POST',
        status: 201,
        body: (init) => {
          created = JSON.parse(init.body);
          return { id: 3, members: [] };
        },
      },
      { path: '/consolidations', body: { items: [], total: 0 } },
    ]);
    renderWithProviders(
      <Routes>
        <Route path="/workspace" element={<WorkspaceListPage />} />
        <Route path="/workspace/:consolidationId" element={<p>Opened master</p>} />
      </Routes>,
      { route: '/workspace' },
    );
    await user.click(await screen.findByRole('button', { name: 'New master' }));
    expect(screen.getByRole('group', { name: 'Part 1 · Shipment' })).toBeInTheDocument();
    const part2 = screen.getByRole('group', { name: 'Part 2 · Master pieces' });
    await user.type(within(part2).getByLabelText('Gross weight (kg) — Master piece #1'), '20');
    await user.type(within(part2).getByLabelText('Length (cm) — Master piece #1'), '60');
    await user.type(within(part2).getByLabelText('Width (cm) — Master piece #1'), '50');
    await user.type(within(part2).getByLabelText('Height (cm) — Master piece #1'), '50');
    await user.click(within(part2).getByRole('button', { name: 'Add master piece' }));
    await user.type(within(part2).getByLabelText('Gross weight (kg) — Master piece #2'), '12');
    expect(within(part2).getByText('2 piece(s) · gross 32 kg · chargeable 37 kg')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Create master' }));
    expect(await screen.findByText('Opened master')).toBeInTheDocument();
    expect(created).toMatchObject({ actual_weight_kg: '20', length_cm: '60', carton_count: 2 });
    expect(cartons).toEqual({
      cartons: [{ weight_kg: '20', length_cm: '60', width_cm: '50', height_cm: '50' }, { weight_kg: '12' }],
    });
  }, 15000);
});

/* --- The whole page ------------------------------------------------------------------------ */

function pageRoutes({ origin, onPatch, onBook, blocking = [], placement = {}, cartons = null, members = null }) {
  const memberRows = members ?? [{ shipment_id: 9, public_id: 'SX-1', customer_name: 'Demo A' }];
  const master = () => ({
    id: 3,
    public_id: 'MST-3',
    solaris_service: 'air_standard',
    solaris_service_label: 'Kango Air Standard',
    origin: origin(),
    state: 'open',
    vendor_reference: 'AWB-1',
    members: memberRows,
  });
  return [
    {
      path: '/consolidations/3/pricing',
      body: {
        estimate: {
          members: [],
          fees: [],
          blocking,
          provisional: [],
          method_detail: {
            packages: [{ sequence: 1, raw_kg: '20', billed_kg: '20', members: [9] }],
            members: { 9: { public_id: 'SX-1', cw_kg: '10', quote_cad: '150.00' } },
            totals: { cost_cad: '100.00', quote_cad: '150.00', profit_cad: '50.00', surcharge_margin_cad: '0.00' },
            reconciled: true,
          },
        },
      },
    },
    { path: '/consolidations/3/cartons', body: cartons ?? [{ sequence: 1, weight_kg: '20', length_cm: '60', width_cm: '50', height_cm: '40' }] },
    { path: '/consolidations/3/packages', body: { notes: {}, members: placement, packed: {}, tracking: {} } },
    { path: '/consolidations/3/manual-pricing', body: {} },
    { path: '/consolidations/3/book', method: 'POST', body: () => { onBook(); return master(); } },
    { path: '/consolidations/3', method: 'PATCH', body: () => { onPatch(); return master(); } },
    { path: '/consolidations/3', body: () => master() },
    { path: '/shipments/9/items', body: [] },
    { path: '/shipments/9/fee-lines', body: [] },
    { path: '/shipments/9/quotes', body: [] },
    { path: '/shipments/10/items', body: [] },
    { path: '/shipments/10/fee-lines', body: [] },
    { path: '/shipments/10/quotes', body: [] },
    { path: '/vendor-invoices', body: [] },
    { path: '/surcharges', body: { items: [] } },
    { path: '/pricing/settings', body: { defaults_owner_confirmed: true } },
    { path: '/tariffs/versions', body: { items: [{ id: 7, status: 'active' }], total: 1 } },
    { path: '/fx/latest', body: {} },
    { path: '/auth/me', body: { user: { id: 1, role: 'admin' }, permissions: [] } },
  ];
}

function renderPage(routes, route = '/workspace/3') {
  const fetchMock = stubFetch(routes);
  renderWithProviders(
    <Routes>
      <Route path="/workspace" element={<p>Master list</p>} />
      <Route path="/workspace/:consolidationId" element={<WorkspacePage />} />
    </Routes>,
    { route },
  );
  return fetchMock;
}

const tree = () => screen.getByRole('navigation', { name: 'Master structure' });

describe('the workspace page (two panes, DEC-0277)', () => {
  it('opens on the shipment with its checks, and books from the summary bar', async () => {
    const user = userEvent.setup();
    let booked = false;
    renderPage(pageRoutes({ origin: () => 'HCM', onPatch: () => {}, onBook: () => (booked = true) }));
    expect(await screen.findByRole('heading', { name: 'Shipment' })).toBeInTheDocument();
    expect(await screen.findByRole('heading', { name: 'Check before booking' })).toBeInTheDocument();
    expect(screen.getByText('Master tracking (AWB) AWB-1 entered')).toBeInTheDocument();
    // The customer is in the tree with its quote; the whole master's screens too.
    expect(within(tree()).getByRole('button', { name: /Demo A/ })).toBeInTheDocument();
    expect(within(tree()).getByRole('button', { name: /Cost and quote/ })).toBeInTheDocument();

    const bar = screen.getByRole('region', { name: 'Master actions' });
    expect(within(bar).getByText('CAD 150.00')).toBeInTheDocument();
    await user.click(within(bar).getByRole('button', { name: 'Book with vendor' }));
    await waitFor(() => expect(booked).toBe(true));
    await user.click(within(bar).getByRole('button', { name: 'Save and close' }));
    expect(await screen.findByText('Master list')).toBeInTheDocument();
  }, 15000);

  it('shows one thing at a time: the cost and quote card from the tree', async () => {
    const user = userEvent.setup();
    renderPage(pageRoutes({ origin: () => 'HCM', onPatch: () => {}, onBook: () => {} }));
    await screen.findByRole('heading', { name: 'Shipment' });
    expect(screen.queryByRole('table', { name: 'Quote by customer' })).toBeNull();
    await user.click(within(tree()).getByRole('button', { name: /Cost and quote/ }));
    expect(await screen.findByRole('table', { name: 'Quote by customer' })).toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: 'Check before booking' })).toBeNull();
  }, 15000);

  it('asks before booking while problems are open, listing them', async () => {
    const user = userEvent.setup();
    let booked = false;
    renderPage(
      pageRoutes({
        origin: () => 'HCM',
        onPatch: () => {},
        onBook: () => (booked = true),
        blocking: [{ code: 'fee_unpriced', message: "SX-1: enter the item's weight (kg).", shipment_id: 9 }],
      }),
    );
    const bar = await screen.findByRole('region', { name: 'Master actions' });
    await user.click(await within(bar).findByRole('button', { name: 'Book (1 to fix)' }));
    const dialog = await screen.findByRole('dialog', { name: 'Book with errors still open?' });
    expect(within(dialog).getByText("SX-1: enter the item's weight (kg).")).toBeInTheDocument();
    expect(booked).toBe(false);
    // "Go and fix" opens the customer with the problem.
    await user.click(within(dialog).getByRole('button', { name: 'Go and fix' }));
    expect(await screen.findByText(/customer 1 of 1/)).toBeInTheDocument();
    expect(screen.getAllByText("SX-1: enter the item's weight (kg).").length).toBeGreaterThan(0);
    await user.click(within(bar).getByRole('button', { name: 'Book (1 to fix)' }));
    await user.click(await screen.findByRole('button', { name: 'Book anyway' }));
    await waitFor(() => expect(booked).toBe(true));
  }, 15000);

  it('marks a customer not placed in a piece and offers the piece', async () => {
    const user = userEvent.setup();
    renderPage(
      pageRoutes({
        origin: () => 'HCM',
        onPatch: () => {},
        onBook: () => {},
        cartons: [
          { sequence: 1, weight_kg: '20', length_cm: '60', width_cm: '50', height_cm: '40' },
          { sequence: 2, weight_kg: '10', length_cm: '40', width_cm: '40', height_cm: '40' },
        ],
        members: [
          { shipment_id: 9, public_id: 'SX-1', customer_name: 'Demo A' },
          { shipment_id: 10, public_id: 'SX-2', customer_name: 'Demo B' },
        ],
        placement: { 9: 1 },
      }),
    );
    expect(await screen.findByText('Not placed in a piece: Demo B')).toBeInTheDocument();
    await user.click(screen.getByText('Not placed in a piece: Demo B'));
    expect(await screen.findByRole('heading', { name: 'Place in a master piece' })).toBeInTheDocument();
    expect(screen.getByRole('combobox', { name: /Master piece/ })).toBeInTheDocument();
  }, 15000);

  it('asks before leaving a screen with unsaved typing', async () => {
    const user = userEvent.setup();
    renderPage(pageRoutes({ origin: () => 'HCM', onPatch: () => {}, onBook: () => {} }), '/workspace/3?sel=c9');
    await user.click(await screen.findByRole('button', { name: 'Add item' }));
    await user.type(screen.getByLabelText(/Description/), 'Áo khoác');
    expect(within(screen.getByRole('region', { name: 'Master actions' })).getByText(/Unsaved changes/)).toBeInTheDocument();
    await user.click(within(tree()).getByRole('button', { name: /^Shipment/ }));
    const dialog = await screen.findByRole('dialog', { name: 'Leave without saving?' });
    await user.click(within(dialog).getByRole('button', { name: 'Stay' }));
    expect(screen.getByLabelText(/Description/)).toHaveValue('Áo khoác');
    await user.click(within(tree()).getByRole('button', { name: /^Shipment/ }));
    await user.click(await screen.findByRole('button', { name: 'Leave without saving' }));
    expect(await screen.findByRole('heading', { name: 'Check before booking' })).toBeInTheDocument();
  }, 15000);

  it('reads the other origin’s surcharge list as soon as the origin changes', async () => {
    const user = userEvent.setup();
    let origin = 'HCM';
    const fetchMock = renderPage(
      pageRoutes({ origin: () => origin, onPatch: () => (origin = 'HAN'), onBook: () => {} }),
      '/workspace/3?sel=c9',
    );
    await waitFor(() =>
      expect(fetchMock.mock.calls.some(([u]) => String(u).includes('section=hcm_air'))).toBe(true),
    );
    await user.click(within(tree()).getByRole('button', { name: /^Shipment/ }));
    await user.click(await screen.findByRole('button', { name: 'Edit shipment' }));
    await user.selectOptions(screen.getByRole('combobox', { name: /Origin/ }), 'HAN');
    await user.click(screen.getByRole('button', { name: 'Save' }));
    await user.click(within(tree()).getByRole('button', { name: /Demo A/ }));
    await waitFor(() =>
      expect(fetchMock.mock.calls.some(([u]) => String(u).includes('section=han_air'))).toBe(true),
    );
  }, 15000);
});

/* --- One customer --------------------------------------------------------------------------- */

const MEMBER = { shipment_id: 9, public_id: 'SX-1', customer_name: 'Demo A' };

describe('a customer card', () => {
  it('removes an item, its fees first', async () => {
    const user = userEvent.setup();
    const calls = [];
    stubFetch([
      { path: '/shipments/9/items/50/remove', method: 'POST', body: () => { calls.push('item'); return {}; } },
      { path: '/shipments/9/fee-lines/70/remove', method: 'POST', body: () => { calls.push('fee'); return {}; } },
      { path: '/shipments/9/items', body: [{ id: 50, description: 'mỹ phẩm', quantity: '1', unit: 'piece', is_active: true }] },
      { path: '/shipments/9/fee-lines', body: [{ id: 70, item_id: 50, section: 'hcm_air', stt: 43, name: 'Hàng Mỹ phẩm', quantity: '1' }] },
      { path: '/shipments/9/quotes', body: [] },
      { path: '/surcharges', body: { items: KANGO_LIKE } },
    ]);
    renderWithProviders(
      <CustomerCard consolidationId={3} member={MEMBER} estimate={null} section="hcm_air" versionId={8} editable removable={false} />,
    );
    await user.click(await screen.findByRole('button', { name: 'Remove item — mỹ phẩm' }));
    expect(screen.getByText('Remove this item and its 1 fee(s)?')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Yes, remove' }));
    await waitFor(() => expect(calls).toEqual(['fee', 'item']));
  });

  it('suggests the cosmetics surcharge on a “mỹ phẩm” item with no fee yet', async () => {
    stubFetch([
      { path: '/shipments/9/items', body: [{ id: 50, description: 'mỹ phẩm', quantity: '1', unit: 'piece', is_active: true }] },
      { path: '/shipments/9/fee-lines', body: [] },
      { path: '/shipments/9/quotes', body: [] },
      { path: '/surcharges', body: { items: KANGO_LIKE } },
    ]);
    renderWithProviders(
      <CustomerCard consolidationId={3} member={MEMBER} estimate={null} section="hcm_air" versionId={8} editable removable={false} />,
    );
    expect(await screen.findByRole('button', { name: 'Review and add — Hàng Mỹ phẩm, TPCN ( nước ngoài )' })).toBeInTheDocument();
  });

  it('edits the reference, weights and piece', async () => {
    const user = userEvent.setup();
    let sent = null;
    stubFetch([
      { path: '/consolidations/3/customers/9', method: 'PATCH', body: (init) => { sent = JSON.parse(init.body); return {}; } },
      { path: '/shipments/9/packages', body: [{ id: 1, is_active: true, weight_kg: '10', length_cm: null, width_cm: null, height_cm: null }] },
      { path: '/shipments/9', body: { id: 9, booking_reference: 'OLD' } },
    ]);
    let done = false;
    renderWithProviders(
      <EditCustomerForm
        consolidationId={3}
        member={MEMBER}
        pieces={[{ sequence: 1 }, { sequence: 2 }]}
        currentPiece={1}
        weightsLocked={false}
        onDone={() => (done = true)}
      />,
    );
    const reference = await screen.findByLabelText('Reference code');
    expect(reference).toHaveValue('OLD');
    await user.clear(reference);
    await user.type(reference, 'NEW');
    const weight = screen.getByLabelText('Gross weight (kg)');
    await user.clear(weight);
    await user.type(weight, '12.5');
    await user.selectOptions(screen.getByLabelText('Piece'), '2');
    await user.click(screen.getByRole('button', { name: 'Save customer' }));
    await waitFor(() => expect(done).toBe(true));
    expect(sent).toEqual({ reference_code: 'NEW', weight_kg: '12.5', carton_sequence: 2 });
  });

  it('on a booked master sends the reference only, weights read-only', async () => {
    const user = userEvent.setup();
    let sent = null;
    stubFetch([
      { path: '/consolidations/3/customers/9', method: 'PATCH', body: (init) => { sent = JSON.parse(init.body); return {}; } },
      { path: '/shipments/9/packages', body: [{ id: 1, is_active: true, weight_kg: '10' }] },
      { path: '/shipments/9', body: { id: 9, booking_reference: null } },
    ]);
    renderWithProviders(
      <EditCustomerForm consolidationId={3} member={MEMBER} pieces={null} weightsLocked onDone={() => {}} />,
    );
    expect(await screen.findByText(/This master is booked/)).toBeInTheDocument();
    expect(screen.getByLabelText('Gross weight (kg)')).toHaveAttribute('readonly');
    await user.type(screen.getByLabelText('Reference code'), 'LABEL');
    await user.click(screen.getByRole('button', { name: 'Save customer' }));
    await waitFor(() => expect(sent).toEqual({ reference_code: 'LABEL' }));
  });
});

/* --- Item weights (DEC-0275) ------------------------------------------------------------------- */

describe('item weights for surcharges', () => {
  const BATTERY = rule(2, 'Pin Kèm thiết bị nhỏ 1-3 Kg', {
    pricing_status: 'tiered',
    basis: 'per_piece',
    scope: 'per_unit',
    above_top_tier: 'manual',
    tiers: [{ weight_to_kg: '3.5', price_vnd: '300000' }, { weight_to_kg: '8', price_vnd: '700000' }],
  });
  const DONG_Y = rule(32, 'Đông y, thuốc nam, thuốc bắc', { scope: 'full_carton' });

  it('asks the battery item’s weight, filled from the item', async () => {
    const user = userEvent.setup();
    stubFetch([{ path: '/surcharges', body: { items: [BATTERY] } }]);
    renderWithProviders(
      <FeePicker
        shipmentId={1}
        item={{ id: 5, weight_kg: '2' }}
        section="hcm_air"
        versionId={8}
        onAdded={() => {}}
        onCancel={() => {}}
      />,
    );
    await user.click(await screen.findByRole('button', { name: /Pin Kèm thiết bị nhỏ/ }));
    const weight = screen.getByLabelText(/Battery item weight/);
    expect(weight).toHaveValue('2');
    expect(screen.getByText(/From the item: 2 kg/)).toBeInTheDocument();
  });

  it('shows the item weight on a per-kg fee line that has none of its own', async () => {
    stubFetch([
      { path: '/shipments/9/items', body: [{ id: 50, description: 'thuốc', quantity: '1', unit: 'piece', weight_kg: '3', is_active: true }] },
      { path: '/shipments/9/fee-lines', body: [{ id: 70, item_id: 50, section: 'hcm_air', stt: 32, quantity: '1', weight_kg: null }] },
      { path: '/shipments/9/quotes', body: [] },
      { path: '/surcharges', body: { items: [DONG_Y] } },
    ]);
    renderWithProviders(
      <CustomerCard consolidationId={3} member={MEMBER} estimate={null} section="hcm_air" versionId={8} editable removable={false} />,
    );
    expect(await screen.findByText(/3 kg \(item weight\)/)).toBeInTheDocument();
  });
});

/* --- Per master piece and per shipment (DEC-0276) ------------------------------------------- */

describe('per-piece and per-shipment surcharges', () => {
  const NAIL = rule(1, 'Sơn móng tay', {
    pricing_status: 'tiered',
    basis: 'per_piece',
    scope: 'per_unit',
    allocation_class: 'PARCEL',
    above_top_tier: 'top',
    tiers: [
      { weight_to_kg: '5', price_vnd: '300000' },
      { weight_to_kg: '22', price_vnd: '500000' },
      { weight_to_kg: '30', price_vnd: '700000' },
    ],
  });
  const WOOD = rule(47, 'Phí hun trùng hàng gỗ', {
    basis: 'per_shipment',
    scope: 'per_shipment',
    allocation_class: 'WHOLE_MASTER',
    unit_price_vnd: '550000',
  });

  function picker() {
    return renderWithProviders(
      <FeePicker
        shipmentId={1}
        item={{ id: 5, weight_kg: '3' }}
        section="hcm_air"
        versionId={8}
        onAdded={() => {}}
        onCancel={() => {}}
      />,
    );
  }

  it('asks the nail-polish item weight, not a quantity, and explains the per-piece charge', async () => {
    const user = userEvent.setup();
    stubFetch([{ path: '/surcharges', body: { items: [NAIL] } }]);
    picker();
    await user.click(await screen.findByRole('button', { name: /Sơn móng tay/ }));
    expect(screen.getByLabelText(/Weight of this item/)).toHaveValue('3');
    expect(screen.queryByLabelText(/Quantity/)).not.toBeInTheDocument();
    expect(screen.getByText(/once per master piece, banded on all of this item/)).toBeInTheDocument();
  });

  it('explains that fumigation is charged once per shipment', async () => {
    const user = userEvent.setup();
    stubFetch([{ path: '/surcharges', body: { items: [WOOD] } }]);
    picker();
    await user.click(await screen.findByRole('button', { name: /hun trùng/ }));
    expect(screen.getByText(/once per shipment/)).toBeInTheDocument();
  });
});
