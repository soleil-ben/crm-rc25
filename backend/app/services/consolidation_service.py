"""Consolidations: create, fill, book, cancel, and fan a master milestone out to members (13B).

Rules this module enforces, each a line in a test:

* **Membership needs a confirmed, live, Vietnam → Canada shipment.** A draft has no Solaris
  ID yet; a cancelled booking is retired; the launch consolidations are the VCA route
  (OD-43: air, Vietnam → Canada). A shipment rides in at most one open consolidation; the
  database's partial unique index is the guarantee, this module gives the readable refusal.
* **Only an open consolidation changes.** Booking freezes the member list and the master
  weights and stores the chargeable weight the vendor bills, computed with the product's
  divisor and the recorded rounding (``pricing.chargeable_weight``). A booked consolidation
  can be completed or cancelled, not edited.
* **Booking resolves the vendor product through the active tariff's mapping.** No active
  tariff, or a service with no mapping (Sea, UPS), is a refusal that names the reason;
  nothing is priced against a guess.
* **A master milestone is one event per member, through ``event_service.record_event``.**
  Every invariant that function holds (no future time, delivery only by the recipient event,
  public wording needs its flag) holds for inherited events too, and each row carries
  a ``consolidation_event_links`` row so it is distinguishable from a milestone recorded on
  the shipment. A milestone with no stated time repeats on type alone.
  The same master milestone (type and occurred time) is not fanned out twice (directive v2.1
  acceptance test 8).
* **Cancelling releases every member** (their memberships close with the reason) and never
  touches the member shipments' own state or events.

Everything here is staff data. No function in this module is reachable from the public or
Customer Account routers.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.enums import (
    BookingState,
    ConsolidationState,
    RouteGroup,
    ShipmentEventType,
    SolarisService,
    TariffOrigin,
)
from app.core.normalization import collapse_whitespace
from app.core.time_utils import as_utc, utcnow
from app.models import (
    KANGO_VENDOR_KEY,
    Consolidation,
    ConsolidationEventLink,
    ConsolidationMembership,
    ServiceVendorProduct,
    Shipment,
    ShipmentEvent,
    TariffProduct,
    TariffVersion,
    User,
)
from app.pricing import chargeable_weight as cw
from app.pricing.service_mapping import UNMAPPED_SERVICE_REASONS
from app.services import (
    audit_service,
    event_service,
    pricing_method_service,
    tariff_import_service,
)
from app.services.errors import ConflictError, NotFoundError, ValidationError
from app.services.identifier_service import next_consolidation_public_id

#: The route group whose shipments may be consolidated today (OD-43: Vietnam → Canada).
CONSOLIDATABLE_ROUTE_GROUPS = (RouteGroup.VCA,)


def get_consolidation(db: Session, consolidation_id: int) -> Consolidation:
    row = db.get(Consolidation, consolidation_id)
    if row is None:
        raise NotFoundError("That consolidation does not exist.")
    return row


def active_memberships(db: Session, consolidation_id: int) -> list[ConsolidationMembership]:
    return list(
        db.scalars(
            select(ConsolidationMembership)
            .where(
                ConsolidationMembership.consolidation_id == consolidation_id,
                ConsolidationMembership.removed_at.is_(None),
            )
            .order_by(ConsolidationMembership.added_at, ConsolidationMembership.id)
        )
    )


def active_membership_for_shipment(db: Session, shipment_id: int) -> ConsolidationMembership | None:
    return db.scalar(
        select(ConsolidationMembership).where(
            ConsolidationMembership.shipment_id == shipment_id,
            ConsolidationMembership.removed_at.is_(None),
        )
    )


def member_shipments(db: Session, consolidation_id: int) -> list[Shipment]:
    ids = [m.shipment_id for m in active_memberships(db, consolidation_id)]
    if not ids:
        return []
    rows = db.scalars(select(Shipment).where(Shipment.id.in_(ids))).all()
    by_id = {s.id: s for s in rows}
    return [by_id[i] for i in ids if i in by_id]


# --- Create and edit ----------------------------------------------------------------------


def _require_open(consolidation: Consolidation) -> None:
    if consolidation.state != ConsolidationState.OPEN:
        raise ConflictError(
            f"This consolidation is {consolidation.state}; only an open consolidation changes."
        )


def _decimal(value: Any, field: str, *, positive: bool = True) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        number = Decimal(str(value))
    except Exception as error:  # noqa: BLE001 - any unparsable input is the same refusal
        raise ValidationError(f"{field} must be a number.", field=field) from error
    if positive and number <= 0:
        raise ValidationError(f"{field} must be greater than zero.", field=field)
    return number


def create_consolidation(
    db: Session, payload: dict[str, Any], *, actor: User | None, ip_address: str | None = None
) -> Consolidation:
    service = payload.get("solaris_service")
    if service not in set(SolarisService):
        raise ValidationError("Choose a Solaris service.", field="solaris_service")
    origin = payload.get("origin")
    if origin not in set(TariffOrigin):
        raise ValidationError("Choose the origin depot (HCM or HAN).", field="origin")
    vendor = tariff_import_service.get_or_create_vendor(db, KANGO_VENDOR_KEY)
    row = Consolidation(
        public_id=next_consolidation_public_id(db),
        vendor_id=vendor.id,
        solaris_service=service,
        origin=origin,
        vendor_reference=collapse_whitespace(payload.get("vendor_reference")) or None,
        state=ConsolidationState.OPEN,
        actual_weight_kg=_decimal(payload.get("actual_weight_kg"), "actual_weight_kg"),
        length_cm=_decimal(payload.get("length_cm"), "length_cm"),
        width_cm=_decimal(payload.get("width_cm"), "width_cm"),
        height_cm=_decimal(payload.get("height_cm"), "height_cm"),
        carton_count=int(payload.get("carton_count") or 1),
        cutoff_at=as_utc(payload.get("cutoff_at")),
        handed_over_at=as_utc(payload.get("handed_over_at")),
        created_by_user_id=actor.id if actor else None,
        internal_notes=payload.get("internal_notes"),
    )
    if row.carton_count < 1:
        raise ValidationError("A consolidation has at least one carton.", field="carton_count")
    db.add(row)
    db.flush()
    audit_service.record_audit(
        db,
        action="consolidation.create",
        entity_type="consolidation",
        entity_id=row.public_id,
        summary=f"Created consolidation {row.public_id} ({service}, {origin})",
        actor=actor,
        ip_address=ip_address,
        detail={"solaris_service": service, "origin": origin},
    )
    return row


EDITABLE_WHEN_BOOKED = ("vendor_reference", "internal_notes")

EDITABLE_FIELDS = (
    "vendor_reference",
    "actual_weight_kg",
    "length_cm",
    "width_cm",
    "height_cm",
    "carton_count",
    "cutoff_at",
    "handed_over_at",
    "internal_notes",
    "solaris_service",
    "origin",
)


def update_consolidation(
    db: Session,
    consolidation: Consolidation,
    payload: dict[str, Any],
    *,
    actor: User | None,
    ip_address: str | None = None,
) -> Consolidation:
    if consolidation.state == ConsolidationState.BOOKED:
        # The vendor's reference and the notes may be corrected after booking (a typo in an
        # AWB should not cost a cancel-and-rebuild); weights, service and origin are frozen.
        frozen = sorted(
            f for f in payload if f not in EDITABLE_WHEN_BOOKED and payload[f] is not None
        )
        if frozen:
            raise ConflictError(
                "A booked consolidation only accepts corrections to the vendor reference and "
                "notes: " + ", ".join(frozen),
                detail={"fields": frozen},
            )
    else:
        _require_open(consolidation)
    changed: list[str] = []
    for field in EDITABLE_FIELDS:
        if field not in payload:
            continue
        value = payload[field]
        if field in {"actual_weight_kg", "length_cm", "width_cm", "height_cm"}:
            value = _decimal(value, field)
        elif field == "carton_count":
            value = int(value or 1)
            if value < 1:
                raise ValidationError("A consolidation has at least one carton.", field=field)
        elif field in {"cutoff_at", "handed_over_at"}:
            value = as_utc(value)
        elif field == "vendor_reference":
            value = collapse_whitespace(value) or None
        elif field == "solaris_service" and value not in set(SolarisService):
            raise ValidationError("Choose a Solaris service.", field=field)
        elif field == "origin" and value not in set(TariffOrigin):
            raise ValidationError("Choose the origin depot (HCM or HAN).", field=field)
        if getattr(consolidation, field) != value:
            setattr(consolidation, field, value)
            changed.append(field)
    db.flush()
    if changed:
        audit_service.record_audit(
            db,
            action="consolidation.update",
            entity_type="consolidation",
            entity_id=consolidation.public_id,
            summary=f"Updated consolidation {consolidation.public_id}",
            actor=actor,
            ip_address=ip_address,
            detail={"fields": changed},
        )
    return consolidation


# --- Membership --------------------------------------------------------------------------


def add_member(
    db: Session,
    consolidation: Consolidation,
    shipment: Shipment,
    *,
    actor: User | None,
    ip_address: str | None = None,
) -> ConsolidationMembership:
    _require_open(consolidation)
    if shipment.booking_state != BookingState.CONFIRMED:
        raise ConflictError(
            "Only a confirmed booking can join a consolidation; confirm it first.",
            field="shipment_id",
        )
    if shipment.route_group not in CONSOLIDATABLE_ROUTE_GROUPS:
        raise ConflictError(
            "Only Vietnam → Canada shipments are consolidated today (OD-43).",
            field="shipment_id",
        )
    existing = active_membership_for_shipment(db, shipment.id)
    if existing is not None:
        other = db.get(Consolidation, existing.consolidation_id)
        raise ConflictError(
            f"{shipment.public_id} is already in consolidation "
            f"{other.public_id if other else existing.consolidation_id}.",
            field="shipment_id",
        )
    membership = ConsolidationMembership(
        consolidation_id=consolidation.id,
        shipment_id=shipment.id,
        added_at=utcnow(),
        added_by_user_id=actor.id if actor else None,
    )
    db.add(membership)
    try:
        with db.begin_nested():
            db.flush()
    except IntegrityError as error:
        # Two staff added the same shipment at once; the partial unique index decided.
        raise ConflictError(
            f"{shipment.public_id} was just added to another consolidation.", field="shipment_id"
        ) from error
    audit_service.record_audit(
        db,
        action="consolidation.member_add",
        entity_type="consolidation",
        entity_id=consolidation.public_id,
        summary=f"Added {shipment.public_id} to consolidation {consolidation.public_id}",
        actor=actor,
        ip_address=ip_address,
        detail={"shipment_id": shipment.id},
    )
    return membership


def remove_member(
    db: Session,
    consolidation: Consolidation,
    shipment: Shipment,
    *,
    reason: str,
    actor: User | None,
    ip_address: str | None = None,
) -> ConsolidationMembership:
    _require_open(consolidation)
    reason = collapse_whitespace(reason) or ""
    if not reason:
        raise ValidationError("Say why the shipment is being removed.", field="reason")
    membership = db.scalar(
        select(ConsolidationMembership).where(
            ConsolidationMembership.consolidation_id == consolidation.id,
            ConsolidationMembership.shipment_id == shipment.id,
            ConsolidationMembership.removed_at.is_(None),
        )
    )
    if membership is None:
        raise NotFoundError("That shipment is not in this consolidation.")
    membership.removed_at = utcnow()
    membership.removed_by_user_id = actor.id if actor else None
    membership.removal_reason = reason[:255]
    db.flush()
    audit_service.record_audit(
        db,
        action="consolidation.member_remove",
        entity_type="consolidation",
        entity_id=consolidation.public_id,
        summary=f"Removed {shipment.public_id} from consolidation {consolidation.public_id}",
        actor=actor,
        ip_address=ip_address,
        detail={"shipment_id": shipment.id, "reason": reason[:255]},
    )
    return membership


def release_membership_for_cancelled_shipment(
    db: Session, shipment: Shipment, *, actor: User | None
) -> ConsolidationMembership | None:
    """Close the shipment's active membership because the booking was cancelled.

    Allowed in any consolidation state: this is the system recording a fact, not staff
    editing a booked master. The consolidation's own figures are not recomputed; a booked
    master keeps the chargeable weight the vendor billed.
    """
    membership = active_membership_for_shipment(db, shipment.id)
    if membership is None:
        return None
    membership.removed_at = utcnow()
    membership.removed_by_user_id = actor.id if actor else None
    membership.removal_reason = "Booking cancelled"
    db.flush()
    consolidation = db.get(Consolidation, membership.consolidation_id)
    audit_service.record_audit(
        db,
        action="consolidation.member_remove",
        entity_type="consolidation",
        entity_id=consolidation.public_id if consolidation else membership.consolidation_id,
        summary=(
            f"Released {shipment.public_id} from consolidation "
            f"{consolidation.public_id if consolidation else membership.consolidation_id}: "
            "booking cancelled"
        ),
        actor=actor,
        detail={"shipment_id": shipment.id, "reason": "Booking cancelled"},
    )
    return membership


# --- Booking -----------------------------------------------------------------------------


def resolve_vendor_product(
    db: Session, service: str, origin: str
) -> tuple[TariffVersion, TariffProduct]:
    """The active tariff's mapping for a service and origin, or a refusal that says why."""
    version = tariff_import_service.active_version(db, KANGO_VENDOR_KEY)
    if version is None:
        raise ConflictError("No tariff version is active; import and activate one first.")
    mapping = db.scalar(
        select(ServiceVendorProduct).where(
            ServiceVendorProduct.tariff_version_id == version.id,
            ServiceVendorProduct.solaris_service == service,
            ServiceVendorProduct.origin == origin,
        )
    )
    if mapping is None:
        reason = UNMAPPED_SERVICE_REASONS.get(SolarisService(service))
        raise ConflictError(
            reason
            or f"No vendor product is mapped for {service} from {origin} on {version.public_id}.",
            field="solaris_service",
        )
    product = db.get(TariffProduct, mapping.tariff_product_id)
    if product is None:  # pragma: no cover - the FK forbids it
        raise ConflictError("The mapped vendor product no longer exists.")
    return version, product


