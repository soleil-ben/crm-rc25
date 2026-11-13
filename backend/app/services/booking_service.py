"""Draft bookings, transactional confirmation, and permanent Solaris shipment IDs.

Everything in CRM.md section 6 that makes a Solaris Shipment ID trustworthy lives here:

* a draft never has a customer-facing ID;
* confirmation happens inside one transaction that either produces exactly one ID or
  produces nothing;
* the ID is route-prefixed and its 12-character suffix comes from a cryptographically
  secure, unambiguous alphabet, with a database unique constraint and collision retry;
* a retried request returns the original booking, and a double-click or two concurrent
  requests cannot produce two bookings;
* the same idempotency key reused for materially different data is a conflict, not a
  silent return of an unrelated booking;
* the route group and the route-defining direction lock once confirmed, and correcting a
  wrong route is an audited cancel-and-rebook that issues a new ID and keeps the link.

**Why no ``SELECT ... FOR UPDATE``.** SQLite does not provide row locks, so serializing
on a row read would be a no-op that only looks safe. Confirmation is serialized by
database uniqueness instead: ``booking_confirmations.shipment_id`` and
``.idempotency_key`` are both unique, so the second writer loses at flush time and is
converted into an idempotent read of the winner's result (DEC-0031).
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from app.core.countries import normalize_country_code
from app.core.enums import (
    DIRECTION_COUNTRIES,
    ROUTE_DIRECTIONS,
    BookingState,
    OperationalState,
    RouteGroup,
    ServiceType,
    ShipmentDirection,
    TransportMode,
)
from app.core.normalization import collapse_whitespace, normalize_email, normalize_phone
from app.core.time_utils import utcnow
from app.models import (
    BookingConfirmation,
    Customer,
    CustomerAddress,
    Shipment,
    ShipmentPackage,
    ShipmentPayer,
    User,
)
from app.services import audit_service, consolidation_service, package_service
from app.services.errors import ConflictError, NotFoundError, ValidationError
from app.services.identifier_service import random_suffix

ID_PREFIX = "SX"
ID_SUFFIX_LENGTH = 12
MAX_ID_ATTEMPTS = 8
MAX_LOCK_RETRIES = 5

# Fields that define the route and therefore lock once a booking is confirmed.
ROUTE_LOCKED_FIELDS = ("route_group", "direction")

SNAPSHOT_ROLES = ("sender", "recipient")


@dataclass(frozen=True)
class ConfirmationResult:
    shipment: Shipment
    created: bool
    """False when an idempotent retry returned the booking confirmed by an earlier call."""
    id_generation_attempts: int


# --- Route and direction validation --------------------------------------


def validate_route(
    route_group: str,
    direction: str | None,
    *,
    origin_country: str | None = None,
    destination_country: str | None = None,
) -> str:
    """Validate a route/direction pair and return the resolved direction.

    Enforced on the server so a bypassed frontend cannot book an out-of-scope lane
    (CRM.md section 6). US to US is not merely absent from the table: it is named in the
    error, because silently classifying it as cross border is the failure mode the brief
    calls out.
    """
    if route_group not in set(RouteGroup):
        raise ValidationError(f"Unknown route group '{route_group}'.", field="route_group")

    allowed = ROUTE_DIRECTIONS[route_group]
    if direction is None:
        if len(allowed) == 1:
            direction = allowed[0]
        else:
            # A two-way route group (XUS) infers its direction from the addresses when
            # they determine it unambiguously; otherwise staff must state it.
            inferred = [
                candidate
                for candidate in allowed
                if DIRECTION_COUNTRIES[candidate] == (origin_country, destination_country)
            ]
            if len(inferred) == 1:
                direction = inferred[0]
            else:
                raise ValidationError(
                    "This route group needs an explicit direction.",
                    field="direction",
                    detail={"allowed": list(allowed)},
                )

    if direction not in set(ShipmentDirection):
        if (origin_country, destination_country) == ("US", "US") or direction == "us_to_us":
            raise ValidationError(
                "United States to United States is outside the launch scope and cannot be "
                "booked as cross border.",
                field="direction",
            )
        raise ValidationError(f"Unknown direction '{direction}'.", field="direction")

    if direction not in allowed:
        raise ValidationError(
            f"Route group {route_group} does not allow direction "
            f"'{direction}'. Allowed: {', '.join(allowed)}.",
            field="direction",
            detail={"route_group": route_group, "allowed": list(allowed)},
        )

    expected_origin, expected_destination = DIRECTION_COUNTRIES[direction]
    if origin_country and origin_country != expected_origin:
        raise ValidationError(
            f"Direction '{direction}' requires an origin in {expected_origin}, "
            f"but the sender address is in {origin_country}.",
            field="sender_country_code",
        )
    if destination_country and destination_country != expected_destination:
        raise ValidationError(
            f"Direction '{direction}' requires a destination in {expected_destination}, "
            f"but the recipient address is in {destination_country}.",
            field="recipient_country_code",
        )
    return direction


# --- Address snapshots ----------------------------------------------------


def snapshot_from_address(address: CustomerAddress) -> dict[str, Any]:
    """Copy an address-book entry into a booking snapshot.

    The values are copied, not referenced. Editing the address book afterwards cannot
    reach a confirmed shipment (AC-5).
    """
    return {
        "name": address.contact_name,
        "company": address.company_name,
        "phone_entered": address.phone_entered,
        "phone_e164": address.phone_e164,
        "email": address.email_entered,
        "address_line1": address.address_line1,
        "address_line2": address.address_line2,
        "city": address.city,
        "province_state": address.province_state,
        "postal_code": address.postal_code,
        "country_code": address.country_code,
        "country_input": address.country_code,
        "delivery_note": address.delivery_note,
    }


def _clean_snapshot(role: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize one party's snapshot fields."""
    entered_country = payload.get("country_input") or payload.get("country_code")
    try:
        country_code = normalize_country_code(payload.get("country_code") or entered_country)
    except ValueError as exc:
        raise ValidationError(str(exc), field=f"{role}_country_code") from exc

    phone_entered, phone_e164, _region = normalize_phone(payload.get("phone_entered"), country_code)
    email_entered = payload.get("email")
    if email_entered:
        try:
            email_entered, _normalized = normalize_email(email_entered)
        except ValueError as exc:
            raise ValidationError(str(exc), field=f"{role}_email") from exc

    cleaned = {
        "name": collapse_whitespace(payload.get("name")),
        "company": collapse_whitespace(payload.get("company")),
        "phone_entered": phone_entered,
        "phone_e164": phone_e164,
        "email": email_entered,
        "address_line1": collapse_whitespace(payload.get("address_line1")),
        "address_line2": collapse_whitespace(payload.get("address_line2")),
        "city": collapse_whitespace(payload.get("city")),
        "province_state": collapse_whitespace(payload.get("province_state")),
        "postal_code": collapse_whitespace(payload.get("postal_code")),
        "country_code": country_code,
        "country_input": collapse_whitespace(entered_country),
    }
    if role == "recipient":
        cleaned["delivery_note"] = collapse_whitespace(payload.get("delivery_note"))
    return cleaned


