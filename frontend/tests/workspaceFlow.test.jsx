/**
 * Workspace redesign (owner, 2026-11-04; DEC-0272): master → pieces → customers.
 * Mocked API throughout; demo data only.
 */

import { describe, expect, it } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {
  AddCustomerForm,
  PieceSection,
  membersByPiece,
  piecesOf,
} from '../src/features/workspace/MasterPieces.jsx';
import { suggestRules } from '../src/features/workspace/FeePicker.jsx';
import { previewCw } from '../src/features/workspace/workspaceFormat.js';
import { renderWithProviders, stubFetch } from './utils.jsx';

const MASTER = {
  id: 7,
  public_id: 'CON-000007',
  solaris_service: 'air_standard',
  solaris_service_label: 'Kango Air Standard',
  origin: 'HCM',
  state: 'open',
  vendor_reference: 'AWB-DEMO',
  actual_weight_kg: '21',
  length_cm: null,
  width_cm: null,
  height_cm: null,
  members: [
    { shipment_id: 11, public_id: 'STCA-000201', customer_name: 'Demo Anh' },
    { shipment_id: 12, public_id: 'STCA-000202', customer_name: 'Demo Binh' },
    { shipment_id: 13, public_id: 'STCA-000203', customer_name: 'Demo Chau' },
  ],
};

describe('pieces and their customers', () => {
  it('uses the master’s own weights as piece 1 when no carton is recorded', () => {
    const pieces = piecesOf(MASTER, []);
    expect(pieces).toHaveLength(1);
    expect(pieces[0]).toMatchObject({ sequence: 1, weight_kg: '21', legacy: true });
  });

  it('puts every customer in piece 1 on a one-piece master', () => {
    const { byPiece, unassigned } = membersByPiece(MASTER, piecesOf(MASTER, []), {});
    expect(byPiece[1]).toHaveLength(3);
    expect(unassigned).toEqual([]);
  });

  it('groups customers by piece and keeps the unplaced ones apart', () => {
    const pieces = [{ sequence: 1 }, { sequence: 2 }];
    const { byPiece, unassigned } = membersByPiece(MASTER, pieces, { 11: 1, 12: 2 });
    expect(byPiece[1].map((m) => m.shipment_id)).toEqual([11]);
    expect(byPiece[2].map((m) => m.shipment_id)).toEqual([12]);
    expect(unassigned.map((m) => m.shipment_id)).toEqual([13]);
  });

  it('previews VW and CW while typing (divisor 6000)', () => {
    expect(previewCw({ weight_kg: '10', length_cm: '60', width_cm: '50', height_cm: '40' })).toEqual({
      vw: 20,
      cw: 20,
    });
    expect(previewCw({ weight_kg: '25' })).toEqual({ vw: null, cw: 25 });
    expect(previewCw({})).toEqual({ vw: null, cw: null });
  });
});

describe('surcharge suggestions from the item name', () => {
  const rules = [
    { section: 'hcm_air', stt: 4, name: 'Mỹ phẩm, son môi', raw_note: null, pricing_status: 'priced' },
    { section: 'hcm_air', stt: 5, name: 'Pin sạc dự phòng', raw_note: 'Power bank', pricing_status: 'priced' },
    { section: 'hcm_air', stt: 6, name: 'Thực phẩm khô', raw_note: null, pricing_status: 'unpriced' },
  ];

  it('matches a phrase of the rule name, accent-insensitively', () => {
    const [hit] = suggestRules('Son moi Dior', rules);
    expect(hit.rule.stt).toBe(4);
    expect(hit.why).toBe('son moi');
  });

  it('matches a word of the item name in the rule note', () => {
    expect(suggestRules('Xiaomi power bank 20000', rules).map((s) => s.rule.stt)).toEqual([5]);
  });

  it('never suggests a rule that cannot be picked, nor on an empty name', () => {
    expect(suggestRules('thuc pham kho', rules)).toEqual([]);
    expect(suggestRules('', rules)).toEqual([]);
  });
});

const DETAIL = {
  base_vnd: '3900000',
  base_basis: 'AIR-CAD zone 2 on 30 kg',
  packages: [
    { sequence: 1, raw_kg: '18', billed_kg: '18', members: [11, 12] },
    { sequence: 2, raw_kg: '12', billed_kg: '12', members: [13] },
  ],
  members: {
    11: { public_id: 'STCA-000201', cw_kg: '10' },
    12: { public_id: 'STCA-000202', cw_kg: '9' },
    13: { public_id: 'STCA-000203', cw_kg: '12' },
  },
};
const ESTIMATE = { method_detail: DETAIL, members: [], fees: [], blocking: [], provisional: [] };

