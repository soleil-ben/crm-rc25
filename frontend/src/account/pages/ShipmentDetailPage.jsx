/**
 * One shipment.
 *
 * Renders the **25 fields** of `AccountShipmentDetail` and nothing else: the 24 Public
 * Tracking also has, and the customer's own booking reference (UAT round 12, DEC-0163),
 * shown first in "Where it is" at every width. The only request
 * this screen makes is `GET /api/v1/account/shipments/{reference}`:
 *
 * * it does **not** call the staff shipment endpoint, which would return internal notes,
 *   money and the owning staff member;
 * * it does **not** fall back to `GET /api/v1/public/track/{reference}` when the
 *   authenticated call refuses. A public lookup as a workaround would mean a customer who
 *   is *not* authorised for a shipment sees it anyway because they know its reference,
 *   which is exactly the claim-by-reference path OD-29 forbids.
 *
 * ## Unknown and unauthorised look identical
 *
 * The server answers both with the same 404 body, and this screen renders one page for
 * it. There is no branch that could tell them apart, because there is nothing in the
 * response to branch on.
 *
 * ## What is deliberately not here
 *
 * No barcode. A screen barcode would be a convenience and a new disclosure surface — it
 * encodes the reference into an image a photograph carries off the screen — and nothing
 * asked for one. No freshness claim: nothing here says "updated 2 minutes ago", because
 * no provider is connected and the only honest statement is the timestamp of the last
 * public update, which is shown as a date. No linked return workflow while OD-22 is open.
 */

