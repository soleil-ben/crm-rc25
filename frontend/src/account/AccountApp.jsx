/**
 * The Customer Account application: its own providers, its own guard, its own routes.
 *
 * Mounted by `app/App.jsx` at `/account/*`, **above** the staff shell and beside the
 * public one, for the reason Public Tracking is mounted there: a customer's page must not
 * request `/auth/me`, must not flash the staff sign-in screen, and must not download the
 * staff portal to look at a parcel.
 *
 * Three providers, all of them this surface's own:
 *
 * * a `QueryClient` created **per mount**, so an authenticated shipment page cannot
 *   outlive the shell in a cache the rest of the build shares. `gcTime: 0` means a result
 *   is dropped when its component unmounts, which is what makes "sign out, press back"
 *   have nothing to render from;
 * * `AccountSessionProvider`, which resolves `/account/me` and holds no permissions
 *   because a customer identity has none;
 * * `AccountI18nProvider`, this surface's own languages: Vietnamese first, English as an
 *   option (OD-71, 2026-10-20, superseding OD-39's English-only release). See `i18n.jsx`
 *   for how the language is chosen; nothing about it is stored in the browser.
 */

import { Suspense, useEffect, useRef, useState } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { Navigate, Route, Routes, useLocation } from 'react-router-dom';
import { AccountApiError } from './accountApi.js';
import { AccountSessionProvider, destinationForSession, useAccountSession } from './AccountSession.jsx';
import { AccountLayout, AccountNarrowPage, AccountPageHeader } from './AccountLayout.jsx';
import { Card, Loading, Notice } from './components.jsx';
import { AccountI18nProvider, useAccountLocale, useAccountT } from './i18n.jsx';
import { RegisterPage } from './pages/RegisterPage.jsx';
import { SignInPage } from './pages/SignInPage.jsx';
import { CheckYourEmailPage } from './pages/CheckYourEmailPage.jsx';
import { VerifyEmailPage } from './pages/VerifyEmailPage.jsx';
import { ResendVerificationPage } from './pages/ResendVerificationPage.jsx';
import { ForgotPasswordPage } from './pages/ForgotPasswordPage.jsx';
import { ResetPasswordPage } from './pages/ResetPasswordPage.jsx';
import { PendingPage } from './pages/PendingPage.jsx';
import { RejectedPage } from './pages/RejectedPage.jsx';
import { UnavailablePage } from './pages/UnavailablePage.jsx';
import { ShipmentListPage } from './pages/ShipmentListPage.jsx';
import { ShipmentDetailPage } from './pages/ShipmentDetailPage.jsx';
import { ProfilePage } from './pages/ProfilePage.jsx';
import { NotificationsPage } from './pages/NotificationsPage.jsx';
import { QuotesPage } from './pages/QuotesPage.jsx';
import { QuoteDetailPage } from './pages/QuoteDetailPage.jsx';
import { SecurityPage } from './pages/SecurityPage.jsx';
import { ConfirmEmailChangePage } from './pages/ConfirmEmailChangePage.jsx';
import './account.css';

/**
 * A cache that keeps nothing between mounts and retries nothing it should not.
 *
 * `gcTime: 0` is the line that matters. An authenticated shipment list held in a cache is
 * protected content sitting in memory after the screen showing it has gone, and "press
 * back after signing out" is exactly the case where that becomes visible.
 */
export function createAccountQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: {
        // A 401, 403, 404 or 422 is a final answer. Retrying a 429 would make a
        // rate-limited screen consume the rest of its allowance arguing.
        retry: (failureCount, error) =>
          !(error instanceof AccountApiError) ? failureCount < 1 : false,
        gcTime: 0,
        staleTime: 0,
        refetchOnWindowFocus: false,
        refetchOnReconnect: false,
      },
      mutations: { retry: false },
    },
  });
}

