/**
 * Shipment list (Design.md section 9).
 *
 * Filters live in the URL so a filtered view is shareable and survives a reload, exactly
 * as the customer list already behaves. Package progress is shown as text — "1 of 3
 * delivered" — rather than as a bare count.
 */

import { useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Link, useSearchParams } from 'react-router-dom';
import { opsApi, shipmentsApi } from '../../api/endpoints.js';
import { downloadUrl } from '../../api/client.js';
import { useT } from '../../i18n/index.jsx';
import { P, useSession } from '../../app/SessionContext.jsx';
import { PageHeader } from '../../components/layout/AppShell.jsx';
import {
  Button,
  Card,
  Checkbox,
  FilterChip,
  Pagination,
  RouteBadge,
  Select,
  TextInput,
} from '../../components/ui/index.jsx';
import { EmptyState, ErrorState, SkeletonRows } from '../../components/state/index.jsx';
import { formatDate, formatDateTime } from '../../utils/format.js';
import { BookingStateBadge, OperationalBadge, PackageProgress } from './shipmentTokens.jsx';
import './shipments.css';

const PAGE_SIZE = 25;
const ROUTE_VALUES = ['VCA', 'CAV', 'CAD', 'XUS'];
const BOOKING_STATES = ['draft', 'confirmed', 'cancelled'];
const OPERATIONAL_STATES = [
  'booked',
  'awaiting_parcel',
  'received_at_solaris',
  'processing',
  'departed_origin',
  'in_transit',
  'customs_processing',
  'arrived_destination',
  'out_for_delivery',
  'partially_delivered',
  'delivered',
  'delivery_attempted',
  'exception',
  'return_in_progress',
  'returned',
  'cancelled',
  'tracking_unavailable',
];

