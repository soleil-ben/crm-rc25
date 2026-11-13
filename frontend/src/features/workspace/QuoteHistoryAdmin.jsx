/**
 * Quote history, Admin only (RC-UAT-21 Phase D, DEC-0233; OD-95, OD-98, OD-107).
 *
 * Every version of one customer's quote, newest first, with an Admin **Delete** action (a
 * soft delete: the record is kept for audit, and the version disappears from staff lists,
 * the Customer Account and accepted-not-invoiced) and, with "Show deleted", **Restore**.
 * Both need a reason and are audited by the server. The server decides what may be deleted
 * and says why not (an open offer, an accepted quote not yet invoiced, a draft or issued
 * invoice, a draft quote, or a version newer than the minimum age); this screen only words
 * the refusal. Rendered only for `quote:delete` (Admin); the server enforces it again.
 */

import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { dataRetentionApi } from '../../api/endpoints.js';
import { P, useOptionalSession } from '../../app/SessionContext.jsx';
import { useT } from '../../i18n/index.jsx';
import { Banner, Button, Checkbox, Field, Modal, StatusBadge, TextArea } from '../../components/ui/index.jsx';
import { formatDateTime, interpolate } from '../../utils/format.js';
import { formatCad, wsKey } from './workspaceFormat.js';

const REASON_MAX = 400;

function ReasonDialog({ mode, row, onClose, onConfirm, pending, error }) {
  const t = useT();
  const [reason, setReason] = useState('');
  const title = interpolate(t(`quoteDeletion.${mode}Title`), { version: row.version });
  return (
    <Modal
      open
      onClose={onClose}
      title={title}
      footer={
        <>
          <Button onClick={onClose}>{t('common.cancel')}</Button>
          <Button
            variant={mode === 'delete' ? 'danger' : 'primary'}
            loading={pending}
            disabled={!reason.trim()}
            onClick={() => onConfirm(reason.trim())}
          >
            {t(`quoteDeletion.${mode}Confirm`)}
          </Button>
        </>
      }
    >
      <p>{t(`quoteDeletion.${mode}Body`)}</p>
      {error && (
        <Banner tone="danger">
          {error.detail?.code ? t(`quoteDeletion.refusal.${error.detail.code}`, error.message) : error.message}
        </Banner>
      )}
      <Field label={t('quoteDeletion.reason')} required>
        {(props) => (
          <TextArea
            {...props}
            rows={3}
            maxLength={REASON_MAX}
            value={reason}
            onChange={(event) => setReason(event.target.value)}
          />
        )}
      </Field>
    </Modal>
  );
}

export function QuoteHistoryAdmin({ consolidationId, shipmentId, refresh, customerLabel }) {
  const t = useT();
  // Optional: the quote panel is also rendered without a session in unit tests.
  const session = useOptionalSession();
  const allowed = Boolean(session?.can(P.QUOTE_DELETE));
  const queryClient = useQueryClient();
  const [showDeleted, setShowDeleted] = useState(false);
  const [dialog, setDialog] = useState(null);
  // Under the workspace's key, so every workspace refresh (a finalise, a send) re-reads it.
  const base = consolidationId
    ? wsKey(consolidationId, 'quote-history', String(shipmentId))
    : ['quote-history', String(shipmentId)];
  const key = [...base, showDeleted];
  const query = useQuery({
    queryKey: key,
    queryFn: () => dataRetentionApi.quoteHistory(shipmentId, showDeleted),
    enabled: allowed,
  });
  const act = useMutation({
    mutationFn: ({ mode, row, reason }) =>
      mode === 'delete'
        ? dataRetentionApi.deleteQuote(row.quote_version_id, reason)
        : dataRetentionApi.restoreQuote(row.quote_version_id, reason),
    onSuccess: () => {
      setDialog(null);
      queryClient.invalidateQueries({ queryKey: base });
      if (refresh) refresh();
    },
  });
  if (!allowed) return null;
  const rows = query.data?.items ?? [];
  const forWhom = (label) => (customerLabel ? `${label} — ${customerLabel}` : label);

  return (
    <details className="ws-quote-history">
      <summary>{forWhom(t('quoteDeletion.title'))}</summary>
      <p className="meta">{t('quoteDeletion.intro')}</p>
      <Checkbox
        id={`quote-history-deleted-${shipmentId}`}
        label={t('quoteDeletion.showDeleted')}
        checked={showDeleted}
        onChange={(event) => setShowDeleted(event.target.checked)}
      />
      {query.error && <Banner tone="danger">{query.error.message}</Banner>}
      {query.data && rows.length === 0 && <p className="meta">{t('quoteDeletion.empty')}</p>}
      {rows.length > 0 && (
        <div className="table-wrap">
          <table className="table">
            <caption className="visually-hidden">{forWhom(t('quoteDeletion.title'))}</caption>
            <thead>
              <tr>
                <th scope="col">{t('quoteDeletion.version')}</th>
                <th scope="col">{t('quoteDeletion.status')}</th>
                <th scope="col">{t('quoteDeletion.total')}</th>
                <th scope="col">{t('quoteDeletion.offer')}</th>
                <th scope="col">{t('quoteDeletion.action')}</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.quote_version_id}>
                  <th scope="row">v{row.version}</th>
                  <td>
                    {t(`workspace.quoteStatus.${row.status}`, row.status)}
                    {row.expired && ` · ${t('quoteDeletion.expired')}`}
                    {row.deleted && (
                      <>
                        {' '}
                        <StatusBadge tone="neutral" label={t('quoteDeletion.deletedBadge')} />
                        <div className="meta">
                          {interpolate(t('quoteDeletion.deletedBy'), {
                            who: row.deleted.deleted_by || t('common.unknown'),
                            date: formatDateTime(row.deleted.deleted_at),
                          })}
                          {' — '}
                          {row.deleted.reason}
                        </div>
                      </>
                    )}
                  </td>
                  <td>{formatCad(row.total_revenue_cad)}</td>
                  <td>{row.offer_status ? t(`quoteDeletion.offerStatus.${row.offer_status}`, row.offer_status) : '—'}</td>
                  <td>
                    {row.deleted ? (
                      <Button
                        compact
                        onClick={() => {
                          act.reset();
                          setDialog({ mode: 'restore', row });
                        }}
                        aria-label={forWhom(interpolate(t('quoteDeletion.restoreLabel'), { version: row.version }))}
                      >
                        {t('quoteDeletion.restore')}
                      </Button>
                    ) : row.deletable ? (
                      <Button
                        compact
                        variant="danger"
                        onClick={() => {
                          act.reset();
                          setDialog({ mode: 'delete', row });
                        }}
                        aria-label={forWhom(interpolate(t('quoteDeletion.deleteLabel'), { version: row.version }))}
                      >
                        {t('quoteDeletion.delete')}
                      </Button>
                    ) : (
                      <span className="meta">
                        {t(`quoteDeletion.refusal.${row.refusal}`, row.refusal_message || '')}
                      </span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {dialog && (
        <ReasonDialog
          mode={dialog.mode}
          row={dialog.row}
          onClose={() => setDialog(null)}
          pending={act.isPending}
          error={act.error}
          onConfirm={(reason) => act.mutate({ ...dialog, reason })}
        />
      )}
    </details>
  );
}
