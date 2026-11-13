/**
 * "Your account is waiting for review."
 *
 * The most common first experience, and it must read as a state rather than as an error
 * (`Design.md` §14a.4). No red, no warning tone, no apology — a calm card that says what
 * has happened and what happens next.
 *
 * It is also the screen for an **active** account whose link has been revoked or whose
 * linked customer was archived. That is deliberate: the server refuses shipment history
 * in both cases with one sentence that does not say which, and a second screen here would
 * put the distinction back that the API removed. `shipmentHistoryAvailable` is the only
 * thing consulted, and it is the server's own answer.
 *
 * **No shipment data reaches this screen**, and there is nothing to show if it did: a
 * pending account has no link, so the list route would refuse.
 */

import { Link } from 'react-router-dom';
import { AccountNarrowPage, AccountPageHeader } from '../AccountLayout.jsx';
import { Button, Card, Loading, Notice } from '../components.jsx';
import { ACCOUNT_STATUS, useAccountSession } from '../AccountSession.jsx';
import { useAccountT } from '../i18n.jsx';

export function PendingPage() {
  const session = useAccountSession();
  const t = useAccountT();

  if (session.isResolving) {
    return (
      <AccountNarrowPage>
        <Loading label={t('common.checkingAccount')} />
      </AccountNarrowPage>
    );
  }

  if (!session.isSignedIn) {
    return (
      <AccountNarrowPage>
        <AccountPageHeader title={t('pending.signInTitle')} />
        <Card>
          <p>{t('pending.signInBody')}</p>
          <ul className="ca-links">
            <li>
              <Link to="/account/sign-in">{t('common.signIn')}</Link>
            </li>
          </ul>
        </Card>
      </AccountNarrowPage>
    );
  }

  const awaitingVerification =
    session.status === ACCOUNT_STATUS.PENDING_APPROVAL && !session.emailVerified;

  return (
    <AccountNarrowPage>
      <AccountPageHeader title={t('pending.title')} />
      <Card>
        <Notice tone="info" title={t('pending.notice')}>
          <p>{t('pending.noticeBody')}</p>
        </Notice>

        <dl className="ca-summary">
          <div className="ca-summary__row">
            <dt>{t('pending.reference')}</dt>
            {/* The account's own reference, which staff can quote on the phone. It is not
                a customer id: OD-27 keeps the canonical CRM reference off this surface. */}
            <dd>{session.accountReference}</dd>
          </div>
          <div className="ca-summary__row">
            <dt>{t('pending.emailConfirmed')}</dt>
            <dd>{session.emailVerified ? t('pending.yes') : t('pending.notYet')}</dd>
          </div>
          <div className="ca-summary__row">
            <dt>{t('pending.history')}</dt>
            <dd>{t('pending.historyNotYet')}</dd>
          </div>
        </dl>

        {awaitingVerification ? (
          <Notice tone="warning" title={t('pending.confirmTitle')}>
            <p>{t('pending.confirmBody')}</p>
          </Notice>
        ) : null}

        <p>{t('pending.nothingToDo')}</p>

        <div className="ca-form__actions">
          {/* Re-reads `/account/me`. A person on this page wants to know whether anything
              has changed, and refreshing the browser to find out is a worse answer. */}
          <Button variant="secondary" onClick={() => session.refresh()}>
            {t('common.checkAgain')}
          </Button>
        </div>

        <ul className="ca-links">
          {awaitingVerification ? (
            <li>
              <Link to="/account/verification/resend">{t('common.resendConfirmation')}</Link>
            </li>
          ) : null}
          <li>
            <Link to="/track">{t('pending.trackSingle')}</Link>
          </li>
        </ul>
      </Card>
    </AccountNarrowPage>
  );
}
