/**
 * Shared public-page pieces: the help link, the support callout, the carrier link, and
 * the honest freshness note.
 *
 * Every one of these is shared between English and Vietnamese. There is one component
 * per idea and two catalogues, never two versions of a page (`Design.md` section 15).
 */

import { usePublicI18n } from './i18n.jsx';

/**
 * Configured contact link, or nothing.
 *
 * The server supplies `help_url` with a tracking result; the landing page has no result
 * yet, so it falls back to the build-time value. Both come from the same deployment
 * configuration. If neither is set the link is simply absent -- a "Contact us" that goes
 * nowhere is worse than no link, and inventing a support URL is not an option.
 */
export function resolveHelpUrl(fromResult) {
  const candidate = fromResult || import.meta.env?.VITE_PUBLIC_HELP_URL || '';
  return isSafeExternalUrl(candidate) ? candidate : null;
}

/**
 * Whether a URL is safe to render as a link on a public page.
 *
 * The server already validates the carrier link against an allowlist before sending it
 * (`public_tracking_service.is_safe_public_carrier_url`). This is the second half of a
 * belt-and-braces pair: it costs nothing, and it means a `javascript:` URL introduced by
 * a future misconfiguration cannot become an anchor on a customer's screen.
 */
export function isSafeExternalUrl(value) {
  if (!value) return false;
  try {
    const url = new URL(value, window.location.origin);
    return url.protocol === 'https:' && !url.username && !url.password;
  } catch {
    return false;
  }
}

export function PublicHelpLink({ helpUrl, className }) {
  const { t } = usePublicI18n();
  const resolved = resolveHelpUrl(helpUrl);
  if (!resolved) return null;
  return (
    <a className={className} href={resolved} rel="noopener noreferrer nofollow">
      {t('landing.helpLink')}
    </a>
  );
}

/**
 * The support callout for an exception or for tracking we cannot show.
 *
 * It says what to do next and nothing about why internally. "Held pending a broker
 * escalation" is a staff sentence; a customer needs to know to get in touch and what to
 * quote.
 */
export function SupportCallout({ status, trackingState, helpUrl }) {
  const { t } = usePublicI18n();
  const isException = ['exception', 'delivery_attempted'].includes(status);
  const isUnavailable = trackingState === 'tracking_unavailable';
  if (!isException && !isUnavailable) return null;

  const tone = isException ? 'danger' : 'neutral';
  return (
    <aside className={`public-callout public-callout--${tone}`} role="note">
      <h2 className="public-callout__title">
        {isException ? t('callout.exceptionTitle') : t('callout.unavailableTitle')}
      </h2>
      <p className="public-callout__body">
        {isException ? t('callout.exceptionBody') : t('callout.unavailableBody')}
      </p>
      <PublicHelpLink helpUrl={helpUrl} className="public-callout__link" />
    </aside>
  );
}

/** The generic name of a tracking leg (owner, 2026-10-22): never a vendor or carrier. */
export function trackingName(t, link) {
  const key = link?.tracking_name_key === 'master_tracking' ? 'master_tracking' : 'last_mile_tracking';
  return t(`callout.trackingNames.${key}`);
}

/**
 * A carrier's own public tracking page, when the server judged one safe to offer. It is
 * labelled with the leg's generic name ("Master Tracking" / "Last Mile Tracking"), never the
 * stored carrier label (owner, 2026-10-22).
 *
 * The note beside it is the honest part. Solaris does not read that page -- Phase 4 does
 * not exist -- so the two can disagree, and saying so is better than letting a customer
 * assume the link and this page are the same information (CRM.md section 9).
 */
/** The links the server allowed (one per generic tracking name, in leg order). */
export function carrierLinksOf(result) {
  if (result?.carrier_links?.length) return result.carrier_links;
  return result?.carrier_link ? [result.carrier_link] : [];
}

export function CarrierLink({ link, showNote = true }) {
  const { t } = usePublicI18n();
  if (!link || !isSafeExternalUrl(link.url)) return null;
  return (
    <div className="public-carrier-link">
      <a
        className="public-button public-button--secondary"
        href={link.url}
        target="_blank"
        rel="noopener noreferrer nofollow"
      >
        {t('callout.carrierLink', { name: trackingName(t, link) })}
      </a>
      {showNote && <p className="public-carrier-link__note">{t('callout.carrierLinkNote')}</p>}
    </div>
  );
}

/**
 * How this shipment is tracked, stated plainly.
 *
 * Phase 4 provider synchronization does not exist, so there is no "last carrier update",
 * no "last successful sync", and no freshness age here. There is the honest state, an
 * explanation of what it means, and -- when there is one -- the time of the most recent
 * update a person actually recorded, labelled as exactly that.
 */
export function FreshnessNote({ trackingState, lastUpdateAt, formatDateTime }) {
  const { t } = usePublicI18n();
  if (!trackingState) return null;
  return (
    <section className="public-freshness" aria-label={t('freshness.label')}>
      <p className="public-freshness__state">
        <span className="public-freshness__label">{t('freshness.label')}:</span>{' '}
        <strong>{t(`freshness.${trackingState}`)}</strong>
      </p>
      <p className="public-freshness__detail">{t(`freshness.${trackingState}_detail`)}</p>
      {lastUpdateAt ? (
        <p className="public-freshness__detail">
          {t('freshness.lastUpdate')}: {formatDateTime(lastUpdateAt)}
        </p>
      ) : null}
    </section>
  );
}

/**
 * The persistent demo warning.
 *
 * Development only, by construction: a demo record returns the same generic not-found
 * response in production, so this banner cannot appear there (CRM.md section 3).
 */
export function DemoBanner({ dataMode }) {
  const { t } = usePublicI18n();
  if (dataMode !== 'demo') return null;
  return (
    <div className="public-demo-banner" role="status">
      <strong>{t('freshness.demo')}</strong>
      <span>{t('freshness.demo_detail')}</span>
    </div>
  );
}