export function ShipmentListPage() {
  const t = useT();
  const { can } = useSession();
  const [params, setParams] = useSearchParams();
  const [showMoreFilters, setShowMoreFilters] = useState(false);

  const offset = Number(params.get('offset') || 0);

  const query = useMemo(
    () => ({
      limit: PAGE_SIZE,
      offset,
      search: params.get('search') || undefined,
      route_group: params.getAll('route_group'),
      booking_state: params.getAll('booking_state'),
      operational_state: params.getAll('operational_state'),
      owner_user_id: params.get('owner_user_id') || undefined,
      exceptions_only: params.get('exceptions_only') === 'true' ? 'true' : undefined,
      booked_from: params.get('booked_from') || undefined,
      booked_to: params.get('booked_to') || undefined,
    }),
    [params, offset],
  );

  const { data, isLoading, isFetching, error, refetch } = useQuery({
    queryKey: ['shipments', query],
    queryFn: () => shipmentsApi.list(query),
    placeholderData: (previous) => previous,
  });

  const staffQuery = useQuery({ queryKey: ['staff-assignable'], queryFn: opsApi.assignableStaff });

  function setParam(key, value) {
    const next = new URLSearchParams(params);
    next.delete('offset');
    if (value === undefined || value === null || value === '' || value === false) {
      next.delete(key);
    } else {
      next.set(key, String(value));
    }
    setParams(next, { replace: true });
  }

  function toggleMulti(key, value) {
    if (!value) return;
    const next = new URLSearchParams(params);
    next.delete('offset');
    const current = next.getAll(key);
    next.delete(key);
    const updated = current.includes(value)
      ? current.filter((item) => item !== value)
      : [...current, value];
    updated.forEach((item) => next.append(key, item));
    setParams(next, { replace: true });
  }

  const activeChips = [];
  params.forEach((value, key) => {
    if (key === 'offset' || key === 'search') return;
    let label = `${key.replace(/_/g, ' ')}: ${value}`;
    if (key === 'route_group') label = t(`routes.${value}`, value);
    if (key === 'booking_state') label = t(`bookingState.${value}`, value);
    if (key === 'operational_state') label = t(`operationalState.${value}`, value);
    if (key === 'exceptions_only') label = t('shipments.exceptionsOnly');
    if (key === 'owner_user_id') {
      const member = (staffQuery.data ?? []).find((item) => String(item.id) === value);
      label = `${t('shipments.ownerFilter')}: ${member?.full_name ?? value}`;
    }
    activeChips.push({ key, value, label });
  });

  function removeChip(key, value) {
    const next = new URLSearchParams(params);
    const remaining = next.getAll(key).filter((item) => item !== value);
    next.delete(key);
    remaining.forEach((item) => next.append(key, item));
    next.delete('offset');
    setParams(next, { replace: true });
  }

  const rows = data?.items ?? [];
  const hasFilters = activeChips.length > 0 || Boolean(params.get('search'));

  return (
    <>
      <PageHeader
        title={t('shipments.title')}
        subtitle={data ? `${data.total} ${t('common.results')}` : t('shipments.subtitle')}
        actions={
          <>
            {can(P.EXPORT_SHIPMENTS) && (
              <Button
                onClick={() => {
                  // Same filters as the list on screen, so the file matches what the
                  // operator is looking at rather than quietly being everything.
                  const { limit, offset: _offset, sort, direction, ...filters } = query;
                  void limit;
                  void sort;
                  void direction;
                  window.location.href = downloadUrl('/exports/shipments.csv', filters);
                }}
              >
                {t('shipments.exportShipments')}
              </Button>
            )}
            {can(P.EXPORT_SHIPMENTS) && (
              <Button
                onClick={() => {
                  const { limit, offset: _offset, sort, direction, ...filters } = query;
                  void limit;
                  void sort;
                  void direction;
                  window.location.href = downloadUrl('/exports/packages.csv', filters);
                }}
              >
                {t('shipments.exportPackages')}
              </Button>
            )}
            {can(P.SHIPMENT_WRITE) && (
              <Link to="/shipments/new" className="btn btn--primary">
                {t('shipments.createBooking')}
              </Link>
            )}
          </>
        }
      />

      <Card flush>
        <div className="filter-bar">
          <div className="filter-bar__row">
            <label className="visually-hidden" htmlFor="shipment-search">
              {t('shipments.searchPlaceholder')}
            </label>
            <TextInput
              id="shipment-search"
              type="search"
              placeholder={t('shipments.searchPlaceholder')}
              defaultValue={params.get('search') || ''}
              onChange={(event) => setParam('search', event.target.value)}
              style={{ maxWidth: 360 }}
            />

            <Select
              aria-label={t('shipments.routeFilter')}
              value=""
              onChange={(event) => toggleMulti('route_group', event.target.value)}
              placeholder={t('shipments.routeFilter')}
              options={ROUTE_VALUES.map((value) => ({ value, label: t(`routes.${value}`) }))}
              style={{ maxWidth: 200 }}
            />

            <Select
              aria-label={t('shipments.statusFilter')}
              value=""
              onChange={(event) => toggleMulti('operational_state', event.target.value)}
              placeholder={t('shipments.statusFilter')}
              options={OPERATIONAL_STATES.map((value) => ({
                value,
                label: t(`operationalState.${value}`),
              }))}
              style={{ maxWidth: 220 }}
            />

            <Checkbox
              label={t('shipments.exceptionsOnly')}
              checked={params.get('exceptions_only') === 'true'}
              onChange={(event) => setParam('exceptions_only', event.target.checked ? 'true' : '')}
            />

            <Button
              variant="tertiary"
              onClick={() => setShowMoreFilters((open) => !open)}
              aria-expanded={showMoreFilters}
            >
              {t('customers.moreFilters')}
            </Button>
          </div>

          {showMoreFilters && (
            <div className="filter-bar__row filter-bar__row--more">
              <Select
                aria-label={t('shipments.bookingStateFilter')}
                value=""
                onChange={(event) => toggleMulti('booking_state', event.target.value)}
                placeholder={t('shipments.bookingStateFilter')}
                options={BOOKING_STATES.map((value) => ({
                  value,
                  label: t(`bookingState.${value}`),
                }))}
                style={{ maxWidth: 200 }}
              />
              <Select
                aria-label={t('shipments.ownerFilter')}
                value={params.get('owner_user_id') || ''}
                onChange={(event) => setParam('owner_user_id', event.target.value)}
                placeholder={t('shipments.ownerFilter')}
                options={(staffQuery.data ?? []).map((member) => ({
                  value: member.id,
                  label: member.full_name,
                }))}
                style={{ maxWidth: 220 }}
              />
              <label className="field field--inline">
                <span className="field__label">{t('shipments.bookedFrom')}</span>
                <TextInput
                  type="date"
                  value={params.get('booked_from') || ''}
                  onChange={(event) => setParam('booked_from', event.target.value)}
                />
              </label>
              <label className="field field--inline">
                <span className="field__label">{t('shipments.bookedTo')}</span>
                <TextInput
                  type="date"
                  value={params.get('booked_to') || ''}
                  onChange={(event) => setParam('booked_to', event.target.value)}
                />
              </label>
            </div>
          )}

          {activeChips.length > 0 && (
            <div className="filter-bar__chips" aria-label={t('shipments.activeFilters')}>
              {activeChips.map((chip) => (
                <FilterChip
                  key={`${chip.key}-${chip.value}`}
                  label={chip.label}
                  onRemove={() => removeChip(chip.key, chip.value)}
                />
              ))}
              <Button variant="tertiary" compact onClick={() => setParams(new URLSearchParams())}>
                {t('common.clearFilters')}
              </Button>
            </div>
          )}
        </div>

        {error && <ErrorState error={error} onRetry={refetch} />}

        {isLoading && (
          <div style={{ padding: 'var(--space-5)' }}>
            <SkeletonRows rows={6} />
          </div>
        )}

        {data && rows.length === 0 && (
          <EmptyState
            title={hasFilters ? t('shipments.emptyTitle') : t('shipments.emptyNoRecords')}
            body={hasFilters ? t('shipments.emptyBody') : t('shipments.emptyNoRecordsBody')}
            action={
              hasFilters ? (
                <Button onClick={() => setParams(new URLSearchParams())}>
                  {t('common.clearFilters')}
                </Button>
              ) : can(P.SHIPMENT_WRITE) ? (
                <Link to="/shipments/new" className="btn btn--primary">
                  {t('shipments.createBooking')}
                </Link>
              ) : null
            }
          />
        )}

        {rows.length > 0 && (
          <>
            <div className="table-wrap" aria-busy={isFetching}>
              <table className="table table--stacked shipments-table">
                <caption className="visually-hidden">{t('shipments.title')}</caption>
                <thead>
                  <tr>
                    <th scope="col">{t('shipments.columnId')}</th>
                    <th scope="col">{t('shipments.columnCustomer')}</th>
                    <th scope="col">{t('shipments.columnRoute')}</th>
                    <th scope="col">{t('shipments.columnPackages')}</th>
                    <th scope="col">{t('shipments.columnStatus')}</th>
                    <th scope="col">{t('shipments.columnCarrier')}</th>
                    <th scope="col">{t('shipments.columnUpdate')}</th>
                    <th scope="col">{t('shipments.columnOwner')}</th>
                    <th scope="col">{t('shipments.columnBooked')}</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((shipment) => (
                    <tr key={shipment.id}>
                      <td data-label={t('shipments.columnId')} className="table__id">
                        <Link to={`/shipments/${shipment.id}`} className="mono">
                          {shipment.public_id || t('shipments.draftNoId')}
                        </Link>
                        <div className="row-wrap shipment-row__flags">
                          <BookingStateBadge value={shipment.booking_state} />
                          {shipment.is_demo_record && (
                            <span className="chip chip--demo">{t('shipments.demoRecord')}</span>
                          )}
                        </div>
                      </td>
                      <td data-label={t('shipments.columnCustomer')} className="table__primary">
                        {shipment.customer ? (
                          <Link to={`/customers/${shipment.customer.id}`}>
                            {shipment.customer.full_name}
                          </Link>
                        ) : (
                          '—'
                        )}
                        <div className="meta">{shipment.recipient_name || '—'}</div>
                      </td>
                      <td data-label={t('shipments.columnRoute')}>
                        <RouteBadge route={shipment.route_group} />
                        {/* Only shown when it adds something: for three of the four
                            route groups the badge already states the direction. */}
                        {shipment.direction_label &&
                          shipment.direction_label !== shipment.route_label && (
                            <div className="meta">{shipment.direction_label}</div>
                          )}
                      </td>
                      <td data-label={t('shipments.columnPackages')}>
                        <PackageProgress progress={shipment.package_progress} />
                      </td>
                      <td data-label={t('shipments.columnStatus')}>
                        <OperationalBadge value={shipment.operational_state} />
                      </td>
                      <td data-label={t('shipments.columnCarrier')}>
                        {shipment.carrier_summary || (
                          <span className="meta">{t('shipments.noCarrier')}</span>
                        )}
                      </td>
                      <td data-label={t('shipments.columnUpdate')}>
                        {shipment.latest_update || (
                          <span className="meta">{t('shipments.noUpdate')}</span>
                        )}
                        {shipment.latest_update_at && (
                          <div className="meta">
                            {formatDateTime(shipment.latest_update_at, { showZone: false })}
                          </div>
                        )}
                      </td>
                      <td data-label={t('shipments.columnOwner')}>
                        {shipment.owner?.full_name || '—'}
                      </td>
                      <td data-label={t('shipments.columnBooked')}>
                        {formatDate(shipment.booking_date)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <Pagination
              total={data.total}
              limit={PAGE_SIZE}
              offset={offset}
              onChange={(next) => setParam('offset', next)}
            />
          </>
        )}
      </Card>
    </>
  );
}
