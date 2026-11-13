/**
 * Reading this run's captured account mail, from the filesystem.
 *
 * ## Why there is no endpoint
 *
 * A captured verification or reset message contains the link in plaintext, and that link
 * is a live credential for somebody's account until it is redeemed. An HTTP route that
 * returned captured mail would be a way to read anybody's account-recovery credential,
 * and `EMAIL_DELIVERY.md` §2 says so in as many words: **no HTTP route exposes captured
 * mail, in any environment.** `backend/tests/test_account_email_capture.py` asserts the
 * absence by walking the route table.
 *
 * So the suite reads the files. `scripts/e2e_env.py` points this run's backend at
 * `data/e2e/run-<id>/mail/` with `ACCOUNT_EMAIL_TRANSPORT=capture`, and
 * `scripts/run_e2e.mjs` passes that path to Playwright as `E2E_MAIL_DIR`. The directory
 * is inside the run's own directory, so it is removed when the run passes and preserved
 * with the evidence when it fails; `data/e2e/` is git-ignored at any depth, so nothing
 * here can be committed.
 *
 * ## Why it refuses outside a run
 *
 * Without `E2E_MAIL_DIR` this module throws rather than falling back to the development
 * capture directory. A fallback would make the helper work when pointed at a developer's
 * own machine, which is the shape of the 2026-09-20 incident: a test that succeeds
 * against the wrong environment is worse than one that fails.
 *
 * ## What a test may do with a token
 *
 * Follow it. Nothing here logs one, writes one to an artifact, or returns the whole
 * message body where a failure message would print it — `verificationLinkFor` returns the
 * URL, and a test navigates to it. A token in a Playwright trace or a screenshot would be
 * a token in a file somebody could attach to a defect report.
 */

import { readdirSync, readFileSync } from 'node:fs';
import { join } from 'node:path';
import process from 'node:process';

/** The capture directory for this run, or a refusal. */
export function mailDirectory() {
  const directory = process.env.E2E_MAIL_DIR;
  if (!directory) {
    throw new Error(
      'E2E_MAIL_DIR is not set. The mail capture helper only works inside a run started ' +
        'by `npm run e2e --prefix frontend`; it deliberately has no fallback to the ' +
        'development capture directory.',
    );
  }
  return directory;
}

function captureFiles() {
  try {
    return readdirSync(mailDirectory()).filter((name) => name.endsWith('.json'));
  } catch (error) {
    if (error.code === 'ENOENT') return [];
    throw error;
  }
}

/**
 * Every captured message for an address, newest last.
 *
 * The filename carries a timestamp prefix and the sanitized address, so the sort is by
 * name and the match is on the address inside the file rather than on the filename —
 * sanitization is lossy and two addresses can produce one filename stem.
 */
export function messagesFor(emailAddress, { templateKey } = {}) {
  const wanted = emailAddress.trim().toLowerCase();
  const directory = mailDirectory();
  return captureFiles()
    .sort()
    .map((name) => JSON.parse(readFileSync(join(directory, name), 'utf8')))
    .filter((message) => message.to_email.trim().toLowerCase() === wanted)
    .filter((message) => !templateKey || message.template_key === templateKey);
}

/** The newest captured message for an address, or null. */
export function latestMessageFor(emailAddress, options) {
  const messages = messagesFor(emailAddress, options);
  return messages.length ? messages[messages.length - 1] : null;
}

/**
 * Wait for a message to arrive.
 *
 * The send happens inside the request the browser made, so by the time a response has
 * rendered the file is almost always already there. Almost: the write and the response
 * are not ordered against each other from the test's point of view, so this polls
 * briefly rather than asserting on the first look and failing intermittently.
 */
export async function waitForMessage(emailAddress, { templateKey, timeoutMs = 10_000 } = {}) {
  const deadline = Date.now() + timeoutMs;
  let seen = null;
  while (Date.now() < deadline) {
    seen = latestMessageFor(emailAddress, { templateKey });
    if (seen) return seen;
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  throw new Error(
    `No captured ${templateKey || 'account'} message for that address within ` +
      `${timeoutMs / 1000}s. The address is not repeated here, because this message ` +
      'reaches the Playwright report.',
  );
}

/** How many messages this run has captured for an address. */
export function messageCountFor(emailAddress, options) {
  return messagesFor(emailAddress, options).length;
}

/**
 * The single URL a captured message carries, as a path the browser can open.
 *
 * Returned as a path rather than an absolute URL because the message is rendered against
 * `TRACKING_BASE_URL`, which in a run points at the default development origin rather
 * than at this run's allocated port. The path is what matters; the origin is the base URL
 * Playwright already has.
 */
export function accountLinkFrom(message) {
  const match = message.body.match(/https?:\/\/\S+/);
  if (!match) throw new Error(`No link in the captured ${message.template_key} message.`);
  const url = new URL(match[0]);
  // The token travels in the fragment since the 2026-10-14 fix pack (CA-SEC-07); the
  // query string is kept for a message rendered by an older backend.
  return `${url.pathname}${url.search}${url.hash}`;
}

/** The single-use token a captured link carries, in either shape. Never logged. */
export function tokenFromLink(link) {
  const url = new URL(link, 'http://localhost');
  if (url.hash.startsWith('#token=')) return decodeURIComponent(url.hash.slice('#token='.length));
  return url.searchParams.get('token');
}

/** Convenience: wait for a verification message and return its link path. */
export async function verificationLinkFor(emailAddress, options) {
  const message = await waitForMessage(emailAddress, {
    templateKey: 'account.verify_email',
    ...options,
  });
  return accountLinkFrom(message);
}

/** Convenience: wait for a password-reset message and return its link path. */
export async function resetLinkFor(emailAddress, options) {
  const message = await waitForMessage(emailAddress, {
    templateKey: 'account.password_reset',
    ...options,
  });
  return accountLinkFrom(message);
}

/** The template keys this suite looks for, so a typo is a name error rather than a timeout. */
export const TEMPLATE = {
  VERIFY_EMAIL: 'account.verify_email',
  REGISTRATION_ATTEMPT_NOTICE: 'account.registration_attempt_notice',
  PASSWORD_RESET: 'account.password_reset',
  PASSWORD_CHANGED: 'account.password_changed',
  ACCOUNT_APPROVED: 'account.approved',
  ACCOUNT_REJECTED: 'account.rejected',
};
