/**
 * Possible duplicates: compare, then merge (fix pack item 9; UAT-AD-04).
 *
 * The profile already carried a "Possible duplicate" badge from `has_duplicate_candidates`
 * and nothing to act on it with. This tab is the action: every candidate the server
 * matched is laid out beside this record, field by field, and an administrator can merge
 * one into the other after choosing which record survives and typing the retiring ID.
 *
 * Three rules, all enforced on the server and merely reflected here:
 *
 * * reviewing needs `duplicate:review`; merging needs `customer:merge` (Admin only);
 * * nothing merges automatically — families share phones and emails (CRM.md section 13);
 * * the merge is confirmed by typing the **source** customer ID exactly, which is the
 *   one that is retired and kept as a former ID on the survivor.
 */

import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Link, useNavigate } from 'react-router-dom';
import { customersApi } from '../../../api/endpoints.js';
import { useT } from '../../../i18n/index.jsx';
import { P, useSession } from '../../../app/SessionContext.jsx';
import {
  Banner,
  Button,
  Card,
  Modal,
  RouteBadge,
  StatusBadge,
  TextInput,
} from '../../../components/ui/index.jsx';
import { EmptyState, ErrorState, SkeletonRows } from '../../../components/state/index.jsx';
import { formatDate, interpolate } from '../../../utils/format.js';

/** The fields compared, in the order a reviewer reads them. */
function comparisonRows(t) {
  return [
    { key: 'public_id', label: t('customers.columnId'), render: (c) => <span className="mono">{c.public_id}</span> },
    { key: 'full_name', label: t('customers.columnName'), render: (c) => c.full_name },
    { key: 'phone_entered', label: t('customers.phone'), render: (c) => c.phone_entered },
    { key: 'email_entered', label: t('customers.email'), render: (c) => c.email_entered },
    {
      key: 'city',
      label: t('customers.city'),
      render: (c) => [c.city, c.province_state, c.country_code].filter(Boolean).join(', '),
    },
    {
      key: 'preferred_language',
      label: t('customers.preferredLanguage'),
      render: (c) => t(`languages.${c.preferred_language}`, c.preferred_language),
    },
    {
      key: 'primary_route_group',
      label: t('customers.columnRoute'),
      render: (c) => <RouteBadge route={c.primary_route_group} />,
    },
    {
      key: 'lifecycle_status',
      label: t('customers.columnLifecycle'),
      render: (c) => <StatusBadge kind="lifecycle" value={c.lifecycle_status} />,
    },
    {
      key: 'total_qualifying_shipments',
      label: t('customers.columnShipments'),
      render: (c) => c.total_qualifying_shipments,
    },
    {
      key: 'last_shipment_at',
      label: t('customers.columnLastShipment'),
      render: (c) => formatDate(c.last_shipment_at),
    },
    { key: 'owner', label: t('customers.columnOwner'), render: (c) => c.owner?.full_name },
    { key: 'created_at', label: t('customers.created'), render: (c) => formatDate(c.created_at) },
  ];
}

