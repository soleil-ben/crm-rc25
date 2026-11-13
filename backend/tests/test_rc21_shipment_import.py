"""RC-UAT-21 Phase A: shipment CSV import (DEC-0230).

Dry run writes nothing; commit needs a matching dry run (digest + operator); per-row
validation; same limits as the customer import; duplicates refused; nothing but shipments
is created (no quote, invoice, event or notification); permissions; audit.
Synthetic fixtures only (tests/fixtures/rc21_shipments_*.csv).
"""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest
from sqlalchemy import func, select

from app.core.enums import Role
from app.models import (
    AuditEvent,
    CustomerInvoice,
    ImportBatch,
    ImportBatchRow,
    NotificationOutbox,
    QuoteVersion,
    Shipment,
    ShipmentEvent,
    ShipmentImportLink,
    ShipmentItem,
    ShipmentPackage,
)
from app.services import csv_safety, shipment_import_service
from tests.conftest import make_customer, see_committed_changes

FIXTURES = Path(__file__).parent / "fixtures"
VALID = (FIXTURES / "rc21_shipments_valid.csv").read_bytes()
INVALID = (FIXTURES / "rc21_shipments_invalid.csv").read_bytes()

DRY_RUN = "/api/v1/imports/shipments/dry-run"
COMMIT = "/api/v1/imports/shipments/commit"


@pytest.fixture
def customers(db):
    first = make_customer(db, full_name="Nguyễn Văn Thử", email="thu1@example.com")
    second = make_customer(db, full_name="Công ty Thử", email="thu2@example.com")
    third = make_customer(
        db,
        full_name="Phạm Văn Thử",
        email="thu3@example.com",
        source_system="csv_import",
        source_record_id="LEGACY-CUST-7",
    )
    assert (first.public_id, second.public_id) == ("STCA-000001", "STCA-000002")
    return first, second, third


def upload(content: bytes, name: str = "shipments.csv") -> dict:
    return {"file": (name, io.BytesIO(content), "text/csv")}


def dry_run(api, content: bytes):
    return api.post(DRY_RUN, files=upload(content))


def commit(api, content: bytes, digest: str, confirm: str = "true"):
    return api.post(
        COMMIT, files=upload(content), data={"content_sha256": digest, "confirm": confirm}
    )


def counts(db) -> dict[str, int]:
    see_committed_changes(db)
    return {
        model.__tablename__: int(db.scalar(select(func.count()).select_from(model)) or 0)
        for model in (Shipment, ShipmentPackage, ShipmentItem, ImportBatch, ShipmentImportLink)
    }


# --- Template and format ------------------------------------------------------------


def test_template_is_synthetic_and_every_header_is_known(as_admin):
    response = as_admin.get("/api/v1/imports/shipments/template.csv")
    assert response.status_code == 200
    body = response.content
    assert b"example.com" in body
    parsed = csv_safety.parse(
        body, known_fields=shipment_import_service.KNOWN_HEADERS, required_headers=()
    )
    assert parsed.unmapped_headers == []
    assert len(parsed.rows) == 2
    assert all(
        len(row.values) == len(shipment_import_service.TEMPLATE_HEADERS) for row in parsed.rows
    )


def test_fields_publish_the_limits_of_the_customer_import(as_admin):
    data = as_admin.get("/api/v1/imports/shipments/fields").json()
    assert data["limits"]["max_file_bytes"] == 2 * 1024 * 1024
    assert data["limits"]["max_rows"] == 5000
    required = {item["field"] for item in data["fields"] if item["required"]}
    assert set(shipment_import_service.REQUIRED_FIELDS) == required


# --- Dry run --------------------------------------------------------------------------


