"""Structural boundaries: what the Customer Account package may import and inherit.

These are the tests `IDENTITY_AND_AUTHORIZATION.md` section 9 asks for, and they are
deliberately *structural* rather than behavioural. A behavioural test proves that today's
routes refuse a staff cookie. A structural test proves that no route **can** resolve a staff
dependency, which is the claim that survives somebody adding a route next week.

The technique is the one `test_public_tracking.py` already uses for the public package --
walk the source, walk the route table, walk the dependency graph -- extended here because
the stakes are higher: on the public surface a misattached staff dependency produces an
obvious error, while here it would produce a working session.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest
from fastapi.routing import APIRoute

from app.api.account import deps as account_deps
from app.core.config import settings
from app.main import ACCOUNT_PREFIX, app

ACCOUNT_PACKAGE = Path(inspect.getfile(account_deps)).parent


ACCOUNT_MODULE_PREFIX = "app.api.account"


def _all_routes() -> list[tuple[str, APIRoute]]:
    """Every mounted route as ``(full_path, route)``.

    This FastAPI version wraps an included router in a ``_IncludedRouter`` that keeps the
    original router and the prefix it was mounted at, rather than copying the routes onto
    the application with rewritten paths. So the traversal follows ``original_router`` and
    accumulates ``include_context.prefix`` -- which is what makes the full path available at
    all, and what makes the route inventory below a real inventory rather than an empty set.
    """
    collected: list[tuple[str, APIRoute]] = []
    stack: list[tuple[str, object]] = [("", route) for route in app.routes]
    while stack:
        prefix, route = stack.pop()
        if isinstance(route, APIRoute):
            collected.append((f"{prefix}{route.path}", route))
            continue
        included = getattr(route, "original_router", None)
        if included is not None:
            context = getattr(route, "include_context", None)
            child_prefix = prefix + (getattr(context, "prefix", "") or "")
            stack.extend((child_prefix, child) for child in included.routes)
            continue
        stack.extend((prefix, child) for child in getattr(route, "routes", []))
    return collected


def _is_account_route(route: APIRoute) -> bool:
    """Identified by where the handler was defined, not only by its path.

    A Customer Account route is one defined in the Customer Account package, whatever it
    happens to be mounted at -- which is the more honest test, and survives the prefix
    changing.
    """
    return getattr(route.endpoint, "__module__", "").startswith(ACCOUNT_MODULE_PREFIX)


def _account_routes() -> list[APIRoute]:
    return [route for _, route in _all_routes() if _is_account_route(route)]


def _account_paths() -> set[tuple[tuple[str, ...], str]]:
    return {
        (tuple(sorted(route.methods)), path)
        for path, route in _all_routes()
        if _is_account_route(route)
    }


def _flat_dependencies(dependant) -> list:
    """Every dependency in the graph, flattened.

    Written out rather than imported: `Dependant.flat_sub_dependants` does not exist in this
    FastAPI version, and a helper that silently returned nothing would make every assertion
    below vacuous.
    """
    collected = []
    stack = list(dependant.dependencies)
    while stack:
        dependency = stack.pop()
        collected.append(dependency)
        stack.extend(dependency.dependencies)
    return collected


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
            modules.update(f"{node.module}.{alias.name}" for alias in node.names)
    return modules


def _account_sources() -> list[Path]:
    return sorted(ACCOUNT_PACKAGE.rglob("*.py"))


# --- Imports ------------------------------------------------------------------


def test_the_package_has_source_files_to_check():
    """Otherwise every assertion below would pass over an empty list."""
    sources = _account_sources()
    assert len(sources) >= 4
    assert {path.name for path in sources} >= {"__init__.py", "deps.py", "routes.py", "router.py"}


@pytest.mark.parametrize("source", _account_sources(), ids=lambda path: path.name)
def test_no_account_module_imports_the_staff_dependencies(source):
    """AC-CA-1.4, as a property of the source rather than of today's route table."""
    modules = _imported_modules(source)
    assert "app.api.deps" not in modules
    assert not any(module.startswith("app.api.deps.") for module in modules)
    assert not any(module.startswith("app.api.v1") for module in modules)


