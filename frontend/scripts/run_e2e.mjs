/**
 * The one command that runs the end-to-end suite (DEC-0112).
 *
 *     npm run e2e --prefix frontend
 *
 * It owns the whole run: it mints a run identifier, builds a scratch database that no
 * other run shares, starts a backend and a Vite dev server that belong to this run alone,
 * points Playwright at them, and then removes everything it created -- or, when the run
 * fails, leaves exactly that run's directory behind and says where it is.
 *
 * ## Why this exists
 *
 * `playwright.config.js` used to expect a stack somebody had already started, and
 * `docs/OPERATIONS.md` explained, in prose, that it should be pointed at a scratch
 * database. On 2026-09-20 it was not, and the staff specs wrote forty customers, thirty-two
 * import batches and a hundred and ninety-five audit rows into `data/solaris_crm.db`.
 *
 * Nothing about that was a bug in a test. The harness simply had no way of knowing which
 * database it was writing to, because it never started the thing that chose one. So this
 * script starts it.
 *
 * ## What it refuses to do
 *
 * **It never adopts a server that is already listening.** That is the entire lesson of the
 * incident: a development backend on port 8000 answers a browser exactly as well as the
 * right one does. So an occupied port is either a hard failure or a controlled move to a
 * different port -- never a silent reuse. See `claimPort`.
 *
 * **It never trusts the port alone either.** Binding a free port proves nothing about what
 * connects to it later, and a stale backend from a previous run could have exited and
 * restarted between the probe and the first test. So before any project runs, the suite's
 * global setup asks the server to prove it belongs to this run: `globalSetup.js` presents
 * the run identifier, and `app.api.e2e` confirms it against both its own environment and a
 * marker row inside the database it is actually serving. Two different things have to agree,
 * and neither can be satisfied by a backend this script did not start.
 *
 * **It never leaves the limiter to be remembered.** `scripts/e2e_env.py` puts the documented
 * E2E rate limits into the backend's environment itself, so a run cannot be started without
 * them and then fail five public-tracking tests for a reason that looks like a layout bug.
 *
 * ## Exit codes
 *
 * 0 success (and the run directory is removed), 1 the suite failed (the run directory is
 * kept), 2 the harness refused to start.
 */

import { spawn, spawnSync } from 'node:child_process';
import { createServer } from 'node:net';
import { closeSync, mkdirSync, openSync } from 'node:fs';
import { dirname, join } from 'node:path';
import process from 'node:process';
import {
  FRONTEND_ROOT,
  PYTHON,
  PYTHON_RELATIVE,
  REPO_ROOT,
  WINDOWS,
} from './pythonInterpreter.mjs';

/**
 * The two Node CLIs, addressed by their module entry point rather than through `npx`.
 *
 * `npx` on Windows is `npx.cmd`, and since the Node 20 fix for CVE-2024-27980 spawning a
 * `.cmd` without a shell fails with `EINVAL` -- while spawning it *with* one would put a
 * command interpreter between this script and the process it has to be able to kill by
 * pid. Running the CLI's own JavaScript with the Node that is already executing this file
 * avoids both, and removes a dependency on whatever `npx` resolves to today.
 */
const VITE_CLI = join(FRONTEND_ROOT, 'node_modules', 'vite', 'bin', 'vite.js');
const PLAYWRIGHT_CLI = join(FRONTEND_ROOT, 'node_modules', '@playwright', 'test', 'cli.js');
const E2E_ENV_SCRIPT = join(REPO_ROOT, 'scripts', 'e2e_env.py');

/** Preferred ports. Neither is reused if occupied; see `claimPort`. */
const PREFERRED_BACKEND_PORT = Number(process.env.E2E_BACKEND_PORT || 8100);
const PREFERRED_FRONTEND_PORT = Number(process.env.E2E_VITE_PORT || 5273);

/**
 * How an occupied preferred port is handled.
 *
 * `allocate` (the default) moves to a free port the operating system picks and says so.
 * `fail` stops the run. Both are safe; neither reuses what is already there. CI sets
 * `fail` so a port collision is a red build rather than a quietly different run.
 */
const OCCUPIED_PORT_POLICY = (process.env.E2E_OCCUPIED_PORT_POLICY || 'allocate').toLowerCase();

const READINESS_TIMEOUT_MS = 120_000;

/** The one address both servers bind and the browser connects to; see `main`. */
const LOOPBACK = '127.0.0.1';

const started = [];

/** Log file descriptors handed to children; see `closeLogs`. */
const openLogFds = [];