def _apply_snapshot(shipment: Shipment, role: str, cleaned: dict[str, Any]) -> None:
    for key, value in cleaned.items():
        setattr(shipment, f"{role}_{key}", value)


def _resolve_snapshot(
    db: Session, customer_id: int, role: str, payload: dict[str, Any] | None
) -> tuple[dict[str, Any] | None, int | None]:
    """Return ``(cleaned snapshot, source address id)`` for one party."""
    if payload is None:
        return None, None
    address_id = payload.get("address_id")
    if address_id:
        address = db.get(CustomerAddress, address_id)
        if address is None or address.customer_id != customer_id:
            raise NotFoundError("That saved address does not belong to this customer.")
        base = snapshot_from_address(address)
        # Explicit overrides still win, so staff can correct one line without editing
        # the customer's saved contact.
        base.update({k: v for k, v in payload.items() if k != "address_id" and v is not None})
        return _clean_snapshot(role, base), address.id
    return _clean_snapshot(role, payload), None


# --- Draft creation and editing -------------------------------------------


def _resolve_payer(db: Session, payer_customer_id: Any, booking_customer_id: int) -> int | None:
    """The paying customer, when it is not the booking customer (Phase 13B).

    ``None`` -- and a payer equal to the booking customer -- both mean "the booking
    customer pays" and are stored as NULL, so the column carries information only when the
    roles differ (handoff section 2).
    """
    if payer_customer_id in (None, ""):
        return None
    try:
        payer_id = int(payer_customer_id)
    except (TypeError, ValueError) as error:
        raise ValidationError(
            "payer_customer_id must be a customer id.", field="payer_customer_id"
        ) from error
    if payer_id == booking_customer_id:
        return None
    payer = db.get(Customer, payer_id)
    if payer is None or payer.merged_into_customer_id is not None:
        raise NotFoundError("That paying customer record does not exist.")
    return payer.id


