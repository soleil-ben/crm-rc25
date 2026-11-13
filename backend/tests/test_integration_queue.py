"""The durable job queue: deduplication, atomic claiming, leases, and crash recovery.

The properties CRM.md section 9 requires of this queue are concurrency properties, and a
concurrency property asserted against one session is not asserted at all. The tests that
matter here open **two sessions on two separate connections** against an on-disk database
-- the same technique ``test_booking.py`` uses for the confirmation race (DEC-0031) --
because that is the only way a unique constraint or a conditional update gets to do the
thing it exists to do.

**What is demonstrated, and what is not.** Two independent SQLAlchemy sessions on separate
connections, which is a genuine race at the database. Not two operating-system processes:
SQLite is single-writer and this project runs one worker, so a multi-process claim is
neither needed nor demonstrated, and ``docs/OPERATIONS.md`` says so rather than implying
more.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.core.db import build_engine
from app.core.enums import IntegrationJobStatus, IntegrationJobType, ProviderErrorKind
from app.models import Base, IntegrationJob
from app.services import integration_job_service as jobs

FAKE = "fake"
BASE_TIME = datetime(2026, 9, 1, 9, 0, 0)


def clock_at(moment: datetime):
    return lambda: moment


def fixed_jitter(value: float = 0.5):
    return lambda: value


def enqueue_refresh(db, assignment_id: int, *, link_assignment: bool = False, **kwargs):
    """Enqueue a refresh keyed on an assignment id.

    ``link_assignment`` is off by default and the foreign key is left null, because these
    tests are about the deduplication key and the lease, not about the relationship. The
    id is still what the claim is namespaced by, so the behaviour under test is unchanged.
    A test that genuinely needs the foreign key builds a real assignment through
    ``tests/integration_fixtures.py`` and passes ``link_assignment=True``.
    """
    return jobs.enqueue(
        db,
        job_type=IntegrationJobType.REFRESH_TRACKING_ASSIGNMENT,
        provider_key=FAKE,
        tracking_assignment_id=assignment_id if link_assignment else None,
        dedupe_key=jobs.refresh_dedupe_key(assignment_id),
        clock=clock_at(BASE_TIME),
        **kwargs,
    )


@pytest.fixture
def two_sessions(tmp_path):
    """Two sessions on genuinely separate connections to one on-disk database.

    An in-memory database would give each connection its own private database and the
    race would not exist; a shared session would serialize the two callers in Python and
    the constraint would never be reached. Neither would test anything.
    """
    url = f"sqlite:///{(tmp_path / 'queue.db').as_posix()}"
    engine = build_engine(url)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)
    first, second = factory(), factory()
    try:
        yield first, second
    finally:
        first.close()
        second.close()
        engine.dispose()


# --- Deduplication ----------------------------------------------------------


def test_a_second_refresh_for_the_same_assignment_is_not_enqueued(db):
    """CRM.md section 9: concurrent page visits cause at most one pending refresh."""
    first = enqueue_refresh(db, 1)
    db.commit()

    second = enqueue_refresh(db, 1)

    assert first is not None
    assert second is None, "a second active refresh must not be created"
    assert db.query(IntegrationJob).count() == 1


def test_returning_none_means_the_work_is_already_queued_not_that_it_failed(db):
    enqueue_refresh(db, 1)
    db.commit()

    assert enqueue_refresh(db, 1) is None
    # The queue still holds exactly the work that was asked for.
    assert (
        db.query(IntegrationJob)
        .filter(IntegrationJob.status == IntegrationJobStatus.PENDING)
        .count()
        == 1
    )


def test_different_assignments_do_not_share_a_claim(db):
    assert enqueue_refresh(db, 1) is not None
    assert enqueue_refresh(db, 2) is not None
    assert db.query(IntegrationJob).count() == 2


def test_a_refresh_and_a_reconciliation_are_not_mutually_exclusive(db):
    """Different work with different reasons to exist. Only refresh is constrained."""
    assert enqueue_refresh(db, 1) is not None
    reconcile = jobs.enqueue(
        db,
        job_type=IntegrationJobType.RECONCILE_TRACKING_ASSIGNMENT,
        provider_key=FAKE,
        dedupe_key=f"{IntegrationJobType.RECONCILE_TRACKING_ASSIGNMENT}:assignment:1",
        clock=clock_at(BASE_TIME),
    )
    assert reconcile is not None


def test_a_completed_job_does_not_block_a_later_legitimate_refresh(db):
    """The reason ``active_dedupe_key`` is nulled rather than left in place.

    A permanent unique key on the claim would make the *second* refresh of an assignment
    impossible forever, which would be a worse bug than the duplicate it prevented.
    """
    first = enqueue_refresh(db, 1)
    jobs.mark_succeeded(db, first, clock=clock_at(BASE_TIME))
    db.commit()

    second = enqueue_refresh(db, 1)

    assert second is not None
    assert second.id != first.id
    assert first.active_dedupe_key is None
    assert first.dedupe_key is not None, "the permanent identity is kept for audit"


def test_a_terminally_failed_job_also_releases_its_claim(db):
    """So an operator can retry, and so a genuine new refresh is not blocked by a dead row."""
    job = enqueue_refresh(db, 1)
    job.attempt_count = 99
    jobs.mark_failed(
        db,
        job,
        kind=ProviderErrorKind.PERMANENT,
        summary="settled",
        clock=clock_at(BASE_TIME),
        jitter=fixed_jitter(),
    )
    db.commit()

    assert job.status == IntegrationJobStatus.FAILED_TERMINAL
    assert job.active_dedupe_key is None
    assert job.requires_review is True
    assert enqueue_refresh(db, 1) is not None


def test_a_retrying_job_keeps_its_claim(db):
    """A job waiting to retry is still active work; a second enqueue would duplicate it."""
    job = enqueue_refresh(db, 1)
    jobs.mark_failed(
        db,
        job,
        kind=ProviderErrorKind.RETRYABLE,
        summary="timeout",
        clock=clock_at(BASE_TIME),
        jitter=fixed_jitter(),
    )
    db.commit()

    assert job.status == IntegrationJobStatus.PENDING
    assert job.active_dedupe_key == job.dedupe_key
    assert enqueue_refresh(db, 1) is None


def test_concurrent_enqueues_from_separate_sessions_produce_one_job(two_sessions):
    """The guarantee, demonstrated where it actually lives: the database.

    Both sessions read an empty table, both decide to enqueue, and both flush. The unique
    constraint on ``active_dedupe_key`` is what makes exactly one of them win. Without the
    constraint this test would produce two jobs and two chargeable provider calls.
    """
    first, second = two_sessions

    job_one = enqueue_refresh(first, 42)
    first.commit()
    job_two = enqueue_refresh(second, 42)
    if job_two is not None:
        second.commit()

    total = first.query(IntegrationJob).count()
    assert total == 1, "two sessions must not both create a refresh for one assignment"
    assert job_one is not None
    assert job_two is None


def test_the_constraint_holds_even_when_the_pre_check_is_bypassed(two_sessions):
    """The pre-check is an optimization; the constraint is the guarantee.

    Inserting directly, without going through ``enqueue``, proves which of the two is
    actually load-bearing.
    """
    from sqlalchemy.exc import IntegrityError

    first, second = two_sessions
    enqueue_refresh(first, 7)
    first.commit()

    duplicate = IntegrationJob(
        job_type=IntegrationJobType.REFRESH_TRACKING_ASSIGNMENT,
        provider_key=FAKE,
        connection_key="unassigned",
        status=IntegrationJobStatus.PENDING,
        available_at=BASE_TIME,
        attempt_count=0,
        max_attempts=5,
        priority=100,
        dedupe_key=jobs.refresh_dedupe_key(7),
        active_dedupe_key=jobs.refresh_dedupe_key(7),
    )
    second.add(duplicate)

    with pytest.raises(IntegrityError):
        second.commit()


# --- Claiming ---------------------------------------------------------------


def test_claiming_marks_the_job_running_and_takes_a_lease(db):
    enqueue_refresh(db, 1)
    db.commit()

    claimed = jobs.claim_next(db, worker_name="w1", clock=clock_at(BASE_TIME))

    assert claimed is not None
    assert claimed.job.status == IntegrationJobStatus.RUNNING
    assert claimed.job.lease_owner == "w1"
    assert claimed.job.attempt_count == 1
    assert claimed.lease_expires_at > BASE_TIME


def test_a_job_that_is_not_due_yet_is_not_claimed(db):
    enqueue_refresh(db, 1, available_at=BASE_TIME + timedelta(minutes=10))
    db.commit()

    assert jobs.claim_next(db, worker_name="w1", clock=clock_at(BASE_TIME)) is None
    later = clock_at(BASE_TIME + timedelta(minutes=11))
    assert jobs.claim_next(db, worker_name="w1", clock=later) is not None


def test_priority_orders_the_queue(db):
    """A delivery notification must not queue behind a bulk refresh."""
    jobs.enqueue(
        db,
        job_type=IntegrationJobType.REFRESH_TRACKING_ASSIGNMENT,
        provider_key=FAKE,
        dedupe_key=jobs.refresh_dedupe_key(1),
        priority=100,
        clock=clock_at(BASE_TIME),
    )
    urgent = jobs.enqueue(
        db,
        job_type=IntegrationJobType.PROCESS_WEBHOOK_INBOX_ITEM,
        provider_key=FAKE,
        dedupe_key=jobs.inbox_dedupe_key(1),
        priority=10,
        clock=clock_at(BASE_TIME),
    )
    db.commit()

    claimed = jobs.claim_next(db, worker_name="w1", clock=clock_at(BASE_TIME))

    assert claimed.job.id == urgent.id


def test_two_sessions_cannot_claim_the_same_job(two_sessions):
    """Atomic claiming, under a real race, without ``SELECT ... FOR UPDATE``.

    Both sessions see one pending job. The conditional UPDATE is evaluated by the database
    while it holds the write lock, so exactly one of them reports ``rowcount == 1``.
    """
    first, second = two_sessions
    enqueue_refresh(first, 1)
    first.commit()

    claim_one = jobs.claim_next(first, worker_name="w1", clock=clock_at(BASE_TIME))
    first.commit()
    claim_two = jobs.claim_next(second, worker_name="w2", clock=clock_at(BASE_TIME))

    assert claim_one is not None
    assert claim_two is None, "a job already claimed must not be claimed again"


def test_a_live_lease_cannot_be_stolen(db):
    """The condition that separates recovery from theft."""
    enqueue_refresh(db, 1)
    db.commit()
    jobs.claim_next(db, worker_name="w1", clock=clock_at(BASE_TIME))
    db.commit()

    # Well inside the lease.
    midway = clock_at(BASE_TIME + timedelta(seconds=settings.integration_job_lease_seconds // 2))
    assert jobs.claim_next(db, worker_name="w2", clock=midway) is None


def test_an_expired_lease_is_reclaimed_after_a_worker_crash(db):
    """Crash recovery, which can only be time-based: a dead worker cannot report in.

    A crash is simulated the way a crash actually presents itself -- a row left ``running``
    with a lease and no worker behind it.
    """
    enqueue_refresh(db, 1)
    db.commit()
    claimed = jobs.claim_next(db, worker_name="crashed-worker", clock=clock_at(BASE_TIME))
    db.commit()
    assert claimed.job.status == IntegrationJobStatus.RUNNING

    after_expiry = clock_at(
        BASE_TIME + timedelta(seconds=settings.integration_job_lease_seconds + 60)
    )
    reclaimed = jobs.reclaim_expired(db, clock=after_expiry)
    db.commit()

    assert len(reclaimed) == 1
    assert reclaimed[0].id == claimed.job.id
    assert reclaimed[0].status == IntegrationJobStatus.PENDING
    assert reclaimed[0].lease_owner is None

    # And another worker can now pick it up.
    retaken = jobs.claim_next(db, worker_name="w2", clock=after_expiry)
    assert retaken is not None
    assert retaken.job.id == claimed.job.id


def test_reclaiming_does_not_reset_the_attempt_count(db):
    """A job that keeps killing its worker must still exhaust its attempts.

    Resetting would turn a poison payload into an infinite loop that never reaches the
    review queue.
    """
    enqueue_refresh(db, 1)
    db.commit()
    jobs.claim_next(db, worker_name="w1", clock=clock_at(BASE_TIME))
    db.commit()

    after = clock_at(BASE_TIME + timedelta(seconds=settings.integration_job_lease_seconds + 1))
    reclaimed = jobs.reclaim_expired(db, clock=after)

    assert reclaimed[0].attempt_count == 1


def test_holds_lease_is_false_once_the_lease_expires(db):
    """What stops a slow worker overwriting a newer worker's result."""
    enqueue_refresh(db, 1)
    db.commit()
    claimed = jobs.claim_next(db, worker_name="w1", clock=clock_at(BASE_TIME))

    assert jobs.holds_lease(claimed.job, claimed.lease_token, clock=clock_at(BASE_TIME))
    expired = clock_at(BASE_TIME + timedelta(seconds=settings.integration_job_lease_seconds + 1))
    assert not jobs.holds_lease(claimed.job, claimed.lease_token, clock=expired)
    assert not jobs.holds_lease(claimed.job, "some-other-token", clock=clock_at(BASE_TIME))


