/**
 * A draft invoice (owner decision 9a, Louis Tong, 2026-10-21).
 *
 * Prepared automatically when the customer accepted the quote. Staff edit the bill-to
 * details, the customer's reference or PO, notes, GST/HST and the lines, then **Save**.
 * **Download** gives the saved draft as a PDF watermarked DRAFT; **Send** issues the real,
 * numbered invoice from the saved draft and emails the customer, after a confirmation that
 * names what happens (a number is assigned), the total and the email address.
 *
 * A newer quote version (independent review M1): the page names both versions; Send needs
 * the box "Send at the accepted price (vN)" ticked, or staff **Withdraw** the draft (with a
 * reason) and issue from the latest version the normal way.
 *
 * Unsaved edits: while the form differs from what is saved, Send and Download are disabled
 * with "Save your changes first", and leaving the page asks for confirmation. A background
 * refetch never overwrites unsaved edits. The server
 * refuses a save, send or download made from a revision that is no longer the saved one, so
 * two people never overwrite each other or send what neither of them saw.
 *
 * GST/HST (owner, Louis Tong, 2026-10-22): rates are usually all-in, so a new draft is at
 * 13 %, included in the price. Staff change the rate and the mode (included / added on top);
 * the tax box shows the rate, the mode and the amounts, and the box "I have checked the
 * GST/HST on this invoice" must be ticked to Save -- changing the rate, the mode or a line
 * clears it. Send needs the saved revision's tax confirmed (the server refuses both with 422
 * `tax_unconfirmed`).
 *
 * The saved figures are the server's. The tax box also shows a preview of the form as typed
 * (`taxPreview`, in whole cents, the server's rule), so staff confirm what they will save.
 *
 * GST/HST by route (owner Ben, 2026-10-23; DEC-0227): the rate is filled in from the route --
 * 0 % when one end is outside Canada; for a domestic shipment the destination province's rate,
 * included in the price. The box names the route it came from. When a domestic shipment's
 * province is unknown there is no rate (`tax_rate_required`): staff choose one before saving.
 * The rates offered are the server's (`allowed_tax_rates`: 0, 5, 13, 14, 15 and the table's).
 * **Download** is disabled, like Send, until the saved revision's GST/HST is confirmed (the
 * server refuses it with 422 `tax_unconfirmed`; DEC-0229).
 *
 * Per line (owner Ben, 2026-10-24; DEC-0235, the Solaris Invoicing desk rules): staff still
 * enter the all-in amounts in included mode; the GST/HST is worked out line by line. The
 * saved draft shows a preview table -- Description, Qty, Rate, the amount before tax, the
 * tax code and the tax of each line, then Subtotal, the tax row(s) and Total -- built from the
 * server's per-line breakdown (`tax_lines`, `tax_rows`), exactly as the issued invoice and
 * its PDF will show them; nothing of it is recomputed here.
 */

