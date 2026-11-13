/**
 * UAT round 3, staff portal:
 *
 * * the audience export is offered on the Segments screen to every role holding
 *   `export:marketing_segment`, and to no other;
 * * a saved internal note shows at once, without waiting for a refetch;
 * * the account menu follows the WAI-ARIA menu button keyboard pattern;
 * * the audit access screen shows a reason code and changed field names, never values.
 */

import { afterEach, describe, expect, it, vi } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Route, Routes } from 'react-router-dom';
import { SessionProvider } from '../src/app/SessionContext.jsx';
import { AppShell } from '../src/components/layout/AppShell.jsx';
import { InteractionsTab } from '../src/features/customers/tabs/InteractionsTab.jsx';
import { SegmentsPage } from '../src/features/segments/SegmentsPage.jsx';
import { SettingsPage } from '../src/features/settings/SettingsPage.jsx';
import { NotesTab } from '../src/features/shipments/shipmentTabs.jsx';
import { renderWithProviders, stubFetch } from './utils.jsx';

function session(role, permissions) {
  return {
    path: '/auth/me',
    body: {
      user: {
        id: 1,
        full_name: 'Test Person',
        email: 'person@demo.example.com',
        role,
        initials: 'TP',
        timezone: 'America/Toronto',
        locale: 'en',
      },
      permissions,
      environment: 'test',
      is_demo_environment: false,
    },
  };
}

afterEach(() => {
  vi.unstubAllGlobals();
});

/* --- a. Audience export on the Segments screen ------------------------------------- */

const SEGMENT = {
  id: 7,
  name: 'Lapsed CAV senders',
  description: null,
  definition: { match: 'all', conditions: [] },
  plain_language: 'Customers on CAV with no shipment in 180 days',
  member_count: 12,
  marketing_eligible_email_count: 8,
  is_system: false,
  owner: null,
  updated_at: '2026-10-01T10:00:00Z',
};

function renderSegments(role, permissions) {
  stubFetch([
    session(role, permissions),
    { path: '/segments/fields', body: { fields: [], note: 'Consent is a separate filter.' } },
    { path: '/segments', body: [SEGMENT] },
    { path: '/tags', body: [] },
    { path: '/staff/assignable', body: [] },
  ]);
  return renderWithProviders(
    <SessionProvider>
      <SegmentsPage />
    </SessionProvider>,
  );
}

const MARKETING = ['segment:read', 'segment:write', 'export:marketing_segment', 'customer:read'];
const READ_ONLY_MANAGER = ['segment:read', 'customer:read', 'audit:read'];

describe('Segments › audience export', () => {
  it('is offered to Marketing, which holds the export permission', async () => {
    renderSegments('marketing', MARKETING);
    expect(
      await screen.findByRole('button', { name: 'Export audience: Lapsed CAV senders' }),
    ).toBeInTheDocument();
  });

  it('follows the permission, not the role name', async () => {
    renderSegments('operations', ['segment:read', 'export:marketing_segment']);
    expect(
      await screen.findByRole('button', { name: 'Export audience: Lapsed CAV senders' }),
    ).toBeInTheDocument();
  });

  it('is absent for a role without the export permission', async () => {
    renderSegments('read_only_manager', READ_ONLY_MANAGER);
    await screen.findByText('Lapsed CAV senders');
    expect(screen.queryByRole('button', { name: /Export audience/ })).toBeNull();
  });

  it('downloads that segment’s audience for the email channel', async () => {
    const user = userEvent.setup();
    const original = window.location;
    // jsdom cannot navigate; a plain object records where the browser was sent.
    delete window.location;
    window.location = { href: '' };
    try {
      renderSegments('marketing', MARKETING);
      await user.click(
        await screen.findByRole('button', { name: 'Export audience: Lapsed CAV senders' }),
      );
      expect(window.location.href).toContain('/exports/segments/7/audience.csv');
      expect(window.location.href).toContain('channel=email');
    } finally {
      window.location = original;
    }
  });
});

