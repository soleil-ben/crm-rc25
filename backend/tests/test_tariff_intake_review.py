"""Phase 13H independent-review fixes (DEC-0214): rejection by version, who changes the
approvers, archive bombs, the held file, the staff-directory strip, duplicate keys, the
folder worker, the Date window and reprocessing. Sanitized fixture and demo addresses only.
"""

from __future__ import annotations

import io
import zipfile
from datetime import date

import openpyxl
import pytest
from sqlalchemy import select

from app.core.config import settings
from app.core.enums import Role, TariffIntakeStatus, TariffVersionStatus
from app.models import AuditEvent, TariffEmailIntake, TariffVersion, TariffVersionReview
from app.services import auth_service
from app.services import tariff_import_service as imports
from app.services import tariff_intake_service as svc
from app.services.errors import ConflictError, PermissionDeniedError, ValidationError
from app.workers import tariff_intake_worker
from tests.conftest import TEST_PASSWORD, ApiClient, see_committed_changes, sign_in
from tests.test_tariff_intake import WORKBOOK, allow_vendor, build_eml, eml_file, ingest

MARKER = "PHONE-MARKER-REVIEW-77"
STRANGER = "rates@stranger.example.org"


@pytest.fixture(autouse=True)
def intake_folder(tmp_path, monkeypatch):
    folder = tmp_path / "intake"
    monkeypatch.setattr(settings, "tariff_intake_dir", str(folder))
    return folder


@pytest.fixture(scope="module")
def workbook_bytes() -> bytes:
    return WORKBOOK.read_bytes()


def with_directory(extra=None) -> bytes:
    workbook = openpyxl.load_workbook(WORKBOOK)
    sheet = workbook.create_sheet("DS SDT test")
    sheet["A1"] = MARKER
    sheet["B2"] = "Demo Person"
    if extra:
        extra(workbook)
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def manual_draft(db, content: bytes) -> TariffVersion:
    version = imports.import_workbook(
        db, content, file_name="m.xlsx", effective_from=date(2026, 10, 12), label=None, actor=None
    )
    db.commit()
    return version


# --- 1. A rejection is recorded by version, whatever its source ---------------------------------


def test_a_rejected_manual_draft_can_never_be_activated(
    db, workbook_bytes, admin_is_tariff_approver, as_admin
):
    version = manual_draft(db, workbook_bytes)
    response = as_admin.post(
        f"/api/v1/tariffs/versions/{version.id}/reject", json={"reason": "Not for us"}
    )
    assert response.status_code == 200, response.text
    assert as_admin.post(f"/api/v1/tariffs/versions/{version.id}/approve").status_code == 409
    assert as_admin.post(f"/api/v1/tariffs/versions/{version.id}/activate").status_code == 409
    see_committed_changes(db)
    review = db.scalar(select(TariffVersionReview))
    assert review.tariff_version_id == version.id and review.decision == "rejected"
    assert review.note == "Not for us" and review.reviewed_by_user_id == admin_is_tariff_approver.id
    # Not even a script without an actor activates a rejected version.
    with pytest.raises(ConflictError, match="rejected"):
        imports.activate_version(db, db.get(TariffVersion, version.id), actor=None)
    db.rollback()
    assert db.get(TariffVersion, version.id).status == TariffVersionStatus.DRAFT


# --- 2. Who may change the approver list --------------------------------------------------------


def _second_admin(db, client):
    other = auth_service.create_user(
        db,
        email="second.admin@demo.example.com",
        full_name="Second Admin",
        password=TEST_PASSWORD,
        role=Role.ADMIN.value,
    )
    db.commit()
    client.cookies.clear()
    return other, ApiClient(client, sign_in(client, other.email))


