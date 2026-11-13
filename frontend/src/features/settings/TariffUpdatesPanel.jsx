/**
 * Settings → Tariff updates (Phase 13H, OD-76).
 *
 * A vendor rate email (`.eml`, the workbook attached) becomes a **draft** tariff version; the
 * designated approver reviews what changed against the active version and approves (after a
 * confirmation naming the version and its change counts) or rejects it. **No mailbox is
 * connected**: staff upload the saved email here, or it is dropped into the intake folder the
 * intake worker reads. Approve, Reject, Release and Reprocess are enabled only for an
 * approver, and the server checks again. Only the sender's address and the subject are shown;
 * the email body is never stored or shown. Server messages are in English: on the Vietnamese
 * screen a Vietnamese explanation is shown, with the server's text labelled as English.
 */

import { useEffect, useRef, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { tariffsApi } from '../../api/endpoints.js';
import { P, useSession } from '../../app/SessionContext.jsx';
import { useI18n, useT } from '../../i18n/index.jsx';
import {
  Banner,
  Button,
  Card,
  Field,
  Modal,
  StatusBadge,
  TextArea,
  TextInput,
} from '../../components/ui/index.jsx';
import { EmptyState, ErrorState, SkeletonRows } from '../../components/state/index.jsx';
import { formatDateTime } from '../../utils/format.js';

const TONE = {
  received: 'info',
  imported: 'success',
  duplicate: 'neutral',
  rejected: 'danger',
  refused: 'danger',
  failed: 'danger',
  no_attachment: 'warning',
  held_sender: 'warning',
};
/** Rows shown per diff list; the server's summary always counts them all. */
const DIFF_ROWS = 50;

function lines(text) {
  return text
    .split(/[\n,;]+/)
    .map((value) => value.trim())
    .filter(Boolean);
}

function vnd(value) {
  return value == null ? '—' : Number(value).toLocaleString('en-CA');
}

/** `rejected` by an approver (reviewed) reads differently from a refusal by rule. */
function stateKey(row) {
  if (row.status === 'rejected' && !row.reviewed_at) return 'refused';
  return row.status;
}

/** A server message, explained in Vietnamese on the Vietnamese screen. */
export function useServerText() {
  const { locale, t } = useI18n();
  return (error) => {
    if (!error) return null;
    if (locale !== 'vi') return error.message;
    const known = [403, 404, 409, 413, 422, 429].includes(error.status) ? error.status : 'other';
    return `${t(`tariffIntake.serverError.${known}`)} (${t('tariffIntake.inEnglish')}: ${error.message})`;
  };
}

function useReasonText() {
  const { locale, t } = useI18n();
  return (text) => (locale === 'vi' ? `${t('tariffIntake.inEnglish')}: ${text}` : text);
}

function IntakeSettings() {
  const t = useT();
  const serverText = useServerText();
  const { can } = useSession();
  const queryClient = useQueryClient();
  const query = useQuery({ queryKey: ['tariff-intake-settings'], queryFn: tariffsApi.intakeSettings });
  const [approvers, setApprovers] = useState('');
  const [domains, setDomains] = useState('');
  const [saved, setSaved] = useState(false);
  const canEdit = can(P.SETTINGS_MANAGE);

  useEffect(() => {
    if (query.data) {
      setApprovers((query.data.approver_emails || []).join('\n'));
      setDomains((query.data.allowed_sender_domains || []).join('\n'));
    }
  }, [query.data]);

  const save = useMutation({
    mutationFn: () =>
      tariffsApi.updateIntakeSettings({
        approver_emails: lines(approvers),
        allowed_sender_domains: lines(domains),
      }),
    onSuccess: (data) => {
      queryClient.setQueryData(['tariff-intake-settings'], data);
      queryClient.invalidateQueries({ queryKey: ['tariff-intake'] });
      setSaved(true);
    },
  });

  if (query.isLoading) return <SkeletonRows rows={2} />;
  if (query.error) return <ErrorState error={query.error} onRetry={query.refetch} />;
  return (
    <Card title={t('tariffIntake.settingsTitle')} headingLevel="h3">
      <p className="meta">
        {t('tariffIntake.mailbox')}: <span className="mono">{query.data.mailbox_address}</span> ·{' '}
        {t('tariffIntake.mailboxNotConnected')}
      </p>
      {query.data.is_default && <Banner tone="neutral">{t('tariffIntake.defaultsInForce')}</Banner>}
      {saved && <Banner tone="info">{t('states.savedSuccess')}</Banner>}
      {save.error && <Banner tone="danger">{serverText(save.error)}</Banner>}
      <form
        onSubmit={(event) => {
          event.preventDefault();
          setSaved(false);
          save.mutate();
        }}
      >
        <Field label={t('tariffIntake.approvers')} hint={t('tariffIntake.approversHint')}>
          {(props) => (
            <TextArea
              {...props}
              rows={3}
              value={approvers}
              readOnly={!canEdit}
              onChange={(event) => setApprovers(event.target.value)}
            />
          )}
        </Field>
        <Field label={t('tariffIntake.domains')} hint={t('tariffIntake.domainsHint')}>
          {(props) => (
            <TextArea
              {...props}
              rows={3}
              value={domains}
              readOnly={!canEdit}
              onChange={(event) => setDomains(event.target.value)}
            />
          )}
        </Field>
        {canEdit && (
          <Button type="submit" variant="primary" loading={save.isPending}>
            {t('tariffIntake.saveSettings')}
          </Button>
        )}
      </form>
    </Card>
  );
}

function DiffTable({ title, rows, total }) {
  const t = useT();
  if (!rows.length) return null;
  return (
    <div className="table-wrap" tabIndex={0} role="region" aria-label={title}>
      <table className="table">
        <caption className="meta">
          {title} ({total}
          {rows.length < total ? `, ${t('tariffIntake.showingFirst')} ${Math.min(rows.length, DIFF_ROWS)}` : ''})
        </caption>
        <thead>
          <tr>
            <th scope="col">{t('tariffIntake.product')}</th>
            <th scope="col">{t('tariffIntake.zone')}</th>
            <th scope="col">{t('tariffIntake.bracket')}</th>
            <th scope="col">{t('tariffIntake.oldPrice')}</th>
            <th scope="col">{t('tariffIntake.newPrice')}</th>
          </tr>
        </thead>
        <tbody>
          {rows.slice(0, DIFF_ROWS).map((row) => (
            <tr key={`${row.origin}-${row.product_code}-${row.kind}-${row.zone}-${row.label}`}>
              <td>
                {row.origin} · <span className="mono">{row.product_code}</span>
              </td>
              <td>{row.zone}</td>
              <td>
                {row.label} ({row.kind})
              </td>
              <td>{vnd(row.old_price_vnd)}</td>
              <td>{vnd(row.new_price_vnd)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function RuleList({ title, rules, render }) {
  if (!rules.length) return null;
  return (
    <>
      <h4>{title}</h4>
      <ul aria-label={title}>
        {rules.slice(0, DIFF_ROWS).map((rule) => (
          <li key={`${rule.section}-${rule.stt}`}>{render(rule)}</li>
        ))}
      </ul>
    </>
  );
}

/**
 * A draft version's diff against the active one, and the approver's decision.
 *
 * Used for an emailed draft here and, since Phase 14, for any draft in the tariff browser
 * (a manual workbook import goes through the same review). `approverOnly` hides Approve and
 * Reject from anyone who is not an approver (the browser); the intake list keeps them
 * visible but disabled. The server decides either way (OD-76).
 */
export function VersionReview({ versionId, publicId, reviewable, isApprover, approverOnly = false }) {
  const t = useT();
  const serverText = useServerText();
  const queryClient = useQueryClient();
  const [reason, setReason] = useState('');
  const [outcome, setOutcome] = useState(null);
  const [confirming, setConfirming] = useState(false);
  const diff = useQuery({
    queryKey: ['tariff-diff', versionId],
    queryFn: () => tariffsApi.diff(versionId),
  });
  const done = (key) => () => {
    setOutcome(key);
    setConfirming(false);
    queryClient.invalidateQueries({ queryKey: ['tariff-intake'] });
    queryClient.invalidateQueries({ queryKey: ['tariff-diff', versionId] });
    queryClient.invalidateQueries({ queryKey: ['tariff-versions'] });
  };
  const approve = useMutation({ mutationFn: () => tariffsApi.approve(versionId), onSuccess: done('approved') });
  const reject = useMutation({
    mutationFn: () => tariffsApi.reject(versionId, reason.trim()),
    onSuccess: done('rejected'),
  });
  const error = approve.error || reject.error;
  const d = diff.data;
  const diffReady = Boolean(d) && !diff.error;

  return (
    <Card title={`${t('tariffIntake.pendingTitle')} ${publicId}`} headingLevel="h3">
      {outcome && <Banner tone="info">{t(`tariffIntake.outcome.${outcome}`)}</Banner>}
      {error && <Banner tone="danger">{serverText(error)}</Banner>}
      {diff.isLoading ? (
        <SkeletonRows rows={3} />
      ) : diff.error ? (
        <ErrorState error={diff.error} onRetry={diff.refetch} />
      ) : (
        <>
          <p>
            {d.against_version_public_id
              ? `${t('tariffIntake.against')} ${d.against_version_public_id}`
              : t('tariffIntake.noActive')}
          </p>
          <ul className="meta" aria-label={t('tariffIntake.summary')}>
            {Object.entries(d.summary).map(([key, count]) => (
              <li key={key}>
                {t(`tariffIntake.diff.${key}`)}: {count}
              </li>
            ))}
          </ul>
          {d.truncated && <Banner tone="neutral">{t('tariffIntake.truncated')}</Banner>}
          {Object.values(d.summary).every((count) => count === 0) && (
            <Banner tone="neutral">{t('tariffIntake.noChanges')}</Banner>
          )}
          <DiffTable
            title={t('tariffIntake.diff.brackets_changed')}
            rows={d.brackets_changed}
            total={d.summary.brackets_changed}
          />
          <DiffTable
            title={t('tariffIntake.diff.brackets_added')}
            rows={d.brackets_added}
            total={d.summary.brackets_added}
          />
          <DiffTable
            title={t('tariffIntake.diff.brackets_removed')}
            rows={d.brackets_removed}
            total={d.summary.brackets_removed}
          />
          <RuleList
            title={t('tariffIntake.diff.surcharges_changed')}
            rules={d.surcharges_changed}
            render={(rule) => (
              <>
                {rule.section} #{rule.stt} {rule.name}:
                <ul>
                  {rule.fields.map((name) => (
                    <li key={name}>
                      {name}: {String(rule.old[name] ?? '—')} → {String(rule.new[name] ?? '—')}
                    </li>
                  ))}
                </ul>
              </>
            )}
          />
          <RuleList
            title={t('tariffIntake.diff.surcharges_added')}
            rules={d.surcharges_added}
            render={(rule) => `${rule.section} #${rule.stt} ${rule.name}`}
          />
          <RuleList
            title={t('tariffIntake.diff.surcharges_removed')}
            rules={d.surcharges_removed}
            render={(rule) => `${rule.section} #${rule.stt} ${rule.name}`}
          />
        </>
      )}
      {reviewable && !outcome && approverOnly && !isApprover && (
        <Banner tone="neutral">{t('tariffIntake.notApprover')}</Banner>
      )}
      {reviewable && !outcome && (isApprover || !approverOnly) && (
        <div className="stack">
          {!isApprover && <Banner tone="neutral">{t('tariffIntake.notApprover')}</Banner>}
          <Button variant="primary" disabled={!isApprover || !diffReady} onClick={() => setConfirming(true)}>
            {t('tariffIntake.approve')}
          </Button>
          <Field label={t('tariffIntake.rejectReason')} required>
            {(props) => (
              <TextInput
                {...props}
                value={reason}
                maxLength={400}
                disabled={!isApprover}
                onChange={(event) => setReason(event.target.value)}
              />
            )}
          </Field>
          <Button
            variant="danger"
            disabled={!isApprover || !reason.trim()}
            loading={reject.isPending}
            onClick={() => reject.mutate()}
          >
            {t('tariffIntake.reject')}
          </Button>
        </div>
      )}
      <Modal
        open={confirming && diffReady}
        onClose={() => setConfirming(false)}
        title={`${t('tariffIntake.confirmTitle')} ${publicId}`}
        footer={
          <>
            <Button onClick={() => setConfirming(false)}>{t('tariffIntake.cancel')}</Button>
            <Button variant="primary" loading={approve.isPending} onClick={() => approve.mutate()}>
              {t('tariffIntake.confirmApprove')}
            </Button>
          </>
        }
      >
        <p>
          {d?.against_version_public_id
            ? `${t('tariffIntake.confirmBody')} ${d.against_version_public_id}.`
            : t('tariffIntake.confirmBodyFirst')}
        </p>
        {d && (
          <ul aria-label={t('tariffIntake.summary')}>
            {Object.entries(d.summary).map(([key, count]) => (
              <li key={key}>
                {t(`tariffIntake.diff.${key}`)}: {count}
              </li>
            ))}
          </ul>
        )}
      </Modal>
    </Card>
  );
}

export function TariffUpdatesPanel() {
  const t = useT();
  const serverText = useServerText();
  const reasonText = useReasonText();
  const queryClient = useQueryClient();
  const fileInput = useRef(null);
  const [selected, setSelected] = useState(null);
  const query = useQuery({ queryKey: ['tariff-intake'], queryFn: () => tariffsApi.intake() });
  const afterRow = (row) => {
    queryClient.invalidateQueries({ queryKey: ['tariff-intake'] });
    if (row.status === 'imported') setSelected(row.id);
  };
  const upload = useMutation({
    mutationFn: (file) => tariffsApi.uploadIntake(file),
    onSuccess: (row) => {
      afterRow(row);
      if (fileInput.current) fileInput.current.value = '';
    },
  });
  const release = useMutation({ mutationFn: (id) => tariffsApi.release(id), onSuccess: afterRow });
  const reprocess = useMutation({ mutationFn: (id) => tariffsApi.reprocess(id), onSuccess: afterRow });
  const rows = query.data?.items ?? [];
  const isApprover = Boolean(query.data?.viewer_is_approver);
  const pending =
    rows.find((row) => row.id === selected) ||
    rows.find((row) => row.status === 'imported' && row.tariff_version_status === 'draft');
  const actionError = release.error || reprocess.error;

  return (
    <>
      <Card title={t('tariffIntake.title')}>
        <Banner tone="info">{t('tariffIntake.intro')}</Banner>
        <label className="import__file">
          <span>{t('tariffIntake.uploadLabel')}</span>
          <input
            ref={fileInput}
            type="file"
            accept=".eml,message/rfc822"
            disabled={upload.isPending}
            onChange={(event) => {
              const file = event.target.files?.[0];
              if (file) upload.mutate(file);
            }}
          />
        </label>
        {upload.error && <Banner tone="danger">{serverText(upload.error)}</Banner>}
        {upload.data && (
          <Banner tone="info">
            {upload.data.created
              ? `${t('tariffIntake.uploaded')}: ${t(`tariffIntake.state.${stateKey(upload.data)}`, upload.data.status)}`
              : t('tariffIntake.alreadyReceived')}
          </Banner>
        )}
        {actionError && <Banner tone="danger">{serverText(actionError)}</Banner>}
        {query.isLoading ? (
          <SkeletonRows rows={3} />
        ) : query.error ? (
          <ErrorState error={query.error} onRetry={query.refetch} />
        ) : rows.length === 0 ? (
          <EmptyState title={t('tariffIntake.emptyTitle')} body={t('tariffIntake.emptyBody')} />
        ) : (
          <div className="table-wrap" tabIndex={0} role="region" aria-label={t('tariffIntake.listLabel')}>
            <table className="table">
              <thead>
                <tr>
                  <th scope="col">{t('tariffIntake.received')}</th>
                  <th scope="col">{t('tariffIntake.sender')}</th>
                  <th scope="col">{t('tariffIntake.subject')}</th>
                  <th scope="col">{t('tariffIntake.attachment')}</th>
                  <th scope="col">{t('tariffIntake.status')}</th>
                  <th scope="col">{t('tariffIntake.version')}</th>
                  <th scope="col">
                    <span className="visually-hidden">{t('tariffIntake.actions')}</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => {
                  const what = row.subject || row.sender || `#${row.id}`;
                  return (
                    <tr key={row.id}>
                      <td>{formatDateTime(row.received_at || row.created_at)}</td>
                      <td className="mono">{row.sender || '—'}</td>
                      <td>{row.subject || '—'}</td>
                      <td>{row.attachment_name || '—'}</td>
                      <td>
                        <StatusBadge
                          tone={TONE[stateKey(row)]}
                          label={t(`tariffIntake.state.${stateKey(row)}`, row.status)}
                        />
                        {row.error && <span className="meta"> · {reasonText(row.error)}</span>}
                        {row.warning && <span className="meta"> · {reasonText(row.warning)}</span>}
                        {row.review_note && <span className="meta"> · {row.review_note}</span>}
                      </td>
                      <td>
                        {row.tariff_version_public_id
                          ? `${row.tariff_version_public_id} (${t(`tariffIntake.versionState.${row.tariff_version_status}`, row.tariff_version_status)})`
                          : '—'}
                      </td>
                      <td>
                        {row.status === 'held_sender' && (
                          <Button
                            compact
                            disabled={!isApprover}
                            loading={release.isPending && release.variables === row.id}
                            onClick={() => release.mutate(row.id)}
                            aria-label={`${t('tariffIntake.release')}: ${what}`}
                          >
                            {t('tariffIntake.release')}
                          </Button>
                        )}
                        {row.status === 'failed' && row.source === 'folder' && (
                          <Button
                            compact
                            disabled={!isApprover}
                            loading={reprocess.isPending && reprocess.variables === row.id}
                            onClick={() => reprocess.mutate(row.id)}
                            aria-label={`${t('tariffIntake.reprocess')}: ${what}`}
                          >
                            {t('tariffIntake.reprocess')}
                          </Button>
                        )}
                        {row.tariff_version_id && row.status === 'imported' && (
                          <Button
                            compact
                            variant="tertiary"
                            onClick={() => setSelected(row.id)}
                            aria-label={`${t('tariffIntake.review')} ${row.tariff_version_public_id}`}
                          >
                            {t('tariffIntake.review')}
                          </Button>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </Card>
      {pending && pending.tariff_version_id && (
        <VersionReview
          key={pending.id}
          versionId={pending.tariff_version_id}
          publicId={pending.tariff_version_public_id}
          reviewable={pending.tariff_version_status === 'draft' && pending.status === 'imported'}
          isApprover={isApprover}
        />
      )}
      <IntakeSettings />
    </>
  );
}
