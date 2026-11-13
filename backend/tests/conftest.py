"""Test fixtures.

Each test gets an isolated on-disk SQLite database created from the SQLAlchemy metadata
(the Alembic migration is exercised separately in ``test_migrations.py``), plus a client
that carries the session cookie and CSRF header the way the real frontend does.

``DATABASE_URL`` is set below, before any application module is imported, and that is
load-bearing -- see the comment on ``_MODULE_DATABASE``.
"""

from __future__ import annotations

import os
import tempfile
from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("SECRET_KEY", "test-only-secret")

# Where `app.core.db.engine` points during the test run.
#
# **Without this the backend suite opens the development database.** Not through a fixture
# and not through a route: `app/core/db.py` builds its module-level engine from
# `settings.database_url` at import, and with only `ENVIRONMENT` overridden that default is
# `data/solaris_crm.db`. Every `TestClient(app)` runs the lifespan, and the lifespan's
# readiness check queries that engine -- so the suite connected to the real development
# database once per app startup, a few thousand times a run.
#
# It never wrote anything, and the file's SHA-256 was identical before and after a full
# validation pass. It was still the development database being opened by an automated
# suite, which is the shape of the incident this whole area exists to prevent -- and
# `test_e2e_safety.py` was asserting the file did not *change* while this quietly made it
# the thing being read.
#
# Set here, before the imports below, because the engine is built at import time and a
# fixture would run too late. Written as a bare call rather than an assignment to keep the
# import block unbroken; the path is read back out of the settings once they exist.
# `tests/test_no_suite_opens_the_development_database.py` asserts the result rather than
# trusting this comment.
os.environ.setdefault(
    "DATABASE_URL",
    "sqlite:///"
    + (Path(tempfile.mkdtemp(prefix="solaris-test-engine-")) / "module-engine.db").as_posix(),
)

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.api.deps import db_session
from app.api.public.deps import public_db_session
from app.core.config import settings
from app.core.db import build_engine
from app.core.enums import BookingState, OperationalState, Role, RouteGroup
from app.core.security import rate_limiter
from app.core.time_utils import utcnow
from app.main import app
from app.models import Base, Customer, OrganizationSettings, Shipment, User
from app.services import auth_service
from app.services.identifier_service import random_suffix

TEST_PASSWORD = "TestPassword!2026"

#: Read back out of the settings, because it was set above before they existed.
_MODULE_DATABASE = Path(settings.database_url.removeprefix("sqlite:///"))


@pytest.fixture(scope="session", autouse=True)
def module_engine_database() -> Iterator[None]:
    """Give the module-level engine a schema, and take it away again afterwards.

    ``/health/ready`` reports ready only when the database is reachable *and* at the
    migration head, and `test_phase5b_startup_and_health.py` asserts it does. That
    assertion used to pass because the engine was pointed at the development database,
    which is migrated -- the test was reading the real thing to prove a health check
    worked. Now it reads this: an empty database created from the same metadata and
    stamped with the same head, so the check answers for a real reason.

    Stamped rather than migrated: ``_check_migrations_current`` compares the rows in
    ``alembic_version`` with the script directory's heads, and running the migrations here
    would add half a minute to every session to produce a schema ``create_all`` already
    built.
    """
    from alembic.config import Config
    from alembic.script import ScriptDirectory
    from sqlalchemy import text

    from app.core.config import BACKEND_ROOT
    from app.core.db import engine

    Base.metadata.create_all(engine)

    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    heads = ScriptDirectory.from_config(config).get_heads()

    with engine.begin() as connection:
        connection.execute(
            text("CREATE TABLE IF NOT EXISTS alembic_version (version_num VARCHAR(32) NOT NULL)")
        )
        connection.execute(text("DELETE FROM alembic_version"))
        for head in heads:
            connection.execute(
                text("INSERT INTO alembic_version (version_num) VALUES (:head)"),
                {"head": head},
            )

    try:
        yield
    finally:
        engine.dispose()
        import shutil  # noqa: PLC0415

        shutil.rmtree(_MODULE_DATABASE.parent, ignore_errors=True)


