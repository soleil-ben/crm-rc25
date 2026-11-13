"""The canonical tables, the shipment tables and the provider work are all untouched.

This module is the whole-surface version of the claim `test_account_registration.py` makes
about registration alone: **nothing a customer can do through this surface writes canonical
data** (OD-23, DEC-0092, T-07). It is asserted by driving every Customer Account route that
exists, against a database that already holds a customer, their shipments, their consent
history and their addresses, and then comparing every canonical table row by row.

The comparison is a row-level snapshot rather than a count, because a count would not notice
an update. A bug that rewrote a customer's phone number in place would leave the count
unchanged and the record wrong -- which is the exact failure OD-23 exists to prevent.

**Two sanctioned exceptions since fix pack 2.** FIELD_MATRIX §3.1 lets a linked customer
change their preferred language directly, and §4 lets them grant or withdraw marketing
consent (an append-only `consent_events` row). Those two routes are therefore not driven
here; `tests/test_account_profile.py` asserts exactly what each writes and nothing more,
and that a profile *proposal* changes no canonical row until a staff member approves it.

The second half asserts the Phase 4A invariants are unmoved: no provider adapter, empty
allowlists, `connected_api` still refused, integration health still `not_configured`, and no
external request from anywhere in this phase.
"""

from __future__ import annotations

import socket

from app.core.config import settings
from app.models import (
    ConsentEvent,
    ContactSuppression,
    Customer,
    CustomerAddress,
    CustomerIdentity,
    CustomerIdentityLink,
    Interaction,
    Shipment,
    ShipmentEvent,
    ShipmentPackage,
    Tag,
    User,
)
from tests.account_fixtures import (
    csrf_headers,
    register,
    registration,
    reset_token,
    sign_in,
)

ADDRESS = "hanh@demo.example.com"
REGISTER = "/api/v1/account/register"
RESEND = "/api/v1/account/verification/resend"
FORGOT = "/api/v1/account/password/forgot"
RESET = "/api/v1/account/password/reset"
VERIFY = "/api/v1/account/verify-email"
ME = "/api/v1/account/me"
SIGN_OUT = "/api/v1/account/sign-out"

#: Every table a customer must not be able to write through this surface.
CANONICAL_MODELS = (
    Customer,
    CustomerAddress,
    ConsentEvent,
    ContactSuppression,
    Shipment,
    ShipmentPackage,
    ShipmentEvent,
    Interaction,
    Tag,
    User,
)


def _snapshot(db) -> dict[str, list[tuple]]:
    """Every row of every canonical table, column by column.

    A count would miss an in-place update, which is the more likely bug: a registration that
    "helpfully" refreshed a matching customer's phone number leaves the count unchanged and
    the record wrong.
    """
    snapshot: dict[str, list[tuple]] = {}
    for model in CANONICAL_MODELS:
        columns = [column.name for column in model.__table__.columns]
        rows = db.query(model).order_by(model.id).all()
        snapshot[model.__tablename__] = [
            tuple(getattr(row, column) for column in columns) for row in rows
        ]
    return snapshot


def _populated(db):
    """A customer who looks exactly like the registrant, with history behind them."""
    from app.services import customer_service
    from tests.conftest import add_shipment

    customer = customer_service.create_customer(
        db,
        {
            "full_name": "Nguyễn Thị Bích Hạnh",
            "email": ADDRESS,
            "phone": "+84 90 123 4567",
            "country_code": "VN",
            "notes": "Prefers afternoon pickup",
        },
    )
    db.commit()
    add_shipment(db, customer, days_ago=20)
    add_shipment(db, customer, days_ago=5, delivered=True)
    db.add(
        ConsentEvent(
            customer_id=customer.id,
            channel="email",
            address_value=ADDRESS,
            status="granted",
            basis="explicit_optin",
            recorded_at=customer.created_at,
        )
    )
    db.commit()
    return customer


