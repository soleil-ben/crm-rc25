/**
 * The searchable fee list for one item (Phase 13D; owner decision 4: fees are attached
 * explicitly to items, never charged automatically).
 *
 * Only the master's own air section is searched (HCM or Hà Nội, OD-49), and only rules that
 * apply to Canada. Picking a rule asks for what that rule is charged on: units for a per-unit
 * rule, the carton's weight for a tiered one, the vendor's quoted price for a manual quote
 * (OD-56; left blank, the file's minimum is used and the quote is flagged), or -- for a rule
 * quoted case by case (`manual_amount`, HCM air row 27, owner 2026-10-22 and 2026-10-23) -- the
 * vendor's cost (VND) and the customer price (CAD) for the whole line, both empty with no
 * default, no weight and no quantity (left blank, the line blocks finalising until both are
 * entered on the line). The server validates everything again; this
 * form only decides which fields to show.
 */

import { useState } from 'react';
import { useMutation, useQuery } from '@tanstack/react-query';
import { pricingApi, tariffsApi } from '../../api/endpoints.js';
import { useT } from '../../i18n/index.jsx';
import { Banner, Button, Field, TextInput } from '../../components/ui/index.jsx';
import { InlineSpinner } from '../../components/state/index.jsx';
import { formatKg, formatVnd } from './workspaceFormat.js';

const PICKABLE = new Set(['priced', 'tiered', 'free', 'manual_quote']);

/**
 * Accent-folded, lower-case text, so "dong ho" finds "Đồng hồ". The vendor writes some names
 * with diacritics and some without, and staff type either way.
 */
export function fold(text) {
  return (text || '')
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .replace(/\u0111/g, 'd')
    .replace(/\u0110/g, 'D')
    .toLowerCase();
}

const MASTER_WIDE_SCOPES = new Set(['full_master', 'full_carton']);

/** Words too common to suggest a surcharge on their own. */
const STOP_WORDS = new Set([
  'hang', 'cac', 'loai', 'mot', 'so', 'khac', 'nhu', 'cho', 'va', 'co', 'the', 'and', 'with',
  'item', 'items', 'kien', 'cai', 'chiec',
]);

const words = (text) => fold(text).replace(/[^a-z0-9]+/g, ' ').trim().split(' ').filter(Boolean);
const core = (list) => list.filter((w) => !STOP_WORDS.has(w)).join(' ');

function phrases(text) {
  return fold(text)
    .split(/[,;/()[\]–:.+]+| - /)
    .map((p) => core(words(p)))
    .filter((p) => p.length >= 3);
}

/**
 * Surcharges that look like they apply to an item, from its name (DEC-0272, improved after
 * the owner's review, DEC-0273). Only a suggestion: staff review and add it themselves (owner
 * decision 4: fees are attached explicitly, never charged automatically).
 *
 * Accent-insensitive, whole words. A rule matches, best first, when
 *   3. a phrase of its name or note is in the item name ("Son môi Dior" → "son môi");
 *   2. the item name is in a phrase of the rule ("mỹ phẩm" → "Hàng Mỹ phẩm, TPCN");
 *   1. a long word of the item name (5 letters or more) is in the rule.
 */
export function suggestRules(itemName, rules, limit = 3) {
  const itemWords = words(itemName);
  const item = ` ${itemWords.join(' ')} `;
  const itemCore = core(itemWords);
  if (itemCore.length < 3) return [];
  const longWords = itemWords.filter((w) => w.length >= 5 && !STOP_WORDS.has(w));
  const scored = [];
  for (const rule of rules) {
    if (!PICKABLE.has(rule.pricing_status)) continue;
    const ruleText = ` ${words(`${rule.name} ${rule.raw_note || ''}`).join(' ')} `;
    const ruleParts = phrases(`${rule.name}, ${rule.raw_note || ''}`);
    const inItem = ruleParts.find((p) => item.includes(` ${p} `));
    const inRule = !inItem && ruleParts.find((p) => ` ${p} `.includes(` ${itemCore} `));
    const word = !inItem && !inRule && longWords.find((w) => ruleText.includes(` ${w} `));
    if (inItem) scored.push({ rule, why: inItem, score: 3 });
    else if (inRule) scored.push({ rule, why: itemCore, score: 2 });
    else if (word) scored.push({ rule, why: word, score: 1 });
  }
  return scored.sort((a, b) => b.score - a.score).slice(0, limit);
}

/** Kango's battery-with-a-small-device rule: banded on the battery kg in the piece (DEC-0276). */
export function isBatteryRule(rule) {
  return rule?.pricing_status === 'tiered' && fold(rule?.name).includes('pin kem thiet bi nho');
}

/** Rules whose weight is the item's own, so the item's weight fills in (DEC-0275, DEC-0276). */
export function usesItemWeight(rule) {
  return rule?.basis === 'per_kg' || rule?.pricing_status === 'tiered';
}

