"""CSV customer import: hostile files, staging, duplicates, and idempotency.

Split into three concerns:

1. **The file is untrusted.** Bounds, encodings, archives, NUL bytes, quoting, headers.
2. **The workflow is staged.** A preview writes nothing; a commit needs the same file, an
   explicit confirmation, and its own permission.
3. **The result is honest.** Duplicates are never merged, existing values are never
   overwritten, a retry creates nothing new, and no imported value reaches a log or an
   audit payload.
"""

from __future__ import annotations

import gzip
import io
import json
import zipfile

import pytest
from sqlalchemy import func, select

from app.core.enums import Role
from app.core.permissions import ROLE_PERMISSIONS, Permission
from app.models import (
    AuditEvent,
    ConsentEvent,
    Customer,
    CustomerTag,
    ImportBatch,
    ImportBatchRow,
    Interaction,
    OrganizationSettings,
    Tag,
)
from app.services import csv_safety, customer_import_service
from tests.conftest import make_customer, see_committed_changes

TEMPLATE_PATH = "/api/v1/imports/customers/template.csv"
FIELDS_PATH = "/api/v1/imports/customers/fields"
PREVIEW_PATH = "/api/v1/imports/customers/preview"
COMMIT_PATH = "/api/v1/imports/customers/commit"

HEADER = "full_name,email,phone,country_code,city,preferred_language\r\n"

SIMPLE_CSV = (
    HEADER
    + "Nguyễn Thị Bích Hạnh,hanh@example.com,+1 416 555 0142,CA,Mississauga,vi\r\n"
    + "Trần Quốc Tuấn,tuan@example.com,+1 416 555 0143,CA,Toronto,vi\r\n"
).encode("utf-8")


@pytest.fixture
def org(db) -> OrganizationSettings:
    return db.scalar(select(OrganizationSettings))


def upload(content: bytes, name: str = "customers.csv") -> dict:
    return {"file": (name, io.BytesIO(content), "text/csv")}


def preview(api, content: bytes, name: str = "customers.csv"):
    return api.post(PREVIEW_PATH, files=upload(content, name))


def commit(api, content: bytes, digest: str, **form):
    data = {"content_sha256": digest, "confirm": "true", **form}
    return api.post(COMMIT_PATH, files=upload(content), data=data)


def preview_then_commit(api, content: bytes, **form):
    previewed = preview(api, content)
    assert previewed.status_code == 200, previewed.text
    digest = previewed.json()["content_sha256"]
    return previewed, commit(api, content, digest, **form)


# --- Permissions --------------------------------------------------------------


@pytest.mark.parametrize(
    ("path", "permission"),
    [
        (TEMPLATE_PATH, Permission.IMPORT_TEMPLATE),
        (FIELDS_PATH, Permission.IMPORT_PREVIEW),
    ],
)
@pytest.mark.parametrize("role", [Role.OPERATIONS, Role.MARKETING, Role.READ_ONLY_MANAGER])
def test_a_role_without_the_import_permission_is_refused(api_for, db, role, path, permission):
    api = api_for(role.value)
    assert permission not in ROLE_PERMISSIONS[role]
    assert api.get(path).status_code == 403


@pytest.mark.parametrize("role", [Role.OPERATIONS, Role.MARKETING, Role.READ_ONLY_MANAGER])
def test_a_role_without_import_preview_cannot_preview(api_for, db, role):
    api = api_for(role.value)
    assert preview(api, SIMPLE_CSV).status_code == 403


@pytest.mark.parametrize("role", [Role.OPERATIONS, Role.MARKETING, Role.READ_ONLY_MANAGER])
def test_a_role_without_import_commit_cannot_commit(api_for, db, role):
    api = api_for(role.value)
    response = api.post(
        COMMIT_PATH,
        files=upload(SIMPLE_CSV),
        data={"content_sha256": "x" * 64, "confirm": "true"},
    )
    assert response.status_code == 403
    # And nothing was written.
    assert db.scalar(select(func.count(Customer.id))) == 0


def test_an_unauthenticated_caller_reaches_no_import_endpoint(client):
    assert client.get(TEMPLATE_PATH).status_code == 401
    assert client.get(FIELDS_PATH).status_code == 401
    assert client.post(PREVIEW_PATH, files=upload(SIMPLE_CSV)).status_code == 401
    assert client.get("/api/v1/imports/batches").status_code == 401


def test_the_three_import_stages_are_separate_permissions():
    """A role could hold the template without the preview, or the preview without commit."""
    assert Permission.IMPORT_TEMPLATE != Permission.IMPORT_PREVIEW != Permission.IMPORT_COMMIT
    for permission in (
        Permission.IMPORT_TEMPLATE,
        Permission.IMPORT_PREVIEW,
        Permission.IMPORT_COMMIT,
    ):
        holders = [role for role, granted in ROLE_PERMISSIONS.items() if permission in granted]
        assert holders == [Role.ADMIN], f"{permission} held by {holders}"


# --- The template --------------------------------------------------------------