def test_dry_run_writes_nothing_and_reports_every_row(as_admin, db, customers):
    before = counts(db)
    response = dry_run(as_admin, VALID)
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["counts"] == {"ready": 3, "duplicate": 0, "rejected": 0}
    assert [row["classification"] for row in data["rows"]] == ["ready"] * 3
    assert data["rows"][2]["customer_public_id"] == customers[2].public_id
    assert data["rows"][0]["summary"]["package_count"] == 2
    assert data["rows"][0]["summary"]["transport_mode"] == "air"
    assert counts(db) == before
    # The only row written is the dry run's own audit entry: counts and digest, no values.
    event = db.scalar(select(AuditEvent).where(AuditEvent.action == "shipments.import_dry_run"))
    assert event is not None
    assert "Trần Thị Thử" not in (event.detail_json or "")
    assert json.loads(event.detail_json)["content_sha256"] == data["content_sha256"]


def test_validation_errors_are_reported_per_row(as_admin, customers):
    data = dry_run(as_admin, INVALID).json()
    by_ref = {row["row_number"]: row for row in data["rows"]}
    codes = {number: {issue["code"] for issue in row["issues"]} for number, row in by_ref.items()}
    assert "unknown_customer" in codes[2]
    assert "air_only" in codes[3]
    assert "invalid_number" in codes[4]
    assert "invalid_route" in codes[5]
    assert "missing_value" in codes[6]
    assert "formula_like_value" in codes[7]
    assert "unknown_unit" in codes[8]
    assert by_ref[9]["classification"] == "ready"
    assert by_ref[10]["classification"] == "duplicate"
    assert "duplicate_within_file" in codes[10]
    assert data["counts"] == {"ready": 1, "duplicate": 1, "rejected": 7}


# --- Commit gating ---------------------------------------------------------------------


def test_commit_without_a_dry_run_is_refused_and_writes_nothing(as_admin, db, customers):
    digest = shipment_import_service.common.content_digest(VALID)
    response = commit(as_admin, VALID, digest)
    assert response.status_code == 409
    assert "dry run" in response.json()["message"].lower()
    assert counts(db)["shipments"] == 0


def test_commit_of_a_changed_file_is_refused(as_admin, db, customers):
    digest = dry_run(as_admin, VALID).json()["content_sha256"]
    changed = VALID.replace(b"TEST-SHP-0003", b"TEST-SHP-0099")
    assert commit(as_admin, changed, digest).status_code == 409
    # The changed file's own digest has no dry run behind it either.
    other = shipment_import_service.common.content_digest(changed)
    assert commit(as_admin, changed, other).status_code == 409
    assert counts(db)["shipments"] == 0


def test_commit_needs_explicit_confirmation(as_admin, db, customers):
    digest = dry_run(as_admin, VALID).json()["content_sha256"]
    assert commit(as_admin, VALID, digest, confirm="false").status_code == 422
    assert counts(db)["shipments"] == 0


# --- Commit -----------------------------------------------------------------------------


def test_commit_creates_air_shipments_traceable_to_the_batch(as_admin, db, customers):
    digest = dry_run(as_admin, VALID).json()["content_sha256"]
    response = commit(as_admin, VALID, digest)
    assert response.status_code == 200, response.text
    result = response.json()
    assert (result["created"], result["skipped"], result["rejected"]) == (3, 0, 0)
    see_committed_changes(db)

    batch = db.scalar(select(ImportBatch).where(ImportBatch.public_id == result["batch_public_id"]))
    assert batch.kind == "shipments" and batch.created_count == 3
    links = db.scalars(
        select(ShipmentImportLink).where(ShipmentImportLink.batch_id == batch.id)
    ).all()
    assert {link.external_reference for link in links} == {
        "TEST-SHP-0001",
        "TEST-SHP-0002",
        "TEST-SHP-0003",
    }
    shipments = {link.external_reference: db.get(Shipment, link.shipment_id) for link in links}
    for reference, shipment in shipments.items():
        assert shipment.transport_mode == "air"
        assert shipment.route_group == "VCA" and shipment.direction == "vn_to_ca"
        assert shipment.source_system == "csv_shipment_import"
        assert shipment.source_record_id == reference

    draft = shipments["TEST-SHP-0001"]
    assert draft.booking_state == "draft" and draft.public_id is None
    assert draft.sender_country_code == "VN"
    assert draft.recipient_name == "Trần Thị Thử"
    packages = db.scalars(
        select(ShipmentPackage).where(ShipmentPackage.shipment_id == draft.id)
    ).all()
    assert sorted(float(p.weight_kg) for p in packages) == [8.0, 12.5]
    items = db.scalars(select(ShipmentItem).where(ShipmentItem.shipment_id == draft.id)).all()
    assert {item.description for item in items} == {"Áo dài", "Cà phê"}

    confirmed = shipments["TEST-SHP-0002"]
    assert confirmed.booking_state == "confirmed"
    assert confirmed.public_id.startswith("SX-VCA-")
    assert confirmed.booking_date.date().isoformat() == "2026-10-01"
    assert confirmed.sender_name == "Công ty Thử"

    assert shipments["TEST-SHP-0003"].customer_id == customers[2].id

    # An import creates no quote, invoice, event or notification.
    for model in (QuoteVersion, CustomerInvoice, ShipmentEvent, NotificationOutbox):
        assert db.scalar(select(func.count()).select_from(model)) == 0

    audit = db.scalar(select(AuditEvent).where(AuditEvent.action == "shipment.import_commit"))
    assert audit.entity_id == batch.public_id
    assert "Trần Thị Thử" not in (audit.detail_json or "")
    rows = db.scalars(select(ImportBatchRow).where(ImportBatchRow.batch_id == batch.id)).all()
    assert {row.outcome for row in rows} == {"created"}


