/**
 * Settings → Integration infrastructure (Phase 4A).
 *
 * Titled for what it is. `Design.md` section 13 asks for provider cards showing source,
 * version, connection state, last successful sync, last error, and pending or failed
 * jobs — and there is no provider, so a card shaped like one would be a card about
 * nothing. This panel describes the **infrastructure** instead: the durable inbox, the
 * job queue, and the worker that a provider integration will eventually use.
 *
 * What it deliberately does not have:
 *
 * - **No Connect button, and no Verify button.** Neither could perform a real operation,
 *   and there is no endpoint behind either. `CRM.md` section 9 is explicit that receiving
 *   a tracking number or a URL does not authorize or enable API tracking; a button
 *   implying otherwise is the interface making that mistake on the customer's behalf.
 * - **No fake success, uptime, freshness, or synthetic health.** Every number here is a
 *   real count from the database, and every value that cannot be supported is shown as
 *   "not measured" rather than as zero. Stale assignments in particular: `0 stale` claims
 *   everything is fresh, which is a stronger and falser statement than "we cannot tell".
 * - **No Disable button while nothing is configured.** The action exists in the API and
 *   answers 404 with no connections, which is truthful; rendering the button anyway would
 *   not be.
 *
 * The retry action is real, because failed jobs are real: it is audited, adds one
 * attempt, and preserves the failure history.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { integrationsApi } from '../../api/endpoints.js';
import { useT } from '../../i18n/index.jsx';
import { P, useSession } from '../../app/SessionContext.jsx';
import { Banner, Button, Card, StatusBadge } from '../../components/ui/index.jsx';
import { EmptyState, ErrorState, SkeletonRows } from '../../components/state/index.jsx';
import { formatDateTime } from '../../utils/format.js';
import './settings.css';

/** Connection states, mapped to the badge tones used everywhere else. */
const STATE_TONE = {
  not_configured: 'neutral',
  disabled: 'neutral',
  verification_required: 'warning',
  connected: 'success',
  error: 'danger',
};

const STATE_KEY = {
  not_configured: 'stateNotConfigured',
  disabled: 'stateDisabled',
  verification_required: 'stateVerificationRequired',
  connected: 'stateConnected',
  error: 'stateError',
};