/**
 * The route guard.
 *
 * Renders **nothing protected** until `/account/me` has answered. `isResolving` is true
 * from the first render until the first answer, whatever the answer is, so there is no
 * window in which a shipment list is on screen before authorization is known — the flash
 * the acceptance checklist names.
 *
 * A signed-in account in the wrong state is redirected, not shown an error: `pending`,
 * `rejected` and `unavailable` are screens, and landing on one of them by deep link and
 * by redirect should look the same.
 */
function RequireShipmentAccess({ children }) {
  const session = useAccountSession();
  const location = useLocation();
  const t = useAccountT();

  if (session.isResolving) {
    return (
      <AccountNarrowPage>
        <Loading label={t('common.checkingAccount')} />
      </AccountNarrowPage>
    );
  }

  if (session.isUnreachable) {
    return (
      <AccountNarrowPage>
        <AccountPageHeader title={t('app.unreachableTitle')} />
        <Card>
          <Notice tone="error" title={t('app.unreachableNotice')}>
            <p>{t('app.unreachableBody')}</p>
          </Notice>
        </Card>
      </AccountNarrowPage>
    );
  }

  if (!session.isSignedIn) {
    // `state.from` lets the sign-in screen send the person back to the deep link they
    // asked for. It carries a path this application produced, never one from a query
    // string, so it cannot be used to bounce somebody off-site.
    return <Navigate to="/account/sign-in" replace state={{ from: location.pathname }} />;
  }

  const destination = destinationForSession(session);
  if (destination !== '/account/shipments') {
    return <Navigate to={destination} replace />;
  }

  return children;
}

/**
 * RC-UAT-21 Phase B: a page any signed-in account may open -- waiting for review or active --
 * because what it changes (the password, the sign-in email) is the account's own. Renders
 * nothing protected until `/account/me` has answered, like `RequireShipmentAccess`.
 */
function RequireSignedIn({ children }) {
  const session = useAccountSession();
  const location = useLocation();
  const t = useAccountT();
  if (session.isResolving) {
    return (
      <AccountNarrowPage>
        <Loading label={t('common.checkingAccount')} />
      </AccountNarrowPage>
    );
  }
  if (!session.isSignedIn) {
    return <Navigate to="/account/sign-in" replace state={{ from: location.pathname }} />;
  }
  return children;
}

/**
 * `/account` itself. Sends a visitor to the screen their own state calls for.
 *
 * It is a redirect rather than a page because "the account home" for a pending applicant
 * and for an active customer are two different screens, and a third screen that explains
 * which one you are about to see helps nobody.
 */
function AccountIndex() {
  const session = useAccountSession();
  const t = useAccountT();
  if (session.isResolving) {
    return (
      <AccountNarrowPage>
        <Loading label={t('common.checkingAccount')} />
      </AccountNarrowPage>
    );
  }
  return <Navigate to={destinationForSession(session)} replace />;
}

/**
 * Anything under `/account` that is not a route.
 *
 * Inside the Customer Account shell, not the staff not-found page: a customer who
 * mistypes a URL must not be handed the internal application's chrome.
 */
function AccountNotFoundPage() {
  const t = useAccountT();
  return (
    <AccountNarrowPage>
      <AccountPageHeader title={t('app.notFoundTitle')} />
      <Card>
        <p>{t('app.notFoundBody')}</p>
      </Card>
    </AccountNarrowPage>
  );
}

/**
 * Paths are relative to the `/account/*` route that mounts this application, so `""` is
 * `/account` and `"sign-in"` is `/account/sign-in`.
 *
 * `verify-email`, `reset-password` and `sign-in` are **fixed** by what the backend
 * already puts in outbound mail (`customer_identity_service.verification_url`,
 * `password_reset_url`, `account_sign_in_url`). Renaming one of them silently breaks
 * every link already sent.
 */
