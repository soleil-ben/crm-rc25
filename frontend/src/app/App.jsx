/**
 * Application root.
 *
 * Two shells share one build and nothing else.
 *
 * `/track` and `/track/:reference` render the **public** tracking application. They sit
 * above the staff providers on purpose: a customer opening a QR code must not have
 * `/auth/me` requested on their behalf, must not see the staff login screen flash, and
 * must not receive the staff shell's chrome. Putting the public routes here, before
 * `SessionProvider` exists, makes that structural rather than a matter of remembering to
 * check a flag (`Design.md` section 14).
 *
 * **Both shells are lazily loaded, and the split is the point.** Without it, a customer
 * who scanned a parcel label downloaded the entire staff portal — every feature screen,
 * the booking workflow, the label drawer — to look at one tracking result. None of it
 * would run and none of it carries data, but shipping the internal application's
 * structure to anyone who scans a label is not something to do by accident. Now the
 * public chunk contains the public shell and the staff chunk is never requested on a
 * public route.
 */

import { lazy, Suspense } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { BrowserRouter, Route, Routes } from 'react-router-dom';
import { shouldRetryQuery } from '../api/retry.js';
import '../styles/fonts.css';
import '../styles/tokens.css';
import '../styles/base.css';

const PublicApp = lazy(() =>
  import('../public/PublicApp.jsx').then((module) => ({ default: module.PublicApp })),
);
const AccountApp = lazy(() =>
  import('../account/AccountApp.jsx').then((module) => ({ default: module.AccountApp })),
);
const StaffApp = lazy(() => import('./StaffApp.jsx'));

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: shouldRetryQuery,
      refetchOnWindowFocus: false,
      staleTime: 30_000,
    },
  },
});

/**
 * The fallback shown while a shell's chunk loads.
 *
 * Deliberately unbranded and almost empty: on a fast connection it is never seen, and on
 * a slow one a bare status line is better than a half-drawn shell that shifts as the real
 * one arrives.
 */
function ShellLoading() {
  return <div className="app-boot" role="status" aria-live="polite" />;
}

export function App() {
  return (
    <QueryClientProvider client={queryClient}>
      {/* React Router v7 behaviour opted into early, so the eventual major upgrade changes
          nothing here. `v7_relativeSplatPath` resolves relative links inside the
          `/track/*` and `/account/*` splat routes against the full matched path; no shell
          uses a relative link, so nothing observable changes.

          `v7_startTransition` is deliberately *not* set. It wraps every navigation in
          `React.startTransition`, and `ReportsPage` drives its route-filter checkboxes
          from `useSearchParams` -- so a click would update the URL in a deferred
          transition and the controlled checkbox would not flip in the same tick. The
          Playwright report-filter test caught exactly that (`locator.check: Clicking the
          checkbox did not change its state`), and it is the caveat React Router's own
          upgrade guide gives for controlled inputs bound to the URL. Turning it on means
          first moving those inputs to local state, which is a behaviour change for a
          later phase, not a flag. `tests/utils.jsx` mirrors this. */}
      <BrowserRouter future={{ v7_relativeSplatPath: true }}>
        <Suspense fallback={<ShellLoading />}>
          <Routes>
            {/* `/track/*` is handled entirely by the public application, which brings its
                own query client and its own bilingual i18n provider. */}
            <Route path="/track/*" element={<PublicApp />} />
            {/* `/account/*` is the Customer Account, and it sits here for the same reason
                Public Tracking does: above `SessionProvider`, so a signed-in customer's
                page never issues `/auth/me`, never flashes the staff sign-in screen, and
                never downloads the staff chunk. It brings its own query client, its own
                session provider, its own API client and its own CSRF realm; it shares the
                design tokens and nothing else (`Design.md` §14a). */}
            <Route path="/account/*" element={<AccountApp />} />
            <Route path="*" element={<StaffApp />} />
          </Routes>
        </Suspense>
      </BrowserRouter>
    </QueryClientProvider>
  );
}
