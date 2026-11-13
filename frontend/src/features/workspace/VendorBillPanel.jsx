/**
 * The vendor's actual bill for a booked master (Phase 13E): entered beside the expected
 * cost, approved with a reason when they differ, then split onto the customers and marked
 * paid. Internal: vendor cost.
 *
 * "Start from the estimate" fills the lines with what the engine expects, so staff correct
 * only what the vendor actually billed differently. A VND bill is converted at the cash-
 * buying rate frozen on the bill; a CAD bill is taken as CAD.
 */

import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { financeApi } from '../../api/endpoints.js';
import { P, useOptionalSession } from '../../app/SessionContext.jsx';
import { useT } from '../../i18n/index.jsx';
import { Banner, Button, Field, Select, StatusBadge, TextInput } from '../../components/ui/index.jsx';
import { CollapsibleCard } from './CollapsibleCard.jsx';
import { ErrorState } from '../../components/state/index.jsx';
import { formatCad, formatVnd, wsKey } from './workspaceFormat.js';

const KINDS = ['base', 'piece_fee', 'surcharge', 'other'];
const BLANK = { kind: 'base', fee_key: '', description: '', amount: '' };
const STATUS_TONE = { entered: 'warning', approved: 'info', paid: 'success', void: 'neutral' };

function linesFromEstimate(estimate) {
  if (!estimate) return [{ ...BLANK }];
  const lines = [];
  if (estimate.base_freight_vnd) {
    lines.push({ kind: 'base', fee_key: '', description: '', amount: String(Number(estimate.base_freight_vnd)) });
  }
  if (Number(estimate.piece_fee_vnd) > 0) {
    lines.push({ kind: 'piece_fee', fee_key: '', description: '', amount: String(Number(estimate.piece_fee_vnd)) });
  }
  for (const fee of estimate.fees) {
    if (fee.vendor_fee_vnd && Number(fee.vendor_fee_vnd) > 0) {
      lines.push({ kind: 'surcharge', fee_key: fee.key, description: fee.name, amount: String(Number(fee.vendor_fee_vnd)) });
    }
  }
  return lines.length ? lines : [{ ...BLANK }];
}