#: Services the confirmed method prices without a Kango product (Sea vendor rate, UPS and Air
#: Cargo manual).
NO_KANGO_PRODUCT_SERVICES = frozenset(
    {SolarisService.SEA, SolarisService.UPS, SolarisService.AIR_CARGO}
)
NO_PRODUCT_DIVISOR = 6000


def _method_bill_weight(db: Session, consolidation: Consolidation, divisor: int) -> Decimal | None:
    from app.models import ConsolidationCarton  # noqa: PLC0415
    from app.pricing import cost_method as mv  # noqa: PLC0415
    from app.pricing import engine as pe  # noqa: PLC0415

    cartons = db.scalars(
        select(ConsolidationCarton)
        .where(ConsolidationCarton.consolidation_id == consolidation.id)
        .order_by(ConsolidationCarton.sequence)
    ).all()
    master = pe.MasterInput(
        consolidation.actual_weight_kg,
        consolidation.length_cm,
        consolidation.width_cm,
        consolidation.height_cm,
        consolidation.carton_count,
        None,
        tuple(pe.PackageInput(c.weight_kg, c.length_cm, c.width_cm, c.height_cm) for c in cartons),
    )
    rounding = pricing_method_service.get_method_settings(db).vendor_bill_rounding
    return mv.vendor_bill_weight(master, divisor, rounding)[1]