export function AccountRoutes() {
  return (
    <AccountLayout>
      <Routes>
        <Route path="" element={<AccountIndex />} />
        <Route path="sign-in" element={<SignInPage />} />
        <Route path="register" element={<RegisterPage />} />
        <Route path="check-your-email" element={<CheckYourEmailPage />} />
        <Route path="verify-email" element={<VerifyEmailPage />} />
        <Route path="verification/resend" element={<ResendVerificationPage />} />
        <Route path="forgot-password" element={<ForgotPasswordPage />} />
        <Route path="reset-password" element={<ResetPasswordPage />} />
        <Route path="pending" element={<PendingPage />} />
        <Route path="rejected" element={<RejectedPage />} />
        <Route path="unavailable" element={<UnavailablePage />} />
        <Route
          path="shipments"
          element={
            <RequireShipmentAccess>
              <ShipmentListPage />
            </RequireShipmentAccess>
          }
        />
        <Route
          path="shipments/:reference"
          element={
            <RequireShipmentAccess>
              <ShipmentDetailPage />
            </RequireShipmentAccess>
          }
        />
        {/* Fix pack 2. Behind the same guard as the shipment screens: an active account
            with exactly one live link (CA-PRF-01 … CA-PRF-04). */}
        <Route
          path="profile"
          element={
            <RequireShipmentAccess>
              <ProfilePage />
            </RequireShipmentAccess>
          }
        />
        {/* OD-72: which milestones are emailed, and what was sent. Same guard. */}
        <Route
          path="notifications"
          element={
            <RequireShipmentAccess>
              <NotificationsPage />
            </RequireShipmentAccess>
          }
        />
        {/* Phase 13G (OD-77): quotes sent by Solaris Express, accepted or declined here.
            Same guard. `quotes` is fixed by the quote-sent email's link
            (`quote_offer_service.ACCOUNT_QUOTES_PATH`). */}
        <Route
          path="quotes"
          element={
            <RequireShipmentAccess>
              <QuotesPage />
            </RequireShipmentAccess>
          }
        />
        <Route
          path="quotes/:quoteId"
          element={
            <RequireShipmentAccess>
              <QuoteDetailPage />
            </RequireShipmentAccess>
          }
        />
        {/* RC-UAT-21 Phase B. Since RC-UAT-25 item 2 the security page only reads the sign-in
            email; `confirm-email-change` stays so a link sent before then lands on a page that
            says it no longer works (the server refuses it too). */}
        <Route
          path="security"
          element={
            <RequireSignedIn>
              <SecurityPage />
            </RequireSignedIn>
          }
        />
        <Route path="confirm-email-change" element={<ConfirmEmailChangePage />} />
        <Route path="*" element={<AccountNotFoundPage />} />
      </Routes>
    </AccountLayout>
  );
}

/**
 * Applies a signed-in identity's `preferred_language` to the screens (OD-71).
 *
 * Once per identity, not on every re-read of `/account/me`: a language saved on the
 * profile page changes how Solaris Express *contacts* the person, and flipping the screen
 * under them as they press Save would be a surprise. It takes effect on the next sign-in or
 * reload. A choice made with the header switch always wins (`adoptPreferredLocale` ignores
 * the preference once the switch has been used).
 */
function SessionLocaleBridge() {
  const session = useAccountSession();
  const { adoptPreferredLocale } = useAccountLocale();
  const adoptedFor = useRef(null);

  useEffect(() => {
    if (!session.isSignedIn) {
      adoptedFor.current = null;
      return;
    }
    if (adoptedFor.current === session.accountReference) return;
    adoptedFor.current = session.accountReference;
    adoptPreferredLocale(session.preferredLanguage);
  }, [session.isSignedIn, session.accountReference, session.preferredLanguage, adoptPreferredLocale]);

  return null;
}

export function AccountApp({ queryClient }) {
  // A fresh cache per mount, not a module singleton. A singleton would survive a
  // navigation out to another shell and back, and would hold an authenticated shipment
  // page for the lifetime of the tab.
  const [client] = useState(() => queryClient || createAccountQueryClient());

  return (
    <QueryClientProvider client={client}>
      <AccountI18nProvider>
        <AccountSessionProvider>
          <SessionLocaleBridge />
          <Suspense fallback={<div className="ca-boot" role="status" aria-live="polite" />}>
            <AccountRoutes />
          </Suspense>
        </AccountSessionProvider>
      </AccountI18nProvider>
    </QueryClientProvider>
  );
}

export default AccountApp;