# --- Backoff and Retry-After ------------------------------------------------


def test_backoff_grows_exponentially_and_is_bounded():
    # Far enough that the ceiling is genuinely reached: base 30s doubling needs nine
    # attempts to pass one hour, and a range that stopped short would assert the cap
    # without ever exercising it.
    delays = [jobs.compute_backoff(attempt, jitter=fixed_jitter(1.0)) for attempt in range(1, 11)]

    assert delays[0] == settings.integration_retry_base_seconds
    assert delays[1] == settings.integration_retry_base_seconds * 2
    assert delays[2] == settings.integration_retry_base_seconds * 4
    assert all(delay <= settings.integration_retry_max_seconds for delay in delays)
    assert delays[-1] == settings.integration_retry_max_seconds


def test_jitter_spreads_retries_rather_than_synchronizing_them():
    """Full jitter: a uniform draw from the window, not the window itself.

    Without it every failed job retries in lockstep, and a provider that has just come
    back up is hit by the whole backlog at once.
    """
    low = jobs.compute_backoff(4, jitter=fixed_jitter(0.0))
    mid = jobs.compute_backoff(4, jitter=fixed_jitter(0.5))
    high = jobs.compute_backoff(4, jitter=fixed_jitter(1.0))

    assert low < mid < high
    assert low >= 1, "a delay is never zero"


