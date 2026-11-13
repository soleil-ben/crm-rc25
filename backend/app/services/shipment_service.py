"""Shipment listing, filtering, and identifier lookup.

Kept separate from ``booking_service`` so the read path has no way to mutate state.

The reference lookup is what the internal barcode search calls. Scanning a package
barcode and scanning the parent Solaris ID both resolve to the same shipment; the package
scan additionally identifies which package was scanned (CRM.md section 6).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import Session

from app.core.enums import EXCEPTION_OPERATIONAL_STATES, BookingState, OperationalState
from app.models import Customer, Shipment, ShipmentPackage

# A scanner types the identifier and presses Enter, so normalization has to survive
# stray spaces, lowercase, and the occasional pasted zero-width character.
_NOISE = re.compile(r"[\s​–—]+")


@dataclass(frozen=True)
class ReferenceMatch:
    shipment: Shipment
    package: ShipmentPackage | None
    matched_value: str
    kind: str  # "shipment" or "package"


def normalize_reference(value: str) -> str:
    """Uppercase, strip noise, and normalize dashes without loosening validation."""
    cleaned = _NOISE.sub("", value or "").upper()
    return cleaned.replace("‐", "-").replace("_", "-")


def lookup_reference(db: Session, value: str) -> ReferenceMatch | None:
    """Exact lookup of a Solaris Shipment ID or a package reference.

    Exact only: a partial identifier must not fan out into other customers' shipments.
    """
    reference = normalize_reference(value)
    if not reference:
        return None

    package = db.scalar(
        select(ShipmentPackage).where(ShipmentPackage.package_reference == reference)
    )
    if package is not None:
        shipment = db.get(Shipment, package.shipment_id)
        if shipment is not None:
            return ReferenceMatch(
                shipment=shipment, package=package, matched_value=reference, kind="package"
            )

    shipment = db.scalar(select(Shipment).where(Shipment.public_id == reference))
    if shipment is not None:
        return ReferenceMatch(
            shipment=shipment, package=None, matched_value=reference, kind="shipment"
        )
    return None


def search_shipments(db: Session, term: str, limit: int = 8) -> list[Shipment]:
    """Top-bar search: exact identifier first, then partial ID and customer name."""
    cleaned = (term or "").strip()
    if not cleaned:
        return []

    results: list[Shipment] = []
    exact = lookup_reference(db, cleaned)
    if exact is not None:
        results.append(exact.shipment)

    like = f"%{normalize_reference(cleaned)}%"
    name_like = f"%{cleaned.lower()}%"
    rows = db.scalars(
        select(Shipment)
        .join(Customer, Customer.id == Shipment.customer_id)
        .where(
            or_(
                Shipment.public_id.like(like),
                Shipment.booking_reference.like(like),
                func.lower(Shipment.recipient_name).like(name_like),
                func.lower(Customer.full_name).like(name_like),
            )
        )
        .order_by(Shipment.booking_date.desc().nullslast(), Shipment.id.desc())
        .limit(limit * 2)
    ).all()
    seen = {shipment.id for shipment in results}
    for shipment in rows:
        if shipment.id not in seen:
            results.append(shipment)
            seen.add(shipment.id)
        if len(results) >= limit:
            break
    return results[:limit]


def build_list_query(
    *,
    search: str | None = None,
    route_group: list[str] | None = None,
    booking_state: list[str] | None = None,
    operational_state: list[str] | None = None,
    customer_id: int | None = None,
    owner_user_id: int | None = None,
    exceptions_only: bool = False,
    booked_from: date | None = None,
    booked_to: date | None = None,
    include_drafts: bool = True,
) -> list[Any]:
    """Filter predicates for the shipment list (Design.md section 9)."""
    conditions: list[Any] = []
    if search:
        reference = normalize_reference(search)
        like = f"%{reference}%"
        name_like = f"%{search.strip().lower()}%"
        conditions.append(
            or_(
                Shipment.public_id.like(like),
                Shipment.booking_reference.like(like),
                func.lower(Shipment.recipient_name).like(name_like),
                Shipment.id.in_(
                    select(ShipmentPackage.shipment_id).where(
                        ShipmentPackage.package_reference.like(like)
                    )
                ),
            )
        )
    if route_group:
        conditions.append(Shipment.route_group.in_(route_group))
    if booking_state:
        conditions.append(Shipment.booking_state.in_(booking_state))
    elif not include_drafts:
        conditions.append(Shipment.booking_state != BookingState.DRAFT)
    if operational_state:
        conditions.append(Shipment.operational_state.in_(operational_state))
    if customer_id is not None:
        conditions.append(Shipment.customer_id == customer_id)
    if owner_user_id is not None:
        conditions.append(Shipment.owner_user_id == owner_user_id)
    if exceptions_only:
        conditions.append(Shipment.operational_state.in_(list(EXCEPTION_OPERATIONAL_STATES)))
    if booked_from:
        conditions.append(
            Shipment.booking_date >= datetime.combine(booked_from, datetime.min.time())
        )
    if booked_to:
        conditions.append(Shipment.booking_date <= datetime.combine(booked_to, datetime.max.time()))
    return conditions


SORT_COLUMNS = {
    "booking_date": Shipment.booking_date,
    "public_id": Shipment.public_id,
    "operational_state": Shipment.operational_state,
    "route_group": Shipment.route_group,
}


def apply_sort(stmt: Select, sort: str, direction: str) -> Select:
    column = SORT_COLUMNS.get(sort, Shipment.booking_date)
    order = column.asc() if direction == "asc" else column.desc()
    return stmt.order_by(order, Shipment.id.desc())


def open_shipment_states() -> tuple[str, ...]:
    """Operational states that mean a shipment is still in flight."""
    return tuple(
        state
        for state in OperationalState
        if state
        not in {
            OperationalState.DELIVERED,
            OperationalState.CANCELLED,
            OperationalState.RETURNED,
        }
    )
