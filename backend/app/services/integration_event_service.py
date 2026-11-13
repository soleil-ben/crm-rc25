"""Normalized provider events, and applying them under the existing status invariants.

Two responsibilities, and the split between them is the point.

**Recording** a normalized event is durable and unconditional: every verified provider
event becomes a row, including a duplicate and including one that arrives out of order.
Losing the record of a late delivery makes a later argument with a carrier unwinnable.

**Applying** it is conditional, and every condition is a rule that already existed.
Phase 2 derives shipment status from events, so applying a provider event means writing a
``shipment_events`` row through ``event_service.record_event`` and letting the same
reducer run. Nothing here re-implements a status rule, and that is why the Phase 2
guarantees survive:

* one delivered package of three stays **Partially delivered** -- derived from package
  rows, not from the event that just arrived;
* an intermediate warehouse receipt is a **milestone**, because only
  ``delivered_to_recipient`` sets ``delivered_to_recipient_at`` (DEC-0036);
* a collection-point handover does not complete a shipment, for the same reason;
* an older **In transit** cannot regress **Delivered**, because package state is the
  latest event by occurred time and a late arrival simply is not the latest (DEC-0037).

**A provider event never overwrites a manual one.** It never voids, edits, or deletes a
staff row -- there is no code path here that touches an existing event -- and at an
identical occurred time the manual row wins the tie, by the source rank in
``event_service._SOURCE_TIE_RANK``.

**Raw provider status is preserved and never published.** ``raw_status`` lives on
``integration_provider_events`` for audit and for debugging a mapping;
``public_tracking_service`` builds its response field by field from an allowlist that does
not include this table, and a provider event produces no public update text unless a staff
member writes one.

**Occurred and received times stay apart**, and a missing timezone is recorded as
``local_no_timezone`` rather than assumed to be UTC (CRM.md section 9).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.enums import (
    EVENT_TYPE_TO_OPERATIONAL_STATE,
    EventSource,
    OccurredTimeProvenance,
    ProviderEventApplication,
    ShipmentEventType,
)
from app.core.time_utils import utcnow
from app.integrations.adapter import (
    NormalizedProviderEvent,
    ProviderAdapterError,
    ProviderCapabilities,
)
from app.integrations.redaction import safe_summary
from app.models import (
    IntegrationProviderEvent,
    IntegrationWebhookInboxItem,
    LegTrackingReference,
    Shipment,
    ShipmentEvent,
    ShipmentLeg,
)
from app.models.integration import UNASSIGNED_CONNECTION
from app.services import event_service

Clock = Callable[[], datetime]


@dataclass(frozen=True)
class ApplicationResult:
    """What recording and applying one provider event produced."""

    record: IntegrationProviderEvent
    #: A ``ProviderEventApplication`` value.
    state: str
    shipment_event: ShipmentEvent | None = None
    #: True when the record already existed. Durable, and with no second effect.
    was_duplicate: bool = False


def _now(clock: Clock | None) -> datetime:
    return clock() if clock else utcnow()


def resolve_assignment(
    db: Session, *, provider_reference: str | None
) -> LegTrackingReference | None:
    """Find the Solaris tracking assignment a provider reference refers to.

    Exact match on an **active** reference only. A retired reference is deliberately not
    resolved: it belongs to a voided label, and applying a scan from a superseded carrier
    number to the parcel that replaced it would attach somebody's history to the wrong
    shipment.
    """
    if not provider_reference:
        return None
    return db.scalar(
        select(LegTrackingReference)
        .where(
            LegTrackingReference.tracking_number == provider_reference.strip(),
            LegTrackingReference.is_active.is_(True),
        )
        .order_by(LegTrackingReference.id.asc())
        .limit(1)
    )


def _shipment_for(db: Session, assignment: LegTrackingReference) -> Shipment | None:
    leg = db.get(ShipmentLeg, assignment.leg_id)
    if leg is None:
        return None
    return db.get(Shipment, leg.shipment_id)


def record_and_apply(
    db: Session,
    *,
    normalized: NormalizedProviderEvent,
    capabilities: ProviderCapabilities,
    verification_source: str,
    provider_reference: str | None,
    connection_key: str = UNASSIGNED_CONNECTION,
    inbox_item: IntegrationWebhookInboxItem | None = None,
    clock: Clock | None = None,
) -> ApplicationResult:
    """Store a normalized provider event, then apply it if the rules allow.

    Returns without raising for every outcome that is not a failure -- a duplicate, a
    superseded event, an unresolvable reference. Those are all things a real integration
    sees constantly, and turning them into exceptions would mean a worker retrying work
    that is already correctly finished.
    """
    now = _now(clock)

    existing = db.scalar(
        select(IntegrationProviderEvent).where(
            IntegrationProviderEvent.provider_key == capabilities.provider_key,
            IntegrationProviderEvent.connection_key == connection_key,
            IntegrationProviderEvent.provider_event_fingerprint == normalized.identity.fingerprint,
        )
    )
    if existing is not None:
        # Durable and already recorded. No second timeline entry, no second delivered
        # count, no second status change, and no audit line implying a separate event.
        return ApplicationResult(
            record=existing, state=existing.application_state, was_duplicate=True
        )

    assignment = resolve_assignment(db, provider_reference=provider_reference)
    shipment = None

    record = IntegrationProviderEvent(
        provider_key=capabilities.provider_key,
        provider_api_version=capabilities.provider_api_version,
        connection_key=connection_key,
        provider_event_id=normalized.identity.event_id,
        provider_event_fingerprint=normalized.identity.fingerprint,
        raw_status=normalized.raw_status,
        raw_status_detail=(normalized.raw_status_detail or None),
        normalized_event_type=normalized.event_type,
        normalized_state=EVENT_TYPE_TO_OPERATIONAL_STATE.get(
            normalized.event_type, normalized.operational_state
        ),
        occurred_at=normalized.occurred_at,
        occurred_at_timezone=normalized.occurred_at_timezone,
        occurred_time_provenance=normalized.occurred_time_provenance,
        received_at=now,
        verification_source=verification_source,
        mapping_version=capabilities.mapping_version,
        inbox_item_id=inbox_item.id if inbox_item else None,
        application_state=ProviderEventApplication.PENDING,
        is_voided=normalized.is_void,
    )
    db.add(record)
    try:
        db.flush()
    except IntegrityError:
        # Another session recorded the same provider event first. The unique constraint
        # over (provider, connection, fingerprint) is what makes "one downstream effect"
        # true under concurrency rather than merely likely.
        db.rollback()
        winner = db.scalar(
            select(IntegrationProviderEvent).where(
                IntegrationProviderEvent.provider_key == capabilities.provider_key,
                IntegrationProviderEvent.connection_key == connection_key,
                IntegrationProviderEvent.provider_event_fingerprint
                == normalized.identity.fingerprint,
            )
        )
        return ApplicationResult(record=winner, state=winner.application_state, was_duplicate=True)

    return apply_record(
        db,
        record=record,
        normalized=normalized,
        assignment=assignment,
        shipment=shipment,
        clock=clock,
    )


def apply_record(
    db: Session,
    *,
    record: IntegrationProviderEvent,
    normalized: NormalizedProviderEvent,
    assignment: LegTrackingReference | None,
    shipment: Shipment | None = None,
    clock: Clock | None = None,
) -> ApplicationResult:
    """Turn a stored normalized event into a shipment event, when the rules allow.

    Four reasons it may not become one, each recorded on the row rather than thrown away:

    * **no assignment** -- the provider reference matches no active tracking assignment,
      so there is nothing to attach it to;
    * **no occurred time** -- ``received_at`` is not a substitute, and a milestone with an
      invented time is worse than a milestone that waits (CRM.md section 9);
    * **already applied** -- an equivalent shipment event exists;
    * **superseded** -- the shipment already knows something later.
    """
    now = _now(clock)

    if assignment is None:
        record.application_state = ProviderEventApplication.REJECTED
        record.application_detail = "no active tracking assignment matches this reference"
        db.flush()
        return ApplicationResult(record=record, state=record.application_state)

    record.tracking_assignment_id = assignment.id
    record.leg_id = assignment.leg_id
    record.package_id = assignment.package_id

    shipment = shipment or _shipment_for(db, assignment)
    if shipment is None:
        record.application_state = ProviderEventApplication.REJECTED
        record.application_detail = "the tracking assignment has no shipment"
        db.flush()
        return ApplicationResult(record=record, state=record.application_state)

    record.shipment_id = shipment.id

    if normalized.occurred_at is None:
        # Explicitly not defaulted to ``received_at``. A provider that told us nothing
        # about when something happened has not told us when it happened, and putting a
        # delivery time on a parcel because that is when a message arrived is a fabricated
        # milestone.
        record.application_state = ProviderEventApplication.REJECTED
        record.application_detail = "the provider supplied no occurred time"
        record.occurred_time_provenance = OccurredTimeProvenance.MISSING
        db.flush()
        return ApplicationResult(record=record, state=record.application_state)

    if _equivalent_event_exists(db, shipment_id=shipment.id, normalized=normalized, record=record):
        record.application_state = ProviderEventApplication.SKIPPED_DUPLICATE
        record.application_detail = "an equivalent event was already applied"
        record.applied_at = now
        db.flush()
        return ApplicationResult(record=record, state=record.application_state)

    payload = {
        "event_type": normalized.event_type,
        "occurred_at": normalized.occurred_at,
        "package_id": assignment.package_id,
        "leg_id": assignment.leg_id,
        "location_label": normalized.location_label,
        "location_country_code": normalized.location_country_code,
        # The provider description is internal detail, exactly like a staff note. A
        # customer-facing update needs a staff member to write one and tick the box; a
        # provider sentence is not approved public wording (CRM.md section 10).
        "internal_detail": normalized.raw_status_detail,
        "is_public_update": False,
        "public_update_text": None,
        "is_final_recipient_delivery": (
            normalized.event_type == ShipmentEventType.DELIVERED_TO_RECIPIENT
        ),
    }

    try:
        created = event_service.record_event(
            db, shipment, payload, actor=None, source=EventSource.PROVIDER
        )
    except Exception as error:  # noqa: BLE001 - the reducer refused; that is an outcome
        record.application_state = ProviderEventApplication.REJECTED
        record.application_detail = safe_summary(type(error).__name__)
        db.flush()
        return ApplicationResult(record=record, state=record.application_state)

    record.application_state = ProviderEventApplication.APPLIED
    record.applied_shipment_event_id = created[0].id if created else None
    record.applied_at = now
    record.application_detail = None
    db.flush()
    return ApplicationResult(
        record=record,
        state=record.application_state,
        shipment_event=created[0] if created else None,
    )


def _equivalent_event_exists(
    db: Session,
    *,
    shipment_id: int,
    normalized: NormalizedProviderEvent,
    record: IntegrationProviderEvent,
) -> bool:
    """Whether this milestone has already been written as a shipment event.

    Belt to the unique constraint's braces. The constraint stops the same *provider
    event* being recorded twice; this stops the same *milestone* being written twice when
    a provider re-reports it under a new event id -- which providers do after an internal
    retry, a correction, or a webhook replay from their own dashboard.

    Matching is on the tuple a customer would recognize as the same line: same package,
    same event type, same occurred time, same source. Deliberately not on the provider
    description, which is free text a provider rewords without the event changing.
    """
    query = select(ShipmentEvent.id).where(
        ShipmentEvent.shipment_id == shipment_id,
        ShipmentEvent.event_type == normalized.event_type,
        ShipmentEvent.occurred_at == normalized.occurred_at,
        ShipmentEvent.source == EventSource.PROVIDER,
        ShipmentEvent.is_voided.is_(False),
    )
    if record.package_id is not None:
        query = query.where(ShipmentEvent.package_id == record.package_id)
    return db.scalar(query.limit(1)) is not None


def void_correction(
    db: Session,
    *,
    record: IntegrationProviderEvent,
    corrects: IntegrationProviderEvent,
    reason: str,
    clock: Clock | None = None,
) -> None:
    """Apply a provider correction, with explicit semantics rather than status ranking.

    The corrected event is **voided, not deleted**, exactly as a staff correction is
    (Phase 2). Its shipment event is voided too, which makes the reducer recompute without
    it -- so a withdrawn delivery genuinely stops counting rather than being outranked by
    something newer.

    A provider correction can only reach a provider event. There is no path from here to a
    manual event, which is what keeps a provider from withdrawing something a staff member
    saw with their own eyes.
    """
    now = _now(clock)
    record.corrects_event_id = corrects.id
    corrects.is_voided = True
    corrects.voided_at = now

    if corrects.applied_shipment_event_id:
        shipment_event = db.get(ShipmentEvent, corrects.applied_shipment_event_id)
        if shipment_event is not None and shipment_event.source == EventSource.PROVIDER:
            event_service.void_event(db, shipment_event, reason=reason, actor=None)
    db.flush()


def normalize_or_raise(adapter, source) -> NormalizedProviderEvent:
    """Ask the adapter to map a verified event, converting a refusal into a mapping error.

    A provider status this adapter has no mapping for is a **mapping** failure, which is
    terminal and goes to the review queue. Retrying it would never help, and guessing a
    plausible state would put a milestone in front of a customer that nobody reported.
    """
    from app.core.enums import ProviderErrorKind

    try:
        return adapter.normalize(source)
    except ProviderAdapterError:
        raise
    except Exception as error:  # noqa: BLE001
        raise ProviderAdapterError(
            ProviderErrorKind.MAPPING,
            f"adapter could not map this event ({type(error).__name__})",
        ) from error


def counts_by_application_state(db: Session) -> dict[str, int]:
    from sqlalchemy import func

    rows = db.execute(
        select(IntegrationProviderEvent.application_state, func.count()).group_by(
            IntegrationProviderEvent.application_state
        )
    ).all()
    return dict(rows)
