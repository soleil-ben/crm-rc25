/**
 * The Customer Account's application boundary, asserted structurally.
 *
 * Two kinds of test live here, and the difference matters.
 *
 * **Source-level tests** read the files and assert what they import and what strings they
 * contain. That is crude, and it is right for rules of the form "this must never appear":
 * a behavioural test can only prove that `localStorage` was not written *on the path it
 * exercised*, while reading the source proves that no path writes it at all.
 *
 * **Behavioural tests** mount the real `App` at an `/account` URL and assert what reached
 * the network. Those prove the composition — that the staff provider is not above the
 * Customer Account in the tree — which no amount of reading imports can establish.
 */

import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join } from 'node:path';
import process from 'node:process';
import { describe, expect, it, beforeEach } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {
  clearBrowserStorage,
  listPageFixture,
  meFixture,
  renderAccount,
  requestedUrls,
  stubAccountFetch,
} from './accountUtils.jsx';

// From the working directory rather than from `import.meta.url`: Vitest rewrites the
// module URL, and on Windows the rewritten form is not a `file:` URL that
// `fileURLToPath` will accept. Vitest's root is `frontend/`, which is where the suite
// is configured to run from.
const ACCOUNT_DIR = join(process.cwd(), 'src', 'account');

function accountFiles(dir = ACCOUNT_DIR) {
  return readdirSync(dir).flatMap((entry) => {
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) return accountFiles(full);
    return /\.(jsx?|css)$/.test(entry) ? [full] : [];
  });
}

function sourceOf(file) {
  return readFileSync(file, 'utf8');
}

/**
 * The file with its comments removed.
 *
 * The rules below are about what the code *does*, and every one of these files documents
 * the thing it must not do — `accountApi.js` explains at length why it is not
 * `publicApi.js` and does not call `/auth/me`. Scanning the raw source would make writing
 * that explanation a test failure, which is an incentive to delete the explanation.
 *
 * Block comments cover JSDoc and CSS. A line comment is stripped only when the `//` is not
 * preceded by a colon, so a `https://` inside a string survives.
 */
function codeOf(file) {
  return readFileSync(file, 'utf8')
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/(^|[^:])\/\/.*$/gm, '$1');
}

/** Import specifiers, from the `from '...'` clauses. */
function importsOf(source) {
  return [...source.matchAll(/from\s+'([^']+)'/g)].map((match) => match[1]);
}

