/**
 * Phase 14, Settings → Pricing. Mocked API throughout; demo data only.
 *
 * The tab is offered with tariff:read; the defaults show as the server holds them (the 2/3
 * share as numerator over denominator, the owner-confirmed flag read-only); a mistake is
 * named beside its field before anything is sent; only changed fields are sent and an
 * emptied Air Express rate is sent as null; a server refusal lands beside its field; the
 * per-rule policies list the active tariff's air surcharges with an accent-insensitive search
 * and save the kind, value, scope override and note. Without settings:manage nothing is
 * editable.
 */

import { describe, expect, it } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { SessionProvider } from '../src/app/SessionContext.jsx';
import { SettingsPage } from '../src/features/settings/SettingsPage.jsx';
import { PricingSettingsPanel, validateSettings } from '../src/features/settings/PricingSettingsPanel.jsx';
import en from '../src/i18n/en.js';
import { renderWithProviders, stubFetch } from './utils.jsx';

const ADMIN = ['settings:read', 'settings:manage', 'tariff:read', 'tariff:manage'];
const OPS = ['settings:read', 'tariff:read'];

function session(permissions) {
  return {
    path: '/auth/me',
    body: {
      user: { id: 1, full_name: 'Demo Admin', email: 'admin@demo.example.com', role: 'admin' },
      permissions,
      environment: 'test',
      is_demo_environment: false,
    },
  };
}

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

const VERSIONS = {
  items: [
    { id: 4, public_id: 'TRF-000004', status: 'active', label: 'Demo', review_decision: null },
  ],
  total: 1,
};

function rule(overrides) {
  return {
    id: overrides.stt,
    section: 'hcm_air',
    section_label: 'HCM air',
    raw_price_text: '50,000 VND / cái',
    raw_note: null,
    basis: 'per_unit',
    scope: 'per_unit',
    pricing_status: 'priced',
    unit_price_vnd: '50000',
    tiers: [],
    ...overrides,
  };
}

const RULES = {
  items: [rule({ stt: 18, name: 'Đồng hồ thường' }), rule({ stt: 19, name: 'Mỹ phẩm', scope: 'full_carton' })],
  total: 2,
};

function renderPanel(permissions = ADMIN, { settingsStatus, settingsError } = {}) {
  const calls = { settings: null, policy: null, policyUrl: null };
  stubFetch([
    session(permissions),
    {
      path: '/pricing/settings',
      method: 'PATCH',
      status: settingsStatus,
      body: (init) => {
        calls.settings = JSON.parse(init.body);
        if (settingsError) return settingsError;
        return { ...PRICING, ...calls.settings, updated_at: '2026-10-20T11:00:00' };
      },
    },
    { path: '/pricing/settings', body: PRICING },
    {
      path: '/pricing/surcharge-policies/',
      method: 'PATCH',
      body: (init) => {
        calls.policy = JSON.parse(init.body);
        return { section: 'hcm_air', stt: 18, ...calls.policy, updated_at: '2026-10-20T11:00:00' };
      },
    },
    {
      path: '/pricing/surcharge-policies',
      body: [
        {
          section: 'hcm_air',
          stt: 19,
          markup_kind: 'fixed_cad',
          markup_value: '3.00',
          scope_override: null,
          note: 'Vendor confirmed',
          updated_at: '2026-10-20T09:00:00',
        },
      ],
    },
    { path: '/tariffs/versions/4/surcharges', body: RULES },
    { path: '/tariffs/versions', body: VERSIONS },
  ]);
  renderWithProviders(
    <SessionProvider>
      <PricingSettingsPanel />
    </SessionProvider>,
  );
  return calls;
}

