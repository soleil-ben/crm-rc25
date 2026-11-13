/**
 * Operational dashboard (Design.md section 6, CRM.md section 12).
 *
 * Every figure comes from the API, which computes it from real records. A comparison
 * line renders only when the API supplies one, and each card links to the records
 * behind it.
 */

import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { opsApi } from '../../api/endpoints.js';
import { useT } from '../../i18n/index.jsx';
import { PageHeader } from '../../components/layout/AppShell.jsx';
import {
  Banner,
  Card,
  InfoDot,
  Select,
  StatusBadge,
} from '../../components/ui/index.jsx';
import { EmptyState, ErrorState, SkeletonCards, SkeletonRows } from '../../components/state/index.jsx';
import { formatDateTime, formatNumber, formatPercent, relativeDays } from '../../utils/format.js';
import { RouteMixChart, TrendChart } from './charts.jsx';
import './dashboard.css';

function greetingKey() {
  const hour = new Date().getHours();
  if (hour < 12) return 'dashboard.greetingMorning';
  if (hour < 18) return 'dashboard.greetingAfternoon';
  return 'dashboard.greetingEvening';
}

function KpiCard({ card, t }) {
  const toneClass =
    card.tone === 'danger' && card.value > 0
      ? 'kpi__value kpi__value--danger'
      : card.tone === 'warning' && card.value > 0
        ? 'kpi__value kpi__value--warning'
        : 'kpi__value';

  return (
    <Link to={card.link} className="kpi">
      <span className="kpi__label">
        {card.label}
        <InfoDot text={card.definition} />
      </span>
      <span className={toneClass}>{formatNumber(card.value)}</span>
      <span className="kpi__foot">
        {card.scope === 'current'
          ? t('dashboard.currentStateNote')
          : card.comparison_value !== null && card.comparison_label
            ? `${formatNumber(card.comparison_value)} ${card.comparison_label}`
            : t('dashboard.noComparison')}
      </span>
    </Link>
  );
}

