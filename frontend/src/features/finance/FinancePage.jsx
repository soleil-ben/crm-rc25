/**
 * Finance (Phase 13E): invoices, receivables, payables, profitability and month close.
 *
 * Revenue tabs (invoices, receivables, periods) need `financial:read`. Payables and
 * profitability carry vendor cost and appear only with `tariff:read`. Every figure is the
 * server's; this page formats and never computes money. Profitability is an internal
 * management convention by hand-in month, not an accounting statement.
 */

import { useEffect, useRef, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { financeApi } from '../../api/endpoints.js';
import { downloadUrl } from '../../api/client.js';
import { P, useSession } from '../../app/SessionContext.jsx';
import { useT } from '../../i18n/index.jsx';
import { PageHeader } from '../../components/layout/AppShell.jsx';
import {
  Banner,
  Button,
  Card,
  Field,
  Pagination,
  Select,
  StatusBadge,
  Tabs,
  TabPanel,
  TextInput,
} from '../../components/ui/index.jsx';
import { EmptyState, ErrorState, SkeletonRows } from '../../components/state/index.jsx';
import { formatDate, interpolate } from '../../utils/format.js';
import { formatCad, formatKg } from '../workspace/workspaceFormat.js';
import { taxRateOf } from './PrintPages.jsx';
import './finance.css';

export const INVOICE_TONE = { issued: 'warning', partially_paid: 'info', paid: 'success', void: 'neutral' };
const PERIOD_TONE = { open: 'success', locked: 'warning', closed: 'neutral', reopened: 'info' };
const PAGE_SIZE = 50;

function thisMonth() {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`;
}

/**
 * Phase 15: quotes the customer accepted whose shipment has no invoice yet. Read-only; each
 * row leads to the master in the workspace, where the existing Issue invoice button is.
 * Nothing is invoiced automatically (stand-in: acceptance records only). Shown only when
 * something waits.
 */
export function AcceptedNotInvoiced() {
  const t = useT();
  const query = useQuery({
    queryKey: ['finance', 'accepted-not-invoiced'],
    queryFn: financeApi.acceptedNotInvoiced,
    retry: false,
  });
  const rows = query.data?.items ?? [];
  if (query.isLoading || query.error || rows.length === 0) return null;
  return (
    <Card title={t('finance.acceptedTitle')}>
      <p className="meta">{t('finance.acceptedIntro')}</p>
      <ul className="fin-accepted">
        {rows.map((row) => {
          const prompt = interpolate(t('finance.acceptedPrompt'), { version: row.version ?? '' });
          return (
            <li key={row.offer_id} className="fin-accepted__row">
              <span>
                <strong>{prompt}</strong>
                {' · '}
                <span className="mono">{row.shipment_reference}</span>
                {row.customer_name ? ` · ${row.customer_name}` : ''}
                {' · '}
                {formatCad(row.total_cad)}
                {' · '}
                {interpolate(t('finance.acceptedOn'), { date: formatDate(row.accepted_at) })}
                {row.superseded_by_version ? (
                  <>
                    {' · '}
                    {interpolate(t('finance.acceptedSuperseded'), {
                      version: row.superseded_by_version,
                    })}
                  </>
                ) : null}
              </span>
              {row.invoice_draft_id ? (
                <Link
                  className="btn btn--primary btn--compact"
                  to={`/finance/invoice-drafts/${row.invoice_draft_id}`}
                  aria-label={`${t('invoiceDraft.open')} — ${row.shipment_reference}`}
                >
                  {t('invoiceDraft.open')}
                </Link>
              ) : null}
              {row.consolidation_id ? (
                <Link
                  className="btn btn--secondary btn--compact"
                  to={`/workspace/${row.consolidation_id}`}
                  aria-label={`${t('finance.acceptedAction')} — ${row.shipment_reference}`}
                >
                  {t('finance.acceptedAction')}
                </Link>
              ) : null}
            </li>
          );
        })}
      </ul>
    </Card>
  );
}

function InvoicesTab() {
  const t = useT();
  const [status, setStatus] = useState('');
  const [offset, setOffset] = useState(0);
  const query = useQuery({
    queryKey: ['finance', 'invoices', status, offset],
    queryFn: () => financeApi.invoices({ status: status || undefined, limit: PAGE_SIZE, offset }),
  });
  const rows = query.data?.items ?? [];
  return (
    <>
    <AcceptedNotInvoiced />
    <Card flush>
      <div className="fin-toolbar">
        <Field label={t('finance.status')}>
          {(props) => (
            <Select
              {...props}
              value={status}
              placeholder={t('finance.allStatuses')}
              onChange={(event) => {
                setStatus(event.target.value);
                setOffset(0);
              }}
              options={['issued', 'partially_paid', 'paid', 'void'].map((value) => ({
                value,
                label: t(`finance.invoiceStatus.${value}`),
              }))}
            />
          )}
        </Field>
      </div>
      {query.isLoading ? (
        <SkeletonRows rows={4} />
      ) : query.error ? (
        <ErrorState error={query.error} onRetry={query.refetch} />
      ) : rows.length === 0 ? (
        <EmptyState title={t('finance.noInvoicesTitle')} body={t('finance.noInvoicesBody')} />
      ) : (
<div className="table-wrap" tabIndex={0} role="region" aria-label={t('finance.tabInvoices')}>
          <table className="table">
            <thead>
              <tr>
                <th scope="col">{t('finance.invoice')}</th>
                <th scope="col">{t('finance.customer')}</th>
                <th scope="col">{t('finance.shipment')}</th>
                <th scope="col">{t('finance.issued')}</th>
                <th scope="col">{t('finance.total')}</th>
                <th scope="col">{t('finance.balance')}</th>
                <th scope="col">{t('finance.status')}</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.id}>
                  <td>
                    <Link className="mono" to={`/finance/invoices/${row.id}`}>
                      {row.public_id}
                    </Link>
                  </td>
                  <td>{row.customer_name}</td>
                  <td className="mono">{row.shipment_reference}</td>
                  <td>{formatDate(row.issued_at)}</td>
                  <td>{formatCad(row.total_cad)}</td>
                  <td>{formatCad(row.balance_cad)}</td>
                  <td>
                    <StatusBadge
                      tone={INVOICE_TONE[row.status]}
                      label={t(`finance.invoiceStatus.${row.status}`, row.status)}
                    />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <Pagination total={query.data?.total ?? 0} limit={PAGE_SIZE} offset={offset} onChange={setOffset} />
    </Card>
    </>
  );
}

function ReceivablesTab() {
  const t = useT();
  const { can } = useSession();
  const query = useQuery({ queryKey: ['finance', 'ar'], queryFn: financeApi.arAging });
  const report = query.data?.report;
  if (query.isLoading) return <SkeletonRows rows={4} />;
  if (query.error) return <ErrorState error={query.error} onRetry={query.refetch} />;
  const buckets = ['current', '1_30', '31_60', '61_90', 'over_90'];
  return (
    <Card
      title={t('finance.receivablesTitle')}
      actions={
        can(P.EXPORT_REPORTS) && (
          <a className="btn btn--secondary btn--compact" href={downloadUrl('/finance/ar-aging.csv')}>
            {t('finance.exportCsv')}
          </a>
        )
      }
    >
      <dl className="fin-buckets">
        {buckets.map((bucket) => (
          <div key={bucket}>
            <dt>{t(`finance.bucket.${bucket}`)}</dt>
            <dd>{formatCad(report.totals[bucket])}</dd>
          </div>
        ))}
        <div>
          <dt>{t('finance.totalOutstanding')}</dt>
          <dd>
            <strong>{formatCad(report.total_cad)}</strong>
          </dd>
        </div>
      </dl>
      {report.rows.length === 0 ? (
        <p className="meta">{t('finance.nothingOutstanding')}</p>
      ) : (
<div className="table-wrap" tabIndex={0} role="region" aria-label={t('finance.receivablesTitle')}>
          <table className="table">
            <thead>
              <tr>
                <th scope="col">{t('finance.invoice')}</th>
                <th scope="col">{t('finance.customer')}</th>
                <th scope="col">{t('finance.due')}</th>
                <th scope="col">{t('finance.daysOverdue')}</th>
                <th scope="col">{t('finance.balance')}</th>
              </tr>
            </thead>
            <tbody>
              {report.rows.map((row) => (
                <tr key={row.invoice_id}>
                  <td>
                    <Link className="mono" to={`/finance/invoices/${row.invoice_id}`}>
                      {row.invoice_number}
                    </Link>
                  </td>
                  <td>{row.customer_name}</td>
                  <td>{formatDate(row.due_at)}</td>
                  <td>{row.days_overdue}</td>
                  <td>{formatCad(row.balance_cad)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}

function PayablesTab() {
  const t = useT();
  const query = useQuery({ queryKey: ['finance', 'ap'], queryFn: financeApi.ap });
  if (query.isLoading) return <SkeletonRows rows={3} />;
  if (query.error) return <ErrorState error={query.error} onRetry={query.refetch} />;
  const report = query.data.report;
  return (
    <Card title={t('finance.payablesTitle')}>
      <p className="meta">{t('finance.internalOnly')}</p>
      {report.rows.length === 0 ? (
        <p className="meta">{t('finance.nothingPayable')}</p>
      ) : (
<div className="table-wrap" tabIndex={0} role="region" aria-label={t('finance.payablesTitle')}>
          <table className="table">
            <thead>
              <tr>
                <th scope="col">{t('finance.vendorBill')}</th>
                <th scope="col">{t('finance.master')}</th>
                <th scope="col">{t('finance.vendorBillNumber')}</th>
                <th scope="col">{t('finance.status')}</th>
                <th scope="col">{t('finance.total')}</th>
              </tr>
            </thead>
            <tbody>
              {report.rows.map((row) => (
                <tr key={row.vendor_invoice_id}>
                  <td className="mono">{row.public_id}</td>
                  <td>
                    <Link className="mono" to={`/workspace/${row.consolidation_id}`}>
                      {row.consolidation_reference}
                    </Link>
                  </td>
                  <td>{row.vendor_bill_number || '—'}</td>
                  <td>{t(`finance.vendorStatus.${row.status}`, row.status)}</td>
                  <td>{formatCad(row.total_cad)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <p>
        {t('finance.totalPayable')}: <strong>{formatCad(report.total_cad)}</strong>
      </p>
    </Card>
  );
}

function ProfitabilityTab() {
  const t = useT();
  const { can } = useSession();
  const [month, setMonth] = useState(thisMonth());
  const query = useQuery({
    queryKey: ['finance', 'profitability', month],
    queryFn: () => financeApi.profitability(month),
    enabled: /^\d{4}-\d{2}$/.test(month),
  });
  const report = query.data?.report;
  return (
    <Card
      title={t('finance.profitabilityTitle')}
      actions={
        can(P.EXPORT_REPORTS) && (
          <a
            className="btn btn--secondary btn--compact"
            href={downloadUrl('/finance/profitability.csv', { month })}
          >
            {t('finance.exportCsv')}
          </a>
        )
      }
    >
      <p className="meta">{t('finance.profitabilityNote')}</p>
      <div className="fin-toolbar">
        <Field label={t('finance.month')}>
          {(props) => (
            <TextInput {...props} type="month" value={month} onChange={(event) => setMonth(event.target.value)} />
          )}
        </Field>
      </div>
      {query.isLoading ? (
        <SkeletonRows rows={3} />
      ) : query.error ? (
        <ErrorState error={query.error} onRetry={query.refetch} />
      ) : report ? (
        <>
          <p>
            <StatusBadge
              tone={PERIOD_TONE[report.state]}
              label={t(`finance.periodState.${report.state}`, report.state)}
            />{' '}
            {report.from_snapshot && <span className="meta">{t('finance.fromSnapshot')}</span>}
          </p>
          <dl className="fin-buckets">
            <div>
              <dt>{t('finance.revenue')}</dt>
              <dd>{formatCad(report.summary.revenue_cad)}</dd>
            </div>
            <div>
              <dt>{t('finance.costUsed')}</dt>
              <dd>{formatCad(report.summary.matched_cost_cad)}</dd>
            </div>
            <div>
              <dt>{t('finance.unmatchedCost')}</dt>
              <dd>{formatCad(report.summary.unmatched_cost_cad)}</dd>
            </div>
            <div>
              <dt>{t('finance.profit')}</dt>
              <dd>
                <strong>{formatCad(report.summary.profit_cad)}</strong>
              </dd>
            </div>
            <div>
              <dt>{t('finance.margin')}</dt>
              <dd>{report.summary.margin_percent === null ? '—' : `${report.summary.margin_percent}%`}</dd>
            </div>
            <div>
              <dt>{t('finance.billableWeight')}</dt>
              <dd>{formatKg(report.summary.billable_kg)}</dd>
            </div>
            <div>
              <dt>{t('finance.profitPerKg')}</dt>
              <dd>{formatCad(report.summary.profit_per_kg_cad)}</dd>
            </div>
          </dl>
          {report.masters.length === 0 ? (
            <p className="meta">{t('finance.noActivity')}</p>
          ) : (
<div className="table-wrap" tabIndex={0} role="region" aria-label={t('finance.profitabilityTitle')}>
              <table className="table">
                <thead>
                  <tr>
                    <th scope="col">{t('finance.master')}</th>
                    <th scope="col">{t('finance.service')}</th>
                    <th scope="col">{t('finance.shipments')}</th>
                    <th scope="col">{t('finance.revenue')}</th>
                    <th scope="col">{t('finance.estimatedCost')}</th>
                    <th scope="col">{t('finance.actualCost')}</th>
                    <th scope="col">{t('finance.unmatchedCost')}</th>
                    <th scope="col">{t('finance.profit')}</th>
                    <th scope="col">{t('finance.margin')}</th>
                  </tr>
                </thead>
                <tbody>
                  {report.masters.map((row) => (
                    <tr key={row.consolidation_id ?? 'none'}>
                      <td className="mono">
                        {row.consolidation_reference || '—'}
                        {row.adjustments > 0 && <span className="meta"> · {t('finance.adjustment')}</span>}
                      </td>
                      <td>
                        {row.service ? t(`finance.serviceName.${row.service}`, row.service) : '—'} {row.origin}
                      </td>
                      <td>{row.shipments}</td>
                      <td>{formatCad(row.revenue_cad)}</td>
                      <td>{formatCad(row.estimated_cost_cad)}</td>
                      <td>{formatCad(row.actual_cost_cad)}</td>
                      <td>{formatCad(row.unmatched_cost_cad)}</td>
                      <td>
                        {formatCad(row.profit_cad)}{' '}
                        <span className="meta">({t(`finance.costBasis.${row.cost_basis}`)})</span>
                      </td>
                      <td>{row.margin_percent === null ? '—' : `${row.margin_percent}%`}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      ) : null}
    </Card>
  );
}

/**
 * Invoice terms (Phase 14): how many days after issue an invoice falls due. Shown to everyone
 * with `financial:read`; changed by Admin (`settings:manage`). It applies to invoices issued
 * from now on; an issued invoice keeps its due date. Tax is chosen per invoice (OD-64).
 */
export function FinanceSettingsCard() {
  const t = useT();
  const { can } = useSession();
  const queryClient = useQueryClient();
  const canEdit = can(P.SETTINGS_MANAGE);
  const query = useQuery({ queryKey: ['finance', 'settings'], queryFn: financeApi.settings });
  const [days, setDays] = useState('');
  const [error, setError] = useState(null);
  const [saved, setSaved] = useState(false);
  const savedRef = useRef(null);

  // The value as last loaded or saved: a refetch replaces the field only if the user has not
  // edited it (Phase 14 review).
  const baseline = useRef(null);
  useEffect(() => {
    if (!query.data) return;
    const fresh = String(query.data.invoice_due_days);
    const before = baseline.current;
    baseline.current = fresh;
    setDays((current) => (before === null || current === before ? fresh : current));
  }, [query.data]);
  useEffect(() => {
    if (saved) savedRef.current?.focus();
  }, [saved]);

  const save = useMutation({
    mutationFn: () => financeApi.updateSettings({ invoice_due_days: Number(days) }),
    onSuccess: (data) => {
      baseline.current = String(data.invoice_due_days);
      setDays(String(data.invoice_due_days));
      queryClient.setQueryData(['finance', 'settings'], data);
      setSaved(true);
    },
  });

  if (query.isLoading) return <SkeletonRows rows={1} />;
  if (query.error) return <ErrorState error={query.error} onRetry={query.refetch} />;
  const serverError =
    save.error && (save.error.field === 'invoice_due_days' || save.error.invalidFields?.includes('invoice_due_days'))
      ? t('financeSettings.dueDaysError')
      : null;
  return (
    <Card title={t('financeSettings.title')}>
      <p className="meta">{t('financeSettings.intro')}</p>
      {saved && (
        <div ref={savedRef} tabIndex={-1}>
          <Banner tone="info">{t('financeSettings.saved')}</Banner>
        </div>
      )}
      {save.error && !serverError && <Banner tone="danger">{save.error.message}</Banner>}
      <form
        noValidate
        onSubmit={(event) => {
          event.preventDefault();
          setSaved(false);
          const value = days.trim();
          if (!/^\d+$/.test(value) || Number(value) > 365) {
            setError(t('financeSettings.dueDaysError'));
            document.getElementById('finance-due-days')?.focus();
            return;
          }
          setError(null);
          save.mutate();
        }}
      >
        <Field
          id="finance-due-days"
          label={t('financeSettings.dueDays')} hint={t('financeSettings.dueDaysHint')} error={error || serverError}>
          {(props) => (
            <TextInput
              {...props}
              inputMode="numeric"
              size={5}
              readOnly={!canEdit}
              value={days}
              onChange={(event) => setDays(event.target.value)}
            />
          )}
        </Field>
        <p className="meta">
          {t('financeSettings.taxStatus')}:{' '}
          {taxRateOf(query.data.tax_status) === null
            ? t(`financeSettings.taxStates.${query.data.tax_status}`, t('financeSettings.taxStates.other'))
            : t('finance.taxLabel').replace('{rate}', String(taxRateOf(query.data.tax_status)))}
        </p>
        {canEdit && (
          <Button type="submit" variant="primary" compact loading={save.isPending}>
            {t('financeSettings.save')}
          </Button>
        )}
      </form>
    </Card>
  );
}

function PeriodsTab() {
  const t = useT();
  const { can } = useSession();
  const queryClient = useQueryClient();
  const [reopening, setReopening] = useState(null);
  // Closing freezes a month and only Admin or Operations (OD-69) can undo it, so it takes
  // a second click.
  const [confirming, setConfirming] = useState(null);
  const [reason, setReason] = useState('');
  const query = useQuery({ queryKey: ['finance', 'periods'], queryFn: financeApi.periods });
  const refresh = () => queryClient.invalidateQueries({ queryKey: ['finance'] });
  const close = useMutation({ mutationFn: (month) => financeApi.closePeriod(month), onSuccess: refresh });
  const reopen = useMutation({
    mutationFn: () => financeApi.reopenPeriod(reopening, reason),
    onSuccess: () => {
      setReopening(null);
      setReason('');
      refresh();
    },
  });
  if (query.isLoading) return <SkeletonRows rows={6} />;
  if (query.error) return <ErrorState error={query.error} onRetry={query.refetch} />;
  return (
    <Card title={t('finance.periodsTitle')}>
      <p className="meta">{t('finance.periodsNote')}</p>
      {(close.error || reopen.error) && (
        <Banner tone="danger">{(close.error || reopen.error).message}</Banner>
      )}
<div className="table-wrap" tabIndex={0} role="region" aria-label={t('finance.periodsTitle')}>
        <table className="table">
          <thead>
            <tr>
              <th scope="col">{t('finance.month')}</th>
              <th scope="col">{t('finance.status')}</th>
              <th scope="col">{t('finance.locksOn')}</th>
              <th scope="col">
                <span className="visually-hidden">{t('finance.actions')}</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {query.data.map((row) => (
              <tr key={row.month}>
                <td className="mono">{row.month}</td>
                <td>
                  <StatusBadge
                    tone={PERIOD_TONE[row.state]}
                    label={t(`finance.periodState.${row.state}`, row.state)}
                  />
                  {row.reopen_reason && <span className="meta"> · {row.reopen_reason}</span>}
                </td>
                <td>{formatDate(row.lock_date)}</td>
                <td>
                  {(row.state === 'locked' || row.state === 'reopened') &&
                    can(P.FINANCIAL_WRITE) &&
                    can(P.TARIFF_READ) && (
                      <Button
                        compact
                        variant={confirming === row.month ? 'danger' : 'secondary'}
                        loading={close.isPending && close.variables === row.month}
                        onClick={() => {
                          if (confirming === row.month) {
                            setConfirming(null);
                            close.mutate(row.month);
                          } else {
                            setConfirming(row.month);
                          }
                        }}
                        aria-label={`${confirming === row.month ? t('finance.confirmClose') : t('finance.closeMonth')} ${row.month}`}
                      >
                        {confirming === row.month ? t('finance.confirmClose') : t('finance.closeMonth')}
                      </Button>
                    )}
                  {row.state === 'closed' && can(P.FINANCIAL_ADJUST) && (
                    <Button
                      compact
                      variant="tertiary"
                      onClick={() => setReopening(row.month)}
                      aria-label={`${t('finance.reopenMonth')} ${row.month}`}
                    >
                      {t('finance.reopenMonth')}
                    </Button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {reopening && (
        <form
          className="ws-form"
          onSubmit={(event) => {
            event.preventDefault();
            reopen.mutate();
          }}
        >
          <Field label={`${t('finance.reopenReason')} (${reopening})`} required>
            {(props) => (
              <TextInput {...props} required value={reason} onChange={(event) => setReason(event.target.value)} />
            )}
          </Field>
          <div className="row-wrap">
            <Button type="submit" variant="danger" loading={reopen.isPending}>
              {t('finance.reopenMonth')}
            </Button>
            <Button onClick={() => setReopening(null)}>{t('common.cancel')}</Button>
          </div>
        </form>
      )}
    </Card>
  );
}

export function FinancePage() {
  const t = useT();
  const { can } = useSession();
  const [params, setParams] = useSearchParams();
  const costs = can(P.TARIFF_READ);
  const tabs = [
    { id: 'invoices', label: t('finance.tabInvoices') },
    { id: 'receivables', label: t('finance.tabReceivables') },
    ...(costs ? [{ id: 'payables', label: t('finance.tabPayables') }] : []),
    ...(costs ? [{ id: 'profitability', label: t('finance.tabProfitability') }] : []),
    { id: 'periods', label: t('finance.tabPeriods') },
  ];
  const requested = params.get('tab');
  const active = tabs.some((tab) => tab.id === requested) ? requested : 'invoices';
  return (
    <>
      <PageHeader title={t('finance.title')} subtitle={t('finance.subtitle')} />
      <Tabs tabs={tabs} active={active} onChange={(id) => setParams({ tab: id })} label={t('finance.title')} />
      <TabPanel id="invoices" active={active}>
        <InvoicesTab />
      </TabPanel>
      <TabPanel id="receivables" active={active}>
        <ReceivablesTab />
      </TabPanel>
      <TabPanel id="payables" active={active}>
        <PayablesTab />
      </TabPanel>
      <TabPanel id="profitability" active={active}>
        <ProfitabilityTab />
      </TabPanel>
      <TabPanel id="periods" active={active}>
        <PeriodsTab />
        {/* Phase 14: invoice due days. */}
        {active === 'periods' && <FinanceSettingsCard />}
      </TabPanel>
    </>
  );
}
