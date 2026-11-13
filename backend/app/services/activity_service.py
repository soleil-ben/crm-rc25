"""Derived customer activity, lifecycle status, and financial coverage.

Every number here is computed from qualifying shipment records; nothing is stored in a
manual counter (CRM.md section 4, AC-14). Financial summaries keep currencies separate
and report missing values as Unknown rather than zero (AC-17).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy import Select, and_, func, select
from sqlalchemy.orm import Session

from app.core.enums import (
    EXCEPTION_OPERATIONAL_STATES,
    OPEN_TASK_STATUSES,
    BookingState,
    LifecycleStatus,
    ServiceIssueStatus,
    TaskStatus,
)
from app.core.time_utils import utcnow
from app.models import (
    Customer,
    FollowUpTask,
    OrganizationSettings,
    Referral,
    ServiceIssue,
    Shipment,
)


@dataclass(frozen=True)
class LifecycleThresholds:
    """Configurable thresholds. Defaults are initial business assumptions, not benchmarks."""

    new_days: int = 30
    active_days: int = 60
    at_risk_days: int = 90

    @classmethod
    def from_settings(cls, org: OrganizationSettings | None) -> LifecycleThresholds:
        if org is None:
            return cls()
        return cls(
            new_days=org.lifecycle_new_days,
            active_days=org.lifecycle_active_days,
            at_risk_days=org.lifecycle_at_risk_days,
        )

    def describe(self) -> dict[str, str]:
        return {
            LifecycleStatus.PROSPECT: "No qualifying shipments yet.",
            LifecycleStatus.NEW: (
                f"Exactly one qualifying shipment within the last {self.new_days} days."
            ),
            LifecycleStatus.ACTIVE: f"Shipped within the last {self.active_days} days.",
            LifecycleStatus.AT_RISK: (
                f"Last shipment {self.active_days + 1}-{self.at_risk_days} days ago."
            ),
            LifecycleStatus.INACTIVE: f"Last shipment more than {self.at_risk_days} days ago.",
            LifecycleStatus.ARCHIVED: "Archived by staff. Set independently of shipping activity.",
        }


@dataclass
class CurrencyTotals:
    currency: str
    recorded_revenue: Decimal = Decimal("0")
    recorded_cost: Decimal = Decimal("0")
    shipments_with_revenue: int = 0
    shipments_with_cost: int = 0

    @property
    def gross_profit(self) -> Decimal | None:
        """Only meaningful when both sides are recorded for the same currency."""
        if self.shipments_with_revenue == 0 or self.shipments_with_cost == 0:
            return None
        return self.recorded_revenue - self.recorded_cost


@dataclass
class CustomerActivity:
    total_qualifying_shipments: int = 0
    total_bookings: int = 0
    delivered_shipments: int = 0
    first_shipment_at: datetime | None = None
    last_shipment_at: datetime | None = None
    is_repeat_customer: bool = False
    observed_primary_route_group: str | None = None
    route_counts: dict[str, int] = field(default_factory=dict)
    lifecycle_status: str = LifecycleStatus.PROSPECT
    days_since_last_shipment: int | None = None
    referral_count: int = 0
    qualified_referral_count: int = 0
    open_task_count: int = 0
    overdue_task_count: int = 0
    next_follow_up_at: datetime | None = None
    last_follow_up_at: datetime | None = None
    unresolved_issue_count: int = 0
    has_service_issue: bool = False
    financial_by_currency: list[CurrencyTotals] = field(default_factory=list)
    financial_coverage_shipments: int = 0


def qualifying_shipment_filter() -> list:
    """SQL predicate for a qualifying shipment (CRM.md section 4)."""
    return [
        Shipment.booking_state == BookingState.CONFIRMED,
        Shipment.first_handoff_at.is_not(None),
        Shipment.cancelled_at.is_(None),
        Shipment.is_return.is_(False),
    ]


def qualifying_shipments(customer_id: int | None = None) -> Select:
    stmt = select(Shipment).where(*qualifying_shipment_filter())
    if customer_id is not None:
        stmt = stmt.where(Shipment.customer_id == customer_id)
    return stmt


def lifecycle_status_for(
    *,
    is_archived: bool,
    qualifying_count: int,
    last_shipment_at: datetime | None,
    thresholds: LifecycleThresholds,
    now: datetime | None = None,
) -> str:
    """Lifecycle rules from CRM.md section 4.

    Archived is a manual state and outranks the derived values. Service restrictions and
    do-not-contact are stored separately and never appear here.
    """
    if is_archived:
        return LifecycleStatus.ARCHIVED
    if qualifying_count == 0 or last_shipment_at is None:
        return LifecycleStatus.PROSPECT

    # Exact elapsed time (not truncated days) so this matches the SQL expression the
    # segment engine compiles from the same thresholds.
    reference = now or utcnow()
    elapsed = reference - last_shipment_at

    if qualifying_count == 1 and elapsed <= timedelta(days=thresholds.new_days):
        return LifecycleStatus.NEW
    if elapsed <= timedelta(days=thresholds.active_days):
        return LifecycleStatus.ACTIVE
    if elapsed <= timedelta(days=thresholds.at_risk_days):
        return LifecycleStatus.AT_RISK
    return LifecycleStatus.INACTIVE


def compute_customer_activity(
    db: Session,
    customer: Customer,
    thresholds: LifecycleThresholds,
    *,
    include_financials: bool = False,
    include_costs: bool = False,
) -> CustomerActivity:
    """Compute every derived activity field for one customer."""
    activity = CustomerActivity()
    now = utcnow()

    # --- Shipment-derived values ----------------------------------------
    row = db.execute(
        select(
            func.count(Shipment.id),
            func.min(Shipment.first_handoff_at),
            func.max(Shipment.first_handoff_at),
        ).where(Shipment.customer_id == customer.id, *qualifying_shipment_filter())
    ).one()
    activity.total_qualifying_shipments = int(row[0] or 0)
    activity.first_shipment_at = row[1]
    activity.last_shipment_at = row[2]
    activity.is_repeat_customer = activity.total_qualifying_shipments >= 2

    # Bookings and delivered shipments are shown separately so demand is distinguishable
    # from actual shipping activity (CRM.md section 4).
    activity.total_bookings = int(
        db.scalar(
            select(func.count(Shipment.id)).where(
                Shipment.customer_id == customer.id,
                Shipment.booking_state != BookingState.DRAFT,
            )
        )
        or 0
    )
    activity.delivered_shipments = int(
        db.scalar(
            select(func.count(Shipment.id)).where(
                Shipment.customer_id == customer.id,
                Shipment.delivered_at.is_not(None),
                *qualifying_shipment_filter(),
            )
        )
        or 0
    )

    route_rows = db.execute(
        select(Shipment.route_group, func.count(Shipment.id))
        .where(Shipment.customer_id == customer.id, *qualifying_shipment_filter())
        .group_by(Shipment.route_group)
        .order_by(func.count(Shipment.id).desc(), Shipment.route_group.asc())
    ).all()
    activity.route_counts = {route: int(count) for route, count in route_rows}
    if route_rows:
        activity.observed_primary_route_group = route_rows[0][0]

    if activity.last_shipment_at is not None:
        activity.days_since_last_shipment = (now - activity.last_shipment_at).days

    activity.lifecycle_status = lifecycle_status_for(
        is_archived=customer.is_archived,
        qualifying_count=activity.total_qualifying_shipments,
        last_shipment_at=activity.last_shipment_at,
        thresholds=thresholds,
        now=now,
    )

    # --- Referrals -------------------------------------------------------
    activity.referral_count = int(
        db.scalar(
            select(func.count(Referral.id)).where(Referral.referrer_customer_id == customer.id)
        )
        or 0
    )
    activity.qualified_referral_count = int(
        db.scalar(
            select(func.count(func.distinct(Referral.referred_customer_id)))
            .select_from(Referral)
            .join(Shipment, Shipment.customer_id == Referral.referred_customer_id)
            .where(Referral.referrer_customer_id == customer.id, *qualifying_shipment_filter())
        )
        or 0
    )

    # --- Follow-up derived fields ---------------------------------------
    open_conditions = and_(
        FollowUpTask.customer_id == customer.id,
        FollowUpTask.status.in_(list(OPEN_TASK_STATUSES)),
    )
    activity.open_task_count = int(
        db.scalar(select(func.count(FollowUpTask.id)).where(open_conditions)) or 0
    )
    activity.overdue_task_count = int(
        db.scalar(
            select(func.count(FollowUpTask.id)).where(
                open_conditions, FollowUpTask.due_at.is_not(None), FollowUpTask.due_at < now
            )
        )
        or 0
    )
    activity.next_follow_up_at = db.scalar(
        select(func.min(FollowUpTask.due_at)).where(
            open_conditions, FollowUpTask.due_at.is_not(None)
        )
    )
    activity.last_follow_up_at = db.scalar(
        select(func.max(FollowUpTask.completed_at)).where(
            FollowUpTask.customer_id == customer.id,
            FollowUpTask.status == TaskStatus.COMPLETED,
        )
    )

    # --- Service issues --------------------------------------------------
    activity.unresolved_issue_count = int(
        db.scalar(
            select(func.count(ServiceIssue.id)).where(
                ServiceIssue.customer_id == customer.id,
                ServiceIssue.status.in_([ServiceIssueStatus.OPEN, ServiceIssueStatus.IN_REVIEW]),
            )
        )
        or 0
    )
    activity.has_service_issue = activity.unresolved_issue_count > 0

    if include_financials:
        activity.financial_by_currency, activity.financial_coverage_shipments = _financial_summary(
            db, customer.id, include_costs=include_costs
        )

    return activity


def _financial_summary(
    db: Session, customer_id: int, *, include_costs: bool
) -> tuple[list[CurrencyTotals], int]:
    """Per-currency totals. Currencies are never merged and missing values stay Unknown."""
    rows = db.execute(
        select(
            Shipment.currency,
            Shipment.selling_amount,
            Shipment.shipping_cost,
            Shipment.surcharges_amount,
            Shipment.discount_amount,
            Shipment.refund_amount,
        ).where(Shipment.customer_id == customer_id, *qualifying_shipment_filter())
    ).all()

    buckets: dict[str, CurrencyTotals] = {}
    covered = 0
    for currency, selling, cost, surcharges, discount, refund in rows:
        if currency is None:
            continue
        bucket = buckets.setdefault(currency, CurrencyTotals(currency=currency))
        has_value = False
        if selling is not None:
            revenue = Decimal(str(selling))
            if surcharges is not None:
                revenue += Decimal(str(surcharges))
            if discount is not None:
                revenue -= Decimal(str(discount))
            if refund is not None:
                revenue -= Decimal(str(refund))
            bucket.recorded_revenue += revenue
            bucket.shipments_with_revenue += 1
            has_value = True
        if include_costs and cost is not None:
            bucket.recorded_cost += Decimal(str(cost))
            bucket.shipments_with_cost += 1
            has_value = True
        if has_value:
            covered += 1

    return sorted(buckets.values(), key=lambda item: item.currency), covered


def customers_with_lifecycle(
    db: Session, thresholds: LifecycleThresholds, statuses: list[str]
) -> list[int]:
    """Customer ids whose derived lifecycle status is in ``statuses``.

    Used by segment filters and dashboard queues; expressed in SQL so it scales past the
    seed dataset.
    """
    now = utcnow()
    agg = (
        select(
            Shipment.customer_id.label("customer_id"),
            func.count(Shipment.id).label("qualifying_count"),
            func.max(Shipment.first_handoff_at).label("last_shipment_at"),
        )
        .where(*qualifying_shipment_filter())
        .group_by(Shipment.customer_id)
        .subquery()
    )
    rows = db.execute(
        select(Customer.id, Customer.is_archived, agg.c.qualifying_count, agg.c.last_shipment_at)
        .outerjoin(agg, agg.c.customer_id == Customer.id)
        .where(Customer.merged_into_customer_id.is_(None))
    ).all()

    wanted = set(statuses)
    matches: list[int] = []
    for customer_id, is_archived, count, last_at in rows:
        status = lifecycle_status_for(
            is_archived=bool(is_archived),
            qualifying_count=int(count or 0),
            last_shipment_at=last_at,
            thresholds=thresholds,
            now=now,
        )
        if status in wanted:
            matches.append(customer_id)
    return matches


def customer_ids_with_overdue_tasks(db: Session) -> list[int]:
    now = utcnow()
    rows = db.scalars(
        select(func.distinct(FollowUpTask.customer_id)).where(
            FollowUpTask.status.in_(list(OPEN_TASK_STATUSES)),
            FollowUpTask.due_at.is_not(None),
            FollowUpTask.due_at < now,
        )
    ).all()
    return list(rows)


def customer_ids_with_service_issues(db: Session) -> list[int]:
    rows = db.scalars(
        select(func.distinct(ServiceIssue.customer_id)).where(
            ServiceIssue.status.in_([ServiceIssueStatus.OPEN, ServiceIssueStatus.IN_REVIEW])
        )
    ).all()
    return list(rows)


def shipment_exception_filter():
    """Predicate matching shipments in an exception-family operational state."""
    return Shipment.operational_state.in_([state.value for state in EXCEPTION_OPERATIONAL_STATES])