/* --- b. A saved internal note shows at once ---------------------------------------- */

describe('Internal notes › shown straight after saving', () => {
  it('puts the saved note in the timeline even before any refetch answers', async () => {
    const user = userEvent.setup();
    const base = stubFetch([
      session('marketing', ['interaction:write', 'customer:read']),
      {
        path: '/customers/1/interactions',
        method: 'POST',
        body: (init) => ({
          id: 31,
          ...JSON.parse(init.body),
          occurred_at: '2026-10-15T14:00:00Z',
          author: { id: 1, full_name: 'Test Person' },
          is_follow_up_completion: false,
        }),
      },
      { path: '/customers/1/interactions', body: { items: [], total: 0, limit: 5, offset: 0 } },
      { path: '/customers/1', body: {} },
    ]);
    // The first read answers "no notes"; every later read never answers, as a slow
    // server would. The note must show regardless.
    let reads = 0;
    vi.stubGlobal('fetch', (input, init = {}) => {
      const url = String(input);
      const isRead = (init.method || 'GET') === 'GET' && url.includes('/interactions');
      if (isRead && (reads += 1) > 1) return new Promise(() => {});
      return base(input, init);
    });

    renderWithProviders(
      <SessionProvider>
        <InteractionsTab customerId={1} compact />
      </SessionProvider>,
    );
    await user.click(await screen.findByRole('button', { name: 'Add note' }));
    await user.type(screen.getByLabelText(/Subject/), 'Called about the Hanoi parcel');
    await user.click(screen.getByRole('button', { name: 'Save' }));

    expect(await screen.findByText('Called about the Hanoi parcel')).toBeInTheDocument();
    expect(screen.queryByText('No activity yet')).toBeNull();
  });

  it('shows the shipment’s internal notes exactly as the server stored them', async () => {
    const user = userEvent.setup();
    const shipment = { id: 10, internal_notes: null };
    stubFetch([
      session('operations', ['shipment:read', 'shipment:write']),
      {
        path: '/shipments/10',
        method: 'PATCH',
        // The server trims; the box must show what was stored, not what was typed.
        body: (init) => ({ ...shipment, internal_notes: JSON.parse(init.body).internal_notes.trim() }),
      },
      { path: '/shipments/10', body: shipment },
    ]);
    renderWithProviders(
      <SessionProvider>
        <NotesTab shipment={shipment} />
      </SessionProvider>,
    );
    // The box is editable once the session says the role may write.
    const save = await screen.findByRole('button', { name: 'Save' });
    const box = screen.getByRole('textbox', { name: 'Internal notes' });
    await user.type(box, 'Shelf B2  ');
    await user.click(save);

    await waitFor(() => expect(box).toHaveValue('Shelf B2'));
  });
});

/* --- c. Account menu keyboard ------------------------------------------------------ */

function renderShell() {
  stubFetch([session('admin', ['dashboard:read', 'settings:read'])]);
  return renderWithProviders(
    <SessionProvider>
      <Routes>
        <Route path="/" element={<AppShell />}>
          <Route index element={<p>Home</p>} />
        </Route>
      </Routes>
    </SessionProvider>,
  );
}

