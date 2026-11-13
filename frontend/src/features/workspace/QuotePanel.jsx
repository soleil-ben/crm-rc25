/**
 * One customer's quote (Phase 13D): price it, confirm or override the selling rate, and
 * finalise. Everything is the server's: the default rate (OD-48, configurable and flagged
 * until the owner confirms it), the reason an override needs (OD-45), the refusal while
 * any blocking issue exists, and the reason a surcharge billed below cost needs (OD-44).
 *
 * A finalised version is frozen; a later change opens a new draft beside it.
 */

import { useState } from 'react';
import { Link } from 'react-router-dom';
import { useMutation, useQuery } from '@tanstack/react-query';
import { pricingApi } from '../../api/endpoints.js';
import { useT } from '../../i18n/index.jsx';
import { Banner, Button, Field, StatusBadge, TextArea, TextInput } from '../../components/ui/index.jsx';
import { formatCad, formatKg, formatVnd, wsKey } from './workspaceFormat.js';
import { IssueList } from './MasterPanels.jsx';
import { InvoiceLink } from './InvoiceLink.jsx';
import { OfferPanel } from './OfferPanel.jsx';
import { QuoteHistoryAdmin } from './QuoteHistoryAdmin.jsx';

const STATUS_TONE = { draft: 'info', finalized: 'success', superseded: 'neutral' };

function Problems({ error }) {
  if (!error) return null;
  const problems = error.detail?.problems;
  return (
    <Banner tone="danger" title={error.message}>
      {Array.isArray(problems) && problems.length > 0 && (
        <ul className="ws-issues">
          {problems.map((p, index) => (
            <li key={`${p.code}-${index}`}>{p.message || p.code}</li>
          ))}
        </ul>
      )}
    </Banner>
  );
}

