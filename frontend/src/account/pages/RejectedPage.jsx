/**
 * "We are not able to set up an account."
 *
 * **No reason, and no reason code.** `STATE_MACHINES.md` §1 transition 5 requires a
 * neutral statement and forbids "a reason that describes another record" — a rejection
 * can be because the application duplicated one that was already decided, which is a fact
 * about somebody else's record. The server never sends the code to this surface;
 * `status_reason_code` on `/account/me` is a code for a screen to turn into a *neutral*
 * sentence, and this screen deliberately does not read it at all, so there is nothing to
 * accidentally render.
 *
 * In practice a rejected identity cannot authenticate — rejection revokes every session
 * and sign-in is refused generically — so this screen is reached by an account whose
 * state changed while a session was live, and by anybody who types the URL. Both see the
 * same page, and it says nothing about whether the visitor has an account at all.
 */

import { Link } from 'react-router-dom';
import { AccountNarrowPage, AccountPageHeader } from '../AccountLayout.jsx';
import { Card, Notice } from '../components.jsx';
import { useAccountT } from '../i18n.jsx';

export function RejectedPage() {
  const t = useAccountT();
  return (
    <AccountNarrowPage>
      <AccountPageHeader title={t('rejected.title')} />
      <Card>
        <Notice tone="info" title={t('rejected.notice')}>
          <p>{t('rejected.noticeBody')}</p>
        </Notice>

        <p>{t('rejected.still')}</p>

        <p>{t('rejected.mistake')}</p>

        <ul className="ca-links">
          <li>
            <Link to="/track">{t('common.trackShipment')}</Link>
          </li>
        </ul>
      </Card>
    </AccountNarrowPage>
  );
}
