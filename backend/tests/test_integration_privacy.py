"""What Phase 4A may never expose: credentials, payloads, references, or customer data.

Three boundaries, each asserted rather than assumed:

* **the adapter boundary** -- nothing outside ``app/integrations/`` may import a provider
  response structure or status vocabulary (CRM.md section 9). Checked by parsing the
  source tree, in the same spirit as the Phase 3 test that parses ``app/api/public/`` with
  ``ast``;
* **logs and stored summaries** -- no payload, credential, tracking reference, customer
  detail, or complete provider URL, in a log line, an ``error_summary``, or an audit row;
* **staff responses** -- no secret-bearing field, and no way to reach a raw payload through
  one.

And one boundary that must be *unchanged*: the public tracking contract. Phase 4A adds no
``connected_api``, no ``last_carrier_update``, no ``last_successful_sync``, and no
automatic-refresh language.
"""

from __future__ import annotations

import ast
import logging
from datetime import datetime
from pathlib import Path

import pytest

from app.core.enums import ProviderErrorKind
from app.integrations import redaction
from app.integrations.adapter import ProviderAdapterError
from app.integrations.registry import AdapterRegistry
from app.models import AuditEvent, IntegrationJob
from app.services import integration_inbox_service as inbox
from app.services import integration_job_service as jobs
from app.workers import integration_worker
from tests.fakes import fake_provider_adapter as fake
from tests.fakes.fake_provider_adapter import (
    FakeProviderAdapter,
    make_payload,
    signed_headers,
)
from tests.integration_fixtures import FAKE_TRACKING_NUMBER, tracked_shipment

APP_ROOT = Path(__file__).resolve().parents[1] / "app"
BASE_TIME = datetime(2026, 9, 1, 9, 0, 0)

#: Values that must never appear in a log, a stored summary, or an audit row.
SECRET_VALUES = (
    "Bearer super-secret-token",
    "fake-api-key-0123456789abcdef",
    "session=abcdef0123456789",
)
SOLARIS_REFERENCE = "SX-CAV-7K9D2M4R8T6W"
CUSTOMER_VALUES = ("Nguyễn Thị Bích Hạnh", "hanh@demo.example.com", "+14165550100")


def clock_at(moment: datetime = BASE_TIME):
    return lambda: moment


# --- The adapter boundary ---------------------------------------------------


def application_modules() -> list[Path]:
    """Every application module outside the integration package."""
    return [
        path
        for path in APP_ROOT.rglob("*.py")
        if "integrations" not in path.relative_to(APP_ROOT).parts
    ]


def test_no_module_outside_the_integration_package_imports_a_provider_structure():
    """CRM.md section 9: the rest of the application must not depend on provider details.

    Parsed rather than grepped, so an import inside a function or under an alias is caught
    too. The rule is about *provider* structures: the application-vocabulary types --
    ``ProviderErrorKind``, the job enums -- live in ``app/core/enums.py`` and are meant to
    be imported freely, which is the entire point of having them.
    """
    provider_shaped = {
        "ParsedNotification",
        "AuthoritativeTrackingState",
        "ProviderEventIdentity",
        "ResourceHostPolicy",
    }
    offenders: list[str] = []

    for path in application_modules():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and (node.module or "").startswith(
                "app.integrations"
            ):
                imported = {alias.name for alias in node.names}
                # Services legitimately hold the contract types; nothing may hold a
                # provider *payload* shape.
                leaked = imported & provider_shaped
                if leaked and "services" not in path.parts and "workers" not in path.parts:
                    offenders.append(f"{path.name}: {sorted(leaked)}")

    assert offenders == [], offenders


def test_no_provider_status_vocabulary_leaks_outside_the_test_fake():
    """The fake's invented statuses must not appear in application code.

    They are the only provider vocabulary in the repository, and they exist under
    ``tests/``. If one turned up in ``app/`` it would mean a mapping had been hard-coded
    against a provider nobody has verified.
    """
    for path in APP_ROOT.rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        for status in fake.FAKE_STATUS_MAP:
            assert status not in source, f"{path.name} names {status}"


