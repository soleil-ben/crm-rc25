"""The integration worker.

A small, provider-neutral process that claims jobs from ``integration_jobs``, runs them
through an adapter, and records what happened. CRM.md section 3 requires that the request
process never perform long provider polling inline; this is the process that does it
instead.

**Two modes.** ``--once`` makes one bounded pass and exits, which is what the tests and
the operator runbook use: a deterministic unit of work with an exit code. Continuous mode
loops with a sleep and stops on ``SIGINT``/``SIGTERM`` by finishing the job in hand and
then exiting, so a shutdown never leaves a half-applied event. **No unattended service was
started during this build**; every demonstration in ``PROJECT_STATUS.md`` is a ``--once``
run against synthetic fixtures.

**Everything variable is injected.** The clock, the jitter source, and the adapter
registry all arrive as parameters, so a test can observe a backoff without waiting for it
and a fake adapter can be used without a real one existing. A worker that reached for
``datetime.now`` and ``random.random`` directly would be a worker whose retry behaviour
could only be tested by sleeping.

**Failure handling is by classification, never by status code.** The adapter says what
kind of failure it was; ``integration_job_service.mark_failed`` decides what that means.
The worker itself contains no provider vocabulary at all, which is the property that lets
the provider be chosen later without rewriting this file.

**Logging is redacted structured text.** Job id, job type, provider key, attempt count,
outcome, and an error *category*. Never a payload, a credential, a tracking reference, a
customer detail, or a complete provider URL. ``app/integrations/redaction.py`` is applied
on the way in, and ``tests/test_integration_privacy.py`` reads the emitted lines back to
check it.
"""

from __future__ import annotations

import argparse
import logging
import random
import signal
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import session_scope
from app.core.enums import (
    IntegrationJobType,
    ProviderErrorKind,
    WebhookVerificationState,
)
from app.core.logging import log_event
from app.core.time_utils import utcnow
from app.integrations.adapter import ProviderAdapter, ProviderAdapterError
from app.integrations.redaction import safe_exception_summary
from app.integrations.registry import AdapterRegistry, AdapterUnavailableError
from app.integrations.registry import registry as default_registry
from app.models import (
    IntegrationJob,
    IntegrationWebhookInboxItem,
    IntegrationWorkerHeartbeat,
)
from app.services import (
    integration_event_service,
    integration_inbox_service,
    integration_job_service,
)

logger = logging.getLogger("solaris.integration_worker")

Clock = Callable[[], datetime]
Jitter = Callable[[], float]

DEFAULT_WORKER_NAME = "integration-worker-1"


@dataclass
class PassResult:
    """What one bounded pass did. Returned rather than logged, so tests can assert it."""

    claimed: int = 0
    succeeded: int = 0
    failed: int = 0
    reclaimed: int = 0
    skipped_no_adapter: int = 0
    outcomes: list[str] = field(default_factory=list)


def _now(clock: Clock | None) -> datetime:
    return clock() if clock else utcnow()


# --- Job handlers -----------------------------------------------------------