function pieceRoutes(extra = []) {
  return [
    ...extra,
    { path: '/consolidations/7/manual-pricing', body: {} },
    { path: '/shipments/', body: [] },
    { path: '/tariffs/versions', body: { items: [] } },
    { path: '/consolidations/7', body: {} },
  ];
}

describe('a master piece', () => {
  it('shows its CW, tracking, the base cost and a gap note that is not a problem', async () => {
    stubFetch(pieceRoutes());
    const pieces = [
      { sequence: 1, weight_kg: '17', length_cm: '60', width_cm: '50', height_cm: '36' },
      { sequence: 2, weight_kg: '12' },
    ];
    renderWithProviders(
      <PieceSection
        master={MASTER}
        pieces={pieces}
        piece={pieces[0]}
        members={MASTER.members.slice(0, 2)}
        estimate={ESTIMATE}
        packagesData={{ tracking: { 1: 'PUR-1' }, notes: {}, packed: {}, members: {} }}
        section="hcm_air"
        versionId={4}
        editable
        itemsLocked={false}
      />,
    );
    expect(screen.getByRole('heading', { name: 'Master piece #1' })).toBeInTheDocument();
    expect(screen.getByLabelText(/Last-mile tracking, piece 1/)).toHaveValue('PUR-1');
    expect(screen.getByText('3,900,000 VND')).toBeInTheDocument();
    // 10 + 9 = 19 kg of customers in an 18 kg piece: information, not an error.
    const note = screen.getByRole('note');
    expect(note).toHaveTextContent('This piece is 18 kg; its customers add up to 19 kg');
    expect(screen.queryByRole('alert')).toBeNull();
    expect(screen.getByRole('heading', { name: 'Customers in piece 1 (2)' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Add customer to piece 1' })).toBeInTheDocument();
  });

  it('saves a piece’s last-mile tracking', async () => {
    const user = userEvent.setup();
    let sent = null;
    stubFetch(
      pieceRoutes([
        {
          path: '/consolidations/7/packages/2/tracking',
          method: 'PATCH',
          body: (init) => {
            sent = JSON.parse(init.body);
            return { tracking: { 2: sent.last_mile_tracking } };
          },
        },
      ]),
    );
    const pieces = [{ sequence: 1, weight_kg: '17' }, { sequence: 2, weight_kg: '12' }];
    renderWithProviders(
      <PieceSection
        master={MASTER}
        pieces={pieces}
        piece={pieces[1]}
        members={[]}
        estimate={ESTIMATE}
        packagesData={{ tracking: {}, notes: {}, packed: {}, members: {} }}
        section="hcm_air"
        versionId={4}
        editable
        itemsLocked={false}
      />,
    );
    await user.type(screen.getByLabelText(/Last-mile tracking, piece 2/), 'PUR-2');
    await user.click(screen.getByRole('button', { name: 'Save tracking' }));
    await waitFor(() => expect(sent).toEqual({ last_mile_tracking: 'PUR-2' }));
    // An empty piece of a multi-piece master can be removed; piece 2 has no base-cost block.
    expect(screen.getByRole('button', { name: 'Remove piece' })).toBeInTheDocument();
    expect(screen.queryByText('Vendor base cost (whole master)')).toBeNull();
  });
});

describe('adding a customer to a piece', () => {
  const CUSTOMER = {
    id: 40,
    public_id: 'STCA-C40',
    full_name: 'Demo Dung',
    phone_entered: '+1 416 555 0100',
    city: 'Toronto',
    country_code: 'CA',
  };
  const ADDRESSES = [
    { id: 90, role: 'sender', contact_name: 'Demo Sender VN', country_code: 'VN', is_default_sender: true, is_archived: false },
    { id: 91, role: 'recipient', contact_name: 'Demo Dung', city: 'Mississauga', country_code: 'CA', is_default_recipient: true, is_archived: false },
  ];

  it('finds the profile, fills the parties from it and books into the piece', async () => {
    const user = userEvent.setup();
    let sent = null;
    stubFetch([
      { path: '/customers/40/addresses', body: ADDRESSES },
      { path: '/customers', body: { items: [CUSTOMER], total: 1 } },
      {
        path: '/consolidations/7/customers',
        method: 'POST',
        status: 201,
        body: (init) => {
          sent = JSON.parse(init.body);
          return MASTER;
        },
      },
    ]);
    let done = false;
    renderWithProviders(<AddCustomerForm master={MASTER} sequence={2} onDone={() => (done = true)} />);
    expect(screen.getByRole('heading', { name: 'Add a customer to piece 2' })).toBeInTheDocument();
    await user.type(screen.getByLabelText('Customer'), 'Dung');
    const results = await screen.findByRole('list', { name: 'Matching customers' });
    await user.click(within(results).getByRole('button', { name: 'Choose' }));
    expect(await screen.findByLabelText(/Sender name/)).toHaveValue('Demo Sender VN');
    expect(screen.getByLabelText(/Recipient city/)).toHaveValue('Mississauga');

    const submit = screen.getByRole('button', { name: 'Add customer' });
    expect(submit).toBeDisabled();
    await user.type(screen.getByLabelText(/Reference code/), 'SELLER-9');
    await user.type(screen.getByLabelText(/Gross weight/), '5');
    await user.type(screen.getByLabelText(/^Length/), '40');
    await user.type(screen.getByLabelText(/^Width/), '30');
    await user.type(screen.getByLabelText(/^Height/), '30');
    expect(screen.getByText(/Chargeable weight 6 kg/)).toBeInTheDocument();
    await user.type(screen.getByLabelText(/^Item 1/), 'Mỹ phẩm');
    // The row suggests the cosmetics surcharge only as information before adding.
    await user.clear(screen.getByLabelText(/^Quantity/));
    await user.type(screen.getByLabelText(/^Quantity/), '2');
    await user.click(screen.getByRole('button', { name: 'Add another item' }));
    await user.type(screen.getByLabelText(/^Item 2/), 'Clothes');
    await user.click(submit);
    await waitFor(() => expect(done).toBe(true));
    expect(sent).toMatchObject({
      customer_id: 40,
      carton_sequence: 2,
      reference_code: 'SELLER-9',
      weight_kg: '5',
      length_cm: '40',
      items: [{ description: 'Mỹ phẩm', quantity: '2' }, { description: 'Clothes', quantity: '1' }],
      sender: { address_id: 90, name: 'Demo Sender VN', country_code: 'VN' },
      recipient: { address_id: 91, name: 'Demo Dung', city: 'Mississauga', country_code: 'CA' },
    });
  }, 15000);

  it('creates a new profile in a quick form when none is found', async () => {
    const user = userEvent.setup();
    let created = null;
    stubFetch([
      { path: '/customers/41/addresses', body: [] },
      {
        path: '/customers',
        method: 'POST',
        status: 201,
        body: (init) => {
          created = JSON.parse(init.body);
          return { id: 41, public_id: 'STCA-C41', full_name: created.full_name, city: created.city, country_code: 'CA' };
        },
      },
      { path: '/customers', body: { items: [], total: 0 } },
    ]);
    renderWithProviders(<AddCustomerForm master={MASTER} sequence={1} onDone={() => {}} />);
    await user.type(screen.getByLabelText('Customer'), 'Demo New');
    expect(await screen.findByText('No customer found. Create a new profile.')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'New customer profile' }));
    const dialog = await screen.findByRole('dialog', { name: 'New customer profile' });
    const fullName = within(dialog).getByLabelText(/Full name/);
    expect(fullName).toHaveValue('Demo New');
    // The dialog moves focus to its first field once it opens; type after that.
    await waitFor(() => expect(fullName).toHaveFocus());
    await user.type(within(dialog).getByLabelText(/^City/), 'Ottawa');
    await user.click(within(dialog).getByRole('button', { name: 'Create profile' }));
    await waitFor(() =>
      expect(created).toEqual({ full_name: 'Demo New', city: 'Ottawa', country_code: 'CA', primary_route_group: 'VCA' }),
    );
    // Back in the form, with the new customer chosen and the recipient filled from it.
    expect(await screen.findByLabelText(/Recipient city/)).toHaveValue('Ottawa');
    expect(screen.getByLabelText(/Recipient name/)).toHaveValue('Demo New');
  }, 15000);
});
