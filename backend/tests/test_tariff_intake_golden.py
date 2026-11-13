"""Independent golden tests for Phase 13H: vendor rate-email intake (OD-76), black box.

Everything goes through the staff HTTP API (upload, list, diff, approve, reject, release,
settings, activate) except the folder worker, which is driven as the operator would run it.
Every email is built here from the **sanitized** fixture workbook or an in-test copy
modified with openpyxl in ``tmp_path``; demo addresses only; no network.

Expected values are worked out by hand from the fixture's cells (read once when this file
was written), not read back from the product:

* HCM-AIR-CAD!C50 is AIR-CAD, zone 2, per-kg tier "21-44": 243,000 VND/kg.
* HN-AIR-CAD!B8 is AIR-CAD (Hà Nội), zone 1, per-bill band "1": 400,455.20 VND.
* HCM-AIR-CAD!A53 is the open per-kg tier "300KGS+", priced for AIR-CAD and AIR-CAD
  EXPRESS in zones 1-3 (six cells).

A failing assertion is a product defect; nothing here is marked xfail.
"""

from __future__ import annotations

import json
from decimal import Decimal
from email.message import EmailMessage
from pathlib import Path

import openpyxl
import pytest
from sqlalchemy import String, Text, select

from app.core.config import settings
from app.core.enums import Role, RouteGroup
from app.core.time_utils import utcnow
from app.models import Base, ShipmentPackage, TariffEmailIntake, TariffVersion
from app.services import consolidation_service as cs
from app.services import fx_service
from app.workers import tariff_intake_worker
from tests.conftest import booked_shipment, make_customer, see_committed_changes
from tests.test_fx_service import SAMPLE_XML

FIXTURE = (
    Path(__file__).resolve().parent / "fixtures" / "kango_canada_rates_2026-10-12_sanitized.xlsx"
)
XLSX_TYPE = ("application", "vnd.openxmlformats-officedocument.spreadsheetml.sheet")
VENDOR = "tariffs@vendor.example.com"
STRANGER = "rates@stranger.example.org"
APPROVER_DOMAIN = "vendor.example.com"
MARKER = "PHONE-MARKER-123"
BODY_MARKER = "GOLDEN-BODY-NEVER-STORED"
D = Decimal

UPLOAD = "/api/v1/tariffs/intake/upload"
LISTING = "/api/v1/tariffs/intake"
SETTINGS = "/api/v1/tariffs/intake/settings"


# --- Helpers ------------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def intake_dir(tmp_path, monkeypatch) -> Path:
    folder = tmp_path / "intake_root" / "inbox"
    monkeypatch.setattr(settings, "tariff_intake_dir", str(folder))
    return folder


def eml(
    attachments: list[tuple[str, bytes]],
    *,
    sender: str = VENDOR,
    message_id: str | None = "<golden-1@vendor.example.com>",
    subject: str = "Golden rates",
    sent: str = "Tue, 20 Oct 2026 10:00:00 -0400",
) -> bytes:
    message = EmailMessage()
    message["From"] = f"Vendor <{sender}>"
    message["To"] = "intake@demo.example.com"
    message["Subject"] = subject
    if message_id:
        message["Message-ID"] = message_id
    message["Date"] = sent
    message.set_content(f"Rates attached. {BODY_MARKER}")
    for name, data in attachments:
        maintype, subtype = (
            XLSX_TYPE if name.lower().endswith(".xlsx") else ("application", "octet-stream")
        )
        message.add_attachment(data, maintype=maintype, subtype=subtype, filename=name)
    return message.as_bytes()


def workbook_copy(tmp_path: Path, name: str, edit=None) -> bytes:
    """A copy of the sanitized fixture, edited with openpyxl and saved under tmp_path."""
    workbook = openpyxl.load_workbook(FIXTURE)
    if edit is not None:
        edit(workbook)
    target = tmp_path / "workbooks" / name
    target.parent.mkdir(parents=True, exist_ok=True)
    workbook.save(target)
    return target.read_bytes()


def upload(client, raw: bytes, filename: str = "rates.eml"):
    return client.post(UPLOAD, files={"file": (filename, raw, "message/rfc822")})


