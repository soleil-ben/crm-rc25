/** Staff sign-in. A separate minimal layout from the application shell. */

import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useT } from '../../i18n/index.jsx';
import { landingPathFor, useSession } from '../../app/SessionContext.jsx';
import { Banner, Button, Card, Field, TextInput } from '../../components/ui/index.jsx';
import './login.css';

export function LoginPage() {
  const t = useT();
  const navigate = useNavigate();
  const { login, isLoggingIn, loginError } = useSession();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');

  async function onSubmit(event) {
    event.preventDefault();
    try {
      const result = await login({ email, password });
      // The sign-in form renders at whatever URL the browser was on -- the previous
      // person's last page, after a sign-out, or a deep link somebody pasted. Neither is
      // this person's. They land on their own first screen, and `replace` keeps the URL
      // they arrived on out of the history (fix pack item 11).
      navigate(landingPathFor(result?.permissions), { replace: true });
    } catch {
      // The error is surfaced from the mutation state below; nothing to do here.
    }
  }

  return (
    <div className="login">
      <div className="login__panel">
        <div className="login__brand">
          {t('brand.nameFirst')} <span className="login__brand-accent">{t('brand.nameSecond')}</span>
        </div>
        <Card title={t('auth.title')}>
          <form className="stack" onSubmit={onSubmit} noValidate>
            <p className="meta">{t('auth.subtitle')}</p>

            {loginError && (
              <Banner tone="danger" title={t('states.errorTitle')}>
                {loginError.message}
                {loginError.isRateLimited && loginError.detail?.retry_after_seconds
                  ? ` Retry in about ${loginError.detail.retry_after_seconds} seconds.`
                  : ''}
              </Banner>
            )}

            <Field label={t('auth.email')} required>
              {(props) => (
                <TextInput
                  {...props}
                  type="email"
                  name="email"
                  autoComplete="username"
                  value={email}
                  onChange={(event) => setEmail(event.target.value)}
                  required
                />
              )}
            </Field>

            <Field label={t('auth.password')} required>
              {(props) => (
                <TextInput
                  {...props}
                  type="password"
                  name="password"
                  autoComplete="current-password"
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                  required
                />
              )}
            </Field>

            <Button type="submit" variant="primary" full loading={isLoggingIn}>
              {t('auth.signIn')}
            </Button>
          </form>
        </Card>
        <p className="meta login__foot">{t('brand.legalEntity')}</p>
      </div>
    </div>
  );
}