function log(message) {
  process.stdout.write(`[e2e] ${message}\n`);
}

function fail(message) {
  process.stderr.write(`[e2e] ${message}\n`);
}

// --- Ports --------------------------------------------------------------------------

/**
 * Is this port free *for us to bind*?
 *
 * Deliberately a bind attempt rather than a connect attempt. "Nothing answered a
 * connection" is not the same as "nothing holds this port", and the question that matters
 * here is whether this run can own the socket -- because a run that cannot own it would
 * otherwise end up talking to whoever does.
 */
function portIsFree(port) {
  return new Promise((done) => {
    const probe = createServer();
    probe.once('error', () => done(false));
    probe.once('listening', () => probe.close(() => done(true)));
    // Every interface, so a server bound to IPv6-only or to a single interface still
    // counts as occupying the port.
    probe.listen(port);
  });
}

/** A port the operating system says is free right now. */
function ephemeralPort() {
  return new Promise((done, reject) => {
    const probe = createServer();
    probe.once('error', reject);
    probe.once('listening', () => {
      const { port } = probe.address();
      probe.close(() => done(port));
    });
    probe.listen(0);
  });
}

/**
 * Claim a port for this run, or refuse.
 *
 * There is no branch here that returns an occupied port. That is the point: the incident
 * happened because a suite connected to something it had not started, and a harness that
 * "reuses the existing server to save time" is that incident with a comment explaining it.
 *
 * The probe binds and releases, so between here and the child binding it there is a window
 * of a few milliseconds in which something else could take the port. That is not a hole in
 * the safety property, because the safety property is not the port: if something else wins
 * the race, the child fails to bind and exits, and `waitForReady` reports that rather than
 * proceeding. And if a server somehow were listening there, `globalSetup.js` would still
 * demand the run identifier from it and stop when it could not produce one. The port check
 * is the first of three, and it is the only one that can be raced.
 */
async function claimPort(label, preferred) {
  if (await portIsFree(preferred)) return preferred;

  if (OCCUPIED_PORT_POLICY === 'fail') {
    throw new Error(
      `Port ${preferred} is already in use and E2E_OCCUPIED_PORT_POLICY=fail. ` +
        `Stop whatever is listening, or allow an alternate port. This run will not ` +
        `reuse a ${label} it did not start.`,
    );
  }
  if (OCCUPIED_PORT_POLICY !== 'allocate') {
    throw new Error(
      `E2E_OCCUPIED_PORT_POLICY=${OCCUPIED_PORT_POLICY} is not a known policy. ` +
        'Use "allocate" or "fail".',
    );
  }

  const alternate = await ephemeralPort();
  log(
    `port ${preferred} is occupied; this run will not reuse it. Allocating ${alternate} ` +
      `for the ${label} instead.`,
  );
  return alternate;
}

// --- Child processes ----------------------------------------------------------------

/**
 * Send a child's output straight to a file, with no Node stream in between.
 *
 * This was `child.stdout.pipe(createWriteStream(...))` and it cost the suite its
 * rate-limit test. A Node write stream buffers in memory when the file system is slow --
 * and this repository lives inside a OneDrive folder, whose sync client is exactly that --
 * so `pipe()` applied backpressure, paused the readable, filled the 64 KiB OS pipe, and
 * left the backend blocking inside `write()` on every log line. The evidence was a
 * `backend.log` frozen at 456 bytes after one request while 149 tests went on passing, and
 * a suite that took 19 minutes against a documented 4.1. Everything was slower; only
 * `zzRateLimit.spec.js` actually failed, because it is the one test that has to fit 200
 * requests inside a 60-second window, and at a quarter of the throughput it no longer did.
 *
 * Handing the child a file descriptor removes Node from the write path entirely: the
 * process writes to the file itself, and nothing in this script can throttle it.
 */
function appendTo(path) {
  const fd = openSync(path, 'a');
  openLogFds.push(fd);
  return ['ignore', fd, fd];
}

/**
 * Close the log descriptors this process is holding.
 *
 * Not tidiness. On Windows a file with an open handle cannot be deleted, and a passing run
 * removes the whole run directory -- these logs included. Leaving the descriptors open
 * would turn every green run into a cleanup failure, which is the same footgun as the
 * stream it replaced, one step further along.
 */
function closeLogs() {
  while (openLogFds.length) {
    try {
      closeSync(openLogFds.pop());
    } catch {
      // Already closed, or never opened. Nothing here is worth failing a run over.
    }
  }
}

