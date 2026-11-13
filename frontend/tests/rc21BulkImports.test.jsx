/**
 * RC-UAT-21 Phase A: shipment import and legacy history baseline screens (DEC-0230).
 *
 * The dry run says nothing was imported and reports problems per row; the import needs an
 * explicit confirmation and re-sends the dry run's digest (and, for a baseline, its cutoff
 * date); a baseline is voided only with a reason; legacy records are labelled as legacy;
 * every new string exists in Vietnamese too.
 */

import { describe, expect, it } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {
  LegacyHistoryImportPage,
  ShipmentImportPage,
  issueText,
  noteText,
} from '../src/features/imports/BulkImportPage.jsx';
import { SessionProvider } from '../src/app/SessionContext.jsx';
import en from '../src/i18n/en.js';
import vi from '../src/i18n/vi.js';
import { renderWithProviders, stubFetch } from './utils.jsx';

const ADMIN = [
  'import:template',
  'import:preview',
  'import:commit',
  'shipment:read',
  'shipment:write',
  'customer:read',
];

function session(permissions) {
  return {
    user: {
      id: 1,
      full_name: 'Test Admin',
      email: 'admin@demo.example.com',
      role: 'admin',
      initials: 'TA',
      timezone: 'America/Toronto',
      locale: 'en',
    },
    permissions,
    environment: 'test',
    is_demo_environment: false,
  };
}

const FIELDS = {
  kind: 'shipments',
  fields: [{ field: 'external_reference', headers: ['external_reference'], required: true }],
  template_headers: ['external_reference'],
  limits: { max_file_bytes: 2097152, max_rows: 5000, max_columns: 60, max_cell_characters: 1000 },
  notes: ['No quote, invoice, email or milestone notification is created by an import.'],
};

const DRY_RUN = {
  kind: 'shipments',
  content_sha256: 'feedface',
  options: {},
  file_name: 'shipments.csv',
  row_count: 2,
  headers: ['external_reference'],
  unmapped_headers: [],
  counts: { ready: 1, duplicate: 0, rejected: 1 },
  notes: ['Dry run only: no shipment, package, item or import batch has been created.'],
  rows: [
    {
      row_number: 2,
      classification: 'ready',
      reference: 'TEST-SHP-0001',
      customer_public_id: 'STCA-000001',
      summary: { recipient_name: 'Trần Thị Thử' },
      issues: [],
    },
    {
      row_number: 3,
      classification: 'rejected',
      reference: 'TEST-SHP-0002',
      customer_public_id: null,
      summary: {},
      issues: [
        {
          field_name: 'transport_mode',
          code: 'air_only',
          message: "'ocean' cannot be imported. Only air shipments are imported in this release.",
        },
      ],
    },
  ],
};

const COMMIT = {
  kind: 'shipments',
  batch_public_id: 'IMP-000007',
  created: 1,
  matched: 0,
  skipped: 0,
  rejected: 1,
  row_count: 2,
  rows: [
    { row_number: 2, outcome: 'created', reason_code: 'created_from_import', reference: 'TEST-SHP-0001', record_id: 5, record_label: 'draft' },
    { row_number: 3, outcome: 'rejected', reason_code: 'air_only', reference: 'TEST-SHP-0002', record_id: null, record_label: null },
  ],
};

const BASELINES = [
  {
    batch_public_id: 'IMP-000002',
    file_name: 'history.csv',
    status: 'active',
    cutoff_date: null,
    row_count: 3,
    created_count: 3,
    matched_count: 0,
    rejected_count: 0,
    committed_at: '2026-10-24T10:00:00',
    voided_at: null,
    void_reason: null,
  },
];

const LEGACY_RECORDS = {
  items: [
    {
      id: 1,
      legacy_reference: 'TEST-OLD-0001',
      customer_id: 1,
      customer_public_id: 'STCA-000001',
      customer_name: 'Trần Văn Cũ',
      route_group: 'VCA',
      direction: 'vn_to_ca',
      transport_mode: 'air',
      booked_on: '2024-03-01',
      final_status: 'delivered',
      completed_on: '2024-03-12',
      recipient_name: 'Trần Thị Cũ',
      recipient_city: 'Toronto',
      is_voided: false,
      is_legacy: true,
      events: [],
    },
  ],
  total: 1,
  limit: 50,
  offset: 0,
};

