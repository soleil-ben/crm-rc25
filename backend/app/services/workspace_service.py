"""Workspace redesign (owner, 2026-11-04; DEC-0272).

The workspace follows the owner's order: master (tracking, origin, service) → master piece →
the customers inside it. Two things the old screens could not do:

* **Last-mile tracking per piece** (optional, may repeat): ``set_piece_tracking``.
* **Add a customer from the workspace**: ``add_customer`` books the customer's shipment
  (draft → confirmed, through ``booking_service`` so every booking rule still applies), joins
  it to the master and places it in its piece, in **one** unit of work. If any step is
  refused nothing is kept, so a half-filled form never leaves a draft behind.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.enums import ConsolidationState, RouteGroup, SolarisService, TransportMode
from app.core.time_utils import utcnow
from app.models import (
    Consolidation,
    ConsolidationPieceTracking,
    Shipment,
    ShipmentPackage,
    User,
)
from app.services import (
    audit_service,
    booking_service,
    consolidation_service,
    master_lock_service,
    package_service,
    pricing_method_service,
    pricing_service,
    shipment_item_service,
)
from app.services.errors import ConflictError, NotFoundError, ValidationError

TRACKING_MAX = 60


def piece_tracking(db: Session, consolidation_id: int) -> dict[int, str]:
    rows = db.scalars(
        select(ConsolidationPieceTracking).where(
            ConsolidationPieceTracking.consolidation_id == consolidation_id
        )
    )
    return {row.carton_sequence: row.last_mile_tracking for row in rows}


def set_piece_tracking(
    db: Session,
    consolidation: Consolidation,
    carton_sequence: int,
    value: str | None,
    *,
    actor: User | None,
) -> None:
    """Set (or, with an empty value, clear) one piece's last-mile tracking. Allowed until the
    master is cancelled: tracking often arrives after booking."""
    if consolidation.state == ConsolidationState.CANCELLED:
        raise ConflictError("This master is cancelled.")
    if int(carton_sequence) < 1:
        raise ValidationError("The piece number starts at 1.", field="carton_sequence")
    text = (value or "").strip() or None
    if text is not None and len(text) > TRACKING_MAX:
        raise ValidationError(
            f"A tracking number is at most {TRACKING_MAX} characters.", field="last_mile_tracking"
        )
    row = db.scalar(
        select(ConsolidationPieceTracking).where(
            ConsolidationPieceTracking.consolidation_id == consolidation.id,
            ConsolidationPieceTracking.carton_sequence == int(carton_sequence),
        )
    )
    before = row.last_mile_tracking if row is not None else None
    if text is None:
        if row is not None:
            db.delete(row)
    else:
        if row is None:
            row = ConsolidationPieceTracking(
                consolidation_id=consolidation.id, carton_sequence=int(carton_sequence)
            )
            db.add(row)
        row.last_mile_tracking = text
        row.updated_at = utcnow()
        row.updated_by_user_id = actor.id if actor else None
    db.flush()
    if before != text:
        audit_service.record_audit(
            db,
            action="consolidation.piece_tracking_set",
            entity_type="consolidation",
            entity_id=consolidation.id,
            summary=f"Piece {carton_sequence} last-mile tracking set",
            actor=actor,
            detail={"carton_sequence": int(carton_sequence), "from": before, "to": text},
        )


def _transport_mode(service: str) -> str:
    return TransportMode.OCEAN if service == SolarisService.SEA else TransportMode.AIR


def add_customer(
    db: Session,
    consolidation: Consolidation,
    payload: dict[str, Any],
    *,
    actor: User | None,
    ip_address: str | None = None,
) -> Shipment:
    """Book a customer's shipment from the workspace and put it in a piece of this master.

    ``payload``: ``customer_id``; ``carton_sequence`` (the piece; optional); ``reference_code``
    (optional, kept as the booking reference); ``weight_kg`` and optional ``length_cm`` /
    ``width_cm`` / ``height_cm`` (one package); ``items`` (at least one: ``description``,
    optional ``quantity`` / ``unit`` / ``weight_kg``); ``sender`` and ``recipient`` (a saved
    address id and/or typed lines, as the booking form takes them).

    The booking's contents description is built from the item names (owner, 2026-11-05: the
    item list already says what is inside; no separate "contents" field). An explicit
    ``contents_description`` is still accepted.
    """
    if consolidation.state != ConsolidationState.OPEN:
        raise ConflictError("Customers can only be added to an open master.")
    sequence = payload.get("carton_sequence")
    if sequence is not None:
        pieces = pricing_service.list_cartons(db, consolidation.id)
        known = {c.sequence for c in pieces} or {1}
        if int(sequence) not in known:
            raise ValidationError(
                f"Piece {sequence} does not exist on this master.", field="carton_sequence"
            )
    weight = payload.get("weight_kg")
    if weight is None or Decimal(str(weight)) <= 0:
        raise ValidationError("Enter the customer's weight.", field="weight_kg")
    items = [i for i in payload.get("items") or [] if (i.get("description") or "").strip()]
    contents = (payload.get("contents_description") or "").strip() or contents_from_items(items)
    if not contents:
        raise ValidationError("Add at least one item.", field="items")
    package = {
        "weight_value": Decimal(str(weight)),
        "weight_unit": "kg",
        "length_value": payload.get("length_cm"),
        "width_value": payload.get("width_cm"),
        "height_value": payload.get("height_cm"),
        "dimension_unit": "cm",
    }
    draft = booking_service.create_draft(
        db,
        {
            "customer_id": payload["customer_id"],
            "route_group": RouteGroup.VCA,
            "transport_mode": _transport_mode(consolidation.solaris_service),
            "booking_reference": (payload.get("reference_code") or "").strip() or None,
            "contents_description": contents,
            "sender": payload.get("sender"),
            "recipient": payload.get("recipient"),
            "packages": [{k: v for k, v in package.items() if v is not None}],
        },
        actor=actor,
        ip_address=ip_address,
    )
    db.flush()
    confirmed = booking_service.confirm_booking(
        db,
        shipment_id=draft.id,
        idempotency_key=f"workspace-{consolidation.id}-{uuid.uuid4().hex}",
        actor=actor,
        ip_address=ip_address,
    ).shipment
    consolidation_service.add_member(
        db, consolidation, confirmed, actor=actor, ip_address=ip_address
    )
    if sequence is not None:
        pricing_method_service.set_package_member(
            db, consolidation.id, confirmed.id, int(sequence), actor=actor
        )
    for item in items:
        shipment_item_service.add_item(db, confirmed, item, actor=actor, ip_address=ip_address)
    db.flush()
    return confirmed


CONTENTS_MAX = 400


def contents_from_items(items: list[dict[str, Any]]) -> str:
    """ "Clothes ×3, Lipstick ×2" -- the booking's contents line, from the item list."""
    parts = []
    for item in items:
        name = " ".join(str(item.get("description") or "").split())
        if not name:
            continue
        quantity = item.get("quantity")
        qty = Decimal(str(quantity)) if quantity not in (None, "") else Decimal(1)
        parts.append(name if qty == 1 else f"{name} ×{qty.normalize():f}")
    text = ", ".join(parts)
    return text if len(text) <= CONTENTS_MAX else text[: CONTENTS_MAX - 1] + "…"