/** Seconds as a coarse, honest duration. Never rounded up into reassurance. */
function formatAge(seconds, t) {
  if (seconds === null || seconds === undefined) return t('integrations.none');
  if (seconds < 60) return `${seconds}s`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h`;
  return `${Math.floor(seconds / 86400)}d`;
}

function Row({ label, value, mono = false }) {
  return (
    <div className="settings-detail-row">
      <dt>{label}</dt>
      <dd className={mono ? 'mono' : undefined}>{value}</dd>
    </div>
  );
}

export function IntegrationPanel() {
  const t = useT();
  const { can } = useSession();
  const queryClient = useQueryClient();

  const healthQuery = useQuery({
    queryKey: ['integration-health'],
    queryFn: integrationsApi.health,
  });

  const reviewQuery = useQuery({
    queryKey: ['integration-jobs', 'review'],
    queryFn: () => integrationsApi.jobs({ review_only: true, limit: 25 }),
  });

  const retryMutation = useMutation({
    mutationFn: (id) => integrationsApi.retryJob(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['integration-health'] });
      queryClient.invalidateQueries({ queryKey: ['integration-jobs'] });
    },
  });

  if (healthQuery.isLoading) return <SkeletonRows rows={4} height={72} />;
  if (healthQuery.error) {
    return <ErrorState error={healthQuery.error} onRetry={healthQuery.refetch} />;
  }

  const health = healthQuery.data;
  const connection = health.connections?.[0];
  const state = connection?.state ?? 'not_configured';
  const configured = health.any_provider_configured;

  return (
    <>
      <Card title={t('integrations.title')}>
        <p className="settings-note">{t('integrations.subtitle')}</p>

        {!configured && (
          <Banner tone="neutral">
            <strong>{t('integrations.notConnected')}</strong> {t('integrations.automaticUnavailable')}{' '}
            {t('integrations.manualStillWorks')}
          </Banner>
        )}

        <dl className="settings-detail-list" style={{ marginTop: 'var(--space-4)' }}>
          <Row
            label={t('integrations.connectionState')}
            value={
              <StatusBadge
                tone={STATE_TONE[state] ?? 'neutral'}
                value={state}
                label={t(`integrations.${STATE_KEY[state] ?? 'stateNotConfigured'}`)}
              />
            }
          />
          <Row
            label={t('integrations.providerVersion')}
            // Shown only when genuinely known. An unverified account has no version, and a
            // plausible-looking string here would be the first thing somebody believed.
            value={
              connection?.provider_key
                ? `${connection.provider_key} ${connection.provider_api_version ?? ''}`.trim()
                : t('integrations.unknownUntilVerified')
            }
          />
          <Row
            label={t('integrations.lastSuccess')}
            value={
              connection?.last_success_at
                ? formatDateTime(connection.last_success_at)
                : t('integrations.never')
            }
          />
          <Row
            label={t('integrations.lastError')}
            value={
              connection?.last_error_code
                ? `${connection.last_error_code} — ${connection.last_error_summary ?? ''}`
                : t('integrations.none')
            }
          />
        </dl>

        <p className="settings-note" style={{ marginTop: 'var(--space-4)' }}>
          {t('integrations.noProviderRequest')}
        </p>
      </Card>

      <Card title={t('integrations.queue')}>
        <dl className="settings-detail-list">
          <Row label={t('integrations.jobsPending')} value={health.jobs_pending} />
          <Row label={t('integrations.jobsRunning')} value={health.jobs_running} />
          <Row label={t('integrations.jobsFailed')} value={health.jobs_failed} />
          <Row label={t('integrations.jobsTerminal')} value={health.jobs_failed_terminal} />
          <Row
            label={t('integrations.oldestPending')}
            value={formatAge(health.oldest_pending_job_age_seconds, t)}
          />
        </dl>
      </Card>

      <Card title={t('integrations.inbox')}>
        <dl className="settings-detail-list">
          <Row label={t('integrations.inboxPending')} value={health.inbox_pending} />
          <Row
            label={t('integrations.inboxAwaitingVerification')}
            value={health.inbox_awaiting_verification}
          />
          <Row label={t('integrations.inboxRejected')} value={health.inbox_rejected} />
          <Row
            label={t('integrations.inboxFailedTerminal')}
            value={health.inbox_failed_terminal}
          />
          <Row
            label={t('integrations.staleAssignments')}
            // `null`, not zero. There is no freshness rule to measure against, and the
            // description says why rather than leaving a reader to guess.
            value={
              health.stale_assignment_count === null
                ? t('integrations.staleUnknown')
                : health.stale_assignment_count
            }
          />
        </dl>
        {health.stale_assignment_count === null && (
          <p className="settings-note">{health.stale_rule_description}</p>
        )}
      </Card>

      <Card title={t('integrations.worker')}>
        {!health.worker && <Banner tone="neutral">{t('integrations.workerNeverRan')}</Banner>}
        {health.worker && (
          <dl className="settings-detail-list">
            <Row label={t('integrations.workerLastSeen')} value={formatDateTime(health.worker.last_seen_at)} />
            <Row
              label={t('integrations.workerStopped')}
              value={
                health.worker.stopped_at
                  ? formatDateTime(health.worker.stopped_at)
                  : t('integrations.none')
              }
            />
          </dl>
        )}
      </Card>

      <Card title={t('integrations.reviewQueue')} flush>
        {reviewQuery.isLoading && (
          <div style={{ padding: 'var(--space-5)' }}>
            <SkeletonRows rows={3} />
          </div>
        )}
        {reviewQuery.data?.items?.length === 0 && (
          <EmptyState title={t('integrations.reviewEmpty')} body={t('integrations.retryHint')} />
        )}
        {reviewQuery.data?.items?.length > 0 && (
          <div className="table-wrap">
            <table className="table table--stacked">
              <caption className="visually-hidden">{t('integrations.reviewQueue')}</caption>
              <thead>
                <tr>
                  <th scope="col">{t('integrations.jobType')}</th>
                  <th scope="col">{t('integrations.attempts')}</th>
                  <th scope="col">{t('integrations.errorCode')}</th>
                  <th scope="col">{t('integrations.errorSummary')}</th>
                  <th scope="col" />
                </tr>
              </thead>
              <tbody>
                {reviewQuery.data.items.map((job) => (
                  <tr key={job.id}>
                    <td data-label={t('integrations.jobType')} className="mono">
                      {job.job_type}
                    </td>
                    <td data-label={t('integrations.attempts')}>
                      {job.attempt_count} / {job.max_attempts}
                    </td>
                    <td data-label={t('integrations.errorCode')}>
                      <StatusBadge tone="danger" value={job.error_code} label={job.error_code} />
                    </td>
                    <td data-label={t('integrations.errorSummary')}>{job.error_summary}</td>
                    <td>
                      {can(P.INTEGRATION_MANAGE) && (
                        <Button
                          variant="secondary"
                          compact
                          onClick={() => retryMutation.mutate(job.id)}
                          disabled={retryMutation.isPending}
                        >
                          {t('integrations.retry')}
                        </Button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {retryMutation.error && <ErrorState error={retryMutation.error} />}
      </Card>
    </>
  );
}

export default IntegrationPanel;
