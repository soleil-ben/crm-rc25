"""Ordered transport legs, package associations, and tracking-reference placeholders.

A leg records how a parcel moves: origin pickup, consolidation or linehaul, destination
handling, final delivery. Carrier references hang off the leg through
``LegTrackingReference`` rather than a single column on the shipment, because CRM.md
section 7 requires one package to be able to carry several sequential carrier numbers and
several packages to share one master reference.

**Nothing here contacts a provider.** Phase 2 accepts a manually typed reference and an
optional validated public carrier link. ``source_mode`` is restricted to ``manual`` and
``external_link``; ``connected_api`` is refused until Phase 4 verifies a real account, so
the interface can never imply that a pasted number is being synchronized
(``docs/INTEGRATIONS.md``).
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.countries import normalize_country_code
from app.core.enums import (
    PHASE_2_TRACKING_SOURCE_MODES,
    LegStatus,
    LegType,
    TrackingSourceMode,
)
from app.core.normalization import collapse_whitespace
from app.core.time_utils import as_utc, utcnow
from app.models import (
    LegTrackingReference,
    Shipment,
    ShipmentLeg,
    ShipmentLegPackage,
    ShipmentPackage,
    User,
)
from app.services import audit_service
from app.services.errors import ConflictError, NotFoundError, ValidationError
from app.services.tariff_import_service import KANGO_VENDOR_NAME

# Carrier names staff may pick. Offering a name never implies an integration exists.
KNOWN_CARRIERS = (
    "UPS",
    "FedEx",
    "Purolator",
    "Canada Post",
    "DHL",
    "USPS",
    "Viettel Post",
    "Vietnam Post",
    "Solaris Express",
    "Other",
)

# The vendor, as staff pick it as a leg's provider (RC-20, owner 2026-10-23). It is
# offered on every leg type, the final delivery leg included; customers never read it
# (they see the generic tracking name of the leg, DEC-0224).
VENDOR_PROVIDER = KANGO_VENDOR_NAME

# The providers the staff leg editor offers for each leg type. Every leg type offers the
# vendor first, then the carrier labels. The stored provider stays free text: this list
# guides the picker, it does not restrict what the API accepts.
LEG_PROVIDERS: dict[str, tuple[str, ...]] = {
    leg_type.value: (VENDOR_PROVIDER, *KNOWN_CARRIERS) for leg_type in LegType
}


def providers_for(leg_type: str | None) -> tuple[str, ...]:
    """The providers offered for ``leg_type`` (an unknown type gets the full list)."""
    return LEG_PROVIDERS.get(str(leg_type or ""), (VENDOR_PROVIDER, *KNOWN_CARRIERS))


def get_leg(db: Session, leg_id: int) -> ShipmentLeg:
    leg = db.get(ShipmentLeg, leg_id)
    if leg is None:
        raise NotFoundError("That transport leg does not exist.")
    return leg


def _next_sequence(db: Session, shipment_id: int) -> int:
    highest = db.scalar(
        select(func.max(ShipmentLeg.sequence)).where(ShipmentLeg.shipment_id == shipment_id)
    )
    return int(highest or 0) + 1


def _country(value: Any, field: str) -> str | None:
    try:
        return normalize_country_code(value)
    except ValueError as exc:
        raise ValidationError(str(exc), field=field) from exc


def _validate_packages(
    db: Session, shipment_id: int, package_ids: list[int]
) -> list[ShipmentPackage]:
    if not package_ids:
        return []
    packages = list(
        db.scalars(
            select(ShipmentPackage).where(
                ShipmentPackage.id.in_(package_ids),
                ShipmentPackage.shipment_id == shipment_id,
            )
        ).all()
    )
    found = {package.id for package in packages}
    missing = [package_id for package_id in package_ids if package_id not in found]
    if missing:
        raise NotFoundError(
            "Some packages do not belong to this shipment.", detail={"package_ids": missing}
        )
    return packages


def create_leg(
    db: Session,
    shipment: Shipment,
    payload: dict[str, Any],
    *,
    actor: User | None = None,
    ip_address: str | None = None,
) -> ShipmentLeg:
    leg_type = payload.get("leg_type")
    if leg_type not in set(LegType):
        raise ValidationError(f"Unknown leg type '{leg_type}'.", field="leg_type")

    leg = ShipmentLeg(
        shipment_id=shipment.id,
        sequence=payload.get("sequence") or _next_sequence(db, shipment.id),
        leg_type=leg_type,
        provider_name=collapse_whitespace(payload.get("provider_name")),
        service_display=collapse_whitespace(payload.get("service_display")),
        origin_label=collapse_whitespace(payload.get("origin_label")),
        origin_country_code=_country(payload.get("origin_country_code"), "origin_country_code"),
        destination_label=collapse_whitespace(payload.get("destination_label")),
        destination_country_code=_country(
            payload.get("destination_country_code"), "destination_country_code"
        ),
        is_final_recipient_delivery=bool(payload.get("is_final_recipient_delivery")),
        consolidation_reference=collapse_whitespace(payload.get("consolidation_reference")),
        status=payload.get("status") or LegStatus.PLANNED,
        scheduled_at=as_utc(payload.get("scheduled_at")),
        internal_notes=payload.get("internal_notes"),
        created_by_user_id=actor.id if actor else None,
    )
    if leg.status not in set(LegStatus):
        raise ValidationError(f"Unknown leg status '{leg.status}'.", field="status")

    db.add(leg)
    db.flush()

    set_leg_packages(db, leg, payload.get("package_ids") or [])

    audit_service.record_audit(
        db,
        action="shipment.leg_create",
        entity_type="shipment",
        entity_id=shipment.id,
        summary=f"Added {leg_type} leg to {shipment.public_id or 'draft booking'}",
        actor=actor,
        ip_address=ip_address,
        detail={"leg_id": leg.id, "provider": leg.provider_name, "sequence": leg.sequence},
    )
    return leg


def update_leg(
    db: Session,
    leg: ShipmentLeg,
    payload: dict[str, Any],
    *,
    actor: User | None = None,
    ip_address: str | None = None,
) -> ShipmentLeg:
    for field in (
        "provider_name",
        "service_display",
        "origin_label",
        "destination_label",
        "consolidation_reference",
    ):
        if field in payload:
            setattr(leg, field, collapse_whitespace(payload[field]))
    if "origin_country_code" in payload:
        leg.origin_country_code = _country(payload["origin_country_code"], "origin_country_code")
    if "destination_country_code" in payload:
        leg.destination_country_code = _country(
            payload["destination_country_code"], "destination_country_code"
        )
    if "is_final_recipient_delivery" in payload:
        leg.is_final_recipient_delivery = bool(payload["is_final_recipient_delivery"])
    if "internal_notes" in payload:
        leg.internal_notes = payload["internal_notes"]
    if "scheduled_at" in payload:
        leg.scheduled_at = as_utc(payload["scheduled_at"])
    if "status" in payload and payload["status"] is not None:
        if payload["status"] not in set(LegStatus):
            raise ValidationError(f"Unknown leg status '{payload['status']}'.", field="status")
        leg.status = payload["status"]
        leg.completed_at = utcnow() if leg.status == LegStatus.COMPLETED else None
    if "sequence" in payload and payload["sequence"]:
        leg.sequence = int(payload["sequence"])

    if payload.get("package_ids") is not None:
        set_leg_packages(db, leg, payload["package_ids"])

    db.flush()
    audit_service.record_audit(
        db,
        action="shipment.leg_update",
        entity_type="shipment",
        entity_id=leg.shipment_id,
        summary=f"Updated {leg.leg_type} leg",
        actor=actor,
        ip_address=ip_address,
        detail={"leg_id": leg.id, "fields": sorted(payload.keys())},
    )
    return leg


def set_leg_packages(db: Session, leg: ShipmentLeg, package_ids: list[int]) -> None:
    """Replace the leg's package associations.

    Reads the association rows directly rather than through ``leg.package_links``: the
    relationship may already be loaded and stale, and acting on a stale collection would
    re-insert a link that already exists.
    """
    packages = _validate_packages(db, leg.shipment_id, package_ids)
    existing = {
        link.package_id: link
        for link in db.scalars(
            select(ShipmentLegPackage).where(ShipmentLegPackage.leg_id == leg.id)
        ).all()
    }
    wanted = {package.id for package in packages}

    for package_id, link in existing.items():
        if package_id not in wanted:
            db.delete(link)
    for package in packages:
        if package.id not in existing:
            db.add(ShipmentLegPackage(leg_id=leg.id, package_id=package.id))
    db.flush()
    db.expire(leg, ["package_links"])


def delete_leg(
    db: Session,
    leg: ShipmentLeg,
    *,
    actor: User | None = None,
    ip_address: str | None = None,
) -> None:
    if any(reference.is_active for reference in leg.tracking_references):
        raise ConflictError(
            "Retire the leg's active tracking references before removing it, so the "
            "carrier history is not lost."
        )
    shipment_id = leg.shipment_id
    leg_type = leg.leg_type
    db.delete(leg)
    db.flush()
    audit_service.record_audit(
        db,
        action="shipment.leg_delete",
        entity_type="shipment",
        entity_id=shipment_id,
        summary=f"Removed {leg_type} leg",
        actor=actor,
        ip_address=ip_address,
    )


# --- Tracking reference placeholders --------------------------------------


def _validate_public_url(value: str | None) -> str | None:
    """Accept an https carrier link, or nothing.

    The link is stored and displayed; it is never fetched. Phase 4 is where a provider is
    actually contacted, behind an allowlist.
    """
    cleaned = collapse_whitespace(value)
    if not cleaned:
        return None
    parsed = urlparse(cleaned)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValidationError(
            "Enter a full carrier tracking link starting with https://.", field="public_url"
        )
    if parsed.scheme == "http":
        raise ValidationError("Use an https carrier link.", field="public_url")
    host = parsed.hostname or ""
    if host in {"localhost", "127.0.0.1", "::1"} or host.endswith(".local"):
        raise ValidationError("That is not a public carrier link.", field="public_url")
    return cleaned[:500]


def add_tracking_reference(
    db: Session,
    leg: ShipmentLeg,
    payload: dict[str, Any],
    *,
    actor: User | None = None,
    ip_address: str | None = None,
) -> LegTrackingReference:
    """Record a carrier tracking reference. No provider call is made.

    The Solaris Shipment ID is untouched by this: assigning, changing, or retiring a
    carrier number never alters the Solaris ID or a package reference (AC-6).
    """
    carrier = collapse_whitespace(payload.get("carrier_name"))
    number = collapse_whitespace(payload.get("tracking_number"))
    if not carrier:
        raise ValidationError("Choose a carrier.", field="carrier_name")
    if not number:
        raise ValidationError("Enter the carrier tracking number.", field="tracking_number")

    mode = payload.get("source_mode") or TrackingSourceMode.MANUAL
    if mode not in PHASE_2_TRACKING_SOURCE_MODES:
        raise ValidationError(
            "Only manual and external-link tracking are available. No provider account "
            "is connected, so nothing can be synchronized automatically.",
            field="source_mode",
            detail={"available": [value.value for value in PHASE_2_TRACKING_SOURCE_MODES]},
        )

    package_id = payload.get("package_id")
    if package_id is not None:
        _validate_packages(db, leg.shipment_id, [package_id])

    reference = LegTrackingReference(
        leg_id=leg.id,
        package_id=package_id,
        carrier_name=carrier[:80],
        tracking_number=number[:120],
        public_url=_validate_public_url(payload.get("public_url")),
        source_mode=mode,
        is_active=True,
        created_by_user_id=actor.id if actor else None,
    )
    db.add(reference)
    db.flush()

    audit_service.record_audit(
        db,
        action="shipment.tracking_reference_add",
        entity_type="shipment",
        entity_id=leg.shipment_id,
        summary=f"Recorded {carrier} reference on a {leg.leg_type} leg",
        actor=actor,
        ip_address=ip_address,
        detail={
            "leg_id": leg.id,
            "reference_id": reference.id,
            "carrier_name": carrier,
            "source_mode": mode,
            "package_id": package_id,
        },
    )
    return reference


def retire_tracking_reference(
    db: Session,
    reference: LegTrackingReference,
    *,
    reason: str,
    actor: User | None = None,
    ip_address: str | None = None,
) -> LegTrackingReference:
    """Mark a carrier reference retired. The row is preserved, never overwritten."""
    cleaned = collapse_whitespace(reason)
    if not cleaned:
        raise ValidationError("Say why the reference is being retired.", field="reason")
    if not reference.is_active:
        raise ConflictError("That tracking reference is already retired.")

    reference.is_active = False
    reference.retired_at = utcnow()
    reference.retired_reason = cleaned[:255]
    db.flush()

    audit_service.record_audit(
        db,
        action="shipment.tracking_reference_retire",
        entity_type="shipment",
        entity_id=reference.leg.shipment_id,
        summary=f"Retired a {reference.carrier_name} reference",
        actor=actor,
        ip_address=ip_address,
        detail={"reference_id": reference.id, "reason": cleaned[:255]},
    )
    return reference


def get_tracking_reference(db: Session, reference_id: int) -> LegTrackingReference:
    reference = db.get(LegTrackingReference, reference_id)
    if reference is None:
        raise NotFoundError("That tracking reference does not exist.")
    return reference


def legs_for(db: Session, shipment_id: int) -> list[ShipmentLeg]:
    return list(
        db.scalars(
            select(ShipmentLeg)
            .where(ShipmentLeg.shipment_id == shipment_id)
            .order_by(ShipmentLeg.sequence)
        ).all()
    )
