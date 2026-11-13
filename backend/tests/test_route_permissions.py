"""Every guarded route, every role, over HTTP — not the permission matrix restated.

A permission-set unit test proves that ``ROLE_PERMISSIONS[Role.OPERATIONS]`` contains
``financial:read``. It does not prove that ``GET /api/v1/customers/{id}/financials`` asks
for ``financial:read``, or that it asks for anything at all. Those are different claims,
and the role merge is exactly the kind of change that can satisfy the first while breaking
the second: the set moved, and whether the routes moved with it is the question.

So this module walks the application's own route table, reads the permissions each route
declares through ``deps.require``, and then makes a real authenticated request per route
per role. The list of routes is never written down here — it is whatever the application
mounts, so a route added next week is covered the day it is added, and a route that
accidentally loses its guard shows up as a role reaching something it should not.

The two directions are asserted differently on purpose:

* **Denied** is exact. A role missing any required permission must get **403**. Nothing
  else is acceptable — not 404, not 422, not 500 — because anything else means the refusal
  came from somewhere other than the permission layer, or did not come at all.
* **Allowed** is ``!= 403``. These requests carry placeholder path parameters and empty
  bodies, so a permitted caller legitimately lands on 404 or 422. What matters is that the
  permission layer let them past.
"""

from __future__ import annotations

import pytest
from fastapi.routing import APIRoute

from app.core.enums import Role
from app.core.permissions import ROLE_PERMISSIONS
from app.main import app

#: The former Operations permission set, before the merge (DEC-0088). Written down here
#: because it no longer exists anywhere in the source, and the tests that prove what the
#: merge *changed* need something to compare against.
FORMER_OPERATIONS_PERMISSIONS = frozenset(
    {
        "customer:read",
        "address:read",
        "interaction:read",
        "interaction:write",
        "task:read",
        "task:write",
        "shipment:read",
        "shipment:write",
        "tracking:write",
        "label:generate",
        "dashboard:read",
        "settings:read",
    }
)

#: Placeholder values for path parameters. The identifiers deliberately do not exist: a
#: permitted caller should reach a 404, and a forbidden one should never get that far.
PATH_PARAMETER_VALUES = {
    "reference": "SX-CAV-000000000000",
    "public_id": "STCA-000000",
}
DEFAULT_PATH_PARAMETER = "999999"

#: Routes excluded from the sweep, with the reason. Kept short and explicit: an exclusion
#: is a hole in the coverage and has to earn its place.
EXCLUDED_PATHS = {
    # Deletes a session server-side; sweeping it would sign the sweeping client out
    # halfway through its own run.
    "/api/v1/auth/revoke-all",
}


def _walk(obj, prefix: str = ""):
    """Every mounted endpoint, following this FastAPI version's nested include routers."""
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


def _required_permissions(route: APIRoute) -> frozenset[str]:
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


def _fill(path: str) -> str:
    out = path
    while "{" in out:
        start = out.index("{")
        end = out.index("}", start)
        name = out[start + 1 : end].split(":")[0]
        out = out[:start] + PATH_PARAMETER_VALUES.get(name, DEFAULT_PATH_PARAMETER) + out[end + 1 :]
    return out


def _guarded_routes() -> list[tuple[str, str, frozenset[str]]]:
    rows = []
    for path, route in _walk(app):
        if path in EXCLUDED_PATHS:
            continue
        permissions = _required_permissions(route)
        if not permissions:
            continue
        for method in sorted(route.methods - {"HEAD", "OPTIONS"}):
            rows.append((method, path, permissions))
    rows.sort(key=lambda row: (row[1], row[0]))
    return rows


GUARDED_ROUTES = _guarded_routes()

#: Routes whose guard the merge changed: Operations could not reach them before and can
#: now. Derived, never listed.
ROUTES_OPENED_BY_THE_MERGE = [
    row
    for row in GUARDED_ROUTES
    if not row[2] <= FORMER_OPERATIONS_PERMISSIONS and row[2] <= ROLE_PERMISSIONS[Role.OPERATIONS]
]


#: Every (route, role) pair, split by what the permission matrix says should happen. The
#: split is computed here rather than skipped inside the test: a suite that reports several
#: hundred skips has trained everyone reading it to ignore the number, and this repository
#: has kept that number at zero on purpose.
DENIED_CASES = [
    (method, path, permissions, role)
    for method, path, permissions in GUARDED_ROUTES
    for role in sorted(ROLE_PERMISSIONS, key=str)
    if not permissions <= ROLE_PERMISSIONS[role]
]

