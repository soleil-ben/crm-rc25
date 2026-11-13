"""Management reports, computed from real records (CRM.md section 12, Design.md section 12).

Every figure here is a database query. Nothing is stored, nothing is a sample value, and
nothing is a comparison the data cannot support. The definitions are written down once, in
``PROJECT_STATUS.md`` section 3 and ``docs/DATA_DICTIONARY.md``, and each one is reconciled
in ``tests/test_reports_metrics.py`` against a calculation performed a different way
(DEC-0077).

Four rules run through the whole module:

* **A shipment is counted once, at the parent level.** Packages and transport legs are
  never counted as shipments (AC-14).
* **Missing is unknown, not zero.** A share over an empty denominator is ``None``; a
  financial figure nobody recorded is absent, not ``0``.
* **Currencies are never combined** (AC-17).
* **Periods are cut in the organization's timezone**, half-open, and bounded (DEC-0076).

A time bucket with no activity is a genuine zero and is emitted as ``0`` so a chart axis
stays continuous. That is different from an unknown value: we know how many shipments were
handed over last Tuesday, and the answer is none.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.enums import (
    OPEN_TASK_STATUSES,
    ROUTE_GROUP_LABELS,
    BookingState,
    LifecycleStatus,
    OperationalState,
    RouteGroup,
    TaskStatus,
    TrackingSourceMode,
    value_label,
)
from app.core.permissions import Permission, permissions_for
from app.core.time_utils import in_zone, local_midnight_utc, period_bounds, utcnow
from app.models import (
    Customer,
    FollowUpTask,
    LegTrackingReference,
    OrganizationSettings,
    Shipment,
    ShipmentLeg,
)
from app.services.activity_service import (
    LifecycleThresholds,
    lifecycle_status_for,
    qualifying_shipment_filter,
    shipment_exception_filter,
)
from app.services.errors import ValidationError

#: Longest period a report will accept: two years plus a leap day. Long enough for any
#: year-over-year question the launch business has, short enough that the query stays
#: predictable. There is no unbounded report (DEC-0076).
MAX_PERIOD_DAYS = 731

#: A date this far from today is a typo or a probe, not a report request.
MAX_YEARS_FROM_NOW = 50

DAY = "day"
WEEK = "week"
MONTH = "month"

#: Granularity is derived from the span rather than chosen by the caller, so the axis
#: label always describes what the buckets actually are.
DAY_MAX_SPAN = 31
WEEK_MAX_SPAN = 182

PERIOD = "period"
CURRENT = "current"

ROUTE_ORDER: tuple[str, ...] = tuple(route.value for route in RouteGroup)

LIFECYCLE_ORDER: tuple[str, ...] = (
    LifecycleStatus.PROSPECT,
    LifecycleStatus.NEW,
    LifecycleStatus.ACTIVE,
    LifecycleStatus.AT_RISK,
    LifecycleStatus.INACTIVE,
    LifecycleStatus.ARCHIVED,
)

#: The tracking source modes a shipment can actually be in. ``connected_api`` is
#: deliberately absent: no provider is connected, and rendering an empty column would
#: imply a mode that could have data in it (DEC-0075).
TRACKING_SOURCE_ORDER: tuple[str, ...] = (
    TrackingSourceMode.MANUAL,
    TrackingSourceMode.EXTERNAL_LINK,
    "none",
)


# --- Period ------------------------------------------------------------------


@dataclass(frozen=True)
class ReportPeriod:
    """A validated, bounded, timezone-correct reporting window."""

    from_date: date
    to_date: date
    timezone_name: str
    start_utc: datetime
    end_utc: datetime
    granularity: str

    def to_dict(self) -> dict:
        return {
            "from_date": self.from_date.isoformat(),
            "to_date": self.to_date.isoformat(),
            "timezone": self.timezone_name,
            "start_utc": self.start_utc,
            "end_utc": self.end_utc,
            "granularity": self.granularity,
            "days": (self.to_date - self.from_date).days + 1,
        }


def resolve_period(
    *, from_date: date | None, to_date: date | None, org: OrganizationSettings | None
) -> ReportPeriod:
    """Validate a requested range and cut it at local midnight (DEC-0076)."""
    tz_name = org.office_timezone if org is not None else None
    today = in_zone(utcnow(), tz_name).date()

    if to_date is None:
        to_date = today
    if from_date is None:
        from_date = to_date - timedelta(days=29)

    if from_date > to_date:
        raise ValidationError(
            "The start of the range must not be after the end.", field="from_date"
        )

    span_days = (to_date - from_date).days + 1
    if span_days > MAX_PERIOD_DAYS:
        raise ValidationError(
            f"A report range may cover at most {MAX_PERIOD_DAYS} days; this one covers "
            f"{span_days}. Narrow the range and try again.",
            field="from_date",
        )

    horizon = timedelta(days=MAX_YEARS_FROM_NOW * 366)
    for label, value in (("from_date", from_date), ("to_date", to_date)):
        if abs((value - today).days) > horizon.days:
            raise ValidationError("That date is outside the supported range.", field=label)

    start_utc, end_utc = period_bounds(from_date, to_date, tz_name)
    return ReportPeriod(
        from_date=from_date,
        to_date=to_date,
        timezone_name=tz_name or "UTC",
        start_utc=start_utc,
        end_utc=end_utc,
        granularity=granularity_for(span_days),
    )


def granularity_for(span_days: int) -> str:
    if span_days <= DAY_MAX_SPAN:
        return DAY
    if span_days <= WEEK_MAX_SPAN:
        return WEEK
    return MONTH


def bucket_label_for_date(value: date, granularity: str) -> str:
    """Bucket label for a local calendar date."""
    if granularity == DAY:
        return value.isoformat()
    if granularity == WEEK:
        return (value - timedelta(days=value.weekday())).isoformat()
    return f"{value.year:04d}-{value.month:02d}"


def bucket_key(value: datetime, granularity: str, tz_name: str) -> str:
    """Bucket label for a stored UTC timestamp, computed in the organization timezone."""
    return bucket_label_for_date(in_zone(value, tz_name).date(), granularity)


def bucket_series(period: ReportPeriod) -> list[str]:
    """Every bucket in the period, including the empty ones.

    A chart with a hole where a quiet week was is harder to read than one with a zero, and
    the zero is true: nothing was handed over that week.
    """
    labels: list[str] = []
    seen: set[str] = set()
    cursor = period.from_date
    while cursor <= period.to_date:
        label = bucket_label_for_date(cursor, period.granularity)
        if label not in seen:
            seen.add(label)
            labels.append(label)
        cursor += timedelta(days=1)
    return labels


# --- Report shape ------------------------------------------------------------


@dataclass
class ReportColumn:
    key: str
    label: str
    #: ``text``, ``integer``, ``share``, ``money`` — drives alignment and CSV formatting.
    kind: str = "text"


@dataclass
class ReportTable:
    """One report: a definition, a set of columns, and rows computed from records."""

    key: str
    title: str
    #: ``period`` when the figures are bounded by the date range; ``current`` when they
    #: describe today and the range does not apply. Reports say which, because a
    #: lifecycle status is a fact about now and a shipment count is a fact about a window.
    scope: str
    definition: str
    columns: list[ReportColumn]
    rows: list[dict] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    #: Optional headline figures rendered above the table.
    summary: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


#: Every report key the API can produce, in display order. The financial summary is
#: appended only for a caller entitled to it (section 3.3 of the plan).
REPORT_KEYS: tuple[str, ...] = (
    "customer_growth",
    "customer_lifecycle",
    "route_mix",
    "shipment_volume",
    "shipment_status",
    "repeat_customers",
    "follow_up_workload",
    "shipment_exceptions",
)

FINANCIAL_REPORT_KEY = "financial_summary"


def available_report_keys(role: str) -> tuple[str, ...]:
    """Report keys this role may receive.

    The financial report is *absent* for a caller without ``financial:read``. It is not
    returned empty, null, or masked, because each of those still tells the caller that a
    financial report exists and they are not allowed to see it.
    """
    if Permission.FINANCIAL_READ in permissions_for(role):
        return (*REPORT_KEYS, FINANCIAL_REPORT_KEY)
    return REPORT_KEYS


# --- Shared query fragments --------------------------------------------------


def _qualifying_in_period(period: ReportPeriod) -> list:
    """Qualifying shipments handed over inside the period."""
    return [
        Shipment.first_handoff_at >= period.start_utc,
        Shipment.first_handoff_at < period.end_utc,
        *qualifying_shipment_filter(),
    ]


def _live_customer_filter() -> list:
    """Customers that still exist as people.

    A merged record's shipments moved to the survivor, so counting both would count one
    person twice.
    """
    return [Customer.merged_into_customer_id.is_(None)]


def _route_filter(route_groups: list[str] | None) -> list:
    if not route_groups:
        return []
    unknown = sorted({route for route in route_groups if route not in ROUTE_ORDER})
    if unknown:
        raise ValidationError(f"Unknown route group(s): {', '.join(unknown)}", field="route_group")
    return [Shipment.route_group.in_(route_groups)]


# --- The reports -------------------------------------------------------------


def customer_growth(db: Session, period: ReportPeriod) -> ReportTable:
    rows_raw = db.scalars(
        select(Customer.created_at).where(
            Customer.created_at >= period.start_utc,
            Customer.created_at < period.end_utc,
            *_live_customer_filter(),
        )
    ).all()

    created: dict[str, int] = dict.fromkeys(bucket_series(period), 0)
    for created_at in rows_raw:
        label = bucket_key(created_at, period.granularity, period.timezone_name)
        if label in created:
            created[label] += 1

    # The cumulative column is computed independently rather than by running-summing the
    # created column, so a record merged after creation is treated consistently by both.
    rows: list[dict] = []
    for label in bucket_series(period):
        bucket_end = _bucket_end_utc(label, period)
        cumulative = int(
            db.scalar(
                select(func.count(Customer.id)).where(
                    Customer.created_at < bucket_end, *_live_customer_filter()
                )
            )
            or 0
        )
        rows.append(
            {
                "bucket": label,
                "created": created[label],
                "cumulative": cumulative,
                "link": _customer_link_for_bucket(label, period),
            }
        )

    return ReportTable(
        key="customer_growth",
        title="Customer growth",
        scope=PERIOD,
        definition=(
            "Customer records created in each period, and the running total of customer "
            "records in existence at the end of each period. Records merged into another "
            "customer are excluded from both, because the surviving record already "
            "carries that person's history."
        ),
        columns=[
            ReportColumn("bucket", "Period"),
            ReportColumn("created", "New customers", "integer"),
            ReportColumn("cumulative", "Total customers", "integer"),
        ],
        rows=rows,
        summary={"created_total": sum(created.values())},
    )


def _bucket_end_utc(label: str, period: ReportPeriod) -> datetime:
    """Exclusive end of a bucket, in naive UTC, cut in the organization timezone."""
    if period.granularity == MONTH:
        year, month = (int(part) for part in label.split("-"))
        next_month = date(year + (month // 12), (month % 12) + 1, 1)
        return local_midnight_utc(next_month, period.timezone_name)
    start = date.fromisoformat(label)
    step = timedelta(days=7 if period.granularity == WEEK else 1)
    return local_midnight_utc(start + step, period.timezone_name)


def _customer_link_for_bucket(label: str, period: ReportPeriod) -> str:
    if period.granularity == MONTH:
        year, month = (int(part) for part in label.split("-"))
        start = date(year, month, 1)
        end = date(year + (month // 12), (month % 12) + 1, 1) - timedelta(days=1)
    else:
        start = date.fromisoformat(label)
        end = start + timedelta(days=6 if period.granularity == WEEK else 0)
    start = max(start, period.from_date)
    end = min(end, period.to_date)
    return f"/customers?created_from={start.isoformat()}&created_to={end.isoformat()}"


def customer_lifecycle(
    db: Session, period: ReportPeriod, thresholds: LifecycleThresholds
) -> ReportTable:
    """Lifecycle distribution. Current state — a lifecycle status is a fact about today."""
    now = utcnow()
    aggregate = (
        select(
            Shipment.customer_id.label("customer_id"),
            func.count(Shipment.id).label("qualifying_count"),
            func.max(Shipment.first_handoff_at).label("last_shipment_at"),
        )
        .where(*qualifying_shipment_filter())
        .group_by(Shipment.customer_id)
        .subquery()
    )
    rows_raw = db.execute(
        select(
            Customer.is_archived,
            aggregate.c.qualifying_count,
            aggregate.c.last_shipment_at,
        )
        .outerjoin(aggregate, aggregate.c.customer_id == Customer.id)
        .where(*_live_customer_filter())
    ).all()

    counts = dict.fromkeys(LIFECYCLE_ORDER, 0)
    for is_archived, qualifying_count, last_shipment_at in rows_raw:
        status = lifecycle_status_for(
            is_archived=bool(is_archived),
            qualifying_count=int(qualifying_count or 0),
            last_shipment_at=last_shipment_at,
            thresholds=thresholds,
            now=now,
        )
        counts[status] = counts.get(status, 0) + 1

    total = sum(counts.values())
    described = thresholds.describe()
    rows = [
        {
            "status": status,
            "status_label": value_label(status),
            "count": counts[status],
            "share": round(counts[status] / total, 4) if total else None,
            "definition": described.get(status, ""),
            "link": f"/customers?lifecycle_status={status}"
            + ("&include_archived=true" if status == LifecycleStatus.ARCHIVED else ""),
        }
        for status in LIFECYCLE_ORDER
    ]

    return ReportTable(
        key="customer_lifecycle",
        title="Customer lifecycle distribution",
        scope=CURRENT,
        definition=(
            "Every customer record that has not been merged, grouped by its derived "
            "lifecycle status using the thresholds an administrator configured. This is "
            "current state: a lifecycle status describes where a customer stands today, "
            "not where they stood during the selected range."
        ),
        columns=[
            ReportColumn("status_label", "Lifecycle status"),
            ReportColumn("count", "Customers", "integer"),
            ReportColumn("share", "Share", "share"),
            ReportColumn("definition", "Definition"),
        ],
        rows=rows,
        summary={"total_customers": total},
        notes=[
            "Thresholds are administrator-editable business assumptions, not benchmarks: "
            f"new within {thresholds.new_days} days, active within {thresholds.active_days}, "
            f"at risk within {thresholds.at_risk_days}."
        ],
    )


def route_mix(db: Session, period: ReportPeriod, route_groups: list[str] | None) -> ReportTable:
    rows_raw = db.execute(
        select(Shipment.route_group, func.count(Shipment.id))
        .where(*_qualifying_in_period(period), *_route_filter(route_groups))
        .group_by(Shipment.route_group)
    ).all()
    counts = {route: 0 for route in ROUTE_ORDER if not route_groups or route in route_groups}
    for route_group, count in rows_raw:
        counts[route_group] = int(count)
    total = sum(counts.values())

    rows = [
        {
            "route_group": route,
            "route_label": value_label(route),
            "count": counts[route],
            # A share of nothing is unknown, not zero percent.
            "share": round(counts[route] / total, 4) if total else None,
            "link": (
                f"/shipments?route_group={route}"
                f"&booked_from={period.from_date.isoformat()}"
                f"&booked_to={period.to_date.isoformat()}"
            ),
        }
        for route in counts
    ]
    rows.sort(key=lambda row: (-row["count"], row["route_group"]))

    return ReportTable(
        key="route_mix",
        title="Route mix",
        scope=PERIOD,
        definition=(
            "Qualifying shipments handed over during the period, grouped by route group. "
            "A qualifying shipment is a confirmed, uncancelled, non-return booking with a "
            "recorded first physical handoff. Packages and transport legs are not counted "
            "separately: one shipment counts once."
        ),
        columns=[
            ReportColumn("route_label", "Route"),
            ReportColumn("count", "Qualifying shipments", "integer"),
            ReportColumn("share", "Share", "share"),
        ],
        rows=rows,
        summary={"total": total},
        notes=[]
        if total
        else ["No qualifying shipments in this period, so no share can be computed."],
    )


def shipment_volume(
    db: Session, period: ReportPeriod, route_groups: list[str] | None
) -> ReportTable:
    rows_raw = db.execute(
        select(Shipment.first_handoff_at, Shipment.route_group).where(
            *_qualifying_in_period(period), *_route_filter(route_groups)
        )
    ).all()

    routes = [route for route in ROUTE_ORDER if not route_groups or route in route_groups]
    buckets = bucket_series(period)
    grid: dict[str, dict[str, int]] = {
        label: dict.fromkeys([*routes, "total"], 0) for label in buckets
    }
    for handoff_at, route_group in rows_raw:
        label = bucket_key(handoff_at, period.granularity, period.timezone_name)
        if label in grid:
            grid[label][route_group] = grid[label].get(route_group, 0) + 1
            grid[label]["total"] += 1

    rows = [{"bucket": label, **grid[label]} for label in buckets]

    return ReportTable(
        key="shipment_volume",
        title="Shipment volume over time",
        scope=PERIOD,
        definition=(
            "Qualifying shipments per period, split by route group, bucketed by first "
            "physical handoff in the organization's timezone. A period with no handoffs "
            "shows zero because that is the true count; it is not a missing value."
        ),
        columns=[
            ReportColumn("bucket", "Period"),
            *[ReportColumn(route, value_label(route), "integer") for route in routes],
            ReportColumn("total", "Total", "integer"),
        ],
        rows=rows,
        summary={"total": sum(row["total"] for row in rows), "granularity": period.granularity},
    )


def shipment_status(
    db: Session, period: ReportPeriod, route_groups: list[str] | None
) -> ReportTable:
    """Booking states over the period, plus the current operational state of its cohort."""
    booking_rows = db.execute(
        select(Shipment.booking_state, func.count(Shipment.id))
        .where(
            Shipment.booking_date >= period.start_utc,
            Shipment.booking_date < period.end_utc,
            *_route_filter(route_groups),
        )
        .group_by(Shipment.booking_state)
    ).all()
    booking_counts = {state.value: 0 for state in BookingState}
    for state, count in booking_rows:
        booking_counts[state] = int(count)

    operational_rows = db.execute(
        select(Shipment.operational_state, func.count(Shipment.id))
        .where(*_qualifying_in_period(period), *_route_filter(route_groups))
        .group_by(Shipment.operational_state)
    ).all()
    operational_counts = {state: int(count) for state, count in operational_rows}

    returns = int(
        db.scalar(
            select(func.count(Shipment.id)).where(
                Shipment.first_handoff_at >= period.start_utc,
                Shipment.first_handoff_at < period.end_utc,
                Shipment.is_return.is_(True),
                Shipment.booking_state == BookingState.CONFIRMED,
                Shipment.cancelled_at.is_(None),
                *_route_filter(route_groups),
            )
        )
        or 0
    )

    rows: list[dict] = []
    for state in BookingState:
        rows.append(
            {
                "group": "booking_state",
                "group_label": "Booking state (booked in period)",
                "state": state.value,
                "state_label": value_label(state.value),
                "count": booking_counts[state.value],
                "link": (
                    f"/shipments?booking_state={state.value}"
                    f"&booked_from={period.from_date.isoformat()}"
                    f"&booked_to={period.to_date.isoformat()}"
                ),
            }
        )
    for state in OperationalState:
        count = operational_counts.get(state.value, 0)
        if count == 0:
            continue
        rows.append(
            {
                "group": "operational_state",
                "group_label": "Current operational state (qualifying shipments in period)",
                "state": state.value,
                "state_label": value_label(state.value),
                "count": count,
                "link": f"/shipments?operational_state={state.value}",
            }
        )
    rows.append(
        {
            "group": "returns",
            "group_label": "Returns",
            "state": "is_return",
            "state_label": "Return shipments handed over in period",
            "count": returns,
            # No `link`. This row used to carry `/shipments?returns_only=true`, a filter
            # the shipment route and the shipment screen both reject, so following it
            # showed the *unfiltered* list while looking like a returns list. The value
            # and the label are true and stay; the drill-through does not, because there
            # is nothing to drill through to. Building the filter, or deleting the row,
            # would each answer OD-22 question 1 by implementation -- removing a control
            # that went nowhere does not.
            "definition": (
                "Reported here only. There is no return-shipment list to open while the "
                "return workflow is undecided."
            ),
        }
    )

    return ReportTable(
        key="shipment_status",
        title="Shipment status distribution",
        scope=PERIOD,
        definition=(
            "Two distributions and one count. Booking state covers every shipment booked "
            "in the period, and is the only place drafts appear. Operational state covers "
            "the qualifying shipments handed over in the period, grouped by where each one "
            "stands *now* — an operational state is current, not historical. Returns are "
            "reported separately and are never added to the qualifying total, because a "
            "return is not another outbound purchase."
        ),
        columns=[
            ReportColumn("group_label", "Grouping"),
            ReportColumn("state_label", "State"),
            ReportColumn("count", "Shipments", "integer"),
        ],
        rows=rows,
        summary={
            "booked_in_period": sum(booking_counts.values()),
            "qualifying_in_period": sum(operational_counts.values()),
            "returns_in_period": returns,
        },
    )


def repeat_customers(
    db: Session, period: ReportPeriod, route_groups: list[str] | None
) -> ReportTable:
    """Period repeat-shipper share, exactly as CRM.md section 12 defines it.

    This is not a cohort retention rate and is never labelled as one.
    """
    shipping_ids = set(
        db.scalars(
            select(func.distinct(Shipment.customer_id))
            .select_from(Shipment)
            .join(Customer, Customer.id == Shipment.customer_id)
            .where(
                *_qualifying_in_period(period),
                *_route_filter(route_groups),
                *_live_customer_filter(),
            )
        ).all()
    )

    repeat = 0
    if shipping_ids:
        lifetime_rows = db.execute(
            select(Shipment.customer_id, func.count(Shipment.id))
            .where(
                Shipment.customer_id.in_(shipping_ids),
                # Lifetime *as of the period end*, so the figure does not change when a
                # later shipment is recorded.
                Shipment.first_handoff_at < period.end_utc,
                *qualifying_shipment_filter(),
            )
            .group_by(Shipment.customer_id)
        ).all()
        repeat = sum(1 for _, count in lifetime_rows if int(count) >= 2)

    total = len(shipping_ids)
    first_time = total - repeat
    share = round(repeat / total, 4) if total else None

    rows = [
        {
            "measure": "shipping_customers",
            "measure_label": "Customers who shipped in this period",
            "value": total,
            "share": None,
            "link": "/shipments?booked_from="
            + period.from_date.isoformat()
            + "&booked_to="
            + period.to_date.isoformat(),
        },
        {
            "measure": "repeat_customers",
            "measure_label": "…holding at least two qualifying lifetime shipments",
            "value": repeat,
            "share": share,
            "link": "/segments",
        },
        {
            "measure": "first_time_customers",
            "measure_label": "…shipping for the first time",
            "value": first_time,
            "share": round(first_time / total, 4) if total else None,
            "link": "/customers?lifecycle_status=new",
        },
    ]

    return ReportTable(
        key="repeat_customers",
        title="Repeat-customer share",
        scope=PERIOD,
        definition=(
            "Customers who shipped during the period and hold at least two qualifying "
            "lifetime shipments as of the period end, divided by all customers who shipped "
            "during the period. This is not a cohort retention rate and must not be "
            "described as one. With nobody shipping, the share is left blank rather than "
            "shown as zero, because there is nothing to divide."
        ),
        columns=[
            ReportColumn("measure_label", "Measure"),
            ReportColumn("value", "Customers", "integer"),
            ReportColumn("share", "Share of shippers", "share"),
        ],
        rows=rows,
        summary={
            "shipping_customers": total,
            "repeat_customers": repeat,
            "first_time_customers": first_time,
            "share": share,
        },
        notes=[]
        if total
        else [
            "No customer shipped in this period, so the repeat share is unknown rather than zero."
        ],
    )


def follow_up_workload(db: Session, period: ReportPeriod) -> ReportTable:
    now = utcnow()
    completed = int(
        db.scalar(
            select(func.count(FollowUpTask.id)).where(
                FollowUpTask.status == TaskStatus.COMPLETED,
                FollowUpTask.completed_at.is_not(None),
                FollowUpTask.completed_at >= period.start_utc,
                FollowUpTask.completed_at < period.end_utc,
            )
        )
        or 0
    )
    created = int(
        db.scalar(
            select(func.count(FollowUpTask.id)).where(
                FollowUpTask.created_at >= period.start_utc,
                FollowUpTask.created_at < period.end_utc,
            )
        )
        or 0
    )
    open_now = int(
        db.scalar(
            select(func.count(FollowUpTask.id)).where(
                FollowUpTask.status.in_(list(OPEN_TASK_STATUSES))
            )
        )
        or 0
    )
    overdue_now = int(
        db.scalar(
            select(func.count(FollowUpTask.id)).where(
                FollowUpTask.status.in_(list(OPEN_TASK_STATUSES)),
                FollowUpTask.due_at.is_not(None),
                FollowUpTask.due_at < now,
            )
        )
        or 0
    )

    # Every link below uses a `view` the follow-ups screen actually renders and filter
    # parameters it actually reads. Three of these four used to name parameters nothing
    # consumed: `?status=completed` was ignored, and `?view=open` and `?view=due` were
    # not one of the screen's two tab ids at all, so the page rendered a tab strip with
    # no tab selected and no panel beneath it. `view=all` defaults `only_open` to true,
    # which is what "open now" means here.
    rows = [
        {
            "measure": "created",
            "measure_label": "Tasks created in period",
            "value": created,
            "scope": PERIOD,
            "link": "/follow-ups",
        },
        {
            "measure": "completed",
            "measure_label": "Tasks completed in period",
            "value": completed,
            "scope": PERIOD,
            "link": "/follow-ups?view=all&only_open=false",
        },
        {
            "measure": "open_now",
            "measure_label": "Tasks open now",
            "value": open_now,
            "scope": CURRENT,
            "link": "/follow-ups?view=all",
        },
        {
            "measure": "overdue_now",
            "measure_label": "Tasks overdue now",
            "value": overdue_now,
            "scope": CURRENT,
            "link": "/follow-ups?view=all&only_overdue=true",
        },
    ]

    return ReportTable(
        key="follow_up_workload",
        title="Follow-up workload",
        scope=PERIOD,
        definition=(
            "Tasks created and completed inside the period, alongside the open and overdue "
            "counts as they stand right now. The two current-state figures are marked as "
            "such: they describe the desk today, not the selected range. Overdue is "
            "derived from an unfinished task's due time, never stored."
        ),
        columns=[
            ReportColumn("measure_label", "Measure"),
            ReportColumn("value", "Tasks", "integer"),
            ReportColumn("scope", "Scope"),
        ],
        rows=rows,
    )


def shipment_exceptions(
    db: Session, period: ReportPeriod, route_groups: list[str] | None
) -> ReportTable:
    """Shipments needing attention now, by route and by how their tracking is sourced."""
    conditions = [
        Shipment.cancelled_at.is_(None),
        shipment_exception_filter(),
        *_route_filter(route_groups),
    ]
    route_rows = db.execute(
        select(Shipment.route_group, func.count(Shipment.id))
        .where(*conditions)
        .group_by(Shipment.route_group)
    ).all()
    route_counts = {route: 0 for route in ROUTE_ORDER if not route_groups or route in route_groups}
    for route_group, count in route_rows:
        route_counts[route_group] = int(count)

    # Tracking source is a property of the active tracking references on a shipment's
    # legs. A shipment with none is reported as ``none`` — honestly, rather than being
    # dropped or attributed to a mode it is not in.
    exception_ids = set(db.scalars(select(Shipment.id).where(*conditions)).all())
    source_counts = dict.fromkeys(TRACKING_SOURCE_ORDER, 0)
    if exception_ids:
        source_rows = db.execute(
            select(ShipmentLeg.shipment_id, LegTrackingReference.source_mode)
            .join(LegTrackingReference, LegTrackingReference.leg_id == ShipmentLeg.id)
            .where(
                ShipmentLeg.shipment_id.in_(exception_ids),
                LegTrackingReference.is_active.is_(True),
            )
        ).all()
        by_shipment: dict[int, set[str]] = {}
        for shipment_id, source_mode in source_rows:
            by_shipment.setdefault(shipment_id, set()).add(source_mode)
        for shipment_id in exception_ids:
            modes = by_shipment.get(shipment_id)
            if not modes:
                source_counts["none"] += 1
                continue
            # A shipment carrying references in more than one mode counts under each,
            # so the source column can sum above the shipment total; the note says so.
            for mode in modes:
                if mode in source_counts:
                    source_counts[mode] += 1

    rows: list[dict] = [
        {
            "group": "route_group",
            "group_label": "By route",
            "key": route,
            "key_label": value_label(route),
            "count": route_counts[route],
            "link": f"/shipments?exceptions_only=true&route_group={route}",
        }
        for route in route_counts
    ]
    rows.extend(
        {
            "group": "tracking_source",
            "group_label": "By tracking source",
            "key": mode,
            "key_label": "No tracking reference" if mode == "none" else value_label(mode),
            "count": source_counts[mode],
            "link": "/shipments?exceptions_only=true",
        }
        for mode in TRACKING_SOURCE_ORDER
    )

    notes = [
        "Current state: these are the shipments in an exception, delivery-attempted, or "
        "return-in-progress state right now, so the date range does not apply.",
        "A shipment carrying tracking references in more than one mode is counted under "
        "each, so the tracking-source figures can total more than the shipment count.",
        "No provider integration is connected, so no shipment can be in a connected-API "
        "tracking mode and that mode is not listed.",
    ]

    return ReportTable(
        key="shipment_exceptions",
        title="Shipment exceptions",
        scope=CURRENT,
        definition=(
            "Shipments currently in an exception, delivery-attempted, or return-in-progress "
            "state, excluding cancelled bookings — grouped by route group, and by the "
            "tracking source mode of their active tracking references."
        ),
        columns=[
            ReportColumn("group_label", "Grouping"),
            ReportColumn("key_label", "Value"),
            ReportColumn("count", "Shipments", "integer"),
        ],
        rows=rows,
        summary={"total": sum(route_counts.values())},
        notes=notes,
    )


def financial_summary(
    db: Session,
    period: ReportPeriod,
    route_groups: list[str] | None,
    *,
    include_costs: bool,
) -> ReportTable:
    """Per-currency recorded revenue, and cost only for a caller entitled to it.

    Currencies are never combined (AC-17). A missing amount is Unknown, never zero, so a
    shipment with no recorded selling amount contributes to neither the total nor the
    coverage count.
    """
    rows_raw = db.execute(
        select(
            Shipment.currency,
            Shipment.selling_amount,
            Shipment.shipping_cost,
            Shipment.surcharges_amount,
            Shipment.discount_amount,
            Shipment.refund_amount,
        ).where(*_qualifying_in_period(period), *_route_filter(route_groups))
    ).all()

    buckets: dict[str, dict] = {}
    unknown_currency = 0
    total_shipments = 0
    for currency, selling, cost, surcharges, discount, refund in rows_raw:
        total_shipments += 1
        if currency is None:
            # Not folded into a default currency: we do not know what this money is.
            unknown_currency += 1
            continue
        bucket = buckets.setdefault(
            currency,
            {
                "currency": currency,
                "recorded_revenue": Decimal("0"),
                "shipments_with_revenue": 0,
                "recorded_cost": Decimal("0"),
                "shipments_with_cost": 0,
                "shipments_total": 0,
            },
        )
        bucket["shipments_total"] += 1
        if selling is not None:
            revenue = Decimal(str(selling))
            if surcharges is not None:
                revenue += Decimal(str(surcharges))
            if discount is not None:
                revenue -= Decimal(str(discount))
            if refund is not None:
                revenue -= Decimal(str(refund))
            bucket["recorded_revenue"] += revenue
            bucket["shipments_with_revenue"] += 1
        if cost is not None:
            bucket["recorded_cost"] += Decimal(str(cost))
            bucket["shipments_with_cost"] += 1

    rows: list[dict] = []
    for currency in sorted(buckets):
        bucket = buckets[currency]
        row = {
            "currency": currency,
            "recorded_revenue": bucket["recorded_revenue"]
            if bucket["shipments_with_revenue"]
            else None,
            "shipments_with_revenue": bucket["shipments_with_revenue"],
            "shipments_total": bucket["shipments_total"],
            "link": "/shipments",
        }
        if include_costs:
            has_cost = bucket["shipments_with_cost"] > 0
            row["recorded_cost"] = bucket["recorded_cost"] if has_cost else None
            row["shipments_with_cost"] = bucket["shipments_with_cost"]
            # Gross profit only when both sides are recorded for this same currency.
            row["gross_profit"] = (
                bucket["recorded_revenue"] - bucket["recorded_cost"]
                if bucket["shipments_with_revenue"] and has_cost
                else None
            )
        rows.append(row)

    columns = [
        ReportColumn("currency", "Currency"),
        ReportColumn("recorded_revenue", "Recorded revenue", "money"),
        ReportColumn("shipments_with_revenue", "Shipments with revenue", "integer"),
        ReportColumn("shipments_total", "Qualifying shipments", "integer"),
    ]
    if include_costs:
        columns.extend(
            [
                ReportColumn("recorded_cost", "Recorded direct cost", "money"),
                ReportColumn("shipments_with_cost", "Shipments with cost", "integer"),
                ReportColumn("gross_profit", "Gross profit", "money"),
            ]
        )

    notes = [
        "Currencies are never combined. No conversion rate has been recorded, so each "
        "currency is reported on its own line.",
        "A missing amount means Unknown and is excluded from the total; it is never "
        "treated as zero.",
        "Revenue excludes sales tax and is recorded manually. It is a record of what was "
        "entered, not an accounting figure.",
    ]
    if unknown_currency:
        notes.append(
            f"{unknown_currency} qualifying shipment(s) in this period have no recorded "
            "currency and appear in no currency line."
        )
    if not include_costs:
        notes.append("Direct costs and gross profit are not included in this report for your role.")

    return ReportTable(
        key=FINANCIAL_REPORT_KEY,
        title="Financial summary",
        scope=PERIOD,
        definition=(
            "Recorded revenue over qualifying shipments handed over in the period, grouped "
            "by currency. Revenue is the recorded selling amount plus surcharges, less "
            "discounts and refunds, over the shipments where a selling amount was entered. "
            "Coverage counts are shown alongside so partial data cannot look complete."
        ),
        columns=columns,
        rows=rows,
        summary={
            "shipments_total": total_shipments,
            "unknown_currency_shipments": unknown_currency,
            "currencies": len(rows),
            "includes_costs": include_costs,
        },
        notes=notes,
    )


# --- Composition -------------------------------------------------------------


def build_report(
    db: Session,
    key: str,
    *,
    period: ReportPeriod,
    thresholds: LifecycleThresholds,
    route_groups: list[str] | None,
    role: str,
) -> ReportTable:
    """Build one report, enforcing the financial permission structurally."""
    if key not in available_report_keys(role):
        # A caller without ``financial:read`` is told the report does not exist for them,
        # not that it exists and is forbidden.
        raise ValidationError(f"Unknown report: {key}", field="report")

    if key == "customer_growth":
        return customer_growth(db, period)
    if key == "customer_lifecycle":
        return customer_lifecycle(db, period, thresholds)
    if key == "route_mix":
        return route_mix(db, period, route_groups)
    if key == "shipment_volume":
        return shipment_volume(db, period, route_groups)
    if key == "shipment_status":
        return shipment_status(db, period, route_groups)
    if key == "repeat_customers":
        return repeat_customers(db, period, route_groups)
    if key == "follow_up_workload":
        return follow_up_workload(db, period)
    if key == "shipment_exceptions":
        return shipment_exceptions(db, period, route_groups)
    if key == FINANCIAL_REPORT_KEY:
        return financial_summary(
            db,
            period,
            route_groups,
            include_costs=Permission.FINANCIAL_COST_READ in permissions_for(role),
        )
    raise ValidationError(f"Unknown report: {key}", field="report")


def build_all(
    db: Session,
    *,
    period: ReportPeriod,
    thresholds: LifecycleThresholds,
    route_groups: list[str] | None,
    role: str,
) -> list[ReportTable]:
    return [
        build_report(
            db,
            key,
            period=period,
            thresholds=thresholds,
            route_groups=route_groups,
            role=role,
        )
        for key in available_report_keys(role)
    ]


def coverage_notes(
    db: Session, period: ReportPeriod, route_groups: list[str] | None = None
) -> list[str]:
    """Notes that apply to the whole report set, describing what the data can support.

    The shipment counts honour the route filter like every figure beneath them. The
    cancelled count did not until UAT round 3: "N booking(s) were cancelled" counted every
    route while the reports it qualified were limited to one. Merged customers have no
    route, so that note is unchanged.
    """
    notes: list[str] = []
    routes = _route_filter(route_groups)
    qualifying = int(
        db.scalar(select(func.count(Shipment.id)).where(*_qualifying_in_period(period), *routes))
        or 0
    )
    if qualifying == 0:
        notes.append(
            "No qualifying shipment was handed over in this period. Shipment reports are "
            "empty rather than zero-filled where a figure would be undefined."
        )
    drafts = int(
        db.scalar(
            select(func.count(Shipment.id)).where(
                Shipment.booking_date >= period.start_utc,
                Shipment.booking_date < period.end_utc,
                Shipment.booking_state == BookingState.DRAFT,
                *routes,
            )
        )
        or 0
    )
    if drafts:
        notes.append(
            f"{drafts} draft booking(s) were created in this period. Drafts are excluded "
            "from every shipment metric except the booking-state distribution."
        )
    cancelled = int(
        db.scalar(
            select(func.count(Shipment.id)).where(
                Shipment.cancelled_at >= period.start_utc,
                Shipment.cancelled_at < period.end_utc,
                *routes,
            )
        )
        or 0
    )
    if cancelled:
        notes.append(
            f"{cancelled} booking(s) were cancelled in this period and are excluded from "
            "qualifying-shipment figures. A cancel-and-rebook pair contributes one "
            "shipment, not two."
        )
    merged = int(
        db.scalar(
            select(func.count(Customer.id)).where(Customer.merged_into_customer_id.is_not(None))
        )
        or 0
    )
    if merged:
        notes.append(
            f"{merged} customer record(s) have been merged into another. They are excluded "
            "from customer counts; the surviving record carries their history."
        )
    notes.append(
        "No prior-period comparison is shown. A change figure is only meaningful with a "
        "comparable prior period, and inventing one would be worse than omitting it."
    )
    return notes


def package_and_leg_guard(
    db: Session, period: ReportPeriod, route_groups: list[str] | None = None
) -> dict:
    """Context figures proving shipments are counted once (AC-14).

    Returned alongside the reports so an operator can see that a period with 30 shipments
    and 74 packages reports 30, and that the difference is visible rather than silent.

    The route filter applies here exactly as it applies to every report beneath it. It did
    not until the 2026-10-14 fix pack (item 8): the headline counted every route while
    the route-mix table beside it honoured the filter, and the two disagreed on the page.
    """
    from app.models import ShipmentPackage

    qualifying_ids = (
        select(Shipment.id)
        .where(*_qualifying_in_period(period), *_route_filter(route_groups))
        .subquery()
    )
    packages = int(
        db.scalar(
            select(func.count(ShipmentPackage.id)).where(
                ShipmentPackage.shipment_id.in_(select(qualifying_ids.c.id))
            )
        )
        or 0
    )
    legs = int(
        db.scalar(
            select(func.count(ShipmentLeg.id)).where(
                ShipmentLeg.shipment_id.in_(select(qualifying_ids.c.id))
            )
        )
        or 0
    )
    shipments = int(
        db.scalar(
            select(func.count(Shipment.id)).where(
                *_qualifying_in_period(period), *_route_filter(route_groups)
            )
        )
        or 0
    )
    active_packages = int(
        db.scalar(
            select(func.count(ShipmentPackage.id)).where(
                ShipmentPackage.shipment_id.in_(select(qualifying_ids.c.id)),
                ShipmentPackage.is_active.is_(True),
            )
        )
        or 0
    )
    note = (
        "Every shipment figure in these reports counts the shipment once. Packages and "
        "transport legs are shown here only so the difference is visible."
    )
    if route_groups:
        labels = ", ".join(ROUTE_GROUP_LABELS.get(route, route) for route in route_groups)
        note += f" These figures are limited to the selected route(s): {labels}."
    return {
        "qualifying_shipments": shipments,
        "packages_on_those_shipments": packages,
        "active_packages_on_those_shipments": active_packages,
        "legs_on_those_shipments": legs,
        "route_groups": list(route_groups or []),
        "note": note,
    }
