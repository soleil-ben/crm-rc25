"""The public boundary: nothing answers before the application's own policy does.

Phase 3 claimed an order of operations -- rate limit, normalize, validate, resolve -- and
the handler body did read that way. It was not what the request actually did, and this
file exists because of that gap.

Two separate defects, found by independent review:

**Framework validation ran first.** ``reference`` was declared
``Path(min_length=1, max_length=120)``. FastAPI validates a path parameter before the
endpoint body, so a 121-character reference produced a 422 whose body named the
constraint and echoed the submitted value back, and the rate limiter never ran. Two more
shapes never reached the route at all: ``/track/`` and ``/track/a/b`` fell through to
Starlette's router 404, whose body differs from the tracking 404. So the surface answered
three distinguishable ways, two of them without spending an allowance -- on an endpoint
whose entire design is that every failure is the same failure.

**A dependency queried the database.** ``PublicOrgSettings`` read the organization
settings row for its display timezone. Dependencies resolve before the endpoint body, so
a request the limiter was about to refuse had already performed a query.

Every test here fails against the Phase 3 code and passes against the correction
(DEC-0059). The behavioural tests that were already passing stay in
``test_public_tracking.py``; this file is about the boundary itself.
"""

from __future__ import annotations

import pytest
from sqlalchemy import event

from app.core.config import settings
from app.core.public_reference import MAX_INPUT_LENGTH
from app.core.security import rate_limiter
from tests.conftest import booked_shipment, make_customer

TRACK = "/api/v1/public/track"

#: A well-formed reference that was never issued. The yardstick every other failure is
#: measured against: whatever this returns, everything else must return too.
UNKNOWN = "SX-CAV-ABCDEFGHJKLM"

#: One character past the bound. The exact input the review reported.
OVERSIZED = "A" * (MAX_INPUT_LENGTH + 1)

#: Far past it, in case something only clamps near the boundary.
SUBSTANTIALLY_OVERSIZED = "SX-CAV-" + ("Z" * 4000)

#: Headers a customer's browser relies on. Compared across every failure path.
PROTECTED_HEADERS = (
    "cache-control",
    "referrer-policy",
    "x-robots-tag",
    "x-content-type-options",
    "x-frame-options",
    "permissions-policy",
)

#: Shapes that used to escape the application's policy, and the ones that never did.
#: Every one of them must be indistinguishable from ``UNKNOWN``.
ESCAPING_SHAPES = [
    pytest.param(OVERSIZED, id="121-characters"),
    pytest.param(SUBSTANTIALLY_OVERSIZED, id="substantially-oversized"),
    pytest.param("", id="empty-reference"),
    pytest.param("SX-CAV-ABCDEFGHJKLM/extra", id="one-extra-separator"),
    pytest.param("SX-CAV-ABCDEFGHJKLM/01/02", id="several-extra-separators"),
    pytest.param("a/b/c/d/e/f", id="path-shaped-noise"),
    pytest.param("SX-CAV-ABCDEFGHJKLM-01/", id="trailing-separator"),
    pytest.param("中文" * 200, id="unicode-noise-oversized"),
    pytest.param("%00%01nul-noise", id="encoded-control-characters"),
    pytest.param("%2e%2e%2f%2e%2e%2fetc", id="encoded-traversal"),
    pytest.param("rubbish", id="plainly-malformed"),
]


def get(client, reference: str):
    return client.get(f"{TRACK}/{reference}")


def comparable_headers(response) -> dict[str, str]:
    """Headers that must match between two indistinguishable failures.

    ``date``, ``server``, and ``content-length`` are excluded: the first two vary with
    the clock and the runtime, and the third is implied by the body, which is compared
    directly.
    """
    ignored = {"date", "server", "content-length"}
    return {
        key.lower(): value for key, value in response.headers.items() if key.lower() not in ignored
    }


# --- The oversized reference -----------------------------------------------


def test_an_oversized_reference_answers_exactly_like_an_unknown_one(client, db):
    """The reported defect, stated as the property it broke.

    Status, body, and every protected header must match. Nothing about the answer may
    reveal that one of these was rejected by a length rule and the other by a lookup.
    """
    customer = make_customer(db)
    booked_shipment(db, customer)
    db.commit()

    oversized = get(client, OVERSIZED)
    unknown = get(client, UNKNOWN)

    assert oversized.status_code == unknown.status_code == 404
    assert oversized.content == unknown.content
    assert comparable_headers(oversized) == comparable_headers(unknown)


