"""Phase 4A changed nothing a customer can see.

The public tracking surface is the one place where a half-built integration could do real
damage: a ``connected_api`` state, a ``last_successful_sync`` field, or a line saying the
page refreshes itself would each be a promise nothing can keep. So this file asserts the
**absence** of the work, alongside the presence of the parts that already worked.

The requirement is explicit. During Phase 4A the public response must not gain
``connected_api``, ``last_carrier_update``, ``last_successful_sync``, automatic-refresh
language, or provider events shown as real. This is that requirement written down where it
fails the build.
"""

from __future__ import annotations

from datetime import datetime

from app.core.enums import EventSource, OperationalState
from app.core.security import rate_limiter
from app.integrations.registry import AdapterRegistry
from app.schemas.public_tracking import PublicTrackingResult, TrackingState
from app.services import integration_inbox_service as inbox
from app.workers import integration_worker
from tests.conftest import booked_shipment, make_customer
from tests.fakes.fake_provider_adapter import (
    FakeProviderAdapter,
    make_payload,
    signed_headers,
)
from tests.integration_fixtures import FAKE_TRACKING_NUMBER, tracked_shipment

TRACK = "/api/v1/public/track"
BASE_TIME = datetime(2026, 9, 1, 9, 0, 0)

#: Field names that must not exist on the public response until a provider is verified.
#: Reserved rather than added as nulls, because a null field is an invitation to populate
#: it with something approximate.
RESERVED_FOR_LATER = (
    "last_carrier_update",
    "last_carrier_update_at",
    "last_successful_sync",
    "last_successful_sync_at",
    "last_synced_at",
    "sync_status",
    "freshness",
    "freshness_age_seconds",
    "next_refresh_at",
    "provider",
    "provider_key",
    "provider_status",
    "raw_status",
    "carrier_status",
)


def clock_at(moment: datetime = BASE_TIME):
    return lambda: moment


def apply_provider_event(db, *, status: str = "FAKE_MOVING"):
    """Put a real, applied provider event on a shipment, then return it."""
    adapter = FakeProviderAdapter()
    tracked = tracked_shipment(db)
    body = make_payload(
        reference=FAKE_TRACKING_NUMBER, status=status, occurred_at="2026-09-01T08:00:00+00:00"
    )
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
    db.commit()
    return tracked


# --- The response shape -----------------------------------------------------


def test_the_public_vocabulary_still_excludes_connected_api():
    """``connected_api`` stays absent from the vocabulary rather than present and unused,
    so it cannot be selected by accident before a provider is verified."""
    values = {state.value for state in TrackingState}

    assert "connected_api" not in values
    assert values == {
        "manual_updates",
        "external_link_only",
        "no_public_milestones",
        "tracking_unavailable",
        "demo",
        "cancelled",
    }


def test_the_public_result_model_gained_no_field():
    """The allowlist is exactly what Phase 3 published, plus what the register records.

    Registered in `SUPERSEDED_ASSERTIONS.md` (AS-33): ``carrier_links`` added by RC-UAT-19
    (2026-10-22).
    """
    assert set(PublicTrackingResult.model_fields) == {
        "shipment_reference",
        "matched_reference_type",
        "selected_package_reference",
        "route_group",
        "route_label",
        "origin",
        "destination",
        "status",
        "status_label",
        "package_count_active",
        "package_count_cancelled",
        "package_count_delivered",
        "progress_summary",
        "packages",
        "estimated_delivery_at",
        "delivered_at",
        "cancelled_at",
        "timeline",
        "tracking_state",
        "last_public_update_at",
        "carrier_link",
        "carrier_links",  # one per generic tracking name (2026-10-22)
        "data_mode",
        "help_url",
        "timezone",
    }


def test_no_reserved_freshness_field_exists_on_any_public_model():
    """Not even as a null. A null field invites something approximate."""
    from app.schemas import public_tracking

    for name in dir(public_tracking):
        model = getattr(public_tracking, name)
        fields = getattr(model, "model_fields", None)
        if not fields:
            continue
        for reserved in RESERVED_FOR_LATER:
            assert reserved not in fields, f"{name}.{reserved}"


