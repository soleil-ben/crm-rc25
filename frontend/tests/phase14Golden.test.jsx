/**
 * Phase 14 golden tests (independent tester): the new staff screens from the user's side.
 * Mocked API throughout; demo data only; air only.
 *
 * - Settings › Pricing: only changed fields are sent; nothing is sent when nothing changed; a
 *   server validation error (domain envelope or FastAPI 422 `detail`) is shown beside its field;
 *   a non-Admin sees every control read-only.
 * - Settings › Tariffs: no Approve / Reject / activate for anyone who is not an approver.
 * - Master: Cancel needs a confirmation and a real (non-blank) reason.
 * - Printable quote: no cost word, even if the payload carried one.
 */

import { describe, expect, it } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Route, Routes } from 'react-router-dom';
import { SessionProvider } from '../src/app/SessionContext.jsx';
import { PricingSettingsPanel } from '../src/features/settings/PricingSettingsPanel.jsx';
import { TariffBrowserPanel } from '../src/features/settings/TariffBrowserPanel.jsx';
import { MasterActionsPanel } from '../src/features/workspace/MasterActions.jsx';
import { QuotePrintPage } from '../src/features/workspace/QuotePrintPage.jsx';
import en from '../src/i18n/en.js';
import { renderWithProviders, stubFetch } from './utils.jsx';

function session(permissions, role = 'admin') {
  return {
    path: '/auth/me',
    body: {
      user: { id: 1, full_name: 'Demo User', email: `${role}@demo.example.com`, role },
      permissions,
      environment: 'test',
      is_demo_environment: false,
    },
  };
}

const ADMIN = ['settings:read', 'settings:manage', 'tariff:read', 'tariff:manage'];
const OPS = ['settings:read', 'tariff:read', 'shipment:read', 'shipment:write', 'tracking:write'];

// --- Settings › Pricing ------------------------------------------------------------------

const PRICING = {
  air_standard_default_rate_cad: '18.00',
  air_express_default_rate_cad: '25.00',
  trigger_share_numerator: 2,
  trigger_share_denominator: 3,
  defaults_owner_confirmed: true,
  vendor_delivery_postal_code: 'L5A3K6',
  updated_at: '2026-10-20T10:00:00',
  default_markup_kind: 'percent',
  default_markup_value: '2.00',
};

const ACTIVE = { id: 4, public_id: 'TRF-000004', status: 'active', label: 'Demo', review_decision: null };

const RULES = {
  items: [
    {
      id: 18,
      stt: 18,
      section: 'hcm_air',
      name: 'Đồng hồ thường',
      raw_price_text: '50,000 VND / cái',
      basis: 'per_unit',
      scope: 'per_unit',
      pricing_status: 'priced',
      tiers: [],
    },
  ],
  total: 1,
};

function renderPricing(permissions, { patchStatus, patchBody } = {}) {
  const sent = [];
  const fetchMock = stubFetch([
    session(permissions),
    {
      path: '/pricing/settings',
      method: 'PATCH',
      status: patchStatus,
      body: (init) => {
        const payload = JSON.parse(init.body);
        sent.push(payload);
        return patchBody ?? { ...PRICING, ...payload };
      },
    },
    { path: '/pricing/settings', body: PRICING },
    { path: '/pricing/surcharge-policies', body: [] },
    { path: '/tariffs/versions/4/surcharges', body: RULES },
    { path: '/tariffs/versions', body: { items: [ACTIVE], total: 1 } },
  ]);
  renderWithProviders(
    <SessionProvider>
      <PricingSettingsPanel />
    </SessionProvider>,
  );
  return { sent, fetchMock };
}

const patches = (fetchMock) =>
  fetchMock.mock.calls.filter(([, init]) => (init?.method || 'GET').toUpperCase() === 'PATCH');

