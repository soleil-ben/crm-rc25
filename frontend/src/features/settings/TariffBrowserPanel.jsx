/**
 * Settings → Tariffs (Phase 14): a read-only tariff browser.
 *
 * Every imported version with its status; for one version its import warnings and the
 * owner-confirmed price steps (RC-20), its air products and their rate
 * brackets, the accessorials and the beyond-area rates; the exchange-rate history the worker
 * recorded. Anyone with `tariff:read` (Operations, Admin) reads it. An administrator with
 * `tariff:manage` may import a workbook by hand: the result is a **draft**, which goes through
 * the same approver review as an emailed one (13H, OD-76) -- its diff, then Approve and
 * activate or Reject, offered only to a designated approver. The server stays the authority.
 *
 * Air only (OD-49): sea products and sea-only accessorials are not listed. Internal: vendor
 * prices in VND and the bank's rates are on this screen; it is staff-only.
 */

import { useEffect, useRef, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { tariffsApi } from '../../api/endpoints.js';
import { P, useSession } from '../../app/SessionContext.jsx';
import { useI18n, useT } from '../../i18n/index.jsx';
import { Banner, Button, Card, Field, StatusBadge, TextInput } from '../../components/ui/index.jsx';
import { EmptyState, ErrorState, SkeletonRows } from '../../components/state/index.jsx';
import { formatDate, formatDateTime } from '../../utils/format.js';
import { formatKg, formatVnd } from '../workspace/workspaceFormat.js';
import { VersionReview, useServerText } from './TariffUpdatesPanel.jsx';

const VERSION_TONE = { draft: 'info', active: 'success', superseded: 'neutral', rejected: 'danger' };

/** A rejected draft stays `draft` (13H); the browser says what it really is. */
export function versionState(version) {
  return version.status === 'draft' && version.review_decision === 'rejected' ? 'rejected' : version.status;
}

function number(value, digits = 2) {
  if (value === null || value === undefined || value === '') return '—';
  return Number(value).toLocaleString('en-CA', { maximumFractionDigits: digits });
}

function isAirAccessorial(row) {
  const modes = String(row.applies_to_modes || '')
    .split(',')
    .map((mode) => mode.trim())
    .filter(Boolean);
  return modes.length === 0 || modes.includes('air');
}

/** The server's own limit (`settings.tariff_import_max_bytes`, 4 MB); it checks again. */
export const MAX_WORKBOOK_BYTES = 4 * 1024 * 1024;
const REPORT_ROWS = 20;

/** What the importer reported about the workbook: counts and its warnings (anomalies). */
function ImportReport({ version }) {
  const t = useT();
  const { locale } = useI18n();
  const report = version.report || {};
  const anomalies = Array.isArray(report.anomalies) ? report.anomalies : [];
  const counts = version.counts || {};
  return (
    <div className="stack">
      <ul className="meta" aria-label={t('tariffBrowser.reportCounts')}>
        {Object.entries(counts).map(([key, count]) => (
          <li key={key}>
            {t(`tariffBrowser.countLabels.${key}`, key)}: {count}
          </li>
        ))}
      </ul>
      {anomalies.length === 0 ? (
        <p className="meta">{t('tariffBrowser.reportClean')}</p>
      ) : (
        <Banner tone="warning" title={t('tariffBrowser.reportWarnings').replace('{count}', String(anomalies.length))}>
          {locale === 'vi' && <p className="meta">{t('tariffBrowser.reportInEnglish')}</p>}
          <ul aria-label={t('tariffBrowser.reportWarningsList')}>
            {anomalies.slice(0, REPORT_ROWS).map((row, index) => (
              // Report rows have no id; their order is the importer's.
              <li key={`${row.code}-${index}`} lang="en">
                {row.message}
                {row.sheet ? ` (${row.sheet}${row.cell ? `!${row.cell}` : ''})` : ''}
              </li>
            ))}
          </ul>
          {anomalies.length > REPORT_ROWS && (
            <p className="meta">{t('tariffBrowser.reportMore').replace('{count}', String(anomalies.length - REPORT_ROWS))}</p>
          )}
        </Banner>
      )}
    </div>
  );
}

function ImportForm({ onImported }) {
  const t = useT();
  const serverText = useServerText();
  const queryClient = useQueryClient();
  const fileRef = useRef(null);
  const [file, setFile] = useState(null);
  const [effectiveFrom, setEffectiveFrom] = useState('');
  const [label, setLabel] = useState('');
  const [errors, setErrors] = useState({});
  const resultRef = useRef(null);
  const imported = useMutation({
    mutationFn: () => tariffsApi.importWorkbook(file, { effectiveFrom, label: label.trim() }),
    onSuccess: (version) => {
      queryClient.invalidateQueries({ queryKey: ['tariff-versions'] });
      // Phase 15: a new draft changes the approver badge.
      queryClient.invalidateQueries({ queryKey: ['tariff-intake', 'pending-count'] });
      setFile(null);
      setLabel('');
      if (fileRef.current) fileRef.current.value = '';
      onImported(version);
    },
  });

  useEffect(() => {
    if (imported.isSuccess) resultRef.current?.focus();
  }, [imported.isSuccess]);

  return (
    <Card title={t('tariffBrowser.importTitle')} headingLevel="h3">
      <p className="meta">{t('tariffBrowser.importIntro')}</p>
      {imported.isSuccess && (
        <div ref={resultRef} tabIndex={-1}>
          <Banner tone="info">
            {t('tariffBrowser.imported').replace('{version}', imported.data.public_id)}
          </Banner>
          <ImportReport version={imported.data} />
        </div>
      )}
      {imported.error && imported.error.field !== 'file' && (
        <Banner tone="danger">{serverText(imported.error)}</Banner>
      )}
      <form
        noValidate
        onSubmit={(event) => {
          event.preventDefault();
          const found = {};
          if (!file) found.file = t('tariffBrowser.errors.file');
          else if (file.size > MAX_WORKBOOK_BYTES) found.file = t('tariffBrowser.errors.tooLarge');
          if (!effectiveFrom) found.effective_from = t('tariffBrowser.errors.effectiveFrom');
          setErrors(found);
          if (found.file) fileRef.current?.focus();
          else if (found.effective_from) document.getElementById('tariff-import-effective')?.focus();
          if (Object.keys(found).length === 0) imported.mutate();
        }}
      >
        <div className="form-grid">
          <Field
            id="tariff-import-file"
            label={t('tariffBrowser.workbook')}
            hint={t('tariffBrowser.workbookHint')}
            error={errors.file || (imported.error?.field === 'file' ? serverText(imported.error) : null)}
            required
          >
            {(props) => (
              <input
                {...props}
                ref={fileRef}
                type="file"
                accept=".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                onChange={(event) => {
                  const chosen = event.target.files?.[0] ?? null;
                  setFile(chosen);
                  setErrors((current) => ({
                    ...current,
                    file:
                      chosen && chosen.size > MAX_WORKBOOK_BYTES ? t('tariffBrowser.errors.tooLarge') : undefined,
                  }));
                }}
              />
            )}
          </Field>
          <Field
            id="tariff-import-effective"
            label={t('tariffBrowser.effectiveFrom')}
            error={errors.effective_from}
            required
          >
            {(props) => (
              <TextInput
                {...props}
                type="date"
                value={effectiveFrom}
                onChange={(event) => setEffectiveFrom(event.target.value)}
              />
            )}
          </Field>
          <Field label={t('tariffBrowser.label')} hint={t('common.optional')}>
            {(props) => (
              <TextInput {...props} maxLength={120} value={label} onChange={(event) => setLabel(event.target.value)} />
            )}
          </Field>
        </div>
        <Button type="submit" variant="primary" loading={imported.isPending}>
          {t('tariffBrowser.importButton')}
        </Button>
      </form>
    </Card>
  );
}

