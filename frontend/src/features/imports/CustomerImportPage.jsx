/**
 * Guided CSV customer import (CRM.md section 13, Design.md section 5).
 *
 * Four steps, and the language changes between them on purpose. Steps 1 to 3 say
 * "preview", "found", "would"; step 4 says "import". Nothing an operator does before the
 * final button writes anything, and the page keeps saying so — an import screen that
 * feels the same before and after the commit is how people import a file twice.
 *
 * The file stays in the browser between preview and commit. The commit re-uploads it with
 * the digest the preview returned, and the server re-validates from scratch: it does not
 * trust anything this component concluded. That is also what makes cancellation free —
 * abandoning the flow leaves nothing behind on the server.
 */

import { useRef, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { importsApi } from '../../api/endpoints.js';
import { downloadUrl } from '../../api/client.js';
import { useT } from '../../i18n/index.jsx';
import { P, useSession } from '../../app/SessionContext.jsx';
import { PageHeader } from '../../components/layout/AppShell.jsx';
import {
  Banner,
  Button,
  Card,
  Modal,
  Select,
  StatusBadge,
} from '../../components/ui/index.jsx';
import { EmptyState, ErrorState, InlineSpinner } from '../../components/state/index.jsx';
import { formatDateTime, formatNumber } from '../../utils/format.js';
import { ImportKindNav } from './ImportKindNav.jsx';
import './imports.css';

const STEP_SELECT = 'select';
const STEP_REVIEW = 'review';
const STEP_DONE = 'done';

const CLASSIFICATION_TONE = {
  new: 'success',
  exact_match: 'neutral',
  duplicate_review: 'warning',
  rejected: 'danger',
};

export function CustomerImportPage() {
  const t = useT();
  const { can } = useSession();
  const queryClient = useQueryClient();
  const fileInput = useRef(null);

  const [step, setStep] = useState(STEP_SELECT);
  const [file, setFile] = useState(null);
  const [preview, setPreview] = useState(null);
  const [decisions, setDecisions] = useState({});
  const [conflictPolicy, setConflictPolicy] = useState('skip');
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [result, setResult] = useState(null);

  const fields = useQuery({ queryKey: ['import-fields'], queryFn: importsApi.fields });
  const batches = useQuery({
    queryKey: ['import-batches'],
    // Customer batches only: shipment and legacy batches have their own pages (RC-UAT-21).
    queryFn: () => importsApi.batches({ limit: 5, kind: 'customers' }),
  });

  const previewMutation = useMutation({
    mutationFn: (selected) => importsApi.preview(selected),
    onSuccess: (data) => {
      setPreview(data);
      setDecisions({});
      setStep(STEP_REVIEW);
    },
  });

  const commitMutation = useMutation({
    mutationFn: () =>
      importsApi.commit(file, {
        contentSha256: preview.content_sha256,
        conflictPolicy,
        decisions,
      }),
    onSuccess: (data) => {
      setResult(data);
      setStep(STEP_DONE);
      setConfirmOpen(false);
      queryClient.invalidateQueries({ queryKey: ['customers'] });
      queryClient.invalidateQueries({ queryKey: ['import-batches'] });
    },
  });

  function chooseFile(event) {
    const selected = event.target.files?.[0];
    if (!selected) return;
    setFile(selected);
    setResult(null);
    previewMutation.mutate(selected);
  }

  /** Cancelling before the commit is free, and the page says so. */
  function startOver() {
    setStep(STEP_SELECT);
    setFile(null);
    setPreview(null);
    setDecisions({});
    setResult(null);
    previewMutation.reset();
    commitMutation.reset();
    if (fileInput.current) fileInput.current.value = '';
  }

  const duplicateRows =
    preview?.rows.filter((row) => row.classification === 'duplicate_review') ?? [];
  const decidedToCreate = Object.values(decisions).filter((value) => value === 'create').length;
  const wouldCreate = (preview?.counts.new ?? 0) + decidedToCreate;
  // No duplicate starts out decided (UAT-XX-05). "Skip" is a decision like "create", and
  // the import waits until every held row has one; the server refuses it otherwise too.
  const undecidedCount = duplicateRows.filter((row) => !decisions[row.row_number]).length;
  // A file whose every held row was decided "Skip" creates nobody, and that is a finished
  // import, not a dead end (UAT round 4): the batch records the decisions. Only a file with
  // nothing at all to record (no new row, no held row, no earlier-import match) stays shut.
  const hasRowsToRecord =
    wouldCreate > 0 || duplicateRows.length > 0 || (preview?.counts.exact_match ?? 0) > 0;

  function decide(rowNumber, value) {
    setDecisions((current) => {
      const next = { ...current };
      if (value) next[rowNumber] = value;
      else delete next[rowNumber];
      return next;
    });
  }

  return (
    <>
      <PageHeader
        title={t('imports.title')}
        subtitle={t('imports.subtitle')}
        breadcrumb={<Link to="/customers">{t('nav.customers')}</Link>}
        actions={
          can(P.IMPORT_TEMPLATE) ? (
            <Button
              variant="secondary"
              onClick={() => {
                window.location.href = downloadUrl('/imports/customers/template.csv');
              }}
            >
              {t('imports.downloadTemplate')}
            </Button>
          ) : null
        }
      />
      <ImportKindNav />

      <ol className="import__steps" aria-label={t('imports.stepsLabel')}>
        <li aria-current={step === STEP_SELECT ? 'step' : undefined}>
          <span className="import__step-number">1</span>
          {t('imports.step1')}
        </li>
        <li aria-current={step === STEP_REVIEW ? 'step' : undefined}>
          <span className="import__step-number">2</span>
          {t('imports.step2')}
        </li>
        <li aria-current={step === STEP_REVIEW && duplicateRows.length > 0 ? 'step' : undefined}>
          <span className="import__step-number">3</span>
          {t('imports.step3')}
        </li>
        <li aria-current={step === STEP_DONE ? 'step' : undefined}>
          <span className="import__step-number">4</span>
          {t('imports.step4')}
        </li>
      </ol>

      {/* --- Step 1: choose a file ------------------------------------- */}
      {step === STEP_SELECT && (
        <>
          <Card title={t('imports.chooseFile')}>
            <p>{t('imports.chooseFileBody')}</p>
            <label className="import__file">
              <span className="visually-hidden">{t('imports.fileInputLabel')}</span>
              <input
                ref={fileInput}
                type="file"
                accept=".csv,text/csv"
                onChange={chooseFile}
                disabled={previewMutation.isPending}
              />
            </label>
            {previewMutation.isPending && <InlineSpinner label={t('imports.reading')} />}
            {previewMutation.error && (
              <Banner tone="danger" title={t('imports.fileProblem')}>
                {previewMutation.error.message}
              </Banner>
            )}
          </Card>

          {fields.data && (
            <Card title={t('imports.fieldsTitle')}>
              <ul className="reports__notes">
                {fields.data.notes.map((note) => (
                  <li key={note}>{note}</li>
                ))}
              </ul>
              <div className="table-wrap">
                <table className="table table--stacked">
                  <caption className="visually-hidden">{t('imports.fieldsTitle')}</caption>
                  <thead>
                    <tr>
                      <th scope="col">{t('imports.columnField')}</th>
                      <th scope="col">{t('imports.columnHeaders')}</th>
                      <th scope="col">{t('imports.columnRequired')}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {fields.data.fields.map((item) => (
                      <tr key={item.field}>
                        <td data-label={t('imports.columnField')} className="table__primary">
                          {item.field}
                        </td>
                        <td data-label={t('imports.columnHeaders')}>
                          <span className="meta">{item.headers.join(', ')}</span>
                          {item.allowed_values && (
                            <div className="meta">
                              {t('imports.allowedValues')}: {item.allowed_values.join(', ')}
                            </div>
                          )}
                        </td>
                        <td data-label={t('imports.columnRequired')}>
                          {item.required ? t('common.required') : t('common.optional')}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Card>
          )}
        </>
      )}

      {/* --- Steps 2 and 3: review -------------------------------------- */}
      {step === STEP_REVIEW && preview && (
        <>
          <Banner tone="info" title={t('imports.previewOnly')}>
            <ul className="reports__notes">
              {preview.notes.map((note) => (
                <li key={note}>{note}</li>
              ))}
            </ul>
          </Banner>

          <Card title={t('imports.mappingTitle')}>
            <p className="meta">{t('imports.mappingBody')}</p>
            <ul className="import__mapping">
              {preview.raw_headers.map((raw, index) => {
                const mapped = preview.headers.includes(raw) || !preview.unmapped_headers.includes(raw);
                return (
                  <li key={`${raw}-${index}`} className={mapped ? '' : 'import__mapping--unmapped'}>
                    <code>{raw || t('imports.blankColumn')}</code>
                    <span aria-hidden="true"> → </span>
                    <span>{mapped ? t('imports.mapped') : t('imports.ignored')}</span>
                  </li>
                );
              })}
            </ul>
            {preview.unmapped_headers.length > 0 && (
              <Banner tone="warning" title={t('imports.unmappedTitle')}>
                {t('imports.unmappedBody')}: {preview.unmapped_headers.join(', ')}
              </Banner>
            )}
          </Card>

          <Card title={t('imports.whatWouldHappen')}>
            <dl className="report__summary">
              {['new', 'exact_match', 'duplicate_review', 'rejected'].map((key) => (
                <div key={key}>
                  <dt>{t(`imports.count.${key}`)}</dt>
                  <dd>{formatNumber(preview.counts[key] ?? 0)}</dd>
                </div>
              ))}
            </dl>
            <p>
              {t('imports.wouldCreate').replace('{count}', String(wouldCreate))}
            </p>
          </Card>

          {duplicateRows.length > 0 && (
            <Card title={t('imports.duplicatesTitle')}>
              <Banner tone="warning" title={t('imports.duplicatesNeverMerged')}>
                {t('imports.duplicatesBody')}
              </Banner>
              <div className="table-wrap">
                <table className="table table--stacked">
                  <caption className="visually-hidden">{t('imports.duplicatesTitle')}</caption>
                  <thead>
                    <tr>
                      <th scope="col">{t('imports.columnRow')}</th>
                      <th scope="col">{t('imports.columnUploaded')}</th>
                      <th scope="col">{t('imports.columnExisting')}</th>
                      <th scope="col">{t('imports.columnDecision')}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {duplicateRows.map((row) => (
                      <tr key={row.row_number}>
                        <td data-label={t('imports.columnRow')}>{row.row_number}</td>
                        <td data-label={t('imports.columnUploaded')} className="table__primary">
                          {row.values.full_name}
                          <div className="meta">
                            {[row.values.email, row.values.phone].filter(Boolean).join(' · ')}
                          </div>
                        </td>
                        <td data-label={t('imports.columnExisting')}>
                          {row.duplicate_candidates.map((candidate) => (
                            <div key={candidate.customer_id}>
                              <Link to={`/customers/${candidate.customer_id}`}>
                                {candidate.full_name}
                              </Link>
                              <div className="meta mono">{candidate.public_id}</div>
                              <div className="meta">
                                {t('imports.matchedOn')}: {candidate.matched_on.join(', ')}
                              </div>
                            </div>
                          ))}
                        </td>
                        <td data-label={t('imports.columnDecision')}>
                          <label className="visually-hidden" htmlFor={`decision-${row.row_number}`}>
                            {t('imports.columnDecision')} {row.row_number}
                          </label>
                          <Select
                            id={`decision-${row.row_number}`}
                            value={decisions[row.row_number] || ''}
                            onChange={(event) => decide(row.row_number, event.target.value)}
                            required
                            aria-invalid={decisions[row.row_number] ? undefined : 'true'}
                            placeholder={t('imports.decisionChoose')}
                            options={[
                              { value: 'skip', label: t('imports.decisionSkip') },
                              { value: 'create', label: t('imports.decisionCreate') },
                            ]}
                          />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Card>
          )}

          <Card title={t('imports.rowsTitle')}>
            <div className="table-wrap">
              <table className="table table--stacked">
                <caption className="visually-hidden">{t('imports.rowsTitle')}</caption>
                <thead>
                  <tr>
                    <th scope="col">{t('imports.columnRow')}</th>
                    <th scope="col">{t('imports.columnName')}</th>
                    <th scope="col">{t('imports.columnClassification')}</th>
                    <th scope="col">{t('imports.columnIssues')}</th>
                  </tr>
                </thead>
                <tbody>
                  {preview.rows.map((row) => (
                    <tr key={row.row_number}>
                      <td data-label={t('imports.columnRow')}>{row.row_number}</td>
                      <td data-label={t('imports.columnName')} className="table__primary">
                        {row.values.full_name || <span className="report__unknown">—</span>}
                        <div className="meta">{row.values.email || row.values.phone || ''}</div>
                      </td>
                      <td data-label={t('imports.columnClassification')}>
                        <StatusBadge
                          tone={CLASSIFICATION_TONE[row.classification]}
                          value={row.classification}
                          label={t(`imports.count.${row.classification}`)}
                        />
                        {row.matched_customer_public_id && (
                          <div className="meta mono">{row.matched_customer_public_id}</div>
                        )}
                      </td>
                      <td data-label={t('imports.columnIssues')}>
                        {row.issues.length === 0 ? (
                          <span className="meta">—</span>
                        ) : (
                          <ul className="import__issues">
                            {row.issues.map((issue) => (
                              <li key={`${issue.field_name}-${issue.code}`}>{issue.message}</li>
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

          <Card title={t('imports.conflictTitle')}>
            <label htmlFor="conflict-policy">{t('imports.conflictLabel')}</label>
            <Select
              id="conflict-policy"
              value={conflictPolicy}
              onChange={(event) => setConflictPolicy(event.target.value)}
              options={[
                { value: 'skip', label: t('imports.policySkip') },
                { value: 'fill_blanks', label: t('imports.policyFillBlanks') },
              ]}
              style={{ maxWidth: 420 }}
            />
            <p className="meta">{t('imports.conflictNeverOverwrites')}</p>
          </Card>

          {commitMutation.error && (
            <Banner tone="danger" title={t('imports.commitProblem')}>
              {commitMutation.error.message}
            </Banner>
          )}

          <div className="import__actions">
            <Button variant="secondary" onClick={startOver}>
              {t('imports.cancel')}
            </Button>
            <span className="spacer" />
            {can(P.IMPORT_COMMIT) ? (
              <Button
                variant="primary"
                onClick={() => setConfirmOpen(true)}
                disabled={commitMutation.isPending || !hasRowsToRecord || undecidedCount > 0}
                aria-describedby={undecidedCount > 0 ? 'import-undecided-hint' : undefined}
              >
                {wouldCreate === 0
                  ? t('imports.finishWithoutCreating')
                  : t('imports.importNow').replace('{count}', String(wouldCreate))}
              </Button>
            ) : (
              <Banner tone="neutral">{t('imports.noCommitPermission')}</Banner>
            )}
          </div>
          {/* Always rendered, so the live region exists before its text changes and a
              screen reader hears the count fall as each row is decided. */}
          <p id="import-undecided-hint" className="field__hint" aria-live="polite">
            {undecidedCount > 0
              ? t('imports.undecidedHint').replace('{count}', String(undecidedCount))
              : ''}
          </p>
          <p className="meta import__cancel-note">{t('imports.cancelIsFree')}</p>
        </>
      )}

      {/* --- Step 4: the summary ---------------------------------------- */}
      {step === STEP_DONE && result && (
        <>
          <Banner tone="success" title={t('imports.doneTitle')}>
            {t('imports.doneBody').replace('{batch}', result.batch_public_id)}
          </Banner>

          <Card title={t('imports.summaryTitle')}>
            <dl className="report__summary">
              {['created', 'matched', 'skipped', 'rejected'].map((key) => (
                <div key={key}>
                  <dt>{t(`imports.result.${key}`)}</dt>
                  <dd>{formatNumber(result[key])}</dd>
                </div>
              ))}
            </dl>
            <p className="meta">{t('imports.summaryDurable').replace('{batch}', result.batch_public_id)}</p>
          </Card>

          <Card title={t('imports.rowsTitle')}>
            <div className="table-wrap">
              <table className="table table--stacked">
                <caption className="visually-hidden">{t('imports.rowsTitle')}</caption>
                <thead>
                  <tr>
                    <th scope="col">{t('imports.columnRow')}</th>
                    <th scope="col">{t('imports.columnOutcome')}</th>
                    <th scope="col">{t('imports.columnReason')}</th>
                    <th scope="col">{t('imports.columnCustomer')}</th>
                  </tr>
                </thead>
                <tbody>
                  {result.rows.map((row) => (
                    <tr key={row.row_number}>
                      <td data-label={t('imports.columnRow')}>{row.row_number}</td>
                      <td data-label={t('imports.columnOutcome')}>
                        <StatusBadge
                          tone={row.outcome === 'created' ? 'success' : 'neutral'}
                          value={row.outcome}
                          label={t(`imports.result.${row.outcome}`)}
                        />
                      </td>
                      <td data-label={t('imports.columnReason')}>
                        <span className="meta">{row.reason_code || '—'}</span>
                      </td>
                      <td data-label={t('imports.columnCustomer')}>
                        {row.customer_id ? (
                          <Link to={`/customers/${row.customer_id}`}>
                            {row.customer_public_id}
                          </Link>
                        ) : (
                          <span className="meta">—</span>
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
              {t('imports.importAnother')}
            </Button>
            <span className="spacer" />
            <Link to="/customers" className="btn btn--primary">
              {t('imports.viewCustomers')}
            </Link>
          </div>
        </>
      )}

      {/* --- Recent imports ---------------------------------------------- */}
      {batches.data && batches.data.items.length > 0 && step !== STEP_REVIEW && (
        <Card title={t('imports.recentTitle')} flush>
          <div className="table-wrap">
            <table className="table table--stacked">
              <caption className="visually-hidden">{t('imports.recentTitle')}</caption>
              <thead>
                <tr>
                  <th scope="col">{t('imports.columnBatch')}</th>
                  <th scope="col">{t('imports.columnWhen')}</th>
                  <th scope="col">{t('imports.result.created')}</th>
                  <th scope="col">{t('imports.result.matched')}</th>
                  <th scope="col">{t('imports.result.skipped')}</th>
                  <th scope="col">{t('imports.result.rejected')}</th>
                </tr>
              </thead>
              <tbody>
                {batches.data.items.map((batch) => (
                  <tr key={batch.public_id}>
                    <td data-label={t('imports.columnBatch')} className="table__id">
                      {batch.public_id}
                      <div className="meta">{batch.file_name || '—'}</div>
                    </td>
                    <td data-label={t('imports.columnWhen')}>
                      {formatDateTime(batch.committed_at)}
                    </td>
                    <td data-label={t('imports.result.created')}>{batch.created_count}</td>
                    <td data-label={t('imports.result.matched')}>{batch.matched_count}</td>
                    <td data-label={t('imports.result.skipped')}>{batch.skipped_count}</td>
                    <td data-label={t('imports.result.rejected')}>{batch.rejected_count}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      {batches.isError && <ErrorState error={batches.error} onRetry={batches.refetch} />}

      {step === STEP_SELECT && batches.data && batches.data.items.length === 0 && (
        <Card>
          <EmptyState title={t('imports.noneYet')} body={t('imports.noneYetBody')} />
        </Card>
      )}

      {/* Explicit confirmation. The wording changes here, and only here, from "would" to
          "will": this is the first and only irreversible step. */}
      <Modal
        open={confirmOpen}
        onClose={() => setConfirmOpen(false)}
        title={t('imports.confirmTitle')}
        footer={
          <>
            <Button variant="secondary" onClick={() => setConfirmOpen(false)}>
              {t('common.cancel')}
            </Button>
            <span className="spacer" />
            <Button
              variant="primary"
              onClick={() => commitMutation.mutate()}
              disabled={commitMutation.isPending}
            >
              {commitMutation.isPending ? t('common.saving') : t('imports.confirmButton')}
            </Button>
          </>
        }
      >
        <p>
          {wouldCreate === 0
            ? t('imports.confirmBodyNone')
            : t('imports.confirmBody').replace('{count}', String(wouldCreate))}
        </p>
        <ul className="reports__notes">
          <li>{t('imports.confirmSkipped').replace(
            '{count}',
            String((preview?.counts.duplicate_review ?? 0) - decidedToCreate),
          )}</li>
          <li>{t('imports.confirmRejected').replace(
            '{count}',
            String(preview?.counts.rejected ?? 0),
          )}</li>
          <li>{t('imports.confirmPolicy')}: {t(`imports.policy${conflictPolicy === 'skip' ? 'Skip' : 'FillBlanks'}`)}</li>
        </ul>
      </Modal>
    </>
  );
}