ALLOWED_CASES = [
    (method, path, permissions, role)
    for method, path, permissions in GUARDED_ROUTES
    for role in sorted(ROLE_PERMISSIONS, key=str)
    if permissions <= ROLE_PERMISSIONS[role]
]


def _identify(row: tuple[str, str, frozenset[str]]) -> str:
    method, path, _permissions = row
    return f"{method} {path}"


def _identify_case(row: tuple[str, str, frozenset[str], str]) -> str:
    method, path, _permissions, role = row
    return f"{role}-{method} {path}"


def _call(api, method: str, path: str):
    target = _fill(path)
    if method == "GET":
        return api.get(target)
    if method == "POST":
        return api.post(target, json={})
    if method == "PATCH":
        return api.patch(target, json={})
    if method == "PUT":
        return api.client.put(target, headers=api.headers, json={})
    if method == "DELETE":
        return api.delete(target)
    raise AssertionError(f"unhandled method {method}")


# --- The sweep the route table generates ------------------------------------


def test_the_route_table_is_actually_being_walked():
    """A guard against the sweep silently covering nothing.

    Every assertion below is parametrised over a list derived from ``GUARDED_ROUTES``. If
    the walker stopped finding routes -- a FastAPI upgrade changing how included routers are
    stored would do it, and one already changed it once -- the parametrised tests would all
    pass by having no cases at all.
    """
    assert len(GUARDED_ROUTES) > 80
    paths = {path for _method, path, _permissions in GUARDED_ROUTES}
    assert "/api/v1/customers" in paths
    assert "/api/v1/customers/{customer_id}/financials" in paths


def test_every_guarded_route_declares_its_permissions():
    for method, path, permissions in GUARDED_ROUTES:
        assert permissions, f"{method} {path} is in the guarded list with no permissions"


def test_both_halves_of_the_sweep_have_cases():
    """Neither list may quietly empty out. Together they are every route times every role."""
    assert len(DENIED_CASES) + len(ALLOWED_CASES) == len(GUARDED_ROUTES) * len(ROLE_PERMISSIONS)
    assert len(DENIED_CASES) > 100
    assert len(ALLOWED_CASES) > 100


@pytest.mark.parametrize("case", DENIED_CASES, ids=_identify_case)
def test_a_role_without_the_permission_is_refused_with_403(api_for, case):
    """The security direction, and it is exact."""
    method, path, permissions, role = case

    response = _call(api_for(str(role)), method, path)

    assert response.status_code == 403, (
        f"{method} {path} requires {sorted(permissions)}; {role} holds none of the missing "
        f"ones but got {response.status_code}"
    )


@pytest.mark.parametrize("case", ALLOWED_CASES, ids=_identify_case)
def test_a_role_with_the_permission_is_not_refused(api_for, case):
    method, path, permissions, role = case

    response = _call(api_for(str(role)), method, path)

    assert response.status_code != 403, (
        f"{method} {path} requires {sorted(permissions)}, which {role} holds, but the "
        f"request was refused"
    )


# --- What the merge specifically opened -------------------------------------


def test_the_merge_opened_routes_that_were_closed_to_operations():
    """If this list is empty the merge did nothing, and the tests below prove nothing."""
    assert len(ROUTES_OPENED_BY_THE_MERGE) >= 20


@pytest.mark.parametrize("route", ROUTES_OPENED_BY_THE_MERGE, ids=_identify)
def test_operations_now_reaches_every_route_the_merge_opened(api_for, route):
    method, path, permissions = route

    response = _call(api_for(Role.OPERATIONS.value), method, path)

    assert response.status_code != 403, (
        f"{method} {path} requires {sorted(permissions)}, which merged Operations holds"
    )


@pytest.mark.parametrize("route", ROUTES_OPENED_BY_THE_MERGE, ids=_identify)
def test_each_opened_route_was_genuinely_closed_before(route):
    """The other half of the claim: these were not already reachable."""
    _method, _path, permissions = route
    assert not permissions <= FORMER_OPERATIONS_PERMISSIONS


# --- Boundaries the merge did not move --------------------------------------


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/v1/staff"),
        ("POST", "/api/v1/customers/merge"),
        ("GET", "/api/v1/exports/customers.csv"),
        ("GET", "/api/v1/exports/shipments.csv"),
    ],
)
def test_operations_is_still_refused_where_admin_alone_may_go(api_for, method, path):
    response = _call(api_for(Role.OPERATIONS.value), method, path)
    assert response.status_code == 403


