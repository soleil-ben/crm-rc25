"""Phase 5A did not touch the provider seam, and cannot have (DEC-0075).

The owner deferred ShipStation and every live-provider task to the final phase. Reporting
is the feature most likely to erode that boundary without anybody noticing, because a
report wants a column for every dimension and an empty column looks like a bug rather than
a truth. Import and export are the features most likely to reach a network.

This file is the standing proof. It asserts three separate things:

1. **Nothing new registers a provider.** The production registry is empty, the resource
   allowlist is empty, and ``connected_api`` is still refused.
2. **No Phase 5A code path can reach a provider.** No report, export, or import module
   imports a provider structure, creates an integration job, or opens a socket.
3. **Nothing invents freshness.** No report displays a last-update, last-successful-sync,
   or staleness figure, because no such value exists.
"""

from __future__ import annotations

import ast
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
from app.services import export_service, report_service
from app.services.activity_service import LifecycleThresholds
from tests.report_fixtures import PERIOD_FROM, PERIOD_TO, TZ, build_dataset

APP_ROOT = Path(__file__).resolve().parents[1] / "app"

#: The modules Phase 5A added or substantially changed.
PHASE_5A_MODULES = (
    "services/report_service.py",
    "services/export_service.py",
    "services/csv_safety.py",
    "services/customer_import_service.py",
    "api/v1/routes/reports.py",
    "api/v1/routes/exports.py",
    "api/v1/routes/imports.py",
    "schemas/report.py",
    "schemas/imports.py",
    "models/imports.py",
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


@pytest.fixture
def period(org):
    return report_service.resolve_period(from_date=PERIOD_FROM, to_date=PERIOD_TO, org=org)


# --- 1. Nothing registers a provider --------------------------------------------


def test_the_production_adapter_registry_is_still_empty():
    assert registry.PRODUCTION_ADAPTERS == {}


def test_the_production_resource_allowlist_is_still_empty():
    assert settings.integration_resource_host_list == []
    assert settings.integration_resource_path_prefix_list == []


def test_connected_api_is_still_refused(db, data):
    """A Phase 5A route must not have quietly widened the tracking source vocabulary.

    Strengthened in Phase 5B's closure review. The original lookup was for
    `leg_service.ALLOWED_SOURCE_MODES`, which does not exist, behind an
    `if allowed is not None` guard -- so this test passed without asserting anything about
    `connected_api` at all. The constant the application actually enforces is
    `PHASE_2_TRACKING_SOURCE_MODES`. The original lines are kept so the check still covers
    an `ALLOWED_SOURCE_MODES` if one is ever introduced.
    """
    from app.core.enums import PHASE_2_TRACKING_SOURCE_MODES
    from app.services import leg_service

    assert TrackingSourceMode.CONNECTED_API in set(TrackingSourceMode)

    # The real gate.
    assert TrackingSourceMode.CONNECTED_API not in PHASE_2_TRACKING_SOURCE_MODES

    # And the original, for a constant that may appear later.
    allowed = getattr(leg_service, "ALLOWED_SOURCE_MODES", None)
    if allowed is not None:
        assert TrackingSourceMode.CONNECTED_API not in allowed


def test_integration_health_is_still_not_configured(as_admin, db):
    body = as_admin.get("/api/v1/integrations/health").json()
    assert body["any_provider_configured"] is False
    for connection in body.get("connections", []):
        assert connection["state"] == "not_configured"


# --- 2. No Phase 5A code path can reach a provider ---------------------------------


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
    return found


@pytest.mark.parametrize("relative", PHASE_5A_MODULES)
def test_no_phase_5a_module_imports_an_integration_structure(relative):
    """Reporting on tracking source must not mean importing the provider layer."""
    modules = _imported_modules(APP_ROOT / relative)
    for module in modules:
        assert not module.startswith("app.integrations"), f"{relative} imports {module}"
        assert "workers" not in module, f"{relative} imports {module}"


@pytest.mark.parametrize("relative", PHASE_5A_MODULES)
def test_no_phase_5a_module_names_a_provider_product(relative):
    source = (APP_ROOT / relative).read_text(encoding="utf-8").lower()
    for name in ("shipstation", "shipengine", "easypost", "aftership"):
        assert name not in source, f"{relative} names {name}"


@pytest.mark.parametrize("relative", PHASE_5A_MODULES)
def test_no_phase_5a_module_imports_an_http_client(relative):
    """Nothing in reporting, export, or import may make an outbound request."""
    modules = _imported_modules(APP_ROOT / relative)
    for module in modules:
        root = module.split(".")[0]
        assert root not in {"httpx", "requests", "urllib", "aiohttp", "http"}, (
            f"{relative} imports {module}"
        )


def test_reports_exports_and_imports_create_no_integration_row(as_admin, db, data):
    """The whole Phase 5A surface, exercised, changes nothing in the integration tables."""
    before = {
        model.__name__: db.scalar(select(func.count(model.id)))
        for model in (IntegrationJob, IntegrationWebhookInboxItem, IntegrationProviderEvent)
    }

    assert (
        as_admin.get(
            "/api/v1/reports", params={"from": "2026-09-01", "to": "2026-09-30"}
        ).status_code
        == 200
    )
    assert as_admin.get("/api/v1/exports/customers.csv").status_code == 200
    assert as_admin.get("/api/v1/exports/shipments.csv").status_code == 200
    assert as_admin.get("/api/v1/exports/packages.csv").status_code == 200
    assert as_admin.get("/api/v1/imports/customers/template.csv").status_code == 200

    db.expire_all()
    after = {
        model.__name__: db.scalar(select(func.count(model.id)))
        for model in (IntegrationJob, IntegrationWebhookInboxItem, IntegrationProviderEvent)
    }
    assert before == after == dict.fromkeys(before, 0)


def test_no_phase_5a_request_opens_a_socket(as_admin, db, data, monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("Phase 5A code attempted a network connection")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket.socket, "connect_ex", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)

    assert as_admin.get("/api/v1/reports").status_code == 200
    assert as_admin.get("/api/v1/exports/customers.csv").status_code == 200
    assert as_admin.get("/api/v1/exports/reports/route_mix.csv").status_code == 200


def test_no_webhook_endpoint_exists(client):
    """A provider delivery has nowhere to arrive."""
    from fastapi.testclient import TestClient

    from app.main import app

    paths = TestClient(app).get("/api/v1/openapi.json").json()["paths"]
    for path in paths:
        assert "webhook" not in path.lower()
        assert "callback" not in path.lower()


# --- 3. Nothing invents freshness ---------------------------------------------------


def test_no_report_carries_a_freshness_or_sync_field(db, data, period):
    tables = report_service.build_all(
        db,
        period=period,
        thresholds=LifecycleThresholds(),
        route_groups=None,
        role=Role.ADMIN,
    )
    banned = (
        "last_sync",
        "last_successful_sync",
        "last_synced",
        "freshness",
        "stale",
        "last_carrier_event",
        "last_update_from_carrier",
    )
    for table in tables:
        serialized = str(table.to_dict()).lower()
        for term in banned:
            assert term not in serialized, f"{table.key} mentions {term}"


def test_the_exception_report_offers_no_connected_api_column(db, data, period):
    table = report_service.shipment_exceptions(db, period, None)
    keys = {row["key"] for row in table.rows if row["group"] == "tracking_source"}
    assert "connected_api" not in keys
    assert keys == {"manual", "external_link", "none"}


def test_no_export_allowlist_carries_a_provider_or_freshness_column():
    for definition in export_service.EXPORTS.values():
        for column in definition.columns:
            haystack = f"{column.key} {column.header}".lower()
            for term in ("provider", "freshness", "last_sync", "webhook", "connected"):
                assert term not in haystack, f"{definition.key}.{column.key}"


def test_the_report_definitions_endpoint_promises_no_provider_data(as_admin, db):
    body = as_admin.get("/api/v1/reports/definitions").json()
    blob = str(body).lower()
    for term in ("shipstation", "carrier api", "synchronis", "synchroniz", "real-time"):
        assert term not in blob


# --- Public tracking is unchanged -----------------------------------------------------


def test_public_tracking_still_answers_and_reveals_nothing_new(client, db, data):
    """A reporting or export change must not widen the public allowlist."""
    shipment = data.shipment("repeat_sep")
    response = client.get(f"/api/v1/public/track/{shipment.public_id}")
    assert response.status_code == 200
    body = response.json()

    # The 24-field allowlist is asserted in full by test_public_contract_unchanged.py.
    # What matters here is that nothing Phase 5A added leaked into it.
    blob = str(body).lower()
    for term in (
        "cost",
        "selling",
        "revenue",
        "source_record_id",
        "import",
        "internal_note",
        "lifecycle",
        "segment",
    ):
        assert term not in blob, f"public payload mentions {term}"


def test_an_unknown_public_reference_is_still_a_generic_404(client, db, data):
    response = client.get("/api/v1/public/track/SX-CAV-ZZZZZZZZZZZZ")
    assert response.status_code == 404
    assert "detail" not in response.json() or response.json().get("detail") is None
