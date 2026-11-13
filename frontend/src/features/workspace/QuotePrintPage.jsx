/**
 * The printable customer quote for one finalised version (Phase 14).
 *
 * Built only from the allowlisted document route (`QuoteDocumentOut`): the company's details
 * as on invoices (OD-64), the customer, the Solaris service name, the customer's charges and
 * the total with its GST/HST sentence (RC-UAT-21). Never a vendor cost, exchange rate, markup, margin, vendor name or
 * product code -- the route does not carry them. A superseded version still prints (it is what
 * the customer was quoted then) with a visible "Superseded by vN" line. Worded in the staff member's interface
 * language (English or Vietnamese), because staff print it; the figures are the same. Nothing
 * is sent to the customer from here (sending is the Phase 13G offer).
 */

import { Link, useParams, useSearchParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { pricingApi } from '../../api/endpoints.js';
import { useT } from '../../i18n/index.jsx';
import { Button, Card } from '../../components/ui/index.jsx';
import { ErrorState, SkeletonCards } from '../../components/state/index.jsx';
import { formatDate } from '../../utils/format.js';
import { formatCad, formatKg } from './workspaceFormat.js';
import '../finance/finance.css';

/**
 * RC-UAT-21 (P-9 stand-in, pending Ben): the quote's GST/HST sentence follows the invoice rule
 * -- domestic "Prices include HST 13 %" at the destination province's rate, international
 * "Zero-rated (0 %)" -- as the Customer Account's quote does, replacing the old "added on the
 * invoice" note.
 */
export function quoteDocTaxSentence(t, tax) {
  if (!tax) return null;
  if (tax.band === 'international') return t('quoteDoc.taxZeroRated');
  if (tax.rate_percent === null || tax.rate_percent === undefined) {
    return t('quoteDoc.taxIncludedNoRate');
  }
  return t('quoteDoc.taxIncluded')
    .replace('{label}', tax.label || 'GST/HST')
    .replace('{rate}', String(tax.rate_percent));
}

export function QuotePrintPage() {
  const t = useT();
  const { shipmentId, version } = useParams();
  const [params] = useSearchParams();
  const from = params.get('from');
  const back = /^\d+$/.test(from || '') ? `/workspace/${from}` : '/workspace';
  const query = useQuery({
    queryKey: ['quote-document', shipmentId, version],
    queryFn: () => pricingApi.quoteDocument(shipmentId, version),
  });
  if (query.isLoading) return <SkeletonCards count={1} />;
  if (query.error) {
    return (
      <Card>
        <ErrorState error={query.error} onRetry={query.refetch} />
      </Card>
    );
  }
  const doc = query.data;
  const baseLabel =
    doc.billable_weight_kg && doc.rate_per_kg_cad
      ? t('quoteDoc.baseLine')
          .replace('{kg}', formatKg(doc.billable_weight_kg))
          .replace('{rate}', formatCad(doc.rate_per_kg_cad))
      : t('quoteDoc.baseLineShort');

  return (
    <>
      <div className="fin-print-actions row-wrap">
        <Link className="btn btn--secondary btn--compact" to={back}>
          {t('quoteDoc.back')}
        </Link>
        <Button compact variant="primary" onClick={() => window.print()}>
          {t('quoteDoc.print')}
        </Button>
      </div>
      <article className="fin-document" aria-label={t('quoteDoc.title')}>
        <header className="fin-document__head">
          <div>
            <div className="fin-document__brand">{doc.company_trade_name}</div>
            <div>{doc.company_name}</div>
            <div className="meta">{doc.company_address}</div>
            {doc.company_email && <div className="meta">{doc.company_email}</div>}
            <div className="meta">
              {t('quoteDoc.businessNumber')} {doc.company_business_number}
            </div>
          </div>
        </header>
        <h1>
          {t('quoteDoc.title')} {doc.shipment_reference} · v{doc.version}
        </h1>
        {doc.status === 'superseded' && (
          <p className="fin-document__notice" role="note">
            <strong>
              {doc.superseded_by_version
                ? t('quoteDoc.supersededBy').replace('{version}', `v${doc.superseded_by_version}`)
                : t('quoteDoc.superseded')}
            </strong>
          </p>
        )}
        <dl className="fin-document__meta">
          <dt>{t('quoteDoc.preparedFor')}</dt>
          <dd>
            {doc.customer_name || '—'}
            {doc.customer_reference ? ` (${doc.customer_reference})` : ''}
          </dd>
          <dt>{t('quoteDoc.shipment')}</dt>
          <dd>{doc.shipment_reference}</dd>
          <dt>{t('quoteDoc.service')}</dt>
          <dd>{doc.service}</dd>
          <dt>{t('quoteDoc.date')}</dt>
          <dd>{formatDate(doc.finalized_at)}</dd>
          <dt>{t('quoteDoc.billableWeight')}</dt>
          <dd>{formatKg(doc.billable_weight_kg)}</dd>
        </dl>
        <table className="table">
          <caption className="visually-hidden">{t('quoteDoc.charges')}</caption>
          <thead>
            <tr>
              <th scope="col">{t('quoteDoc.description')}</th>
              <th scope="col">{t('quoteDoc.amount')}</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td>{baseLabel}</td>
              <td>{formatCad(doc.base_charge_cad)}</td>
            </tr>
            {doc.surcharges.map((row, index) => (
              // Document lines have no id; their order is the quote's.
              <tr key={`${row.name}-${index}`}>
                <td>{row.name}</td>
                <td>{formatCad(row.amount_cad)}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <dl className="fin-document__totals">
          <dt>{doc.tax ? t('quoteDoc.total') : t('quoteDoc.totalBeforeTax')}</dt>
          <dd>
            <strong>{formatCad(doc.total_cad)}</strong>
          </dd>
        </dl>
        {doc.tax ? <p className="meta">{quoteDocTaxSentence(t, doc.tax)}</p> : null}
        <p className="meta">{t('quoteDoc.currencyNote')}</p>
      </article>
    </>
  );
}
