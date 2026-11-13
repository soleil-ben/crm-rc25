/**
 * Whether the staff application retries a failed read.
 *
 * A 401, 403, 404, 409 or 422 is a final answer about the request or the record, not a
 * transient failure, so it is shown at once. 409 joined the list in UAT round 5: reloading
 * an application that had already been decided waited through the retries on "Loading…"
 * before the "already decided" page appeared, although the first answer said so. Anything
 * else (a network failure, a 5xx) is tried twice more.
 */

import { ApiError } from './client.js';

const FINAL_STATUSES = new Set([401, 403, 404, 409, 422]);

export function shouldRetryQuery(failureCount, error) {
  if (error instanceof ApiError && FINAL_STATUSES.has(error.status)) return false;
  return failureCount < 2;
}