def test_only_a_current_approver_changes_the_approver_list(db, client, users, api_for):
    admin = api_for(Role.ADMIN)
    # Default list: no active administrator matches, so an Admin may set it (recovery).
    recovered = admin.patch(
        "/api/v1/tariffs/intake/settings", json={"approver_emails": [users[Role.ADMIN].email]}
    )
    assert recovered.status_code == 200, recovered.text
    see_committed_changes(db)
    event = db.scalar(
        select(AuditEvent).where(AuditEvent.action == "tariff_intake.approvers_recovered")
    )
    assert event is not None
    assert users[Role.ADMIN].email in event.detail_json

    _other, second = _second_admin(db, client)
    refused = second.patch(
        "/api/v1/tariffs/intake/settings",
        json={"approver_emails": ["second.admin@demo.example.com"]},
    )
    assert refused.status_code == 403
    assert "approver" in refused.json()["message"].lower()
    # Domains are not the approver list: any administrator may change them; audited in full.
    domains = second.patch(
        "/api/v1/tariffs/intake/settings", json={"allowed_sender_domains": ["vendor.example.com"]}
    )
    assert domains.status_code == 200
    assert domains.json()["approver_emails"] == [users[Role.ADMIN].email]

    first = api_for(Role.ADMIN)
    changed = first.patch(
        "/api/v1/tariffs/intake/settings",
        json={"approver_emails": [users[Role.ADMIN].email, "second.admin@demo.example.com"]},
    )
    assert changed.status_code == 200
    see_committed_changes(db)
    last = db.scalars(
        select(AuditEvent)
        .where(AuditEvent.action == "tariff_intake.settings_updated")
        .order_by(AuditEvent.id.desc())
    ).first()
    assert '"old": ["admin@demo.example.com"]' in last.detail_json
    assert "second.admin@demo.example.com" in last.detail_json
    assert '"vendor.example.com"' in last.detail_json


def test_the_service_refuses_a_non_approver_admin_when_an_approver_admin_exists(db, users):
    svc.update_settings(db, approver_emails=[users[Role.ADMIN].email], actor=None)
    db.commit()
    other = auth_service.create_user(
        db, email="third.admin@demo.example.com", full_name="Third Admin",
        password=TEST_PASSWORD, role=Role.ADMIN.value,
    )  # fmt: skip
    db.commit()
    with pytest.raises(PermissionDeniedError):
        svc.update_settings(db, approver_emails=[other.email], actor=other)
    db.rollback()
    # Once the approving administrator is deactivated, recovery is possible again.
    users[Role.ADMIN].is_active = False
    db.commit()
    svc.update_settings(db, approver_emails=[other.email], actor=other)
    db.commit()
    assert svc.get_settings(db).approver_emails == [other.email]


# --- 3. Archive bombs ---------------------------------------------------------------------------