@pytest.fixture
def db_path(tmp_path) -> str:
    return f"sqlite:///{(tmp_path / 'test.db').as_posix()}"


@pytest.fixture
def engine(db_path):
    engine = build_engine(db_path)
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def session_factory(engine):
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


@pytest.fixture
def db(session_factory) -> Iterator[Session]:
    session = session_factory()
    session.add(OrganizationSettings())
    session.commit()
    yield session
    session.close()


@pytest.fixture
def client(session_factory, db) -> Iterator[TestClient]:
    rate_limiter.reset()

    def override_session() -> Iterator[Session]:
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[db_session] = override_session
    # The public surface has its own session dependency rather than reusing the staff
    # one, which is the point (app/api/public/deps.py). Both are pointed at the same test
    # database here so a single test can exercise a staff write and then the public read
    # of what it produced.
    app.dependency_overrides[public_db_session] = override_session
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def see_committed_changes(session: Session) -> None:
    """End this session's read transaction so the next query sees other connections' work.

    Since DEC-0108 a session holds its SQLite read snapshot from its **first statement**
    until it commits or rolls back. A test that reads, then drives an HTTP request that
    writes and commits on a *different* session, and then reads again, is re-reading the
    snapshot it opened before the request -- so the write is invisible and the assertion
    fails or, worse, passes for the wrong reason.

    ``expire_all()`` does not fix it: it discards cached *objects*, and the reload runs
    against the same snapshot. Ending the transaction is what is needed, and a rollback is
    the right way to do it here because the test session has nothing of its own pending --
    everything these tests set up is committed before the request goes out.

    Named rather than inlined so the reason travels with the call.
    """
    session.rollback()
    session.expire_all()


@pytest.fixture
def users(db) -> dict[str, User]:
    created = {}
    for role in Role:
        created[role.value] = auth_service.create_user(
            db,
            email=f"{role.value}@demo.example.com",
            full_name=f"Test {role.value.replace('_', ' ').title()}",
            password=TEST_PASSWORD,
            role=role.value,
        )
    db.commit()
    return created


def sign_in(client: TestClient, email: str, password: str = TEST_PASSWORD) -> str:
    """Sign in and return the CSRF token; the session cookie stays on the client."""
    response = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return response.json()["csrf_token"]


class ApiClient:
    """Small wrapper that always sends the CSRF header on state-changing requests."""

    def __init__(self, client: TestClient, csrf_token: str):
        self.client = client
        self.headers = {settings.csrf_header_name: csrf_token}

    def get(self, url, **kwargs):
        return self.client.get(url, **kwargs)

    def post(self, url, **kwargs):
        return self.client.post(url, headers=self.headers, **kwargs)

    def patch(self, url, **kwargs):
        return self.client.patch(url, headers=self.headers, **kwargs)

    def delete(self, url, **kwargs):
        return self.client.delete(url, headers=self.headers, **kwargs)


@pytest.fixture
def as_admin(client, users) -> ApiClient:
    return ApiClient(client, sign_in(client, users[Role.ADMIN].email))


@pytest.fixture
def api_for(client, users):
    def _factory(role: str) -> ApiClient:
        client.cookies.clear()
        return ApiClient(client, sign_in(client, users[role].email))

    return _factory


@pytest.fixture
def admin_is_tariff_approver(db, users) -> User:
    """Make the demo Admin the designated tariff approver (Phase 13H, OD-76).

    Since 13H only an approver may activate a tariff version over HTTP; by default the
    approver is the owner's real address, which no test user has.
    """
    from app.services import tariff_intake_service

    admin = users[Role.ADMIN]
    tariff_intake_service.update_settings(db, approver_emails=[admin.email], actor=None)
    db.commit()
    return admin