def test_a_substantially_oversized_reference_returns_no_framework_validation_body(client):
    """No ``detail`` array, no constraint name, and no echo of what was submitted."""
    response = get(client, SUBSTANTIALLY_OVERSIZED)

    assert response.status_code == 404
    body = response.json()
    assert set(body) == {"code", "message"}
    assert body["code"] == "tracking_not_found"
    assert "detail" not in body

    serialized = response.text.lower()
    for giveaway in (
        "string_too_long",
        "max_length",
        "at most",
        "ctx",
        "loc",
        "value_error",
        "path",
        "characters",
    ):
        assert giveaway not in serialized, giveaway
    # The submitted value is not reflected back in any form.
    assert "zzzz" not in serialized


@pytest.mark.parametrize("reference", ESCAPING_SHAPES)
def test_every_escaping_shape_is_indistinguishable_from_an_unknown_reference(client, db, reference):
    """One failure, whatever shape the caller sent.

    ``/track/`` and ``/track/a/b`` previously answered from Starlette's router with
    ``{"detail": "Not Found"}``, which is a different body from the tracking failure and
    told a caller that their input had not even been understood as a reference.
    """
    customer = make_customer(db)
    booked_shipment(db, customer)
    db.commit()

    escaping = get(client, reference)
    unknown = get(client, UNKNOWN)

    assert escaping.status_code == unknown.status_code == 404
    assert escaping.json() == unknown.json()
    assert comparable_headers(escaping) == comparable_headers(unknown)


def test_the_bare_track_path_answers_with_the_same_policy(client):
    """``/api/v1/public/track`` with nothing after it is still a tracking failure."""
    bare = client.get(TRACK)
    unknown = get(client, UNKNOWN)

    assert bare.status_code == 404
    assert bare.json() == unknown.json()
    assert comparable_headers(bare) == comparable_headers(unknown)


@pytest.mark.parametrize("reference", ESCAPING_SHAPES)
def test_every_escaping_shape_keeps_the_protected_headers(client, reference):
    """Privacy headers are not conditional on which code path produced the response."""
    headers = get(client, reference).headers

    for header in PROTECTED_HEADERS:
        assert header in headers, header
    assert "no-store" in headers["Cache-Control"]
    assert "noindex" in headers["X-Robots-Tag"]
    assert headers["Referrer-Policy"] == "no-referrer"


# --- The rate limiter now genuinely runs first -------------------------------


def test_repeated_oversized_references_consume_the_allowance_and_reach_429(client, monkeypatch):
    """The heart of the defect: framework validation used to be free.

    Each of these requests used to return 422 without touching the limiter, so an
    attacker could send unlimited oversized probes. They now cost the same as any other
    lookup.
    """
    monkeypatch.setattr(settings, "public_tracking_rate_limit_attempts", 3)
    rate_limiter.reset()

    statuses = [get(client, f"{OVERSIZED}{index}").status_code for index in range(5)]

    assert statuses == [404, 404, 404, 429, 429]


def test_a_mixture_of_escaping_shapes_shares_one_allowance(client, monkeypatch):
    """No shape is cheaper than another, so none of them is a way around the limit."""
    monkeypatch.setattr(settings, "public_tracking_rate_limit_attempts", 4)
    rate_limiter.reset()

    sequence = [OVERSIZED, "", "a/b/c", UNKNOWN, UNKNOWN]
    statuses = [get(client, reference).status_code for reference in sequence]

    assert statuses == [404, 404, 404, 404, 429]


def test_the_bare_track_path_also_consumes_the_allowance(client, monkeypatch):
    monkeypatch.setattr(settings, "public_tracking_rate_limit_attempts", 2)
    rate_limiter.reset()

    statuses = [client.get(TRACK).status_code for _ in range(3)]

    assert statuses == [404, 404, 429]


def test_a_rate_limited_oversized_request_still_returns_the_protected_429(client, monkeypatch):
    monkeypatch.setattr(settings, "public_tracking_rate_limit_attempts", 1)
    rate_limiter.reset()
    get(client, OVERSIZED)

    limited = get(client, SUBSTANTIALLY_OVERSIZED)

    assert limited.status_code == 429
    assert set(limited.json()) == {"code", "message"}
    assert limited.json()["code"] == "rate_limited"
    assert int(limited.headers["Retry-After"]) >= 1
    for header in PROTECTED_HEADERS:
        assert header in limited.headers
    assert "zzzz" not in limited.text.lower()


# --- A refused request must not reach the database ---------------------------


class _StatementCounter:
    """Counts SQL statements executed on an engine.

    Attached to the engine rather than to the session, so a query issued by *any* code
    path -- a dependency, a service, the ORM flushing -- is counted. A dependency that
    reads a row is exactly what this is looking for.
    """

    def __init__(self, engine):
        self.engine = engine
        self.statements: list[str] = []

    def __enter__(self):
        event.listen(self.engine, "before_cursor_execute", self._record)
        return self

    def __exit__(self, *_exc):
        event.remove(self.engine, "before_cursor_execute", self._record)
        return False

    def _record(self, _conn, _cursor, statement, *_args):  # noqa: ANN001
        self.statements.append(statement)

    @property
    def count(self) -> int:
        return len(self.statements)


