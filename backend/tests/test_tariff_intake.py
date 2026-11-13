"""Vendor rate-email intake, version diff and approval (Phase 13H, OD-76).

Every email here is built in the test from the **sanitized** fixture workbook (or an
in-test modified copy of it), with demo addresses only. Nothing connects to a mailbox or
the network: emails arrive as uploads or as files in a temporary intake folder.
"""

from __future__ import annotations

import io
import json
import sqlite3
from datetime import date
from email.message import EmailMessage
from pathlib import Path

import openpyxl
import pytest
from sqlalchemy import select

from app.core.config import settings
from app.core.enums import Role, TariffIntakeStatus, TariffVersionStatus
from app.models import (
    AuditEvent,
    Base,
    TariffEmailIntake,
    TariffIntakeSettings,
    TariffProduct,
    TariffRateBracket,
    TariffVersion,
)
from app.models.tariff_intake import DEFAULT_APPROVER_EMAILS
from app.services import tariff_import_service as imports
from app.services import tariff_intake_service as svc
from app.services.errors import PermissionDeniedError, ValidationError
from app.workers import tariff_intake_worker
from tests.conftest import see_committed_changes
from tests.test_migrations_phase13c import _alembic, _tables

FIXTURES = Path(__file__).resolve().parent / "fixtures"
WORKBOOK = FIXTURES / "kango_canada_rates_2026-10-12_sanitized.xlsx"
XLSX_TYPE = ("application", "vnd.openxmlformats-officedocument.spreadsheetml.sheet")
VENDOR = "rates@vendor.example.com"
BODY_MARKER = "BODY-TEXT-NEVER-STORED"


@pytest.fixture(scope="module")
def workbook_bytes() -> bytes:
    return WORKBOOK.read_bytes()


@pytest.fixture(autouse=True)
def intake_folder(tmp_path, monkeypatch) -> Path:
    folder = tmp_path / "intake"
    monkeypatch.setattr(settings, "tariff_intake_dir", str(folder))
    return folder


def build_eml(
    attachments: list[tuple[str, bytes]],
    *,
    sender: str = VENDOR,
    subject: str = "Kango Canada rates apply 12 Oct 2026",
    message_id: str | None = "<rates-1@vendor.example.com>",
    sent: str = "Mon, 12 Oct 2026 15:00:00 +0700",
) -> bytes:
    message = EmailMessage()
    message["From"] = f"Vendor Rates <{sender}>"
    message["To"] = "intake@demo.example.com"
    message["Subject"] = subject
    if message_id:
        message["Message-ID"] = message_id
    message["Date"] = sent
    message.set_content(f"Dear Solaris, new rates attached. {BODY_MARKER}")
    message.add_alternative(
        f'<html><body><a href="http://example.invalid/track">{BODY_MARKER}</a></body></html>',
        subtype="html",
    )
    for name, data in attachments:
        maintype, subtype = XLSX_TYPE if name.endswith(".xlsx") else ("application", "octet-stream")
        message.add_attachment(data, maintype=maintype, subtype=subtype, filename=name)
    return message.as_bytes()


def modified_workbook(edit) -> bytes:
    workbook = openpyxl.load_workbook(WORKBOOK)
    edit(workbook)
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def allow_vendor(db, approver: str | None = None) -> None:
    svc.update_settings(
        db,
        allowed_sender_domains=["vendor.example.com"],
        approver_emails=[approver] if approver else None,
        actor=None,
    )
    db.commit()


def ingest(db, raw: bytes, source: str = "upload") -> svc.IntakeResult:
    result = svc.ingest_and_commit(db, raw, source=source, actor=None)
    return result


def eml_file(name: str, raw: bytes) -> dict:
    return {"file": (name, raw, "message/rfc822")}


# --- Intake ---------------------------------------------------------------------------------


