/**
 * The Settings integration panel must stay honest.
 *
 * `Design.md` section 13 asks for provider cards. There is no provider, so this panel
 * describes the infrastructure instead — and the tests that matter here are the ones
 * asserting what it does **not** show: no Connect button, no Verify button, no fabricated
 * uptime or freshness, and no claim of a connection.
 *
 * The `stale_assignment_count` case is the one worth reading twice. The API returns
 * `null`, and the panel must render that as "not measured" rather than as `0`, because
 * "0 stale" tells a staff member everything is fresh — which nothing here can support.
 */

import { describe, expect, it } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { IntegrationPanel } from '../src/features/settings/IntegrationPanel.jsx';
import { SessionProvider } from '../src/app/SessionContext.jsx';
import { renderWithProviders, stubFetch } from './utils.jsx';

/** A signed-in admin, carrying both integration permissions. */
const ADMIN_SESSION = {
  user: {
    id: 1,
    full_name: 'Test Admin',
    email: 'admin@demo.example.com',
    role: 'admin',
    initials: 'TA',
    timezone: 'America/Toronto',
    locale: 'en',
  },
  permissions: ['settings:read', 'integration:read', 'integration:manage'],
  csrf_token: 'test-csrf',
};

/** A reader who may see health but may not change the integration. */
const READ_ONLY_SESSION = {
  ...ADMIN_SESSION,
  user: { ...ADMIN_SESSION.user, role: 'read_only_manager' },
  permissions: ['settings:read', 'integration:read'],
};

/** What the API actually returns today, copied from a live response. */
const NOT_CONFIGURED = {
  any_provider_configured: false,
  connections: [
    {
      provider_key: null,
      state: 'not_configured',
      provider_api_version: null,
      display_label: null,
      connection_id: null,
      is_enabled: false,
      last_success_at: null,
      last_success_operation: null,
      last_error_at: null,
      last_error_code: null,
      last_error_summary: null,
    },
  ],
  jobs_pending: 0,
  jobs_running: 0,
  jobs_failed: 0,
  jobs_failed_terminal: 0,
  jobs_requiring_review: 0,
  oldest_pending_job_age_seconds: null,
  inbox_pending: 0,
  inbox_awaiting_verification: 0,
  inbox_rejected: 0,
  inbox_failed_terminal: 0,
  stale_assignment_count: null,
  stale_rule_description:
    'No freshness rule exists. A freshness threshold needs a provider notes update cadence, and no provider is configured.',
  worker: null,
  summary:
    'No provider account is connected. Automatic tracking is unavailable. Manual milestones and external carrier links continue to work.',
};

const EMPTY_REVIEW = { items: [], total: 0 };

function renderPanel({
  health = NOT_CONFIGURED,
  jobs = EMPTY_REVIEW,
  session = ADMIN_SESSION,
} = {}) {
  const fetchMock = stubFetch([
    { path: '/auth/me', body: session },
    { path: '/integrations/jobs/7/retry', method: 'POST', body: { id: 7, status: 'pending' } },
    { path: '/integrations/jobs', body: jobs },
    { path: '/integrations/health', body: health },
  ]);
  const rendered = renderWithProviders(
    <SessionProvider>
      <IntegrationPanel />
    </SessionProvider>,
  );
  return { ...rendered, fetchMock };
}