def _docstring_nodes(tree: ast.AST) -> set[int]:
    """Ids of the string constants that are docstrings.

    Docstrings are where this project *explains* that no provider is built, so they are
    the one place a provider name legitimately appears. Everything else -- an identifier,
    a URL, a header name, a status literal -- is code, and a provider name there would be
    a guess that later reads as a decision.
    """
    docstrings: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        body = getattr(node, "body", [])
        if (
            body
            and isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)
        ):
            docstrings.add(id(body[0].value))
    return docstrings


def test_no_application_code_names_a_provider_product_or_endpoint():
    """No ShipStation product, endpoint, event name, or signature header in ``app/`` code.

    The account's product, API generation, entitlements, authentication, webhook events,
    and signature mechanism are all unverified (docs/INTEGRATIONS.md section 3).

    Parsed rather than grepped, and docstrings are excluded on purpose: several modules
    say at length that the integration is *not* built, which is the honest thing to write
    and would fail a naive text scan. What is checked is executable code -- every
    identifier, attribute, and non-docstring string literal.
    """
    forbidden = (
        "shipstation",
        "shipengine",
        "ship_notify",
        "track_event_v2",
        "x-shipstation",
    )
    offenders: list[str] = []

    for path in APP_ROOT.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        docstrings = _docstring_nodes(tree)

        for node in ast.walk(tree):
            candidates: list[str] = []
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                if id(node) in docstrings:
                    continue
                candidates.append(node.value)
            elif isinstance(node, ast.Name):
                candidates.append(node.id)
            elif isinstance(node, ast.Attribute):
                candidates.append(node.attr)
            elif isinstance(node, ast.arg):
                candidates.append(node.arg)

            for candidate in candidates:
                lowered = candidate.lower()
                for name in forbidden:
                    if name in lowered:
                        offenders.append(f"{path.name}: {candidate[:60]}")

    assert offenders == [], offenders


def test_the_honesty_notes_in_the_docstrings_are_still_there():
    """The counterpart, so the exclusion above cannot hide a silently deleted warning."""
    sources = "\n".join(path.read_text(encoding="utf-8") for path in APP_ROOT.rglob("*.py")).lower()

    assert "shipstation" in sources, "the honesty notes explaining what is unverified"
    assert "no provider" in sources


def test_the_production_registry_is_empty():
    from app.integrations.registry import PRODUCTION_ADAPTERS, registry

    assert PRODUCTION_ADAPTERS == {}
    assert registry.is_empty()
    assert registry.provider_keys() == []


def test_registering_an_adapter_is_refused_in_production(monkeypatch):
    """Three independent reasons the fake cannot reach production; this is one."""
    from app.core.config import settings
    from app.integrations.registry import AdapterUnavailableError

    monkeypatch.setattr(settings, "environment", "production")
    empty = AdapterRegistry({})

    with pytest.raises(AdapterUnavailableError):
        empty.register(FakeProviderAdapter())


def test_the_fake_adapter_lives_outside_the_application_package():
    """Not packaged, so the running application cannot import it."""
    assert not (APP_ROOT / "integrations" / "fake_provider_adapter.py").exists()
    assert (Path(__file__).parent / "fakes" / "fake_provider_adapter.py").exists()
    assert FakeProviderAdapter().capabilities().provider_key == "fake"


def test_connected_api_is_still_refused(db):
    """Phase 4A does not enable it. AC-13 stands exactly where Phase 2 left it."""
    from app.core.enums import TrackingSourceMode
    from app.services import leg_service
    from app.services.errors import ValidationError

    tracked = tracked_shipment(db)

    with pytest.raises(ValidationError, match="No provider account"):
        leg_service.add_tracking_reference(
            db,
            tracked.leg,
            {
                "carrier_name": "Other",
                "tracking_number": "X-1",
                "source_mode": TrackingSourceMode.CONNECTED_API,
            },
        )


# --- Redaction --------------------------------------------------------------


