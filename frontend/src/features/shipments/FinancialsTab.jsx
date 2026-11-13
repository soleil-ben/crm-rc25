/**
 * The shipment page's Financials tab.
 *
 * Two parts:
 *
 * 1. **Quote and invoice** (RC-UAT-25 item 8, Ben 2026-10-25): straight after booking, the
 *    quoted revenue, the vendor cost when the role may see it (``tariff:read``, as on the
 *    quote and vendor-bill screens), and one clear next step -- price, finalise, issue the
 *    invoice (the manual path, ``POST /shipments/{id}/invoice``), review the draft prepared
 *    when the customer accepted, or open the issued invoice. A blocked Issue invoice is shown
 *    disabled with the refusal Issue invoice itself would return. Refunds and voids stay on
 *    the invoice page.
 * 2. **Recorded amounts**: the manually entered selling amount, costs and currency.
 *
 * RC-UAT-25 item 7: a currency stored as typed ("CA", "$") made the money formatter throw and
 * the whole page went blank. The server now refuses such a code, this form checks it before
 * saving, `formatMoney` no longer throws, and a code stored before the fix is shown with a
 * request to correct it.
 */

import { useState } from 'react';
import { Link } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { financeApi, shipmentsApi } from '../../api/endpoints.js';
import { useT } from '../../i18n/index.jsx';
import { P, useSession } from '../../app/SessionContext.jsx';
import { Banner, Button, Card, Field, Select, TextInput } from '../../components/ui/index.jsx';
import { EmptyState, SkeletonRows } from '../../components/state/index.jsx';
import { formatMoney, isFormattableCurrency } from '../../utils/format.js';

const CURRENCY_CODE = /^[A-Za-z]{3}$/;
const NEXT_STEPS = [
  'add_to_master',
  'price',
  'finalise_quote',
  'requote',
  'issue_invoice',
  'review_draft',
  'open_invoice',
];

function Detail({ label, children }) {
  return (
    <div className="detail-row">
      <span className="detail-row__label">{label}</span>
      <span className="detail-row__value">{children ?? '—'}</span>
    </div>
  );
}

function cad(value) {
  return formatMoney(value, 'CAD');
}

/** The step's action: a link, the Issue invoice form, or nothing. */
function NextStepAction({ summary, shipmentId }) {
  const t = useT();
  const queryClient = useQueryClient();
  const [taxRate, setTaxRate] = useState('0');
  const issue = useMutation({
    mutationFn: () => financeApi.issueInvoice(shipmentId, Number(taxRate)),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['shipment-financial-summary', String(shipmentId)] });
      queryClient.invalidateQueries({ queryKey: ['shipment', String(shipmentId)] });
    },
  });
  const master = summary.master;
  const workspaceLink = master ? `/workspace/${master.id}` : '/workspace';
  const step = summary.next_step;

  if (step === 'open_invoice' && summary.invoice) {
    return (
      <Link className="btn btn--primary" to={`/finance/invoices/${summary.invoice.id}`}>
        {t('shipmentDetail.finOpenInvoice').replace('{id}', summary.invoice.public_id)}
      </Link>
    );
  }
  if (step === 'review_draft' && summary.draft_invoice) {
    return (
      <Link
        className="btn btn--primary"
        to={`/finance/invoice-drafts/${summary.draft_invoice.id}`}
      >
        {t('shipmentDetail.finReviewDraft')}
      </Link>
    );
  }
  if (step === 'issue_invoice') {
    if (!summary.can_issue_invoice) {
      return (
        <>
          <Button variant="primary" disabled>
            {t('finance.issueInvoice')}
          </Button>
          <p className="meta">{t('shipmentDetail.finIssueNoPermission')}</p>
        </>
      );
    }
    return (
      <div className="fin-issue">
        {issue.error && <Banner tone="danger">{issue.error.message}</Banner>}
        <Field label={t('finance.taxRate')} hint={t('finance.taxRateHint')}>
          {(props) => (
            <Select
              {...props}
              value={taxRate}
              onChange={(event) => setTaxRate(event.target.value)}
              options={['0', '5', '13'].map((value) => ({ value, label: `${value} %` }))}
            />
          )}
        </Field>
        <Button variant="primary" loading={issue.isPending} onClick={() => issue.mutate()}>
          {t('finance.issueInvoice')}
        </Button>
      </div>
    );
  }

  // Not invoiceable yet: the way forward, then Issue invoice disabled with the server's reason.
  const actionLabel = {
    add_to_master: 'shipmentDetail.finOpenWorkspace',
    price: 'shipmentDetail.finPriceAction',
    finalise_quote: 'shipmentDetail.finFinaliseAction',
    requote: 'shipmentDetail.finRequoteAction',
  }[step];
  return (
    <>
      {actionLabel &&
        (summary.can_price ? (
          <Link className="btn btn--primary" to={workspaceLink}>
            {t(actionLabel)}
          </Link>
        ) : (
          <p className="meta">{t('shipmentDetail.finPriceNoPermission')}</p>
        ))}
      {summary.can_issue_invoice && (
        <div className="fin-blocked">
          <Button disabled aria-describedby="fin-issue-blocked">
            {t('finance.issueInvoice')}
          </Button>
          {summary.invoice_blocked_reason && (
            <p className="meta" id="fin-issue-blocked">
              {t('shipmentDetail.finIssueBlocked')} {summary.invoice_blocked_reason}
            </p>
          )}
        </div>
      )}
    </>
  );
}