def book_consolidation(
    db: Session,
    consolidation: Consolidation,
    *,
    actor: User | None,
    ip_address: str | None = None,
    now: datetime | None = None,
) -> Consolidation:
    """Hand the master to the vendor: freeze members and weights, store the chargeable weight."""
    _require_open(consolidation)
    members = active_memberships(db, consolidation.id)
    if not members:
        raise ConflictError("A consolidation needs at least one shipment before it is booked.")
    for membership in members:
        member = db.get(Shipment, membership.shipment_id)
        if member is None or member.booking_state != BookingState.CONFIRMED:
            raise ConflictError(
                f"{member.public_id if member else membership.shipment_id} is no longer a "
                "confirmed booking; remove it before booking the consolidation."
            )
    if not consolidation.vendor_reference:
        raise ValidationError(
            "Enter the vendor's booking reference before booking.", field="vendor_reference"
        )
    if consolidation.actual_weight_kg is None:
        raise ValidationError("Enter the master's actual weight.", field="actual_weight_kg")
    confirmed_method = pricing_method_service.uses_confirmed_method(db)
    product: TariffProduct | None
    if confirmed_method and consolidation.solaris_service in NO_KANGO_PRODUCT_SERVICES:
        # Method v0.7 (DEC-0265): Sea is the sea vendor's rate and UPS is manual; neither is
        # priced through a Kango product. Divisor 6000 (Louis, entry 31).
        version = tariff_import_service.active_version(db, KANGO_VENDOR_KEY)
        product, divisor = None, NO_PRODUCT_DIVISOR
    else:
        version, product = resolve_vendor_product(
            db, consolidation.solaris_service, consolidation.origin
        )
        divisor = product.dim_divisor
    weight = cw.chargeable_weight(
        consolidation.actual_weight_kg,
        length_cm=consolidation.length_cm,
        width_cm=consolidation.width_cm,
        height_cm=consolidation.height_cm,
        divisor=divisor,
    )
    chargeable = weight.chargeable_kg
    if confirmed_method:
        # The vendor bill weight of the confirmed method (§6): Kango's rounding of Σ the
        # recorded packages' CW, exactly what the open estimate used (DEC-0265).
        chargeable = _method_bill_weight(db, consolidation, divisor) or chargeable
    now = now or utcnow()
    consolidation.tariff_version_id = version.id if version is not None else None
    consolidation.tariff_product_id = product.id if product is not None else None
    consolidation.dim_divisor = divisor
    consolidation.volumetric_weight_kg = weight.volumetric_kg
    consolidation.chargeable_weight_kg = chargeable
    consolidation.state = ConsolidationState.BOOKED
    consolidation.booked_at = now
    consolidation.booked_by_user_id = actor.id if actor else None
    if consolidation.handed_over_at is None:
        consolidation.handed_over_at = now
    db.flush()
    audit_service.record_audit(
        db,
        action="consolidation.book",
        entity_type="consolidation",
        entity_id=consolidation.public_id,
        summary=(
            f"Booked consolidation {consolidation.public_id} with the vendor: "
            f"{len(members)} shipment(s), {chargeable} kg chargeable"
        ),
        actor=actor,
        ip_address=ip_address,
        detail={
            "member_count": len(members),
            "tariff_version": version.public_id if version is not None else None,
            "vendor_product": product.code if product is not None else None,
            "dim_divisor": divisor,
            "chargeable_weight_kg": str(chargeable),
            "bill_weight_rule": "kango" if confirmed_method else "od50",
            "half_kg_convention_used": weight.used_half_kg_convention,
        },
    )
    return consolidation