export function DuplicatesTab({ customer }) {
  const t = useT();
  const { can } = useSession();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [merging, setMerging] = useState(null); // the candidate being merged, or null
  const [keep, setKeep] = useState('this'); // 'this' | 'other'
  const [confirmation, setConfirmation] = useState('');

  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ['duplicate-candidates', customer.id],
    queryFn: () => customersApi.duplicateCandidates(customer.id),
    enabled: can(P.DUPLICATE_REVIEW),
  });

  const mergeMutation = useMutation({
    mutationFn: ({ source, target }) =>
      customersApi.merge({
        source_customer_id: source.id,
        target_customer_id: target.id,
        confirmation: confirmation.trim().toUpperCase(),
      }),
    onSuccess: (survivor) => {
      queryClient.invalidateQueries({ queryKey: ['customers'] });
      queryClient.invalidateQueries({ queryKey: ['customer'] });
      queryClient.invalidateQueries({ queryKey: ['duplicate-candidates'] });
      setMerging(null);
      setConfirmation('');
      // The survivor's profile is where the merged history now lives.
      navigate(`/customers/${survivor.id}`, { replace: true });
    },
  });

  if (!can(P.DUPLICATE_REVIEW)) {
    return (
      <Card>
        <EmptyState title={t('states.permissionTitle')} body={t('states.permissionBody')} />
      </Card>
    );
  }
  if (isLoading) return <SkeletonRows rows={4} height={72} />;
  if (error) return <ErrorState error={error} onRetry={refetch} />;

  const candidates = data?.candidates ?? [];
  const rows = comparisonRows(t);
  const canMerge = can(P.CUSTOMER_MERGE) && !customer.merged_into_customer_id;

  const source = merging ? (keep === 'this' ? merging.customer : customer) : null;
  const target = merging ? (keep === 'this' ? customer : merging.customer) : null;
  const confirmed = Boolean(source) && confirmation.trim().toUpperCase() === source.public_id;

  return (
    <>
      <div className="stack">
        <Banner tone="neutral" title={t('customers.duplicatePanelTitle')}>
          {data?.guidance || t('customers.duplicatePanelBody')}
        </Banner>

        {candidates.length === 0 ? (
          <Card>
            <EmptyState
              title={t('customers.noDuplicatesTitle')}
              body={t('customers.noDuplicatesBody')}
            />
          </Card>
        ) : (
          candidates.map((candidate) => (
            <Card
              key={candidate.customer.id}
              title={`${t('customers.compareWith')} ${candidate.customer.full_name}`}
              actions={
                <>
                  <Link to={`/customers/${candidate.customer.id}`} className="btn btn--secondary">
                    {t('customers.openExisting')}
                  </Link>
                  {canMerge && (
                    <Button
                      variant="primary"
                      onClick={() => {
                        setMerging(candidate);
                        setKeep('this');
                        setConfirmation('');
                      }}
                    >
                      {t('customers.mergeAction')}
                    </Button>
                  )}
                </>
              }
              flush
            >
              <div className="table-wrap">
                <table className="table compare-table">
                  <caption className="visually-hidden">
                    {t('customers.compareWith')} {candidate.customer.full_name}
                  </caption>
                  <thead>
                    <tr>
                      <th scope="col">{t('customers.compareField')}</th>
                      <th scope="col">{t('customers.thisRecord')}</th>
                      <th scope="col">{t('customers.candidateRecord')}</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr>
                      <th scope="row">{t('customers.matchedOn')}</th>
                      <td colSpan={2}>
                        {candidate.matched_on.join(', ')} · {t('customers.confidence')}{' '}
                        {candidate.confidence}%
                      </td>
                    </tr>
                    {rows.map((row) => (
                      <tr key={row.key}>
                        <th scope="row">{row.label}</th>
                        <td>{row.render(customer) ?? '—'}</td>
                        <td>{row.render(candidate.customer) ?? '—'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Card>
          ))
        )}

        {!canMerge && candidates.length > 0 && (
          <p className="meta">{t('customers.mergeRequiresAdmin')}</p>
        )}
      </div>

      <Modal
        open={Boolean(merging)}
        onClose={() => setMerging(null)}
        title={t('customers.mergeTitle')}
        footer={
          <>
            <Button onClick={() => setMerging(null)}>{t('common.cancel')}</Button>
            <span className="spacer" />
            <Button
              variant="danger"
              disabled={!confirmed}
              loading={mergeMutation.isPending}
              onClick={() => mergeMutation.mutate({ source, target })}
            >
              {t('customers.mergeAction')}
            </Button>
          </>
        }
      >
        {merging && (
          <div className="stack">
            {mergeMutation.error && <Banner tone="danger">{mergeMutation.error.message}</Banner>}
            <p>{t('customers.mergeKeep')}</p>
            <label className="checkbox">
              <input
                type="radio"
                name="merge-keep"
                value="this"
                checked={keep === 'this'}
                onChange={() => setKeep('this')}
              />
              <span>
                {t('customers.mergeKeepThis')} — <span className="mono">{customer.public_id}</span>{' '}
                {customer.full_name}
              </span>
            </label>
            <label className="checkbox">
              <input
                type="radio"
                name="merge-keep"
                value="other"
                checked={keep === 'other'}
                onChange={() => setKeep('other')}
              />
              <span>
                {t('customers.mergeKeepOther')} —{' '}
                <span className="mono">{merging.customer.public_id}</span>{' '}
                {merging.customer.full_name}
              </span>
            </label>
            <Banner tone="warning">
              {interpolate(t('customers.mergeConsequence'), {
                source: source.public_id,
                target: target.public_id,
              })}
            </Banner>
            <label className="field__label" htmlFor="merge-confirmation">
              {interpolate(t('customers.mergeConfirmLabel'), { source: source.public_id })}
            </label>
            <TextInput
              id="merge-confirmation"
              value={confirmation}
              autoComplete="off"
              onChange={(event) => setConfirmation(event.target.value)}
            />
          </div>
        )}
      </Modal>
    </>
  );
}
