/**
 * Staff shell: fixed navy sidebar, white top bar, content region (Design.md section 4).
 *
 * The internal staff portal and the public tracking page are separate shells that share
 * only approved brand tokens; nothing here is reused for the public page.
 */

import { useEffect, useRef, useState } from 'react';
import { NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom';
import { useT } from '../../i18n/index.jsx';
import { P, useSession } from '../../app/SessionContext.jsx';
import { Avatar, Button } from '../ui/index.jsx';
import { GlobalSearch } from './GlobalSearch.jsx';
import { useTariffPending } from '../../features/settings/useTariffPending.js';
import { interpolate } from '../../utils/format.js';
import {
  IconCustomers,
  IconDashboard,
  IconMenu,
  IconReports,
  IconSegments,
  IconSettings,
  IconShipments,
  IconTasks,
  IconWorkspace,
} from './Icons.jsx';
import './shell.css';

const APP_VERSION = '0.1.0';

function navigationItems(t, can) {
  return [
    { to: '/', label: t('nav.dashboard'), Icon: IconDashboard, end: true, permission: P.DASHBOARD_READ },
    { to: '/customers', label: t('nav.customers'), Icon: IconCustomers, permission: P.CUSTOMER_READ },
    { to: '/segments', label: t('nav.segments'), Icon: IconSegments, permission: P.SEGMENT_READ },
    { to: '/shipments', label: t('nav.shipments'), Icon: IconShipments, permission: P.SHIPMENT_READ },
    // Phase 13D. Vendor cost lives here, so only a role holding `tariff:read` (Operations
    // and Admin) sees the entry; every request behind it refuses independently.
    { to: '/workspace', label: t('nav.workspace'), Icon: IconWorkspace, permission: P.TARIFF_READ },
    // Phase 13E. Revenue for `financial:read`; the cost tabs inside need `tariff:read` too.
    { to: '/finance', label: t('nav.finance'), Icon: IconReports, permission: P.FINANCIAL_READ },
    { to: '/follow-ups', label: t('nav.followUps'), Icon: IconTasks, permission: P.TASK_READ },
    // Operations and Admin only. Marketing and the read-only manager hold neither
    // Customer Account permission, so the entry is absent for them -- and the route and
    // every request behind it refuse independently, because a hidden link is not a
    // boundary (CRM.md section 11).
    {
      to: '/customer-accounts',
      label: t('nav.customerAccounts'),
      Icon: IconCustomers,
      permission: P.CUSTOMER_ACCOUNT_REVIEW,
    },
    { to: '/reports', label: t('nav.reports'), Icon: IconReports, permission: P.REPORT_READ },
    { to: '/settings', label: t('nav.settings'), Icon: IconSettings, permission: P.SETTINGS_READ },
  ].filter((item) => can(item.permission));
}

export function AppShell() {
  const t = useT();
  const location = useLocation();
  const navigate = useNavigate();
  const { user, logout, can, isDemoEnvironment, environment } = useSession();
  const tariffPending = useTariffPending(can(P.TARIFF_MANAGE) && can(P.SETTINGS_READ));
  const [navOpen, setNavOpen] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const menuRef = useRef(null);
  const triggerRef = useRef(null);
  // Which item takes focus when the menu opens: 'first', 'last', or null for a pointer
  // open, which leaves focus on the trigger.
  const pendingFocusRef = useRef(null);

  // Close the mobile drawer and account menu on navigation.
  useEffect(() => {
    setNavOpen(false);
    setMenuOpen(false);
  }, [location.pathname]);

  useEffect(() => {
    if (!menuOpen) return undefined;
    function onClick(event) {
      if (menuRef.current && !menuRef.current.contains(event.target)) setMenuOpen(false);
    }
    document.addEventListener('mousedown', onClick);
    return () => document.removeEventListener('mousedown', onClick);
  }, [menuOpen]);

  // Once the menu is in the DOM, move focus to the item the keyboard asked for.
  useEffect(() => {
    if (!menuOpen || !pendingFocusRef.current) return;
    const menuItems = Array.from(menuRef.current?.querySelectorAll('[role="menuitem"]') ?? []);
    const target =
      pendingFocusRef.current === 'last' ? menuItems[menuItems.length - 1] : menuItems[0];
    pendingFocusRef.current = null;
    target?.focus();
  }, [menuOpen]);

  function accountMenuItems() {
    return Array.from(menuRef.current?.querySelectorAll('[role="menuitem"]') ?? []);
  }

  function openAccountMenu(focus) {
    pendingFocusRef.current = focus;
    setMenuOpen(true);
  }

  function closeAccountMenu({ returnFocus = false } = {}) {
    setMenuOpen(false);
    if (returnFocus) triggerRef.current?.focus();
  }

  // The WAI-ARIA menu button pattern: Enter, Space or ArrowDown on the button opens the
  // menu on its first item, ArrowUp on its last.
  function onTriggerKeyDown(event) {
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault();
      openAccountMenu(event.key === 'ArrowUp' ? 'last' : 'first');
    }
  }

  // Inside the menu: arrows move and wrap, Home and End jump, Escape closes and hands
  // focus back to the button, Tab closes and lets focus move on as usual.
  function onMenuKeyDown(event) {
    const menuItems = accountMenuItems();
    if (menuItems.length === 0) return;
    const index = menuItems.indexOf(document.activeElement);
    let next = null;
    switch (event.key) {
      case 'ArrowDown':
        next = menuItems[(index + 1) % menuItems.length];
        break;
      case 'ArrowUp':
        next = menuItems[(index - 1 + menuItems.length) % menuItems.length];
        break;
      case 'Home':
        next = menuItems[0];
        break;
      case 'End':
        next = menuItems[menuItems.length - 1];
        break;
      case 'Escape':
        event.preventDefault();
        event.stopPropagation();
        closeAccountMenu({ returnFocus: true });
        return;
      case 'Tab':
        closeAccountMenu();
        return;
      default:
        return;
    }
    event.preventDefault();
    next?.focus();
  }

  const items = navigationItems(t, can);

  return (
    <div className="shell">
      <a className="skip-link" href="#main-content">
        {t('nav.skipToContent')}
      </a>

      {navOpen && <div className="sidebar-scrim" onClick={() => setNavOpen(false)} />}

      <nav
        className={navOpen ? 'sidebar is-open' : 'sidebar'}
        aria-label={t('nav.mainNavigation')}
      >
        <div className="sidebar__brand">
          {/* Text wordmark only. No official Solaris symbol is invented here. */}
          {t('brand.nameFirst')} <span className="sidebar__brand-accent">{t('brand.nameSecond')}</span>
        </div>
        <div className="sidebar__nav">
          {items.map(({ to, label, Icon, end }) => (
            <NavLink
              key={to}
              to={to}
              end={end}
              className={({ isActive }) => (isActive ? 'sidebar__link is-active' : 'sidebar__link')}
            >
              <Icon />
              <span className="sidebar__label">{label}</span>
              {/* Phase 15: an approver sees how many tariff drafts and held senders wait. */}
              {to === '/settings' && tariffPending.count > 0 && (
                <>
                  <span className="sidebar__badge" aria-hidden="true">
                    {tariffPending.count}
                  </span>
                  <span className="visually-hidden">
                    {interpolate(t('tariffPending.navBadge'), { count: tariffPending.count })}
                  </span>
                </>
              )}
            </NavLink>
          ))}
        </div>
        <div className="sidebar__footer">
          <span>
            {environment || 'development'} · v{APP_VERSION}
          </span>
          <a href="mailto:support@solarisexpress.example">{t('nav.support')}</a>
        </div>
      </nav>

      <div className="main">
        {isDemoEnvironment && (
          <div className="demo-banner" role="status">
            Demo environment — every customer and shipment record shown here is synthetic
            sample data.
          </div>
        )}

        <header className="topbar">
          <Button
            variant="tertiary"
            className="topbar__menu-toggle"
            onClick={() => setNavOpen((open) => !open)}
            aria-label={navOpen ? t('nav.closeMenu') : t('nav.openMenu')}
            aria-expanded={navOpen}
          >
            <IconMenu />
          </Button>

          <GlobalSearch />

          <span className="spacer" />

          <div ref={menuRef} style={{ position: 'relative' }}>
            <button
              ref={triggerRef}
              type="button"
              id="account-menu-button"
              className="topbar__user"
              onClick={(event) => {
                if (menuOpen) {
                  closeAccountMenu();
                } else {
                  // `detail` is 0 for a click synthesised from Enter or Space: a keyboard
                  // open, which focuses the first item. A pointer open leaves focus here.
                  openAccountMenu(event.detail === 0 ? 'first' : null);
                }
              }}
              onKeyDown={onTriggerKeyDown}
              aria-haspopup="menu"
              aria-expanded={menuOpen}
              aria-controls={menuOpen ? 'account-menu' : undefined}
              aria-label={t('auth.userMenu')}
            >
              <Avatar initials={user?.initials ?? '?'} />
              <span>
                <span className="topbar__user-name">{user?.full_name}</span>
                <br />
                <span className="topbar__user-role">{user?.role?.replace(/_/g, ' ')}</span>
              </span>
            </button>
            {menuOpen && (
              <div
                className="topbar__menu"
                role="menu"
                id="account-menu"
                aria-labelledby="account-menu-button"
                onKeyDown={onMenuKeyDown}
              >
                {/* Items are out of the Tab order: inside a menu the arrows move focus,
                    and Tab leaves the menu (WAI-ARIA menu pattern). */}
                <button
                  type="button"
                  role="menuitem"
                  tabIndex={-1}
                  className="topbar__menu-item"
                  onClick={() => navigate('/settings')}
                >
                  {t('nav.settings')}
                </button>
                {/* RC-UAT-21 Phase B (DEC-0231): change your own password. */}
                <button
                  type="button"
                  role="menuitem"
                  tabIndex={-1}
                  className="topbar__menu-item"
                  onClick={() => navigate('/my-password')}
                >
                  {t('staffPassword.menuItem')}
                </button>
                <button
                  type="button"
                  role="menuitem"
                  tabIndex={-1}
                  className="topbar__menu-item"
                  onClick={async () => {
                    try {
                      await logout();
                    } finally {
                      // The address bar leaves the record the person was looking at, and
                      // `replace` means Back does not return to that URL either. The
                      // sign-in screen renders at `/` whatever happens to the request.
                      navigate('/', { replace: true });
                    }
                  }}
                >
                  {t('auth.signOut')}
                </button>
              </div>
            )}
          </div>
        </header>

        <main id="main-content" className="content" tabIndex={-1}>
          <Outlet />
        </main>
      </div>
    </div>
  );
}

export function PageHeader({ title, subtitle, actions, breadcrumb }) {
  return (
    <div>
      {breadcrumb && <nav className="breadcrumb">{breadcrumb}</nav>}
      <div className="page-header">
        <div className="page-header__text">
          <h1>{title}</h1>
          {subtitle && <p className="page-header__subtitle">{subtitle}</p>}
        </div>
        <span className="spacer" />
        {actions && <div className="row-wrap">{actions}</div>}
      </div>
    </div>
  );
}
