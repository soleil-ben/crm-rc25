"""Phase 5B changed how the application is operated, not what it does.

`test_phase5a_integration_seam.py` is the Phase 5A standing proof and is unchanged. This
is its Phase 5B counterpart, covering the surfaces Phase 5B actually added -- structured
logging, the health and readiness endpoints, the configuration validator, and the
correlation middleware -- because a seam test that only inspects last phase's files stops
being evidence the moment a new file appears.

Four claims, each asserted rather than asserted-about:

1. **Phase 5B registered no provider.** The registry and both allowlists are still empty,
   `connected_api` is still refused, and integration health is still `not_configured`.
2. **Phase 5B reached no network.** No Phase 5B module imports an HTTP client or a
   provider structure, and exercising the new surfaces opens no socket.
3. **Phase 5B changed no contract.** The public allowlist is still 24 fields, the report
   definitions and metric values are untouched, and no import or export permission moved.
4. **Phase 5B exposed no private value.** Health and readiness say nothing about the
   installation, and the logging path is asserted against planted sentinels here as well
   as in `test_phase5b_logging.py` -- once through the filter directly, and once through a
   real request.
"""

from __future__ import annotations

import ast
import json
import logging
import socket
from pathlib import Path

import pytest
from sqlalchemy import func, select

from app.core.config import settings
from app.core.enums import Role, TrackingSourceMode
from app.integrations import registry
from app.models import (
    IntegrationJob,
    IntegrationProviderEvent,
    IntegrationWebhookInboxItem,
    OrganizationSettings,
)
from tests.report_fixtures import TZ, build_dataset

APP_ROOT = Path(__file__).resolve().parents[1] / "app"

#: The modules Phase 5B added or substantially changed.
PHASE_5B_MODULES = (
    "core/logging.py",
    "core/config.py",
    "main.py",
)


@pytest.fixture
def org(db):
    row = db.scalar(select(OrganizationSettings))
    row.office_timezone = TZ
    db.commit()
    return row


@pytest.fixture
def data(db, org):
    return build_dataset(db)


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
    return found


# --- 1. Phase 5B registered no provider -------------------------------------------------


def test_the_production_registry_is_still_empty():
    assert registry.PRODUCTION_ADAPTERS == {}


def test_both_resource_allowlists_are_still_empty():
    assert settings.integration_resource_host_list == []
    assert settings.integration_resource_path_prefix_list == []


def test_connected_api_is_still_refused():
    """Asserted against the constant the application actually enforces.

    The Phase 5A and 5B seam files both probed `leg_service.ALLOWED_SOURCE_MODES`, which
    does not exist, behind an `if allowed is not None` guard -- so the assertion never ran.
    The real gate is `PHASE_2_TRACKING_SOURCE_MODES`, checked in `leg_service.add_tracking
    _reference`. A guard that passes because it found nothing to check is not a guard,
    which is precisely the failure this closure review exists to catch.
    """
    from app.core.enums import PHASE_2_TRACKING_SOURCE_MODES

    assert not hasattr(leg_service_module(), "ALLOWED_SOURCE_MODES"), (
        "leg_service grew an ALLOWED_SOURCE_MODES; point this test at it as well"
    )
    assert TrackingSourceMode.CONNECTED_API not in PHASE_2_TRACKING_SOURCE_MODES
    assert set(PHASE_2_TRACKING_SOURCE_MODES) == {
        TrackingSourceMode.MANUAL,
        TrackingSourceMode.EXTERNAL_LINK,
    }


def leg_service_module():
    from app.services import leg_service

    return leg_service


def test_the_api_refuses_a_connected_api_tracking_reference(as_admin, db, data):
    """End to end, through the route, because a constant is only half the proof."""
    shipment = data.shipment("repeat_sep")  # three packages, two legs
    legs = as_admin.get(f"/api/v1/shipments/{shipment.id}/legs").json()
    assert legs, "the fixture shipment has no transport leg to attach a reference to"
    leg_id = legs[0]["id"]

    response = as_admin.post(
        f"/api/v1/legs/{leg_id}/tracking-references",
        json={
            "carrier_name": "Some Carrier",
            "tracking_number": "TEST123456789",
            "source_mode": "connected_api",
        },
    )

    assert response.status_code == 422, response.text
    body = response.json()
    assert body["field"] == "source_mode"
    assert "no provider account is connected" in body["message"].lower()
    # And the refusal names only the two modes that do exist.
    assert body["detail"]["available"] == ["manual", "external_link"]


