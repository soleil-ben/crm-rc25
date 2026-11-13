/**
 * "Forgotten your password?"
 *
 * One field, one outcome. The server returns the same body for a known address and an
 * unknown one (AC-CA-2.7), and this screen navigates to the same confirmation either way
 * — including when a rate limit refused the work, because a visible throttle on this form
 * would separate "an address somebody keeps trying" from "an address nobody has".
 *
 * That includes the per-connection 429 (UAT round 4): the server answers it with the
 * ordinary recovery sentence and this screen goes to the same confirmation, exactly as the
 * registration form does since UAT round 3. No screen on this path says "too many".
 */

import { useRef, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { AccountNarrowPage, AccountPageHeader } from '../AccountLayout.jsx';
import { Button, Card, Field, Notice, TextInput } from '../components.jsx';
import { AccountApiError, accountApi } from '../accountApi.js';
import { useAccountErrorText, useAccountT } from '../i18n.jsx';

/** The one field this form shows, in the screen's language. */
const EMAIL_FIELD_KEYS = { email: 'register.invalidEmail' };

export function ForgotPasswordPage() {
  const navigate = useNavigate();
  const [email, setEmail] = useState('');
  const [error, setError] = useState(null);
  const [submitting, setSubmitting] = useState(false);
  const noticeRef = useRef(null);
  const t = useAccountT();
  const errorText = useAccountErrorText();
  const emailFieldMessage = (field) => (EMAIL_FIELD_KEYS[field] ? t(EMAIL_FIELD_KEYS[field]) : null);

  async function onSubmit(event) {
    event.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await accountApi.forgotPassword(email.trim());
      navigate('/account/check-your-email', { replace: true, state: { from: 'reset' } });
    } catch (requestError) {
      if (requestError instanceof AccountApiError && requestError.isRateLimited) {
        // A refused request reads exactly as an accepted one: same destination, same words.
        navigate('/account/check-your-email', { replace: true, state: { from: 'reset' } });
        return;
      }
      setError(requestError);
      noticeRef.current?.focus();
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <AccountNarrowPage>
      <AccountPageHeader
        title={t('forgot.title')}
        intro={t('forgot.intro')}
      />
      <Card>
        <div tabIndex={-1} ref={noticeRef}>
          {error ? (
            <Notice tone="error" title={t('common.couldNotSend')}>
              <p>{errorText(error, { fieldMessage: emailFieldMessage })}</p>
            </Notice>
          ) : null}
        </div>

        <form className="ca-form" onSubmit={onSubmit} noValidate>
          <Field label={t('common.emailAddress')} required>
            {({ id, describedBy }) => (
              <TextInput
                id={id}
                describedBy={describedBy}
                type="email"
                name="email"
                autoComplete="username"
                inputMode="email"
                maxLength={320}
                value={email}
                onChange={(event) => setEmail(event.target.value)}
              />
            )}
          </Field>
          <div className="ca-form__actions">
            <Button type="submit" busy={submitting}>
              {t('forgot.submit')}
            </Button>
          </div>
        </form>

        <ul className="ca-links">
          <li>
            <Link to="/account/sign-in">{t('common.backToSignIn')}</Link>
          </li>
        </ul>
      </Card>
    </AccountNarrowPage>
  );
}
