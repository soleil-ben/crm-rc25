"""The durable integration job queue.

Enqueue, claim, complete, fail, retry, and reclaim. Everything a worker does to a job
goes through here, so the concurrency rules exist in one place rather than being
re-derived at each call site.

**Three guarantees, and where each one actually lives.**

*At most one active job per deduplication claim* is a **database** guarantee.
``integration_jobs.active_dedupe_key`` is unique and nullable: it carries the claim while
a job is pending or running, and is set to NULL the moment the job stops. Two concurrent
enqueues therefore collide at flush, not in an application check that one of them might
run first; and a completed job stops constraining, so a later legitimate reconciliation is
not blocked by history. CRM.md section 9 requires exactly this -- concurrent page visits
must cause at most one pending refresh per assignment.

*Claiming is atomic* without ``SELECT ... FOR UPDATE``, which SQLite does not have.
``claim_next`` issues a conditional ``UPDATE`` whose ``WHERE`` clause is the guard: the row
must still be pending, still be due, and still be unleased or expired. The database
evaluates that predicate while holding the write lock, so exactly one worker sees
``rowcount == 1``. A loser reads zero and moves on. This is the same reasoning as
DEC-0031: uniqueness and conditional updates are the honest primitives here, and a lock
that does not exist is worse than no lock because it looks like protection.

*A crash does not strand work.* A lease expires. A worker that dies holding a running row
loses the lease by the passage of time, and ``reclaim_expired`` returns the row to
pending. A **live** lease cannot be stolen: the same ``WHERE`` clause refuses a row whose
lease is still in the future.

**SQLite, honestly.** This is single-writer. Two worker processes against one database
file will serialize on the write lock and the conditional update still makes the claim
correct, but this project has demonstrated the claim under two *sessions on separate
connections*, not under two operating-system processes, and it does not claim more than it
has shown (``docs/OPERATIONS.md``). Run one worker.
"""

from __future__ import annotations

import secrets
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.enums import (
    ACTIVE_JOB_STATUSES,
    IntegrationJobStatus,
    IntegrationJobType,
    ProviderErrorKind,
)
from app.core.time_utils import utcnow
from app.integrations.redaction import safe_summary
from app.models import IntegrationJob, User
from app.models.integration import UNASSIGNED_CONNECTION
from app.services import audit_service

#: Injected so tests are deterministic and a backoff can be observed rather than waited
#: out. Production passes nothing and gets the real clock.
Clock = Callable[[], datetime]
#: Injected jitter source, returning a float in [0, 1).
Jitter = Callable[[], float]


def _now(clock: Clock | None) -> datetime:
    return clock() if clock else utcnow()


@dataclass(frozen=True)
class ClaimedJob:
    """A job this worker holds, and the token proving it."""

    job: IntegrationJob
    lease_token: str
    lease_expires_at: datetime


def refresh_dedupe_key(tracking_assignment_id: int) -> str:
    """The claim a refresh takes out on one tracking assignment.

    Namespaced by job type, so a refresh and a reconciliation for the same assignment are
    not accidentally mutually exclusive: they are different work with different reasons to
    exist, and CRM.md section 9 constrains only the refresh.
    """
    return f"{IntegrationJobType.REFRESH_TRACKING_ASSIGNMENT}:assignment:{tracking_assignment_id}"


def inbox_dedupe_key(inbox_item_id: int) -> str:
    """The claim processing takes out on one inbox item."""
    return f"{IntegrationJobType.PROCESS_WEBHOOK_INBOX_ITEM}:inbox:{inbox_item_id}"


def verification_dedupe_key(inbox_item_id: int) -> str:
    return f"{IntegrationJobType.VERIFY_NOTIFICATION}:inbox:{inbox_item_id}"


# --- Enqueue ---------------------------------------------------------------