def test_the_template_is_synthetic_and_downloadable(as_admin, db):
    response = as_admin.get(TEMPLATE_PATH)
    assert response.status_code == 200
    assert "attachment" in response.headers["content-disposition"]
    body = response.text
    assert body.startswith("﻿")
    # Reserved domain and fictional numbers only: no real person is in the template.
    assert "@example.com" in body
    assert "555" in body
    assert "Nguyễn" in body


def test_the_template_round_trips_through_the_importer(as_admin, db):
    """A template that the importer rejects is worse than no template."""
    content = as_admin.get(TEMPLATE_PATH).content
    response = preview(as_admin, content, "template.csv")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["row_count"] == 2
    assert body["unmapped_headers"] == []
    assert all(row["classification"] == "new" for row in body["rows"])


def test_the_fields_endpoint_lists_only_the_documented_fields(as_admin, db):
    body = as_admin.get(FIELDS_PATH).json()
    fields = {item["field"] for item in body["fields"]}
    assert fields == set(customer_import_service.FIELD_SYNONYMS)
    # Consent is not among them, deliberately.
    assert not any("consent" in name for name in fields)
    assert any("Consent is never imported" in note for note in body["notes"])
    assert body["limits"]["max_rows"] == csv_safety.MAX_ROWS


# --- Hostile and malformed files ------------------------------------------------


def test_an_empty_file_is_refused(as_admin, db):
    response = preview(as_admin, b"")
    assert response.status_code == 422
    assert "empty" in response.json()["message"].lower()


def test_a_zip_archive_is_refused_by_its_bytes_not_its_name(as_admin, db):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("customers.csv", SIMPLE_CSV.decode("utf-8"))
    response = preview(as_admin, buffer.getvalue(), "customers.csv")
    assert response.status_code == 422
    assert "zip" in response.json()["message"].lower()


def test_a_gzip_file_is_refused(as_admin, db):
    response = preview(as_admin, gzip.compress(SIMPLE_CSV), "customers.csv")
    assert response.status_code == 422
    assert "gzip" in response.json()["message"].lower()


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        (b"%PDF-1.7\nnot a csv", "pdf"),
        (b"\x89PNG\r\n\x1a\nrest", "png"),
        (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1rest", "xls"),
        (b"SQLite format 3\x00rest", "sqlite"),
    ],
)
def test_a_binary_file_is_refused(as_admin, db, content, expected):
    response = preview(as_admin, content)
    assert response.status_code == 422
    assert expected in response.json()["message"].lower()


def test_a_nul_byte_anywhere_refuses_the_file(as_admin, db):
    content = HEADER.encode("utf-8") + b"Name,a@example.com,,CA,City,en\x00\r\n"
    response = preview(as_admin, content)
    assert response.status_code == 422
    assert "nul" in response.json()["message"].lower()


def test_a_utf16_file_is_refused_with_an_instruction(as_admin, db):
    response = preview(as_admin, SIMPLE_CSV.decode("utf-8").encode("utf-16"))
    assert response.status_code == 422
    message = response.json()["message"].lower()
    assert "utf-16" in message or "nul" in message
    assert "utf-8" in message


def test_a_latin1_file_is_refused_rather_than_silently_mangled(as_admin, db):
    content = (HEADER + "Café Owner,cafe@example.com,,CA,City,en\r\n").encode("latin-1")
    response = preview(as_admin, content)
    assert response.status_code == 422
    assert "utf-8" in response.json()["message"].lower()


def test_an_oversized_file_is_refused(as_admin, db):
    padding = "x" * 200
    rows = [
        f"Customer {index} {padding},c{index}@example.com,,CA,City,en" for index in range(20000)
    ]
    content = (HEADER + "\r\n".join(rows)).encode("utf-8")
    assert len(content) > csv_safety.MAX_FILE_BYTES
    response = preview(as_admin, content)
    assert response.status_code == 422
    assert "larger than" in response.json()["message"].lower()


def test_too_many_rows_is_refused_and_imports_nothing(as_admin, db):
    rows = [
        f"Person {index},p{index}@example.com,,CA,City,en"
        for index in range(csv_safety.MAX_ROWS + 5)
    ]
    content = (HEADER + "\r\n".join(rows)).encode("utf-8")
    response = preview(as_admin, content)
    assert response.status_code == 422
    assert "rows" in response.json()["message"].lower()
    assert db.scalar(select(func.count(Customer.id))) == 0


def test_too_many_columns_is_refused(as_admin, db):
    header = ",".join(f"col{index}" for index in range(csv_safety.MAX_COLUMNS + 1))
    content = (header + "\r\n" + ",".join("x" for _ in range(csv_safety.MAX_COLUMNS + 1))).encode()
    response = preview(as_admin, content)
    assert response.status_code == 422
    assert "columns" in response.json()["message"].lower()


def test_an_overlong_cell_is_refused(as_admin, db):
    long_value = "N" * (csv_safety.MAX_CELL_CHARS + 1)
    content = (HEADER + f"{long_value},a@example.com,,CA,City,en\r\n").encode("utf-8")
    response = preview(as_admin, content)
    assert response.status_code == 422
    assert "characters" in response.json()["message"].lower()


