"""Helpers for the Phase 10 staff approval suites.

The *fixtures* stay in ``conftest.py``; what lives here is the things a test calls. The
pattern is `account_fixtures.py`'s, and the two are used together: that module gets an
identity to ``pending_approval`` through the real customer-facing routes, and this one
drives the staff review routes against it.

Every suite here runs against the **account** database, because these tests need a staff
user and a customer identity in one database -- a staff session resolving against a
different SQLite file would make "Operations can approve this" pass for the wrong reason.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.enums import BookingState, OperationalState, RouteGroup
from app.core.time_utils import utcnow
from app.models import Customer, Shipment
from app.services.identifier_service import random_suffix
from tests.account_fixtures import registered_and_verified

BASE = "/api/v1/customer-account/registrations"


def staff(client: TestClient, email: str, password: str = "TestPassword!2026") -> StaffClient:
    """Sign a staff user in against the account database and return a CSRF-carrying client."""
    client.cookies.clear()
    response = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return StaffClient(client, response.json()["csrf_token"])


class StaffClient:
    """A staff caller that always sends the staff CSRF header on a non-safe method.

    Deliberately the *staff* header name. A test that used the account header here would
    pass or fail for a reason that had nothing to do with what it was testing, and the
    two names differing is itself one of the invariants (AC-CA-1.3).
    """

    def __init__(self, client: TestClient, csrf_token: str) -> None:
        self.client = client
        self.headers = {settings.csrf_header_name: csrf_token}

    def get(self, url: str, **kwargs):
        return self.client.get(url, **kwargs)

    def post(self, url: str, **kwargs):
        return self.client.post(url, headers=self.headers, **kwargs)


def pending_identity(client: TestClient, mail, email_address: str) -> str:
    """Register and verify one applicant. Returns the ``CA-`` account reference.

    The identity comes out ``pending_approval`` with a pending registration proposal --
    exactly where Phase 9 leaves it, reached through the real routes rather than by
    inserting rows, so the proposal a reviewer reads is one registration actually built.
    """
    registered_and_verified(client, mail, email_address)
    from app.models import CustomerIdentity

    # The reference is read back through the sign-in response rather than the database, so
    # the helper does not need a session.
    response = client.post(
        "/api/v1/account/sign-in",
        json={"email": email_address, "password": "SolarisCustomer!2026"},
    )
    assert response.status_code == 200, response.text
    reference = response.json()["account_reference"]
    client.post(
        "/api/v1/account/sign-out",
        headers={settings.account_csrf_header_name: response.json()["csrf_token"]},
    )
    client.cookies.clear()
    assert CustomerIdentity  # imported for the reader; the reference is what callers need
    return reference


def key() -> str:
    """A fresh idempotency key. Fresh by default so a test that is not about idempotency
    does not accidentally replay."""
    return uuid.uuid4().hex


def preview(api: StaffClient, reference: str, action: str, customer: str | None = None):
    params = {"action": action}
    if customer:
        params["customer_public_id"] = customer
    return api.get(f"{BASE}/{reference}/preview", params=params)


def acknowledge(api: StaffClient, reference: str, body: dict):
    return api.post(f"{BASE}/{reference}/disclosure-acknowledgement", json=body)


def acknowledged_preview(
    api: StaffClient, reference: str, action: str, customer: str | None = None
) -> str:
    """Take a preview, acknowledge it, and return the fingerprint. The happy path, once."""
    response = preview(api, reference, action, customer)
    assert response.status_code == 200, response.text
    fingerprint = response.json()["fingerprint"]
    ack = acknowledge(
        api,
        reference,
        {"action": action, "customer_public_id": customer, "fingerprint": fingerprint},
    )
    assert ack.status_code == 200, ack.text
    return fingerprint


def approve_create(api: StaffClient, reference: str, fingerprint: str, **extra):
    body = {"preview_fingerprint": fingerprint, "idempotency_key": extra.pop("key", key())}
    body.update(extra)
    return api.post(f"{BASE}/{reference}/approve/create-new", json=body)


def approve_link(api: StaffClient, reference: str, customer: str, fingerprint: str, **extra):
    body = {
        "customer_public_id": customer,
        "preview_fingerprint": fingerprint,
        "idempotency_key": extra.pop("key", key()),
    }
    body.update(extra)
    return api.post(f"{BASE}/{reference}/approve/link-existing", json=body)


def reject(api: StaffClient, reference: str, reason: str = "unverifiable_details", **extra):
    body = {"reason_code": reason, "idempotency_key": extra.pop("key", key())}
    body.update(extra)
    return api.post(f"{BASE}/{reference}/reject", json=body)


# --- Canonical fixtures the disclosure arithmetic needs -----------------------


def make_customer(db: Session, **overrides) -> Customer:
    """A canonical customer, created through the service the approval also uses."""
    from app.services import customer_service

    payload = {
        "full_name": "Existing Customer",
        "email": "existing.customer@demo.example.com",
        "phone": "+1 416 555 0199",
        "country_code": "CA",
    }
    payload.update(overrides)
    customer = customer_service.create_customer(db, payload)
    db.commit()
    return customer


def add_shipment(
    db: Session,
    customer: Customer,
    *,
    days_ago: int = 10,
    booking_state: str = BookingState.CONFIRMED,
    is_demo_record: bool = False,
    rebooked_to: int | None = None,
    rebooked_from: int | None = None,
) -> Shipment:
    """One shipment, shaped so the disclosure rule's three clauses can be exercised.

    A draft gets no ``public_id``, exactly as the booking flow leaves it, so a test that
    expects drafts to be excluded is excluding the same thing production would.
    """
    now = utcnow()
    shipment = Shipment(
        # See the note in `conftest.add_shipment`: a uuid-derived suffix is not a valid
        # Solaris reference four times in five (DEC-0117).
        public_id=None if booking_state == BookingState.DRAFT else f"SX-CAV-{random_suffix(12)}",
        customer_id=customer.id,
        route_group=RouteGroup.CAV,
        booking_state=booking_state,
        operational_state=(
            OperationalState.CANCELLED
            if booking_state == BookingState.CANCELLED
            else OperationalState.IN_TRANSIT
        ),
        booking_date=now - timedelta(days=days_ago),
        cancelled_at=now - timedelta(days=days_ago - 1)
        if booking_state == BookingState.CANCELLED
        else None,
        is_demo_record=is_demo_record,
        rebooked_to_shipment_id=rebooked_to,
        rebooked_from_shipment_id=rebooked_from,
        package_count=1,
    )
    db.add(shipment)
    db.commit()
    return shipment
