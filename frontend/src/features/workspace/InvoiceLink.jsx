/**
 * From a finalised quote to its invoice (Phase 13E): the invoice when one exists, else the
 * button that issues it. An invoice is only ever issued from a finalised quote; the server
 * refuses anything else.
 *
 * Owner decision 9a (2026-10-21): when the customer accepted the quote, its invoice was
 * prepared as a draft; Issue invoice then leads to the draft, where staff review and send it.
 * An expired quote (decision 9) is not invoiced: re-quote first.
 */

import { Link } from 'react-router-dom';
import { useState } from 'react';
import { useMutation, useQuery } from '@tanstack/react-query';
import { financeApi, invoiceDraftsApi, pricingApi } from '../../api/endpoints.js';
import { P, useOptionalSession } from '../../app/SessionContext.jsx';
import { useT } from '../../i18n/index.jsx';
import { Banner, Button, Field, Select } from '../../components/ui/index.jsx';
import { formatCad, wsKey } from './workspaceFormat.js';

/** The Issue invoice button's id, so the accepted-quote prompt (Phase 15) can move to it. */
export function issueInvoiceButtonId(shipmentId) {
  return `ws-issue-invoice-${shipmentId}`;
}

/** Offer states that leave Issue invoice allowed but warned (Phase 17 stand-in). */
const CLOSED_OFFER_STATES = ['withdrawn', 'declined'];

export function InvoiceLink({
  consolidationId,
  shipmentId,
  customerLabel,
  refresh,
  finalized,
  expired = false,
}) {
  const t = useT();
  const session = useOptionalSession();
  const canRead = Boolean(session?.can(P.FINANCIAL_READ));
  const canIssue = Boolean(session?.can(P.FINANCIAL_WRITE));
  const query = useQuery({
    queryKey: wsKey(consolidationId, 'invoice', shipmentId),
    queryFn: () => financeApi.shipmentInvoice(shipmentId),
    enabled: canRead,
  });
  const draftQuery = useQuery({
    queryKey: wsKey(consolidationId, 'invoice-draft', shipmentId),
    queryFn: () => invoiceDraftsApi.forShipment(shipmentId),
    enabled: canRead,
  });
  // GST/HST is chosen per invoice (OD-64): 0 % for an international move, 5 or 13 % for a
  // domestic one. Staff choose; nothing guesses it.
  const [taxRate, setTaxRate] = useState('0');
  const issue = useMutation({
    mutationFn: () => financeApi.issueInvoice(shipmentId, Number(taxRate)),
    onSuccess: refresh,
  });
  // The same query (and cache entry) as the offer panel's.
  const offersQuery = useQuery({
    queryKey: wsKey(consolidationId, 'offers', shipmentId),
    queryFn: () => pricingApi.offers(shipmentId),
    enabled: canIssue && Boolean(finalized),
  });
  if (!canRead || query.isLoading || draftQuery.isLoading) return null;
  const invoice = query.data;
  const draft = draftQuery.data?.status === 'draft' ? draftQuery.data : null;
  const closedOffer = finalized
    ? (offersQuery.data ?? []).find(
        (offer) =>
          offer.quote_version_id === finalized.id && CLOSED_OFFER_STATES.includes(offer.status),
      )
    : null;
  if (invoice) {
    return (
      <p className="ws-invoice">
        <Link className="mono" to={`/finance/invoices/${invoice.id}`}>
          {invoice.public_id}
        </Link>{' '}
        · {t(`finance.invoiceStatus.${invoice.status}`, invoice.status)} · {t('finance.balance')}{' '}
        {formatCad(invoice.balance_cad)}
      </p>
    );
  }
  if (draft) {
    return (
      <div className="ws-invoice">
        <p className="meta">{t('invoiceDraft.workspaceReady')}</p>
        <Link
          className="btn btn--primary btn--compact"
          id={issueInvoiceButtonId(shipmentId)}
          to={`/finance/invoice-drafts/${draft.id}`}
          aria-label={`${t('invoiceDraft.open')} — ${customerLabel}`}
        >
          {t('invoiceDraft.open')}
        </Link>
      </div>
    );
  }
  if (!canIssue) return null;
  if (expired) return <p className="meta ws-invoice">{t('quoteExpiry.noInvoice')}</p>;
  return (
    <div className="ws-invoice">
      {issue.error && <Banner tone="danger">{issue.error.message}</Banner>}
      {closedOffer && (
        <Banner tone="warning">
          {t('finance.issueOfferWarning')
            .replace('{version}', String(finalized.version))
            .replace(
              '{status}',
              t(`workspace.offer.status.${closedOffer.status}`, closedOffer.status),
            )}
        </Banner>
      )}
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
      <Button
        compact
        variant="primary"
        id={issueInvoiceButtonId(shipmentId)}
        loading={issue.isPending}
        onClick={() => issue.mutate()}
        aria-label={`${t('finance.issueInvoice')} — ${customerLabel}`}
      >
        {t('finance.issueInvoice')}
      </Button>
    </div>
  );
}
