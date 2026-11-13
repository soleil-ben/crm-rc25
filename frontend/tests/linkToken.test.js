/**
 * CA-SEC-07: the token a verification or reset link carries is read out of the URL
 * fragment at the earliest moment, held in memory once, and stripped from the address bar
 * in place -- never pushed, never left for Back to find.
 */

import { afterEach, describe, expect, it } from 'vitest';
import {
  captureLinkToken,
  locationCarriesToken,
  takeLinkToken,
  tokenFromLocation,
} from '../src/account/linkToken.js';

afterEach(() => {
  takeLinkToken(); // drain whatever a test left behind
  window.history.replaceState({}, '', '/');
});

describe('captureLinkToken', () => {
  it('moves a fragment token into memory and rewrites the address bar in place', () => {
    window.history.pushState({}, '', '/account/reset-password#token=SECRET-RESET');
    const depth = window.history.length;

    captureLinkToken();

    expect(window.location.hash).toBe('');
    expect(window.location.pathname).toBe('/account/reset-password');
    expect(window.location.href).not.toContain('SECRET-RESET');
    // Replaced, not pushed: Back would not walk onto the token.
    expect(window.history.length).toBe(depth);
    expect(takeLinkToken()).toBe('SECRET-RESET');
  });

  it('hands the token out exactly once', () => {
    window.history.pushState({}, '', '/account/verify-email#token=ONCE');
    captureLinkToken();
    expect(takeLinkToken()).toBe('ONCE');
    expect(takeLinkToken()).toBeNull();
  });

  it('keeps the query string the page may still need', () => {
    window.history.pushState({}, '', '/account/verify-email?lang=en#token=T');
    captureLinkToken();
    expect(window.location.search).toBe('?lang=en');
    expect(window.location.hash).toBe('');
  });

  it('decodes a percent-encoded token', () => {
    window.history.pushState({}, '', '/account/verify-email#token=a%2Bb%3D');
    captureLinkToken();
    expect(takeLinkToken()).toBe('a+b=');
  });

  it('does nothing on a URL without a token fragment', () => {
    window.history.pushState({}, '', '/track/SX-CAV-ABCDEFGHJKLM#timeline');
    captureLinkToken();
    expect(window.location.hash).toBe('#timeline');
    expect(takeLinkToken()).toBeNull();
  });

  it('tolerates an environment without a window', () => {
    expect(() => captureLinkToken(null)).not.toThrow();
  });
});

describe('tokenFromLocation', () => {
  it('reads the fragment shape', () => {
    expect(tokenFromLocation({ hash: '#token=ABC', search: '' })).toBe('ABC');
    expect(locationCarriesToken({ hash: '#token=ABC', search: '' })).toBe(true);
  });

  it('still reads the query-string shape a pre-fix link uses', () => {
    expect(tokenFromLocation({ hash: '', search: '?token=OLD' })).toBe('OLD');
    expect(locationCarriesToken({ hash: '', search: '?token=OLD' })).toBe(true);
  });

  it('prefers the fragment when both are present', () => {
    expect(tokenFromLocation({ hash: '#token=NEW', search: '?token=OLD' })).toBe('NEW');
  });

  it('reports no token for an ordinary location', () => {
    expect(tokenFromLocation({ hash: '', search: '' })).toBeNull();
    expect(locationCarriesToken({ hash: '#section', search: '?page=2' })).toBe(false);
    expect(tokenFromLocation(undefined)).toBeNull();
  });
});