def test_integration_health_is_still_not_configured(as_admin):
    body = as_admin.get("/api/v1/integrations/health").json()

    assert body["any_provider_configured"] is False
    for connection in body.get("connections", []):
        assert connection["state"] == "not_configured"


def test_no_webhook_endpoint_exists(client):
    paths = client.get("/api/v1/openapi.json").json()["paths"]

    for path in paths:
        assert "webhook" not in path.lower()
        assert "callback" not in path.lower()


def test_phase_5b_added_no_route_to_the_versioned_api(client):
    """A phase about operations should not have grown the product API.

    The health endpoints *are* in the OpenAPI document -- FastAPI documents every route on
    the application, not only the ones under a prefix -- so the check is that nothing new
    appeared under `/api/v1`, which is the surface with sessions, permissions and customer
    data behind it.
    """
    paths = set(client.get("/api/v1/openapi.json").json()["paths"])
    versioned = {path for path in paths if path.startswith("/api/v1")}

    # The Phase 5B endpoints live at the application root, not under the versioned API.
    for added in ("/api/v1/health", "/api/v1/health/live", "/api/v1/health/ready"):
        assert added not in versioned

    # `/api/v1/integrations/health` is the Phase 4A integration panel's endpoint and
    # predates this phase. It is expected, and its presence is not a Phase 5B addition.
    health_paths = {path for path in versioned if "health" in path}
    assert health_paths == {"/api/v1/integrations/health"}

    # No endpoint exposing logs or correlation state. Matched on a path segment rather
    # than a substring: `/api/v1/auth/logout` contains "log" and is Phase 1.
    for path in versioned:
        segments = set(path.strip("/").split("/"))
        assert "logs" not in segments
        assert "correlation" not in segments


# --- 2. Phase 5B reached no network -----------------------------------------------------


@pytest.mark.parametrize("relative", PHASE_5B_MODULES)
def test_no_phase_5b_module_imports_an_http_client(relative):
    modules = _imported_modules(APP_ROOT / relative)

    for module in modules:
        root = module.split(".")[0]
        assert root not in {"httpx", "requests", "urllib", "aiohttp", "http", "socket"}, (
            f"{relative} imports {module}"
        )


#: Files Phase 5B created outright. `core/config.py` and `main.py` are shared files that
#: carried Phase 4A text before this phase began -- `config.py` has held a comment since
#: 071bd01 stating that no request has ever been made to ShipStation, which is a
#: disclaimer rather than a registration, and a blunt name check would flag it.
PHASE_5B_NEW_MODULES = ("core/logging.py",)


@pytest.mark.parametrize("relative", PHASE_5B_NEW_MODULES)
def test_no_module_phase_5b_created_names_a_provider_product(relative):
    source = (APP_ROOT / relative).read_text(encoding="utf-8").lower()

    for name in ("shipstation", "shipengine", "easypost", "aftership"):
        assert name not in source, f"{relative} names {name}"


def test_the_shared_files_mention_a_provider_only_to_deny_one(db):
    """What matters is not whether the word appears, but whether anything is configured.

    `config.py` names ShipStation in a Phase 4A comment. The load-bearing assertion is
    that the settings it describes are still empty, which is checked above and again
    here from the running configuration.
    """
    assert settings.integration_resource_host_list == []
    assert settings.integration_resource_path_prefix_list == []
    assert registry.PRODUCTION_ADAPTERS == {}


def test_the_only_integration_import_in_phase_5b_is_the_redaction_helper():
    """`app/core/logging.py` imports `redact_text`, and that is deliberate.

    `app.integrations.redaction` is named for where it was first needed, not for what it
    couples to: at module level it imports only `hashlib`, `re` and `urllib.parse`. It
    registers no adapter and opens no socket. This test pins that down, so the import
    cannot quietly become a route into the provider layer.
    """
    modules = _imported_modules(APP_ROOT / "core" / "logging.py")
    integration_imports = {m for m in modules if m.startswith("app.integrations")}

    assert integration_imports == {"app.integrations.redaction"}

    # Every import in redaction.py, including the ones inside functions, is either the
    # standard library or the adapter error type it needs to recognise. It reaches
    # nothing that could make a request.
    redaction_imports = _imported_modules(APP_ROOT / "integrations" / "redaction.py")
    allowed_stdlib = {"hashlib", "hmac", "re", "urllib", "__future__"}
    for module in redaction_imports:
        root = module.split(".")[0]
        assert root in allowed_stdlib or module == "app.integrations.adapter", (
            f"redaction.py grew an import that is neither stdlib nor the adapter type: {module}"
        )