describe('IntegrationPanel', () => {
  it('is titled as infrastructure rather than as a provider connection', async () => {
    renderPanel();
    await screen.findByText('Integration infrastructure');

    expect(screen.getByText('Integration infrastructure')).toBeInTheDocument();
    // Not "Provider integrations", which would describe something that does not exist.
    expect(screen.queryByText(/^Provider integrations$/)).not.toBeInTheDocument();
  });

  it('says plainly that no provider account is connected', async () => {
    renderPanel();
    await screen.findByText('Integration infrastructure');

    // ``getAllByText``: the sentence appears both inside the <strong> and in the banner
    // that wraps it, so a single-match query would fail on the markup rather than on the
    // copy, which is what is actually under test.
    expect(screen.getAllByText(/No provider account is connected\./).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/Automatic tracking is unavailable\./).length).toBeGreaterThan(0);
  });

  it('reassures staff that manual milestones and external links still work', async () => {
    renderPanel();
    await screen.findByText('Integration infrastructure');

    expect(
      screen.getByText(/Manual milestones and external carrier links continue to work/),
    ).toBeInTheDocument();
  });

  it('offers no Connect and no Verify button', async () => {
    renderPanel();
    await screen.findByText('Integration infrastructure');

    for (const label of [/connect/i, /verify/i, /authorize/i, /test connection/i]) {
      expect(screen.queryByRole('button', { name: label })).not.toBeInTheDocument();
    }
  });

  it('offers no Disable button while nothing is configured', async () => {
    renderPanel();
    await screen.findByText('Integration infrastructure');

    expect(screen.queryByRole('button', { name: /disable/i })).not.toBeInTheDocument();
  });

  it('shows the connection state as Not configured', async () => {
    renderPanel();
    await screen.findByText('Integration infrastructure');

    expect(screen.getByText('Not configured')).toBeInTheDocument();
    expect(screen.queryByText('Connected')).not.toBeInTheDocument();
  });

  it('shows the provider version as unknown rather than inventing one', async () => {
    renderPanel();
    await screen.findByText('Integration infrastructure');

    expect(screen.getByText('Unknown until an account is verified')).toBeInTheDocument();
  });

  it('shows the last successful operation as Never', async () => {
    renderPanel();
    await screen.findByText('Integration infrastructure');

    expect(screen.getByText('Never')).toBeInTheDocument();
  });

  it('renders a null stale count as not measured, never as zero', async () => {
    renderPanel();
    await screen.findByText('Integration infrastructure');

    const staleLabel = screen.getByText('Stale tracking assignments');
    const staleValue = staleLabel.parentElement.querySelector('dd');

    expect(staleValue).toHaveTextContent('Not measured');
    expect(staleValue).not.toHaveTextContent('0');
    expect(screen.getByText(/No freshness rule exists/)).toBeInTheDocument();
  });

  it('says no worker has reported in rather than showing a fabricated heartbeat', async () => {
    renderPanel();
    await screen.findByText('Integration infrastructure');

    expect(
      screen.getByText(/No worker has reported in. Nothing is scheduled to run\./),
    ).toBeInTheDocument();
  });

  it('states that no request has ever been made to a provider', async () => {
    renderPanel();
    await screen.findByText('Integration infrastructure');

    expect(
      screen.getByText(/No request has ever been made to a carrier or to a provider/),
    ).toBeInTheDocument();
  });

  it('claims no synchronization anywhere on the panel', async () => {
    renderPanel();
    await screen.findByText('Integration infrastructure');

    const text = document.body.textContent.toLowerCase();
    for (const claim of ['synchroni', 'last successful sync', 'uptime', 'healthy', 'live']) {
      expect(text).not.toContain(claim);
    }
  });

  it('shows an empty review queue when nothing has failed', async () => {
    renderPanel();
    await screen.findByText('Integration infrastructure');

    expect(await screen.findByText('No failed jobs.')).toBeInTheDocument();
  });
});

describe('IntegrationPanel with failed jobs', () => {
  const FAILED = {
    items: [
      {
        id: 7,
        job_type: 'reconcile_tracking_assignment',
        provider_key: 'fake',
        status: 'failed_terminal',
        attempt_count: 5,
        max_attempts: 5,
        priority: 100,
        available_at: '2026-09-01T09:00:00',
        last_attempt_at: '2026-09-01T09:05:00',
        next_retry_at: null,
        provider_retry_after_seconds: null,
        error_code: 'retryable',
        error_summary: 'provider request timed out',
        requires_review: true,
        manual_retry_count: 0,
        last_manual_retry_at: null,
        completed_at: null,
        failed_at: '2026-09-01T09:05:00',
        shipment_id: null,
        tracking_assignment_id: null,
        inbox_item_id: null,
      },
    ],
    total: 1,
  };

  it('lists a failed job with its category and redacted summary', async () => {
    renderPanel({ jobs: FAILED });
    await screen.findByText('Integration infrastructure');

    expect(await screen.findByText('reconcile_tracking_assignment')).toBeInTheDocument();
    expect(screen.getByText('provider request timed out')).toBeInTheDocument();
    expect(screen.getByText('5 / 5')).toBeInTheDocument();
  });

  it('offers a retry that explains it preserves the failure history', async () => {
    renderPanel({ jobs: FAILED });
    await screen.findByText('Integration infrastructure');

    expect(await screen.findByRole('button', { name: 'Retry job' })).toBeInTheDocument();
  });

  it('sends the retry to the job it belongs to', async () => {
    renderPanel({ jobs: FAILED });
    await screen.findByText('Integration infrastructure');
    const button = await screen.findByRole('button', { name: 'Retry job' });

    await userEvent.click(button);

    await waitFor(() => {
      const calls = global.fetch.mock.calls.map((call) => String(call[0]));
      expect(calls.some((url) => url.includes('/integrations/jobs/7/retry'))).toBe(true);
    });
  });
});

describe('IntegrationPanel without the manage permission', () => {
  it('shows the review queue but offers no retry button', async () => {
    renderPanel({
      session: READ_ONLY_SESSION,
      jobs: {
        items: [
          {
            id: 7,
            job_type: 'reconcile_tracking_assignment',
            provider_key: 'fake',
            status: 'failed_terminal',
            attempt_count: 5,
            max_attempts: 5,
            priority: 100,
            available_at: '2026-09-01T09:00:00',
            error_code: 'retryable',
            error_summary: 'provider request timed out',
            requires_review: true,
            manual_retry_count: 0,
          },
        ],
        total: 1,
      },
    });

    expect(await screen.findByText('reconcile_tracking_assignment')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Retry job' })).not.toBeInTheDocument();
  });
});
