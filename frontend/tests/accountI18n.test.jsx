/**
 * The Customer Account's two languages (OD-71: Vietnamese first, English as an option).
 *
 * Catalogue checks read `src/account/i18n/en.js` and `vi.js`; the source check reads every
 * file under `src/account` for the keys it asks for; the behavioural checks mount the real
 * `App` and drive the header switch.
 */

import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join } from 'node:path';
import process from 'node:process';
import { beforeEach, describe, expect, it } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import en from '../src/account/i18n/en.js';
import vi from '../src/account/i18n/vi.js';
import {
  defaultAccountLocale,
  localizeAccountError,
  translate,
} from '../src/account/i18n.jsx';
import { AccountApiError } from '../src/account/accountApi.js';
import {
  clearBrowserStorage,
  listPageFixture,
  meFixture,
  renderAccount,
  stubAccountFetch,
} from './accountUtils.jsx';

const ACCOUNT_DIR = join(process.cwd(), 'src', 'account');

const SIGNED_OUT = {
  path: '/api/v1/account/me',
  status: 401,
  body: { code: 'unauthenticated', message: 'Sign in to continue.', field: null },
};

/**
 * Values that are the same in both languages on purpose: names, and the label each
 * language button carries in its own language.
 */
const SAME_IN_BOTH = new Set(['Solaris Express', 'Tiếng Việt', 'English']);

function sourceFiles(dir = ACCOUNT_DIR) {
  return readdirSync(dir).flatMap((entry) => {
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) return entry === 'i18n' ? [] : sourceFiles(full);
    return /\.jsx?$/.test(entry) ? [full] : [];
  });
}

/** Comments out, so a key named in an explanation is not mistaken for a use. */
function codeOf(file) {
  return readFileSync(file, 'utf8')
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/(^|[^:])\/\/.*$/gm, '$1');
}

describe('the catalogues', () => {
  it('have exactly the same keys', () => {
    const enKeys = Object.keys(en).sort();
    const viKeys = Object.keys(vi).sort();
    expect(viKeys.filter((key) => !(key in en))).toEqual([]);
    expect(enKeys.filter((key) => !(key in vi))).toEqual([]);
  });

  it('have no empty value in either language', () => {
    const empty = [...Object.entries(en), ...Object.entries(vi)]
      .filter(([, value]) => typeof value !== 'string' || value.trim() === '')
      .map(([key]) => key);
    expect(empty).toEqual([]);
  });

  it('leave nothing longer than 12 characters untranslated in Vietnamese', () => {
    const untranslated = Object.keys(en).filter(
      (key) => vi[key] === en[key] && en[key].length > 12 && !SAME_IN_BOTH.has(en[key]),
    );
    expect(untranslated).toEqual([]);
  });

  it('use the same placeholders in both languages', () => {
    const placeholders = (value) => [...value.matchAll(/\{(\w+)\}/g)].map((m) => m[1]).sort();
    const mismatched = Object.keys(en).filter(
      (key) => JSON.stringify(placeholders(en[key])) !== JSON.stringify(placeholders(vi[key])),
    );
    expect(mismatched).toEqual([]);
  });

  it('carry the review note on the Vietnamese file', () => {
    const source = readFileSync(join(ACCOUNT_DIR, 'i18n', 'vi.js'), 'utf8');
    expect(source).toMatch(/awaiting review by Vietnamese-speaking staff/i);
  });
});