describe('the Customer Account has its own component tree', () => {
  const files = accountFiles();

  it('has files to check', () => {
    expect(files.length).toBeGreaterThan(10);
  });

  it('imports nothing from the staff application, features or shared components', () => {
    const offenders = [];
    files
      .filter((file) => file.endsWith('.jsx') || file.endsWith('.js'))
      .forEach((file) => {
        importsOf(sourceOf(file))
          .filter((specifier) =>
            /(\.\.\/)+(app|features|components|hooks|i18n)\//.test(specifier),
          )
          .forEach((specifier) => offenders.push(`${file} -> ${specifier}`));
      });
    expect(offenders).toEqual([]);
  });

  it('imports nothing from the public tracking application', () => {
    const offenders = [];
    files
      .filter((file) => file.endsWith('.jsx') || file.endsWith('.js'))
      .forEach((file) => {
        importsOf(sourceOf(file))
          .filter((specifier) => /(\.\.\/)+public\//.test(specifier))
          .forEach((specifier) => offenders.push(`${file} -> ${specifier}`));
      });
    expect(offenders).toEqual([]);
  });

  it('imports the shared API client nowhere', () => {
    const offenders = files.filter((file) =>
      /from\s+'[^']*api\/(client|endpoints)\.js'/.test(sourceOf(file)),
    );
    expect(offenders).toEqual([]);
  });

  it('never names the staff session provider, its hook or its permission constants', () => {
    const forbidden = ['SessionProvider', 'useSession', 'authApi', "P.CUSTOMER_READ"];
    const offenders = [];
    files.forEach((file) => {
      const source = codeOf(file);
      forbidden.forEach((needle) => {
        // `useAccountSession` and `AccountSessionProvider` legitimately contain the staff
        // names as substrings, so the check is for the staff name *not* preceded by
        // "Account" or "useAccount".
        const pattern = new RegExp(`(?<!Account)(?<!useAccount)\\b${needle}\\b`);
        if (pattern.test(source)) offenders.push(`${file}: ${needle}`);
      });
    });
    expect(offenders).toEqual([]);
  });

  it('never writes to localStorage or sessionStorage', () => {
    const offenders = files.filter((file) => /localStorage|sessionStorage/.test(codeOf(file)));
    expect(offenders).toEqual([]);
  });

  it('never requests a staff or public endpoint', () => {
    const offenders = [];
    files.forEach((file) => {
      const source = codeOf(file);
      if (/['"`]\/api\/v1\/public\//.test(source)) offenders.push(`${file}: public api`);
      if (/['"`]\/auth\//.test(source)) offenders.push(`${file}: /auth`);
      // Any `/api/v1/...` literal that is not the account prefix.
      [...source.matchAll(/['"`](\/api\/v1\/[^'"`]*)['"`]/g)].forEach((match) => {
        if (!match[1].startsWith('/api/v1/account')) offenders.push(`${file}: ${match[1]}`);
      });
    });
    expect(offenders).toEqual([]);
  });

  it('uses the account CSRF header and cookie, and never the staff ones', () => {
    const client = sourceOf(join(ACCOUNT_DIR, 'accountApi.js'));
    expect(client).toContain('solaris_account_csrf');
    expect(client).toContain('X-Account-CSRF-Token');
    // The staff names, as whole tokens. `solaris_account_csrf` contains neither.
    expect(client).not.toMatch(/'solaris_csrf'/);
    expect(client).not.toMatch(/'X-CSRF-Token'/);
  });

  it('uses no literal colour, so the corrected tokens cannot be bypassed', () => {
    const css = codeOf(join(ACCOUNT_DIR, 'account.css'));
    // No hex, no rgb(), no hsl(). Every colour is a var() from tokens.css.
    expect(css).not.toMatch(/#[0-9a-fA-F]{3,8}\b/);
    expect(css).not.toMatch(/\brgba?\(/);
    expect(css).not.toMatch(/\bhsla?\(/);
  });

  it('never uses the reference orange, which fails AA', () => {
    const offenders = files.filter((file) => /brand-orange-ref/.test(codeOf(file)));
    expect(offenders).toEqual([]);
  });

  // OD-71 (2026-10-20) supersedes OD-39: the account is Vietnamese first with an English
  // option, and the switch lives in the layout header. It must keep the choice in memory.
  it('offers a language switch in the layout, and stores the choice nowhere', () => {
    const layout = codeOf(join(ACCOUNT_DIR, 'AccountLayout.jsx'));
    expect(layout).toMatch(/<LanguageSwitch \/>/);
    expect(layout).toMatch(/aria-pressed/);
    const provider = codeOf(join(ACCOUNT_DIR, 'i18n.jsx'));
    expect(provider).not.toMatch(/localStorage|sessionStorage|indexedDB/);
  });
});

describe('the Customer Account mounts no other surface', () => {
  beforeEach(clearBrowserStorage);

  it('never requests /auth/me, even when signed in', async () => {
    const { calls } = stubAccountFetch([
      { path: '/api/v1/account/me', body: meFixture() },
      { path: '/api/v1/account/shipments', body: listPageFixture() },
    ]);

    renderAccount('/account/shipments');
    await screen.findByRole('heading', { name: 'My shipments', level: 1 });

    expect(requestedUrls(calls).filter((url) => url.includes('/auth/'))).toEqual([]);
  });

  it('requests only /api/v1/account paths', async () => {
    const { calls } = stubAccountFetch([
      { path: '/api/v1/account/me', body: meFixture() },
      { path: '/api/v1/account/shipments', body: listPageFixture() },
    ]);

    renderAccount('/account/shipments');
    await screen.findByRole('heading', { name: 'My shipments', level: 1 });

    requestedUrls(calls).forEach((url) => {
      expect(url.startsWith('/api/v1/account')).toBe(true);
    });
  });

  it('makes no request to any external origin', async () => {
    const { calls } = stubAccountFetch([
      { path: '/api/v1/account/me', body: meFixture() },
      { path: '/api/v1/account/shipments', body: listPageFixture() },
    ]);

    renderAccount('/account/shipments');
    await screen.findByRole('heading', { name: 'My shipments', level: 1 });

    requestedUrls(calls).forEach((url) => {
      expect(url).not.toMatch(/^https?:\/\//);
    });
  });

  it('writes nothing to localStorage or sessionStorage', async () => {
    stubAccountFetch([
      { path: '/api/v1/account/me', body: meFixture() },
      { path: '/api/v1/account/shipments', body: listPageFixture() },
    ]);

    renderAccount('/account/shipments');
    await screen.findByRole('heading', { name: 'My shipments', level: 1 });

    expect(window.localStorage.length).toBe(0);
    expect(window.sessionStorage.length).toBe(0);
  });

  it('shows no staff navigation', async () => {
    stubAccountFetch([
      { path: '/api/v1/account/me', body: meFixture() },
      { path: '/api/v1/account/shipments', body: listPageFixture() },
    ]);

    renderAccount('/account/shipments');
    await screen.findByRole('heading', { name: 'My shipments', level: 1 });

    ['Dashboard', 'Customers', 'Segments', 'Follow-ups', 'Reports', 'Settings'].forEach(
      (label) => {
        expect(screen.queryByRole('link', { name: label })).toBeNull();
      },
    );
    // "Portal" is staff terminology and must not appear on this surface at all.
    expect(document.body.textContent).not.toMatch(/\bPortal\b/);
  });

  it('sends the account CSRF header on a state-changing request, and not the staff one', async () => {
    document.cookie = 'solaris_account_csrf=account-token-value';
    document.cookie = 'solaris_csrf=staff-token-value';

    const { calls } = stubAccountFetch([
      { path: '/api/v1/account/me', status: 401, body: { code: 'unauthenticated', message: 'Sign in to continue.', field: null } },
      {
        path: '/api/v1/account/password/forgot',
        method: 'POST',
        body: { message: 'If that address has an account, we have sent a message to it.' },
      },
    ]);

    const user = userEvent.setup();
    renderAccount('/account/forgot-password');
    await user.type(await screen.findByLabelText(/Email address/), 'someone@example.com');
    await user.click(screen.getByRole('button', { name: 'Send the reset link' }));

    await waitFor(() => {
      expect(calls.some((call) => call.method === 'POST')).toBe(true);
    });
    const post = calls.find((call) => call.method === 'POST');
    expect(post.headers['X-Account-CSRF-Token']).toBe('account-token-value');
    expect(post.headers['X-CSRF-Token']).toBeUndefined();
  });
});