def payer_customer_id(db: Session, shipment_id: int) -> int | None:
    """The paying customer's id, or None when the booking customer pays (Phase 13B)."""
    row = db.get(ShipmentPayer, shipment_id)
    return row.payer_customer_id if row else None


def set_payer(
    db: Session, shipment: Shipment, payer_id: int | None, *, actor: User | None = None
) -> None:
    """Write, replace or clear the ``shipment_payers`` row. ``None`` clears it."""
    row = db.get(ShipmentPayer, shipment.id)
    if payer_id is None:
        if row is not None:
            db.delete(row)
            db.flush()
        return
    if row is None:
        db.add(
            ShipmentPayer(
                shipment_id=shipment.id,
                payer_customer_id=payer_id,
                set_at=utcnow(),
                set_by_user_id=actor.id if actor else None,
            )
        )
    elif row.payer_customer_id != payer_id:
        row.payer_customer_id = payer_id
        row.set_at = utcnow()
        row.set_by_user_id = actor.id if actor else None
    db.flush()


def _require_customer(db: Session, customer_id: int) -> Customer:
    customer = db.get(Customer, customer_id)
    if customer is None or customer.merged_into_customer_id is not None:
        raise NotFoundError("That customer record does not exist.")
    return customer


def get_shipment(db: Session, shipment_id: int) -> Shipment:
    shipment = db.get(Shipment, shipment_id)
    if shipment is None:
        raise NotFoundError("That shipment does not exist.")
    return shipment


def create_draft(
    db: Session,
    payload: dict[str, Any],
    *,
    actor: User | None = None,
    ip_address: str | None = None,
) -> Shipment:
    """Create a draft booking. A draft never receives a customer-facing ID."""
    customer = _require_customer(db, payload["customer_id"])

    sender, sender_address_id = _resolve_snapshot(db, customer.id, "sender", payload.get("sender"))
    recipient, recipient_address_id = _resolve_snapshot(
        db, customer.id, "recipient", payload.get("recipient")
    )

    direction = validate_route(
        payload["route_group"],
        payload.get("direction"),
        origin_country=(sender or {}).get("country_code"),
        destination_country=(recipient or {}).get("country_code"),
    )

    payer_id = _resolve_payer(db, payload.get("payer_customer_id"), customer.id)
    shipment = Shipment(
        public_id=None,
        customer_id=customer.id,
        route_group=payload["route_group"],
        direction=direction,
        service_type=payload.get("service_type") or ServiceType.STANDARD_PARCEL,
        transport_mode=payload.get("transport_mode") or TransportMode.UNSPECIFIED,
        booking_state=BookingState.DRAFT,
        operational_state=OperationalState.BOOKED,
        booking_reference=collapse_whitespace(payload.get("booking_reference")),
        contents_description=collapse_whitespace(payload.get("contents_description")),
        declared_value=_as_decimal(payload.get("declared_value"), "declared_value"),
        declared_value_currency=_currency(payload.get("declared_value_currency")),
        estimated_delivery_at=payload.get("estimated_delivery_at"),
        owner_user_id=payload.get("owner_user_id") or (actor.id if actor else None),
        internal_notes=payload.get("internal_notes"),
        sender_address_id=sender_address_id,
        recipient_address_id=recipient_address_id,
        package_count=0,
        is_demo_record=bool(payload.get("is_demo_record", False)),
    )
    if sender:
        _apply_snapshot(shipment, "sender", sender)
    if recipient:
        _apply_snapshot(shipment, "recipient", recipient)
    _apply_route_summary(shipment)

    db.add(shipment)
    db.flush()
    set_payer(db, shipment, payer_id, actor=actor)

    for index, package_payload in enumerate(payload.get("packages") or [], start=1):
        package_service.add_package(db, shipment, package_payload, actor=actor, sequence=index)
    package_service.refresh_package_count(db, shipment)

    audit_service.record_audit(
        db,
        action="shipment.draft_create",
        entity_type="shipment",
        entity_id=shipment.id,
        summary=f"Created draft booking for customer {customer.public_id}",
        actor=actor,
        ip_address=ip_address,
        detail={"route_group": shipment.route_group, "direction": shipment.direction},
    )
    return shipment


