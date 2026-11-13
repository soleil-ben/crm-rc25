/**
 * Customer list (Design.md section 7).
 *
 * Filters live in the URL so a filtered view is shareable and survives a reload.
 * Active filters render as removable chips, and the empty state explains which filters
 * are applied.
 */

import { useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { customersApi, opsApi } from '../../api/endpoints.js';
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
  StatusBadge,
  TextInput,
} from '../../components/ui/index.jsx';
import { EmptyState, ErrorState, SkeletonRows } from '../../components/state/index.jsx';
import { formatDate, relativeDays } from '../../utils/format.js';
import { CustomerFormDrawer } from './CustomerFormDrawer.jsx';
import './customers.css';

const PAGE_SIZE = 25;

const LIFECYCLE_VALUES = ['prospect', 'new', 'active', 'at_risk', 'inactive', 'archived'];
const LANGUAGE_VALUES = ['en', 'vi', 'fr', 'other', 'unknown'];
const ROUTE_VALUES = ['VCA', 'CAV', 'CAD', 'XUS'];

/**
 * `?search=` is what the search box writes; `?q=` is what the global search and a person
 * typing a URL by hand use, and the UAT run used it and got an unfiltered list (fix pack
 * item 4). Both are read; the API accepts both too.
 */
function searchTerm(params) {
  return params.get('search') || params.get('q') || '';
}

