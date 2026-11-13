/**
 * Notifications (OD-72, 2026-10-20).
 *
 * The customer chooses, per milestone, whether Solaris Express emails them — received, in
 * transit, out for delivery, delivered — and sees what has been sent. Two calls, both on
 * the account API (`GET /account/notifications`, `POST /account/notifications/preferences`);
 * both answer with the whole state, so the screen never assembles it from pieces.
 *
 * **Saved on change, and no change is ever dropped.** Each box posts only its own
 * milestone. Changes are queued and sent one at a time, in the order they were made; a
 * second change to a milestone that is still waiting replaces the waiting one (the latest
 * choice is the one that counts), and a change made while another is in flight waits its
 * turn rather than being ignored. While a milestone has a change outstanding its box shows
 * the value being saved. Each outcome — saved, or not saved and why — is announced through
 * one polite live region, and a failure is also shown as an alert with the reason.
 *
 * Email is the only channel today, and the page says so, with a note that a mobile app is
 * planned. It does not promise a date for it.
 */

import { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { AccountPageHeader } from '../AccountLayout.jsx';
import { AccountApiError, accountApi } from '../accountApi.js';
import { Button, Card, CheckboxField, EmptyState, Loading, Notice } from '../components.jsx';
import { FALLBACK_TIMEZONE } from '../format.js';
import { useAccountErrorText, useAccountFormat, useAccountT } from '../i18n.jsx';

const NOTIFICATIONS_KEY = ['account', 'notifications'];

/** The milestones, in the order a parcel reaches them. */
export const NOTIFICATION_MILESTONES = ['received', 'in_transit', 'out_for_delivery', 'delivered'];

const MILESTONE_LABELS = {
  received: 'notifications.milestone.received',
  in_transit: 'notifications.milestone.in_transit',
  out_for_delivery: 'notifications.milestone.out_for_delivery',
  delivered: 'notifications.milestone.delivered',
};

const STATE_LABELS = {
  pending: 'notifications.state.pending',
  sent: 'notifications.state.sent',
  not_sent: 'notifications.state.not_sent',
};

export function NotificationsPage() {
  const queryClient = useQueryClient();
  const headingRef = useRef(null);
  const t = useAccountT();
  const errorText = useAccountErrorText();
  const { formatDateTime, notRecorded } = useAccountFormat();

  // Milestone -> the value waiting to be (or being) saved.
  const [outstanding, setOutstanding] = useState({});
  // The latest outcome, announced by the one live region: `{ milestone, on, error? }`.
  const [outcome, setOutcome] = useState(null);
  const queue = useRef([]);
  const draining = useRef(false);

  const notifications = useQuery({
    queryKey: NOTIFICATIONS_KEY,
    queryFn: ({ signal }) => accountApi.notifications({ signal }),
  });

  // Focus the heading once the settings (or the reason they cannot be shown) are on screen,
  // as the shipment page does, so the result is announced rather than left to be found.
  const settled = !notifications.isPending;
  useEffect(() => {
    if (settled) headingRef.current?.focus();
  }, [settled]);

  const milestoneLabel = (milestone) =>
    MILESTONE_LABELS[milestone] ? t(MILESTONE_LABELS[milestone]) : milestone;

  async function drain() {
    if (draining.current) return;
    draining.current = true;
    while (queue.current.length > 0) {
      const { milestone, on } = queue.current.shift();
      try {
        const data = await accountApi.updateNotificationPreferences({ [milestone]: on });
        queryClient.setQueryData(NOTIFICATIONS_KEY, data);
        setOutcome({ milestone, on });
      } catch (error) {
        setOutcome({ milestone, on, error });
      }
      // Released only if no newer change to the same milestone is still waiting.
      if (!queue.current.some((item) => item.milestone === milestone)) {
        setOutstanding((current) => {
          const next = { ...current };
          delete next[milestone];
          return next;
        });
      }
    }
    draining.current = false;
  }

  function choose(milestone, on) {
    setOutstanding((current) => ({ ...current, [milestone]: on }));
    queue.current = [
      ...queue.current.filter((item) => item.milestone !== milestone),
      { milestone, on },
    ];
    drain();
  }

  if (notifications.isPending) return <Loading label={t('notifications.loading')} />;

  if (notifications.error) {
    const error = notifications.error;
    const signedOut = error instanceof AccountApiError && error.isSignedOut;
    return (
      <div className="ca-wide">
        <AccountPageHeader title={t('notifications.title')} headingRef={headingRef} />
        <Card>
          {signedOut ? (
            <>
              <Notice tone="warning" title={t('list.sessionEnded')}>
                <p>{t('notifications.sessionEndedBody')}</p>
              </Notice>
              <ul className="ca-links">
                <li>
                  <Link to="/account/sign-in">{t('common.signIn')}</Link>
                </li>
              </ul>
            </>
          ) : (
            <>
              <Notice tone="error" title={t('notifications.loadFailed')}>
                <p>{errorText(error)}</p>
              </Notice>
              <div className="ca-form__actions">
                <Button variant="secondary" onClick={() => notifications.refetch()}>
                  {t('common.tryAgain')}
                </Button>
              </div>
            </>
          )}
        </Card>
      </div>
    );
  }

  const data = notifications.data;
  const preferences = data.preferences ?? {};
  const history = data.history ?? [];
  // The response's own zone when it carries one, otherwise the organization default every
  // other account page falls back to — never the browser's.
  const timeZone = data.timezone || FALLBACK_TIMEZONE;

  const checkedFor = (milestone) =>
    milestone in outstanding ? outstanding[milestone] : Boolean(preferences[milestone]);

  let announcement = '';
  if (outcome) {
    const label = milestoneLabel(outcome.milestone);
    if (outcome.error) announcement = t('notifications.saveFailed', { milestone: label });
    else announcement = t(outcome.on ? 'notifications.savedOn' : 'notifications.savedOff', { milestone: label });
  }

  return (
    <div className="ca-wide">
      <AccountPageHeader
        title={t('notifications.title')}
        headingRef={headingRef}
        intro={t('notifications.intro')}
      />

      <Notice tone="info">
        <p>{t('notifications.channelNote')}</p>
      </Notice>

      <Card title={t('notifications.preferencesTitle')}>
        {/* One live region for every save, so each outcome is announced once and in turn. */}
        <p className="ca-meta" role="status" aria-live="polite">
          {announcement}
        </p>
        {outcome?.error ? (
          <Notice tone="error" title={t('common.couldNotSave')}>
            <p>{errorText(outcome.error)}</p>
          </Notice>
        ) : null}
        <fieldset className="ca-fieldset">
          <legend className="ca-fieldset__legend">{t('notifications.preferencesCard')}</legend>
          {NOTIFICATION_MILESTONES.map((milestone) => (
            <CheckboxField
              key={milestone}
              name={`notify-${milestone}`}
              fieldKey={`notify_${milestone}`}
              label={milestoneLabel(milestone)}
              checked={checkedFor(milestone)}
              onChange={(on) => choose(milestone, on)}
            />
          ))}
        </fieldset>
      </Card>

      <Card title={t('notifications.historyCard')}>
        <p className="ca-meta">{t('notifications.timesShownIn', { zone: timeZone })}</p>
        {history.length === 0 ? (
          <EmptyState title={t('notifications.historyEmpty')} />
        ) : (
          <ul className="ca-notification-history" aria-label={t('notifications.historyCaption')}>
            {history.map((entry, index) => (
              <li
                key={`${entry.created_at}-${entry.milestone}-${index}`}
                className="ca-notification-history__item"
              >
                <dl className="ca-detail-grid">
                  <div className="ca-detail-row">
                    <dt className="ca-detail-row__label">{t('notifications.colMilestone')}</dt>
                    <dd className="ca-detail-row__value">{milestoneLabel(entry.milestone)}</dd>
                  </div>
                  <div className="ca-detail-row">
                    <dt className="ca-detail-row__label">{t('notifications.colShipment')}</dt>
                    <dd className="ca-detail-row__value ca-mono">
                      {entry.shipment_reference || notRecorded}
                    </dd>
                  </div>
                  <div className="ca-detail-row">
                    <dt className="ca-detail-row__label">{t('notifications.colDate')}</dt>
                    <dd className="ca-detail-row__value">
                      {formatDateTime(entry.created_at, timeZone) || notRecorded}
                    </dd>
                  </div>
                  <div className="ca-detail-row">
                    <dt className="ca-detail-row__label">{t('notifications.colState')}</dt>
                    <dd className="ca-detail-row__value">
                      {STATE_LABELS[entry.state] ? t(STATE_LABELS[entry.state]) : entry.state}
                    </dd>
                  </div>
                </dl>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}