def enqueue(
    db: Session,
    *,
    job_type: str,
    provider_key: str,
    connection_key: str = UNASSIGNED_CONNECTION,
    connection_id: int | None = None,
    tracking_assignment_id: int | None = None,
    inbox_item_id: int | None = None,
    shipment_id: int | None = None,
    dedupe_key: str | None = None,
    available_at: datetime | None = None,
    priority: int = 100,
    max_attempts: int | None = None,
    clock: Clock | None = None,
) -> IntegrationJob | None:
    """Add a job, unless an identical active claim already exists.

    Returns the new job, or ``None`` when an equivalent job is already pending or
    running. ``None`` is a **success**: it means the work is already queued, which is
    precisely what the deduplication is for. A caller that treats it as a failure has
    misread the contract.

    The check is done twice on purpose. The pre-check keeps the common case cheap and
    avoids burning primary keys; the ``IntegrityError`` catch is what makes it correct,
    because between the pre-check and the flush another session may have inserted. Only
    the second one is a guarantee.

    **An ``IntegrityError`` is not assumed to be the deduplication constraint.** SQLite
    enforces foreign keys on every connection here, so a job naming a tracking assignment
    or an inbox item that does not exist also raises one -- and swallowing that as "already
    queued" would silently drop real work while reporting success. After the rollback the
    table is re-read: a winner means it was a duplicate, no winner means the insert failed
    for some other reason and the error propagates.
    """
    if job_type not in set(IntegrationJobType):
        raise ValueError(f"Unknown integration job type {job_type!r}")

    now = _now(clock)

    if dedupe_key:
        existing = db.scalar(
            select(IntegrationJob).where(
                IntegrationJob.active_dedupe_key == dedupe_key,
                IntegrationJob.status.in_(ACTIVE_JOB_STATUSES),
            )
        )
        if existing is not None:
            return None

    job = IntegrationJob(
        job_type=job_type,
        provider_key=provider_key,
        connection_key=connection_key,
        connection_id=connection_id,
        tracking_assignment_id=tracking_assignment_id,
        inbox_item_id=inbox_item_id,
        shipment_id=shipment_id,
        status=IntegrationJobStatus.PENDING,
        available_at=available_at or now,
        attempt_count=0,
        max_attempts=max_attempts or settings.integration_job_max_attempts,
        priority=priority,
        dedupe_key=dedupe_key,
        active_dedupe_key=dedupe_key,
    )
    db.add(job)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        if not dedupe_key:
            # Nothing to deduplicate on, so this cannot have been a duplicate.
            raise
        winner = db.scalar(
            select(IntegrationJob).where(
                IntegrationJob.active_dedupe_key == dedupe_key,
                IntegrationJob.status.in_(ACTIVE_JOB_STATUSES),
            )
        )
        if winner is None:
            # Not the deduplication constraint -- a bad foreign key, most likely. Losing
            # the job quietly would be worse than failing loudly.
            raise
        # Another session won the race. The unique constraint on ``active_dedupe_key``
        # is what turns "two workers both thought they should enqueue" into one job.
        return None
    return job


# --- Claim -----------------------------------------------------------------


def claim_next(
    db: Session,
    *,
    worker_name: str,
    provider_keys: list[str] | None = None,
    clock: Clock | None = None,
    lease_seconds: int | None = None,
) -> ClaimedJob | None:
    """Atomically claim one due job, or return ``None``.

    The selection query is a hint; the ``UPDATE`` is the decision. Between reading a
    candidate id and updating it, another worker may have taken it -- so the update
    repeats every condition, and a ``rowcount`` of zero means "somebody else got it",
    which is an ordinary outcome rather than an error.

    Two conditions are worth reading closely:

    * ``status == PENDING`` -- a running job is not claimable, whatever its lease says.
    * ``lease_expires_at IS NULL OR lease_expires_at <= now`` -- a **live** lease is never
      stolen. Reclaiming an expired one is the recovery path, and it is the database that
      decides whether the lease has expired, not the worker that wants the job.
    """
    now = _now(clock)
    seconds = lease_seconds or settings.integration_job_lease_seconds

    for _attempt in range(10):
        query = (
            select(IntegrationJob.id)
            .where(
                IntegrationJob.status == IntegrationJobStatus.PENDING,
                IntegrationJob.available_at <= now,
            )
            .order_by(
                IntegrationJob.priority.asc(),
                IntegrationJob.available_at.asc(),
                IntegrationJob.id.asc(),
            )
            .limit(1)
        )
        if provider_keys:
            query = query.where(IntegrationJob.provider_key.in_(provider_keys))

        candidate_id = db.scalar(query)
        if candidate_id is None:
            return None

        token = secrets.token_hex(16)
        expires_at = now + timedelta(seconds=seconds)

        result = db.execute(
            update(IntegrationJob)
            .where(
                IntegrationJob.id == candidate_id,
                IntegrationJob.status == IntegrationJobStatus.PENDING,
                IntegrationJob.available_at <= now,
                (IntegrationJob.lease_expires_at.is_(None))
                | (IntegrationJob.lease_expires_at <= now),
            )
            .values(
                status=IntegrationJobStatus.RUNNING,
                lease_owner=worker_name,
                lease_token=token,
                lease_expires_at=expires_at,
                attempt_count=IntegrationJob.attempt_count + 1,
                last_attempt_at=now,
                updated_at=now,
            )
        )
        db.flush()

        if result.rowcount == 1:
            job = db.get(IntegrationJob, candidate_id)
            db.refresh(job)
            return ClaimedJob(job=job, lease_token=token, lease_expires_at=expires_at)

        # Lost the race. Try the next candidate rather than failing the pass.

    return None


