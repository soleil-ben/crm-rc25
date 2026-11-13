/**
 * The harness refuses to write into a database it did not create.
 *
 * `backend/tests/test_e2e_safety.py` proves the backend cannot *serve* the wrong database.
 * This file proves the other half: that the browser suite cannot *reach* a backend it did
 * not start. Both halves are needed, because on 2026-09-20 the first one would not have
 * helped — nothing was misconfigured. The suite simply connected to a development backend
 * that was already listening on the port it expected, and the staff specs wrote 40
 * customers, 32 import batches and 195 audit events into `data/solaris_crm.db`.
 *
 * So every test here stands a fake server in front of `globalSetup` and asks what it does.
 * A real server rather than a mocked fetch: the thing being tested is a decision made from
 * an HTTP response, and a stub that returns the response we expected would only prove we
 * can predict ourselves.
 */

import http from 'node:http';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import globalSetup from './e2e/globalSetup.js';

const RUN_ID = '0123456789abcdef0123456789abcdef';
const OTHER_RUN_ID = 'fedcba9876543210fedcba9876543210';

const HANDSHAKE = '/api/v1/e2e/handshake';
const TRACKING_PREFIX = '/api/v1/public/track/';

/** `globalSetup` reads `config.projects[0].use.baseURL` when the env var is absent. */
const EMPTY_CONFIG = { projects: [{ use: {} }] };

/**
 * Source with block and line comments removed.
 *
 * For the assertions that say "this file must not do X". The files under test explain
 * *why* they do not do X, naming X in prose, and a test that read the explanation as the
 * thing itself would make the explanation unwritable.
 */
