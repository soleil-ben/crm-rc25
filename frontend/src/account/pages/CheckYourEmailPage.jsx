/**
 * "Check your email."
 *
 * The one confirmation for registration, for a resend, and for a password-reset request.
 * **The same words for every outcome**, because the server gives the same response for
 * every outcome: an address that was registered, one that already had an account, one
 * that is suppressed, and one a rate limit refused all arrive here reading the same page
 * (T-02, `STATE_MACHINES.md` §2).
 *
 * It therefore says nothing about *which* message was sent, nothing about whether an
 * account exists, and nothing about how long the link lasts for a case that may not have
 * produced a link at all.
 *
 * `location.state.from` only changes the follow-up links — never the message — so a
 * person who came from the reset form is offered the reset form again rather than the
 * registration form.
 */

import { Link, useLocation } from 'react-router-dom';
import { AccountNarrowPage, AccountPageHeader } from '../AccountLayout.jsx';
import { Card, Notice } from '../components.jsx';
import { useAccountT } from '../i18n.jsx';

export function CheckYourEmailPage() {
  const location = useLocation();
  const from = location.state?.from;
  const t = useAccountT();

  return (
    <AccountNarrowPage>
      <AccountPageHeader title={t('checkEmail.title')} />
      <Card>
        <Notice tone="success" title={t('checkEmail.notice')}>
          <p>{t('checkEmail.follow')}</p>
        </Notice>

        <p>{t('checkEmail.nothing')}</p>

        <ul className="ca-links">
          {from === 'reset' ? (
            <li>
              <Link to="/account/forgot-password">{t('checkEmail.anotherReset')}</Link>
            </li>
          ) : (
            <li>
              <Link to="/account/verification/resend">{t('common.resendConfirmation')}</Link>
            </li>
          )}
          <li>
            <Link to="/account/sign-in">{t('common.backToSignIn')}</Link>
          </li>
        </ul>
      </Card>
    </AccountNarrowPage>
  );
}
