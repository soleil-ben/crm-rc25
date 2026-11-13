"""AC-2: server-side authorization cannot be bypassed by calling an endpoint directly."""

from __future__ import annotations

import pytest

from app.core.config import settings
from app.core.enums import Role
from app.core.permissions import ROLE_PERMISSIONS, Permission
from tests.conftest import make_customer


def test_unauthenticated_requests_are_rejected(client):
    assert client.get("/api/v1/customers").status_code == 401
    assert client.get("/api/v1/dashboard/summary").status_code == 401
    assert client.post("/api/v1/customers", json={"full_name": "x"}).status_code == 401


@pytest.mark.parametrize(
    "role",
    [Role.OPERATIONS, Role.MARKETING, Role.READ_ONLY_MANAGER],
)
def test_non_admin_roles_cannot_export_customers(api_for, db, role):
    make_customer(db)
    api = api_for(role.value)
    response = api.get("/api/v1/exports/customers.csv")
    assert response.status_code == 403
    assert response.json()["code"] == "permission_denied"


def test_admin_can_export_customers(as_admin, db):
    make_customer(db)
    response = as_admin.get("/api/v1/exports/customers.csv")
    assert response.status_code == 200
    assert "STCA-000001" in response.text


@pytest.mark.parametrize("role", [Role.MARKETING])
def test_roles_without_financial_permission_cannot_read_financials(api_for, db, role):
    customer = make_customer(db)
    api = api_for(role.value)
    assert api.get(f"/api/v1/customers/{customer.id}/financials").status_code == 403


def test_operations_may_read_financials_since_the_role_merge(api_for, db):
    """The merged Operations role carries Customer service's financial:read (DEC-0088).

    Recorded as its own test rather than by deleting the one above, because this is the
    permission the merge actually widened and it should fail loudly if it is taken away.
    """
    customer = make_customer(db)
    api = api_for(Role.OPERATIONS.value)
    assert api.get(f"/api/v1/customers/{customer.id}/financials").status_code == 200


def test_read_only_manager_sees_revenue_but_not_costs(api_for, db):
    from tests.conftest import add_shipment

    customer = make_customer(db)
    add_shipment(db, customer, days_ago=5, currency="CAD", selling_amount=200, shipping_cost=90)

    api = api_for(Role.READ_ONLY_MANAGER.value)
    response = api.get(f"/api/v1/customers/{customer.id}/financials")
    assert response.status_code == 200
    body = response.json()
    assert body["includes_costs"] is False
    assert body["by_currency"][0]["recorded_cost"] is None
    assert body["by_currency"][0]["gross_profit"] is None


def test_admin_sees_costs(as_admin, db):
    from tests.conftest import add_shipment

    customer = make_customer(db)
    add_shipment(db, customer, days_ago=5, currency="CAD", selling_amount=200, shipping_cost=90)
    body = as_admin.get(f"/api/v1/customers/{customer.id}/financials").json()
    assert body["includes_costs"] is True
    assert float(body["by_currency"][0]["recorded_cost"]) == 90.0
    assert float(body["by_currency"][0]["gross_profit"]) == 110.0


def test_read_only_manager_cannot_write(api_for, db):
    customer = make_customer(db)
    api = api_for(Role.READ_ONLY_MANAGER.value)
    assert (
        api.post(
            "/api/v1/customers", json={"full_name": "New", "phone": "+1 416 555 0199"}
        ).status_code
        == 403
    )
    assert (
        api.patch(f"/api/v1/customers/{customer.id}", json={"city": "Toronto"}).status_code == 403
    )


def test_operations_can_manage_consent_and_segments_since_the_role_merge(api_for, db):
    """Reversed by DEC-0088. Operations absorbed Customer service, which held both.

    The read-only manager below is what still guards the boundary: holding a role that
    can work customers is not the same as holding one that can author segments.
    """
    customer = make_customer(db)
    api = api_for(Role.OPERATIONS.value)
    assert api.get(f"/api/v1/customers/{customer.id}/consent").status_code == 200
    assert (
        api.post(
            "/api/v1/segments",
            json={
                "name": "Ops segment",
                "definition": {
                    "match": "all",
                    "conditions": [{"field": "is_archived", "operator": "is", "value": False}],
                },
            },
        ).status_code
        == 201
    )


def test_the_read_only_manager_still_cannot_manage_consent_or_segments(api_for, db):
    api = api_for(Role.READ_ONLY_MANAGER.value)
    assert (
        api.post(
            "/api/v1/segments",
            json={
                "name": "Manager segment",
                "definition": {
                    "match": "all",
                    "conditions": [{"field": "is_archived", "operator": "is", "value": False}],
                },
            },
        ).status_code
        == 403
    )


