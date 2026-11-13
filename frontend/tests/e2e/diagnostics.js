/**
 * Failure-only diagnostic capture.
 *
 * Phase 6 recorded one unexplained failure: `staffKeyboard.spec.js:212`, on a **blank
 * rendered page**, with no backend error and no Vite error in either log. It did not
 * reproduce. The evidence retained at the time -- a screenshot of a blank page and a
 * trace -- could not distinguish between a product defect, a dev-server defect, a
 * navigation that never completed, and a document that was served but never executed.
 *
 * This module exists so that if it happens again, the next person is not guessing. It
 * collects, **only when a test has already failed**, the evidence that would separate
 * those cases:
 *
 * | Question | Evidence collected |
 * |---|---|
 * | Did the document arrive at all? | main-document response status and content type |
 * | Did the browser go where the test thought? | the page's current URL at failure |
 * | Did the module graph load? | failed requests, aborted requests |
 * | Did the application throw? | uncaught `pageerror`, console messages |
 * | Did React mount? | a bounded, **structural** DOM snapshot of `#root` and `body` |
 * | Was the dev server alive and healthy? | Vite process status and a redacted log window |
 * | Was the API alive? | backend process status and a redacted log window |
 * | Do browser and server evidence line up? | ISO timestamps on every record, one clock sample |
 *
 * ## What this deliberately does not do
 *
 * * **It does not weaken any assertion.** It adds no wait, no poll, no fallback and no
 *   `catch` that would let a failing expectation pass. Every capture runs *after* the
 *   test body has finished and its status is already decided.
 * * **It does not enable retries.** `retries` stays 0 in `playwright.config.js`. A
 *   diagnostic that made the failure survivable would destroy the thing it is measuring.
 * * **It does not add a sleep.** The one bounded wait here is the TCP probe's connect
 *   timeout, and it runs only on a test that has already failed.
 * * **It costs a passing run nothing but two event listeners** and four bounded arrays.
 *
 * ## What it must never capture
 *
 * Credentials, session cookies, CSRF values, customer information, tracking references,
 * CSV contents, and complete sensitive responses. So: **no header is ever read except a
 * response's content type**, no response body is ever read, no request body is ever read,
 * and no DOM *text* is ever read -- the snapshot records tag names, a safe subset of
 * attributes, and the *length* of text, never the text. Everything recorded still passes
 * through `redact()` as a second line of defence, because the first line being sufficient
 * is a claim rather than a guarantee.
 */

import net from 'node:net';
import { readFileSync, statSync, writeFileSync } from 'node:fs';
import { test as base, expect } from '@playwright/test';

/** Caps. A diagnostic that can grow without bound is its own outage. */
const LIMITS = {
  consoleMessages: 120,
  messageChars: 400,
  pageErrors: 25,
  errorChars: 800,
  failedRequests: 60,
  documentResponses: 20,
  logLines: 120,
  // Generous on purpose: the backend logs one JSON object per line and its `ts` field
  // sits at the end, so a tight clamp would remove the very timestamp that makes a
  // server line correlatable with a browser event.
  logLineChars: 600,
  domChars: 6000,
  domNodes: 400,
};

// --- Redaction -------------------------------------------------------------------------

/**
 * Patterns that must never reach an artifact. Order matters: the broad secret-ish rule
 * runs last so the specific rules can label what they removed.
 */
const REDACTIONS = [
  // A Solaris public reference. A tracking reference is customer-identifying by design,
  // which is the whole reason the public page carries a no-referrer policy.
  [/\bSX-[A-Z]{2,4}-[A-Z0-9]{6,}\b/g, 'SX-<redacted>'],
  [/[\w.+-]+@[\w-]+\.[\w.-]+/g, '<email redacted>'],
  // Cookie material, in any casing, however it is spelled in a log line.
  // `(?:bearer\s+)?` matters: without it, `Authorization: Bearer eyJhb...` consumes only
  // the word "Bearer" and leaves the token sitting in the artifact. Found by
  // `tests/e2eDiagnostics.test.js`, which is the reason that file exists.
  [
    /\b(set-cookie|cookie|authorization|x-csrf-token|csrf[_-]?token)\b\s*[:=]\s*(?:bearer\s+)?\S+/gi,
    '$1=<redacted>',
  ],
  [/\bsolaris_session=\S+/gi, 'solaris_session=<redacted>'],
  // Anything that calls itself a secret, token, password or key.
  [/\b(password|passwd|secret|token|api[_-]?key|bearer)\b\s*[:=]?\s*\S+/gi, '$1 <redacted>'],
];

