/**
 * My shipments.
 *
 * Renders the **18 fields** of `AccountShipmentListItem` and nothing else. The list is
 * the response; there is no second request, no enrichment, and no field derived from a
 * value the response does not carry. In particular there is no carrier tracking number
 * (the list response has none), no recipient name, email, phone or street, no money of
 * any kind, no staff note, no internal operational state, no provider freshness and no
 * integration status. `tests/accountShipmentList.test.jsx` plants sentinels in a response
 * and asserts none of them reaches the DOM.
 *
 * ## Filters
 *
 * A keyword search (`q`: part of a Solaris Shipment ID, package reference, booking
 * reference or city, any case or accents, UAT rounds 10 and 11, DEC-0156, DEC-0161),
 * status group, booking-date range and exact route group (OD-41). Every one of them is
 * **reflected in the URL**, so a filtered view can be bookmarked, shared with staff on a
 * call, and survives a refresh. The URL is the single
 * source of truth for filter state: there is no parallel React state that could disagree
 * with the address bar after a Back. A link from before round 10 carrying the exact
 * `reference` filter opens as that keyword, which finds the same shipment.
 *
 * ## Layout
 *
 * A table at wide widths and cards below 768 px, from one array. Each row and each card
 * shows the customer's own booking reference (UAT round 11, DEC-0160), so a shipment found
 * by it says why; under the Solaris Shipment ID on the table, as the first full-width fact
 * on a card. Both are keyboard operable, and neither wraps a row in a `<div onClick>`:
 * the reference is a real link, which is what gives a row its accessible name, its
 * context menu, and its behaviour under Ctrl-click.
 *
 * ## What a screen may not do
 *
 * Filter for privacy. Every row here is one the server's ownership clause returned; the
 * screen never removes a row it does not like the look of, because a screen that hides a
 * row is a courtesy and never a boundary.
 */

