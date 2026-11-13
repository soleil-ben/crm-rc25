/**
 * Reports (Design.md section 12, CRM.md section 12).
 *
 * Every figure comes from the API, which computes it from records. There is no comparison
 * line, no trend arrow, and no percentage change anywhere on this page, because none of
 * them can be derived honestly from a single period — and a fabricated one is worse than
 * none.
 *
 * The date range and the route filter live in the URL, so a report someone is looking at
 * is a link they can send to a colleague and a state that survives a reload.
 *
 * Each report states its own scope: whether its figures describe the selected period or
 * describe today. That distinction is the easiest thing on the page to misread, so it is
 * text next to the title rather than a colour or a position.
 */

import { useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useSearchParams } from 'react-router-dom';
import { reportsApi } from '../../api/endpoints.js';
import { downloadUrl } from '../../api/client.js';
import { useT } from '../../i18n/index.jsx';
import { P, useSession } from '../../app/SessionContext.jsx';
import { PageHeader } from '../../components/layout/AppShell.jsx';
import { Banner, Button, Card, FilterChip, TextInput } from '../../components/ui/index.jsx';
import { EmptyState, ErrorState, SkeletonRows } from '../../components/state/index.jsx';
import { ReportSummary, ReportTable, ScopeBadge } from './ReportTable.jsx';
import './reports.css';

const ROUTE_VALUES = ['VCA', 'CAV', 'CAD', 'XUS'];

/** Presets, expressed as day counts so the server still decides the bucket granularity. */
const PRESETS = [
  { days: 7, labelKey: 'reports.last7' },
  { days: 30, labelKey: 'reports.last30' },
  { days: 90, labelKey: 'reports.last90' },
  { days: 365, labelKey: 'reports.last365' },
];

function isoDaysAgo(days) {
  const date = new Date();
  date.setDate(date.getDate() - days);
  return date.toISOString().slice(0, 10);
}

function today() {
  return new Date().toISOString().slice(0, 10);
}