def complete_consolidation(
    db: Session, consolidation: Consolidation, *, actor: User | None, ip_address: str | None = None
) -> Consolidation:
    if consolidation.state != ConsolidationState.BOOKED:
        raise ConflictError("Only a booked consolidation can be completed.")
    consolidation.state = ConsolidationState.COMPLETED
    consolidation.completed_at = utcnow()
    db.flush()
    audit_service.record_audit(
        db,
        action="consolidation.complete",
        entity_type="consolidation",
        entity_id=consolidation.public_id,
        summary=f"Completed consolidation {consolidation.public_id}",
        actor=actor,
        ip_address=ip_address,
    )
    return consolidation


def cancel_consolidation(
    db: Session,
    consolidation: Consolidation,
    *,
    reason: str,
    actor: User | None,
    ip_address: str | None = None,
) -> Consolidation:
    """Cancel and release every member. The members' own bookings are untouched."""
    if consolidation.state in {ConsolidationState.COMPLETED, ConsolidationState.CANCELLED}:
        raise ConflictError(f"This consolidation is already {consolidation.state}.")
    reason = collapse_whitespace(reason) or ""
    if not reason:
        raise ValidationError("Say why the consolidation is being cancelled.", field="reason")
    now = utcnow()
    released = 0
    for membership in active_memberships(db, consolidation.id):
        membership.removed_at = now
        membership.removed_by_user_id = actor.id if actor else None
        membership.removal_reason = f"Consolidation cancelled: {reason}"[:255]
        released += 1
    consolidation.state = ConsolidationState.CANCELLED
    consolidation.cancelled_at = now
    consolidation.cancellation_reason = reason[:255]
    db.flush()
    audit_service.record_audit(
        db,
        action="consolidation.cancel",
        entity_type="consolidation",
        entity_id=consolidation.public_id,
        summary=(
            f"Cancelled consolidation {consolidation.public_id}, releasing {released} shipment(s)"
        ),
        actor=actor,
        ip_address=ip_address,
        detail={"released": released, "reason": reason[:255]},
    )
    return consolidation