describe('Golden › Pricing settings', () => {
  it('sends exactly the one field that changed', async () => {
    const user = userEvent.setup();
    const { sent } = renderPricing(ADMIN);
    const standard = await screen.findByRole('textbox', { name: /Air Standard default rate/ });
    await user.clear(standard);
    await user.type(standard, '20');
    await user.click(screen.getByRole('button', { name: 'Save pricing settings' }));
    await waitFor(() => expect(sent).toHaveLength(1));
    expect(sent[0]).toEqual({ air_standard_default_rate_cad: '20' });
    expect(await screen.findByText(en.pricingSettings.saved)).toBeInTheDocument();
  });

  it('sends the markup kind alone when switched to pass-through', async () => {
    const user = userEvent.setup();
    const { sent } = renderPricing(ADMIN);
    const kind = await screen.findByRole('combobox', { name: /Default surcharge markup/ });
    await user.selectOptions(kind, 'pass_through');
    await user.click(screen.getByRole('button', { name: 'Save pricing settings' }));
    await waitFor(() => expect(sent).toHaveLength(1));
    expect(sent[0]).toEqual({ default_markup_kind: 'pass_through' });
  });

  it('sends nothing when nothing changed, and says so', async () => {
    const user = userEvent.setup();
    const { fetchMock } = renderPricing(ADMIN);
    await screen.findByRole('textbox', { name: /Air Standard default rate/ });
    await user.click(screen.getByRole('button', { name: 'Save pricing settings' }));
    expect(await screen.findByText(en.pricingSettings.unchanged)).toBeInTheDocument();
    expect(patches(fetchMock)).toHaveLength(0);
  });

  it('shows a domain refusal beside the field the server names', async () => {
    const user = userEvent.setup();
    renderPricing(ADMIN, {
      patchStatus: 422,
      patchBody: { code: 'validation_error', message: 'The default rate must be positive.', field: 'air_standard_default_rate_cad' },
    });
    const standard = await screen.findByRole('textbox', { name: /Air Standard default rate/ });
    await user.clear(standard);
    await user.type(standard, '19');
    await user.click(screen.getByRole('button', { name: 'Save pricing settings' }));
    await waitFor(() => expect(standard).toHaveAttribute('aria-invalid', 'true'));
    const describedBy = standard.getAttribute('aria-describedby') || '';
    const texts = describedBy
      .split(' ')
      .map((id) => document.getElementById(id)?.textContent || '')
      .join(' ');
    expect(texts).toContain('The default rate must be positive.');
  });

  it('shows a FastAPI 422 beside the field its location names', async () => {
    const user = userEvent.setup();
    renderPricing(ADMIN, {
      patchStatus: 422,
      patchBody: {
        detail: [
          { loc: ['body', 'air_express_default_rate_cad'], msg: 'Input should be greater than 0', type: 'greater_than' },
        ],
      },
    });
    const express = await screen.findByRole('textbox', { name: /Air Express default rate/ });
    await user.clear(express);
    await user.type(express, '30');
    await user.click(screen.getByRole('button', { name: 'Save pricing settings' }));
    await waitFor(() => expect(express).toHaveAttribute('aria-invalid', 'true'));
    expect(screen.getByText('Input should be greater than 0')).toBeInTheDocument();
    // The Standard rate was not blamed.
    expect(screen.getByRole('textbox', { name: /Air Standard default rate/ })).not.toHaveAttribute('aria-invalid', 'true');
  });

  it('is entirely read-only for a non-Admin (Operations)', async () => {
    const user = userEvent.setup();
    const { fetchMock } = renderPricing(OPS);
    const standard = await screen.findByRole('textbox', { name: /Air Standard default rate/ });
    for (const name of [/Air Standard default rate/, /Air Express default rate/, 'Numerator', 'Denominator']) {
      expect(screen.getByRole('textbox', { name })).toHaveAttribute('readonly');
    }
    expect(screen.getByRole('combobox', { name: /Default surcharge markup/ })).toBeDisabled();
    expect(screen.queryByRole('button', { name: 'Save pricing settings' })).toBeNull();
    // Typing into a read-only field changes nothing and Enter sends nothing.
    await user.type(standard, '9{Enter}');
    expect(standard).toHaveValue('18');
    await screen.findByRole('region', { name: 'Surcharges and their policies' });
    expect(screen.queryByRole('button', { name: /Edit policy/ })).toBeNull();
    expect(screen.queryByRole('form', { name: /Edit policy/ })).toBeNull();
    expect(patches(fetchMock)).toHaveLength(0);
  });
});