/** Remove anything sensitive from a string. Always applied, to every captured string. */
export function redact(value) {
  if (value == null) return value;
  let out = String(value);
  for (const [pattern, replacement] of REDACTIONS) out = out.replace(pattern, replacement);
  return out;
}

/** Truncate with an explicit marker, so a short record is never mistaken for a whole one. */
function clamp(value, max) {
  const text = String(value ?? '');
  return text.length <= max ? text : `${text.slice(0, max)}... [${text.length - max} more chars]`;
}

/**
 * A URL safe to record: origin and path only.
 *
 * The query string is dropped rather than redacted. Staff search and report filters put
 * customer-supplied text in `?q=`, and a redaction list is a guess about what those will
 * contain; the names of the parameters answer the diagnostic question -- "was this the
 * filtered request or the bare one?" -- without the values.
 */
export function safeUrl(rawUrl) {
  try {
    const parsed = new URL(rawUrl);
    const params = [...parsed.searchParams.keys()];
    const query = params.length ? `?<${params.length} param(s): ${params.join(',')}>` : '';
    return redact(`${parsed.origin}${parsed.pathname}${query}${parsed.hash ? '#<hash>' : ''}`);
  } catch {
    return redact(clamp(rawUrl, 200));
  }
}

// --- Process and port probes -----------------------------------------------------------

/** Is a process with this pid alive? Signal 0 checks for existence without signalling. */
function pidAlive(pid) {
  if (!pid) return null;
  try {
    process.kill(Number(pid), 0);
    return true;
  } catch (error) {
    // EPERM means it exists and belongs to somebody else, which is still "alive".
    return error.code === 'EPERM';
  }
}

/** Can something accept a TCP connection on this port? Bounded, and only run on failure. */
function portListening(port, timeoutMs = 1500) {
  return new Promise((resolve) => {
    const socket = new net.Socket();
    const finish = (result) => {
      socket.destroy();
      resolve(result);
    };
    socket.setTimeout(timeoutMs);
    socket.once('connect', () => finish(true));
    socket.once('timeout', () => finish(false));
    socket.once('error', () => finish(false));
    // The host the browser uses: `run_e2e.mjs` binds Vite to the literal loopback address
    // in `E2E_BASE_URL`, so this probe asks the same question the browser does.
    socket.connect(Number(port), probeHost());
  });
}

function probeHost() {
  try {
    return new URL(process.env.E2E_BASE_URL).hostname.replace(/^\[|\]$/g, '');
  } catch {
    return 'localhost';
  }
}

/**
 * The tail of a process log, redacted and bounded.
 *
 * `windowStartIso` is recorded alongside so the reader knows which window of the run this
 * is; the lines are not filtered by timestamp, because uvicorn's access log and Vite's
 * output use different formats and a parser that guessed wrong would silently drop the
 * evidence. The tail plus both timestamps is the honest version.
 */
function readLogTail(path, sinceIso) {
  if (!path) return { path: null, available: false, reason: 'no log path configured' };
  try {
    const stats = statSync(path);
    const lines = readFileSync(path, 'utf8').split(/\r?\n/).filter(Boolean);
    return {
      path,
      available: true,
      sizeBytes: stats.size,
      modifiedAtIso: stats.mtime.toISOString(),
      windowStartIso: sinceIso,
      note: `last ${Math.min(lines.length, LIMITS.logLines)} line(s) of the file, redacted`,
      lines: lines.slice(-LIMITS.logLines).map((line) => clamp(redact(line), LIMITS.logLineChars)),
    };
  } catch (error) {
    return { path, available: false, reason: clamp(error.message, 200) };
  }
}

/**
 * Status of one of the two stack processes.
 *
 * Both are started outside Playwright (`playwright.config.js` explains why there is no
 * `webServer` block), so a run is *told* about them through the environment rather than
 * owning them. When it is not told, that is reported as unknown rather than guessed.
 */
async function processStatus({ label, pidEnv, portEnv, defaultPort, logEnv }, sinceIso) {
  const pid = process.env[pidEnv];
  const port = process.env[portEnv] || defaultPort;
  return {
    label,
    pid: pid ? Number(pid) : null,
    pidSource: pid ? pidEnv : `${pidEnv} not set -- process not started by the harness`,
    processAlive: pidAlive(pid),
    port: Number(port),
    portListening: await portListening(port),
    log: readLogTail(process.env[logEnv], sinceIso),
  };
}

