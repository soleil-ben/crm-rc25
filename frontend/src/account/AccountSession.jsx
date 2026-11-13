/**
 * The Customer Account's own session context. Not `app/SessionContext.jsx`.
 *
 * The staff provider resolves `/auth/me`, holds a permission `Set`, and exposes `can()`.
 * None of that exists here, and the absence is the design: **a customer identity has no
 * role and no permission set** (`IDENTITY_AND_AUTHORIZATION.md`, T-12). There is nothing
 * for a `can()` to consult, so there is no `can()` to misuse as an authorization boundary.
 *
 * What this provider holds is four booleans and a status string, all of them re-read from
 * the server. It caches nothing it could be wrong about:
 *
 * * `status` — the identity's own lifecycle state, straight from `/account/me`;
 * * `linked` — whether an approved link exists;
 * * `shipmentHistoryAvailable` — whether the shipment routes would serve this caller.
 *   Deliberately **not** derived from `linked`: the server answers it with the same helper
 *   the shipment routes apply, and deriving it here would let the shell promise a screen
 *   the API then refuses.
 *
 * **The server is the authority.** Every value here decides what to *show*. Ownership of a
 * shipment is enforced in SQL, on every request, and a screen that hides a row is a
 * courtesy and never a boundary.
 */

import { createContext, useContext, useMemo } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { AccountApiError, accountApi } from './accountApi.js';

const AccountSessionContext = createContext(null);

/** The identity states `/account/me` can report (`app/core/account_enums.py`). */
export const ACCOUNT_STATUS = {
  PENDING_VERIFICATION: 'pending_verification',
  PENDING_APPROVAL: 'pending_approval',
  ACTIVE: 'active',
  REJECTED: 'rejected',
  SUSPENDED: 'suspended',
  DEACTIVATED: 'deactivated',
};

/** The query key for `/account/me`. Exported so a screen can invalidate it by name. */
export const ACCOUNT_SESSION_KEY = ['account', 'me'];

export function AccountSessionProvider({ children }) {
  const queryClient = useQueryClient();

  const sessionQuery = useQuery({
    queryKey: ACCOUNT_SESSION_KEY,
    queryFn: ({ signal }) => accountApi.me({ signal }),
    // A 401 here is the ordinary "not signed in" answer, not a failure worth retrying.
    // Retrying it would also spend the account rate-limit allowance three times over on
    // every visit by a signed-out stranger.
    retry: false,
    // Re-read on mount rather than trusted from cache: suspension and link revocation
    // take effect on the *next request* by design, and a cached `me` is the one way the
    // browser could keep showing a shell the server would now refuse.
    staleTime: 0,
    refetchOnWindowFocus: false,
  });

  const signIn = useMutation({
    mutationFn: ({ email, password }) => accountApi.signIn(email, password),
    // The sign-in response carries `csrf_token`, and it is deliberately ignored: the same
    // value is already in the readable cookie, and the API client reads it there at call
    // time. Copying it into React state would be keeping a credential in a place the
    // browser does not scope or expire.
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ACCOUNT_SESSION_KEY }),
  });

  const signOut = useMutation({
    mutationFn: () => accountApi.signOut(),
    onSettled: () => {
      // Clear first, then refetch. `clear()` drops every cached shipment page and detail,
      // so the back button after a sign-out has nothing to render from — the browser is
      // asked for the page again and the server answers 401. A `removeQueries` on the
      // session key alone would leave the list in the cache.
      queryClient.clear();
      queryClient.invalidateQueries({ queryKey: ACCOUNT_SESSION_KEY });
    },
  });

  const error = sessionQuery.error;
  const signedOut = error instanceof AccountApiError && error.isSignedOut;

  const value = useMemo(() => {
    const me = sessionQuery.data ?? null;
    return {
      // `isResolving` is the gate the guard waits on. It is true until the first answer
      // arrives, whatever that answer is.
      isResolving: sessionQuery.isPending,
      isSignedIn: Boolean(me),
      // A failed session read that is *not* a 401 — a network error, a 500 — is not a
      // sign-out. The shell says so rather than bouncing the person to a sign-in form
      // that will not help them.
      isUnreachable: Boolean(error) && !signedOut,
      accountReference: me?.account_reference ?? null,
      status: me?.status ?? null,
      emailVerified: me?.email_verified ?? false,
      linked: me?.linked ?? false,
      shipmentHistoryAvailable: me?.shipment_history_available ?? false,
      hasPendingProposal: me?.has_pending_proposal ?? false,
      // Read by the language bridge (OD-71): the screens follow it unless the person has
      // used the switch. Not otherwise interpreted here.
      preferredLanguage: me?.preferred_language ?? null,
      signIn: signIn.mutateAsync,
      signInError: signIn.error,
      isSigningIn: signIn.isPending,
      signOut: signOut.mutateAsync,
      isSigningOut: signOut.isPending,
      refresh: () => queryClient.invalidateQueries({ queryKey: ACCOUNT_SESSION_KEY }),
    };
  }, [sessionQuery.data, sessionQuery.isPending, error, signedOut, signIn, signOut, queryClient]);

  return (
    <AccountSessionContext.Provider value={value}>{children}</AccountSessionContext.Provider>
  );
}

export function useAccountSession() {
  const context = useContext(AccountSessionContext);
  if (!context) {
    throw new Error('useAccountSession must be used inside AccountSessionProvider');
  }
  return context;
}

/**
 * Where a signed-in account belongs, given only its status and whether history is
 * available.
 *
 * One function, so the guard, the sign-in redirect and the `/account` index cannot
 * disagree about where an account should land. Every branch returns a route, including
 * the default: an unrecognised status is a state this build does not know about, and the
 * pending card is the safe thing to show somebody in one.
 */
export function destinationForSession(session) {
  if (!session.isSignedIn) return '/account/sign-in';
  switch (session.status) {
    case ACCOUNT_STATUS.ACTIVE:
      // Active but not yet linked is a real state: approval sets both, but a link can be
      // revoked without the identity changing. The pending card is the honest screen for
      // it, and it says what it says without naming a reason.
      return session.shipmentHistoryAvailable ? '/account/shipments' : '/account/pending';
    case ACCOUNT_STATUS.PENDING_APPROVAL:
      return '/account/pending';
    case ACCOUNT_STATUS.REJECTED:
      return '/account/rejected';
    case ACCOUNT_STATUS.SUSPENDED:
    case ACCOUNT_STATUS.DEACTIVATED:
      return '/account/unavailable';
    default:
      return '/account/pending';
  }
}
