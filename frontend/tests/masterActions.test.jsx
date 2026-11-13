/**
 * Phase 14, the workspace: a master milestone that fans out to every member, completing
 * and cancelling a master behind a confirmation, editing an item, and the printable
 * customer quote. Mocked API; demo data only.
 */

import { describe, expect, it } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Route, Routes } from 'react-router-dom';
import { MasterActionsPanel } from '../src/features/workspace/MasterActions.jsx';
import { EditItemForm } from '../src/features/workspace/CustomerCard.jsx';
import { QuotePrintPage } from '../src/features/workspace/QuotePrintPage.jsx';
import { QuotePanel } from '../src/features/workspace/QuotePanel.jsx';
import { I18nProvider } from '../src/i18n/index.jsx';
import { SessionProvider } from '../src/app/SessionContext.jsx';
import { renderWithProviders, stubFetch } from './utils.jsx';

function master(overrides = {}) {
  return {
    id: 3,
    public_id: 'CON-000003',
    state: 'booked',
    members: [
      { shipment_id: 11, public_id: 'SX-VCA-AAAA11' },
      { shipment_id: 12, public_id: 'SX-VCA-AAAA12' },
    ],
    ...overrides,
  };
}

describe('Master milestone', () => {
  it('records once for the master and reports what each shipment received', async () => {
    const user = userEvent.setup();
    let sent = null;
    stubFetch([
      {
        path: '/consolidations/3/events',
        method: 'POST',
        status: 201,
        body: (init) => {
          sent = JSON.parse(init.body);
          return {
            event_type: 'in_transit',
            occurred_at: '2026-10-20T10:00:00',
            applied: ['SX-VCA-AAAA11'],
            duplicates: [],
            refused: [{ shipment: 'SX-VCA-AAAA12', reason: 'This shipment is cancelled.' }],
          };
        },
      },
    ]);
    renderWithProviders(<MasterActionsPanel master={master()} />);
    await user.click(screen.getByRole('button', { name: 'Record a milestone' }));
    const form = screen.getByRole('form', { name: 'Record a milestone for the whole master' });
    expect(within(form).getByRole('combobox', { name: /Event type/ })).toHaveFocus();
    expect(within(form).getByText(/every shipment of this master \(2 now\)/)).toBeInTheDocument();

    // Own wording: required when publishing without a standard update.
    await user.selectOptions(within(form).getByRole('combobox', { name: /Standard update/ }), '');
    await user.click(within(form).getByRole('button', { name: 'Record for all shipments' }));
    expect(
      within(form).getByText('Write the update the customer will see, or choose a standard update.'),
    ).toBeInTheDocument();
    expect(sent).toBeNull();

    await user.type(within(form).getByRole('textbox', { name: /Public wording/ }), 'Your parcel left Vietnam.');
    await user.click(within(form).getByRole('button', { name: 'Record for all shipments' }));
    await waitFor(() => expect(sent).not.toBeNull());
    expect(sent).toMatchObject({
      event_type: 'in_transit',
      is_public_update: true,
      public_update_text: 'Your parcel left Vietnam.',
    });
    expect(sent.public_update_template_key).toBeUndefined();
    const outcome = await screen.findByRole('list', { name: 'What each shipment received' });
    expect(within(outcome).getByText(/Updated: SX-VCA-AAAA11/)).toBeInTheDocument();
    expect(within(outcome).getByText(/Refused: SX-VCA-AAAA12 — This shipment is cancelled./)).toBeInTheDocument();
    await waitFor(() => expect(outcome.closest('[tabindex="-1"]')).toHaveFocus());
  });

  it('sends a standard update by its key, never with typed text', async () => {
    const user = userEvent.setup();
    let sent = null;
    stubFetch([
      {
        path: '/consolidations/3/events',
        method: 'POST',
        status: 201,
        body: (init) => {
          sent = JSON.parse(init.body);
          return { event_type: 'in_transit', occurred_at: '2026-10-20T10:00:00', applied: ['SX-VCA-AAAA11', 'SX-VCA-AAAA12'], duplicates: [], refused: [] };
        },
      },
    ]);
    renderWithProviders(<MasterActionsPanel master={master()} />);
    await user.click(screen.getByRole('button', { name: 'Record a milestone' }));
    await user.click(screen.getByRole('button', { name: 'Record for all shipments' }));
    await waitFor(() => expect(sent).not.toBeNull());
    expect(sent.is_public_update).toBe(true);
    expect(sent.public_update_template_key).toBeTruthy();
    expect(sent.public_update_text).toBeUndefined();
  });

  it('is closed for a completed master, and needs a member first', () => {
    renderWithProviders(<MasterActionsPanel master={master({ state: 'completed' })} />);
    expect(screen.getByText('This master is closed; it takes no more milestones.')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Record a milestone' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Cancel master' })).toBeNull();
  });

  it('asks for a member before a milestone on an empty master', () => {
    renderWithProviders(<MasterActionsPanel master={master({ state: 'open', members: [] })} />);
    expect(screen.getByText('Add a shipment before recording a milestone.')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Record a milestone' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Complete master' })).toBeNull();
    expect(screen.getByRole('button', { name: 'Cancel master' })).toBeInTheDocument();
  });
});