function Figures({ version }) {
  const t = useT();
  return (
    <>
      <dl className="ws-details">
        <div className="ws-detail">
          <dt>{t('workspace.billableWeight')}</dt>
          <dd>{formatKg(version.billable_weight_kg)}</dd>
        </div>
        <div className="ws-detail">
          <dt>{t('workspace.sellingRate')}</dt>
          <dd>
            {formatCad(version.selling_rate_cad)} / kg{' '}
            <span className="meta">
              ({t('workspace.defaultRate')} {formatCad(version.default_rate_cad)})
            </span>
          </dd>
        </div>
        <div className="ws-detail">
          <dt>{t('workspace.revenue')}</dt>
          <dd>{formatCad(version.total_revenue_cad)}</dd>
        </div>
        <div className="ws-detail">
          <dt>{t('workspace.allocatedCost')}</dt>
          <dd>{formatCad(version.allocated_cost_cad)}</dd>
        </div>
        <div className="ws-detail">
          <dt>{t('workspace.grossProfit')}</dt>
          <dd>
            <strong>{formatCad(version.gross_profit_cad)}</strong>
          </dd>
        </div>
      </dl>
      <div className="table-wrap">
        <table className="table ws-lines">
          <thead>
            <tr>
              <th scope="col">{t('workspace.line')}</th>
              <th scope="col">{t('workspace.revenue')}</th>
              <th scope="col">{t('workspace.costVnd')}</th>
              <th scope="col">{t('workspace.costCad')}</th>
            </tr>
          </thead>
          <tbody>
            {version.lines.map((line) => (
              <tr key={line.sequence}>
                <td>
                  {line.description}
                  {!line.is_trigger && line.kind === 'surcharge' && (
                    <span className="meta"> · {t('workspace.costShareOnly')}</span>
                  )}
                </td>
                <td>{formatCad(line.revenue_cad)}</td>
                <td>{formatVnd(line.cost_vnd)}</td>
                <td>{formatCad(line.cost_cad)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

export function QuotePanel({
  consolidationId,
  shipmentId,
  refresh,
  editable,
  customerLabel,
  currentCostCad,
}) {
  const t = useT();
  const quotesQuery = useQuery({
    queryKey: wsKey(consolidationId, 'quotes', shipmentId),
    queryFn: () => pricingApi.quotes(shipmentId),
  });
  const versions = quotesQuery.data ?? [];
  const draft = versions.find((v) => v.status === 'draft');
  const finalized = [...versions].reverse().find((v) => v.status === 'finalized');
  const current = draft || finalized;

  const [rate, setRate] = useState('');
  const [reason, setReason] = useState('');
  const [marginReason, setMarginReason] = useState('');

  // A blank box confirms the rate the draft already carries, override included; it never
  // falls back to the default behind the user's back.
  const effectiveRate = rate || current?.selling_rate_cad || undefined;
  const differs =
    Boolean(current) &&
    effectiveRate !== undefined &&
    Number(effectiveRate) !== Number(current.default_rate_cad);
  // The draft's figures were written when it was last priced; the estimate beside it is
  // live. When they disagree, say so rather than show two different costs silently.
  const stale =
    Boolean(draft) &&
    currentCostCad !== null &&
    currentCostCad !== undefined &&
    draft.allocated_cost_cad !== null &&
    Math.abs(Number(draft.allocated_cost_cad) - Number(currentCostCad)) >= 0.005;
  const forWhom = (label) => (customerLabel ? `${label} — ${customerLabel}` : label);

  const reprice = useMutation({ mutationFn: () => pricingApi.reprice(shipmentId), onSuccess: refresh });
  const confirm = useMutation({
    mutationFn: () =>
      pricingApi.confirmRate(shipmentId, {
        rate: effectiveRate,
        reason: differs ? reason || current.override_reason || undefined : undefined,
      }),
    onSuccess: () => {
      setRate('');
      setReason('');
      refresh();
    },
  });
  const finalize = useMutation({
    mutationFn: () =>
      pricingApi.finalize(shipmentId, { negative_margin_reason: marginReason || undefined }),
    onSuccess: () => {
      setMarginReason('');
      refresh();
    },
  });


  return (
    <div className="ws-quote">
      <div className="ws-quote__head">
        <h4>{t('workspace.quoteTitle')}</h4>
        {current && (
          <StatusBadge
            tone={STATUS_TONE[current.status]}
            label={`v${current.version} · ${t(`workspace.quoteStatus.${current.status}`, current.status)}`}
          />
        )}
        {current?.status === 'draft' && (
          <StatusBadge
            tone={current.rate_confirmed ? 'success' : 'warning'}
            label={current.rate_confirmed ? t('workspace.rateConfirmed') : t('workspace.rateNotConfirmed')}
          />
        )}
        <span className="spacer" />
        {editable && (
          <Button
            compact
            loading={reprice.isPending}
            onClick={() => reprice.mutate()}
            aria-label={forWhom(draft ? t('workspace.reprice') : t('workspace.priceQuote'))}
          >
            {draft ? t('workspace.reprice') : t('workspace.priceQuote')}
          </Button>
        )}
      </div>
      <Problems error={reprice.error} />
      {/* Owner decision 9: a new tariff became active before the goods were received. */}
      {finalized?.expiry && !draft && (
        <Banner
          tone="warning"
          title={t('quoteExpiry.title')}
          action={
            editable ? (
              <Button
                compact
                loading={reprice.isPending}
                onClick={() => reprice.mutate()}
                aria-label={forWhom(t('quoteExpiry.requote'))}
              >
                {t('quoteExpiry.requote')}
              </Button>
            ) : null
          }
        >
          {t('quoteExpiry.body')
            .replace('{version}', String(finalized.version))
            .replace('{tariff}', finalized.expiry.tariff_version_public_id || '')}
        </Banner>
      )}
      {stale && <Banner tone="warning">{t('workspace.staleQuote')}</Banner>}
      {!current ? (
        <p className="meta">{t('workspace.noQuote')}</p>
      ) : (
        <>
          <Figures version={current} />
          {finalized && (
            <p>
              <Link
                className="btn btn--secondary btn--compact"
                to={`/workspace/quotes/${shipmentId}/${finalized.version}/print?from=${consolidationId}`}
                aria-label={forWhom(`${t('workspace.printQuote')} v${finalized.version}`)}
              >
                {t('workspace.printQuote')} v{finalized.version}
              </Link>
            </p>
          )}
          {finalized && (
            <InvoiceLink
              consolidationId={consolidationId}
              shipmentId={shipmentId}
              customerLabel={customerLabel}
              refresh={refresh}
              finalized={finalized}
              expired={Boolean(finalized.expiry)}
            />
          )}
          {/* Phase 13G (OD-77): send the finalised quote; the customer answers in their
              account. Not while a newer draft is open: finalise it first. */}
          {finalized && (
            <OfferPanel
              consolidationId={consolidationId}
              shipmentId={shipmentId}
              finalized={finalized}
              canSend={!draft && !finalized.expiry}
              customerLabel={customerLabel}
              refresh={refresh}
            />
          )}
          {current.status === 'draft' && (
            <>
              <IssueList issues={current.blocking} tone="danger" title={t('workspace.blockingTitle')} />
              <IssueList
                issues={current.provisional}
                tone="warning"
                title={t('workspace.provisionalTitle')}
              />
            </>
          )}
          {current.status === 'draft' && editable && (
            <>
              <form
                className="ws-form"
                onSubmit={(event) => {
                  event.preventDefault();
                  confirm.mutate();
                }}
              >
                <Problems error={confirm.error} />
                <div className="ws-grid">
                  <Field label={t('workspace.rateToConfirm')} hint={t('workspace.rateToConfirmHint')}>
                    {(props) => (
                      <TextInput
                        {...props}
                        inputMode="decimal"
                        placeholder={current.selling_rate_cad ? String(Number(current.selling_rate_cad)) : ''}
                        value={rate}
                        onChange={(event) => setRate(event.target.value)}
                      />
                    )}
                  </Field>
                  {differs && (
                    <Field label={t('workspace.overrideReason')} required>
                      {(props) => (
                        <TextArea
                          {...props}
                          rows={2}
                          placeholder={current.override_reason || ''}
                          value={reason}
                          onChange={(event) => setReason(event.target.value)}
                        />
                      )}
                    </Field>
                  )}
                </div>
                <Button
                  type="submit"
                  loading={confirm.isPending}
                  aria-label={forWhom(t('workspace.confirmRate'))}
                >
                  {t('workspace.confirmRate')}
                </Button>
              </form>
              <form
                className="ws-form"
                onSubmit={(event) => {
                  event.preventDefault();
                  finalize.mutate();
                }}
              >
                <Problems error={finalize.error} />
                <Field label={t('workspace.marginReason')} hint={t('workspace.marginReasonHint')}>
                  {(props) => (
                    <TextArea
                      {...props}
                      rows={2}
                      value={marginReason}
                      onChange={(event) => setMarginReason(event.target.value)}
                    />
                  )}
                </Field>
                <Button
                  type="submit"
                  variant="primary"
                  loading={finalize.isPending}
                  aria-label={forWhom(t('workspace.finalize'))}
                >
                  {t('workspace.finalize')}
                </Button>
              </form>
            </>
          )}
        </>
      )}
      {/* RC-UAT-21 Phase D (DEC-0233): Admin soft delete and restore of old versions. */}
      <QuoteHistoryAdmin
        consolidationId={consolidationId}
        shipmentId={shipmentId}
        refresh={refresh}
        customerLabel={customerLabel}
      />
    </div>
  );
}
