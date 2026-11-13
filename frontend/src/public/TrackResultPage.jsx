/**
 * `/track/:reference` -- the tracking result.
 *
 * This is the route a label's QR code opens, so it has to work as a cold entry point: no
 * prior landing-page state, nothing in storage, just the reference in the URL.
 *
 * **No result outlives its lookup.** The query is keyed on the normalized reference and
 * the client is created with `gcTime: 0`, so a second lookup cannot render the first
 * one's data while it loads, and a *failed* second lookup shows the error rather than the
 * previous customer's shipment. That is the bug this page most needs not to have: two
 * people sharing a phone, or one person checking two parcels.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Link, useParams } from 'react-router-dom';
import { CATALOGUES, usePublicI18n } from './i18n.jsx';
import { renderTemplate } from '../shared/publicUpdateTemplates.js';
import { parseServerDate } from '../shared/serverDate.js';
import { fetchPublicTracking, PublicTrackingError } from './publicApi.js';
import { normalizeReference } from './reference.js';
import {
  CarrierLink,
  carrierLinksOf,
  DemoBanner,
  FreshnessNote,
  PublicHelpLink,
  SupportCallout,
} from './PublicCallouts.jsx';

/** Statuses that carry a tone. Colour supports meaning; it never carries it alone. */
const STATUS_TONE = {
  delivered: 'success',
  partially_delivered: 'info',
  in_transit: 'info',
  out_for_delivery: 'info',
  departed_origin: 'info',
  arrived_destination: 'info',
  customs_processing: 'warning',
  awaiting_parcel: 'warning',
  delivery_attempted: 'warning',
  exception: 'danger',
  return_in_progress: 'warning',
  returned: 'neutral',
  cancelled: 'neutral',
  tracking_unavailable: 'neutral',
};

function useFormatters() {
  const { locale } = usePublicI18n();
  return useMemo(() => {
    const dateTime = (value, timeZone) => {
      if (!value) return null;
      // The API sends UTC; the office timezone comes with the result so a customer sees
      // the same clock Solaris does, with the zone named (Design.md section 15).
      const date = parseServerDate(value);
      if (!date) return null;
      try {
        return new Intl.DateTimeFormat(locale, {
          dateStyle: 'medium',
          timeStyle: 'short',
          timeZone: timeZone || undefined,
          timeZoneName: 'short',
        }).format(date);
      } catch {
        return new Intl.DateTimeFormat(locale, {
          dateStyle: 'medium',
          timeStyle: 'short',
        }).format(date);
      }
    };
    const dateOnly = (value, timeZone) => {
      if (!value) return null;
      const date = parseServerDate(value);
      if (!date) return null;
      try {
        return new Intl.DateTimeFormat(locale, {
          dateStyle: 'long',
          timeZone: timeZone || undefined,
        }).format(date);
      } catch {
        return new Intl.DateTimeFormat(locale, { dateStyle: 'long' }).format(date);
      }
    };
    return { dateTime, dateOnly };
  }, [locale]);
}

function StatusBadge({ status, label }) {
  const tone = STATUS_TONE[status] || 'neutral';
  // The text is the status. The colour is decoration on top of it.
  return <span className={`public-badge public-badge--${tone}`}>{label}</span>;
}

/**
 * The Solaris Shipment ID, in monospace, with a copy button.
 *
 * `Design.md` section 19 asks that the ID be readable and copyable wherever it appears.
 * On a phone this matters more than on the desktop: this is the value a customer reads
 * out or pastes into a message when they contact us.
 */
function CopyableReference({ value }) {
  const { t } = usePublicI18n();
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (!copied) return undefined;
    const timer = setTimeout(() => setCopied(false), 2000);
    return () => clearTimeout(timer);
  }, [copied]);

  async function copy() {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
    } catch {
      // A browser that refuses clipboard access is not worth an error message; the value
      // is on screen and selectable.
    }
  }

  return (
    <span className="public-copyable">
      <span className="public-copyable__value">{value}</span>
      <button type="button" className="public-copyable__button" onClick={copy}>
        {copied ? t('result.copied') : t('result.copyId')}
      </button>
      {/* Announced only on change, so a screen reader confirms the copy without
          re-reading the whole row. */}
      <span className="public-visually-hidden" role="status">
        {copied ? t('result.copied') : ''}
      </span>
    </span>
  );
}

