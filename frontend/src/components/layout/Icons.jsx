/**
 * One outline icon set with consistent 1.75px strokes (Design.md section 3).
 * Icons are decorative here; every navigation item also carries a visible text label.
 */

const base = {
  width: 20,
  height: 20,
  viewBox: '0 0 24 24',
  fill: 'none',
  stroke: 'currentColor',
  strokeWidth: 1.75,
  strokeLinecap: 'round',
  strokeLinejoin: 'round',
  'aria-hidden': 'true',
  focusable: 'false',
  className: 'sidebar__icon',
};

export function IconDashboard(props) {
  return (
    <svg {...base} {...props}>
      <path d="M3 10.5 12 3l9 7.5" />
      <path d="M5 9.5V20h14V9.5" />
      <path d="M9.5 20v-5.5h5V20" />
    </svg>
  );
}

export function IconCustomers(props) {
  return (
    <svg {...base} {...props}>
      <circle cx="9" cy="8" r="3.2" />
      <path d="M3.5 19.5c.6-3.1 2.9-4.8 5.5-4.8s4.9 1.7 5.5 4.8" />
      <path d="M16.2 6.2a3 3 0 0 1 0 5.6" />
      <path d="M17.6 14.9c2 .5 3.4 2 3.9 4.6" />
    </svg>
  );
}

export function IconSegments(props) {
  return (
    <svg {...base} {...props}>
      <circle cx="12" cy="12" r="8.5" />
      <path d="M12 3.5v8.5l6 6" />
    </svg>
  );
}

export function IconShipments(props) {
  return (
    <svg {...base} {...props}>
      <path d="M12 3 20 7.2v9.6L12 21l-8-4.2V7.2z" />
      <path d="M4 7.2 12 11.5l8-4.3" />
      <path d="M12 11.5V21" />
    </svg>
  );
}

export function IconWorkspace(props) {
  return (
    <svg {...base} {...props}>
      <rect x="3" y="4" width="18" height="6" rx="1.5" />
      <rect x="3" y="14" width="8" height="6" rx="1.5" />
      <rect x="13" y="14" width="8" height="6" rx="1.5" />
    </svg>
  );
}

export function IconTasks(props) {
  return (
    <svg {...base} {...props}>
      <rect x="3.5" y="4.5" width="17" height="16" rx="2.5" />
      <path d="M8 3v3M16 3v3M3.5 9.5h17" />
      <path d="m9 14.5 2 2 4-4" />
    </svg>
  );
}

export function IconReports(props) {
  return (
    <svg {...base} {...props}>
      <path d="M4 20V10M10 20V4M16 20v-7M22 20H2" />
    </svg>
  );
}

export function IconSettings(props) {
  return (
    <svg {...base} {...props}>
      <circle cx="12" cy="12" r="3" />
      <path d="M12 2.5v2.2M12 19.3v2.2M4.2 4.2l1.6 1.6M18.2 18.2l1.6 1.6M2.5 12h2.2M19.3 12h2.2M4.2 19.8l1.6-1.6M18.2 5.8l1.6-1.6" />
    </svg>
  );
}

export function IconSearch(props) {
  return (
    <svg {...base} {...props}>
      <circle cx="11" cy="11" r="6.5" />
      <path d="m16 16 4.5 4.5" />
    </svg>
  );
}

export function IconMenu(props) {
  return (
    <svg {...base} {...props}>
      <path d="M4 7h16M4 12h16M4 17h16" />
    </svg>
  );
}

export function IconAlert(props) {
  return (
    <svg {...base} {...props}>
      <path d="M12 4.5 21 19.5H3z" />
      <path d="M12 10v4M12 16.8v.2" />
    </svg>
  );
}