function QuoteInvoiceSummary({ shipmentId }) {
  const t = useT();
  const query = useQuery({
    queryKey: ['shipment-financial-summary', String(shipmentId)],
    queryFn: () => financeApi.shipmentFinancialSummary(shipmentId),
  });
  if (query.isLoading) {
    return (
      <Card title={t('shipmentDetail.finSummaryTitle')}>
        <SkeletonRows rows={3} />
      </Card>
    );
  }
  const summary = query.data;
  if (query.error || !summary || !NEXT_STEPS.includes(summary.next_step)) {
    return (
      <Card title={t('shipmentDetail.finSummaryTitle')}>
        <Banner tone="warning">
          {t('shipmentDetail.finSummaryError')}
          {query.error?.message ? ` ${query.error.message}` : ''}
        </Banner>
        <Button onClick={() => query.refetch()}>{t('states.panelErrorRetry')}</Button>
      </Card>
    );
  }

  const quote = summary.quote;
  const master = summary.master;
  const invoice = summary.invoice;
  const stepKey = {
    add_to_master: 'finStepAddToMaster',
    price: 'finStepPrice',
    finalise_quote: 'finStepFinalise',
    requote: 'finStepRequote',
    issue_invoice: 'finStepIssue',
    review_draft: 'finStepReviewDraft',
    open_invoice: 'finStepOpenInvoice',
  }[summary.next_step];

  return (
    <Card title={t('shipmentDetail.finSummaryTitle')}>
      <section aria-label={t('shipmentDetail.finSummaryTitle')} data-testid="fin-summary">
        <Detail label={t('shipmentDetail.finMaster')}>
          {master ? (
            <>
              <span className="mono">{master.public_id}</span>
              {master.locked && <span className="meta"> · {t('shipmentDetail.finMasterLocked')}</span>}
            </>
          ) : (
            t('shipmentDetail.finMasterNone')
          )}
        </Detail>
        <Detail label={t('shipmentDetail.finQuote')}>
          {quote
            ? `v${quote.version} · ${t(`shipmentDetail.finQuoteStatus.${quote.status}`, quote.status)}${
                quote.expired ? ` · ${t('shipmentDetail.finExpired')}` : ''
              }`
            : t('shipmentDetail.finNoQuote')}
        </Detail>
        {quote && (
          <>
            <Detail label={t('shipmentDetail.finRevenue')}>{cad(quote.total_revenue_cad)}</Detail>
            {summary.cost_visible ? (
              <>
                <Detail label={t('shipmentDetail.finCost')}>
                  {cad(quote.allocated_cost_cad)}
                </Detail>
                <Detail label={t('shipmentDetail.finMargin')}>
                  {cad(quote.gross_profit_cad)}
                </Detail>
              </>
            ) : (
              <p className="meta">{t('shipmentDetail.finCostHidden')}</p>
            )}
          </>
        )}
        {invoice && (
          <Detail label={t('shipmentDetail.finInvoice')}>
            <span className="mono">{invoice.public_id}</span> ·{' '}
            {t(`finance.invoiceStatus.${invoice.status}`, invoice.status)} ·{' '}
            {t('finance.balance')} {cad(invoice.balance_cad)}
          </Detail>
        )}
        <div className="fin-next" data-testid="fin-next-step" data-step={summary.next_step}>
          <p>
            <strong>{t(`shipmentDetail.${stepKey}`)}</strong>
          </p>
          <NextStepAction summary={summary} shipmentId={shipmentId} />
        </div>
      </section>
    </Card>
  );
}