# --- Master milestones ---------------------------------------------------------------------


def _already_inherited(
    db: Session,
    consolidation_id: int,
    shipment_id: int,
    event_type: str,
    occurred_at: datetime | None,
    *,
    published: bool = False,
) -> bool:
    """Has this consolidation already given this shipment this milestone?

    With a stated time, the same type **and** time is a repeat. With no stated time (the
    staff clicked the milestone again), the same type is a repeat: two clicks of
    "departed origin" are one departure (directive v2.1 acceptance test 8).

    A **published** milestone repeats only a published one (Phase 17 UAT, UAT-MLS-04).
    Recorded first unpublished and then published, the published one is recorded, so the
    customer's page and the milestone email follow it; the notification key still makes the
    milestone notify once.
    """
    conditions = [
        ConsolidationEventLink.consolidation_id == consolidation_id,
        ConsolidationEventLink.shipment_id == shipment_id,
        ShipmentEvent.event_type == event_type,
        ShipmentEvent.is_voided.is_(False),
    ]
    if published:
        conditions.append(ShipmentEvent.is_public_update.is_(True))
    if occurred_at is not None:
        conditions.append(ShipmentEvent.occurred_at == occurred_at)
    return (
        db.scalar(
            select(func.count())
            .select_from(ConsolidationEventLink)
            .join(ShipmentEvent, ShipmentEvent.id == ConsolidationEventLink.event_id)
            .where(*conditions)
        )
        or 0
    ) > 0