def reclaim_expired(
    db: Session, *, clock: Clock | None = None, limit: int = 100
) -> list[IntegrationJob]:
    """Return jobs whose lease has expired to the pending queue.

    This is the crash recovery path, and it is deliberately time-based rather than
    liveness-based. A worker that dies cannot tell anybody, so nothing but a clock can
    notice, and the alternative -- an administrator spotting a stuck row -- is not a
    recovery mechanism.

    The lease is cleared but the attempt count is **not** reset. A job that keeps killing
    its worker must still exhaust its attempts and reach the review queue, or a poison
    payload becomes an infinite loop.
    """
    now = _now(clock)
    rows = list(
        db.scalars(
            select(IntegrationJob)
            .where(
                IntegrationJob.status == IntegrationJobStatus.RUNNING,
                IntegrationJob.lease_expires_at.is_not(None),
                IntegrationJob.lease_expires_at <= now,
            )
            .limit(limit)
        ).all()
    )
    for job in rows:
        job.status = IntegrationJobStatus.PENDING
        job.lease_owner = None
        job.lease_token = None
        job.lease_expires_at = None
        job.available_at = now
        job.active_dedupe_key = job.dedupe_key
    db.flush()
    return rows


def holds_lease(job: IntegrationJob, lease_token: str, *, clock: Clock | None = None) -> bool:
    """Whether this token still holds a live lease on this job.

    Checked before a worker writes a result. Without it, a worker whose lease expired
    mid-flight -- and whose job another worker has since claimed and finished -- would
    overwrite the newer outcome with its own stale one.
    """
    now = _now(clock)
    return (
        job.lease_token == lease_token
        and job.lease_expires_at is not None
        and job.lease_expires_at > now
    )


# --- Outcomes --------------------------------------------------------------


def mark_succeeded(db: Session, job: IntegrationJob, *, clock: Clock | None = None) -> None:
    """Finish a job. The deduplication claim is released here and only here."""
    now = _now(clock)
    job.status = IntegrationJobStatus.SUCCEEDED
    job.completed_at = now
    job.lease_owner = None
    job.lease_token = None
    job.lease_expires_at = None
    job.error_code = None
    job.error_summary = None
    job.requires_review = False
    # Releasing the claim is what lets the next legitimate refresh be enqueued.
    job.active_dedupe_key = None
    db.flush()


def compute_backoff(
    attempt: int,
    *,
    retry_after_seconds: int | None = None,
    jitter: Jitter | None = None,
) -> int:
    """Seconds to wait before the next attempt.

    Exponential with **full jitter**: the delay is a uniform draw from ``[0, window)``
    rather than the window itself. Equal-jitter and no-jitter schemes leave every failed
    job retrying in lockstep, so a provider that just came back up is hit by the entire
    backlog at once -- which is how an outage turns into a second outage.

    A provider ``Retry-After`` is authoritative and is used as given, not jittered: the
    provider said when to come back, and spreading that request out means ignoring it.
    It is still bounded, so a provider cannot park a job indefinitely.
    """
    if retry_after_seconds is not None and retry_after_seconds > 0:
        return min(retry_after_seconds, settings.integration_retry_max_seconds)

    window = settings.integration_retry_base_seconds * (2 ** max(0, attempt - 1))
    window = min(window, settings.integration_retry_max_seconds)
    draw = jitter() if jitter else 0.5
    return max(1, int(window * draw))


def mark_failed(
    db: Session,
    job: IntegrationJob,
    *,
    kind: ProviderErrorKind,
    summary: str | None,
    retry_after_seconds: int | None = None,
    clock: Clock | None = None,
    jitter: Jitter | None = None,
) -> IntegrationJob:
    """Record a failure and decide whether this job may be attempted again.

    The decision is the adapter's classification plus the attempt count, and nothing
    else. In particular it is not a provider HTTP status: the worker never sees one.

    * ``MALFORMED_PAYLOAD``, ``MAPPING``, ``PERMANENT`` stop immediately. No retry changes
      a payload that does not parse or a status nothing maps to, and retrying makes the
      review queue slower to reach.
    * ``AUTHENTICATION`` gets a much smaller allowance than everything else. Repeating a
      rejected credential achieves nothing and can lock an account.
    * ``RETRYABLE`` and ``RATE_LIMITED`` back off and try again until the attempts run out.

    A terminal job sets ``requires_review`` and releases its deduplication claim, so an
    operator can retry it and a later legitimate enqueue is not blocked by a dead row.
    """
    now = _now(clock)
    job.error_code = kind.value
    job.error_summary = safe_summary(summary)
    job.provider_retry_after_seconds = retry_after_seconds
    job.lease_owner = None
    job.lease_token = None
    job.lease_expires_at = None

    if kind is ProviderErrorKind.AUTHENTICATION:
        allowance = min(job.max_attempts, settings.integration_auth_max_attempts)
    else:
        allowance = job.max_attempts

    unrecoverable = kind in {
        ProviderErrorKind.MALFORMED_PAYLOAD,
        ProviderErrorKind.MAPPING,
        ProviderErrorKind.PERMANENT,
    }

    if unrecoverable or job.attempt_count >= allowance:
        job.status = IntegrationJobStatus.FAILED_TERMINAL
        job.failed_at = now
        job.next_retry_at = None
        job.requires_review = True
        job.active_dedupe_key = None
    else:
        delay = compute_backoff(
            job.attempt_count, retry_after_seconds=retry_after_seconds, jitter=jitter
        )
        job.status = IntegrationJobStatus.PENDING
        job.next_retry_at = now + timedelta(seconds=delay)
        job.available_at = job.next_retry_at
        job.requires_review = False
        job.active_dedupe_key = job.dedupe_key

    db.flush()
    return job


