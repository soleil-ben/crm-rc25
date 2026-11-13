/**
 * The Customer Account shell (`Design.md` §14a.2).
 *
 * A slim top bar: wordmark, the signed-in destinations, and a sign-out control. **No
 * staff navigation** — no sidebar, no global search, no internal counts, no environment
 * banner, no user menu. Nothing in this file imports from `src/components` or
 * `src/features`, and `tests/accountBoundary.test.jsx` asserts that by reading the
 * imports rather than by trusting this sentence.
 *
 * The navigation is rendered **only when the session is signed in**, so a stranger on the
 * sign-in page is not shown a link to a shipment list they cannot open. That is a
 * courtesy and not a boundary: the guard refuses the route and the server refuses the
 * request, both independently.
 *
 * The **language switch** (OD-71) is the exception: it is in the header on every screen,
 * signed in or not, because the person who most needs it is the one who cannot read the
 * sign-in form in the default language. It changes React state only; nothing is stored.
 */

import { Link, NavLink, useLocation } from 'react-router-dom';
import { AccountWordmark, Button } from './components.jsx';
import { useAccountSession } from './AccountSession.jsx';
import { ACCOUNT_LOCALES, useAccountLocale, useAccountT } from './i18n.jsx';

const MAIN_ID = 'ca-main';

function navClass({ isActive }) {
  return `ca-nav__link${isActive ? ' ca-nav__link--active' : ''}`;
}

/**
 * Two buttons, each named in its own language and marked with its own `lang`, so a
 * screen reader pronounces "Tiếng Việt" as Vietnamese whichever language the page is in.
 * `aria-pressed` says which one is on, in words as well as in the tint.
 */
export function LanguageSwitch() {
  const t = useAccountT();
  const { locale, setLocale } = useAccountLocale();
  return (
    <div className="ca-lang" role="group" aria-label={t('language.switchLabel')}>
      {ACCOUNT_LOCALES.map((code) => (
        <button
          key={code}
          type="button"
          lang={code}
          className={`ca-lang__option${locale === code ? ' ca-lang__option--active' : ''}`}
          aria-pressed={locale === code}
          onClick={() => setLocale(code)}
        >
          {t(`language.${code}`)}
        </button>
      ))}
    </div>
  );
}

export function AccountLayout({ children }) {
  const session = useAccountSession();
  const location = useLocation();
  const t = useAccountT();

  return (
    <div className="ca-shell">
      {/* First focusable element on the page. Required by Design.md section 15 and by
          every keyboard pass: without it a keyboard user tabs the whole header again on
          every navigation. */}
      <a className="ca-skip-link" href={`#${MAIN_ID}`}>
        {t('layout.skipToMain')}
      </a>

      <header className="ca-header">
        <div className="ca-header__inner">
          <Link
            to={session.isSignedIn ? '/account' : '/account/sign-in'}
            className="ca-header__brand"
          >
            <AccountWordmark />
            <span className="ca-header__surface">{t('layout.surface')}</span>
          </Link>

          <LanguageSwitch />

          {session.isSignedIn ? (
            <nav className="ca-nav" aria-label={t('layout.navLabel')}>
              {session.shipmentHistoryAvailable ? (
                <NavLink
                  to="/account/shipments"
                  className={navClass}
                  // The current page is announced as such rather than only underlined.
                  end={false}
                >
                  {t('layout.navShipments')}
                </NavLink>
              ) : null}
              {session.shipmentHistoryAvailable ? (
                <NavLink to="/account/profile" className={navClass}>
                  {t('layout.navProfile')}
                </NavLink>
              ) : null}
              {/* OD-72. Behind the same condition as the profile: the page is behind the
                  same guard. */}
              {session.shipmentHistoryAvailable ? (
                <NavLink to="/account/notifications" className={navClass}>
                  {t('layout.navNotifications')}
                </NavLink>
              ) : null}
              {/* Phase 13G (OD-77). Same condition: the page is behind the same guard. */}
              {session.shipmentHistoryAvailable ? (
                <NavLink to="/account/quotes" className={navClass} end={false}>
                  {t('layout.navQuotes')}
                </NavLink>
              ) : null}
              {/* RC-UAT-21 Phase B: any signed-in account changes its own password and email. */}
              <NavLink to="/account/security" className={navClass}>
                {t('layout.navSecurity')}
              </NavLink>
              <Button
                variant="ghost"
                onClick={() => session.signOut()}
                busy={session.isSigningOut}
              >
                {t('layout.signOut')}
              </Button>
            </nav>
          ) : null}
        </div>
      </header>

      {/*
        `key` on the main element, changed by pathname, so assistive technology treats a
        navigation as new content rather than as a mutation of the old page. React Router
        does not reload the document, and without this a screen reader can stay where it
        was on the previous screen.
      */}
      <main id={MAIN_ID} className="ca-main" key={location.pathname}>
        {children}
      </main>

      <footer className="ca-footer">
        <p className="ca-footer__line">
          <AccountWordmark />
        </p>
        <p className="ca-footer__note">
          {t('layout.footerBefore')} <Link to="/track">{t('layout.footerLink')}</Link>
          {t('layout.footerAfter')}
        </p>
      </footer>
    </div>
  );
}

/**
 * The page title region every screen starts with.
 *
 * One `h1` per screen, rendered here so no screen can forget it or use an `h2` as the
 * first heading. `intro` is the sentence under it, which several screens need and none
 * should invent its own markup for.
 */
export function AccountPageHeader({ title, intro, headingRef }) {
  return (
    <div className="ca-page-header">
      {/*
        `tabIndex={-1}` and a ref so a screen that has just changed state — a completed
        reset, a failed sign-in, an opened shipment — can move focus to the heading. Focus
        only lands here when a screen puts it here deliberately.
      */}
      <h1 className="ca-page-header__title" tabIndex={-1} ref={headingRef}>
        {title}
      </h1>
      {intro ? <p className="ca-page-header__intro">{intro}</p> : null}
    </div>
  );
}

/** A narrow single-card page: sign in, register, every token landing, every state card. */
export function AccountNarrowPage({ children }) {
  return <div className="ca-narrow">{children}</div>;
}