def test_a_rate_email_from_an_allowed_sender_becomes_a_draft_and_never_activates(
    db, workbook_bytes
):
    allow_vendor(db)
    result = ingest(db, build_eml([("Kango rates.xlsx", workbook_bytes)]))
    intake = result.intake
    assert result.created and intake.status == TariffIntakeStatus.IMPORTED
    assert intake.sender == VENDOR and intake.source == "upload"
    assert intake.attachment_name == "Kango rates.xlsx"
    assert len(intake.attachment_sha256) == 64
    version = db.get(TariffVersion, intake.tariff_version_id)
    assert version.status == TariffVersionStatus.DRAFT
    assert version.label == "Kango Canada rates apply 12 Oct 2026"
    assert version.effective_from == date(2026, 10, 12)
    assert imports.active_version(db) is None  # nothing activated by itself
    actions = [a.action for a in db.scalars(select(AuditEvent))]
    assert "tariff_intake.received" in actions and "tariff_intake.imported" in actions
    assert "tariff_version.activated" not in actions

    diff = svc.version_diff(db, version)
    assert diff["against_version_id"] is None and diff["mode"] == "air"
    assert diff["summary"]["brackets_changed"] == 0 and diff["summary"]["brackets_removed"] == 0
    assert diff["summary"]["brackets_added"] > 0
    assert len(diff["brackets_added"]) <= svc.MAX_DIFF_ENTRIES


def test_the_effective_date_is_the_email_date_in_toronto(db, workbook_bytes):
    allow_vendor(db)
    # 02:30 UTC on 12 October is 22:30 on 11 October in Toronto.
    raw = build_eml([("r.xlsx", workbook_bytes)], sent="Mon, 12 Oct 2026 02:30:00 +0000")
    version = db.get(TariffVersion, ingest(db, raw).intake.tariff_version_id)
    assert version.effective_from == date(2026, 10, 11)


def test_the_same_email_twice_is_received_once(db, workbook_bytes):
    allow_vendor(db)
    raw = build_eml([("r.xlsx", workbook_bytes)])
    first = ingest(db, raw)
    second = ingest(db, raw)
    assert second.created is False and second.intake.id == first.intake.id
    assert len(db.scalars(select(TariffEmailIntake)).all()) == 1
    assert len(db.scalars(select(TariffVersion)).all()) == 1


def test_the_same_workbook_in_another_email_is_a_duplicate(db, workbook_bytes):
    allow_vendor(db)
    first = ingest(db, build_eml([("r.xlsx", workbook_bytes)]))
    again = ingest(
        db, build_eml([("r.xlsx", workbook_bytes)], message_id="<rates-2@vendor.example.com>")
    )
    assert again.created and again.intake.status == TariffIntakeStatus.DUPLICATE
    assert again.intake.tariff_version_id == first.intake.tariff_version_id
    assert "already imported" in again.intake.error
    assert len(db.scalars(select(TariffVersion)).all()) == 1


def test_an_email_without_attachment(db):
    allow_vendor(db)
    intake = ingest(db, build_eml([])).intake
    assert intake.status == TariffIntakeStatus.NO_ATTACHMENT and intake.tariff_version_id is None


def test_an_attachment_that_is_not_xlsx_is_rejected(db):
    allow_vendor(db)
    intake = ingest(db, build_eml([("rates.csv", b"a,b\n1,2\n")])).intake
    assert intake.status == TariffIntakeStatus.REJECTED and ".xlsx" in intake.error
    fake = ingest(
        db, build_eml([("rates.xlsx", b"not a zip")], message_id="<fake@vendor.example.com>")
    ).intake
    assert fake.status == TariffIntakeStatus.REJECTED and "not an .xlsx" in fake.error
    assert db.scalars(select(TariffVersion)).all() == []


