// RC-UAT-24 (owner Ben, 2026-10-24; DEC-0236, I-10): the legal entity is Solaris Express Inc.
// The login footer reads it from `brand.legalEntity`; Settings shows the server's value.
import { describe, expect, it } from 'vitest';
import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { SessionProvider } from '../src/app/SessionContext.jsx';
import { SettingsPage } from '../src/features/settings/SettingsPage.jsx';
import { en } from '../src/i18n/en.js';
import { vi } from '../src/i18n/vi.js';
import { renderWithProviders, stubFetch } from './utils.jsx';

const ADMIN = {
  user: { id: 1, full_name: 'Demo Admin', email: 'admin@demo.example.com', role: 'admin' },
  permissions: ['settings:read', 'settings:manage'],
  environment: 'test',
  is_demo_environment: false,
};

const SETTINGS = {
  brand_name: 'Solaris Express',
  legal_entity_name: 'Solaris Express Inc.',
  office_timezone: 'America/Toronto',
  default_currency: 'CAD',
  tracking_base_url: 'http://localhost:5173/track',
  lifecycle_new_days: 30,
  lifecycle_active_days: 90,
  lifecycle_at_risk_days: 180,
  rule_first_delivery_follow_up_enabled: true,
  rule_first_delivery_follow_up_days: 3,
  rule_at_risk_task_enabled: true,
  rule_exception_task_enabled: true,
  is_demo_environment: false,
  lifecycle_definitions: {},
};

describe('the legal entity is Solaris Express Inc.', () => {
  it('in both languages of the staff portal (the login footer)', () => {
    expect(en.brand.legalEntity).toBe('Solaris Express Inc.');
    expect(vi.brand.legalEntity).toBe('Solaris Express Inc.');
    expect(JSON.stringify(en)).not.toContain('Soleil Global');
    expect(JSON.stringify(vi)).not.toContain('Soleil Global');
  });

  it('on Settings', async () => {
    stubFetch([
      { path: '/auth/me', body: ADMIN },
      { path: '/settings', body: SETTINGS },
    ]);
    renderWithProviders(
      <SessionProvider>
        <SettingsPage />
      </SessionProvider>,
    );
    const user = userEvent.setup();
    await screen.findByRole('heading', { name: 'Settings' });
    await user.click(screen.getByRole('tab', { name: en.settings.brand }));
    expect(await screen.findByText('Solaris Express Inc.')).toBeInTheDocument();
    expect(screen.queryByText(/Soleil Global/)).not.toBeInTheDocument();
  });
});