import { useEffect, useRef } from 'react';
import { Link, useParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { AccountPageHeader } from '../AccountLayout.jsx';
import {
  Button,
  Card,
  CarrierLink,
  DetailRow,
  EmptyState,
  Flag,
  Loading,
  Notice,
  StatusPill,
} from '../components.jsx';
import { AccountApiError, accountApi } from '../accountApi.js';
import { useAccountSession } from '../AccountSession.jsx';
import {
  useAccountErrorText,
  useAccountFormat,
  useAccountT,
  useServerLabel,
} from '../i18n.jsx';
import { renderTemplate } from '../../shared/publicUpdateTemplates.js';

/**
 * How each `tracking_state` reads to a customer.
 *
 * A closed map over the response's own enum. A state that is not in it falls back to a
 * sentence that claims nothing, rather than to the raw value — a customer should never
 * read `no_public_milestones`.
 */
const TRACKING_STATE_TEXT = {
  manual_updates: 'detail.trackingManual',
  external_link_only: 'detail.trackingExternal',
  no_public_milestones: 'detail.trackingNone',
  tracking_unavailable: 'detail.trackingUnavailable',
  cancelled: 'detail.trackingCancelled',
  demo: 'detail.trackingDemo',
};

/** The event types with a standard sentence in the account catalogue (`detail.event.*`). */
const STANDARD_EVENT_TYPES = new Set([
  'booked',
  'awaiting_parcel',
  'received_at_solaris',
  'processing',
  'departed_origin',
  'in_transit',
  'customs_processing',
  'arrived_destination',
  'out_for_delivery',
  'delivered_to_collection_point',
  'delivered_to_recipient',
  'delivery_attempted',
  'exception',
  'return_in_progress',
  'returned',
]);

/**
 * One timeline entry's words (Phase 15 stand-in): the standard sentence for the event's type
 * in the customer's language (the parcel's sentence when the entry's `scope` is `package`), and beneath it what the staff published -- a standard update
 * rendered in the same language, or the sentence they typed. The published text is left out
 * when it says exactly what the standard sentence already says.
 */
export function TimelineWording({ entry }) {
  const t = useAccountT();
  const { locale } = useAccountFormat();
  // A step on some, not all, of several parcels reads as a parcel's step (AC-7): one parcel
  // of three delivered is not "your shipment has been delivered".
  const type = entry.event_type;
  let standard = t('detail.eventFallback');
  if (STANDARD_EVENT_TYPES.has(type)) {
    standard =
      entry.scope === 'package' ? t(`detail.eventPackage.${type}`) : t(`detail.event.${type}`);
  }
  const published =
    (entry.message_template_key && renderTemplate(entry.message_template_key, locale)) ||
    entry.message ||
    '';
  const showPublished = published.trim() !== '' && published.trim() !== standard.trim();
  return (
    <>
      <p className="ca-timeline__message">{standard}</p>
      {showPublished ? (
        <p className="ca-timeline__note">
          <span className="ca-visually-hidden">{t('detail.staffNote')}: </span>
          {published}
        </p>
      ) : null}
    </>
  );
}

export function ShipmentDetailPage() {
  const { reference } = useParams();
  const session = useAccountSession();
  const headingRef = useRef(null);
  const t = useAccountT();
  const label = useServerLabel();
  const { formatDate, formatDateTime, placeLine, packageSummary, notRecorded, locale } =
    useAccountFormat();

  const query = useQuery({
    queryKey: ['account', 'shipment', reference],
    queryFn: ({ signal }) => accountApi.shipment(reference, { signal }),
  });

  // Focus moves to the page heading once the shipment (or the reason it cannot be shown)
  // has rendered. A person arrives here from a link in the list, and that link is gone
  // from the page, so without this a keyboard user is left at the top of the document
  // with nothing announced, or, worse, at the end of the page the list used to be.
  const settled = !query.isPending;
  useEffect(() => {
    if (settled) headingRef.current?.focus();
  }, [settled, reference]);

  if (query.isPending) {
    return (
      <div className="ca-wide">
        <Loading label={t('detail.loading')} />
      </div>
    );
  }

  if (query.error) {
    return (
      <DetailError
        error={query.error}
        onRetry={() => query.refetch()}
        session={session}
        headingRef={headingRef}
      />
    );
  }

  const shipment = query.data;
  const tz = shipment.timezone;

  return (
    <div className="ca-wide">
      <p className="ca-breadcrumb">
        <Link to="/account/shipments">{t('detail.back')}</Link>
      </p>

      <AccountPageHeader
        title={shipment.shipment_reference}
        intro={label('route', shipment.route_group, shipment.route_label)}
        headingRef={headingRef}
      />

      {shipment.cancelled_at ? (
        <Notice tone="info" title={t('detail.cancelledTitle')}>
          <p>{t('detail.cancelledBody', { date: formatDate(shipment.cancelled_at, tz) })}</p>
        </Notice>
      ) : null}

      <Card title={t('detail.whereItIs')} headingLevel="h2">
        <p className="ca-detail-status">
          <StatusPill
            status={shipment.status}
            label={label('status', shipment.status, shipment.status_label)}
          />
        </p>
        {/* The progress summary is the server's sentence, and it is the text equivalent
            of the package counts beside it. Nothing here is a bar with no words. In
            Vietnamese the same sentence is built from the counts, because the server's is
            English. */}
        <p className="ca-detail-progress">
          {locale === 'en'
            ? shipment.progress_summary
            : t('detail.progressSummary', {
                delivered: shipment.package_count_delivered,
                active: shipment.package_count_active,
              })}
        </p>
        <p className="ca-detail-progress">
          {packageSummary({
            active: shipment.package_count_active,
            cancelled: shipment.package_count_cancelled,
            delivered: shipment.package_count_delivered,
          })}
        </p>

        <dl className="ca-detail-grid">
          {/* The same value and words as the list row (DEC-0160, DEC-0163). */}
          <DetailRow label={t('format.bookingReference')}>
            {shipment.booking_reference || notRecorded}
          </DetailRow>
          <DetailRow label={t('detail.from')}>{placeLine(shipment.origin)}</DetailRow>
          <DetailRow label={t('detail.to')}>{placeLine(shipment.destination)}</DetailRow>
          <DetailRow label={t('detail.estimatedDelivery')}>
            {formatDate(shipment.estimated_delivery_at, tz) || notRecorded}
          </DetailRow>
          <DetailRow label={t('detail.delivered')}>
            {formatDate(shipment.delivered_at, tz) || notRecorded}
          </DetailRow>
          <DetailRow label={t('detail.lastUpdate')}>
            {formatDate(shipment.last_public_update_at, tz) || notRecorded}
          </DetailRow>
          <DetailRow label={t('detail.datesShownIn')}>{tz}</DetailRow>
        </dl>

        <p className="ca-detail-tracking">
          {t(TRACKING_STATE_TEXT[shipment.tracking_state] || 'detail.trackingNone')}
        </p>

        {/* One link per generic tracking name, in leg order (2026-10-22). */}
        {(shipment.carrier_links?.length
          ? shipment.carrier_links
          : shipment.carrier_link
            ? [shipment.carrier_link]
            : []
        ).map((link, index) => (
          <p className="ca-detail-carrier" key={link.tracking_name_key || index}>
            <CarrierLink href={link.url} trackingNameKey={link.tracking_name_key} />
          </p>
        ))}
      </Card>

      <Card title={t('detail.packages')} headingLevel="h2">
        {shipment.packages.length === 0 ? (
          <EmptyState title={t('detail.noPackages')} />
        ) : (
          <ul className="ca-packages">
            {shipment.packages.map((pkg) => (
              <li
                key={pkg.package_reference}
                className={`ca-package${pkg.is_selected ? ' ca-package--selected' : ''}`}
              >
                <p className="ca-package__reference">{pkg.package_reference}</p>
                <p className="ca-package__status">
                  <StatusPill status={pkg.status} label={label('status', pkg.status, pkg.status_label)} />
                </p>
                {pkg.is_cancelled ? <Flag>{t('detail.cancelled')}</Flag> : null}
                {pkg.delivered_at ? (
                  <p className="ca-package__date">
                    {t('detail.deliveredOn', { date: formatDate(pkg.delivered_at, tz) })}
                  </p>
                ) : null}
              </li>
            ))}
          </ul>
        )}
      </Card>

      <Card title={t('detail.updates')} headingLevel="h2">
        {shipment.timeline.length === 0 ? (
          <EmptyState
            title={t('detail.noUpdatesTitle')}
            body={t('detail.noUpdatesBody')}
          />
        ) : (
          <ol className="ca-timeline">
            {shipment.timeline.map((entry, index) => (
              <li
                key={`${entry.occurred_at}-${entry.status}-${index}`}
                className="ca-timeline__entry"
              >
                <p className="ca-timeline__when">{formatDateTime(entry.occurred_at, tz)}</p>
                <p className="ca-timeline__status">
                  <StatusPill
                    status={entry.status}
                    label={label('status', entry.status, entry.status_label)}
                  />
                </p>
                {/* Phase 15: the standard wording for the event's type in the reader's
                    language, then the staff's published text beneath it when it adds
                    something. Only approved public wording: a timeline entry never carries
                    internal detail, the recording staff member, the internal event id or
                    the leg (SHIPMENT_ALLOWLISTS.md §4). */}
                <TimelineWording entry={entry} />
                {entry.location ? (
                  <p className="ca-timeline__where">{placeLine(entry.location)}</p>
                ) : null}
                {entry.package_references.length > 0 ? (
                  <p className="ca-timeline__packages">
                    {t('detail.timelinePackages', { list: entry.package_references.join(', ') })}
                  </p>
                ) : null}
              </li>
            ))}
          </ol>
        )}
      </Card>

      {/* Configured help behaviour: the link appears when the organization has configured
          one and is absent otherwise. Nothing is invented and no default URL is shipped. */}
      {shipment.help_url ? (
        <Card title={t('detail.needHelp')} headingLevel="h2">
          <p>
            <a
              href={shipment.help_url}
              target="_blank"
              rel="noopener noreferrer"
              referrerPolicy="no-referrer"
            >
              {t('common.contactSolaris')}
              <span className="ca-carrier-link__note">{t('common.opensInNewTab')}</span>
            </a>
          </p>
        </Card>
      ) : null}
    </div>
  );
}

/**
 * The failure screens.
 *
 * The 404 is the important one: it is the answer for a reference that does not exist, one
 * that is malformed, one that belongs to somebody else, and one that is a draft. It says
 * the same thing for all four, and there is nothing in the response that would let it say
 * anything else.
 */
function DetailError({ error, onRetry, session, headingRef }) {
  const t = useAccountT();
  const errorText = useAccountErrorText();
  if (error instanceof AccountApiError && error.isNotFound) {
    return (
      <div className="ca-wide">
        <p className="ca-breadcrumb">
          <Link to="/account/shipments">{t('detail.back')}</Link>
        </p>
        <AccountPageHeader title={t('detail.notFoundTitle')} headingRef={headingRef} />
        <Card>
          <Notice tone="info" title={t('detail.notFoundNotice')}>
            <p>{errorText(error)}</p>
          </Notice>
          <p>{t('detail.notFoundBody')}</p>
        </Card>
      </div>
    );
  }

  if (error instanceof AccountApiError && error.isSignedOut) {
    return (
      <div className="ca-wide">
        <AccountPageHeader title={t('detail.sessionTitle')} headingRef={headingRef} />
        <Card>
          <Notice tone="warning" title={t('detail.sessionNotice')}>
            <p>{t('detail.nothingLost')}</p>
          </Notice>
          <ul className="ca-links">
            <li>
              <Link to="/account/sign-in">{t('common.signIn')}</Link>
            </li>
          </ul>
        </Card>
      </div>
    );
  }

  if (error instanceof AccountApiError && error.isRateLimited) {
    return (
      <div className="ca-wide">
        <AccountPageHeader title={t('detail.tooManyTitle')} headingRef={headingRef} />
        <Card>
          <Notice tone="warning" title={t('detail.tooManyNotice')}>
            <p>
              {error.retryAfterSeconds
                ? t('detail.trySeconds', { seconds: error.retryAfterSeconds })
                : t('detail.tryMoment')}
            </p>
          </Notice>
          <div className="ca-form__actions">
            <Button variant="secondary" onClick={onRetry}>
              {t('common.tryAgain')}
            </Button>
          </div>
        </Card>
      </div>
    );
  }

  if (error instanceof AccountApiError && error.isRefused) {
    return (
      <div className="ca-wide">
        <AccountPageHeader title={t('detail.refusedTitle')} headingRef={headingRef} />
        <Card>
          <Notice tone="info" title={t('list.historyUnavailable')}>
            <p>{errorText(error)}</p>
          </Notice>
          <div className="ca-form__actions">
            <Button variant="secondary" onClick={() => session.refresh()}>
              {t('common.checkAgain')}
            </Button>
          </div>
        </Card>
      </div>
    );
  }

  return (
    <div className="ca-wide">
      <AccountPageHeader title={t('detail.loadFailedTitle')} headingRef={headingRef} />
      <Card>
        <Notice tone="error" title={t('detail.loadFailedNotice')}>
          <p>{errorText(error)}</p>
        </Notice>
        <div className="ca-form__actions">
          <Button variant="secondary" onClick={onRetry}>
            {t('common.tryAgain')}
          </Button>
        </div>
      </Card>
    </div>
  );
}