@pytest.mark.parametrize(
    "row",
    [
        # Data after a closing quote: the parser cannot tell where the field ends.
        '"Nguyen"extra,a@example.com,,CA,City,en',
        # A quote that is never closed: the file ends inside a field.
        '"Unclosed Name,a@example.com,,CA,City,en',
    ],
)
def test_malformed_quoting_fails_loudly_rather_than_shifting_columns(as_admin, db, row):
    """Lenient parsing would shift every subsequent column without saying so."""
    content = (HEADER + row + "\r\n").encode("utf-8")
    response = preview(as_admin, content)
    assert response.status_code == 422
    assert "quot" in response.json()["message"].lower()


def test_an_inch_mark_inside_an_unquoted_field_is_not_treated_as_malformed(as_admin, db):
    """Over-strict quote checking would reject legitimate files.

    A bare quote inside an unquoted field is unambiguous, and refusing it would fail an
    address like `Unit 5, 12" clearance`. Only genuinely ambiguous quoting is refused.
    """
    content = b'full_name,email,city\r\nA Person,a@example.com,Unit 5 12" clearance\r\n'
    response = preview(as_admin, content)
    assert response.status_code == 200, response.text
    assert response.json()["rows"][0]["values"]["city"] == 'Unit 5 12" clearance'


def test_a_row_with_more_values_than_headers_is_refused(as_admin, db):
    content = (HEADER + "Name,a@example.com,,CA,City,en,extra,more\r\n").encode("utf-8")
    response = preview(as_admin, content)
    assert response.status_code == 422
    assert "header" in response.json()["message"].lower()


def test_a_file_with_no_header_row_is_refused(as_admin, db):
    response = preview(as_admin, b"\r\n")
    assert response.status_code == 422


def test_a_file_whose_columns_match_nothing_is_refused(as_admin, db):
    content = b"alpha,beta,gamma\r\n1,2,3\r\n"
    response = preview(as_admin, content)
    assert response.status_code == 422
    assert "match a field" in response.json()["message"].lower()


def test_a_file_missing_the_required_column_is_refused(as_admin, db):
    content = b"email,phone\r\na@example.com,+1 416 555 0100\r\n"
    response = preview(as_admin, content)
    assert response.status_code == 422
    assert "full_name" in response.json()["message"]


# --- Headers ------------------------------------------------------------------


def test_two_headers_that_mean_the_same_field_are_refused_as_ambiguous(as_admin, db):
    content = b"full_name,Full Name,email\r\nA,B,a@example.com\r\n"
    response = preview(as_admin, content)
    assert response.status_code == 422
    message = response.json()["message"].lower()
    assert "same field" in message
    assert "unambiguous" in message


def test_headers_are_matched_regardless_of_case_spacing_and_punctuation(as_admin, db):
    content = (
        "  FULL-NAME , E-Mail ,Phone Number,Country\r\n"
        "Trần Quốc Tuấn,tuan@example.com,+1 416 555 0143,Canada\r\n"
    ).encode()
    response = preview(as_admin, content)
    assert response.status_code == 200, response.text
    row = response.json()["rows"][0]
    assert row["classification"] == "new"
    assert row["values"]["full_name"] == "Trần Quốc Tuấn"
    assert row["values"]["country_code"] == "CA"


def test_an_unrecognized_column_is_reported_and_its_values_dropped(as_admin, db):
    content = b"full_name,email,secret_internal_score\r\nA Person,a@example.com,99\r\n"
    response = preview(as_admin, content)
    assert response.status_code == 200
    body = response.json()
    assert body["unmapped_headers"] == ["secret_internal_score"]
    assert "99" not in json.dumps(body["rows"])
    assert any("not recognized" in note for note in body["notes"])


def test_a_vietnamese_header_matches_its_field(as_admin, db):
    content = "Họ và tên,Email\r\nLê Minh Khôi,khoi@example.com\r\n".encode()
    response = preview(as_admin, content)
    assert response.status_code == 200, response.text
    assert response.json()["rows"][0]["values"]["full_name"] == "Lê Minh Khôi"


# --- Preview writes nothing -----------------------------------------------------


def test_a_preview_creates_no_customer_data_whatsoever(as_admin, db):
    before = {
        model.__name__: db.scalar(select(func.count(model.id)))
        for model in (Customer, Tag, CustomerTag, ConsentEvent, Interaction, ImportBatch)
    }
    response = preview(as_admin, SIMPLE_CSV)
    assert response.status_code == 200
    after = {
        model.__name__: db.scalar(select(func.count(model.id)))
        for model in (Customer, Tag, CustomerTag, ConsentEvent, Interaction, ImportBatch)
    }
    assert before == after


def test_a_preview_says_plainly_that_nothing_was_imported(as_admin, db):
    body = preview(as_admin, SIMPLE_CSV).json()
    assert any("Nothing has been imported" in note for note in body["notes"])