/** Kango charges it once per master piece (DEC-0276). */
export function isPerPiece(rule) {
  return rule?.allocation_class === 'PARCEL';
}

/** Kango charges it once per shipment, each customer with the item pays it (DEC-0276). */
export function isPerShipment(rule) {
  return rule?.allocation_class === 'WHOLE_MASTER' && rule?.basis === 'per_shipment';
}

/** A rule quoted case by case: one amount for the line (owner, 2026-10-22). */
export function isManualAmount(rule) {
  return rule?.basis === 'manual_amount';
}

/** A tiered rule reads the carton weight; a per-kg rule not charged on the whole master or
 * carton reads the line's own kilograms (the engine refuses the line without them). */
function needsWeight(rule) {
  return (
    rule.pricing_status === 'tiered' ||
    (rule.basis === 'per_kg' && !MASTER_WIDE_SCOPES.has(rule.scope))
  );
}

/** Quantity means nothing to a per-kg or per-shipment rule, so it is not asked. */
function needsQuantity(rule) {
  // A per-piece fee is charged once per master piece; only a per-bottle part (compound) counts.
  if (isPerPiece(rule) && rule.basis !== 'compound') return false;
  return rule.basis !== 'per_kg' && rule.basis !== 'per_shipment' && !isManualAmount(rule);
}

function topTierKg(rule) {
  const bounds = (rule.tiers || []).map((tier) => Number(tier.weight_to_kg)).filter(Number.isFinite);
  return bounds.length ? Math.max(...bounds) : null;
}

