/** Customer list behaviour: rendering, accented names, states, and filter chips. */

import { describe, expect, it } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Route, Routes } from 'react-router-dom';
import { CustomerListPage, CustomerNewPage } from '../src/features/customers/CustomerListPage.jsx';
import { SessionProvider } from '../src/app/SessionContext.jsx';
import { customerFixture, renderWithProviders, stubFetch } from './utils.jsx';

const SESSION = {
  user: { id: 1, full_name: 'Test Admin', email: 'admin@demo.example.com', role: 'admin', initials: 'TA', timezone: 'America/Toronto', locale: 'en' },
  permissions: ['customer:read', 'customer:create', 'export:customers', 'task:read'],
  environment: 'test',
  is_demo_environment: false,
};

function renderList({ items = [customerFixture], total = 1, status = 200 } = {}) {
  stubFetch([
    { path: '/auth/me', body: SESSION },
    { path: '/staff/assignable', body: [] },
    {
      path: '/customers',
      status,
      body: status === 200 ? { items, total, limit: 25, offset: 0 } : { code: 'permission_denied', message: 'Your role does not allow this action.' },
    },
  ]);
  return renderWithProviders(
    <SessionProvider>
      <CustomerListPage />
    </SessionProvider>,
  );
}

describe('CustomerListPage', () => {
  it('renders customers with accented names intact', async () => {
    renderList();
    expect(await screen.findByText('Nguyễn Thị Bích Hạnh')).toBeInTheDocument();
    expect(screen.getByText('STCA-000001')).toBeInTheDocument();
  });

  it('shows the derived lifecycle status and qualifying shipment count', async () => {
    renderList();
    await screen.findByText('Nguyễn Thị Bích Hạnh');
    const table = screen.getByRole('table', { name: 'Customers' });
    // The filter dropdown also contains "Active"; assert against the row itself.
    expect(within(table).getByText('Active')).toBeInTheDocument();
    expect(within(table).getByText('3')).toBeInTheDocument();
  });

  it('shows an empty state that explains filters when a search returns nothing', async () => {
    const user = userEvent.setup();
    renderList({ items: [], total: 0 });
    await screen.findByRole('heading', { name: 'Customers' });

    await user.type(screen.getByPlaceholderText(/Search name/i), 'zzz');
    await waitFor(() =>
      expect(screen.getByText('No customers match these filters')).toBeInTheDocument(),
    );
    expect(screen.getByRole('button', { name: 'Clear filters' })).toBeInTheDocument();
  });

  it('renders a permission-denied state rather than a generic error', async () => {
    renderList({ status: 403 });
    expect(await screen.findByText('You do not have access to this')).toBeInTheDocument();
  });

  it('offers the add-customer action when the role allows it', async () => {
    renderList();
    expect(await screen.findByRole('button', { name: 'Add customer' })).toBeInTheDocument();
  });

  it('applies ?q= from the URL as the search term (fix pack item 4)', async () => {
    const fetchMock = stubFetch([
      { path: '/auth/me', body: SESSION },
      { path: '/staff/assignable', body: [] },
      { path: '/customers', body: { items: [customerFixture], total: 1, limit: 25, offset: 0 } },
    ]);
    renderWithProviders(
      <SessionProvider>
        <CustomerListPage />
      </SessionProvider>,
      { route: '/customers?q=h%E1%BA%A1nh' },
    );
    await screen.findByText('Nguyễn Thị Bích Hạnh');

    const listCall = fetchMock.mock.calls.find(([url]) => String(url).includes('/api/v1/customers?'));
    expect(decodeURIComponent(String(listCall[0]))).toContain('search=hạnh');
    expect(screen.getByPlaceholderText(/Search name/i)).toHaveValue('hạnh');
    // The term is not a removable chip -- it has the search box.
    expect(screen.queryByText(/^q:/)).toBeNull();
  });
});