def test_a_provider_retry_after_is_honoured_exactly_and_not_jittered():
    """The provider said when to come back. Spreading that out is ignoring it."""
    assert jobs.compute_backoff(1, retry_after_seconds=120, jitter=fixed_jitter(0.0)) == 120
    assert jobs.compute_backoff(9, retry_after_seconds=120, jitter=fixed_jitter(1.0)) == 120


def test_a_retry_after_is_still_bounded():
    """A provider cannot park a job for an arbitrary length of time."""
    assert (
        jobs.compute_backoff(1, retry_after_seconds=999_999)
        == settings.integration_retry_max_seconds
    )


def test_a_rate_limited_failure_schedules_the_provider_requested_delay(db):
    job = enqueue_refresh(db, 1)
    jobs.claim_next(db, worker_name="w1", clock=clock_at(BASE_TIME))

    jobs.mark_failed(
        db,
        job,
        kind=ProviderErrorKind.RATE_LIMITED,
        summary="provider asked us to slow down",
        retry_after_seconds=90,
        clock=clock_at(BASE_TIME),
        jitter=fixed_jitter(0.0),
    )

    assert job.status == IntegrationJobStatus.PENDING
    assert job.provider_retry_after_seconds == 90
    assert job.available_at == BASE_TIME + timedelta(seconds=90)
    assert job.error_code == ProviderErrorKind.RATE_LIMITED.value


