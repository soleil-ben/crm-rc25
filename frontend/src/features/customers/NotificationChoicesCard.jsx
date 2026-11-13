/**
 * A customer's milestone email choices, edited by staff on their behalf (Phase 14; the
 * choices themselves are Phase 13F, OD-72).
 *
 * Four milestones -- received, in transit, out for delivery, delivered -- each on or off.
 * Reading needs `shipment:read` and `customer:read`; changing needs `tracking:write`
 * (Operations, Admin). The server records the change as made by staff and audits it. Test
 * capture only: no email reaches a customer from this build.
 */

import { useEffect, useRef, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { notificationsApi } from '../../api/endpoints.js';
import { P, useSession } from '../../app/SessionContext.jsx';
import { useT } from '../../i18n/index.jsx';
import { Banner, Button, Card, Checkbox } from '../../components/ui/index.jsx';
import { ErrorState, SkeletonRows } from '../../components/state/index.jsx';

export const MILESTONES = ['received', 'in_transit', 'out_for_delivery', 'delivered'];

export function NotificationChoicesCard({ customer }) {
  const t = useT();
  const { can } = useSession();
  const queryClient = useQueryClient();
  const canEdit = can(P.TRACKING_WRITE) && !customer.merged_into_customer_id;
  const key = ['customer-notification-preferences', String(customer.id)];
  const query = useQuery({ queryKey: key, queryFn: () => notificationsApi.preferences(customer.id) });
  const [choices, setChoices] = useState(null);
  const [saved, setSaved] = useState(false);
  const savedRef = useRef(null);
  // The choices as last loaded or saved. A refetch refills only the boxes the user has not
  // touched, so it cannot wipe an unsaved edit (Phase 14 review).
  const baseline = useRef(null);

  useEffect(() => {
    if (!query.data) return;
    const fresh = query.data.preferences;
    const before = baseline.current;
    baseline.current = fresh;
    setChoices((current) => {
      if (!current || !before) return fresh;
      const next = { ...current };
      for (const milestone of MILESTONES) {
        if (current[milestone] === before[milestone]) next[milestone] = fresh[milestone];
      }
      return next;
    });
  }, [query.data]);

  const changed = choices && baseline.current
    ? Object.fromEntries(
        MILESTONES.filter((m) => Boolean(choices[m]) !== Boolean(baseline.current[m])).map((m) => [m, Boolean(choices[m])]),
      )
    : {};
  const dirty = Object.keys(changed).length > 0;
  useEffect(() => {
    if (saved) savedRef.current?.focus();
  }, [saved]);

  const save = useMutation({
    // Only the choices that changed are sent.
    mutationFn: () => notificationsApi.setPreferences(customer.id, changed),
    onSuccess: (data) => {
      baseline.current = data.preferences;
      setChoices(data.preferences);
      queryClient.setQueryData(key, data);
      setSaved(true);
    },
  });

  return (
    <Card title={t('customerNotify.title')}>
      <p className="meta">{t('customerNotify.intro')}</p>
      {query.isLoading || !choices ? (
        query.error ? (
          <ErrorState error={query.error} onRetry={query.refetch} />
        ) : (
          <SkeletonRows rows={2} />
        )
      ) : (
        <form
          onSubmit={(event) => {
            event.preventDefault();
            setSaved(false);
            save.mutate();
          }}
        >
          {saved && (
            <div ref={savedRef} tabIndex={-1}>
              <Banner tone="info">{t('customerNotify.saved')}</Banner>
            </div>
          )}
          {save.error && <Banner tone="danger">{save.error.message}</Banner>}
          <fieldset className="notify-choices">
            <legend className="visually-hidden">{t('customerNotify.title')}</legend>
            {MILESTONES.map((milestone) => (
              <Checkbox
                key={milestone}
                label={t(`customerNotify.milestone.${milestone}`)}
                checked={Boolean(choices[milestone])}
                disabled={!canEdit}
                onChange={(event) => {
                  setSaved(false);
                  setChoices((current) => ({ ...current, [milestone]: event.target.checked }));
                }}
              />
            ))}
          </fieldset>
          {canEdit ? (
            <Button type="submit" compact variant="primary" loading={save.isPending} disabled={!dirty}>
              {t('customerNotify.save')}
            </Button>
          ) : (
            <p className="meta">{t('customerNotify.readOnly')}</p>
          )}
        </form>
      )}
    </Card>
  );
}