describe('every key the account asks for exists', () => {
  const prefixes = [...new Set(Object.keys(en).map((key) => key.split('.')[0]))];
  const keyPattern = new RegExp(`^(${prefixes.join('|')})\\.[A-Za-z0-9_.]+$`);

  it('finds t() calls to check', () => {
    const calls = sourceFiles().flatMap((file) => [
      ...codeOf(file).matchAll(/\bt\(\s*'([^']+)'/g),
    ]);
    expect(calls.length).toBeGreaterThan(200);
  });

  it('defines every literal t() key and every key-shaped string', () => {
    const missing = [];
    sourceFiles().forEach((file) => {
      const code = codeOf(file);
      for (const match of code.matchAll(/\bt\(\s*'([^']+)'/g)) {
        if (!(match[1] in en)) missing.push(`${file}: ${match[1]}`);
      }
      // Keys kept in maps (`labelKey: 'list.statusDelivered'`) are strings of the same shape.
      for (const match of code.matchAll(/'([A-Za-z0-9_.]+)'/g)) {
        if (keyPattern.test(match[1]) && !(match[1] in en)) {
          missing.push(`${file}: ${match[1]}`);
        }
      }
    });
    expect(missing).toEqual([]);
  });

  it('defines the keys built from a code', () => {
    ['vi', 'en'].forEach((code) => expect(en[`language.${code}`]).toBeTruthy());
    ['', 'Billing'].forEach((which) =>
      ['Country', 'Line1', 'City', 'Province'].forEach((part) =>
        expect(en[`register.missing${which}${part}`]).toBeTruthy(),
      ),
    );
  });
});

describe('translate()', () => {
  it('interpolates {name} and falls back to English, then to the key', () => {
    expect(translate('vi', 'common.useAtLeast', { count: 12 })).toBe(
      'Vui lòng dùng ít nhất 12 ký tự.',
    );
    expect(translate('en', 'common.useAtLeast', { count: 12 })).toBe('Use at least 12 characters.');
    expect(translate('xx', 'common.signIn')).toBe('Sign in');
    expect(translate('vi', 'no.such.key')).toBe('no.such.key');
  });
});

describe('choosing the language', () => {
  beforeEach(clearBrowserStorage);

  it('defaults to Vietnamese unless the build names en or vi', () => {
    expect(defaultAccountLocale({})).toBe('vi');
    expect(defaultAccountLocale({ VITE_ACCOUNT_DEFAULT_LOCALE: 'fr' })).toBe('vi');
    expect(defaultAccountLocale({ VITE_ACCOUNT_DEFAULT_LOCALE: 'en' })).toBe('en');
    expect(defaultAccountLocale({ VITE_ACCOUNT_DEFAULT_LOCALE: 'vi' })).toBe('vi');
  });

  it('opens in Vietnamese when nothing says otherwise', async () => {
    stubAccountFetch([SIGNED_OUT]);
    renderAccount('/account/sign-in', { locale: null });

    expect(
      await screen.findByRole('heading', { name: 'Đăng nhập', level: 1 }),
    ).toBeInTheDocument();
    expect(document.documentElement.lang).toBe('vi');
    expect(screen.getByRole('button', { name: 'Tiếng Việt' })).toHaveAttribute(
      'aria-pressed',
      'true',
    );
  });

  it('switches to English and back, and stores nothing in the browser', async () => {
    const user = userEvent.setup();
    stubAccountFetch([SIGNED_OUT]);
    renderAccount('/account/sign-in', { locale: null });
    await screen.findByRole('heading', { name: 'Đăng nhập', level: 1 });

    const switcher = screen.getByRole('group', { name: 'Ngôn ngữ' });
    await user.click(within(switcher).getByRole('button', { name: 'English' }));

    expect(await screen.findByRole('heading', { name: 'Sign in', level: 1 })).toBeInTheDocument();
    expect(screen.getByLabelText('Email address')).toBeInTheDocument();
    expect(document.documentElement.lang).toBe('en');
    expect(screen.getByRole('button', { name: 'English' })).toHaveAttribute('aria-pressed', 'true');

    await user.click(screen.getByRole('button', { name: 'Tiếng Việt' }));
    expect(await screen.findByRole('heading', { name: 'Đăng nhập', level: 1 })).toBeInTheDocument();
    expect(screen.getByLabelText('Địa chỉ email')).toBeInTheDocument();

    expect(window.localStorage.length).toBe(0);
    expect(window.sessionStorage.length).toBe(0);
  });

  it("follows a signed-in identity's preferred language", async () => {
    stubAccountFetch([
      { path: '/api/v1/account/me', body: meFixture({ preferred_language: 'vi' }) },
      { path: '/api/v1/account/shipments', body: listPageFixture() },
    ]);
    // English is the starting point here; the preference must win over it.
    renderAccount('/account/shipments', { locale: 'en' });

    expect(
      await screen.findByRole('heading', { name: 'Lô hàng của tôi', level: 1 }),
    ).toBeInTheDocument();
    expect(document.documentElement.lang).toBe('vi');
  });

  it('lets the switch beat the preference for the rest of the page view', async () => {
    const user = userEvent.setup();
    stubAccountFetch([
      { path: '/api/v1/account/me', body: meFixture({ preferred_language: 'vi' }) },
      { path: '/api/v1/account/shipments', body: listPageFixture() },
    ]);
    renderAccount('/account/shipments', { locale: null });
    await screen.findByRole('heading', { name: 'Lô hàng của tôi', level: 1 });

    await user.click(screen.getByRole('button', { name: 'English' }));
    expect(
      await screen.findByRole('heading', { name: 'My shipments', level: 1 }),
    ).toBeInTheDocument();
    // Navigating within the account keeps the choice.
    await user.click(screen.getByRole('link', { name: 'My profile' }));
    await waitFor(() => expect(document.documentElement.lang).toBe('en'));
  });

  it('translates server status and route labels in Vietnamese', async () => {
    stubAccountFetch([
      { path: '/api/v1/account/me', body: meFixture({ preferred_language: 'vi' }) },
      { path: '/api/v1/account/shipments', body: listPageFixture() },
    ]);
    renderAccount('/account/shipments', { locale: null });
    await screen.findByRole('heading', { name: 'Lô hàng của tôi', level: 1 });

    expect((await screen.findAllByText('Đang vận chuyển')).length).toBeGreaterThan(0);
    expect(screen.getAllByText('Canada đến Việt Nam').length).toBeGreaterThan(0);
    expect(screen.queryByText('In transit')).toBeNull();
  });
});

