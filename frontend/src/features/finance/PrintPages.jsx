/**
 * The customer's invoice and receipt, for printing (Phase 13E).
 *
 * Built only from the allowlisted document routes (`InvoiceDocumentOut`,
 * `ReceiptDocumentOut`): revenue, never cost, margin, exchange rate or vendor. Marked as a
 * draft for review while the tax treatment and the document wording await the owner (D-11);
 * nothing is sent to a customer from here.
 *
 * An invoice issued with the Solaris Invoicing layout (DEC-0235, `tax_layout`) prints its lines
 * as the PDF does -- Qty, Rate, Amount before tax, Tax -- then Subtotal, the tax row(s), Total,
 * the terms and how to pay. An older invoice prints as before.
 */

import { Fragment } from 'react';
import { Link, useParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { financeApi } from '../../api/endpoints.js';
import { useT } from '../../i18n/index.jsx';
import { Button, Card } from '../../components/ui/index.jsx';
import { ErrorState, SkeletonCards } from '../../components/state/index.jsx';
import { formatDate, formatReceivedDate } from '../../utils/format.js';
import { formatCad, formatVnd } from '../workspace/workspaceFormat.js';
import './finance.css';

/** "gst_hst_13" -> 13; anything else -> null (an invoice from before the owner decided). */
export function taxRateOf(status) {
  const match = /^gst_hst_(\d+)$/.exec(status || '');
  return match ? Number(match[1]) : null;
}

function DocumentFrame({ back, company, children }) {
  const t = useT();
  return (
    <>
      <div className="fin-print-actions row-wrap">
        <Link className="btn btn--secondary btn--compact" to={back}>
          {t('finance.back')}
        </Link>
        <Button compact variant="primary" onClick={() => window.print()}>
          {t('finance.print')}
        </Button>
      </div>
      <article className="fin-document">
        <header className="fin-document__head">
          <div>
            <div className="fin-document__brand">{company.company_trade_name}</div>
            <div>{company.company_name}</div>
            <div className="meta">{company.company_address}</div>
            {company.company_email && <div className="meta">{company.company_email}</div>}
            <div className="meta">
              {t('finance.businessNumber')} {company.company_business_number}
            </div>
          </div>
        </header>
        {children}
      </article>
    </>
  );
}

export function InvoicePrintPage() {
  const t = useT();
  const { invoiceId } = useParams();
  const query = useQuery({
    queryKey: ['finance', 'invoice-document', invoiceId],
    queryFn: () => financeApi.invoiceDocument(invoiceId),
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
  return (
    <DocumentFrame back={`/finance/invoices/${invoiceId}`} company={doc}>
      <h1>
        {t('finance.invoiceDocTitle')} {doc.invoice_number}
        {doc.status === 'void' && ` — ${t('finance.invoiceStatus.void')}`}
      </h1>
      <dl className="fin-document__meta">
        <dt>{t('finance.billTo')}</dt>
        <dd>
          {doc.customer_name} ({doc.customer_reference})
        </dd>
        <dt>{t('finance.shipment')}</dt>
        <dd>{doc.shipment_reference}</dd>
        <dt>{t('finance.service')}</dt>
        <dd>{doc.service}</dd>
        <dt>{t('finance.issued')}</dt>
        <dd>{formatDate(doc.issued_at)}</dd>
        <dt>{t('finance.due')}</dt>
        <dd>{formatDate(doc.due_at)}</dd>
      </dl>
      {doc.tax_layout ? (
        <InvoicingDocument doc={doc} />
      ) : (
        <LegacyInvoiceDocument doc={doc} />
      )}
    </DocumentFrame>
  );
}

/** The Solaris Invoicing layout (DEC-0235): per-line Qty / Rate / Amount / Tax. */
function InvoicingDocument({ doc }) {
  const t = useT();
  return (
    <>
      <table className="table">
        <thead>
          <tr>
            <th scope="col">{t('finance.description')}</th>
            <th scope="col">{t('finance.quantity')}</th>
            <th scope="col">{t('finance.unitPrice')}</th>
            <th scope="col">{t('finance.amount')}</th>
            <th scope="col">{t('finance.taxCode')}</th>
          </tr>
        </thead>
        <tbody>
          {doc.lines.map((line, index) => (
            // Document lines have no id; their order is the invoice's.
            <tr key={`${line.description}-${index}`}>
              <td>{line.description}</td>
              <td>{line.quantity === null ? '1' : Number(line.quantity)}</td>
              <td>{line.unit_price_cad === null ? '—' : Number(line.unit_price_cad).toFixed(4)}</td>
              <td>{formatCad(line.amount_cad)}</td>
              <td>{line.tax_code}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <dl className="fin-document__totals">
        <dt>{t('finance.subtotal')}</dt>
        <dd>{formatCad(doc.subtotal_cad)}</dd>
        {(doc.tax_rows || []).map((row) => (
          <Fragment key={row.label}>
            <dt>{row.label}</dt>
            <dd>{formatCad(row.tax_cad)}</dd>
          </Fragment>
        ))}
        <dt>{t('finance.total')}</dt>
        <dd>
          <strong>{formatCad(doc.total_cad)}</strong>
        </dd>
        <dt>{t('finance.paid')}</dt>
        <dd>{formatCad(doc.paid_cad)}</dd>
        <dt>{t('finance.balance')}</dt>
        <dd>
          <strong>{formatCad(doc.balance_cad)}</strong>
        </dd>
      </dl>
      <p className="meta">Terms: {doc.payment_terms}</p>
      <p className="meta">Payment: E-transfer to {doc.payment_etransfer}</p>
      <p className="meta">Wire: {doc.payment_wire}</p>
    </>
  );
}

/** An invoice issued before DEC-0235, printed as it always was. */
function LegacyInvoiceDocument({ doc }) {
  const t = useT();
  return (
    <>
      <table className="table">
        <thead>
          <tr>
            <th scope="col">{t('finance.description')}</th>
            <th scope="col">{t('finance.quantity')}</th>
            <th scope="col">{t('finance.amount')}</th>
          </tr>
        </thead>
        <tbody>
          {doc.lines.map((line, index) => (
            // Document lines have no id; their order is the invoice's.
            <tr key={`${line.description}-${index}`}>
              <td>{line.description}</td>
              <td>{line.quantity === null ? '—' : `${Number(line.quantity)} ${line.unit || ''}`}</td>
              <td>{formatCad(line.amount_cad)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {doc.tax_included_note && (
        // Owner, 2026-10-22: the line amounts include the GST/HST (customer's language).
        <p className="fin-document__tax-note">{doc.tax_included_note}</p>
      )}
      <dl className="fin-document__totals">
        <dt>{doc.tax_included_note ? t('finance.subtotalBeforeTax') : t('finance.subtotal')}</dt>
        <dd>{formatCad(doc.subtotal_cad)}</dd>
        <dt>
          {/* Review 2026-10-24: "HST 13 %", "GST 5 %", "Zero-rated (0 %)" from the document. */}
          {doc.tax_line_label ||
            (taxRateOf(doc.tax_status) === null
              ? t('finance.tax')
              : t('finance.taxLabel').replace('{rate}', String(taxRateOf(doc.tax_status))))}
        </dt>
        <dd>{doc.tax_cad === null ? t('finance.taxUnderReview') : formatCad(doc.tax_cad)}</dd>
        <dt>{t('finance.total')}</dt>
        <dd>
          <strong>{formatCad(doc.total_cad)}</strong>
        </dd>
        <dt>{t('finance.paid')}</dt>
        <dd>{formatCad(doc.paid_cad)}</dd>
        <dt>{t('finance.balance')}</dt>
        <dd>
          <strong>{formatCad(doc.balance_cad)}</strong>
        </dd>
      </dl>
    </>
  );
}

export function ReceiptPrintPage() {
  const t = useT();
  const { paymentId } = useParams();
  const query = useQuery({
    queryKey: ['finance', 'receipt', paymentId],
    queryFn: () => financeApi.receipt(paymentId),
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
  return (
    <DocumentFrame back="/finance" company={doc}>
      <h1>
        {t('finance.receiptDocTitle')} {doc.receipt_number}
      </h1>
      <dl className="fin-document__meta">
        <dt>{t('finance.receivedFrom')}</dt>
        <dd>
          {doc.customer_name} ({doc.customer_reference})
        </dd>
        <dt>{t('finance.invoice')}</dt>
        <dd>{doc.invoice_number}</dd>
        <dt>{t('finance.shipment')}</dt>
        <dd>{doc.shipment_reference}</dd>
        <dt>{t('finance.date')}</dt>
        <dd>{formatReceivedDate(doc.received_at)}</dd>
        <dt>{t('finance.method')}</dt>
        <dd>{t(`finance.methods.${doc.method}`, doc.method)}</dd>
        {doc.reference && (
          <>
            <dt>{t('finance.reference')}</dt>
            <dd>{doc.reference}</dd>
          </>
        )}
      </dl>
      <dl className="fin-document__totals">
        {doc.amount_received_vnd && (
          <>
            <dt>{t('finance.amountReceivedVnd')}</dt>
            <dd>{formatVnd(doc.amount_received_vnd)}</dd>
            <dt>{t('finance.conversion')}</dt>
            <dd>{t('finance.conversionValue').replace('{rate}', formatVnd(doc.conversion_vnd_per_cad))}</dd>
          </>
        )}
        <dt>{t('finance.amountReceived')}</dt>
        <dd>
          <strong>{formatCad(doc.amount_cad)}</strong>
        </dd>
        <dt>{t('finance.invoiceTotal')}</dt>
        <dd>{formatCad(doc.invoice_total_cad)}</dd>
        <dt>{t('finance.balance')}</dt>
        <dd>{formatCad(doc.balance_cad)}</dd>
      </dl>
    </DocumentFrame>
  );
}