def test_a_preview_classifies_new_rows(as_admin, db):
    body = preview(as_admin, SIMPLE_CSV).json()
    assert body["counts"]["new"] == 2
    assert body["counts"]["duplicate_review"] == 0
    assert [row["default_action"] for row in body["rows"]] == ["created", "created"]


def test_a_row_missing_a_name_or_contact_is_rejected_with_a_reason(as_admin, db):
    content = (
        HEADER
        + ",no.name@example.com,,CA,City,en\r\n"
        + "No Contact Person,,,CA,City,en\r\n"
        + "Bad Email,not-an-email,,CA,City,en\r\n"
    ).encode("utf-8")
    body = preview(as_admin, content).json()
    assert body["counts"]["rejected"] == 3
    codes = {issue["code"] for row in body["rows"] for issue in row["issues"]}
    assert {"missing_name", "missing_contact", "invalid_email"} <= codes


def test_an_unknown_enumerated_value_is_rejected_rather_than_defaulted(as_admin, db):
    content = (HEADER + "A Person,a@example.com,,CA,City,Klingon\r\n").encode("utf-8")
    body = preview(as_admin, content).json()
    row = body["rows"][0]
    assert row["classification"] == "rejected"
    issue = next(item for item in row["issues"] if item["field_name"] == "preferred_language")
    assert issue["code"] == "unknown_value"
    # The message names the accepted values so the operator can fix the file.
    assert "en" in issue["message"] and "vi" in issue["message"]


def test_a_friendly_language_spelling_is_accepted(as_admin, db):
    content = (HEADER + "A Person,a@example.com,,CA,City,Vietnamese\r\n").encode("utf-8")
    row = preview(as_admin, content).json()["rows"][0]
    assert row["classification"] == "new"
    assert row["values"]["preferred_language"] == "vi"


# --- Duplicates -----------------------------------------------------------------


def test_a_probable_duplicate_is_held_for_review_and_never_merged(as_admin, db):
    existing = make_customer(
        db, full_name="Nguyễn Thị Bích Hạnh", email="hanh@example.com", country_code="CA"
    )
    body = preview(as_admin, SIMPLE_CSV).json()

    duplicate_row = next(row for row in body["rows"] if row["classification"] == "duplicate_review")
    assert duplicate_row["default_action"] == "skipped"
    assert duplicate_row["duplicate_candidates"]
    assert duplicate_row["duplicate_candidates"][0]["public_id"] == existing.public_id
    assert any("merged automatically" in note for note in body["notes"])


def test_committing_without_a_decision_on_a_duplicate_is_refused_and_writes_nothing(as_admin, db):
    """UAT-XX-05: an undecided duplicate is not quietly skipped. The commit is refused."""
    make_customer(db, full_name="Nguyễn Thị Bích Hạnh", email="hanh@example.com", country_code="CA")
    before = db.scalar(select(func.count(Customer.id)))

    previewed, response = preview_then_commit(as_admin, SIMPLE_CSV)
    assert response.status_code == 422, response.text
    body = response.json()
    duplicate_row = next(
        row for row in previewed.json()["rows"] if row["classification"] == "duplicate_review"
    )
    assert "no decision" in body["message"]
    assert str(duplicate_row["row_number"]) in body["message"]

    see_committed_changes(db)
    assert db.scalar(select(func.count(Customer.id))) == before
    assert db.scalar(select(func.count(ImportBatch.id))) == 0
    assert (
        db.scalar(
            select(func.count(AuditEvent.id)).where(AuditEvent.action == "customer.import_commit")
        )
        == 0
    )


def test_a_decision_on_a_different_row_does_not_cover_the_duplicate(as_admin, db):
    make_customer(db, full_name="Nguyễn Thị Bích Hạnh", email="hanh@example.com", country_code="CA")
    previewed = preview(as_admin, SIMPLE_CSV).json()
    other_row = next(row for row in previewed["rows"] if row["classification"] == "new")

    response = commit(
        as_admin,
        SIMPLE_CSV,
        previewed["content_sha256"],
        decisions_json=json.dumps({str(other_row["row_number"]): "skip"}),
    )
    assert response.status_code == 422, response.text
    assert db.scalar(select(func.count(ImportBatch.id))) == 0


def test_an_explicit_skip_skips_the_duplicate_and_merges_nothing(as_admin, db):
    existing = make_customer(
        db, full_name="Nguyễn Thị Bích Hạnh", email="hanh@example.com", country_code="CA"
    )
    before = db.scalar(select(func.count(Customer.id)))
    previewed = preview(as_admin, SIMPLE_CSV).json()
    duplicate_row = next(
        row for row in previewed["rows"] if row["classification"] == "duplicate_review"
    )

    response = commit(
        as_admin,
        SIMPLE_CSV,
        previewed["content_sha256"],
        decisions_json=json.dumps({str(duplicate_row["row_number"]): "skip"}),
    )
    assert response.status_code == 200, response.text
    result = response.json()

    assert result["skipped"] == 1
    assert result["created"] == 1
    skipped = next(row for row in result["rows"] if row["outcome"] == "skipped")
    assert skipped["row_number"] == duplicate_row["row_number"]
    # The stored reason says somebody chose this, not that nobody looked.
    assert skipped["reason_code"] == "duplicate_skipped"

    see_committed_changes(db)
    assert db.scalar(select(func.count(Customer.id))) == before + 1
    # The existing record was not touched, merged, or archived.
    db.refresh(existing)
    assert existing.merged_into_customer_id is None
    assert existing.is_archived is False