describe('Phase 14 review: master panel', () => {
  it('says plainly when the milestone reached no shipment at all', async () => {
    const user = userEvent.setup();
    stubFetch([
      {
        path: '/consolidations/3/events',
        method: 'POST',
        status: 201,
        body: {
          event_type: 'in_transit',
          occurred_at: '2026-10-20T10:00:00',
          applied: [],
          duplicates: [],
          refused: [
            { shipment: 'SX-VCA-AAAA11', reason: 'This shipment is cancelled.' },
            { shipment: 'SX-VCA-AAAA12', reason: 'This shipment is cancelled.' },
          ],
        },
      },
    ]);
    renderWithProviders(<MasterActionsPanel master={master()} />);
    await user.click(screen.getByRole('button', { name: 'Record a milestone' }));
    await user.click(screen.getByRole('button', { name: 'Record for all shipments' }));
    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('In transit was not recorded on any shipment');
    expect(alert).toHaveTextContent('Refused: SX-VCA-AAAA11 — This shipment is cancelled.');
    expect(alert).toHaveTextContent('Refused: SX-VCA-AAAA12');
    expect(screen.queryByText(/recorded on the master/)).toBeNull();
  });

  it('hides the actions a role cannot use', async () => {
    stubFetch([
      {
        path: '/auth/me',
        body: {
          user: { id: 2, full_name: 'Viewer', email: 'viewer@demo.example.com', role: 'operations' },
          permissions: ['shipment:read', 'tariff:read', 'tracking:write'],
          environment: 'test',
          is_demo_environment: false,
        },
      },
    ]);
    renderWithProviders(
      <SessionProvider>
        <MasterActionsPanel master={master()} />
      </SessionProvider>,
    );
    expect(await screen.findByRole('button', { name: 'Record a milestone' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Complete master' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Cancel master' })).toBeNull();
  });

  it('warns before cancelling a master whose customers hold a finalised quote or an accepted offer', async () => {
    const user = userEvent.setup();
    stubFetch([]);
    const { queryClient } = renderWithProviders(<MasterActionsPanel master={master()} />);
    // On the page the customer cards keep these loaded; here nothing observes them.
    queryClient.setQueryDefaults(['workspace'], { gcTime: Infinity });
    queryClient.setQueryData(['workspace', '3', 'quotes', 11], [{ version: 1, status: 'finalized' }]);
    queryClient.setQueryData(['workspace', '3', 'offers', 12], [{ id: 5, status: 'accepted' }]);
    await user.click(screen.getByRole('button', { name: 'Cancel master' }));
    const dialog = screen.getByRole('dialog', { name: 'Cancel CON-000003' });
    const list = within(dialog).getByRole('list', { name: 'Customers already quoted' });
    expect(list).toHaveTextContent('SX-VCA-AAAA11: finalised quote v1');
    expect(list).toHaveTextContent('SX-VCA-AAAA12: the customer accepted the quote');
    expect(within(dialog).getByText(/does not withdraw these quotes/)).toBeInTheDocument();
  });
});