def test_two_workbooks_in_one_email_are_rejected(db, workbook_bytes):
    allow_vendor(db)
    other = modified_workbook(lambda wb: None)
    intake = ingest(db, build_eml([("a.xlsx", workbook_bytes), ("b.xlsx", other)])).intake
    assert intake.status == TariffIntakeStatus.REJECTED
    assert "exactly one workbook" in intake.error
    assert db.scalars(select(TariffVersion)).all() == []


def test_an_oversized_email_is_refused_before_it_is_read(db, as_admin, monkeypatch):
    monkeypatch.setattr(settings, "tariff_intake_max_eml_bytes", 1024)
    with pytest.raises(ValidationError, match="larger than"):
        svc.ingest_eml(db, b"x" * 2048, source="upload", actor=None)
    response = as_admin.post(
        "/api/v1/tariffs/intake/upload", files=eml_file("big.eml", b"x" * 2048)
    )
    assert response.status_code == 422
    db.rollback()
    assert db.scalars(select(TariffEmailIntake)).all() == []


def test_a_malformed_file_is_recorded_as_failed(db):
    intake = ingest(db, b"\x00\x01 this is not an email at all \xff").intake
    assert intake.status == TariffIntakeStatus.FAILED
    assert intake.sender is None and intake.message_id.startswith("sha256:")
    assert "not a readable email" in intake.error
    assert "Traceback" not in intake.error


def test_a_sender_outside_the_allowed_domains_is_held_until_an_approver_releases_it(
    db, workbook_bytes, intake_folder, users, api_for
):
    # Default settings: no allowed domain, so every sender is held.
    result = ingest(db, build_eml([("r.xlsx", workbook_bytes)]))
    intake = result.intake
    assert intake.status == TariffIntakeStatus.HELD_SENDER
    assert intake.tariff_version_id is None
    assert db.scalars(select(TariffVersion)).all() == []
    held = intake_folder / "held" / f"intake-{intake.id}.xlsx"
    assert held.read_bytes() == workbook_bytes

    with pytest.raises(PermissionDeniedError):
        svc.release(db, intake, users[Role.ADMIN])  # Admin, but not an approver
    db.rollback()

    admin = api_for(Role.ADMIN)
    assert admin.post(f"/api/v1/tariffs/intake/{intake.id}/release").status_code == 403
    see_committed_changes(db)
    svc.update_settings(db, approver_emails=[users[Role.ADMIN].email], actor=None)
    db.commit()
    released = admin.post(f"/api/v1/tariffs/intake/{intake.id}/release")
    assert released.status_code == 200, released.text
    body = released.json()
    assert body["status"] == "imported" and body["tariff_version_status"] == "draft"
    assert body["review_note"]
    assert not held.exists()
    assert (intake_folder / "processed" / f"released-intake-{intake.id}.xlsx").exists()
    again = admin.post(f"/api/v1/tariffs/intake/{intake.id}/release")
    assert again.status_code == 409


# --- Approval -------------------------------------------------------------------------------


def _draft_by_email(db, workbook_bytes) -> TariffVersion:
    allow_vendor(db)
    intake = ingest(db, build_eml([("r.xlsx", workbook_bytes)])).intake
    return db.get(TariffVersion, intake.tariff_version_id)