def test_the_phase_5b_surfaces_open_no_socket(as_admin, client, monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("Phase 5B code attempted a network connection")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket.socket, "connect_ex", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)

    assert client.get("/health").status_code == 200
    assert client.get("/health/live").status_code == 200
    assert client.get("/health/ready").status_code in (200, 503)
    assert as_admin.get("/api/v1/integrations/health").status_code == 200


def test_the_phase_5b_surfaces_create_no_integration_row(as_admin, client, db, data):
    models = (IntegrationJob, IntegrationWebhookInboxItem, IntegrationProviderEvent)
    before = {m.__name__: db.scalar(select(func.count(m.id))) for m in models}

    client.get("/health")
    client.get("/health/ready")
    as_admin.get("/api/v1/integrations/health")

    db.expire_all()
    after = {m.__name__: db.scalar(select(func.count(m.id))) for m in models}

    assert before == after == dict.fromkeys(before, 0)


# --- 3. Phase 5B changed no contract ----------------------------------------------------


def test_the_public_result_model_still_has_exactly_twenty_five_fields():
    """The phase brief names this number. Phase 5A1's addition was to a nested model.

    Registered in `SUPERSEDED_ASSERTIONS.md` (AS-36): twenty-four until RC-UAT-19 added
    ``carrier_links`` (DEC-0224, OD-91, OD-92) -- the only new field.
    """
    from app.schemas.public_tracking import PublicTrackingResult

    assert len(PublicTrackingResult.model_fields) == 25
    assert "carrier_links" in PublicTrackingResult.model_fields


def test_public_tracking_gained_no_provider_field(client, db, data):
    shipment = data.shipment("repeat_sep")

    body = client.get(f"/api/v1/public/track/{shipment.public_id}").json()

    blob = json.dumps(body).lower()
    for term in (
        "provider",
        "freshness",
        "last_sync",
        "last_successful_sync",
        "connected",
        "webhook",
        "stale",
        "correlation",
    ):
        assert term not in blob, f"the public payload mentions {term}"


def test_a_public_response_carries_no_correlation_header(client, db, data):
    """DEC-0085. Every public failure must remain byte-identical to every other."""
    shipment = data.shipment("repeat_sep")

    found = client.get(f"/api/v1/public/track/{shipment.public_id}")
    missing = client.get("/api/v1/public/track/SX-CAV-ABCDEFGHJKLM")

    assert "X-Correlation-ID" not in found.headers
    assert "X-Correlation-ID" not in missing.headers


def test_two_public_failures_are_still_byte_identical(client, db, data):
    first = client.get("/api/v1/public/track/SX-CAV-ABCDEFGHJKLM")
    second = client.get("/api/v1/public/track/SX-CAD-MLKJHGFEDCBA")

    assert first.status_code == second.status_code
    assert first.text == second.text
    assert dict(first.headers) == dict(second.headers)


def test_the_report_key_set_is_unchanged(db):
    """Phase 5B measured the reports; it did not redefine one."""
    from app.services import report_service

    # Marketing, not Operations: since the role merge (DEC-0088) Operations holds
    # financial:read and therefore also receives FINANCIAL_REPORT_KEY. Marketing is now
    # the role that reads the base set and nothing more.
    assert report_service.available_report_keys(Role.MARKETING) == report_service.REPORT_KEYS
    assert report_service.MAX_PERIOD_DAYS == 731


def test_report_definitions_still_promise_no_provider_data(as_admin):
    body = as_admin.get("/api/v1/reports/definitions").json()

    blob = json.dumps(body).lower()
    for term in ("shipstation", "carrier api", "synchronis", "synchroniz", "real-time"):
        assert term not in blob


