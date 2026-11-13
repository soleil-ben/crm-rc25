/**
 * One report, rendered as a table (Design.md section 12, CRM.md section 12).
 *
 * Tables rather than charts, deliberately. Every figure here is one an operator will act
 * on or copy into something else, and a table is exact, sortable by eye, screen-readable,
 * and impossible to misread by a few pixels. Where a proportion genuinely helps, a bar sits
 * *inside* the row next to its number rather than replacing it — the number is the content
 * and the bar is decoration, so the row still reads correctly with no colour at all.
 *
 * Three rules the components below enforce:
 *
 * - a `null` renders as "Unknown", never as `0` or a blank cell;
 * - a share renders only when the API supplied one;
 * - a row with a `link` becomes a link to the records behind it, because every aggregate
 *   must open its supporting records.
 */

import { Link } from 'react-router-dom';
import { InfoDot } from '../../components/ui/index.jsx';
import { useT } from '../../i18n/index.jsx';
import { formatNumber, formatPercent } from '../../utils/format.js';

const ROUTE_COLORS = {
  VCA: 'var(--route-vca)',
  CAV: 'var(--route-cav)',
  CAD: 'var(--route-cad)',
  XUS: 'var(--route-xus)',
};

/** Render one cell according to the column kind the API declared. */
function Cell({ column, row, t }) {
  const value = row[column.key];

  if (value === null || value === undefined) {
    // Unknown, and said so. An empty cell reads as zero to most people.
    return <span className="report__unknown">{t('reports.unknown')}</span>;
  }
  if (column.kind === 'integer') return formatNumber(value);
  if (column.kind === 'share') return formatPercent(value);
  if (column.kind === 'money') return value;
  return String(value);
}

export function ReportTable({ table, maxBarValue }) {
  const t = useT();
  const numericColumn = table.columns.find((column) => column.kind === 'integer');
  const barMax =
    maxBarValue ??
    (numericColumn
      ? Math.max(...table.rows.map((row) => Number(row[numericColumn.key]) || 0), 1)
      : 0);

  if (table.rows.length === 0) {
    return (
      <p className="report__empty">{t('reports.noRows')}</p>
    );
  }

  return (
    <div className="table-wrap">
      <table className="table table--stacked report__table">
        <caption className="visually-hidden">
          {table.title}. {table.definition}
        </caption>
        <thead>
          <tr>
            {table.columns.map((column) => (
              <th
                key={column.key}
                scope="col"
                className={column.kind === 'integer' || column.kind === 'share' ? 'numeric' : undefined}
              >
                {column.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {table.rows.map((row, index) => (
            <tr key={row.link ? `${row.link}-${index}` : index}>
              {table.columns.map((column, columnIndex) => {
                const isFirst = columnIndex === 0;
                const content = <Cell column={column} row={row} t={t} />;
                const showBar =
                  numericColumn &&
                  column.key === numericColumn.key &&
                  barMax > 0 &&
                  Number(row[column.key]) > 0;

                return (
                  <td
                    key={column.key}
                    data-label={column.label}
                    className={
                      column.kind === 'integer' || column.kind === 'share'
                        ? 'numeric'
                        : undefined
                    }
                  >
                    {isFirst && row.link ? (
                      <Link to={row.link} className="report__row-link">
                        {content}
                      </Link>
                    ) : (
                      content
                    )}
                    {showBar && (
                      <span
                        className="report__bar"
                        aria-hidden="true"
                        style={{
                          width: `${(Number(row[column.key]) / barMax) * 100}%`,
                          background: ROUTE_COLORS[row.route_group] || 'var(--brand-orange-500)',
                        }}
                      />
                    )}
                    {isFirst && row.definition && <p className="meta">{row.definition}</p>}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/**
 * A short prose summary above each table.
 *
 * The accessible summary is not an afterthought bolted onto a chart: it is the primary
 * reading of the report, and it never relies on colour or position.
 */
export function ReportSummary({ table }) {
  const t = useT();
  const entries = Object.entries(table.summary || {}).filter(
    ([key]) => key !== 'granularity' && key !== 'includes_costs',
  );
  if (entries.length === 0) return null;

  return (
    <dl className="report__summary">
      {entries.map(([key, value]) => (
        <div key={key}>
          <dt>{t(`reports.summary.${key}`, key.replace(/_/g, ' '))}</dt>
          <dd>
            {value === null || value === undefined ? (
              <span className="report__unknown">{t('reports.unknown')}</span>
            ) : typeof value === 'number' && key === 'share' ? (
              formatPercent(value)
            ) : typeof value === 'number' ? (
              formatNumber(value)
            ) : (
              String(value)
            )}
          </dd>
        </div>
      ))}
    </dl>
  );
}

export function ScopeBadge({ scope }) {
  const t = useT();
  // Text, not colour: whether a figure describes the period or today is the single most
  // misreadable thing on this page.
  return (
    <span className={`report__scope report__scope--${scope}`}>
      {scope === 'current' ? t('reports.scopeCurrent') : t('reports.scopePeriod')}
      <InfoDot
        text={
          scope === 'current'
            ? t('reports.scopeCurrentHelp')
            : t('reports.scopePeriodHelp')
        }
      />
    </span>
  );
}