def test_only_an_approver_approves_or_rejects(db, workbook_bytes, users, api_for):
    version = _draft_by_email(db, workbook_bytes)
    operations = api_for(Role.OPERATIONS)
    assert operations.post(f"/api/v1/tariffs/versions/{version.id}/approve").status_code == 403
    assert (
        operations.post(
            f"/api/v1/tariffs/versions/{version.id}/reject", json={"reason": "x"}
        ).status_code
        == 403
    )
    admin = api_for(Role.ADMIN)
    refused = admin.post(f"/api/v1/tariffs/versions/{version.id}/approve")
    assert refused.status_code == 403
    assert "approver" in refused.json()["message"].lower()
    assert (
        admin.post(
            f"/api/v1/tariffs/versions/{version.id}/reject", json={"reason": "x"}
        ).status_code
        == 403
    )
    with pytest.raises(PermissionDeniedError):
        svc.approve(db, version, users[Role.ADMIN])
    db.rollback()

    svc.update_settings(db, approver_emails=[users[Role.ADMIN].email.upper()], actor=None)
    db.commit()
    approved = admin.post(f"/api/v1/tariffs/versions/{version.id}/approve")
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "active"
    see_committed_changes(db)
    actions = [a.action for a in db.scalars(select(AuditEvent))]
    assert "tariff_version.approved" in actions and "tariff_version.activated" in actions
    intake = db.scalar(select(TariffEmailIntake))
    assert intake.reviewed_at is not None and intake.status == "imported"
    # Approving it again: only a draft can be approved.
    assert admin.post(f"/api/v1/tariffs/versions/{version.id}/approve").status_code == 409


def test_an_operations_user_on_the_approver_list_still_cannot_approve(db, workbook_bytes, users):
    version = _draft_by_email(db, workbook_bytes)
    svc.update_settings(db, approver_emails=[users[Role.OPERATIONS].email], actor=None)
    db.commit()
    with pytest.raises(PermissionDeniedError):
        svc.approve(db, version, users[Role.OPERATIONS])


def test_a_rejected_draft_stays_a_draft_and_can_never_be_activated(
    db, workbook_bytes, admin_is_tariff_approver, as_admin
):
    version = _draft_by_email(db, workbook_bytes)
    no_reason = as_admin.post(f"/api/v1/tariffs/versions/{version.id}/reject", json={"reason": " "})
    assert no_reason.status_code == 422
    rejected = as_admin.post(
        f"/api/v1/tariffs/versions/{version.id}/reject", json={"reason": "Prices look wrong"}
    )
    assert rejected.status_code == 200 and rejected.json()["status"] == "draft"
    see_committed_changes(db)
    intake = db.scalar(select(TariffEmailIntake))
    assert intake.status == TariffIntakeStatus.REJECTED
    assert intake.review_note == "Prices look wrong" and intake.reviewed_at is not None
    assert as_admin.post(f"/api/v1/tariffs/versions/{version.id}/approve").status_code == 409
    assert as_admin.post(f"/api/v1/tariffs/versions/{version.id}/activate").status_code == 409
    assert (
        as_admin.post(
            f"/api/v1/tariffs/versions/{version.id}/reject", json={"reason": "again"}
        ).status_code
        == 409
    )


def test_the_activate_route_is_approver_only_and_service_calls_without_an_actor_are_not(
    db, workbook_bytes, users, as_admin
):
    version = imports.import_workbook(
        db,
        workbook_bytes,
        file_name="k.xlsx",
        effective_from=date(2026, 10, 12),
        label=None,
        actor=None,
    )
    db.commit()
    refused = as_admin.post(f"/api/v1/tariffs/versions/{version.id}/activate")
    assert refused.status_code == 403
    assert "approver" in refused.json()["message"].lower()
    see_committed_changes(db)
    svc.update_settings(db, approver_emails=[users[Role.ADMIN].email], actor=None)
    db.commit()
    assert as_admin.post(f"/api/v1/tariffs/versions/{version.id}/activate").status_code == 200

    # Seed and demo scripts activate through the service with no actor: unchanged.
    see_committed_changes(db)
    second = imports.import_workbook(
        db,
        modified_workbook(lambda wb: wb.create_sheet("Notes")),
        file_name="k2.xlsx",
        effective_from=date(2026, 10, 19),
        label=None,
        actor=None,
    )
    imports.activate_version(db, second, actor=None)
    db.commit()
    assert second.status == TariffVersionStatus.ACTIVE


# --- Diff ----------------------------------------------------------------------------------