function RecordedAmounts({ shipment, financials }) {
  const t = useT();
  const { can } = useSession();
  const queryClient = useQueryClient();
  const [form, setForm] = useState(() => ({
    selling_amount: financials?.selling_amount ?? '',
    shipping_cost: financials?.costs?.shipping_cost ?? '',
    surcharges_amount: financials?.costs?.surcharges_amount ?? '',
    discount_amount: financials?.discount_amount ?? '',
    refund_amount: financials?.refund_amount ?? '',
    currency: financials?.currency ?? '',
  }));
  const [currencyError, setCurrencyError] = useState(null);

  const mutation = useMutation({
    mutationFn: () => {
      const payload = {};
      Object.entries(form).forEach(([key, value]) => {
        if (value !== '' && value !== null) payload[key] = value;
      });
      return shipmentsApi.updateFinancials(shipment.id, payload);
    },
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: ['shipment', String(shipment.id)] }),
  });

  const currency = isFormattableCurrency(financials.currency)
    ? financials.currency || 'CAD'
    : financials.currency;

  return (
    <Card title={t('shipmentDetail.financialsTitle')}>
      <Banner tone="neutral">{financials.coverage_note}</Banner>
      {!isFormattableCurrency(financials.currency) && (
        <Banner tone="warning">
          {t('shipmentDetail.financialsCurrencyInvalid').replace(
            '{code}',
            String(financials.currency),
          )}
        </Banner>
      )}

      <Detail label={t('shipmentDetail.sellingAmount')}>
        {formatMoney(financials.selling_amount, currency)}
      </Detail>
      <Detail label={t('shipmentDetail.discount')}>
        {formatMoney(financials.discount_amount, currency)}
      </Detail>
      <Detail label={t('shipmentDetail.refund')}>
        {formatMoney(financials.refund_amount, currency)}
      </Detail>
      <Detail label={t('shipmentDetail.declaredValue')}>
        {formatMoney(financials.declared_value, financials.declared_value_currency || currency)}
      </Detail>

      {financials.costs ? (
        <>
          <Detail label={t('shipmentDetail.shippingCost')}>
            {formatMoney(financials.costs.shipping_cost, currency)}
          </Detail>
          <Detail label={t('shipmentDetail.surcharges')}>
            {formatMoney(financials.costs.surcharges_amount, currency)}
          </Detail>
          {/* Selling amount less discount, refund, shipping cost and surcharges. The API
              sends null -- never zero -- when either side is unrecorded, and `formatMoney`
              renders that as Unknown (fix pack item 7). */}
          <Detail label={t('shipmentDetail.grossProfit')}>
            <strong>{formatMoney(financials.costs.gross_profit, currency)}</strong>
          </Detail>
        </>
      ) : (
        <p className="meta">{t('shipmentDetail.costsHidden')}</p>
      )}

      {can(P.FINANCIAL_WRITE) && (
        <form
          onSubmit={(event) => {
            event.preventDefault();
            const code = String(form.currency ?? '').trim();
            if (code && !CURRENCY_CODE.test(code)) {
              setCurrencyError(t('shipmentDetail.currencyInvalid'));
              return;
            }
            setCurrencyError(null);
            mutation.mutate();
          }}
        >
          {mutation.error && <Banner tone="danger">{mutation.error.message}</Banner>}
          <div className="form-grid">
            <Field
              label={t('booking.declaredCurrency')}
              hint={t('shipmentDetail.currencyHint')}
              error={currencyError}
            >
              {(props) => (
                <TextInput
                  {...props}
                  maxLength={3}
                  value={form.currency}
                  onChange={(event) =>
                    setForm({ ...form, currency: event.target.value.toUpperCase() })
                  }
                />
              )}
            </Field>
            <Field label={t('shipmentDetail.sellingAmount')}>
              {(props) => (
                <TextInput
                  {...props}
                  inputMode="decimal"
                  value={form.selling_amount}
                  onChange={(event) => setForm({ ...form, selling_amount: event.target.value })}
                />
              )}
            </Field>
            {financials.costs && (
              <>
                <Field label={t('shipmentDetail.shippingCost')}>
                  {(props) => (
                    <TextInput
                      {...props}
                      inputMode="decimal"
                      value={form.shipping_cost}
                      onChange={(event) =>
                        setForm({ ...form, shipping_cost: event.target.value })
                      }
                    />
                  )}
                </Field>
                <Field label={t('shipmentDetail.surcharges')}>
                  {(props) => (
                    <TextInput
                      {...props}
                      inputMode="decimal"
                      value={form.surcharges_amount}
                      onChange={(event) =>
                        setForm({ ...form, surcharges_amount: event.target.value })
                      }
                    />
                  )}
                </Field>
              </>
            )}
          </div>
          <Button type="submit" variant="primary" loading={mutation.isPending}>
            {t('shipmentDetail.saveFinancials')}
          </Button>
        </form>
      )}
    </Card>
  );
}

export function FinancialsTab({ shipment }) {
  const t = useT();
  const financials = shipment.financials;

  // The API omits the block entirely for a role without financial:read.
  if (!financials) {
    return (
      <Card>
        <EmptyState title={t('shipmentDetail.financialsHidden')} />
      </Card>
    );
  }

  return (
    <>
      <QuoteInvoiceSummary shipmentId={shipment.id} />
      <RecordedAmounts shipment={shipment} financials={financials} />
    </>
  );
}
