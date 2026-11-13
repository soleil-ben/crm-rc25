"""Who may review, who may decide, and what a denied request leaves behind.

``tests/test_route_permissions.py`` already sweeps every guarded route against every role
and picked these up the day they were mounted. It asserts the permission layer answered.
It does **not** assert which permissions each route asked for, that the right roles hold
them, that a Customer Account cookie authenticates nothing here, or that a refused request
wrote nothing. Those are this module's four claims.

The fourth is the one a permission test usually omits. "403" is a status code; "and the
database is unchanged" is the property. A route that checked its permission *after* doing
its work would pass the first and fail the second.
"""

from __future__ import annotations

from fastapi.routing import APIRoute

from app.core.config import settings
from app.core.enums import Role
from app.core.permissions import ROLE_PERMISSIONS, Permission
from app.main import app
from app.models import (
    AuditEvent,
    Customer,
    CustomerAccountApprovalAttempt,
    CustomerAccountDisclosureAcknowledgement,
    CustomerDataProposal,
    CustomerIdentity,
    CustomerIdentityLink,
)
from tests.account_fixtures import sign_in as customer_sign_in
from tests.approval_fixtures import BASE, key, make_customer, pending_identity, staff

IDENTITIES = "/api/v1/customer-account/identities"

READ = Permission.CUSTOMER_ACCOUNT_REVIEW
APPROVE = Permission.CUSTOMER_ACCOUNT_APPROVE
DEACTIVATE = Permission.CUSTOMER_ACCOUNT_DEACTIVATE

#: Every route this phase adds, with the permissions it must declare.
EXPECTED = {
    ("GET", "/api/v1/customer-account/registrations"): {READ},
    ("GET", "/api/v1/customer-account/registrations/{account_reference}"): {READ},
    (
        "GET",
        "/api/v1/customer-account/registrations/{account_reference}/duplicate-candidates",
    ): {READ},
    ("GET", "/api/v1/customer-account/registrations/{account_reference}/preview"): {READ},
    (
        "POST",
        "/api/v1/customer-account/registrations/{account_reference}/disclosure-acknowledgement",
    ): {READ, APPROVE},
    (
        "POST",
        "/api/v1/customer-account/registrations/{account_reference}/approve/create-new",
    ): {READ, APPROVE},
    (
        "POST",
        "/api/v1/customer-account/registrations/{account_reference}/approve/link-existing",
    ): {READ, APPROVE},
    ("POST", "/api/v1/customer-account/registrations/{account_reference}/reject"): {
        READ,
        APPROVE,
    },
    # Sprint 13 Lane A, A-1 (fix pack of 2026-10-14): the identity lifecycle routes.
    ("GET", "/api/v1/customer-account/identities/{account_reference}"): {READ},
    ("POST", "/api/v1/customer-account/identities/{account_reference}/suspend"): {
        READ,
        APPROVE,
    },
    ("POST", "/api/v1/customer-account/identities/{account_reference}/reinstate"): {
        READ,
        APPROVE,
    },
    # UAT round 4 (DEC-0126, DEC-0131): deactivation, Admin-only, so not `approve`.
    ("POST", "/api/v1/customer-account/identities/{account_reference}/deactivate"): {
        READ,
        DEACTIVATE,
    },
    # RC-UAT-21 Phase B: reinstating a deactivated account, Admin-only like deactivation.
    ("GET", "/api/v1/customer-account/identities-deactivated"): {READ, DEACTIVATE},
    ("POST", "/api/v1/customer-account/identities/{account_reference}/reactivate"): {
        READ,
        DEACTIVATE,
    },
    # RC-UAT-22 (B-13): re-link or close an orphaned account, Admin-only like reinstatement.
    ("GET", "/api/v1/customer-account/identities-orphaned"): {READ, DEACTIVATE},
    ("GET", "/api/v1/customer-account/identities/{account_reference}/relink-preview"): {
        READ,
        DEACTIVATE,
    },
    ("POST", "/api/v1/customer-account/identities/{account_reference}/relink"): {
        READ,
        DEACTIVATE,
    },
    ("POST", "/api/v1/customer-account/identities/{account_reference}/close-orphan"): {
        READ,
        DEACTIVATE,
    },
    # RC-UAT-25 item 2 (Ben, 2026-10-25): only an Admin changes a sign-in email.
    ("POST", "/api/v1/customer-account/identities/{account_reference}/sign-in-email"): {
        READ,
        DEACTIVATE,
    },
    # Fix pack 2: post-approval profile-change review (FIELD_MATRIX.md §5).
    ("GET", "/api/v1/customer-account/profile-proposals"): {READ},
    ("GET", "/api/v1/customer-account/identities/{account_reference}/profile-proposal"): {READ},
    (
        "POST",
        "/api/v1/customer-account/identities/{account_reference}/profile-proposal/decide",
    ): {READ, APPROVE},
}