def _handle_process_inbox_item(
    db: Session, job: IntegrationJob, adapter: ProviderAdapter, *, clock: Clock | None
) -> str:
    """Turn a verified notification into a normalized event, and apply it.

    The authenticity gate is re-checked here rather than trusted from the enqueue. A job
    can sit in the queue while its inbox item is re-judged, and the rule that only a
    verified notification or an authenticated read may create a normalized event has to
    hold at the moment of application, not at the moment of queueing (CRM.md section 9).
    """
    item = db.get(IntegrationWebhookInboxItem, job.inbox_item_id) if job.inbox_item_id else None
    if item is None:
        raise ProviderAdapterError(ProviderErrorKind.PERMANENT, "the inbox item no longer exists")

    if item.verification_state not in {
        WebhookVerificationState.SIGNATURE_VALID,
        WebhookVerificationState.VERIFIED_BY_READ,
    }:
        # A forged or merely unsigned notification cannot mutate shipment or package
        # state. This is the line AC-10 turns on.
        raise ProviderAdapterError(
            ProviderErrorKind.PERMANENT,
            "notification is not verified; it cannot change shipment state",
        )

    if item.payload_text is None:
        raise ProviderAdapterError(
            ProviderErrorKind.MALFORMED_PAYLOAD, "the payload was not retained"
        )

    body = item.payload_text.encode("utf-8")
    try:
        parsed = adapter.parse_notification(body=body, headers={})
    except ProviderAdapterError:
        raise
    except Exception as error:  # noqa: BLE001
        raise ProviderAdapterError(
            ProviderErrorKind.MALFORMED_PAYLOAD, safe_exception_summary(error)
        ) from error

    normalized = integration_event_service.normalize_or_raise(adapter, parsed)
    result = integration_event_service.record_and_apply(
        db,
        normalized=normalized,
        capabilities=adapter.capabilities(),
        verification_source=item.verification_state,
        provider_reference=parsed.provider_reference,
        connection_key=item.connection_key,
        inbox_item=item,
        clock=clock,
    )

    if result.was_duplicate:
        integration_inbox_service.mark_duplicate(db, item, clock=clock)
    else:
        integration_inbox_service.mark_processed(db, item, clock=clock)
    return result.state


def _handle_verify_notification(
    db: Session, job: IntegrationJob, adapter: ProviderAdapter, *, clock: Clock | None
) -> str:
    """Ask the provider directly about an unsigned notification.

    The rule this implements: an unsigned notification is a hint that something may have
    changed. It may cause exactly one thing -- an authenticated question to the provider --
    and the *answer* is what may move a parcel. Nothing from the notification body is
    applied, including the status it claimed.
    """
    item = db.get(IntegrationWebhookInboxItem, job.inbox_item_id) if job.inbox_item_id else None
    if item is None:
        raise ProviderAdapterError(ProviderErrorKind.PERMANENT, "the inbox item no longer exists")

    if not adapter.capabilities().supports_authenticated_read:
        # No signature and no authenticated read means nothing about this notification can
        # be established. Manual milestones remain the honest mode; the item stays for
        # review rather than being applied on trust.
        raise ProviderAdapterError(
            ProviderErrorKind.PERMANENT,
            "provider offers neither a signature nor an authenticated read",
        )

    if item.payload_text is None:
        raise ProviderAdapterError(
            ProviderErrorKind.MALFORMED_PAYLOAD, "the payload was not retained"
        )

    parsed = adapter.parse_notification(body=item.payload_text.encode("utf-8"), headers={})
    if not parsed.provider_reference:
        raise ProviderAdapterError(
            ProviderErrorKind.MALFORMED_PAYLOAD,
            "the notification names no provider reference to verify",
        )

    authoritative = adapter.fetch_authoritative_state(provider_reference=parsed.provider_reference)
    normalized = integration_event_service.normalize_or_raise(adapter, authoritative)

    integration_inbox_service.mark_verified_by_read(db, item, clock=clock)
    result = integration_event_service.record_and_apply(
        db,
        normalized=normalized,
        capabilities=adapter.capabilities(),
        verification_source=WebhookVerificationState.VERIFIED_BY_READ,
        provider_reference=authoritative.provider_reference,
        connection_key=item.connection_key,
        inbox_item=item,
        clock=clock,
    )
    if result.was_duplicate:
        integration_inbox_service.mark_duplicate(db, item, clock=clock)
    else:
        integration_inbox_service.mark_processed(db, item, clock=clock)
    return result.state