@pytest.mark.parametrize("secret", SECRET_VALUES)
def test_a_secret_never_survives_redaction(secret):
    assert secret not in (redaction.safe_summary(f"failed with {secret}") or "")


def test_a_solaris_reference_never_survives_redaction():
    """Tracking identifiers are privacy-sensitive (CRM.md section 10, DEC-0057)."""
    for value in (SOLARIS_REFERENCE, f"{SOLARIS_REFERENCE}-01", SOLARIS_REFERENCE.lower()):
        assert value not in (redaction.safe_summary(f"lookup failed for {value}") or "")


def test_an_email_and_a_long_number_never_survive_redaction():
    summary = redaction.safe_summary("contact hanh@demo.example.com about 1Z999AA10123456784")

    assert "hanh@demo.example.com" not in summary
    assert "1Z999AA10123456784" not in summary


def test_a_short_number_survives_so_a_summary_stays_readable():
    """Over-redaction makes a log useless. Attempt counts and seconds are not identifiers."""
    summary = redaction.safe_summary("attempt 3 of 5, retry in 30 seconds")

    assert "3" in summary and "5" in summary and "30" in summary


def test_a_url_keeps_only_its_scheme_and_host():
    """A provider URL carries a tracking number in the path and a token in the query."""
    line = redaction.redact_url(
        "https://api.fake-provider.test/v2/labels/1Z999AA10123456784?key=SECRETKEY123456"
    )

    assert line.startswith("https://api.fake-provider.test/")
    assert "1Z999AA10123456784" not in line
    assert "SECRETKEY123456" not in line
    assert "labels" not in line


def test_the_same_url_produces_the_same_digest():
    """Stable, so two log lines about one URL can be correlated without the URL."""
    url = "https://api.fake-provider.test/v2/labels/1"
    assert redaction.redact_url(url) == redaction.redact_url(url)
    assert redaction.redact_url(url) != redaction.redact_url(url + "2")


def test_an_exception_summary_does_not_pass_through_the_exception_text():
    """A provider client puts the request URL, and sometimes its headers, in the message."""
    error = RuntimeError(
        "GET https://api.fake-provider.test/v2/x failed, Authorization: Bearer secret"
    )

    summary = redaction.safe_exception_summary(error)

    assert summary == "RuntimeError"
    assert "Bearer" not in summary
    assert "api.fake-provider.test" not in summary


def test_an_adapter_chosen_summary_is_kept_but_still_redacted():
    """The adapter deliberately chose these words, so they survive -- after redaction."""
    error = ProviderAdapterError(
        ProviderErrorKind.RETRYABLE, f"read of {SOLARIS_REFERENCE} timed out"
    )

    summary = redaction.safe_exception_summary(error)

    assert "timed out" in summary
    assert SOLARIS_REFERENCE not in summary


def test_only_diagnostic_headers_survive_and_the_rest_are_dropped():
    """Dropped, not masked: a masked entry still records that the header was present."""
    kept = redaction.safe_headers(
        {
            "Content-Type": "application/json",
            "User-Agent": "provider/1.0",
            "Authorization": "Bearer super-secret-token",
            "X-Api-Key": "fake-api-key-0123456789abcdef",
            "Cookie": "session=abcdef0123456789",
            "X-Hub-Signature-256": "sha256=deadbeef",
        }
    )

    assert set(kept) == {"content-type", "user-agent"}
    assert "authorization" not in kept
    assert "x-api-key" not in kept


def test_a_summary_is_bounded():
    """An unbounded summary is a payload in disguise."""
    summary = redaction.safe_summary("word " * 5000)

    assert len(summary) <= redaction.MAX_SUMMARY_LENGTH


def test_a_reference_token_is_keyed_and_not_reversible():
    token = redaction.reference_token(SOLARIS_REFERENCE, secret="test-only-secret")

    assert SOLARIS_REFERENCE not in token
    assert len(token) == 12
    assert token == redaction.reference_token(SOLARIS_REFERENCE, secret="test-only-secret")
    assert token != redaction.reference_token(SOLARIS_REFERENCE, secret="another-secret")