/**
 * A coarse place: city and country. Never a street, a unit, or a postal code -- the API
 * does not send them, and this is the component that would display them if it did.
 */
function Place({ place, fallback }) {
  const { language } = usePublicI18n();
  if (!place) return <span>{fallback}</span>;

  const code = place.country_code;
  const translated = code ? CATALOGUES[language]?.countries?.[code] : null;
  // A country we have not translated falls back to the label the API sent, then to the
  // code. Never to an invented name.
  const country = translated || place.country_label || code || null;
  const city = place.city || fallback;

  return <span>{country && country !== city ? `${city}, ${country}` : city}</span>;
}

function PackageList({ packages, selectedReference }) {
  const { t } = usePublicI18n();
  if (!packages?.length) return null;
  return (
    <section className="public-section" aria-label={t('a11y.packagesRegion')}>
      <h2 className="public-section__title">{t('result.packagesTitle')}</h2>
      <ul className="public-packages">
        {packages.map((item) => {
          const isSelected = item.package_reference === selectedReference;
          return (
            <li
              key={item.package_reference}
              className={`public-package${isSelected ? ' public-package--selected' : ''}`}
              // The scanned package is announced, not merely tinted: somebody who scanned
              // a specific parcel needs to find it without relying on a highlight colour.
              aria-current={isSelected ? 'true' : undefined}
            >
              <span className="public-package__reference">{item.package_reference}</span>
              <StatusBadge status={item.status} label={t(`status.${item.status}`)} />
              {isSelected ? (
                <span className="public-package__marker">{t('result.packageSelected')}</span>
              ) : null}
              {item.is_cancelled ? (
                <span className="public-package__note">{t('result.packageCancelled')}</span>
              ) : null}
            </li>
          );
        })}
      </ul>
    </section>
  );
}

function Timeline({ entries, timezone }) {
  const { t, language } = usePublicI18n();
  const { dateTime } = useFormatters();

  if (!entries?.length) {
    return (
      <section className="public-section" aria-label={t('a11y.timelineRegion')}>
        <h2 className="public-section__title">{t('result.timelineTitle')}</h2>
        <div className="public-empty">
          <p className="public-empty__title">{t('result.timelineEmpty')}</p>
          <p className="public-empty__body">{t('result.timelineEmptyBody')}</p>
        </div>
      </section>
    );
  }

  return (
    <section className="public-section" aria-label={t('a11y.timelineRegion')}>
      <h2 className="public-section__title">{t('result.timelineTitle')}</h2>
      <ol className="public-timeline">
        {entries.map((entry, index) => (
          <li className="public-timeline__item" key={`${entry.status}-${entry.occurred_at}-${index}`}>
            <div className="public-timeline__marker" aria-hidden="true" />
            <div className="public-timeline__content">
              <p className="public-timeline__status">{t(`status.${entry.status}`)}</p>
              {/* A milestone recorded from an approved template is rendered here in the
                  language this reader chose, not the language the staff member was working
                  in. `message` is the server's own rendering and stays the fallback: free
                  text staff typed, or a template this build does not know (DEC-0084). */}
              <p className="public-timeline__message">
                {renderTemplate(entry.message_template_key, language) || entry.message}
              </p>
              <p className="public-timeline__meta">
                <time dateTime={entry.occurred_at}>{dateTime(entry.occurred_at, timezone)}</time>
                {entry.location?.city || entry.location?.country_code ? (
                  <>
                    {' · '}
                    <Place place={entry.location} fallback={t('result.unknownCity')} />
                  </>
                ) : null}
                {' · '}
                {t('freshness.sourceManual')}
              </p>
              {entry.package_references?.length > 1 ? (
                <p className="public-timeline__packages">
                  {t('result.appliesTo')}: {entry.package_references.join(', ')}
                </p>
              ) : null}
            </div>
          </li>
        ))}
      </ol>
    </section>
  );
}

