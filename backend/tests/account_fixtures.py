"""Shared helpers and sample payloads for the Customer Account suites.

The *fixtures* live in ``conftest.py``, where pytest finds them by name; only a fixture a
test actually requests is ever built, so the opt-in capture transport stays opt-in. What
lives here is the things a test calls rather than requests: the sample registration body,
the request helpers, and the two functions that pull a single-use link out of a captured
message.

The default transport everywhere remains the **null** one. A test that wants to read a
message requests ``captured_mail``.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.core.config import settings
from app.services import account_email_service as email

#: A customer password that satisfies the twelve-character minimum and is not in the
#: common-password list. Used everywhere so a failure is never about the password policy.
ACCOUNT_PASSWORD = "SolarisCustomer!2026"

#: A complete, acceptable registration body. Tests copy it and change one thing, so a
#: failure points at the thing they changed.
REGISTRATION_BODY: dict = {
    "email": "hanh@demo.example.com",
    "password": ACCOUNT_PASSWORD,
    "password_confirmation": ACCOUNT_PASSWORD,
    "accept_terms": True,
    "accept_privacy": True,
    # This body carries its own billing address, so it says so: the API's default is
    # "the same as the address above" since UAT round 12 (DEC-0166).
    "billing_same_as_shipping": False,
    "customer": {
        "customer_type": "individual",
        "legal_name": "Nguyễn Thị Bích Hạnh",
        "display_name": "Hạnh",
        "primary_contact_name": "Nguyễn Thị Bích Hạnh",
        "phone_country_code": "VN",
        "phone": "0901234567",
        "preferred_language": "en",
        "marketing_consent": True,
        "billing_address.address_line1": "125 Đường Nguyễn Huệ",
        "billing_address.city": "Thành phố Hồ Chí Minh",
        "billing_address.province_state": "Hồ Chí Minh",
        "billing_address.postal_code": "700000",
        "billing_address.country_code": "VN",
        "pickup_address.1.contact_name": "Tran Quoc Tuan",
        "pickup_address.1.address_line1": "4120 Dixie Road",
        "pickup_address.1.city": "Mississauga",
        "pickup_address.1.province_state": "ON",
        "pickup_address.1.postal_code": "L4W 1V2",
        "pickup_address.1.country_code": "CA",
    },
    "notification_topics": ["shipment_milestones"],
}


#: A complete address registration accepts: the four required parts (UAT rounds 9 and 11)
#: and a postal code, which is optional since round 11. A test that replaces ``customer``
#: adds this and ``billing_same_as_shipping=True``.
REQUIRED_ADDRESS: dict = {
    "pickup_address.1.country_code": "CA",
    "pickup_address.1.address_line1": "4120 Dixie Road",
    "pickup_address.1.city": "Mississauga",
    "pickup_address.1.province_state": "ON",
    "pickup_address.1.postal_code": "L4W 1V2",
}


def registration(**overrides) -> dict:
    """A registration body with a fresh idempotency key unless one is given.

    The key is fresh by default because most tests are about something other than
    idempotency, and reusing one silently would make the second registration in a test a
    replay rather than the new request the test meant to make.
    """
    body = {
        key: dict(value) if isinstance(value, dict) else value
        for key, value in REGISTRATION_BODY.items()
    }
    body.setdefault("idempotency_key", None)
    # A test that changes the password means the person typed it twice (UAT round 8).
    if "password" in overrides and "password_confirmation" not in overrides:
        body["password_confirmation"] = overrides["password"]
    body.update(overrides)
    if body.get("idempotency_key") is None:
        import uuid

        body["idempotency_key"] = uuid.uuid4().hex
    return body


def verification_token(mail: email.CaptureEmailTransport, to_email: str) -> str:
    """Pull the single-use link out of the most recent verification message.

    Reading the token from the message rather than from the database is deliberate: it
    proves the plaintext really does reach the recipient and really is the value the
    endpoint accepts, which a database read would assume.
    """
    return _token_from(mail, email.TEMPLATE_VERIFY_EMAIL, to_email)


def reset_token(mail: email.CaptureEmailTransport, to_email: str) -> str:
    return _token_from(mail, email.TEMPLATE_PASSWORD_RESET, to_email)


def _token_from(mail: email.CaptureEmailTransport, template_key: str, to_email: str) -> str:
    for message in reversed(mail.messages):
        if message["template_key"] == template_key and message["to_email"].lower() == to_email:
            return message["body"].split("token=")[1].split()[0]
    raise AssertionError(f"no {template_key} message captured for {to_email}")


def register(client: TestClient, **overrides):
    return client.post("/api/v1/account/register", json=registration(**overrides))


def verify(client: TestClient, token: str):
    return client.post("/api/v1/account/verify-email", json={"token": token})


def sign_in(client: TestClient, email_address: str, password: str = ACCOUNT_PASSWORD):
    return client.post(
        "/api/v1/account/sign-in", json={"email": email_address, "password": password}
    )


def csrf_headers(sign_in_response) -> dict[str, str]:
    return {settings.account_csrf_header_name: sign_in_response.json()["csrf_token"]}


def registered_and_verified(
    client: TestClient, mail: email.CaptureEmailTransport, email_address: str | None = None
) -> str:
    """Register, read the link, verify. Returns the address, which is ``pending_approval``.

    This is as far as Phase 9 goes on purpose: the identity is verified and **still
    pending**, with no link and no shipment access, because approval is a staff act and
    staff approval is Phase 10.
    """
    address = email_address or REGISTRATION_BODY["email"]
    response = register(client, email=address)
    assert response.status_code == 200, response.text
    verify(client, verification_token(mail, address)).raise_for_status()
    return address
