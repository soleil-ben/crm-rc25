/**
 * Shared helpers for the public tracking end-to-end suite.
 *
 * References are read from the seeded demo database rather than hard-coded, because the
 * Solaris ID suffix is cryptographically random and changes on every reseed. Hard-coding
 * one would produce a suite that passes once and then fails for a reason that has nothing
 * to do with the code.
 */

import { execFileSync } from 'node:child_process';
import { PYTHON, PYTHON_RELATIVE, REPO_ROOT } from '../../scripts/pythonInterpreter.mjs';

/**
 * Ask the seeded database for the references this suite needs.
 *
 * Reads through the same SQLAlchemy engine the application uses, so the WAL-mode
 * pragmas apply and a concurrently running dev server is not disturbed.
 */
export function loadSeedReferences() {
  const script = `
import json, sys
sys.path.insert(0, "backend")
from sqlalchemy import text
from app.core.config import settings
from app.core.db import build_engine

engine = build_engine(settings.database_url)
out = {}
with engine.connect() as connection:
    def one(sql):
        row = connection.execute(text(sql)).fetchone()
        return row[0] if row else None

    # A multi-package shipment that is partly delivered and has approved public updates:
    # the richest honest result the demo data contains.
    out["partial"] = one("""
        SELECT s.public_id FROM shipments s
        WHERE s.operational_state = 'partially_delivered'
          AND s.booking_state = 'confirmed'
          AND (SELECT COUNT(*) FROM shipment_events e
               WHERE e.shipment_id = s.id AND e.is_public_update = 1 AND e.is_voided = 0) > 0
        ORDER BY s.id LIMIT 1
    """)
    out["partial_package"] = one(f"""
        SELECT p.package_reference FROM shipment_packages p
        JOIN shipments s ON s.id = p.shipment_id
        WHERE s.public_id = '{out["partial"]}' AND p.sequence = 2
    """)
    # The public page derives its status from **published** events only (fix pack of
    # 2026-10-14, UAT-XX-02), so a shipment whose stored state rests on an unpublished
    # event -- the seed keeps one such on purpose -- would read differently in public.
    # These pick shipments whose public story matches their stored state.
    out["exception"] = one("""
        SELECT s.public_id FROM shipments s
        WHERE s.operational_state = 'exception' AND s.booking_state = 'confirmed'
          AND EXISTS (SELECT 1 FROM shipment_events e
                      WHERE e.shipment_id = s.id AND e.is_public_update = 1
                        AND e.is_voided = 0 AND e.operational_state = 'exception')
        ORDER BY s.id LIMIT 1
    """)
    out["cancelled"] = one("""
        SELECT public_id FROM shipments
        WHERE booking_state = 'cancelled' AND public_id IS NOT NULL
        ORDER BY id LIMIT 1
    """)
    out["delivered"] = one("""
        SELECT s.public_id FROM shipments s
        WHERE s.operational_state = 'delivered' AND s.booking_state = 'confirmed'
          AND EXISTS (SELECT 1 FROM shipment_events e
                      WHERE e.shipment_id = s.id AND e.is_public_update = 1
                        AND e.is_voided = 0 AND e.is_final_recipient_delivery = 1)
        ORDER BY s.id LIMIT 1
    """)
print(json.dumps(out))
`;
  const stdout = execFileSync(PYTHON, ['-c', script], {
    cwd: REPO_ROOT,
    encoding: 'utf8',
    env: { ...process.env, PYTHONIOENCODING: 'utf-8' },
  });
  const references = JSON.parse(stdout.trim().split('\n').pop());

  for (const [name, value] of Object.entries(references)) {
    if (!value) {
      throw new Error(
        `The demo database has no shipment for "${name}". ` +
          `Run: ${PYTHON_RELATIVE} -m app.seed --reset`,
      );
    }
  }
  return references;
}

/** A reference that is well formed but was never issued. */
export const UNKNOWN_REFERENCE = 'SX-CAV-ABCDEFGHJKLM';

/** A reference that is not well formed at all. */
export const MALFORMED_REFERENCE = 'not-a-solaris-reference';

/**
 * Record every request the page makes, so a test can assert what was *not* called.
 *
 * Most of the public privacy requirements are negative -- no staff endpoint, no
 * third-party host, no analytics beacon -- and a negative is only provable by watching
 * the whole conversation rather than one request.
 */
export function recordRequests(page) {
  const requests = [];
  page.on('request', (request) => {
    requests.push({
      url: request.url(),
      method: request.method(),
      resourceType: request.resourceType(),
    });
  });
  return requests;
}

/** Hosts that are ours. Anything else on a public page is a finding. */
export function isFirstParty(url, baseUrl) {
  try {
    const parsed = new URL(url, baseUrl);
    const base = new URL(baseUrl);
    return parsed.host === base.host || parsed.protocol === 'data:' || parsed.protocol === 'blob:';
  } catch {
    return false;
  }
}

/** Staff API prefixes that must never be requested by a public page. */
export const STAFF_API_PREFIXES = [
  '/api/v1/auth',
  '/api/v1/customers',
  '/api/v1/shipments',
  '/api/v1/packages',
  '/api/v1/legs',
  '/api/v1/events',
  '/api/v1/segments',
  '/api/v1/tasks',
  '/api/v1/admin',
  '/api/v1/search',
  '/api/v1/interactions',
];

/** Third-party analytics, error tracking, ads, and social widgets. */
export const TRACKER_PATTERNS = [
  /google-analytics/i,
  /googletagmanager/i,
  /doubleclick/i,
  /facebook\.(net|com)/i,
  /sentry\.io/i,
  /hotjar/i,
  /segment\.(io|com)/i,
  /mixpanel/i,
  /fullstory/i,
  /clarity\.ms/i,
  /fonts\.(googleapis|gstatic)\.com/i,
  /cdn\.jsdelivr/i,
  /unpkg\.com/i,
];
