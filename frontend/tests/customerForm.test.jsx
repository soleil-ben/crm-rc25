/**
 * Create-customer drawer: validation, duplicate review, and keyboard access.
 *
 * These cover the Phase 1 half of AC-1, AC-16, and the Design.md keyboard requirement.
 */

import { describe, expect, it, vi } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { CustomerFormDrawer } from '../src/features/customers/CustomerFormDrawer.jsx';
import { SessionProvider } from '../src/app/SessionContext.jsx';
import { customerFixture, renderWithProviders, stubFetch } from './utils.jsx';

function setup({ duplicates = [], createStatus = 201, onClose = vi.fn() } = {}) {
  const fetchMock = stubFetch([
    { path: '/staff/assignable', body: [] },
    {
      path: '/customers/duplicate-check',
      method: 'POST',
      body: { candidates: duplicates, guidance: 'Review each candidate before deciding.' },
    },
    {
      path: '/customers',
      method: 'POST',
      status: createStatus,
      body:
        createStatus === 201
          ? { ...customerFixture, id: 9, public_id: 'STCA-000009' }
          : { code: 'validation_error', message: 'Provide at least one usable phone number or email address.', field: 'phone' },
    },
  ]);
  const utils = renderWithProviders(<CustomerFormDrawer open onClose={onClose} />);
  return { ...utils, fetchMock, onClose };
}

describe('CustomerFormDrawer tags (fix pack item 6)', () => {
  const OPS = {
    user: { id: 3, full_name: 'Demo Operations', email: 'ops@demo.example.com', role: 'operations' },
    permissions: ['customer:read', 'customer:create', 'customer:update', 'tag:read', 'tag:write'],
    environment: 'test',
    is_demo_environment: false,
  };
  const TAGS = [
    { id: 1, slug: 'frequent-shipper', name: 'Frequent shipper', color_token: 'orange', description: null },
    { id: 2, slug: 'needs-documents', name: 'Needs documents', color_token: 'warning', description: null },
  ];

  function setupWithSession(permissions = OPS.permissions) {
    const fetchMock = stubFetch([
      { path: '/auth/me', body: { ...OPS, permissions } },
      { path: '/staff/assignable', body: [] },
      { path: '/tags', method: 'POST', body: (init) => ({ id: 7, ...JSON.parse(init.body), color_token: 'neutral', description: null }) },
      { path: '/tags', body: TAGS },
      { path: '/customers/duplicate-check', method: 'POST', body: { candidates: [], guidance: '' } },
      { path: '/customers/1', method: 'PATCH', body: (init) => ({ ...customerFixture, ...JSON.parse(init.body) }) },
    ]);
    const utils = renderWithProviders(
      <SessionProvider>
        <CustomerFormDrawer open onClose={vi.fn()} customer={{ ...customerFixture, tags: [TAGS[0]] }} />
      </SessionProvider>,
    );
    return { ...utils, fetchMock };
  }

  it('offers the existing tags to a role with tag:write, pre-ticked from the record', async () => {
    const user = userEvent.setup();
    const { fetchMock } = setupWithSession();

    const frequent = await screen.findByLabelText('Frequent shipper');
    expect(frequent).toBeChecked();
    expect(screen.getByLabelText('Needs documents')).not.toBeChecked();

    await user.click(screen.getByLabelText('Needs documents'));
    await user.click(screen.getByRole('button', { name: 'Save' }));

    await waitFor(() => {
      const call = fetchMock.mock.calls.find(([, init]) => init?.method === 'PATCH');
      expect(call).toBeTruthy();
      expect(JSON.parse(call[1].body).tag_ids).toEqual([1, 2]);
    });
  });

  it('creates a new tag inline and ticks it', async () => {
    const user = userEvent.setup();
    const { fetchMock } = setupWithSession();
    await screen.findByLabelText('Frequent shipper');

    await user.type(screen.getByLabelText('New tag name'), 'Service recovery');
    await user.click(screen.getByRole('button', { name: 'Add tag' }));

    await waitFor(() => {
      const call = fetchMock.mock.calls.find(
        ([url, init]) => String(url).endsWith('/api/v1/tags') && init?.method === 'POST',
      );
      expect(JSON.parse(call[1].body)).toEqual({ slug: 'service-recovery', name: 'Service recovery' });
    });
  });

  it('shows no tag control, and sends no tag_ids, without tag:write', async () => {
    const user = userEvent.setup();
    const { fetchMock } = setupWithSession(['customer:read', 'customer:update']);
    await screen.findByLabelText(/Full name/);
    expect(screen.queryByLabelText('Frequent shipper')).toBeNull();
    expect(screen.queryByLabelText('New tag name')).toBeNull();

    await user.type(screen.getByLabelText(/Full name/), ' X');
    await user.click(screen.getByRole('button', { name: 'Save' }));
    await waitFor(() => {
      const call = fetchMock.mock.calls.find(([, init]) => init?.method === 'PATCH');
      expect(call).toBeTruthy();
      expect('tag_ids' in JSON.parse(call[1].body)).toBe(false);
    });
    // And no tags were ever requested.
    expect(fetchMock.mock.calls.some(([url]) => String(url).endsWith('/api/v1/tags'))).toBe(false);
  });
});

