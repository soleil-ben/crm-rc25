/**
 * Phase 15: what waits for a tariff approver -- draft versions with no decision yet and rate
 * emails held because their sender is not on the allowed list. The route needs `tariff:read`,
 * but only a holder of `tariff:manage` can be an approver, so nobody else asks; the badge is
 * shown only to a designated approver (the server says who), and only when something waits. The query key sits under `tariff-intake`, so every approve, reject, release or upload
 * that refreshes the intake list refreshes the badge too. No email is sent about it.
 */

import { useQuery } from '@tanstack/react-query';
import { tariffsApi } from '../../api/endpoints.js';

export const TARIFF_PENDING_KEY = ['tariff-intake', 'pending-count'];

export function useTariffPending(canManage) {
  const query = useQuery({
    queryKey: TARIFF_PENDING_KEY,
    queryFn: tariffsApi.pendingCount,
    enabled: Boolean(canManage),
    staleTime: 60_000,
    retry: false,
  });
  const data = query.data;
  const count = data?.viewer_is_approver
    ? (Number(data.drafts_awaiting) || 0) + (Number(data.held_senders) || 0)
    : 0;
  return { count, data };
}
