/**
 * Contrast regressions for the corrected colour tokens (DEC-0086).
 *
 * The axe audit checks the rendered result, which is the real proof — but it needs both
 * applications running, so it is not what a developer gets on `npm run test`. This does
 * the arithmetic directly against `src/styles/tokens.css`, in under a millisecond, so a
 * future edit to a hex value fails immediately rather than at the next full audit.
 *
 * It reads the token file rather than duplicating the values. A test that restated the
 * hex codes would keep passing after somebody changed them, which is exactly the failure
 * it exists to prevent.
 *
 * The history worth remembering: `Design.md` asserted that `#E9652A` "retains white-text
 * contrast". It measures 3.30:1 against a 4.5:1 requirement, and that single unverified
 * annotation put every primary button in both applications below AA. Stated contrast is
 * not measured contrast.
 */

import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

import { describe, expect, it } from 'vitest';

const HERE = dirname(fileURLToPath(import.meta.url));
const TOKENS = readFileSync(join(HERE, '..', 'src', 'styles', 'tokens.css'), 'utf8');

/** Pull a custom property's value out of the token file. */
function token(name) {
  const match = TOKENS.match(new RegExp(`--${name}\\s*:\\s*(#[0-9a-fA-F]{6})`));
  if (!match) throw new Error(`token --${name} not found in tokens.css`);
  return match[1].toLowerCase();
}

/** WCAG 2.x relative luminance. */
function luminance(hex) {
  const channels = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255);
  const [r, g, b] = channels.map((c) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4));
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

function ratio(a, b) {
  const [x, y] = [luminance(a), luminance(b)];
  return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05);
}

const WHITE = '#ffffff';

/** AA thresholds. */
const NORMAL_TEXT = 4.5;
const NON_TEXT = 3;

describe('DEC-0086: the corrected interaction tokens still meet AA', () => {
  const orange600 = token('brand-orange-600');
  const orange700 = token('brand-orange-700');
  const orange500 = token('brand-orange-500');
  const teal700 = token('accent-teal-700');
  const teal600 = token('accent-teal-600');
  const orange100 = token('brand-orange-100');
  const teal100 = token('accent-teal-100');
  const neutral50 = token('neutral-50');
  const navy900 = token('brand-navy-900');

  it('white text on the primary button fill meets AA', () => {
    // The defect that started this: every primary button in both applications.
    expect(ratio(orange600, WHITE)).toBeGreaterThanOrEqual(NORMAL_TEXT);
  });

  it('orange as text meets AA on every light surface it lands on', () => {
    expect(ratio(orange700, WHITE)).toBeGreaterThanOrEqual(NORMAL_TEXT);
    expect(ratio(orange700, neutral50)).toBeGreaterThanOrEqual(NORMAL_TEXT);
    expect(ratio(orange700, orange100)).toBeGreaterThanOrEqual(NORMAL_TEXT);
  });

  it('teal as badge text meets AA on its tinted background', () => {
    // The route badge, repeated on every row of the customer and shipment lists.
    expect(ratio(teal700, teal100)).toBeGreaterThanOrEqual(NORMAL_TEXT);
    expect(ratio(teal700, WHITE)).toBeGreaterThanOrEqual(NORMAL_TEXT);
    expect(ratio(teal700, neutral50)).toBeGreaterThanOrEqual(NORMAL_TEXT);
  });

  it('the lighter orange still passes as text on navy, which is where it is used', () => {
    // The wordmark on the sidebar, the public header, and the login page. Darkening this
    // one makes it worse, which a previous attempt in this phase proved twice.
    expect(ratio(orange500, navy900)).toBeGreaterThanOrEqual(NORMAL_TEXT);
  });

  it('the non-text tokens clear the 3:1 bar that applies to them', () => {
    expect(ratio(teal600, WHITE)).toBeGreaterThanOrEqual(NON_TEXT);
    expect(ratio(orange600, WHITE)).toBeGreaterThanOrEqual(NON_TEXT);
  });
});

describe('DEC-0086: the values that failed must not come back', () => {
  it('the original brand orange is not used as a primary fill', () => {
    // #E9652A is retained in Design.md as `brand.orange.ref`, decorative only. If it
    // ever reappears as --brand-orange-600, white text on it is 3.30:1 again.
    expect(token('brand-orange-600')).not.toBe('#e9652a');
  });

  it('the original teal is not used as badge text', () => {
    expect(token('accent-teal-700')).not.toBe('#16867d');
  });

  it('the failing pairings are genuinely below AA, so these guards mean something', () => {
    // Guards the guard. If these ever passed, the thresholds above would be wrong.
    expect(ratio('#e9652a', WHITE)).toBeLessThan(NORMAL_TEXT);
    expect(ratio('#16867d', token('accent-teal-100'))).toBeLessThan(NORMAL_TEXT);
    expect(ratio('#f47a3a', token('neutral-50'))).toBeLessThan(NORMAL_TEXT);
  });
});

describe('DEC-0086: every status badge pairing meets AA', () => {
  // These four already passed and are asserted so they keep passing.
  const pairs = [
    ['success-700', 'success-100'],
    ['warning-700', 'warning-100'],
    ['danger-700', 'danger-100'],
    ['info-700', 'info-100'],
  ];

  it.each(pairs)('%s on %s', (fg, bg) => {
    expect(ratio(token(fg), token(bg))).toBeGreaterThanOrEqual(NORMAL_TEXT);
  });
});
