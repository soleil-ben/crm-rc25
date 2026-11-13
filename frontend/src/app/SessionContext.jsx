/**
 * Session and permission context.
 *
 * The permission list is used only to decide what to *show*. Every action is enforced
 * again on the server, so hiding a control is never the authorization boundary
 * (CRM.md section 11).
 */

import { createContext, useCallback, useContext, useEffect, useMemo } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { authApi } from '../api/endpoints.js';

const SessionContext = createContext(null);

/**
 * The page the signed-in person lands on: the first navigation entry their role can
 * open. Every role holds `dashboard:read` today, so this is `/` in practice; it is
 * computed rather than hard-coded so a future role without the dashboard is not sent to
 * a screen that refuses it. Kept here, beside the permission list, rather than in the
 * shell, so the sign-in form can call it with the permissions the login response just
 * returned (UAT-AD-01 / fix pack item 11: a sign-in must open the signed-in user's own
 * landing page, never the previous user's last page).
 */
const LANDING_ORDER = [
  ['/', 'dashboard:read'],
  ['/customers', 'customer:read'],
  ['/shipments', 'shipment:read'],
  ['/follow-ups', 'task:read'],
  ['/segments', 'segment:read'],
  ['/reports', 'report:read'],
  ['/settings', 'settings:read'],
];

export function landingPathFor(permissions) {
  const granted = new Set(permissions ?? []);
  const entry = LANDING_ORDER.find(([, permission]) => granted.has(permission));
  return entry ? entry[0] : '/';
}

export function SessionProvider({ children }) {
  const queryClient = useQueryClient();

  const sessionQuery = useQuery({
    queryKey: ['session'],
    queryFn: authApi.me,
    retry: false,
    staleTime: 60_000,
  });

  const loginMutation = useMutation({
    mutationFn: ({ email, password }) => authApi.login(email, password),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['session'] }),
  });

  const logoutMutation = useMutation({
    mutationFn: authApi.logout,
    onSettled: () => {
      // Every cached staff response goes, not just the session: a customer list held
      // in memory after sign-out is customer data a Back press could render
      // (UAT-AD-01).
      queryClient.clear();
      queryClient.invalidateQueries({ queryKey: ['session'] });
    },
  });

  // A page restored from the back-forward cache comes back with its React state and its
  // query cache exactly as they were when the person left -- including after a sign-out
  // that happened on a later page. `pageshow` with `persisted` is the one signal the
  // browser gives for that. Resetting every query drops the cached data at once and
  // refetches the session, which answers 401 for a signed-out person and sends them to
  // the sign-in screen rather than to the restored dashboard (UAT-AD-01).
  useEffect(() => {
    function onPageShow(event) {
      if (event.persisted) queryClient.resetQueries();
    }
    window.addEventListener('pageshow', onPageShow);
    return () => window.removeEventListener('pageshow', onPageShow);
  }, [queryClient]);

  const permissions = useMemo(
    () => new Set(sessionQuery.data?.permissions ?? []),
    [sessionQuery.data],
  );

  const can = useCallback((permission) => permissions.has(permission), [permissions]);

  const value = useMemo(
    () => ({
      user: sessionQuery.data?.user ?? null,
      environment: sessionQuery.data?.environment ?? null,
      isDemoEnvironment: sessionQuery.data?.is_demo_environment ?? false,
      isLoading: sessionQuery.isLoading,
      isAuthenticated: Boolean(sessionQuery.data?.user),
      can,
      permissions,
      login: loginMutation.mutateAsync,
      loginError: loginMutation.error,
      isLoggingIn: loginMutation.isPending,
      logout: logoutMutation.mutateAsync,
    }),
    [sessionQuery.data, sessionQuery.isLoading, can, permissions, loginMutation, logoutMutation],
  );

  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSession() {
  const context = useContext(SessionContext);
  if (!context) throw new Error('useSession must be used inside SessionProvider');
  return context;
}