def test_an_explicit_decision_creates_the_duplicate_as_a_separate_customer(as_admin, db):
    make_customer(db, full_name="Nguyễn Thị Bích Hạnh", email="hanh@example.com", country_code="CA")
    previewed = preview(as_admin, SIMPLE_CSV).json()
    duplicate_row = next(
        row for row in previewed["rows"] if row["classification"] == "duplicate_review"
    )

    response = commit(
        as_admin,
        SIMPLE_CSV,
        previewed["content_sha256"],
        decisions_json=json.dumps({str(duplicate_row["row_number"]): "create"}),
    )
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["created"] == 2
    assert result["skipped"] == 0
    created = next(
        row for row in result["rows"] if row["row_number"] == duplicate_row["row_number"]
    )
    assert created["reason_code"] == "created_after_review"


def test_an_unknown_decision_value_is_refused(as_admin, db):
    previewed = preview(as_admin, SIMPLE_CSV).json()
    response = commit(
        as_admin,
        SIMPLE_CSV,
        previewed["content_sha256"],
        decisions_json=json.dumps({"2": "merge"}),
    )
    assert response.status_code == 422
    assert "merge" in response.json()["message"]


def test_a_duplicate_inside_one_file_is_imported_once(as_admin, db):
    content = (
        HEADER
        + "Nguyễn Thị Bích Hạnh,hanh@example.com,+1 416 555 0142,CA,Mississauga,vi\r\n"
        + "Nguyễn Thị Bích Hạnh,hanh@example.com,+1 416 555 0142,CA,Mississauga,vi\r\n"
    ).encode("utf-8")
    _, response = preview_then_commit(as_admin, content)
    result = response.json()
    assert result["created"] == 1
    assert result["skipped"] == 1
    skipped = next(row for row in result["rows"] if row["outcome"] == "skipped")
    assert skipped["reason_code"] == "duplicate_within_file"


# --- Commit gating ---------------------------------------------------------------


def test_a_commit_without_confirmation_is_refused(as_admin, db):
    previewed = preview(as_admin, SIMPLE_CSV).json()
    response = as_admin.post(
        COMMIT_PATH,
        files=upload(SIMPLE_CSV),
        data={"content_sha256": previewed["content_sha256"], "confirm": "false"},
    )
    assert response.status_code == 422
    assert "confirm" in response.json()["message"].lower()
    assert db.scalar(select(func.count(Customer.id))) == 0


def test_a_commit_of_a_different_file_than_the_one_previewed_is_refused(as_admin, db):
    previewed = preview(as_admin, SIMPLE_CSV).json()
    tampered = SIMPLE_CSV + b"Sneaky Person,sneaky@example.com,,CA,City,en\r\n"

    response = commit(as_admin, tampered, previewed["content_sha256"])
    assert response.status_code == 409
    assert "previewed" in response.json()["message"].lower()
    assert db.scalar(select(func.count(Customer.id))) == 0


def test_an_unknown_conflict_policy_is_refused(as_admin, db):
    previewed = preview(as_admin, SIMPLE_CSV).json()
    response = commit(
        as_admin, SIMPLE_CSV, previewed["content_sha256"], conflict_policy="overwrite"
    )
    assert response.status_code == 422
    assert "conflict policy" in response.json()["message"].lower()
    # There is deliberately no overwrite policy.
    assert "overwrite" not in customer_import_service.CONFLICT_POLICIES


# --- Committing ------------------------------------------------------------------


def test_a_commit_creates_customers_through_the_service(as_admin, db):
    _, response = preview_then_commit(as_admin, SIMPLE_CSV)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["created"] == 2

    customers = db.scalars(select(Customer).order_by(Customer.id)).all()
    assert len(customers) == 2
    # Public IDs were allocated by the identifier service, exactly as for a typed record.
    assert [customer.public_id for customer in customers] == ["STCA-000001", "STCA-000002"]
    # Normalization ran: the accented name is intact and the phone was parsed.
    assert customers[0].full_name == "Nguyễn Thị Bích Hạnh"
    assert customers[0].phone_e164 == "+14165550142"
    assert customers[0].email_normalized == "hanh@example.com"
    assert customers[0].name_match_key is not None


def test_vietnamese_names_and_addresses_survive_the_round_trip(as_admin, db):
    content = (
        "full_name,email,city,province_state\r\n"
        "Đặng Thị Hồng Nhung,nhung@example.com,Thành phố Hồ Chí Minh,Hồ Chí Minh\r\n"
    ).encode()
    _, response = preview_then_commit(as_admin, content)
    assert response.status_code == 200, response.text

    customer = db.scalar(select(Customer))
    assert customer.full_name == "Đặng Thị Hồng Nhung"
    assert customer.city == "Thành phố Hồ Chí Minh"
    assert customer.province_state == "Hồ Chí Minh"


