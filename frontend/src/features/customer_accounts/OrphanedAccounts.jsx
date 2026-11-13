/**
 * RC-UAT-22 (B-13, DEC-0234 draft): accounts that were approved once and no longer have a
 * customer -- typically an RC-UAT-21 reinstatement found the customer merged or archived and
 * ended the link. The approval queue cannot decide them (there is no pending proposal), so
 * this list is where an Admin re-links each one or closes it.
 *
 * **Re-link** follows the approval's order: name the customer (the merge survivor is
 * prefilled as a suggestion, never applied), read the history that link opens -- the five
 * OD-29 figures the server computed -- tick the acknowledgement, choose a reason, confirm.
 * The server refuses a preview that moved since it was read (409 `preview_stale`); this
 * screen then discards the acknowledgement and asks for a fresh look rather than retrying.
 *
 * **Close** deactivates the account with reason `orphan_closed`, after a reason and a
 * confirmation. Nothing is emailed to the customer.
 *
 * Admin only (`customer_account:deactivate`, the reinstatement permission); the server checks
 * it on every request.
 */

import { useState } from 'react';
import { Link } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  Banner,
  Button,
  Card,
  Checkbox,
  Field,
  Modal,
  Select,
  TextArea,
  TextInput,
} from '../../components/ui/index.jsx';
import { EmptyState, ErrorState } from '../../components/state/index.jsx';
import { useT } from '../../i18n/index.jsx';
import { ApiError } from '../../api/client.js';
import { customerAccountReviewApi } from '../../api/endpoints.js';
import { formatDate, formatDateTime } from '../../utils/format.js';

const LIST_KEY = ['customer-account', 'orphaned'];

