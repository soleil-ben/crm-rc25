/**
 * Cost vs quote under the owner's cost and quote method (step 2, DEC-0270).
 *
 * Three panels for one master, all fed by the estimate the API computed
 * (`estimate.method_detail`, `app/pricing/cost_method.py`); this screen does no pricing
 * arithmetic beyond adding up the customers of one package:
 *
 * - `CostQuotePanel`: the master, each big package (kiện) and each customer -- VND cost, CAD
 *   cost, CAD quote, profit and surcharge margin -- with the engine's warnings.
 * - `PackagesPanel`: per package, the short note listing its customers (`customer_note`),
 *   "packed as one box for Kango" (one-package masters only, DEC-0262) and, on a master with
 *   several packages, which package each customer rides in.
 * - `ManualPricingPanel`: Air Express / UPS vendor cost and selling rate, entered by hand,
 *   with Kango's Express zone table shown for reference only.
 *
 * Internal: vendor cost is on every panel. Staff only, behind `tariff:read`.
 */

import { useEffect, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { consolidationsApi, tariffsApi } from '../../api/endpoints.js';
import { useT } from '../../i18n/index.jsx';
import { Banner, Button, Card, Checkbox, Field, Select, TextInput } from '../../components/ui/index.jsx';
import { ErrorState, SkeletonRows } from '../../components/state/index.jsx';
import { IssueList } from './MasterPanels.jsx';
import { CollapsibleCard } from './CollapsibleCard.jsx';
import { formatCad, formatKg, formatVnd, sumOf, wsKey } from './workspaceFormat.js';

function useRefresh(consolidationId) {
  const queryClient = useQueryClient();
  return () => queryClient.invalidateQueries({ queryKey: wsKey(consolidationId) });
}

/** Add up decimal strings; null as soon as one is missing. */
function total(values) {
  if (!values.length || values.some((v) => v === null || v === undefined)) return null;
  return values.reduce((sum, v) => sum + Number(v), 0);
}

function profitTone(value) {
  if (value === null || value === undefined) return '';
  return Number(value) < 0 ? 'cq-negative' : '';
}

/** Rows of the package table: recorded packages, or one "whole master" row. */
export function packageRows(detail) {
  const packages = detail?.packages ?? [];
  const members = detail?.members ?? {};
  return packages.map((pkg) => {
    const ids = (pkg.members ?? []).map(String);
    const rows = ids.map((id) => members[id]).filter(Boolean);
    return {
      sequence: pkg.sequence,
      cwKg: pkg.raw_kg,
      billedKg: pkg.billed_kg,
      packed: Boolean(pkg.packed_as_one_box),
      memberIds: ids,
      publicIds: rows.map((r) => r.public_id),
      costVnd: total(rows.map((r) => r.cost_vnd)),
      costCad: total(rows.map((r) => r.cost_cad)),
      quoteCad: total(rows.map((r) => r.quote_cad)),
      profitCad: total(rows.map((r) => r.profit_cad)),
      marginCad: total(rows.map((r) => r.surcharge_margin_cad)),
    };
  });
}

function Tile({ label, children, tone = '' }) {
  return (
    <div className={`ws-tile ${tone}`.trim()}>
      <dt>{label}</dt>
      <dd>{children}</dd>
    </div>
  );
}

function Line({ label, children, strong = false, note = null }) {
  return (
    <div className="ws-cost-line">
      <dt>
        {label}
        {note && <span className="meta"> · {note}</span>}
      </dt>
      <dd>{strong ? <strong>{children}</strong> : children}</dd>
    </div>
  );
}

/**
 * Cost and quote for the whole master, in one card (owner review, 2026-11-05; DEC-0274): it
 * replaces the separate "Vendor cost" side panel and the old "Cost vs quote" tables.
 *
 * - Headline figures: vendor bill weight, vendor cost, quote, profit, surcharge margin.
 * - Vendor cost: what the vendor charges for the **master** (base freight on the pieces'
 *   bill weight, piece fee, surcharges), with the exchange rate.
 * - Quote by customer: weight, rate and quote. No per-customer cost is shown: the vendor's
 *   base rate is charged on the master pieces, not on each small box (owner, 2026-11-05).
 * - By piece, when the master has several pieces: weights and quote. Cost and profit are
 *   shown for the whole master only, where the vendor charges them.
 *
 * Every figure is the server's (`estimate`, `estimate.method_detail`).
 */
export function CostQuotePanel({ master, estimateQuery, collapsible = false, defaultOpen = true }) {
  const t = useT();
  const fxQuery = useQuery({ queryKey: ['fx-latest'], queryFn: tariffsApi.fxLatest });
  const estimate = estimateQuery.data?.estimate;
  const detail = estimate?.method_detail;
  const nameOf = Object.fromEntries(master.members.map((m) => [String(m.shipment_id), m]));
  const fx = fxQuery.data;

  if (estimateQuery.isLoading || estimateQuery.error || !estimate) {
    return (
      <CollapsibleCard title={t('costMethod.panelTitle')} collapsible={collapsible} defaultOpen={defaultOpen}>
        {estimateQuery.error ? (
          <ErrorState error={estimateQuery.error} onRetry={estimateQuery.refetch} />
        ) : (
          <SkeletonRows rows={4} />
        )}
      </CollapsibleCard>
    );
  }
  const totals = detail?.totals ?? {};
  const packages = detail ? packageRows(detail) : [];
  const memberRows = detail ? Object.entries(detail.members ?? {}) : [];
  const surchargesVnd = sumOf((estimate.fees ?? []).map((f) => f.vendor_fee_vnd));
  const costVnd = detail?.bill_vnd ?? estimate.total_cost_vnd;

  return (
    <CollapsibleCard
      title={t('costMethod.panelTitle')}
      collapsible={collapsible}
      defaultOpen={defaultOpen}
      summary={
        detail
          ? t('wsFlow.costSummary')
              .replace('{cost}', formatCad(totals.cost_cad))
              .replace('{quote}', formatCad(totals.quote_cad))
              .replace('{profit}', formatCad(totals.profit_cad))
          : formatVnd(estimate.total_cost_vnd)
      }
    >
      <p className="meta">{t('wsFlow.costIntro')}</p>
      <dl className="ws-tiles">
        <Tile label={t('costMethod.billWeight')}>{formatKg(detail?.bill_kg ?? estimate.master_chargeable_kg)}</Tile>
        <Tile label={t('wsFlow.vendorCost')}>
          {formatVnd(costVnd)}
          {detail && <div className="meta">{formatCad(totals.cost_cad)}</div>}
        </Tile>
        {detail && <Tile label={t('wsFlow.quoteTotal')}>{formatCad(totals.quote_cad)}</Tile>}
        {detail && (
          <Tile label={t('costMethod.profitCad')} tone={profitTone(totals.profit_cad)}>
            {formatCad(totals.profit_cad)}
          </Tile>
        )}
        {detail && <Tile label={t('wsFlow.surchargeMargin')}>{formatCad(totals.surcharge_margin_cad)}</Tile>}
      </dl>
      {detail?.reconciled === false && <Banner tone="danger">{t('costMethod.notReconciled')}</Banner>}

      <div className="ws-cost-grid">
        <section aria-labelledby="ws-vendor-cost">
          <h3 className="ws-subtitle" id="ws-vendor-cost">
            {t('wsFlow.vendorCostTitle')}
          </h3>
          <p className="meta">{t('workspace.internalOnly')}</p>
          <dl className="ws-cost-lines">
            <Line label={t('workspace.vendorProduct')}>{estimate.product_code || '—'}</Line>
            <Line label={t('workspace.deliveryPoint')}>
              {estimate.delivery_postal_code || '—'} · {t('workspace.zone')} {estimate.zone ?? '—'}
            </Line>
            <Line label={t('workspace.baseFreight')} note={detail?.base_basis}>
              {formatVnd(detail?.base_vnd ?? estimate.base_freight_vnd)}
            </Line>
            <Line label={t('workspace.pieceFee')}>{formatVnd(detail?.piece_vnd ?? estimate.piece_fee_vnd)}</Line>
            <Line label={t('workspace.surcharges')}>{formatVnd(surchargesVnd)}</Line>
            <Line label={t('workspace.totalVendorCost')} strong>
              {formatVnd(costVnd)}
            </Line>
          </dl>
          <p className="meta">
            {detail && (
              <>
                {t('costMethod.fxRate')}: {formatVnd(detail.fx?.cost_rate_vnd)} / CAD ·{' '}
                {t(`costMethod.fxSource.${detail.fx?.cost_source}`, detail.fx?.cost_source)}.{' '}
              </>
            )}
            {fx?.snapshot &&
              t('workspace.fxLine')
                .replace('{buy}', formatVnd(fx.snapshot.cash_buy_vnd))
                .replace('{sell}', formatVnd(fx.snapshot.sell_vnd))}
          </p>
        </section>

        {detail && (
          <section aria-labelledby="ws-quote-by-customer">
            <h3 className="ws-subtitle" id="ws-quote-by-customer">
              {t('wsFlow.quoteByCustomer')}
            </h3>
            <div className="table-wrap">
              <table className="table cq-table" aria-label={t('wsFlow.quoteByCustomer')}>
                <thead>
                  <tr>
                    <th scope="col">{t('costMethod.customer')}</th>
                    <th scope="col" className="num">{t('costMethod.weight')}</th>
                    <th scope="col" className="num">{t('wsFlow.rate')}</th>
                    <th scope="col" className="num">{t('costMethod.quoteCad')}</th>
                  </tr>
                </thead>
                <tbody>
                  {memberRows.map(([sid, row]) => (
                    <tr key={sid}>
                      <th scope="row">
                        {nameOf[sid]?.customer_name || row.public_id}
                        <div className="meta mono">{row.public_id}</div>
                      </th>
                      <td className="num">{formatKg(row.cw_kg)}</td>
                      <td className="num">{formatCad(row.rate_cad_kg)}/kg</td>
                      <td className="num">{formatCad(row.quote_cad)}</td>
                    </tr>
                  ))}
                </tbody>
                <tfoot>
                  <tr>
                    <th scope="row">{t('wsFlow.total')}</th>
                    <td />
                    <td />
                    <td className="num">
                      <strong>{formatCad(totals.quote_cad)}</strong>
                    </td>
                  </tr>
                </tfoot>
              </table>
            </div>
          </section>
        )}
      </div>

      {packages.length > 1 && (
        <>
          <h3 className="ws-subtitle">{t('wsFlow.byPiece')}</h3>
          <div className="table-wrap">
            <table className="table cq-table" aria-label={t('wsFlow.byPiece')}>
              <thead>
                <tr>
                  <th scope="col">{t('wsFlow.piece')}</th>
                  <th scope="col" className="num">{t('wsFlow.pieceCw')}</th>
                  <th scope="col" className="num">{t('wsFlow.billedKg')}</th>
                  <th scope="col" className="num">{t('costMethod.quoteCad')}</th>
                </tr>
              </thead>
              <tbody>
                {packages.map((pkg) => (
                  <tr key={pkg.sequence}>
                    <th scope="row">
                      {t('wsFlow.pieceTitle').replace('{n}', String(pkg.sequence))}
                      <div className="meta">
                        {pkg.memberIds.map((id) => nameOf[id]?.customer_name || id).join(', ') ||
                          t('costMethod.noCustomersRecorded')}
                      </div>
                    </th>
                    <td className="num">{formatKg(pkg.cwKg)}</td>
                    <td className="num">{formatKg(pkg.billedKg)}</td>
                    <td className="num">{formatCad(pkg.quoteCad)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}

      {!detail && <p className="meta">{t('costMethod.rc25Method')}</p>}
      <IssueList issues={estimate.blocking} tone="danger" title={t('workspace.blockingTitle')} />
      <IssueList issues={estimate.provisional} tone="warning" title={t('costMethod.warningsTitle')} />
      {detail && (
        <details className="cq-why">
          <summary>{t('costMethod.whyTitle')}</summary>
          <ul>
            {memberRows.flatMap(([sid, row]) =>
              (row.rules ?? []).map((rule, index) => (
                <li key={`${sid}-${index}`}>
                  <span className="mono">{row.public_id}</span> · {rule}
                </li>
              )),
            )}
          </ul>
        </details>
      )}
    </CollapsibleCard>
  );
}

/* --- Packages: note, packed flag, customer → package ----------------------------------------- */

export function NoteEditor({ consolidationId, sequence, note, editable }) {
  const t = useT();
  const refresh = useRefresh(consolidationId);
  const [value, setValue] = useState(note ?? '');
  useEffect(() => setValue(note ?? ''), [note]);
  const save = useMutation({
    mutationFn: () => consolidationsApi.setPackageNote(consolidationId, sequence, value.trim()),
    onSuccess: refresh,
  });
  return (
    <form
      className="row-wrap"
      onSubmit={(event) => {
        event.preventDefault();
        save.mutate();
      }}
    >
      <Field
        label={t('costMethod.customerNote').replace('{n}', String(sequence))}
        hint={t('costMethod.customerNoteHint')}
        error={save.error?.message}
      >
        {(props) => (
          <TextInput
            {...props}
            maxLength={200}
            readOnly={!editable}
            value={value}
            onChange={(event) => setValue(event.target.value)}
          />
        )}
      </Field>
      {editable && (
        <Button type="submit" compact loading={save.isPending} disabled={value === (note ?? '')}>
          {t('costMethod.saveNote')}
        </Button>
      )}
    </form>
  );
}

export function PackagesPanel({ master, estimate, editable }) {
  const t = useT();
  const refresh = useRefresh(master.id);
  const packagesQuery = useQuery({
    queryKey: wsKey(master.id, 'packages'),
    queryFn: () => consolidationsApi.packages(master.id),
  });
  const detail = estimate?.method_detail;
  const packed = useMutation({
    mutationFn: (value) => consolidationsApi.setPacked(master.id, 1, value),
    onSuccess: refresh,
  });
  const place = useMutation({
    mutationFn: ({ shipmentId, sequence }) =>
      consolidationsApi.setPackageMember(master.id, shipmentId, sequence),
    onSuccess: refresh,
  });
  if (!detail) return null;
  const notes = packagesQuery.data?.notes ?? {};
  const members = packagesQuery.data?.members ?? {};
  const flags = packagesQuery.data?.packed ?? {};
  const sequences = (detail.packages ?? []).map((p) => p.sequence);
  const single = sequences.length <= 1;

  return (
    <Card title={t('costMethod.packagesPanelTitle')}>
      <p className="meta">{t('costMethod.packagesPanelIntro')}</p>
      {packagesQuery.error && <ErrorState error={packagesQuery.error} />}
      {sequences.map((sequence) => (
        <NoteEditor
          key={sequence}
          consolidationId={master.id}
          sequence={sequence}
          note={notes[String(sequence)]}
          editable={editable}
        />
      ))}
      <Checkbox
        label={t('costMethod.packedLabel')}
        hint={single ? t('costMethod.packedHint') : t('costMethod.packedOnlySingle')}
        checked={Boolean(flags['1'])}
        disabled={!editable || !single || packed.isPending}
        onChange={(event) => packed.mutate(event.target.checked)}
      />
      {packed.error && <Banner tone="danger">{packed.error.message}</Banner>}
      {!single && (
        <>
          <h3 className="ws-subtitle">{t('costMethod.placeCustomers')}</h3>
          <p className="meta">{t('costMethod.placeCustomersHint')}</p>
          {place.error && <Banner tone="danger">{place.error.message}</Banner>}
          <div className="ws-grid">
            {master.members.map((member) => (
              <Field
                key={member.shipment_id}
                label={`${member.public_id} · ${member.customer_name || ''}`}
              >
                {(props) => (
                  <Select
                    {...props}
                    disabled={!editable}
                    value={String(members[String(member.shipment_id)] ?? '')}
                    placeholder={t('costMethod.notRecorded')}
                    onChange={(event) =>
                      place.mutate({ shipmentId: member.shipment_id, sequence: event.target.value })
                    }
                    options={sequences.map((s) => ({
                      value: String(s),
                      label: t('costMethod.packageN').replace('{n}', String(s)),
                    }))}
                  />
                )}
              </Field>
            ))}
          </div>
        </>
      )}
    </Card>
  );
}

/* --- Vendor base cost: rate sheet, override, or entered by hand (DEC-0271) ----------------- */

/** UPS and Air Cargo have no rate sheet: cost and selling rate are entered per master. */
export const MANUAL_SERVICES = new Set(['ups', 'air_cargo']);
/** Kango Air Express takes a selling rate here (default: Settings → Pricing). */
const SELL_HERE = new Set(['ups', 'air_cargo', 'air_express']);

const BLANK_MANUAL = {
  manual_cost_vnd_per_kg: '',
  manual_cost_vnd_total: '',
  manual_sell_cad_per_kg: '',
  reason: '',
};

function manualForm(data) {
  if (!data) return BLANK_MANUAL;
  const text = (v) => (v === null || v === undefined ? '' : String(Number(v)));
  return {
    manual_cost_vnd_per_kg: text(data.manual_cost_vnd_per_kg),
    manual_cost_vnd_total: text(data.manual_cost_vnd_total),
    manual_sell_cad_per_kg: text(data.manual_sell_cad_per_kg),
    reason: data.reason ?? '',
  };
}

/**
 * The vendor base cost of the master, shown with the first piece. Kango Air Standard and
 * Express, and Sea, come from their rate sheet; staff may enter a different cost, with a
 * reason, and the estimate then says it was overridden. UPS and Air Cargo are entered here.
 */
export function BaseCostPanel({ master, estimate, editable, embedded = false }) {
  const t = useT();
  const refresh = useRefresh(master.id);
  const service = master.solaris_service;
  const manualService = MANUAL_SERVICES.has(service);
  const query = useQuery({
    queryKey: wsKey(master.id, 'manual-pricing'),
    queryFn: () => consolidationsApi.manualPricing(master.id),
  });
  const [form, setForm] = useState(BLANK_MANUAL);
  const [overriding, setOverriding] = useState(false);
  const [error, setError] = useState(null);
  useEffect(() => setForm(manualForm(query.data)), [query.data]);
  const overridden =
    !manualService &&
    query.data &&
    (query.data.manual_cost_vnd_per_kg != null || query.data.manual_cost_vnd_total != null);
  const save = useMutation({
    mutationFn: (values) =>
      consolidationsApi.setManualPricing(
        master.id,
        Object.fromEntries(
          Object.entries(values).map(([k, v]) => [k, String(v).trim() === '' ? null : String(v).trim()]),
        ),
      ),
    onSuccess: () => {
      setOverriding(false);
      refresh();
    },
  });
  const detail = estimate?.method_detail;
  const reference = detail?.express_reference;
  const set = (field) => (event) => setForm((c) => ({ ...c, [field]: event.target.value }));
  const label = t(`costMethod.service.${service}`, service);
  const showCost = manualService || overriding;
  const showSell = SELL_HERE.has(service);

  function submit(event) {
    event.preventDefault();
    if (form.manual_cost_vnd_per_kg.trim() && form.manual_cost_vnd_total.trim()) {
      setError(t('costMethod.perKgOrTotal'));
      return;
    }
    if (!manualService && overriding && !form.reason.trim()) {
      setError(t('wsFlow.overrideNeedsReason'));
      return;
    }
    setError(null);
    save.mutate(form);
  }

  const body = (
    <>
      <p className="ws-base-line">
        <strong>{t('wsFlow.baseCost')}:</strong> {formatVnd(detail?.base_vnd)}{' '}
        <span className="meta">· {detail?.base_basis || '—'}</span>
      </p>
      <p className="meta">
        {manualService
          ? t('wsFlow.manualIntro').replace('{service}', label)
          : t('wsFlow.rateSheetIntro').replace('{service}', label)}
      </p>
      {overridden && (
        <Banner tone="warning" title={t('wsFlow.overriddenTitle')}>
          {t('wsFlow.overriddenBody').replace('{reason}', query.data.reason || '—')}
          {reference && (
            <div>
              {t('costMethod.expressReference')
                .replace('{zone}', String(reference.zone))
                .replace('{kg}', formatKg(reference.bill_kg))
                .replace('{vnd}', formatVnd(reference.vnd))}
            </div>
          )}
        </Banner>
      )}
      {query.error && <ErrorState error={query.error} />}
      {(showCost || showSell) && (
        <form className="ws-form" onSubmit={submit}>
          {(error || save.error) && <Banner tone="danger">{error || save.error.message}</Banner>}
          <div className="ws-grid">
            {showCost &&
              [
                ['manual_cost_vnd_per_kg', 'costMethod.costPerKg'],
                ['manual_cost_vnd_total', 'costMethod.costTotal'],
              ].map(([field, key]) => (
                <Field key={field} label={t(key)}>
                  {(props) => (
                    <TextInput
                      {...props}
                      inputMode="decimal"
                      readOnly={!editable}
                      value={form[field]}
                      onChange={set(field)}
                    />
                  )}
                </Field>
              ))}
            {showSell && (
              <Field
                label={t('costMethod.sellPerKg')}
                hint={service === 'air_express' ? t('wsFlow.expressSellHint') : undefined}
              >
                {(props) => (
                  <TextInput
                    {...props}
                    inputMode="decimal"
                    readOnly={!editable}
                    value={form.manual_sell_cad_per_kg}
                    onChange={set('manual_sell_cad_per_kg')}
                  />
                )}
              </Field>
            )}
            {(showCost || manualService) && (
              <Field label={t('costMethod.reason')} required={!manualService && overriding}>
                {(props) => (
                  <TextInput
                    {...props}
                    maxLength={400}
                    readOnly={!editable}
                    value={form.reason}
                    onChange={set('reason')}
                  />
                )}
              </Field>
            )}
          </div>
          {editable && (
            <div className="row-wrap">
              <Button type="submit" variant="primary" compact loading={save.isPending}>
                {overriding ? t('wsFlow.saveOverride') : t('costMethod.saveManual')}
              </Button>
              {overriding && (
                <Button compact onClick={() => setOverriding(false)}>
                  {t('common.cancel')}
                </Button>
              )}
            </div>
          )}
        </form>
      )}
      {editable && !manualService && !overriding && (
        <div className="row-wrap">
          <Button compact onClick={() => setOverriding(true)}>
            {t('wsFlow.enterDifferentCost')}
          </Button>
          {overridden && (
            <Button
              compact
              variant="tertiary"
              loading={save.isPending}
              onClick={() =>
                save.mutate({
                  ...form,
                  manual_cost_vnd_per_kg: '',
                  manual_cost_vnd_total: '',
                  reason: '',
                })
              }
            >
              {t('wsFlow.backToRateSheet')}
            </Button>
          )}
        </div>
      )}
    </>
  );
  if (embedded) {
    return (
      <div className="ws-base" aria-label={t('wsFlow.baseCostTitle')} role="group">
        <h3 className="ws-subtitle">{t('wsFlow.baseCostTitle')}</h3>
        {body}
      </div>
    );
  }
  return <Card title={t('wsFlow.baseCostTitle')}>{body}</Card>;
}

/** Step 2 name, kept for imports: the base cost panel covers manual pricing now. */
export const ManualPricingPanel = BaseCostPanel;
