/**
 * One customer invoice (Phase 13E): lines, payments and receipts, record a payment, refund
 * a payment (Admin), void (Admin), and print the customer's invoice or a receipt.
 *
 * Payments are CAD only and never exceed the balance: nothing is kept as credit. A receipt
 * exists only for a recorded payment.
 *
 * An invoice issued with the Solaris Invoicing layout (`tax_layout: invoicing_v1`; owner Ben,
 * 2026-10-24, DEC-0235) shows its lines as printed -- Description, Qty (blank reads 1), Rate,
 * Amount before tax, Tax -- and Subtotal, the tax row(s) and Total. An older invoice shows
 * its lines as before.
 */

import { useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { financeApi, invoiceDraftsApi } from '../../api/endpoints.js';
import { saveBlob } from '../../api/client.js';
import { P, useSession } from '../../app/SessionContext.jsx';
import { useT } from '../../i18n/index.jsx';
import { PageHeader } from '../../components/layout/AppShell.jsx';
import { Banner, Button, Card, Field, Select, StatusBadge, TextInput } from '../../components/ui/index.jsx';
import { ErrorState, SkeletonCards } from '../../components/state/index.jsx';
import { formatDate, formatReceivedDate, localToday } from '../../utils/format.js';
import { formatCad } from '../workspace/workspaceFormat.js';
import { INVOICE_TONE } from './FinancePage.jsx';
import './finance.css';

const METHODS = ['cash', 'bank_transfer', 'e_transfer', 'card', 'other'];

/** Today's date where staff are (the browser's zone), never the UTC date (RC-20). */
function today() {
  return localToday();
}

function PaymentForm({ invoice, onDone }) {
  const t = useT();
  const [form, setForm] = useState({
    currency: 'CAD',
    amount: '',
    method: 'e_transfer',
    reference: '',
    received_at: today(),
  });
  const set = (field) => (event) => setForm((current) => ({ ...current, [field]: event.target.value }));
  const record = useMutation({
    mutationFn: () =>
      financeApi.recordPayment(invoice.id, {
        currency: form.currency,
        // OD-66: a VND payment is converted at Vietcombank's selling rate on the invoice date.
        ...(form.currency === 'VND' ? { amount_vnd: form.amount } : { amount_cad: form.amount }),
        method: form.method,
        reference: form.reference || undefined,
        // A plain date (RC-20): the server stores that day as written, with no zone shift.
        received_at: form.received_at || undefined,
      }),
    onSuccess: () => {
      setForm((current) => ({ ...current, amount: '', reference: '' }));
      onDone();
    },
  });
  return (
    <form
      className="ws-form"
      onSubmit={(event) => {
        event.preventDefault();
        record.mutate();
      }}
    >
      {record.error && <Banner tone="danger">{record.error.message}</Banner>}
      <div className="ws-grid">
        <Field label={t('finance.currency')}>
          {(props) => (
            <Select
              {...props}
              value={form.currency}
              onChange={set('currency')}
              options={[
                { value: 'CAD', label: 'CAD' },
                { value: 'VND', label: 'VND' },
              ]}
            />
          )}
        </Field>
        <Field
          label={form.currency === 'VND' ? t('finance.amountVnd') : t('finance.amountCad')}
          hint={`${t('finance.balance')}: ${formatCad(invoice.balance_cad)}`}
          required
        >
          {(props) => (
            <TextInput {...props} required inputMode="decimal" value={form.amount} onChange={set('amount')} />
          )}
        </Field>
        <Field label={t('finance.method')}>
          {(props) => (
            <Select
              {...props}
              value={form.method}
              onChange={set('method')}
              options={METHODS.map((value) => ({ value, label: t(`finance.methods.${value}`) }))}
            />
          )}
        </Field>
        <Field label={t('finance.receivedOn')}>
          {(props) => <TextInput {...props} type="date" value={form.received_at} onChange={set('received_at')} />}
        </Field>
        <Field label={t('finance.reference')}>
          {(props) => <TextInput {...props} value={form.reference} onChange={set('reference')} />}
        </Field>
      </div>
      <p className="meta">{t('finance.paymentNote')}</p>
      <Button type="submit" variant="primary" loading={record.isPending}>
        {t('finance.recordPayment')}
      </Button>
    </form>
  );
}

function RefundForm({ payment, remaining, onDone, onCancel }) {
  const t = useT();
  // What is left to refund on this payment, not its original amount.
  const [amount, setAmount] = useState(String(remaining));
  const [reason, setReason] = useState('');
  const refund = useMutation({
    mutationFn: () => financeApi.refund(payment.id, { amount_cad: amount, reason }),
    onSuccess: onDone,
  });
  return (
    <form
      className="ws-form"
      onSubmit={(event) => {
        event.preventDefault();
        refund.mutate();
      }}
    >
      {refund.error && <Banner tone="danger">{refund.error.message}</Banner>}
      <div className="ws-grid">
        <Field label={t('finance.refundAmount')} required>
          {(props) => (
            <TextInput {...props} required inputMode="decimal" value={amount} onChange={(e) => setAmount(e.target.value)} />
          )}
        </Field>
        <Field label={t('finance.refundReason')} required>
          {(props) => <TextInput {...props} required value={reason} onChange={(e) => setReason(e.target.value)} />}
        </Field>
      </div>
      <div className="row-wrap">
        <Button type="submit" variant="danger" loading={refund.isPending}>
          {t('finance.refund')}
        </Button>
        <Button onClick={onCancel}>{t('common.cancel')}</Button>
      </div>
    </form>
  );
}

function VoidForm({ invoice, onDone, onCancel }) {
  const t = useT();
  const [reason, setReason] = useState('');
  const voidIt = useMutation({ mutationFn: () => financeApi.voidInvoice(invoice.id, reason), onSuccess: onDone });
  return (
    <form
      className="ws-form"
      onSubmit={(event) => {
        event.preventDefault();
        voidIt.mutate();
      }}
    >
      {voidIt.error && <Banner tone="danger">{voidIt.error.message}</Banner>}
      <Field label={t('finance.voidReason')} required>
        {(props) => <TextInput {...props} required value={reason} onChange={(e) => setReason(e.target.value)} />}
      </Field>
      <div className="row-wrap">
        <Button type="submit" variant="danger" loading={voidIt.isPending}>
          {t('finance.voidInvoice')}
        </Button>
        <Button onClick={onCancel}>{t('common.cancel')}</Button>
      </div>
    </form>
  );
}

/** The lines of an invoice issued with the Solaris Invoicing layout, as printed (DEC-0235). */
export function InvoicingLines({ invoice }) {
  const t = useT();
  return (
    <div data-testid="invoice-invoicing-lines">
      <div className="table-wrap" tabIndex={0} role="region" aria-label={t('finance.linesTitle')}>
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
            {invoice.lines.map((line) => (
              <tr key={line.sequence}>
                <td>{line.description}</td>
                <td>{line.quantity === null ? '1' : `${Number(line.quantity)} ${line.unit || ''}`.trim()}</td>
                <td>{line.unit_price_cad === null ? '—' : Number(line.unit_price_cad).toFixed(4)}</td>
                <td>{formatCad(line.amount_cad)}</td>
                <td>{line.tax_code || '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <dl className="fin-buckets" data-testid="invoice-invoicing-summary">
        <div>
          <dt>{t('finance.subtotal')}</dt>
          <dd>{formatCad(invoice.subtotal_cad)}</dd>
        </div>
        {(invoice.tax_rows || []).map((row) => (
          <div key={row.label}>
            <dt>{row.label}</dt>
            <dd>{formatCad(row.tax_cad)}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

export function InvoicePage() {
  const t = useT();
  const { can } = useSession();
  const { invoiceId } = useParams();
  const queryClient = useQueryClient();
  const [refunding, setRefunding] = useState(null);
  const [voiding, setVoiding] = useState(false);
  // Owner decision 9a: the issued invoice as a PDF (no watermark), drawn by the server.
  const pdf = useMutation({
    mutationFn: () => invoiceDraftsApi.downloadInvoicePdf(invoiceId),
    onSuccess: saveBlob,
  });
  const query = useQuery({ queryKey: ['finance', 'invoice', invoiceId], queryFn: () => financeApi.invoice(invoiceId) });
  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: ['finance'] });
    queryClient.invalidateQueries({ queryKey: ['workspace'] });
  };

  if (query.isLoading) return <SkeletonCards count={2} />;
  if (query.error) {
    return (
      <Card>
        <ErrorState error={query.error} onRetry={query.refetch} />
      </Card>
    );
  }
  const invoice = query.data;
  const open = invoice.status !== 'void';
  const refundedOf = (paymentId) =>
    invoice.payments
      .filter((p) => p.kind === 'refund' && p.refund_of_payment_id === paymentId)
      .reduce((total, p) => total + Number(p.amount_cad), 0);

  return (
    <>
      <PageHeader
        breadcrumb={<Link to="/finance">{t('finance.title')}</Link>}
        title={`${invoice.public_id} · ${invoice.customer_name || ''}`}
        subtitle={`${t('finance.shipment')} ${invoice.shipment_reference} · ${t('finance.period')} ${invoice.period_month}${
          invoice.is_adjustment ? ` (${t('finance.adjustment')})` : ''
        }`}
        actions={
          <>
            <StatusBadge tone={INVOICE_TONE[invoice.status]} label={t(`finance.invoiceStatus.${invoice.status}`)} />
            <Link className="btn btn--secondary btn--compact" to={`/finance/invoices/${invoice.id}/print`}>
              {t('finance.printInvoice')}
            </Link>
            <Button compact loading={pdf.isPending} onClick={() => pdf.mutate()}>
              {t('invoiceDraft.downloadInvoice')}
            </Button>
          </>
        }
      />
      {pdf.error && <Banner tone="danger">{pdf.error.message}</Banner>}
      {invoice.tax_status === 'review_pending' && (
        <Banner tone="warning">{t('finance.taxPendingNote')}</Banner>
      )}
      <Card title={t('finance.linesTitle')}>
        {invoice.tax_layout ? (
          <InvoicingLines invoice={invoice} />
        ) : (
<div className="table-wrap" tabIndex={0} role="region" aria-label={t('finance.linesTitle')}>
          <table className="table">
            <thead>
              <tr>
                <th scope="col">{t('finance.description')}</th>
                <th scope="col">{t('finance.quantity')}</th>
                <th scope="col">{t('finance.amount')}</th>
              </tr>
            </thead>
            <tbody>
              {invoice.lines.map((line) => (
                <tr key={line.sequence}>
                  <td>{line.description}</td>
                  <td>{line.quantity === null ? '—' : `${Number(line.quantity)} ${line.unit || ''}`}</td>
                  <td>{formatCad(line.amount_cad)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        )}
        <dl className="fin-buckets">
          <div>
            <dt>{t('finance.total')}</dt>
            <dd>
              <strong>{formatCad(invoice.total_cad)}</strong>
            </dd>
          </div>
          <div>
            <dt>{t('finance.tax')}</dt>
            <dd>{formatCad(invoice.tax_cad)}</dd>
          </div>
          <div>
            <dt>{t('finance.paid')}</dt>
            <dd>{formatCad(invoice.paid_cad)}</dd>
          </div>
          <div>
            <dt>{t('finance.balance')}</dt>
            <dd>{formatCad(invoice.balance_cad)}</dd>
          </div>
          <div>
            <dt>{t('finance.due')}</dt>
            <dd>{formatDate(invoice.due_at)}</dd>
          </div>
        </dl>
        {invoice.void_reason && (
          <p className="meta">
            {t('finance.voided')}: {invoice.void_reason}
          </p>
        )}
      </Card>

      <Card title={t('finance.paymentsTitle')}>
        {invoice.payments.length === 0 ? (
          <p className="meta">{t('finance.noPayments')}</p>
        ) : (
<div className="table-wrap" tabIndex={0} role="region" aria-label={t('finance.paymentsTitle')}>
            <table className="table">
              <thead>
                <tr>
                  <th scope="col">{t('finance.receipt')}</th>
                  <th scope="col">{t('finance.date')}</th>
                  <th scope="col">{t('finance.method')}</th>
                  <th scope="col">{t('finance.amount')}</th>
                  <th scope="col">
                    <span className="visually-hidden">{t('finance.actions')}</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {invoice.payments.map((payment) => (
                  <tr key={payment.id}>
                    <td className="mono">
                      {payment.kind === 'refund' ? t('finance.refundLabel') : payment.receipt_public_id}
                    </td>
                    <td>{formatReceivedDate(payment.received_at)}</td>
                    <td>{t(`finance.methods.${payment.method}`, payment.method)}</td>
                    <td>
                      {payment.kind === 'refund' ? '−' : ''}
                      {formatCad(payment.amount_cad)}
                      {payment.note && payment.kind === 'refund' && <span className="meta"> · {payment.note}</span>}
                    </td>
                    <td className="row-wrap">
                      {payment.kind === 'payment' && (
                        <Link
                          className="btn btn--tertiary btn--compact"
                          to={`/finance/receipts/${payment.id}/print`}
                          aria-label={`${t('finance.printReceipt')} ${payment.receipt_public_id}`}
                        >
                          {t('finance.printReceipt')}
                        </Link>
                      )}
                      {payment.kind === 'payment' &&
                        can(P.FINANCIAL_ADJUST) &&
                        refundedOf(payment.id) < Number(payment.amount_cad) && (
                          <Button
                            compact
                            variant="tertiary"
                            onClick={() => setRefunding(payment)}
                            aria-label={`${t('finance.refund')} ${payment.receipt_public_id}`}
                          >
                            {t('finance.refund')}
                          </Button>
                        )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {refunding && (
          <RefundForm
            payment={refunding}
            remaining={Number(refunding.amount_cad) - refundedOf(refunding.id)}
            onCancel={() => setRefunding(null)}
            onDone={() => {
              setRefunding(null);
              refresh();
            }}
          />
        )}
        {open && Number(invoice.balance_cad) > 0 && can(P.FINANCIAL_WRITE) && (
          <PaymentForm invoice={invoice} onDone={refresh} />
        )}
      </Card>

      {open && can(P.FINANCIAL_ADJUST) && (
        <Card title={t('finance.voidTitle')}>
          <p className="meta">{t('finance.voidNote')}</p>
          {voiding ? (
            <VoidForm
              invoice={invoice}
              onCancel={() => setVoiding(false)}
              onDone={() => {
                setVoiding(false);
                refresh();
              }}
            />
          ) : (
            <Button variant="danger" onClick={() => setVoiding(true)}>
              {t('finance.voidInvoice')}
            </Button>
          )}
        </Card>
      )}
    </>
  );
}