describe('Account menu › keyboard', () => {
  it('opens from the keyboard on its first item, and arrows wrap', async () => {
    const user = userEvent.setup();
    renderShell();
    const trigger = await screen.findByRole('button', { name: 'Account menu' });
    trigger.focus();

    await user.keyboard('{Enter}');
    const menu = await screen.findByRole('menu');
    // RC-UAT-21 added "Change password" between Settings and Sign out.
    const [settings, changePassword, signOut] = within(menu).getAllByRole('menuitem');
    expect(trigger).toHaveAttribute('aria-expanded', 'true');
    await waitFor(() => expect(settings).toHaveFocus());

    await user.keyboard('{ArrowDown}');
    expect(changePassword).toHaveFocus();
    await user.keyboard('{ArrowDown}');
    expect(signOut).toHaveFocus();
    await user.keyboard('{ArrowDown}');
    expect(settings).toHaveFocus();
    await user.keyboard('{ArrowUp}');
    expect(signOut).toHaveFocus();
    await user.keyboard('{Home}');
    expect(settings).toHaveFocus();
    await user.keyboard('{End}');
    expect(signOut).toHaveFocus();
  });

  it('closes on Escape and returns focus to the button', async () => {
    const user = userEvent.setup();
    renderShell();
    const trigger = await screen.findByRole('button', { name: 'Account menu' });
    trigger.focus();
    await user.keyboard('{ArrowDown}');
    await waitFor(() => expect(screen.getAllByRole('menuitem')[0]).toHaveFocus());

    await user.keyboard('{Escape}');
    expect(screen.queryByRole('menu')).toBeNull();
    expect(trigger).toHaveFocus();
    expect(trigger).toHaveAttribute('aria-expanded', 'false');
  });

  it('opens on its last item with ArrowUp', async () => {
    const user = userEvent.setup();
    renderShell();
    const trigger = await screen.findByRole('button', { name: 'Account menu' });
    trigger.focus();
    await user.keyboard('{ArrowUp}');
    await waitFor(() => expect(screen.getByRole('menuitem', { name: 'Sign out' })).toHaveFocus());
  });

  it('keeps the items out of the Tab order', async () => {
    const user = userEvent.setup();
    renderShell();
    await user.click(await screen.findByRole('button', { name: 'Account menu' }));
    for (const item of screen.getAllByRole('menuitem')) {
      expect(item).toHaveAttribute('tabindex', '-1');
    }
  });
});

/* --- d. Audit access detail -------------------------------------------------------- */

describe('Settings › Audit access detail', () => {
  it('shows the reason code and changed field names, never the stored values', async () => {
    const user = userEvent.setup();
    stubFetch([
      session('admin', ['settings:read', 'audit:read']),
      { path: '/settings', body: { lifecycle_definitions: {} } },
      {
        path: '/audit',
        body: {
          items: [
            {
              id: 2,
              occurred_at: '2026-10-15T14:00:00Z',
              actor_label: 'admin@demo.example.com',
              action: 'customer.update',
              entity_type: 'customer',
              entity_id: 'STCA-000001',
              summary: 'Updated customer STCA-000001',
              // Whatever the raw detail holds, the screen does not read it.
              detail_json: '{"changed_fields": ["city", "notes"], "reason": "Mrs Lan asked"}',
              reason_code: null,
              changed_fields: ['city', 'notes'],
            },
            {
              id: 1,
              occurred_at: '2026-10-15T13:00:00Z',
              actor_label: 'ops@demo.example.com',
              action: 'customer_account.reject',
              entity_type: 'customer_account',
              entity_id: null,
              summary: 'Rejected an application',
              detail_json: null,
              reason_code: 'duplicate_reviewed',
              changed_fields: [],
            },
          ],
          total: 2,
          limit: 50,
          offset: 0,
        },
      },
    ]);
    renderWithProviders(
      <SessionProvider>
        <SettingsPage />
      </SessionProvider>,
    );
    await screen.findByRole('heading', { name: 'Settings' });
    await user.click(screen.getByRole('tab', { name: 'Audit access' }));
    const table = await screen.findByRole('table', { name: 'Audit access' });

    expect(within(table).getByRole('columnheader', { name: 'Details' })).toBeInTheDocument();
    const [, updateRow, rejectRow] = within(table).getAllByRole('row');
    expect(within(updateRow).getByText('Fields changed')).toBeInTheDocument();
    expect(within(updateRow).getByText('city, notes')).toBeInTheDocument();
    expect(within(rejectRow).getByText('Reason code')).toBeInTheDocument();
    expect(within(rejectRow).getByText('duplicate_reviewed')).toBeInTheDocument();
    expect(screen.queryByText(/Mrs Lan/)).toBeNull();
  });
});