function EnterBill({ master, estimate, onDone, onCancel }) {
  const t = useT();
  const [currency, setCurrency] = useState('VND');
  const [billNumber, setBillNumber] = useState('');
  const [lines, setLines] = useState(() => linesFromEstimate(estimate));
  const setLine = (index, field) => (event) =>
    setLines((current) => current.map((line, i) => (i === index ? { ...line, [field]: event.target.value } : line)));
  const fees = estimate?.fees ?? [];
  const enter = useMutation({
    mutationFn: () =>
      financeApi.enterVendorInvoice(master.id, {
        currency,
        vendor_bill_number: billNumber || undefined,
        lines: lines
          .filter((line) => line.amount !== '')
          .map((line) => ({
            kind: line.kind,
            fee_key: line.kind === 'surcharge' && line.fee_key ? line.fee_key : undefined,
            description: line.description || undefined,
            amount: line.amount,
          })),
      }),
    onSuccess: onDone,
  });
  return (
    <form
      className="ws-form"
      onSubmit={(event) => {
        event.preventDefault();
        enter.mutate();
      }}
    >
      {enter.error && <Banner tone="danger">{enter.error.message}</Banner>}
      <div className="ws-grid">
        <Field label={t('finance.currency')}>
          {(props) => (
            <Select
              {...props}
              value={currency}
              onChange={(event) => setCurrency(event.target.value)}
              options={[
                { value: 'VND', label: 'VND' },
                { value: 'CAD', label: 'CAD' },
              ]}
            />
          )}
        </Field>
        <Field label={t('finance.vendorBillNumber')}>
          {(props) => <TextInput {...props} value={billNumber} onChange={(event) => setBillNumber(event.target.value)} />}
        </Field>
      </div>
<div className="table-wrap" tabIndex={0} role="region" aria-label={t('finance.vendorBillTitle')}>
        <table className="table">
          <thead>
            <tr>
              <th scope="col">{t('finance.lineKind')}</th>
              <th scope="col">{t('finance.surchargeOnEstimate')}</th>
              <th scope="col">{t('finance.description')}</th>
              <th scope="col">{t('finance.amount')}</th>
              <th scope="col">
                <span className="visually-hidden">{t('finance.actions')}</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {lines.map((line, index) => (
              <tr key={index}>
                <td>
                  <Select
                    aria-label={`${t('finance.lineKind')} ${index + 1}`}
                    value={line.kind}
                    onChange={setLine(index, 'kind')}
                    options={KINDS.map((value) => ({ value, label: t(`finance.kind.${value}`) }))}
                  />
                </td>
                <td>
                  {line.kind === 'surcharge' ? (
                    <Select
                      aria-label={`${t('finance.surchargeOnEstimate')} ${index + 1}`}
                      value={line.fee_key}
                      placeholder={t('finance.notOnEstimate')}
                      onChange={setLine(index, 'fee_key')}
                      options={fees.map((fee) => ({ value: fee.key, label: fee.name }))}
                    />
                  ) : (
                    '—'
                  )}
                </td>
                <td>
                  <TextInput
                    aria-label={`${t('finance.description')} ${index + 1}`}
                    value={line.description}
                    onChange={setLine(index, 'description')}
                  />
                </td>
                <td>
                  <TextInput
                    aria-label={`${t('finance.amount')} ${index + 1}`}
                    inputMode="decimal"
                    value={line.amount}
                    onChange={setLine(index, 'amount')}
                  />
                </td>
                <td>
                  <Button
                    compact
                    variant="tertiary"
                    aria-label={`${t('finance.removeLine')} ${index + 1}`}
                    onClick={() => setLines((current) => current.filter((_, i) => i !== index))}
                  >
                    {t('finance.removeLine')}
                  </Button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="row-wrap">
        <Button onClick={() => setLines((current) => [...current, { ...BLANK }])}>{t('finance.addLine')}</Button>
        <Button type="submit" variant="primary" loading={enter.isPending}>
          {t('finance.enterBill')}
        </Button>
        <Button onClick={onCancel}>{t('common.cancel')}</Button>
      </div>
    </form>
  );
}

function BillActions({ bill, refresh }) {
  const t = useT();
  const session = useOptionalSession();
  const [reason, setReason] = useState('');
  const [reference, setReference] = useState('');
  const [voidReason, setVoidReason] = useState('');
  const approve = useMutation({
    mutationFn: () => financeApi.approveVendorInvoice(bill.id, { variance_reason: reason || undefined }),
    onSuccess: refresh,
  });
  const paid = useMutation({
    mutationFn: () => financeApi.vendorInvoicePaid(bill.id, { reference: reference || undefined }),
    onSuccess: refresh,
  });
  const voidIt = useMutation({ mutationFn: () => financeApi.voidVendorInvoice(bill.id, voidReason), onSuccess: refresh });
  const error = approve.error || paid.error || voidIt.error;
  const canWrite = Boolean(session?.can(P.FINANCIAL_WRITE));
  const canAdjust = Boolean(session?.can(P.FINANCIAL_ADJUST));
  return (
    <>
      {error && <Banner tone="danger">{error.message}</Banner>}
      {bill.status === 'entered' && canWrite && (
        <form
          className="ws-form"
          onSubmit={(event) => {
            event.preventDefault();
            approve.mutate();
          }}
        >
          <Field label={t('finance.varianceReason')} hint={t('finance.varianceReasonHint')}>
            {(props) => <TextInput {...props} value={reason} onChange={(event) => setReason(event.target.value)} />}
          </Field>
          <Button type="submit" variant="primary" loading={approve.isPending}>
            {t('finance.approveBill')}
          </Button>
        </form>
      )}
      {bill.status === 'approved' && canWrite && (
        <form
          className="ws-form"
          onSubmit={(event) => {
            event.preventDefault();
            paid.mutate();
          }}
        >
          <Field label={t('finance.paymentReference')}>
            {(props) => <TextInput {...props} value={reference} onChange={(event) => setReference(event.target.value)} />}
          </Field>
          <Button type="submit" loading={paid.isPending}>
            {t('finance.markPaid')}
          </Button>
        </form>
      )}
      {(bill.status === 'entered' || bill.status === 'approved') && canAdjust && (
        <form
          className="ws-form"
          onSubmit={(event) => {
            event.preventDefault();
            voidIt.mutate();
          }}
        >
          <Field label={t('finance.voidReason')}>
            {(props) => (
              <TextInput {...props} required value={voidReason} onChange={(event) => setVoidReason(event.target.value)} />
            )}
          </Field>
          <Button type="submit" variant="danger" compact loading={voidIt.isPending}>
            {t('finance.voidBill')}
          </Button>
        </form>
      )}
    </>
  );
}

export function VendorBillPanel({ master, estimate, collapsible = false, defaultOpen = true }) {
  const t = useT();
  const session = useOptionalSession();
  const queryClient = useQueryClient();
  const [entering, setEntering] = useState(false);
  const enabled = master.state === 'booked' || master.state === 'completed';
  const query = useQuery({
    queryKey: wsKey(master.id, 'vendor-bills'),
    queryFn: () => financeApi.vendorInvoices(master.id),
    enabled: enabled && Boolean(session?.can(P.FINANCIAL_READ)),
  });
  if (!enabled || !session?.can(P.FINANCIAL_READ)) return null;
  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: wsKey(master.id) });
    queryClient.invalidateQueries({ queryKey: ['finance'] });
  };
  const bills = query.data ?? [];
  const live = bills.find((bill) => bill.status !== 'void');
  const nameOf = Object.fromEntries(master.members.map((m) => [String(m.shipment_id), m.customer_name || m.public_id]));

  return (
    <CollapsibleCard
      collapsible={collapsible}
      defaultOpen={defaultOpen}
      summary={live ? t(`finance.vendorStatus.${live.status}`, live.status) : t('wsFlow.noBillYet')}
      title={t('finance.vendorBillTitle')}
      actions={
        !live &&
        !entering &&
        session.can(P.FINANCIAL_WRITE) && (
          <Button compact onClick={() => setEntering(true)}>
            {t('finance.startFromEstimate')}
          </Button>
        )
      }
    >
      <p className="meta">{t('finance.vendorBillNote')}</p>
      {query.error && <ErrorState error={query.error} onRetry={query.refetch} />}
      {entering && (
        <EnterBill
          master={master}
          estimate={estimate}
          onCancel={() => setEntering(false)}
          onDone={() => {
            setEntering(false);
            refresh();
          }}
        />
      )}
      {bills.map((bill) => (
        <section key={bill.id} className="fin-bill" aria-label={bill.public_id}>
          <p>
            <strong className="mono">{bill.public_id}</strong>{' '}
            <StatusBadge tone={STATUS_TONE[bill.status]} label={t(`finance.vendorStatus.${bill.status}`, bill.status)} />{' '}
            {bill.vendor_bill_number && <span className="meta">{bill.vendor_bill_number}</span>}
            {bill.is_adjustment && <span className="meta"> · {t('finance.adjustment')} ({bill.period_month})</span>}
          </p>
          <dl className="fin-buckets">
            <div>
              <dt>{t('finance.billed')}</dt>
              <dd>
                {bill.currency === 'VND' ? formatVnd(bill.total_amount) : formatCad(bill.total_amount)}
                {bill.currency === 'VND' && <span className="meta"> = {formatCad(bill.total_cad)}</span>}
              </dd>
            </div>
            <div>
              <dt>{t('finance.expected')}</dt>
              <dd>{formatCad(bill.expected_cad)}</dd>
            </div>
            <div>
              <dt>{t('finance.variance')}</dt>
              <dd>
                <strong>{formatCad(bill.variance_cad)}</strong>
              </dd>
            </div>
          </dl>
          {bill.variance_reason && (
            <p className="meta">
              {t('finance.varianceReason')}: {bill.variance_reason}
            </p>
          )}
          {Object.keys(bill.allocations).length > 0 && (
            <ul className="ws-split" aria-label={t('finance.actualByCustomer')}>
              {Object.entries(bill.allocations).map(([shipmentId, amount]) => (
                <li key={shipmentId}>
                  <span>{nameOf[shipmentId] || shipmentId}</span>
                  <span>{formatCad(amount)}</span>
                </li>
              ))}
            </ul>
          )}
          <BillActions bill={bill} refresh={refresh} />
        </section>
      ))}
    </CollapsibleCard>
  );
}
