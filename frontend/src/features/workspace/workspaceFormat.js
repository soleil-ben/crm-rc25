/**
 * Number formatting for the workspace (Phase 13D).
 *
 * Amounts arrive from the API as decimal strings. VND is shown as stored, to the cent where
 * there is one, because the owner does not round vendor amounts (OD-60); CAD always shows
 * cents. Neither currency is ever merged into the other's total.
 */

const VND = new Intl.NumberFormat('en-CA', { minimumFractionDigits: 0, maximumFractionDigits: 2 });
const CAD = new Intl.NumberFormat('en-CA', {
  style: 'currency',
  currency: 'CAD',
  currencyDisplay: 'code',
});
const KG = new Intl.NumberFormat('en-CA', { minimumFractionDigits: 0, maximumFractionDigits: 3 });

function present(value) {
  return value !== null && value !== undefined && value !== '';
}

export function formatVnd(value) {
  return present(value) ? `${VND.format(Number(value))} VND` : '—';
}

export function formatCad(value) {
  return present(value) ? CAD.format(Number(value)) : '—';
}

export function formatKg(value) {
  return present(value) ? `${KG.format(Number(value))} kg` : '—';
}

/** Sum of decimal strings, or null when any is missing. */
export function sumOf(values) {
  if (values.some((v) => !present(v))) return null;
  return values.reduce((total, v) => total + Number(v), 0);
}

/** Air sections only (OD-49): the vendor's surcharge sheet per origin. */
export const SECTION_BY_ORIGIN = { HCM: 'hcm_air', HAN: 'han_air' };

/** Every query the workspace makes is under this key, so one invalidation refreshes all. */
export function wsKey(consolidationId, ...rest) {
  return ['workspace', String(consolidationId), ...rest];
}

const DIM_DIVISOR = 6000;
const num = (value) => (value === null || value === undefined || value === '' ? null : Number(value));

/** VW and CW as a form shows them while typing (divisor 6000); the server's figures count. */
export function previewCw({ weight_kg, length_cm, width_cm, height_cm }) {
  const gw = num(weight_kg);
  const [l, w, h] = [num(length_cm), num(width_cm), num(height_cm)];
  const vw = l && w && h ? (l * w * h) / DIM_DIVISOR : null;
  if (gw === null && vw === null) return { vw: null, cw: null };
  return { vw, cw: Math.max(gw ?? 0, vw ?? 0) };
}
