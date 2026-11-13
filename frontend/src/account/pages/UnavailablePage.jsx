/**
 * "This account is not available."
 *
 * The screen for **suspended and deactivated**, and it does not say which. The two have
 * different causes and different routes back — a suspension can be reinstated, a
 * deactivation follows a privacy request — and neither is something this surface narrates.
 * The server refuses sign-in for both with the same generic sentence, and a screen that
 * separated them would be a way to ask which one applied to an address.
 *
 * One page, one sentence, one route back: contact Solaris Express.
 */

import { Link } from 'react-router-dom';
import { AccountNarrowPage, AccountPageHeader } from '../AccountLayout.jsx';
import { Card, Notice } from '../components.jsx';
import { useAccountT } from '../i18n.jsx';

export function UnavailablePage() {
  const t = useAccountT();
  return (
    <AccountNarrowPage>
      <AccountPageHeader title={t('unavailable.title')} />
      <Card>
        <Notice tone="info" title={t('unavailable.notice')}>
          <p>{t('unavailable.noticeBody')}</p>
        </Notice>

        <p>{t('unavailable.still')}</p>

        <ul className="ca-links">
          <li>
            <Link to="/track">{t('common.trackShipment')}</Link>
          </li>
          <li>
            <Link to="/account/sign-in">{t('common.backToSignIn')}</Link>
          </li>
        </ul>
      </Card>
    </AccountNarrowPage>
  );
}
