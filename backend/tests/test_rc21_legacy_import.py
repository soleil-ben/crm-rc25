"""RC-UAT-21 Phase A: legacy history baseline import (DEC-0230).

Read-only historical shipments with dated milestones: dry run writes nothing; commit needs a
matching dry run (digest, options, operator); per-row validation; idempotent re-run; soft
void of a whole baseline (audited); never notifies; absent from operational and finance
lists; staff-only reads. Synthetic fixtures only (tests/fixtures/rc21_legacy_*.csv).
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from sqlalchemy import func, select

from app.core.enums import Role
from app.models import (
    AuditEvent,
    ImportBatch,
    LegacyBaseline,
    LegacyShipment,
    LegacyShipmentEvent,
    NotificationOutbox,
    Shipment,
    ShipmentEvent,
)
from app.services import bulk_import_common
from tests.conftest import make_customer, see_committed_changes

FIXTURES = Path(__file__).parent / "fixtures"
HISTORY = (FIXTURES / "rc21_legacy_history.csv").read_bytes()
INVALID = (FIXTURES / "rc21_legacy_invalid.csv").read_bytes()

DRY_RUN = "/api/v1/imports/legacy-history/dry-run"
COMMIT = "/api/v1/imports/legacy-history/commit"
BASELINES = "/api/v1/imports/legacy-history/baselines"
RECORDS = "/api/v1/legacy-shipments"


@pytest.fixture
def customers(db):
    first = make_customer(db, full_name="Trần Văn Cũ", email="cu1@example.com")
    second = make_customer(db, full_name="Lê Thị Cũ", email="cu2@example.com")
    assert (first.public_id, second.public_id) == ("STCA-000001", "STCA-000002")
    return first, second


def upload(content: bytes) -> dict:
    return {"file": ("history.csv", io.BytesIO(content), "text/csv")}


def dry_run(api, content: bytes, cutoff: str | None = None):
    data = {"cutoff_date": cutoff} if cutoff else {}
    return api.post(DRY_RUN, files=upload(content), data=data)


def commit(api, content: bytes, digest: str, cutoff: str | None = None, confirm: str = "true"):
    data = {"content_sha256": digest, "confirm": confirm}
    if cutoff:
        data["cutoff_date"] = cutoff
    return api.post(COMMIT, files=upload(content), data=data)


def run_baseline(api, content: bytes = HISTORY, cutoff: str | None = None) -> dict:
    digest = dry_run(api, content, cutoff).json()["content_sha256"]
    response = commit(api, content, digest, cutoff)
    assert response.status_code == 200, response.text
    return response.json()


def count(db, model) -> int:
    see_committed_changes(db)
    return int(db.scalar(select(func.count()).select_from(model)) or 0)


def test_dry_run_writes_nothing(as_admin, db, customers):
    response = dry_run(as_admin, HISTORY)
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["counts"] == {"ready": 3, "already_imported": 0, "duplicate": 0, "rejected": 0}
    assert data["rows"][0]["summary"]["milestone_count"] == 7
    for model in (LegacyShipment, LegacyBaseline, ImportBatch, LegacyShipmentEvent):
        assert count(db, model) == 0


def test_commit_without_a_matching_dry_run_is_refused(as_admin, db, customers):
    digest = bulk_import_common.content_digest(HISTORY)
    assert commit(as_admin, HISTORY, digest).status_code == 409
    # A dry run with one cutoff does not authorize a commit with another.
    dry_run(as_admin, HISTORY, cutoff="2024-12-31")
    assert commit(as_admin, HISTORY, digest, cutoff="2025-06-30").status_code == 409
    assert (
        commit(as_admin, HISTORY, digest, cutoff="2024-12-31", confirm="false").status_code == 422
    )
    assert count(db, LegacyShipment) == 0


def test_commit_creates_read_only_records_with_their_milestones(as_admin, db, customers):
    result = run_baseline(as_admin)
    assert (result["created"], result["matched"], result["rejected"]) == (3, 0, 0)
    see_committed_changes(db)
    delivered = db.scalar(
        select(LegacyShipment).where(LegacyShipment.legacy_reference == "TEST-OLD-0001")
    )
    assert delivered.final_status == "delivered"
    assert delivered.completed_on.isoformat() == "2024-03-12"
    assert delivered.transport_mode == "air" and delivered.route_group == "VCA"
    assert [event.event_type for event in delivered.events] == [
        "booked",
        "received_at_solaris",
        "departed_origin",
        "customs_processing",
        "arrived_destination",
        "out_for_delivery",
        "delivered_to_recipient",
    ]
    cancelled = db.scalar(
        select(LegacyShipment).where(LegacyShipment.legacy_reference == "TEST-OLD-0002")
    )
    assert [event.event_type for event in cancelled.events] == ["booked", "cancelled"]

    batch = db.scalar(select(ImportBatch).where(ImportBatch.public_id == result["batch_public_id"]))
    assert batch.kind == "legacy_history"
    audit = db.scalar(select(AuditEvent).where(AuditEvent.action == "legacy_history.import_commit"))
    assert audit.entity_id == batch.public_id
    assert "Trần Thị Cũ" not in (audit.detail_json or "")


def test_legacy_events_never_notify_and_never_become_operational(as_admin, db, customers):
    run_baseline(as_admin)
    assert count(db, NotificationOutbox) == 0
    assert count(db, ShipmentEvent) == 0
    assert count(db, Shipment) == 0
    # Not in the operational shipment list, nor in the customer's shipment list.
    assert as_admin.get("/api/v1/shipments").json()["total"] == 0
    assert (
        as_admin.get("/api/v1/shipments", params={"customer_id": customers[0].id}).json()["total"]
        == 0
    )
    # Not in any finance report or list.
    for path in (
        "/api/v1/finance/accepted-not-invoiced",
        "/api/v1/finance/profitability?month=2024-03",
        "/api/v1/finance/ar-aging",
        "/api/v1/invoices",
    ):
        response = as_admin.get(path)
        assert response.status_code == 200, (path, response.text)
        assert "TEST-OLD-0001" not in response.text
    # Staff see it in the legacy list, flagged as legacy.
    listed = as_admin.get(RECORDS, params={"customer_id": customers[0].id}).json()
    assert listed["total"] == 2
    assert all(item["is_legacy"] for item in listed["items"])
    detail = as_admin.get(f"{RECORDS}/{listed['items'][0]['id']}").json()
    assert detail["events"]


def test_a_baseline_re_run_is_idempotent(as_admin, db, customers):
    run_baseline(as_admin)
    again = dry_run(as_admin, HISTORY).json()
    assert again["counts"]["already_imported"] == 3
    result = commit(as_admin, HISTORY, again["content_sha256"]).json()
    assert (result["created"], result["matched"]) == (0, 3)
    assert {row["reason_code"] for row in result["rows"]} == {"already_in_baseline"}
    assert count(db, LegacyShipment) == 3


def test_a_baseline_is_voided_as_a_whole_and_can_then_be_reimported(as_admin, db, customers):
    batch_id = run_baseline(as_admin)["batch_public_id"]
    path = f"{BASELINES}/{batch_id}/void"
    assert (
        as_admin.post(path, json={"reason": "Wrong source file", "confirm": False}).status_code
        == 422
    )
    assert as_admin.post(path, json={"reason": "x", "confirm": True}).status_code == 422
    response = as_admin.post(path, json={"reason": "Wrong source file", "confirm": True})
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "voided"
    assert (
        as_admin.post(path, json={"reason": "Wrong source file", "confirm": True}).status_code
        == 409
    )

    assert as_admin.get(RECORDS).json()["total"] == 0
    voided = as_admin.get(RECORDS, params={"include_voided": True}).json()
    assert voided["total"] == 3 and all(item["is_voided"] for item in voided["items"])
    see_committed_changes(db)
    audit = db.scalar(select(AuditEvent).where(AuditEvent.action == "legacy_history.baseline_void"))
    assert audit.entity_id == batch_id

    # Soft void: nothing deleted, and the same history can be imported again.
    assert run_baseline(as_admin)["created"] == 3
    assert count(db, LegacyShipment) == 6
    statuses = {item["status"] for item in as_admin.get(BASELINES).json()}
    assert statuses == {"active", "voided"}


def test_validation_errors_are_reported_per_row(as_admin, customers):
    data = dry_run(as_admin, INVALID).json()
    codes = {row["row_number"]: {issue["code"] for issue in row["issues"]} for row in data["rows"]}
    assert "out_of_order" in codes[2]
    assert "missing_value" in codes[3]
    assert "future_date" in codes[4]
    assert "air_only" in codes[5]
    assert "invalid_date" in codes[6]
    assert data["counts"]["rejected"] == 5


def test_rows_after_the_cutoff_are_rejected(as_admin, customers):
    data = dry_run(as_admin, HISTORY, cutoff="2024-01-31").json()
    rejected = [row for row in data["rows"] if row["classification"] == "rejected"]
    assert {issue["code"] for row in rejected for issue in row["issues"]} == {"after_cutoff"}
    assert len(rejected) == 2
    assert dry_run(as_admin, HISTORY, cutoff="2999-01-01").status_code == 422


@pytest.mark.parametrize("role", [Role.OPERATIONS, Role.MARKETING, Role.READ_ONLY_MANAGER])
def test_staff_read_legacy_records_but_only_admin_imports_or_voids(
    as_admin, api_for, db, customers, role
):
    batch_id = run_baseline(as_admin)["batch_public_id"]
    api = api_for(role.value)
    assert api.get(RECORDS).status_code == 200
    assert dry_run(api, HISTORY).status_code == 403
    assert commit(api, HISTORY, "0" * 64).status_code == 403
    void = api.post(f"{BASELINES}/{batch_id}/void", json={"reason": "Not allowed", "confirm": True})
    assert void.status_code == 403
    assert count(db, LegacyShipment) == 3


def test_an_unauthenticated_caller_is_refused(client):
    assert client.get(RECORDS).status_code == 401
    assert client.post(DRY_RUN, files=upload(HISTORY)).status_code == 401


# --- Review fixes (M4, L8, L11) -------------------------------------------------------------


def test_a_merge_moves_legacy_history_to_the_surviving_customer(as_admin, db, users, customers):
    from app.services import customer_service

    run_baseline(as_admin)
    see_committed_changes(db)
    source, target = customers
    customer_service.merge_customers(
        db, source=source, target=target, actor=users[Role.ADMIN.value]
    )
    db.commit()
    owners = {
        record.legacy_reference: record.customer_id
        for record in db.scalars(select(LegacyShipment)).all()
    }
    assert set(owners.values()) == {target.id}
    audit = db.scalar(select(AuditEvent).where(AuditEvent.action == "customer.merge"))
    assert '"legacy_shipments": 2' in audit.detail_json
    listed = as_admin.get(RECORDS, params={"customer_id": target.id}).json()
    assert listed["total"] == 3


def test_search_treats_percent_and_underscore_literally(as_admin, customers):
    run_baseline(as_admin)
    assert as_admin.get(RECORDS, params={"search": "%"}).json()["total"] == 0
    assert as_admin.get(RECORDS, params={"search": "_"}).json()["total"] == 0
    assert as_admin.get(RECORDS, params={"search": "OLD-0001"}).json()["total"] == 1
    assert as_admin.get(RECORDS, params={"search": "TEST-OLD"}).json()["total"] == 3


def test_a_slash_date_is_refused_not_guessed(as_admin, customers):
    slashed = HISTORY.replace(b",2024-03-01,", b",01/03/2024,")
    data = dry_run(as_admin, slashed).json()
    row = next(item for item in data["rows"] if item["reference"] == "TEST-OLD-0001")
    assert row["classification"] == "rejected"
    assert "invalid_date" in {issue["code"] for issue in row["issues"]}