def test_non_admin_cannot_manage_staff_or_settings(api_for):
    api = api_for(Role.OPERATIONS.value)
    assert api.get("/api/v1/staff").status_code == 403
    assert api.patch("/api/v1/settings", json={"lifecycle_new_days": 10}).status_code == 403
    assert (
        api.post(
            "/api/v1/staff",
            json={
                "email": "sneaky@demo.example.com",
                "full_name": "Sneaky",
                "password": "LongEnoughPassword1",
                "role": "admin",
            },
        ).status_code
        == 403
    )


def test_non_admin_cannot_merge_customers(api_for, db):
    first = make_customer(db, full_name="A", email="a@demo.example.com")
    second = make_customer(db, full_name="B", email="b@demo.example.com")
    api = api_for(Role.OPERATIONS.value)
    response = api.post(
        "/api/v1/customers/merge",
        json={
            "source_customer_id": first.id,
            "target_customer_id": second.id,
            "confirmation": first.public_id,
        },
    )
    assert response.status_code == 403


def test_state_changing_request_without_csrf_header_is_rejected(client, users):
    from tests.conftest import sign_in

    sign_in(client, users[Role.ADMIN].email)
    # Cookie is present, CSRF header is not.
    response = client.post(
        "/api/v1/customers", json={"full_name": "No CSRF", "phone": "+1 416 555 0111"}
    )
    assert response.status_code == 403
    assert "security token" in response.json()["message"].lower()


def test_wrong_csrf_token_is_rejected(client, users):
    from tests.conftest import sign_in

    sign_in(client, users[Role.ADMIN].email)
    response = client.post(
        "/api/v1/customers",
        json={"full_name": "Wrong CSRF", "phone": "+1 416 555 0112"},
        headers={settings.csrf_header_name: "not-the-real-token"},
    )
    assert response.status_code == 403


def test_session_cookie_is_http_only(client, users):
    response = client.post(
        "/api/v1/auth/login",
        json={"email": users[Role.ADMIN].email, "password": "TestPassword!2026"},
    )
    set_cookie_headers = response.headers.get_list("set-cookie")
    session_cookie = next(
        h for h in set_cookie_headers if h.startswith(settings.session_cookie_name)
    )
    assert "HttpOnly" in session_cookie
    # The CSRF cookie is deliberately readable so the frontend can echo it in a header.
    csrf_cookie = next(h for h in set_cookie_headers if h.startswith(settings.csrf_cookie_name))
    assert "HttpOnly" not in csrf_cookie


def test_logout_revokes_the_session(client, users):
    from tests.conftest import sign_in

    csrf = sign_in(client, users[Role.ADMIN].email)
    assert client.get("/api/v1/auth/me").status_code == 200
    assert (
        client.post("/api/v1/auth/logout", headers={settings.csrf_header_name: csrf}).status_code
        == 200
    )
    assert client.get("/api/v1/auth/me").status_code == 401


def test_deactivated_user_session_stops_working(client, users, db):
    from tests.conftest import sign_in

    sign_in(client, users[Role.OPERATIONS].email)
    assert client.get("/api/v1/auth/me").status_code == 200

    user = db.get(type(users[Role.OPERATIONS]), users[Role.OPERATIONS].id)
    user.is_active = False
    db.commit()

    assert client.get("/api/v1/auth/me").status_code == 401


def test_login_failures_are_rate_limited(client, users):
    codes = []
    for _ in range(12):
        response = client.post(
            "/api/v1/auth/login",
            json={"email": users[Role.ADMIN].email, "password": "wrong-password"},
        )
        codes.append(response.status_code)
    assert 429 in codes
    assert codes[0] == 401


def test_login_failure_message_does_not_reveal_account_existence(client, users):
    unknown = client.post(
        "/api/v1/auth/login", json={"email": "nobody@demo.example.com", "password": "whatever12345"}
    )
    known = client.post(
        "/api/v1/auth/login", json={"email": users[Role.ADMIN].email, "password": "whatever12345"}
    )
    assert unknown.json()["message"] == known.json()["message"]


def test_permission_matrix_grants_admin_everything():
    all_permissions = {
        value
        for key, value in vars(Permission).items()
        if not key.startswith("_") and isinstance(value, str)
    }
    assert ROLE_PERMISSIONS[Role.ADMIN] == all_permissions
    # No other role may hold integration credentials or suppression release.
    for role, granted in ROLE_PERMISSIONS.items():
        if role == Role.ADMIN:
            continue
        assert Permission.INTEGRATION_MANAGE not in granted
        assert Permission.SUPPRESSION_RELEASE not in granted
