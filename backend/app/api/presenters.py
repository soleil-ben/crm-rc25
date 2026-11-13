"""Model to response mapping.

List responses batch their derived values into a handful of grouped queries rather than
recomputing per row, so the customer list stays a small fixed number of statements.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.enums import OPEN_TASK_STATUSES, ServiceIssueStatus, TaskStatus
from app.core.time_utils import utcnow
from app.models import (
    ConsentEvent,
    Customer,
    CustomerIdAlias,
    CustomerTag,
    FollowUpTask,
    Interaction,
    Referral,
    SavedSegment,
    ServiceIssue,
    Shipment,
    Tag,
    User,
)
from app.schemas.customer import (
    AddressOut,
    CurrencyTotalsOut,
    CustomerActivityOut,
    CustomerDetail,
    CustomerFinancialSummaryOut,
    CustomerListItem,
    DuplicateCandidateOut,
    ReferralOut,
    StaffSummary,
    TagOut,
)
from app.schemas.engagement import (
    ConsentEventOut,
    ConsentStateOut,
    InteractionOut,
    SegmentOut,
    TaskCustomerSummary,
    TaskOut,
)
from app.services import consent_service, segment_service, task_service
from app.services import customer_account_link_policy as link_policy
from app.services.activity_service import (
    CustomerActivity,
    LifecycleThresholds,
    compute_customer_activity,
    lifecycle_status_for,
    qualifying_shipment_filter,
)


def staff_summary(user: User | None) -> StaffSummary | None:
    if user is None:
        return None
    return StaffSummary(id=user.id, full_name=user.full_name, email=user.email, role=user.role)


def _staff_map(db: Session, user_ids: set[int]) -> dict[int, User]:
    ids = {user_id for user_id in user_ids if user_id}
    if not ids:
        return {}
    return {user.id: user for user in db.scalars(select(User).where(User.id.in_(ids))).all()}


def tag_out(tag: Tag) -> TagOut:
    return TagOut(
        id=tag.id,
        slug=tag.slug,
        name=tag.name,
        color_token=tag.color_token,
        description=tag.description,
    )


def customer_list_items(
    db: Session,
    customers: list[Customer],
    thresholds: LifecycleThresholds,
    *,
    duplicate_ids: set[int] | None = None,
) -> list[CustomerListItem]:
    if not customers:
        return []
    ids = [customer.id for customer in customers]
    now = utcnow()

    shipment_rows = db.execute(
        select(
            Shipment.customer_id,
            func.count(Shipment.id),
            func.max(Shipment.first_handoff_at),
        )
        .where(Shipment.customer_id.in_(ids), *qualifying_shipment_filter())
        .group_by(Shipment.customer_id)
    ).all()
    shipment_stats = {row[0]: (int(row[1]), row[2]) for row in shipment_rows}

    next_task_rows = db.execute(
        select(FollowUpTask.customer_id, func.min(FollowUpTask.due_at))
        .where(
            FollowUpTask.customer_id.in_(ids),
            FollowUpTask.status.in_(list(OPEN_TASK_STATUSES)),
            FollowUpTask.due_at.is_not(None),
        )
        .group_by(FollowUpTask.customer_id)
    ).all()
    next_task = {row[0]: row[1] for row in next_task_rows}

    overdue_ids = set(
        db.scalars(
            select(func.distinct(FollowUpTask.customer_id)).where(
                FollowUpTask.customer_id.in_(ids),
                FollowUpTask.status.in_(list(OPEN_TASK_STATUSES)),
                FollowUpTask.due_at.is_not(None),
                FollowUpTask.due_at < now,
            )
        ).all()
    )
    issue_ids = set(
        db.scalars(
            select(func.distinct(ServiceIssue.customer_id)).where(
                ServiceIssue.customer_id.in_(ids),
                ServiceIssue.status.in_([ServiceIssueStatus.OPEN, ServiceIssueStatus.IN_REVIEW]),
            )
        ).all()
    )

    tag_rows = db.execute(
        select(CustomerTag.customer_id, Tag)
        .join(Tag, Tag.id == CustomerTag.tag_id)
        .where(CustomerTag.customer_id.in_(ids))
    ).all()
    tags_by_customer: dict[int, list[Tag]] = {}
    for customer_id, tag in tag_rows:
        tags_by_customer.setdefault(customer_id, []).append(tag)

    owners = _staff_map(db, {customer.owner_user_id for customer in customers})

    items: list[CustomerListItem] = []
    for customer in customers:
        count, last_at = shipment_stats.get(customer.id, (0, None))
        items.append(
            CustomerListItem(
                id=customer.id,
                public_id=customer.public_id,
                full_name=customer.full_name,
                phone_entered=customer.phone_entered,
                email_entered=customer.email_entered,
                city=customer.city,
                province_state=customer.province_state,
                country_code=customer.country_code,
                preferred_language=customer.preferred_language,
                category=customer.category,
                primary_route_group=customer.primary_route_group,
                owner=staff_summary(owners.get(customer.owner_user_id)),
                tags=[
                    tag_out(tag)
                    for tag in sorted(tags_by_customer.get(customer.id, []), key=lambda t: t.name)
                ],
                is_archived=customer.is_archived,
                do_not_contact=customer.do_not_contact,
                created_at=customer.created_at,
                lifecycle_status=lifecycle_status_for(
                    is_archived=customer.is_archived,
                    qualifying_count=count,
                    last_shipment_at=last_at,
                    thresholds=thresholds,
                    now=now,
                ),
                total_qualifying_shipments=count,
                last_shipment_at=last_at,
                next_follow_up_at=next_task.get(customer.id),
                has_overdue_task=customer.id in overdue_ids,
                has_service_issue=customer.id in issue_ids,
                has_duplicate_candidates=bool(duplicate_ids and customer.id in duplicate_ids),
            )
        )
    return items


def activity_out(activity: CustomerActivity) -> CustomerActivityOut:
    return CustomerActivityOut(
        total_qualifying_shipments=activity.total_qualifying_shipments,
        total_bookings=activity.total_bookings,
        delivered_shipments=activity.delivered_shipments,
        first_shipment_at=activity.first_shipment_at,
        last_shipment_at=activity.last_shipment_at,
        is_repeat_customer=activity.is_repeat_customer,
        observed_primary_route_group=activity.observed_primary_route_group,
        route_counts=activity.route_counts,
        lifecycle_status=activity.lifecycle_status,
        days_since_last_shipment=activity.days_since_last_shipment,
        referral_count=activity.referral_count,
        qualified_referral_count=activity.qualified_referral_count,
        open_task_count=activity.open_task_count,
        overdue_task_count=activity.overdue_task_count,
        next_follow_up_at=activity.next_follow_up_at,
        last_follow_up_at=activity.last_follow_up_at,
        unresolved_issue_count=activity.unresolved_issue_count,
        has_service_issue=activity.has_service_issue,
    )


def customer_detail(
    db: Session,
    customer: Customer,
    thresholds: LifecycleThresholds,
    *,
    has_duplicates: bool = False,
) -> CustomerDetail:
    activity = compute_customer_activity(db, customer, thresholds)
    base = customer_list_items(db, [customer], thresholds)[0]
    aliases = db.scalars(
        select(CustomerIdAlias.alias_public_id).where(CustomerIdAlias.customer_id == customer.id)
    ).all()
    return CustomerDetail(
        **base.model_dump(),
        phone_e164=customer.phone_e164,
        email_normalized=customer.email_normalized,
        business_type=customer.business_type,
        business_name=customer.business_name,
        primary_shipping_purpose=customer.primary_shipping_purpose,
        shipping_frequency=customer.shipping_frequency,
        estimated_monthly_shipments=customer.estimated_monthly_shipments,
        preferred_contact_channel=customer.preferred_contact_channel,
        best_contact_time=customer.best_contact_time,
        contact_timezone=customer.contact_timezone,
        service_restriction_note=customer.service_restriction_note,
        notes=customer.notes,
        additional_route_interests=sorted(
            interest.route_group for interest in customer.route_interests
        ),
        archived_at=customer.archived_at,
        archive_reason=customer.archive_reason,
        merged_into_customer_id=customer.merged_into_customer_id,
        former_public_ids=sorted(aliases),
        is_demo_record=customer.is_demo_record,
        activity=activity_out(activity),
        email_held_by_account=link_policy.has_live_account_link(db, customer.id),
    ).model_copy(update={"has_duplicate_candidates": has_duplicates})


def financial_summary_out(
    activity: CustomerActivity, *, include_costs: bool
) -> CustomerFinancialSummaryOut:
    coverage = (
        activity.financial_coverage_shipments / activity.total_qualifying_shipments
        if activity.total_qualifying_shipments
        else None
    )
    note = (
        "Currencies are reported separately and are never combined without a recorded "
        "conversion. Shipments without a recorded amount are Unknown, not zero."
    )
    if not include_costs:
        note += " Carrier and direct costs are hidden for your role."
    return CustomerFinancialSummaryOut(
        by_currency=[
            CurrencyTotalsOut(
                currency=bucket.currency,
                recorded_revenue=bucket.recorded_revenue,
                recorded_cost=bucket.recorded_cost if include_costs else None,
                gross_profit=bucket.gross_profit if include_costs else None,
                shipments_with_revenue=bucket.shipments_with_revenue,
                shipments_with_cost=bucket.shipments_with_cost if include_costs else 0,
            )
            for bucket in activity.financial_by_currency
        ],
        qualifying_shipments=activity.total_qualifying_shipments,
        shipments_with_any_financial_record=activity.financial_coverage_shipments,
        coverage_share=round(coverage, 4) if coverage is not None else None,
        includes_costs=include_costs,
        note=note,
    )


def address_out(address) -> AddressOut:
    return AddressOut.model_validate(address)


def interaction_out(db: Session, interaction: Interaction) -> InteractionOut:
    author = db.get(User, interaction.author_user_id) if interaction.author_user_id else None
    return InteractionOut(
        id=interaction.id,
        customer_id=interaction.customer_id,
        shipment_id=interaction.shipment_id,
        task_id=interaction.task_id,
        occurred_at=interaction.occurred_at,
        channel=interaction.channel,
        direction=interaction.direction,
        subject=interaction.subject,
        body=interaction.body,
        outcome=interaction.outcome,
        visibility=interaction.visibility,
        is_follow_up_completion=interaction.is_follow_up_completion,
        author=staff_summary(author),
        created_at=interaction.created_at,
    )


def interaction_list(db: Session, interactions: list[Interaction]) -> list[InteractionOut]:
    staff = _staff_map(db, {item.author_user_id for item in interactions})
    return [
        InteractionOut(
            id=item.id,
            customer_id=item.customer_id,
            shipment_id=item.shipment_id,
            task_id=item.task_id,
            occurred_at=item.occurred_at,
            channel=item.channel,
            direction=item.direction,
            subject=item.subject,
            body=item.body,
            outcome=item.outcome,
            visibility=item.visibility,
            is_follow_up_completion=item.is_follow_up_completion,
            author=staff_summary(staff.get(item.author_user_id)),
            created_at=item.created_at,
        )
        for item in interactions
    ]


def task_list(db: Session, tasks: list[FollowUpTask]) -> list[TaskOut]:
    if not tasks:
        return []
    now = utcnow()
    customer_ids = {task.customer_id for task in tasks}
    customers = {
        customer.id: customer
        for customer in db.scalars(select(Customer).where(Customer.id.in_(customer_ids))).all()
    }
    staff = _staff_map(
        db,
        {task.assignee_user_id for task in tasks} | {task.created_by_user_id for task in tasks},
    )
    items: list[TaskOut] = []
    for task in tasks:
        customer = customers.get(task.customer_id)
        items.append(
            TaskOut(
                id=task.id,
                customer=TaskCustomerSummary(
                    id=customer.id,
                    public_id=customer.public_id,
                    full_name=customer.full_name,
                    preferred_language=customer.preferred_language,
                ),
                shipment_id=task.shipment_id,
                subject=task.subject,
                detail=task.detail,
                purpose=task.purpose,
                priority=task.priority,
                status=task.status,
                due_at=task.due_at,
                is_overdue=task_service.is_overdue(task, now),
                assignee=staff_summary(staff.get(task.assignee_user_id)),
                created_by=staff_summary(staff.get(task.created_by_user_id)),
                completed_at=task.completed_at,
                outcome=task.outcome,
                cancelled_reason=task.cancelled_reason,
                source_rule=task.source_rule,
                created_at=task.created_at,
            )
        )
    return items


def consent_state_out(state: consent_service.ChannelConsentState) -> ConsentStateOut:
    return ConsentStateOut(
        channel=state.channel,
        address_value=state.address_value,
        status=state.status,
        basis=state.basis,
        obtained_at=state.obtained_at,
        withdrawn_at=state.withdrawn_at,
        expires_at=state.expires_at,
        recorded_at=state.recorded_at,
        source=state.source,
        is_suppressed=state.is_suppressed,
        suppression_reason=state.suppression_reason,
        is_marketing_eligible=state.is_marketing_eligible,
    )


def consent_event_list(db: Session, events: list[ConsentEvent]) -> list[ConsentEventOut]:
    staff = _staff_map(db, {event.recorded_by_user_id for event in events})
    return [
        ConsentEventOut(
            id=event.id,
            channel=event.channel,
            address_value=event.address_value,
            status=event.status,
            basis=event.basis,
            obtained_at=event.obtained_at,
            withdrawn_at=event.withdrawn_at,
            expires_at=event.expires_at,
            source=event.source,
            evidence_reference=event.evidence_reference,
            note=event.note,
            recorded_at=event.recorded_at,
            recorded_by=staff_summary(staff.get(event.recorded_by_user_id)),
            recorded_by_account=_consent_account_actor(event),
        )
        for event in events
    ]


def _consent_account_actor(event: ConsentEvent) -> str | None:
    """``customer_account:CA-...`` when the customer recorded the choice themselves.

    Their own grant or withdrawal from the portal has no staff recorder, and the consent
    history used to show it as ``system`` (UAT round 8). The reference is the one the
    profile service writes, read back under its own shape.
    """
    reference = event.evidence_reference or ""
    if event.source == "customer_account" and reference.startswith("customer_account:CA-"):
        return reference
    return None


def referral_list(
    db: Session, referrals: list[Referral], thresholds: LifecycleThresholds
) -> list[ReferralOut]:
    if not referrals:
        return []
    customer_ids = {referral.referrer_customer_id for referral in referrals} | {
        referral.referred_customer_id for referral in referrals
    }
    customers = {
        customer.id: customer
        for customer in db.scalars(select(Customer).where(Customer.id.in_(customer_ids))).all()
    }
    items = customer_list_items(db, list(customers.values()), thresholds)
    by_id = {item.id: item for item in items}
    qualified_ids = set(
        db.scalars(
            select(func.distinct(Shipment.customer_id)).where(
                Shipment.customer_id.in_(customer_ids), *qualifying_shipment_filter()
            )
        ).all()
    )
    recorder_ids = {
        referral.recorded_by_user_id for referral in referrals if referral.recorded_by_user_id
    }
    recorders = (
        {user.id: user for user in db.scalars(select(User).where(User.id.in_(recorder_ids))).all()}
        if recorder_ids
        else {}
    )
    return [
        ReferralOut(
            id=referral.id,
            referrer=by_id.get(referral.referrer_customer_id),
            referred=by_id.get(referral.referred_customer_id),
            note=referral.note,
            created_at=referral.created_at,
            referred_has_qualifying_shipment=referral.referred_customer_id in qualified_ids,
            recorded_by=staff_summary(recorders.get(referral.recorded_by_user_id)),
        )
        for referral in referrals
    ]


def duplicate_candidates_out(
    db: Session, candidates, thresholds: LifecycleThresholds
) -> list[DuplicateCandidateOut]:
    if not candidates:
        return []
    items = customer_list_items(db, [candidate.customer for candidate in candidates], thresholds)
    by_id = {item.id: item for item in items}
    return [
        DuplicateCandidateOut(
            customer=by_id[candidate.customer.id],
            matched_on=candidate.matched_on,
            confidence=candidate.confidence,
        )
        for candidate in candidates
    ]


def segment_out(
    db: Session,
    segment: SavedSegment,
    thresholds: LifecycleThresholds,
    *,
    include_marketing_count: bool,
) -> SegmentOut:
    definition = segment_service.load_definition(segment.definition_json)
    tag_names = segment_service.resolve_tag_names(db)
    staff_names = {user.id: user.full_name for user in db.scalars(select(User)).all()}
    owner = db.get(User, segment.owner_user_id) if segment.owner_user_id else None
    return SegmentOut(
        id=segment.id,
        slug=segment.slug,
        name=segment.name,
        description=segment.description,
        definition=definition,
        plain_language=segment_service.describe(definition, tag_names, staff_names),
        member_count=segment_service.count_members(db, definition, thresholds),
        marketing_eligible_email_count=(
            segment_service.marketing_eligible_count(db, definition, thresholds)
            if include_marketing_count
            else None
        ),
        is_system=segment.is_system,
        is_shared=segment.is_shared,
        owner=staff_summary(owner),
        created_at=segment.created_at,
        updated_at=segment.updated_at,
    )


def last_follow_up_at(db: Session, customer_id: int) -> datetime | None:
    return db.scalar(
        select(func.max(FollowUpTask.completed_at)).where(
            FollowUpTask.customer_id == customer_id, FollowUpTask.status == TaskStatus.COMPLETED
        )
    )