def _zip(members: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in members.items():
            archive.writestr(name, data)
    return buffer.getvalue()


def test_an_archive_bomb_is_rejected_before_openpyxl(db, monkeypatch):
    allow_vendor(db)

    def never(*_a, **_k):
        raise AssertionError("the importer must not see an archive bomb")

    monkeypatch.setattr(imports, "import_workbook", never)
    bomb = _zip({"xl/workbook.xml": b"<workbook/>", "xl/worksheets/sheet1.xml": b"0" * (8 << 20)})
    many = _zip({f"xl/p{i}.xml": b"x" for i in range(2001)})
    for n, content in enumerate((bomb, many)):
        intake = ingest(
            db, build_eml([("r.xlsx", content)], message_id=f"<bomb{n}@vendor.example.com>")
        ).intake
        assert intake.status == TariffIntakeStatus.REJECTED, intake.error
        assert "refused" in intake.error


# --- 4. The held file ---------------------------------------------------------------------------


def test_a_lost_held_file_is_restored_by_the_same_email_and_no_temp_file_remains(
    db, workbook_bytes, intake_folder
):
    raw = build_eml([("r.xlsx", workbook_bytes)])
    intake = ingest(db, raw).intake
    held = svc.held_path(intake.id)
    assert held.exists()
    assert [p.name for p in held.parent.iterdir()] == [held.name]  # no temporary file left
    held.unlink()  # lost (for example, a crash between commit and rename)
    again = ingest(db, raw)
    assert again.created is False and again.intake.id == intake.id
    assert held.read_bytes() == workbook_bytes


def test_a_failed_unit_leaves_no_held_file(db, workbook_bytes, intake_folder, monkeypatch):
    def broken_commit():
        raise RuntimeError("commit failed")

    monkeypatch.setattr(db, "commit", broken_commit)
    with pytest.raises(RuntimeError):
        ingest(db, build_eml([("r.xlsx", workbook_bytes)]))
    held_dir = intake_folder / "held"
    assert not held_dir.exists() or list(held_dir.iterdir()) == []


# --- 5. The staff directory is stripped before anything stores it ------------------------------


def test_the_staff_directory_never_reaches_the_held_or_processed_workbook(db, users, intake_folder):
    raw_workbook = with_directory()
    intake = ingest(
        db, build_eml([("d.xlsx", raw_workbook)], sender=STRANGER, message_id="<sdt@x.example.org>")
    ).intake
    assert intake.status == TariffIntakeStatus.HELD_SENDER
    held = svc.held_path(intake.id)
    stripped = held.read_bytes()
    assert stripped != raw_workbook
    assert intake.attachment_sha256 == svc.hashlib.sha256(stripped).hexdigest()
    with zipfile.ZipFile(io.BytesIO(stripped)) as archive:
        everything = b"".join(archive.read(n) for n in archive.namelist())
    assert MARKER.encode() not in everything and b"Demo Person" not in everything
    assert "DS SDT test" not in openpyxl.load_workbook(io.BytesIO(stripped)).sheetnames

    svc.update_settings(db, approver_emails=[users[Role.ADMIN].email], actor=None)
    db.commit()
    svc.release(db, intake, users[Role.ADMIN])
    db.commit()
    svc.archive_held(intake.id)
    assert intake.status == TariffIntakeStatus.IMPORTED
    for path in intake_folder.rglob("*.xlsx"):
        assert MARKER.encode() not in path.read_bytes()
    report = imports.report(db.get(TariffVersion, intake.tariff_version_id))
    assert report["skipped_sheets"] == []  # the reader never even saw the sheet


def test_stripping_is_deterministic_so_a_resent_workbook_is_a_duplicate(db):
    allow_vendor(db)
    content = with_directory()
    first = ingest(db, build_eml([("a.xlsx", content)], message_id="<a@vendor.example.com>"))
    second = ingest(db, build_eml([("a.xlsx", content)], message_id="<b@vendor.example.com>"))
    assert first.intake.status == TariffIntakeStatus.IMPORTED
    assert second.intake.status == TariffIntakeStatus.DUPLICATE
    assert second.intake.attachment_sha256 == first.intake.attachment_sha256


# --- 7. Duplicate keys --------------------------------------------------------------------------


def test_an_outside_sender_cannot_pre_empt_the_vendors_message_id(db, workbook_bytes):
    allow_vendor(db)
    message_id = "<shared-id@vendor.example.com>"
    squatter = ingest(
        db, build_eml([("r.xlsx", workbook_bytes)], sender=STRANGER, message_id=message_id)
    ).intake
    assert squatter.status == TariffIntakeStatus.HELD_SENDER
    vendor = ingest(db, build_eml([("r.xlsx", workbook_bytes)], message_id=message_id))
    assert vendor.created and vendor.intake.id != squatter.id
    assert vendor.intake.status == TariffIntakeStatus.IMPORTED


def test_a_concurrent_duplicate_meets_the_unique_key_and_gets_the_first_row(
    db, workbook_bytes, monkeypatch
):
    allow_vendor(db)
    raw = build_eml([("r.xlsx", workbook_bytes)])
    first = ingest(db, raw).intake
    real = svc._find_existing
    calls = {"n": 0}

    def racing(session, message_id, sender):
        calls["n"] += 1
        return None if calls["n"] == 1 else real(session, message_id, sender)

    monkeypatch.setattr(svc, "_find_existing", racing)
    again = ingest(db, raw)
    assert again.created is False and again.intake.id == first.id
    assert len(db.scalars(select(TariffEmailIntake)).all()) == 1


# --- 8. The folder worker -----------------------------------------------------------------------


def test_a_file_that_cannot_be_moved_is_not_ingested_or_audited_again(
    db, session_factory, workbook_bytes, intake_folder, monkeypatch
):
    allow_vendor(db)
    intake_folder.mkdir(parents=True, exist_ok=True)
    (intake_folder / "a.eml").write_bytes(build_eml([("r.xlsx", workbook_bytes)]))
    real_move = tariff_intake_worker._move

    def stuck(path, folder):
        raise OSError("locked by another program")

    monkeypatch.setattr(tariff_intake_worker, "_move", stuck)
    assert tariff_intake_worker.run_once(session_factory=session_factory) == {"imported": 1}
    assert (intake_folder / "a.eml").exists()
    see_committed_changes(db)
    audits = len(db.scalars(select(AuditEvent)).all())

    assert tariff_intake_worker.run_once(session_factory=session_factory) == {"already_received": 1}
    see_committed_changes(db)
    assert len(db.scalars(select(AuditEvent)).all()) == audits

    monkeypatch.setattr(tariff_intake_worker, "_move", real_move)
    tariff_intake_worker.run_once(session_factory=session_factory)
    assert (intake_folder / "processed" / "a.eml").exists()
    assert len(db.scalars(select(TariffEmailIntake)).all()) == 1


def test_symbolic_links_are_skipped(db, session_factory, workbook_bytes, intake_folder, tmp_path):
    outside = tmp_path / "outside.eml"
    outside.write_bytes(build_eml([("r.xlsx", workbook_bytes)]))
    intake_folder.mkdir(parents=True, exist_ok=True)
    try:
        (intake_folder / "link.eml").symlink_to(outside)
    except OSError:
        pytest.skip("this account may not create symbolic links")
    assert tariff_intake_worker.run_once(session_factory=session_factory) == {}
    assert outside.exists() and (intake_folder / "link.eml").is_symlink()


# --- 9. An implausible Date ---------------------------------------------------------------------


def test_an_implausible_email_date_is_not_the_effective_date(db, workbook_bytes):
    allow_vendor(db)
    intake = ingest(
        db, build_eml([("r.xlsx", workbook_bytes)], sent="Mon, 12 Oct 2020 10:00:00 +0000")
    ).intake
    version = db.get(TariffVersion, intake.tariff_version_id)
    assert version.effective_from == svc.effective_date(None, svc.utcnow())
    assert "more than 60 days" in intake.warning


# --- 10. Reprocessing a failed folder email ------------------------------------------------------


def test_an_approver_reprocesses_a_failed_folder_email(
    db, session_factory, workbook_bytes, intake_folder, monkeypatch, users, api_for
):
    allow_vendor(db)
    intake_folder.mkdir(parents=True, exist_ok=True)
    (intake_folder / "r.eml").write_bytes(build_eml([("r.xlsx", workbook_bytes)]))
    real_import = imports.import_workbook

    def transient(*_a, **_k):
        raise ValidationError("The workbook could not be read (transient test fault).")

    monkeypatch.setattr(imports, "import_workbook", transient)
    assert tariff_intake_worker.run_once(session_factory=session_factory) == {"failed": 1}
    monkeypatch.setattr(imports, "import_workbook", real_import)
    see_committed_changes(db)
    intake = db.scalar(select(TariffEmailIntake))
    assert intake.stored_file == "failed/r.eml"

    admin = api_for(Role.ADMIN)
    assert admin.post(f"/api/v1/tariffs/intake/{intake.id}/reprocess").status_code == 403
    see_committed_changes(db)
    svc.update_settings(db, approver_emails=[users[Role.ADMIN].email], actor=None)
    db.commit()
    response = admin.post(f"/api/v1/tariffs/intake/{intake.id}/reprocess")
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "imported"
    assert response.json()["tariff_version_status"] == "draft"
    assert (intake_folder / "processed" / "r.eml").exists()
    assert admin.post(f"/api/v1/tariffs/intake/{intake.id}/reprocess").status_code == 409


def test_an_uploaded_failed_email_cannot_be_reprocessed(db, admin_is_tariff_approver, as_admin):
    response = as_admin.post(
        "/api/v1/tariffs/intake/upload", files=eml_file("bad.eml", b"\x00 not an email")
    )
    assert response.json()["status"] == "failed"
    assert (
        as_admin.post(f"/api/v1/tariffs/intake/{response.json()['id']}/reprocess").status_code
        == 409
    )