function ResultView({ result }) {
  const { t } = usePublicI18n();
  const { dateTime, dateOnly } = useFormatters();
  const timezone = result.timezone;

  const progress = t(
    result.package_count_active === 1 ? 'progress.summaryOne' : 'progress.summaryMany',
    { delivered: result.package_count_delivered, active: result.package_count_active },
  );

  return (
    <div className="public-result">
      <DemoBanner dataMode={result.data_mode} />

      <section className="public-card" aria-label={t('a11y.resultRegion')}>
        {/* tabIndex -1 so focus can be moved here after a lookup; it is not in the
            tab order, so keyboard users are not made to step through it. */}
        <h1 className="public-title public-title--result" tabIndex={-1}>
          {t('result.summaryTitle')}
        </h1>

        <dl className="public-summary">
          <div className="public-summary__row">
            <dt>{t('result.shipmentId')}</dt>
            <dd>
              <CopyableReference value={result.shipment_reference} />
            </dd>
          </div>
          <div className="public-summary__row">
            <dt>{t('result.status')}</dt>
            <dd>
              <StatusBadge status={result.status} label={t(`status.${result.status}`)} />
            </dd>
          </div>
          <div className="public-summary__row">
            <dt>{t('result.route')}</dt>
            <dd>{t(`routes.${result.route_group}`)}</dd>
          </div>
          <div className="public-summary__row">
            <dt>{t('result.from')}</dt>
            <dd>
              <Place place={result.origin} fallback={t('result.unknownCity')} />
            </dd>
          </div>
          <div className="public-summary__row">
            <dt>{t('result.to')}</dt>
            <dd>
              <Place place={result.destination} fallback={t('result.unknownCity')} />
            </dd>
          </div>
          <div className="public-summary__row">
            <dt>{t('result.packages')}</dt>
            <dd>
              {progress}
              {result.package_count_cancelled > 0 ? (
                <span className="public-summary__note">
                  {' · '}
                  {t(
                    result.package_count_cancelled === 1
                      ? 'progress.cancelledCountOne'
                      : 'progress.cancelledCountMany',
                    { count: result.package_count_cancelled },
                  )}
                </span>
              ) : null}
            </dd>
          </div>

          {result.selected_package_reference ? (
            <div className="public-summary__row">
              <dt>{t('result.scannedPackage')}</dt>
              <dd>
                <span className="public-copyable__value">
                  {result.selected_package_reference}
                </span>
              </dd>
            </div>
          ) : null}

          {/* An estimate appears only when a real source supplied one, and always says
              so. Nothing here computes a transit time (CRM.md section 10). */}
          {result.estimated_delivery_at ? (
            <div className="public-summary__row">
              <dt>{t('result.estimatedDelivery')}</dt>
              <dd>
                <span className="public-badge public-badge--muted">
                  {t('result.estimatedBadge')}
                </span>{' '}
                {dateOnly(result.estimated_delivery_at, timezone)}
                <span className="public-summary__note"> {t('result.estimatedNote')}</span>
              </dd>
            </div>
          ) : null}

          {result.delivered_at ? (
            <div className="public-summary__row">
              <dt>{t('result.deliveredOn')}</dt>
              <dd>{dateTime(result.delivered_at, timezone)}</dd>
            </div>
          ) : null}

          {result.cancelled_at ? (
            <div className="public-summary__row">
              <dt>{t('result.cancelledOn')}</dt>
              <dd>{dateTime(result.cancelled_at, timezone)}</dd>
            </div>
          ) : null}
        </dl>
      </section>

      <SupportCallout
        status={result.status}
        trackingState={result.tracking_state}
        helpUrl={result.help_url}
      />

      <section className="public-card">
        <FreshnessNote
          trackingState={result.tracking_state}
          lastUpdateAt={result.last_public_update_at}
          formatDateTime={(value) => dateTime(value, timezone)}
        />
        {/* Master Tracking and Last Mile Tracking, each when it exists (2026-10-22). */}
        {carrierLinksOf(result).map((link, index, all) => (
          <CarrierLink key={link.tracking_name_key || index} link={link} showNote={index === all.length - 1} />
        ))}
      </section>

      <section className="public-card">
        <Timeline entries={result.timeline} timezone={timezone} />
      </section>

      <section className="public-card">
        <PackageList
          packages={result.packages}
          selectedReference={result.selected_package_reference}
        />
      </section>

      <div className="public-actions">
        <Link className="public-button public-button--secondary" to="/track">
          {t('result.trackAnother')}
        </Link>
        <PublicHelpLink helpUrl={result.help_url} className="public-help-link" />
      </div>
    </div>
  );
}