def _walk(obj, prefix: str = ""):
    routes = getattr(obj, "routes", None)
    if routes is None and hasattr(obj, "original_router"):
        context = getattr(obj, "include_context", None)
        yield from _walk(obj.original_router, prefix + (getattr(context, "prefix", "") or ""))
        return
    for route in routes or []:
        if isinstance(route, APIRoute):
            yield prefix + route.path, route
        elif hasattr(route, "original_router") or hasattr(route, "routes"):
            yield from _walk(route, prefix)


def _declared(route: APIRoute) -> frozenset[str]:
    found: set[str] = set()
    stack = [route.dependant]
    while stack:
        dependant = stack.pop()
        for sub in dependant.dependencies:
            declared = getattr(sub.call, "required_permissions", None)
            if declared:
                found |= set(declared)
            stack.append(sub)
    return frozenset(found)


def test_every_route_declares_exactly_the_permissions_it_should():
    """Read routes ask for read; every mutation asks for **both**.

    Asking for both on a mutation is what keeps the two meaningful: the approve
    permission cannot be granted to somebody who may not look at what they are approving,
    and holding read alone reaches nothing that decides.
    """
    found = {}
    for path, route in _walk(app):
        if "/customer-account/" not in path and not path.endswith("/customer-account"):
            continue
        for method in sorted(route.methods - {"HEAD", "OPTIONS"}):
            found[(method, path)] = set(_declared(route))

    assert found == EXPECTED, found


def test_only_admin_and_operations_hold_the_two_permissions():
    """OD-24, read off the matrix rather than out of a document."""
    for permission in (READ, APPROVE):
        holders = {role for role, granted in ROLE_PERMISSIONS.items() if permission in granted}
        assert holders == {Role.ADMIN, Role.OPERATIONS}, (permission, holders)

    for role in (Role.MARKETING, Role.READ_ONLY_MANAGER):
        assert READ not in ROLE_PERMISSIONS[role]
        assert APPROVE not in ROLE_PERMISSIONS[role]


def test_only_admin_holds_deactivate():
    """DEC-0126: deactivation is Admin's alone. Operations approves and suspends, no more."""
    holders = {role for role, granted in ROLE_PERMISSIONS.items() if DEACTIVATE in granted}
    assert holders == {Role.ADMIN}


def test_duplicate_review_alone_reaches_none_of_it():
    """The distinction the instruction insists on, asserted as a fact about the matrix.

    Marketing and the read-only manager both hold ``duplicate:review``. Deciding whether
    two records are one person and deciding whether a person with a password may read a
    customer's shipment history are related powers and different ones.
    """
    for role in (Role.MARKETING, Role.READ_ONLY_MANAGER):
        assert Permission.DUPLICATE_REVIEW in ROLE_PERMISSIONS[role]
        assert READ not in ROLE_PERMISSIONS[role]


def _snapshot(session) -> tuple[int, ...]:
    return (
        session.query(Customer).count(),
        session.query(CustomerIdentityLink).count(),
        session.query(CustomerAccountApprovalAttempt).count(),
        session.query(CustomerAccountDisclosureAcknowledgement).count(),
        session.query(CustomerDataProposal).filter_by(status="approved").count(),
        session.query(CustomerIdentity).filter_by(status="active").count(),
    )


def _every_call(api, reference: str, customer_reference: str):
    return [
        ("read", api.get(BASE)),
        ("read", api.get(f"{BASE}/{reference}")),
        ("read", api.get(f"{BASE}/{reference}/duplicate-candidates")),
        (
            "read",
            api.get(f"{BASE}/{reference}/preview", params={"action": "create_new"}),
        ),
        (
            "write",
            api.post(
                f"{BASE}/{reference}/disclosure-acknowledgement",
                json={
                    "action": "create_new",
                    "customer_public_id": None,
                    "fingerprint": "0" * 64,
                },
            ),
        ),
        (
            "write",
            api.post(
                f"{BASE}/{reference}/approve/create-new",
                json={"preview_fingerprint": "0" * 64, "idempotency_key": key()},
            ),
        ),
        (
            "write",
            api.post(
                f"{BASE}/{reference}/approve/link-existing",
                json={
                    "customer_public_id": customer_reference,
                    "preview_fingerprint": "0" * 64,
                    "idempotency_key": key(),
                },
            ),
        ),
        (
            "write",
            api.post(
                f"{BASE}/{reference}/reject",
                json={"reason_code": "abuse_or_test", "idempotency_key": key()},
            ),
        ),
        ("read", api.get(f"{IDENTITIES}/{reference}")),
        (
            "write",
            api.post(f"{IDENTITIES}/{reference}/suspend", json={"reason_code": "staff_review"}),
        ),
        (
            "write",
            api.post(
                f"{IDENTITIES}/{reference}/reinstate", json={"reason_code": "review_complete"}
            ),
        ),
    ]


