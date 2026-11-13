/**
 * A staff member changes their own password (RC-UAT-21 Phase B, DEC-0231).
 *
 * Reached from the account menu. The current password is required; the new one is at least
 * twelve characters, typed twice, and different from the current one. This session stays
 * signed in; every other session of the user is signed out by the server. The server's
 * refusal is shown beside the field it names.
 */

import { useState } from 'react';
import { PageHeader } from '../../components/layout/AppShell.jsx';
import { Banner, Button, Card, Field, TextInput } from '../../components/ui/index.jsx';
import { useT } from '../../i18n/index.jsx';
import { authApi } from '../../api/endpoints.js';

const MIN_LENGTH = 12;

export function ChangePasswordPage() {
  const t = useT();
  const [current, setCurrent] = useState('');
  const [next, setNext] = useState('');
  const [again, setAgain] = useState('');
  const [errors, setErrors] = useState({});
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);

  async function onSubmit(event) {
    event.preventDefault();
    const found = {};
    if (!current) found.current_password = t('staffPassword.required');
    if (next.length < MIN_LENGTH) found.password = t('staffPassword.tooShort');
    if (next !== again) found.new_password_confirmation = t('staffPassword.mismatch');
    setErrors(found);
    setDone(false);
    if (Object.keys(found).length) return;
    setBusy(true);
    try {
      await authApi.changePassword({
        current_password: current,
        new_password: next,
        new_password_confirmation: again,
      });
      setCurrent('');
      setNext('');
      setAgain('');
      setDone(true);
    } catch (error) {
      const field = error?.field;
      setErrors(
        ['current_password', 'password', 'new_password_confirmation'].includes(field)
          ? { [field]: error.message }
          : { form: error?.message },
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <PageHeader title={t('staffPassword.title')} subtitle={t('staffPassword.intro')} />
      <Card>
        {done && <Banner tone="success">{t('staffPassword.done')}</Banner>}
        {errors.form && <Banner tone="danger">{errors.form}</Banner>}
        <form className="stack" onSubmit={onSubmit} noValidate>
          <Field label={t('staffPassword.current')} required error={errors.current_password}>
            {(fieldProps) => (
              <TextInput
                {...fieldProps}
                type="password"
                autoComplete="current-password"
                value={current}
                onChange={(event) => setCurrent(event.target.value)}
              />
            )}
          </Field>
          <Field
            label={t('staffPassword.next')}
            hint={t('staffPassword.nextHint')}
            required
            error={errors.password}
          >
            {(fieldProps) => (
              <TextInput
                {...fieldProps}
                type="password"
                autoComplete="new-password"
                value={next}
                onChange={(event) => setNext(event.target.value)}
              />
            )}
          </Field>
          <Field
            label={t('staffPassword.again')}
            required
            error={errors.new_password_confirmation}
          >
            {(fieldProps) => (
              <TextInput
                {...fieldProps}
                type="password"
                autoComplete="new-password"
                value={again}
                onChange={(event) => setAgain(event.target.value)}
              />
            )}
          </Field>
          <div className="row-wrap">
            <Button type="submit" variant="primary" loading={busy} disabled={busy}>
              {t('staffPassword.submit')}
            </Button>
          </div>
        </form>
      </Card>
    </>
  );
}