function trackedSpawn(label, command, args, options) {
  const child = spawn(command, args, { ...options, shell: false, windowsHide: true });
  started.push({ label, child });
  child.on('error', (error) => fail(`${label} failed to start: ${error.message}`));
  return child;
}

/**
 * Stop a child and everything it started.
 *
 * Uvicorn with `--reload` and Vite both spawn workers, and killing the parent leaves them
 * holding the port -- which would make the *next* run meet an occupied port and, worse,
 * a listening server. `taskkill /T` walks the tree on Windows; elsewhere the process group
 * is signalled.
 */
function killTree({ label, child }) {
  if (!child.pid || child.exitCode !== null || child.signalCode !== null) return;
  try {
    if (WINDOWS) {
      spawnSync('taskkill', ['/PID', String(child.pid), '/T', '/F'], { stdio: 'ignore' });
    } else {
      process.kill(-child.pid, 'SIGTERM');
    }
  } catch (error) {
    fail(`could not stop ${label}: ${error.message}`);
  }
}

function stopEverything() {
  for (const entry of started.reverse()) killTree(entry);
}

// --- The scratch environment ---------------------------------------------------------

function python(args, { capture = true } = {}) {
  const result = spawnSync(PYTHON, [E2E_ENV_SCRIPT, ...args], {
    cwd: REPO_ROOT,
    encoding: 'utf8',
    stdio: capture ? ['ignore', 'pipe', 'pipe'] : 'inherit',
  });
  if (result.error) throw result.error;
  if (result.status !== 0) {
    if (capture) {
      process.stdout.write(result.stdout || '');
      process.stderr.write(result.stderr || '');
    }
    throw new Error(`scripts/e2e_env.py ${args.join(' ')} exited ${result.status}`);
  }
  return capture ? result.stdout : '';
}

// --- Readiness -----------------------------------------------------------------------

const sleep = (ms) => new Promise((done) => setTimeout(done, ms));

async function waitForReady(url, label, child) {
  const deadline = Date.now() + READINESS_TIMEOUT_MS;
  while (Date.now() < deadline) {
    if (child.exitCode !== null) {
      throw new Error(`${label} exited with code ${child.exitCode} before it became ready.`);
    }
    try {
      const response = await fetch(url);
      if (response.ok) return;
    } catch {
      // Not up yet. The deadline is the only thing that ends this loop.
    }
    await sleep(500);
  }
  throw new Error(`${label} was not ready within ${READINESS_TIMEOUT_MS / 1000}s (${url}).`);
}

// --- Main ----------------------------------------------------------------------------