// --- Settings › Tariffs ------------------------------------------------------------------

function version(overrides) {
  return {
    vendor_key: 'kango',
    label: 'Demo rates',
    source_file_name: 'rates.xlsx',
    source_sha256: 'a'.repeat(64),
    effective_from: '2026-10-12',
    effective_to: null,
    imported_at: '2026-10-12T09:00:00',
    activated_at: null,
    dim_divisor_default: 6000,
    fixed_fx_vnd_per_cad: null,
    cost_currency: 'VND',
    review_decision: null,
    ...overrides,
  };
}

const VERSIONS = [
  version({ id: 5, public_id: 'TRF-000005', status: 'draft', effective_from: '2026-10-19' }),
  version({ id: 4, public_id: 'TRF-000004', status: 'active', activated_at: '2026-10-12T10:00:00' }),
  version({ id: 3, public_id: 'TRF-000003', status: 'draft', review_decision: 'rejected' }),
];

const DIFF = {
  version_id: 5,
  version_public_id: 'TRF-000005',
  against_version_public_id: 'TRF-000004',
  summary: {
    brackets_changed: 1,
    brackets_added: 0,
    brackets_removed: 0,
    surcharges_changed: 0,
    surcharges_added: 0,
    surcharges_removed: 0,
  },
  truncated: false,
  brackets_changed: [],
  brackets_added: [],
  brackets_removed: [],
  surcharges_changed: [],
  surcharges_added: [],
  surcharges_removed: [],
};

function renderTariffs(permissions, { approver = false } = {}) {
  const fetchMock = stubFetch([
    session(permissions),
    { path: '/tariffs/versions/5/diff', body: DIFF },
    { path: '/products', body: [] },
    { path: '/accessorials', body: [] },
    { path: '/beyond-rates', body: [] },
    { path: '/tariffs/versions', body: { items: VERSIONS, total: VERSIONS.length } },
    { path: '/tariffs/intake', body: { items: [], total: 0, viewer_is_approver: approver } },
    { path: '/fx/history', body: { snapshots: [], attempts: [] } },
  ]);
  renderWithProviders(
    <SessionProvider>
      <TariffBrowserPanel />
    </SessionProvider>,
  );
  return fetchMock;
}

const REVIEW_BUTTONS = [/approve/i, /^reject$/i, /activate/i];

function expectNoReviewButtons() {
  for (const name of REVIEW_BUTTONS) {
    expect(screen.queryByRole('button', { name })).toBeNull();
  }
  expect(screen.queryByRole('textbox', { name: /Reason for rejecting/ })).toBeNull();
}

