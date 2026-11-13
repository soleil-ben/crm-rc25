"""Helpers for the Phase 11 authenticated shipment-history suites.

The *fixtures* stay in ``conftest.py``; what lives here is the things a test calls. Two
things matter about the way an account gets here.

**Every linked account is produced by the real Phase 10 approval routes.** Nothing inserts
a ``customer_identity_links`` row. An ownership test that built its own link would be
proving that the query filters on a row the test wrote, which is a weaker statement than
the one it looks like -- and it would keep passing if approval stopped writing the link the
Phase 11 query reads.

**Shipments are built directly**, because there is no customer-facing booking route and the
staff booking flow would make every history test a booking test. The rows are shaped the
way ``booking_service`` leaves them, including the denormalized ``origin_*``/``destination_*``
summary the list allowlist reads, so a test that expects a city is expecting the same value
production would store.
"""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.enums import BookingState, OperationalState, Role, RouteGroup
from app.core.time_utils import utcnow
from app.models import Customer, Shipment, ShipmentEvent, ShipmentPackage
from app.services.identifier_service import UNAMBIGUOUS_ALPHABET
from tests.account_fixtures import ACCOUNT_PASSWORD
from tests.approval_fixtures import (
    acknowledged_preview,
    approve_link,
    make_customer,
    pending_identity,
    staff,
)

LIST_URL = "/api/v1/account/shipments"


def reference_for(route_group: str) -> str:
    """A Solaris Shipment ID the strict parser actually accepts.

    Twelve characters of ``UNAMBIGUOUS_ALPHABET``, from the same constant the generator
    uses. Built this way rather than from a hex string because hex contains ``0`` and
    ``1``, which the unambiguous alphabet deliberately excludes -- so a hex-derived
    reference is a string the detail route is right to refuse, and a fixture that produced
    one would make the detail suite fail at random.
    """
    suffix = "".join(secrets.choice(UNAMBIGUOUS_ALPHABET) for _ in range(12))
    return f"SX-{route_group}-{suffix}"


def detail_url(reference: str) -> str:
    return f"{LIST_URL}/{reference}"


# --- Getting an account to "active, linked, may read history" -----------------


def link_account(
    client: TestClient,
    mail,
    users: dict,
    *,
    email_address: str,
    customer: Customer,
) -> str:
    """Register, verify, and have Operations approve a link to ``customer``.

    Returns the ``CA-`` account reference. The client is left **signed out with no
    cookies**, so a caller decides which surface signs in next -- several tests here sign in
    as staff and as the customer in the same test and would otherwise inherit whichever
    session ran last.
    """
    reference = pending_identity(client, mail, email_address)
    api = staff(client, users[Role.OPERATIONS].email)
    fingerprint = acknowledged_preview(api, reference, "link_existing", customer.public_id)
    response = approve_link(api, reference, customer.public_id, fingerprint)
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "active"
    client.cookies.clear()
    return reference


def sign_in_account(client: TestClient, email_address: str) -> TestClient:
    """Sign the customer in. The session cookie stays on the client, as a browser's would."""
    client.cookies.clear()
    response = client.post(
        "/api/v1/account/sign-in",
        json={"email": email_address, "password": ACCOUNT_PASSWORD},
    )
    assert response.status_code == 200, response.text
    return client


def linked_and_signed_in(
    client: TestClient, mail, users: dict, *, email_address: str, customer: Customer
) -> TestClient:
    """The whole happy path in one call: registered, verified, approved, linked, signed in."""
    link_account(client, mail, users, email_address=email_address, customer=customer)
    return sign_in_account(client, email_address)


def csrf_for(client: TestClient) -> dict[str, str]:
    """The account CSRF header, read from the cookie a sign-in set.

    Only needed by the tests that prove a non-safe method does not exist on this surface;
    both shipment routes are ``GET``.
    """
    token = client.cookies.get(settings.account_csrf_cookie_name)
    return {settings.account_csrf_header_name: token} if token else {}


# --- Canonical rows ------------------------------------------------------------


def customer(db: Session, **overrides) -> Customer:
    return make_customer(db, **overrides)