export function FeePicker({ shipmentId, item, section, versionId, onAdded, onCancel, initialQuery = '' }) {
  const t = useT();
  const [query, setQuery] = useState(initialQuery);
  const [rule, setRule] = useState(null);
  const [quantity, setQuantity] = useState('1');
  const [weight, setWeight] = useState(item.weight_kg ? String(Number(item.weight_kg)) : '');
  const [manualPrice, setManualPrice] = useState('');
  // The customer price (CAD) of a line quoted case by case (DEC-0228); empty, no default.
  const [customerPrice, setCustomerPrice] = useState('');

  const rulesQuery = useQuery({
    // The whole section (a few dozen rules) once; the search is folded here, not on the server.
    queryKey: ['workspace-rules', versionId, section],
    queryFn: () => tariffsApi.surcharges(versionId, { section }),
    enabled: Boolean(versionId && section),
  });
  const needle = fold(query.trim());
  const pickable = (rulesQuery.data?.items ?? []).filter((r) => PICKABLE.has(r.pricing_status));
  // Every surcharge of the section is listed (it used to stop at 12); the search also reads
  // the vendor's note, so "power bank" finds "Sạc dự phòng" (owner review, 2026-11-05).
  const rules = pickable.filter(
    (r) => !needle || fold(`${r.name} ${r.raw_note || ''}`).includes(needle),
  );

  const add = useMutation({
    mutationFn: () =>
      pricingApi.addFeeLine(shipmentId, {
        item_id: item.id,
        section: rule.section,
        stt: rule.stt,
        quantity: (showQuantity && quantity) || '1',
        weight_kg: (showWeight && weight) || undefined,
        manual_unit_price_vnd: (showManual && manualPrice.trim()) || undefined,
        customer_price_cad: (isManualAmount(rule) && customerPrice.trim()) || undefined,
      }),
    onSuccess: onAdded,
  });

  if (!versionId) return <Banner tone="danger">{t('workspace.noActiveTariff')}</Banner>;

  const top = rule ? topTierKg(rule) : null;
  // The server takes a vendor price only for a manual quote, or for a carton above the top
  // tier of a rule whose top tier does not simply continue (batteries over 8 kg, OD-59).
  const showManual =
    rule &&
    (rule.pricing_status === 'manual_quote' ||
      (rule.pricing_status === 'tiered' &&
        rule.above_top_tier === 'manual' &&
        top !== null &&
        Number(weight) > top));
  const showWeight = rule ? needsWeight(rule) : false;
  const showQuantity = rule ? needsQuantity(rule) : false;

  return (
    <div className="ws-picker">
      {!rule ? (
        <>
          <Field label={t('workspace.searchFees')} hint={t('workspace.searchFeesHint')}>
            {(props) => (
              <TextInput
                {...props}
                type="search"
                value={query}
                onChange={(event) => setQuery(event.target.value)}
              />
            )}
          </Field>
          {rulesQuery.isLoading && <InlineSpinner label={t('common.loading')} />}
          {rulesQuery.error && <Banner tone="danger">{rulesQuery.error.message}</Banner>}
          {rulesQuery.isSuccess && (
            <p className="meta" role="status">
              {t('wsFlow.feeCount')
                .replace('{shown}', String(rules.length))
                .replace('{total}', String(pickable.length))
                .replace('{section}', t(`wsFlow.section.${section}`, section))}
            </p>
          )}
          <ul className="ws-rule-list" aria-label={t('workspace.feeResults')}>
            {rules.map((r) => (
              <li key={`${r.section}-${r.stt}`}>
                <button type="button" className="ws-rule" onClick={() => setRule(r)}>
                  <span className="ws-rule__name">{r.name}</span>
                  <span className="meta">
                    {r.raw_price_text} · {t(`workspace.pricingStatus.${r.pricing_status}`, r.pricing_status)}
                  </span>
                </button>
              </li>
            ))}
          </ul>
          {rulesQuery.isSuccess && rules.length === 0 && <p className="meta">{t('workspace.noFees')}</p>}
          <Button compact onClick={onCancel}>
            {t('common.cancel')}
          </Button>
        </>
      ) : (
        <form
          className="ws-form"
          onSubmit={(event) => {
            event.preventDefault();
            add.mutate();
          }}
        >
          <p>
            <strong>{rule.name}</strong> <span className="meta">{rule.raw_price_text}</span>
          </p>
          {isPerPiece(rule) && (
            <p className="meta">
              {t(rule.pricing_status === 'tiered' ? 'wsFlow.perPieceBanded' : 'wsFlow.perPieceFlat')}
            </p>
          )}
          {isPerShipment(rule) && <p className="meta">{t('wsFlow.perShipmentFee')}</p>}
          {rule.pricing_status === 'manual_quote' && !isManualAmount(rule) && (
            <p className="meta">
              {t('workspace.manualQuoteNote').replace('{minimum}', formatVnd(rule.unit_price_vnd))}
            </p>
          )}
          {add.error && <Banner tone="danger">{add.error.message}</Banner>}
          <div className="ws-grid">
            {showQuantity && (
            <Field label={t('workspace.feeQuantity')} hint={t(`workspace.basis.${rule.basis}`, rule.basis)}>
              {(props) => (
                <TextInput
                  {...props}
                  inputMode="decimal"
                  value={quantity}
                  onChange={(event) => setQuantity(event.target.value)}
                />
              )}
            </Field>
            )}
            {!showQuantity && (
              <p className="meta">{t(`workspace.basis.${rule.basis}`, rule.basis)}</p>
            )}
            {showWeight && (
              <Field
                label={
                  isBatteryRule(rule)
                    ? t('wsFlow.batteryItemWeight')
                    : rule.pricing_status === 'tiered'
                      ? t('wsFlow.typeItemWeight')
                      : t('workspace.itemWeight')
                }
                hint={
                  usesItemWeight(rule)
                    ? item.weight_kg
                      ? t('wsFlow.itemWeightFilled').replace('{kg}', formatKg(item.weight_kg))
                      : t('wsFlow.itemWeightMissing')
                    : undefined
                }
                required={!(usesItemWeight(rule) && item.weight_kg)}
              >
                {(props) => (
                  <TextInput
                    {...props}
                    inputMode="decimal"
                    value={weight}
                    onChange={(event) => setWeight(event.target.value)}
                  />
                )}
              </Field>
            )}
            {showManual && isManualAmount(rule) && (
              <>
                <p className="meta">{t('workspace.manualPricesAddHint')}</p>
                <Field label={t('workspace.manualCostVnd')}>
                  {(props) => (
                    <TextInput
                      {...props}
                      name="quoted_amount_vnd"
                      inputMode="decimal"
                      value={manualPrice}
                      onChange={(event) => setManualPrice(event.target.value)}
                    />
                  )}
                </Field>
                <Field label={t('workspace.manualPriceCad')}>
                  {(props) => (
                    <TextInput
                      {...props}
                      name="customer_price_cad"
                      inputMode="decimal"
                      value={customerPrice}
                      onChange={(event) => setCustomerPrice(event.target.value)}
                    />
                  )}
                </Field>
              </>
            )}
            {showManual && !isManualAmount(rule) && (
              <Field label={t('workspace.vendorPrice')} hint={t('workspace.vendorPriceHint')}>
                {(props) => (
                  <TextInput
                    {...props}
                    inputMode="decimal"
                    value={manualPrice}
                    onChange={(event) => setManualPrice(event.target.value)}
                  />
                )}
              </Field>
            )}
          </div>
          <div className="row-wrap">
            <Button type="submit" variant="primary" loading={add.isPending}>
              {t('workspace.addFee')}
            </Button>
            <Button onClick={() => setRule(null)}>{t('workspace.chooseAnother')}</Button>
            <Button onClick={onCancel}>{t('common.cancel')}</Button>
          </div>
        </form>
      )}
    </div>
  );
}