describe('Golden › Tariff browser review actions', () => {
  for (const [label, permissions] of [
    ['a reader (Operations)', ['tariff:read']],
    ['a manager who is not a designated approver', ['tariff:read', 'tariff:manage', 'settings:manage']],
  ]) {
    it(`offers no Approve, Reject or activate to ${label}, on any version`, async () => {
      const user = userEvent.setup();
      const fetchMock = renderTariffs(permissions, { approver: false });
      await screen.findByRole('button', { name: 'View TRF-000005' });
      for (const id of ['TRF-000004', 'TRF-000005', 'TRF-000003']) {
        await user.click(screen.getByRole('button', { name: `View ${id}` }));
        await screen.findByRole('heading', { name: new RegExp(`^${id} ·`) });
        expectNoReviewButtons();
      }
      // Nothing was ever posted.
      expect(fetchMock.mock.calls.filter(([, init]) => (init?.method || 'GET') !== 'GET')).toHaveLength(0);
    });
  }

  it('offers Approve and Reject to a designated approver on a pending draft only', async () => {
    const user = userEvent.setup();
    renderTariffs(ADMIN, { approver: true });
    await user.click(await screen.findByRole('button', { name: 'View TRF-000005' }));
    expect(await screen.findByRole('button', { name: 'Approve and activate' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Reject' })).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'View TRF-000003' }));
    await screen.findByRole('heading', { name: /^TRF-000003 ·/ });
    expectNoReviewButtons();
    await user.click(screen.getByRole('button', { name: 'View TRF-000004' }));
    await screen.findByRole('heading', { name: /^TRF-000004 ·/ });
    expectNoReviewButtons();
  });
});

// --- Master cancel -----------------------------------------------------------------------

function master(overrides = {}) {
  return {
    id: 3,
    public_id: 'MST-000003',
    state: 'booked',
    members: [
      { shipment_id: 11, public_id: 'SX-VCA-AAAA11' },
      { shipment_id: 12, public_id: 'SX-VCA-AAAA12' },
    ],
    ...overrides,
  };
}

describe('Golden › Cancelling a master', () => {
  it('needs the confirmation and a non-blank reason; the reason is sent trimmed', async () => {
    const user = userEvent.setup();
    const bodies = [];
    stubFetch([
      {
        path: '/consolidations/3/cancel',
        method: 'POST',
        body: (init) => {
          bodies.push(JSON.parse(init.body));
          return master({ state: 'cancelled', members: [] });
        },
      },
    ]);
    renderWithProviders(<MasterActionsPanel master={master()} />);
    await user.click(screen.getByRole('button', { name: 'Cancel master' }));
    const dialog = screen.getByRole('dialog', { name: 'Cancel MST-000003' });
    expect(bodies).toHaveLength(0);

    // Empty, then whitespace only: refused on the screen, nothing sent.
    await user.click(within(dialog).getByRole('button', { name: 'Cancel the master' }));
    expect(within(dialog).getByText(en.masterOps.errors.reason)).toBeInTheDocument();
    const reason = within(dialog).getByRole('textbox', { name: /Why is the master/ });
    expect(reason).toHaveFocus();
    await user.type(reason, '    ');
    await user.click(within(dialog).getByRole('button', { name: 'Cancel the master' }));
    expect(within(dialog).getByText(en.masterOps.errors.reason)).toBeInTheDocument();
    expect(bodies).toHaveLength(0);

    await user.clear(reason);
    await user.type(reason, '  Vendor flight cancelled  ');
    await user.click(within(dialog).getByRole('button', { name: 'Cancel the master' }));
    await waitFor(() => expect(bodies).toEqual([{ reason: 'Vendor flight cancelled' }]));
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
  });

  it('keeping the master sends nothing and forgets nothing it should not', async () => {
    const user = userEvent.setup();
    const fetchMock = stubFetch([]);
    renderWithProviders(<MasterActionsPanel master={master({ state: 'open' })} />);
    expect(screen.queryByRole('button', { name: 'Complete master' })).toBeNull();
    await user.click(screen.getByRole('button', { name: 'Cancel master' }));
    const dialog = screen.getByRole('dialog', { name: 'Cancel MST-000003' });
    await user.type(within(dialog).getByRole('textbox', { name: /Why is the master/ }), 'maybe');
    await user.click(within(dialog).getByRole('button', { name: 'Keep the master' }));
    expect(screen.queryByRole('dialog')).toBeNull();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('shows the server refusal inside the dialog', async () => {
    const user = userEvent.setup();
    stubFetch([
      {
        path: '/consolidations/3/cancel',
        method: 'POST',
        status: 409,
        body: { code: 'conflict', message: 'This consolidation is already completed.' },
      },
    ]);
    renderWithProviders(<MasterActionsPanel master={master()} />);
    await user.click(screen.getByRole('button', { name: 'Cancel master' }));
    const dialog = screen.getByRole('dialog', { name: 'Cancel MST-000003' });
    await user.type(within(dialog).getByRole('textbox', { name: /Why is the master/ }), 'Late');
    await user.click(within(dialog).getByRole('button', { name: 'Cancel the master' }));
    expect(await within(dialog).findByText('This consolidation is already completed.')).toBeInTheDocument();
  });
});

// --- Printable quote ---------------------------------------------------------------------

const DOCUMENT = {
  company_name: 'Solaris Express Inc.',
  company_trade_name: 'Solaris Express',
  company_business_number: '795093756RT0001',
  company_address: '2446 Cawthra Road B1U8, Mississauga ON L5A 3K6',
  customer_name: 'Demo Customer',
  customer_reference: 'STCA-000101',
  shipment_reference: 'SX-VCA-AAAA11',
  version: 2,
  finalized_at: '2026-10-20T10:00:00',
  service: 'Air Standard',
  billable_weight_kg: '12.000',
  rate_per_kg_cad: '17.00',
  base_charge_cad: '204.00',
  surcharges: [{ name: 'Đồng hồ thường', amount_cad: '3.92' }],
  total_cad: '207.92',
  currency: 'CAD',
  tax_included: false,
};

// Fields a careless server change could add; the page must not render any of them.
const LEAKY = {
  ...DOCUMENT,
  allocated_cost_cad: '987.65',
  gross_profit_cad: '-779.73',
  vendor_reference: 'VENDORREF77',
  vendor_product_code: 'AIR-CAD',
  fx_cash_buy_vnd: '18123.45',
  markup_value: '44.44',
  override_reason: 'SENTINEL-OVERRIDE',
  negative_margin_reason: 'SENTINEL-MARGIN',
  tariff_version_public_id: 'TRF-000004',
};

function renderPrint(payload) {
  stubFetch([{ path: '/shipments/11/quotes/2/document', body: payload }]);
  return renderWithProviders(
    <Routes>
      <Route path="/workspace/quotes/:shipmentId/:version/print" element={<QuotePrintPage />} />
    </Routes>,
    { route: '/workspace/quotes/11/2/print?from=3' },
  );
}

const COST_WORDS = [/cost/i, /vendor/i, /markup/i, /margin/i, /\bfx\b/i, /exchange/i, /tariff/i, /kango/i, /AIR-CAD/, /VND/, /override/i, /profit/i];

describe('Golden › Printable quote', () => {
  it('renders the customer figures and no cost word on the whole page', async () => {
    const { container } = renderPrint(DOCUMENT);
    const doc = await screen.findByRole('article', { name: 'Quote' });
    expect(doc.textContent).toMatch(/CAD\s207\.92/);
    expect(doc.textContent).toMatch(/CAD\s3\.92/);
    expect(doc.textContent).toContain('Demo Customer (STCA-000101)');
    for (const word of COST_WORDS) {
      expect(container.textContent).not.toMatch(word);
    }
  });

  it('renders none of the extra cost fields even if the payload carried them', async () => {
    const { container } = renderPrint(LEAKY);
    await screen.findByRole('article', { name: 'Quote' });
    const text = container.textContent;
    for (const word of COST_WORDS) {
      expect(text).not.toMatch(word);
    }
    for (const figure of ['987.65', '779.73', '18123', '18,123', '44.44', 'VENDORREF77', 'SENTINEL', 'TRF-000004']) {
      expect(text).not.toContain(figure);
    }
  });

  it('shows an error, not a document, when the version is a draft (409)', async () => {
    stubFetch([
      {
        path: '/shipments/11/quotes/2/document',
        status: 409,
        body: { code: 'conflict', message: 'Only a finalised quote has a printable document.' },
      },
    ]);
    renderWithProviders(
      <Routes>
        <Route path="/workspace/quotes/:shipmentId/:version/print" element={<QuotePrintPage />} />
      </Routes>,
      { route: '/workspace/quotes/11/2/print' },
    );
    expect(await screen.findByText(/Only a finalised quote has a printable document/)).toBeInTheDocument();
    expect(screen.queryByRole('article')).toBeNull();
    expect(screen.queryByRole('button', { name: 'Print' })).toBeNull();
  });
});