import { useEffect, useMemo, useRef, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { invoiceDraftsApi } from '../../api/endpoints.js';
import { saveBlob } from '../../api/client.js';
import { P, useSession } from '../../app/SessionContext.jsx';
import { useT } from '../../i18n/index.jsx';
import { PageHeader } from '../../components/layout/AppShell.jsx';
import {
  Banner,
  Button,
  Card,
  Checkbox,
  Field,
  Modal,
  Select,
  StatusBadge,
  TextArea,
  TextInput,
} from '../../components/ui/index.jsx';
import { ErrorState, SkeletonCards } from '../../components/state/index.jsx';
import { formatDateTime } from '../../utils/format.js';
import { formatCad } from '../workspace/workspaceFormat.js';
import './finance.css';

const DRAFT_TONE = { draft: 'info', issued: 'success', discarded: 'neutral' };

/** Cents of a typed amount, or null when it is not a number. */
function cents(value) {
  const number = Number(String(value ?? '').trim());
  return Number.isFinite(number) ? Math.round(number * 100) : null;
}

/** Round half up of n / d for whole, non-negative n and d. */
function roundHalfUp(n, d) {
  return Math.floor((2 * n + d) / (2 * d));
}

/**
 * The GST/HST of the form as typed, by the server's rule (`invoice_tax_math`, DEC-0235), line
 * by line in whole cents: included -- each line's net is `round_half_up(gross / (1 + r))`,
 * its tax `round_half_up(net * r)`, and the net is nudged so net + tax is the line exactly;
 * added -- each line's tax is charged on top. The figures are the sums. Returns CAD strings,
 * or null while a line amount is not a number. (What staff confirm is echoed and checked by
 * the server, so a difference here is refused, never saved.)
 */
export function taxPreview(lines, ratePercent, mode) {
  // No rate chosen yet (domestic, province unknown): nothing to preview.
  if (ratePercent === '' || ratePercent === null || ratePercent === undefined) return null;
  const rate = Number(ratePercent) || 0;
  let subtotal = 0;
  let tax = 0;
  for (const line of lines || []) {
    const gross = cents(line.amount_cad);
    if (gross === null) return null;
    let lineTax = 0;
    let net = gross;
    if (rate > 0 && mode === 'included') {
      net = roundHalfUp(gross * 100, 100 + rate);
      lineTax = roundHalfUp(net * rate, 100);
      net = gross - lineTax;
    } else if (rate > 0) {
      lineTax = roundHalfUp(net * rate, 100);
    }
    subtotal += net;
    tax += lineTax;
  }
  const cad = (value) => (value / 100).toFixed(2);
  return { subtotal_cad: cad(subtotal), tax_cad: cad(tax), total_cad: cad(subtotal + tax) };
}

/**
 * The saved draft as the issued invoice will show it (DEC-0235): the server's per-line
 * breakdown and summary rows, or nothing while no rate is chosen.
 */
export function InvoicePreview({ draft }) {
  const t = useT();
  if (!draft.tax_lines || !draft.tax_rows) return null;
  return (
    <div data-testid="draft-invoice-preview">
      <h3 className="ws-subtitle">{t('invoiceDraft.previewTitle')}</h3>
      <p className="meta">{t('invoiceDraft.previewHint')}</p>
      <div className="table-wrap" tabIndex={0} role="region" aria-label={t('invoiceDraft.previewTitle')}>
        <table className="table">
          <thead>
            <tr>
              <th scope="col">{t('finance.description')}</th>
              <th scope="col">{t('finance.quantity')}</th>
              <th scope="col">{t('finance.unitPrice')}</th>
              <th scope="col">{t('invoiceDraft.previewNet')}</th>
              <th scope="col">{t('finance.taxCode')}</th>
              <th scope="col">{t('finance.lineTax')}</th>
            </tr>
          </thead>
          <tbody>
            {draft.tax_lines.map((line, index) => (
              // Draft lines have no id of their own; the position is the identity.
              <tr key={index}>
                <td>{line.description}</td>
                <td>{line.quantity}</td>
                <td>{line.unit_price_cad}</td>
                <td>{formatCad(line.net_cad)}</td>
                <td>{line.tax_code}</td>
                <td>{formatCad(line.tax_cad)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <dl className="fin-buckets" data-testid="draft-invoice-preview-summary">
        <div>
          <dt>{t('invoiceDraft.subtotal')}</dt>
          <dd>{formatCad(draft.subtotal_cad)}</dd>
        </div>
        {draft.tax_rows.map((row) => (
          <div key={row.label}>
            <dt>{row.label}</dt>
            <dd>{formatCad(row.tax_cad)}</dd>
          </div>
        ))}
        <div>
          <dt>{`${t('finance.total')} (CAD)`}</dt>
          <dd>
            <strong>{formatCad(draft.total_cad)}</strong>
          </dd>
        </div>
      </dl>
    </div>
  );
}

/**
 * The invoice's summary row for a rate, as `invoice_tax_math.summary_label` prints it
 * (DEC-0235): "GST @ 5%", "HST ON @ 13%", "HST @ 14%", "HST @ 15%"; any other rate "GST @ r%"
 * when its table label is GST, else "HST @ r%". RC-UAT-24 (I-11): the draft editor's
 * included-tax sentence uses the same words as the invoice.
 */
export function summaryLabel(rate, label) {
  const r = Number(rate);
  if (r === 0 || r === 5) return `GST @ ${r}%`;
  if (r === 13) return 'HST ON @ 13%';
  if (r === 14 || r === 15) return `HST @ ${r}%`;
  return `${label === 'GST' ? 'GST' : 'HST'} @ ${r}%`;
}

export function taxSummary(t, { rate, mode, subtotal, tax, total, label = 'GST/HST' }) {
  // At 0 % nothing is included or added (zero-rated, DEC-0227): the documents print no
  // "Prices include" sentence either.
  if (Number(rate) === 0) {
    return t('invoiceDraft.taxZeroSummary').replace('{total}', formatCad(total));
  }
  return t(mode === 'included' ? 'invoiceDraft.taxIncludedSummary' : 'invoiceDraft.taxAddedSummary')
    .replace('{summary}', summaryLabel(rate, label))
    .replaceAll('{label}', label)
    .replace('{rate}', String(rate))
    .replace('{subtotal}', formatCad(subtotal))
    .replace('{tax}', formatCad(tax))
    .replace('{total}', formatCad(total));
}

export function formFromDraft(draft) {
  return {
    bill_to_name: draft.bill_to_name || '',
    bill_to_address: draft.bill_to_address || '',
    customer_reference: draft.customer_reference || '',
    notes: draft.notes || '',
    // '' while no rate is chosen (domestic, province unknown; DEC-0227).
    tax_rate_percent: draft.tax_rate_percent === null ? '' : String(draft.tax_rate_percent ?? 0),
    tax_mode: draft.tax_mode || 'added',
    tax_confirmed: Boolean(draft.tax_confirmed),
    total_change_reason: draft.total_change_reason || '',
    lines: (draft.lines || []).map((line) => ({
      description: line.description,
      amount_cad: String(line.amount_cad),
    })),
  };
}

const FALLBACK_RATES = [0, 5, 13, 14, 15];

/** The rates staff may choose, as select options (a placeholder while none is chosen). */
export function rateOptions(t, draft, current) {
  const rates = (draft.allowed_tax_rates?.length ? draft.allowed_tax_rates : FALLBACK_RATES).map(
    String,
  );
  const options = rates.map((value) => ({ value, label: `${value} %` }));
  return current === '' ? [{ value: '', label: t('invoiceDraft.taxRateChoose') }, ...options] : options;
}

/** Where the rate was filled in from (DEC-0227), or null for a draft made before. */
export function routeNote(t, draft) {
  const route = draft.tax_route;
  if (!route) return null;
  const words = (key) =>
    t(key)
      .replace('{origin}', route.origin_country_code || '?')
      .replace('{destination}', route.destination_country_code || '?')
      .replace('{province}', route.destination_province || '?')
      .replace('{rate}', String(route.suggested_rate_percent ?? ''));
  if (route.route_band === 'international') return words('invoiceDraft.taxRouteInternational');
  if (route.suggested_rate_percent === null) return words('invoiceDraft.taxRouteUnknown');
  return words('invoiceDraft.taxRouteDomestic');
}

function sameForm(a, b) {
  return JSON.stringify(a) === JSON.stringify(b);
}

/**
 * Ask before leaving with unsaved edits: closing or reloading the tab (beforeunload) and
 * following any in-app link (a capture-phase click guard, because this app's router is not
 * a data router and has no navigation blocker).
 */
export function useUnsavedChangesGuard(dirty, message) {
  const dirtyRef = useRef(dirty);
  dirtyRef.current = dirty;
  useEffect(() => {
    const onBeforeUnload = (event) => {
      if (!dirtyRef.current) return undefined;
      event.preventDefault();
      event.returnValue = message;
      return message;
    };
    const onClick = (event) => {
      if (!dirtyRef.current || event.defaultPrevented || event.button !== 0) return;
      if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
      const anchor = event.target?.closest?.('a[href]');
      if (!anchor || anchor.hasAttribute('download') || anchor.target === '_blank') return;
      // The browser's own confirmation, by design.
      if (!window.confirm(message)) {
        event.preventDefault();
        event.stopPropagation();
      }
    };
    window.addEventListener('beforeunload', onBeforeUnload);
    document.addEventListener('click', onClick, true);
    return () => {
      window.removeEventListener('beforeunload', onBeforeUnload);
      document.removeEventListener('click', onClick, true);
    };
  }, [message]);
}

function isStale(error) {
  return error?.status === 409 && error?.detail?.code === 'stale_revision';
}

function SendDialog({ draft, onClose, onConfirm, pending }) {
  const t = useT();
  return (
    <Modal
      open
      onClose={onClose}
      title={t('invoiceDraft.confirmTitle')}
      footer={
        <>
          <Button onClick={onClose}>{t('common.cancel')}</Button>
          <Button variant="primary" loading={pending} onClick={onConfirm}>
            {t('invoiceDraft.confirmSend')}
          </Button>
        </>
      }
    >
      <p>{t('invoiceDraft.confirmNumber')}</p>
      <p>
        <strong>{t('invoiceDraft.confirmTotal').replace('{total}', formatCad(draft.total_cad))}</strong>
      </p>
      <p>
        {taxSummary(t, {
          rate: draft.tax_rate_percent,
          mode: draft.tax_mode,
          subtotal: draft.subtotal_cad,
          tax: draft.tax_cad,
          total: draft.total_cad,
          label: draft.tax_label || 'GST/HST',
        })}
      </p>
      <p>
        {draft.customer_email
          ? t('invoiceDraft.confirmEmail').replace('{email}', draft.customer_email)
          : t('invoiceDraft.confirmNoEmail')}
      </p>
    </Modal>
  );
}

function WithdrawDialog({ onClose, onConfirm, pending, error }) {
  const t = useT();
  const [reason, setReason] = useState('');
  return (
    <Modal
      open
      onClose={onClose}
      title={t('invoiceDraft.withdrawTitle')}
      footer={
        <>
          <Button onClick={onClose}>{t('common.cancel')}</Button>
          <Button
            variant="primary"
            loading={pending}
            disabled={!reason.trim()}
            onClick={() => onConfirm(reason.trim())}
          >
            {t('invoiceDraft.withdrawConfirm')}
          </Button>
        </>
      }
    >
      <p>{t('invoiceDraft.withdrawBody')}</p>
      {error && <Banner tone="danger">{error.message}</Banner>}
      <Field label={t('invoiceDraft.withdrawReason')} required>
        {(props) => (
          <TextArea
            {...props}
            rows={3}
            maxLength={300}
            value={reason}
            onChange={(event) => setReason(event.target.value)}
          />
        )}
      </Field>
    </Modal>
  );
}

function LinesEditor({ lines, onChange, disabled }) {
  const t = useT();
  const setLine = (index, field) => (event) =>
    onChange(lines.map((line, i) => (i === index ? { ...line, [field]: event.target.value } : line)));
  return (
    <fieldset className="fin-draft-lines" disabled={disabled}>
      <legend className="ws-subtitle">{t('invoiceDraft.lines')}</legend>
      {lines.map((line, index) => (
        // Lines have no id of their own; the position is the identity.
        <div className="ws-grid fin-draft-line" key={index}>
          <Field label={`${t('invoiceDraft.lineDescription')} ${index + 1}`}>
            {(props) => (
              <TextInput
                {...props}
                maxLength={300}
                value={line.description}
                onChange={setLine(index, 'description')}
              />
            )}
          </Field>
          <Field label={`${t('invoiceDraft.lineAmount')} ${index + 1}`}>
            {(props) => (
              <TextInput
                {...props}
                inputMode="decimal"
                value={line.amount_cad}
                onChange={setLine(index, 'amount_cad')}
              />
            )}
          </Field>
          <div className="fin-draft-line__remove">
            <Button
              compact
              variant="tertiary"
              disabled={disabled || lines.length === 1}
              onClick={() => onChange(lines.filter((_line, i) => i !== index))}
              aria-label={`${t('invoiceDraft.removeLine')} ${index + 1}`}
            >
              {t('invoiceDraft.removeLine')}
            </Button>
          </div>
        </div>
      ))}
      <Button
        compact
        disabled={disabled}
        onClick={() => onChange([...lines, { description: '', amount_cad: '0.00' }])}
      >
        {t('invoiceDraft.addLine')}
      </Button>
    </fieldset>
  );
}

export function InvoiceDraftPage() {
  const t = useT();
  const { draftId } = useParams();
  const { can } = useSession();
  const queryClient = useQueryClient();
  const canWrite = can(P.FINANCIAL_WRITE);
  const query = useQuery({
    queryKey: ['finance', 'invoice-draft', draftId],
    queryFn: () => invoiceDraftsApi.get(draftId),
  });
  const draft = query.data;
  const saved = useMemo(() => (draft ? formFromDraft(draft) : null), [draft]);
  const [form, setForm] = useState(null);
  const [notice, setNotice] = useState(null);
  const [sentResult, setSentResult] = useState(null);
  const [confirming, setConfirming] = useState(false);
  const [withdrawing, setWithdrawing] = useState(false);
  const [acknowledged, setAcknowledged] = useState(false);
  // The saved form the current edits started from.
  const baseRef = useRef(null);

  // Take the saved draft into the form when it first loads, and on a refetch only while
  // there are no unsaved edits: a background refetch never overwrites what staff typed.
  // (After a save, a send, a withdrawal or Reload the form is set explicitly.)
  useEffect(() => {
    if (!saved) return;
    const base = baseRef.current;
    setForm((current) =>
      current === null || base === null || sameForm(current, base) ? saved : current,
    );
    baseRef.current = saved;
  }, [saved]);

  const adopt = (updated) => {
    const fresh = formFromDraft(updated);
    baseRef.current = fresh;
    setForm(fresh);
    queryClient.setQueryData(['finance', 'invoice-draft', draftId], updated);
  };

  const editable = Boolean(draft && draft.status === 'draft' && canWrite);
  const dirty = Boolean(form && saved && !sameForm(form, saved));
  useUnsavedChangesGuard(dirty, t('invoiceDraft.leaveConfirm'));

  const refreshAll = () => {
    queryClient.invalidateQueries({ queryKey: ['finance'] });
    queryClient.invalidateQueries({ queryKey: ['workspace'] });
  };
  const save = useMutation({
    mutationFn: () =>
      invoiceDraftsApi.update(draft.id, {
        expected_revision: draft.revision,
        bill_to_name: form.bill_to_name,
        bill_to_address: form.bill_to_address,
        customer_reference: form.customer_reference,
        notes: form.notes,
        tax_rate_percent: Number(form.tax_rate_percent),
        tax_mode: form.tax_mode,
        tax_confirmed: form.tax_confirmed,
        // What the tax box showed beside the ticked box; the server refuses a save whose
        // figures differ (review, 2026-10-22).
        ...(preview
          ? {
              confirmed_total_cad: preview.total_cad,
              confirmed_tax_mode: form.tax_mode,
              confirmed_tax_rate_percent: Number(form.tax_rate_percent),
            }
          : {}),
        total_change_reason: form.total_change_reason,
        lines: form.lines,
      }),
    onSuccess: (updated) => {
      adopt(updated);
      setNotice(t('invoiceDraft.saved'));
      refreshAll();
    },
  });
  const send = useMutation({
    mutationFn: () =>
      invoiceDraftsApi.send(draft.id, draft.revision, {
        acknowledgeSuperseded: Boolean(draft.superseded_by_version) && acknowledged,
      }),
    onSuccess: (result) => {
      setConfirming(false);
      setSentResult(result);
      adopt(result.draft);
      refreshAll();
    },
    onError: () => setConfirming(false),
  });
  const withdraw = useMutation({
    mutationFn: (reason) => invoiceDraftsApi.withdraw(draft.id, reason),
    onSuccess: (updated) => {
      setWithdrawing(false);
      adopt(updated);
      refreshAll();
    },
  });
  const download = useMutation({
    mutationFn: () => invoiceDraftsApi.downloadPdf(draft.id, draft.revision),
    onSuccess: saveBlob,
  });

  if (query.isLoading || (draft && !form)) return <SkeletonCards count={2} />;
  if (query.error) {
    return (
      <Card>
        <ErrorState error={query.error} onRetry={query.refetch} />
      </Card>
    );
  }

  const set = (field) => (event) => {
    setNotice(null);
    setForm((current) => ({ ...current, [field]: event.target.value }));
  };
  // Changing what the tax is computed from clears the GST/HST check (owner, 2026-10-22).
  const setTax = (field) => (event) => {
    setNotice(null);
    setForm((current) => ({ ...current, [field]: event.target.value, tax_confirmed: false }));
  };
  const preview = taxPreview(form.lines, form.tax_rate_percent, form.tax_mode);
  const rateMissing = form.tax_rate_percent === '';
  const taxBlocked = editable && dirty && !form.tax_confirmed;
  const sendTaxBlocked = !draft.tax_confirmed;
  const conflict = [save.error, send.error, download.error].find(isStale);
  const otherError = [save.error, send.error, download.error].find((e) => e && !isStale(e));
  const reload = async () => {
    save.reset();
    send.reset();
    download.reset();
    const fresh = await query.refetch();
    if (fresh.data) adopt(fresh.data);
  };
  const superseded = draft.status === 'draft' && Boolean(draft.superseded_by_version);
  const versionWords = (key) =>
    t(key)
      .replaceAll('{version}', String(draft.quote_version ?? ''))
      .replaceAll('{latest}', String(draft.superseded_by_version ?? ''));

  return (
    <>
      <PageHeader
        breadcrumb={<Link to="/finance">{t('finance.title')}</Link>}
        title={`${t('invoiceDraft.title')} · ${draft.shipment_reference || ''}`}
        subtitle={`${draft.customer_name || ''} · ${t('invoiceDraft.fromQuote').replace(
          '{version}',
          String(draft.quote_version ?? ''),
        )}`}
        actions={
          <StatusBadge
            tone={DRAFT_TONE[draft.status]}
            label={t(`invoiceDraft.status.${draft.status}`, draft.status)}
          />
        }
      />
      {draft.status === 'draft' && <Banner tone="info">{t('invoiceDraft.noNumberYet')}</Banner>}
      {draft.quote_expired && <Banner tone="warning">{t('invoiceDraft.quoteExpired')}</Banner>}
      {superseded && (
        <Banner tone="warning" title={t('invoiceDraft.supersededTitle')}>
          {versionWords('invoiceDraft.supersededBody')}
        </Banner>
      )}
      {draft.status === 'discarded' && (
        <Banner tone="warning" title={t('invoiceDraft.discardedTitle')}>
          {draft.discard_reason}
        </Banner>
      )}
      {draft.status === 'issued' && draft.issued_invoice_id && (
        <Banner tone="success" title={t('invoiceDraft.sentTitle')}>
          <Link to={`/finance/invoices/${draft.issued_invoice_id}`} className="mono">
            {draft.issued_invoice_public_id}
          </Link>
          {draft.email_status
            ? ` · ${t('invoiceDraft.emailStatus').replace(
                '{status}',
                t(`workspace.offer.emailStatus.${draft.email_status}`, draft.email_status),
              )}`
            : ''}
        </Banner>
      )}
      {conflict && (
        <Banner
          tone="danger"
          title={t('invoiceDraft.conflictTitle')}
          action={
            <Button compact onClick={reload}>
              {t('invoiceDraft.reload')}
            </Button>
          }
        >
          {t('invoiceDraft.conflictBody')}
        </Banner>
      )}
      {otherError && <Banner tone="danger">{otherError.message}</Banner>}

      <Card title={t('invoiceDraft.detailsTitle')}>
        <form
          className="ws-form"
          aria-label={t('invoiceDraft.detailsTitle')}
          onSubmit={(event) => {
            event.preventDefault();
            if (editable && dirty && form.tax_confirmed && !rateMissing) save.mutate();
          }}
        >
          <fieldset disabled={!editable} className="fin-draft-fields">
            <div className="ws-grid">
              <Field label={t('invoiceDraft.billToName')}>
                {(props) => (
                  <TextInput
                    {...props}
                    maxLength={200}
                    value={form.bill_to_name}
                    onChange={set('bill_to_name')}
                  />
                )}
              </Field>
              <Field label={t('invoiceDraft.customerReference')} hint={t('common.optional')}>
                {(props) => (
                  <TextInput
                    {...props}
                    maxLength={120}
                    value={form.customer_reference}
                    onChange={set('customer_reference')}
                  />
                )}
              </Field>
            </div>
            <Field label={t('invoiceDraft.billToAddress')} hint={t('common.optional')}>
              {(props) => (
                <TextArea
                  {...props}
                  rows={3}
                  maxLength={1000}
                  value={form.bill_to_address}
                  onChange={set('bill_to_address')}
                />
              )}
            </Field>
          </fieldset>
          <LinesEditor
            lines={form.lines}
            disabled={!editable}
            onChange={(lines) => {
              setNotice(null);
              setForm((current) => ({ ...current, lines, tax_confirmed: false }));
            }}
          />
          <fieldset disabled={!editable} className="fin-draft-fields fin-draft-tax">
            <legend className="ws-subtitle">{t('invoiceDraft.taxTitle')}</legend>
            <div className="ws-grid">
              <Field label={t('finance.taxRate')} hint={t('invoiceDraft.taxRateHint')}>
                {(props) => (
                  <Select
                    {...props}
                    value={form.tax_rate_percent}
                    onChange={setTax('tax_rate_percent')}
                    options={rateOptions(t, draft, form.tax_rate_percent)}
                  />
                )}
              </Field>
              <Field label={t('invoiceDraft.taxMode')}>
                {(props) => (
                  <Select
                    {...props}
                    value={form.tax_mode}
                    onChange={setTax('tax_mode')}
                    options={['included', 'added'].map((value) => ({
                      value,
                      label: t(`invoiceDraft.taxModes.${value}`),
                    }))}
                  />
                )}
              </Field>
            </div>
            {routeNote(t, draft) && (
              <p className="meta" data-testid="draft-tax-route">
                {routeNote(t, draft)}
              </p>
            )}
            {rateMissing && (
              <p className="fin-draft-blocked" id="fin-draft-rate-required" role="note">
                {t('invoiceDraft.taxRateRequired')}
              </p>
            )}
            {preview && (
              <p className="fin-draft-tax__summary" data-testid="draft-tax-summary">
                {taxSummary(t, {
                  rate: form.tax_rate_percent,
                  mode: form.tax_mode,
                  subtotal: preview.subtotal_cad,
                  tax: preview.tax_cad,
                  total: preview.total_cad,
                  // The table's label (HST / GST) holds for the saved, auto-filled rate only.
                  label:
                    form.tax_rate_percent === String(draft.tax_rate_percent)
                      ? draft.tax_label || 'GST/HST'
                      : 'GST/HST',
                })}
              </p>
            )}
            {dirty && <p className="meta">{t('invoiceDraft.taxPreview')}</p>}
            <Checkbox
              label={t('invoiceDraft.taxConfirm')}
              checked={form.tax_confirmed}
              onChange={(event) => {
                setNotice(null);
                const checked = event.target.checked;
                setForm((current) => ({ ...current, tax_confirmed: checked }));
              }}
            />
            {!dirty && draft.tax_confirmed && draft.tax_confirmed_by && (
              <p className="meta">
                {t('invoiceDraft.taxConfirmedBy').replace('{who}', draft.tax_confirmed_by)}
              </p>
            )}
          </fieldset>
          <fieldset disabled={!editable} className="fin-draft-fields">
            <Field
              label={t('invoiceDraft.totalChangeReason')}
              hint={t('invoiceDraft.totalChangeReasonHint').replace(
                '{total}',
                formatCad(draft.quote_total_cad),
              )}
            >
              {(props) => (
                <TextInput
                  {...props}
                  maxLength={400}
                  value={form.total_change_reason}
                  onChange={set('total_change_reason')}
                />
              )}
            </Field>
            <Field label={t('invoiceDraft.notes')} hint={t('common.optional')}>
              {(props) => (
                <TextArea
                  {...props}
                  rows={3}
                  maxLength={2000}
                  value={form.notes}
                  onChange={set('notes')}
                />
              )}
            </Field>
          </fieldset>
          {editable && (
            <div className="row-wrap">
              <Button
                type="submit"
                variant="primary"
                loading={save.isPending}
                disabled={!dirty || !form.tax_confirmed || rateMissing}
                aria-describedby={
                  rateMissing
                    ? 'fin-draft-rate-required'
                    : taxBlocked
                      ? 'fin-draft-tax-blocked'
                      : undefined
                }
              >
                {t('invoiceDraft.save')}
              </Button>
              {dirty && (
                <Button compact onClick={() => setForm(saved)}>
                  {t('invoiceDraft.discardChanges')}
                </Button>
              )}
            </div>
          )}
          {taxBlocked && (
            <p className="fin-draft-blocked" id="fin-draft-tax-blocked" role="note">
              {t('invoiceDraft.taxConfirmBeforeSave')}
            </p>
          )}
          <div role="status" className="meta">
            {notice || ''}
          </div>
        </form>
      </Card>

      <Card title={t('invoiceDraft.savedTotalsTitle')}>
        {dirty && <p className="meta">{t('invoiceDraft.totalsAfterSave')}</p>}
        <dl className="fin-buckets">
          <div>
            <dt>{t('invoiceDraft.subtotal')}</dt>
            <dd>{draft.subtotal_cad === null ? '—' : formatCad(draft.subtotal_cad)}</dd>
          </div>
          <div>
            <dt>
              {draft.tax_rate_percent === null
                ? `${t('finance.tax')} · ${t('invoiceDraft.noRate')}`
                : `${t('finance.tax')} ${draft.tax_rate_percent} % · ${t(
                    `invoiceDraft.taxModes.${draft.tax_mode}`,
                    draft.tax_mode,
                  )}`}
            </dt>
            <dd>{draft.tax_cad === null ? '—' : formatCad(draft.tax_cad)}</dd>
          </div>
          <div>
            <dt>{t('finance.total')}</dt>
            <dd>
              <strong>{draft.total_cad === null ? '—' : formatCad(draft.total_cad)}</strong>
            </dd>
          </div>
          <div>
            <dt>{t('invoiceDraft.acceptedQuote')}</dt>
            <dd>{formatCad(draft.quote_total_cad)}</dd>
          </div>
        </dl>
        <InvoicePreview draft={draft} />
        <p className="meta">
          {t('invoiceDraft.revision')
            .replace('{revision}', String(draft.revision))
            .replace('{date}', formatDateTime(draft.updated_at))}
        </p>
        {draft.status === 'draft' && (
          <div className="ws-form">
            {dirty && (
              <p className="fin-draft-blocked" id="fin-draft-blocked" role="note">
                {t('invoiceDraft.saveFirst')}
              </p>
            )}
            {/* Send and Download alike (owner, 2026-10-23; DEC-0229). */}
            {!dirty && sendTaxBlocked && (
              <p className="fin-draft-blocked" id="fin-draft-send-tax" role="note">
                {/* A reader cannot tick and save: tell them neutrally (review, 2026-10-24). */}
                {t(canWrite ? 'invoiceDraft.taxUnconfirmedSend' : 'invoiceDraft.taxUnconfirmedReader')}
              </p>
            )}
            {superseded && canWrite && (
              <Checkbox
                label={versionWords('invoiceDraft.acknowledgeSuperseded')}
                checked={acknowledged}
                onChange={(event) => setAcknowledged(event.target.checked)}
              />
            )}
            <div className="row-wrap">
              <Button
                loading={download.isPending}
                disabled={dirty || sendTaxBlocked}
                aria-describedby={
                  dirty ? 'fin-draft-blocked' : sendTaxBlocked ? 'fin-draft-send-tax' : undefined
                }
                onClick={() => download.mutate()}
              >
                {t('invoiceDraft.download')}
              </Button>
              {canWrite && (
                <Button
                  variant="primary"
                  loading={send.isPending}
                  disabled={
                    dirty || sendTaxBlocked || draft.quote_expired || (superseded && !acknowledged)
                  }
                  aria-describedby={
                    dirty ? 'fin-draft-blocked' : sendTaxBlocked ? 'fin-draft-send-tax' : undefined
                  }
                  onClick={() => setConfirming(true)}
                >
                  {t('invoiceDraft.send')}
                </Button>
              )}
              {canWrite && (
                <Button variant="tertiary" onClick={() => setWithdrawing(true)}>
                  {t('invoiceDraft.withdraw')}
                </Button>
              )}
            </div>
            <p className="meta">{t('invoiceDraft.sendHint')}</p>
          </div>
        )}
        {sentResult && (
          <p role="status">
            {t('invoiceDraft.sentAs').replace('{number}', sentResult.invoice_public_id)}
          </p>
        )}
      </Card>
      {confirming && (
        <SendDialog
          draft={draft}
          pending={send.isPending}
          onClose={() => setConfirming(false)}
          onConfirm={() => send.mutate()}
        />
      )}
      {withdrawing && (
        <WithdrawDialog
          pending={withdraw.isPending}
          error={withdraw.error}
          onClose={() => {
            withdraw.reset();
            setWithdrawing(false);
          }}
          onConfirm={(reason) => withdraw.mutate(reason)}
        />
      )}
    </>
  );
}