/** An error as the API client builds it: the server's English sentence in `message`. */
function apiError(status, overrides = {}) {
  return new AccountApiError({
    status,
    code: 'some_code',
    message: 'The server said this in English.',
    field: null,
    ...overrides,
  });
}

describe('server sentences on a Vietnamese screen', () => {
  const vi_ = (error, options) => localizeAccountError('vi', error, options);

  it('shows the server sentence unchanged in English', () => {
    expect(localizeAccountError('en', apiError(422))).toBe('The server said this in English.');
    expect(localizeAccountError('en', apiError(429, { retryAfterSeconds: 9 }))).toBe(
      'The server said this in English.',
    );
  });

  it('never shows the English in Vietnamese, and chooses by status', () => {
    const cases = [
      [apiError(422), vi['api.422']],
      [apiError(400), vi['api.422']],
      [apiError(401), vi['api.401']],
      [apiError(403), vi['api.403']],
      [apiError(404), vi['api.404']],
      [apiError(409), vi['api.409']],
      [apiError(429), vi['api.429']],
      [apiError(503), vi['api.503']],
      [apiError(500), vi['api.generic']],
      [apiError(0, { code: 'network_error' }), vi['api.network']],
      [new Error('boom'), vi['api.generic']],
    ];
    cases.forEach(([error, expected]) => {
      expect(vi_(error)).toBe(expected);
      expect(vi_(error)).not.toContain('English');
    });
  });

  it('says how long to wait when the server says so', () => {
    expect(vi_(apiError(429, { retryAfterSeconds: 42 }))).toBe(
      'Quá nhiều yêu cầu. Vui lòng đợi khoảng 42 giây rồi thử lại.',
    );
  });

  it("uses the page's own sentence for a field it maps, and a field sentence otherwise", () => {
    const fieldMessage = (field) => (field === 'email' ? 'EMAIL SENTENCE' : null);
    expect(vi_(apiError(422, { field: 'email' }), { fieldMessage })).toBe('EMAIL SENTENCE');
    expect(vi_(apiError(422, { field: 'phone' }), { fieldMessage })).toBe(vi['api.field']);
    expect(vi_(apiError(422, { field: 'token' }))).toBe(vi['common.linkInvalid']);
  });

  it('keeps sign-in failures generic whatever the status', () => {
    [401, 403, 422, 423, 500].forEach((status) =>
      expect(vi_(apiError(status), { context: 'signIn' })).toBe(vi['signIn.genericFailure']),
    );
    // A throttle and a network failure are still said as themselves.
    expect(vi_(apiError(429), { context: 'signIn' })).toBe(vi['api.429']);
    expect(vi_(apiError(0, { code: 'network_error' }), { context: 'signIn' })).toBe(
      vi['api.network'],
    );
  });
});

