/**
 * Customer import flow behaviour.
 *
 * What matters here is the staging, not the markup: that the preview says nothing has been
 * imported, that the commit needs an explicit confirmation, that a duplicate starts out
 * undecided (never defaulted to skip, never to merge) and blocks the import until somebody
 * decides it, that cancelling is free, and that the commit re-sends the file with the digest
 * the preview returned.
 */

import { describe, expect, it } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { CustomerImportPage } from '../src/features/imports/CustomerImportPage.jsx';
import { SessionProvider } from '../src/app/SessionContext.jsx';
import { renderWithProviders, stubFetch } from './utils.jsx';

const ALL_PERMISSIONS = [
  'import:template',
  'import:preview',
  'import:commit',
  'duplicate:review',
  'customer:create',
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
  fields: [
    { field: 'full_name', headers: ['full_name', 'name'], required: true, allowed_values: null },
    {
      field: 'preferred_language',
      headers: ['preferred_language', 'language'],
      required: false,
      allowed_values: ['en', 'vi', 'fr', 'other', 'unknown'],
    },
  ],
  template_headers: ['full_name', 'email'],
  conflict_policies: ['skip', 'fill_blanks'],
  limits: { max_file_bytes: 2097152, max_rows: 5000, max_columns: 60, max_cell_characters: 1000 },
  notes: [
    'Only the fields listed here are imported.',
    'Consent is never imported. Imported contact details are not marketing eligible until consent is recorded in the CRM with its evidence.',
  ],
};

const PREVIEW = {
  content_sha256: 'abc123def456',
  file_name: 'customers.csv',
  row_count: 3,
  headers: ['full_name', 'email'],
  raw_headers: ['full_name', 'email', 'loyalty_points'],
  unmapped_headers: ['loyalty_points'],
  counts: { new: 1, exact_match: 0, duplicate_review: 1, rejected: 1 },
  notes: [
    'Nothing has been imported. This is a preview: no customer record has been created, changed, or merged.',
    '1 row(s) look like people already in the CRM. Nothing is merged automatically — families legitimately share a phone number or an email address.',
  ],
  rows: [
    {
      row_number: 2,
      classification: 'new',
      values: { full_name: 'Trần Quốc Tuấn', email: 'tuan@example.com', phone: null },
      issues: [],
      matched_customer_id: null,
      matched_customer_public_id: null,
      duplicate_candidates: [],
      source_record_id: 'row:aaa',
      default_action: 'created',
    },
    {
      row_number: 3,
      classification: 'duplicate_review',
      values: { full_name: 'Nguyễn Thị Bích Hạnh', email: 'hanh@example.com', phone: null },
      issues: [],
      matched_customer_id: null,
      matched_customer_public_id: null,
      duplicate_candidates: [
        {
          customer_id: 7,
          public_id: 'STCA-000007',
          full_name: 'Nguyễn Thị Bích Hạnh',
          city: 'Toronto',
          country_code: 'CA',
          matched_on: ['email', 'name'],
          confidence: 85,
        },
      ],
      source_record_id: 'row:bbb',
      default_action: 'skipped',
    },
    {
      row_number: 4,
      classification: 'rejected',
      values: { full_name: null, email: 'noname@example.com', phone: null },
      issues: [
        {
          field_name: 'full_name',
          code: 'missing_name',
          message: 'Full name is required and this row has none.',
        },
      ],
      matched_customer_id: null,
      matched_customer_public_id: null,
      duplicate_candidates: [],
      source_record_id: 'row:ccc',
      default_action: 'rejected',
    },
  ],
};

const COMMIT_RESULT = {
  batch_public_id: 'IMP-000001',
  created: 1,
  matched: 0,
  skipped: 1,
  rejected: 1,
  row_count: 3,
  conflict_policy: 'skip',
  rows: [
    { row_number: 2, outcome: 'created', reason_code: 'created_from_import', customer_id: 9, customer_public_id: 'STCA-000009' },
    { row_number: 3, outcome: 'skipped', reason_code: 'duplicate_not_reviewed', customer_id: null, customer_public_id: null },
    { row_number: 4, outcome: 'rejected', reason_code: 'missing_name', customer_id: null, customer_public_id: null },
  ],
};