EDITABLE_AFTER_CONFIRMATION = {
    # Phase 13B: who pays may be corrected at any time; it is not part of the route.
    "payer_customer_id",
    "service_type",
    "transport_mode",
    "booking_reference",
    "contents_description",
    "declared_value",
    "declared_value_currency",
    "estimated_delivery_at",
    "owner_user_id",
    "internal_notes",
    "payment_state",
}


def update_shipment(
    db: Session,
    shipment: Shipment,
    payload: dict[str, Any],
    *,
    actor: User | None = None,
    ip_address: str | None = None,
) -> Shipment:
    """Edit a booking.

    A draft may change anything. After confirmation the route group and direction are
    locked, because the Solaris ID already encodes the route and its meaning must never
    change (CRM.md section 6). Correcting a route is cancel-and-rebook.
    """
    locked = shipment.route_is_locked
    if locked:
        attempted = [
            field
            for field in ROUTE_LOCKED_FIELDS
            if field in payload
            and payload[field] is not None
            and payload[field] != getattr(shipment, field)
        ]
        if attempted:
            raise ConflictError(
                "The route group and direction lock once a booking is confirmed. "
                "Use cancel and rebook to issue a corrected shipment.",
                field=attempted[0],
                detail={"locked_fields": list(ROUTE_LOCKED_FIELDS), "attempted": attempted},
            )
        rejected = sorted(
            key
            for key in payload
            if key not in EDITABLE_AFTER_CONFIRMATION
            and key not in ROUTE_LOCKED_FIELDS
            and payload[key] is not None
        )
        if rejected:
            raise ConflictError(
                "These fields cannot be changed after confirmation: " + ", ".join(rejected),
                detail={"fields": rejected},
            )

    if not locked:
        sender, sender_address_id = _resolve_snapshot(
            db, shipment.customer_id, "sender", payload.get("sender")
        )
        recipient, recipient_address_id = _resolve_snapshot(
            db, shipment.customer_id, "recipient", payload.get("recipient")
        )
        if sender:
            _apply_snapshot(shipment, "sender", sender)
            shipment.sender_address_id = sender_address_id
        if recipient:
            _apply_snapshot(shipment, "recipient", recipient)
            shipment.recipient_address_id = recipient_address_id

        route_group = payload.get("route_group") or shipment.route_group
        direction = payload.get("direction") or (
            shipment.direction if route_group == shipment.route_group else None
        )
        shipment.direction = validate_route(
            route_group,
            direction,
            origin_country=shipment.sender_country_code,
            destination_country=shipment.recipient_country_code,
        )
        shipment.route_group = route_group

    for field in EDITABLE_AFTER_CONFIRMATION:
        if field not in payload:
            continue
        value = payload[field]
        if field == "declared_value":
            value = _as_decimal(value, "declared_value")
        elif field == "declared_value_currency":
            value = _currency(value, unchanged=shipment.declared_value_currency)
        elif field in {"booking_reference", "contents_description"}:
            value = collapse_whitespace(value)
        elif field == "payer_customer_id":
            set_payer(db, shipment, _resolve_payer(db, value, shipment.customer_id), actor=actor)
            continue
        setattr(shipment, field, value)

    _apply_route_summary(shipment)
    db.flush()

    reference = shipment.public_id or "draft booking"
    # A save from the Internal notes box gets its own action and a summary that says what
    # it was, so the shipment's audit list shows "Internal notes updated" rather than a
    # generic "Updated" a reader cannot tell apart from any other edit (UAT round 4). The
    # detail names the field and never carries the note itself.
    notes_only = set(payload) == {"internal_notes"}
    audit_service.record_audit(
        db,
        action="shipment.internal_notes_update" if notes_only else "shipment.update",
        entity_type="shipment",
        entity_id=shipment.id,
        summary=f"Internal notes updated on {reference}" if notes_only else f"Updated {reference}",
        actor=actor,
        ip_address=ip_address,
        detail={"fields": sorted(payload.keys()), "locked": locked},
    )
    return shipment