def _exercise_every_route(client, db, mail) -> None:
    """Drive all eight routes, including the failure paths.

    The failure paths matter as much as the successes: an exception handler that rolled back
    part of a transaction and left another part committed would show up here and nowhere
    else.
    """
    from app.core.security import rate_limiter

    register(client, email=ADDRESS)
    rate_limiter.reset()
    register(client, email=ADDRESS)  # existing address
    rate_limiter.reset()
    register(client, email="someone.new@demo.example.com")
    rate_limiter.reset()

    client.post(REGISTER, content=b"{bad", headers={"content-type": "application/json"})
    client.post(REGISTER, json=registration(customer={"internal_notes": "x"}))
    rate_limiter.reset()

    client.post(VERIFY, json={"token": "a" * 43})
    from tests.account_fixtures import verification_token

    client.post(VERIFY, json={"token": verification_token(mail, ADDRESS)})
    rate_limiter.reset()

    client.post(RESEND, json={"email": ADDRESS})
    client.post(RESEND, json={"email": "nobody@demo.example.com"})
    rate_limiter.reset()

    sign_in(client, ADDRESS, password="WrongPassword!2026")
    response = sign_in(client, ADDRESS)
    client.get(ME)
    client.post(SIGN_OUT, headers=csrf_headers(response))
    rate_limiter.reset()

    client.post(FORGOT, json={"email": ADDRESS})
    client.post(
        RESET,
        json={
            "token": reset_token(mail, ADDRESS),
            "password": "Replacement!2026",
            "password_confirmation": "Replacement!2026",
        },
    )
    client.post(
        RESET,
        json={
            "token": "a" * 43,
            "password": "Replacement!2026",
            "password_confirmation": "Replacement!2026",
        },
    )
    rate_limiter.reset()


# --- Canonical data -----------------------------------------------------------


def test_no_canonical_row_changes_when_every_route_is_exercised(
    account_client, account_db, captured_mail
):
    _populated(account_db)
    before = _snapshot(account_db)

    _exercise_every_route(account_client, account_db, captured_mail)

    account_db.expire_all()
    after = _snapshot(account_db)
    for table, rows in before.items():
        assert after[table] == rows, f"{table} changed"


def test_the_surface_creates_no_identity_link(account_client, account_db, captured_mail):
    """Linking is a staff act, and staff approval is Phase 10 (OD-24)."""
    _populated(account_db)
    _exercise_every_route(account_client, account_db, captured_mail)
    assert account_db.query(CustomerIdentityLink).count() == 0


def test_no_identity_reaches_active_through_any_route(account_client, account_db, captured_mail):
    """`active` is reachable only through an explicit staff action (AC-CA-4.1)."""
    _populated(account_db)
    _exercise_every_route(account_client, account_db, captured_mail)

    account_db.expire_all()
    for identity in account_db.query(CustomerIdentity).all():
        assert identity.status != "active"
        assert identity.approved_at is None
        assert identity.approved_by_user_id is None


def test_no_customer_row_gains_a_column_pointing_at_an_identity():
    """`DATA_MODEL.md` section 1: no existing table learns the account feature exists."""
    columns = {column.name for column in Customer.__table__.columns}
    assert "identity_id" not in columns
    assert "customer_identity_id" not in columns
    assert "account_id" not in columns

    for model in (Shipment, CustomerAddress, User):
        names = {column.name for column in model.__table__.columns}
        assert not [name for name in names if "identity" in name], model.__tablename__


def test_the_three_deferred_canonical_columns_landed_in_phase_10():
    """DEC-0096 deferred three columns; DEC-0101 is where the deferral ended.

    **This assertion was inverted in Phase 10, and the inversion is the point.** As written
    in Phase 9 it said `customers` has no `display_name` and no `legal_name`, and
    `AddressRole` has three members -- which was the owner's Phase 9 instruction, held as a
    schema fact so that nobody added a column quietly.

    The reason that instruction gave expired exactly when Phase 10 began: nothing in
    Phase 9 could *apply* a proposal, so a column added then would have been a column with
    no writer. Phase 10 applies one, and `FIELD_MATRIX.md` section 6 always expected the
    three to be decided in the phase that first did.

    So the test now asserts the resolution rather than the deferral, and it still asserts
    the shape of it: two nullable columns, one enum member, and **no** `is_billing` boolean
    -- because a billing address is a role, not a sender row with a flag (DEC-0101).

    See `docs/customer_account/SUPERSEDED_ASSERTIONS.md`, entry AS-03.
    """
    from app.core.enums import AddressRole

    columns = {column.name for column in Customer.__table__.columns}
    assert "display_name" in columns
    assert "legal_name" in columns
    for name in ("display_name", "legal_name"):
        column = Customer.__table__.columns[name]
        assert column.nullable is True, name
        assert column.default is None and column.server_default is None, name

    assert {role.value for role in AddressRole} == {"sender", "recipient", "both", "billing"}
    assert "is_billing" not in {column.name for column in CustomerAddress.__table__.columns}

    # And `full_name` is untouched: still required, still the contactable name.
    assert Customer.__table__.columns["full_name"].nullable is False