export function DashboardPage() {
  const t = useT();
  const [days, setDays] = useState(30);

  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ['dashboard', days],
    queryFn: () => opsApi.dashboard(days),
  });

  return (
    <>
      <PageHeader
        title={t(greetingKey())}
        subtitle={t('dashboard.subtitle')}
        actions={
          <>
            <label className="visually-hidden" htmlFor="dashboard-range">
              {t('dashboard.periodLabel')}
            </label>
            <Select
              id="dashboard-range"
              value={days}
              onChange={(event) => setDays(Number(event.target.value))}
              options={[
                { value: 7, label: t('dashboard.last7') },
                { value: 30, label: t('dashboard.last30') },
                { value: 90, label: t('dashboard.last90') },
              ]}
              style={{ width: 180 }}
            />
          </>
        }
      />

      {error && <ErrorState error={error} onRetry={refetch} />}

      {isLoading && (
        <>
          <div className="grid-kpi">
            <SkeletonCards count={4} />
          </div>
          <SkeletonRows rows={4} height={200} />
        </>
      )}

      {data && (
        <>
          <div className="grid-kpi">
            {data.kpis.map((card) => (
              <KpiCard key={card.key} card={card} t={t} />
            ))}
          </div>

          {data.queues.length > 0 && (
            <div className="grid-halves">
              {data.queues.map((card) => (
                <KpiCard key={card.key} card={card} t={t} />
              ))}
            </div>
          )}

          {data.data_notes.length > 0 && (
            <Banner tone="neutral">
              <ul className="dashboard__notes">
                {data.data_notes.map((note) => (
                  <li key={note}>{note}</li>
                ))}
              </ul>
            </Banner>
          )}

          <div className="grid-2-1">
            <Card title={t('dashboard.shipmentTrend')}>
              <TrendChart points={data.shipment_trend} />
            </Card>
            <Card title={t('dashboard.shipmentsByRoute')}>
              <RouteMixChart rows={data.route_mix} />
            </Card>
          </div>

          <div className="grid-2-1">
            <Card title={t('dashboard.followUpQueue')} flush>
              {data.follow_up_queue.length === 0 ? (
                <EmptyState
                  title="No follow-ups scheduled"
                  body="Tasks appear here as soon as they are created with a due date."
                />
              ) : (
                <div className="table-wrap">
                  <table className="table table--stacked">
                    <caption className="visually-hidden">{t('dashboard.followUpQueue')}</caption>
                    <thead>
                      <tr>
                        <th scope="col">{t('tasks.subject')}</th>
                        <th scope="col">{t('tasks.customer')}</th>
                        <th scope="col">{t('tasks.status')}</th>
                        <th scope="col">{t('tasks.dueAt')}</th>
                      </tr>
                    </thead>
                    <tbody>
                      {data.follow_up_queue.map((task) => (
                        <tr key={task.id}>
                          <td data-label={t('tasks.subject')} className="table__primary">
                            {/* `?task=<id>` used to be appended here. Nothing on the
                                follow-ups screen reads it, so it promised a focused task
                                and delivered an ordinary list. The list is where the task
                                is; the parameter was the only untrue part. */}
                            <Link to="/follow-ups">{task.subject}</Link>
                          </td>
                          <td data-label={t('tasks.customer')}>
                            <Link to={`/customers/${task.customer_id}`}>{task.customer_name}</Link>
                            <div className="meta mono">{task.customer_public_id}</div>
                          </td>
                          <td data-label={t('tasks.status')}>
                            {task.is_overdue ? (
                              <StatusBadge tone="danger" label={t('tasks.overdue')} value="overdue" />
                            ) : (
                              <StatusBadge kind="task" value={task.status} />
                            )}
                          </td>
                          <td data-label={t('tasks.dueAt')}>
                            {formatDateTime(task.due_at)}
                            <div className="meta">{relativeDays(task.due_at)}</div>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </Card>

            <div className="stack">
              <Card title={t('dashboard.lifecycleMix')}>
                <ul className="dashboard__list">
                  {data.lifecycle_mix.map((row) => (
                    <li key={row.status}>
                      <Link to={row.link} className="dashboard__list-link">
                        <StatusBadge kind="lifecycle" value={row.status} />
                        <span className="spacer" />
                        <strong>{formatNumber(row.count)}</strong>
                      </Link>
                      <p className="meta">{row.definition}</p>
                    </li>
                  ))}
                </ul>
              </Card>

              <Card title={t('dashboard.repeatShare')}>
                {data.repeat_shipper_share ? (
                  <>
                    <p className="kpi__value">
                      {formatPercent(data.repeat_shipper_share.share)}
                    </p>
                    <p className="meta">
                      {formatNumber(data.repeat_shipper_share.repeat_customers)} of{' '}
                      {formatNumber(data.repeat_shipper_share.shipping_customers)} customers who
                      shipped in this period.
                    </p>
                    <p className="meta dashboard__definition">
                      {data.repeat_shipper_share.definition}
                    </p>
                  </>
                ) : (
                  <EmptyState
                    title="No qualifying shipments in this period"
                    body="This share is left blank rather than shown as zero, because there is nothing to divide."
                  />
                )}
              </Card>
            </div>
          </div>

          <Card title={t('dashboard.recentCustomers')} flush>
            {data.recent_customers.length === 0 ? (
              <EmptyState title={t('customers.emptyNoRecords')} body={t('customers.emptyNoRecordsBody')} />
            ) : (
              <div className="table-wrap">
                <table className="table table--stacked">
                  <caption className="visually-hidden">{t('dashboard.recentCustomers')}</caption>
                  <thead>
                    <tr>
                      <th scope="col">{t('customers.columnId')}</th>
                      <th scope="col">{t('customers.columnName')}</th>
                      <th scope="col">{t('customers.columnRoute')}</th>
                      <th scope="col">Added</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.recent_customers.map((customer) => (
                      <tr key={customer.id}>
                        <td data-label={t('customers.columnId')} className="table__id">
                          {customer.public_id}
                        </td>
                        <td data-label={t('customers.columnName')} className="table__primary">
                          <Link to={`/customers/${customer.id}`}>{customer.full_name}</Link>
                          <div className="meta">
                            {[customer.city, customer.country_code].filter(Boolean).join(', ') || '—'}
                          </div>
                        </td>
                        <td data-label={t('customers.columnRoute')}>
                          {customer.primary_route_group
                            ? t(`routes.${customer.primary_route_group}`)
                            : '—'}
                        </td>
                        <td data-label="Added">{formatDateTime(customer.created_at)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Card>
        </>
      )}
    </>
  );
}
