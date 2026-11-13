"""Multi-package records: stable references, measurements, and progress.

Two rules from CRM.md section 7 shape this module.

**Both values are kept.** A package stores what the staff member entered *and* its unit,
plus the canonical centimetre and kilogram values. Nothing is silently rewritten, and a
label can print "12.5 lb" when that is what was weighed.

**References are permanent.** ``SX-VCA-7K9D2M4R8T6W-01`` is allocated once, from the
parent Solaris ID and the package's stable sequence. Cancelling a package, reprinting its
label, or adding a fourth package never changes or reuses an existing reference, and the
sequence is never renumbered.

All arithmetic uses ``Decimal``. Measurements and money are compared and rounded exactly;
binary floats would make ``0.1 + 0.2 != 0.3`` a data-integrity question.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.enums import DimensionUnit, OperationalState, WeightUnit
from app.core.normalization import collapse_whitespace
from app.core.time_utils import utcnow
from app.models import Shipment, ShipmentPackage, User
from app.services import audit_service
from app.services.errors import ConflictError, NotFoundError, ValidationError

CM_PER_INCH = Decimal("2.54")
KG_PER_POUND = Decimal("0.45359237")

DIMENSION_PLACES = Decimal("0.01")
WEIGHT_PLACES = Decimal("0.001")

MAX_PACKAGES_PER_SHIPMENT = 99  # the two-digit reference suffix is the hard limit


@dataclass(frozen=True)
class PackageProgress:
    """Derived package progress; nothing here is a stored counter (DEC-0030)."""

    total: int
    active: int
    cancelled: int
    delivered: int

    @property
    def summary(self) -> str:
        """The "1 of 3 packages delivered" line required by CRM.md section 7."""
        noun = "package" if self.active == 1 else "packages"
        return f"{self.delivered} of {self.active} {noun} delivered"


# --- Measurement conversion ------------------------------------------------


def _to_decimal(value: Any, field: str) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValidationError("Enter a number.", field=field) from exc
    if not amount.is_finite():
        raise ValidationError("Enter a number.", field=field)
    return amount


def to_centimetres(value: Any, unit: str, field: str) -> tuple[Decimal | None, Decimal | None]:
    """Return ``(entered value, canonical centimetres)``.

    A supplied measurement of zero or less is rejected; ``None`` means "not recorded",
    which is a different and legitimate answer.
    """
    entered = _to_decimal(value, field)
    if entered is None:
        return None, None
    if entered <= 0:
        raise ValidationError(
            "A measurement must be greater than zero. Leave it blank if it was not measured.",
            field=field,
        )
    canonical = entered if unit == DimensionUnit.CM else entered * CM_PER_INCH
    return entered.quantize(DIMENSION_PLACES), canonical.quantize(DIMENSION_PLACES)


def to_kilograms(
    value: Any, unit: str, field: str = "weight_value"
) -> tuple[Decimal | None, Decimal | None]:
    entered = _to_decimal(value, field)
    if entered is None:
        return None, None
    if entered <= 0:
        raise ValidationError(
            "A weight must be greater than zero. Leave it blank if it was not weighed.",
            field=field,
        )
    canonical = entered if unit == WeightUnit.KG else entered * KG_PER_POUND
    return entered.quantize(WEIGHT_PLACES), canonical.quantize(WEIGHT_PLACES)


def _validate_unit(value: Any, allowed: type, field: str, default: str) -> str:
    if value is None or value == "":
        return default
    text = str(value).lower()
    if text not in {member.value for member in allowed}:
        raise ValidationError(
            f"Unknown unit '{value}'. Use one of: "
            + ", ".join(sorted(member.value for member in allowed)),
            field=field,
        )
    return text


# --- References ------------------------------------------------------------


def package_reference_for(public_id: str, sequence: int) -> str:
    """``SX-VCA-7K9D2M4R8T6W`` + sequence 1 -> ``SX-VCA-7K9D2M4R8T6W-01``."""
    return f"{public_id}-{sequence:02d}"


def _next_sequence(db: Session, shipment_id: int) -> int:
    """Next free sequence. Cancelled packages still hold theirs, so nothing is reused."""
    highest = db.scalar(
        select(func.max(ShipmentPackage.sequence)).where(ShipmentPackage.shipment_id == shipment_id)
    )
    return int(highest or 0) + 1


def assign_references(db: Session, shipment: Shipment) -> list[ShipmentPackage]:
    """Give every package on a newly confirmed shipment its permanent reference.

    Called once, inside the confirming transaction. A package that already has a
    reference keeps it, so this is safe to call again.
    """
    if not shipment.public_id:
        raise ConflictError("A shipment must have a Solaris ID before package references exist.")
    packages = db.scalars(
        select(ShipmentPackage)
        .where(ShipmentPackage.shipment_id == shipment.id)
        .order_by(ShipmentPackage.sequence)
    ).all()
    for package in packages:
        if not package.package_reference:
            package.package_reference = package_reference_for(shipment.public_id, package.sequence)
    db.flush()
    return list(packages)


# --- Package writes --------------------------------------------------------


def _apply_measurements(package: ShipmentPackage, payload: dict[str, Any]) -> None:
    dimension_unit = _validate_unit(
        payload.get("dimension_unit"), DimensionUnit, "dimension_unit", DimensionUnit.CM
    )
    weight_unit = _validate_unit(
        payload.get("weight_unit"), WeightUnit, "weight_unit", WeightUnit.KG
    )

    package.dimension_unit = dimension_unit
    package.weight_unit = weight_unit
    for axis in ("length", "width", "height"):
        entered, canonical = to_centimetres(
            payload.get(f"{axis}_value"), dimension_unit, f"{axis}_value"
        )
        setattr(package, f"{axis}_value", entered)
        setattr(package, f"{axis}_cm", canonical)
    entered, canonical = to_kilograms(payload.get("weight_value"), weight_unit)
    package.weight_value = entered
    package.weight_kg = canonical


def add_package(
    db: Session,
    shipment: Shipment,
    payload: dict[str, Any],
    *,
    actor: User | None = None,
    sequence: int | None = None,
    ip_address: str | None = None,
) -> ShipmentPackage:
    """Add a package. A confirmed shipment's new package gets its reference immediately."""
    if shipment.booking_state == "cancelled":
        raise ConflictError("Cannot add a package to a cancelled booking.")

    next_sequence = sequence if sequence is not None else _next_sequence(db, shipment.id)
    if next_sequence > MAX_PACKAGES_PER_SHIPMENT:
        raise ValidationError(
            f"A shipment supports at most {MAX_PACKAGES_PER_SHIPMENT} packages.",
            field="packages",
        )

    package = ShipmentPackage(
        shipment_id=shipment.id,
        sequence=next_sequence,
        is_active=True,
        contents_summary=collapse_whitespace(payload.get("contents_summary")),
        handling_note=collapse_whitespace(payload.get("handling_note")),
        warehouse_location=collapse_whitespace(payload.get("warehouse_location")),
        operational_state=OperationalState.BOOKED,
        created_by_user_id=actor.id if actor else None,
    )
    _apply_measurements(package, payload)
    if shipment.public_id:
        package.package_reference = package_reference_for(shipment.public_id, next_sequence)

    db.add(package)
    db.flush()
    refresh_package_count(db, shipment)

    if shipment.public_id:
        audit_service.record_audit(
            db,
            action="package.create",
            entity_type="shipment_package",
            entity_id=package.id,
            summary=f"Added package {package.package_reference} to {shipment.public_id}",
            actor=actor,
            ip_address=ip_address,
            detail={"shipment_id": shipment.id, "sequence": package.sequence},
        )
    return package


