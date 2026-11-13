/**
 * Switch between the three import kinds (RC-UAT-21 Phase A): customers, shipments and the
 * legacy history baseline. Each is its own page and URL, so this is navigation with
 * `aria-current`, not a tab list.
 */

import { NavLink } from 'react-router-dom';
import { useT } from '../../i18n/index.jsx';

const KINDS = [
  { to: '/customers/import', key: 'customers', end: true },
  { to: '/customers/import/shipments', key: 'shipments' },
  { to: '/customers/import/legacy', key: 'legacy' },
];

export function ImportKindNav() {
  const t = useT();
  return (
    <nav className="import__kinds" aria-label={t('bulkImports.nav.label')}>
      {KINDS.map((kind) => (
        <NavLink
          key={kind.key}
          to={kind.to}
          end={kind.end}
          className={({ isActive }) => `import__kind${isActive ? ' import__kind--active' : ''}`}
        >
          {t(`bulkImports.nav.${kind.key}`)}
        </NavLink>
      ))}
    </nav>
  );
}