def _apply_route_summary(shipment: Shipment) -> None:
    """Keep the denormalized origin/destination summary aligned with the snapshots."""
    shipment.origin_country_code = shipment.sender_country_code
    shipment.origin_city = shipment.sender_city
    shipment.destination_country_code = shipment.recipient_country_code
    shipment.destination_city = shipment.recipient_city


def _as_decimal(value: Any, field: str) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        amount = Decimal(str(value))
    except (ArithmeticError, ValueError) as exc:
        raise ValidationError("Enter a number.", field=field) from exc
    if amount < 0:
        raise ValidationError("A declared value cannot be negative.", field=field)
    return amount.quantize(Decimal("0.01"))


#: The currencies a declared value may be stated in (RC-UAT-25 item 3, Ben 2026-10-25):
#: the two the CRM handles anywhere -- customer payments and vendor bills take exactly CAD
#: and VND. The booking screen offers these in a list (``/shipments/meta``), and a value
#: outside it is refused here, so a bypassed screen or an import cannot store another.
DECLARED_VALUE_CURRENCIES: tuple[str, ...] = ("CAD", "VND")

DECLARED_VALUE_CURRENCY_MESSAGE = "Choose CAD or VND for the declared value currency."


def _currency(value: str | None, *, unchanged: str | None = None) -> str | None:
    """Clean and check a declared value currency; blank stays blank (it is optional).

    ``unchanged`` is the value already stored on the shipment: re-sending it untouched is
    accepted even if it predates the list, so an edit of another field never fails on a
    currency nobody changed.
    """
    cleaned = collapse_whitespace(value)
    if not cleaned:
        return None
    code = cleaned.upper()
    if unchanged is not None and code == unchanged.upper():
        return unchanged
    if code not in DECLARED_VALUE_CURRENCIES:
        raise ValidationError(
            DECLARED_VALUE_CURRENCY_MESSAGE,
            field="declared_value_currency",
            detail={"allowed": list(DECLARED_VALUE_CURRENCIES)},
        )
    return code


# --- Confirmation ---------------------------------------------------------