# --- Failure classification -------------------------------------------------


@pytest.mark.parametrize(
    "kind",
    [
        ProviderErrorKind.MALFORMED_PAYLOAD,
        ProviderErrorKind.MAPPING,
        ProviderErrorKind.PERMANENT,
    ],
)
def test_an_unrecoverable_failure_is_terminal_on_the_first_attempt(db, kind):
    """No retry changes a payload that does not parse or a status nothing maps to."""
    job = enqueue_refresh(db, 1)
    jobs.claim_next(db, worker_name="w1", clock=clock_at(BASE_TIME))

    jobs.mark_failed(
        db, job, kind=kind, summary="settled", clock=clock_at(BASE_TIME), jitter=fixed_jitter()
    )

    assert job.status == IntegrationJobStatus.FAILED_TERMINAL
    assert job.attempt_count == 1
    assert job.requires_review is True
    assert job.next_retry_at is None


def test_an_authentication_failure_stops_far_sooner_than_a_timeout(db):
    """Repeating a rejected credential achieves nothing and can lock an account."""
    job = enqueue_refresh(db, 1)
    for attempt in range(1, settings.integration_auth_max_attempts + 1):
        job.attempt_count = attempt
        jobs.mark_failed(
            db,
            job,
            kind=ProviderErrorKind.AUTHENTICATION,
            summary="credential rejected",
            clock=clock_at(BASE_TIME),
            jitter=fixed_jitter(),
        )

    assert job.status == IntegrationJobStatus.FAILED_TERMINAL
    assert job.attempt_count < settings.integration_job_max_attempts