def test_a_commit_records_a_durable_batch_summary(as_admin, db):
    _, response = preview_then_commit(as_admin, SIMPLE_CSV)
    batch_id = response.json()["batch_public_id"]

    batch = db.scalar(select(ImportBatch).where(ImportBatch.public_id == batch_id))
    assert batch is not None
    assert batch.row_count == 2
    assert batch.created_count == 2
    assert batch.conflict_policy == "skip"
    assert len(batch.rows) == 2

    detail = as_admin.get(f"/api/v1/imports/batches/{batch_id}").json()
    assert detail["created_count"] == 2
    assert len(detail["rows"]) == 2
    assert {row["outcome"] for row in detail["rows"]} == {"created"}


def test_the_batch_record_holds_no_cell_value_from_the_file(as_admin, db):
    preview_then_commit(as_admin, SIMPLE_CSV)
    rows = db.scalars(select(ImportBatchRow)).all()
    blob = json.dumps(
        [
            {
                "outcome": row.outcome,
                "reason": row.reason_code,
                "source": row.source_record_id,
            }
            for row in rows
        ]
    )
    assert "Nguyễn" not in blob
    assert "hanh@example.com" not in blob
    assert "416" not in blob


def test_tags_are_imported_as_a_set(as_admin, db):
    content = b"full_name,email,tags\r\nTagged Person,tagged@example.com,family;vip;family\r\n"
    preview_then_commit(as_admin, content)

    customer = db.scalar(select(Customer))
    assert {link.tag.name for link in customer.tag_links} == {"family", "vip"}


def test_consent_is_never_created_by_an_import(as_admin, db):
    content = (
        b"full_name,email,email_consent_status\r\n"
        b"Consenting Person,consent@example.com,consented\r\n"
    )
    body = preview(as_admin, content).json()
    # The column is not even recognized.
    assert body["unmapped_headers"] == ["email_consent_status"]

    preview_then_commit(as_admin, content)
    assert db.scalar(select(func.count(ConsentEvent.id))) == 0


# --- Idempotency and retry --------------------------------------------------------


def test_importing_the_same_file_twice_creates_nothing_the_second_time(as_admin, db):
    _, first = preview_then_commit(as_admin, SIMPLE_CSV)
    assert first.json()["created"] == 2

    counts_after_first = {
        model.__name__: db.scalar(select(func.count(model.id)))
        for model in (Customer, Tag, CustomerTag, ConsentEvent, Interaction)
    }

    _, second = preview_then_commit(as_admin, SIMPLE_CSV)
    result = second.json()
    assert result["created"] == 0
    assert result["matched"] == 2
    assert all(row["reason_code"] == "already_imported" for row in result["rows"])

    db.expire_all()
    counts_after_second = {
        model.__name__: db.scalar(select(func.count(model.id)))
        for model in (Customer, Tag, CustomerTag, ConsentEvent, Interaction)
    }
    assert counts_after_first == counts_after_second


def test_a_retry_with_tags_does_not_duplicate_the_tag_links(as_admin, db):
    content = b"full_name,email,tags\r\nTagged Person,tagged@example.com,family;vip\r\n"
    preview_then_commit(as_admin, content)
    first = db.scalar(select(func.count(CustomerTag.id)))

    preview_then_commit(as_admin, content)
    db.expire_all()
    assert db.scalar(select(func.count(CustomerTag.id))) == first == 2


def test_a_preview_of_an_already_imported_file_reports_exact_matches(as_admin, db):
    preview_then_commit(as_admin, SIMPLE_CSV)
    body = preview(as_admin, SIMPLE_CSV).json()
    assert body["counts"]["exact_match"] == 2
    assert body["counts"]["new"] == 0
    assert all(row["matched_customer_public_id"] for row in body["rows"])
    assert any("already been imported" in note for note in body["notes"])


def test_the_source_key_from_the_file_is_used_when_supplied(as_admin, db):
    content = b"full_name,email,source_record_id\r\nKeyed Person,keyed@example.com,LEGACY-42\r\n"
    preview_then_commit(as_admin, content)

    customer = db.scalar(select(Customer))
    assert customer.source_record_id == "LEGACY-42"
    assert customer.source_system == "csv_import"

    # The same person, re-exported with a different spelling of the name but the same key,
    # is still the same record.
    changed = b"full_name,email,source_record_id\r\nKeyed  Person,keyed@example.com,LEGACY-42\r\n"
    _, response = preview_then_commit(as_admin, changed)
    assert response.json()["created"] == 0
    assert response.json()["matched"] == 1