/**
 * The session when there is one, or null. For a component that is also rendered outside
 * the staff shell (a form mounted by a unit test on its own) and only *adds* a control
 * when a permission is known to be held.
 */
export function useOptionalSession() {
  return useContext(SessionContext);
}

/** Permission constants mirrored from the backend matrix. */
export const P = {
  CUSTOMER_READ: 'customer:read',
  CUSTOMER_CREATE: 'customer:create',
  CUSTOMER_UPDATE: 'customer:update',
  CUSTOMER_ARCHIVE: 'customer:archive',
  CUSTOMER_MERGE: 'customer:merge',
  ADDRESS_WRITE: 'address:write',
  INTERACTION_WRITE: 'interaction:write',
  TASK_READ: 'task:read',
  TASK_WRITE: 'task:write',
  CONSENT_READ: 'consent:read',
  CONSENT_WRITE: 'consent:write',
  // UAT round 4: suppressing an address from the Consent tab. Marketing and Admin.
  SUPPRESSION_ADD: 'suppression:add',
  TAG_READ: 'tag:read',
  TAG_WRITE: 'tag:write',
  REFERRAL_READ: 'referral:read',
  REFERRAL_WRITE: 'referral:write',
  SEGMENT_READ: 'segment:read',
  SHIPMENT_READ: 'shipment:read',
  SHIPMENT_WRITE: 'shipment:write',
  SHIPMENT_CANCEL: 'shipment:cancel',
  TRACKING_WRITE: 'tracking:write',
  LABEL_GENERATE: 'label:generate',
  FINANCIAL_COST_READ: 'financial_cost:read',
  FINANCIAL_WRITE: 'financial:write',
  SEGMENT_WRITE: 'segment:write',
  DASHBOARD_READ: 'dashboard:read',
  REPORT_READ: 'report:read',
  FINANCIAL_READ: 'financial:read',
  // Vendor cost: Operations and Admin (DEC-0172, OD-45). Gates the workspace (Phase 13D).
  TARIFF_READ: 'tariff:read',
  // Importing and approving tariffs: Admin (Phase 13H adds the approver list, OD-76).
  TARIFF_MANAGE: 'tariff:manage',
  // Phase 13E: refunds, voids and reopening a closed month. Admin only.
  FINANCIAL_ADJUST: 'financial:adjust',
  EXPORT_REPORTS: 'export:reports',
  EXPORT_CUSTOMERS: 'export:customers',
  EXPORT_MARKETING_SEGMENT: 'export:marketing_segment',
  EXPORT_SHIPMENTS: 'export:shipments',
  IMPORT_TEMPLATE: 'import:template',
  IMPORT_PREVIEW: 'import:preview',
  IMPORT_COMMIT: 'import:commit',
  DUPLICATE_REVIEW: 'duplicate:review',
  // Phase 10's two, held by Operations and Admin only. `review` reads the queue, an
  // application, its duplicate candidates and a preview; `approve` acknowledges,
  // approves, links and rejects. Neither is `duplicate:review`, which Marketing and the
  // read-only manager hold and which must reach none of this.
  CUSTOMER_ACCOUNT_REVIEW: 'customer_account:review',
  CUSTOMER_ACCOUNT_APPROVE: 'customer_account:approve',
  // Admin only (DEC-0126): deactivation is permanent for the account.
  CUSTOMER_ACCOUNT_DEACTIVATE: 'customer_account:deactivate',
  STAFF_MANAGE: 'staff:manage',
  INTEGRATION_READ: 'integration:read',
  INTEGRATION_MANAGE: 'integration:manage',
  SETTINGS_READ: 'settings:read',
  SETTINGS_MANAGE: 'settings:manage',
  AUDIT_READ: 'audit:read',
  // Owner decision 8 (2026-10-21): unlocking a booked master for item and fee edits. Admin only.
  MASTER_UNLOCK: 'master:unlock',
  // RC-UAT-21 Phase D (DEC-0233): Admin's alone.
  QUOTE_DELETE: 'quote:delete',
  RETENTION_MANAGE: 'retention:manage',
};