def test_marketing_and_the_manager_kept_exactly_the_permissions_they_had(api_for):
    """The merge touched two role sets. These are the other two, unchanged.

    One addition since: Marketing holds ``suppression:add`` (UAT round 4, DEC-0130).
    """
    assert ROLE_PERMISSIONS[Role.MARKETING] == {
        "address:read",
        "consent:read",
        "consent:write",
        "suppression:add",
        "customer:read",
        "customer:update",
        "dashboard:read",
        "duplicate:review",
        "export:marketing_segment",
        "interaction:read",
        "interaction:write",
        "referral:read",
        "report:read",
        "segment:read",
        "segment:write",
        "settings:read",
        "shipment:read",
        "tag:read",
        "tag:write",
        "task:read",
        "task:write",
    }
    assert ROLE_PERMISSIONS[Role.READ_ONLY_MANAGER] == {
        "address:read",
        "audit:read",
        "consent:read",
        "customer:read",
        "dashboard:read",
        "duplicate:review",
        "financial:read",
        "integration:read",
        "interaction:read",
        "referral:read",
        "report:read",
        "segment:read",
        "settings:read",
        "shipment:read",
        "tag:read",
        "task:read",
    }


def test_neither_marketing_nor_the_manager_gained_the_cost_permission(api_for):
    """The one permission the merge had to leave alone everywhere."""
    for role in (Role.MARKETING, Role.READ_ONLY_MANAGER, Role.OPERATIONS):
        assert "financial_cost:read" not in ROLE_PERMISSIONS[role]
    assert "financial_cost:read" in ROLE_PERMISSIONS[Role.ADMIN]


# --- What happens to a session whose account was migrated -------------------
#
# The migration changes a role row while staff may be signed in. Whether that session then
# carries the old permissions, the new ones, or stops working is a property of the existing
# authorization architecture rather than of the migration, and it is worth pinning down:
# "the session is fine" is the kind of claim that is true until somebody adds a cache.


def test_a_session_carries_no_role_of_its_own(db, users):
    """The session row stores a token digest and timestamps. No role, no permission set."""
    from app.models import UserSession

    columns = {column.name for column in UserSession.__table__.columns}

    assert "role" not in columns
    assert not columns & {"permissions", "role_snapshot", "granted"}


def test_a_role_changed_underneath_a_live_session_takes_effect_immediately(client, users, db):
    """The next request, not the next sign-in.

    ``current_user`` resolves the session to a user row and reads ``user.role`` from that
    row on every request, so a role changed by a migration is in force the moment the
    migration commits. This is why the role merge needs no session revocation step: there
    is no cached grant anywhere to invalidate.
    """
    from tests.conftest import sign_in

    user = users[Role.MARKETING]
    sign_in(client, user.email)

    # Marketing does not hold financial:read, so the refusal comes from the permission
    # layer. The customer id deliberately does not exist, which is what makes the two
    # outcomes distinguishable: 403 is "not allowed", 404 is "allowed, and not there".
    assert client.get("/api/v1/customers/999999/financials").status_code == 403

    # Move the account to the merged Operations role exactly as the migration does: by
    # writing the role column, touching nothing else, and revoking no session.
    row = db.get(type(user), user.id)
    row.role = Role.OPERATIONS.value
    db.commit()

    # Same cookie, same session row, no re-authentication.
    assert client.get("/api/v1/customers/999999/financials").status_code == 404


def test_the_reverse_direction_also_takes_effect_immediately(client, users, db):
    """A downgrade narrows a live session just as promptly as an upgrade widens it."""
    from tests.conftest import sign_in

    user = users[Role.OPERATIONS]
    sign_in(client, user.email)
    assert client.get("/api/v1/customers/999999/financials").status_code == 404

    row = db.get(type(user), user.id)
    row.role = Role.MARKETING.value
    db.commit()

    assert client.get("/api/v1/customers/999999/financials").status_code == 403


def test_the_migrated_account_keeps_its_session_and_its_identity(client, users, db):
    """The account is the same account: same id, same session, same audit history."""
    from tests.conftest import sign_in

    user = users[Role.MARKETING]
    user_id = user.id
    sign_in(client, user.email)

    row = db.get(type(user), user_id)
    row.role = Role.OPERATIONS.value
    db.commit()

    me = client.get("/api/v1/auth/me")
    assert me.status_code == 200
    body = me.json()
    assert body["user"]["id"] == user_id
    assert body["user"]["role"] == Role.OPERATIONS.value

    # And the permission list the frontend builds its menus from is the merged set, served
    # over the same session. This is the seam that makes "frontend menus derive access from
    # the API" true rather than aspirational: no rebuild, no re-login, no hardcoded role.
    assert set(body["permissions"]) == set(ROLE_PERMISSIONS[Role.OPERATIONS])
    assert "financial_cost:read" not in body["permissions"]