def test_the_uniqueness_index_refuses_a_second_row_with_the_same_source_key(db, org):
    """The idempotency guarantee is enforced by the database, not only by a lookup."""
    from sqlalchemy.exc import IntegrityError

    db.add(
        Customer(
            public_id="STCA-900001",
            full_name="First",
            email_entered="one@example.com",
            email_normalized="one@example.com",
            source_system="csv_import",
            source_record_id="DUPKEY",
        )
    )
    db.commit()
    db.add(
        Customer(
            public_id="STCA-900002",
            full_name="Second",
            email_entered="two@example.com",
            email_normalized="two@example.com",
            source_system="csv_import",
            source_record_id="DUPKEY",
        )
    )
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_hand_created_customers_do_not_collide_on_the_partial_index(db, org):
    """Both carry NULL provenance, and the index must not treat that as a duplicate."""
    make_customer(db, full_name="Hand One", email="hand1@example.com")
    make_customer(db, full_name="Hand Two", email="hand2@example.com")
    assert db.scalar(select(func.count(Customer.id))) == 2


# --- Conflict policy ---------------------------------------------------------------


def test_the_default_policy_leaves_an_existing_record_untouched(as_admin, db):
    preview_then_commit(as_admin, SIMPLE_CSV)
    customer = db.scalar(select(Customer).where(Customer.email_normalized == "hanh@example.com"))
    customer.city = "Hand-edited city"
    db.commit()

    _, response = preview_then_commit(as_admin, SIMPLE_CSV)
    assert response.json()["matched"] == 2
    db.refresh(customer)
    assert customer.city == "Hand-edited city"


def test_fill_blanks_writes_only_where_the_field_is_empty(as_admin, db):
    sparse = "full_name,email,source_record_id\r\nSparse Person,sparse@example.com,S-1\r\n"
    preview_then_commit(as_admin, sparse.encode("utf-8"))
    customer = db.scalar(select(Customer))
    assert customer.city is None

    customer.province_state = "Kept by hand"
    db.commit()

    fuller = (
        b"full_name,email,source_record_id,city,province_state\r\n"
        b"Sparse Person,sparse@example.com,S-1,Mississauga,Overwritten\r\n"
    )
    _, response = preview_then_commit(as_admin, fuller, conflict_policy="fill_blanks")
    assert response.status_code == 200, response.text

    db.refresh(customer)
    # The empty field was filled...
    assert customer.city == "Mississauga"
    # ...and the non-empty one was not touched.
    assert customer.province_state == "Kept by hand"


def test_fill_blanks_audits_the_field_names_and_not_the_values(as_admin, db):
    sparse = "full_name,email,source_record_id\r\nSparse Person,sparse@example.com,S-1\r\n"
    preview_then_commit(as_admin, sparse.encode("utf-8"))
    fuller = (
        b"full_name,email,source_record_id,city\r\n"
        b"Sparse Person,sparse@example.com,S-1,Mississauga\r\n"
    )
    preview_then_commit(as_admin, fuller, conflict_policy="fill_blanks")

    event = db.scalar(
        select(AuditEvent)
        .where(AuditEvent.action == "customer.import_fill_blanks")
        .order_by(AuditEvent.id.desc())
    )
    assert event is not None
    assert json.loads(event.detail_json)["fields"] == ["city"]
    assert "Mississauga" not in (event.detail_json or "")


# --- Transaction behaviour ----------------------------------------------------------


def test_a_failure_partway_through_a_commit_leaves_nothing_behind(as_admin, db, monkeypatch):
    """All-or-nothing over the accepted rows (DEC-0079)."""
    content = (
        HEADER
        + "First Person,first@example.com,,CA,City,en\r\n"
        + "Second Person,second@example.com,,CA,City,en\r\n"
        + "Third Person,third@example.com,,CA,City,en\r\n"
    ).encode("utf-8")

    calls = {"count": 0}
    real_create = customer_import_service.customer_service.create_customer

    def exploding_create(*args, **kwargs):
        calls["count"] += 1
        if calls["count"] == 3:
            raise RuntimeError("database went away")
        return real_create(*args, **kwargs)

    monkeypatch.setattr(
        customer_import_service.customer_service, "create_customer", exploding_create
    )

    previewed = preview(as_admin, content).json()
    # The test client re-raises a server-side exception rather than turning it into a
    # 500, which is what makes the rollback observable here.
    with pytest.raises(RuntimeError, match="database went away"):
        commit(as_admin, content, previewed["content_sha256"])

    db.expire_all()
    # Not one, not two - none. And no batch record either.
    assert db.scalar(select(func.count(Customer.id))) == 0
    assert db.scalar(select(func.count(ImportBatch.id))) == 0
    assert db.scalar(select(func.count(ImportBatchRow.id))) == 0


def test_rejected_rows_do_not_prevent_the_valid_rows_from_committing(as_admin, db):
    """Validation decides membership; the transaction is atomic over the members."""
    content = (
        HEADER
        + "Good Person,good@example.com,,CA,City,en\r\n"
        + ",no.name@example.com,,CA,City,en\r\n"
        + "Another Good,another@example.com,,CA,City,en\r\n"
    ).encode("utf-8")
    _, response = preview_then_commit(as_admin, content)
    result = response.json()
    assert result["created"] == 2
    assert result["rejected"] == 1
    assert db.scalar(select(func.count(Customer.id))) == 2


# --- Audit and logging ---------------------------------------------------------------


