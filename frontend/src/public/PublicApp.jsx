/**
 * The public tracking application.
 *
 * Rendered **outside** the staff `SessionGate` and `AppShell`. That is the whole point of
 * this file: a customer opening a QR code must never see the staff login screen flash,
 * and the page must never call `/auth/me` (`Design.md` section 14).
 *
 * It brings its own providers rather than borrowing the staff ones:
 *
 * * its own `QueryClient`, so a tracking result is never retained in the cache the staff
 *   portal shares, and so `gcTime: 0` can apply here without changing staff behaviour;
 * * its own i18n provider, because this shell is bilingual from the first render while
 *   the staff portal is English-first.
 */

import { useState } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { Route, Routes } from 'react-router-dom';
import { PublicI18nProvider } from './i18n.jsx';
import { PublicLayout } from './PublicLayout.jsx';
import { TrackLandingPage } from './TrackLandingPage.jsx';
import { TrackResultPage } from './TrackResultPage.jsx';
import './public.css';

/**
 * A cache that keeps nothing.
 *
 * `gcTime: 0` means a result is discarded the moment its component unmounts, so a
 * tracking result cannot be read back later or rendered under a different reference.
 * `retry: false` means a not-found stays a not-found instead of being retried three
 * times against a rate-limited endpoint.
 */
export function createPublicQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
        gcTime: 0,
        staleTime: 0,
        refetchOnWindowFocus: false,
        refetchOnReconnect: false,
      },
    },
  });
}

/**
 * Paths are relative to the `/track/*` route that mounts this application in `App.jsx`,
 * so `""` is `/track` and `":reference"` is `/track/:reference`.
 */
export function PublicRoutes() {
  return (
    <PublicLayout>
      <Routes>
        <Route path="" element={<TrackLandingPage />} />
        {/* The route a label's QR code opens. `TRACKING_BASE_URL` plus the package
            reference lands exactly here (backend/app/services/label_service.py). */}
        <Route path=":reference" element={<TrackResultPage />} />
        {/* Anything deeper is not a tracking URL; send it to the lookup form rather
            than to the staff portal's not-found page. */}
        <Route path="*" element={<TrackLandingPage />} />
      </Routes>
    </PublicLayout>
  );
}

export function PublicApp({ queryClient, initialLanguage }) {
  // A fresh cache per mount, not a module-level singleton. A singleton would outlive the
  // public shell -- surviving a navigation out to the staff portal and back, and living
  // for the lifetime of the tab -- which is exactly the wrong lifetime for a tracking
  // result. Creating it here means the cache cannot exist while the public app does not.
  const [client] = useState(() => queryClient || createPublicQueryClient());

  return (
    <QueryClientProvider client={client}>
      <PublicI18nProvider initialLanguage={initialLanguage}>
        <PublicRoutes />
      </PublicI18nProvider>
    </QueryClientProvider>
  );
}