def shipment(
    db: Session,
    owner: Customer,
    *,
    days_ago: int = 10,
    booking_state: str = BookingState.CONFIRMED,
    operational_state: str | None = None,
    route_group: str = RouteGroup.CAV,
    origin_city: str = "Mississauga",
    origin_country: str = "CA",
    destination_city: str = "Ho Chi Minh City",
    destination_country: str = "VN",
    delivered: bool = False,
    cancelled: bool = False,
    is_demo_record: bool = False,
    is_return: bool = False,
    rebooked_to: int | None = None,
    rebooked_from: int | None = None,
    estimated_delivery_at: datetime | None = None,
    packages: int = 0,
    cancelled_packages: int = 0,
    **columns,
) -> Shipment:
    """One shipment, owned by ``owner``, shaped the way the booking flow leaves one.

    ``**columns`` is how the privacy suites plant a sentinel in a real column -- an internal
    note, a recipient phone number, a selling amount -- without this helper having to know
    about every one of them.
    """
    now = utcnow()
    state = operational_state or (
        OperationalState.CANCELLED
        if cancelled or booking_state == BookingState.CANCELLED
        else OperationalState.DELIVERED
        if delivered
        else OperationalState.IN_TRANSIT
    )
    is_cancelled = cancelled or booking_state == BookingState.CANCELLED
    row = Shipment(
        public_id=None if booking_state == BookingState.DRAFT else reference_for(route_group),
        customer_id=owner.id,
        route_group=route_group,
        booking_state=BookingState.CANCELLED if is_cancelled else booking_state,
        operational_state=state,
        booking_date=now - timedelta(days=days_ago),
        first_handoff_at=now - timedelta(days=max(0, days_ago - 1)),
        delivered_at=now - timedelta(days=max(0, days_ago - 5)) if delivered else None,
        cancelled_at=now - timedelta(days=max(0, days_ago - 2)) if is_cancelled else None,
        estimated_delivery_at=estimated_delivery_at,
        # The booking flow keeps these two pairs aligned (`booking_service._apply_route_summary`),
        # so the list's `origin_*` and the detail's `sender_*` describe one place.
        origin_city=origin_city,
        origin_country_code=origin_country,
        destination_city=destination_city,
        destination_country_code=destination_country,
        sender_city=origin_city,
        sender_country_code=origin_country,
        recipient_city=destination_city,
        recipient_country_code=destination_country,
        is_demo_record=is_demo_record,
        is_return=is_return,
        rebooked_to_shipment_id=rebooked_to,
        rebooked_from_shipment_id=rebooked_from,
        package_count=max(1, packages),
        **columns,
    )
    db.add(row)
    db.commit()

    for index in range(packages):
        add_package(db, row, sequence=index + 1)
    for index in range(cancelled_packages):
        add_package(db, row, sequence=packages + index + 1, active=False)
    return row


def add_package(
    db: Session, row: Shipment, *, sequence: int, active: bool = True, delivered: bool = False
) -> ShipmentPackage:
    package = ShipmentPackage(
        shipment_id=row.id,
        sequence=sequence,
        # The real package-reference shape: the parent id plus a two-digit sequence.
        package_reference=f"{row.public_id}-{sequence:02d}",
        operational_state=(
            OperationalState.DELIVERED if delivered else OperationalState.IN_TRANSIT
        ),
        is_active=active,
        delivered_to_recipient_at=utcnow() if delivered else None,
    )
    db.add(package)
    db.commit()
    return package


def add_event(
    db: Session,
    row: Shipment,
    *,
    public: bool = True,
    text: str | None = "Arrived at the Ho Chi Minh City facility.",
    template_key: str | None = None,
    internal_detail: str | None = None,
    days_ago: int = 2,
    state: str = OperationalState.ARRIVED_DESTINATION,
    voided: bool = False,
    package_id: int | None = None,
) -> ShipmentEvent:
    """One shipment event. ``public=False`` builds the kind that must never be published."""
    now = utcnow()
    event = ShipmentEvent(
        shipment_id=row.id,
        package_id=package_id,
        # `event_type` is the manual vocabulary and `operational_state` the normalized one;
        # they coincide for every state these suites use, and the column is NOT NULL.
        event_type=state,
        operational_state=state,
        occurred_at=now - timedelta(days=days_ago),
        recorded_at=now - timedelta(days=days_ago),
        is_public_update=public,
        public_update_text=text if public else None,
        public_update_template_key=template_key if public else None,
        internal_detail=internal_detail,
        is_voided=voided,
    )
    db.add(event)
    db.commit()
    return event


# --- Reading a response ---------------------------------------------------------


def references(payload: dict) -> list[str]:
    return [item["shipment_reference"] for item in payload["items"]]


def walk(value, path: str = "$"):
    """Every (path, key, value) triple in a decoded JSON body, recursively.

    Used by the privacy suites, which assert over the *whole* body rather than over the
    top-level keys: a forbidden value nested three levels inside a timeline entry is still
    a disclosure.
    """
    if isinstance(value, dict):
        for key, child in value.items():
            yield f"{path}.{key}", key, child
            yield from walk(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from walk(child, f"{path}[{index}]")