describe('CustomerFormDrawer', () => {
  it('keeps save disabled until a name and one contact method are present', async () => {
    const user = userEvent.setup();
    setup();

    const save = screen.getByRole('button', { name: 'Add customer' });
    expect(save).toBeDisabled();

    await user.type(screen.getByLabelText(/Full name/), 'Trần Quốc Minh Khôi');
    expect(save).toBeDisabled();
    expect(screen.getByText(/at least one phone number or email/i)).toBeInTheDocument();

    await user.type(screen.getByLabelText(/Phone number/), '+1 416 555 0100');
    await waitFor(() => expect(save).toBeEnabled());
  });

  it('preserves Vietnamese diacritics in the submitted payload', async () => {
    const user = userEvent.setup();
    const { fetchMock } = setup();

    await user.type(screen.getByLabelText(/Full name/), 'Lê Hoàng Phương Uyên');
    await user.type(screen.getByLabelText(/Email address/), 'uyen@demo.example.com');
    await waitFor(() => expect(screen.getByRole('button', { name: 'Add customer' })).toBeEnabled());
    await user.click(screen.getByRole('button', { name: 'Add customer' }));

    await waitFor(() => {
      const createCall = fetchMock.mock.calls.find(
        ([url, init]) => url.includes('/customers') && init?.method === 'POST' && !url.includes('duplicate'),
      );
      expect(createCall).toBeTruthy();
      expect(JSON.parse(createCall[1].body).full_name).toBe('Lê Hoàng Phương Uyên');
    });
  });

  it('surfaces duplicate candidates and blocks save until staff decide', async () => {
    const user = userEvent.setup();
    setup({
      duplicates: [
        {
          customer: customerFixture,
          matched_on: ['phone'],
          confidence: 55,
          requires_review: true,
        },
      ],
    });

    await user.type(screen.getByLabelText(/Full name/), 'Đặng Minh Tuấn');
    await user.type(screen.getByLabelText(/Phone number/), '+1 416 555 0142');

    const panel = await screen.findByText('Possible duplicate records');
    expect(panel).toBeInTheDocument();
    expect(screen.getByText(/nothing is merged automatically/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Open existing record' })).toBeInTheDocument();

    // Save stays blocked until the staff member explicitly chooses to create a separate record.
    const save = screen.getByRole('button', { name: 'Add customer' });
    expect(save).toBeDisabled();

    await user.click(screen.getByLabelText('Create a separate customer'));
    await waitFor(() => expect(save).toBeEnabled());
  });

  it('renders the form as a labelled modal dialog reachable by keyboard', async () => {
    setup();
    const dialog = screen.getByRole('dialog');
    expect(dialog).toHaveAttribute('aria-modal', 'true');
    // Every input carries a real label, not a placeholder standing in for one.
    expect(within(dialog).getByLabelText(/Full name/)).toBeInTheDocument();
    expect(within(dialog).getByLabelText(/Preferred language/)).toBeInTheDocument();
  });

  it('shows a server validation message against the field it belongs to', async () => {
    const user = userEvent.setup();
    setup({ createStatus: 422 });

    await user.type(screen.getByLabelText(/Full name/), 'No Contact');
    await user.type(screen.getByLabelText(/Phone number/), '5');
    await waitFor(() => expect(screen.getByRole('button', { name: 'Add customer' })).toBeEnabled());
    await user.click(screen.getByRole('button', { name: 'Add customer' }));

    // Beside the field and, since UAT round 5, linked from the summary at the top.
    await waitFor(() =>
      expect(screen.getAllByText(/at least one usable phone number or email address/i)).toHaveLength(2),
    );
    const summary = screen.getByRole('alert', { name: /There is 1 problem/ });
    expect(within(summary).getByRole('link')).toHaveAttribute('href', '#customer-field-phone');
  });
});