describe('Settings › Pricing', () => {
  it('is offered with tariff:read and hidden without it', async () => {
    const user = userEvent.setup();
    stubFetch([
      session(OPS),
      { path: '/pricing/settings', body: PRICING },
      { path: '/pricing/surcharge-policies', body: [] },
      { path: '/tariffs/versions/4/surcharges', body: RULES },
      { path: '/tariffs/versions', body: VERSIONS },
      { path: '/fx/history', body: { snapshots: [], attempts: [] } },
      { path: '/settings', body: { lifecycle_new_days: 30, lifecycle_active_days: 90, lifecycle_at_risk_days: 180 } },
    ]);
    renderWithProviders(
      <SessionProvider>
        <SettingsPage />
      </SessionProvider>,
    );
    await user.click(await screen.findByRole('tab', { name: 'Pricing' }));
    expect(await screen.findByRole('textbox', { name: /Air Standard default rate/ })).toHaveValue('18');
    expect(screen.getByRole('tab', { name: 'Tariffs' })).toBeInTheDocument();
  });

  it('is not offered without tariff:read', async () => {
    stubFetch([
      session(['settings:read']),
      { path: '/settings', body: { lifecycle_new_days: 30, lifecycle_active_days: 90, lifecycle_at_risk_days: 180 } },
    ]);
    renderWithProviders(
      <SessionProvider>
        <SettingsPage />
      </SessionProvider>,
    );
    await screen.findByRole('heading', { name: 'Settings' });
    await waitFor(() => expect(screen.getAllByRole('tab').length).toBeGreaterThan(0));
    expect(screen.queryByRole('tab', { name: 'Pricing' })).toBeNull();
    expect(screen.queryByRole('tab', { name: 'Tariffs' })).toBeNull();
  });

  it('shows the defaults, the share as a fraction and the owner flag read-only', async () => {
    renderPanel();
    expect(await screen.findByRole('textbox', { name: /Air Standard default rate/ })).toHaveValue('18');
    expect(screen.getByRole('textbox', { name: /Air Express default rate/ })).toHaveValue('25');
    expect(screen.getByRole('textbox', { name: 'Numerator' })).toHaveValue('2');
    expect(screen.getByRole('textbox', { name: 'Denominator' })).toHaveValue('3');
    expect(screen.getByRole('group', { name: /Share carried/ })).toBeInTheDocument();
    expect(screen.getByText('Confirmed by the owner')).toBeInTheDocument();
    expect(screen.queryByRole('checkbox', { name: /owner/i })).toBeNull();
    expect(screen.getByRole('combobox', { name: /Default surcharge markup/ })).toHaveValue('percent');
    expect(screen.getByRole('textbox', { name: 'Markup (%)' })).toHaveValue('2');
  });

  it('names a mistake beside its field and sends nothing', async () => {
    const user = userEvent.setup();
    const calls = renderPanel();
    const numerator = await screen.findByRole('textbox', { name: 'Numerator' });
    await user.clear(numerator);
    await user.type(numerator, '4');
    const standard = screen.getByRole('textbox', { name: /Air Standard default rate/ });
    await user.clear(standard);
    await user.click(screen.getByRole('button', { name: 'Save pricing settings' }));
    expect(await screen.findByText(en.pricingSettings.errors.positiveRate)).toBeInTheDocument();
    expect(screen.getByText(en.pricingSettings.errors.shareFraction)).toBeInTheDocument();
    expect(standard).toHaveAttribute('aria-invalid', 'true');
    expect(standard).toHaveFocus();
    expect(calls.settings).toBeNull();
  });

  it('sends only what changed, an emptied Express rate as null, and confirms', async () => {
    const user = userEvent.setup();
    const calls = renderPanel();
    const express = await screen.findByRole('textbox', { name: /Air Express default rate/ });
    await user.clear(express);
    const value = screen.getByRole('textbox', { name: 'Markup (%)' });
    await user.clear(value);
    await user.type(value, '3.5');
    await user.click(screen.getByRole('button', { name: 'Save pricing settings' }));
    await waitFor(() =>
      expect(calls.settings).toEqual({ air_express_default_rate_cad: null, default_markup_value: '3.5' }),
    );
    const saved = await screen.findByText('Pricing settings saved.');
    await waitFor(() => expect(saved.closest('[tabindex="-1"]')).toHaveFocus());
  });

  it('puts a server refusal beside the field it names', async () => {
    const user = userEvent.setup();
    renderPanel(ADMIN, {
      settingsStatus: 422,
      settingsError: {
        code: 'validation_error',
        message: 'The trigger share is a fraction between 0 and 1.',
        field: 'trigger_share_numerator',
      },
    });
    const denominator = await screen.findByRole('textbox', { name: 'Denominator' });
    await user.clear(denominator);
    await user.type(denominator, '5');
    await user.click(screen.getByRole('button', { name: 'Save pricing settings' }));
    const numerator = screen.getByRole('textbox', { name: 'Numerator' });
    await waitFor(() => expect(numerator).toHaveAttribute('aria-invalid', 'true'));
    expect(screen.getByText('The trigger share is a fraction between 0 and 1.')).toBeInTheDocument();
  });

  it('lists the air surcharges with their policies and finds them without accents', async () => {
    const user = userEvent.setup();
    renderPanel();
    const table = await screen.findByRole('region', { name: 'Surcharges and their policies' });
    const rows = within(table).getAllByRole('row');
    expect(within(rows[1]).getByText('Đồng hồ thường')).toBeInTheDocument();
    expect(within(rows[1]).getByText('Default (Percent 2 %)')).toBeInTheDocument();
    expect(within(rows[2]).getByText('Fixed amount 3 CAD')).toBeInTheDocument();
    expect(within(rows[2]).getByText('Vendor confirmed')).toBeInTheDocument();
    await user.type(screen.getByRole('searchbox', { name: /Search surcharges/ }), 'dong ho');
    await waitFor(() => expect(within(table).getAllByRole('row')).toHaveLength(2));
    expect(within(table).queryByText('Mỹ phẩm')).toBeNull();
    // Sea is never offered (OD-49).
    const sections = screen.getByRole('combobox', { name: 'Surcharge sheet' });
    expect(within(sections).getAllByRole('option').map((o) => o.value)).toEqual(['hcm_air', 'han_air']);
  });

  it('edits a rule policy: kind, value, scope override and note', async () => {
    const user = userEvent.setup();
    const calls = renderPanel();
    await screen.findByRole('region', { name: 'Surcharges and their policies' });
    await user.click(screen.getByRole('button', { name: 'Edit policy: 18. Đồng hồ thường' }));
    const form = screen.getByRole('form', { name: 'Edit policy: 18. Đồng hồ thường' });
    const kind = within(form).getByRole('combobox', { name: 'Markup' });
    expect(kind).toHaveFocus();
    expect(within(kind).getAllByRole('option').map((o) => o.value)).toEqual([
      'default',
      'percent',
      'fixed_cad',
      'pass_through',
    ]);
    await user.selectOptions(kind, 'percent');
    await user.click(within(form).getByRole('button', { name: 'Save policy' }));
    expect(await within(form).findByText(en.pricingSettings.errors.markupNumber)).toBeInTheDocument();
    expect(calls.policy).toBeNull();
    await user.type(within(form).getByRole('textbox', { name: /Markup \(%\)/ }), '5');
    await user.selectOptions(within(form).getByRole('combobox', { name: /Weight basis override/ }), 'full_carton');
    await user.type(within(form).getByRole('textbox', { name: /Note/ }), 'Owner asked');
    await user.click(within(form).getByRole('button', { name: 'Save policy' }));
    await waitFor(() =>
      expect(calls.policy).toEqual({
        markup_kind: 'percent',
        markup_value: '5',
        scope_override: 'full_carton',
        note: 'Owner asked',
      }),
    );
    expect(await screen.findByText('Policy saved for 18. Đồng hồ thường.')).toBeInTheDocument();
  });

  it('a refetch never sends a stale value back: changes are measured from what was loaded', async () => {
    const user = userEvent.setup();
    const server = { ...PRICING };
    let sent = null;
    stubFetch([
      session(ADMIN),
      {
        path: '/pricing/settings',
        method: 'PATCH',
        body: (init) => {
          sent = JSON.parse(init.body);
          Object.assign(server, sent);
          return { ...server };
        },
      },
      { path: '/pricing/settings', body: () => ({ ...server }) },
      { path: '/pricing/surcharge-policies', body: [] },
      { path: '/tariffs/versions/4/surcharges', body: RULES },
      { path: '/tariffs/versions', body: VERSIONS },
    ]);
    const { queryClient } = renderWithProviders(
      <SessionProvider>
        <PricingSettingsPanel />
      </SessionProvider>,
    );
    const express = await screen.findByRole('textbox', { name: /Air Express default rate/ });
    await user.clear(express);
    await user.type(express, '26');
    // Another administrator changes the Standard rate; this screen refetches.
    server.air_standard_default_rate_cad = '19.00';
    queryClient.invalidateQueries({ queryKey: ['pricing-settings'] });
    const standard = screen.getByRole('textbox', { name: /Air Standard default rate/ });
    await waitFor(() => expect(standard).toHaveValue('19'));
    expect(express).toHaveValue('26');
    await user.click(screen.getByRole('button', { name: 'Save pricing settings' }));
    await waitFor(() => expect(sent).toEqual({ air_express_default_rate_cad: '26' }));
  });

  it('limits the default markup to two decimals', async () => {
    const user = userEvent.setup();
    const calls = renderPanel();
    const value = await screen.findByRole('textbox', { name: 'Markup (%)' });
    await user.clear(value);
    await user.type(value, '2.125');
    await user.click(screen.getByRole('button', { name: 'Save pricing settings' }));
    expect(screen.getByText(en.pricingSettings.errors.markupDecimals)).toBeInTheDocument();
    expect(value).toHaveFocus();
    expect(calls.settings).toBeNull();
  });

  it('offers no editing without settings:manage', async () => {
    renderPanel(OPS);
    const standard = await screen.findByRole('textbox', { name: /Air Standard default rate/ });
    expect(standard).toHaveAttribute('readonly');
    expect(screen.queryByRole('button', { name: 'Save pricing settings' })).toBeNull();
    await screen.findByRole('region', { name: 'Surcharges and their policies' });
    expect(screen.queryByRole('button', { name: /Edit policy/ })).toBeNull();
  });
});

describe('validateSettings', () => {
  const t = (key) => key;
  const base = {
    air_standard_default_rate_cad: '18',
    air_express_default_rate_cad: '',
    trigger_share_numerator: '2',
    trigger_share_denominator: '3',
    default_markup_kind: 'percent',
    default_markup_value: '2',
  };
  it('accepts the owner defaults with an empty Express rate', () => {
    expect(validateSettings(base, t)).toEqual({});
  });
  it('refuses zero, a fraction above one and a markup above 100', () => {
    expect(
      validateSettings(
        { ...base, air_standard_default_rate_cad: '0', trigger_share_numerator: '3', trigger_share_denominator: '2', default_markup_value: '200' },
        t,
      ),
    ).toEqual({
      air_standard_default_rate_cad: 'pricingSettings.errors.positiveRate',
      trigger_share_numerator: 'pricingSettings.errors.shareFraction',
      default_markup_value: 'pricingSettings.errors.markupCeiling',
    });
  });
  it('ignores the value of a pass-through markup', () => {
    expect(validateSettings({ ...base, default_markup_kind: 'pass_through', default_markup_value: 'x' }, t)).toEqual({});
  });
});