def test_a_preview_is_audited_without_any_personal_data(as_admin, db):
    preview(as_admin, SIMPLE_CSV)
    event = db.scalar(select(AuditEvent).where(AuditEvent.action == "customer.import_preview"))
    assert event is not None
    detail = json.loads(event.detail_json)
    assert detail["row_count"] == 2
    assert detail["new"] == 2

    blob = f"{event.summary} {event.detail_json}"
    for secret in ("Nguyễn", "hanh@example.com", "416 555 0142", "Mississauga"):
        assert secret not in blob


def test_a_commit_is_audited_with_counts_and_the_conflict_choice(as_admin, db):
    preview_then_commit(as_admin, SIMPLE_CSV, conflict_policy="fill_blanks")
    event = db.scalar(select(AuditEvent).where(AuditEvent.action == "customer.import_commit"))
    assert event is not None
    detail = json.loads(event.detail_json)
    assert detail["created"] == 2
    assert detail["matched"] == 0
    assert detail["skipped"] == 0
    assert detail["rejected"] == 0
    assert detail["conflict_policy"] == "fill_blanks"
    assert "batch_public_id" in detail


def test_no_audit_entry_from_an_import_contains_a_cell_value(as_admin, db):
    make_customer(db, full_name="Nguyễn Thị Bích Hạnh", email="hanh@example.com")
    previewed = preview(as_admin, SIMPLE_CSV).json()
    duplicate_row = next(
        row for row in previewed["rows"] if row["classification"] == "duplicate_review"
    )
    commit(
        as_admin,
        SIMPLE_CSV,
        previewed["content_sha256"],
        decisions_json=json.dumps({str(duplicate_row["row_number"]): "create"}),
    )

    events = db.scalars(select(AuditEvent)).all()
    blob = " ".join(f"{event.summary} {event.detail_json or ''}" for event in events)
    for secret in ("hanh@example.com", "tuan@example.com", "+1 416 555 0142", "Mississauga"):
        assert secret not in blob


def test_no_imported_value_reaches_the_application_log(as_admin, db, caplog):
    import logging

    with caplog.at_level(logging.DEBUG):
        preview_then_commit(as_admin, SIMPLE_CSV)

    text = " ".join(record.getMessage() for record in caplog.records)
    for secret in ("Nguyễn", "hanh@example.com", "tuan@example.com", "555 0142"):
        assert secret not in text


def test_a_rejected_file_does_not_log_its_contents(as_admin, db, caplog):
    import logging

    hostile = (HEADER + "Secret Person,secret@example.com,,CA,City,en\x00\r\n").encode("utf-8")
    with caplog.at_level(logging.DEBUG):
        assert preview(as_admin, hostile).status_code == 422

    text = " ".join(record.getMessage() for record in caplog.records)
    assert "secret@example.com" not in text
    assert "Secret Person" not in text


# --- Batch history ------------------------------------------------------------------


def test_batch_history_lists_committed_imports_newest_first(as_admin, db):
    preview_then_commit(as_admin, SIMPLE_CSV)
    other = (HEADER + "Later Person,later@example.com,,CA,City,en\r\n").encode("utf-8")
    preview_then_commit(as_admin, other)

    body = as_admin.get("/api/v1/imports/batches").json()
    assert body["total"] == 2
    assert body["items"][0]["public_id"] == "IMP-000002"


def test_an_unknown_batch_is_a_404(as_admin, db):
    assert as_admin.get("/api/v1/imports/batches/IMP-999999").status_code == 404


def test_an_abandoned_preview_leaves_no_batch(as_admin, db):
    preview(as_admin, SIMPLE_CSV)
    assert as_admin.get("/api/v1/imports/batches").json()["total"] == 0


# --- Values are never interpreted -----------------------------------------------------


@pytest.mark.parametrize(
    "hostile",
    [
        "=cmd|'/c calc'!A1",
        "../../etc/passwd",
        "file:///etc/passwd",
        "https://evil.example/steal",
        "'; DROP TABLE customers; --",
        "<script>alert(1)</script>",
        "{{7*7}}",
    ],
)
def test_a_hostile_cell_value_is_stored_as_text_and_nothing_else(as_admin, db, hostile):
    content = (f'full_name,email,city\r\n"{hostile}",hostile@example.com,"{hostile}"\r\n').encode()
    _, response = preview_then_commit(as_admin, content)
    assert response.status_code == 200, response.text

    customer = db.scalar(select(Customer))
    # Stored verbatim: not evaluated, not fetched, not executed, and not stripped.
    assert customer.city == hostile
    assert hostile in customer.full_name
    # The customers table is still there, which is the point of the SQL case.
    assert db.scalar(select(func.count(Customer.id))) == 1


def test_the_importer_makes_no_outbound_request(as_admin, db, monkeypatch):
    """A URL in a cell is a string. Nothing follows it."""
    import socket

    def refuse(*args, **kwargs):
        raise AssertionError("the importer attempted a network connection")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)

    content = (
        b"full_name,email,notes\r\nURL Person,url@example.com,https://evil.example/callback\r\n"
    )
    _, response = preview_then_commit(as_admin, content)
    assert response.status_code == 200