def _handle_tracking_read(
    db: Session, job: IntegrationJob, adapter: ProviderAdapter, *, clock: Clock | None
) -> str:
    """Reconcile or refresh one tracking assignment from an authenticated read.

    **A failure here never replaces a known status with "unknown".** Nothing in this
    function writes on the failure path: the exception propagates, the job is retried or
    sent to review, and the shipment keeps the last state it legitimately had
    (CRM.md section 9). Overwriting a real Delivered with a placeholder because a request
    timed out would turn a provider outage into a customer-facing lie.
    """
    from app.models import LegTrackingReference

    assignment = (
        db.get(LegTrackingReference, job.tracking_assignment_id)
        if job.tracking_assignment_id
        else None
    )
    if assignment is None:
        raise ProviderAdapterError(
            ProviderErrorKind.PERMANENT, "the tracking assignment no longer exists"
        )
    if not assignment.is_active:
        # Retired: the label was voided or replaced. Routine polling stops for a retired
        # assignment rather than continuing to spend requests on a dead label.
        return "assignment_retired"

    authoritative = adapter.fetch_authoritative_state(provider_reference=assignment.tracking_number)
    normalized = integration_event_service.normalize_or_raise(adapter, authoritative)
    result = integration_event_service.record_and_apply(
        db,
        normalized=normalized,
        capabilities=adapter.capabilities(),
        verification_source=WebhookVerificationState.VERIFIED_BY_READ,
        provider_reference=authoritative.provider_reference,
        connection_key=job.connection_key,
        clock=clock,
    )
    return result.state


HANDLERS: dict[str, Callable[..., str]] = {
    IntegrationJobType.PROCESS_WEBHOOK_INBOX_ITEM: _handle_process_inbox_item,
    IntegrationJobType.VERIFY_NOTIFICATION: _handle_verify_notification,
    IntegrationJobType.RECONCILE_TRACKING_ASSIGNMENT: _handle_tracking_read,
    IntegrationJobType.REFRESH_TRACKING_ASSIGNMENT: _handle_tracking_read,
    IntegrationJobType.RETRY_PROVIDER_OPERATION: _handle_tracking_read,
}


# --- The pass ---------------------------------------------------------------


def run_once(
    db: Session,
    *,
    worker_name: str = DEFAULT_WORKER_NAME,
    batch_size: int | None = None,
    registry: AdapterRegistry | None = None,
    clock: Clock | None = None,
    jitter: Jitter | None = None,
    mode: str = "once",
) -> PassResult:
    """One bounded pass: reclaim expired leases, then claim and run up to ``batch_size``.

    Reclaiming first is deliberate. A worker that starts after a crash should pick up the
    work the dead worker was holding before it looks for anything new, or a stranded job
    stays stranded for as long as there is fresh work to prefer.
    """
    limit = batch_size or settings.integration_worker_batch_size
    adapters = registry or default_registry
    result = PassResult()

    reclaimed = integration_job_service.reclaim_expired(db, clock=clock)
    result.reclaimed = len(reclaimed)
    if reclaimed:
        log_event(
            logger,
            logging.INFO,
            "integration_worker_reclaimed_expired_leases",
            worker_name=worker_name,
            count=len(reclaimed),
        )

    for _index in range(limit):
        claimed = integration_job_service.claim_next(db, worker_name=worker_name, clock=clock)
        if claimed is None:
            break

        result.claimed += 1
        _run_claimed_job(
            db,
            claimed=claimed,
            adapters=adapters,
            result=result,
            worker_name=worker_name,
            clock=clock,
            jitter=jitter,
        )
        db.commit()

    _record_heartbeat(db, worker_name=worker_name, mode=mode, result=result, clock=clock)
    db.commit()
    return result