export function ReportsPage() {
  const t = useT();
  const { can } = useSession();
  const [params, setParams] = useSearchParams();

  const from = params.get('from') || isoDaysAgo(29);
  const to = params.get('to') || today();
  const routeGroups = params.getAll('route_group');

  const query = useMemo(
    () => ({ from, to, route_group: routeGroups }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [from, to, routeGroups.join(',')],
  );

  const { data, isLoading, isFetching, error, refetch } = useQuery({
    queryKey: ['reports', query],
    queryFn: () => reportsApi.read(query),
    placeholderData: (previous) => previous,
  });

  function setParam(key, value) {
    const next = new URLSearchParams(params);
    if (!value) next.delete(key);
    else next.set(key, value);
    setParams(next, { replace: true });
  }

  function applyPreset(days) {
    const next = new URLSearchParams(params);
    next.set('from', isoDaysAgo(days - 1));
    next.set('to', today());
    setParams(next, { replace: true });
  }

  function toggleRoute(route) {
    const next = new URLSearchParams(params);
    const current = next.getAll('route_group');
    next.delete('route_group');
    const updated = current.includes(route)
      ? current.filter((item) => item !== route)
      : [...current, route];
    updated.forEach((item) => next.append('route_group', item));
    setParams(next, { replace: true });
  }

  // A validation failure from the server (range too long, start after end) arrives as a
  // 422 with a message written for the operator. It is shown inline rather than as a
  // generic error, because the operator can fix it.
  const isValidationError = error?.status === 422;

  return (
    <>
      <PageHeader
        title={t('nav.reports')}
        subtitle={t('reports.subtitle')}
        actions={
          isFetching && !isLoading ? <span className="meta">{t('common.loading')}</span> : null
        }
      />

      <Card title={t('reports.filters')}>
        <div className="reports__filters">
          <div className="reports__range">
            <label htmlFor="report-from">{t('reports.from')}</label>
            <TextInput
              id="report-from"
              type="date"
              value={from}
              max={to}
              onChange={(event) => setParam('from', event.target.value)}
            />
            <label htmlFor="report-to">{t('reports.to')}</label>
            <TextInput
              id="report-to"
              type="date"
              value={to}
              min={from}
              onChange={(event) => setParam('to', event.target.value)}
            />
          </div>

          <div className="reports__presets" role="group" aria-label={t('reports.presets')}>
            {PRESETS.map((preset) => (
              <Button
                key={preset.days}
                variant="secondary"
                compact
                onClick={() => applyPreset(preset.days)}
              >
                {t(preset.labelKey)}
              </Button>
            ))}
          </div>

          <fieldset className="reports__routes">
            <legend>{t('reports.routeFilter')}</legend>
            {ROUTE_VALUES.map((route) => (
              <label key={route} className="reports__route-option">
                <input
                  type="checkbox"
                  checked={routeGroups.includes(route)}
                  onChange={() => toggleRoute(route)}
                />
                {t(`routes.${route}`)}
              </label>
            ))}
          </fieldset>
        </div>

        {routeGroups.length > 0 && (
          <div className="reports__chips">
            {routeGroups.map((route) => (
              <FilterChip
                key={route}
                label={t(`routes.${route}`)}
                onRemove={() => toggleRoute(route)}
              />
            ))}
          </div>
        )}
      </Card>

      {isValidationError && (
        <Banner tone="warning" title={t('reports.rangeProblem')}>
          {error.message}
        </Banner>
      )}
      {error && !isValidationError && <ErrorState error={error} onRetry={refetch} />}

      {isLoading && <SkeletonRows rows={4} height={220} />}

      {data && (
        <>
          <Banner tone="neutral" title={t('reports.periodTitle')}>
            <p>
              {t('reports.periodExplained')
                .replace('{from}', data.period.from_date)
                .replace('{to}', data.period.to_date)
                .replace('{timezone}', data.period.timezone)}
            </p>
            <ul className="reports__notes">
              {data.coverage_notes.map((note) => (
                <li key={note}>{note}</li>
              ))}
            </ul>
          </Banner>

          <Card title={t('reports.countingGuard')}>
            {/* AC-14 made visible: an operator can see that packages outnumber shipments
                and that the shipment figures still count each shipment once. */}
            <p>{data.counting_guard.note}</p>
            <dl className="report__summary">
              <div>
                <dt>{t('reports.summary.qualifying_shipments')}</dt>
                <dd>{data.counting_guard.qualifying_shipments}</dd>
              </div>
              <div>
                <dt>{t('reports.guardPackages')}</dt>
                <dd>{data.counting_guard.packages_on_those_shipments}</dd>
              </div>
              <div>
                <dt>{t('reports.guardLegs')}</dt>
                <dd>{data.counting_guard.legs_on_those_shipments}</dd>
              </div>
            </dl>
          </Card>

          {data.reports.length === 0 ? (
            <Card>
              <EmptyState title={t('reports.noneAvailable')} body={t('reports.noneAvailableBody')} />
            </Card>
          ) : (
            data.reports.map((table) => (
              <Card
                key={table.key}
                title={
                  <>
                    {table.title} <ScopeBadge scope={table.scope} />
                  </>
                }
                actions={
                  can(P.EXPORT_REPORTS) ? (
                    <Button
                      variant="secondary"
                      compact
                      onClick={() => {
                        window.location.href = downloadUrl(
                          `/exports/reports/${table.key}.csv`,
                          { from, to, route_group: routeGroups },
                        );
                      }}
                    >
                      {t('reports.exportCsv')}
                    </Button>
                  ) : null
                }
              >
                <p className="report__definition">{table.definition}</p>
                <ReportSummary table={table} />
                <ReportTable table={table} />
                {table.notes.length > 0 && (
                  <ul className="reports__notes">
                    {table.notes.map((note) => (
                      <li key={note}>{note}</li>
                    ))}
                  </ul>
                )}
              </Card>
            ))
          )}

          <Card title={t('reports.whatIsNotHere')}>
            {/* Stated on the page rather than only in the docs, because the absence of a
                comparison column is the kind of thing a reader assumes is a bug. */}
            <ul className="reports__notes">
              <li>{t('reports.noComparison')}</li>
              <li>{t('reports.noFreshness')}</li>
              <li>{t('reports.currencySeparate')}</li>
            </ul>
          </Card>
        </>
      )}
    </>
  );
}