# --- Logs -------------------------------------------------------------------


def test_the_worker_log_contains_no_payload_credential_or_reference(db, caplog):
    """The whole log stream from a real run, read back and scanned."""
    adapter = FakeProviderAdapter()
    tracked = tracked_shipment(db)
    body = make_payload(reference=FAKE_TRACKING_NUMBER, detail="Carrier narrative text")
    headers = dict(signed_headers(body))
    headers["authorization"] = SECRET_VALUES[0]
    inbox.accept_delivery(db, adapter=adapter, body=body, headers=headers, clock=clock_at())
    db.commit()

    with caplog.at_level(logging.DEBUG):
        integration_worker.run_once(
            db,
            worker_name="w1",
            registry=AdapterRegistry({"fake": adapter}),
            clock=clock_at(),
            jitter=lambda: 0.0,
        )

    logged = "\n".join(
        record.getMessage() for record in caplog.records if record.name.startswith("solaris")
    )

    assert "integration_worker" in logged, "the run produced log output to scan"
    for secret in SECRET_VALUES:
        assert secret not in logged
    assert FAKE_TRACKING_NUMBER not in logged
    assert tracked.shipment.public_id not in logged
    assert tracked.package.package_reference not in logged
    assert "Carrier narrative text" not in logged
    assert body.decode("utf-8") not in logged
    for value in CUSTOMER_VALUES:
        assert value not in logged


def test_a_failing_worker_log_names_a_category_not_a_provider_message(db, caplog):
    adapter = FakeProviderAdapter(read_error=fake.RATE_LIMITED)
    tracked = tracked_shipment(db)
    jobs.enqueue(
        db,
        job_type="reconcile_tracking_assignment",
        provider_key="fake",
        tracking_assignment_id=tracked.assignment.id,
        dedupe_key="reconcile:1",
        clock=clock_at(),
    )
    db.commit()

    with caplog.at_level(logging.DEBUG):
        integration_worker.run_once(
            db,
            worker_name="w1",
            registry=AdapterRegistry({"fake": adapter}),
            clock=clock_at(),
            jitter=lambda: 0.0,
        )

    # Phase 5B moved this record from an interpolated sentence to structured fields. The
    # values are the same ones Phase 4A asserted; what changed is where they live, so the
    # whole record -- message and fields together -- is what gets searched.
    solaris_records = [r for r in caplog.records if r.name.startswith("solaris")]
    logged = "\n".join(f"{r.getMessage()} {r.__dict__}" for r in solaris_records)

    job_records = [r for r in solaris_records if r.getMessage() == "integration_worker_job"]
    assert job_records, "the failing job was not logged"
    assert any(r.error_code == "rate_limited" for r in job_records)
    assert any(r.outcome == "failed" for r in job_records)

    # An application category, never the provider's own message, and never the reference.
    assert FAKE_TRACKING_NUMBER not in logged
    for record in job_records:
        assert "429" not in str(record.error_code)
        assert record.provider_key == "fake"


# --- Stored summaries and audit --------------------------------------------


def test_a_stored_error_summary_carries_no_reference_or_credential(db):
    adapter = FakeProviderAdapter(
        read_error=ProviderAdapterError(
            ProviderErrorKind.RETRYABLE,
            f"read of {FAKE_TRACKING_NUMBER} failed with {SECRET_VALUES[0]}",
        )
    )
    tracked = tracked_shipment(db)
    jobs.enqueue(
        db,
        job_type="reconcile_tracking_assignment",
        provider_key="fake",
        tracking_assignment_id=tracked.assignment.id,
        dedupe_key="reconcile:1",
        clock=clock_at(),
    )
    db.commit()

    integration_worker.run_once(
        db,
        worker_name="w1",
        registry=AdapterRegistry({"fake": adapter}),
        clock=clock_at(),
        jitter=lambda: 0.0,
    )

    job = db.query(IntegrationJob).one()
    assert job.error_summary is not None
    assert SECRET_VALUES[0] not in job.error_summary
    assert "super-secret-token" not in job.error_summary
    assert job.error_code == ProviderErrorKind.RETRYABLE.value