def _run_claimed_job(
    db: Session,
    *,
    claimed: integration_job_service.ClaimedJob,
    adapters: AdapterRegistry,
    result: PassResult,
    worker_name: str,
    clock: Clock | None,
    jitter: Jitter | None,
) -> None:
    job = claimed.job

    try:
        adapter = adapters.get(job.provider_key)
    except AdapterUnavailableError:
        # No provider is configured. This is the normal state of this installation, not a
        # failure: the job waits, the CRM keeps working, and nothing pretends otherwise.
        result.skipped_no_adapter += 1
        integration_job_service.mark_failed(
            db,
            job,
            kind=ProviderErrorKind.PERMANENT,
            summary="no provider adapter is configured",
            clock=clock,
            jitter=jitter,
        )
        result.failed += 1
        result.outcomes.append("no_adapter")
        _log_outcome(job, outcome="no_adapter", worker=worker_name)
        return

    handler = HANDLERS.get(job.job_type)
    if handler is None:
        integration_job_service.mark_failed(
            db,
            job,
            kind=ProviderErrorKind.PERMANENT,
            summary=f"no handler for job type {job.job_type}",
            clock=clock,
            jitter=jitter,
        )
        result.failed += 1
        result.outcomes.append("no_handler")
        _log_outcome(job, outcome="no_handler", worker=worker_name)
        return

    try:
        outcome = handler(db, job, adapter, clock=clock)
    except ProviderAdapterError as error:
        _fail(db, job, error.kind, error.summary, error.retry_after_seconds, result, clock, jitter)
        _log_outcome(job, outcome="failed", worker=worker_name, error_code=error.kind.value)
        return
    except Exception as error:  # noqa: BLE001 - an unclassified failure is still a failure
        # The adapter is asked to classify even a failure it did not raise itself, because
        # only it knows what its transport's exceptions mean.
        try:
            kind = adapter.classify_error(error)
        except Exception:  # noqa: BLE001
            kind = ProviderErrorKind.RETRYABLE
        _fail(
            db,
            job,
            kind,
            safe_exception_summary(error),
            None,
            result,
            clock,
            jitter,
        )
        _log_outcome(job, outcome="failed", worker=worker_name, error_code=kind.value)
        return

    if not integration_job_service.holds_lease(job, claimed.lease_token, clock=clock):
        # The lease expired while this job ran, and another worker may have claimed and
        # finished it. Writing a result now would overwrite a newer outcome with a stale
        # one, so the work is abandoned rather than recorded.
        result.outcomes.append("lease_lost")
        _log_outcome(job, outcome="lease_lost", worker=worker_name)
        return

    integration_job_service.mark_succeeded(db, job, clock=clock)
    result.succeeded += 1
    result.outcomes.append(outcome)
    _log_outcome(job, outcome=outcome, worker=worker_name)


def _fail(
    db: Session,
    job: IntegrationJob,
    kind: ProviderErrorKind,
    summary: str | None,
    retry_after: int | None,
    result: PassResult,
    clock: Clock | None,
    jitter: Jitter | None,
) -> None:
    integration_job_service.mark_failed(
        db,
        job,
        kind=kind,
        summary=summary,
        retry_after_seconds=retry_after,
        clock=clock,
        jitter=jitter,
    )
    result.failed += 1
    result.outcomes.append(f"failed:{kind.value}")


def _log_outcome(
    job: IntegrationJob, *, outcome: str, worker: str, error_code: str | None = None
) -> None:
    """One structured line per job. Identifiers and categories only.

    Everything here is either a database id, an application enum value, or a count.
    There is no payload, no credential, no tracking reference, no customer detail, and no
    provider URL -- and none of those can arrive through ``outcome`` or ``error_code``,
    because both are drawn from fixed vocabularies rather than from provider text.
    """
    log_event(
        logger,
        logging.INFO,
        "integration_worker_job",
        job_id=job.id,
        job_type=job.job_type,
        provider_key=job.provider_key,
        attempt=job.attempt_count,
        outcome=outcome,
        error_code=error_code or "none",
        worker=worker,
    )