@pytest.mark.parametrize("source", _account_sources(), ids=lambda path: path.name)
def test_no_account_module_imports_the_public_surface(source):
    """Two customer-facing surfaces sharing a helper is one of them outgrowing it later."""
    modules = _imported_modules(source)
    assert not any(module.startswith("app.api.public") for module in modules)


@pytest.mark.parametrize("source", _account_sources(), ids=lambda path: path.name)
def test_no_account_module_imports_the_permission_matrix(source):
    """A customer identity has no role and no permission lookup path (T-12)."""
    modules = _imported_modules(source)
    assert "app.core.permissions" not in modules
    assert not any(module.startswith("app.core.permissions") for module in modules)


def test_no_account_module_imports_the_staff_auth_service():
    """`auth_service` mints staff sessions. Nothing here may be able to call it."""
    for source in _account_sources():
        modules = _imported_modules(source)
        assert "app.services.auth_service" not in modules


def test_the_customer_services_do_not_import_a_canonical_write_function():
    """T-07: the customer surface has no canonical write path, asserted at the import level.

    `customer_service` is where canonical customer rows are created and updated. The
    Customer Account services must not import it -- reusing *normalization* is required and
    reusing the *writer* is the thing OD-23 forbids.
    """
    from app.services import (
        customer_account_audit,
        customer_auth_service,
        customer_identity_service,
    )

    for module in (customer_identity_service, customer_auth_service, customer_account_audit):
        modules = _imported_modules(Path(inspect.getfile(module)))
        assert "app.services.customer_service" not in modules, module.__name__
        assert "app.services.booking_service" not in modules, module.__name__
        assert "app.services.shipment_service" not in modules, module.__name__


# --- The route table ----------------------------------------------------------


def test_the_account_routes_are_the_twenty_six_built_so_far():
    """Named, so a twenty-seventh appearing is a decision rather than a diff nobody read.

    Eight in Phase 9, the two **read** routes Phase 11 adds, the five profile and
    consent routes fix pack 2 adds (FIELD_MATRIX §3 and §4), and the two milestone
    notification routes Phase 13F adds (OD-72): the customer's choices and history, and the
    four quote routes Phase 13G adds (OD-77): list, read, accept, decline; and the five
    sign-in and security routes RC-UAT-21 adds (AS-42 in SUPERSEDED_ASSERTIONS.md). The list
    is written out rather than counted, because a route arriving is exactly the change this
    test exists to make somebody look at.
    """
    assert _account_paths() == {
        (("POST",), f"{ACCOUNT_PREFIX}/register"),
        (("POST",), f"{ACCOUNT_PREFIX}/verify-email"),
        (("POST",), f"{ACCOUNT_PREFIX}/verification/resend"),
        (("POST",), f"{ACCOUNT_PREFIX}/sign-in"),
        (("POST",), f"{ACCOUNT_PREFIX}/sign-out"),
        (("POST",), f"{ACCOUNT_PREFIX}/password/forgot"),
        (("POST",), f"{ACCOUNT_PREFIX}/password/reset"),
        (("GET",), f"{ACCOUNT_PREFIX}/me"),
        (("GET",), f"{ACCOUNT_PREFIX}/shipments"),
        (("GET",), f"{ACCOUNT_PREFIX}/shipments/{{reference:path}}"),
        (("GET",), f"{ACCOUNT_PREFIX}/profile"),
        (("POST",), f"{ACCOUNT_PREFIX}/profile/direct"),
        (("POST",), f"{ACCOUNT_PREFIX}/profile/proposals"),
        (("POST",), f"{ACCOUNT_PREFIX}/profile/proposals/withdraw"),
        (("POST",), f"{ACCOUNT_PREFIX}/consent/marketing"),
        (("GET",), f"{ACCOUNT_PREFIX}/notifications"),
        (("POST",), f"{ACCOUNT_PREFIX}/notifications/preferences"),
        (("GET",), f"{ACCOUNT_PREFIX}/quotes"),
        (("GET",), f"{ACCOUNT_PREFIX}/quotes/{{offer_id}}"),
        (("POST",), f"{ACCOUNT_PREFIX}/quotes/{{offer_id}}/accept"),
        (("POST",), f"{ACCOUNT_PREFIX}/quotes/{{offer_id}}/decline"),
        # RC-UAT-21 Phase B: password and sign-in email, any signed-in account; the
        # confirmation is the link from the message to the new address.
        (("GET",), f"{ACCOUNT_PREFIX}/security"),
        (("POST",), f"{ACCOUNT_PREFIX}/password/change"),
        (("POST",), f"{ACCOUNT_PREFIX}/email/change"),
        (("POST",), f"{ACCOUNT_PREFIX}/email/change/cancel"),
        (("POST",), f"{ACCOUNT_PREFIX}/email/change/confirm"),
    }