// --- The structural DOM snapshot --------------------------------------------------------

/**
 * A snapshot that answers "did anything render?" without recording what was rendered.
 *
 * Text is reduced to its length. Attributes are limited to the ones that identify
 * structure, and even those are clamped. A customer's name is text, and text never
 * leaves the browser here.
 */
function snapshotStructure({ maxNodes, maxChars }) {
  const KEEP = ['id', 'class', 'role', 'type', 'data-testid', 'aria-label', 'aria-hidden'];
  let budget = maxNodes;

  const describe = (node, depth) => {
    if (budget <= 0 || depth > 12) return '';
    budget -= 1;
    const pad = '  '.repeat(depth);
    const attrs = KEEP.filter((name) => node.hasAttribute && node.hasAttribute(name))
      .map((name) => `${name}="${String(node.getAttribute(name)).slice(0, 60)}"`)
      .join(' ');
    const ownText = [...node.childNodes]
      .filter((child) => child.nodeType === 3)
      .map((child) => child.textContent.trim())
      .join('').length;
    const head =
      `${pad}<${node.tagName.toLowerCase()}${attrs ? ` ${attrs}` : ''}>` +
      (ownText ? ` [text: ${ownText} chars]` : '');
    const children = [...node.children].map((child) => describe(child, depth + 1)).filter(Boolean);
    return [head, ...children].join('\n');
  };

  const root = document.getElementById('root');
  const body = document.body;
  return {
    readyState: document.readyState,
    title: document.title,
    documentElementChildCount: document.documentElement.childElementCount,
    bodyChildCount: body ? body.childElementCount : null,
    bodyTextLength: body ? body.innerText.length : null,
    bodyHtmlLength: body ? body.innerHTML.length : null,
    rootPresent: Boolean(root),
    rootChildCount: root ? root.childElementCount : null,
    rootHtmlLength: root ? root.innerHTML.length : null,
    // The single most useful bit for a blank page: the shell is there, but empty.
    looksBlank: Boolean(root) && root.childElementCount === 0,
    scriptCount: document.scripts.length,
    stylesheetCount: document.styleSheets.length,
    visibilityState: document.visibilityState,
    structure: body ? describe(body, 0).slice(0, maxChars) : null,
    browserNowIso: new Date().toISOString(),
    browserNowMs: Date.now(),
  };
}

// --- The fixture -------------------------------------------------------------------------

/**
 * `test` with failure-only diagnostics attached.
 *
 * Import this instead of `@playwright/test` in a spec. `expect` is re-exported unchanged,
 * so the import is a one-line change and no assertion behaviour moves.
 */