def _record_heartbeat(
    db: Session,
    *,
    worker_name: str,
    mode: str,
    result: PassResult,
    clock: Clock | None,
    stopped: bool = False,
) -> None:
    """Record that this worker ran. A heartbeat exists only because a worker wrote it."""
    now = _now(clock)
    row = db.scalar(
        select(IntegrationWorkerHeartbeat).where(
            IntegrationWorkerHeartbeat.worker_name == worker_name
        )
    )
    if row is None:
        # The counters are set explicitly rather than left to the column defaults. A
        # SQLAlchemy ``default=`` is applied at flush, so a freshly constructed row holds
        # ``None`` until then -- and the ``+=`` below happens first.
        row = IntegrationWorkerHeartbeat(
            worker_name=worker_name,
            mode=mode,
            started_at=now,
            last_seen_at=now,
            jobs_claimed=0,
            jobs_succeeded=0,
            jobs_failed=0,
        )
        db.add(row)
    row.mode = mode
    row.last_seen_at = now
    row.jobs_claimed += result.claimed
    row.jobs_succeeded += result.succeeded
    row.jobs_failed += result.failed
    row.stopped_at = now if stopped else None
    db.flush()


# --- Entry point ------------------------------------------------------------


class _Shutdown:
    """Graceful stop: finish the job in hand, then exit.

    Killing a worker mid-job is survivable -- the lease expires and the job is reclaimed --
    but survivable is not the same as clean, and an operator restarting a worker should not
    have to wait out a lease to know the queue is idle.
    """

    def __init__(self) -> None:
        self.requested = False

    def install(self) -> None:
        for name in ("SIGINT", "SIGTERM"):
            handler = getattr(signal, name, None)
            if handler is not None:
                signal.signal(handler, self._request)

    def _request(self, _signum, _frame) -> None:  # noqa: ANN001
        self.requested = True
        log_event(logger, logging.INFO, "integration_worker_shutdown_requested")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="integration-worker",
        description=(
            "Provider-neutral integration worker. No provider is configured, so a run "
            "against a real installation processes nothing and reports that honestly."
        ),
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Make one bounded pass and exit. Deterministic; used by tests and runbooks.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=None,
        help="Jobs to claim in one pass. Defaults to INTEGRATION_WORKER_BATCH_SIZE.",
    )
    parser.add_argument(
        "--worker-name",
        default=DEFAULT_WORKER_NAME,
        help="Lease owner and heartbeat identity. Give each worker its own.",
    )
    parser.add_argument(
        "--poll-seconds",
        type=int,
        default=None,
        help="Sleep between passes in continuous mode.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

    jitter = random.Random().random  # noqa: S311 - backoff spread, not a security decision

    if args.once:
        with session_scope() as db:
            result = run_once(
                db,
                worker_name=args.worker_name,
                batch_size=args.batch_size,
                jitter=jitter,
                mode="once",
            )
        log_event(
            logger,
            logging.INFO,
            "integration_worker_pass_complete",
            claimed=result.claimed,
            succeeded=result.succeeded,
            failed=result.failed,
            reclaimed=result.reclaimed,
        )
        return 0

    shutdown = _Shutdown()
    shutdown.install()
    interval = args.poll_seconds or settings.integration_worker_poll_seconds
    log_event(
        logger,
        logging.INFO,
        "integration_worker_started",
        worker_name=args.worker_name,
        outcome="continuous",
    )

    while not shutdown.requested:
        with session_scope() as db:
            result = run_once(
                db,
                worker_name=args.worker_name,
                batch_size=args.batch_size,
                jitter=jitter,
                mode="continuous",
            )
        if shutdown.requested:
            break
        if result.claimed == 0:
            time.sleep(interval)

    with session_scope() as db:
        _record_heartbeat(
            db,
            worker_name=args.worker_name,
            mode="continuous",
            result=PassResult(),
            clock=None,
            stopped=True,
        )
    log_event(logger, logging.INFO, "integration_worker_stopped", worker_name=args.worker_name)
    return 0


if __name__ == "__main__":  # pragma: no cover - process entry point
    sys.exit(main())