def make_customer(db: Session, **overrides) -> Customer:
    from app.services import customer_service

    payload = {
        "full_name": "Test Customer",
        "email": "test.customer@demo.example.com",
        "phone": "+1 416 555 0100",
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
    route_group: str = RouteGroup.CAV,
    booking_state: str = BookingState.CONFIRMED,
    handoff: bool = True,
    cancelled: bool = False,
    is_return: bool = False,
    delivered: bool = False,
    currency: str | None = None,
    selling_amount: float | None = None,
    shipping_cost: float | None = None,
) -> Shipment:
    now = utcnow()
    shipment = Shipment(
        # `random_suffix`, not `uuid4().hex`. Hex has no `0` and no `1` in the
        # unambiguous alphabet the real generator draws from, so a uuid-derived suffix
        # fails `SHIPMENT_PATTERN` about four times in five. A shipment whose reference
        # the public parser rejects can be listed but never opened, and a test that
        # fetches one by reference then passes only when the dice land right (DEC-0117).
        public_id=None
        if booking_state == BookingState.DRAFT
        else f"SX-{route_group}-{random_suffix(12)}",
        customer_id=customer.id,
        route_group=route_group,
        booking_state=booking_state,
        operational_state=(
            OperationalState.DELIVERED if delivered else OperationalState.IN_TRANSIT
        ),
        booking_date=now - timedelta(days=days_ago + 1),
        first_handoff_at=now - timedelta(days=days_ago) if handoff else None,
        delivered_at=now - timedelta(days=max(0, days_ago - 5)) if delivered else None,
        cancelled_at=now - timedelta(days=days_ago - 1) if cancelled else None,
        is_return=is_return,
        package_count=1,
        currency=currency,
        selling_amount=selling_amount,
        shipping_cost=shipping_cost,
    )
    db.add(shipment)
    db.commit()
    return shipment


# --- Phase 2 helpers ------------------------------------------------------

VN_ADDRESS = {
    "name": "Nguyễn Thị Bích Hạnh",
    "phone_entered": "+84 90 123 4567",
    "address_line1": "125 Đường Nguyễn Huệ",
    "city": "Thành phố Hồ Chí Minh",
    "province_state": "Hồ Chí Minh",
    "postal_code": "700000",
    "country_code": "VN",
}

CA_ADDRESS = {
    "name": "Tran Quoc Tuan",
    "phone_entered": "+1 416 555 0188",
    "address_line1": "4120 Dixie Road",
    "city": "Mississauga",
    "province_state": "ON",
    "postal_code": "L4W 1V2",
    "country_code": "CA",
}

US_ADDRESS = {
    "name": "Dana Whitfield",
    "phone_entered": "+1 206 555 0143",
    "address_line1": "900 Pike Street",
    "city": "Seattle",
    "province_state": "WA",
    "postal_code": "98101",
    "country_code": "US",
}

ADDRESS_BY_COUNTRY = {"VN": VN_ADDRESS, "CA": CA_ADDRESS, "US": US_ADDRESS}

# Origin and destination country for each launch route group.
ROUTE_ENDPOINTS = {
    RouteGroup.VCA: ("VN", "CA"),
    RouteGroup.CAV: ("CA", "VN"),
    RouteGroup.CAD: ("CA", "CA"),
    RouteGroup.XUS: ("CA", "US"),
}


def draft_payload(customer, route_group: str = RouteGroup.CAV, packages: int = 1, **overrides):
    """A complete, confirmable draft booking payload."""
    origin, destination = ROUTE_ENDPOINTS[route_group]
    payload = {
        "customer_id": customer.id,
        "route_group": route_group,
        "service_type": "standard_parcel",
        "transport_mode": "air",
        "contents_description": "Gift parcel: dried fruit, clothing, vitamins",
        "sender": dict(ADDRESS_BY_COUNTRY[origin]),
        "recipient": dict(ADDRESS_BY_COUNTRY[destination]),
        "packages": [
            {
                "length_value": "40",
                "width_value": "30",
                "height_value": "20",
                "dimension_unit": "cm",
                "weight_value": "5.5",
                "weight_unit": "kg",
                "contents_summary": f"Carton {index + 1}",
            }
            for index in range(packages)
        ],
    }
    payload.update(overrides)
    return payload


def make_draft(
    db: Session, customer, route_group: str = RouteGroup.CAV, packages: int = 1, **overrides
):
    """Create a draft through the service, exactly as the API route does."""
    from app.services import booking_service

    shipment = booking_service.create_draft(
        db, draft_payload(customer, route_group, packages, **overrides)
    )
    db.commit()
    return shipment