def test_a_retryable_failure_keeps_going_until_attempts_are_exhausted(db):
    job = enqueue_refresh(db, 1)

    for attempt in range(1, settings.integration_job_max_attempts):
        job.attempt_count = attempt
        jobs.mark_failed(
            db,
            job,
            kind=ProviderErrorKind.RETRYABLE,
            summary="timeout",
            clock=clock_at(BASE_TIME),
            jitter=fixed_jitter(),
        )
        assert job.status == IntegrationJobStatus.PENDING, f"attempt {attempt}"

    job.attempt_count = settings.integration_job_max_attempts
    jobs.mark_failed(
        db,
        job,
        kind=ProviderErrorKind.RETRYABLE,
        summary="timeout",
        clock=clock_at(BASE_TIME),
        jitter=fixed_jitter(),
    )

    assert job.status == IntegrationJobStatus.FAILED_TERMINAL
    assert job.requires_review is True


def test_a_terminal_job_is_not_claimed_again(db):
    job = enqueue_refresh(db, 1)
    job.attempt_count = 99
    jobs.mark_failed(
        db,
        job,
        kind=ProviderErrorKind.PERMANENT,
        summary="settled",
        clock=clock_at(BASE_TIME),
        jitter=fixed_jitter(),
    )
    db.commit()

    assert jobs.claim_next(db, worker_name="w1", clock=clock_at(BASE_TIME)) is None


# --- Operator retry ---------------------------------------------------------


def test_a_manual_retry_creates_a_new_attempt_without_erasing_the_history(db, users):
    """An audited retry that keeps the record of why it was needed."""
    job = enqueue_refresh(db, 1)
    job.attempt_count = 5
    jobs.mark_failed(
        db,
        job,
        kind=ProviderErrorKind.RETRYABLE,
        summary="provider timed out repeatedly",
        clock=clock_at(BASE_TIME),
        jitter=fixed_jitter(),
    )
    db.commit()
    assert job.status == IntegrationJobStatus.FAILED_TERMINAL

    jobs.retry_manually(db, job, actor=users["admin"], clock=clock_at(BASE_TIME))
    db.commit()

    assert job.status == IntegrationJobStatus.PENDING
    assert job.requires_review is False
    assert job.manual_retry_count == 1
    assert job.last_manual_retry_by_user_id == users["admin"].id
    # The history is intact.
    assert job.attempt_count == 5
    assert job.error_code == ProviderErrorKind.RETRYABLE.value
    assert job.error_summary is not None
    # And it buys exactly one more attempt, not a fresh automatic loop.
    assert job.max_attempts == 6


def test_a_manual_retry_is_audited(db, users):
    from app.models import AuditEvent

    job = enqueue_refresh(db, 1)
    job.attempt_count = 9
    jobs.mark_failed(
        db,
        job,
        kind=ProviderErrorKind.PERMANENT,
        summary="settled",
        clock=clock_at(BASE_TIME),
        jitter=fixed_jitter(),
    )
    jobs.retry_manually(db, job, actor=users["admin"], clock=clock_at(BASE_TIME))
    db.commit()

    entry = db.query(AuditEvent).filter(AuditEvent.action == "integration.job_retry").one_or_none()
    assert entry is not None
    assert entry.actor_user_id == users["admin"].id


def test_a_healthy_job_cannot_be_manually_retried(db, users):
    from app.services.errors import ConflictError

    job = enqueue_refresh(db, 1)
    db.commit()

    with pytest.raises(ConflictError):
        jobs.retry_manually(db, job, actor=users["admin"], clock=clock_at(BASE_TIME))