def test_a_second_import_of_the_same_references_is_refused(as_admin, db, customers):
    digest = dry_run(as_admin, VALID).json()["content_sha256"]
    assert commit(as_admin, VALID, digest).json()["created"] == 3

    again = dry_run(as_admin, VALID).json()
    assert again["counts"]["duplicate"] == 3
    assert {issue["code"] for row in again["rows"] for issue in row["issues"]} == {
        "already_imported"
    }
    result = commit(as_admin, VALID, again["content_sha256"]).json()
    assert (result["created"], result["skipped"]) == (0, 3)
    assert {row["reason_code"] for row in result["rows"]} == {"duplicate_external_reference"}
    assert counts(db)["shipments"] == 3


def test_a_mixed_file_imports_only_its_valid_rows_once(as_admin, db, customers):
    digest = dry_run(as_admin, INVALID).json()["content_sha256"]
    result = commit(as_admin, INVALID, digest).json()
    assert (result["created"], result["skipped"], result["rejected"]) == (1, 1, 7)
    assert counts(db)["shipments"] == 1


def test_batch_history_filters_by_kind(as_admin, customers):
    digest = dry_run(as_admin, VALID).json()["content_sha256"]
    commit(as_admin, VALID, digest)
    shipments = as_admin.get("/api/v1/imports/batches", params={"kind": "shipments"}).json()
    assert shipments["total"] == 1 and shipments["items"][0]["kind"] == "shipments"
    assert (
        as_admin.get("/api/v1/imports/batches", params={"kind": "customers"}).json()["total"] == 0
    )


# --- Limits ---------------------------------------------------------------------------------


def test_the_customer_import_limits_apply(as_admin, customers):
    header = VALID.split(b"\n", 1)[0] + b"\n"
    row = VALID.split(b"\n")[1] + b"\n"
    too_many = header + row * (csv_safety.MAX_ROWS + 1)
    assert dry_run(as_admin, too_many).status_code == 422
    too_big = header + b"x" * (csv_safety.MAX_FILE_BYTES + 10)
    assert dry_run(as_admin, too_big).status_code == 422
    assert dry_run(as_admin, b"PK\x03\x04not a csv").status_code == 422
    missing = b"external_reference,customer_ref\nA,STCA-000001\n"
    assert dry_run(as_admin, missing).status_code == 422


# --- Permissions ------------------------------------------------------------------------------


@pytest.mark.parametrize("role", [Role.OPERATIONS, Role.MARKETING, Role.READ_ONLY_MANAGER])
def test_roles_without_the_import_permissions_are_refused(api_for, db, customers, role):
    api = api_for(role.value)
    assert dry_run(api, VALID).status_code == 403
    assert commit(api, VALID, "0" * 64).status_code == 403
    assert api.get("/api/v1/imports/shipments/template.csv").status_code == 403
    assert counts(db)["shipments"] == 0