import { useEffect, useRef, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { AccountPageHeader } from '../AccountLayout.jsx';
import {
  Button,
  Card,
  EmptyState,
  Field,
  Flag,
  Loading,
  Notice,
  Pagination,
  SelectInput,
  StatusPill,
  TextInput,
} from '../components.jsx';
import { AccountApiError, accountApi } from '../accountApi.js';
import { useAccountSession } from '../AccountSession.jsx';
import { BOOKING_REFERENCE_LABEL } from '../format.js';
import {
  englishT,
  useAccountErrorText,
  useAccountFormat,
  useAccountT,
  useServerLabel,
} from '../i18n.jsx';

/** The four status groups (`customer_account_shipment_service.STATUS_GROUPS`). */
const STATUS_GROUPS = [
  { value: 'in_progress', labelKey: 'list.statusInProgress' },
  { value: 'delivered', labelKey: 'list.statusDelivered' },
  { value: 'exception', labelKey: 'list.statusException' },
  { value: 'cancelled', labelKey: 'list.statusCancelled' },
];

/** The route vocabulary (`app/core/enums.py::RouteGroup`). */
const ROUTE_GROUPS = [
  { value: 'CAV', labelKey: 'route.CAV' },
  { value: 'VCA', labelKey: 'route.VCA' },
  { value: 'CAD', labelKey: 'route.CAD' },
  { value: 'XUS', labelKey: 'route.XUS' },
];

const PAGE_SIZE = 20;

/** The server's bound (`MAX_KEYWORD_LENGTH`), so the box cannot ask for a 422. */
const KEYWORD_MAX_LENGTH = 64;

/** The English hint, which the tests compare against; the screen renders `list.searchHint`. */
export const SEARCH_HINT = englishT('list.searchHint');

export { BOOKING_REFERENCE_LABEL };

/** Only these keys are read from, or written to, the query string. */
const FILTER_KEYS = ['q', 'status_group', 'route_group', 'booked_from', 'booked_to'];

function readFilters(searchParams) {
  const filters = {};
  FILTER_KEYS.forEach((key) => {
    const value = searchParams.get(key);
    if (value) filters[key] = value;
  });
  // A pre-round-10 link: its whole Solaris Shipment ID still finds that shipment as a keyword.
  const legacyReference = searchParams.get('reference');
  if (!filters.q && legacyReference) filters.q = legacyReference;
  return filters;
}

export function ShipmentListPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const session = useAccountSession();
  const filters = readFilters(searchParams);
  const offset = Number.parseInt(searchParams.get('offset') || '0', 10) || 0;
  const resultsRef = useRef(null);
  const t = useAccountT();
  const options = (list) => list.map(({ value, labelKey }) => ({ value, label: t(labelKey) }));

  // The form's own copy, so typing in the search box does not fire a request per
  // keystroke — which would be a request per keystroke against a rate-limited endpoint.
  // It is seeded from the URL and re-seeded whenever the URL changes, so Back and a
  // pasted link both refill the controls correctly.
  const [draft, setDraft] = useState(filters);
  useEffect(() => {
    setDraft(readFilters(searchParams));
  }, [searchParams]);

  const query = useQuery({
    queryKey: ['account', 'shipments', filters, offset],
    queryFn: ({ signal }) =>
      accountApi.shipments({ ...filters, limit: PAGE_SIZE, offset }, { signal }),
  });

  function applyFilters(next, { keepOffset = false } = {}) {
    const params = new URLSearchParams();
    FILTER_KEYS.forEach((key) => {
      const value = (next[key] || '').trim();
      if (value) params.set(key, value);
    });
    // A new filter means a new first page. Keeping the offset would show page three of a
    // result that now has one page, which reads as an empty list.
    if (keepOffset && offset) params.set('offset', String(offset));
    setSearchParams(params, { replace: false });
  }

  function onSubmit(event) {
    event.preventDefault();
    applyFilters(draft);
  }

  function clearFilters() {
    setSearchParams(new URLSearchParams(), { replace: false });
  }

  function goToOffset(nextOffset) {
    const params = new URLSearchParams(searchParams);
    if (nextOffset > 0) params.set('offset', String(nextOffset));
    else params.delete('offset');
    setSearchParams(params, { replace: false });
    // Focus the results region so a keyboard user is not returned to the top of the
    // document after paging.
    resultsRef.current?.focus();
  }

  const hasFilters = Object.keys(filters).length > 0;
  const page = query.data;
  const error = query.error;

  return (
    <div className="ca-wide">
      <AccountPageHeader
        title={t('list.title')}
        intro={t('list.intro')}
      />

      <Card title={t('list.find')} headingLevel="h2">
        <form className="ca-filters" onSubmit={onSubmit}>
          <Field label={t('list.search')} optional hint={t('list.searchHint')}>
            {({ id, describedBy }) => (
              <TextInput
                id={id}
                describedBy={describedBy}
                type="search"
                name="q"
                maxLength={KEYWORD_MAX_LENGTH}
                autoComplete="off"
                autoCapitalize="none"
                spellCheck="false"
                enterKeyHint="search"
                value={draft.q || ''}
                onChange={(event) => setDraft({ ...draft, q: event.target.value })}
              />
            )}
          </Field>

          <Field label={t('list.status')} optional>
            {({ id, describedBy }) => (
              <SelectInput
                id={id}
                describedBy={describedBy}
                options={options(STATUS_GROUPS)}
                placeholder={t('list.anyStatus')}
                value={draft.status_group || ''}
                onChange={(event) => setDraft({ ...draft, status_group: event.target.value })}
              />
            )}
          </Field>

          <Field label={t('list.route')} optional>
            {({ id, describedBy }) => (
              <SelectInput
                id={id}
                describedBy={describedBy}
                options={options(ROUTE_GROUPS)}
                placeholder={t('list.anyRoute')}
                value={draft.route_group || ''}
                onChange={(event) => setDraft({ ...draft, route_group: event.target.value })}
              />
            )}
          </Field>

          <Field label={t('list.bookedFrom')} optional>
            {({ id, describedBy }) => (
              <TextInput
                id={id}
                describedBy={describedBy}
                type="date"
                name="booked_from"
                value={draft.booked_from || ''}
                onChange={(event) => setDraft({ ...draft, booked_from: event.target.value })}
              />
            )}
          </Field>

          <Field label={t('list.bookedTo')} optional>
            {({ id, describedBy }) => (
              <TextInput
                id={id}
                describedBy={describedBy}
                type="date"
                name="booked_to"
                value={draft.booked_to || ''}
                onChange={(event) => setDraft({ ...draft, booked_to: event.target.value })}
              />
            )}
          </Field>

          <div className="ca-filters__actions">
            <Button type="submit">{t('list.apply')}</Button>
            <Button variant="secondary" onClick={clearFilters} disabled={!hasFilters}>
              {t('list.clear')}
            </Button>
          </div>
        </form>
      </Card>

      {/*
        The results region is a live region, so the outcome of applying a filter is
        announced. `tabIndex={-1}` lets paging move focus here.
      */}
      <div
        className="ca-results"
        ref={resultsRef}
        tabIndex={-1}
        aria-live="polite"
        aria-busy={query.isFetching || undefined}
      >
        {query.isPending ? <Loading label={t('list.loading')} /> : null}

        {error ? <ListError error={error} onRetry={() => query.refetch()} session={session} /> : null}

        {page && page.items.length === 0 ? (
          hasFilters ? (
            <Card>
              <EmptyState
                title={t('list.noMatchTitle')}
                body={t('list.noMatchBody')}
                action={
                  <Button variant="secondary" onClick={clearFilters}>
                    {t('list.clear')}
                  </Button>
                }
              />
            </Card>
          ) : (
            <Card>
              <EmptyState
                title={t('list.emptyTitle')}
                body={t('list.emptyBody')}
              />
            </Card>
          )
        ) : null}

        {page && page.items.length > 0 ? (
          <>
            <ShipmentTable items={page.items} timezone={page.timezone} />
            <ShipmentCards items={page.items} timezone={page.timezone} />
            <Pagination
              total={page.total}
              limit={page.limit}
              offset={page.offset}
              onChange={goToOffset}
            />
          </>
        ) : null}
      </div>
    </div>
  );
}

