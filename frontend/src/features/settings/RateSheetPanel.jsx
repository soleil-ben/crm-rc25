/**
 * Settings → Kango rate sheets (step 2, DEC-0264 / DEC-0270).
 *
 * Upload → draft → diff → confirm, with the version history and rollback. Nothing prices
 * differently until a holder of the `tariff:approve` permission confirms (DEC-0268): the
 * server is the authority; this screen hides Confirm and Roll back from everyone else and
 * says why. An Admin (`staff:manage`) gives or takes the permission here.
 */

import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { opsApi, rateSheetApi } from '../../api/endpoints.js';
import { P, useSession } from '../../app/SessionContext.jsx';
import { useT } from '../../i18n/index.jsx';
import {
  Banner,
  Button,
  Card,
  Field,
  Select,
  StatusBadge,
  TextInput,
} from '../../components/ui/index.jsx';
import { EmptyState, ErrorState, SkeletonRows } from '../../components/state/index.jsx';
import { formatDateTime } from '../../utils/format.js';
import { TARIFF_PENDING_KEY } from './useTariffPending.js';
import { formatVnd } from '../workspace/workspaceFormat.js';

const STATUS_TONE = { active: 'success', draft: 'warning', superseded: 'neutral' };

function count(value) {
  return Array.isArray(value) ? value.length : Number(value ?? 0);
}

