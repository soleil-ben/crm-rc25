"""Follow-up task routes."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import select

from app.api import presenters
from app.api.deps import CurrentUser, DbSession, client_ip, require
from app.core.db import commit_with_retry
from app.core.permissions import Permission
from app.models import FollowUpTask, User
from app.schemas.common import Page
from app.schemas.engagement import (
    TaskCompleteRequest,
    TaskCompleteResponse,
    TaskCreate,
    TaskOut,
    TaskUpdate,
)
from app.services import customer_service, task_service
from app.services.errors import NotFoundError

router = APIRouter(prefix="/tasks", tags=["follow-ups"])


def _load_task(db, task_id: int) -> FollowUpTask:
    task = db.get(FollowUpTask, task_id)
    if task is None:
        raise NotFoundError("Follow-up task not found.")
    return task


@router.get("", response_model=Page[TaskOut])
def list_tasks(
    db: DbSession,
    _user: Annotated[User, Depends(require(Permission.TASK_READ))],
    assignee_user_id: int | None = None,
    customer_id: int | None = None,
    status: list[str] | None = Query(default=None),
    only_open: bool = False,
    only_overdue: bool = False,
    due_before: datetime | None = None,
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> Page[TaskOut]:
    conditions = task_service.task_query_conditions(
        assignee_user_id=assignee_user_id,
        customer_id=customer_id,
        status=status,
        only_open=only_open,
        only_overdue=only_overdue,
        due_before=due_before,
    )
    total = task_service.count_tasks(db, conditions)
    rows = list(
        db.scalars(
            select(FollowUpTask)
            .where(*conditions)
            # Overdue and soonest-due first; undated open tasks last (Design.md section 11).
            .order_by(
                FollowUpTask.due_at.is_(None).asc(),
                FollowUpTask.due_at.asc(),
                FollowUpTask.id.asc(),
            )
            .limit(limit)
            .offset(offset)
        ).all()
    )
    return Page[TaskOut](
        items=presenters.task_list(db, rows), total=total, limit=limit, offset=offset
    )


@router.post("", response_model=TaskOut, status_code=201)
def create_task(
    payload: TaskCreate,
    request: Request,
    db: DbSession,
    user: Annotated[User, Depends(require(Permission.TASK_WRITE))],
) -> TaskOut:
    customer = customer_service.get_customer(db, payload.customer_id)
    task = task_service.create_task(
        db,
        customer=customer,
        subject=payload.subject,
        due_at=payload.due_at,
        assignee_user_id=payload.assignee_user_id or user.id,
        purpose=payload.purpose.value,
        priority=payload.priority.value,
        status=payload.status.value,
        detail=payload.detail,
        shipment_id=payload.shipment_id,
        actor=user,
        ip_address=client_ip(request),
    )
    commit_with_retry(db)
    return presenters.task_list(db, [task])[0]


@router.patch("/{task_id}", response_model=TaskOut)
def update_task(
    task_id: int,
    payload: TaskUpdate,
    request: Request,
    db: DbSession,
    user: Annotated[User, Depends(require(Permission.TASK_WRITE))],
) -> TaskOut:
    task = _load_task(db, task_id)
    data = payload.model_dump(exclude_unset=True)
    for key, value in list(data.items()):
        if value is not None and hasattr(value, "value"):
            data[key] = value.value
    task_service.update_task(db, task, data, actor=user, ip_address=client_ip(request))
    commit_with_retry(db)
    return presenters.task_list(db, [task])[0]


@router.post("/{task_id}/complete", response_model=TaskCompleteResponse)
def complete_task(
    task_id: int,
    payload: TaskCompleteRequest,
    request: Request,
    db: DbSession,
    user: Annotated[User, Depends(require(Permission.TASK_WRITE))],
) -> TaskCompleteResponse:
    """Completing a task closes only this task (CRM.md section 4)."""
    task = _load_task(db, task_id)
    next_task_payload = payload.next_task.model_dump() if payload.next_task else None
    if next_task_payload and next_task_payload.get("purpose") is not None:
        purpose = next_task_payload["purpose"]
        next_task_payload["purpose"] = purpose.value if hasattr(purpose, "value") else purpose
    if next_task_payload and next_task_payload.get("priority") is not None:
        priority = next_task_payload["priority"]
        next_task_payload["priority"] = priority.value if hasattr(priority, "value") else priority

    completed, created = task_service.complete_task(
        db,
        task,
        outcome=payload.outcome,
        completed_at=payload.completed_at,
        log_interaction=payload.log_interaction,
        channel=payload.channel.value,
        actor=user,
        ip_address=client_ip(request),
        next_task=next_task_payload,
    )
    commit_with_retry(db)
    rendered = presenters.task_list(db, [completed] + ([created] if created else []))
    return TaskCompleteResponse(
        task=rendered[0], next_task=rendered[1] if len(rendered) > 1 else None
    )


@router.get("/mine", response_model=Page[TaskOut])
def my_tasks(
    db: DbSession,
    user: CurrentUser,
    _guard: Annotated[User, Depends(require(Permission.TASK_READ))],
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> Page[TaskOut]:
    conditions = task_service.task_query_conditions(assignee_user_id=user.id, only_open=True)
    total = task_service.count_tasks(db, conditions)
    rows = list(
        db.scalars(
            select(FollowUpTask)
            .where(*conditions)
            .order_by(FollowUpTask.due_at.is_(None).asc(), FollowUpTask.due_at.asc())
            .limit(limit)
            .offset(offset)
        ).all()
    )
    return Page[TaskOut](
        items=presenters.task_list(db, rows), total=total, limit=limit, offset=offset
    )