describe('pages word server outcomes in the screen language', () => {
  beforeEach(clearBrowserStorage);

  it('sign in: a refusal reads generically in Vietnamese', async () => {
    const user = userEvent.setup();
    stubAccountFetch([
      SIGNED_OUT,
      {
        path: '/api/v1/account/sign-in',
        method: 'POST',
        status: 401,
        body: {
          code: 'authentication_failed',
          message: 'Email or password is incorrect.',
          field: null,
        },
      },
    ]);
    renderAccount('/account/sign-in', { locale: null });
    await user.type(await screen.findByLabelText('Địa chỉ email'), 'a@example.com');
    await user.type(screen.getByLabelText('Mật khẩu'), 'not-the-password');
    await user.click(screen.getByRole('button', { name: 'Đăng nhập' }));

    expect(await screen.findByText('Email hoặc mật khẩu không đúng.')).toBeInTheDocument();
    expect(screen.queryByText('Email or password is incorrect.')).toBeNull();

    // And it follows the switch, because the error is kept, not its words.
    await user.click(screen.getByRole('button', { name: 'English' }));
    expect(await screen.findByText('Email or password is incorrect.')).toBeInTheDocument();
  });

  it('shipment list: a refusal is worded in Vietnamese', async () => {
    stubAccountFetch([
      { path: '/api/v1/account/me', body: meFixture({ preferred_language: 'vi' }) },
      {
        path: '/api/v1/account/shipments',
        status: 403,
        body: {
          code: 'account_unavailable',
          message: 'Shipment history is not available for this account.',
          field: null,
        },
      },
    ]);
    renderAccount('/account/shipments', { locale: null });
    expect(await screen.findByText(vi['api.403'])).toBeInTheDocument();
    expect(screen.queryByText('Shipment history is not available for this account.')).toBeNull();
  });

  it('verify email: the success sentence is the catalogue one in Vietnamese', async () => {
    window.location.hash = '';
    stubAccountFetch([
      SIGNED_OUT,
      {
        path: '/api/v1/account/verify-email',
        method: 'POST',
        body: { message: 'Your email address is confirmed. An English server sentence.' },
      },
    ]);
    renderAccount('/account/verify-email?token=abc', { locale: 'vi' });
    expect(await screen.findByText(vi['verify.confirmedBody'])).toBeInTheDocument();
    expect(screen.queryByText(/An English server sentence/)).toBeNull();
  });

  it('register: a server field refusal is worded beside the field in Vietnamese', async () => {
    const user = userEvent.setup();
    stubAccountFetch([
      SIGNED_OUT,
      {
        path: '/api/v1/account/register',
        method: 'POST',
        status: 422,
        body: {
          code: 'validation_error',
          message: 'Enter a valid email address, like name@example.com.',
          field: 'email',
        },
      },
    ]);
    renderAccount('/account/register', { locale: 'vi' });
    await user.type(await screen.findByLabelText('Địa chỉ email'), 'a@example.com');
    await user.type(screen.getByLabelText(/^Mật khẩu/), 'a long enough password');
    await user.type(screen.getByLabelText(/^Xác nhận mật khẩu/), 'a long enough password');
    await user.type(screen.getByLabelText(/^Họ tên đầy đủ/), 'Nguyen Van A');
    const address = within(screen.getByRole('group', { name: 'Địa chỉ' }));
    await user.type(address.getByLabelText(/^Dòng địa chỉ 1/), '4120 Dixie Road');
    await user.type(address.getByLabelText(/^Thành phố/), 'Mississauga');
    await user.type(address.getByLabelText(/^Tỉnh hoặc bang/), 'ON');
    await user.click(screen.getByLabelText(/^Tôi đồng ý/));
    await user.click(screen.getByRole('button', { name: 'Tạo tài khoản' }));

    expect((await screen.findAllByText(vi['register.invalidEmail'])).length).toBeGreaterThan(0);
    expect(screen.queryByText('Enter a valid email address, like name@example.com.')).toBeNull();
  });
});