def test_a_rate_limited_request_performs_no_database_query(client, db, engine, monkeypatch):
    """A refused caller costs the server a dictionary lookup and nothing more.

    Phase 3 resolved the organization settings row as a request dependency, so every
    refused request still ran ``SELECT ... FROM organization_settings``. The limiter
    statement was the first line of the handler and still ran second.
    """
    monkeypatch.setattr(settings, "public_tracking_rate_limit_attempts", 1)
    rate_limiter.reset()
    customer = make_customer(db)
    shipment = booked_shipment(db, customer)
    db.commit()

    # Spend the allowance. This one is allowed to query.
    assert get(client, shipment.public_id).status_code == 200

    with _StatementCounter(engine) as counter:
        refused = get(client, shipment.public_id)

    assert refused.status_code == 429
    assert counter.count == 0, f"a refused request ran {counter.statements}"


def test_a_rate_limited_request_performs_no_lookup_for_any_shape(client, db, engine, monkeypatch):
    monkeypatch.setattr(settings, "public_tracking_rate_limit_attempts", 1)
    rate_limiter.reset()
    get(client, UNKNOWN)

    with _StatementCounter(engine) as counter:
        for reference in (UNKNOWN, OVERSIZED, "", "a/b/c"):
            assert get(client, reference).status_code == 429
        assert client.get(TRACK).status_code == 429

    assert counter.count == 0, counter.statements


def test_an_invalid_reference_never_reaches_the_database(client, db, engine):
    """Validation happens in application code, before any query.

    This was true in Phase 3 for values that reached the handler; it is now true for the
    shapes that used to be rejected before the handler as well.
    """
    make_customer(db)
    db.commit()
    rate_limiter.reset()

    with _StatementCounter(engine) as counter:
        for reference in (OVERSIZED, "", "a/b/c", "rubbish", "STCA-000001"):
            assert get(client, reference).status_code == 404

    assert counter.count == 0, counter.statements


def test_a_valid_unknown_reference_does_reach_the_database(client, db, engine):
    """The counterpart, so the test above cannot pass by the endpoint doing nothing.

    This is also the timing difference DEC-0051 records honestly: a well-formed unknown
    reference costs a lookup, a malformed one does not.
    """
    make_customer(db)
    db.commit()
    rate_limiter.reset()

    with _StatementCounter(engine) as counter:
        assert get(client, UNKNOWN).status_code == 404

    assert counter.count >= 1


def test_a_successful_lookup_reads_the_timezone_after_resolving(client, db, engine):
    """The settings read still happens -- just not before the reference is known good."""
    customer = make_customer(db)
    shipment = booked_shipment(db, customer)
    db.commit()
    rate_limiter.reset()

    with _StatementCounter(engine) as counter:
        response = get(client, shipment.public_id)

    assert response.status_code == 200
    assert response.json()["timezone"]
    joined = " ".join(counter.statements).lower()
    assert "organization_settings" in joined
    # And the shipment was resolved before the settings row was read.
    order = [
        index
        for index, statement in enumerate(counter.statements)
        if "organization_settings" in statement.lower()
    ]
    shipments = [
        index
        for index, statement in enumerate(counter.statements)
        if "from shipments" in statement.lower()
    ]
    assert shipments and order and min(shipments) < min(order)


# --- The catch-all must not swallow anything else ----------------------------


def walk_api_routes(node=None, prefix=""):
    """Every leaf route, with the full path it answers on.

    ``app.routes`` does not hold the leaves. This FastAPI version keeps an included
    router as a single wrapper object carrying its prefix and the original router, so a
    flat scan of ``app.routes`` sees four entries and two opaque containers -- which is
    how a route-table assertion can pass while asserting nothing. Recursing through the
    wrappers is the only way to see what the application actually serves, and seeing that
    is the entire point of the tests below.
    """
    from app.main import app

    node = app.router if node is None else node

    context = getattr(node, "include_context", None)
    if context is not None:
        yield from walk_api_routes(context.included_router, prefix + (context.prefix or ""))
        return

    for route in getattr(node, "routes", None) or []:
        path = getattr(route, "path", None)
        if path is not None and getattr(route, "endpoint", None) is not None:
            yield prefix + path, route
        else:
            yield from walk_api_routes(route, prefix)