function renderImport({ permissions = ALL_PERMISSIONS, previewStatus = 200, previewBody = PREVIEW } = {}) {
  const handler = stubFetch([
    { path: '/auth/me', body: session(permissions) },
    { path: '/imports/customers/fields', body: FIELDS },
    { path: '/imports/batches', body: { items: [], total: 0, limit: 5, offset: 0 } },
    {
      path: '/imports/customers/preview',
      method: 'POST',
      status: previewStatus,
      body:
        previewStatus === 200
          ? previewBody
          : { code: 'validation_error', message: 'This looks like a ZIP archive or an .xlsx workbook, not a CSV file.' },
    },
    { path: '/imports/customers/commit', method: 'POST', body: COMMIT_RESULT },
  ]);
  return {
    handler,
    ...renderWithProviders(
      <SessionProvider>
        <CustomerImportPage />
      </SessionProvider>,
      { route: '/customers/import' },
    ),
  };
}

function csvFile(name = 'customers.csv') {
  return new File(['full_name,email\r\nA,a@example.com\r\n'], name, { type: 'text/csv' });
}

async function uploadFile(container) {
  const input = container.querySelector('input[type="file"]');
  await userEvent.upload(input, csvFile());
  return input;
}

/** The import waits for every duplicate to be decided; most tests just skip row 3. */
async function decideDuplicate(value = 'skip') {
  await screen.findByRole('heading', { name: 'Possible duplicates' });
  await userEvent.selectOptions(screen.getByLabelText('Decision 3'), value);
}

