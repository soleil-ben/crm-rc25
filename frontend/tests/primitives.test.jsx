/** Design-system guarantees: status text, focus handling, and the API client contract. */

import { describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { I18nProvider } from '../src/i18n/index.jsx';
import { CopyableId, Drawer, StatusBadge } from '../src/components/ui/index.jsx';
import { ErrorState } from '../src/components/state/index.jsx';
import { ApiError, api } from '../src/api/client.js';
import { formatMoney, formatPercent, relativeDays } from '../src/utils/format.js';
import { stubFetch } from './utils.jsx';

function withI18n(ui) {
  return render(<I18nProvider>{ui}</I18nProvider>);
}

describe('StatusBadge', () => {
  it('always renders a text label, never colour alone', () => {
    withI18n(<StatusBadge kind="lifecycle" value="at_risk" />);
    expect(screen.getByText('At risk')).toBeInTheDocument();
  });

  it('uses the same tone for one state everywhere it appears', () => {
    const { container: first } = withI18n(<StatusBadge kind="lifecycle" value="active" />);
    const { container: second } = withI18n(<StatusBadge kind="lifecycle" value="active" />);
    expect(first.querySelector('.badge').className).toBe(second.querySelector('.badge').className);
  });

  it('renders task and consent states with their own labels', () => {
    withI18n(<StatusBadge kind="task" value="waiting_for_customer" />);
    expect(screen.getByText('Waiting for customer')).toBeInTheDocument();
  });
});

describe('CopyableId', () => {
  it('exposes an accessible copy action that puts the identifier on the clipboard', async () => {
    const user = userEvent.setup();
    withI18n(<CopyableId value="STCA-000123" />);
    expect(screen.getByText('STCA-000123')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: /Copy STCA-000123/ }));
    await waitFor(async () => {
      expect(await navigator.clipboard.readText()).toBe('STCA-000123');
    });
  });
});

describe('Drawer', () => {
  it('is a labelled modal dialog and closes on Escape', async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    withI18n(
      <Drawer open onClose={onClose} title="Add customer">
        <input aria-label="Field" />
      </Drawer>,
    );

    const dialog = screen.getByRole('dialog');
    expect(dialog).toHaveAttribute('aria-modal', 'true');
    expect(dialog).toHaveAttribute('aria-label', 'Add customer');

    await user.keyboard('{Escape}');
    expect(onClose).toHaveBeenCalled();
  });

  it('moves focus into the dialog when it opens', async () => {
    withI18n(
      <Drawer open onClose={() => {}} title="Add customer">
        <input aria-label="First field" />
      </Drawer>,
    );
    await waitFor(() => expect(screen.getByLabelText('First field')).toHaveFocus());
  });
});

describe('ErrorState', () => {
  it('distinguishes permission denied from a generic failure', () => {
    withI18n(<ErrorState error={new ApiError({ status: 403, code: 'permission_denied', message: 'Nope' })} />);
    expect(screen.getByText('You do not have access to this')).toBeInTheDocument();
  });

  it('distinguishes not found', () => {
    withI18n(<ErrorState error={new ApiError({ status: 404, code: 'not_found', message: 'Missing' })} />);
    expect(screen.getByText('Not found')).toBeInTheDocument();
  });

  it('explains an offline failure', () => {
    withI18n(
      <ErrorState error={new ApiError({ status: 0, code: 'network_error', message: 'Could not reach the server' })} />,
    );
    expect(screen.getByText('Cannot reach the server')).toBeInTheDocument();
  });
});

describe('api client', () => {
  it('sends the CSRF header from the cookie on state-changing requests', async () => {
    document.cookie = 'solaris_csrf=token-123';
    const fetchMock = stubFetch([{ path: '/customers', method: 'POST', status: 201, body: { id: 1 } }]);
    await api.post('/customers', { full_name: 'Test' });
    const [, init] = fetchMock.mock.calls[0];
    expect(init.headers['X-CSRF-Token']).toBe('token-123');
    expect(init.credentials).toBe('same-origin');
  });

  it('never sends a CSRF header on a read', async () => {
    const fetchMock = stubFetch([{ path: '/customers', body: { items: [], total: 0 } }]);
    await api.get('/customers');
    const [, init] = fetchMock.mock.calls[0];
    expect(init.headers['X-CSRF-Token']).toBeUndefined();
  });

  it('turns a failed response into a typed ApiError', async () => {
    stubFetch([
      {
        path: '/customers',
        status: 403,
        body: { code: 'permission_denied', message: 'Your role does not allow this action.' },
      },
    ]);
    await expect(api.get('/customers')).rejects.toMatchObject({
      status: 403,
      code: 'permission_denied',
      isPermissionDenied: true,
    });
  });
});

describe('formatting', () => {
  it('reports a missing amount as Unknown, never as zero', () => {
    expect(formatMoney(null, 'CAD')).toBe('Unknown');
    expect(formatMoney(0, 'CAD')).not.toBe('Unknown');
  });

  it('renders each amount with its own currency code', () => {
    expect(formatMoney(120, 'CAD')).toContain('CAD');
    expect(formatMoney(120, 'USD')).toContain('USD');
  });

  it('renders a missing share as a dash rather than 0%', () => {
    expect(formatPercent(null)).toBe('—');
  });

  it('describes relative dates in plain language', () => {
    const yesterday = new Date(Date.now() - 86_400_000).toISOString();
    expect(relativeDays(yesterday)).toBe('yesterday');
  });
});