# --- A shipment with a real provider event ----------------------------------


def test_a_provider_event_moves_the_internal_status_and_nothing_public(client, db):
    """The seam Phase 2 built, still doing its job -- and stopping where it should.

    A provider event drives the derived **internal** status; that is the point of deriving
    status from events. It carries no approved public wording, so it never appears as a
    customer-facing milestone -- and, since the 2026-10-14 fix pack, it does not move the
    public status either: the public page reflects published events only (UAT-XX-02).
    """
    rate_limiter.reset()
    tracked = apply_provider_event(db, status="FAKE_MOVING")

    body = client.get(f"{TRACK}/{tracked.shipment.public_id}").json()

    db.refresh(tracked.shipment)
    assert tracked.shipment.operational_state == OperationalState.IN_TRANSIT
    assert body["status"] == OperationalState.BOOKED
    assert body["timeline"] == []
    assert body["tracking_state"] == TrackingState.NO_PUBLIC_MILESTONES
    assert body["last_public_update_at"] is None


def test_no_raw_provider_status_reaches_a_customer(client, db):
    """``raw_status`` is preserved for audit and never published."""
    rate_limiter.reset()
    tracked = apply_provider_event(db, status="FAKE_MOVING")

    text = client.get(f"{TRACK}/{tracked.shipment.public_id}").text

    assert "FAKE_MOVING" not in text
    assert "fake" not in text.lower()
    assert "mapping" not in text.lower()


def test_no_provider_narrative_text_reaches_a_customer(client, db):
    rate_limiter.reset()
    adapter = FakeProviderAdapter()
    tracked = tracked_shipment(db)
    body = make_payload(
        reference=FAKE_TRACKING_NUMBER,
        detail="Carrier narrative nobody at Solaris approved",
        occurred_at="2026-09-01T08:00:00+00:00",
    )
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
    db.commit()

    text = client.get(f"{TRACK}/{tracked.shipment.public_id}").text

    assert "Carrier narrative" not in text


def test_a_provider_delivery_is_delivered_internally_and_unpublished_publicly(client, db):
    """The internal outcome is identical whether staff or a provider reported it; the
    public outcome waits, in both cases, for a published milestone."""
    rate_limiter.reset()
    tracked = apply_provider_event(db, status="FAKE_HANDED_TO_RECIPIENT")

    body = client.get(f"{TRACK}/{tracked.shipment.public_id}").json()

    db.refresh(tracked.shipment)
    assert tracked.shipment.operational_state == OperationalState.DELIVERED
    assert tracked.shipment.delivered_at is not None
    assert body["status"] == OperationalState.BOOKED
    assert body["package_count_delivered"] == 0
    assert body["delivered_at"] is None
    # And still nothing claiming a synchronization.
    assert body["tracking_state"] != "connected_api"


def test_a_staff_published_update_still_appears(client, db):
    """The counterpart: what a customer *does* see has not been narrowed."""
    from app.core.enums import ShipmentEventType
    from app.services import event_service

    rate_limiter.reset()
    tracked = apply_provider_event(db, status="FAKE_MOVING")
    event_service.record_event(
        db,
        tracked.shipment,
        {
            "event_type": ShipmentEventType.CUSTOMS_PROCESSING,
            "occurred_at": datetime(2026, 9, 1, 8, 30),
            "is_public_update": True,
            "public_update_text": "Your parcel is clearing customs in Hanoi.",
        },
    )
    db.commit()

    body = client.get(f"{TRACK}/{tracked.shipment.public_id}").json()

    assert len(body["timeline"]) == 1
    assert body["timeline"][0]["message"] == "Your parcel is clearing customs in Hanoi."
    assert body["timeline"][0]["source_label"] == "manual_update"
    assert body["tracking_state"] == TrackingState.MANUAL_UPDATES


# --- No synchronization language --------------------------------------------


