/**
 * Sign in.
 *
 * **One failure message, whatever happened.** A wrong password, an unknown address, an
 * unverified account, a suspended one, a rejected one and a deactivated one all produce
 * the same sentence from the server (`STATE_MACHINES.md` §7), and this screen renders the
 * server's sentence rather than deciding anything from the status code. A screen that
 * said "check your password" for one and "contact us" for another would undo the whole
 * arrangement from the client side.
 *
 * Password managers work here: a real `<form>`, `autoComplete` on both fields, no paste
 * handler and no `onCopy` blocking. Blocking paste is a measure that makes long random
 * passwords harder to use and short memorable ones easier, which is backwards.
 */

import { useEffect, useRef, useState } from 'react';
import { Link, Navigate, useLocation, useNavigate } from 'react-router-dom';
import { AccountNarrowPage, AccountPageHeader } from '../AccountLayout.jsx';
import { Button, Card, Field, Loading, Notice, TextInput } from '../components.jsx';
import { destinationForSession, useAccountSession } from '../AccountSession.jsx';
import { useAccountErrorText, useAccountT } from '../i18n.jsx';

export function SignInPage() {
  const session = useAccountSession();
  const navigate = useNavigate();
  const location = useLocation();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [failure, setFailure] = useState(null);
  const failureRef = useRef(null);
  const t = useAccountT();
  const errorText = useAccountErrorText();

  // Focus moves to the failure when one appears, so a keyboard or screen-reader user is
  // told the attempt failed instead of finding the form apparently unchanged.
  useEffect(() => {
    if (failure) failureRef.current?.focus();
  }, [failure]);

  if (session.isResolving) {
    return (
      <AccountNarrowPage>
        <Loading label={t('common.checkingAccount')} />
      </AccountNarrowPage>
    );
  }

  // Already signed in: go where this session belongs rather than offering a second
  // sign-in, which would rotate a perfectly good session for nothing.
  if (session.isSignedIn) {
    return <Navigate to={destinationForSession(session)} replace />;
  }

  async function onSubmit(event) {
    event.preventDefault();
    setFailure(null);
    try {
      await session.signIn({ email, password });
      // `from` is a path this application put into history, never a value read from the
      // query string, so it cannot send somebody off-site. It is still checked for shape.
      const requested = location.state?.from;
      const target = typeof requested === 'string' && requested.startsWith('/account/')
        ? requested
        : '/account';
      navigate(target, { replace: true });
    } catch (error) {
      // The error itself, so the sentence follows the language. Generic on purpose.
      setFailure(error);
      // The password field is cleared and the email is not. Retyping an address after a
      // typo in a password is the annoyance that makes people paste from a note.
      setPassword('');
    }
  }

  return (
    <AccountNarrowPage>
      <AccountPageHeader
        title={t('common.signIn')}
        intro={t('signIn.intro')}
      />
      <Card>
        {failure ? (
          <div tabIndex={-1} ref={failureRef}>
            <Notice tone="error" title={t('signIn.failed')}>
              <p>{errorText(failure, { context: 'signIn' })}</p>
            </Notice>
          </div>
        ) : null}

        <form className="ca-form" onSubmit={onSubmit} noValidate>
          <Field label={t('common.emailAddress')} required>
            {({ id, describedBy, invalid }) => (
              <TextInput
                id={id}
                describedBy={describedBy}
                invalid={invalid}
                type="email"
                name="email"
                autoComplete="username"
                inputMode="email"
                maxLength={320}
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                required
              />
            )}
          </Field>

          <Field label={t('common.password')} required>
            {({ id, describedBy, invalid }) => (
              <TextInput
                id={id}
                describedBy={describedBy}
                invalid={invalid}
                type="password"
                name="password"
                autoComplete="current-password"
                maxLength={200}
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                required
              />
            )}
          </Field>

          <div className="ca-form__actions">
            <Button type="submit" busy={session.isSigningIn}>
              {t('common.signIn')}
            </Button>
          </div>
        </form>

        <ul className="ca-links">
          <li>
            <Link to="/account/forgot-password">{t('signIn.forgot')}</Link>
          </li>
          <li>
            <Link to="/account/verification/resend">{t('common.resendConfirmation')}</Link>
          </li>
          <li>
            <Link to="/account/register">{t('signIn.create')}</Link>
          </li>
        </ul>
      </Card>
    </AccountNarrowPage>
  );
}