describe('Completing and cancelling a master', () => {
  it('completes only after the confirmation', async () => {
    const user = userEvent.setup();
    let completed = false;
    stubFetch([
      {
        path: '/consolidations/3/complete',
        method: 'POST',
        body: () => {
          completed = true;
          return master({ state: 'completed' });
        },
      },
    ]);
    renderWithProviders(<MasterActionsPanel master={master()} />);
    await user.click(screen.getByRole('button', { name: 'Complete master' }));
    const dialog = screen.getByRole('dialog', { name: 'Complete CON-000003' });
    expect(completed).toBe(false);
    await user.click(within(dialog).getByRole('button', { name: 'Yes, complete it' }));
    await waitFor(() => expect(completed).toBe(true));
    expect(await screen.findByText('The master is completed.')).toBeInTheDocument();
  });

  it('cancels only with a reason, and keeping the master sends nothing', async () => {
    const user = userEvent.setup();
    let reason = null;
    stubFetch([
      {
        path: '/consolidations/3/cancel',
        method: 'POST',
        body: (init) => {
          reason = JSON.parse(init.body).reason;
          return master({ state: 'cancelled' });
        },
      },
    ]);
    renderWithProviders(<MasterActionsPanel master={master()} />);
    await user.click(screen.getByRole('button', { name: 'Cancel master' }));
    let dialog = screen.getByRole('dialog', { name: 'Cancel CON-000003' });
    expect(within(dialog).getByText(/Every shipment on it \(2\)/)).toBeInTheDocument();
    await user.click(within(dialog).getByRole('button', { name: 'Keep the master' }));
    expect(screen.queryByRole('dialog')).toBeNull();

    await user.click(screen.getByRole('button', { name: 'Cancel master' }));
    dialog = screen.getByRole('dialog', { name: 'Cancel CON-000003' });
    await user.click(within(dialog).getByRole('button', { name: 'Cancel the master' }));
    expect(within(dialog).getByText('Say why the master is being cancelled.')).toBeInTheDocument();
    expect(reason).toBeNull();
    await user.type(within(dialog).getByRole('textbox', { name: /Why is the master/ }), 'Vendor flight cancelled');
    await user.click(within(dialog).getByRole('button', { name: 'Cancel the master' }));
    await waitFor(() => expect(reason).toBe('Vendor flight cancelled'));
    expect(await screen.findByText('The master is cancelled and its shipments are released.')).toBeInTheDocument();
  });
});