def test_the_diff_lists_exactly_the_one_price_that_changed(
    db, workbook_bytes, admin_is_tariff_approver, as_admin
):
    base = imports.import_workbook(
        db,
        workbook_bytes,
        file_name="k.xlsx",
        effective_from=date(2026, 10, 12),
        label=None,
        actor=None,
    )
    imports.activate_version(db, base, actor=None)
    db.commit()
    bracket = db.scalar(
        select(TariffRateBracket)
        .join(TariffProduct)
        .where(TariffProduct.version_id == base.id, TariffProduct.mode == "air")
        .order_by(TariffRateBracket.id)
        .offset(40)
    )
    product = db.get(TariffProduct, bracket.product_id)
    old_price = bracket.price_vnd
    new_price = old_price + 1000

    def edit(workbook):
        workbook[bracket.source_sheet][bracket.source_cell] = float(new_price)

    allow_vendor(db)
    intake = ingest(
        db,
        build_eml([("r.xlsx", modified_workbook(edit))], message_id="<rates-3@vendor.example.com>"),
    ).intake
    assert intake.status == TariffIntakeStatus.IMPORTED

    response = as_admin.get(f"/api/v1/tariffs/versions/{intake.tariff_version_id}/diff")
    assert response.status_code == 200, response.text
    diff = response.json()
    assert diff["against_version_id"] == base.id
    assert diff["summary"] == {
        "brackets_changed": 1,
        "brackets_added": 0,
        "brackets_removed": 0,
        "surcharges_changed": 0,
        "surcharges_added": 0,
        "surcharges_removed": 0,
    }
    (entry,) = diff["brackets_changed"]
    assert entry["origin"] == product.origin and entry["product_code"] == product.code
    assert entry["kind"] == bracket.kind and entry["zone"] == bracket.zone
    assert entry["label"] == bracket.label
    assert entry["old_price_vnd"] == f"{old_price:.2f}"
    assert entry["new_price_vnd"] == f"{new_price:.2f}"
    assert diff["products_added"] == [] and diff["products_removed"] == []
    assert diff["truncated"] is False
    assert diff["counts"]["version"]["rate_brackets"] == diff["counts"]["against"]["rate_brackets"]


# --- Privacy -----------------------------------------------------------------------------------


def _every_stored_value(db) -> str:
    chunks = []
    for table in Base.metadata.sorted_tables:
        for row in db.execute(select(table)).all():
            chunks.append(" ".join(str(v) for v in row))
    return "\n".join(chunks)


def test_a_staff_directory_sheet_is_never_stored_or_reported(db, as_admin):
    def edit(workbook):
        sheet = workbook.create_sheet("DS SDT NV VẬN HÀNH")
        sheet["A1"] = "STT"
        sheet["B2"] = "Person Never Stored"
        sheet["E2"] = "0900000123"

    allow_vendor(db)
    raw = build_eml([("r.xlsx", modified_workbook(edit))])
    response = as_admin.post("/api/v1/tariffs/intake/upload", files=eml_file("r.eml", raw))
    assert response.status_code == 201, response.text
    assert response.json()["status"] == "imported"
    listing = as_admin.get("/api/v1/tariffs/intake").text
    diff = as_admin.get(f"/api/v1/tariffs/versions/{response.json()['tariff_version_id']}/diff")
    detail = as_admin.get(f"/api/v1/tariffs/versions/{response.json()['tariff_version_id']}")
    see_committed_changes(db)
    stored = _every_stored_value(db)
    for text in (response.text, listing, diff.text, detail.text, stored):
        assert "Person Never Stored" not in text
        assert "0900000123" not in text
        assert BODY_MARKER not in text
        assert "example.invalid" not in text