def test_every_catch_all_is_scoped_to_its_own_prefix():
    """A catch-all route is a liability if its scope is not pinned down.

    ``{reference:path}`` matches greedily, so the thing to prove is that each one's *prefix*
    is narrow and that nothing with its own handler lives underneath it.

    **There are two since Phase 11**, and both are catch-alls for the same reason: a plain
    ``{reference}`` does not match a value containing a separator, so ``/track/a/b`` and
    ``/shipments/a/b`` would miss their routes entirely and fall through to Starlette's
    router 404 -- a second, different failure shape on two surfaces whose whole design is
    that every failure looks identical (DEC-0059). The list is written out by name so that a
    third one appearing is a decision somebody reads rather than a diff nobody does.
    """
    paths = [path for path, _route in walk_api_routes()]

    catch_all = sorted(path for path in paths if path.endswith("{reference:path}"))
    assert catch_all == [
        "/api/v1/account/shipments/{reference:path}",
        "/api/v1/public/track/{reference:path}",
    ], paths

    for path in catch_all:
        prefix = path[: -len("{reference:path}")]
        shadowed = [other for other in paths if other.startswith(prefix) and other not in catch_all]
        assert shadowed == [], (prefix, shadowed)

    # The two prefixes are siblings: neither is inside the other, so neither swallows the
    # other's routes. The account one also sits behind an authenticated dependency, which
    # the public one deliberately does not have.
    assert not any(
        one != other and one.startswith(other[: -len("{reference:path}")])
        for one in catch_all
        for other in catch_all
    )

    # And the staff API is a sibling, not a descendant.
    assert any(path == "/api/v1/shipments" for path in paths), paths
    assert not any(path.startswith("/api/v1/public/") and "/track" not in path for path in paths), (
        paths
    )


def test_unrelated_staff_routes_are_not_shadowed(client, as_admin):
    """The staff API still answers on its own paths, with its own authorization."""
    assert as_admin.get("/api/v1/shipments").status_code == 200
    assert as_admin.get("/api/v1/customers").status_code == 200
    assert as_admin.get("/api/v1/settings").status_code == 200
    assert client.get("/health").status_code == 200
    assert client.get("/api/v1/openapi.json").status_code == 200


def test_a_staff_path_that_merely_resembles_the_public_one_is_untouched(client):
    """``/api/v1/public-something`` is not under the catch-all and must 404 normally."""
    response = client.get("/api/v1/publications")

    assert response.status_code in {401, 404}
    # It is not answered by the tracking policy.
    assert response.json().get("code") != "tracking_not_found"


def test_the_ordinary_lookups_still_work(client, db):
    """The correction must not have narrowed what legitimately resolves."""
    from app.services import package_service

    customer = make_customer(db, full_name="Nguyễn Thị Bích Hạnh")
    shipment = booked_shipment(db, customer, packages=3)
    db.commit()
    rate_limiter.reset()

    parent = get(client, shipment.public_id)
    assert parent.status_code == 200
    assert parent.json()["shipment_reference"] == shipment.public_id
    assert parent.json()["matched_reference_type"] == "shipment"

    reference = package_service.active_packages(db, shipment.id)[1].package_reference
    package = get(client, reference)
    assert package.status_code == 200
    assert package.json()["shipment_reference"] == shipment.public_id
    assert package.json()["selected_package_reference"] == reference
    assert package.json()["matched_reference_type"] == "package"

    # And the forgiving normalization the catch-all now carries end to end.
    assert get(client, shipment.public_id.lower()).status_code == 200
    assert get(client, f"{shipment.public_id}.").status_code == 200


def test_a_reference_exactly_at_the_bound_is_still_processed(client, db):
    """The bound rejects; it does not shift. 120 characters is refused as malformed, not
    as an oversized special case, and the answer is the same either way."""
    rate_limiter.reset()
    at_bound = "B" * MAX_INPUT_LENGTH
    past_bound = "B" * (MAX_INPUT_LENGTH + 1)

    first = get(client, at_bound)
    second = get(client, past_bound)

    assert first.status_code == second.status_code == 404
    assert first.json() == second.json()


def test_the_route_still_declares_no_security_dependency():
    """The correction added a route; it must not have added a dependency with it.

    Also the reason ``public_org_settings`` is gone rather than merely unused: a
    dependency that reads a row is exactly the thing this walk is looking for.
    """
    public = [
        (path, route) for path, route in walk_api_routes() if path.startswith("/api/v1/public")
    ]
    assert len(public) == 2, [path for path, _ in public]

    forbidden = {
        "current_user",
        "current_session",
        "org_settings",
        "public_org_settings",
        "_dependency",
    }
    for path, route in public:
        names = {
            getattr(dependency.call, "__name__", "") for dependency in route.dependant.dependencies
        }
        assert not names & forbidden, (path, sorted(names))
        # Exactly what a public route is allowed to want.
        assert names <= {"public_db_session", "public_client_key"}, (path, sorted(names))


def test_the_settings_dependency_is_gone_rather_than_merely_unused():
    """Removing the import is what stops it being reattached by a one-line mistake."""
    import app.api.public.deps as deps

    assert not hasattr(deps, "public_org_settings")
    assert not hasattr(deps, "PublicOrgSettings")
    assert "OrganizationSettings" not in vars(deps)
