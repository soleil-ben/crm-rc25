/**
 * The password-reset landing page.
 *
 * The token handling is `VerifyEmailPage`'s, for the same reasons, with one difference:
 * the token is not redeemed on arrival. A reset needs a new password, so the token has to
 * survive until the form is submitted. It is held in a **ref** for that time — never in
 * state that renders, never in `localStorage` or `sessionStorage`. The link carries it in
 * the URL fragment (`#token=`, CA-SEC-07), which `main.jsx` has already moved into memory
 * and stripped from the address bar before React mounted; a `?token=` link from before
 * the change is stripped here on first render, with `replace`, before the person starts
 * typing.
 *
 * **A completed reset revokes every session for the identity** and does not sign the
 * person in. The server clears the cookies and says so; turning a reset into a session
 * would make the mailbox the credential.
 *
 * Unknown, expired, consumed and replayed tokens are one response with one sentence.
 *
 * **A short password or a mismatch is reported beside its own box** (UAT round 8), with
 * the server's sentences, before anything is sent; the server refuses both as well and its
 * answer lands in the same place. Only a link problem is reported for the whole form.
 */

import { useEffect, useRef, useState } from 'react';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import { AccountNarrowPage, AccountPageHeader } from '../AccountLayout.jsx';
import { Button, Card, Field, Notice, TextInput } from '../components.jsx';
import { AccountApiError, accountApi } from '../accountApi.js';
import { useAccountSession } from '../AccountSession.jsx';
import { locationCarriesToken, takeLinkToken, tokenFromLocation } from '../linkToken.js';
import { useAccountErrorText, useAccountT } from '../i18n.jsx';

const MIN_PASSWORD_LENGTH = 12;

/** The fields a server refusal can be shown beside. */
const INLINE_FIELDS = ['password', 'password_confirmation'];

export function ResetPasswordPage() {
  const location = useLocation();
  const navigate = useNavigate();
  const session = useAccountSession();
  const tokenRef = useRef(null);
  const headingRef = useRef(null);
  const [password, setPassword] = useState('');
  const [confirmation, setConfirmation] = useState('');
  const [errors, setErrors] = useState({});
  const [done, setDone] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const t = useAccountT();
  const errorText = useAccountErrorText();
  // A server refusal is kept as the error and worded at render; a local check is a sentence.
  const fieldMessage = (field) =>
    ({
      password: t('common.useAtLeast', { count: MIN_PASSWORD_LENGTH }),
      password_confirmation: t('common.passwordMismatch'),
    })[field] ?? null;
  const shown = Object.fromEntries(
    Object.entries(errors).map(([key, value]) => [
      key,
      typeof value === 'string' ? value : errorText(value, { fieldMessage }),
    ]),
  );

  // Runs on every location change, not once: a second link opened while this page is
  // already showing differs only by its fragment, which the browser treats as a
  // same-document navigation -- `main.jsx` does not run again, and the token arrives
  // here through the router's location instead. A fresh token starts a fresh form.
  useEffect(() => {
    const token = tokenFromLocation(location) ?? takeLinkToken();
    if (token) {
      tokenRef.current = token;
      setDone(false);
      setErrors({});
    }
    if (locationCarriesToken(location)) {
      navigate('/account/reset-password', { replace: true });
    }
  }, [navigate, location]);

  useEffect(() => {
    if (done) headingRef.current?.focus();
  }, [done]);

  async function onSubmit(event) {
    event.preventDefault();

    const found = {};
    if (password.length < MIN_PASSWORD_LENGTH) {
      found.password = t('common.useAtLeast', { count: MIN_PASSWORD_LENGTH });
    }
    if (!confirmation) {
      found.password_confirmation = t('common.passwordMissing');
    } else if (password !== confirmation) {
      found.password_confirmation = t('common.passwordMismatch');
    }
    setErrors(found);
    if (Object.keys(found).length > 0) return;

    const token = tokenRef.current;
    if (!token) {
      setErrors({ form: t('common.linkInvalid') });
      return;
    }

    setSubmitting(true);
    try {
      await accountApi.resetPassword(token, password, confirmation);
      // Spent, whatever happened next. It is single-use server-side too; dropping it here
      // means a resubmit cannot replay it from this page.
      tokenRef.current = null;
      setPassword('');
      setConfirmation('');
      setDone(true);
      // The server cleared the session cookies. Re-read `/account/me` so the shell agrees
      // with the browser rather than showing navigation for a session that is gone.
      session.refresh();
    } catch (requestError) {
      const field = requestError instanceof AccountApiError ? requestError.field : null;
      setErrors(
        INLINE_FIELDS.includes(field)
          ? { [field]: requestError }
          : { form: requestError },
      );
    } finally {
      setSubmitting(false);
    }
  }

  if (done) {
    return (
      <AccountNarrowPage>
        <AccountPageHeader title={t('reset.doneTitle')} headingRef={headingRef} />
        <Card>
          <Notice tone="success" title={t('reset.doneNotice')}>
            <p>{t('reset.doneBody')}</p>
          </Notice>
          <ul className="ca-links">
            <li>
              <Link to="/account/sign-in">{t('common.signIn')}</Link>
            </li>
          </ul>
        </Card>
      </AccountNarrowPage>
    );
  }

  return (
    <AccountNarrowPage>
      <AccountPageHeader
        title={t('reset.title')}
        intro={t('reset.intro')}
      />
      <Card>
        {shown.form ? (
          <Notice tone="error" title={t('reset.failed')}>
            <p>{shown.form}</p>
          </Notice>
        ) : null}

        <form className="ca-form" onSubmit={onSubmit} noValidate>
          <Field
            label={t('reset.newPassword')}
            required
            fieldKey="password"
            error={shown.password}
            hint={t('reset.newPasswordHint', { count: MIN_PASSWORD_LENGTH })}
          >
            {({ id, describedBy, invalid }) => (
              <TextInput
                id={id}
                describedBy={describedBy}
                invalid={invalid}
                type="password"
                name="new-password"
                autoComplete="new-password"
                minLength={MIN_PASSWORD_LENGTH}
                maxLength={200}
                value={password}
                onChange={(event) => setPassword(event.target.value)}
              />
            )}
          </Field>

          <Field
            label={t('reset.newPasswordAgain')}
            required
            fieldKey="password_confirmation"
            error={shown.password_confirmation}
          >
            {({ id, describedBy, invalid }) => (
              <TextInput
                id={id}
                describedBy={describedBy}
                invalid={invalid}
                type="password"
                name="confirm-password"
                autoComplete="new-password"
                maxLength={200}
                value={confirmation}
                onChange={(event) => setConfirmation(event.target.value)}
              />
            )}
          </Field>

          <div className="ca-form__actions">
            <Button type="submit" busy={submitting}>
              {t('reset.submit')}
            </Button>
          </div>
        </form>

        <ul className="ca-links">
          <li>
            <Link to="/account/forgot-password">{t('reset.newLink')}</Link>
          </li>
        </ul>
      </Card>
    </AccountNarrowPage>
  );
}