def test_responses_carry_provenance_and_never_the_email_body(db, as_admin, workbook_bytes):
    raw = build_eml([("r.xlsx", workbook_bytes)])
    response = as_admin.post("/api/v1/tariffs/intake/upload", files=eml_file("r.eml", raw))
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "held_sender" and body["created"] is True
    assert set(body) == {
        "id", "message_id", "sender", "subject", "received_at", "source", "attachment_name",
        "attachment_sha256", "status", "tariff_version_id", "tariff_version_public_id",
        "tariff_version_status", "error", "warning", "reviewed_at", "review_note", "created_at", "created",
    }  # fmt: skip
    again = as_admin.post("/api/v1/tariffs/intake/upload", files=eml_file("r.eml", raw))
    assert again.status_code == 201 and again.json()["created"] is False
    listing = as_admin.get("/api/v1/tariffs/intake").json()
    assert listing["total"] == 1 and listing["viewer_is_approver"] is False
    assert BODY_MARKER not in json.dumps(listing)
    not_eml = as_admin.post(
        "/api/v1/tariffs/intake/upload", files={"file": ("r.xlsx", workbook_bytes, "x/y")}
    )
    assert not_eml.status_code == 422


def test_marketing_and_operations_cannot_use_the_intake(api_for):
    for role in (Role.OPERATIONS, Role.MARKETING, Role.READ_ONLY_MANAGER):
        client = api_for(role)
        assert client.get("/api/v1/tariffs/intake").status_code == 403
        assert client.get("/api/v1/tariffs/intake/settings").status_code == 403
        assert (
            client.post(
                "/api/v1/tariffs/intake/upload", files=eml_file("r.eml", b"From: a@b.example\n")
            ).status_code
            == 403
        )


# --- Settings ----------------------------------------------------------------------------------


def test_settings_read_the_owner_default_without_writing(db, as_admin):
    response = as_admin.get("/api/v1/tariffs/intake/settings")
    assert response.status_code == 200
    body = response.json()
    assert body["approver_emails"] == list(DEFAULT_APPROVER_EMAILS)
    assert body["allowed_sender_domains"] == [] and body["is_default"] is True
    see_committed_changes(db)
    assert db.get(TariffIntakeSettings, 1) is None