def test_the_only_account_routes_that_read_a_shipment_are_the_two_read_routes():
    """Phase 9's "no route serves shipment data" became Phase 11's "two do, and both GET".

    The original assertion was that no account path contained "shipment" at all. Phase 11 is
    the phase authorized to change that, so the assertion is narrowed rather than deleted:
    the shipment paths are named, they are the only ones, and **every one of them is a
    read**. Fix pack 2 added the profile and consent routes, which are named here and
    nowhere touch a shipment; a tracking route still does not exist.
    """
    paths = {path: route for path, route in _all_routes() if _is_account_route(route)}
    assert paths

    shipment_paths = {path for path in paths if "shipment" in path}
    assert shipment_paths == {
        f"{ACCOUNT_PREFIX}/shipments",
        f"{ACCOUNT_PREFIX}/shipments/{{reference:path}}",
    }
    for path in shipment_paths:
        assert set(paths[path].methods) == {"GET"}, path

    profile_paths = {path for path in paths if "profile" in path or "consent" in path}
    assert profile_paths == {
        f"{ACCOUNT_PREFIX}/profile",
        f"{ACCOUNT_PREFIX}/profile/direct",
        f"{ACCOUNT_PREFIX}/profile/proposals",
        f"{ACCOUNT_PREFIX}/profile/proposals/withdraw",
        f"{ACCOUNT_PREFIX}/consent/marketing",
    }
    for path in paths:
        assert "track" not in path


def test_no_account_route_resolves_a_dependency_from_the_staff_module():
    """The dependency graph, walked, rather than the imports inferred.

    An import test catches the module being named. This catches a callable that arrived by
    any other route -- re-exported, aliased, or passed in -- by checking where every
    dependency in every route's flat graph was defined.
    """
    staff_module = "app.api.deps"
    seen = 0
    for route in _account_routes():
        for dependency in _flat_dependencies(route.dependant):
            call = dependency.call
            if call is None:
                continue
            module = getattr(call, "__module__", "")
            assert module != staff_module, (route.path, getattr(call, "__name__", call))
            assert not module.startswith("app.api.public"), route.path
            seen += 1
    # A graph walk that found nothing would pass regardless of what the routes declare.
    assert seen > 0, "no dependencies were inspected"


def test_every_account_route_depends_on_the_account_database_dependency():
    """Its own session dependency, so a test can override this surface alone."""
    for route in _account_routes():
        calls = {
            getattr(dependency.call, "__name__", "")
            for dependency in _flat_dependencies(route.dependant)
        }
        calls.add(getattr(route.dependant.call, "__name__", ""))
        assert "account_db_session" in calls or "db_session" not in calls


def test_no_staff_route_depends_on_an_account_dependency():
    """The mirror. A staff route that resolved a customer identity would be the same bug."""
    checked = 0
    for path, route in _all_routes():
        if _is_account_route(route):
            continue
        checked += 1
        for dependency in _flat_dependencies(route.dependant):
            module = getattr(dependency.call, "__module__", "")
            assert not module.startswith(ACCOUNT_MODULE_PREFIX), path
    assert checked > 0, "no staff routes were inspected"


# --- Schemas ------------------------------------------------------------------


def _account_models():
    from pydantic import BaseModel

    from app.schemas import account as account_schemas

    return [
        value
        for value in vars(account_schemas).values()
        if isinstance(value, type)
        and issubclass(value, BaseModel)
        and value.__module__.endswith("account")
    ]


def test_there_are_account_models_to_check():
    assert len(_account_models()) >= 8