describe('Tags on the customer list (UAT-OP-17, fix pack 2 item 3)', () => {
  const TAGS = [
    { id: 1, slug: 'frequent-shipper', name: 'Frequent shipper', color_token: 'orange', description: null },
    { id: 2, slug: 'needs-documents', name: 'Needs documents', color_token: 'warning', description: null },
  ];

  function renderTagged(route = '/customers') {
    const fetchMock = stubFetch([
      { path: '/auth/me', body: { ...SESSION, permissions: [...SESSION.permissions, 'tag:read'] } },
      { path: '/staff/assignable', body: [] },
      { path: '/tags', body: TAGS },
      {
        path: '/customers',
        body: {
          items: [{ ...customerFixture, tags: [TAGS[0]] }],
          total: 1,
          limit: 25,
          offset: 0,
        },
      },
    ]);
    renderWithProviders(
      <SessionProvider>
        <CustomerListPage />
      </SessionProvider>,
      { route },
    );
    return fetchMock;
  }

  it('shows each customer’s tags in a Tags column', async () => {
    renderTagged();
    const table = await screen.findByRole('table', { name: 'Customers' });
    expect(within(table).getByRole('columnheader', { name: 'Tags' })).toBeInTheDocument();
    expect(within(table).getByText('Frequent shipper')).toBeInTheDocument();
  });

  it('filters by tag from More filters and names the tag in the chip', async () => {
    const user = userEvent.setup();
    const fetchMock = renderTagged();
    await screen.findByRole('table', { name: 'Customers' });
    await user.click(screen.getByRole('button', { name: 'More filters' }));
    await user.selectOptions(screen.getByLabelText('Tag'), '2');

    await waitFor(() => {
      const listed = fetchMock.mock.calls
        .map(([url]) => String(url))
        .filter((url) => url.includes('/api/v1/customers?'));
      expect(listed.some((url) => url.includes('tag_id=2'))).toBe(true);
    });
    expect(await screen.findByText('Tag: Needs documents')).toBeInTheDocument();
  });

  it('applies a tag filter that arrives in the URL', async () => {
    const fetchMock = renderTagged('/customers?tag_id=1');
    await screen.findByRole('table', { name: 'Customers' });
    const listed = fetchMock.mock.calls
      .map(([url]) => String(url))
      .filter((url) => url.includes('/api/v1/customers?'));
    expect(listed.every((url) => url.includes('tag_id=1'))).toBe(true);
  });
});

describe('CustomerNewPage', () => {
  it('opens the create drawer for a role that may create', async () => {
    stubFetch([
      { path: '/auth/me', body: SESSION },
      { path: '/staff/assignable', body: [] },
      { path: '/customers/duplicate-check', method: 'POST', body: { candidates: [] } },
      { path: '/customers', body: { items: [], total: 0, limit: 25, offset: 0 } },
    ]);
    renderWithProviders(
      <SessionProvider>
        <Routes>
          <Route path="/customers/new" element={<CustomerNewPage />} />
        </Routes>
      </SessionProvider>,
      { route: '/customers/new' },
    );
    expect(await screen.findByRole('dialog', { name: 'Add customer' })).toBeInTheDocument();
  });

  it('shows a clear refusal, not a validation message, to a read-only role', async () => {
    stubFetch([
      { path: '/auth/me', body: { ...SESSION, permissions: ['customer:read'] } },
    ]);
    renderWithProviders(
      <SessionProvider>
        <Routes>
          <Route path="/customers/new" element={<CustomerNewPage />} />
        </Routes>
      </SessionProvider>,
      { route: '/customers/new' },
    );
    expect(await screen.findByText('You do not have access to this')).toBeInTheDocument();
    expect(screen.getByText(/Your role can view customers but not add them/)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Back to customers' })).toHaveAttribute('href', '/customers');
    expect(document.body.textContent).not.toMatch(/valid integer/);
    // No customer named "new" was ever requested.
    expect(window.fetch.mock.calls.some(([url]) => String(url).includes('/customers/new'))).toBe(false);
  });
});