def test_the_submitted_values_are_still_carried_as_proposal_fields(
    account_client, account_db, captured_mail
):
    """Registration still writes them as proposal fields and still writes no customer.

    The columns exist now, and **registration still does not touch them**: a proposal is
    what a registration produces, and only an approval reaches `customers` (DEC-0092). The
    assertion is unchanged from Phase 9 for that reason -- what changed is where the values
    can *later* land, not where registration puts them.

    See `docs/customer_account/SUPERSEDED_ASSERTIONS.md`, entry AS-04.
    """
    from app.models import CustomerDataProposalField

    register(account_client, email=ADDRESS)
    keys = {row.field_key for row in account_db.query(CustomerDataProposalField).all()}
    assert "display_name" in keys
    assert "legal_name" in keys
    assert any(key.startswith("billing_address.") for key in keys)


# --- Provider work, and the RC baseline invariants ----------------------------


def test_no_provider_adapter_is_registered():
    from app.integrations.registry import PRODUCTION_ADAPTERS, is_any_provider_configured

    assert PRODUCTION_ADAPTERS == {}
    assert is_any_provider_configured() is False


def test_both_provider_resource_allowlists_are_still_empty():
    assert settings.integration_resource_host_list == []
    assert settings.integration_resource_path_prefix_list == []


def test_connected_api_is_still_refused_by_the_public_vocabulary():
    from app.schemas.public_tracking import TrackingState

    values = {state.value for state in TrackingState}
    assert "connected_api" not in values


def test_the_tracking_source_modes_are_unchanged():
    from app.core.enums import TrackingSourceMode

    assert TrackingSourceMode.MANUAL == "manual"
    assert TrackingSourceMode.EXTERNAL_LINK == "external_link"


def test_the_nine_provisional_carrier_link_hosts_are_unchanged():
    hosts = settings.public_carrier_link_host_list
    assert len(hosts) == 9
    assert hosts == [
        "www.ups.com",
        "www.fedex.com",
        "www.purolator.com",
        "www.canadapost-postescanada.ca",
        "www.dhl.com",
        "tools.usps.com",
        "www.usps.com",
        "vnpost.vn",
        "viettelpost.com.vn",
    ]


def test_no_customer_account_route_makes_an_external_request(
    account_client, account_db, captured_mail, monkeypatch
):
    """The baseline invariant, extended to the mail path (T-15)."""
    attempts: list[object] = []

    class Refusing(socket.socket):
        def __init__(self, *args, **kwargs):
            attempts.append(args)
            raise AssertionError("a Customer Account route opened a socket")

    monkeypatch.setattr(socket, "socket", Refusing)
    _exercise_every_route(account_client, account_db, captured_mail)
    assert attempts == []


def test_no_customer_account_module_names_uniuni_or_connected_api():
    """Instruction section 2: no UniUni, no carrier adapter, no `connected_api`."""
    import inspect
    from pathlib import Path

    from app.api.account import deps as account_deps
    from app.services import account_email_service, customer_auth_service, customer_identity_service

    sources = list(Path(inspect.getfile(account_deps)).parent.rglob("*.py"))
    sources += [
        Path(inspect.getfile(module))
        for module in (customer_identity_service, customer_auth_service, account_email_service)
    ]
    for path in sources:
        text = path.read_text(encoding="utf-8").lower()
        assert "uniuni" not in text, path.name
        assert "connected_api" not in text, path.name


def test_integration_health_still_reports_not_configured(account_client, account_db):
    """Untouched by this phase: no connection exists and no adapter could serve one."""
    from app.integrations.registry import is_any_provider_configured
    from app.models import IntegrationConnection

    assert account_db.query(IntegrationConnection).count() == 0
    assert is_any_provider_configured() is False