def booking_fingerprint(db: Session, shipment: Shipment) -> str:
    """Stable hash of the material booking data behind an idempotency key.

    Deliberately excludes everything confirmation itself sets (public ID, state,
    timestamps) so a genuine retry matches, and includes every field a staff member
    could have changed between two clicks so a materially different request is caught.
    """
    packages = db.scalars(
        select(ShipmentPackage)
        .where(ShipmentPackage.shipment_id == shipment.id)
        .order_by(ShipmentPackage.sequence)
    ).all()

    material: dict[str, Any] = {
        "customer_id": shipment.customer_id,
        "route_group": shipment.route_group,
        "direction": shipment.direction,
        "service_type": shipment.service_type,
        "transport_mode": shipment.transport_mode,
        "booking_reference": shipment.booking_reference,
        "contents_description": shipment.contents_description,
        "declared_value": None if shipment.declared_value is None else str(shipment.declared_value),
        "declared_value_currency": shipment.declared_value_currency,
        "packages": [
            {
                "sequence": package.sequence,
                "length_cm": _decimal_text(package.length_cm),
                "width_cm": _decimal_text(package.width_cm),
                "height_cm": _decimal_text(package.height_cm),
                "weight_kg": _decimal_text(package.weight_kg),
                "contents_summary": package.contents_summary,
                "is_active": package.is_active,
            }
            for package in packages
        ],
    }
    for role in SNAPSHOT_ROLES:
        for field in (
            "name",
            "company",
            "phone_e164",
            "phone_entered",
            "email",
            "address_line1",
            "address_line2",
            "city",
            "province_state",
            "postal_code",
            "country_code",
        ):
            material[f"{role}_{field}"] = getattr(shipment, f"{role}_{field}")

    canonical = json.dumps(material, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _decimal_text(value: Decimal | None) -> str | None:
    """Normalize a decimal to text so 5.0 and 5.00 hash identically."""
    if value is None:
        return None
    return format(Decimal(str(value)).normalize(), "f")


def _generate_public_id(db: Session, shipment: Shipment) -> int:
    """Assign a unique route-prefixed Solaris ID, retrying on collision.

    The suffix comes from ``identifier_service.random_suffix``: 12 characters from a
    cryptographically secure, unambiguous uppercase alphabet. A pre-check catches the
    common case; the savepoint plus the ``uq_shipments_public_id`` constraint catches a
    genuine race between two connections.
    """
    prefix = f"{ID_PREFIX}-{shipment.route_group}-"
    for attempt in range(1, MAX_ID_ATTEMPTS + 1):
        candidate = prefix + random_suffix(ID_SUFFIX_LENGTH)
        taken = db.scalar(select(Shipment.id).where(Shipment.public_id == candidate))
        if taken is not None:
            continue
        savepoint = db.begin_nested()
        try:
            shipment.public_id = candidate
            db.flush()
        except IntegrityError:
            savepoint.rollback()
            shipment.public_id = None
            continue
        else:
            savepoint.commit()
            return attempt
    raise ConflictError(
        "Could not allocate a unique Solaris shipment ID. Try again.",
        detail={"attempts": MAX_ID_ATTEMPTS},
    )


def confirm_booking(
    db: Session,
    *,
    shipment_id: int,
    idempotency_key: str,
    actor: User | None = None,
    ip_address: str | None = None,
) -> ConfirmationResult:
    """Confirm a draft transactionally and return the confirmed shipment.

    The caller commits. Every path either produces exactly one confirmation row plus one
    Solaris ID, or leaves the draft untouched.
    """
    key = collapse_whitespace(idempotency_key)
    if not key:
        raise ValidationError("An idempotency key is required to confirm a booking.")

    last_error: OperationalError | None = None
    for attempt in range(MAX_LOCK_RETRIES):
        try:
            return _confirm_once(
                db, shipment_id=shipment_id, key=key, actor=actor, ip_address=ip_address
            )
        except OperationalError as exc:  # pragma: no cover - timing dependent
            if "database is locked" not in str(exc).lower():
                raise
            # Another connection is mid-confirmation. Drop our read snapshot and retry;
            # the next pass sees the winner's row and returns it idempotently.
            last_error = exc
            db.rollback()
            time.sleep(0.05 * (2**attempt))
    raise ConflictError(
        "The booking is being confirmed by another request. Reload the shipment.",
        detail={"reason": str(last_error) if last_error else "locked"},
    )


def _existing_confirmation(db: Session, key: str) -> BookingConfirmation | None:
    return db.scalar(select(BookingConfirmation).where(BookingConfirmation.idempotency_key == key))


def _confirm_once(
    db: Session,
    *,
    shipment_id: int,
    key: str,
    actor: User | None,
    ip_address: str | None,
) -> ConfirmationResult:
    shipment = get_shipment(db, shipment_id)

    existing = _existing_confirmation(db, key)
    if existing is not None:
        return _replay(db, existing, shipment, key)

    if shipment.booking_state == BookingState.CANCELLED:
        raise ConflictError("This booking is cancelled. Rebook it instead of confirming it.")
    if shipment.booking_state == BookingState.CONFIRMED:
        # Confirmed already, under a different key.
        prior = db.scalar(
            select(BookingConfirmation).where(BookingConfirmation.shipment_id == shipment.id)
        )
        raise ConflictError(
            f"Booking {shipment.public_id} is already confirmed.",
            detail={
                "public_id": shipment.public_id,
                "confirmed_with_key": prior.idempotency_key if prior else None,
            },
        )

    _validate_confirmable(db, shipment)
    fingerprint = booking_fingerprint(db, shipment)
    now = utcnow()

    # Claim the booking before anything else. Losing this race is the double-click and
    # concurrent-request case, and it is resolved by returning the winner's shipment.
    confirmation = BookingConfirmation(
        shipment_id=shipment.id,
        idempotency_key=key,
        request_fingerprint=fingerprint,
        public_id="",
        confirmed_at=now,
        confirmed_by_user_id=actor.id if actor else None,
        generation_attempts=0,
    )
    savepoint = db.begin_nested()
    try:
        db.add(confirmation)
        db.flush()
    except IntegrityError:
        savepoint.rollback()
        db.expire_all()
        winner = _existing_confirmation(db, key) or db.scalar(
            select(BookingConfirmation).where(BookingConfirmation.shipment_id == shipment_id)
        )
        if winner is None:  # pragma: no cover - only reachable on an unrelated conflict
            raise
        return _replay(db, winner, get_shipment(db, winner.shipment_id), key)
    else:
        savepoint.commit()

    attempts = _generate_public_id(db, shipment)
    confirmation.public_id = shipment.public_id
    confirmation.generation_attempts = attempts

    shipment.booking_state = BookingState.CONFIRMED
    shipment.confirmed_at = now
    shipment.confirmed_by_user_id = actor.id if actor else None
    shipment.booking_date = shipment.booking_date or now
    shipment.idempotency_key = key
    if shipment.operational_state == OperationalState.BOOKED:
        shipment.operational_state = OperationalState.BOOKED

    package_service.assign_references(db, shipment)
    package_service.refresh_package_count(db, shipment)
    db.flush()

    audit_service.record_audit(
        db,
        action="shipment.confirm",
        entity_type="shipment",
        entity_id=shipment.id,
        summary=f"Confirmed booking {shipment.public_id}",
        actor=actor,
        ip_address=ip_address,
        detail={
            "public_id": shipment.public_id,
            "route_group": shipment.route_group,
            "direction": shipment.direction,
            "package_count": shipment.package_count,
            "id_generation_attempts": attempts,
        },
    )
    return ConfirmationResult(shipment=shipment, created=True, id_generation_attempts=attempts)


def _replay(
    db: Session, confirmation: BookingConfirmation, requested: Shipment, key: str
) -> ConfirmationResult:
    """Idempotent retry: return the original booking, or refuse a mismatched reuse."""
    original = db.get(Shipment, confirmation.shipment_id)
    if original is None:  # pragma: no cover - FK cascade makes this unreachable
        raise NotFoundError("The confirmed booking behind that idempotency key is gone.")

    if confirmation.shipment_id != requested.id:
        raise ConflictError(
            "That idempotency key already confirmed a different booking.",
            detail={"idempotency_key": key, "public_id": original.public_id},
        )
    current = booking_fingerprint(db, original)
    if current != confirmation.request_fingerprint:
        raise ConflictError(
            "That idempotency key was used for materially different booking data. "
            "Use a new key, or reload the shipment.",
            detail={"idempotency_key": key, "public_id": original.public_id},
        )
    return ConfirmationResult(
        shipment=original, created=False, id_generation_attempts=confirmation.generation_attempts
    )


def _validate_confirmable(db: Session, shipment: Shipment) -> None:
    """Everything a booking must have before it can carry a customer-facing ID."""
    validate_route(
        shipment.route_group,
        shipment.direction,
        origin_country=shipment.sender_country_code,
        destination_country=shipment.recipient_country_code,
    )
    missing: list[str] = []
    if not shipment.sender_name:
        missing.append("sender_name")
    if not shipment.sender_country_code:
        missing.append("sender_country_code")
    if not shipment.recipient_name:
        missing.append("recipient_name")
    if not shipment.recipient_country_code:
        missing.append("recipient_country_code")
    if not shipment.recipient_city:
        missing.append("recipient_city")
    if not shipment.contents_description:
        missing.append("contents_description")
    if missing:
        raise ValidationError(
            "Complete the booking before confirming it.",
            field=missing[0],
            detail={"missing": missing},
        )

    active = db.scalar(
        select(ShipmentPackage.id)
        .where(ShipmentPackage.shipment_id == shipment.id, ShipmentPackage.is_active.is_(True))
        .limit(1)
    )
    if active is None:
        raise ValidationError("Add at least one package before confirming.", field="packages")


# --- Cancellation and rebooking -------------------------------------------


def cancel_shipment(
    db: Session,
    shipment: Shipment,
    *,
    reason: str,
    actor: User | None = None,
    ip_address: str | None = None,
    occurred_at: datetime | None = None,
) -> Shipment:
    """Cancel a booking. The Solaris ID is retired with the record and never reused."""
    cleaned = collapse_whitespace(reason)
    if not cleaned:
        raise ValidationError("A cancellation reason is required.", field="reason")
    if shipment.booking_state == BookingState.CANCELLED:
        raise ConflictError("That booking is already cancelled.")

    shipment.booking_state = BookingState.CANCELLED
    # Phase 13B: a cancelled booking leaves its consolidation, whatever the consolidation's
    # state; the master's member list must not keep a shipment that will never travel.
    consolidation_service.release_membership_for_cancelled_shipment(db, shipment, actor=actor)
    shipment.operational_state = OperationalState.CANCELLED
    shipment.cancelled_at = occurred_at or utcnow()
    shipment.cancellation_reason = cleaned[:255]
    shipment.cancelled_by_user_id = actor.id if actor else None
    db.flush()

    audit_service.record_audit(
        db,
        action="shipment.cancel",
        entity_type="shipment",
        entity_id=shipment.id,
        summary=f"Cancelled {shipment.public_id or 'draft booking'}",
        actor=actor,
        ip_address=ip_address,
        detail={"public_id": shipment.public_id, "reason": cleaned[:255]},
    )
    return shipment


def rebook_shipment(
    db: Session,
    shipment: Shipment,
    *,
    reason: str,
    changes: dict[str, Any] | None = None,
    actor: User | None = None,
    ip_address: str | None = None,
) -> Shipment:
    """Cancel a booking and create a linked replacement draft (CRM.md section 6).

    The replacement is a draft: confirming it issues a *new* Solaris ID. The original ID
    keeps its original meaning, is never reused, and both records keep a link to each
    other so the correction is traceable.
    """
    if shipment.rebooked_to_shipment_id is not None:
        raise ConflictError(
            "That booking has already been rebooked.",
            detail={"rebooked_to_shipment_id": shipment.rebooked_to_shipment_id},
        )

    changes = changes or {}
    payload: dict[str, Any] = {
        "customer_id": shipment.customer_id,
        "route_group": changes.get("route_group") or shipment.route_group,
        "direction": changes.get("direction"),
        "service_type": changes.get("service_type") or shipment.service_type,
        "transport_mode": changes.get("transport_mode") or shipment.transport_mode,
        "booking_reference": shipment.booking_reference,
        "contents_description": shipment.contents_description,
        "declared_value": shipment.declared_value,
        # Copied forward below, as stored: a currency that predates the list must not stop
        # a correction (RC-UAT-25 item 3).
        "declared_value_currency": None,
        "owner_user_id": shipment.owner_user_id,
        "internal_notes": shipment.internal_notes,
        "is_demo_record": shipment.is_demo_record,
        # Snapshots are copied forward from the cancelled record, then overridden.
        "sender": changes.get("sender") or _snapshot_payload(shipment, "sender"),
        "recipient": changes.get("recipient") or _snapshot_payload(shipment, "recipient"),
        "packages": changes.get("packages") or _package_payloads(db, shipment),
    }

    replacement = create_draft(db, payload, actor=actor, ip_address=ip_address)
    replacement.declared_value_currency = shipment.declared_value_currency
    replacement.rebooked_from_shipment_id = shipment.id
    db.flush()

    cancel_shipment(
        db,
        shipment,
        reason=f"Rebooked: {reason}",
        actor=actor,
        ip_address=ip_address,
    )
    shipment.rebooked_to_shipment_id = replacement.id
    db.flush()

    audit_service.record_audit(
        db,
        action="shipment.rebook",
        entity_type="shipment",
        entity_id=shipment.id,
        summary=(
            f"Rebooked {shipment.public_id or 'draft booking'} as a new draft "
            f"(shipment {replacement.id})"
        ),
        actor=actor,
        ip_address=ip_address,
        detail={
            "original_public_id": shipment.public_id,
            "replacement_shipment_id": replacement.id,
            "reason": collapse_whitespace(reason),
        },
    )
    return replacement


def _snapshot_payload(shipment: Shipment, role: str) -> dict[str, Any]:
    fields = [
        "name",
        "company",
        "phone_entered",
        "email",
        "address_line1",
        "address_line2",
        "city",
        "province_state",
        "postal_code",
        "country_code",
        "country_input",
    ]
    payload = {field: getattr(shipment, f"{role}_{field}") for field in fields}
    if role == "recipient":
        payload["delivery_note"] = shipment.recipient_delivery_note
    return payload


def _package_payloads(db: Session, shipment: Shipment) -> list[dict[str, Any]]:
    packages = db.scalars(
        select(ShipmentPackage)
        .where(ShipmentPackage.shipment_id == shipment.id, ShipmentPackage.is_active.is_(True))
        .order_by(ShipmentPackage.sequence)
    ).all()
    return [
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
        }
        for package in packages
    ]