def update_customer(
    db: Session,
    consolidation: Consolidation,
    shipment: Shipment,
    payload: dict[str, Any],
    *,
    actor: User | None,
    ip_address: str | None = None,
) -> Shipment:
    """Edit a customer's details from the workspace (owner, 2026-11-05): reference code,
    weight and dimensions of its package, and the piece it rides in.

    Weights move the cost split, so they follow the master lock (owner decision 8): refused
    on a booked master unless an Admin unlocked it. The reference is a label, editable while
    the master is not cancelled. Sender and recipient lock with the booking (CRM.md §6).
    """
    membership = consolidation_service.active_membership_for_shipment(db, shipment.id)
    if membership is None or membership.consolidation_id != consolidation.id:
        raise NotFoundError("That shipment is not in this master.")
    if consolidation.state == ConsolidationState.CANCELLED:
        raise ConflictError("This master is cancelled.")
    if "reference_code" in payload:
        booking_service.update_shipment(
            db,
            shipment,
            {"booking_reference": (payload.get("reference_code") or "").strip() or None},
            actor=actor,
            ip_address=ip_address,
        )
    measures = {
        key: payload[key]
        for key in ("weight_kg", "length_cm", "width_cm", "height_cm")
        if key in payload
    }
    if measures or "carton_sequence" in payload:
        master_lock_service.require_editable(db, shipment)
    if measures:
        packages = [
            p
            for p in db.scalars(
                select(ShipmentPackage)
                .where(ShipmentPackage.shipment_id == shipment.id)
                .order_by(ShipmentPackage.id)
            )
            if p.is_active
        ]
        if len(packages) != 1:
            raise ConflictError(
                "This booking has several packages; edit them on the shipment page.",
                field="weight_kg",
            )
        if "weight_kg" in measures and (
            measures["weight_kg"] is None or Decimal(str(measures["weight_kg"])) <= 0
        ):
            raise ValidationError("Enter the customer's weight.", field="weight_kg")
        names = {"weight_kg": "weight_value", "length_cm": "length_value",
                 "width_cm": "width_value", "height_cm": "height_value"}  # fmt: skip
        update = {names[k]: v for k, v in measures.items()}
        if "weight_value" in update:
            update["weight_unit"] = "kg"
        if {"length_value", "width_value", "height_value"} & update.keys():
            update["dimension_unit"] = "cm"
        package_service.update_package(db, packages[0], update, actor=actor, ip_address=ip_address)
    if "carton_sequence" in payload:
        sequence = payload.get("carton_sequence")
        if sequence is not None:
            pieces = pricing_service.list_cartons(db, consolidation.id)
            known = {c.sequence for c in pieces} or {1}
            if int(sequence) not in known:
                raise ValidationError(
                    f"Piece {sequence} does not exist on this master.", field="carton_sequence"
                )
        pricing_method_service.set_package_member(
            db, consolidation.id, shipment.id, sequence, actor=actor
        )
    db.flush()
    return shipment