def test_financial_gating_still_follows_the_permission_exactly(db):
    """Not "only admin" -- that would hardcode a matrix that is still an open decision."""
    from app.core.permissions import Permission, permissions_for
    from app.services import report_service

    for role in Role:
        shown = "financial_summary" in report_service.available_report_keys(role)
        allowed = Permission.FINANCIAL_READ in permissions_for(role)
        assert shown == allowed, f"{role.value}: shown={shown} allowed={allowed}"


def test_no_import_or_export_permission_was_weakened():
    """Phase 5A granted these to Admin only, pending the owner's decision (DEC-0082)."""
    from app.core.permissions import Permission, permissions_for

    guarded = (
        Permission.IMPORT_PREVIEW,
        Permission.IMPORT_COMMIT,
        Permission.EXPORT_CUSTOMERS,
        Permission.EXPORT_SHIPMENTS,
    )
    for permission in guarded:
        holders = {role.value for role in Role if permission in permissions_for(role)}
        assert holders == {"admin"}, f"{permission} is held by {holders}, expected admin only"


def test_the_export_allowlists_carry_no_provider_column():
    from app.services import export_service

    for definition in export_service.EXPORTS.values():
        for column in definition.columns:
            haystack = f"{column.key} {column.header}".lower()
            for term in ("provider", "freshness", "last_sync", "webhook", "connected"):
                assert term not in haystack, f"{definition.key}.{column.key}"


# --- 4. Phase 5B exposed no private value -----------------------------------------------

#: Anything that would tell an anonymous caller about the installation.
FORBIDDEN_IN_HEALTH = (
    "production",
    "development",
    "staging",
    "test",
    "sqlite",
    "traceback",
    "secret",
    "password",
    "token",
    "alembic",
    "america/toronto",
    ".py",
    "solaris_crm.db",
    "e5623fcf8018",
)


@pytest.mark.parametrize("path", ["/health", "/health/live", "/health/ready"])
def test_a_health_response_says_nothing_about_the_installation(client, path):
    body = client.get(path).text.lower()

    for term in FORBIDDEN_IN_HEALTH:
        assert term not in body, f"{path} mentions {term}"


def test_readiness_names_checks_but_not_internals(client):
    body = client.get("/health/ready").json()

    assert set(body["checks"]) == {"database", "migrations", "timezone"}
    assert set(body["checks"].values()) <= {"ok", "failed"}


def test_a_request_log_never_carries_the_public_reference(client, db, data, caplog):
    """The route template is logged; the resolved path would contain the reference."""
    shipment = data.shipment("repeat_sep")

    with caplog.at_level(logging.INFO):
        client.get(f"/api/v1/public/track/{shipment.public_id}")

    records = [r for r in caplog.records if r.name.startswith("solaris")]
    blob = "\n".join(f"{r.getMessage()} {r.__dict__}" for r in records)

    assert shipment.public_id not in blob
    suffix = shipment.public_id.split("-")[-1]
    assert suffix not in blob


def test_a_customer_name_cannot_reach_a_log_through_a_request(client, db, caplog):
    """The sentinel test at the unit level, repeated through a real request path."""
    from tests.conftest import make_customer

    sentinel = "Zzyzx Sentinel Nguyễn"
    customer = make_customer(db, full_name=sentinel, email="zzyzx.sentinel@demo.example.com")
    db.commit()

    with caplog.at_level(logging.DEBUG):
        client.get(f"/api/v1/customers/{customer.id}")

    records = [r for r in caplog.records if r.name.startswith("solaris")]
    blob = "\n".join(f"{r.getMessage()} {r.__dict__}" for r in records)

    assert sentinel not in blob
    assert "zzyzx.sentinel@demo.example.com" not in blob


def test_an_error_response_carries_no_stack_trace(as_admin):
    response = as_admin.get("/api/v1/customers/99999999")

    assert response.status_code == 404
    assert "Traceback" not in response.text
    assert ".py" not in response.text


# --- The Phase 5A seam file itself ------------------------------------------------------


def test_the_phase_5a_seam_file_is_still_present():
    """The phase brief requires it preserved. A deleted guard is a removed guarantee."""
    seam = Path(__file__).resolve().parent / "test_phase5a_integration_seam.py"

    assert seam.exists()
    source = seam.read_text(encoding="utf-8")
    assert "test_the_production_adapter_registry_is_still_empty" in source
    assert "test_connected_api_is_still_refused" in source
