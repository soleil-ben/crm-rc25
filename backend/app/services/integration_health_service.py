"""Integration health, reported honestly.

CRM.md section 9 asks for integration health: last success, last error, pending and failed
jobs, stale shipments, and a permission-controlled retry action. ``Design.md`` section 13
asks for provider cards showing source, version, connection state, last successful sync,
last error, and pending/failed jobs.

**Everything this returns today is either a real count or the word "not configured".**
There is no provider account, the adapter registry is empty, and no request has ever been
made to a carrier or to ShipStation by this application. So:

* the connection state is ``not_configured``, because that is the only state a
  registry with nothing in it can truthfully report;
* ``provider_api_version`` is ``None`` rather than a plausible-looking string;
* ``last_success_at`` is ``None`` rather than a recent timestamp;
* the worker heartbeat is ``None`` unless a worker actually wrote one;
* **stale-assignment count is ``None``, not zero.** No freshness rule exists, because a
  freshness rule needs a provider's documented update cadence, and there is no provider.
  Reporting ``0 stale`` would be a claim that everything is fresh, which is a stronger and
  falser statement than "we cannot tell".

The distinction in that last point is the one that matters most in this file. A health
panel exists to be believed, so a number it cannot support has to be absent rather than
reassuring. ``Design.md`` section 5 makes the same point about KPI comparisons: an
unavailable figure is omitted, never fabricated.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.enums import (
    InboxProcessingState,
    IntegrationConnectionState,
    IntegrationJobStatus,
)
from app.core.time_utils import utcnow
from app.integrations.registry import AdapterRegistry
from app.integrations.registry import registry as default_registry
from app.models import (
    IntegrationConnection,
    IntegrationJob,
    IntegrationWebhookInboxItem,
    IntegrationWorkerHeartbeat,
    User,
)
from app.services import audit_service, integration_job_service
from app.services.errors import ConflictError, NotFoundError

Clock = Callable[[], datetime]


@dataclass(frozen=True)
class ConnectionHealth:
    """One provider connection, or the absence of any."""

    provider_key: str | None
    #: ``not_configured`` until an account is verified. Never guessed.
    state: str
    #: Only when genuinely known. ``None`` is the honest answer for an unverified account.
    provider_api_version: str | None = None
    display_label: str | None = None
    connection_id: int | None = None
    is_enabled: bool = False
    last_success_at: datetime | None = None
    last_success_operation: str | None = None
    last_error_at: datetime | None = None
    #: A ``ProviderErrorKind`` value, never a provider status code.
    last_error_code: str | None = None
    #: Redacted. Never a payload, credential, URL, or tracking reference.
    last_error_summary: str | None = None


@dataclass(frozen=True)
class WorkerHealth:
    """A worker heartbeat, present only because a worker wrote one."""

    worker_name: str
    mode: str
    last_seen_at: datetime
    seconds_since_last_seen: int
    stopped_at: datetime | None
    jobs_claimed: int
    jobs_succeeded: int
    jobs_failed: int


@dataclass(frozen=True)
class IntegrationHealth:
    """The whole picture, with every unavailable value explicitly absent."""

    #: True only when an adapter is registered. False everywhere today.
    any_provider_configured: bool
    connections: list[ConnectionHealth] = field(default_factory=list)

    jobs_pending: int = 0
    jobs_running: int = 0
    jobs_failed: int = 0
    jobs_failed_terminal: int = 0
    jobs_requiring_review: int = 0
    #: ``None`` when nothing is waiting. The number that reveals a stopped worker.
    oldest_pending_job_age_seconds: int | None = None

    inbox_pending: int = 0
    inbox_awaiting_verification: int = 0
    inbox_rejected: int = 0
    inbox_failed_terminal: int = 0

    #: ``None`` because no freshness rule exists, **not** zero. See the module docstring.
    stale_assignment_count: int | None = None
    stale_rule_description: str = (
        "No freshness rule exists. A freshness threshold needs a provider's documented "
        "update cadence, and no provider is configured."
    )

    #: ``None`` unless a worker has genuinely reported in.
    worker: WorkerHealth | None = None

    #: What a reader should understand from all of the above, in one sentence.
    summary: str = ""


def _now(clock: Clock | None) -> datetime:
    return clock() if clock else utcnow()


def build_health(
    db: Session,
    *,
    registry: AdapterRegistry | None = None,
    clock: Clock | None = None,
) -> IntegrationHealth:
    """Assemble the health picture from what is actually recorded."""
    adapters = registry or default_registry
    now = _now(clock)

    job_counts = integration_job_service.counts_by_status(db)
    inbox_counts = _inbox_counts(db)

    review_count = (
        db.scalar(
            select(func.count())
            .select_from(IntegrationJob)
            .where(IntegrationJob.requires_review.is_(True))
        )
        or 0
    )

    connections = _connections(db, adapters=adapters)

    heartbeat_row = db.scalar(
        select(IntegrationWorkerHeartbeat)
        .order_by(IntegrationWorkerHeartbeat.last_seen_at.desc())
        .limit(1)
    )
    worker = None
    if heartbeat_row is not None:
        worker = WorkerHealth(
            worker_name=heartbeat_row.worker_name,
            mode=heartbeat_row.mode,
            last_seen_at=heartbeat_row.last_seen_at,
            seconds_since_last_seen=max(0, int((now - heartbeat_row.last_seen_at).total_seconds())),
            stopped_at=heartbeat_row.stopped_at,
            jobs_claimed=heartbeat_row.jobs_claimed,
            jobs_succeeded=heartbeat_row.jobs_succeeded,
            jobs_failed=heartbeat_row.jobs_failed,
        )

    configured = adapters.is_empty() is False

    return IntegrationHealth(
        any_provider_configured=configured,
        connections=connections,
        jobs_pending=job_counts.get(IntegrationJobStatus.PENDING, 0),
        jobs_running=job_counts.get(IntegrationJobStatus.RUNNING, 0),
        jobs_failed=job_counts.get(IntegrationJobStatus.FAILED, 0),
        jobs_failed_terminal=job_counts.get(IntegrationJobStatus.FAILED_TERMINAL, 0),
        jobs_requiring_review=review_count,
        oldest_pending_job_age_seconds=integration_job_service.oldest_pending_age_seconds(
            db, clock=clock
        ),
        inbox_pending=inbox_counts.get(InboxProcessingState.PENDING, 0),
        inbox_awaiting_verification=_awaiting_verification(db),
        inbox_rejected=inbox_counts.get(InboxProcessingState.REJECTED, 0),
        inbox_failed_terminal=inbox_counts.get(InboxProcessingState.FAILED_TERMINAL, 0),
        # Deliberately None. See the module docstring.
        stale_assignment_count=None,
        worker=worker,
        summary=_summary(configured=configured, connections=connections),
    )


def _summary(*, configured: bool, connections: list[ConnectionHealth]) -> str:
    """One sentence a staff member can act on, and no more than is true."""
    states = {connection.state for connection in connections}
    if not configured or states == {IntegrationConnectionState.NOT_CONFIGURED}:
        # One sentence, whether the absence is expressed as no rows at all or as the
        # single ``not_configured`` placeholder. The third clause is the part staff
        # actually need: nothing has stopped working, because nothing was ever automatic.
        return (
            "No provider account is connected. Automatic tracking is unavailable. "
            "Manual milestones and external carrier links continue to work."
        )
    if IntegrationConnectionState.ERROR in states:
        return "A provider connection is reporting errors."
    if IntegrationConnectionState.DISABLED in states:
        return "A provider connection is disabled."
    if IntegrationConnectionState.VERIFICATION_REQUIRED in states:
        return "A provider connection is configured but has not been verified."
    return "A provider connection is active."


def _connections(db: Session, *, adapters: AdapterRegistry) -> list[ConnectionHealth]:
    """One entry per connection row, or a single honest placeholder when there are none.

    The placeholder is not a fake connection card. It carries no provider key, no version,
    and no timestamps -- only the state ``not_configured``, which is what the interface
    renders as "No provider account is connected".
    """
    rows = list(db.scalars(select(IntegrationConnection).order_by(IntegrationConnection.id)).all())
    if not rows:
        return [
            ConnectionHealth(
                provider_key=None,
                state=IntegrationConnectionState.NOT_CONFIGURED,
                provider_api_version=None,
            )
        ]

    out: list[ConnectionHealth] = []
    for row in rows:
        state = row.state
        if not adapters.has(row.provider_key):
            # A row exists but nothing can serve it. Reporting anything other than
            # "not configured" would claim a capability this process does not have.
            state = IntegrationConnectionState.NOT_CONFIGURED
        elif not row.is_enabled:
            state = IntegrationConnectionState.DISABLED
        out.append(
            ConnectionHealth(
                provider_key=row.provider_key,
                state=state,
                # Only reported when the row genuinely records one.
                provider_api_version=row.provider_api_version,
                display_label=row.display_label,
                connection_id=row.id,
                is_enabled=row.is_enabled,
                last_success_at=row.last_success_at,
                last_success_operation=row.last_success_operation,
                last_error_at=row.last_error_at,
                last_error_code=row.last_error_code,
                last_error_summary=row.last_error_summary,
            )
        )
    return out


def _inbox_counts(db: Session) -> dict[str, int]:
    rows = db.execute(
        select(IntegrationWebhookInboxItem.processing_state, func.count()).group_by(
            IntegrationWebhookInboxItem.processing_state
        )
    ).all()
    return dict(rows)


def _awaiting_verification(db: Session) -> int:
    from app.services import integration_inbox_service

    return integration_inbox_service.awaiting_verification_count(db)


# --- Permission-controlled actions ------------------------------------------


def retry_job(
    db: Session,
    *,
    job_id: int,
    actor: User | None = None,
    ip_address: str | None = None,
    clock: Clock | None = None,
) -> IntegrationJob:
    """Operator retry of a failed job. Audited, and never erases the failure history."""
    job = db.get(IntegrationJob, job_id)
    if job is None:
        raise NotFoundError("That integration job does not exist.")
    return integration_job_service.retry_manually(
        db, job, actor=actor, ip_address=ip_address, clock=clock
    )


def disable_connection(
    db: Session,
    *,
    connection_id: int,
    reason: str,
    actor: User | None = None,
    ip_address: str | None = None,
    clock: Clock | None = None,
) -> IntegrationConnection:
    """Switch a provider connection off. Safe, reversible, and audited.

    "Safe" here means it stops the integration without touching shipment data: no event is
    voided, no status is recomputed, no tracking assignment is retired. Turning a provider
    off is an operational decision, and it must not silently rewrite what customers have
    already been told.

    With no connections configured this raises a 404, which is the truthful answer -- there
    is nothing to disable. The interface renders no Disable button in that state rather
    than offering one that cannot do anything (CRM.md section 9, Design.md section 13).
    """
    connection = db.get(IntegrationConnection, connection_id)
    if connection is None:
        raise NotFoundError("That provider connection does not exist.")
    if not connection.is_enabled:
        raise ConflictError("That provider connection is already disabled.")

    connection.is_enabled = False
    connection.state = IntegrationConnectionState.DISABLED
    connection.disabled_at = _now(clock)
    connection.disabled_reason = reason[:255]
    connection.disabled_by_user_id = actor.id if actor else None
    db.flush()

    audit_service.record_audit(
        db,
        action="integration.connection_disable",
        entity_type="integration_connection",
        entity_id=connection.id,
        summary=f"Disabled the {connection.provider_key} provider connection",
        actor=actor,
        ip_address=ip_address,
        detail={"provider_key": connection.provider_key, "reason": reason[:255]},
    )
    return connection