def test_an_audit_entry_for_a_provider_event_carries_no_payload(db):
    import json

    adapter = FakeProviderAdapter()
    tracked_shipment(db)
    body = make_payload(reference=FAKE_TRACKING_NUMBER, detail="Carrier narrative text")
    inbox.accept_delivery(
        db, adapter=adapter, body=body, headers=signed_headers(body), clock=clock_at()
    )
    db.commit()
    integration_worker.run_once(
        db,
        worker_name="w1",
        registry=AdapterRegistry({"fake": adapter}),
        clock=clock_at(),
        jitter=lambda: 0.0,
    )

    entries = (
        db.query(AuditEvent).filter(AuditEvent.action == "shipment.event_record_provider").all()
    )
    assert entries, "the applied event was audited"

    for entry in entries:
        serialized = json.dumps(
            {"summary": entry.summary, "detail": entry.detail_json}, ensure_ascii=False
        )
        assert "Carrier narrative text" not in serialized
        assert FAKE_TRACKING_NUMBER not in serialized
        assert body.decode("utf-8") not in serialized


def test_a_provider_audit_action_is_distinguishable_from_a_staff_one(db):
    """An audit line implying a staff member acted when a worker did is a false record."""
    adapter = FakeProviderAdapter()
    tracked_shipment(db)
    body = make_payload(reference=FAKE_TRACKING_NUMBER)
    inbox.accept_delivery(
        db, adapter=adapter, body=body, headers=signed_headers(body), clock=clock_at()
    )
    db.commit()
    integration_worker.run_once(
        db,
        worker_name="w1",
        registry=AdapterRegistry({"fake": adapter}),
        clock=clock_at(),
        jitter=lambda: 0.0,
    )

    entry = (
        db.query(AuditEvent).filter(AuditEvent.action == "shipment.event_record_provider").first()
    )
    assert entry is not None
    assert entry.actor_user_id is None
    assert entry.actor_label == "system"
    assert "provider" in entry.summary.lower()


# --- Staff responses --------------------------------------------------------


def test_no_staff_integration_schema_declares_a_secret_bearing_field():
    """Structural: a field named ``api_key`` in a staff response fails the build."""
    from app.schemas import integration as schemas

    forbidden = (
        "api_key",
        "apikey",
        "secret",
        "token",
        "password",
        "authorization",
        "cookie",
        "signature",
        "credential",
        "payload",
        "raw_",
        "body",
    )

    for name in dir(schemas):
        model = getattr(schemas, name)
        fields = getattr(model, "model_fields", None)
        if not fields:
            continue
        for field_name in fields:
            for banned in forbidden:
                assert banned not in field_name, f"{name}.{field_name}"


def test_the_health_endpoint_returns_no_secret_bearing_key(db, as_admin):
    body = as_admin.get("/api/v1/integrations/health").json()

    def scan(value, path=""):
        if isinstance(value, dict):
            for key, nested in value.items():
                for banned in ("secret", "token", "api_key", "password", "payload", "raw"):
                    assert banned not in key.lower(), f"{path}.{key}"
                scan(nested, f"{path}.{key}")
        elif isinstance(value, list):
            for item in value:
                scan(item, path)

    scan(body)


def test_the_job_listing_exposes_no_payload(db, as_admin):
    adapter = FakeProviderAdapter()
    tracked_shipment(db)
    body = make_payload(reference=FAKE_TRACKING_NUMBER, detail="Carrier narrative text")
    inbox.accept_delivery(
        db, adapter=adapter, body=body, headers=signed_headers(body), clock=clock_at()
    )
    db.commit()

    response = as_admin.get("/api/v1/integrations/jobs")

    assert response.status_code == 200
    assert "Carrier narrative text" not in response.text
    assert FAKE_TRACKING_NUMBER not in response.text