def test_settings_are_validated_and_admin_only(db, as_admin, api_for):
    bad = [
        {"approver_emails": ["not-an-email"]},
        {"approver_emails": []},
        {"allowed_sender_domains": ["not a domain"]},
        {"allowed_sender_domains": ["http://vendor.example.com"]},
    ]
    for payload in bad:
        assert as_admin.patch("/api/v1/tariffs/intake/settings", json=payload).status_code == 422
    saved = as_admin.patch(
        "/api/v1/tariffs/intake/settings",
        json={
            "approver_emails": [" Approver@Demo.Example.com ", "approver@demo.example.com"],
            "allowed_sender_domains": ["@Vendor.Example.com"],
        },
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["approver_emails"] == ["approver@demo.example.com"]
    assert saved.json()["allowed_sender_domains"] == ["vendor.example.com"]
    assert saved.json()["is_default"] is False
    operations = api_for(Role.OPERATIONS)
    assert (
        operations.patch(
            "/api/v1/tariffs/intake/settings", json={"allowed_sender_domains": []}
        ).status_code
        == 403
    )


# --- Folder worker -----------------------------------------------------------------------------


def test_the_folder_worker_moves_every_file_and_deletes_none(
    db, session_factory, workbook_bytes, intake_folder
):
    allow_vendor(db)
    intake_folder.mkdir(parents=True, exist_ok=True)
    (intake_folder / "good.eml").write_bytes(build_eml([("r.xlsx", workbook_bytes)]))
    (intake_folder / "garbage.eml").write_bytes(b"\x00 not an email")
    (intake_folder / "empty.eml").write_bytes(
        build_eml([], message_id="<empty@vendor.example.com>")
    )
    (intake_folder / "notes.txt").write_text("not an email file")

    outcomes = tariff_intake_worker.run_once(intake_folder, session_factory=session_factory)

    assert outcomes == {"imported": 1, "failed": 1, "no_attachment": 1}
    assert sorted(p.name for p in (intake_folder / "processed").iterdir()) == ["good.eml"]
    assert sorted(p.name for p in (intake_folder / "failed").iterdir()) == [
        "empty.eml",
        "garbage.eml",
    ]
    assert not list(intake_folder.glob("*.eml"))
    assert (intake_folder / "notes.txt").exists()  # not an .eml: left alone
    see_committed_changes(db)
    intake = db.scalar(select(TariffEmailIntake).where(TariffEmailIntake.status == "imported"))
    assert intake.source == "folder"
    assert db.get(TariffVersion, intake.tariff_version_id).status == TariffVersionStatus.DRAFT

    # The same email dropped again: recorded once, moved to processed/ under a new name.
    (intake_folder / "good.eml").write_bytes(build_eml([("r.xlsx", workbook_bytes)]))
    tariff_intake_worker.run_once(intake_folder, session_factory=session_factory)
    assert sorted(p.name for p in (intake_folder / "processed").iterdir()) == [
        "good-1.eml",
        "good.eml",
    ]
    see_committed_changes(db)
    assert len(db.scalars(select(TariffEmailIntake)).all()) == 3


def test_the_worker_refuses_an_oversized_file_into_failed(
    db, session_factory, intake_folder, monkeypatch
):
    monkeypatch.setattr(settings, "tariff_intake_max_eml_bytes", 100)
    intake_folder.mkdir(parents=True, exist_ok=True)
    (intake_folder / "big.eml").write_bytes(b"x" * 500)
    outcomes = tariff_intake_worker.run_once(intake_folder, session_factory=session_factory)
    assert outcomes == {"refused": 1}
    assert (intake_folder / "failed" / "big.eml").exists()


def test_the_service_never_writes_to_the_intake_settings_when_reading(db):
    row = svc.get_settings(db)
    assert row.approver_emails == list(DEFAULT_APPROVER_EMAILS)
    assert row not in db
    assert svc.is_approver(db, None) is False


# --- Migration ---------------------------------------------------------------------------------

PHASE_13H_REVISION = "c5e8a1f3d7b9"
PHASE_13G_REVISION = "b7d2e9a4c1f6"
NEW_TABLES = {"tariff_intake_settings", "tariff_email_intakes", "tariff_version_reviews"}


def test_the_migration_is_the_head_and_only_adds_three_tables(tmp_path):
    path = tmp_path / "m.db"
    url = f"sqlite:///{path.as_posix()}"
    assert _alembic(url, "upgrade", PHASE_13G_REVISION).returncode == 0
    before = _tables(path)
    with sqlite3.connect(path) as c:
        schema_before = dict(c.execute("select name, sql from sqlite_master where sql is not null"))
    # Upgraded to 13H itself: fix pack F's revision follows it (its own test covers it).
    assert _alembic(url, "upgrade", PHASE_13H_REVISION).returncode == 0
    assert PHASE_13H_REVISION in _alembic(url, "current").stdout
    assert _tables(path) - before == NEW_TABLES
    with sqlite3.connect(path) as c:
        schema_after = dict(c.execute("select name, sql from sqlite_master where sql is not null"))
        fks = {
            r[3]: (r[2], r[6]) for r in c.execute("pragma foreign_key_list(tariff_email_intakes)")
        }
    for name, sql in schema_before.items():
        assert schema_after[name] == sql, name  # nothing existing altered
    assert fks["tariff_version_id"] == ("tariff_versions", "SET NULL")
    assert fks["reviewed_by_user_id"] == ("users", "SET NULL")
    assert _alembic(url, "upgrade", "head").returncode == 0
    check = _alembic(url, "check")
    assert check.returncode == 0, check.stdout + check.stderr
    assert _alembic(url, "downgrade", PHASE_13G_REVISION).returncode == 0
    assert NEW_TABLES.isdisjoint(_tables(path))
    assert _alembic(url, "upgrade", "head").returncode == 0