def retry_manually(
    db: Session,
    job: IntegrationJob,
    *,
    actor: User | None = None,
    ip_address: str | None = None,
    clock: Clock | None = None,
) -> IntegrationJob:
    """An operator asks for a terminal job to be attempted again.

    **Nothing about the failure history is erased.** ``attempt_count`` keeps counting,
    ``error_code`` and ``error_summary`` stay until the next attempt overwrites them, and
    ``manual_retry_count`` records that a person intervened. A retry that wiped the
    history would make the second failure look like the first.

    The attempt allowance is raised rather than reset, so a manual retry buys exactly one
    more attempt. A person deciding to try again is a reason to try once; it is not a
    reason to restart an automatic loop that already exhausted itself.
    """
    now = _now(clock)
    if job.status not in {IntegrationJobStatus.FAILED_TERMINAL, IntegrationJobStatus.FAILED}:
        from app.services.errors import ConflictError

        raise ConflictError("Only a failed job can be retried.")

    job.status = IntegrationJobStatus.PENDING
    job.available_at = now
    job.next_retry_at = None
    job.max_attempts = job.attempt_count + 1
    job.requires_review = False
    job.failed_at = None
    job.lease_owner = None
    job.lease_token = None
    job.lease_expires_at = None
    job.manual_retry_count += 1
    job.last_manual_retry_at = now
    job.last_manual_retry_by_user_id = actor.id if actor else None
    job.active_dedupe_key = job.dedupe_key
    db.flush()

    audit_service.record_audit(
        db,
        action="integration.job_retry",
        entity_type="integration_job",
        entity_id=job.id,
        summary=f"Operator retried a failed {job.job_type} job",
        actor=actor,
        ip_address=ip_address,
        detail={
            "job_type": job.job_type,
            "provider_key": job.provider_key,
            "attempt_count": job.attempt_count,
            "manual_retry_count": job.manual_retry_count,
            # The classification, never the provider message.
            "previous_error_code": job.error_code,
        },
    )
    return job


def cancel(db: Session, job: IntegrationJob, *, clock: Clock | None = None) -> IntegrationJob:
    """Stop a job for good, releasing its claim."""
    job.status = IntegrationJobStatus.CANCELLED
    job.completed_at = _now(clock)
    job.lease_owner = None
    job.lease_token = None
    job.lease_expires_at = None
    job.requires_review = False
    job.active_dedupe_key = None
    db.flush()
    return job


# --- Inspection ------------------------------------------------------------


def counts_by_status(db: Session) -> dict[str, int]:
    """Queue depth per status. Survives a restart, because the queue is in the database."""
    from sqlalchemy import func

    rows = db.execute(
        select(IntegrationJob.status, func.count()).group_by(IntegrationJob.status)
    ).all()
    return dict(rows)


def oldest_pending_age_seconds(db: Session, *, clock: Clock | None = None) -> int | None:
    """Age of the oldest job waiting to run, or ``None`` when nothing is waiting.

    The single most useful number for noticing that a worker has stopped: pending counts
    look the same whether work is flowing or frozen, and this does not.
    """
    now = _now(clock)
    oldest = db.scalar(
        select(IntegrationJob.available_at)
        .where(IntegrationJob.status == IntegrationJobStatus.PENDING)
        .order_by(IntegrationJob.available_at.asc())
        .limit(1)
    )
    if oldest is None:
        return None
    return max(0, int((now - oldest).total_seconds()))


def jobs_requiring_review(db: Session, *, limit: int = 50) -> list[IntegrationJob]:
    """The failed-job review queue."""
    return list(
        db.scalars(
            select(IntegrationJob)
            .where(IntegrationJob.requires_review.is_(True))
            .order_by(IntegrationJob.failed_at.desc(), IntegrationJob.id.desc())
            .limit(limit)
        ).all()
    )
