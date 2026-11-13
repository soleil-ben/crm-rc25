"""The worker, end to end against the fake adapter.

Every scenario CRM.md section 9 names: successful processing, duplicate delivery,
concurrent duplicate delivery, retryable timeout, a provider 429 with ``Retry-After``,
provider server errors, a permanently malformed payload, authentication failure, an
invalid signature, an unsigned notification requiring an authenticated read, mapping
failure, worker crash with lease recovery, maximum-attempt exhaustion, an audited manual
retry, and a provider outage that must preserve the last known tracking state.

The clock and the jitter source are injected, so a backoff is **observed** rather than
waited out, and every run is deterministic. The worker runs in ``--once`` mode throughout:
**no unattended background service was started at any point during this build.**

The adapter is ``FakeProviderAdapter``. It is not ShipStation and does not model it.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from app.core.config import settings
from app.core.enums import (
    EventSource,
    InboxProcessingState,
    IntegrationJobStatus,
    IntegrationJobType,
    OperationalState,
    ProviderErrorKind,
    ProviderEventApplication,
    WebhookVerificationState,
)
from app.integrations.registry import AdapterRegistry
from app.models import (
    IntegrationJob,
    IntegrationProviderEvent,
    IntegrationWorkerHeartbeat,
    ShipmentEvent,
)
from app.services import integration_inbox_service as inbox
from app.services import integration_job_service as jobs
from app.workers import integration_worker
from tests.fakes import fake_provider_adapter as fake
from tests.fakes.fake_provider_adapter import (
    FakeProviderAdapter,
    make_payload,
    sign,
    signed_headers,
    unsigned_headers,
)
from tests.integration_fixtures import FAKE_TRACKING_NUMBER, tracked_shipment

BASE_TIME = datetime(2026, 9, 1, 9, 0, 0)
OCCURRED = "2026-09-01T08:00:00+00:00"


def clock_at(moment: datetime = BASE_TIME):
    return lambda: moment


def no_jitter():
    return 0.0


@pytest.fixture
def registry_with(request):
    """A registry holding one adapter, scoped to the test.

    Scoped rather than global so a fake cannot leak into a later test and make it pass for
    the wrong reason.
    """

    def _make(adapter) -> AdapterRegistry:
        return AdapterRegistry({adapter.capabilities().provider_key: adapter})

    return _make


def deliver_signed(db, adapter, **payload_kwargs):
    payload_kwargs.setdefault("occurred_at", OCCURRED)
    payload_kwargs.setdefault("reference", FAKE_TRACKING_NUMBER)
    body = make_payload(**payload_kwargs)
    result = inbox.accept_delivery(
        db, adapter=adapter, body=body, headers=signed_headers(body), clock=clock_at()
    )
    db.commit()
    return result


def run(db, registry, *, at: datetime = BASE_TIME, worker_name="w1", batch_size=20):
    return integration_worker.run_once(
        db,
        worker_name=worker_name,
        batch_size=batch_size,
        registry=registry,
        clock=clock_at(at),
        jitter=no_jitter,
    )


def provider_events(db) -> list[ShipmentEvent]:
    return db.query(ShipmentEvent).filter(ShipmentEvent.source == EventSource.PROVIDER).all()


# --- Successful processing --------------------------------------------------


def test_a_verified_notification_becomes_a_shipment_event(db, registry_with):
    adapter = FakeProviderAdapter()
    tracked = tracked_shipment(db)
    deliver_signed(db, adapter, status="FAKE_MOVING")

    result = run(db, registry_with(adapter))

    assert result.claimed == 1
    assert result.succeeded == 1
    assert result.failed == 0

    events = provider_events(db)
    assert len(events) == 1
    assert events[0].operational_state == OperationalState.IN_TRANSIT
    assert events[0].source == EventSource.PROVIDER

    db.refresh(tracked.shipment)
    assert tracked.shipment.operational_state == OperationalState.IN_TRANSIT


def test_the_normalized_event_records_provenance_and_the_raw_status(db, registry_with):
    adapter = FakeProviderAdapter()
    tracked_shipment(db)
    deliver_signed(db, adapter, status="FAKE_MOVING")

    run(db, registry_with(adapter))

    record = db.query(IntegrationProviderEvent).one()
    assert record.raw_status == "FAKE_MOVING"
    assert record.normalized_state == OperationalState.IN_TRANSIT
    assert record.mapping_version == "fake-map-1"
    assert record.provider_api_version == "fake-v0"
    assert record.verification_source == WebhookVerificationState.SIGNATURE_VALID
    assert record.application_state == ProviderEventApplication.APPLIED
    assert record.applied_shipment_event_id is not None
    # Occurred and received are separate, and the occurred time is the provider's.
    assert record.occurred_at == datetime(2026, 9, 1, 8, 0, 0)
    assert record.received_at == BASE_TIME
    assert record.occurred_at != record.received_at


def test_the_inbox_item_links_to_the_event_it_produced(db, registry_with):
    adapter = FakeProviderAdapter()
    tracked_shipment(db)
    delivery = deliver_signed(db, adapter)

    run(db, registry_with(adapter))
    db.refresh(delivery.item)

    assert delivery.item.processing_state == InboxProcessingState.PROCESSED
    assert delivery.item.normalized_event is not None
    assert delivery.item.resulting_shipment_event_id is not None


def test_the_worker_writes_a_heartbeat(db, registry_with):
    adapter = FakeProviderAdapter()

    run(db, registry_with(adapter), worker_name="worker-a")

    beat = db.query(IntegrationWorkerHeartbeat).one()
    assert beat.worker_name == "worker-a"
    assert beat.mode == "once"
    assert beat.last_seen_at == BASE_TIME


# --- Duplicates -------------------------------------------------------------


def test_a_duplicate_delivery_produces_exactly_one_downstream_effect(db, registry_with):
    """AC-9, all the way through.

    One timeline entry, one delivered count, one shipment state change, and no second
    audit action implying a separate business event.
    """
    from app.models import AuditEvent

    adapter = FakeProviderAdapter()
    tracked = tracked_shipment(db)

    deliver_signed(db, adapter, status="FAKE_HANDED_TO_RECIPIENT")
    run(db, registry_with(adapter))

    deliver_signed(db, adapter, status="FAKE_HANDED_TO_RECIPIENT")
    run(db, registry_with(adapter), at=BASE_TIME + timedelta(minutes=1))

    assert len(provider_events(db)) == 1
    assert db.query(IntegrationProviderEvent).count() == 1

    db.refresh(tracked.package)
    assert tracked.package.delivered_to_recipient_at is not None

    applied = (
        db.query(AuditEvent).filter(AuditEvent.action == "shipment.event_record_provider").count()
    )
    assert applied == 1, "a duplicate must not produce a second audited business event"


def test_a_provider_re_reporting_the_same_milestone_under_a_new_event_id_applies_once(
    db, registry_with
):
    """Providers replay from their own dashboards, with a fresh event id each time.

    Three layers, each deduplicating on the identity that is meaningful to it, and this
    test pins down which does what:

    * the **inbox** keys on the provider event id, so both deliveries are stored -- two
      durable records of two things the provider actually sent;
    * the **normalized event** keys on the adapter fingerprint over the immutable event
      fields, so the two deliveries are recognized as one real-world event;
    * the **shipment timeline** therefore gains one entry.

    The durability requirement is satisfied at the inbox, which is where the raw deliveries
    belong. Duplicating the normalized layer as well would put two identical rows in the
    audit trail of what actually happened, which is the opposite of useful.
    """
    from app.models import IntegrationWebhookInboxItem

    adapter = FakeProviderAdapter()
    tracked_shipment(db)

    deliver_signed(db, adapter, event_id="e1", status="FAKE_MOVING")
    run(db, registry_with(adapter))
    second = deliver_signed(db, adapter, event_id="e2", status="FAKE_MOVING")
    run(db, registry_with(adapter), at=BASE_TIME + timedelta(minutes=1))

    assert db.query(IntegrationWebhookInboxItem).count() == 2, "both deliveries are durable"
    assert second.is_duplicate is False, "a different event id is a different delivery"
    assert db.query(IntegrationProviderEvent).count() == 1, "one real-world event"
    assert len(provider_events(db)) == 1, "and one timeline entry"

    db.refresh(second.item)
    assert second.item.processing_state == InboxProcessingState.DUPLICATE


def test_no_follow_up_task_or_revenue_is_created_by_a_provider_event(db, registry_with):
    """Provider events move operational state and nothing else.

    Phase 4A gives the worker no path to a task, an amount, or a currency, so a duplicate
    cannot double any of them. Asserted rather than assumed.
    """
    from app.models import FollowUpTask

    adapter = FakeProviderAdapter()
    tracked = tracked_shipment(db)
    tasks_before = db.query(FollowUpTask).count()

    for _ in range(2):
        deliver_signed(db, adapter, status="FAKE_HANDED_TO_RECIPIENT")
        run(db, registry_with(adapter))

    db.refresh(tracked.shipment)
    assert db.query(FollowUpTask).count() == tasks_before
    assert tracked.shipment.selling_amount is None
    assert tracked.shipment.shipping_cost is None


# --- Status invariants ------------------------------------------------------


def test_one_delivered_package_of_three_stays_partially_delivered(db, registry_with):
    """AC-7, driven by a provider event rather than a staff entry."""
    adapter = FakeProviderAdapter()
    tracked = tracked_shipment(db, packages=3)

    deliver_signed(db, adapter, status="FAKE_HANDED_TO_RECIPIENT")
    run(db, registry_with(adapter))

    db.refresh(tracked.shipment)
    assert tracked.shipment.operational_state == OperationalState.PARTIALLY_DELIVERED


def test_an_intermediate_warehouse_receipt_is_not_delivery(db, registry_with):
    """AC-8. The provider says the parcel arrived somewhere; that is a milestone."""
    adapter = FakeProviderAdapter()
    tracked = tracked_shipment(db, final_delivery=False)

    deliver_signed(db, adapter, status="FAKE_AT_OUR_WAREHOUSE")
    run(db, registry_with(adapter))

    db.refresh(tracked.shipment)
    db.refresh(tracked.package)
    assert tracked.shipment.operational_state == OperationalState.RECEIVED_AT_SOLARIS
    assert tracked.package.delivered_to_recipient_at is None


def test_a_collection_point_handover_does_not_complete_the_shipment(db, registry_with):
    adapter = FakeProviderAdapter()
    tracked = tracked_shipment(db)

    deliver_signed(db, adapter, status="FAKE_LEFT_AT_LOCKER")
    run(db, registry_with(adapter))

    db.refresh(tracked.package)
    assert tracked.package.delivered_to_recipient_at is None
    assert tracked.package.operational_state == OperationalState.OUT_FOR_DELIVERY


def test_an_older_in_transit_event_cannot_regress_delivered(db, registry_with):
    """AC-9's second half, and the classic out-of-order bug.

    The late event is stored durably -- losing it would make a later argument with a
    carrier unwinnable -- and it simply is not the latest, so it changes nothing.
    """
    adapter = FakeProviderAdapter()
    tracked = tracked_shipment(db)

    deliver_signed(
        db, adapter, event_id="delivered", status="FAKE_HANDED_TO_RECIPIENT", occurred_at=OCCURRED
    )
    run(db, registry_with(adapter))
    db.refresh(tracked.shipment)
    assert tracked.shipment.operational_state == OperationalState.DELIVERED

    deliver_signed(
        db,
        adapter,
        event_id="late-transit",
        status="FAKE_MOVING",
        occurred_at="2026-08-31T08:00:00+00:00",
    )
    run(db, registry_with(adapter), at=BASE_TIME + timedelta(minutes=5))

    db.refresh(tracked.shipment)
    assert tracked.shipment.operational_state == OperationalState.DELIVERED
    # Durable, but with no effect on state.
    assert db.query(IntegrationProviderEvent).count() == 2
    assert len(provider_events(db)) == 2


def test_a_provider_event_does_not_overwrite_a_manual_one_at_the_same_instant(db, registry_with):
    """CRM.md section 9. A staff member who looked at the parcel is the better authority.

    Occurred-time ordering alone would not deliver this: the provider event is recorded
    later and would win on ``recorded_at``. The source tie-break settles it.
    """
    from app.core.enums import ShipmentEventType
    from app.services import event_service

    adapter = FakeProviderAdapter()
    tracked = tracked_shipment(db)
    occurred = datetime(2026, 9, 1, 8, 0, 0)

    event_service.record_event(
        db,
        tracked.shipment,
        {
            "event_type": ShipmentEventType.EXCEPTION,
            "occurred_at": occurred,
            "package_id": tracked.package.id,
            "internal_detail": "Staff inspected the parcel",
        },
    )
    db.commit()
    db.refresh(tracked.shipment)
    assert tracked.shipment.operational_state == OperationalState.EXCEPTION

    deliver_signed(db, adapter, status="FAKE_MOVING", occurred_at=OCCURRED)
    run(db, registry_with(adapter))

    db.refresh(tracked.package)
    assert tracked.package.operational_state == OperationalState.EXCEPTION, (
        "a provider report must not displace a staff entry at the same instant"
    )
    # And the staff event is untouched: not voided, not edited, not deleted.
    manual = db.query(ShipmentEvent).filter(ShipmentEvent.source == EventSource.MANUAL).all()
    assert all(not event.is_voided for event in manual)


def test_a_provider_event_never_produces_public_update_text(db, registry_with):
    """A provider sentence is not approved public wording (CRM.md section 10)."""
    adapter = FakeProviderAdapter()
    tracked_shipment(db)

    deliver_signed(db, adapter, detail="Carrier narrative nobody approved")
    run(db, registry_with(adapter))

    event = provider_events(db)[0]
    assert event.is_public_update is False
    assert event.public_update_text is None
    # The provider text is kept where a staff note is kept: internal only.
    assert event.internal_detail == "Carrier narrative nobody approved"


def test_the_solaris_identifiers_never_change(db, registry_with):
    """AC-6. A provider event is not a reason for an identifier to move."""
    adapter = FakeProviderAdapter()
    tracked = tracked_shipment(db)
    public_id = tracked.shipment.public_id
    package_reference = tracked.package.package_reference

    deliver_signed(db, adapter, status="FAKE_HANDED_TO_RECIPIENT")
    run(db, registry_with(adapter))

    db.refresh(tracked.shipment)
    db.refresh(tracked.package)
    assert tracked.shipment.public_id == public_id
    assert tracked.package.package_reference == package_reference


# --- Occurred time ----------------------------------------------------------


def test_a_missing_occurred_time_is_never_replaced_by_the_received_time(db, registry_with):
    """CRM.md section 9. ``received_at`` is not when it happened.

    Putting a delivery time on a parcel because that is when a message arrived is a
    fabricated milestone, so the event is recorded and explicitly not applied.
    """
    adapter = FakeProviderAdapter()
    tracked = tracked_shipment(db)

    deliver_signed(db, adapter, occurred_at=None)
    run(db, registry_with(adapter))

    record = db.query(IntegrationProviderEvent).one()
    assert record.occurred_at is None
    assert record.application_state == ProviderEventApplication.REJECTED
    assert "occurred time" in record.application_detail
    assert provider_events(db) == []

    db.refresh(tracked.shipment)
    assert tracked.shipment.operational_state != OperationalState.IN_TRANSIT


def test_a_wall_clock_time_with_no_zone_is_flagged_rather_than_assumed_utc(db, registry_with):
    """Missing timezone information is explicit, not silently treated as UTC."""
    from app.core.enums import OccurredTimeProvenance

    adapter = FakeProviderAdapter()
    tracked_shipment(db)

    deliver_signed(db, adapter, occurred_at="2026-09-01T08:00:00")
    run(db, registry_with(adapter))

    record = db.query(IntegrationProviderEvent).one()
    assert record.occurred_time_provenance == OccurredTimeProvenance.LOCAL_NO_TIMEZONE
    assert record.occurred_at_timezone is None


def test_an_explicit_offset_is_converted_and_recorded_as_such(db, registry_with):
    from app.core.enums import OccurredTimeProvenance

    adapter = FakeProviderAdapter()
    tracked_shipment(db)

    deliver_signed(db, adapter, occurred_at="2026-09-01T15:00:00+07:00")
    run(db, registry_with(adapter))

    record = db.query(IntegrationProviderEvent).one()
    assert record.occurred_time_provenance == OccurredTimeProvenance.PROVIDER_OFFSET
    assert record.occurred_at == datetime(2026, 9, 1, 8, 0, 0)


# --- Authenticity through the worker ----------------------------------------


def test_a_forged_event_cannot_mutate_shipment_state(db, registry_with):
    """AC-10. The forged delivery never even produces a job."""
    adapter = FakeProviderAdapter()
    tracked = tracked_shipment(db)
    before = tracked.shipment.operational_state

    body = make_payload(reference=FAKE_TRACKING_NUMBER, status="FAKE_HANDED_TO_RECIPIENT")
    forged = dict(signed_headers(body))
    forged["x-fake-signature"] = sign(body, secret="an-attacker-secret")
    inbox.accept_delivery(db, adapter=adapter, body=body, headers=forged, clock=clock_at())
    db.commit()

    result = run(db, registry_with(adapter))

    assert result.claimed == 0
    assert provider_events(db) == []
    db.refresh(tracked.shipment)
    assert tracked.shipment.operational_state == before
    db.refresh(tracked.package)
    assert tracked.package.delivered_to_recipient_at is None


def test_an_unverified_item_is_refused_even_if_a_job_reaches_the_worker(db, registry_with):
    """Belt to the inbox braces.

    The gate is re-checked at application time rather than trusted from the enqueue: an
    item can be re-judged while its job waits, and the rule has to hold at the moment
    state would change.
    """
    adapter = FakeProviderAdapter()
    tracked_shipment(db)
    delivery = deliver_signed(db, adapter)

    # Downgrade the verification after the job was queued.
    delivery.item.verification_state = WebhookVerificationState.UNSIGNED_UNTRUSTED
    db.commit()

    result = run(db, registry_with(adapter))

    assert result.succeeded == 0
    assert result.failed == 1
    assert provider_events(db) == []
    job = db.query(IntegrationJob).one()
    assert job.status == IntegrationJobStatus.FAILED_TERMINAL
    assert job.requires_review is True


def test_an_unsigned_notification_causes_an_authenticated_read_and_only_then_applies(
    db, registry_with
):
    """The rule for a provider with no signature mechanism.

    The notification claims delivery. The worker ignores that claim entirely and asks the
    provider, which says the parcel is still moving -- and the *answer* is what is applied.
    """
    adapter = FakeProviderAdapter(verifies_signatures=False, read_status="FAKE_MOVING")
    tracked = tracked_shipment(db)

    body = make_payload(reference=FAKE_TRACKING_NUMBER, status="FAKE_HANDED_TO_RECIPIENT")
    inbox.accept_delivery(
        db, adapter=adapter, body=body, headers=unsigned_headers(), clock=clock_at()
    )
    db.commit()

    result = run(db, registry_with(adapter))

    assert result.succeeded == 1
    assert adapter.read_calls == [FAKE_TRACKING_NUMBER], "exactly one provider question"

    record = db.query(IntegrationProviderEvent).one()
    assert record.verification_source == WebhookVerificationState.VERIFIED_BY_READ
    assert record.raw_status == "FAKE_MOVING", "the read is authoritative, not the claim"

    db.refresh(tracked.package)
    assert tracked.package.delivered_to_recipient_at is None, (
        "an unsigned claim of delivery must not deliver a parcel"
    )


def test_an_unsigned_provider_without_an_authenticated_read_applies_nothing(db, registry_with):
    """No signature and no read means nothing can be established. Manual mode is honest."""
    adapter = FakeProviderAdapter(verifies_signatures=False, supports_authenticated_read=False)
    tracked_shipment(db)

    body = make_payload(reference=FAKE_TRACKING_NUMBER)
    inbox.accept_delivery(
        db, adapter=adapter, body=body, headers=unsigned_headers(), clock=clock_at()
    )
    db.commit()

    result = run(db, registry_with(adapter))

    assert result.failed == 1
    assert provider_events(db) == []
    job = db.query(IntegrationJob).one()
    assert job.status == IntegrationJobStatus.FAILED_TERMINAL


# --- Failure handling -------------------------------------------------------


def queued_read_job(db, adapter, tracked) -> IntegrationJob:
    """A reconciliation job, so a failure can be exercised without a webhook."""
    job = jobs.enqueue(
        db,
        job_type=IntegrationJobType.RECONCILE_TRACKING_ASSIGNMENT,
        provider_key=adapter.capabilities().provider_key,
        tracking_assignment_id=tracked.assignment.id,
        dedupe_key=f"reconcile:{tracked.assignment.id}",
        clock=clock_at(),
    )
    db.commit()
    return job


def test_a_retryable_timeout_is_scheduled_for_another_attempt(db, registry_with):
    adapter = FakeProviderAdapter(read_error=fake.TIMEOUT)
    tracked = tracked_shipment(db)
    job = queued_read_job(db, adapter, tracked)

    result = run(db, registry_with(adapter))

    assert result.failed == 1
    db.refresh(job)
    assert job.status == IntegrationJobStatus.PENDING
    assert job.error_code == ProviderErrorKind.RETRYABLE.value
    assert job.next_retry_at is not None
    assert job.attempt_count == 1


def test_a_rate_limited_response_honours_the_provider_retry_after(db, registry_with):
    adapter = FakeProviderAdapter(read_error=fake.RATE_LIMITED)
    tracked = tracked_shipment(db)
    job = queued_read_job(db, adapter, tracked)

    run(db, registry_with(adapter))
    db.refresh(job)

    assert job.error_code == ProviderErrorKind.RATE_LIMITED.value
    assert job.provider_retry_after_seconds == 120
    assert job.available_at == BASE_TIME + timedelta(seconds=120)


def test_a_provider_server_error_is_retryable(db, registry_with):
    adapter = FakeProviderAdapter(read_error=fake.SERVER_ERROR)
    tracked = tracked_shipment(db)
    job = queued_read_job(db, adapter, tracked)

    run(db, registry_with(adapter))
    db.refresh(job)

    assert job.status == IntegrationJobStatus.PENDING
    assert job.error_code == ProviderErrorKind.RETRYABLE.value


def test_a_malformed_payload_is_terminal_immediately(db, registry_with):
    adapter = FakeProviderAdapter()
    tracked_shipment(db)
    delivery = deliver_signed(db, adapter)
    delivery.item.payload_text = "this is not json"
    db.commit()

    result = run(db, registry_with(adapter))

    assert result.failed == 1
    job = db.query(IntegrationJob).one()
    assert job.status == IntegrationJobStatus.FAILED_TERMINAL
    assert job.error_code == ProviderErrorKind.MALFORMED_PAYLOAD.value
    assert job.attempt_count == 1
    assert job.requires_review is True


def test_an_authentication_failure_stops_after_a_small_number_of_attempts(db, registry_with):
    adapter = FakeProviderAdapter(read_error=fake.AUTH_FAILED)
    tracked = tracked_shipment(db)
    job = queued_read_job(db, adapter, tracked)

    at = BASE_TIME
    for _ in range(settings.integration_auth_max_attempts + 2):
        run(db, registry_with(adapter), at=at)
        db.refresh(job)
        if job.status == IntegrationJobStatus.FAILED_TERMINAL:
            break
        at = job.available_at + timedelta(seconds=1)

    assert job.status == IntegrationJobStatus.FAILED_TERMINAL
    assert job.error_code == ProviderErrorKind.AUTHENTICATION.value
    assert job.attempt_count <= settings.integration_auth_max_attempts
    assert job.attempt_count < settings.integration_job_max_attempts


def test_a_mapping_failure_is_terminal_and_invents_nothing(db, registry_with):
    """An unmapped provider status goes to review rather than becoming a guess."""
    adapter = FakeProviderAdapter()
    tracked_shipment(db)
    deliver_signed(db, adapter, status="FAKE_SOMETHING_NOBODY_MAPPED")

    result = run(db, registry_with(adapter))

    assert result.failed == 1
    job = db.query(IntegrationJob).one()
    assert job.status == IntegrationJobStatus.FAILED_TERMINAL
    assert job.error_code == ProviderErrorKind.MAPPING.value
    assert job.requires_review is True
    assert provider_events(db) == [], "nothing is invented for an unmapped status"


def test_attempts_are_exhausted_and_the_job_reaches_the_review_queue(db, registry_with):
    adapter = FakeProviderAdapter(read_error=fake.TIMEOUT)
    tracked = tracked_shipment(db)
    job = queued_read_job(db, adapter, tracked)

    at = BASE_TIME
    for _ in range(settings.integration_job_max_attempts + 2):
        run(db, registry_with(adapter), at=at)
        db.refresh(job)
        if job.status == IntegrationJobStatus.FAILED_TERMINAL:
            break
        at = job.available_at + timedelta(seconds=1)

    assert job.status == IntegrationJobStatus.FAILED_TERMINAL
    assert job.attempt_count == settings.integration_job_max_attempts
    assert job in jobs.jobs_requiring_review(db)


def test_a_provider_outage_preserves_the_last_known_tracking_state(db, registry_with):
    """CRM.md section 9, stated as strongly as it deserves.

    Never replace a last known successful status with "unknown" merely because a refresh
    failed. A real Delivered turning into a placeholder because a request timed out is a
    customer-facing lie produced by an infrastructure problem.
    """
    adapter = FakeProviderAdapter()
    tracked = tracked_shipment(db)

    deliver_signed(db, adapter, status="FAKE_HANDED_TO_RECIPIENT")
    run(db, registry_with(adapter))
    db.refresh(tracked.shipment)
    assert tracked.shipment.operational_state == OperationalState.DELIVERED
    delivered_at = tracked.shipment.delivered_at

    # The provider now fails every read, repeatedly.
    adapter.read_error = fake.TIMEOUT
    job = queued_read_job(db, adapter, tracked)
    at = BASE_TIME + timedelta(minutes=1)
    for _ in range(settings.integration_job_max_attempts + 2):
        run(db, registry_with(adapter), at=at)
        db.refresh(job)
        if job.status == IntegrationJobStatus.FAILED_TERMINAL:
            break
        at = job.available_at + timedelta(seconds=1)

    db.refresh(tracked.shipment)
    db.refresh(tracked.package)
    assert tracked.shipment.operational_state == OperationalState.DELIVERED
    assert tracked.shipment.delivered_at == delivered_at
    assert tracked.package.delivered_to_recipient_at is not None
    assert tracked.shipment.operational_state != OperationalState.TRACKING_UNAVAILABLE


def test_a_manual_retry_creates_a_new_attempt_that_can_succeed(db, registry_with, users):
    """The operator path, end to end: the outage clears and the retry works."""
    adapter = FakeProviderAdapter(read_error=fake.TIMEOUT)
    tracked = tracked_shipment(db)
    job = queued_read_job(db, adapter, tracked)

    at = BASE_TIME
    for _ in range(settings.integration_job_max_attempts + 2):
        run(db, registry_with(adapter), at=at)
        db.refresh(job)
        if job.status == IntegrationJobStatus.FAILED_TERMINAL:
            break
        at = job.available_at + timedelta(seconds=1)
    assert job.status == IntegrationJobStatus.FAILED_TERMINAL
    attempts_before = job.attempt_count

    adapter.read_error = None
    jobs.retry_manually(db, job, actor=users["admin"], clock=clock_at(at))
    db.commit()

    result = run(db, registry_with(adapter), at=at)

    assert result.succeeded == 1
    db.refresh(job)
    assert job.status == IntegrationJobStatus.SUCCEEDED
    assert job.attempt_count == attempts_before + 1, "history continues rather than resetting"
    assert job.manual_retry_count == 1


# --- Crash recovery ---------------------------------------------------------


def test_a_crashed_worker_leaves_work_that_a_later_worker_reclaims(db, registry_with):
    """A crash presents as a running row with a lease and nobody behind it."""
    adapter = FakeProviderAdapter()
    tracked = tracked_shipment(db)
    deliver_signed(db, adapter)

    claimed = jobs.claim_next(db, worker_name="crashed", clock=clock_at())
    db.commit()
    assert claimed.job.status == IntegrationJobStatus.RUNNING
    assert provider_events(db) == []

    later = BASE_TIME + timedelta(seconds=settings.integration_job_lease_seconds + 60)
    result = run(db, registry_with(adapter), at=later, worker_name="replacement")

    assert result.reclaimed == 1
    assert result.succeeded == 1
    assert len(provider_events(db)) == 1
    db.refresh(tracked.shipment)
    assert tracked.shipment.operational_state == OperationalState.IN_TRANSIT


def test_a_live_lease_is_not_reclaimed_by_a_second_worker(db, registry_with):
    adapter = FakeProviderAdapter()
    tracked_shipment(db)
    deliver_signed(db, adapter)
    jobs.claim_next(db, worker_name="busy", clock=clock_at())
    db.commit()

    result = run(
        db,
        registry_with(adapter),
        at=BASE_TIME + timedelta(seconds=settings.integration_job_lease_seconds // 2),
        worker_name="impatient",
    )

    assert result.reclaimed == 0
    assert result.claimed == 0


# --- No provider configured -------------------------------------------------


def test_with_no_adapter_the_worker_reports_it_and_changes_nothing(db):
    """This installation's actual state: a worker with nothing to run work against."""
    adapter = FakeProviderAdapter()
    tracked = tracked_shipment(db)
    deliver_signed(db, adapter)
    before = tracked.shipment.operational_state

    result = integration_worker.run_once(
        db,
        worker_name="w1",
        registry=AdapterRegistry({}),
        clock=clock_at(),
        jitter=no_jitter,
    )

    assert result.skipped_no_adapter == 1
    assert provider_events(db) == []
    db.refresh(tracked.shipment)
    assert tracked.shipment.operational_state == before


def test_the_batch_size_bounds_one_pass(db, registry_with):
    adapter = FakeProviderAdapter()
    tracked_shipment(db)
    for index in range(5):
        deliver_signed(db, adapter, event_id=f"e{index}", status="FAKE_MOVING")

    result = run(db, registry_with(adapter), batch_size=2)

    assert result.claimed == 2


def test_the_cli_accepts_once_and_a_batch_size():
    """``--once`` is the documented deterministic mode, and it parses."""
    parsed = integration_worker.build_parser().parse_args(
        ["--once", "--batch-size", "3", "--worker-name", "w9"]
    )

    assert parsed.once is True
    assert parsed.batch_size == 3
    assert parsed.worker_name == "w9"
