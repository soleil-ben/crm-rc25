"""Dashboard aggregates computed from real records (CRM.md section 12).

Rules honoured here:

* every KPI is a database query, never a sample value;
* a comparison line is returned only when a genuine prior-period figure exists;
* queue cards report current state and say so, independent of the date range;
* every aggregate carries the filter needed to open its supporting records.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.enums import (
    OPEN_TASK_STATUSES,
    BookingState,
    LifecycleStatus,
    OperationalState,
    ServiceIssueStatus,
)
from app.core.time_utils import utcnow
from app.models import Customer, FollowUpTask, OrganizationSettings, ServiceIssue, Shipment
from app.services.activity_service import (
    LifecycleThresholds,
    customers_with_lifecycle,
    qualifying_shipment_filter,
    shipment_exception_filter,
)

ACTIVE_OPERATIONAL_STATES = [
    OperationalState.AWAITING_PARCEL,
    OperationalState.RECEIVED_AT_SOLARIS,
    OperationalState.PROCESSING,
    OperationalState.DEPARTED_ORIGIN,
    OperationalState.IN_TRANSIT,
    OperationalState.CUSTOMS_PROCESSING,
    OperationalState.ARRIVED_DESTINATION,
    OperationalState.OUT_FOR_DELIVERY,
    OperationalState.PARTIALLY_DELIVERED,
]


@dataclass
class KpiCard:
    key: str
    label: str
    value: int
    definition: str
    link: str
    scope: str = "period"  # "period" or "current"
    comparison_value: int | None = None
    comparison_label: str | None = None
    tone: str = "neutral"


@dataclass
class DashboardSummary:
    period_start: datetime
    period_end: datetime
    previous_period_available: bool
    kpis: list[KpiCard] = field(default_factory=list)
    queues: list[KpiCard] = field(default_factory=list)
    shipment_trend: list[dict] = field(default_factory=list)
    route_mix: list[dict] = field(default_factory=list)
    lifecycle_mix: list[dict] = field(default_factory=list)
    follow_up_queue: list[dict] = field(default_factory=list)
    recent_customers: list[dict] = field(default_factory=list)
    repeat_shipper_share: dict | None = None
    data_notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def _active_shipments_link() -> str:
    """The shipment list, filtered to exactly what the Active shipments card counted.

    Derived from the same constant the count uses, so the card and the list cannot drift
    apart. The shipment route and the shipment screen both accept repeated
    ``operational_state`` values, which is what makes an exact drill-through possible here
    rather than an approximate one.
    """
    states = "".join(f"&operational_state={state.value}" for state in ACTIVE_OPERATIONAL_STATES)
    return f"/shipments?booking_state={BookingState.CONFIRMED.value}{states}"


def _count(db: Session, stmt) -> int:
    return int(db.scalar(stmt) or 0)


def _bucket_trend(rows, period_start: datetime, period_end: datetime) -> list[dict]:
    """Group qualifying shipments into daily or weekly buckets depending on span."""
    span_days = max(1, (period_end - period_start).days)
    # Daily points over a month read as noise; switch to weekly past a fortnight.
    weekly = span_days > 14
    buckets: dict[tuple[str, str], int] = {}
    for handoff_at, route_group in rows:
        if handoff_at is None:
            continue
        if weekly:
            start_of_week = (handoff_at - timedelta(days=handoff_at.weekday())).date()
            label = start_of_week.isoformat()
        else:
            label = handoff_at.date().isoformat()
        key = (label, route_group)
        buckets[key] = buckets.get(key, 0) + 1
    return [
        {
            "bucket": label,
            "route_group": route_group,
            "count": count,
            "granularity": "week" if weekly else "day",
        }
        for (label, route_group), count in sorted(buckets.items())
    ]


def build_summary(
    db: Session,
    *,
    org: OrganizationSettings | None,
    period_start: datetime,
    period_end: datetime,
    viewer_user_id: int | None = None,
) -> DashboardSummary:
    thresholds = LifecycleThresholds.from_settings(org)
    now = utcnow()
    span = period_end - period_start
    previous_start = period_start - span
    earliest_customer = db.scalar(select(func.min(Customer.created_at)))
    previous_period_available = (
        earliest_customer is not None and earliest_customer <= previous_start
    )

    summary = DashboardSummary(
        period_start=period_start,
        period_end=period_end,
        previous_period_available=previous_period_available,
    )

    # --- KPI: new customers (period) ------------------------------------
    new_customers = _count(
        db,
        select(func.count(Customer.id)).where(
            Customer.created_at >= period_start,
            Customer.created_at < period_end,
            Customer.merged_into_customer_id.is_(None),
        ),
    )
    previous_new_customers = (
        _count(
            db,
            select(func.count(Customer.id)).where(
                Customer.created_at >= previous_start,
                Customer.created_at < period_start,
                Customer.merged_into_customer_id.is_(None),
            ),
        )
        if previous_period_available
        else None
    )
    summary.kpis.append(
        KpiCard(
            key="new_customers",
            label="New customers",
            value=new_customers,
            definition="Customer records created in the selected period.",
            link=f"/customers?created_from={period_start.date()}&created_to={period_end.date()}",
            comparison_value=previous_new_customers,
            comparison_label="vs. previous period" if previous_period_available else None,
        )
    )

    # --- KPI: active shipments (current state) ---------------------------
    active_shipments = _count(
        db,
        select(func.count(Shipment.id)).where(
            Shipment.booking_state == BookingState.CONFIRMED,
            Shipment.cancelled_at.is_(None),
            Shipment.operational_state.in_([state.value for state in ACTIVE_OPERATIONAL_STATES]),
        ),
    )
    summary.kpis.append(
        KpiCard(
            key="active_shipments",
            label="Active shipments",
            value=active_shipments,
            definition=(
                "Confirmed shipments currently between handoff and final delivery. "
                "Current state, not limited by the date range."
            ),
            # Built from ACTIVE_OPERATIONAL_STATES rather than written out, so the card
            # and the list it opens can never disagree. It used to be
            # `/shipments?status=active`: `status` is not a filter the shipment route or
            # the shipment screen accepts, so following the card showed the *unfiltered*
            # list while appearing to show the active ones.
            link=_active_shipments_link(),
            scope="current",
        )
    )

    # --- KPI: follow-ups due (current state) -----------------------------
    follow_ups_due = _count(
        db,
        select(func.count(FollowUpTask.id)).where(
            FollowUpTask.status.in_(list(OPEN_TASK_STATUSES)),
            FollowUpTask.due_at.is_not(None),
            FollowUpTask.due_at < now + timedelta(days=1),
        ),
    )
    overdue = _count(
        db,
        select(func.count(FollowUpTask.id)).where(
            FollowUpTask.status.in_(list(OPEN_TASK_STATUSES)),
            FollowUpTask.due_at.is_not(None),
            FollowUpTask.due_at < now,
        ),
    )
    summary.kpis.append(
        KpiCard(
            key="follow_ups_due",
            label="Follow-ups due",
            value=follow_ups_due,
            definition=(
                "Open follow-up tasks that are overdue or due within the next 24 hours. "
                "Current state."
            ),
            # `?view=due` was not one of the follow-up screen's two tab ids, so the page
            # rendered a tab strip with nothing selected and no panel under it. `view=all`
            # is a real tab, and it opens the open-task list -- which contains every task
            # this card counts. `only_overdue=true` would have shown *fewer* rows than the
            # number on the card, because the card also counts tasks due in the next 24
            # hours; a drill-through that under-shows its own figure is its own defect.
            link="/follow-ups?view=all",
            scope="current",
            tone="warning" if overdue else "neutral",
        )
    )

    # --- KPI: delivery exceptions (current state) ------------------------
    exceptions = _count(
        db,
        select(func.count(Shipment.id)).where(
            Shipment.cancelled_at.is_(None), shipment_exception_filter()
        ),
    )
    unresolved_issues = _count(
        db,
        select(func.count(ServiceIssue.id)).where(
            ServiceIssue.status.in_([ServiceIssueStatus.OPEN, ServiceIssueStatus.IN_REVIEW])
        ),
    )
    summary.kpis.append(
        KpiCard(
            key="delivery_exceptions",
            label="Delivery exceptions",
            value=exceptions,
            definition=(
                "Shipments in an exception, delivery-attempted, or return-in-progress state. "
                "Current state."
            ),
            link="/shipments?exceptions_only=true",
            scope="current",
            tone="danger" if exceptions else "neutral",
        )
    )
    summary.queues.append(
        KpiCard(
            key="unresolved_service_issues",
            label="Unresolved service issues",
            value=unresolved_issues,
            definition="Open or in-review service issues across all customers. Current state.",
            link="/customers?has_service_issue=true",
            scope="current",
            tone="danger" if unresolved_issues else "neutral",
        )
    )
    summary.queues.append(
        KpiCard(
            key="customers_at_risk",
            label="Customers at risk or inactive",
            value=0,  # filled from the lifecycle mix below
            definition="Customers whose last qualifying shipment is older than the Active window.",
            link="/customers?lifecycle_status=at_risk&lifecycle_status=inactive",
            scope="current",
        )
    )

    # --- Trend: qualifying shipments per bucket per route -----------------
    # Bucketing happens in Python rather than in a SQLite-only date function, so the
    # query stays portable to PostgreSQL (CRM.md section 3).
    trend_rows = db.execute(
        select(Shipment.first_handoff_at, Shipment.route_group).where(
            Shipment.first_handoff_at >= period_start,
            Shipment.first_handoff_at < period_end,
            *qualifying_shipment_filter(),
        )
    ).all()
    summary.shipment_trend = _bucket_trend(trend_rows, period_start, period_end)

    # --- Route mix --------------------------------------------------------
    route_rows = db.execute(
        select(Shipment.route_group, func.count(Shipment.id))
        .where(
            Shipment.first_handoff_at >= period_start,
            Shipment.first_handoff_at < period_end,
            *qualifying_shipment_filter(),
        )
        .group_by(Shipment.route_group)
        .order_by(func.count(Shipment.id).desc())
    ).all()
    total_route = sum(int(count) for _, count in route_rows)
    summary.route_mix = [
        {
            "route_group": route_group,
            "count": int(count),
            "share": round(int(count) / total_route, 4) if total_route else None,
            "link": f"/customers?observed_route={route_group}",
        }
        for route_group, count in route_rows
    ]

    # --- Lifecycle distribution ------------------------------------------
    for status in (
        LifecycleStatus.PROSPECT,
        LifecycleStatus.NEW,
        LifecycleStatus.ACTIVE,
        LifecycleStatus.AT_RISK,
        LifecycleStatus.INACTIVE,
    ):
        member_ids = customers_with_lifecycle(db, thresholds, [status.value])
        summary.lifecycle_mix.append(
            {
                "status": status.value,
                "count": len(member_ids),
                "definition": thresholds.describe()[status],
                "link": f"/customers?lifecycle_status={status.value}",
            }
        )

    at_risk_total = sum(
        row["count"]
        for row in summary.lifecycle_mix
        if row["status"] in (LifecycleStatus.AT_RISK, LifecycleStatus.INACTIVE)
    )
    for queue in summary.queues:
        if queue.key == "customers_at_risk":
            queue.value = at_risk_total
            queue.tone = "warning" if at_risk_total else "neutral"

    # --- Follow-up queue: overdue first ----------------------------------
    queue_rows = db.execute(
        select(FollowUpTask, Customer)
        .join(Customer, Customer.id == FollowUpTask.customer_id)
        .where(FollowUpTask.status.in_(list(OPEN_TASK_STATUSES)), FollowUpTask.due_at.is_not(None))
        .order_by(FollowUpTask.due_at.asc())
        .limit(8)
    ).all()
    summary.follow_up_queue = [
        {
            "id": task.id,
            "subject": task.subject,
            "purpose": task.purpose,
            "priority": task.priority,
            "status": task.status,
            "due_at": task.due_at,
            "is_overdue": task.due_at is not None and task.due_at < now,
            "assignee_user_id": task.assignee_user_id,
            "customer_id": customer.id,
            "customer_public_id": customer.public_id,
            "customer_name": customer.full_name,
        }
        for task, customer in queue_rows
    ]

    # --- Recently added customers ----------------------------------------
    recent_rows = db.scalars(
        select(Customer)
        .where(Customer.merged_into_customer_id.is_(None))
        .order_by(Customer.created_at.desc())
        .limit(6)
    ).all()
    summary.recent_customers = [
        {
            "id": customer.id,
            "public_id": customer.public_id,
            "full_name": customer.full_name,
            "city": customer.city,
            "country_code": customer.country_code,
            "primary_route_group": customer.primary_route_group,
            "created_at": customer.created_at,
        }
        for customer in recent_rows
    ]

    # --- Period repeat-shipper share --------------------------------------
    summary.repeat_shipper_share = _repeat_shipper_share(db, period_start, period_end)

    if not summary.shipment_trend:
        summary.data_notes.append(
            "No qualifying shipments were recorded in this period, so trend and route "
            "charts are empty rather than zero."
        )
    if not previous_period_available:
        summary.data_notes.append(
            "There is not enough history before this period to show a comparison, so "
            "change figures are omitted."
        )
    return summary


def _repeat_shipper_share(db: Session, period_start: datetime, period_end: datetime) -> dict | None:
    """Period repeat-shipper share, exactly as defined in CRM.md section 12.

    Customers shipping during the period who hold at least two qualifying lifetime
    shipments as of period end, divided by all customers shipping during the period.
    This is not a cohort retention rate and is never labelled as one.
    """
    shipping_customer_ids = set(
        db.scalars(
            select(func.distinct(Shipment.customer_id)).where(
                Shipment.first_handoff_at >= period_start,
                Shipment.first_handoff_at < period_end,
                *qualifying_shipment_filter(),
            )
        ).all()
    )
    if not shipping_customer_ids:
        return None

    lifetime_rows = db.execute(
        select(Shipment.customer_id, func.count(Shipment.id))
        .where(
            Shipment.customer_id.in_(shipping_customer_ids),
            Shipment.first_handoff_at < period_end,
            *qualifying_shipment_filter(),
        )
        .group_by(Shipment.customer_id)
    ).all()
    repeat = sum(1 for _, count in lifetime_rows if int(count) >= 2)
    total = len(shipping_customer_ids)
    return {
        "repeat_customers": repeat,
        "shipping_customers": total,
        "share": round(repeat / total, 4),
        "definition": (
            "Customers who shipped in this period and hold at least two qualifying lifetime "
            "shipments as of the period end, divided by all customers who shipped in the period. "
            "This is not a cohort retention rate."
        ),
    }