export function CustomerListPage({ initialDrawerOpen = false, onDrawerClose }) {
  const t = useT();
  const { can } = useSession();
  const [params, setParams] = useSearchParams();
  const [drawerOpen, setDrawerOpen] = useState(initialDrawerOpen);
  const [showMoreFilters, setShowMoreFilters] = useState(false);

  const offset = Number(params.get('offset') || 0);

  const query = useMemo(() => {
    const value = {
      limit: PAGE_SIZE,
      offset,
      search: searchTerm(params) || undefined,
      lifecycle_status: params.getAll('lifecycle_status'),
      preferred_language: params.getAll('preferred_language'),
      primary_route: params.getAll('primary_route'),
      observed_route: params.get('observed_route') || undefined,
      category: params.getAll('category'),
      tag_id: params.getAll('tag_id'),
      owner_user_id: params.get('owner_user_id') || undefined,
      has_overdue_task: params.get('has_overdue_task') || undefined,
      has_service_issue: params.get('has_service_issue') || undefined,
      created_from: params.get('created_from') || undefined,
      created_to: params.get('created_to') || undefined,
      include_archived: params.get('include_archived') === 'true' ? 'true' : undefined,
      last_shipment_before_days: params.get('last_shipment_before_days') || undefined,
    };
    return value;
  }, [params, offset]);

  const { data, isLoading, isFetching, error, refetch } = useQuery({
    queryKey: ['customers', query],
    queryFn: () => customersApi.list(query),
    placeholderData: (previous) => previous,
  });

  const staffQuery = useQuery({ queryKey: ['staff-assignable'], queryFn: opsApi.assignableStaff });
  // Tags for the More filters picker and for naming a tag chip (UAT-OP-17). Every role
  // holds `tag:read`; a role that somehow did not would see no tag filter, not an error.
  const tagsQuery = useQuery({ queryKey: ['tags'], queryFn: opsApi.tags, enabled: can(P.TAG_READ) });
  const tagName = (id) =>
    (tagsQuery.data ?? []).find((tag) => String(tag.id) === String(id))?.name ?? id;

  function setParam(key, value) {
    const next = new URLSearchParams(params);
    next.delete('offset');
    // Typing in the box takes over from a `?q=` somebody arrived with.
    if (key === 'search') next.delete('q');
    if (value === undefined || value === null || value === '' || value === false) {
      next.delete(key);
    } else {
      next.set(key, String(value));
    }
    setParams(next, { replace: true });
  }

  function toggleMulti(key, value) {
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
    if (key === 'offset' || key === 'search' || key === 'q') return;
    let label = `${key.replace(/_/g, ' ')}: ${value}`;
    if (key === 'lifecycle_status') label = t(`lifecycle.${value}`, value);
    if (key === 'preferred_language') label = t(`languages.${value}`, value);
    if (key === 'primary_route' || key === 'observed_route') label = t(`routes.${value}`, value);
    if (key === 'has_overdue_task') label = t('customers.overdueFilter');
    if (key === 'has_service_issue') label = t('customers.issueFilter');
    if (key === 'include_archived') label = t('customers.includeArchived');
    if (key === 'tag_id') label = `${t('customers.tagFilter')}: ${tagName(value)}`;
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
  const hasFilters = activeChips.length > 0 || Boolean(searchTerm(params));

  function closeDrawer() {
    setDrawerOpen(false);
    onDrawerClose?.();
  }

  return (
    <>
      <PageHeader
        title={t('customers.title')}
        subtitle={data ? `${data.total} ${t('common.results')}` : undefined}
        actions={
          <>
            {can(P.IMPORT_PREVIEW) && (
              <Link to="/customers/import" className="btn btn--secondary">
                {t('customers.import')}
              </Link>
            )}
            {can(P.EXPORT_CUSTOMERS) && (
              <Button
                onClick={() => {
                  // The export carries the *same* filters the list is showing, so the
                  // file matches what is on screen rather than quietly being everybody.
                  const { limit, offset: _offset, ...filters } = query;
                  void limit;
                  window.location.href = downloadUrl('/exports/customers.csv', filters);
                }}
              >
                {t('customers.export')}
              </Button>
            )}
            {can(P.CUSTOMER_CREATE) && (
              <Button variant="primary" onClick={() => setDrawerOpen(true)}>
                {t('customers.add')}
              </Button>
            )}
          </>
        }
      />

      <Card flush>
        <div className="filter-bar">
          <div className="filter-bar__row">
            <label className="visually-hidden" htmlFor="customer-search">
              {t('customers.searchPlaceholder')}
            </label>
            <TextInput
              id="customer-search"
              type="search"
              placeholder={t('customers.searchPlaceholder')}
              defaultValue={searchTerm(params)}
              onChange={(event) => setParam('search', event.target.value)}
              style={{ maxWidth: 340 }}
            />

            <Select
              aria-label={t('customers.lifecycleFilter')}
              value=""
              onChange={(event) => toggleMulti('lifecycle_status', event.target.value)}
              placeholder={t('customers.lifecycleFilter')}
              options={LIFECYCLE_VALUES.map((value) => ({ value, label: t(`lifecycle.${value}`) }))}
              style={{ maxWidth: 200 }}
            />

            <Select
              aria-label={t('customers.routeFilter')}
              value=""
              onChange={(event) => toggleMulti('primary_route', event.target.value)}
              placeholder={t('customers.routeFilter')}
              options={ROUTE_VALUES.map((value) => ({ value, label: t(`routes.${value}`) }))}
              style={{ maxWidth: 200 }}
            />

            <Select
              aria-label={t('customers.languageFilter')}
              value=""
              onChange={(event) => toggleMulti('preferred_language', event.target.value)}
              placeholder={t('customers.languageFilter')}
              options={LANGUAGE_VALUES.map((value) => ({ value, label: t(`languages.${value}`) }))}
              style={{ maxWidth: 200 }}
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
                aria-label={t('customers.ownerFilter')}
                value={params.get('owner_user_id') || ''}
                onChange={(event) => setParam('owner_user_id', event.target.value)}
                placeholder={t('customers.ownerFilter')}
                options={(staffQuery.data ?? []).map((member) => ({
                  value: member.id,
                  label: member.full_name,
                }))}
                style={{ maxWidth: 220 }}
              />
              {can(P.TAG_READ) && (
                <Select
                  aria-label={t('customers.tagFilter')}
                  value=""
                  onChange={(event) => toggleMulti('tag_id', event.target.value)}
                  placeholder={t('customers.tagFilter')}
                  options={(tagsQuery.data ?? []).map((tag) => ({
                    value: String(tag.id),
                    label: tag.name,
                  }))}
                  style={{ maxWidth: 220 }}
                />
              )}
              <Checkbox
                label={t('customers.overdueFilter')}
                checked={params.get('has_overdue_task') === 'true'}
                onChange={(event) => setParam('has_overdue_task', event.target.checked ? 'true' : '')}
              />
              <Checkbox
                label={t('customers.issueFilter')}
                checked={params.get('has_service_issue') === 'true'}
                onChange={(event) => setParam('has_service_issue', event.target.checked ? 'true' : '')}
              />
              <Checkbox
                label={t('customers.includeArchived')}
                checked={params.get('include_archived') === 'true'}
                onChange={(event) => setParam('include_archived', event.target.checked ? 'true' : '')}
              />
            </div>
          )}

          {activeChips.length > 0 && (
            <div className="filter-bar__chips" aria-label={t('customers.activeFilters')}>
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
            title={hasFilters ? t('customers.emptyTitle') : t('customers.emptyNoRecords')}
            body={hasFilters ? t('customers.emptyBody') : t('customers.emptyNoRecordsBody')}
            action={
              hasFilters ? (
                <Button onClick={() => setParams(new URLSearchParams())}>
                  {t('common.clearFilters')}
                </Button>
              ) : can(P.CUSTOMER_CREATE) ? (
                <Button variant="primary" onClick={() => setDrawerOpen(true)}>
                  {t('customers.add')}
                </Button>
              ) : null
            }
          />
        )}

        {rows.length > 0 && (
          <>
            <div className="table-wrap" aria-busy={isFetching}>
              <table className="table table--stacked">
                <caption className="visually-hidden">{t('customers.title')}</caption>
                <thead>
                  <tr>
                    <th scope="col">{t('customers.columnId')}</th>
                    <th scope="col">{t('customers.columnName')}</th>
                    <th scope="col">{t('customers.columnContact')}</th>
                    <th scope="col">{t('customers.columnRoute')}</th>
                    <th scope="col">{t('customers.columnLifecycle')}</th>
                    <th scope="col">{t('customers.columnTags')}</th>
                    <th scope="col">{t('customers.columnShipments')}</th>
                    <th scope="col">{t('customers.columnLastShipment')}</th>
                    <th scope="col">{t('customers.columnOwner')}</th>
                    <th scope="col">{t('customers.columnNextFollowUp')}</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((customer) => (
                    <tr key={customer.id}>
                      <td data-label={t('customers.columnId')} className="table__id">
                        {customer.public_id}
                      </td>
                      <td data-label={t('customers.columnName')} className="table__primary">
                        <Link to={`/customers/${customer.id}`}>{customer.full_name}</Link>
                        <div className="row-wrap customer-row__flags">
                          {customer.has_service_issue && (
                            <StatusBadge tone="danger" value="issue" label={t('profile.serviceIssue')} />
                          )}
                          {customer.do_not_contact && (
                            <StatusBadge tone="warning" value="dnc" label={t('customers.doNotContact')} />
                          )}
                        </div>
                      </td>
                      <td data-label={t('customers.columnContact')}>
                        <div>{customer.phone_entered || '—'}</div>
                        <div className="meta">{customer.email_entered || '—'}</div>
                      </td>
                      <td data-label={t('customers.columnRoute')}>
                        <RouteBadge route={customer.primary_route_group} />
                      </td>
                      <td data-label={t('customers.columnLifecycle')}>
                        <StatusBadge kind="lifecycle" value={customer.lifecycle_status} />
                      </td>
                      <td data-label={t('customers.columnTags')}>
                        {customer.tags?.length ? (
                          <div className="row-wrap">
                            {customer.tags.map((tag) => (
                              <span key={tag.id} className="badge badge--teal">
                                {tag.name}
                              </span>
                            ))}
                          </div>
                        ) : (
                          '—'
                        )}
                      </td>
                      <td data-label={t('customers.columnShipments')}>
                        {customer.total_qualifying_shipments}
                      </td>
                      <td data-label={t('customers.columnLastShipment')}>
                        {formatDate(customer.last_shipment_at)}
                        {customer.last_shipment_at && (
                          <div className="meta">{relativeDays(customer.last_shipment_at)}</div>
                        )}
                      </td>
                      <td data-label={t('customers.columnOwner')}>{customer.owner?.full_name || '—'}</td>
                      <td data-label={t('customers.columnNextFollowUp')}>
                        {formatDate(customer.next_follow_up_at)}
                        {customer.has_overdue_task && (
                          <div>
                            <StatusBadge tone="danger" value="overdue" label={t('tasks.overdue')} />
                          </div>
                        )}
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

      <CustomerFormDrawer open={drawerOpen} onClose={closeDrawer} />
    </>
  );
}

/**
 * `/customers/new`: the list with the create drawer already open, for a role that may
 * create, and a plain refusal for one that may not.
 *
 * Before this route existed the path fell through to `customers/:customerId`, the API was
 * asked for customer "new", and a read-only manager saw "Input should be a valid
 * integer" -- a validation message about a number they never typed (fix pack item 11).
 */
export function CustomerNewPage() {
  const t = useT();
  const { can } = useSession();
  const navigate = useNavigate();

  if (!can(P.CUSTOMER_CREATE)) {
    return (
      <>
        <PageHeader title={t('customers.add')} />
        <Card>
          <EmptyState
            title={t('states.permissionTitle')}
            body={t('customers.createRefusedBody')}
            action={
              <Link to="/customers" className="btn btn--secondary">
                {t('customers.backToList')}
              </Link>
            }
          />
        </Card>
      </>
    );
  }

  return (
    <CustomerListPage
      initialDrawerOpen
      onDrawerClose={() => navigate('/customers', { replace: true })}
    />
  );
}
