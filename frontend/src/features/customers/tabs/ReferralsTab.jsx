/**
 * Referrals (CRM.md section 4).
 *
 * Shows who referred this customer and whom they referred, with the qualified-referral
 * outcome shown separately from the raw count. Self-referrals are rejected server-side.
 */

import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { customersApi, opsApi } from '../../../api/endpoints.js';
import { useT } from '../../../i18n/index.jsx';
import { P, useSession } from '../../../app/SessionContext.jsx';
import { Banner, Button, Card, Drawer, Field, StatusBadge, TextInput } from '../../../components/ui/index.jsx';
import { EmptyState, ErrorState, SkeletonRows } from '../../../components/state/index.jsx';
import { formatDate } from '../../../utils/format.js';

/** "Recorded by Demo Operations on 12 Sep 2026" — or who is unknown, but when is not. */
function RecordedBy({ row, t }) {
  return (
    <span className="meta">
      {t('profile.recordedBy')}{' '}
      {row.recorded_by ? row.recorded_by.full_name : t('profile.recordedByUnknown')}
      {' · '}
      {formatDate(row.created_at)}
    </span>
  );
}

export function ReferralsTab({ customer }) {
  const t = useT();
  const { can } = useSession();
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState('');
  const [note, setNote] = useState('');
  const [selected, setSelected] = useState(null);

  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ['referrals', customer.id],
    queryFn: () => customersApi.referrals(customer.id),
  });

  const searchQuery = useQuery({
    queryKey: ['referral-search', search],
    queryFn: () => opsApi.search(search, 6),
    enabled: open && search.trim().length >= 2,
  });

  const createMutation = useMutation({
    mutationFn: () =>
      customersApi.createReferral(customer.id, {
        referred_customer_id: selected.id,
        note: note || null,
      }),
    onSuccess: () => {
      // Every referrals list and every customer record, not just this one. A referral
      // has two ends: the referred customer's tab (and both customers' referral counts)
      // were served from cache until a reload (UAT round 2, fix pack 2 item 3).
      queryClient.invalidateQueries({ queryKey: ['referrals'] });
      queryClient.invalidateQueries({ queryKey: ['customer'] });
      queryClient.invalidateQueries({ queryKey: ['customers'] });
      setOpen(false);
      setSelected(null);
      setNote('');
      setSearch('');
    },
  });

  if (isLoading) return <SkeletonRows rows={3} height={72} />;
  if (error) return <ErrorState error={error} onRetry={refetch} />;

  const referrals = data ?? [];
  const referredBy = referrals.filter((row) => row.referred?.id === customer.id);
  const referredOthers = referrals.filter((row) => row.referrer?.id === customer.id);

  return (
    <>
      <div className="stack">
        <Banner tone="neutral">
          A referral is a recorded relationship only. It creates no reward and never
          implies marketing consent.
        </Banner>

        <Card title="Referred by">
          {referredBy.length === 0 ? (
            <p className="meta">No referring customer recorded.</p>
          ) : (
            referredBy.map((row) => (
              <p key={row.id}>
                <Link to={`/customers/${row.referrer.id}`}>{row.referrer.full_name}</Link>{' '}
                <span className="meta mono">{row.referrer.public_id}</span>
                {row.note && <span className="meta"> — {row.note}</span>}
                <br />
                <RecordedBy row={row} t={t} />
              </p>
            ))
          )}
        </Card>

        <Card
          title={t('profile.referrals')}
          actions={
            can(P.REFERRAL_WRITE) ? (
              <Button variant="primary" compact onClick={() => setOpen(true)}>
                Record referral
              </Button>
            ) : null
          }
          flush
        >
          {referredOthers.length === 0 ? (
            <EmptyState
              title="No referrals recorded"
              body="Record a referral when a customer tells you who sent them."
            />
          ) : (
            <div className="table-wrap">
              <table className="table table--stacked">
                <caption className="visually-hidden">Customers referred by this customer</caption>
                <thead>
                  <tr>
                    <th scope="col">{t('customers.columnId')}</th>
                    <th scope="col">{t('customers.columnName')}</th>
                    <th scope="col">{t('customers.columnLifecycle')}</th>
                    <th scope="col">Qualified</th>
                    <th scope="col">{t('profile.recordedBy')}</th>
                  </tr>
                </thead>
                <tbody>
                  {referredOthers.map((row) => (
                    <tr key={row.id}>
                      <td data-label={t('customers.columnId')} className="table__id">
                        {row.referred?.public_id}
                      </td>
                      <td data-label={t('customers.columnName')} className="table__primary">
                        <Link to={`/customers/${row.referred?.id}`}>{row.referred?.full_name}</Link>
                        {row.note && <div className="meta">{row.note}</div>}
                      </td>
                      <td data-label={t('customers.columnLifecycle')}>
                        <StatusBadge kind="lifecycle" value={row.referred?.lifecycle_status} />
                      </td>
                      <td data-label="Qualified">
                        {row.referred_has_qualifying_shipment ? (
                          <StatusBadge tone="success" value="yes" label="Shipped" />
                        ) : (
                          <StatusBadge tone="neutral" value="no" label="Not yet" />
                        )}
                      </td>
                      <td data-label={t('profile.recordedBy')}>
                        {row.recorded_by ? row.recorded_by.full_name : t('profile.recordedByUnknown')}
                        <div className="meta">{formatDate(row.created_at)}</div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>
      </div>

      <Drawer
        open={open}
        onClose={() => setOpen(false)}
        title="Record referral"
        footer={
          <>
            <Button onClick={() => setOpen(false)}>{t('common.cancel')}</Button>
            <Button
              variant="primary"
              disabled={!selected}
              loading={createMutation.isPending}
              onClick={() => createMutation.mutate()}
            >
              {t('common.save')}
            </Button>
          </>
        }
      >
        <div className="stack">
          {createMutation.error && <ErrorState error={createMutation.error} />}
          <p className="field__hint">
            Search for the customer that {customer.full_name} referred. A customer cannot
            refer themselves.
          </p>
          <Field label={t('common.search')}>
            {(props) => (
              <TextInput
                {...props}
                type="search"
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                placeholder={t('customers.searchPlaceholder')}
              />
            )}
          </Field>
          <ul className="picker-list">
            {(searchQuery.data?.items ?? [])
              .filter((item) => item.id !== customer.id)
              .map((item) => (
                <li key={item.id}>
                  <button
                    type="button"
                    className={
                      selected?.id === item.id ? 'picker-list__item is-selected' : 'picker-list__item'
                    }
                    onClick={() => setSelected(item)}
                  >
                    <span className="mono">{item.public_id}</span>
                    <span>{item.full_name}</span>
                  </button>
                </li>
              ))}
          </ul>
          <Field label="Note">
            {(props) => (
              <TextInput
                {...props}
                value={note}
                onChange={(event) => setNote(event.target.value)}
              />
            )}
          </Field>
        </div>
      </Drawer>
    </>
  );
}