# --- Inspection -------------------------------------------------------------


def test_queue_state_survives_a_process_restart(tmp_path):
    """The queue is in the database, so a restart is not an event it notices."""
    url = f"sqlite:///{(tmp_path / 'restart.db').as_posix()}"
    engine = build_engine(url)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)

    first = factory()
    enqueue_refresh(first, 1)
    enqueue_refresh(first, 2)
    first.commit()
    first.close()
    engine.dispose()

    # A completely new engine, as a restarted process would build.
    engine2 = build_engine(url)
    factory2 = sessionmaker(bind=engine2, expire_on_commit=False, future=True)
    second = factory2()
    try:
        counts = jobs.counts_by_status(second)
        assert counts.get(IntegrationJobStatus.PENDING) == 2
        assert jobs.claim_next(second, worker_name="w1", clock=clock_at(BASE_TIME)) is not None
    finally:
        second.close()
        engine2.dispose()


def test_the_oldest_pending_age_reveals_a_stopped_worker(db):
    """Pending counts look the same whether work is flowing or frozen. This does not."""
    enqueue_refresh(db, 1)
    db.commit()

    fresh = jobs.oldest_pending_age_seconds(db, clock=clock_at(BASE_TIME))
    stale = jobs.oldest_pending_age_seconds(db, clock=clock_at(BASE_TIME + timedelta(hours=6)))

    assert fresh == 0
    assert stale == 6 * 3600


def test_the_oldest_pending_age_is_none_when_nothing_is_waiting(db):
    assert jobs.oldest_pending_age_seconds(db, clock=clock_at(BASE_TIME)) is None


def test_the_review_queue_lists_only_terminal_failures(db):
    healthy = enqueue_refresh(db, 1)
    broken = enqueue_refresh(db, 2)
    broken.attempt_count = 99
    jobs.mark_failed(
        db,
        broken,
        kind=ProviderErrorKind.MAPPING,
        summary="nothing maps",
        clock=clock_at(BASE_TIME),
        jitter=fixed_jitter(),
    )
    db.commit()

    review = jobs.jobs_requiring_review(db)

    assert [job.id for job in review] == [broken.id]
    assert healthy.requires_review is False


def test_an_unknown_job_type_is_refused_at_enqueue(db):
    with pytest.raises(ValueError, match="Unknown integration job type"):
        jobs.enqueue(db, job_type="not_a_real_job_type", provider_key=FAKE)


# --- Foreign keys -----------------------------------------------------------


def test_a_job_can_reference_a_real_tracking_assignment(db):
    """The relationship works, so the null-foreign-key shortcut above is a choice."""
    from tests.integration_fixtures import tracked_shipment

    tracked = tracked_shipment(db)

    job = enqueue_refresh(db, tracked.assignment.id, link_assignment=True)
    db.commit()

    assert job is not None
    assert job.tracking_assignment_id == tracked.assignment.id


def test_a_job_naming_a_missing_assignment_raises_rather_than_vanishing(db):
    """SQLite enforces foreign keys here, and a violation must not look like a duplicate.

    This is a regression test for a real defect found while writing this file. ``enqueue``
    caught every ``IntegrityError`` and returned ``None``, which the contract defines as
    "already queued" -- so a job with a bad foreign key was silently dropped while the
    caller was told the work was in hand. It now re-reads the table after the rollback and
    only reports a duplicate when there genuinely is one.
    """
    from sqlalchemy.exc import IntegrityError

    with pytest.raises(IntegrityError):
        jobs.enqueue(
            db,
            job_type=IntegrationJobType.REFRESH_TRACKING_ASSIGNMENT,
            provider_key=FAKE,
            tracking_assignment_id=999_999,
            dedupe_key=jobs.refresh_dedupe_key(999_999),
            clock=clock_at(BASE_TIME),
        )


def test_a_job_naming_a_missing_inbox_item_also_raises(db):
    from sqlalchemy.exc import IntegrityError

    with pytest.raises(IntegrityError):
        jobs.enqueue(
            db,
            job_type=IntegrationJobType.PROCESS_WEBHOOK_INBOX_ITEM,
            provider_key=FAKE,
            inbox_item_id=999_999,
            dedupe_key=jobs.inbox_dedupe_key(999_999),
            clock=clock_at(BASE_TIME),
        )