function renderPage(Page, route, extra = []) {
  const handler = stubFetch([
    { path: '/auth/me', body: session(ADMIN) },
    ...extra,
    { path: '/imports/shipments/fields', body: FIELDS },
    { path: '/imports/legacy-history/fields', body: { ...FIELDS, kind: 'legacy_history' } },
    { path: '/imports/shipments/dry-run', method: 'POST', body: DRY_RUN },
    { path: '/imports/shipments/commit', method: 'POST', body: COMMIT },
    {
      path: '/imports/legacy-history/dry-run',
      method: 'POST',
      body: { ...DRY_RUN, kind: 'legacy_history', options: { cutoff_date: '2024-12-31' } },
    },
    {
      path: '/imports/legacy-history/commit',
      method: 'POST',
      body: { ...COMMIT, kind: 'legacy_history' },
    },
    {
      path: '/imports/legacy-history/baselines/IMP-000002/void',
      method: 'POST',
      body: { ...BASELINES[0], status: 'voided', void_reason: 'Wrong source file' },
    },
    { path: '/imports/legacy-history/baselines', body: BASELINES },
    { path: '/legacy-shipments', body: LEGACY_RECORDS },
  ]);
  return {
    handler,
    ...renderWithProviders(
      <SessionProvider>
        <Page />
      </SessionProvider>,
      { route },
    ),
  };
}

async function chooseFile(container) {
  const input = await waitFor(() => {
    const found = container.querySelector('input[type="file"]');
    expect(found).not.toBeNull();
    return found;
  });
  await userEvent.upload(
    input,
    new File(['external_reference\r\nTEST-SHP-0001\r\n'], 'shipments.csv', { type: 'text/csv' }),
  );
}

