/**
 * The redaction promise in `tests/e2e/diagnostics.js`, asserted.
 *
 * The failure-diagnostic capture is allowed to write an artifact to disk, and that
 * artifact is the kind of thing that gets attached to a defect report and mailed around.
 * Its docstring promises it never records credentials, session cookies, CSRF values,
 * customer information, tracking references, or CSV contents.
 *
 * A promise in a comment is not a control. These tests are the control, and they exist so
 * that a later edit which loosens a pattern fails here rather than in an artifact nobody
 * re-reads. They are unit tests of the two pure functions, run by the normal frontend
 * suite -- the capture itself only runs on an already-failed end-to-end test, which is
 * not a thing a unit test can or should provoke.
 */

import { describe, expect, it } from 'vitest';

import { redact, safeUrl } from './e2e/diagnostics.js';

describe('redact', () => {
  it('removes a Solaris tracking reference', () => {
    const out = redact('lookup for SX-CAV-2D8VRR5ECF54 returned 200');
    expect(out).not.toContain('2D8VRR5ECF54');
    expect(out).toContain('SX-<redacted>');
  });

  it('removes every tracking reference in a line, not just the first', () => {
    const out = redact('SX-CAV-ABCDEFGHJKLM then SX-VNC-ZZZZ99999999');
    expect(out).not.toMatch(/ABCDEFGHJKLM|ZZZZ99999999/);
  });

  it('removes an email address', () => {
    const out = redact('signed in as minh.tuan.demo@demo.example.com');
    expect(out).not.toContain('minh.tuan.demo');
    expect(out).toContain('<email redacted>');
  });

  it('removes session cookie material', () => {
    expect(redact('cookie: solaris_session=abc123def')).not.toContain('abc123def');
    expect(redact('solaris_session=abc123def')).not.toContain('abc123def');
    expect(redact('Set-Cookie: solaris_session=abc123def; HttpOnly')).not.toContain('abc123def');
  });

  it('removes a CSRF token however it is spelled', () => {
    expect(redact('x-csrf-token: 9f8e7d6c')).not.toContain('9f8e7d6c');
    expect(redact('csrf_token=9f8e7d6c')).not.toContain('9f8e7d6c');
    expect(redact('csrf-token: 9f8e7d6c')).not.toContain('9f8e7d6c');
  });

  it('removes credentials and bearer material', () => {
    expect(redact('password=SolarisDemo!2026')).not.toContain('SolarisDemo');
    expect(redact('Authorization: Bearer eyJhbGciOi')).not.toContain('eyJhbGciOi');
    expect(redact('api_key ABCD-1234')).not.toContain('ABCD-1234');
  });

  it('passes through a line that carries nothing sensitive', () => {
    const line = 'GET /shipments 200 in 14.65ms';
    expect(redact(line)).toBe(line);
  });

  it('is null-safe, because a console message can have no text', () => {
    expect(redact(null)).toBe(null);
    expect(redact(undefined)).toBe(undefined);
  });
});

describe('safeUrl', () => {
  it('keeps origin and path, which is what a diagnostic needs', () => {
    expect(safeUrl('http://localhost:5183/shipments/12')).toBe('http://localhost:5183/shipments/12');
  });

  it('drops query values and keeps only the parameter names', () => {
    const out = safeUrl('http://localhost:5183/customers?q=Nguy%E1%BB%85n&page=2');
    expect(out).not.toContain('Nguy');
    expect(out).toContain('2 param(s): q,page');
  });

  it('drops a fragment rather than recording it', () => {
    expect(safeUrl('http://localhost:5183/reports#section-a')).toContain('#<hash>');
    expect(safeUrl('http://localhost:5183/reports#section-a')).not.toContain('section-a');
  });

  it('redacts a tracking reference that sits in the path', () => {
    const out = safeUrl('http://localhost:5183/api/v1/public/track/SX-CAV-2D8VRR5ECF54');
    expect(out).not.toContain('2D8VRR5ECF54');
    expect(out).toContain('SX-<redacted>');
  });

  it('still redacts when the value does not parse as a URL', () => {
    expect(safeUrl('not a url SX-CAV-2D8VRR5ECF54')).not.toContain('2D8VRR5ECF54');
  });
});