function Brackets({ versionId, product }) {
  const t = useT();
  const query = useQuery({
    queryKey: ['tariff-browser', versionId, 'product', product.id],
    queryFn: () => tariffsApi.product(versionId, product.id),
  });
  if (query.isLoading) return <SkeletonRows rows={3} />;
  if (query.error) return <ErrorState error={query.error} onRetry={query.refetch} />;
  const title = `${t('tariffBrowser.bracketsOf')} ${product.code} (${product.origin})`;
  return (
    <div className="table-wrap" tabIndex={0} role="region" aria-label={title}>
      <table className="table">
        <caption className="meta">{title}</caption>
        <thead>
          <tr>
            <th scope="col">{t('tariffBrowser.kind')}</th>
            <th scope="col">{t('tariffBrowser.zone')}</th>
            <th scope="col">{t('tariffBrowser.band')}</th>
            <th scope="col">{t('tariffBrowser.fromKg')}</th>
            <th scope="col">{t('tariffBrowser.toKg')}</th>
            <th scope="col">{t('tariffBrowser.priceVnd')}</th>
          </tr>
        </thead>
        <tbody>
          {query.data.brackets.map((row) => (
            <tr key={`${row.kind}-${row.zone}-${row.label}`}>
              <td>{row.kind}</td>
              <td>{row.zone}</td>
              <td>{row.label}</td>
              <td>{formatKg(row.weight_from_kg)}</td>
              <td>{formatKg(row.weight_to_kg)}</td>
              <td>{formatVnd(row.price_vnd)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** RC-20: rows per page of a version's import warnings. */
export const WARNINGS_PAGE = 25;

function fill(text, values) {
  return Object.entries(values).reduce((out, [key, value]) => out.replaceAll(`{${key}}`, String(value)), text);
}

function cellOf(row) {
  if (!row.sheet) return '';
  return row.cell ? `${row.sheet}!${row.cell}` : row.sheet;
}

/**
 * RC-20 (owner, 2026-10-23): every version's import warnings -- the count, the full list a
 * page at a time -- and, apart, the price steps the owner confirmed (DEC-0222), which are
 * not warnings and are not counted.
 */
function ImportWarnings({ version }) {
  const t = useT();
  const { locale } = useI18n();
  const [offset, setOffset] = useState(0);
  const query = useQuery({
    queryKey: ['tariff-browser', version.id, 'warnings', offset],
    queryFn: () => tariffsApi.warnings(version.id, { limit: WARNINGS_PAGE, offset }),
  });
  const data = query.data || {};
  const count = Number.isInteger(data.count) ? data.count : 0;
  const items = count > 0 && Array.isArray(data.items) ? data.items : [];
  const steps = Array.isArray(data.confirmed_price_steps) ? data.confirmed_price_steps : [];
  const byCode = data.counts_by_code && typeof data.counts_by_code === 'object' ? data.counts_by_code : {};
  const title = fill(t('tariffWarnings.title'), { count });
  const listName = fill(t('tariffWarnings.listLabel'), { version: version.public_id });
  const stepsTitle = fill(t('tariffWarnings.confirmedTitle'), { count: steps.length });
  const from = items.length ? offset + 1 : 0;
  const to = offset + items.length;

  return (
    <Card title={`${title} · ${version.public_id}`} headingLevel="h3">
      {query.isLoading ? (
        <SkeletonRows rows={3} />
      ) : query.error ? (
        <ErrorState error={query.error} onRetry={query.refetch} />
      ) : (
        <div className="stack">
          <p className="meta">{t('tariffWarnings.intro')}</p>
          {count === 0 ? (
            <p className="meta">{t('tariffWarnings.none')}</p>
          ) : (
            <>
              <ul className="meta" aria-label={t('tariffWarnings.byCode')}>
                {Object.entries(byCode).map(([code, n]) => (
                  <li key={code}>
                    <span className="mono">{code}</span>: {n}
                  </li>
                ))}
              </ul>
              {locale === 'vi' && <p className="meta">{t('tariffBrowser.reportInEnglish')}</p>}
              <ol start={from || 1} aria-label={listName}>
                {items.map((row, index) => (
                  // Report rows have no id; their order is the importer's.
                  <li key={`${offset + index}-${row.code}`} lang="en">
                    <span className="mono">{row.code}</span>
                    {cellOf(row) ? <span className="mono"> · {cellOf(row)}</span> : null} · {row.message}
                  </li>
                ))}
              </ol>
              <p className="meta" aria-live="polite">
                {fill(t('tariffWarnings.showing'), { from, to, count })}
              </p>
              {count > WARNINGS_PAGE && (
                <div className="row">
                  <Button
                    compact
                    variant="secondary"
                    disabled={offset === 0}
                    onClick={() => setOffset(Math.max(0, offset - WARNINGS_PAGE))}
                  >
                    {t('tariffWarnings.previous')}
                  </Button>
                  <Button
                    compact
                    variant="secondary"
                    disabled={offset + WARNINGS_PAGE >= count}
                    onClick={() => setOffset(offset + WARNINGS_PAGE)}
                  >
                    {t('tariffWarnings.next')}
                  </Button>
                </div>
              )}
            </>
          )}
          <h4>{stepsTitle}</h4>
          <p className="meta">{t('tariffWarnings.confirmedIntro')}</p>
          {steps.length === 0 ? (
            <p className="meta">{t('tariffBrowser.none')}</p>
          ) : (
            <ul aria-label={stepsTitle}>
              {steps.map((step) => (
                <li key={cellOf(step)}>
                  <span className="mono">{cellOf(step)}</span>
                  {step.product_code ? ` · ${step.product_code}` : ''}
                  {step.zone !== null && step.zone !== undefined ? ` · ${t('tariffBrowser.zone')} ${step.zone}` : ''}
                  {step.label ? ` · ${step.label}` : ''}
                  {step.price_vnd ? ` · ${formatVnd(step.price_vnd)}` : ''}
                  {' · '}
                  <StatusBadge tone="success" label={t('tariffWarnings.confirmed')} />
                  {step.reference && (
                    <span className="meta" lang="en">
                      {' '}
                      ({step.reference})
                    </span>
                  )}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </Card>
  );
}

function VersionDetail({ version, isApprover }) {
  const t = useT();
  const [product, setProduct] = useState(null);
  const products = useQuery({
    queryKey: ['tariff-browser', version.id, 'products'],
    queryFn: () => tariffsApi.products(version.id),
  });
  const accessorials = useQuery({
    queryKey: ['tariff-browser', version.id, 'accessorials'],
    queryFn: () => tariffsApi.accessorials(version.id),
  });
  const beyond = useQuery({
    queryKey: ['tariff-browser', version.id, 'beyond'],
    queryFn: () => tariffsApi.beyondRates(version.id),
  });
  const airProducts = (products.data ?? []).filter((row) => row.mode === 'air');
  const airAccessorials = (accessorials.data ?? []).filter(isAirAccessorial);
  const state = versionState(version);

  return (
    <>
      {state === 'draft' && (
        <VersionReview
          key={version.id}
          versionId={version.id}
          publicId={version.public_id}
          reviewable
          isApprover={isApprover}
          approverOnly
        />
      )}
      {state === 'rejected' && <Banner tone="neutral">{t('tariffIntake.outcome.rejected')}</Banner>}
      <ImportWarnings version={version} />
      <Card title={`${t('tariffBrowser.productsTitle')} · ${version.public_id}`} headingLevel="h3">
        <p className="meta">{t('tariffBrowser.airOnly')}</p>
        {products.isLoading ? (
          <SkeletonRows rows={3} />
        ) : products.error ? (
          <ErrorState error={products.error} onRetry={products.refetch} />
        ) : airProducts.length === 0 ? (
          <p className="meta">{t('tariffBrowser.noProducts')}</p>
        ) : (
          <div className="table-wrap" tabIndex={0} role="region" aria-label={t('tariffBrowser.productsTitle')}>
            <table className="table">
              <thead>
                <tr>
                  <th scope="col">{t('tariffBrowser.code')}</th>
                  <th scope="col">{t('tariffBrowser.origin')}</th>
                  <th scope="col">{t('tariffBrowser.lastMile')}</th>
                  <th scope="col">{t('tariffBrowser.dimDivisor')}</th>
                  <th scope="col">{t('tariffBrowser.minChargeable')}</th>
                  <th scope="col">{t('tariffBrowser.transit')}</th>
                  <th scope="col">
                    <span className="visually-hidden">{t('tariffBrowser.actions')}</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {airProducts.map((row) => (
                  <tr key={row.id}>
                    <td className="mono">{row.code}</td>
                    <td>{row.origin}</td>
                    <td>{row.last_mile}</td>
                    <td>{row.dim_divisor}</td>
                    <td>{formatKg(row.min_chargeable_kg)}</td>
                    <td>{row.transit_text || '—'}</td>
                    <td>
                      <Button
                        compact
                        variant="tertiary"
                        aria-pressed={product?.id === row.id}
                        aria-label={`${t('tariffBrowser.showBrackets')} ${row.code} (${row.origin})`}
                        onClick={() => setProduct(product?.id === row.id ? null : row)}
                      >
                        {t('tariffBrowser.showBrackets')}
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {product && <Brackets versionId={version.id} product={product} />}
      </Card>
      <Card title={t('tariffBrowser.accessorialsTitle')} headingLevel="h3">
        {accessorials.isLoading ? (
          <SkeletonRows rows={2} />
        ) : accessorials.error ? (
          <ErrorState error={accessorials.error} onRetry={accessorials.refetch} />
        ) : airAccessorials.length === 0 ? (
          <p className="meta">{t('tariffBrowser.none')}</p>
        ) : (
          <div className="table-wrap" tabIndex={0} role="region" aria-label={t('tariffBrowser.accessorialsTitle')}>
            <table className="table">
              <thead>
                <tr>
                  <th scope="col">{t('tariffBrowser.description')}</th>
                  <th scope="col">{t('tariffBrowser.amount')}</th>
                  <th scope="col">{t('tariffBrowser.basis')}</th>
                </tr>
              </thead>
              <tbody>
                {airAccessorials.map((row) => (
                  <tr key={row.key}>
                    <td>{row.description}</td>
                    <td>
                      {number(row.amount)} {row.currency}
                    </td>
                    <td>{row.basis}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
      <Card title={t('tariffBrowser.beyondTitle')} headingLevel="h3">
        {beyond.isLoading ? (
          <SkeletonRows rows={2} />
        ) : beyond.error ? (
          <ErrorState error={beyond.error} onRetry={beyond.refetch} />
        ) : (beyond.data ?? []).length === 0 ? (
          <p className="meta">{t('tariffBrowser.none')}</p>
        ) : (
          <div className="table-wrap" tabIndex={0} role="region" aria-label={t('tariffBrowser.beyondTitle')}>
            <table className="table">
              <thead>
                <tr>
                  <th scope="col">{t('tariffBrowser.beyondCode')}</th>
                  <th scope="col">{t('tariffBrowser.status')}</th>
                  <th scope="col">{t('tariffBrowser.baseCad')}</th>
                  <th scope="col">{t('tariffBrowser.perLbCad')}</th>
                </tr>
              </thead>
              <tbody>
                {beyond.data.map((row) => (
                  <tr key={row.beyond_code}>
                    <td className="mono">{row.beyond_code}</td>
                    <td>{row.status}</td>
                    <td>{number(row.base_cad)}</td>
                    <td>{number(row.per_lb_cad)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </>
  );
}

function FxHistory() {
  const t = useT();
  const query = useQuery({ queryKey: ['fx-history'], queryFn: () => tariffsApi.fxHistory(30) });
  return (
    <Card title={t('tariffBrowser.fxTitle')} headingLevel="h3">
      <p className="meta">{t('tariffBrowser.fxIntro')}</p>
      {query.isLoading ? (
        <SkeletonRows rows={3} />
      ) : query.error ? (
        <ErrorState error={query.error} onRetry={query.refetch} />
      ) : query.data.snapshots.length === 0 ? (
        <p className="meta">{t('tariffBrowser.fxNone')}</p>
      ) : (
        <div className="table-wrap" tabIndex={0} role="region" aria-label={t('tariffBrowser.fxTitle')}>
          <table className="table">
            <thead>
              <tr>
                <th scope="col">{t('tariffBrowser.retrievedAt')}</th>
                <th scope="col">{t('tariffBrowser.publishedAt')}</th>
                <th scope="col">{t('tariffBrowser.cashBuy')}</th>
                <th scope="col">{t('tariffBrowser.transferBuy')}</th>
                <th scope="col">{t('tariffBrowser.sell')}</th>
              </tr>
            </thead>
            <tbody>
              {query.data.snapshots.map((row) => (
                <tr key={row.id}>
                  <td>
                    {formatDateTime(row.retrieved_at)}
                    {row.is_demo && (
                      <>
                        {' '}
                        <StatusBadge tone="warning" label={t('tariffBrowser.demoRate')} />
                      </>
                    )}
                  </td>
                  <td>{row.bank_published_raw || formatDateTime(row.bank_published_at)}</td>
                  <td>{formatVnd(row.cash_buy_vnd)}</td>
                  <td>{formatVnd(row.transfer_buy_vnd)}</td>
                  <td>{formatVnd(row.sell_vnd)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {query.data?.attempts?.length > 0 && (
        <>
          <h4>{t('tariffBrowser.attemptsTitle')}</h4>
          <ul className="meta" aria-label={t('tariffBrowser.attemptsTitle')}>
            {query.data.attempts.slice(0, 10).map((row) => (
              <li key={row.id}>
                {formatDateTime(row.attempted_at)} · {row.outcome}
                {row.error_summary ? ` · ${row.error_summary}` : ''}
              </li>
            ))}
          </ul>
        </>
      )}
    </Card>
  );
}

export function TariffBrowserPanel() {
  const t = useT();
  const { can } = useSession();
  const [selectedId, setSelectedId] = useState(null);
  const detailRef = useRef(null);
  const canImport = can(P.TARIFF_MANAGE);
  const versions = useQuery({ queryKey: ['tariff-versions'], queryFn: tariffsApi.versions });
  // Whether this user is a designated approver: the intake list says so (tariff:manage).
  const approver = useQuery({
    queryKey: ['tariff-intake', 'approver'],
    queryFn: () => tariffsApi.intake({ limit: 1 }),
    enabled: canImport,
  });
  const isApprover = Boolean(approver.data?.viewer_is_approver);
  const rows = versions.data?.items ?? [];
  const selected =
    rows.find((row) => row.id === selectedId) || rows.find((row) => row.status === 'active') || null;

  function choose(id) {
    setSelectedId(id);
    setTimeout(() => detailRef.current?.focus(), 0);
  }

  return (
    <>
      <Card title={t('tariffBrowser.versionsTitle')}>
        <p className="meta">{t('tariffBrowser.intro')}</p>
        {versions.isLoading ? (
          <SkeletonRows rows={3} />
        ) : versions.error ? (
          <ErrorState error={versions.error} onRetry={versions.refetch} />
        ) : rows.length === 0 ? (
          <EmptyState title={t('tariffBrowser.noVersions')} body={t('tariffBrowser.noVersionsBody')} />
        ) : (
          <div className="table-wrap" tabIndex={0} role="region" aria-label={t('tariffBrowser.versionsTitle')}>
            <table className="table">
              <thead>
                <tr>
                  <th scope="col">{t('tariffBrowser.version')}</th>
                  <th scope="col">{t('tariffBrowser.label')}</th>
                  <th scope="col">{t('tariffBrowser.effectiveFrom')}</th>
                  <th scope="col">{t('tariffBrowser.status')}</th>
                  <th scope="col">{t('tariffBrowser.importedAt')}</th>
                  <th scope="col">{t('tariffBrowser.activatedAt')}</th>
                  <th scope="col">
                    <span className="visually-hidden">{t('tariffBrowser.actions')}</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => {
                  const state = versionState(row);
                  return (
                    <tr key={row.id} aria-current={selected?.id === row.id ? 'true' : undefined}>
                      <td className="mono">{row.public_id}</td>
                      <td>{row.label}</td>
                      <td>{formatDate(row.effective_from)}</td>
                      <td>
                        <StatusBadge tone={VERSION_TONE[state]} label={t(`tariffBrowser.state.${state}`, state)} />
                      </td>
                      <td>{formatDateTime(row.imported_at)}</td>
                      <td>{row.activated_at ? formatDateTime(row.activated_at) : '—'}</td>
                      <td>
                        <Button
                          compact
                          variant="tertiary"
                          onClick={() => choose(row.id)}
                          aria-label={`${t('tariffBrowser.view')} ${row.public_id}`}
                        >
                          {t('tariffBrowser.view')}
                        </Button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </Card>
      {canImport && <ImportForm onImported={(version) => setSelectedId(version.id)} />}
      {selected && (
        <section aria-labelledby="tariff-browser-detail">
          <h3 id="tariff-browser-detail" ref={detailRef} tabIndex={-1} className="ws-section-title">
            {selected.public_id} · {t(`tariffBrowser.state.${versionState(selected)}`, selected.status)}
          </h3>
          <VersionDetail key={selected.id} version={selected} isApprover={isApprover} />
        </section>
      )}
      <FxHistory />
    </>
  );
}