describe('Editing an item', () => {
  const ITEM = {
    id: 7,
    sequence: 1,
    description: 'Watch',
    quantity: '1.000',
    unit: 'piece',
    weight_kg: '0.400',
    declared_value: null,
    declared_value_currency: null,
    package_id: null,
    is_active: true,
    notes: null,
  };

  it('sends only the changed fields and clears an emptied weight', async () => {
    const user = userEvent.setup();
    let sent = null;
    let done = false;
    stubFetch([
      {
        path: '/shipments/11/items/7',
        method: 'PATCH',
        body: (init) => {
          sent = JSON.parse(init.body);
          return { ...ITEM, ...sent };
        },
      },
    ]);
    renderWithProviders(
      <EditItemForm shipmentId={11} item={ITEM} onDone={() => (done = true)} onCancel={() => {}} />,
    );
    const description = screen.getByRole('textbox', { name: /Description/ });
    expect(description).toHaveFocus();
    await user.clear(description);
    await user.type(description, 'Wrist watch');
    await user.clear(screen.getByRole('textbox', { name: /Weight/ }));
    await user.click(screen.getByRole('button', { name: 'Save item' }));
    await waitFor(() => expect(sent).toEqual({ description: 'Wrist watch', weight_kg: null }));
    await waitFor(() => expect(done).toBe(true));
  });

  it('offers the units the server accepts', () => {
    renderWithProviders(<EditItemForm shipmentId={11} item={ITEM} onDone={() => {}} onCancel={() => {}} />);
    const unit = screen.getByRole('combobox', { name: /Unit/ });
    expect(within(unit).getAllByRole('option').map((o) => o.value)).toEqual([
      'piece',
      'pair',
      'box',
      'bottle',
      'set',
      'kg',
      'carton',
      'other',
    ]);
    expect(unit).toHaveValue('piece');
  });

  it('names a bad quantity beside the field and sends nothing', async () => {
    const user = userEvent.setup();
    const fetchMock = stubFetch([]);
    renderWithProviders(<EditItemForm shipmentId={11} item={ITEM} onDone={() => {}} onCancel={() => {}} />);
    const quantity = screen.getByRole('textbox', { name: /Quantity/ });
    await user.clear(quantity);
    await user.type(quantity, '0');
    await user.click(screen.getByRole('button', { name: 'Save item' }));
    expect(screen.getByText('Enter a quantity above zero.')).toBeInTheDocument();
    expect(quantity).toHaveFocus();
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

const DOCUMENT = {
  company_name: 'Solaris Express Inc.',
  company_trade_name: 'Solaris Express',
  company_business_number: '795093756RT0001',
  company_address: '2446 Cawthra Road B1U8, Mississauga ON L5A 3K6',
  customer_name: 'Demo Customer',
  customer_reference: 'CUS-000101',
  shipment_reference: 'SX-VCA-AAAA11',
  version: 1,
  finalized_at: '2026-10-20T10:00:00',
  service: 'Air Standard',
  billable_weight_kg: '12.000',
  rate_per_kg_cad: '18.00',
  base_charge_cad: '216.00',
  surcharges: [{ name: 'Đồng hồ thường', amount_cad: '3.92' }],
  total_cad: '219.92',
  currency: 'CAD',
  tax_included: false,
  // RC-UAT-21 (P-9 stand-in): the invoice's GST/HST rule. VN -> CA is zero-rated.
  tax: { band: 'international', label: null, rate_percent: 0 },
};

function renderPrint(locale = 'en') {
  stubFetch([{ path: '/shipments/11/quotes/1/document', body: DOCUMENT }]);
  return renderWithProviders(
    <I18nProvider initialLocale={locale}>
      <Routes>
        <Route path="/workspace/quotes/:shipmentId/:version/print" element={<QuotePrintPage />} />
      </Routes>
    </I18nProvider>,
    { route: '/workspace/quotes/11/1/print?from=3' },
  );
}

describe('Printable customer quote', () => {
  it('shows the company, the customer, the service and the charges before tax, and no cost', async () => {
    renderPrint();
    const doc = await screen.findByRole('article', { name: 'Quote' });
    const text = doc.textContent;
    expect(text).toContain('Solaris Express Inc.');
    expect(text).toContain('795093756RT0001');
    expect(text).toContain('2446 Cawthra Road B1U8, Mississauga ON L5A 3K6');
    expect(text).toContain('Demo Customer (CUS-000101)');
    expect(text).toContain('Air Standard');
    // Currency amounts use a no-break space after the code.
    expect(text).toMatch(/Air freight, 12 kg at CAD\s18\.00 per kg/);
    expect(text).toContain('Đồng hồ thường');
    expect(within(doc).getByText('Total')).toBeInTheDocument();
    expect(text).toMatch(/CAD\s219\.92/);
    expect(text).toContain('Zero-rated (0 %)');
    expect(text).not.toContain('added on the invoice');
    for (const word of [/cost/i, /VND/, /markup/i, /\bFX\b/, /exchange/i, /vendor/i, /kango/i, /margin/i]) {
      expect(text).not.toMatch(word);
    }
    expect(screen.getByRole('link', { name: 'Back to the workspace' })).toHaveAttribute('href', '/workspace/3');
    expect(screen.getByRole('button', { name: 'Print' })).toBeInTheDocument();
  });

  it('is worded in the staff language: Vietnamese', async () => {
    renderPrint('vi');
    const doc = await screen.findByRole('article', { name: 'Báo giá' });
    expect(doc.textContent).toContain('Tổng cộng');
    expect(doc.textContent).toContain('Thuế suất 0 (0 %)');
    expect(doc.textContent).toContain('Mã số doanh nghiệp 795093756RT0001');
  });
});

describe('Printable quote, superseded', () => {
  it('still prints a superseded version and says which version replaced it', async () => {
    stubFetch([
      {
        path: '/shipments/11/quotes/1/document',
        body: { ...DOCUMENT, status: 'superseded', superseded_by_version: 2 },
      },
    ]);
    renderWithProviders(
      <Routes>
        <Route path="/workspace/quotes/:shipmentId/:version/print" element={<QuotePrintPage />} />
      </Routes>,
      { route: '/workspace/quotes/11/1/print?from=3' },
    );
    const note = await screen.findByRole('note');
    expect(note).toHaveTextContent('Superseded by v2');
  });

  it('shows no superseded line on a current version', async () => {
    renderPrint();
    await screen.findByRole('article', { name: 'Quote' });
    expect(screen.queryByRole('note')).toBeNull();
  });
});

describe('Quote panel print link', () => {
  it('offers the printable quote for the finalised version', async () => {
    const version = {
      id: 21,
      shipment_id: 11,
      version: 1,
      status: 'finalized',
      solaris_service: 'air_standard',
      default_rate_cad: '18.00',
      selling_rate_cad: '18.00',
      rate_confirmed: true,
      billable_weight_kg: '12.000',
      total_revenue_cad: '219.92',
      allocated_cost_cad: '150.00',
      gross_profit_cad: '69.92',
      blocking: [],
      provisional: [],
      lines: [],
    };
    stubFetch([
      { path: '/shipments/11/quote-offers', body: [] },
      { path: '/shipments/11/invoice', body: null },
      { path: '/shipments/11/quotes', body: [version] },
    ]);
    renderWithProviders(
      <QuotePanel consolidationId={3} shipmentId={11} refresh={() => {}} editable customerLabel="Demo Customer" />,
    );
    const link = await screen.findByRole('link', { name: 'Print customer quote v1 — Demo Customer' });
    expect(link).toHaveAttribute('href', '/workspace/quotes/11/1/print?from=3');
  });
});