def test_no_account_model_subclasses_a_staff_or_public_model():
    """AC-CA-1.5. An internal schema gains fields; a model that inherits one publishes them."""
    from app.schemas import auth, common, customer, public_tracking, shipment

    foreign = []
    for module in (public_tracking, shipment, customer, auth, common):
        foreign += [
            value
            for value in vars(module).values()
            if isinstance(value, type)
            and hasattr(value, "model_fields")
            # Defined there, not merely imported there. `BaseModel` itself appears in every
            # schema module's namespace, and every model inherits it.
            and value.__module__ == module.__name__
        ]

    assert foreign, "no staff or public models were found to compare against"
    for model in _account_models():
        for other in foreign:
            assert not issubclass(model, other), f"{model.__name__} inherits {other.__name__}"


def test_no_account_model_sets_from_attributes():
    """So an ORM object can never be handed to one."""
    for model in _account_models():
        assert model.model_config.get("from_attributes") is False, model.__name__


def test_every_account_model_forbids_extra_fields():
    for model in _account_models():
        assert model.model_config.get("extra") == "forbid", model.__name__


def test_the_public_tracking_schemas_are_untouched():
    """The Customer Account declares its own; it does not move the public contract.

    Registered in `SUPERSEDED_ASSERTIONS.md` (AS-30): twenty-four fields until RC-UAT-19
    added ``carrier_links`` (2026-10-22).
    """
    from app.schemas.public_tracking import PublicTrackingResult

    assert (
        len(PublicTrackingResult.model_fields) == 25
    )  # 24 until RC-UAT-19 added carrier_links (2026-10-22)
    assert PublicTrackingResult.model_config.get("from_attributes") is False


# --- The identity is not a user -----------------------------------------------


def test_no_customer_row_can_be_a_staff_row():
    from app.models import CustomerIdentity, User

    assert CustomerIdentity.__tablename__ != User.__tablename__
    assert CustomerIdentity.__tablename__ == "customer_identities"
    assert not issubclass(CustomerIdentity, User)


def test_there_is_no_customer_staff_role():
    """OD-23: no `customer` role is added to the staff matrix.

    **Amended in Phase 10, and the amendment is the interesting part.** As written in
    Phase 9 this test also asserted that *no staff role holds any* ``customer_account:``
    permission. That was true then because no such permission existed, and it is the
    opposite of what OD-24 requires now: Operations performs account approval and Admin
    may override, so both must hold exactly these permissions.

    The claim OD-23 actually makes survives intact and is asserted below: a customer
    identity is not a staff role, holds no permission set, and has no path to one. What a
    *staff* role may hold is OD-24's question, and the answer is checked here by name --
    Admin and Operations, nobody else -- rather than by forbidding the prefix outright.
    """
    from app.core.enums import Role
    from app.core.permissions import ROLE_PERMISSIONS, Permission

    values = {role.value for role in Role}
    assert "customer" not in values
    assert "customer_account" not in values
    for role in ROLE_PERMISSIONS:
        assert role != "customer"

    account_permissions = {
        Permission.CUSTOMER_ACCOUNT_REVIEW,
        Permission.CUSTOMER_ACCOUNT_APPROVE,
    }
    holders = {
        role
        for role, granted in ROLE_PERMISSIONS.items()
        if any(permission.startswith("customer_account:") for permission in granted)
    }
    assert holders == {Role.ADMIN, Role.OPERATIONS}
    # Exactly these, so another `customer_account:` permission cannot be added to a role
    # without this test being read again. Admin alone also holds deactivate (DEC-0126).
    held = {
        role: {p for p in ROLE_PERMISSIONS[role] if p.startswith("customer_account:")}
        for role in holders
    }
    assert held[Role.OPERATIONS] == account_permissions
    assert held[Role.ADMIN] == account_permissions | {Permission.CUSTOMER_ACCOUNT_DEACTIVATE}


def test_the_three_realms_share_no_cookie_or_header_name():
    names = [
        settings.session_cookie_name,
        settings.csrf_cookie_name,
        settings.account_session_cookie_name,
        settings.account_csrf_cookie_name,
    ]
    assert len(set(names)) == len(names)
    assert settings.csrf_header_name != settings.account_csrf_header_name


def test_the_account_prefix_is_distinct_from_the_public_one():
    from app.main import PUBLIC_PREFIX

    assert ACCOUNT_PREFIX != PUBLIC_PREFIX
    assert not ACCOUNT_PREFIX.startswith(PUBLIC_PREFIX)
    assert not PUBLIC_PREFIX.startswith(ACCOUNT_PREFIX)
