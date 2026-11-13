/**
 * The staff portal: providers, session gate, login, and the application shell.
 *
 * Split into its own module so `App.jsx` can load it lazily. Everything the staff portal
 * needs — the session context, the staff API client, the full route table, and every
 * feature screen it pulls in behind that — is reachable only from here, so a bundler can
 * put the whole portal in a chunk a public visitor never downloads.
 */

import { I18nProvider, useT } from '../i18n/index.jsx';
import { SessionProvider, useSession } from './SessionContext.jsx';
import { LoginPage } from '../features/auth/LoginPage.jsx';
import { AppRoutes } from './routes.jsx';

function SessionGate() {
  const t = useT();
  const { isLoading, isAuthenticated } = useSession();

  if (isLoading) {
    return (
      <div className="app-boot" role="status">
        <span className="btn__spinner" aria-hidden="true" />
        <span>{t('states.loading')}</span>
      </div>
    );
  }

  if (!isAuthenticated) return <LoginPage />;
  return <AppRoutes />;
}

/**
 * Mounted only for non-public routes, so `SessionProvider` — and the `/auth/me` request
 * it makes on mount — never runs on a customer's page.
 */
export default function StaffApp() {
  return (
    <I18nProvider>
      <SessionProvider>
        <SessionGate />
      </SessionProvider>
    </I18nProvider>
  );
}
