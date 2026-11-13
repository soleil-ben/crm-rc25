"""Follow-up task rules (CRM.md sections 4 and 5).

* Overdue is derived from an unfinished task's due time; it is never stored.
* Completing one task never touches another.
* Automation rules create internal tasks only, deduplicated by a stable key, and each
  rule can be disabled in settings.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.enums import (
    OPEN_TASK_STATUSES,
    ContactChannel,
    InteractionDirection,
    TaskPriority,
    TaskPurpose,
    TaskStatus,
)
from app.core.time_utils import utcnow
from app.models import Customer, FollowUpTask, Interaction, OrganizationSettings, User
from app.services import audit_service
from app.services.errors import ConflictError, ValidationError

TERMINAL_STATUSES = {TaskStatus.COMPLETED, TaskStatus.CANCELLED}


def is_overdue(task: FollowUpTask, now: datetime | None = None) -> bool:
    if task.status in TERMINAL_STATUSES or task.due_at is None:
        return False
    return task.due_at < (now or utcnow())


def create_task(
    db: Session,
    *,
    customer: Customer,
    subject: str,
    due_at: datetime | None,
    assignee_user_id: int | None,
    purpose: str = TaskPurpose.GENERAL,
    priority: str = TaskPriority.NORMAL,
    status: str = TaskStatus.SCHEDULED,
    detail: str | None = None,
    shipment_id: int | None = None,
    source_rule: str | None = None,
    dedupe_key: str | None = None,
    actor: User | None = None,
    ip_address: str | None = None,
) -> FollowUpTask:
    if status in (TaskStatus.SCHEDULED, TaskStatus.IN_PROGRESS) and due_at is None:
        raise ValidationError("A scheduled task needs a due date and time.", field="due_at")
    if status in TERMINAL_STATUSES:
        raise ValidationError(
            "Create the task in an open status; complete or cancel it afterwards.", field="status"
        )

    task = FollowUpTask(
        customer_id=customer.id,
        shipment_id=shipment_id,
        subject=subject.strip(),
        detail=detail,
        purpose=purpose,
        priority=priority,
        status=status,
        due_at=due_at,
        assignee_user_id=assignee_user_id,
        created_by_user_id=actor.id if actor else None,
        source_rule=source_rule,
        dedupe_key=dedupe_key,
    )
    db.add(task)
    db.flush()
    audit_service.record_audit(
        db,
        action="task.create",
        entity_type="follow_up_task",
        entity_id=task.id,
        summary=f"Created follow-up '{task.subject}' for {customer.public_id}",
        actor=actor,
        ip_address=ip_address,
        detail={"purpose": purpose, "priority": priority},
    )
    return task


def update_task(
    db: Session,
    task: FollowUpTask,
    data: dict,
    *,
    actor: User | None = None,
    ip_address: str | None = None,
) -> FollowUpTask:
    if task.status == TaskStatus.COMPLETED and data.get("status") not in (
        None,
        TaskStatus.COMPLETED,
    ):
        raise ConflictError("A completed task cannot be reopened; create a follow-up task instead.")

    for field_name in (
        "subject",
        "detail",
        "purpose",
        "priority",
        "status",
        "due_at",
        "assignee_user_id",
        "shipment_id",
    ):
        if field_name in data:
            setattr(task, field_name, data[field_name])

    if task.status in (TaskStatus.SCHEDULED, TaskStatus.IN_PROGRESS) and task.due_at is None:
        raise ValidationError("A scheduled task needs a due date and time.", field="due_at")
    if task.status == TaskStatus.CANCELLED:
        task.cancelled_reason = data.get("cancelled_reason") or task.cancelled_reason

    audit_service.record_audit(
        db,
        action="task.update",
        entity_type="follow_up_task",
        entity_id=task.id,
        summary=f"Updated follow-up task {task.id}",
        actor=actor,
        ip_address=ip_address,
        detail={"status": task.status},
    )
    return task


def complete_task(
    db: Session,
    task: FollowUpTask,
    *,
    outcome: str,
    completed_at: datetime | None = None,
    log_interaction: bool = True,
    channel: str = ContactChannel.PHONE,
    actor: User | None = None,
    ip_address: str | None = None,
    next_task: dict | None = None,
) -> tuple[FollowUpTask, FollowUpTask | None]:
    """Complete exactly this task and optionally schedule one follow-on task."""
    if task.status == TaskStatus.COMPLETED:
        raise ConflictError("This task is already completed.")

    task.status = TaskStatus.COMPLETED
    task.completed_at = completed_at or utcnow()
    task.completed_by_user_id = actor.id if actor else None
    task.outcome = outcome.strip()

    if log_interaction:
        # Last Follow-up Date is derived from completed follow-up interactions.
        db.add(
            Interaction(
                customer_id=task.customer_id,
                shipment_id=task.shipment_id,
                task_id=task.id,
                occurred_at=task.completed_at,
                channel=channel,
                direction=InteractionDirection.OUTBOUND,
                subject=f"Follow-up completed: {task.subject}",
                body=task.outcome,
                outcome=task.outcome[:200],
                is_follow_up_completion=True,
                author_user_id=actor.id if actor else None,
            )
        )

    created: FollowUpTask | None = None
    if next_task:
        customer = db.get(Customer, task.customer_id)
        created = create_task(
            db,
            customer=customer,
            subject=next_task["subject"],
            due_at=next_task.get("due_at"),
            assignee_user_id=next_task.get("assignee_user_id", task.assignee_user_id),
            purpose=next_task.get("purpose", task.purpose),
            priority=next_task.get("priority", TaskPriority.NORMAL),
            detail=next_task.get("detail"),
            shipment_id=task.shipment_id,
            actor=actor,
        )

    audit_service.record_audit(
        db,
        action="task.complete",
        entity_type="follow_up_task",
        entity_id=task.id,
        summary=f"Completed follow-up task {task.id}",
        actor=actor,
        ip_address=ip_address,
    )
    return task, created


def ensure_rule_task(
    db: Session,
    *,
    customer: Customer,
    rule: str,
    subject: str,
    due_at: datetime,
    purpose: str,
    priority: str = TaskPriority.NORMAL,
    shipment_id: int | None = None,
    assignee_user_id: int | None = None,
    detail: str | None = None,
) -> FollowUpTask | None:
    """Create a retention-rule task unless an identical one already exists.

    Returns ``None`` when the task already exists, so a rule run is idempotent
    (CRM.md section 5, AC-9 spirit).
    """
    dedupe_key = f"{rule}:{customer.id}:{shipment_id or 'none'}"
    existing = db.scalar(select(FollowUpTask).where(FollowUpTask.dedupe_key == dedupe_key))
    if existing is not None:
        return None
    return create_task(
        db,
        customer=customer,
        subject=subject,
        due_at=due_at,
        assignee_user_id=assignee_user_id or customer.owner_user_id,
        purpose=purpose,
        priority=priority,
        detail=detail,
        shipment_id=shipment_id,
        source_rule=rule,
        dedupe_key=dedupe_key,
    )


def run_retention_rules(db: Session, settings_row: OrganizationSettings) -> dict[str, int]:
    """Internal task automation only. This never sends a customer message."""
    from app.services.activity_service import LifecycleThresholds, customers_with_lifecycle

    created = {"at_risk_check_in": 0}
    if settings_row.rule_at_risk_task_enabled:
        thresholds = LifecycleThresholds.from_settings(settings_row)
        at_risk_ids = customers_with_lifecycle(db, thresholds, ["at_risk"])
        for customer_id in at_risk_ids:
            customer = db.get(Customer, customer_id)
            if customer is None or customer.do_not_contact:
                continue
            task = ensure_rule_task(
                db,
                customer=customer,
                rule="at_risk_check_in",
                subject=f"Check in with {customer.full_name}",
                due_at=utcnow() + timedelta(days=2),
                purpose=TaskPurpose.AT_RISK_CHECK_IN,
                detail="Customer moved to At risk. Internal check-in only; no promotional message.",
            )
            if task is not None:
                created["at_risk_check_in"] += 1
    return created


def task_query_conditions(
    *,
    assignee_user_id: int | None = None,
    customer_id: int | None = None,
    status: list[str] | None = None,
    only_open: bool = False,
    only_overdue: bool = False,
    due_before: datetime | None = None,
) -> list:
    conditions = []
    if assignee_user_id is not None:
        conditions.append(FollowUpTask.assignee_user_id == assignee_user_id)
    if customer_id is not None:
        conditions.append(FollowUpTask.customer_id == customer_id)
    if status:
        conditions.append(FollowUpTask.status.in_(status))
    if only_open:
        conditions.append(FollowUpTask.status.in_(list(OPEN_TASK_STATUSES)))
    if only_overdue:
        conditions.extend(
            [
                FollowUpTask.status.in_(list(OPEN_TASK_STATUSES)),
                FollowUpTask.due_at.is_not(None),
                FollowUpTask.due_at < utcnow(),
            ]
        )
    if due_before is not None:
        conditions.append(or_(FollowUpTask.due_at.is_(None), FollowUpTask.due_at <= due_before))
    return conditions


def count_tasks(db: Session, conditions: list) -> int:
    return int(db.scalar(select(func.count(FollowUpTask.id)).where(*conditions)) or 0)
