/**
 * Sign-in and security (RC-UAT-21 Phase B; RC-UAT-25 item 2): change the password, read the
 * sign-in email.
 *
 * Open to any signed-in account -- waiting for review or active -- because a password belongs
 * to the account, not to the linked customer.
 *
 * **Password.** The current password is asked for first; the new one is typed twice and must
 * be at least twelve characters. On success this browser stays signed in (on a new session)
 * and every other signed-in browser is signed out; an email confirms the change.
 *
 * **Email.** Shown, not changed: since RC-UAT-25 (Ben, 2026-10-25) only Solaris Express
 * changes a sign-in email, from the staff account screen. The page says so; the server refuses
 * the old change request and closes any change still pending when this page is read.
 */

import { useEffect, useRef, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { AccountPageHeader } from '../AccountLayout.jsx';
import { AccountApiError, accountApi } from '../accountApi.js';
import { Button, Card, DetailRow, Field, Loading, Notice, TextInput } from '../components.jsx';
import { useAccountErrorText, useAccountT, useServerSentence } from '../i18n.jsx';

const SECURITY_KEY = ['account', 'security'];

/**
 * The server's English refusal sentences, turned into this page's keys so a Vietnamese
 * screen says the same thing in Vietnamese (the server's English is never shown there).
 */
const SERVER_SENTENCES = [
  [/^The current password is not correct/, 'security.currentWrong'],
  [/^Use at least/, 'security.tooShort'],
  [/^Password cannot start or end with a space/, 'security.spaces'],
  [/^Choose a less common password/, 'security.common'],
  [/^Choose a new password that is different/, 'security.samePassword'],
  [/^The two passwords do not match/, 'common.passwordMismatch'],
  [/^Type the password again/, 'common.passwordMissing'],
];

function useFieldMessage(min) {
  const t = useAccountT();
  return (error) => () => {
    const message = error instanceof AccountApiError ? error.message || '' : '';
    const hit = SERVER_SENTENCES.find(([pattern]) => pattern.test(message));
    if (hit) return t(hit[1], { count: min });
    return null;
  };
}

function PasswordCard({ min }) {
  const t = useAccountT();
  const errorText = useAccountErrorText();
  const serverSentence = useServerSentence();
  const fieldMessageFor = useFieldMessage(min);
  const [current, setCurrent] = useState('');
  const [next, setNext] = useState('');
  const [again, setAgain] = useState('');
  const [errors, setErrors] = useState({});
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(null);
  const doneRef = useRef(null);

  useEffect(() => {
    if (done) doneRef.current?.focus();
  }, [done]);

  const shown = Object.fromEntries(
    Object.entries(errors).map(([key, value]) => [
      key,
      typeof value === 'string' ? value : errorText(value, { fieldMessage: fieldMessageFor(value) }),
    ]),
  );

  async function onSubmit(event) {
    event.preventDefault();
    const found = {};
    if (!current) found.current_password = t('security.currentRequired');
    if (next.length < min) found.password = t('security.tooShort', { count: min });
    if (!again) found.password_confirmation = t('common.passwordMissing');
    else if (next !== again) found.password_confirmation = t('common.passwordMismatch');
    setErrors(found);
    setDone(null);
    if (Object.keys(found).length) return;
    setBusy(true);
    try {
      const response = await accountApi.changePassword(current, next, again);
      setCurrent('');
      setNext('');
      setAgain('');
      setDone(response?.message ?? '');
    } catch (error) {
      const field = error instanceof AccountApiError ? error.field : null;
      setErrors(
        ['current_password', 'password', 'password_confirmation'].includes(field)
          ? { [field]: error }
          : { form: error },
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card title={t('security.passwordTitle')}>
      {done !== null ? (
        <div tabIndex={-1} ref={doneRef}>
          <Notice tone="success" title={t('security.passwordChanged')}>
            <p>{serverSentence(done || null, 'security.passwordChangedBody')}</p>
          </Notice>
        </div>
      ) : null}
      {shown.form ? (
        <Notice tone="error" title={t('common.couldNotSave')}>
          <p>{shown.form}</p>
        </Notice>
      ) : null}
      <form className="ca-form" onSubmit={onSubmit} noValidate>
        <Field
          label={t('security.currentPassword')}
          required
          fieldKey="current_password"
          error={shown.current_password}
        >
          {({ id, describedBy, invalid }) => (
            <TextInput
              id={id}
              describedBy={describedBy}
              invalid={invalid}
              type="password"
              name="current-password"
              autoComplete="current-password"
              maxLength={200}
              value={current}
              onChange={(event) => setCurrent(event.target.value)}
            />
          )}
        </Field>
        <Field
          label={t('security.newPassword')}
          required
          fieldKey="password"
          error={shown.password}
          hint={t('security.newPasswordHint', { count: min })}
        >
          {({ id, describedBy, invalid }) => (
            <TextInput
              id={id}
              describedBy={describedBy}
              invalid={invalid}
              type="password"
              name="new-password"
              autoComplete="new-password"
              maxLength={200}
              value={next}
              onChange={(event) => setNext(event.target.value)}
            />
          )}
        </Field>
        <Field
          label={t('security.newPasswordAgain')}
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
              value={again}
              onChange={(event) => setAgain(event.target.value)}
            />
          )}
        </Field>
        <div className="ca-form__actions">
          <Button type="submit" busy={busy}>
            {t('security.changePassword')}
          </Button>
        </div>
      </form>
    </Card>
  );
}

/**
 * The sign-in email, read only (RC-UAT-25 item 2, Ben 2026-10-25): only Solaris Express
 * changes it, on the staff account screen. No form, no pending change, nothing to cancel.
 */
function EmailCard({ data }) {
  const t = useAccountT();
  return (
    <Card title={t('security.emailReadOnlyTitle')}>
      <dl className="ca-detail-grid">
        <DetailRow label={t('security.currentEmail')}>{data.email}</DetailRow>
      </dl>
      <p className="ca-meta">{t('security.emailByStaff')}</p>
    </Card>
  );
}

export function SecurityPage() {
  const t = useAccountT();
  const errorText = useAccountErrorText();
  const headingRef = useRef(null);
  const security = useQuery({
    queryKey: SECURITY_KEY,
    queryFn: ({ signal }) => accountApi.security({ signal }),
  });

  const settled = !security.isPending;
  useEffect(() => {
    if (settled) headingRef.current?.focus();
  }, [settled]);

  if (security.isPending) return <Loading label={t('security.loading')} />;
  if (security.error) {
    return (
      <div className="ca-wide">
        <AccountPageHeader title={t('security.title')} headingRef={headingRef} />
        <Card>
          <Notice tone="error" title={t('security.loadFailed')}>
            <p>{errorText(security.error)}</p>
          </Notice>
        </Card>
      </div>
    );
  }
  const min = security.data.min_password_length || 12;
  return (
    <div className="ca-wide">
      <AccountPageHeader title={t('security.title')} headingRef={headingRef} intro={t('security.intro')} />
      <PasswordCard min={min} />
      <EmailCard data={security.data} />
    </div>
  );
}