function ErrorView({ error, onRetry }) {
  const { t } = usePublicI18n();
  const kind = error instanceof PublicTrackingError ? error.kind : 'server';

  const copy = {
    // An invalid reference and an unknown one produce the same server response and the
    // same screen. The page never says "that format is wrong", because doing so would
    // tell a stranger which of their guesses are well formed.
    not_found: { title: t('errors.notFoundTitle'), body: t('errors.notFoundBody') },
    rate_limited: {
      title: t('errors.rateLimitedTitle'),
      body: error?.retryAfterSeconds
        ? t('errors.rateLimitedBody', { seconds: error.retryAfterSeconds })
        : t('errors.rateLimitedBodyGeneric'),
    },
    network: { title: t('errors.networkTitle'), body: t('errors.networkBody') },
    server: { title: t('errors.networkTitle'), body: t('errors.networkBody') },
  }[kind];

  return (
    <div className="public-card public-card--error">
      {/* `role="alert"` so the failure is announced rather than silently replacing the
          previous screen for somebody using a screen reader. */}
      <div role="alert">
        <h1 className="public-title" tabIndex={-1}>
          {copy.title}
        </h1>
        <p className="public-lede">{copy.body}</p>
      </div>
      <div className="public-actions">
        {kind !== 'not_found' ? (
          <button type="button" className="public-button public-button--primary" onClick={onRetry}>
            {t('errors.tryAgain')}
          </button>
        ) : null}
        <Link className="public-button public-button--secondary" to="/track">
          {t('result.trackAnother')}
        </Link>
      </div>
      <PublicHelpLink className="public-help-link" />
    </div>
  );
}

export function TrackResultPage() {
  const { t } = usePublicI18n();
  const { reference: rawReference } = useParams();
  const reference = useMemo(() => normalizeReference(rawReference), [rawReference]);

  const query = useQuery({
    // The key *is* the reference, so React Query can never serve one reference's result
    // under another. `gcTime: 0` on the client means nothing is retained after unmount.
    queryKey: ['public-tracking', reference],
    queryFn: ({ signal }) => fetchPublicTracking(reference, { signal }),
    enabled: Boolean(reference),
    retry: false,
    // No background refetch. This page does not claim to update itself, so it must not
    // quietly try to (CRM.md section 9).
    refetchOnWindowFocus: false,
    refetchOnMount: 'always',
    refetchInterval: false,
    staleTime: 0,
    gcTime: 0,
  });

  const shellRef = useRef(null);
  // Move focus to the heading of whichever state arrived, so a keyboard or screen-reader
  // user is not left at the top of a page whose content changed underneath them.
  //
  // The heading rather than the container: focusing a wrapper that spans the entire
  // result draws the focus ring around the whole page, which looks like a rendering
  // fault and tells a sighted keyboard user nothing about where they now are. This was
  // visible in the first screenshot pass.
  useEffect(() => {
    if (!query.isSuccess && !query.isError) return;
    const heading = shellRef.current?.querySelector('h1');
    heading?.focus();
  }, [query.isSuccess, query.isError, reference]);

  const retry = useCallback(() => query.refetch(), [query]);

  if (!reference) return <TrackResultMissingReference />;

  return (
    <div className="public-result-shell" ref={shellRef}>
      {query.isPending ? (
        <div className="public-card" role="status" aria-live="polite">
          <p className="public-lede">{t('a11y.loading')}</p>
        </div>
      ) : null}

      {/* A failed lookup renders the error and nothing else. The previous result is not
          held anywhere it could reappear. */}
      {query.isError ? <ErrorView error={query.error} onRetry={retry} /> : null}

      {query.isSuccess && !query.isError ? <ResultView result={query.data} /> : null}
    </div>
  );
}

function TrackResultMissingReference() {
  const { t } = usePublicI18n();
  return (
    <div className="public-card public-card--error">
      <h1 className="public-title">{t('errors.notFoundTitle')}</h1>
      <p className="public-lede">{t('errors.notFoundBody')}</p>
      <Link className="public-button public-button--secondary" to="/track">
        {t('result.trackAnother')}
      </Link>
    </div>
  );
}
