/**
 * The landing page of a link sent to a **new** sign-in email before RC-UAT-25.
 *
 * Since RC-UAT-25 item 2 (Ben, 2026-10-25) only Solaris Express changes a sign-in email, so a
 * link like this no longer changes anything, whatever state it is in. The page says so and
 * points the customer to Solaris Express. The token is still handled the way the verification
 * link's is -- `main.jsx` has already moved a fragment token into memory; this page takes it,
 * rewrites the address bar if it still carries one (`replace`, so Back does not walk onto it)
 * -- and it is sent once, so the server consumes it and closes the request it belonged to.
 * The server's answer is always the refusal; the page does not wait for it.
 */

import { useEffect, useRef } from 'react';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import { AccountNarrowPage, AccountPageHeader } from '../AccountLayout.jsx';
import { useAccountSession } from '../AccountSession.jsx';
import { Card, Notice } from '../components.jsx';
import { accountApi } from '../accountApi.js';
import { useAccountT } from '../i18n.jsx';
import { locationCarriesToken, takeLinkToken, tokenFromLocation } from '../linkToken.js';

export function ConfirmEmailChangePage() {
  const location = useLocation();
  const navigate = useNavigate();
  const session = useAccountSession();
  const headingRef = useRef(null);
  const sentRef = useRef(false);
  const t = useAccountT();

  useEffect(() => {
    const token = tokenFromLocation(location) ?? takeLinkToken();
    if (locationCarriesToken(location)) {
      navigate('/account/confirm-email-change', { replace: true });
    }
    if (token && !sentRef.current) {
      sentRef.current = true;
      accountApi.confirmEmailChange(token).catch(() => {});
    }
  }, [navigate, location]);

  useEffect(() => {
    headingRef.current?.focus();
  }, []);

  return (
    <AccountNarrowPage>
      <AccountPageHeader title={t('emailChange.withdrawnTitle')} headingRef={headingRef} />
      <Card>
        <Notice tone="info" title={t('emailChange.failedNotice')}>
          <p>{t('emailChange.withdrawnBody')}</p>
        </Notice>
        <ul className="ca-links">
          <li>
            <Link to={session.isSignedIn ? '/account/security' : '/account/sign-in'}>
              {session.isSignedIn ? t('emailChange.backToSecurity') : t('common.backToSignIn')}
            </Link>
          </li>
        </ul>
      </Card>
    </AccountNarrowPage>
  );
}