/**
 * Every failure this screen can show, and they are different screens rather than one
 * "something went wrong".
 *
 * A 401 is not an error to retry — the session has gone, and the honest thing is to say so
 * and offer sign-in. A 429 says when to come back. A 422 is a filter the server would not
 * accept, and it names the field so the person can correct it.
 */
function ListError({ error, onRetry, session }) {
  const t = useAccountT();
  const errorText = useAccountErrorText();
  if (error instanceof AccountApiError && error.isSignedOut) {
    return (
      <Card>
        <Notice tone="warning" title={t('list.sessionEnded')}>
          <p>{t('list.sessionEndedBody')}</p>
        </Notice>
        <ul className="ca-links">
          <li>
            <Link to="/account/sign-in">{t('common.signIn')}</Link>
          </li>
        </ul>
      </Card>
    );
  }

  if (error instanceof AccountApiError && error.isRateLimited) {
    return (
      <Card>
        <Notice tone="warning" title={t('list.tooMany')}>
          <p>
            {error.retryAfterSeconds
              ? t('list.waitSeconds', { seconds: error.retryAfterSeconds })
              : t('list.waitMoment')}
          </p>
        </Notice>
        <div className="ca-form__actions">
          <Button variant="secondary" onClick={onRetry}>
            {t('common.tryAgain')}
          </Button>
        </div>
      </Card>
    );
  }

  if (error instanceof AccountApiError && error.isRefused) {
    // Pending approval, a revoked link, an archived or merged linked customer — one
    // sentence from the server, rendered as it arrived. The session is re-read because
    // the state that produced this may have changed the shell too.
    return (
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
    );
  }

  if (error instanceof AccountApiError && error.isValidation) {
    return (
      <Card>
        <Notice tone="error" title={t('list.badFilters')}>
          <p>{errorText(error)}</p>
        </Notice>
      </Card>
    );
  }

  return (
    <Card>
      <Notice tone="error" title={t('list.loadFailed')}>
        <p>{errorText(error)}</p>
      </Notice>
      <div className="ca-form__actions">
        <Button variant="secondary" onClick={onRetry}>
          {t('common.tryAgain')}
        </Button>
      </div>
    </Card>
  );
}