describe('CustomerImportPage', () => {
  it('shows the four steps as an ordered list a screen reader can follow', async () => {
    renderImport();
    const steps = await screen.findByRole('list', { name: 'Import steps' });
    const items = within(steps).getAllByRole('listitem');
    expect(items).toHaveLength(4);
    expect(items[0]).toHaveAttribute('aria-current', 'step');
  });

  it('says what the import can write, including that consent never is', async () => {
    renderImport();
    expect(
      await screen.findByText(/Consent is never imported/i),
    ).toBeInTheDocument();
  });

  it('states plainly after a preview that nothing has been imported', async () => {
    const { container } = renderImport();
    await screen.findByLabelText('CSV file to import');
    await uploadFile(container);

    // The banner title and the server's own note both say it; either alone is enough.
    expect((await screen.findAllByText(/This is a preview/i)).length).toBeGreaterThan(0);
    expect(
      screen.getByText(/no customer record has been created, changed, or merged/i),
    ).toBeInTheDocument();
  });

  it('reports a column it did not recognize instead of silently dropping it', async () => {
    const { container } = renderImport();
    await screen.findByLabelText('CSV file to import');
    await uploadFile(container);

    await screen.findByText('Column mapping');
    expect(screen.getByText('Some columns were not recognized')).toBeInTheDocument();
    // Named in the mapping list and again in the warning, so the operator cannot miss it.
    expect(screen.getAllByText(/loyalty_points/).length).toBeGreaterThan(0);
  });

  it('starts a probable duplicate undecided and offers no merge option at all', async () => {
    const { container } = renderImport();
    await screen.findByLabelText('CSV file to import');
    await uploadFile(container);

    await screen.findByRole('heading', { name: 'Possible duplicates' });
    const select = screen.getByLabelText('Decision 3');
    // UAT-XX-05: no decision is made on the operator's behalf, not even "skip".
    expect(select).toHaveValue('');
    expect(select).toBeRequired();
    expect(select).toHaveAttribute('aria-invalid', 'true');

    const options = within(select).getAllByRole('option').map((option) => option.textContent);
    expect(options).toEqual(['Choose a decision', 'Skip this row', 'Create separate customer']);
    expect(options.join(' ')).not.toMatch(/merge/i);
  });

  it('keeps the import disabled, and says why, until every duplicate is decided', async () => {
    const { container, handler } = renderImport();
    await screen.findByLabelText('CSV file to import');
    await uploadFile(container);

    const button = await screen.findByRole('button', { name: /Import 1 customer/ });
    expect(button).toBeDisabled();
    const hint = screen.getByText(/1 possible duplicate\(s\) still need a decision/);
    expect(hint).toHaveAttribute('id', 'import-undecided-hint');
    expect(hint).toHaveAttribute('aria-live', 'polite');
    expect(button).toHaveAttribute('aria-describedby', 'import-undecided-hint');

    await userEvent.click(button);
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(handler.mock.calls.filter(([url]) => String(url).includes('/commit'))).toHaveLength(0);

    await decideDuplicate('skip');
    expect(screen.getByRole('button', { name: /Import 1 customer/ })).toBeEnabled();
    expect(screen.queryByText(/still need a decision/)).not.toBeInTheDocument();
    expect(screen.getByLabelText('Decision 3')).not.toHaveAttribute('aria-invalid');
  });

  it('counts every undecided duplicate, and going back to no choice blocks the import again', async () => {
    const duplicateRow = PREVIEW.rows[1];
    const previewBody = {
      ...PREVIEW,
      counts: { ...PREVIEW.counts, duplicate_review: 2 },
      rows: [...PREVIEW.rows, { ...duplicateRow, row_number: 5, source_record_id: 'row:ddd' }],
    };
    const { container } = renderImport({ previewBody });
    await screen.findByLabelText('CSV file to import');
    await uploadFile(container);

    await screen.findByText(/2 possible duplicate\(s\) still need a decision/);
    await userEvent.selectOptions(screen.getByLabelText('Decision 3'), 'skip');
    expect(await screen.findByText(/1 possible duplicate\(s\) still need a decision/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Import 1 customer/ })).toBeDisabled();

    await userEvent.selectOptions(screen.getByLabelText('Decision 5'), 'create');
    expect(screen.getByRole('button', { name: /Import 2 customer/ })).toBeEnabled();

    await userEvent.selectOptions(screen.getByLabelText('Decision 5'), '');
    expect(await screen.findByText(/1 possible duplicate\(s\) still need a decision/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Import 1 customer/ })).toBeDisabled();
  });

  it('sends an explicit skip decision, not an absent one', async () => {
    const { container, handler } = renderImport();
    await screen.findByLabelText('CSV file to import');
    await uploadFile(container);

    await decideDuplicate('skip');
    await userEvent.click(screen.getByRole('button', { name: /Import 1 customer/ }));
    await userEvent.click(await screen.findByRole('button', { name: 'Yes, import now' }));

    await waitFor(() => {
      const call = handler.mock.calls.find(([url]) => String(url).includes('/commit'));
      expect(JSON.parse(call[1].body.get('decisions_json'))).toEqual({ 3: 'skip' });
    });
  });

  it('explains that duplicates are never merged automatically', async () => {
    const { container } = renderImport();
    await screen.findByLabelText('CSV file to import');
    await uploadFile(container);

    await screen.findByRole('heading', { name: 'Possible duplicates' });
    expect(screen.getByText('Nothing is merged automatically')).toBeInTheDocument();
    expect(screen.getByText(/never merges two people together/i)).toBeInTheDocument();
  });

  it('links a duplicate candidate to the existing customer record', async () => {
    const { container } = renderImport();
    await screen.findByLabelText('CSV file to import');
    await uploadFile(container);

    await screen.findByRole('heading', { name: 'Possible duplicates' });
    const link = screen.getAllByRole('link', { name: 'Nguyễn Thị Bích Hạnh' })[0];
    expect(link).toHaveAttribute('href', '/customers/7');
  });

  it('shows the row-level reason a row cannot be imported', async () => {
    const { container } = renderImport();
    await screen.findByLabelText('CSV file to import');
    await uploadFile(container);

    await screen.findByRole('heading', { name: 'Every row' });
    expect(
      screen.getByText('Full name is required and this row has none.'),
    ).toBeInTheDocument();
  });

  it('offers no overwrite option in the conflict policy', async () => {
    const { container } = renderImport();
    await screen.findByLabelText('CSV file to import');
    await uploadFile(container);

    const select = await screen.findByLabelText(
      'When a row matches a record this import created previously',
    );
    const options = within(select).getAllByRole('option').map((option) => option.textContent);
    expect(options).toEqual([
      'Leave the existing record untouched',
      'Fill fields that are empty, and only those',
    ]);
    expect(options.join(' ')).not.toMatch(/overwrite|replace/i);
  });

  it('requires an explicit confirmation before committing', async () => {
    const { container, handler } = renderImport();
    await screen.findByLabelText('CSV file to import');
    await uploadFile(container);

    await decideDuplicate();
    const commitCalls = () =>
      handler.mock.calls.filter(([url]) => String(url).includes('/commit'));

    // Clicking the primary action opens a confirmation; it does not commit.
    await userEvent.click(screen.getByRole('button', { name: /Import 1 customer/ }));
    expect(await screen.findByRole('dialog')).toBeInTheDocument();
    expect(commitCalls()).toHaveLength(0);

    await userEvent.click(screen.getByRole('button', { name: 'Yes, import now' }));
    await waitFor(() => expect(commitCalls()).toHaveLength(1));
  });

  it('says in the confirmation exactly what will and will not happen', async () => {
    const { container } = renderImport();
    await screen.findByLabelText('CSV file to import');
    await uploadFile(container);

    await decideDuplicate();
    await userEvent.click(screen.getByRole('button', { name: /Import 1 customer/ }));
    const dialog = await screen.findByRole('dialog');

    expect(within(dialog).getByText(/1 customer record\(s\) will be created/)).toBeInTheDocument();
    expect(within(dialog).getByText(/1 possible duplicate\(s\) will be skipped/)).toBeInTheDocument();
    expect(within(dialog).getByText(/1 row\(s\) cannot be imported/)).toBeInTheDocument();
  });

  it('sends the digest the preview returned, so the file cannot have changed', async () => {
    const { container, handler } = renderImport();
    await screen.findByLabelText('CSV file to import');
    await uploadFile(container);

    await decideDuplicate();
    await userEvent.click(screen.getByRole('button', { name: /Import 1 customer/ }));
    await userEvent.click(await screen.findByRole('button', { name: 'Yes, import now' }));

    await waitFor(() => {
      const call = handler.mock.calls.find(([url]) => String(url).includes('/commit'));
      expect(call).toBeDefined();
      const body = call[1].body;
      expect(body.get('content_sha256')).toBe('abc123def456');
      expect(body.get('confirm')).toBe('true');
      expect(body.get('file')).toBeInstanceOf(File);
    });
  });

  it('sends the duplicate decision the operator actually chose', async () => {
    const { container, handler } = renderImport();
    await screen.findByLabelText('CSV file to import');
    await uploadFile(container);

    await screen.findByRole('heading', { name: 'Possible duplicates' });
    await userEvent.selectOptions(screen.getByLabelText('Decision 3'), 'create');

    await userEvent.click(screen.getByRole('button', { name: /Import 2 customer/ }));
    await userEvent.click(await screen.findByRole('button', { name: 'Yes, import now' }));

    await waitFor(() => {
      const call = handler.mock.calls.find(([url]) => String(url).includes('/commit'));
      expect(JSON.parse(call[1].body.get('decisions_json'))).toEqual({ 3: 'create' });
    });
  });

  it('says that cancelling before the commit costs nothing, and cancelling works', async () => {
    const { container } = renderImport();
    await screen.findByLabelText('CSV file to import');
    await uploadFile(container);

    await screen.findByRole('heading', { name: 'Every row' });
    expect(
      screen.getByText(/Cancelling now costs nothing/i),
    ).toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: 'Cancel and start over' }));
    expect(await screen.findByLabelText('CSV file to import')).toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: 'Every row' })).not.toBeInTheDocument();
  });

  it('shows a durable summary naming the batch after committing', async () => {
    const { container } = renderImport();
    await screen.findByLabelText('CSV file to import');
    await uploadFile(container);

    await decideDuplicate();
    await userEvent.click(screen.getByRole('button', { name: /Import 1 customer/ }));
    await userEvent.click(await screen.findByRole('button', { name: 'Yes, import now' }));

    expect(await screen.findByText('Import finished')).toBeInTheDocument();
    // Named in the success banner and again in the durable-summary note.
    expect(screen.getAllByText(/IMP-000001/).length).toBeGreaterThan(0);
    expect(screen.getAllByText('Created').length).toBeGreaterThan(0);
  });

  it('links each created customer from the summary', async () => {
    const { container } = renderImport();
    await screen.findByLabelText('CSV file to import');
    await uploadFile(container);

    await decideDuplicate();
    await userEvent.click(screen.getByRole('button', { name: /Import 1 customer/ }));
    await userEvent.click(await screen.findByRole('button', { name: 'Yes, import now' }));

    await screen.findByText('Import finished');
    expect(screen.getByRole('link', { name: 'STCA-000009' })).toHaveAttribute(
      'href',
      '/customers/9',
    );
  });

  it('explains a rejected file in the operator\'s terms', async () => {
    const { container } = renderImport({ previewStatus: 422 });
    await screen.findByLabelText('CSV file to import');
    await uploadFile(container);

    expect(await screen.findByText('This file cannot be read')).toBeInTheDocument();
    expect(screen.getByText(/ZIP archive or an .xlsx workbook/)).toBeInTheDocument();
    // And the flow stays on step one rather than pretending to have a preview.
    expect(screen.queryByRole('heading', { name: 'Every row' })).not.toBeInTheDocument();
  });

  it('hides the commit action from a role that can only preview', async () => {
    const { container } = renderImport({
      permissions: ['import:template', 'import:preview', 'duplicate:review', 'customer:read'],
    });
    await screen.findByLabelText('CSV file to import');
    await uploadFile(container);

    await screen.findByRole('heading', { name: 'Every row' });
    expect(screen.queryByRole('button', { name: /Import 1 customer/ })).not.toBeInTheDocument();
    expect(
      screen.getByText(/can preview an import but not commit one/i),
    ).toBeInTheDocument();
  });

  it('hides the template download from a role without that permission', async () => {
    renderImport({ permissions: ['import:preview', 'duplicate:review', 'customer:read'] });
    await screen.findByLabelText('CSV file to import');
    expect(screen.queryByRole('button', { name: 'Download template' })).not.toBeInTheDocument();
  });

  it('keeps the confirmation dialog focus-trapped and closable', async () => {
    const { container } = renderImport();
    await screen.findByLabelText('CSV file to import');
    await uploadFile(container);

    await decideDuplicate();
    await userEvent.click(screen.getByRole('button', { name: /Import 1 customer/ }));
    const dialog = await screen.findByRole('dialog');
    expect(dialog).toHaveAttribute('aria-modal', 'true');

    await userEvent.keyboard('{Escape}');
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
  });

  it('preserves Vietnamese diacritics through the preview', async () => {
    const { container } = renderImport();
    await screen.findByLabelText('CSV file to import');
    await uploadFile(container);

    await screen.findByRole('heading', { name: 'Every row' });
    expect(screen.getAllByText('Trần Quốc Tuấn').length).toBeGreaterThan(0);
    expect(screen.getAllByText('Nguyễn Thị Bích Hạnh').length).toBeGreaterThan(0);
  });
});
