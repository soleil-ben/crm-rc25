"""Staff integration-health routes.

Three read paths and two actions, all on the **staff** router, all behind the permission
matrix, and all outside ``/api/v1/public``. Nothing here is reachable without a session,
and nothing here is added to the public tracking vocabulary: Phase 4A does not put
``connected_api`` on the public page, does not add ``last_carrier_update`` or
``last_successful_sync``, and does not change the public privacy contract in any way.

**No route here contacts a provider.** ``/health`` reads rows. ``/jobs/{id}/retry`` queues
work for a worker that has no adapter to run it against. There is deliberately no
``/connect`` and no ``/verify`` endpoint, because either would be a button that cannot
perform a real operation -- and CRM.md section 9 is explicit that receiving a tracking
number or a URL does not authorize or enable API tracking.

Permissions split along the line CRM.md section 11 draws. ``integration:read`` sees health,
which is counts and states and carries no secret; ``integration:manage`` is admin only and
gates anything that changes the integration.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, select

from app.api.deps import CurrentUser, DbSession, client_ip, require
from app.core.db import commit_with_retry
from app.core.permissions import Permission
from app.models import IntegrationJob, User
from app.schemas.integration import (
    DisableConnectionIn,
    IntegrationHealthOut,
    IntegrationJobListOut,
    IntegrationJobOut,
)
from app.services import integration_health_service

router = APIRouter(tags=["integrations"])


@router.get("/integrations/health", response_model=IntegrationHealthOut)
def integration_health(
    db: DbSession,
    _guard: Annotated[User, Depends(require(Permission.INTEGRATION_READ))],
) -> IntegrationHealthOut:
    """Integration health.

    Today this reports ``any_provider_configured: false``, one connection entry in state
    ``not_configured``, zero jobs, no worker heartbeat unless one has run, and
    ``stale_assignment_count: null`` -- because no freshness rule exists and ``0`` would
    assert that everything is fresh.
    """
    health = integration_health_service.build_health(db)
    return IntegrationHealthOut.model_validate(health)


@router.get("/integrations/jobs", response_model=IntegrationJobListOut)
def integration_jobs(
    db: DbSession,
    _guard: Annotated[User, Depends(require(Permission.INTEGRATION_READ))],
    review_only: bool = Query(default=False),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> IntegrationJobListOut:
    """The job queue, and with ``review_only`` the failed-job review queue.

    Queue state is in the database, so this answers the same way after a process restart
    as before one.
    """
    conditions = []
    if review_only:
        conditions.append(IntegrationJob.requires_review.is_(True))

    total = db.scalar(select(func.count()).select_from(IntegrationJob).where(*conditions)) or 0
    rows = db.scalars(
        select(IntegrationJob)
        .where(*conditions)
        .order_by(IntegrationJob.id.desc())
        .limit(limit)
        .offset(offset)
    ).all()
    return IntegrationJobListOut(
        items=[IntegrationJobOut.model_validate(row) for row in rows], total=total
    )


@router.post("/integrations/jobs/{job_id}/retry", response_model=IntegrationJobOut)
def retry_integration_job(
    job_id: int,
    db: DbSession,
    request: Request,
    user: CurrentUser,
    _guard: Annotated[User, Depends(require(Permission.INTEGRATION_MANAGE))],
) -> IntegrationJobOut:
    """Retry a failed job. Audited, and the failure history is preserved.

    The attempt count keeps counting and ``manual_retry_count`` records that a person
    intervened, so a second failure is visibly a second failure rather than looking like
    the first.
    """
    job = integration_health_service.retry_job(
        db, job_id=job_id, actor=user, ip_address=client_ip(request)
    )
    commit_with_retry(db)
    db.refresh(job)
    return IntegrationJobOut.model_validate(job)


@router.post("/integrations/connections/{connection_id}/disable", response_model=dict)
def disable_connection(
    connection_id: int,
    payload: DisableConnectionIn,
    db: DbSession,
    request: Request,
    user: CurrentUser,
    _guard: Annotated[User, Depends(require(Permission.INTEGRATION_MANAGE))],
) -> dict:
    """Switch a provider connection off.

    Safe by construction: it stops the integration and touches no shipment data. No event
    is voided, no status recomputed, no tracking assignment retired -- turning a provider
    off must not silently rewrite what customers have already been told.

    With no connections configured this answers 404, which is the truthful response. The
    Settings panel renders no Disable button in that state rather than offering one that
    cannot do anything.
    """
    connection = integration_health_service.disable_connection(
        db,
        connection_id=connection_id,
        reason=payload.reason,
        actor=user,
        ip_address=client_ip(request),
    )
    commit_with_retry(db)
    return {"connection_id": connection.id, "state": connection.state, "is_enabled": False}