def confirm_draft(db: Session, shipment, key: str = "test-key-0001", actor=None):
    from app.core.db import commit_with_retry
    from app.services import booking_service

    result = booking_service.confirm_booking(
        db, shipment_id=shipment.id, idempotency_key=key, actor=actor
    )
    commit_with_retry(db)
    db.refresh(result.shipment)
    return result


def booked_shipment(
    db: Session,
    customer,
    route_group: str = RouteGroup.CAV,
    packages: int = 1,
    key: str | None = None,
):
    """A confirmed booking with a permanent Solaris ID and package references."""
    shipment = make_draft(db, customer, route_group, packages)
    confirm_draft(db, shipment, key or f"key-{uuid4().hex[:12]}")
    return shipment


# --- Phase 9: Customer Account --------------------------------------------
#
# A separate database and a separate client from the staff fixtures above, because several
# Customer Account tests exist precisely to present one surface's cookie to another. Only a
# fixture a test requests is ever built, so `captured_mail` stays opt-in and every other
# suite keeps the null transport.


@pytest.fixture
def account_engine(tmp_path):
    engine = build_engine(f"sqlite:///{(tmp_path / 'account.db').as_posix()}")
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def account_session_factory(account_engine):
    return sessionmaker(bind=account_engine, autoflush=False, expire_on_commit=False, future=True)


@pytest.fixture
def account_db(account_session_factory) -> Iterator[Session]:
    session = account_session_factory()
    session.add(OrganizationSettings())
    session.commit()
    yield session
    session.close()


@pytest.fixture
def account_client(account_session_factory, account_db) -> Iterator[TestClient]:
    """A client whose three surfaces share one test database.

    All three dependency overrides are installed -- staff, public and account -- because
    the isolation tests present one surface's cookie to another and prove it authenticates
    nothing. That only means something if both surfaces are reachable and backed by the
    same data.
    """
    from app.api.account.deps import account_db_session

    rate_limiter.reset()

    def override() -> Iterator[Session]:
        session = account_session_factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[db_session] = override
    app.dependency_overrides[public_db_session] = override
    app.dependency_overrides[account_db_session] = override
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
    rate_limiter.reset()


@pytest.fixture
def captured_mail(tmp_path):
    """Install the capture transport for one test, then put the null one back.

    Opt-in, and restored afterwards, so no other suite inherits a transport that writes
    files. The directory is a pytest temporary path, never the configured development one.
    """
    from app.services import account_email_service

    transport = account_email_service.CaptureEmailTransport(tmp_path / "mail")
    account_email_service.set_transport(transport)
    yield transport
    account_email_service.reset_transport()


@pytest.fixture
def account_users(account_db) -> dict[str, User]:
    """Staff accounts in the **account** test database.

    The `users` fixture above writes to the staff `db`, which is a different SQLite file.
    The cross-surface isolation tests need a real staff user and a real customer identity in
    *one* database, because "a staff cookie authenticates nothing on a customer route" would
    otherwise pass for the wrong reason -- the staff session simply would not exist.
    """
    created = {}
    for role in Role:
        created[role.value] = auth_service.create_user(
            account_db,
            email=f"{role.value}@demo.example.com",
            full_name=f"Test {role.value.replace('_', ' ').title()}",
            password=TEST_PASSWORD,
            role=role.value,
        )
    account_db.commit()
    return created


def shown_tax(lines, rate, mode):
    """The GST/HST the draft invoice screen showed beside the ticked box, which a save
    changing the lines, the rate or the mode echoes (RC-UAT-19 review, 2026-10-22)."""
    from decimal import Decimal

    from app.services import invoice_draft_service

    # Line by line (DEC-0235), as the screen and the server work it out.
    total = invoice_draft_service.totals(
        [Decimal(str(x["amount_cad"])) for x in lines], rate, mode
    )[2]
    return {
        "confirmed_total_cad": str(total),
        "confirmed_tax_mode": mode,
        "confirmed_tax_rate_percent": rate,
    }
