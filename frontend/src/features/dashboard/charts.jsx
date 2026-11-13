/**
 * Dashboard charts (Design.md section 6).
 *
 * Charts are inline SVG driven by real API values. Route colour is consistent across
 * the app, and every chart ships an accessible table alternative because colour is
 * never the only carrier of meaning.
 */

import { useState } from 'react';
import { useT } from '../../i18n/index.jsx';
import { Button } from '../../components/ui/index.jsx';
import { EmptyState } from '../../components/state/index.jsx';
import { formatNumber, formatPercent } from '../../utils/format.js';

const ROUTE_COLORS = {
  VCA: 'var(--route-vca)',
  CAV: 'var(--route-cav)',
  CAD: 'var(--route-cad)',
  XUS: 'var(--route-xus)',
};

const ROUTE_ORDER = ['VCA', 'CAV', 'CAD', 'XUS'];

function useToggle(initial = false) {
  const [on, setOn] = useState(initial);
  return [on, () => setOn((value) => !value)];
}

export function TrendChart({ points }) {
  const t = useT();
  const [showTable, toggleTable] = useToggle(false);

  if (!points || points.length === 0) {
    return (
      <EmptyState
        title="No qualifying shipments in this period"
        body="The chart stays empty rather than drawing a flat zero line, because there is no data to plot."
      />
    );
  }

  const buckets = [...new Set(points.map((point) => point.bucket))].sort();
  const routes = ROUTE_ORDER.filter((route) => points.some((point) => point.route_group === route));
  const maxValue = Math.max(...points.map((point) => point.count), 1);

  const width = 640;
  const height = 220;
  const padding = { top: 16, right: 16, bottom: 34, left: 34 };
  const plotWidth = width - padding.left - padding.right;
  const plotHeight = height - padding.top - padding.bottom;

  const x = (index) =>
    padding.left + (buckets.length === 1 ? plotWidth / 2 : (index / (buckets.length - 1)) * plotWidth);
  const y = (value) => padding.top + plotHeight - (value / maxValue) * plotHeight;

  const seriesFor = (route) =>
    buckets.map((bucket, index) => {
      const found = points.find((point) => point.bucket === bucket && point.route_group === route);
      return { x: x(index), y: y(found ? found.count : 0), value: found ? found.count : 0, bucket };
    });

  return (
    <div className="chart">
      <svg
        viewBox={`0 0 ${width} ${height}`}
        className="chart__svg"
        role="img"
        aria-label={`Qualifying shipments by route across ${buckets.length} periods. Highest value ${maxValue}.`}
      >
        {[0, 0.5, 1].map((ratio) => (
          <line
            key={ratio}
            x1={padding.left}
            x2={width - padding.right}
            y1={padding.top + plotHeight * ratio}
            y2={padding.top + plotHeight * ratio}
            stroke="var(--border-subtle)"
          />
        ))}
        <text x={4} y={padding.top + 4} className="chart__axis-label">
          {maxValue}
        </text>
        <text x={4} y={padding.top + plotHeight + 4} className="chart__axis-label">
          0
        </text>

        {routes.map((route) => {
          const series = seriesFor(route);
          const path = series
            .map((point, index) => `${index === 0 ? 'M' : 'L'}${point.x.toFixed(1)},${point.y.toFixed(1)}`)
            .join(' ');
          return (
            <g key={route}>
              <path d={path} fill="none" stroke={ROUTE_COLORS[route]} strokeWidth="2" />
              {series.map((point) => (
                <circle
                  key={`${route}-${point.bucket}`}
                  cx={point.x}
                  cy={point.y}
                  r="3"
                  fill={ROUTE_COLORS[route]}
                >
                  <title>{`${t(`routes.${route}`)} · ${point.bucket} · ${point.value}`}</title>
                </circle>
              ))}
            </g>
          );
        })}

        {buckets.map((bucket, index) =>
          index === 0 || index === buckets.length - 1 || index === Math.floor(buckets.length / 2) ? (
            <text key={bucket} x={x(index)} y={height - 12} textAnchor="middle" className="chart__axis-label">
              {bucket}
            </text>
          ) : null,
        )}
      </svg>

      <ul className="chart__legend">
        {routes.map((route) => (
          <li key={route}>
            <span className="chart__swatch" style={{ background: ROUTE_COLORS[route] }} aria-hidden="true" />
            {t(`routes.${route}`)}
          </li>
        ))}
      </ul>

      <Button variant="tertiary" compact onClick={toggleTable} aria-expanded={showTable}>
        {showTable ? t('dashboard.chartAlternative') : t('dashboard.tableAlternative')}
      </Button>

      {showTable && (
        <div className="table-wrap">
          <table className="table">
            <caption className="visually-hidden">Qualifying shipments by period and route</caption>
            <thead>
              <tr>
                <th scope="col">Period</th>
                {routes.map((route) => (
                  <th key={route} scope="col">
                    {t(`routes.${route}`)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {buckets.map((bucket) => (
                <tr key={bucket}>
                  <th scope="row">{bucket}</th>
                  {routes.map((route) => {
                    const found = points.find(
                      (point) => point.bucket === bucket && point.route_group === route,
                    );
                    return <td key={route}>{formatNumber(found ? found.count : 0)}</td>;
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

/**
 * Horizontal bars rather than a donut: route labels and counts are dense, and a bar
 * keeps them readable (Design.md section 6).
 */
export function RouteMixChart({ rows }) {
  const t = useT();
  if (!rows || rows.length === 0) {
    return (
      <EmptyState
        title="No route activity in this period"
        body="Route mix appears once qualifying shipments are recorded."
      />
    );
  }
  const max = Math.max(...rows.map((row) => row.count), 1);

  return (
    <ul className="route-mix">
      {rows.map((row) => (
        <li key={row.route_group}>
          <a href={row.link} className="route-mix__row">
            <span className="route-mix__label">{t(`routes.${row.route_group}`)}</span>
            <span className="route-mix__bar" aria-hidden="true">
              <span
                className="route-mix__fill"
                style={{
                  width: `${(row.count / max) * 100}%`,
                  background: ROUTE_COLORS[row.route_group] || 'var(--neutral-300)',
                }}
              />
            </span>
            <span className="route-mix__value">
              {formatNumber(row.count)}
              {row.share !== null && <span className="meta"> · {formatPercent(row.share)}</span>}
            </span>
          </a>
        </li>
      ))}
    </ul>
  );
}
