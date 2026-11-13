/**
 * The pending Customer Account registration queue (Staff Portal).
 *
 * Phase 10 built the API and left it without a screen; the UAT pack has been saying "open
 * the approval queue" against nothing since then. This is the queue.
 *
 * **What a row carries, and what it does not.** Six fields: the account reference, the
 * state, when it was submitted, when the address was confirmed, the proposal id and how
 * many fields were submitted. No name, no email, no phone, no address — a reviewer
 * chooses a row and opens it, and the list is not a place to read who has applied
 * (`customer_account_review.py`, `PendingRegistrationRow`).
 *
 * **Permission.** The route is guarded by `customer_account:review`, and the server checks
 * it again on every request. Marketing and the read-only manager hold neither Customer
 * Account permission, so they see no navigation entry and the route refuses — the
 * navigation is the courtesy and the server is the boundary.
 */

import { useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { PageHeader } from '../../components/layout/AppShell.jsx';
import { Button, Card, Pagination, TextInput } from '../../components/ui/index.jsx';
import { EmptyState, ErrorState, SkeletonRows } from '../../components/state/index.jsx';
import { useT } from '../../i18n/index.jsx';
import { customerAccountReviewApi } from '../../api/endpoints.js';
import { formatDateTime } from '../../utils/format.js';
import { P, useSession } from '../../app/SessionContext.jsx';
import { OrphanedAccounts } from './OrphanedAccounts.jsx';

const PAGE_SIZE = 25;

export function CustomerAccountQueuePage() {
  const { can } = useSession();
  // A role without the review permission gets the refusal, not the queue's title over an
  // error. The server refuses the data either way; this keeps the screen from implying a
  // queue exists for that role (fix pack 2; the role-boundary spec in accountApproval).
  if (!can(P.CUSTOMER_ACCOUNT_REVIEW)) return <ReviewRefused />;
  return <CustomerAccountQueue />;
}

/** The permission refusal, shared by the Customer Account review screens. */
export function ReviewRefused() {
  const t = useT();
  return (
    <Card>
      <EmptyState title={t('states.permissionTitle')} body={t('states.permissionBody')} />
    </Card>
  );
}

function CustomerAccountQueue() {
  const t = useT();
  const { can } = useSession();
  const [searchParams, setSearchParams] = useSearchParams();
  const reference = searchParams.get('account_reference') || '';
  const offset = Number.parseInt(searchParams.get('offset') || '0', 10) || 0;
  const [draftReference, setDraftReference] = useState(reference);

  const query = useQuery({
    queryKey: ['customer-account', 'registrations', reference, offset],
    queryFn: () =>
      customerAccountReviewApi.registrations({
        limit: PAGE_SIZE,
        offset,
        account_reference: reference || undefined,
      }),
  });

  function applyFilter(event) {
    event.preventDefault();
    const params = new URLSearchParams();
    if (draftReference.trim()) params.set('account_reference', draftReference.trim());
    // A new filter means a new first page: the offset is dropped rather than carried.
    setSearchParams(params);
  }

  function clearFilter() {
    setDraftReference('');
    setSearchParams(new URLSearchParams());
  }

  function goToOffset(nextOffset) {
    const params = new URLSearchParams(searchParams);
    if (nextOffset > 0) params.set('offset', String(nextOffset));
    else params.delete('offset');
    setSearchParams(params);
  }

  const page = query.data;

  // Second, not in parallel: each list read writes an audit row, and two audited reads
  // racing on SQLite is the `database is locked` the review screen already learned to
  // avoid by chaining (CustomerAccountReviewPage). Fix pack 2.
  const profileChanges = useQuery({
    queryKey: ['customer-account', 'profile-proposals'],
    queryFn: () => customerAccountReviewApi.profileProposals(),
    enabled: query.isSuccess,
  });

  return (
    <>
      <PageHeader
        title={t('customerAccounts.queueTitle')}
        subtitle={t('customerAccounts.queueSubtitle')}
      />

      <Card flush>
        <div className="filter-bar">
          <form className="filter-bar__row" onSubmit={applyFilter}>
            <label className="visually-hidden" htmlFor="customer-account-reference">
              {t('customerAccounts.accountReference')}
            </label>
            <TextInput
              id="customer-account-reference"
              type="search"
              placeholder={t('customerAccounts.accountReference')}
              value={draftReference}
              maxLength={20}
              onChange={(event) => setDraftReference(event.target.value)}
              style={{ maxWidth: 260 }}
            />
            <Button type="submit">{t('customerAccounts.applyFilter')}</Button>
            <Button variant="tertiary" onClick={clearFilter} disabled={!reference}>
              {t('customerAccounts.clearFilter')}
            </Button>
          </form>
        </div>

        {query.isPending && <SkeletonRows rows={5} />}
        {query.error && <ErrorState error={query.error} onRetry={() => query.refetch()} />}

        {page && page.items.length === 0 && (
          <EmptyState
            title={t('customerAccounts.emptyTitle')}
            body={
              reference ? t('customerAccounts.emptyFiltered') : t('customerAccounts.emptyBody')
            }
          />
        )}

        {page && page.items.length > 0 && (
          <>
            <div className="table-wrap" aria-busy={query.isFetching}>
              <table className="table table--stacked">
                <caption className="visually-hidden">{t('customerAccounts.queueTitle')}</caption>
                <thead>
                  <tr>
                    <th scope="col">{t('customerAccounts.accountReference')}</th>
                    <th scope="col">{t('customerAccounts.state')}</th>
                    <th scope="col">{t('customerAccounts.submitted')}</th>
                    <th scope="col">{t('customerAccounts.emailConfirmed')}</th>
                    <th scope="col">{t('customerAccounts.fieldCount')}</th>
                  </tr>
                </thead>
                <tbody>
                  {page.items.map((row) => (
                    <tr key={row.account_reference}>
                      <td
                        data-label={t('customerAccounts.accountReference')}
                        className="table__id"
                      >
                        <Link to={`/customer-accounts/${row.account_reference}`}>
                          {row.account_reference}
                        </Link>
                      </td>
                      <td data-label={t('customerAccounts.state')}>
                        {t(`customerAccounts.status.${row.status}`)}
                      </td>
                      <td data-label={t('customerAccounts.submitted')}>
                        {formatDateTime(row.submitted_at)}
                      </td>
                      <td data-label={t('customerAccounts.emailConfirmed')}>
                        {row.email_verified_at
                          ? formatDateTime(row.email_verified_at)
                          : t('customerAccounts.notConfirmed')}
                      </td>
                      <td data-label={t('customerAccounts.fieldCount')}>{row.field_count}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <Pagination
              total={page.total}
              limit={page.limit}
              offset={page.offset}
              onChange={goToOffset}
            />
          </>
        )}
      </Card>

      <Card title={t('customerAccounts.profileChangesTitle')} flush>
        <p className="meta" style={{ padding: '0 var(--space-5)' }}>
          {t('customerAccounts.profileChangesBody')}
        </p>
        {profileChanges.error && (
          <ErrorState error={profileChanges.error} onRetry={() => profileChanges.refetch()} />
        )}
        {profileChanges.data && profileChanges.data.items.length === 0 && (
          <EmptyState title={t('customerAccounts.profileChangesEmpty')} />
        )}
        {profileChanges.data && profileChanges.data.items.length > 0 && (
          <div className="table-wrap">
            <table className="table table--stacked">
              <caption className="visually-hidden">
                {t('customerAccounts.profileChangesTitle')}
              </caption>
              <thead>
                <tr>
                  <th scope="col">{t('customerAccounts.accountReference')}</th>
                  <th scope="col">{t('customerAccounts.profileChangesCustomer')}</th>
                  <th scope="col">{t('customerAccounts.submitted')}</th>
                  <th scope="col">{t('customerAccounts.profileChangesWhat')}</th>
                </tr>
              </thead>
              <tbody>
                {profileChanges.data.items.map((row) => (
                  <tr key={row.account_reference}>
                    <td data-label={t('customerAccounts.accountReference')}>
                      <Link to={`/customer-accounts/${row.account_reference}/profile-change`}>
                        {row.account_reference}
                      </Link>
                    </td>
                    <td data-label={t('customerAccounts.profileChangesCustomer')} className="mono">
                      {row.customer_public_id}
                    </td>
                    <td data-label={t('customerAccounts.submitted')}>
                      {formatDateTime(row.submitted_at)}
                    </td>
                    <td data-label={t('customerAccounts.profileChangesWhat')}>
                      {row.groups
                        .map((group) => t(`customerAccounts.profileGroup.${group}`, group))
                        .join(', ')}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      {can(P.CUSTOMER_ACCOUNT_DEACTIVATE) && (
        <DeactivatedAccounts enabled={profileChanges.isSuccess || profileChanges.isError} />
      )}
    </>
  );
}

/**
 * RC-UAT-21 Phase B (DEC-0231): the deactivated accounts, for the Admin who may reinstate
 * them. Same permission as deactivation; read after the lists above (one audited read at a
 * time on SQLite). Each row opens the account, where the reinstatement control is.
 *
 * RC-UAT-22 (B-13): followed by the accounts needing a customer, read after this list for
 * the same reason.
 */
function DeactivatedAccounts({ enabled }) {
  const t = useT();
  const list = useQuery({
    queryKey: ['customer-account', 'deactivated'],
    queryFn: () => customerAccountReviewApi.deactivatedIdentities(),
    enabled,
  });
  return (
    <>
      <Card title={t('customerAccounts.deactivatedListTitle')} flush>
        <p className="meta" style={{ padding: '0 var(--space-5)' }}>
          {t('customerAccounts.deactivatedListIntro')}
        </p>
        {list.error && <ErrorState error={list.error} onRetry={() => list.refetch()} />}
        {list.data && list.data.items.length === 0 && (
          <EmptyState title={t('customerAccounts.deactivatedListEmpty')} />
        )}
        {list.data && list.data.items.length > 0 && (
          <div className="table-wrap">
            <table className="table table--stacked">
              <caption className="visually-hidden">
                {t('customerAccounts.deactivatedListTitle')}
              </caption>
              <thead>
                <tr>
                  <th scope="col">{t('customerAccounts.accountReference')}</th>
                  <th scope="col">{t('customerAccounts.loginAddress')}</th>
                  <th scope="col">{t('customerAccounts.deactivatedSince')}</th>
                  <th scope="col">{t('customerAccounts.statusReason')}</th>
                  <th scope="col">{t('customerAccounts.reactivateTitle')}</th>
                </tr>
              </thead>
              <tbody>
                {list.data.items.map((row) => (
                  <tr key={row.account_reference}>
                    <td data-label={t('customerAccounts.accountReference')}>
                      <Link to={`/customer-accounts/${row.account_reference}`}>
                        {row.account_reference}
                      </Link>
                    </td>
                    <td data-label={t('customerAccounts.loginAddress')}>
                      {row.account_email_entered}
                    </td>
                    <td data-label={t('customerAccounts.deactivatedSince')}>
                      {formatDateTime(row.deactivated_at)}
                    </td>
                    <td data-label={t('customerAccounts.statusReason')}>
                      {row.status_reason_code
                        ? t(
                            `customerAccounts.statusReasonCode.${row.status_reason_code}`,
                            row.status_reason_code,
                          )
                        : '—'}
                    </td>
                    <td data-label={t('customerAccounts.reactivateTitle')}>
                      {row.can_reactivate
                        ? t('customerAccounts.deactivatedListReinstatable')
                        : t('customerAccounts.deactivatedListNotReinstatable')}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
      <OrphanedAccounts enabled={list.isSuccess || list.isError} />
    </>
  );
}