def test_marketing_and_the_read_only_manager_are_refused_everywhere(
    account_client, account_db, account_users, captured_mail
):
    reference = pending_identity(account_client, captured_mail, "hanh@demo.example.com")
    customer = make_customer(account_db, email="target@demo.example.com")
    account_db.expire_all()
    before = _snapshot(account_db)

    for role in (Role.MARKETING, Role.READ_ONLY_MANAGER):
        api = staff(account_client, account_users[role].email)
        for _kind, response in _every_call(api, reference, customer.public_id):
            assert response.status_code == 403, (role, response.request.url, response.text)

    account_db.expire_all()
    assert _snapshot(account_db) == before


def test_an_unauthenticated_caller_is_refused_everywhere(
    account_client, account_db, account_users, captured_mail
):
    """401, not 403: a 403 would say the caller was authenticated."""
    reference = pending_identity(account_client, captured_mail, "hanh@demo.example.com")
    customer = make_customer(account_db, email="target@demo.example.com")
    account_db.expire_all()
    before = _snapshot(account_db)

    account_client.cookies.clear()

    class _Anonymous:
        def __init__(self, client):
            self.client = client

        def get(self, url, **kwargs):
            return self.client.get(url, **kwargs)

        def post(self, url, **kwargs):
            return self.client.post(url, **kwargs)

    api = _Anonymous(account_client)
    for _kind, response in _every_call(api, reference, customer.public_id):
        assert response.status_code == 401, (response.request.url, response.text)

    account_db.expire_all()
    assert _snapshot(account_db) == before


def test_a_customer_account_cookie_authenticates_nothing_here(
    account_client, account_db, account_users, captured_mail
):
    """T-01 and T-12, in the direction Phase 10 newly makes interesting.

    The customer's own cookie is presented to the routes that could activate their
    account. It resolves nothing: the staff resolver reads ``user_sessions`` and a
    customer session is a row in ``customer_sessions``. **401, never 403** -- a 403 would
    tell the caller they had been authenticated and merely lacked a permission.
    """
    reference = pending_identity(account_client, captured_mail, "hanh@demo.example.com")
    customer = make_customer(account_db, email="target@demo.example.com")
    account_db.expire_all()
    before = _snapshot(account_db)

    account_client.cookies.clear()
    signed_in = customer_sign_in(account_client, "hanh@demo.example.com")
    assert signed_in.status_code == 200
    # The customer realm's CSRF header too, in case a route looked for the wrong one.
    headers = {settings.account_csrf_header_name: signed_in.json()["csrf_token"]}

    class _AsCustomer:
        def __init__(self, client):
            self.client = client

        def get(self, url, **kwargs):
            return self.client.get(url, headers=headers, **kwargs)

        def post(self, url, **kwargs):
            return self.client.post(url, headers=headers, **kwargs)

    api = _AsCustomer(account_client)
    for _kind, response in _every_call(api, reference, customer.public_id):
        assert response.status_code == 401, (response.request.url, response.text)

    account_db.expire_all()
    assert _snapshot(account_db) == before


def test_a_staff_cookie_authenticates_nothing_on_the_customer_surface(
    account_client, account_users, captured_mail
):
    """The other direction, re-asserted now that a staff session can activate an account."""
    pending_identity(account_client, captured_mail, "hanh@demo.example.com")
    staff(account_client, account_users[Role.ADMIN].email)
    assert account_client.get("/api/v1/account/me").status_code == 401


def test_admin_and_operations_both_reach_the_review_routes(
    account_client, account_db, account_users, captured_mail
):
    """The positive half. OD-24: Operations approves, Admin may override."""
    reference = pending_identity(account_client, captured_mail, "hanh@demo.example.com")
    for role in (Role.OPERATIONS, Role.ADMIN):
        api = staff(account_client, account_users[role].email)
        assert api.get(BASE).status_code == 200
        assert api.get(f"{BASE}/{reference}").status_code == 200
        assert api.get(f"{BASE}/{reference}/duplicate-candidates").status_code == 200
        assert (
            api.get(f"{BASE}/{reference}/preview", params={"action": "create_new"}).status_code
            == 200
        )


def test_a_refused_decision_writes_no_audit_row_about_the_applicant(
    account_client, account_db, account_users, captured_mail
):
    """A denial is a staff-authorization event, not an access to the application.

    Marketing being refused must not produce a row that reads as though Marketing looked
    at somebody's registration.
    """
    reference = pending_identity(account_client, captured_mail, "hanh@demo.example.com")
    # Counted *after* the sign-in, which legitimately writes its own staff auth event.
    api = staff(account_client, account_users[Role.MARKETING].email)
    account_db.expire_all()
    before = account_db.query(AuditEvent).count()

    assert api.get(f"{BASE}/{reference}").status_code == 403

    account_db.expire_all()
    assert account_db.query(AuditEvent).count() == before
    # And specifically none of the review actions, which are the ones that would read as
    # "Marketing opened this person's application".
    assert (
        account_db.query(AuditEvent)
        .filter(AuditEvent.action == "customer_account.registration_opened")
        .count()
        == 0
    )