def get_package(db: Session, package_id: int) -> ShipmentPackage:
    package = db.get(ShipmentPackage, package_id)
    if package is None:
        raise NotFoundError("That package does not exist.")
    return package


EDITABLE_PACKAGE_FIELDS = {
    "length_value",
    "width_value",
    "height_value",
    "dimension_unit",
    "weight_value",
    "weight_unit",
    "contents_summary",
    "handling_note",
    "warehouse_location",
}


def update_package(
    db: Session,
    package: ShipmentPackage,
    payload: dict[str, Any],
    *,
    actor: User | None = None,
    ip_address: str | None = None,
) -> ShipmentPackage:
    """Edit a package. The reference and sequence are never editable."""
    if not package.is_active:
        raise ConflictError("A cancelled package cannot be edited.")

    measurement_keys = {
        "length_value",
        "width_value",
        "height_value",
        "dimension_unit",
        "weight_value",
        "weight_unit",
    }
    if measurement_keys & payload.keys():
        merged = {
            "dimension_unit": payload.get("dimension_unit", package.dimension_unit),
            "weight_unit": payload.get("weight_unit", package.weight_unit),
            "length_value": payload.get("length_value", package.length_value),
            "width_value": payload.get("width_value", package.width_value),
            "height_value": payload.get("height_value", package.height_value),
            "weight_value": payload.get("weight_value", package.weight_value),
        }
        _apply_measurements(package, merged)

    for field in ("contents_summary", "handling_note", "warehouse_location"):
        if field in payload:
            setattr(package, field, collapse_whitespace(payload[field]))

    db.flush()
    audit_service.record_audit(
        db,
        action="package.update",
        entity_type="shipment_package",
        entity_id=package.id,
        summary=f"Updated package {package.package_reference or package.sequence}",
        actor=actor,
        ip_address=ip_address,
        detail={"fields": sorted(set(payload) & EDITABLE_PACKAGE_FIELDS)},
    )
    return package


