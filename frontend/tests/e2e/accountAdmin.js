/**
 * Staff actions that Phase 12 built no screen for, performed against this run's database.
 *
 * ## Why this exists at all
 *
 * `PRODUCT_SPEC.md` §4 lists four pieces of staff work the Customer Account creates:
 * approval, proposal review, rejection **and suspension**, and privacy requests. The
 * owner's Phase 12 instruction builds the approval queue and says nothing about a
 * suspension screen, so there is none — and `accountRecovery.spec.js` still has to reach
 * the suspended state, because the *customer-facing* behaviour under test is what a
 * suspended person sees.
 *
 * ## Why it is not an HTTP call
 *
 * There is no route for it either: suspension is `customer_identity_service.suspend`, and
 * Phase 10 exposed approve, link and reject, not suspend. Inventing a route for a test to
 * call would be adding a mutation endpoint the owner did not authorise, which is a worse
 * answer than a test helper that reaches past the API.
 *
 * ## What keeps this honest
 *
 * * it runs **only** inside a run `scripts/run_e2e.mjs` started, because it reads
 *   `E2E_DATABASE_URL`, which nothing else sets, and refuses without it;
 * * it refuses any database whose URL is not this repository's E2E scratch shape, so it
 *   cannot be pointed at `data/solaris_crm.db` by an exported environment variable;
 * * it calls the **service**, through the same subprocess entry point the harness uses
 *   for migration and seeding, rather than issuing SQL — so the state it produces is the
 *   state the application produces, with its audit row, and not a row a test invented.
 *
 * Nothing here is used to *set up* a passing assertion about the Customer Account's own
 * behaviour. It changes an account's state and then the spec drives the browser.
 */

import { execFileSync } from 'node:child_process';
import process from 'node:process';
import { PYTHON, REPO_ROOT } from '../../scripts/pythonInterpreter.mjs';

/** The database this run owns, or a refusal. */
function e2eDatabaseUrl() {
  const url = process.env.E2E_DATABASE_URL;
  if (!url) {
    throw new Error(
      'E2E_DATABASE_URL is not set. These helpers only work inside a run started by ' +
        '`npm run e2e --prefix frontend`.',
    );
  }
  if (!url.includes('/data/e2e/') || !url.includes('.e2e.db')) {
    throw new Error(
      `Refusing to act on ${url}: it is not an end-to-end scratch database. ` +
        'The only databases these helpers may touch are the ones a run created.',
    );
  }
  return url;
}

function runPython(script) {
  const url = e2eDatabaseUrl();
  const result = execFileSync(PYTHON, ['-c', script], {
    cwd: REPO_ROOT,
    encoding: 'utf8',
    env: {
      ...process.env,
      DATABASE_URL: url,
      ENVIRONMENT: 'e2e',
      // `ENVIRONMENT=e2e` turns on the guard that refuses to start without the run
      // identifier, which is exactly the guard that should be on — so the identifier is
      // passed too. Without it the subprocess refuses, correctly, and the test fails with
      // a message about an unsafe setting rather than about the thing it was checking.
      SOLARIS_E2E_RUN_ID: process.env.E2E_RUN_ID,
      PYTHONIOENCODING: 'utf-8',
    },
  });
  return result.trim();
}

/**
 * Suspend the identity for an address, through the service.
 *
 * Reason code and actor are what a staff action would carry. The actor is the seeded
 * Operations user, so the audit row names a real staff member rather than "the test".
 */
export function suspendIdentity(emailAddress) {
  const script = `
import sys
sys.path.insert(0, "backend")
from sqlalchemy import select
from app.core.db import SessionLocal
from app.core.normalization import normalize_email
from app.models import CustomerIdentity, User
from app.services import customer_identity_service

_, normalized = normalize_email(${JSON.stringify(emailAddress)})
with SessionLocal() as db:
    identity = db.scalar(
        select(CustomerIdentity).where(CustomerIdentity.email_normalized == normalized)
    )
    if identity is None:
        raise SystemExit("no identity for that address in this run's database")
    actor = db.scalar(select(User).where(User.email == "ops@demo.example.com"))
    customer_identity_service.suspend(
        db, identity=identity, actor=actor, reason_code="service_restriction"
    )
    db.commit()
    print(identity.public_id)
`;
  return runPython(script);
}

/**
 * The account reference for an address, read from this run's database.
 *
 * Used where a spec needs to name an account it created and the queue would be ambiguous.
 */
export function accountReferenceFor(emailAddress) {
  const script = `
import sys
sys.path.insert(0, "backend")
from sqlalchemy import select
from app.core.db import SessionLocal
from app.core.normalization import normalize_email
from app.models import CustomerIdentity

_, normalized = normalize_email(${JSON.stringify(emailAddress)})
with SessionLocal() as db:
    identity = db.scalar(
        select(CustomerIdentity).where(CustomerIdentity.email_normalized == normalized)
    )
    if identity is None:
        raise SystemExit("no identity for that address in this run's database")
    print(identity.public_id)
`;
  return runPython(script);
}