async function main() {
  const passthrough = process.argv.slice(2);

  const runId = python(['--new-run-id']).trim();
  log(`run ${runId}`);

  const backendPort = await claimPort('backend', PREFERRED_BACKEND_PORT);
  const frontendPort = await claimPort('frontend dev server', PREFERRED_FRONTEND_PORT);

  log('building the scratch database');
  python(['--reset', '--run-id', runId], { capture: false });

  const backendEnv = JSON.parse(python(['--print-env', '--run-id', runId]));
  const artifactsDir = backendEnv.E2E_ARTIFACTS_DIR;
  delete backendEnv.E2E_ARTIFACTS_DIR;
  mkdirSync(artifactsDir, { recursive: true });

  // Where the capture transport writes this run's account mail. Created here rather than
  // left to the first send, so the helper that reads it can tell "no message yet" from
  // "the transport is not configured" -- an empty directory and a missing one are
  // different failures and one of them is a harness bug.
  const mailDir = backendEnv.ACCOUNT_EMAIL_CAPTURE_DIR;
  mkdirSync(mailDir, { recursive: true });

  // Beside the artifacts directory, not inside it. Playwright empties its `outputDir`
  // when a run starts, and a log the harness is still writing to would go with it --
  // taking the evidence for a failure that happened during startup.
  const runDir = dirname(artifactsDir);
  const backendLog = join(runDir, 'backend.log');
  const viteLog = join(runDir, 'vite.log');

  // Loopback by literal address for both servers, and Vite told to bind that same address.
  // Left to itself Vite binds `localhost`, which Node resolves to `::1` alone on Windows,
  // while Chromium resolves `localhost` on its own and -- whenever its periodic IPv6 probe
  // says no -- connects over IPv4, where nothing listens. That was the RC-UAT-21 flake: one
  // module request refused (`ERR_CONNECTION_REFUSED`), a blank page, a different spec each
  // full run. With one address on both sides there is no name to resolve. Both origins are
  // passed explicitly to every party -- the proxy target, the browser base URL, and the
  // diagnostics fixture -- rather than left to three defaults that could disagree.
  const backendOrigin = `http://${LOOPBACK}:${backendPort}`;
  const frontendOrigin = `http://${LOOPBACK}:${frontendPort}`;

  log(`backend ${backendOrigin}`);
  log(`frontend ${frontendOrigin}`);

  const backend = trackedSpawn(
    'backend',
    PYTHON,
    [
      '-m',
      'uvicorn',
      'app.main:app',
      '--host',
      LOOPBACK,
      '--port',
      String(backendPort),
      '--app-dir',
      'backend',
      // DEC-0048. The suite arrives from loopback with no proxy in front of it, and a
      // believed forwarding header would let a test choose its own rate-limit bucket.
      '--no-proxy-headers',
    ],
    {
      cwd: REPO_ROOT,
      env: {
        ...process.env,
        ...backendEnv,
        // CORS is not exercised -- Vite proxies /api so the browser stays same-origin --
        // but the value is passed rather than inherited so nothing falls back to 5173.
        CORS_ORIGINS: frontendOrigin,
      },
      detached: !WINDOWS,
      stdio: appendTo(backendLog),
    },
  );

  await waitForReady(`${backendOrigin}/health/live`, 'backend', backend);
  log('backend is live');

  const vite = trackedSpawn(
    'vite',
    process.execPath,
    [VITE_CLI, '--host', LOOPBACK, '--port', String(frontendPort), '--strictPort'],
    {
      cwd: FRONTEND_ROOT,
      // The Customer Account defaults to Vietnamese (OD-71); the account specs assert the
      // English copy, so this server starts it in English. `accountVietnamese.spec.js`
      // switches to Vietnamese through the header, which is the path a customer takes.
      env: { ...process.env, VITE_API_TARGET: backendOrigin, VITE_ACCOUNT_DEFAULT_LOCALE: 'en' },
      detached: !WINDOWS,
      stdio: appendTo(viteLog),
    },
  );

  await waitForReady(frontendOrigin, 'frontend dev server', vite);
  log('frontend dev server is up');

  const playwrightEnv = {
    ...process.env,
    // What the suite asserts against, and what `globalSetup.js` uses for the handshake.
    E2E_BASE_URL: frontendOrigin,
    E2E_BACKEND_URL: backendOrigin,
    E2E_RUN_ID: runId,
    E2E_DATABASE_URL: backendEnv.DATABASE_URL,
    // Read by `tests/e2e/fixtures.js`, so the seeded references it looks up come from
    // this run's database rather than from whatever `DATABASE_URL` the shell exported.
    DATABASE_URL: backendEnv.DATABASE_URL,
    E2E_ARTIFACTS_DIR: artifactsDir,
    // Read by `tests/e2e/mailCapture.js`. The helper refuses to run without it, which is
    // what keeps it usable only inside a run this script started.
    E2E_MAIL_DIR: mailDir,
    // Consumed by `tests/e2e/diagnostics.js` on a failed test.
    E2E_BACKEND_PID: String(backend.pid),
    E2E_BACKEND_PORT: String(backendPort),
    E2E_BACKEND_LOG: backendLog,
    E2E_VITE_PID: String(vite.pid),
    E2E_VITE_PORT: String(frontendPort),
    E2E_VITE_LOG: viteLog,
  };

  log('running the suite');
  const suite = spawnSync(
    process.execPath,
    [PLAYWRIGHT_CLI, 'test', ...passthrough],
    { cwd: FRONTEND_ROOT, env: playwrightEnv, stdio: 'inherit', shell: false },
  );

  stopEverything();
  closeLogs();

  if (suite.status === 0) {
    // Only this run's directory, and only because this run succeeded. Nothing sweeps
    // `data/e2e/` looking for things to tidy: another run's preserved evidence is not
    // this run's to remove.
    python(['--destroy', '--run-id', runId], { capture: false });
    log('passed; scratch database and artifacts removed');
    return 0;
  }

  fail(`the suite failed (exit ${suite.status}).`);
  fail(`evidence preserved in ${runDir}`);
  fail('it is untracked, contains synthetic data only, and is removed with:');
  fail(`  ${PYTHON_RELATIVE} scripts/e2e_env.py --destroy --run-id ${runId}`);
  return 1;
}

for (const signal of ['SIGINT', 'SIGTERM']) {
  process.on(signal, () => {
    stopEverything();
    closeLogs();
    process.exit(130);
  });
}

main()
  .then((code) => process.exit(code))
  .catch((error) => {
    fail(error.message);
    stopEverything();
    closeLogs();
    process.exit(2);
  });