def record_master_event(
    db: Session,
    consolidation: Consolidation,
    payload: dict[str, Any],
    *,
    actor: User | None,
    ip_address: str | None = None,
) -> dict[str, Any]:
    """Record one master milestone on every active member shipment.

    Returns a summary: which shipments received it, which were skipped because they
    already carry this milestone from this consolidation, and which were skipped because
    the event service refused (a cancelled member, for instance), with the reason.
    """
    if consolidation.state not in {ConsolidationState.BOOKED, ConsolidationState.OPEN}:
        raise ConflictError(
            f"This consolidation is {consolidation.state}; it no longer carries milestones."
        )
    event_type = payload.get("event_type")
    if event_type not in set(ShipmentEventType):
        raise ValidationError(f"Unknown event type '{event_type}'.", field="event_type")
    if payload.get("package_id") is not None:
        raise ValidationError(
            "A master milestone applies to whole shipments; record a package event on the "
            "shipment itself.",
            field="package_id",
        )
    stated_at = as_utc(payload.get("occurred_at"))
    occurred_at = stated_at or utcnow()
    members = member_shipments(db, consolidation.id)
    if not members:
        raise ConflictError("This consolidation has no shipments to receive the milestone.")

    applied: list[str] = []
    duplicates: list[str] = []
    refused: list[dict[str, str]] = []
    for shipment in members:
        if _already_inherited(
            db,
            consolidation.id,
            shipment.id,
            event_type,
            stated_at,
            published=bool(payload.get("is_public_update")),
        ):
            duplicates.append(shipment.public_id or str(shipment.id))
            continue
        member_payload = dict(payload, occurred_at=occurred_at)
        try:
            with db.begin_nested():
                events = event_service.record_event(
                    db, shipment, member_payload, actor=actor, ip_address=ip_address
                )
                for event in events:
                    db.add(
                        ConsolidationEventLink(
                            event_id=event.id,
                            consolidation_id=consolidation.id,
                            shipment_id=shipment.id,
                        )
                    )
                db.flush()
        except (ConflictError, ValidationError) as error:
            refused.append(
                {"shipment": shipment.public_id or str(shipment.id), "reason": str(error)}
            )
            continue
        applied.append(shipment.public_id or str(shipment.id))

    audit_service.record_audit(
        db,
        action="consolidation.event_record",
        entity_type="consolidation",
        entity_id=consolidation.public_id,
        summary=(
            f"Recorded {event_type} on consolidation {consolidation.public_id}: "
            f"{len(applied)} shipment(s) updated, {len(duplicates)} already had it, "
            f"{len(refused)} refused"
        ),
        actor=actor,
        ip_address=ip_address,
        detail={
            "event_type": event_type,
            "occurred_at": occurred_at.isoformat(),
            "applied": applied,
            "duplicates": duplicates,
            "refused": refused,
        },
    )
    return {
        "event_type": event_type,
        "occurred_at": occurred_at,
        "applied": applied,
        "duplicates": duplicates,
        "refused": refused,
    }
