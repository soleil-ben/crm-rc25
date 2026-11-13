/**
 * The public tracking shell.
 *
 * A separate, deliberately small layout (`Design.md` section 14). No sidebar, no staff
 * navigation, no global search, no user menu, no session information, no administrative
 * control, and no call to an internal API. It shares the brand tokens with the staff
 * portal and nothing else.
 *
 * Mobile-first: this is a page somebody opens standing up, on a phone, having just
 * scanned a label.
 */

import { Link } from 'react-router-dom';
import { usePublicI18n } from './i18n.jsx';

/**
 * The text wordmark. No invented symbol or logo file ships anywhere in this product
 * until an approved asset exists (CRM.md section 14, DEC-0019).
 */
export function PublicWordmark() {
  const { t } = usePublicI18n();
  return (
    <span className="public-wordmark">
      <span className="public-wordmark__first">{t('brand.nameFirst')}</span>
      <span className="public-wordmark__second">{t('brand.nameSecond')}</span>
    </span>
  );
}

function LanguageSwitch() {
  const { language, setLanguage, languages, t } = usePublicI18n();
  return (
    <div className="public-language" role="group" aria-label={t('a11y.languageSwitcher')}>
      {languages.map(({ code, name }) => (
        <button
          key={code}
          type="button"
          className="public-language__option"
          // `aria-pressed` rather than a hidden radio group: two buttons is the simplest
          // honest markup for a two-way toggle, and it stays operable by keyboard.
          aria-pressed={language === code}
          lang={code}
          onClick={() => setLanguage(code)}
        >
          {name}
        </button>
      ))}
    </div>
  );
}

export function PublicLayout({ children }) {
  const { t } = usePublicI18n();
  return (
    <div className="public-shell">
      <a className="public-skip-link" href="#public-main">
        {t('a11y.skipToContent')}
      </a>

      <header className="public-header">
        <div className="public-header__inner">
          <Link to="/track" className="public-header__brand">
            <PublicWordmark />
            <span className="public-header__tagline">{t('brand.tagline')}</span>
          </Link>
          <LanguageSwitch />
        </div>
      </header>

      <main id="public-main" className="public-main" aria-label={t('a11y.mainContent')}>
        {children}
      </main>

      <footer className="public-footer">
        <p className="public-footer__line">
          <PublicWordmark />
        </p>
        <p className="public-footer__note">{t('landing.privacyNote')}</p>
      </footer>
    </div>
  );
}
