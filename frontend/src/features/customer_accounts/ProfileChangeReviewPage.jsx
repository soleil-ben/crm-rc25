/**
 * Review a linked customer's profile change (fix pack 2; CA-PRF-02; FIELD_MATRIX.md §5).
 *
 * The reviewer sees, for every proposed field: the value proposed, the value on file when
 * it was proposed, the value on file **now**, and the normalized form. Each group — legal
 * name, preferred name, phone, pickup address — is approved or declined on its own, and a
 * group whose record changed underneath the request is flagged here and refused by the
 * server if approved. A decided request is shown read-only with what was applied.
 *
 * Reading needs `customer_account:review`; deciding also needs `customer_account:approve`.
 * The controls are absent for a role without it, and the server refuses it independently.
 */

import { useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { PageHeader } from '../../components/layout/AppShell.jsx';
import { Banner, Button, Card, Select, StatusBadge } from '../../components/ui/index.jsx';
import { ErrorState, SkeletonRows } from '../../components/state/index.jsx';
import { useT } from '../../i18n/index.jsx';
import { P, useSession } from '../../app/SessionContext.jsx';
import { customerAccountReviewApi } from '../../api/endpoints.js';
import { formatDateTime, interpolate } from '../../utils/format.js';
import { ReviewRefused } from './CustomerAccountQueuePage.jsx';
import './customer_accounts.css';

export function ProfileChangeReviewPage() {
  const { can } = useSession();
  if (!can(P.CUSTOMER_ACCOUNT_REVIEW)) return <ReviewRefused />;
  return <ProfileChangeReview />;
}

function ProfileChangeReview() {
  const t = useT();
  const { accountReference } = useParams();
  const { can } = useSession();
  const queryClient = useQueryClient();
  const mayDecide = can(P.CUSTOMER_ACCOUNT_APPROVE);
  const [decisions, setDecisions] = useState({});
  const [reasonCode, setReasonCode] = useState('');

  const review = useQuery({
    queryKey: ['customer-account', 'profile-proposal', accountReference],
    queryFn: () => customerAccountReviewApi.profileProposal(accountReference),
  });

  const decide = useMutation({
    mutationFn: () =>
      customerAccountReviewApi.decideProfileProposal(accountReference, {
        decisions,
        reason_code: reasonCode || null,
      }),
    onSuccess: (data) => {
      queryClient.setQueryData(['customer-account', 'profile-proposal', accountReference], data);
      queryClient.invalidateQueries({ queryKey: ['customer-account', 'profile-proposals'] });
      queryClient.invalidateQueries({ queryKey: ['customer'] });
    },
  });

  if (review.isPending) return <SkeletonRows rows={6} />;
  if (review.error) return <ErrorState error={review.error} onRetry={() => review.refetch()} />;

  const data = review.data;
  const pending = data.status === 'pending';
  const anyDeclined = Object.values(decisions).includes('decline');
  const complete = data.groups.every((group) => decisions[group]);
  const groupLabel = (group) => t(`customerAccounts.profileGroup.${group}`, group);

  return (
    <>
      <PageHeader
        title={`${t('customerAccounts.profileChangeTitle')} — ${data.account_reference}`}
        subtitle={t('customerAccounts.profileChangeSubtitle')}
        breadcrumb={<Link to="/customer-accounts">{t('customerAccounts.backToQueue')}</Link>}
      />

      {!pending && (
        <Banner tone="neutral" title={t('customerAccounts.profileChangeDecided')}>
          <p>
            {t(`customerAccounts.profileStatus.${data.status}`, data.status)}
            {data.reviewed_at ? ` · ${formatDateTime(data.reviewed_at)}` : ''}
          </p>
        </Banner>
      )}
      {decide.error && <Banner tone="danger">{decide.error.message}</Banner>}

      <Card>
        <p>
          {t('customerAccounts.profileChangeCustomer')}{' '}
          <Link to={`/customers?search=${encodeURIComponent(data.customer_public_id)}`} className="mono">
            {data.customer_public_id}
          </Link>{' '}
          · {t('customerAccounts.submitted')} {formatDateTime(data.submitted_at)}
        </p>
      </Card>

      {data.groups.map((group) => {
        const rows = data.fields.filter((row) => row.group === group);
        const drifted = rows.some((row) => row.drifted);
        return (
          <Card key={group} title={groupLabel(group)}>
            {drifted && pending && (
              <Banner tone="warning" title={t('customerAccounts.profileDriftTitle')}>
                {t('customerAccounts.profileDriftBody')}
              </Banner>
            )}
            <div className="table-wrap">
              <table className="table table--stacked">
                <caption className="visually-hidden">{groupLabel(group)}</caption>
                <thead>
                  <tr>
                    <th scope="col">{t('customerAccounts.field')}</th>
                    <th scope="col">{t('customerAccounts.profileProposed')}</th>
                    <th scope="col">{t('customerAccounts.profileOnFileThen')}</th>
                    <th scope="col">{t('customerAccounts.profileOnFileNow')}</th>
                    <th scope="col">{t('customerAccounts.profileNormalized')}</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((row) => (
                    <tr key={row.field_key}>
                      <td data-label={t('customerAccounts.field')} className="mono">
                        {row.field_key}
                      </td>
                      <td data-label={t('customerAccounts.profileProposed')}>
                        <strong>{row.proposed_value ?? '—'}</strong>
                        {!pending && (
                          <div>
                            <StatusBadge
                              tone={row.applied ? 'success' : 'neutral'}
                              value={row.applied ? 'applied' : 'not_applied'}
                              label={
                                row.applied
                                  ? t('customerAccounts.profileApplied')
                                  : t('customerAccounts.profileNotApplied')
                              }
                            />
                          </div>
                        )}
                      </td>
                      <td data-label={t('customerAccounts.profileOnFileThen')}>
                        {row.current_value_at_submission ?? '—'}
                      </td>
                      <td data-label={t('customerAccounts.profileOnFileNow')}>
                        {row.current_value_now ?? '—'}
                        {row.drifted && (
                          <div>
                            <StatusBadge
                              tone="warning"
                              value="changed"
                              label={t('customerAccounts.profileChangedSince')}
                            />
                          </div>
                        )}
                      </td>
                      <td data-label={t('customerAccounts.profileNormalized')} className="mono">
                        {row.proposed_value_normalized ?? '—'}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {pending && mayDecide && (
              <fieldset className="ca-decision">
                <legend>{interpolate(t('customerAccounts.profileDecisionFor'), { group: groupLabel(group) })}</legend>
                {['approve', 'decline'].map((verdict) => (
                  <label key={verdict} className="checkbox">
                    <input
                      type="radio"
                      name={`decision-${group}`}
                      value={verdict}
                      checked={decisions[group] === verdict}
                      onChange={() => setDecisions((current) => ({ ...current, [group]: verdict }))}
                    />
                    <span>{t(`customerAccounts.profileVerdict.${verdict}`)}</span>
                  </label>
                ))}
              </fieldset>
            )}
          </Card>
        );
      })}

      {pending && mayDecide && (
        <Card>
          {anyDeclined && (
            <Select
              aria-label={t('customerAccounts.profileDeclineReason')}
              value={reasonCode}
              onChange={(event) => setReasonCode(event.target.value)}
              placeholder={t('customerAccounts.profileDeclineReason')}
              options={data.decline_reason_codes.map((value) => ({
                value,
                label: t(`customerAccounts.profileDeclineCode.${value}`, value),
              }))}
              style={{ maxWidth: 320 }}
            />
          )}
          <div className="row-wrap" style={{ marginTop: 'var(--space-3)' }}>
            <Button
              variant="primary"
              disabled={!complete || (anyDeclined && !reasonCode) || decide.isPending}
              loading={decide.isPending}
              onClick={() => decide.mutate()}
            >
              {t('customerAccounts.profileRecordDecision')}
            </Button>
          </div>
        </Card>
      )}
      {pending && !mayDecide && <p className="meta">{t('customerAccounts.readOnlyNotice')}</p>}
    </>
  );
}