function withoutComments(source) {
  return source.replace(/\/\*[\s\S]*?\*\//g, '').replace(/(^|[^:])\/\/.*$/gm, '$1');
}

let server;
let received;

/**
 * Stand up a loopback server that answers the two paths `globalSetup` asks about.
 *
 * `handshake` decides what the handshake returns; `tracking` decides what the public
 * limiter probe returns. The default tracking answer is 404, which is what an open window
 * looks like — the limiter answers 404 for anything under the limit (DEC-0051).
 */
async function stand({ handshake, tracking = () => ({ status: 404, body: '{}' }) }) {
  received = [];
  server = http.createServer((request, response) => {
    received.push({ url: request.url, headers: request.headers });
    const answer = request.url.startsWith(HANDSHAKE)
      ? handshake(request)
      : request.url.startsWith(TRACKING_PREFIX)
        ? tracking(request)
        : { status: 404, body: '{}' };
    response.writeHead(answer.status, {
      'content-type': 'application/json',
      ...(answer.headers || {}),
    });
    response.end(answer.body ?? '{}');
  });
  await new Promise((done) => server.listen(0, '127.0.0.1', done));
  return `http://127.0.0.1:${server.address().port}`;
}

/** A backend that belongs to this run: it knows the endpoint and agrees on the identifier. */
const correctBackend = (expected = RUN_ID) => (request) =>
  request.headers['x-e2e-run-id'] === expected
    ? { status: 200, body: '{"status":"ok"}' }
    : { status: 409, body: '{"status":"mismatch"}' };

/** A development, UAT or production backend: the route was never mounted, so 404. */
const backendWithoutTheEndpoint = () => ({ status: 404, body: '{"detail":"Not Found"}' });

beforeEach(() => {
  delete process.env.E2E_RUN_ID;
  delete process.env.E2E_BASE_URL;
});

afterEach(async () => {
  if (server) await new Promise((done) => server.close(done));
  server = undefined;
  delete process.env.E2E_RUN_ID;
  delete process.env.E2E_BASE_URL;
});

describe('the suite refuses a backend it did not start', () => {
  it('refuses an arbitrary backend that is already listening', async () => {
    process.env.E2E_BASE_URL = await stand({ handshake: backendWithoutTheEndpoint });
    process.env.E2E_RUN_ID = RUN_ID;

    await expect(globalSetup(EMPTY_CONFIG)).rejects.toThrow(/has no end-to-end handshake/);
  });

  it('names the consequence rather than only the symptom', async () => {
    process.env.E2E_BASE_URL = await stand({ handshake: backendWithoutTheEndpoint });
    process.env.E2E_RUN_ID = RUN_ID;

    // A refusal a developer cannot act on is a refusal they will work around.
    await expect(globalSetup(EMPTY_CONFIG)).rejects.toThrow(/npm run e2e --prefix frontend/);
  });

  it('refuses a stale backend left over from an earlier run', async () => {
    process.env.E2E_BASE_URL = await stand({ handshake: correctBackend(OTHER_RUN_ID) });
    process.env.E2E_RUN_ID = RUN_ID;

    await expect(globalSetup(EMPTY_CONFIG)).rejects.toThrow(/belongs to a different run/);
  });

  it('refuses when the identifier does not match', async () => {
    process.env.E2E_BASE_URL = await stand({
      handshake: () => ({ status: 409, body: '{"status":"mismatch"}' }),
    });
    process.env.E2E_RUN_ID = RUN_ID;

    await expect(globalSetup(EMPTY_CONFIG)).rejects.toThrow(/Refusing to run/);
  });

  it('refuses when nothing is listening at all', async () => {
    // Bind and release, so the port is one nothing holds.
    const origin = await stand({ handshake: correctBackend() });
    await new Promise((done) => server.close(done));
    server = undefined;
    process.env.E2E_BASE_URL = origin;
    process.env.E2E_RUN_ID = RUN_ID;

    await expect(globalSetup(EMPTY_CONFIG)).rejects.toThrow(/Nothing answered|Refusing to run/);
  });

  it('refuses when Playwright was started outside the harness', async () => {
    process.env.E2E_BASE_URL = await stand({ handshake: correctBackend() });
    // No E2E_RUN_ID: this is `npx playwright test` typed by hand, which is exactly what
    // happened on 2026-09-20.
    await expect(globalSetup(EMPTY_CONFIG)).rejects.toThrow(/E2E_RUN_ID is not set/);
  });

  it('refuses before it probes anything else', async () => {
    process.env.E2E_BASE_URL = await stand({ handshake: backendWithoutTheEndpoint });
    process.env.E2E_RUN_ID = RUN_ID;

    await expect(globalSetup(EMPTY_CONFIG)).rejects.toThrow();
    // The handshake and nothing after it. A refusal that had already drained the limiter
    // would have already talked to the wrong server.
    expect(received.every((entry) => entry.url.startsWith(HANDSHAKE))).toBe(true);
  });

  it('presents the identifier in a header, never in the path', async () => {
    process.env.E2E_BASE_URL = await stand({ handshake: correctBackend() });
    process.env.E2E_RUN_ID = RUN_ID;

    await globalSetup(EMPTY_CONFIG);
    const handshakeCall = received.find((entry) => entry.url.startsWith(HANDSHAKE));
    expect(handshakeCall.url).toBe(HANDSHAKE);
    expect(handshakeCall.headers['x-e2e-run-id']).toBe(RUN_ID);
  });
});

describe('the suite proceeds when the backend is its own', () => {
  it('accepts a matching run and goes on to drain the limiter', async () => {
    process.env.E2E_BASE_URL = await stand({ handshake: correctBackend() });
    process.env.E2E_RUN_ID = RUN_ID;

    await expect(globalSetup(EMPTY_CONFIG)).resolves.toBeUndefined();
    expect(received.some((entry) => entry.url.startsWith(TRACKING_PREFIX))).toBe(true);
  });

  it('two sequential runs each verify their own identifier', async () => {
    // Nothing is carried between runs: the second presents its own identifier and the
    // server it reaches has to agree with that one, not with the first.
    process.env.E2E_BASE_URL = await stand({ handshake: correctBackend(RUN_ID) });
    process.env.E2E_RUN_ID = RUN_ID;
    await globalSetup(EMPTY_CONFIG);
    await new Promise((done) => server.close(done));

    process.env.E2E_BASE_URL = await stand({ handshake: correctBackend(OTHER_RUN_ID) });
    process.env.E2E_RUN_ID = OTHER_RUN_ID;
    await expect(globalSetup(EMPTY_CONFIG)).resolves.toBeUndefined();
  });

  it('a run cannot satisfy the handshake with the previous run identifier', async () => {
    process.env.E2E_BASE_URL = await stand({ handshake: correctBackend(OTHER_RUN_ID) });
    process.env.E2E_RUN_ID = RUN_ID;
    await expect(globalSetup(EMPTY_CONFIG)).rejects.toThrow();
  });
});

describe('the documented command is the one that is wired up', () => {
  const manifest = JSON.parse(
    readFileSync(join(process.cwd(), 'package.json'), 'utf8'),
  );

  it('npm run e2e starts the orchestrator, not playwright directly', () => {
    // If this ever goes back to `playwright test`, the suite reaches whatever is
    // listening again -- which is the incident, restored.
    expect(manifest.scripts.e2e).toBe('node scripts/run_e2e.mjs');
  });

  it('the orchestrator never reuses an occupied port', () => {
    const source = withoutComments(
      readFileSync(join(process.cwd(), 'scripts', 'run_e2e.mjs'), 'utf8'),
    );
    // `claimPort` has exactly two outcomes: the preferred port when it was free, or a
    // port the operating system just handed out. There is no path that returns a port
    // something else is holding.
    expect(source).toMatch(/if \(await portIsFree\(preferred\)\) return preferred;/);
    expect(source).toMatch(/E2E_OCCUPIED_PORT_POLICY/);
    expect(source).not.toMatch(/reuseExistingServer/);
  });

  it('playwright.config declares no webServer that could adopt one', () => {
    const source = withoutComments(
      readFileSync(join(process.cwd(), 'playwright.config.js'), 'utf8'),
    );
    expect(source).not.toMatch(/^\s*webServer:/m);
  });

  it('never pipes a child process’s output through a Node stream', () => {
    // Found by the first green-looking run, which was not green. `pipe()` into a
    // `createWriteStream` buffers in memory when the file system is slow -- this
    // repository sits inside a OneDrive folder -- and the backpressure reaches the child
    // as a blocked `write()` on stdout. The suite still passed 149 tests; it took 19
    // minutes instead of four, and `zzRateLimit.spec.js` timed out, because it is the one
    // spec that has to fit 200 requests inside a 60-second window.
    //
    // A throughput assertion would be flaky. The mechanism is not: hand the child a file
    // descriptor and nothing in this script can throttle it.
    //
    // Comments are stripped first, because the fix is documented in the file it fixed --
    // the comment names `child.stdout.pipe(createWriteStream(...))` so the next reader
    // knows what not to go back to, and an assertion that could not tell prose from code
    // would forbid explaining it.
    const source = withoutComments(
      readFileSync(join(process.cwd(), 'scripts', 'run_e2e.mjs'), 'utf8'),
    );
    expect(source).not.toMatch(/\.std(out|err)\.pipe\(/);
    expect(source).not.toMatch(/createWriteStream/);
    expect(source).toMatch(/stdio: appendTo\(/);
  });

  it('tells the backend not to buffer its own output', () => {
    // The other half of the same problem: Python block-buffers stdout when it is not a
    // terminal, so the last seconds before a failure -- the only part anybody reads --
    // would still be in the child's buffer when the harness kills it.
    const source = readFileSync(join(process.cwd(), '..', 'scripts', 'e2e_env.py'), 'utf8');
    expect(source).toMatch(/"PYTHONUNBUFFERED": "1"/);
  });
});