/** The diff the server computed, as the owner reads it. */
export function RateSheetDiff({ diff }) {
  const t = useT();
  const groups = (diff.bracket_groups ?? []).filter((g) => g.changed || g.added || g.removed);
  const summary = diff.summary ?? {};
  return (
    <div className="rs-diff">
      <p className="meta">
        {t('rateSheet.against').replace(
          '{version}',
          diff.against_version_public_id || t('rateSheet.nothingActive'),
        )}
      </p>
      <div className="rs-diff-grid">
        <div>
          <strong>{t('rateSheet.fx')}</strong>
          <div>
            {formatVnd(diff.fx?.old_vnd_per_cad)} → {formatVnd(diff.fx?.new_vnd_per_cad)}{' '}
            <StatusBadge
              tone={diff.fx?.changed ? 'warning' : 'neutral'}
              label={diff.fx?.changed ? t('rateSheet.changed') : t('rateSheet.unchanged')}
            />
          </div>
        </div>
        <div>
          <strong>{t('rateSheet.warehouseZone')}</strong>
          <div>
            {diff.warehouse_zone
              ? t('rateSheet.warehouseZoneValue')
                  .replace('{ground}', String(diff.warehouse_zone.ground_zone))
                  .replace('{express}', String(diff.warehouse_zone.express_zone))
              : '—'}
          </div>
        </div>
        <div>
          <strong>{t('rateSheet.pieceFees')}</strong>
          <div>
            {count(diff.piece_fees_changed)
              ? t('rateSheet.nChanged').replace('{n}', String(count(diff.piece_fees_changed)))
              : t('rateSheet.unchanged')}
          </div>
        </div>
        <div>
          <strong>{t('rateSheet.zones')}</strong>
          <div>
            {t('rateSheet.zonesSummary')
              .replace('{changed}', String(diff.zones_summary?.changed ?? 0))
              .replace('{added}', String(diff.zones_summary?.added ?? 0))
              .replace('{removed}', String(diff.zones_summary?.removed ?? 0))}
          </div>
        </div>
        <div>
          <strong>{t('rateSheet.surcharges')}</strong>
          <div>
            {t('rateSheet.surchargesSummary')
              .replace('{changed}', String(summary.surcharges_changed ?? 0))
              .replace('{added}', String(summary.surcharges_added ?? 0))
              .replace('{removed}', String(summary.surcharges_removed ?? 0))}
          </div>
        </div>
      </div>

      <h4>{t('rateSheet.ratesHeading')}</h4>
      {groups.length === 0 ? (
        <p>{t('rateSheet.noRateChanges')}</p>
      ) : (
        <div className="table-wrap">
          <table className="table" aria-label={t('rateSheet.ratesHeading')}>
            <thead>
              <tr>
                <th scope="col">{t('rateSheet.origin')}</th>
                <th scope="col">{t('rateSheet.product')}</th>
                <th scope="col">{t('rateSheet.zone')}</th>
                <th scope="col">{t('rateSheet.kind')}</th>
                <th scope="col">{t('rateSheet.changedCount')}</th>
                <th scope="col">{t('rateSheet.delta')}</th>
              </tr>
            </thead>
            <tbody>
              {groups.map((g) => (
                <tr key={`${g.origin}-${g.product_code}-${g.zone}-${g.kind}`}>
                  <td>{g.origin}</td>
                  <td className="mono">{g.product_code}</td>
                  <td>{g.zone}</td>
                  <td>{t(`rateSheet.kindLabel.${g.kind}`, g.kind)}</td>
                  <td>
                    {g.changed}
                    {g.added ? ` +${g.added}` : ''}
                    {g.removed ? ` −${g.removed}` : ''}
                  </td>
                  <td>
                    {g.delta_min_vnd === null
                      ? '—'
                      : g.delta_min_vnd === g.delta_max_vnd
                        ? formatVnd(g.delta_min_vnd)
                        : `${formatVnd(g.delta_min_vnd)} … ${formatVnd(g.delta_max_vnd)}`}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {(diff.surcharges_changed ?? []).length > 0 && (
        <>
          <h4>{t('rateSheet.surchargesChanged')}</h4>
          <ul>
            {diff.surcharges_changed.map((r) => (
              <li key={`${r.section}-${r.stt}`}>
                <span className="mono">
                  {r.section} {r.stt}
                </span>{' '}
                {r.name}: {r.fields.join(', ')}
              </li>
            ))}
          </ul>
        </>
      )}
      {['surcharges_added', 'surcharges_removed'].map((key) =>
        (diff[key] ?? []).length > 0 ? (
          <div key={key}>
            <h4>{t(`rateSheet.${key}`)}</h4>
            <ul>
              {diff[key].map((r) => (
                <li key={`${r.section}-${r.stt}`}>
                  <span className="mono">
                    {r.section} {r.stt}
                  </span>{' '}
                  {r.name}
                </li>
              ))}
            </ul>
          </div>
        ) : null,
      )}
      {(diff.surcharges_excluded_non_canada ?? []).length > 0 && (
        <details>
          <summary>
            {t('rateSheet.excluded').replace(
              '{n}',
              String(diff.surcharges_excluded_non_canada.length),
            )}
          </summary>
          <ul>
            {diff.surcharges_excluded_non_canada.map((r) => (
              <li key={`${r.section}-${r.stt}`}>
                <span className="mono">
                  {r.section} {r.stt}
                </span>{' '}
                {r.name}
              </li>
            ))}
          </ul>
        </details>
      )}
      {diff.truncated && <p className="meta">{t('rateSheet.truncated')}</p>}
    </div>
  );
}

function ReviewCard({ versionId, diff: initialDiff, isApprover, onDone }) {
  const t = useT();
  const queryClient = useQueryClient();
  const diffQuery = useQuery({
    queryKey: ['rate-sheet-diff', versionId],
    queryFn: () => rateSheetApi.diff(versionId),
    initialData: initialDiff,
  });
  const [reason, setReason] = useState('');
  const refreshAll = () => {
    queryClient.invalidateQueries({ queryKey: ['rate-sheet-history'] });
    queryClient.invalidateQueries({ queryKey: ['tariff-versions'] });
    queryClient.invalidateQueries({ queryKey: TARIFF_PENDING_KEY });
    queryClient.invalidateQueries({ queryKey: ['workspace'] });
  };
  const confirm = useMutation({
    mutationFn: () => rateSheetApi.confirm(versionId),
    onSuccess: () => {
      refreshAll();
      onDone('confirmed');
    },
  });
  const discard = useMutation({
    mutationFn: () => rateSheetApi.discard(versionId, reason.trim()),
    onSuccess: () => {
      refreshAll();
      onDone('discarded');
    },
  });
  const diff = diffQuery.data;
  if (!diff) return <SkeletonRows rows={3} />;
  const draft = diff.version_status === 'draft';
  return (
    <Card
      title={t('rateSheet.reviewTitle').replace('{version}', diff.version_public_id)}
      headingLevel="h3"
    >
      <p className="meta">
        {t('rateSheet.fileLine')
          .replace('{file}', diff.source_file_name || '—')
          .replace('{date}', diff.effective_from)
          .replace('{hash}', (diff.source_sha256 || '').slice(0, 12))}
      </p>
      <RateSheetDiff diff={diff} />
      {draft && !isApprover && <Banner tone="info">{t('rateSheet.notApprover')}</Banner>}
      {(confirm.error || discard.error) && (
        <Banner tone="danger">{(confirm.error || discard.error).message}</Banner>
      )}
      {draft && isApprover && (
        <div className="row-wrap">
          <Button variant="primary" loading={confirm.isPending} onClick={() => confirm.mutate()}>
            {t('rateSheet.confirm')}
          </Button>
          <Field label={t('rateSheet.discardReason')}>
            {(props) => (
              <TextInput {...props} value={reason} onChange={(event) => setReason(event.target.value)} />
            )}
          </Field>
          <Button
            variant="tertiary"
            disabled={!reason.trim()}
            loading={discard.isPending}
            onClick={() => discard.mutate()}
          >
            {t('rateSheet.discard')}
          </Button>
        </div>
      )}
    </Card>
  );
}

function UploadCard({ onImported }) {
  const t = useT();
  const queryClient = useQueryClient();
  const [file, setFile] = useState(null);
  const [effectiveFrom, setEffectiveFrom] = useState('');
  const [label, setLabel] = useState('');
  const upload = useMutation({
    mutationFn: () => rateSheetApi.importSheet(file, { effectiveFrom, label: label.trim() }),
    onSuccess: (result) => {
      queryClient.invalidateQueries({ queryKey: ['rate-sheet-history'] });
      queryClient.invalidateQueries({ queryKey: TARIFF_PENDING_KEY });
      onImported(result);
    },
  });
  return (
    <Card title={t('rateSheet.uploadTitle')} headingLevel="h3">
      <p className="meta">{t('rateSheet.uploadIntro')}</p>
      {upload.error && <Banner tone="danger">{upload.error.message}</Banner>}
      <form
        className="form-grid"
        onSubmit={(event) => {
          event.preventDefault();
          upload.mutate();
        }}
      >
        <Field label={t('rateSheet.file')} required>
          {(props) => (
            <input
              {...props}
              type="file"
              accept=".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
              onChange={(event) => setFile(event.target.files?.[0] ?? null)}
            />
          )}
        </Field>
        <Field label={t('rateSheet.effectiveFrom')} hint={t('rateSheet.effectiveHint')} required>
          {(props) => (
            <TextInput
              {...props}
              type="date"
              value={effectiveFrom}
              onChange={(event) => setEffectiveFrom(event.target.value)}
            />
          )}
        </Field>
        <Field label={t('rateSheet.label')}>
          {(props) => (
            <TextInput {...props} maxLength={120} value={label} onChange={(event) => setLabel(event.target.value)} />
          )}
        </Field>
        <div className="row-wrap">
          <Button
            type="submit"
            variant="primary"
            disabled={!file || !effectiveFrom}
            loading={upload.isPending}
          >
            {t('rateSheet.upload')}
          </Button>
        </div>
      </form>
    </Card>
  );
}

function HistoryCard({ isApprover, onReview }) {
  const t = useT();
  const queryClient = useQueryClient();
  const history = useQuery({ queryKey: ['rate-sheet-history'], queryFn: rateSheetApi.history });
  const rollback = useMutation({
    mutationFn: (versionId) => rateSheetApi.rollback(versionId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['rate-sheet-history'] });
      queryClient.invalidateQueries({ queryKey: ['tariff-versions'] });
      queryClient.invalidateQueries({ queryKey: ['workspace'] });
    },
  });
  const versions = history.data?.versions ?? [];
  return (
    <Card title={t('rateSheet.historyTitle')} headingLevel="h3" flush>
      {history.isLoading ? (
        <SkeletonRows rows={3} />
      ) : history.error ? (
        <ErrorState error={history.error} onRetry={history.refetch} />
      ) : versions.length === 0 ? (
        <EmptyState title={t('rateSheet.noVersions')} />
      ) : (
        <div className="table-wrap">
          {rollback.error && <Banner tone="danger">{rollback.error.message}</Banner>}
          <table className="table" aria-label={t('rateSheet.historyTitle')}>
            <thead>
              <tr>
                <th scope="col">{t('rateSheet.version')}</th>
                <th scope="col">{t('rateSheet.status')}</th>
                <th scope="col">{t('rateSheet.effectiveFrom')}</th>
                <th scope="col">{t('rateSheet.file')}</th>
                <th scope="col">{t('rateSheet.hash')}</th>
                <th scope="col">{t('rateSheet.imported')}</th>
                <th scope="col">{t('rateSheet.activated')}</th>
                <th scope="col">
                  <span className="visually-hidden">{t('rateSheet.actions')}</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {versions.map((v) => (
                <tr key={v.id}>
                  <td className="mono">{v.public_id}</td>
                  <td>
                    <StatusBadge
                      tone={STATUS_TONE[v.status] ?? 'neutral'}
                      label={t(`rateSheet.statusLabel.${v.status}`, v.status)}
                    />
                  </td>
                  <td>
                    {v.effective_from}
                    {v.effective_to ? ` → ${v.effective_to}` : ''}
                  </td>
                  <td>{v.source_file_name || '—'}</td>
                  <td className="mono" title={v.source_sha256}>
                    {(v.source_sha256 || '').slice(0, 12)}
                  </td>
                  <td>{formatDateTime(v.imported_at)}</td>
                  <td>{v.activated_at ? formatDateTime(v.activated_at) : '—'}</td>
                  <td>
                    <div className="row-wrap">
                      <Button compact onClick={() => onReview(v.id)}>
                        {t('rateSheet.viewChanges')}
                      </Button>
                      {isApprover && v.status === 'superseded' && (
                        <Button
                          compact
                          variant="tertiary"
                          loading={rollback.isPending && rollback.variables === v.id}
                          onClick={() => rollback.mutate(v.id)}
                        >
                          {t('rateSheet.rollback')}
                        </Button>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}

function ApproversCard() {
  const t = useT();
  const { can } = useSession();
  const canManage = can(P.STAFF_MANAGE);
  const queryClient = useQueryClient();
  const grants = useQuery({ queryKey: ['permission-grants'], queryFn: rateSheetApi.grants });
  const staff = useQuery({ queryKey: ['staff'], queryFn: opsApi.staff, enabled: canManage });
  const [pick, setPick] = useState('');
  const change = useMutation({
    mutationFn: ({ userId, give }) => (give ? rateSheetApi.grant(userId) : rateSheetApi.revoke(userId)),
    onSuccess: (data) => {
      queryClient.setQueryData(['permission-grants'], data);
      queryClient.invalidateQueries({ queryKey: TARIFF_PENDING_KEY });
      setPick('');
    },
  });
  const holders = grants.data?.['tariff:approve'] ?? [];
  const held = new Set(holders.map((h) => h.user_id));
  // The grant takes effect with the Admin role only (tariff:manage, DEC-0268), so only
  // active Admins are offered.
  const candidates = (staff.data ?? []).filter(
    (s) => s.is_active && s.role === 'admin' && !held.has(s.id),
  );
  return (
    <Card title={t('rateSheet.approversTitle')} headingLevel="h3">
      <p className="meta">{t('rateSheet.approversIntro')}</p>
      {grants.error && <ErrorState error={grants.error} />}
      {change.error && <Banner tone="danger">{change.error.message}</Banner>}
      {holders.length === 0 ? (
        <p>{t('rateSheet.noApprovers')}</p>
      ) : (
        <ul className="rs-approvers">
          {holders.map((h) => (
            <li key={h.user_id}>
              {h.full_name} <span className="meta">({h.email})</span>
              {canManage && (
                <Button
                  compact
                  variant="tertiary"
                  onClick={() => change.mutate({ userId: h.user_id, give: false })}
                >
                  {t('rateSheet.revoke')}
                </Button>
              )}
            </li>
          ))}
        </ul>
      )}
      {canManage && (
        <div className="row-wrap">
          <Field label={t('rateSheet.grantTo')}>
            {(props) => (
              <Select
                {...props}
                value={pick}
                placeholder={t('rateSheet.chooseStaff')}
                onChange={(event) => setPick(event.target.value)}
                options={candidates.map((s) => ({
                  value: String(s.id),
                  label: `${s.full_name} (${s.email})`,
                }))}
              />
            )}
          </Field>
          <Button
            disabled={!pick}
            loading={change.isPending}
            onClick={() => change.mutate({ userId: Number(pick), give: true })}
          >
            {t('rateSheet.grant')}
          </Button>
        </div>
      )}
    </Card>
  );
}

export function RateSheetPanel() {
  const t = useT();
  const status = useQuery({ queryKey: TARIFF_PENDING_KEY, queryFn: rateSheetApi.pendingCount });
  const isApprover = Boolean(status.data?.viewer_is_approver);
  const [review, setReview] = useState(null); // { versionId, diff? }
  const [notice, setNotice] = useState(null);
  return (
    <div className="settings-stack">
      <p className="meta">{t('rateSheet.intro')}</p>
      {notice && (
        <Banner tone="info">
          {notice === 'confirmed' ? t('rateSheet.confirmedNotice') : t('rateSheet.discardedNotice')}
        </Banner>
      )}
      <UploadCard
        onImported={(result) => {
          setNotice(null);
          setReview({ versionId: result.version.id, diff: result.diff });
        }}
      />
      {review && (
        <ReviewCard
          key={review.versionId}
          versionId={review.versionId}
          diff={review.diff}
          isApprover={isApprover}
          onDone={(what) => {
            setNotice(what);
            setReview(null);
          }}
        />
      )}
      <HistoryCard
        isApprover={isApprover}
        onReview={(versionId) => setReview({ versionId, diff: undefined })}
      />
      <ApproversCard />
    </div>
  );
}
