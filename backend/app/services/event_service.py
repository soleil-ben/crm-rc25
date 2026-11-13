"""Manual operational events and the derived shipment status.

CRM.md section 7 and section 10 impose four rules that this module exists to enforce.

1. **One delivered package of three is Partially delivered**, never Delivered, and the
   progress line reads "1 of 3 packages delivered".
2. **Delivery to an intermediate Solaris warehouse is a milestone**, not delivery, when
   the customer's destination is elsewhere. Only an event that is explicitly a
   final-recipient delivery can complete a package.
3. **A late or older event must not regress a newer valid state.** Package state is the
   *latest* event by occurred time, so an out-of-order arrival simply is not the latest.
4. **Internal notes are never public updates.** A public update needs its own flag and
   its own text; ``internal_detail`` is never read into a customer-facing field.

``occurred_at`` and ``recorded_at`` are stored separately so a late entry cannot
masquerade as a fresh scan.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.countries import normalize_country_code
from app.core.enums import (
    EVENT_TYPE_TO_OPERATIONAL_STATE,
    BookingState,
    EventSource,
    OperationalState,
    ShipmentEventType,
)
from app.core.normalization import collapse_whitespace
from app.core.time_utils import as_utc, utcnow
from app.models import (
    Shipment,
    ShipmentEvent,
    ShipmentEventRevision,
    ShipmentLeg,
    ShipmentPackage,
    User,
)
from app.services import audit_service, package_service
from app.services import public_update_templates as templates
from app.services.errors import ConflictError, NotFoundError, ValidationError

# Only this event type can complete a package. A collection-point handover and a
# warehouse receipt are deliberately separate types (CRM.md section 10).
FINAL_DELIVERY_EVENT = ShipmentEventType.DELIVERED_TO_RECIPIENT

# Event types that describe arrival at a Solaris facility rather than at the consignee.
INTERMEDIATE_EVENTS = frozenset(
    {
        ShipmentEventType.RECEIVED_AT_SOLARIS,
        ShipmentEventType.ARRIVED_DESTINATION,
        ShipmentEventType.PROCESSING,
    }
)

# How far along the normalized journey each state is. Used only to pick the most
# representative state across several packages -- never to decide whether a newer event
# may overwrite an older one, which is settled by occurred time alone.
STATE_PROGRESS: dict[str, int] = {
    OperationalState.TRACKING_UNAVAILABLE: 0,
    OperationalState.BOOKED: 1,
    OperationalState.AWAITING_PARCEL: 2,
    OperationalState.RECEIVED_AT_SOLARIS: 3,
    OperationalState.PROCESSING: 4,
    OperationalState.DEPARTED_ORIGIN: 5,
    OperationalState.IN_TRANSIT: 6,
    OperationalState.CUSTOMS_PROCESSING: 7,
    OperationalState.ARRIVED_DESTINATION: 8,
    OperationalState.OUT_FOR_DELIVERY: 9,
    OperationalState.DELIVERY_ATTEMPTED: 9,
    OperationalState.PARTIALLY_DELIVERED: 10,
    OperationalState.DELIVERED: 11,
    OperationalState.EXCEPTION: 6,
    OperationalState.RETURN_IN_PROGRESS: 6,
    OperationalState.RETURNED: 11,
    OperationalState.CANCELLED: 11,
}

# States that demand staff attention and therefore surface ahead of ordinary progress.
ATTENTION_STATES = (
    OperationalState.EXCEPTION,
    OperationalState.DELIVERY_ATTEMPTED,
    OperationalState.RETURN_IN_PROGRESS,
)


@dataclass(frozen=True)
class StatusResult:
    operational_state: str
    progress: package_service.PackageProgress
    delivered_at: datetime | None


#: Tie-break rank when two events claim the same occurred time.
#:
#: The latest event is chosen with ``max``, so the **higher** rank wins -- which is why
#: manual is 1 and provider is 0. A staff entry outranks a provider report at the same
#: instant.
#:
#: Added in Phase 4A. CRM.md section 9 requires that a provider event must not overwrite a
#: manual one, and occurred-time ordering alone does not deliver that: a provider event
#: stamped at the same instant as a staff correction would be recorded later and would
#: therefore win on ``recorded_at``. A staff member who has looked at the parcel is the
#: better authority when the two disagree about the same moment.
#:
#: This changes nothing about Phase 2 behaviour. Every event written before Phase 4A has
#: ``source = "manual"``, so the rank is constant across them and the ordering is exactly
#: what it was. It is also **not** a status ranking: it settles a tie at an identical
#: occurred time and never decides whether a newer event may overwrite an older one, which
#: remains occurred time alone (DEC-0037).
_SOURCE_TIE_RANK = {EventSource.MANUAL: 1, EventSource.PROVIDER: 0}


def _event_sort_key(event: ShipmentEvent) -> tuple[datetime, int, datetime, int]:
    """Latest-wins ordering: occurred time, then source, then entry time, then insertion."""
    return (
        event.occurred_at,
        _SOURCE_TIE_RANK.get(event.source, 1),
        event.recorded_at,
        event.id or 0,
    )


# --- Recording -------------------------------------------------------------


def record_event(
    db: Session,
    shipment: Shipment,
    payload: dict[str, Any],
    *,
    actor: User | None = None,
    ip_address: str | None = None,
    source: str = EventSource.MANUAL,
) -> list[ShipmentEvent]:
    """Record one operational event, then recompute derived status.

    An event with no ``package_id`` applies to every active package, which is how staff
    record "the whole shipment departed origin" without ticking three boxes.

    ``source`` is ``manual`` for everything a person enters and ``provider`` for a
    normalized provider event applied by the integration worker (Phase 4A). It exists so
    a provider row is distinguishable by that column alone, and so the audit entry says
    which of the two happened -- an audit line implying a staff member acted when a
    worker did would be a false record of a business event.

    Routing provider events through this function rather than writing
    ``shipment_events`` directly is deliberate. Every invariant lives here: only a
    ``delivered_to_recipient`` event may complete a package, a warehouse receipt and a
    collection-point handover cannot be flagged as final delivery, a future occurred time
    is refused, and public wording requires its own explicit flag. A second write path
    would be a second place for those rules to be forgotten.
    """
    if shipment.booking_state == BookingState.DRAFT:
        raise ConflictError("Confirm the booking before recording operational events.")
    if shipment.booking_state == BookingState.CANCELLED:
        # A milestone on a cancelled booking would sit on a timeline nobody should be
        # acting on. The detail page no longer offers the action (UAT round 3); this is
        # the rule that holds whatever the client sends.
        raise ConflictError("This booking is cancelled; it cannot receive new events.")

    event_type = payload.get("event_type")
    if event_type not in set(ShipmentEventType):
        raise ValidationError(f"Unknown event type '{event_type}'.", field="event_type")

    occurred_at = as_utc(payload.get("occurred_at")) or utcnow()
    recorded_at = utcnow()
    if occurred_at > recorded_at:
        raise ValidationError("An event cannot have occurred in the future.", field="occurred_at")

    try:
        country = normalize_country_code(payload.get("location_country_code"))
    except ValueError as exc:
        raise ValidationError(str(exc), field="location_country_code") from exc

    is_public = bool(payload.get("is_public_update"))
    public_text = collapse_whitespace(payload.get("public_update_text"))
    template_key = (payload.get("public_update_template_key") or "").strip() or None

    # A milestone carries an approved template key *or* a typed sentence, never both.
    # Merging them would mean the customer's language decided which of two different
    # messages they read, and staff would have no way to see what was actually published.
    if template_key and public_text:
        raise ValidationError(
            "Choose a standard update or write your own wording, not both.",
            field="public_update_template_key",
        )
    if template_key and not templates.is_valid_for(template_key, event_type):
        raise ValidationError(
            "That standard update is not offered for this event type.",
            field="public_update_template_key",
        )
    if is_public and not public_text and not template_key:
        raise ValidationError(
            "A public update needs its own wording. Internal detail is never shown to customers.",
            field="public_update_text",
        )
    if (public_text or template_key) and not is_public:
        # Wording without the flag would be an unapproved public update; refuse rather than
        # guessing the staff member's intent.
        raise ValidationError(
            "Tick 'Publish this update' to make this text customer-visible.",
            field="is_public_update",
        )

    leg = None
    if payload.get("leg_id"):
        leg = db.get(ShipmentLeg, payload["leg_id"])
        if leg is None or leg.shipment_id != shipment.id:
            raise NotFoundError("That transport leg does not belong to this shipment.")

    # Final-recipient delivery is explicit. A leg flagged as final delivery may supply
    # the default, but only the recipient-delivery event type can ever complete.
    is_final = bool(payload.get("is_final_recipient_delivery"))
    if event_type == FINAL_DELIVERY_EVENT:
        is_final = True
    elif is_final:
        raise ValidationError(
            "Only a 'Delivered to recipient' event can complete a package. A warehouse "
            "or collection-point handover is a milestone.",
            field="is_final_recipient_delivery",
        )

    targets = _resolve_targets(db, shipment, payload.get("package_id"))
    created: list[ShipmentEvent] = []
    for package in targets:
        event = ShipmentEvent(
            shipment_id=shipment.id,
            package_id=package.id if package else None,
            leg_id=leg.id if leg else None,
            event_type=event_type,
            operational_state=EVENT_TYPE_TO_OPERATIONAL_STATE[event_type],
            occurred_at=occurred_at,
            recorded_at=recorded_at,
            location_label=collapse_whitespace(payload.get("location_label")),
            location_country_code=country,
            internal_detail=payload.get("internal_detail"),
            is_public_update=is_public,
            public_update_text=public_text,
            public_update_template_key=template_key,
            is_final_recipient_delivery=is_final,
            source=source,
            recorded_by_user_id=actor.id if actor else None,
        )
        db.add(event)
        created.append(event)
    db.flush()

    recompute_status(db, shipment)

    # Phase 13F: a published milestone queues one email per milestone (OD-72). Imported here
    # so the notification module, which reads packages and consent, never imports this one.
    from app.services import notification_service  # noqa: PLC0415

    notification_service.enqueue_for_events(db, shipment, created)

    is_provider = source == EventSource.PROVIDER
    audit_service.record_audit(
        db,
        action="shipment.event_record_provider" if is_provider else "shipment.event_record",
        entity_type="shipment",
        entity_id=shipment.id,
        summary=(
            f"{'Applied a provider' if is_provider else 'Recorded'} {event_type} on "
            f"{shipment.public_id} ({len(created)} package record(s))"
        ),
        actor=actor,
        ip_address=ip_address,
        detail={
            "event_type": event_type,
            "source": source,
            "occurred_at": occurred_at.isoformat(),
            "recorded_at": recorded_at.isoformat(),
            "is_public_update": is_public,
            # The key, never the rendered sentence: the audit records which approved
            # wording was chosen, and the catalogue says what that wording was.
            "public_update_template_key": template_key,
            "is_final_recipient_delivery": is_final,
            "packages": [package.id for package in targets if package],
        },
    )
    return created


def _resolve_targets(
    db: Session, shipment: Shipment, package_id: int | None
) -> list[ShipmentPackage | None]:
    if package_id is not None:
        package = db.get(ShipmentPackage, package_id)
        if package is None or package.shipment_id != shipment.id:
            raise NotFoundError("That package does not belong to this shipment.")
        if not package.is_active:
            raise ConflictError("That package is cancelled; it cannot receive new events.")
        return [package]
    active = package_service.active_packages(db, shipment.id)
    if not active:
        return [None]
    return list(active)


def void_event(
    db: Session,
    event: ShipmentEvent,
    *,
    reason: str,
    actor: User | None = None,
    ip_address: str | None = None,
) -> ShipmentEvent:
    """Void an event as a correction. History is preserved, never deleted."""
    cleaned = collapse_whitespace(reason)
    if not cleaned:
        raise ValidationError("A correction needs a reason.", field="reason")
    if event.is_voided:
        raise ConflictError("That event is already voided.")

    event.is_voided = True
    event.voided_at = utcnow()
    event.voided_reason = cleaned[:255]
    db.flush()

    shipment = db.get(Shipment, event.shipment_id)
    recompute_status(db, shipment)

    # Phase 13F: a voided milestone's unsent notification is withdrawn and its key freed.
    from app.services import notification_service  # noqa: PLC0415

    notification_service.withdraw_for_voided_event(db, event)

    audit_service.record_audit(
        db,
        action="shipment.event_void",
        entity_type="shipment",
        entity_id=event.shipment_id,
        summary=f"Voided a {event.event_type} event on {shipment.public_id}",
        actor=actor,
        ip_address=ip_address,
        detail={"event_id": event.id, "reason": cleaned[:255]},
    )
    return event


# --- Derived status --------------------------------------------------------


def package_events(db: Session, package_id: int) -> list[ShipmentEvent]:
    return list(
        db.scalars(
            select(ShipmentEvent).where(
                ShipmentEvent.package_id == package_id, ShipmentEvent.is_voided.is_(False)
            )
        ).all()
    )


def _package_state(events: list[ShipmentEvent]) -> tuple[str, datetime | None]:
    """State and final-delivery time for one package.

    The latest event by occurred time wins. That single rule is what stops an older
    "In transit" entered after the fact from regressing a delivered package, and it does
    so without ranking states against each other.
    """
    if not events:
        return OperationalState.BOOKED, None
    latest = max(events, key=_event_sort_key)
    delivered_events = [event for event in events if event.is_final_recipient_delivery]
    delivered_at = (
        min(event.occurred_at for event in delivered_events) if delivered_events else None
    )
    return latest.operational_state, delivered_at


def recompute_status(db: Session, shipment: Shipment) -> StatusResult:
    """Recompute every package state and the overall shipment state.

    Package states are written back so list queries stay cheap; this function is their
    only writer.
    """
    packages = package_service.all_packages(db, shipment.id)
    for package in packages:
        if not package.is_active:
            package.operational_state = OperationalState.CANCELLED
            continue
        state, delivered_at = _package_state(package_events(db, package.id))
        package.operational_state = state
        package.delivered_to_recipient_at = delivered_at
    db.flush()

    progress = package_service.progress(db, shipment.id)
    overall, delivered_at = _overall_state(shipment, packages, progress)

    if shipment.booking_state != BookingState.CANCELLED:
        shipment.operational_state = overall
        shipment.delivered_at = delivered_at
        # First physical handoff is the qualifying-shipment trigger (CRM.md section 4):
        # the earliest moment Solaris or a carrier actually took custody.
        shipment.first_handoff_at = shipment.first_handoff_at or _first_handoff(db, shipment.id)
    db.flush()
    return StatusResult(
        operational_state=shipment.operational_state,
        progress=progress,
        delivered_at=delivered_at,
    )


def _overall_state(
    shipment: Shipment,
    packages: list[ShipmentPackage],
    progress: package_service.PackageProgress,
) -> tuple[str, datetime | None]:
    if shipment.booking_state == BookingState.CANCELLED:
        return OperationalState.CANCELLED, None
    if shipment.booking_state == BookingState.DRAFT:
        return OperationalState.BOOKED, None

    active = [package for package in packages if package.is_active]
    if not active:
        # Every package cancelled but the booking is not: honest neutral state rather
        # than a delivered/partial claim about nothing.
        return OperationalState.CANCELLED, None

    delivered = [package for package in active if package.delivered_to_recipient_at is not None]

    if len(delivered) == len(active):
        return OperationalState.DELIVERED, max(
            package.delivered_to_recipient_at for package in delivered
        )
    if delivered:
        # One of three delivered is Partially delivered, never Delivered (AC-7).
        return OperationalState.PARTIALLY_DELIVERED, None

    states = [package.operational_state for package in active]
    for attention in ATTENTION_STATES:
        if attention in states:
            return attention, None
    # Otherwise the shipment is only as far along as its least advanced active package,
    # which is why a warehouse receipt for one parcel does not advance the whole booking.
    least = min(states, key=lambda state: STATE_PROGRESS.get(state, 0))
    return least, None


def _first_handoff(db: Session, shipment_id: int) -> datetime | None:
    """Earliest event that represents real custody, not a booking record."""
    custody_states = (
        OperationalState.RECEIVED_AT_SOLARIS,
        OperationalState.PROCESSING,
        OperationalState.DEPARTED_ORIGIN,
        OperationalState.IN_TRANSIT,
        OperationalState.CUSTOMS_PROCESSING,
        OperationalState.ARRIVED_DESTINATION,
        OperationalState.OUT_FOR_DELIVERY,
        OperationalState.DELIVERED,
    )
    return db.scalar(
        select(ShipmentEvent.occurred_at)
        .where(
            ShipmentEvent.shipment_id == shipment_id,
            ShipmentEvent.is_voided.is_(False),
            ShipmentEvent.operational_state.in_(custody_states),
        )
        .order_by(ShipmentEvent.occurred_at.asc())
        .limit(1)
    )


def timeline(db: Session, shipment_id: int, *, include_voided: bool = False) -> list[ShipmentEvent]:
    conditions = [ShipmentEvent.shipment_id == shipment_id]
    if not include_voided:
        conditions.append(ShipmentEvent.is_voided.is_(False))
    return list(
        db.scalars(
            select(ShipmentEvent)
            .where(*conditions)
            .order_by(ShipmentEvent.occurred_at.desc(), ShipmentEvent.id.desc())
        ).all()
    )


# --- Editing a recorded event (RC-UAT-25 item 6, Ben 2026-10-25) ------------------------------
#
# Staff (Admin and Operations: whoever holds ``tracking:write``, which records and voids) may
# correct an event after it was recorded -- including one already published to the customer.
# The rows are corrected in place so the timeline, the derived status and the customer's view
# all read the corrected values; ``shipment_event_revisions`` keeps what they said before and
# after, and the audit row says who, when and which fields.
#
# The rules that keep it from being a silent rewrite:
#
# * **Publishing does not change.** An edit never publishes or unpublishes: a published event
#   stays published, an internal one stays internal. Telling the customer something new is a
#   new event; withdrawing a published one is a void.
# * **Customer-visible wording follows the publish rules.** A published event's sentence may
#   be changed only to a **standard update** valid for the (new) event type -- the same
#   catalogue and the same check ``record_event`` applies. Own wording already on the event may
#   be kept as it is; it cannot be rewritten in an edit (record a new event to say something
#   new). A retired standard update may be kept unchanged on an event whose type does not
#   change; any other key must be offered for the event type.
# * **No milestone email.** An edit never queues, sends or withdraws a milestone email, even
#   when it changes the type to a later milestone: the customer was emailed (or not) when the
#   event was recorded, and a correction is not news. To email the customer, record the
#   milestone as a new event.
# * **A reason is required**, and every edit is one revision row plus one audit row.

#: The fields an edit may correct, as stored on each row of the recording. ``package_ids`` is
#: the set of packages the recording covers (one row each).
EDITABLE_FIELDS = (
    "event_type",
    "occurred_at",
    "location_label",
    "location_country_code",
    "leg_id",
    "package_ids",
    "internal_detail",
    "public_update_template_key",
    "public_update_text",
    "is_final_recipient_delivery",
)
PUBLIC_FIELDS = ("public_update_template_key", "public_update_text")
OWN_WORDING_LOCKED = (
    "A published update's wording can only be changed to a standard update. To tell the "
    "customer something new, record a new event."
)
NOT_PUBLISHED_NO_WORDING = (
    "This event was not published. Editing does not publish it: record a new event to tell "
    "the customer."
)
NOTHING_CHANGED = "Nothing was changed."


@dataclass(frozen=True)
class EditResult:
    events: list[ShipmentEvent]
    revision: ShipmentEventRevision


def _recording(db: Session, shipment: Shipment, event_ids: list[int]) -> list[ShipmentEvent]:
    """The rows of one recording: same shipment, live, manual, one type, one entry time."""
    if not event_ids:
        raise ValidationError("Choose the event to edit.", field="event_ids")
    rows = list(db.scalars(select(ShipmentEvent).where(ShipmentEvent.id.in_(set(event_ids)))).all())
    if len(rows) != len(set(event_ids)) or any(row.shipment_id != shipment.id for row in rows):
        raise NotFoundError("That event does not belong to this shipment.")
    if any(row.is_voided for row in rows):
        raise ConflictError("A voided event cannot be edited.")
    if any(row.source != EventSource.MANUAL for row in rows):
        raise ConflictError("A provider event cannot be edited; it is corrected at the source.")
    first = rows[0]
    if any(
        (row.event_type, row.recorded_at, row.is_public_update)
        != (first.event_type, first.recorded_at, first.is_public_update)
        for row in rows
    ):
        raise ConflictError("Those rows were not recorded together; edit them one at a time.")
    return sorted(rows, key=lambda row: row.id)


def _snapshot(rows: list[ShipmentEvent]) -> dict[str, Any]:
    first = rows[0]
    return {
        "event_type": first.event_type,
        "occurred_at": as_utc(first.occurred_at).isoformat(),
        "location_label": first.location_label,
        "location_country_code": first.location_country_code,
        "leg_id": first.leg_id,
        "package_ids": sorted(row.package_id for row in rows if row.package_id is not None),
        "internal_detail": first.internal_detail,
        "public_update_template_key": first.public_update_template_key,
        "public_update_text": first.public_update_text,
        "is_final_recipient_delivery": first.is_final_recipient_delivery,
    }


def edit_event(
    db: Session,
    shipment: Shipment,
    payload: dict[str, Any],
    *,
    actor: User | None = None,
    ip_address: str | None = None,
) -> EditResult:
    """Correct one recorded event (all of its package rows). See the rules above."""
    if shipment.booking_state == BookingState.CANCELLED:
        raise ConflictError("This booking is cancelled; its events cannot be edited.")
    reason = collapse_whitespace(payload.get("reason"))
    if not reason:
        raise ValidationError("An edit needs a reason.", field="reason")
    rows = _recording(db, shipment, list(payload.get("event_ids") or []))
    first = rows[0]
    before = _snapshot(rows)
    published = first.is_public_update

    event_type = payload.get("event_type") or first.event_type
    if event_type not in set(ShipmentEventType):
        raise ValidationError(f"Unknown event type '{event_type}'.", field="event_type")
    occurred_at = as_utc(payload.get("occurred_at")) or as_utc(first.occurred_at)
    if occurred_at > utcnow():
        raise ValidationError("An event cannot have occurred in the future.", field="occurred_at")
    try:
        country = normalize_country_code(payload.get("location_country_code"))
    except ValueError as exc:
        raise ValidationError(str(exc), field="location_country_code") from exc

    leg_id = payload.get("leg_id") or None
    if leg_id is not None:
        leg = db.get(ShipmentLeg, leg_id)
        if leg is None or leg.shipment_id != shipment.id:
            raise NotFoundError("That transport leg does not belong to this shipment.")

    template_key = (payload.get("public_update_template_key") or "").strip() or None
    public_text = collapse_whitespace(payload.get("public_update_text"))
    if template_key and public_text:
        raise ValidationError(
            "Choose a standard update or keep the own wording, not both.",
            field="public_update_template_key",
        )
    if not published:
        if template_key or public_text:
            raise ValidationError(NOT_PUBLISHED_NO_WORDING, field="is_public_update")
    else:
        if not template_key and not public_text:
            raise ValidationError(
                "A published event keeps a customer-visible sentence: choose a standard update.",
                field="public_update_template_key",
            )
        if public_text and public_text != first.public_update_text:
            raise ValidationError(OWN_WORDING_LOCKED, field="public_update_text")
        kept_key = template_key == first.public_update_template_key and (
            event_type == first.event_type
        )
        if template_key and not kept_key and not templates.is_valid_for(template_key, event_type):
            raise ValidationError(
                "That standard update is not offered for this event type.",
                field="public_update_template_key",
            )

    is_final = event_type == FINAL_DELIVERY_EVENT

    # Packages: an empty list is "every active package", as when recording.
    requested = [int(value) for value in (payload.get("package_ids") or [])]
    current = {row.package_id: row for row in rows}
    if requested:
        targets: list[int | None] = []
        for package_id in dict.fromkeys(requested):
            package = db.get(ShipmentPackage, package_id)
            if package is None or package.shipment_id != shipment.id:
                raise NotFoundError("That package does not belong to this shipment.")
            if not package.is_active and package_id not in current:
                raise ConflictError("That package is cancelled; it cannot receive new events.")
            targets.append(package_id)
    else:
        active = package_service.active_packages(db, shipment.id)
        targets = [package.id for package in active] if active else [None]

    after = {
        "event_type": event_type,
        "occurred_at": occurred_at.isoformat(),
        "location_label": collapse_whitespace(payload.get("location_label")),
        "location_country_code": country,
        "leg_id": leg_id,
        "package_ids": sorted(value for value in targets if value is not None),
        "internal_detail": (payload.get("internal_detail") or None),
        "public_update_template_key": template_key if published else None,
        "public_update_text": public_text if published else None,
        "is_final_recipient_delivery": is_final,
    }
    if after == before:
        raise ValidationError(NOTHING_CHANGED, field="event_ids")

    def apply(row: ShipmentEvent) -> None:
        row.event_type = event_type
        row.operational_state = EVENT_TYPE_TO_OPERATIONAL_STATE[event_type]
        row.occurred_at = occurred_at
        row.location_label = after["location_label"]
        row.location_country_code = country
        row.leg_id = leg_id
        row.internal_detail = after["internal_detail"]
        row.public_update_template_key = after["public_update_template_key"]
        row.public_update_text = after["public_update_text"]
        row.is_final_recipient_delivery = is_final

    live: list[ShipmentEvent] = []
    for package_id in targets:
        row = current.get(package_id)
        if row is None:
            # A package added by the edit gets its own row of the same recording: the same
            # entry time and author, so the timeline still shows one event.
            row = ShipmentEvent(
                shipment_id=shipment.id,
                package_id=package_id,
                recorded_at=first.recorded_at,
                recorded_by_user_id=first.recorded_by_user_id,
                is_public_update=published,
                source=EventSource.MANUAL,
            )
            db.add(row)
        apply(row)
        live.append(row)
    now = utcnow()
    for package_id, row in current.items():
        if package_id not in targets:
            # A package removed by the edit: its row is voided, never deleted.
            row.is_voided = True
            row.voided_at = now
            row.voided_reason = f"Removed from this event by an edit: {reason}"[:255]
    db.flush()

    # Deliberately no ``notification_service`` call: an edit sends no milestone email.
    recompute_status(db, shipment)

    wording_changed = any(before[field] != after[field] for field in PUBLIC_FIELDS)
    revision = ShipmentEventRevision(
        shipment_id=shipment.id,
        event_ids_before=json.dumps([row.id for row in rows]),
        event_ids_after=json.dumps(sorted(row.id for row in live)),
        before_json=json.dumps(before, ensure_ascii=False, sort_keys=True),
        after_json=json.dumps(after, ensure_ascii=False, sort_keys=True),
        reason=reason[:255],
        was_published=published,
        public_wording_changed=wording_changed and published,
        edited_at=now,
        edited_by_user_id=actor.id if actor else None,
    )
    db.add(revision)
    db.flush()

    changed = [field for field in EDITABLE_FIELDS if before[field] != after[field]]
    # Free text (the internal note, own public wording) is named as changed, never copied:
    # the revision row holds it for staff; the audit row records the change.
    redacted = {"internal_detail", "public_update_text"}
    audit_service.record_audit(
        db,
        action="shipment.event_edit",
        entity_type="shipment",
        entity_id=shipment.id,
        summary=(
            f"Edited a{' published' if published else 'n internal'} {before['event_type']} "
            f"event on {shipment.public_id} ({', '.join(changed)})"
        ),
        actor=actor,
        ip_address=ip_address,
        detail={
            "revision_id": revision.id,
            "event_ids": [row.id for row in rows],
            "was_published": published,
            "public_wording_changed": revision.public_wording_changed,
            "changed_fields": changed,
            "before": {k: v for k, v in before.items() if k not in redacted},
            "after": {k: v for k, v in after.items() if k not in redacted},
            "reason": reason[:255],
        },
    )
    return EditResult(events=live, revision=revision)


def revisions(db: Session, shipment_id: int) -> list[Any]:
    return list(
        db.scalars(
            select(ShipmentEventRevision)
            .where(ShipmentEventRevision.shipment_id == shipment_id)
            .order_by(ShipmentEventRevision.edited_at.desc(), ShipmentEventRevision.id.desc())
        ).all()
    )