def duplicate_package(
    db: Session,
    package: ShipmentPackage,
    *,
    actor: User | None = None,
    ip_address: str | None = None,
) -> ShipmentPackage:
    """Copy a package's measurements into a new one with its own new reference."""
    shipment = db.get(Shipment, package.shipment_id)
    return add_package(
        db,
        shipment,
        {
            "length_value": package.length_value,
            "width_value": package.width_value,
            "height_value": package.height_value,
            "dimension_unit": package.dimension_unit,
            "weight_value": package.weight_value,
            "weight_unit": package.weight_unit,
            "contents_summary": package.contents_summary,
            "handling_note": package.handling_note,
            "warehouse_location": package.warehouse_location,
        },
        actor=actor,
        ip_address=ip_address,
    )


def cancel_package(
    db: Session,
    package: ShipmentPackage,
    *,
    reason: str | None = None,
    actor: User | None = None,
    ip_address: str | None = None,
) -> ShipmentPackage:
    """Cancel a package.

    The reference is retained and never reused, and the package is excluded from active
    counts and from "1 of 3 delivered" progress.
    """
    if not package.is_active:
        raise ConflictError("That package is already cancelled.")
    shipment = db.get(Shipment, package.shipment_id)
    remaining = db.scalar(
        select(func.count(ShipmentPackage.id)).where(
            ShipmentPackage.shipment_id == package.shipment_id,
            ShipmentPackage.is_active.is_(True),
            ShipmentPackage.id != package.id,
        )
    )
    if not remaining and shipment.booking_state == "confirmed":
        raise ConflictError(
            "A confirmed shipment must keep at least one active package. "
            "Cancel the booking instead."
        )

    package.is_active = False
    package.cancelled_at = utcnow()
    package.cancellation_reason = (collapse_whitespace(reason) or "Cancelled by staff")[:255]
    package.operational_state = OperationalState.CANCELLED
    db.flush()
    refresh_package_count(db, shipment)

    audit_service.record_audit(
        db,
        action="package.cancel",
        entity_type="shipment_package",
        entity_id=package.id,
        summary=f"Cancelled package {package.package_reference or package.sequence}",
        actor=actor,
        ip_address=ip_address,
        detail={"reason": package.cancellation_reason, "reference_retained": True},
    )
    return package


def remove_draft_package(
    db: Session,
    package: ShipmentPackage,
    *,
    actor: User | None = None,
) -> None:
    """Delete a package from an unconfirmed draft.

    Only a draft package can be deleted outright, because it has never had a public
    reference. Once confirmed, a package is cancelled instead so its reference survives.
    """
    shipment = db.get(Shipment, package.shipment_id)
    if shipment.booking_state != "draft":
        raise ConflictError(
            "A confirmed shipment's package is cancelled, not deleted, so its reference survives."
        )
    db.delete(package)
    db.flush()
    refresh_package_count(db, shipment)


# --- Derived values --------------------------------------------------------


def active_packages(db: Session, shipment_id: int) -> list[ShipmentPackage]:
    return list(
        db.scalars(
            select(ShipmentPackage)
            .where(ShipmentPackage.shipment_id == shipment_id, ShipmentPackage.is_active.is_(True))
            .order_by(ShipmentPackage.sequence)
        ).all()
    )


def all_packages(db: Session, shipment_id: int) -> list[ShipmentPackage]:
    return list(
        db.scalars(
            select(ShipmentPackage)
            .where(ShipmentPackage.shipment_id == shipment_id)
            .order_by(ShipmentPackage.sequence)
        ).all()
    )


def progress(db: Session, shipment_id: int) -> PackageProgress:
    """Package progress, derived from package rows.

    Cancelled packages are counted separately and never inflate or deflate the delivered
    ratio, so "1 of 3 delivered" stays truthful after a package is cancelled.
    """
    rows = all_packages(db, shipment_id)
    active = [package for package in rows if package.is_active]
    delivered = [package for package in active if package.delivered_to_recipient_at is not None]
    return PackageProgress(
        total=len(rows),
        active=len(active),
        cancelled=len(rows) - len(active),
        delivered=len(delivered),
    )


def position_label(package: ShipmentPackage, active: list[ShipmentPackage]) -> str:
    """The "Package 1 of 3" line, counted over *active* packages."""
    references = [item.id for item in active]
    try:
        index = references.index(package.id) + 1
    except ValueError:
        # A cancelled package keeps its own sequence rather than borrowing a position.
        return f"Package {package.sequence} (cancelled)"
    return f"Package {index} of {len(active)}"


def refresh_package_count(db: Session, shipment: Shipment) -> int:
    """Keep ``shipments.package_count`` aligned with the active package rows."""
    count = db.scalar(
        select(func.count(ShipmentPackage.id)).where(
            ShipmentPackage.shipment_id == shipment.id, ShipmentPackage.is_active.is_(True)
        )
    )
    shipment.package_count = int(count or 0)
    db.flush()
    return shipment.package_count
