/**
 * Shipment import and legacy history baseline (RC-UAT-21 Phase A, DEC-0230).
 *
 * Same shape as the customer import: choose a file, read the dry-run report, confirm, and
 * only then import. The dry run writes nothing; the commit re-sends the same file with the
 * digest the dry run returned, and the server refuses it unless the same staff member
 * dry-ran the same bytes (and, for a baseline, the same cutoff date).
 *
 * The legacy page also lists baselines (each can be voided as a whole, with a reason) and
 * the legacy records themselves, which staff can read but never act on.
 */

import { useRef, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { bulkImportsApi } from '../../api/endpoints.js';
import { downloadUrl } from '../../api/client.js';
import { useT } from '../../i18n/index.jsx';
import { P, useSession } from '../../app/SessionContext.jsx';
import { PageHeader } from '../../components/layout/AppShell.jsx';
import {
  Banner,
  Button,
  Card,
  Checkbox,
  Field,
  Modal,
  StatusBadge,
  TextArea,
  TextInput,
} from '../../components/ui/index.jsx';
import { EmptyState, ErrorState, InlineSpinner } from '../../components/state/index.jsx';
import { formatDateTime, formatNumber } from '../../utils/format.js';
import { ImportKindNav } from './ImportKindNav.jsx';
import './imports.css';

const CLASSIFICATION_TONE = {
  ready: 'success',
  already_imported: 'neutral',
  duplicate: 'warning',
  rejected: 'danger',
};

const KIND_CONFIG = {
  shipments: {
    segment: 'shipments',
    i18n: 'shipments',
    counts: ['ready', 'duplicate', 'rejected'],
  },
  legacy_history: {
    segment: 'legacy-history',
    i18n: 'legacy',
    counts: ['ready', 'already_imported', 'duplicate', 'rejected'],
  },
};

/**
 * The server sends English text plus a stable code. Where the catalogue knows the code, the
 * staff UI shows the catalogue text in the active language (en/vi), naming the column; an
 * unknown code falls back to the server's English sentence (kept as the tooltip).
 */
export function issueText(t, issue) {
  const text = t(`bulkImports.issue.${issue.code}`, '');
  return text ? `${text} (${issue.field_name})` : issue.message;
}

export function noteText(t, report, note, index) {
  const code = report.note_codes?.[index];
  const text = code ? t(`bulkImports.note.${code}`, '') : '';
  return text ? text.replace('{columns}', (report.unmapped_headers || []).join(', ')) : note;
}

export function ShipmentImportPage() {
  return <BulkImportPage kind="shipments" />;
}

export function LegacyHistoryImportPage() {
  return <BulkImportPage kind="legacy_history" />;
}

function BulkImportPage({ kind }) {
  const t = useT();
  const { can } = useSession();
  const queryClient = useQueryClient();
  const fileInput = useRef(null);
  const config = KIND_CONFIG[kind];
  const isLegacy = kind === 'legacy_history';

  const [file, setFile] = useState(null);
  const [cutoffDate, setCutoffDate] = useState('');
  const [report, setReport] = useState(null);
  const [result, setResult] = useState(null);
  const [confirmOpen, setConfirmOpen] = useState(false);

  const fields = useQuery({
    queryKey: ['bulk-import-fields', kind],
    queryFn: () => bulkImportsApi.fields(config.segment),
  });

  const dryRun = useMutation({
    mutationFn: (selected) =>
      bulkImportsApi.dryRun(config.segment, selected, { cutoffDate: cutoffDate || undefined }),
    onSuccess: (data) => {
      setReport(data);
      setResult(null);
    },
  });

  const commit = useMutation({
    mutationFn: () =>
      bulkImportsApi.commit(config.segment, file, {
        contentSha256: report.content_sha256,
        cutoffDate: report.options?.cutoff_date || undefined,
      }),
    onSuccess: (data) => {
      setResult(data);
      setConfirmOpen(false);
      queryClient.invalidateQueries({ queryKey: ['shipments'] });
      queryClient.invalidateQueries({ queryKey: ['legacy-baselines'] });
      queryClient.invalidateQueries({ queryKey: ['legacy-shipments'] });
      queryClient.invalidateQueries({ queryKey: ['import-batches'] });
    },
  });

  function chooseFile(event) {
    const selected = event.target.files?.[0];
    if (!selected) return;
    setFile(selected);
    setReport(null);
    setResult(null);
    commit.reset();
    dryRun.mutate(selected);
  }

  function startOver() {
    setFile(null);
    setReport(null);
    setResult(null);
    dryRun.reset();
    commit.reset();
    if (fileInput.current) fileInput.current.value = '';
  }

  const k = (key) => t(`bulkImports.${key}`);
  const wouldImport = report?.counts.ready ?? 0;

  return (
    <>
      <PageHeader
        title={k(`${config.i18n}.title`)}
        subtitle={k(`${config.i18n}.subtitle`)}
        breadcrumb={<Link to="/customers">{t('nav.customers')}</Link>}
        actions={
          can(P.IMPORT_TEMPLATE) ? (
            <Button
              variant="secondary"
              onClick={() => {
                window.location.href = downloadUrl(`/imports/${config.segment}/template.csv`);
              }}
            >
              {k('downloadTemplate')}
            </Button>
          ) : null
        }
      />
      <ImportKindNav />

      {!can(P.IMPORT_PREVIEW) && <Banner tone="neutral">{k('noDryRunPermission')}</Banner>}

      {can(P.IMPORT_PREVIEW) && !report && !result && (
        <Card title={k('chooseFile')}>
          <p>{k(`${config.i18n}.chooseFileBody`)}</p>
          {isLegacy && (
            <Field id="legacy-cutoff" label={k('cutoffLabel')} hint={k('cutoffHint')}>
              {(props) => (
                <TextInput
                  {...props}
                  type="date"
                  value={cutoffDate}
                  onChange={(event) => setCutoffDate(event.target.value)}
                  style={{ maxWidth: 220 }}
                />
              )}
            </Field>
          )}
          <label className="import__file">
            <span className="visually-hidden">{k('fileInputLabel')}</span>
            <input
              ref={fileInput}
              type="file"
              accept=".csv,text/csv"
              onChange={chooseFile}
              disabled={dryRun.isPending}
              data-testid={`bulk-import-file-${kind}`}
            />
          </label>
          {dryRun.isPending && <InlineSpinner label={k('reading')} />}
          {dryRun.error && (
            <Banner tone="danger" title={k('fileProblem')}>
              {dryRun.error.message}
            </Banner>
          )}
        </Card>
      )}

      {report && !result && (
        <>
          <Banner tone="info" title={k('dryRunOnly')}>
            <ul className="reports__notes">
              {report.notes.map((note, index) => (
                <li key={note}>{noteText(t, report, note, index)}</li>
              ))}
            </ul>
          </Banner>

          <Card title={k('reportTitle')}>
            <dl className="report__summary">
              {config.counts.map((key) => (
                <div key={key}>
                  <dt>{k(`count.${key}`)}</dt>
                  <dd>{formatNumber(report.counts[key] ?? 0)}</dd>
                </div>
              ))}
            </dl>
            {report.options?.cutoff_date && (
              <p className="meta">
                {k('cutoffLabel')}: {report.options.cutoff_date}
              </p>
            )}
          </Card>

          <Card title={k('rowsTitle')}>
            <div className="table-wrap">
              <table className="table table--stacked">
                <caption className="visually-hidden">{k('rowsTitle')}</caption>
                <thead>
                  <tr>
                    <th scope="col">{k('columnRow')}</th>
                    <th scope="col">{k('columnReference')}</th>
                    <th scope="col">{k('columnClassification')}</th>
                    <th scope="col">{k('columnIssues')}</th>
                  </tr>
                </thead>
                <tbody>
                  {report.rows.map((row) => (
                    <tr key={row.row_number}>
                      <td data-label={k('columnRow')}>{row.row_number}</td>
                      <td data-label={k('columnReference')} className="table__primary">
                        <span className="mono">{row.reference || '—'}</span>
                        <div className="meta">
                          {[row.customer_public_id, row.summary?.recipient_name]
                            .filter(Boolean)
                            .join(' · ')}
                        </div>
                      </td>
                      <td data-label={k('columnClassification')}>
                        <StatusBadge
                          tone={CLASSIFICATION_TONE[row.classification]}
                          value={row.classification}
                          label={k(`count.${row.classification}`)}
                        />
                      </td>
                      <td data-label={k('columnIssues')}>
                        {row.issues.length === 0 ? (
                          <span className="meta">—</span>
                        ) : (
                          <ul className="import__issues">
                            {row.issues.map((issue, index) => (
                              <li
                                key={`${issue.field_name}-${issue.code}-${index}`}
                                title={issue.message}
                              >
                                {issueText(t, issue)}
                              </li>
                            ))}
                          </ul>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>

          {commit.error && (
            <Banner tone="danger" title={k('commitProblem')}>
              {commit.error.message}
            </Banner>
          )}

          <div className="import__actions">
            <Button variant="secondary" onClick={startOver}>
              {k('cancel')}
            </Button>
            <span className="spacer" />
            {can(P.IMPORT_COMMIT) && can(P.SHIPMENT_WRITE) ? (
              <Button
                variant="primary"
                onClick={() => setConfirmOpen(true)}
                disabled={commit.isPending || wouldImport === 0}
              >
                {wouldImport === 0
                  ? k('nothingToImport')
                  : k('importNow').replace('{count}', String(wouldImport))}
              </Button>
            ) : (
              <Banner tone="neutral">{k('noCommitPermission')}</Banner>
            )}
          </div>
          <p className="meta import__cancel-note">{k('cancelIsFree')}</p>
        </>
      )}

      {result && (
        <>
          <Banner tone="success" title={k('doneTitle')}>
            {k('doneBody').replace('{batch}', result.batch_public_id)}
          </Banner>
          <Card title={k('summaryTitle')}>
            <dl className="report__summary">
              {['created', 'matched', 'skipped', 'rejected'].map((key) => (
                <div key={key}>
                  <dt>{k(`result.${key}`)}</dt>
                  <dd>{formatNumber(result[key])}</dd>
                </div>
              ))}
            </dl>
          </Card>
          <Card title={k('rowsTitle')}>
            <div className="table-wrap">
              <table className="table table--stacked">
                <caption className="visually-hidden">{k('rowsTitle')}</caption>
                <thead>
                  <tr>
                    <th scope="col">{k('columnRow')}</th>
                    <th scope="col">{k('columnReference')}</th>
                    <th scope="col">{k('columnOutcome')}</th>
                    <th scope="col">{k('columnRecord')}</th>
                  </tr>
                </thead>
                <tbody>
                  {result.rows.map((row) => (
                    <tr key={row.row_number}>
                      <td data-label={k('columnRow')}>{row.row_number}</td>
                      <td data-label={k('columnReference')} className="mono">
                        {row.reference || '—'}
                      </td>
                      <td data-label={k('columnOutcome')}>
                        <StatusBadge
                          tone={row.outcome === 'created' ? 'success' : 'neutral'}
                          value={row.outcome}
                          label={k(`result.${row.outcome}`)}
                        />
                        <div className="meta">{row.reason_code || ''}</div>
                      </td>
                      <td data-label={k('columnRecord')}>
                        {row.record_id && !isLegacy ? (
                          <Link to={`/shipments/${row.record_id}`}>{row.record_label}</Link>
                        ) : (
                          <span className="meta">{row.record_label || '—'}</span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
          <div className="import__actions">
            <Button variant="secondary" onClick={startOver}>
              {k('importAnother')}
            </Button>
          </div>
        </>
      )}

      {!report && !result && fields.data && (
        <Card title={k('fieldsTitle')}>
          <ul className="reports__notes">
            {fields.data.notes.map((note) => (
              <li key={note}>{note}</li>
            ))}
          </ul>
          <p className="meta">
            {k('limits')
              .replace('{rows}', formatNumber(fields.data.limits.max_rows))
              .replace('{mib}', String(fields.data.limits.max_file_bytes / (1024 * 1024)))}
          </p>
          <div className="table-wrap">
            <table className="table table--stacked">
              <caption className="visually-hidden">{k('fieldsTitle')}</caption>
              <thead>
                <tr>
                  <th scope="col">{k('columnField')}</th>
                  <th scope="col">{k('columnHeaders')}</th>
                  <th scope="col">{k('columnRequired')}</th>
                </tr>
              </thead>
              <tbody>
                {fields.data.fields.map((item) => (
                  <tr key={item.field}>
                    <td data-label={k('columnField')} className="table__primary">
                      {item.field}
                    </td>
                    <td data-label={k('columnHeaders')}>
                      <span className="meta">{item.headers.join(', ')}</span>
                    </td>
                    <td data-label={k('columnRequired')}>
                      {item.required ? t('common.required') : t('common.optional')}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      {isLegacy && <LegacyBaselines />}
      {isLegacy && <LegacyRecords />}

      <Modal
        open={confirmOpen}
        onClose={() => setConfirmOpen(false)}
        title={k('confirmTitle')}
        footer={
          <>
            <Button variant="secondary" onClick={() => setConfirmOpen(false)}>
              {t('common.cancel')}
            </Button>
            <span className="spacer" />
            <Button variant="primary" onClick={() => commit.mutate()} disabled={commit.isPending}>
              {commit.isPending ? t('common.saving') : k('confirmButton')}
            </Button>
          </>
        }
      >
        <p>{k(`${config.i18n}.confirmBody`).replace('{count}', String(wouldImport))}</p>
        <ul className="reports__notes">
          <li>
            {k('confirmRefused').replace(
              '{count}',
              String((report?.counts.rejected ?? 0) + (report?.counts.duplicate ?? 0)),
            )}
          </li>
        </ul>
      </Modal>
    </>
  );
}

/* --- Legacy baselines --------------------------------------------------------------- */

function LegacyBaselines() {
  const t = useT();
  const k = (key) => t(`bulkImports.${key}`);
  const { can } = useSession();
  const queryClient = useQueryClient();
  const [voiding, setVoiding] = useState(null);
  const [reason, setReason] = useState('');

  const baselines = useQuery({
    queryKey: ['legacy-baselines'],
    queryFn: bulkImportsApi.baselines,
    enabled: can(P.IMPORT_PREVIEW),
  });

  const voidMutation = useMutation({
    mutationFn: () => bulkImportsApi.voidBaseline(voiding, reason.trim()),
    onSuccess: () => {
      setVoiding(null);
      setReason('');
      queryClient.invalidateQueries({ queryKey: ['legacy-baselines'] });
      queryClient.invalidateQueries({ queryKey: ['legacy-shipments'] });
    },
  });

  if (!can(P.IMPORT_PREVIEW)) return null;
  if (baselines.isError) return <ErrorState error={baselines.error} onRetry={baselines.refetch} />;
  if (!baselines.data || baselines.data.length === 0) return null;
  const canVoid = can(P.IMPORT_COMMIT) && can(P.SHIPMENT_WRITE);

  return (
    <Card title={k('baselinesTitle')} flush>
      <div className="table-wrap">
        <table className="table table--stacked">
          <caption className="visually-hidden">{k('baselinesTitle')}</caption>
          <thead>
            <tr>
              <th scope="col">{k('columnBatch')}</th>
              <th scope="col">{k('columnWhen')}</th>
              <th scope="col">{k('result.created')}</th>
              <th scope="col">{k('columnStatus')}</th>
              <th scope="col">
                <span className="visually-hidden">{k('voidButton')}</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {baselines.data.map((baseline) => (
              <tr key={baseline.batch_public_id}>
                <td data-label={k('columnBatch')} className="table__id">
                  {baseline.batch_public_id}
                  <div className="meta">{baseline.file_name || '—'}</div>
                </td>
                <td data-label={k('columnWhen')}>{formatDateTime(baseline.committed_at)}</td>
                <td data-label={k('result.created')}>{baseline.created_count}</td>
                <td data-label={k('columnStatus')}>
                  <StatusBadge
                    tone={baseline.status === 'voided' ? 'neutral' : 'success'}
                    value={baseline.status}
                    label={k(`status.${baseline.status}`)}
                  />
                  {baseline.void_reason && <div className="meta">{baseline.void_reason}</div>}
                </td>
                <td>
                  {canVoid && baseline.status === 'active' && (
                    <Button
                      variant="secondary"
                      onClick={() => {
                        voidMutation.reset();
                        setVoiding(baseline.batch_public_id);
                      }}
                    >
                      {k('voidButton')}
                      <span className="visually-hidden"> {baseline.batch_public_id}</span>
                    </Button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <Modal
        open={Boolean(voiding)}
        onClose={() => setVoiding(null)}
        title={k('voidTitle').replace('{batch}', voiding || '')}
        footer={
          <>
            <Button variant="secondary" onClick={() => setVoiding(null)}>
              {t('common.cancel')}
            </Button>
            <span className="spacer" />
            <Button
              variant="danger"
              onClick={() => voidMutation.mutate()}
              disabled={voidMutation.isPending || reason.trim().length < 5}
            >
              {k('voidConfirm')}
            </Button>
          </>
        }
      >
        <p>{k('voidBody')}</p>
        <Field id="void-reason" label={k('voidReason')} hint={k('voidReasonHint')} required>
          {(props) => (
            <TextArea
              {...props}
              value={reason}
              maxLength={400}
              required
              onChange={(event) => setReason(event.target.value)}
            />
          )}
        </Field>
        {voidMutation.error && (
          <Banner tone="danger" title={k('voidProblem')}>
            {voidMutation.error.message}
          </Banner>
        )}
      </Modal>
    </Card>
  );
}

/* --- Legacy records (staff read-only) -------------------------------------------------- */

function LegacyRecords() {
  const t = useT();
  const k = (key) => t(`bulkImports.${key}`);
  const { can } = useSession();
  const [search, setSearch] = useState('');
  const [includeVoided, setIncludeVoided] = useState(false);

  const records = useQuery({
    queryKey: ['legacy-shipments', search, includeVoided],
    queryFn: () =>
      bulkImportsApi.legacyShipments({
        search: search.trim() || undefined,
        include_voided: includeVoided || undefined,
        limit: 50,
      }),
    enabled: can(P.SHIPMENT_READ),
  });

  if (!can(P.SHIPMENT_READ)) return null;

  return (
    <Card title={k('recordsTitle')} flush>
      <div className="import__records-filters">
        <Field id="legacy-search" label={k('searchLabel')}>
          <TextInput
            id="legacy-search"
            type="search"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
          />
        </Field>
        <Checkbox
          id="legacy-include-voided"
          label={k('includeVoided')}
          checked={includeVoided}
          onChange={(event) => setIncludeVoided(event.target.checked)}
        />
      </div>
      <p className="meta import__records-note">{k('recordsNote')}</p>
      {records.isError && <ErrorState error={records.error} onRetry={records.refetch} />}
      {records.data && records.data.items.length === 0 && (
        <EmptyState title={k('noRecords')} body={k('noRecordsBody')} />
      )}
      {records.data && records.data.items.length > 0 && (
        <div className="table-wrap">
          <table className="table table--stacked">
            <caption className="visually-hidden">{k('recordsTitle')}</caption>
            <thead>
              <tr>
                <th scope="col">{k('columnReference')}</th>
                <th scope="col">{k('columnCustomer')}</th>
                <th scope="col">{k('columnBooked')}</th>
                <th scope="col">{k('columnFinal')}</th>
                <th scope="col">{k('columnRecipient')}</th>
              </tr>
            </thead>
            <tbody>
              {records.data.items.map((record) => (
                <tr key={record.id}>
                  <td data-label={k('columnReference')} className="table__primary">
                    <span className="mono">{record.legacy_reference}</span>{' '}
                    <StatusBadge tone="neutral" value="legacy" label={k('legacyBadge')} />
                    {record.is_voided && (
                      <StatusBadge tone="danger" value="voided" label={k('status.voided')} />
                    )}
                  </td>
                  <td data-label={k('columnCustomer')}>
                    <Link to={`/customers/${record.customer_id}`}>{record.customer_name}</Link>
                    <div className="meta mono">{record.customer_public_id}</div>
                  </td>
                  <td data-label={k('columnBooked')}>{record.booked_on}</td>
                  <td data-label={k('columnFinal')}>
                    {k(`finalStatus.${record.final_status}`)}
                    {record.completed_on && <div className="meta">{record.completed_on}</div>}
                  </td>
                  <td data-label={k('columnRecipient')}>
                    {[record.recipient_name, record.recipient_city].filter(Boolean).join(', ') ||
                      '—'}
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
