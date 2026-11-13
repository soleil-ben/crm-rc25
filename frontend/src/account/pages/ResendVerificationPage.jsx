/**
 * "Send the confirmation email again."
 *
 * The same shape as the forgot-password form and for the same reason: one field, one
 * outcome. That includes the per-connection 429 (owner decision, 2026-10-15): the server
 * answers it with the ordinary sentence and this screen goes to the same confirmation, as
 * registration and reset do. No screen on this path says "too many".
 *
 * Asking for a new confirmation link **invalidates the previous one** (T-05,
 * `STATE_MACHINES.md` §5). That is said on the page, because somebody with two messages
 * open will otherwise click the older link and read "no longer valid" as a fault.
 */

import { useRef, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { AccountNarrowPage, AccountPageHeader } from '../AccountLayout.jsx';
import { Button, Card, Field, Notice, TextInput } from '../components.jsx';
import { AccountApiError, accountApi } from '../accountApi.js';
import { useAccountErrorText, useAccountT } from '../i18n.jsx';

/** The one field this form shows, in the screen's language. */
const EMAIL_FIELD_KEYS = { email: 'register.invalidEmail' };

export function ResendVerificationPage() {
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
      await accountApi.resendVerification(email.trim());
      navigate('/account/check-your-email', { replace: true, state: { from: 'resend' } });
    } catch (requestError) {
      if (requestError instanceof AccountApiError && requestError.isRateLimited) {
        // A refused request reads exactly as an accepted one: same destination, same words.
        navigate('/account/check-your-email', { replace: true, state: { from: 'resend' } });
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
        title={t('common.resendConfirmation')}
        intro={t('resend.intro')}
      />
      <Card>
        <div tabIndex={-1} ref={noticeRef}>
          {error ? (
            <Notice tone="error" title={t('common.couldNotSend')}>
              <p>{errorText(error, { fieldMessage: emailFieldMessage })}</p>
            </Notice>
          ) : null}
        </div>

        <Notice tone="info" title={t('resend.cancelsTitle')}>
          <p>{t('resend.cancelsBody')}</p>
        </Notice>

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
              {t('resend.submit')}
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