def test_an_unauthenticated_caller_is_refused(client):
    assert client.post(DRY_RUN, files=upload(VALID)).status_code == 401
    assert client.get("/api/v1/imports/shipments/fields").status_code == 401


# --- Review fixes (M3, M5, L7, L8, L9, i18n codes) ---------------------------------------------


def test_a_source_id_shared_by_two_customers_is_ambiguous(as_admin, db, customers):
    make_customer(
        db,
        full_name="Đỗ Thị Trùng",
        email="trung@example.com",
        source_system="other_system",
        source_record_id="LEGACY-CUST-7",
    )
    data = dry_run(as_admin, VALID).json()
    row = next(item for item in data["rows"] if item["reference"] == "TEST-SHP-0003")
    assert row["classification"] == "rejected"
    assert {issue["code"] for issue in row["issues"]} == {"ambiguous_customer"}
    # The Solaris customer ID still resolves exactly.
    assert data["rows"][0]["classification"] == "ready"


def test_a_dry_run_is_consumed_by_its_commit(as_admin, db, customers):
    digest = dry_run(as_admin, VALID).json()["content_sha256"]
    assert commit(as_admin, VALID, digest).status_code == 200
    second = commit(as_admin, VALID, digest)
    assert second.status_code == 409
    assert "dry run" in second.json()["message"].lower()
    see_committed_changes(db)
    assert db.scalar(select(func.count()).select_from(ImportBatch)) == 1
    # A new dry run allows one more commit.
    again = dry_run(as_admin, VALID).json()["content_sha256"]
    assert commit(as_admin, VALID, again).status_code == 200


def test_a_database_lock_aborts_the_whole_commit(as_admin, db, customers, monkeypatch):
    from sqlalchemy.exc import OperationalError

    from app.services import booking_service

    def locked(*_args, **_kwargs):
        raise OperationalError("UPDATE shipments", {}, Exception("database is locked"))

    digest = dry_run(as_admin, VALID).json()["content_sha256"]
    # Row 2 (a draft) is created first; row 3 (confirmed) then hits the lock.
    monkeypatch.setattr(booking_service, "_confirm_once", locked)
    response = commit(as_admin, VALID, digest)
    assert response.status_code == 409, response.text
    assert response.json()["detail"]["reason"] == "database_busy"
    after = counts(db)
    assert after["shipments"] == 0 and after["import_batches"] == 0
    assert after["shipment_import_links"] == 0
    # The dry run was not consumed by the failed commit.
    monkeypatch.undo()
    assert commit(as_admin, VALID, digest).json()["created"] == 3


def test_a_concurrent_duplicate_is_a_refused_row_not_an_error(as_admin, db, customers, monkeypatch):
    first = dry_run(as_admin, VALID).json()["content_sha256"]
    assert commit(as_admin, VALID, first).json()["created"] == 3
    digest = dry_run(as_admin, VALID).json()["content_sha256"]
    # Simulate the race: the pre-check sees nothing, the unique constraint catches it.
    monkeypatch.setattr(shipment_import_service, "_already_imported", lambda *_a: None)
    response = commit(as_admin, VALID, digest)
    assert response.status_code == 200, response.text
    result = response.json()
    assert (result["created"], result["skipped"]) == (0, 3)
    assert {row["reason_code"] for row in result["rows"]} == {"duplicate_external_reference"}
    assert counts(db)["shipments"] == 3


def test_only_iso_dates_are_accepted(as_admin, customers):
    slashed = VALID.replace(b",2026-10-01,", b",01/10/2026,")
    data = dry_run(as_admin, slashed).json()
    row = next(item for item in data["rows"] if item["reference"] == "TEST-SHP-0002")
    assert row["classification"] == "rejected"
    assert {issue["code"] for issue in row["issues"]} == {"invalid_date"}


def test_dry_run_notes_carry_stable_codes(as_admin, customers):
    data = dry_run(as_admin, VALID).json()
    assert data["note_codes"][0] == "dry_run_only_shipments"
    assert len(data["note_codes"]) == len(data["notes"])