export const test = base.extend({
  // Playwright names this second parameter `use` by convention. It is positional, and
  // `react-hooks/rules-of-hooks` reads a function called `use` as a React Hook called
  // from a non-component, so it is named `runTest` here. Renaming it keeps the lint rule
  // switched on for every other test file, which is worth more than the convention.
  page: async ({ page }, runTest, testInfo) => {
    const testStartedAtMs = Date.now();
    const testStartedAtIso = new Date(testStartedAtMs).toISOString();

    const consoleMessages = [];
    const pageErrors = [];
    const failedRequests = [];
    const documentResponses = [];

    const stamp = () => ({
      atIso: new Date().toISOString(),
      msSinceTestStart: Date.now() - testStartedAtMs,
    });

    const push = (list, limit, record) => {
      if (list.length < limit) list.push(record);
      else if (list.length === limit) list.push({ note: `... further records dropped at ${limit}` });
    };

    page.on('console', (message) => {
      const location = message.location();
      push(consoleMessages, LIMITS.consoleMessages, {
        ...stamp(),
        type: message.type(),
        text: clamp(redact(message.text()), LIMITS.messageChars),
        location: location && location.url ? safeUrl(location.url) : null,
      });
    });

    page.on('pageerror', (error) => {
      push(pageErrors, LIMITS.pageErrors, {
        ...stamp(),
        name: error.name,
        message: clamp(redact(error.message), LIMITS.messageChars),
        stack: clamp(redact(error.stack || ''), LIMITS.errorChars),
      });
    });

    page.on('requestfailed', (request) => {
      const failure = request.failure();
      const text = failure ? failure.errorText : 'unknown';
      push(failedRequests, LIMITS.failedRequests, {
        ...stamp(),
        url: safeUrl(request.url()),
        method: request.method(),
        resourceType: request.resourceType(),
        errorText: clamp(redact(text), 200),
        // Chromium reports a cancelled request as ERR_ABORTED. A navigation that
        // supersedes another produces one legitimately, so these are separated rather
        // than lumped in with genuine network failures.
        aborted: text.includes('ERR_ABORTED'),
      });
    });

    page.on('response', (response) => {
      const request = response.request();
      if (request.resourceType() !== 'document') return;
      if (request.frame() !== page.mainFrame()) return;
      push(documentResponses, LIMITS.documentResponses, {
        ...stamp(),
        url: safeUrl(response.url()),
        status: response.status(),
        statusText: clamp(response.statusText(), 80),
        // The only header read anywhere in this module.
        contentType: response.headers()['content-type'] || null,
        fromServiceWorker: response.fromServiceWorker(),
      });
    });

    await runTest(page);

    // ---- Everything below runs only after the test body finished, and only if it failed.
    if (testInfo.status === testInfo.expectedStatus) return;

    let dom = null;
    let currentUrl = null;
    try {
      currentUrl = safeUrl(page.url());
      // A closed or crashed page cannot be evaluated; that is itself the finding, and it
      // is recorded as one rather than being allowed to mask the real failure.
      dom = await page.evaluate(snapshotStructure, {
        maxNodes: LIMITS.domNodes,
        maxChars: LIMITS.domChars,
      });
      if (dom && dom.structure) dom.structure = redact(dom.structure);
      if (dom && dom.title) dom.title = redact(dom.title);
    } catch (error) {
      dom = { unavailable: true, reason: clamp(redact(error.message), 300) };
    }

    const capturedAtMs = Date.now();
    const report = {
      schema: 'solaris-e2e-failure-diagnostics/1',
      test: {
        title: testInfo.title,
        file: testInfo.titlePath[0],
        line: testInfo.line,
        project: testInfo.project.name,
        status: testInfo.status,
        expectedStatus: testInfo.expectedStatus,
        retry: testInfo.retry,
        durationMs: testInfo.duration,
        errors: testInfo.errors.map((error) => ({
          message: clamp(redact(error.message || ''), LIMITS.errorChars),
        })),
      },
      // Browser records carry `msSinceTestStart`; server logs carry their own wall clock.
      // Both anchors are recorded here so the two can be lined up without guessing.
      timing: {
        testStartedAtIso,
        capturedAtIso: new Date(capturedAtMs).toISOString(),
        elapsedMs: capturedAtMs - testStartedAtMs,
        nodeNowMs: capturedAtMs,
        browserNowMs: dom && dom.browserNowMs ? dom.browserNowMs : null,
        browserMinusNodeMs: dom && dom.browserNowMs ? dom.browserNowMs - capturedAtMs : null,
      },
      page: {
        currentUrl,
        mainDocumentResponses: documentResponses,
        dom,
      },
      browser: {
        consoleMessages,
        pageErrors,
        failedRequests: failedRequests.filter((record) => !record.aborted),
        abortedRequests: failedRequests.filter((record) => record.aborted),
      },
      stack: {
        vite: await processStatus(
          {
            label: 'Vite dev server',
            pidEnv: 'E2E_VITE_PID',
            portEnv: 'E2E_VITE_PORT',
            defaultPort: 5173,
            logEnv: 'E2E_VITE_LOG',
          },
          testStartedAtIso,
        ),
        backend: await processStatus(
          {
            label: 'FastAPI backend',
            pidEnv: 'E2E_BACKEND_PID',
            portEnv: 'E2E_BACKEND_PORT',
            defaultPort: 8000,
            logEnv: 'E2E_BACKEND_LOG',
          },
          testStartedAtIso,
        ),
      },
    };

    // Written to the output directory rather than attached from memory: an attachment
    // with a `body` lives in the report only, and the evidence for an intermittent
    // failure has to survive on disk next to the trace and the screenshot that go with
    // it. `testInfo.outputPath` is the same per-test directory Playwright puts those in.
    const target = testInfo.outputPath('failure-diagnostics.json');
    writeFileSync(target, JSON.stringify(report, null, 2), 'utf8');
    await testInfo.attach('failure-diagnostics.json', {
      path: target,
      contentType: 'application/json',
    });
  },
});

export { expect };