export function OrphanedAccounts({ enabled }) {
  const t = useT();
  const queryClient = useQueryClient();
  const [relinkRow, setRelinkRow] = useState(null);
  const [closeRow, setCloseRow] = useState(null);
  const [notice, setNotice] = useState(null);

  const list = useQuery({
    queryKey: LIST_KEY,
    queryFn: () => customerAccountReviewApi.orphanedIdentities(),
    enabled,
  });

  function done(message) {
    setRelinkRow(null);
    setCloseRow(null);
    setNotice(message);
    queryClient.invalidateQueries({ queryKey: LIST_KEY });
    queryClient.invalidateQueries({ queryKey: ['customer-account', 'deactivated'] });
  }

  const data = list.data;
  return (
    <Card title={t('customerAccounts.orphanedTitle')} flush>
      <p className="meta" style={{ padding: '0 var(--space-5)' }}>
        {t('customerAccounts.orphanedIntro')}
      </p>
      {notice && <Banner tone="info">{notice}</Banner>}
      {list.error && <ErrorState error={list.error} onRetry={() => list.refetch()} />}
      {data && data.items.length === 0 && (
        <EmptyState title={t('customerAccounts.orphanedEmpty')} />
      )}
      {data && data.items.length > 0 && (
        <div className="table-wrap">
          <table className="table table--stacked" data-testid="orphaned-accounts">
            <caption className="visually-hidden">{t('customerAccounts.orphanedTitle')}</caption>
            <thead>
              <tr>
                <th scope="col">{t('customerAccounts.accountReference')}</th>
                <th scope="col">{t('customerAccounts.loginAddress')}</th>
                <th scope="col">{t('customerAccounts.orphanedApprovedAt')}</th>
                <th scope="col">{t('customerAccounts.orphanedLastCustomer')}</th>
                <th scope="col">{t('customerAccounts.orphanedEndReason')}</th>
                <th scope="col">{t('customerAccounts.orphanedSuggested')}</th>
                <th scope="col">{t('customerAccounts.orphanedActions')}</th>
              </tr>
            </thead>
            <tbody>
              {data.items.map((row) => (
                <tr key={row.account_reference}>
                  <td data-label={t('customerAccounts.accountReference')}>
                    <Link to={`/customer-accounts/${row.account_reference}`}>
                      {row.account_reference}
                    </Link>
                  </td>
                  <td data-label={t('customerAccounts.loginAddress')}>
                    {row.account_email_entered}
                  </td>
                  <td data-label={t('customerAccounts.orphanedApprovedAt')}>
                    {row.approved_at ? formatDateTime(row.approved_at) : '—'}
                  </td>
                  <td data-label={t('customerAccounts.orphanedLastCustomer')} className="mono">
                    {row.last_customer_public_id || '—'}
                    {row.last_customer_merged && ` ${t('customerAccounts.orphanedMerged')}`}
                  </td>
                  <td data-label={t('customerAccounts.orphanedEndReason')}>
                    {row.last_link_end_reason
                      ? t(
                          `customerAccounts.linkEndReason.${row.last_link_end_reason}`,
                          row.last_link_end_reason,
                        )
                      : '—'}
                  </td>
                  <td data-label={t('customerAccounts.orphanedSuggested')} className="mono">
                    {row.suggested_customer_public_id || t('customerAccounts.orphanedNoSuggestion')}
                  </td>
                  <td data-label={t('customerAccounts.orphanedActions')}>
                    <div className="row-wrap">
                      <Button
                        compact
                        onClick={() => {
                          setNotice(null);
                          setRelinkRow(row);
                        }}
                      >
                        {t('customerAccounts.relinkAction')}
                      </Button>
                      <Button
                        compact
                        variant="danger"
                        onClick={() => {
                          setNotice(null);
                          setCloseRow(row);
                        }}
                      >
                        {t('customerAccounts.closeAction')}
                      </Button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {relinkRow && (
        <RelinkDialog
          row={relinkRow}
          reasons={data?.relink_reason_codes ?? []}
          onClose={() => setRelinkRow(null)}
          onDone={() => done(t('customerAccounts.relinkDone'))}
        />
      )}
      {closeRow && (
        <CloseDialog
          row={closeRow}
          reasons={data?.close_reason_codes ?? []}
          onClose={() => setCloseRow(null)}
          onDone={() => done(t('customerAccounts.closeDone'))}
        />
      )}
    </Card>
  );
}

function ReasonSelect({ label, value, onChange, reasons, prefix }) {
  const t = useT();
  return (
    <Field label={label}>
      {(fieldProps) => (
        <Select
          {...fieldProps}
          value={value}
          onChange={(event) => onChange(event.target.value)}
          placeholder={t('customerAccounts.chooseReason')}
          options={reasons.map((code) => ({ value: code, label: t(`${prefix}.${code}`, code) }))}
        />
      )}
    </Field>
  );
}

function NoteField({ label, value, onChange }) {
  return (
    <Field label={label}>
      {(fieldProps) => (
        <TextArea
          {...fieldProps}
          rows={2}
          maxLength={500}
          value={value}
          onChange={(event) => onChange(event.target.value)}
        />
      )}
    </Field>
  );
}

function RelinkDialog({ row, reasons, onClose, onDone }) {
  const t = useT();
  const reference = row.account_reference;
  const [customer, setCustomer] = useState(row.suggested_customer_public_id || '');
  const [checked, setChecked] = useState(null);
  const [acknowledged, setAcknowledged] = useState(false);
  const [reason, setReason] = useState('');
  const [note, setNote] = useState('');
  const [stale, setStale] = useState(false);

  const preview = useMutation({
    mutationFn: () => customerAccountReviewApi.relinkPreview(reference, customer.trim()),
    onSuccess: (data) => {
      setChecked(data);
      setAcknowledged(false);
      setStale(false);
      // A fresh look replaces the refusal that asked for it; without this, the 409 of the
      // stale attempt reappears as a failure banner once `stale` is cleared.
      relink.reset();
    },
  });

  const relink = useMutation({
    mutationFn: () =>
      customerAccountReviewApi.relink(reference, {
        customer_public_id: checked.target_customer_public_id,
        reason_code: reason,
        note: note.trim() || null,
        history_acknowledged: acknowledged,
        preview_fingerprint: checked.fingerprint,
      }),
    onSuccess: () => onDone(),
    onError: (error) => {
      // A moved preview is not retried with the new fingerprint: the acknowledgement was
      // of the old figures. Discard it and ask for a fresh look.
      if (error instanceof ApiError && error.detail?.code === 'preview_stale') {
        setChecked(null);
        setAcknowledged(false);
        setStale(true);
      }
    },
  });

  const disclosure = checked?.disclosure;
  const failure = relink.error && !stale ? relink.error.message : null;

  return (
    <Modal
      open
      onClose={onClose}
      title={t('customerAccounts.relinkTitle').replace('{reference}', reference)}
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            {t('common.cancel')}
          </Button>
          <span className="spacer" />
          <Button
            variant="primary"
            disabled={!checked || !acknowledged || !reason || relink.isPending}
            loading={relink.isPending}
            onClick={() => relink.mutate()}
          >
            {t('customerAccounts.relinkConfirm')}
          </Button>
        </>
      }
    >
      <div className="stack">
        {stale && <Banner tone="warning">{t('customerAccounts.relinkStale')}</Banner>}
        {preview.error && <Banner tone="danger">{preview.error.message}</Banner>}
        {failure && <Banner tone="danger">{failure}</Banner>}
        <Field label={t('customerAccounts.relinkCustomer')}>
          {(fieldProps) => (
            <TextInput
              {...fieldProps}
              value={customer}
              maxLength={20}
              onChange={(event) => {
                setCustomer(event.target.value);
                setChecked(null);
                setAcknowledged(false);
              }}
            />
          )}
        </Field>
        <div className="row-wrap">
          <Button
            variant="secondary"
            disabled={!customer.trim() || preview.isPending}
            loading={preview.isPending}
            onClick={() => preview.mutate()}
          >
            {t('customerAccounts.relinkCheck')}
          </Button>
        </div>

        {checked && (
          <>
            <h3 className="card__title">{t('customerAccounts.relinkHistoryTitle')}</h3>
            <dl className="ca-review-list" data-testid="relink-history">
              <div className="ca-review-row">
                <dt>{t('customerAccounts.intendedCustomer')}</dt>
                <dd className="mono">{checked.target_customer_public_id}</dd>
              </div>
              <div className="ca-review-row">
                <dt>{t('customerAccounts.disclosureCount')}</dt>
                <dd>
                  <strong>{disclosure.shipment_count}</strong>
                </dd>
              </div>
              <div className="ca-review-row">
                <dt>{t('customerAccounts.disclosureOldest')}</dt>
                <dd>
                  {disclosure.oldest_booked_at ? formatDate(disclosure.oldest_booked_at) : '—'}
                </dd>
              </div>
              <div className="ca-review-row">
                <dt>{t('customerAccounts.disclosureNewest')}</dt>
                <dd>
                  {disclosure.newest_booked_at ? formatDate(disclosure.newest_booked_at) : '—'}
                </dd>
              </div>
              <div className="ca-review-row">
                <dt>{t('customerAccounts.disclosureCancelled')}</dt>
                <dd>{disclosure.includes_cancelled ? t('common.yes') : t('common.no')}</dd>
              </div>
              <div className="ca-review-row">
                <dt>{t('customerAccounts.disclosureRebooked')}</dt>
                <dd>{disclosure.includes_rebooked ? t('common.yes') : t('common.no')}</dd>
              </div>
            </dl>
            {checked.email_change && (
              <Banner tone="warning">
                <strong>{t('customerAccounts.emailChangeTitle')}</strong>
                <div>
                  {t('customerAccounts.emailChangeFrom')}: {checked.email_change.current || '—'}
                </div>
                <div>
                  {t('customerAccounts.emailChangeTo')}: {checked.email_change.new}
                </div>
              </Banner>
            )}
            <Checkbox
              label={t('customerAccounts.relinkAcknowledge')}
              checked={acknowledged}
              onChange={(event) => setAcknowledged(event.target.checked)}
            />
            <ReasonSelect
              label={t('customerAccounts.relinkReason')}
              value={reason}
              onChange={setReason}
              reasons={reasons}
              prefix="customerAccounts.relinkReasonCode"
            />
            <NoteField label={t('customerAccounts.relinkNote')} value={note} onChange={setNote} />
          </>
        )}
      </div>
    </Modal>
  );
}

function CloseDialog({ row, reasons, onClose, onDone }) {
  const t = useT();
  const reference = row.account_reference;
  const [reason, setReason] = useState('');
  const [note, setNote] = useState('');

  const close = useMutation({
    mutationFn: () =>
      customerAccountReviewApi.closeOrphan(reference, {
        reason_code: reason,
        note: note.trim() || null,
      }),
    onSuccess: () => onDone(),
  });

  return (
    <Modal
      open
      onClose={onClose}
      title={t('customerAccounts.closeTitle').replace('{reference}', reference)}
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            {t('common.cancel')}
          </Button>
          <span className="spacer" />
          <Button
            variant="danger"
            disabled={!reason || close.isPending}
            loading={close.isPending}
            onClick={() => close.mutate()}
          >
            {t('customerAccounts.closeConfirm')}
          </Button>
        </>
      }
    >
      <div className="stack">
        {close.error && <Banner tone="danger">{close.error.message}</Banner>}
        <p>{t('customerAccounts.closeBody')}</p>
        <ReasonSelect
          label={t('customerAccounts.closeReason')}
          value={reason}
          onChange={setReason}
          reasons={reasons}
          prefix="customerAccounts.closeReasonCode"
        />
        <NoteField label={t('customerAccounts.closeNote')} value={note} onChange={setNote} />
      </div>
    </Modal>
  );
}