/** The wide-screen table. Hidden below 768 px by CSS, not unmounted. */
function ShipmentTable({ items, timezone }) {
  const t = useAccountT();
  const label = useServerLabel();
  const { formatDate, cityCountryLine, packageSummary, notRecorded } = useAccountFormat();
  return (
    <div className="ca-table-wrap">
      <table className="ca-table">
        <caption className="ca-visually-hidden">{t('list.caption')}</caption>
        <thead>
          <tr>
            <th scope="col">{t('list.colShipment')}</th>
            <th scope="col">{t('list.colBooked')}</th>
            <th scope="col">{t('list.colRoute')}</th>
            <th scope="col">{t('list.colFrom')}</th>
            <th scope="col">{t('list.colTo')}</th>
            <th scope="col">{t('list.colStatus')}</th>
            <th scope="col">{t('list.colPackages')}</th>
            <th scope="col">{t('list.colLastUpdate')}</th>
          </tr>
        </thead>
        <tbody>
          {items.map((item) => (
            <tr key={item.shipment_reference}>
              <th scope="row" className="ca-table__reference">
                <Link to={`/account/shipments/${encodeURIComponent(item.shipment_reference)}`}>
                  {item.shipment_reference}
                </Link>
                <span className="ca-table__sub ca-table__booking-reference">
                  {t('format.bookingReference')}: {item.booking_reference || notRecorded}
                </span>
                <RowFlags item={item} />
              </th>
              <td>{formatDate(item.booked_at, timezone) || notRecorded}</td>
              <td>{label('route', item.route_group, item.route_label)}</td>
              <td>{cityCountryLine(item.origin_city, item.origin_country_code)}</td>
              <td>{cityCountryLine(item.destination_city, item.destination_country_code)}</td>
              <td>
                <StatusPill
                  status={item.status}
                  label={label('status', item.status, item.status_label)}
                />
                <DatesUnderStatus item={item} timezone={timezone} />
              </td>
              <td>
                {packageSummary({
                  active: item.package_count_active,
                  cancelled: item.package_count_cancelled,
                })}
              </td>
              <td>{formatDate(item.last_public_update_at, timezone) || notRecorded}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** The narrow-screen cards. Shown below 768 px by CSS. */
function ShipmentCards({ items, timezone }) {
  const t = useAccountT();
  const label = useServerLabel();
  const { formatDate, cityCountryLine, packageSummary, notRecorded } = useAccountFormat();
  return (
    <ul className="ca-cards">
      {items.map((item) => (
        <li key={item.shipment_reference} className="ca-shipment-card">
          <h3 className="ca-shipment-card__reference">
            <Link to={`/account/shipments/${encodeURIComponent(item.shipment_reference)}`}>
              {item.shipment_reference}
            </Link>
          </h3>
          <RowFlags item={item} />
          <p className="ca-shipment-card__status">
            <StatusPill status={item.status} label={label('status', item.status, item.status_label)} />
          </p>
          <dl className="ca-shipment-card__facts">
            <div className="ca-shipment-card__fact--wide">
              <dt>{t('format.bookingReference')}</dt>
              <dd>{item.booking_reference || notRecorded}</dd>
            </div>
            <div>
              <dt>{t('list.colBooked')}</dt>
              <dd>{formatDate(item.booked_at, timezone) || notRecorded}</dd>
            </div>
            <div>
              <dt>{t('list.colRoute')}</dt>
              <dd>{label('route', item.route_group, item.route_label)}</dd>
            </div>
            <div>
              <dt>{t('list.colFrom')}</dt>
              <dd>{cityCountryLine(item.origin_city, item.origin_country_code)}</dd>
            </div>
            <div>
              <dt>{t('list.colTo')}</dt>
              <dd>{cityCountryLine(item.destination_city, item.destination_country_code)}</dd>
            </div>
            <div>
              <dt>{t('list.colPackages')}</dt>
              <dd>
                {packageSummary({
                  active: item.package_count_active,
                  cancelled: item.package_count_cancelled,
                })}
              </dd>
            </div>
            <div>
              <dt>{t('list.colLastUpdate')}</dt>
              <dd>{formatDate(item.last_public_update_at, timezone) || notRecorded}</dd>
            </div>
            {item.delivered_at ? (
              <div>
                <dt>{t('list.delivered')}</dt>
                <dd>{formatDate(item.delivered_at, timezone)}</dd>
              </div>
            ) : null}
            {item.cancelled_at ? (
              <div>
                <dt>{t('list.cancelled')}</dt>
                <dd>{formatDate(item.cancelled_at, timezone)}</dd>
              </div>
            ) : null}
          </dl>
        </li>
      ))}
    </ul>
  );
}

/**
 * `is_cancelled` and `is_rebooked`, as words.
 *
 * Both are booleans in the response and both are facts the shipper should see. The
 * rebooked flag says the shipment was replaced and deliberately does **not** name the
 * replacement: the response does not carry its reference, because linking the two would
 * be a second disclosure decision (`SHIPMENT_ALLOWLISTS.md` §5).
 */
function RowFlags({ item }) {
  const t = useAccountT();
  if (!item.is_cancelled && !item.is_rebooked) return null;
  return (
    <p className="ca-flags">
      {item.is_cancelled ? <Flag>{t('list.cancelled')}</Flag> : null}
      {item.is_rebooked ? <Flag>{t('list.rebooked')}</Flag> : null}
    </p>
  );
}

/** Delivered and cancelled dates, shown under the status in the table. */
function DatesUnderStatus({ item, timezone }) {
  const t = useAccountT();
  const { formatDate } = useAccountFormat();
  if (item.delivered_at) {
    return (
      <span className="ca-table__sub">
        {t('list.deliveredOn', { date: formatDate(item.delivered_at, timezone) })}
      </span>
    );
  }
  if (item.cancelled_at) {
    return (
      <span className="ca-table__sub">
        {t('list.cancelledOn', { date: formatDate(item.cancelled_at, timezone) })}
      </span>
    );
  }
  return null;
}
