"""Commodity line items on a customer shipment (Phase 13B).

A shipment carries any number of items (handoff owner decision 4: unlimited commodity
items). An item is a description with a quantity and unit, optionally a weight, a declared
value and the package it travels in. Nothing here charges a fee: Phase 13C attaches
surcharge rules to items explicitly, through the fee picker, never from a keyword.

Items can be edited while the shipment is a draft or confirmed; a cancelled booking is
read-only, and once the shipment's master is booked they are locked (owner decision 8)
unless an Admin unlocked it. Removing an item deactivates it rather than deleting it, so a
quotation that referenced it keeps its meaning.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.enums import BookingState
from app.core.normalization import collapse_whitespace
from app.models import Shipment, ShipmentItem, ShipmentPackage, User
from app.services import audit_service, master_lock_service
from app.services.errors import ConflictError, NotFoundError, ValidationError

ALLOWED_UNITS = ("piece", "pair", "box", "bottle", "set", "kg", "carton", "other")


def list_items(
    db: Session, shipment_id: int, *, include_inactive: bool = False
) -> list[ShipmentItem]:
    query = select(ShipmentItem).where(ShipmentItem.shipment_id == shipment_id)
    if not include_inactive:
        query = query.where(ShipmentItem.is_active.is_(True))
    return list(db.scalars(query.order_by(ShipmentItem.sequence)))


def _require_editable(db: Session, shipment: Shipment):
    """Refuse a change to a cancelled booking's items, or to a booked master's (owner
    decision 8: locked once booked, unless an Admin unlocked it). Returns the open unlock
    the change is made under, if any, for the audit row."""
    if shipment.booking_state == BookingState.CANCELLED:
        raise ConflictError("This booking is cancelled; its items are read-only.")
    return master_lock_service.require_editable(db, shipment)


#: Stored precision per field (the Numeric scale of the column), so what is kept in memory
#: equals what SQLite gives back.
_SCALE = {
    "quantity": Decimal("0.01"),
    "weight_kg": Decimal("0.001"),
    "declared_value": Decimal("0.01"),
}


def _decimal(value: Any, field: str, *, allow_zero: bool = False) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        number = Decimal(str(value))
    except Exception as error:  # noqa: BLE001
        raise ValidationError(f"{field} must be a number.", field=field) from error
    if number < 0 or (number == 0 and not allow_zero):
        raise ValidationError(f"{field} must be greater than zero.", field=field)
    scale = _SCALE.get(field)
    return number.quantize(scale, rounding=ROUND_HALF_UP) if scale else number


def _currency(value: Any) -> str | None:
    cleaned = collapse_whitespace(value) if isinstance(value, str) else None
    if not cleaned:
        return None
    if len(cleaned) != 3 or not cleaned.isalpha():
        raise ValidationError(
            "Use a three-letter currency code such as CAD.", field="declared_value_currency"
        )
    return cleaned.upper()


def _package(db: Session, shipment: Shipment, package_id: int | None) -> ShipmentPackage | None:
    if package_id is None:
        return None
    package = db.get(ShipmentPackage, package_id)
    if package is None or package.shipment_id != shipment.id:
        raise NotFoundError("That package does not belong to this shipment.")
    return package


def add_item(
    db: Session,
    shipment: Shipment,
    payload: dict[str, Any],
    *,
    actor: User | None,
    ip_address: str | None = None,
) -> ShipmentItem:
    unlock = _require_editable(db, shipment)
    description = collapse_whitespace(payload.get("description")) or ""
    if not description:
        raise ValidationError("Describe the item.", field="description")
    unit = (payload.get("unit") or "piece").strip().lower()
    if unit not in ALLOWED_UNITS:
        raise ValidationError(f"Unit must be one of {', '.join(ALLOWED_UNITS)}.", field="unit")
    quantity = _decimal(payload.get("quantity", 1), "quantity") or Decimal(1)
    package = _package(db, shipment, payload.get("package_id"))
    next_sequence = (
        db.scalar(
            select(func.coalesce(func.max(ShipmentItem.sequence), 0)).where(
                ShipmentItem.shipment_id == shipment.id
            )
        )
        or 0
    ) + 1
    item = ShipmentItem(
        shipment_id=shipment.id,
        sequence=next_sequence,
        description=description[:300],
        quantity=quantity,
        unit=unit,
        weight_kg=_decimal(payload.get("weight_kg"), "weight_kg"),
        declared_value=_decimal(payload.get("declared_value"), "declared_value", allow_zero=True),
        declared_value_currency=_currency(payload.get("declared_value_currency")),
        package_id=package.id if package else None,
        notes=collapse_whitespace(payload.get("notes")) or None,
    )
    db.add(item)
    db.flush()
    audit_service.record_audit(
        db,
        action="shipment.item_add",
        entity_type="shipment",
        entity_id=shipment.id,
        summary=f"Added item {item.sequence} to {shipment.public_id or 'draft booking'}",
        actor=actor,
        ip_address=ip_address,
        detail={
            "item_id": item.id,
            "sequence": item.sequence,
            **master_lock_service.audit_detail(unlock),
        },
    )
    return item


EDITABLE = (
    "description",
    "quantity",
    "unit",
    "weight_kg",
    "declared_value",
    "declared_value_currency",
    "package_id",
    "notes",
)


def update_item(
    db: Session,
    shipment: Shipment,
    item: ShipmentItem,
    payload: dict[str, Any],
    *,
    actor: User | None,
    ip_address: str | None = None,
) -> ShipmentItem:
    unlock = _require_editable(db, shipment)
    if item.shipment_id != shipment.id:
        raise NotFoundError("That item does not belong to this shipment.")
    if not item.is_active:
        raise ConflictError("That item was removed; add a new one instead.")
    changed: list[str] = []
    for field in EDITABLE:
        if field not in payload:
            continue
        value = payload[field]
        if field == "description":
            value = collapse_whitespace(value) or ""
            if not value:
                raise ValidationError("Describe the item.", field=field)
            value = value[:300]
        elif field == "quantity":
            value = _decimal(value, field) or Decimal(1)
        elif field == "unit":
            value = (value or "piece").strip().lower()
            if value not in ALLOWED_UNITS:
                raise ValidationError(
                    f"Unit must be one of {', '.join(ALLOWED_UNITS)}.", field=field
                )
        elif field == "weight_kg":
            value = _decimal(value, field)
        elif field == "declared_value":
            value = _decimal(value, field, allow_zero=True)
        elif field == "declared_value_currency":
            value = _currency(value)
        elif field == "package_id":
            package = _package(db, shipment, value)
            value = package.id if package else None
        elif field == "notes":
            value = collapse_whitespace(value) or None
        if getattr(item, field) != value:
            setattr(item, field, value)
            changed.append(field)
    db.flush()
    if changed:
        audit_service.record_audit(
            db,
            action="shipment.item_update",
            entity_type="shipment",
            entity_id=shipment.id,
            summary=f"Updated item {item.sequence} on {shipment.public_id or 'draft booking'}",
            actor=actor,
            ip_address=ip_address,
            detail={
                "item_id": item.id,
                "fields": changed,
                **master_lock_service.audit_detail(unlock),
            },
        )
    return item


def remove_item(
    db: Session,
    shipment: Shipment,
    item: ShipmentItem,
    *,
    actor: User | None,
    ip_address: str | None = None,
) -> ShipmentItem:
    unlock = _require_editable(db, shipment)
    if item.shipment_id != shipment.id:
        raise NotFoundError("That item does not belong to this shipment.")
    if not item.is_active:
        return item
    item.is_active = False
    db.flush()
    audit_service.record_audit(
        db,
        action="shipment.item_remove",
        entity_type="shipment",
        entity_id=shipment.id,
        summary=f"Removed item {item.sequence} from {shipment.public_id or 'draft booking'}",
        actor=actor,
        ip_address=ip_address,
        detail={"item_id": item.id, **master_lock_service.audit_detail(unlock)},
    )
    return item
