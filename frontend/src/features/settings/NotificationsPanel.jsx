/**
 * Settings → Customer notifications (Phase 13F, OD-72).
 *
 * The milestone email outbox: what was queued for whom, and what happened -- sent through the
 * test transport, recorded by the null transport, or skipped (opted out, suppressed, no
 * address) -- with a retry for a failed one. **Test capture only**: there is no production
 * email transport, so nothing here reaches a customer. The outbox holds no address and no
 * message body.
 */

import { useState } from 'react';
import { Link } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { notificationsApi } from '../../api/endpoints.js';
import { P, useSession } from '../../app/SessionContext.jsx';
import { useT } from '../../i18n/index.jsx';
import { Banner, Button, Card, Field, Pagination, Select, StatusBadge } from '../../components/ui/index.jsx';
import { EmptyState, ErrorState, SkeletonRows } from '../../components/state/index.jsx';
import { formatDateTime } from '../../utils/format.js';

const PAGE_SIZE = 50;
const TONE = { queued: 'info', sending: 'info', sent: 'success', recorded: 'neutral', skipped: 'warning', failed: 'danger' };

export function NotificationsPanel() {
  const t = useT();
  const { can } = useSession();
  const queryClient = useQueryClient();
  const [status, setStatus] = useState('');
  const [offset, setOffset] = useState(0);
  const query = useQuery({
    queryKey: ['notifications', status, offset],
    queryFn: () => notificationsApi.list({ status: status || undefined, limit: PAGE_SIZE, offset }),
  });
  const retry = useMutation({
    mutationFn: (id) => notificationsApi.retry(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['notifications'] }),
  });
  const rows = query.data?.items ?? [];

  return (
    <Card title={t('notifications.title')}>
      <Banner tone="info">{t('notifications.testOnly')}</Banner>
      <div className="fin-toolbar">
        <Field label={t('notifications.status')}>
          {(props) => (
            <Select
              {...props}
              value={status}
              placeholder={t('notifications.allStatuses')}
              onChange={(event) => {
                setStatus(event.target.value);
                setOffset(0);
              }}
              options={['queued', 'sending', 'sent', 'recorded', 'skipped', 'failed'].map((value) => ({
                value,
                label: t(`notifications.state.${value}`),
              }))}
            />
          )}
        </Field>
      </div>
      {retry.error && <Banner tone="danger">{retry.error.message}</Banner>}
      {query.isLoading ? (
        <SkeletonRows rows={4} />
      ) : query.error ? (
        <ErrorState error={query.error} onRetry={query.refetch} />
      ) : rows.length === 0 ? (
        <EmptyState title={t('notifications.emptyTitle')} body={t('notifications.emptyBody')} />
      ) : (
        <div className="table-wrap" tabIndex={0} role="region" aria-label={t('notifications.title')}>
          <table className="table">
            <thead>
              <tr>
                <th scope="col">{t('notifications.when')}</th>
                <th scope="col">{t('notifications.shipment')}</th>
                <th scope="col">{t('notifications.customer')}</th>
                <th scope="col">{t('notifications.milestone')}</th>
                <th scope="col">{t('notifications.language')}</th>
                <th scope="col">{t('notifications.status')}</th>
                <th scope="col">
                  <span className="visually-hidden">{t('notifications.actions')}</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.id}>
                  <td>{formatDateTime(row.created_at)}</td>
                  <td>
                    <Link className="mono" to={`/shipments/${row.shipment_id}`}>
                      {row.shipment_reference}
                    </Link>
                  </td>
                  <td>{row.customer_name || '—'}</td>
                  <td>{t(`notifications.milestones.${row.milestone}`, row.milestone)}</td>
                  <td>{row.language.toUpperCase()}</td>
                  <td>
                    <StatusBadge tone={TONE[row.status]} label={t(`notifications.state.${row.status}`, row.status)} />
                    {row.skip_reason && (
                      <span className="meta"> · {t(`notifications.reason.${row.skip_reason}`, row.skip_reason)}</span>
                    )}
                  </td>
                  <td>
                    {row.status === 'failed' && can(P.TRACKING_WRITE) && (
                      <Button
                        compact
                        loading={retry.isPending && retry.variables === row.id}
                        onClick={() => retry.mutate(row.id)}
                        aria-label={`${t('notifications.retry')} ${row.shipment_reference} ${t(`notifications.milestones.${row.milestone}`, row.milestone)}`}
                      >
                        {t('notifications.retry')}
                      </Button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <Pagination total={query.data?.total ?? 0} limit={PAGE_SIZE} offset={offset} onChange={setOffset} />
    </Card>
  );
}