describe('ShipmentImportPage', () => {
  it('links the three import kinds and marks the current one', async () => {
    renderPage(ShipmentImportPage, '/customers/import/shipments');
    const nav = await screen.findByRole('navigation', { name: 'Import type' });
    const links = within(nav).getAllByRole('link');
    expect(links.map((link) => link.textContent)).toEqual([
      'Customers',
      'Shipments',
      'Legacy history',
    ]);
    expect(within(nav).getByRole('link', { name: 'Shipments' })).toHaveAttribute(
      'aria-current',
      'page',
    );
  });

  it('says the dry run imported nothing and shows each row problem', async () => {
    const { container } = renderPage(ShipmentImportPage, '/customers/import/shipments');
    await chooseFile(container);
    expect(await screen.findByText('Dry run only. Nothing has been imported.')).toBeInTheDocument();
    expect(screen.getByText(/Only air shipments are imported/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Import 1 row(s)' })).toBeEnabled();
  });

  it('commits only after confirmation, re-sending the dry run digest', async () => {
    const { container, handler } = renderPage(ShipmentImportPage, '/customers/import/shipments');
    await chooseFile(container);
    await userEvent.click(await screen.findByRole('button', { name: 'Import 1 row(s)' }));
    expect(handler.mock.calls.some(([url]) => String(url).includes('/commit'))).toBe(false);
    const dialog = await screen.findByRole('dialog');
    expect(within(dialog).getByText(/No quote, invoice, email or milestone notification/)).toBeInTheDocument();
    await userEvent.click(within(dialog).getByRole('button', { name: 'Import now' }));
    await waitFor(() => {
      const call = handler.mock.calls.find(([url]) => String(url).includes('/shipments/commit'));
      expect(call).toBeDefined();
      expect(call[1].body.get('content_sha256')).toBe('feedface');
      expect(call[1].body.get('confirm')).toBe('true');
    });
    expect(await screen.findByText(/Batch IMP-000007 is recorded/)).toBeInTheDocument();
  });
});

describe('LegacyHistoryImportPage', () => {
  it('sends the cutoff date with the dry run and with the commit', async () => {
    const { container, handler } = renderPage(LegacyHistoryImportPage, '/customers/import/legacy');
    const cutoff = await screen.findByLabelText('Baseline cutoff date');
    await userEvent.type(cutoff, '2024-12-31');
    await chooseFile(container);
    await userEvent.click(await screen.findByRole('button', { name: 'Import 1 row(s)' }));
    await userEvent.click(within(await screen.findByRole('dialog')).getByRole('button', { name: 'Import now' }));
    await waitFor(() => {
      const dry = handler.mock.calls.find(([url]) => String(url).includes('/legacy-history/dry-run'));
      const commit = handler.mock.calls.find(([url]) => String(url).includes('/legacy-history/commit'));
      expect(dry[1].body.get('cutoff_date')).toBe('2024-12-31');
      expect(commit[1].body.get('cutoff_date')).toBe('2024-12-31');
    });
  });

  it('lists legacy records labelled as legacy, read-only', async () => {
    renderPage(LegacyHistoryImportPage, '/customers/import/legacy');
    expect(await screen.findByText('TEST-OLD-0001')).toBeInTheDocument();
    expect(screen.getAllByText('Legacy').length).toBeGreaterThan(0);
    expect(screen.getByText(/never quoted, invoiced or notified/)).toBeInTheDocument();
  });

  it('voids a baseline only with a reason of at least five characters', async () => {
    const { handler } = renderPage(LegacyHistoryImportPage, '/customers/import/legacy');
    await userEvent.click(await screen.findByRole('button', { name: /Void baseline IMP-000002/ }));
    const dialog = await screen.findByRole('dialog');
    const confirm = within(dialog).getByRole('button', { name: 'Void baseline' });
    expect(confirm).toBeDisabled();
    await userEvent.type(within(dialog).getByLabelText(/Reason/), 'Wrong source file');
    expect(confirm).toBeEnabled();
    await userEvent.click(confirm);
    await waitFor(() => {
      const call = handler.mock.calls.find(([url]) => String(url).includes('/void'));
      expect(JSON.parse(call[1].body)).toEqual({ reason: 'Wrong source file', confirm: true });
    });
  });
});

describe('bulk import catalogue', () => {
  function flatten(node, prefix = '') {
    return Object.entries(node).flatMap(([key, value]) =>
      value && typeof value === 'object' ? flatten(value, `${prefix}${key}.`) : [`${prefix}${key}`],
    );
  }

  it('has every English string in Vietnamese, with diacritics', () => {
    expect(flatten(vi.bulkImports).sort()).toEqual(flatten(en.bulkImports).sort());
    expect(vi.bulkImports.nav.shipments).toBe('Lô hàng');
    expect(vi.bulkImports.legacy.title).toBe('Nhập lịch sử cũ');
  });
});

describe('translated dry-run messages', () => {
  function tFor(catalogue) {
    return (key, fallback) => {
      const value = key.split('.').reduce((node, part) => (node == null ? undefined : node[part]), catalogue);
      return typeof value === 'string' ? value : (fallback ?? key);
    };
  }

  it('renders a known issue code in Vietnamese and names the column', () => {
    const issue = { field_name: 'transport_mode', code: 'air_only', message: "'ocean' cannot be imported." };
    expect(issueText(tFor(vi), issue)).toBe(
      'Phiên bản này chỉ nhập lô hàng đường hàng không. (transport_mode)',
    );
  });

  it('falls back to the server sentence for an unknown code', () => {
    const issue = { field_name: 'items', code: 'refused:new_rule', message: 'Server says no.' };
    expect(issueText(tFor(vi), issue)).toBe('Server says no.');
  });

  it('translates coded notes and fills in the unrecognized columns', () => {
    const report = {
      notes: ['Dry run only.', 'These columns were not recognized and are ignored: x.'],
      note_codes: ['dry_run_only_legacy', 'unmapped_columns'],
      unmapped_headers: ['loyalty_points'],
    };
    expect(noteText(tFor(vi), report, report.notes[1], 1)).toBe(
      'Các cột sau không được nhận diện và bị bỏ qua: loyalty_points.',
    );
    expect(noteText(tFor(vi), { notes: ['Plain.'] }, 'Plain.', 0)).toBe('Plain.');
  });
});