def make_admin_approver(client, users, domains=(APPROVER_DOMAIN,)):
    response = client.patch(
        SETTINGS,
        json={
            "approver_emails": [users[Role.ADMIN].email],
            "allowed_sender_domains": list(domains),
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def version_status(client, version_id: int) -> str:
    response = client.get(f"/api/v1/tariffs/versions/{version_id}")
    assert response.status_code == 200, response.text
    return response.json()["status"]


def version_count(db) -> int:
    see_committed_changes(db)
    return len(db.scalars(select(TariffVersion)).all())


def edit_prices(workbook) -> None:
    workbook["HCM-AIR-CAD"]["C50"] = 250000  # 243,000 -> 250,000 (per kg, 21-44, zone 2)
    workbook["HN-AIR-CAD"]["B8"] = 410000  # 400,455.20 -> 410,000 (per bill, band 1, zone 1)
    workbook["HCM-AIR-CAD"]["A53"] = "300+"  # the open tier relabelled: 6 removed, 6 added


# --- Happy path: upload -> draft -> diff -> approve -> pricing ------------------------------


def _consolidation(db):
    fx_service.sync_once(db, fetcher=lambda _u: SAMPLE_XML, clock=utcnow, worker_name="t")
    db.commit()
    kids = []
    for i, kg in enumerate((3, 6, 12)):
        shipment = booked_shipment(
            db, make_customer(db, email=f"golden{i}@demo.example.com"), RouteGroup.VCA
        )
        for package in db.query(ShipmentPackage).filter_by(shipment_id=shipment.id):
            package.weight_kg = D(kg)
            package.weight_value = D(kg)
            package.length_cm = package.width_cm = package.height_cm = None
        kids.append(shipment)
    db.commit()
    con = cs.create_consolidation(
        db,
        {
            "solaris_service": "air_standard",
            "origin": "HCM",
            "vendor_reference": "GOLDN",
            "actual_weight_kg": "21",
        },
        actor=None,
    )
    for shipment in kids:
        cs.add_member(db, con, shipment, actor=None)
    db.commit()
    return con


def test_happy_path_diff_approve_supersede_and_pricing_uses_the_new_price(
    db, as_admin, users, tmp_path
):
    make_admin_approver(as_admin, users)

    first = upload(as_admin, eml([("base.xlsx", FIXTURE.read_bytes())]))
    assert first.status_code == 201, first.text
    assert first.json()["status"] == "imported"
    assert first.json()["tariff_version_status"] == "draft"
    base_id = first.json()["tariff_version_id"]
    approved = as_admin.post(f"/api/v1/tariffs/versions/{base_id}/approve")
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "active"

    see_committed_changes(db)
    con = _consolidation(db)
    before = as_admin.get(f"/api/v1/consolidations/{con.id}/pricing")
    assert before.status_code == 200, before.text
    assert D(before.json()["estimate"]["base_freight_vnd"]) == D("243000") * 21  # 5,103,000

    changed = workbook_copy(tmp_path, "changed.xlsx", edit_prices)
    second = upload(
        as_admin,
        eml([("changed.xlsx", changed)], message_id="<golden-2@vendor.example.com>"),
    )
    assert second.status_code == 201, second.text
    assert second.json()["status"] == "imported"
    new_id = second.json()["tariff_version_id"]
    assert new_id != base_id
    assert version_status(as_admin, new_id) == "draft"
    assert version_status(as_admin, base_id) == "active"  # nothing activates by itself

    diff = as_admin.get(f"/api/v1/tariffs/versions/{new_id}/diff")
    assert diff.status_code == 200, diff.text
    body = diff.json()
    assert body["against_version_id"] == base_id
    assert body["summary"] == {
        "brackets_changed": 2,
        "brackets_added": 6,
        "brackets_removed": 6,
        "surcharges_changed": 0,
        "surcharges_added": 0,
        "surcharges_removed": 0,
    }
    by_price = {(e["old_price_vnd"], e["new_price_vnd"]): e for e in body["brackets_changed"]}
    assert set(by_price) == {("243000.00", "250000.00"), ("400455.20", "410000.00")}
    hcm = by_price[("243000.00", "250000.00")]
    assert (hcm["product_code"], hcm["kind"], hcm["zone"], hcm["label"]) == (
        "AIR-CAD",
        "per_kg",
        2,
        "21-44",
    )
    han = by_price[("400455.20", "410000.00")]
    assert (han["product_code"], han["kind"], han["zone"]) == ("AIR-CAD", "per_bill", 1)
    assert han["origin"] != hcm["origin"]
    removed = {(e["product_code"], e["zone"], e["label"]) for e in body["brackets_removed"]}
    added = {(e["product_code"], e["zone"], e["label"]) for e in body["brackets_added"]}
    assert removed == {(c, z, "300KGS+") for c in ("AIR-CAD", "AIR-CAD EXPRESS") for z in (1, 2, 3)}
    assert added == {(c, z, "300+") for c in ("AIR-CAD", "AIR-CAD EXPRESS") for z in (1, 2, 3)}
    old_300 = {(e["product_code"], e["zone"]): e["old_price_vnd"] for e in body["brackets_removed"]}
    assert old_300[("AIR-CAD", 2)] == "228000.00" and old_300[("AIR-CAD EXPRESS", 2)] == "296000.00"
    assert all(e["new_price_vnd"] is None for e in body["brackets_removed"])
    assert all(e["old_price_vnd"] is None for e in body["brackets_added"])
    assert body["products_added"] == [] and body["products_removed"] == []

    approved = as_admin.post(f"/api/v1/tariffs/versions/{new_id}/approve")
    assert approved.status_code == 200, approved.text
    assert version_status(as_admin, new_id) == "active"
    assert version_status(as_admin, base_id) == "superseded"

    after = as_admin.get(f"/api/v1/consolidations/{con.id}/pricing")
    assert after.status_code == 200, after.text
    assert D(after.json()["estimate"]["base_freight_vnd"]) == D("250000") * 21  # 5,250,000


# --- Who may do what ----------------------------------------------------------------------


def test_a_non_approver_admin_gets_403_on_approve_reject_release_and_legacy_activate(
    db, as_admin, users
):
    # Allowed domain, but the approver list is the owner's default: the Admin is not on it.
    saved = as_admin.patch(SETTINGS, json={"allowed_sender_domains": [APPROVER_DOMAIN]})
    assert saved.status_code == 200
    assert users[Role.ADMIN].email not in saved.json()["approver_emails"]
    draft = upload(as_admin, eml([("r.xlsx", FIXTURE.read_bytes())])).json()
    version_id = draft["tariff_version_id"]
    for url, payload in (
        (f"/api/v1/tariffs/versions/{version_id}/approve", None),
        (f"/api/v1/tariffs/versions/{version_id}/activate", None),
        (f"/api/v1/tariffs/versions/{version_id}/reject", {"reason": "no"}),
    ):
        response = as_admin.post(url, json=payload) if payload else as_admin.post(url)
        assert response.status_code == 403, (url, response.text)
    held = upload(
        as_admin,
        eml([("r.xlsx", FIXTURE.read_bytes())], sender=STRANGER, message_id="<h@x.example.org>"),
    ).json()
    assert held["status"] == "held_sender"
    assert as_admin.post(f"/api/v1/tariffs/intake/{held['id']}/release").status_code == 403
    assert version_status(as_admin, version_id) == "draft"
    listing = as_admin.get(LISTING).json()
    assert listing["viewer_is_approver"] is False


@pytest.mark.parametrize("role", [Role.OPERATIONS, Role.MARKETING, Role.READ_ONLY_MANAGER])
def test_other_roles_are_refused_upload_approve_and_settings(db, api_for, users, role):
    admin = api_for(Role.ADMIN)
    make_admin_approver(admin, users)
    draft = upload(admin, eml([("r.xlsx", FIXTURE.read_bytes())])).json()
    version_id = draft["tariff_version_id"]

    client = api_for(role)
    raw = eml([("r.xlsx", FIXTURE.read_bytes())], message_id="<other@vendor.example.com>")
    assert upload(client, raw).status_code == 403
    assert client.post(f"/api/v1/tariffs/versions/{version_id}/approve").status_code == 403
    assert client.post(f"/api/v1/tariffs/versions/{version_id}/activate").status_code == 403
    assert (
        client.post(
            f"/api/v1/tariffs/versions/{version_id}/reject", json={"reason": "x"}
        ).status_code
        == 403
    )
    assert client.get(SETTINGS).status_code == 403
    assert client.patch(SETTINGS, json={"allowed_sender_domains": []}).status_code == 403
    assert client.get(LISTING).status_code == 403
    see_committed_changes(db)
    assert len(db.scalars(select(TariffEmailIntake)).all()) == 1
    assert db.get(TariffVersion, version_id).status == "draft"


def test_settings_validation_refuses_bad_input_and_changes_nothing(as_admin):
    before = as_admin.get(SETTINGS).json()
    for payload in (
        {"approver_emails": ["ben-at-demo.example.com"]},
        {"approver_emails": ["ok@demo.example.com", "not an email"]},
        {"approver_emails": []},
        {"approver_emails": ["   "]},
        {"allowed_sender_domains": ["vendor"]},
        {"allowed_sender_domains": ["vendor.example.com/path"]},
        {"allowed_sender_domains": ["*.vendor.example.com"]},
        {"allowed_sender_domains": ["vendor..example.com"]},
    ):
        response = as_admin.patch(SETTINGS, json=payload)
        assert response.status_code == 422, (payload, response.text)
    after = as_admin.get(SETTINGS).json()
    assert after == before and after["is_default"] is True


# --- Held sender, reject, duplicates ---------------------------------------------------------


def test_a_held_sender_is_not_imported_until_released(db, as_admin, users, intake_dir):
    make_admin_approver(as_admin, users)  # vendor.example.com allowed; stranger is not
    raw = eml([("r.xlsx", FIXTURE.read_bytes())], sender=STRANGER, message_id="<s1@x.example.org>")
    held = upload(as_admin, raw)
    assert held.status_code == 201
    body = held.json()
    assert body["status"] == "held_sender" and body["tariff_version_id"] is None
    assert version_count(db) == 0
    assert (intake_dir / "held" / f"intake-{body['id']}.xlsx").exists()

    released = as_admin.post(f"/api/v1/tariffs/intake/{body['id']}/release")
    assert released.status_code == 200, released.text
    assert released.json()["status"] == "imported"
    assert released.json()["tariff_version_status"] == "draft"
    assert version_count(db) == 1
    assert not (intake_dir / "held" / f"intake-{body['id']}.xlsx").exists()
    assert (intake_dir / "processed" / f"released-intake-{body['id']}.xlsx").exists()
    assert as_admin.post(f"/api/v1/tariffs/intake/{body['id']}/release").status_code == 409


def test_lookalike_senders_are_held(db, as_admin, users):
    make_admin_approver(as_admin, users)
    book = FIXTURE.read_bytes()
    for n, sender in enumerate(
        (
            "rates@sub.vendor.example.com",
            "rates@vendor.example.com.evil.example.org",
            "rates@xvendor.example.com",
        )
    ):
        result = _outcome(as_admin, eml([("r.xlsx", book)], sender=sender, message_id=f"<l{n}@e>"))
        assert result["status"] == "held_sender", (sender, result)
    # A display name that claims the allowed domain does not make the address allowed.
    message = EmailMessage()
    message["From"] = '"tariffs@vendor.example.com" <attacker@evil.example.org>'
    message["Subject"] = "rates"
    message["Message-ID"] = "<spoof@evil.example.org>"
    message.set_content("x")
    message.add_attachment(book, maintype=XLSX_TYPE[0], subtype=XLSX_TYPE[1], filename="r.xlsx")
    result = _outcome(as_admin, message.as_bytes())
    assert result["status"] == "held_sender" and result["sender"] == "attacker@evil.example.org"
    assert version_count(db) == 0


def test_a_tampered_held_workbook_is_not_released(db, as_admin, users, intake_dir):
    make_admin_approver(as_admin, users)
    raw = eml([("r.xlsx", FIXTURE.read_bytes())], sender=STRANGER, message_id="<t@x.example.org>")
    held = _outcome(as_admin, raw)
    path = intake_dir / "held" / f"intake-{held['id']}.xlsx"
    path.write_bytes(path.read_bytes() + b"tampered")
    assert as_admin.post(f"/api/v1/tariffs/intake/{held['id']}/release").status_code == 409
    assert path.exists() and version_count(db) == 0


def test_a_superseded_version_cannot_be_approved_again(db, as_admin, users, tmp_path):
    make_admin_approver(as_admin, users)
    first = _outcome(as_admin, eml([("a.xlsx", FIXTURE.read_bytes())]))["tariff_version_id"]
    other = workbook_copy(tmp_path, "o.xlsx", edit_prices)
    second = _outcome(as_admin, eml([("b.xlsx", other)], message_id="<sup@vendor.example.com>"))[
        "tariff_version_id"
    ]
    assert as_admin.post(f"/api/v1/tariffs/versions/{first}/approve").status_code == 200
    assert as_admin.post(f"/api/v1/tariffs/versions/{second}/approve").status_code == 200
    assert as_admin.post(f"/api/v1/tariffs/versions/{first}/approve").status_code == 409
    assert as_admin.post(f"/api/v1/tariffs/versions/{first}/activate").status_code == 409
    assert version_status(as_admin, first) == "superseded"
    assert version_status(as_admin, second) == "active"


def test_a_rejected_draft_cannot_be_approved_or_activated(db, as_admin, users):
    make_admin_approver(as_admin, users)
    version_id = upload(as_admin, eml([("r.xlsx", FIXTURE.read_bytes())])).json()[
        "tariff_version_id"
    ]
    rejected = as_admin.post(
        f"/api/v1/tariffs/versions/{version_id}/reject", json={"reason": "Wrong prices"}
    )
    assert rejected.status_code == 200, rejected.text
    assert as_admin.post(f"/api/v1/tariffs/versions/{version_id}/approve").status_code == 409
    assert as_admin.post(f"/api/v1/tariffs/versions/{version_id}/activate").status_code == 409
    assert version_status(as_admin, version_id) == "draft"
    items = as_admin.get(LISTING).json()["items"]
    assert [i["status"] for i in items] == ["rejected"]
    assert items[0]["review_note"] == "Wrong prices"


def test_duplicate_message_id_and_duplicate_attachment(db, as_admin, users):
    make_admin_approver(as_admin, users)
    raw = eml([("r.xlsx", FIXTURE.read_bytes())])
    first = upload(as_admin, raw).json()
    again = upload(as_admin, raw).json()
    assert again["created"] is False and again["id"] == first["id"]
    assert version_count(db) == 1

    other = upload(
        as_admin, eml([("r.xlsx", FIXTURE.read_bytes())], message_id="<dup2@vendor.example.com>")
    ).json()
    assert other["created"] is True and other["id"] != first["id"]
    assert other["status"] == "duplicate"
    assert other["tariff_version_id"] == first["tariff_version_id"]
    assert version_count(db) == 1
    assert as_admin.get(LISTING).json()["total"] == 2


# --- Refused emails ---------------------------------------------------------------------------


def _outcome(as_admin, raw: bytes) -> dict:
    response = upload(as_admin, raw)
    assert response.status_code == 201, response.text
    return response.json()


def test_refused_attachments(db, as_admin, users, tmp_path):
    make_admin_approver(as_admin, users)
    book = FIXTURE.read_bytes()
    cases = [
        ([], "no_attachment"),
        ([("rates.xlsm", book)], "rejected"),
        ([("rates.csv", b"zone,price\n1,2\n")], "rejected"),
        ([("a.xlsx", book), ("b.xlsx", workbook_copy(tmp_path, "b.xlsx"))], "rejected"),
        ([("fake.xlsx", b"PK\x03\x04 this is not really a workbook")], "failed"),
    ]
    for n, (attachments, status) in enumerate(cases):
        result = _outcome(as_admin, eml(attachments, message_id=f"<ref{n}@vendor.example.com>"))
        assert result["status"] == status, (attachments and attachments[0][0], result)
        assert result["tariff_version_id"] is None
        assert result["error"] and "Traceback" not in result["error"]
    assert version_count(db) == 0


def test_oversize_email_and_oversize_workbook(db, as_admin, users, monkeypatch):
    make_admin_approver(as_admin, users)
    monkeypatch.setattr(settings, "tariff_intake_max_eml_bytes", 4096)
    big = eml([("r.xlsx", FIXTURE.read_bytes())])
    assert len(big) > 4096
    assert upload(as_admin, big).status_code == 422
    see_committed_changes(db)
    assert db.scalars(select(TariffEmailIntake)).all() == []

    monkeypatch.setattr(settings, "tariff_intake_max_eml_bytes", 15 * 1024 * 1024)
    monkeypatch.setattr(settings, "tariff_import_max_bytes", 1024)
    result = _outcome(as_admin, eml([("r.xlsx", FIXTURE.read_bytes())]))
    assert result["status"] == "rejected" and "larger than" in result["error"]
    assert version_count(db) == 0


def test_malformed_bytes_are_failed_not_a_500(db, as_admin):
    for n, raw in enumerate((b"\x00\xff\xfe garbage", b"", b"From:\n\n\n", b"Subject: x\n\nno")):
        response = upload(as_admin, raw, filename=f"bad{n}.eml")
        assert response.status_code == 201, (raw, response.text)
        assert response.json()["status"] == "failed"
    assert version_count(db) == 0


def test_path_traversal_file_names_never_write_outside_the_intake_dir(
    db, as_admin, users, intake_dir, tmp_path
):
    make_admin_approver(as_admin, users)
    book = FIXTURE.read_bytes()
    names = ("../../x.xlsx", "..\\..\\y.xlsx", "/etc/z.xlsx")
    ids = []
    for n, name in enumerate(names):
        raw = eml([(name, book)], sender=STRANGER, message_id=f"<pt{n}@x.example.org>")
        response = upload(as_admin, raw, filename="../../evil.eml")
        assert response.status_code == 201, response.text
        body = response.json()
        assert body["status"] in {"held_sender", "duplicate"}
        assert "/" not in body["attachment_name"] and "\\" not in body["attachment_name"]
        assert ".." not in body["attachment_name"]
        ids.append(body["id"])
    released = as_admin.post(f"/api/v1/tariffs/intake/{ids[0]}/release")
    assert released.status_code == 200, released.text

    intake_root = intake_dir.resolve()
    for path in tmp_path.rglob("*"):
        if path.is_file():
            resolved = path.resolve()
            inside = resolved.is_relative_to(intake_root)
            assert inside or resolved.name.startswith("test.db"), resolved
    for stray in ("x.xlsx", "y.xlsx", "z.xlsx", "evil.eml"):
        assert not (intake_dir.parent / stray).exists()
        assert not (intake_dir.parent.parent / stray).exists()
        assert not (Path.cwd() / stray).exists()


# --- The staff-directory sheet ----------------------------------------------------------------


def _text_columns(db) -> str:
    see_committed_changes(db)
    chunks = []
    for table in Base.metadata.sorted_tables:
        if not (
            table.name.startswith("tariff")
            or "intake" in table.name
            or table.name == "audit_events"
        ):
            continue
        columns = [c for c in table.columns if isinstance(c.type, String | Text)]
        if not columns:
            continue
        for row in db.execute(select(*columns)).all():
            chunks.extend(str(v) for v in row if v is not None)
    return "\n".join(chunks)


def test_a_ds_sdt_sheet_marker_reaches_no_response_db_column_or_derived_file(
    db, as_admin, users, intake_dir, tmp_path
):
    def add_directory(workbook):
        sheet = workbook.create_sheet("DS SDT test")
        sheet["A1"] = "STT"
        sheet["B2"] = "Demo Person"
        sheet["E2"] = MARKER

    book = workbook_copy(tmp_path, "with-directory.xlsx", add_directory)
    make_admin_approver(as_admin, users)
    responses = []
    imported = upload(as_admin, eml([("d.xlsx", book)]))
    responses.append(imported)
    version_id = imported.json()["tariff_version_id"]
    assert imported.json()["status"] == "imported", imported.text
    held_raw = eml(
        [
            (
                "d2.xlsx",
                workbook_copy(
                    tmp_path, "d2.xlsx", lambda wb: (add_directory(wb), wb.create_sheet("Notes"))
                ),
            )
        ],
        sender=STRANGER,
        message_id="<sdt-held@x.example.org>",
    )
    held = upload(as_admin, held_raw)
    responses.append(held)
    responses.append(as_admin.post(f"/api/v1/tariffs/intake/{held.json()['id']}/release"))
    for suffix in ("", "/diff", "/products", "/surcharges", "/zones", "/beyond-rates"):
        responses.append(as_admin.get(f"/api/v1/tariffs/versions/{version_id}{suffix}"))
    responses.append(as_admin.get(LISTING))
    responses.append(as_admin.get("/api/v1/tariffs/versions"))
    responses.append(as_admin.post(f"/api/v1/tariffs/versions/{version_id}/approve"))
    for response in responses:
        assert MARKER not in response.text, response.url
        assert BODY_MARKER not in response.text, response.url

    stored = _text_columns(db)
    assert MARKER not in stored and "Demo Person" not in stored
    assert BODY_MARKER not in stored

    # What the design keeps on disk: only the held workbook (later moved to
    # processed/released-intake-N.xlsx). Review fix 5 (DEC-0214): it is the workbook with the
    # staff-directory sheet stripped at the zip level, not the raw attachment.
    kept = sorted(
        p.relative_to(intake_dir).as_posix() for p in intake_dir.rglob("*") if p.is_file()
    )
    assert kept == [f"processed/released-intake-{held.json()['id']}.xlsx"]
    for path in intake_dir.rglob("*"):
        if path.is_file():
            data = path.read_bytes()
            assert MARKER.encode() not in data
            assert data != (tmp_path / "workbooks" / "d2.xlsx").read_bytes()  # stripped
            assert "DS SDT test" not in openpyxl.load_workbook(path, read_only=True).sheetnames


# --- The folder worker ------------------------------------------------------------------------


def test_the_folder_worker_moves_every_file_and_deletes_nothing(
    db, session_factory, as_admin, users, intake_dir, tmp_path
):
    make_admin_approver(as_admin, users)
    intake_dir.mkdir(parents=True, exist_ok=True)
    book = FIXTURE.read_bytes()
    files = {
        "a-good.eml": eml([("r.xlsx", book)], message_id="<w1@vendor.example.com>"),
        "b-held.eml": eml(
            [("r2.xlsx", workbook_copy(tmp_path, "w2.xlsx", lambda wb: wb.create_sheet("N")))],
            sender=STRANGER,
            message_id="<w2@x.example.org>",
        ),
        "c-dup.eml": eml([("r.xlsx", book)], message_id="<w3@vendor.example.com>"),
        "d-csv.eml": eml([("r.csv", b"a,b\n")], message_id="<w4@vendor.example.com>"),
        "e-none.eml": eml([], message_id="<w5@vendor.example.com>"),
        "f-garbage.eml": b"\x00\x01\x02",
    }
    for name, raw in files.items():
        (intake_dir / name).write_bytes(raw)
    (intake_dir / "readme.txt").write_text("left alone")

    outcomes = tariff_intake_worker.run_once(session_factory=session_factory)  # settings path

    assert dict(outcomes) == {
        "imported": 1,
        "held_sender": 1,
        "duplicate": 1,
        "rejected": 1,
        "no_attachment": 1,
        "failed": 1,
    }
    processed = sorted(p.name for p in (intake_dir / "processed").iterdir())
    failed = sorted(p.name for p in (intake_dir / "failed").iterdir())
    assert processed == ["a-good.eml", "b-held.eml", "c-dup.eml"]
    assert failed == ["d-csv.eml", "e-none.eml", "f-garbage.eml"]
    for name, raw in files.items():
        folder = "processed" if name in processed else "failed"
        assert (intake_dir / folder / name).read_bytes() == raw  # moved intact
    assert not list(intake_dir.glob("*.eml"))
    assert (intake_dir / "readme.txt").read_text() == "left alone"
    held_files = list((intake_dir / "held").iterdir())
    assert len(held_files) == 1

    see_committed_changes(db)
    rows = db.scalars(select(TariffEmailIntake)).all()
    assert {r.source for r in rows} == {"folder"} and len(rows) == 6
    assert all(v.status == "draft" for v in db.scalars(select(TariffVersion)))

    # A second run over an empty inbox changes nothing and deletes nothing.
    before = sorted(p.as_posix() for p in intake_dir.rglob("*"))
    assert dict(tariff_intake_worker.run_once(session_factory=session_factory)) == {}
    assert sorted(p.as_posix() for p in intake_dir.rglob("*")) == before
    listed = json.dumps(as_admin.get(LISTING).json())
    assert BODY_MARKER not in listed
