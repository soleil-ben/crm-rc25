/**
 * Customer profile (Design.md section 7).
 *
 * Summary card plus peer tabs for one record. The selected tab lives in the URL. The
 * Overview uses the specified 7/5 desktop grid and stacks below 1280px.
 */

import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Link, useParams, useSearchParams } from 'react-router-dom';
import { customersApi } from '../../api/endpoints.js';
import { useT } from '../../i18n/index.jsx';
import { P, useSession } from '../../app/SessionContext.jsx';
import { PageHeader } from '../../components/layout/AppShell.jsx';
import {
  Avatar,
  Banner,
  Button,
  Card,
  CopyableId,
  InfoDot,
  Modal,
  RouteBadge,
  StatusBadge,
  TabPanel,
  Tabs,
  TextInput,
} from '../../components/ui/index.jsx';
import { ErrorState, SkeletonRows } from '../../components/state/index.jsx';
import { formatDate, formatDateTime, relativeDays } from '../../utils/format.js';
import { CustomerFormDrawer } from './CustomerFormDrawer.jsx';
import { AddressBookTab } from './tabs/AddressBookTab.jsx';
import { ConsentTab } from './tabs/ConsentTab.jsx';
import { DuplicatesTab } from './tabs/DuplicatesTab.jsx';
import { InteractionsTab } from './tabs/InteractionsTab.jsx';
import { ReferralsTab } from './tabs/ReferralsTab.jsx';
import { ShipmentsTab } from './tabs/ShipmentsTab.jsx';
import { CustomerTasksTab } from './tabs/CustomerTasksTab.jsx';
import { NotificationChoicesCard } from './NotificationChoicesCard.jsx';
import './customers.css';

function DetailRow({ label, value, hint }) {
  return (
    <div className="detail-row">
      <dt>
        {label}
        {hint && <InfoDot text={hint} />}
      </dt>
      <dd>{value ?? '—'}</dd>
    </div>
  );
}

