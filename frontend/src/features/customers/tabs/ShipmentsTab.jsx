/**
 * Shipments tab.
 *
 * The derived activity that segments and the dashboard already depend on, plus the
 * permission-gated financial summary with its coverage warning (CRM.md section 12). A
 * customer with nothing recorded gets a plain empty state rather than a row of zeros.
 */

import { useQuery } from '@tanstack/react-query';
import { customersApi } from '../../../api/endpoints.js';
import { useT } from '../../../i18n/index.jsx';
import { P, useSession } from '../../../app/SessionContext.jsx';
import { Banner, Card, InfoDot, RouteBadge } from '../../../components/ui/index.jsx';
import { EmptyState, ErrorState, SkeletonRows } from '../../../components/state/index.jsx';
import { formatDate, formatMoney, formatNumber, formatPercent } from '../../../utils/format.js';

export function ShipmentsTab({ customer }) {
  const t = useT();
  const { can } = useSession();
  const activity = customer.activity;

  const financialsQuery = useQuery({
    queryKey: ['financials', customer.id],
    queryFn: () => customersApi.financials(customer.id),
    enabled: can(P.FINANCIAL_READ),
    retry: false,
  });

  return (
    <div className="stack">
      {activity.total_bookings === 0 && activity.total_qualifying_shipments === 0 ? (
        <EmptyState
          title="No bookings or shipments yet"
          body="Bookings and shipments recorded for this customer will appear here."
        />
      ) : (
        <p className="meta">{t('profile.shipmentsSourceNote')}</p>
      )}

      <Card title={t('profile.activityMetrics')}>
        <div className="metric-grid">
          <div className="metric">
            <span className="metric__label">
              {t('profile.qualifyingShipments')}
              <InfoDot text={t('profile.qualifyingHint')} />
            </span>
            <span className="metric__value">
              {formatNumber(activity.total_qualifying_shipments)}
            </span>
          </div>
          <div className="metric">
            <span className="metric__label">
              {t('profile.bookings')}
              <InfoDot text="All non-draft bookings, including cancelled ones. Shown separately from qualifying shipments so demand is distinguishable from actual shipping." />
            </span>
            <span className="metric__value">{formatNumber(activity.total_bookings)}</span>
          </div>
          <div className="metric">
            <span className="metric__label">{t('profile.delivered')}</span>
            <span className="metric__value">{formatNumber(activity.delivered_shipments)}</span>
          </div>
          <div className="metric">
            <span className="metric__label">{t('profile.firstShipment')}</span>
            <span className="metric__value">{formatDate(activity.first_shipment_at)}</span>
          </div>
          <div className="metric">
            <span className="metric__label">{t('profile.lastShipment')}</span>
            <span className="metric__value">{formatDate(activity.last_shipment_at)}</span>
          </div>
        </div>
      </Card>

      <Card title="Route mix (observed)">
        {Object.keys(activity.route_counts).length === 0 ? (
          <EmptyState
            title="No qualifying shipments yet"
            body="Route mix is derived from actual shipment history, not from the declared route."
          />
        ) : (
          <ul className="route-count-list">
            {Object.entries(activity.route_counts).map(([route, count]) => (
              <li key={route}>
                <RouteBadge route={route} />
                <span className="spacer" />
                <strong>{formatNumber(count)}</strong>
              </li>
            ))}
          </ul>
        )}
      </Card>

      {can(P.FINANCIAL_READ) && (
        <Card title="Recorded financials">
          {financialsQuery.isLoading && <SkeletonRows rows={2} height={48} />}
          {financialsQuery.error && <ErrorState error={financialsQuery.error} />}
          {financialsQuery.data && (
            <>
              <Banner tone="neutral">{financialsQuery.data.note}</Banner>
              {financialsQuery.data.by_currency.length === 0 ? (
                <EmptyState
                  title="No financial amounts recorded"
                  body="Amounts are entered manually. Nothing is assumed to be zero."
                />
              ) : (
                <div className="table-wrap">
                  <table className="table">
                    <caption className="visually-hidden">Recorded amounts by currency</caption>
                    <thead>
                      <tr>
                        <th scope="col">Currency</th>
                        <th scope="col">Recorded revenue</th>
                        <th scope="col">Recorded cost</th>
                        <th scope="col">Gross profit</th>
                      </tr>
                    </thead>
                    <tbody>
                      {financialsQuery.data.by_currency.map((row) => (
                        <tr key={row.currency}>
                          <th scope="row">{row.currency}</th>
                          <td>
                            {formatMoney(row.recorded_revenue, row.currency)}
                            <div className="meta">
                              {row.shipments_with_revenue} shipment(s) recorded
                            </div>
                          </td>
                          <td>
                            {row.recorded_cost === null
                              ? 'Hidden for your role'
                              : formatMoney(row.recorded_cost, row.currency)}
                          </td>
                          <td>
                            {row.gross_profit === null
                              ? 'Unknown'
                              : formatMoney(row.gross_profit, row.currency)}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
              <p className="meta">
                Coverage: {financialsQuery.data.shipments_with_any_financial_record} of{' '}
                {financialsQuery.data.qualifying_shipments} qualifying shipments have a
                recorded amount
                {financialsQuery.data.coverage_share !== null
                  ? ` (${formatPercent(financialsQuery.data.coverage_share)})`
                  : ''}
                .
              </p>
            </>
          )}
        </Card>
      )}
    </div>
  );
}