def test_no_public_response_claims_anything_is_synchronized(client, db):
    rate_limiter.reset()
    tracked = apply_provider_event(db)

    text = client.get(f"{TRACK}/{tracked.shipment.public_id}").text.lower()

    for claim in (
        "synchroni",
        "last_synced",
        "last_successful_sync",
        "last_carrier_update",
        "auto_refresh",
        "refreshes",
        "connected_api",
        "provider",
        "webhook",
    ):
        assert claim not in text, claim


def test_the_recursive_key_scan_finds_no_reserved_field(client, db):
    """At any depth, including inside a package or a timeline entry."""
    rate_limiter.reset()
    tracked = apply_provider_event(db)

    def keys(value):
        if isinstance(value, dict):
            for key, nested in value.items():
                yield key
                yield from keys(nested)
        elif isinstance(value, list):
            for item in value:
                yield from keys(item)

    found = set(keys(client.get(f"{TRACK}/{tracked.shipment.public_id}").json()))

    for reserved in RESERVED_FOR_LATER:
        assert reserved not in found, reserved


# --- Nothing about the boundary moved ---------------------------------------


def test_the_public_router_still_imports_no_integration_module():
    """A provider concern must not become a public dependency by an import."""
    import ast
    from pathlib import Path

    package = Path(__file__).resolve().parents[1] / "app" / "api" / "public"

    for path in package.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            module = ""
            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
            elif isinstance(node, ast.Import):
                module = ",".join(alias.name for alias in node.names)
            assert "integrations" not in module, f"{path.name}: {module}"
            assert "worker" not in module, f"{path.name}: {module}"


def test_the_public_service_still_imports_no_integration_module():
    import ast
    from pathlib import Path

    path = Path(__file__).resolve().parents[1] / "app" / "services" / "public_tracking_service.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))

    for node in ast.walk(tree):
        module = ""
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
        elif isinstance(node, ast.Import):
            module = ",".join(alias.name for alias in node.names)
        assert "integration" not in module, module


def test_the_public_failure_response_is_unchanged(client, db):
    """The Phase 3 correction is the last word on this; Phase 4A did not touch it."""
    rate_limiter.reset()
    make_customer(db)
    db.commit()

    invalid = client.get(f"{TRACK}/rubbish")
    unknown = client.get(f"{TRACK}/SX-CAV-ABCDEFGHJKLM")
    oversized = client.get(f"{TRACK}/{'A' * 200}")

    for other in (unknown, oversized):
        assert invalid.status_code == other.status_code == 404
        assert invalid.content == other.content
    assert set(invalid.json()) == {"code", "message"}


def test_an_ordinary_manual_lookup_is_unaffected_by_the_new_tables(client, db):
    """Manual milestones, bookings, and public tracking work with no provider at all."""
    from app.core.enums import ShipmentEventType
    from app.services import event_service

    rate_limiter.reset()
    customer = make_customer(db, full_name="Nguyễn Thị Bích Hạnh")
    shipment = booked_shipment(db, customer, packages=2)
    event_service.record_event(
        db,
        shipment,
        {
            "event_type": ShipmentEventType.IN_TRANSIT,
            "occurred_at": datetime(2026, 9, 1, 8, 0),
            "is_public_update": True,
            "public_update_text": "On its way.",
        },
    )
    db.commit()

    body = client.get(f"{TRACK}/{shipment.public_id}").json()

    assert body["shipment_reference"] == shipment.public_id
    assert body["status"] == OperationalState.IN_TRANSIT
    assert body["tracking_state"] == TrackingState.MANUAL_UPDATES
    assert len(body["timeline"]) == 1


def test_every_shipment_event_is_still_attributable_to_its_source(db):
    """``source`` remains the column that tells a staff entry from a provider report."""
    from app.models import ShipmentEvent

    apply_provider_event(db)

    sources = {row.source for row in db.query(ShipmentEvent).all()}

    assert sources <= {EventSource.MANUAL, EventSource.PROVIDER}
    assert EventSource.PROVIDER in sources