export function CustomerProfilePage() {
  const { customerId } = useParams();
  const t = useT();
  const { can } = useSession();
  const queryClient = useQueryClient();
  const [params, setParams] = useSearchParams();
  const [editOpen, setEditOpen] = useState(false);
  const [archiveOpen, setArchiveOpen] = useState(false);
  const [archiveReason, setArchiveReason] = useState('');

  const activeTab = params.get('tab') || 'overview';

  const { data: customer, isLoading, error, refetch } = useQuery({
    queryKey: ['customer', customerId],
    queryFn: () => customersApi.get(customerId),
  });

  const archiveMutation = useMutation({
    mutationFn: () =>
      customer.is_archived
        ? customersApi.restore(customer.id)
        : customersApi.archive(customer.id, archiveReason || null),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['customer', customerId] });
      queryClient.invalidateQueries({ queryKey: ['customers'] });
      setArchiveOpen(false);
      setArchiveReason('');
    },
  });

  if (isLoading) return <SkeletonRows rows={6} height={90} />;
  if (error) return <ErrorState error={error} onRetry={refetch} />;
  if (!customer) return null;

  const activity = customer.activity;

  const tabs = [
    { id: 'overview', label: t('profile.overview') },
    { id: 'shipments', label: t('profile.shipments'), count: activity.total_bookings },
    { id: 'follow-ups', label: t('profile.followUps'), count: activity.open_task_count },
    { id: 'interactions', label: t('profile.interactions') },
    { id: 'addresses', label: t('profile.addresses') },
    ...(can(P.CONSENT_READ) ? [{ id: 'consent', label: t('profile.consent') }] : []),
    ...(can(P.REFERRAL_READ)
      ? [{ id: 'referrals', label: t('profile.referrals'), count: activity.referral_count }]
      : []),
    // The compare-and-merge screen behind the "Possible duplicate" badge (fix pack item 9).
    // Shown to every role that may review duplicates; merging inside it is Admin-only.
    ...(can(P.DUPLICATE_REVIEW) && !customer.merged_into_customer_id
      ? [{ id: 'duplicates', label: t('profile.duplicates') }]
      : []),
  ];

  function setTab(id) {
    const next = new URLSearchParams(params);
    next.set('tab', id);
    setParams(next, { replace: true });
  }

  return (
    <>
      <PageHeader
        breadcrumb={
          <>
            <Link to="/customers">{t('customers.title')}</Link>
            <span aria-hidden="true">/</span>
            <span>{customer.full_name}</span>
          </>
        }
        title={customer.full_name}
        actions={
          <>
            {can(P.CUSTOMER_UPDATE) && !customer.merged_into_customer_id && (
              <Button onClick={() => setEditOpen(true)}>{t('profile.editCustomer')}</Button>
            )}
            {can(P.CUSTOMER_ARCHIVE) && !customer.merged_into_customer_id && (
              <Button
                variant={customer.is_archived ? 'secondary' : 'tertiary'}
                onClick={() => setArchiveOpen(true)}
              >
                {customer.is_archived ? t('customers.restore') : t('customers.archive')}
              </Button>
            )}
          </>
        }
      />

      {customer.merged_into_customer_id && (
        <Banner tone="neutral" title={t('states.notFoundTitle')}>
          {t('profile.mergedInto')}{' '}
          <Link to={`/customers/${customer.merged_into_customer_id}`}>
            {t('common.viewAll')}
          </Link>
        </Banner>
      )}

      {customer.is_demo_record && (
        <Banner tone="warning" title={t('common.demoData')}>
          This is a synthetic demo record created by the seed command. It is not a real
          customer.
        </Banner>
      )}

      {activity.has_service_issue && (
        <Banner tone="danger" title={t('profile.serviceIssue')}>
          {t('profile.serviceIssueBody')} ({activity.unresolved_issue_count})
        </Banner>
      )}

      <Card>
        <div className="profile-summary">
          <Avatar initials={initialsOf(customer.full_name)} large />
          <div className="profile-summary__main">
            <div className="row-wrap">
              <h2>{customer.full_name}</h2>
              <StatusBadge kind="lifecycle" value={customer.lifecycle_status} />
              {customer.do_not_contact && (
                <StatusBadge tone="warning" value="dnc" label={t('customers.doNotContact')} />
              )}
              {customer.has_duplicate_candidates && (
                <button
                  type="button"
                  className="badge-button"
                  onClick={() => setTab('duplicates')}
                  aria-label={t('customers.duplicateReview')}
                >
                  <StatusBadge tone="warning" value="duplicate" label={t('customers.duplicateFlag')} />
                </button>
              )}
            </div>
            <div className="row-wrap profile-summary__meta">
              <CopyableId value={customer.public_id} />
              <span className="meta">
                Added {formatDate(customer.created_at)}
              </span>
            </div>
            <div className="row-wrap profile-summary__meta">
              <span>{customer.phone_entered || '—'}</span>
              <span aria-hidden="true">·</span>
              <span>{customer.email_entered || '—'}</span>
              <span aria-hidden="true">·</span>
              <span>
                {[customer.city, customer.province_state, customer.country_code]
                  .filter(Boolean)
                  .join(', ') || '—'}
              </span>
            </div>
            <div className="row-wrap">
              <RouteBadge route={customer.primary_route_group} />
              <span className="badge badge--neutral">
                {t(`languages.${customer.preferred_language}`, customer.preferred_language)}
              </span>
              <span className="badge badge--neutral">{customer.category}</span>
              {customer.tags.map((tag) => (
                <span key={tag.id} className="badge badge--teal">
                  {tag.name}
                </span>
              ))}
            </div>
            {customer.former_public_ids.length > 0 && (
              <p className="meta">
                {t('profile.formerIds')}: {customer.former_public_ids.join(', ')}
              </p>
            )}
          </div>
        </div>
      </Card>

      <Tabs tabs={tabs} active={activeTab} onChange={setTab} label={t('customers.title')} />

      <TabPanel id="overview" active={activeTab}>
        <div className="grid-7-5">
          <div className="stack">
            <Card title={t('profile.customerDetails')}>
              <dl className="detail-list">
                <DetailRow label={t('profile.declaredRoute')} value={
                  customer.primary_route_group ? t(`routes.${customer.primary_route_group}`) : null
                } />
                <DetailRow
                  label={t('profile.observedRoute')}
                  hint="Derived from qualifying shipment history, independent of the declared route."
                  value={
                    activity.observed_primary_route_group
                      ? t(`routes.${activity.observed_primary_route_group}`)
                      : null
                  }
                />
                <DetailRow
                  label={t('customers.additionalRoutes')}
                  value={
                    customer.additional_route_interests.length
                      ? customer.additional_route_interests.map((r) => t(`routes.${r}`)).join(', ')
                      : null
                  }
                />
                <DetailRow
                  label={t('customers.shippingPurpose')}
                  value={customer.primary_shipping_purpose.replace(/_/g, ' ')}
                />
                <DetailRow
                  label={t('customers.shippingFrequency')}
                  hint={t('customers.frequencyHint')}
                  value={customer.shipping_frequency.replace(/_/g, ' ')}
                />
                <DetailRow
                  label={t('customers.estimatedMonthly')}
                  value={customer.estimated_monthly_shipments ?? null}
                />
                <DetailRow label={t('customers.contactChannel')} value={customer.preferred_contact_channel} />
                <DetailRow label={t('customers.bestContactTime')} value={customer.best_contact_time} />
                <DetailRow label={t('customers.owner')} value={customer.owner?.full_name} />
                {customer.service_restriction_note && (
                  <DetailRow
                    label={t('customers.restrictionNote')}
                    value={customer.service_restriction_note}
                  />
                )}
              </dl>
              {customer.notes && (
                <>
                  <h3 style={{ marginTop: 'var(--space-4)' }}>{t('customers.notes')}</h3>
                  <p className="profile-notes">{customer.notes}</p>
                </>
              )}
            </Card>

            <Card title={t('profile.activityMetrics')}>
              <div className="metric-grid">
                <Metric
                  label={t('profile.qualifyingShipments')}
                  value={activity.total_qualifying_shipments}
                  hint={t('profile.qualifyingHint')}
                />
                <Metric label={t('profile.bookings')} value={activity.total_bookings} />
                <Metric label={t('profile.delivered')} value={activity.delivered_shipments} />
                <Metric
                  label={t('profile.repeatCustomer')}
                  value={activity.is_repeat_customer ? t('common.yes') : t('common.no')}
                  hint="At least two qualifying shipments."
                />
                <Metric label={t('profile.firstShipment')} value={formatDate(activity.first_shipment_at)} />
                <Metric
                  label={t('profile.lastShipment')}
                  value={formatDate(activity.last_shipment_at)}
                  sub={activity.last_shipment_at ? relativeDays(activity.last_shipment_at) : null}
                />
                <Metric label={t('profile.referralCount')} value={activity.referral_count} />
                <Metric
                  label={t('profile.qualifiedReferrals')}
                  value={activity.qualified_referral_count}
                  hint="Referred customers who completed a qualifying shipment."
                />
              </div>
            </Card>
          </div>

          <div className="stack">
            <Card title={t('profile.nextFollowUp')}>
              {activity.next_follow_up_at ? (
                <>
                  <p className="kpi__value">{formatDateTime(activity.next_follow_up_at)}</p>
                  <p className="meta">
                    {relativeDays(activity.next_follow_up_at)} ·{' '}
                    {activity.open_task_count} {t('profile.openTasks').toLowerCase()}
                  </p>
                  {activity.overdue_task_count > 0 && (
                    <p>
                      <StatusBadge
                        tone="danger"
                        value="overdue"
                        label={`${activity.overdue_task_count} ${t('tasks.overdue').toLowerCase()}`}
                      />
                    </p>
                  )}
                </>
              ) : (
                <p className="meta">No open follow-up is scheduled for this customer.</p>
              )}
              <p className="meta">
                {t('profile.lastFollowUp')}: {formatDateTime(activity.last_follow_up_at)}
              </p>
              {/* Only for a role that can create one: for a read-only role it led to a
                  tab with no create control, a button that did nothing (UAT round 3). */}
              {can(P.TASK_WRITE) && (
                <Button onClick={() => setTab('follow-ups')} compact>
                  {t('profile.addFollowUp')}
                </Button>
              )}
            </Card>

            {/* Phase 14: the customer's milestone email choices (13F), edited by staff. */}
            {can(P.SHIPMENT_READ) && can(P.CUSTOMER_READ) && (
              <NotificationChoicesCard customer={customer} />
            )}

            <Card title={t('profile.activityTimeline')}>
              <InteractionsTab customerId={customer.id} compact />
            </Card>
          </div>
        </div>
      </TabPanel>

      <TabPanel id="shipments" active={activeTab}>
        <ShipmentsTab customer={customer} />
      </TabPanel>

      <TabPanel id="follow-ups" active={activeTab}>
        <CustomerTasksTab customer={customer} />
      </TabPanel>

      <TabPanel id="interactions" active={activeTab}>
        <InteractionsTab customerId={customer.id} />
      </TabPanel>

      <TabPanel id="addresses" active={activeTab}>
        <AddressBookTab customer={customer} />
      </TabPanel>

      <TabPanel id="consent" active={activeTab}>
        <ConsentTab customer={customer} />
      </TabPanel>

      <TabPanel id="referrals" active={activeTab}>
        <ReferralsTab customer={customer} />
      </TabPanel>

      <TabPanel id="duplicates" active={activeTab}>
        <DuplicatesTab customer={customer} />
      </TabPanel>

      <CustomerFormDrawer
        open={editOpen}
        onClose={() => setEditOpen(false)}
        customer={customer}
      />

      <Modal
        open={archiveOpen}
        onClose={() => setArchiveOpen(false)}
        title={customer.is_archived ? t('customers.restore') : t('customers.archiveConfirmTitle')}
        footer={
          <>
            <Button onClick={() => setArchiveOpen(false)}>{t('common.cancel')}</Button>
            <Button
              variant={customer.is_archived ? 'primary' : 'danger'}
              loading={archiveMutation.isPending}
              onClick={() => archiveMutation.mutate()}
            >
              {customer.is_archived ? t('customers.restore') : t('customers.archive')}
            </Button>
          </>
        }
      >
        {!customer.is_archived && (
          <div className="stack">
            <p>{t('customers.archiveConfirmBody')}</p>
            <label className="field__label" htmlFor="archive-reason">
              {t('customers.archiveReason')}
            </label>
            <TextInput
              id="archive-reason"
              value={archiveReason}
              onChange={(event) => setArchiveReason(event.target.value)}
            />
          </div>
        )}
        {customer.is_archived && <p>This customer will appear in the default list again.</p>}
      </Modal>
    </>
  );
}

function Metric({ label, value, hint, sub }) {
  return (
    <div className="metric">
      <span className="metric__label">
        {label}
        {hint && <InfoDot text={hint} />}
      </span>
      <span className="metric__value">{value}</span>
      {sub && <span className="meta">{sub}</span>}
    </div>
  );
}

function initialsOf(name) {
  // Ignore punctuation and parenthetical suffixes such as "(demo)" so initials stay
  // readable for Vietnamese names and seeded records alike.
  const parts = String(name || '')
    .replace(/\([^)]*\)/g, ' ')
    .split(/\s+/)
    .map((part) => part.replace(/[^\p{L}\p{N}]/gu, ''))
    .filter(Boolean);
  if (!parts.length) return '?';
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
}
