"""Authenticated Customer Account shipment history. The queries, and the allowlists.

This module decides what a signed-in customer may see about their own shipments. It is
separate from ``shipment_service`` for the reason ``public_tracking_service`` is separate
from it, and separate from ``public_tracking_service`` for a reason of its own: the two
answer to different authorizations and will diverge, and a shared builder is a shared
builder one of them eventually has to change.

Five rules shape everything below.

**Ownership is in the SQL.** The list is constrained by
``shipments.customer_id = <the effective linked customer>`` in the ``WHERE`` clause; the
detail re-checks the same equality on the loaded row. Nothing is filtered after loading and
nothing is filtered in a screen. The linked customer comes from
``customer_account_link_policy.resolve_readable_customer`` -- the established helper -- and
from nowhere else: not from an email, a phone number, recipient data, address similarity,
possession of a reference, a customer id in a query string, a proposal, an audit row, or a
carrier tracking number (OD-29, OD-30, T-03, T-04).

**One inclusion rule.** ``customer_account_disclosure_service.qualifying_conditions`` is the
OD-29 definition, and the staff disclosure preview counts rows with the same call. The
number a reviewer acknowledged and the rows a customer can read cannot drift apart because
there is only one definition to drift.

**One failure.** A malformed reference, an unknown one, another customer's, a merged or
alias identifier, and an ineligible one all raise the same error with the same status, body
and headers. Which of them happened is not observable from outside (T-03, T-16, T-17).

**Allowlist, not exclusion.** Both results are built field by field. No ORM object is
serialized, no public or staff schema is reused as the response, and there is no
``**row.__dict__`` anywhere in this file.

**No per-row queries, and no writes.** The list runs a bounded number of statements
whatever the page size: a count, a page of rows, and two grouped aggregates. Nothing in
this module writes anything, to any table -- there is no repair path, no link retargeting,
and no lazily created settings row.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from sqlalchemy import Select, and_, exists, func, or_, select
from sqlalchemy.orm import Session

from app.core.config import settings as app_settings
from app.core.enums import (
    ROUTE_GROUP_LABELS,
    BookingState,
    OperationalState,
    RouteGroup,
    value_label,
)
from app.core.normalization import SEARCH_FOLD_SQL_NAME, search_fold
from app.core.public_reference import parse_public_reference
from app.core.time_utils import period_bounds
from app.models import Customer, Shipment, ShipmentEvent, ShipmentPackage
from app.schemas.account_shipments import (
    AccountCarrierLink,
    AccountDataMode,
    AccountPackage,
    AccountPlace,
    AccountShipmentDetail,
    AccountShipmentListItem,
    AccountShipmentListPage,
    AccountTimelineEntry,
    AccountTrackingState,
)
from app.services import package_service, public_tracking_service
from app.services import public_update_templates as templates
from app.services.customer_account_disclosure_service import qualifying_conditions
from app.services.errors import NotFoundError, ValidationError

logger = logging.getLogger("solaris.account_shipments")

#: The single customer-facing failure message for a shipment that cannot be returned. Used
#: for every unsuccessful lookup, so "there is no such shipment" and "that shipment is
#: somebody else's" are one sentence. Deliberately does **not** say "your" -- a possessive
#: invites the reader to conclude that the shipment exists and belongs to someone.
GENERIC_NOT_FOUND = "We could not find that shipment. Check the Solaris Shipment ID and try again."

#: English country names for the lanes in scope, matching what the public page publishes.
#: An unrecognized code falls back to the code rather than to an invented name.
_COUNTRY_NAMES = {"CA": "Canada", "VN": "Vietnam", "US": "United States"}


# --- Filters ------------------------------------------------------------------
#
# `SHIPMENT_ALLOWLISTS.md` §3.2 approves status group, date range, exact reference and
# exact route group, and §3.4 (UAT round 10, DEC-0156) one keyword search over four fixed
# columns and, since UAT round 11 (DEC-0161), the shipment's own package references.
# There is still no recipient search, no carrier-tracking-number search, no sort
# parameter, and no field the caller can name -- the searched columns and the ordering are
# fixed below and are not addressable, so there is no column-injection surface to defend.


#: Status groups, over ``shipments.operational_state``. The specification names "status
#: group" and defines no vocabulary, so this is Phase 11's, recorded as DEC-0113: a closed
#: set, each member a question a shipper actually asks, and every operational state
#: belonging to exactly one group so the four are a partition rather than four overlapping
#: filters.
STATUS_GROUPS: dict[str, tuple[str, ...]] = {
    "in_progress": (
        OperationalState.BOOKED,
        OperationalState.AWAITING_PARCEL,
        OperationalState.RECEIVED_AT_SOLARIS,
        OperationalState.PROCESSING,
        OperationalState.DEPARTED_ORIGIN,
        OperationalState.IN_TRANSIT,
        OperationalState.CUSTOMS_PROCESSING,
        OperationalState.ARRIVED_DESTINATION,
        OperationalState.OUT_FOR_DELIVERY,
        OperationalState.PARTIALLY_DELIVERED,
        OperationalState.TRACKING_UNAVAILABLE,
    ),
    "delivered": (OperationalState.DELIVERED,),
    "cancelled": (OperationalState.CANCELLED,),
    #: Everything that needs a person to look at it, including the two return states. A
    #: return is not given a group of its own: OD-22 is open, and a `return_*` group would
    #: be the first half of a return workflow this phase is forbidden to start.
    "exception": (
        OperationalState.EXCEPTION,
        OperationalState.DELIVERY_ATTEMPTED,
        OperationalState.RETURN_IN_PROGRESS,
        OperationalState.RETURNED,
    ),
}

#: The maximum span of a date-range filter, in days. Bounded so a filter cannot be used to
#: ask for an unbounded scan, and generous enough that "everything since I started" is one
#: request for any real customer history.
MAX_DATE_RANGE_DAYS = 400

#: Page size bound. The default is what a first screen shows; the maximum is what bulk
#: scraping through a compromised session is held to (`RATE_LIMITS_AND_ABUSE.md` §5).
DEFAULT_LIMIT = 20
MAX_LIMIT = 50
MAX_OFFSET = 10_000

#: The longest a filter value may be before it is refused unparsed. Generous next to the
#: ten characters a date needs and the longest status group name, and small enough that an
#: oversized query string is refused rather than parsed. Enforced here rather than as a
#: FastAPI ``Query(max_length=...)`` so that every malformed filter produces **one** body:
#: a framework-level length rejection answers with FastAPI's own 422 shape, which is a
#: second failure shape on a route that should have one (DEC-0059's reasoning, applied to
#: the query string).
MAX_FILTER_VALUE_LENGTH = 64

#: The keyword search's bound, the same as every other filter's. Named so the screen's
#: `maxLength` and the refusal sentence read from one number.
MAX_KEYWORD_LENGTH = MAX_FILTER_VALUE_LENGTH

#: The escape character for a keyword's ``LIKE`` pattern.
_LIKE_ESCAPE = "\\"

#: What the keyword search reads on the shipment row (DEC-0156): the Solaris Shipment ID,
#: the booking reference, and the two cities the list shows. Not a recipient, an address,
#: a phone, an email, a carrier number, contents or a note. Since UAT round 11 the booking
#: reference is also shown on the row (DEC-0160), so every column searched here is one the
#: list publishes. The one other thing searched is `KEYWORD_PACKAGE_COLUMN`.
KEYWORD_COLUMNS = (
    Shipment.public_id,
    Shipment.booking_reference,
    Shipment.origin_city,
    Shipment.destination_city,
)

#: The package reference (``SX-…-01``) also finds its shipment (UAT round 11, DEC-0161).
#: Read through an ``EXISTS`` correlated on ``shipment_id``, so a package can only ever
#: match the shipment it belongs to, and that shipment still has to pass the ownership
#: clause. Cancelled packages count: the detail shows them as cancelled, not hidden.
KEYWORD_PACKAGE_COLUMN = ShipmentPackage.package_reference


#: The route-group filter's vocabulary. The **existing** enum, named here so the
#: membership check and the error message read from one place, and so a fifth route group
#: added to `RouteGroup` becomes filterable without a second list to remember (OD-41).
ROUTE_GROUP_VALUES: frozenset[str] = frozenset(group.value for group in RouteGroup)


@dataclass(frozen=True)
class ListFilters:
    """The parsed, validated filter set. Only values this module produced ever reach SQL."""

    status_group: str | None = None
    booked_from: datetime | None = None
    booked_to: datetime | None = None
    #: An exact, already-normalized Solaris **shipment** reference, or None (OD-41). Never
    #: a fragment, never a package reference, and never a string a caller composed: it is
    #: the output of `parse_public_reference`, so what reaches SQL is a value this module
    #: built.
    reference: str | None = None
    #: An exact member of `ROUTE_GROUP_VALUES`, or None (OD-41).
    route_group: str | None = None
    #: The keyword, already folded by `search_fold` and with its LIKE wildcards escaped, or
    #: None (DEC-0156). Only ever bound as a parameter.
    keyword_pattern: str | None = None
    limit: int = DEFAULT_LIMIT
    offset: int = 0


def _parse_day(raw: str | None, field: str) -> date | None:
    """``YYYY-MM-DD`` and nothing else.

    Canonical parsing rather than a permissive one: ``date.fromisoformat`` in 3.11+ accepts
    several ISO 8601 spellings, including week dates and ``YYYYMMDD``, and a filter with
    more than one spelling is a filter whose behaviour depends on which one a client picked.
    The length and shape are checked first, so the parser only ever sees the one form.
    """
    if raw is None:
        return None
    value = raw.strip()
    if not value:
        return None
    if len(value) != 10 or value[4] != "-" or value[7] != "-":
        raise ValidationError("Enter a date as YYYY-MM-DD.", field=field)
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValidationError("Enter a date as YYYY-MM-DD.", field=field) from exc


#: What a `reference` filter that is not a Solaris shipment reference matches. A sentinel
#: rather than `None`, because `None` already means "no filter was supplied" and the two
#: must not collapse: a caller who filters by nonsense must get an **empty** list, not the
#: unfiltered one (OD-41).
NO_SUCH_REFERENCE = "\x00no-such-reference"


def _parse_reference_filter(raw: str | None) -> str | None:
    """The exact-reference filter, or ``None`` when none was supplied.

    Exact, and exact in one specific sense: the value is run through
    ``parse_public_reference`` -- the **same** parser the detail route and Public Tracking
    use -- and what comes back is compared with ``==``. There is no ``LIKE``, no prefix, no
    wildcard and no collation trick anywhere in this path, and there is nowhere to add one
    without changing this function (OD-41).

    **A value that is not a Solaris shipment reference returns the sentinel, not an
    error.** Three cases collapse into it deliberately:

    * a malformed or oversized value -- refusing it by name would make the filter a grammar
      oracle, and this surface's whole design is one answer;
    * a **package** reference, which is a well-formed identifier in a second space the list
      is not addressed by. Answering it differently from an unknown shipment reference
      would say that the space exists;
    * a well-formed shipment reference belonging to somebody else, which the ownership
      clause excludes anyway.

    All three then produce the same empty page as a reference that simply does not exist,
    which is what makes this filter useless as an ownership oracle.
    """
    if raw is None:
        return None
    if not raw.strip():
        # An empty box on a form is not a filter. Submitting one clears it.
        return None
    parsed = parse_public_reference(raw)
    if parsed is None or parsed.is_package:
        return NO_SUCH_REFERENCE
    return parsed.value


def _escape_like(value: str) -> str:
    """``%``, ``_`` and the escape character itself, matched literally."""
    return (
        value.replace(_LIKE_ESCAPE, _LIKE_ESCAPE * 2)
        .replace("%", _LIKE_ESCAPE + "%")
        .replace("_", _LIKE_ESCAPE + "_")
    )


def _parse_keyword(raw: str | None) -> str | None:
    """The keyword search's ``LIKE`` pattern, or ``None`` when there is nothing to search.

    Folded (case and accents, `search_fold`), wildcards escaped, and wrapped in ``%`` so it
    matches anywhere in a column. An empty or all-space box is no search, as it is for the
    reference filter. The length bound is checked by `parse_filters` before this runs.
    """
    folded = search_fold(raw)
    if not folded:
        return None
    return f"%{_escape_like(folded)}%"


def parse_filters(
    *,
    status_group: str | None,
    booked_from: str | None,
    booked_to: str | None,
    reference: str | None = None,
    route_group: str | None = None,
    q: str | None = None,
    limit: int | None,
    offset: int | None,
    timezone_name: str,
) -> ListFilters:
    """Validate the query string into a closed object. Raises rather than ignoring.

    A rejected filter is refused **by name**, which is safe: the filter vocabulary is a
    property of the API and not of any account, so "that status group is not available"
    discloses nothing about anybody's shipments. Silently dropping an unrecognized value
    would be worse than refusing it -- a client would believe it had filtered and would show
    a customer rows it thought it had excluded.

    Date boundaries are cut at **local midnight in the organization's configured timezone**
    and then converted to UTC, the same rule every report boundary uses (DEC-0076). A
    parcel booked at 23:30 on 30 September in Mississauga belongs to 30 September in the
    filter, and cutting on UTC midnight would move it to 1 October for four hours of every
    day.
    """
    for field, raw in (
        ("status_group", status_group),
        ("booked_from", booked_from),
        ("booked_to", booked_to),
        ("reference", reference),
        ("route_group", route_group),
    ):
        if raw is not None and len(raw) > MAX_FILTER_VALUE_LENGTH:
            raise ValidationError("That filter value is not valid.", field=field)
    if q is not None and len(q) > MAX_KEYWORD_LENGTH:
        # Named, and without echoing the value: the bound is a property of the API.
        raise ValidationError(f"Search for {MAX_KEYWORD_LENGTH} characters or fewer.", field="q")

    group = (status_group or "").strip() or None
    if group is not None and group not in STATUS_GROUPS:
        raise ValidationError("That status filter is not available.", field="status_group")

    route = (route_group or "").strip().upper() or None
    if route is not None and route not in ROUTE_GROUP_VALUES:
        # Refused by name, and safe to refuse by name: the route vocabulary is a property
        # of the API and not of anybody's shipments, so "that route filter is not
        # available" says nothing about any account. Upper-cased first because the
        # vocabulary is upper-case and a lower-case spelling of a real group is a
        # presentation difference rather than a different value -- the same forgiveness
        # the reference parser applies, for the same reason.
        raise ValidationError("That route filter is not available.", field="route_group")

    exact_reference = _parse_reference_filter(reference)

    start_day = _parse_day(booked_from, "booked_from")
    end_day = _parse_day(booked_to, "booked_to")
    if start_day and end_day:
        if end_day < start_day:
            raise ValidationError("The end date is before the start date.", field="booked_to")
        if (end_day - start_day).days > MAX_DATE_RANGE_DAYS:
            raise ValidationError(
                f"Choose a date range of {MAX_DATE_RANGE_DAYS} days or fewer.",
                field="booked_to",
            )
    elif start_day or end_day:
        # One-sided ranges are bounded too, by filling in the other end. An open-ended
        # "everything before this date" is a full scan with a friendly name.
        if start_day:
            end_day = start_day + timedelta(days=MAX_DATE_RANGE_DAYS)
        else:
            start_day = end_day - timedelta(days=MAX_DATE_RANGE_DAYS)

    booked_from_utc = booked_to_utc = None
    if start_day and end_day:
        booked_from_utc, booked_to_utc = period_bounds(start_day, end_day, timezone_name)

    resolved_limit = DEFAULT_LIMIT if limit is None else limit
    if resolved_limit < 1 or resolved_limit > MAX_LIMIT:
        raise ValidationError(f"Choose a page size between 1 and {MAX_LIMIT}.", field="limit")
    resolved_offset = 0 if offset is None else offset
    if resolved_offset < 0 or resolved_offset > MAX_OFFSET:
        raise ValidationError("That page is out of range.", field="offset")

    return ListFilters(
        status_group=group,
        booked_from=booked_from_utc,
        booked_to=booked_to_utc,
        reference=exact_reference,
        route_group=route,
        keyword_pattern=_parse_keyword(q),
        limit=resolved_limit,
        offset=resolved_offset,
    )


# --- The ownership query ------------------------------------------------------


def _owned(customer_id: int, filters: ListFilters) -> list:
    """Every clause that constrains the list, ownership first.

    ``qualifying_conditions`` is the OD-29 rule and carries the ``customer_id`` equality
    itself, so ownership cannot be dropped by editing a filter. The filter clauses are
    appended after it and can only ever narrow.
    """
    conditions = list(qualifying_conditions(customer_id))
    if filters.status_group:
        conditions.append(Shipment.operational_state.in_(STATUS_GROUPS[filters.status_group]))
    if filters.reference is not None:
        # Equality, against a value `_parse_reference_filter` produced. The sentinel
        # matches no `public_id`, so an unparseable reference and an unknown one are the
        # same empty page -- and because this clause is appended **after**
        # `qualifying_conditions`, another customer's real reference is the same empty page
        # again (OD-41, DEC-0114).
        conditions.append(Shipment.public_id == filters.reference)
    if filters.route_group:
        conditions.append(Shipment.route_group == filters.route_group)
    if filters.keyword_pattern is not None:
        # DEC-0156: any of four fixed columns contains the keyword, folded on both sides,
        # or (DEC-0161) one of this shipment's own package references does. Appended after
        # `qualifying_conditions` like every filter, so it searches the caller's own rows
        # and nothing else. The pattern is a bound parameter.
        fold = getattr(func, SEARCH_FOLD_SQL_NAME)
        package_matches = exists().where(
            ShipmentPackage.shipment_id == Shipment.id,
            fold(KEYWORD_PACKAGE_COLUMN).like(filters.keyword_pattern, escape=_LIKE_ESCAPE),
        )
        conditions.append(
            or_(
                *(
                    fold(column).like(filters.keyword_pattern, escape=_LIKE_ESCAPE)
                    for column in KEYWORD_COLUMNS
                ),
                package_matches,
            )
        )
    if filters.booked_from is not None:
        # Half-open [from, to). A shipment with no booking date is outside every range
        # rather than inside all of them, which is what a customer filtering by date means.
        conditions.append(Shipment.booking_date >= filters.booked_from)
    if filters.booked_to is not None:
        conditions.append(Shipment.booking_date < filters.booked_to)
    return conditions


def _ordered(statement: Select) -> Select:
    """The total order: newest booking first, reference ascending as the tie-break.

    Total, not merely deterministic. ``booking_date`` alone repeats across rows, and a
    non-total order under ``LIMIT/OFFSET`` lets a row appear on two consecutive pages or on
    neither. ``public_id`` is unique and never null on any qualifying row -- a draft is the
    only shipment without one and drafts are excluded -- so the pair is a total order.

    Null booking dates sort last. SQLite orders NULLs first by default, which would put the
    least identifiable rows at the top of the first page; the explicit ``is_(None)`` key
    makes the answer the same on any backend rather than a property of this one.
    """
    return statement.order_by(
        Shipment.booking_date.is_(None).asc(),
        Shipment.booking_date.desc(),
        Shipment.public_id.asc(),
    )


def _package_counts(db: Session, shipment_ids: list[int]) -> dict[int, tuple[int, int]]:
    """Active and cancelled package counts for a whole page, in **one** statement.

    Grouped rather than joined onto the row query: a join to ``shipment_packages`` would
    multiply a three-package shipment into three list rows, and a ``DISTINCT`` to undo that
    would break the ``LIMIT``. Grouped rather than per-row because a query per row is the
    thing §24.12 exists to forbid.
    """
    if not shipment_ids:
        return {}
    rows = db.execute(
        select(
            ShipmentPackage.shipment_id,
            func.count(ShipmentPackage.id).filter(ShipmentPackage.is_active.is_(True)),
            func.count(ShipmentPackage.id).filter(ShipmentPackage.is_active.is_(False)),
        )
        .where(ShipmentPackage.shipment_id.in_(shipment_ids))
        .group_by(ShipmentPackage.shipment_id)
    ).all()
    return {row[0]: (int(row[1] or 0), int(row[2] or 0)) for row in rows}


def _last_public_update(db: Session, shipment_ids: list[int]) -> dict[int, datetime]:
    """Newest approved public milestone per shipment, for a whole page, in one statement.

    The ``WHERE`` clause is the same publication gate ``public_tracking_service`` applies:
    not voided, explicitly marked as a public update, and carrying approved wording either
    as typed text or as a catalogue key. A shipment whose only events are internal has no
    entry here and reports ``null`` -- which is correct, and is not the same as "nothing has
    happened".
    """
    if not shipment_ids:
        return {}
    rows = db.execute(
        select(ShipmentEvent.shipment_id, func.max(ShipmentEvent.occurred_at))
        .where(
            ShipmentEvent.shipment_id.in_(shipment_ids),
            ShipmentEvent.is_voided.is_(False),
            ShipmentEvent.is_public_update.is_(True),
            or_(
                and_(
                    ShipmentEvent.public_update_text.is_not(None),
                    ShipmentEvent.public_update_text != "",
                ),
                and_(
                    ShipmentEvent.public_update_template_key.is_not(None),
                    ShipmentEvent.public_update_template_key != "",
                ),
            ),
        )
        .group_by(ShipmentEvent.shipment_id)
    ).all()
    return {row[0]: row[1] for row in rows if row[1] is not None}


def list_shipments(
    db: Session, *, customer: Customer, filters: ListFilters, timezone_name: str
) -> AccountShipmentListPage:
    """One page of this customer's shipment history.

    Statement budget, whatever the page size: one ``COUNT(*)``, one page of rows, one
    grouped package aggregate, one grouped event aggregate. Four, and four for a page of
    fifty as much as for a page of one.

    An empty page is a legitimate answer and is returned as one -- ``items: []``,
    ``total: 0`` -- never as an error and never with a hint that shipments might exist
    somewhere else (AC-CA-5.7).
    """
    conditions = _owned(customer.id, filters)

    total = int(db.scalar(select(func.count(Shipment.id)).where(*conditions)) or 0)

    rows = list(
        db.scalars(
            _ordered(select(Shipment).where(*conditions))
            .limit(filters.limit)
            .offset(filters.offset)
        ).all()
    )

    shipment_ids = [row.id for row in rows]
    counts = _package_counts(db, shipment_ids)
    updates = _last_public_update(db, shipment_ids)

    return AccountShipmentListPage(
        items=[_list_item(row, counts, updates) for row in rows],
        total=total,
        limit=filters.limit,
        offset=filters.offset,
        timezone=timezone_name,
    )


def _booking_reference(shipment: Shipment) -> str | None:
    """The customer's own booking reference, trimmed, or None when blank (DEC-0160, DEC-0163).

    One function for the list row and the detail, so the two always show the same value.
    """
    return (shipment.booking_reference or "").strip() or None


def _list_item(
    shipment: Shipment,
    counts: dict[int, tuple[int, int]],
    updates: dict[int, datetime],
) -> AccountShipmentListItem:
    """Eighteen assignments. Read this function as the list allowlist.

    If a value is not assigned here it is not published, and adding one means editing
    `SHIPMENT_ALLOWLISTS.md` first.
    """
    active, cancelled_packages = counts.get(shipment.id, (0, 0))
    is_cancelled = shipment.booking_state == BookingState.CANCELLED

    return AccountShipmentListItem(
        shipment_reference=shipment.public_id,
        # The customer's own reference for the booking, shown since UAT round 11 (DEC-0160).
        booking_reference=_booking_reference(shipment),
        booked_at=shipment.booking_date,
        route_group=shipment.route_group,
        route_label=ROUTE_GROUP_LABELS.get(shipment.route_group, shipment.route_group),
        origin_city=(shipment.origin_city or "").strip() or None,
        origin_country_code=(shipment.origin_country_code or "").upper() or None,
        destination_city=(shipment.destination_city or "").strip() or None,
        destination_country_code=(shipment.destination_country_code or "").upper() or None,
        status=shipment.operational_state,
        status_label=value_label(shipment.operational_state),
        package_count_active=active,
        package_count_cancelled=cancelled_packages,
        # A cancelled booking reports its cancellation and not a delivery date, matching
        # the public rule so the two surfaces cannot disagree about one shipment.
        delivered_at=None if is_cancelled else shipment.delivered_at,
        cancelled_at=shipment.cancelled_at if is_cancelled else None,
        last_public_update_at=updates.get(shipment.id),
        is_cancelled=is_cancelled,
        # The replacement's reference is deliberately absent. See the field's docstring.
        is_rebooked=shipment.rebooked_to_shipment_id is not None,
    )


# --- The detail ----------------------------------------------------------------


def _not_found() -> NotFoundError:
    return NotFoundError(GENERIC_NOT_FOUND)


def resolve_owned_shipment(db: Session, *, customer: Customer, raw_reference: str) -> Shipment:
    """The one lookup, and the one failure.

    Order, and the order is the contract:

    1. **Validate the reference in application code** before anything reaches the database.
       A value that is too long, empty, mis-shaped or carrying extra separators is simply
       not a Solaris reference and never becomes a query.
    2. **Refuse a package reference.** The authenticated route is addressed by Solaris
       Shipment ID only. A package reference is a well-formed identifier in a second space,
       and answering it differently from an unknown one would say that the space exists.
    3. **Ask one question with ownership inside it.** ``customer_id`` is a ``WHERE`` clause,
       not a post-load check, so "no such shipment" and "not yours" are the same miss on
       the same statement -- one query, one shape, one latency profile.
    4. **Re-check ownership on the loaded row**, belt and braces, because §24.4 says the
       detail re-checks and a query is a thing somebody can edit.

    Every failure raises the same ``NotFoundError`` with the same message.
    """
    reference = parse_public_reference(raw_reference)
    if reference is None or reference.is_package:
        raise _not_found()

    shipment = db.scalar(
        select(Shipment).where(
            Shipment.public_id == reference.value,
            *qualifying_conditions(customer.id),
        )
    )
    if shipment is None or shipment.customer_id != customer.id:
        raise _not_found()
    return shipment


def _place(city: str | None, country_code: str | None) -> AccountPlace:
    code = (country_code or "").upper() or None
    return AccountPlace(
        city=(city or "").strip() or None,
        country_code=code,
        country_label=_COUNTRY_NAMES.get(code or "", code),
    )


def _timeline(
    db: Session, shipment_id: int, references: dict[int, str]
) -> list[AccountTimelineEntry]:
    """Approved public milestones, newest first, identical entries grouped.

    The rows come from ``public_tracking_service.public_events`` -- the single publication
    gate, shared so it cannot drift -- and the **entries are built here**, into this
    surface's own model. Nothing reads ``internal_detail``, the recording staff member, the
    internal event id or the leg, and there is no field on ``AccountTimelineEntry`` that
    could carry one.

    Recording one shipment-wide milestone writes a row per active package, so rows that
    agree on every visible attribute collapse into one entry listing the references they
    cover. Display grouping only: no event is hidden, and a genuinely per-package update
    still stands alone.
    """
    grouped: dict[tuple, AccountTimelineEntry] = {}
    order: list[tuple] = []
    # Staff-typed wording that names a vendor is screened on output (DEC-0222).
    screen = public_tracking_service.vendor_screen(db, shipment_id)
    for event in public_tracking_service.public_events(db, shipment_id):
        key = (
            event.operational_state,
            event.event_type,
            event.public_update_text,
            event.public_update_template_key,
            event.occurred_at,
            event.location_label,
            event.location_country_code,
        )
        reference = references.get(event.package_id) if event.package_id else None
        if key in grouped:
            if reference and reference not in grouped[key].package_references:
                grouped[key].package_references.append(reference)
            continue
        location = (
            _place(screen(event.location_label), event.location_country_code)
            if (event.location_label or event.location_country_code)
            else None
        )
        order.append(key)
        grouped[key] = AccountTimelineEntry(
            status=event.operational_state,
            status_label=value_label(event.operational_state),
            event_type=event.event_type,
            message=(
                screen(event.public_update_text)
                or templates.render(event.public_update_template_key or "")
                or ""
            ),
            message_template_key=event.public_update_template_key,
            occurred_at=event.occurred_at,
            location=location,
            package_references=[reference] if reference else [],
            # Every event in this system was typed by a person. Nothing may be described
            # as a carrier scan or a synchronized update (CRM.md section 9).
            source_label="manual_update",
        )
    entries = [grouped[key] for key in order]
    # Phase 15 review (AC-7): an entry covering some but not all of several active parcels is
    # about a parcel, and the account words it so ("One of your parcels ...").
    active = {
        package.package_reference
        for package in package_service.active_packages(db, shipment_id)
        if package.package_reference
    }
    for entry in entries:
        entry.package_references.sort()
        covered = active.intersection(entry.package_references)
        if len(active) > 1 and covered and len(covered) < len(active):
            entry.scope = "package"
    entries.reverse()
    return entries


def _carrier_link(db: Session, shipment_id: int) -> AccountCarrierLink | None:
    """The allowlisted public carrier link, copied into this surface's own model.

    ``public_tracking_service.public_carrier_link`` decides *whether* a link may be shown --
    HTTPS, no credentials, no fragment, no port, an allowlisted host, never an address or a
    private range, and never fetched. That policy is shared. The object is not: the two
    values are copied into an ``AccountCarrierLink`` and the public model is discarded, so
    a field added to the public one cannot appear here.

    The carrier's tracking **number** is not returned in any form, on this surface either.
    """
    links = _carrier_links(db, shipment_id)
    return links[0] if links else None


def _carrier_links(db: Session, shipment_id: int) -> list[AccountCarrierLink]:
    """Every link the shared policy allows, at most one per generic tracking name, in leg order
    (Master Tracking and Last Mile Tracking both shown when both exist; 2026-10-22)."""
    return [
        AccountCarrierLink(
            carrier_name=link.carrier_name, tracking_name_key=link.tracking_name_key, url=link.url
        )
        for link in public_tracking_service.public_carrier_links(db, shipment_id)
    ]


def _estimated_delivery(shipment: Shipment) -> datetime | None:
    """An estimate, only while it is still ahead of what actually happened.

    Nothing computes a transit time and nothing infers a date from a route: a null stays
    null and the screen says nothing, which is better than a confident guess a customer
    plans around.
    """
    if shipment.estimated_delivery_at is None:
        return None
    if shipment.booking_state == BookingState.CANCELLED:
        return None
    if shipment.operational_state in {
        OperationalState.DELIVERED,
        OperationalState.RETURNED,
        OperationalState.CANCELLED,
    }:
        return None
    return shipment.estimated_delivery_at


def _tracking_state(
    shipment: Shipment,
    timeline: list[AccountTimelineEntry],
    carrier_link: AccountCarrierLink | None,
) -> AccountTrackingState:
    """Which honest tracking story this shipment can tell.

    No "synchronized", no "last carrier update", no freshness age, because no provider has
    ever been contacted. Cancellation comes first: a withdrawn booking is the single most
    useful thing to say about it. ``DEMO`` is unreachable here -- demo rows never qualify --
    and the branch is kept so the function is total over the model rather than over the
    subset this surface happens to serve.
    """
    if shipment.booking_state == BookingState.CANCELLED:
        return AccountTrackingState.CANCELLED
    if timeline:
        return AccountTrackingState.MANUAL_UPDATES
    if carrier_link is not None:
        return AccountTrackingState.EXTERNAL_LINK_ONLY
    if shipment.is_demo_record:  # pragma: no cover - excluded by the inclusion rule
        return AccountTrackingState.DEMO
    if shipment.operational_state == OperationalState.TRACKING_UNAVAILABLE:
        return AccountTrackingState.TRACKING_UNAVAILABLE
    return AccountTrackingState.NO_PUBLIC_MILESTONES


def _packages(db: Session, shipment_id: int) -> list[AccountPackage]:
    """Safe per-package state, built into this surface's own model.

    A cancelled package is shown as cancelled rather than hidden: the shipper paid for it
    and is entitled to an answer about it. It is counted separately so it cannot distort
    "1 of 3 delivered".
    """
    out: list[AccountPackage] = []
    for package in package_service.all_packages(db, shipment_id):
        if not package.package_reference:
            continue
        out.append(
            AccountPackage(
                package_reference=package.package_reference,
                status=package.operational_state,
                status_label=value_label(package.operational_state),
                # No package is "selected" here: the route is addressed by shipment
                # reference, so there is nothing for a selection to mean.
                is_selected=False,
                is_cancelled=not package.is_active,
                delivered_at=package.delivered_to_recipient_at,
            )
        )
    return out


def build_detail(db: Session, shipment: Shipment, *, timezone_name: str) -> AccountShipmentDetail:
    """Assemble the detail, one allowlisted field at a time.

    Read this function as the specification of the authenticated detail surface. Twenty-five
    assignments; if a value is not assigned here, it is not published.

    The caller has already established ownership. This function does not re-derive it and
    must never be reachable with a shipment the caller does not own -- which is why it takes
    a ``Shipment`` that ``resolve_owned_shipment`` returned rather than a reference it would
    look up itself.
    """
    is_cancelled = shipment.booking_state == BookingState.CANCELLED

    references = {
        package.id: package.package_reference
        for package in package_service.all_packages(db, shipment.id)
        if package.package_reference
    }

    # A cancelled booking returns the cancellation and nothing else. Publishing the journey
    # of a withdrawn booking only invites confusion, and the public surface already answers
    # this shipment the same way.
    timeline = [] if is_cancelled else _timeline(db, shipment.id, references)
    carrier_links = [] if is_cancelled else _carrier_links(db, shipment.id)
    carrier_link = carrier_links[0] if carrier_links else None

    progress = package_service.progress(db, shipment.id)

    return AccountShipmentDetail(
        # Identity: the customer-facing identifier and the customer's own booking reference
        # (DEC-0163). No row id, no customer id, no idempotency key, no source record id.
        shipment_reference=shipment.public_id,
        booking_reference=_booking_reference(shipment),
        matched_reference_type="shipment",
        selected_package_reference=None,
        # Route and coarse geography: city and country. Never an address line, a postal
        # code, a recipient name or a phone number.
        route_group=shipment.route_group,
        route_label=ROUTE_GROUP_LABELS.get(shipment.route_group, shipment.route_group),
        origin=_place(shipment.sender_city, shipment.sender_country_code),
        destination=_place(shipment.recipient_city, shipment.recipient_country_code),
        status=shipment.operational_state,
        status_label=value_label(shipment.operational_state),
        package_count_active=progress.active,
        package_count_cancelled=progress.cancelled,
        package_count_delivered=progress.delivered,
        progress_summary=progress.summary,
        packages=_packages(db, shipment.id),
        estimated_delivery_at=_estimated_delivery(shipment),
        delivered_at=None if is_cancelled else shipment.delivered_at,
        cancelled_at=shipment.cancelled_at if is_cancelled else None,
        timeline=timeline,
        tracking_state=_tracking_state(shipment, timeline, carrier_link),
        last_public_update_at=timeline[0].occurred_at if timeline else None,
        carrier_link=carrier_link,
        carrier_links=carrier_links,
        # Demo rows never qualify, so this is a constant that a test asserts rather than a
        # branch that could one day pick the other value.
        data_mode=AccountDataMode.LIVE,
        help_url=(app_settings.public_help_url or "").strip() or None,
        timezone=timezone_name,
    )
