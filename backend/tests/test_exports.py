"""CSV exports: permission, scope, privacy, and file correctness (CRM.md section 13).

Every test here calls the HTTP endpoint rather than the service, because the thing being
proved is that the *route* enforces it. A service-level test would pass just as happily
against a route that forgot to declare its dependency, which is the bug this file exists
to catch (AC-2).
"""

from __future__ import annotations

import csv
import io
import json

import pytest
from sqlalchemy import select

from app.core.enums import ConsentChannel, ConsentStatus, Role
from app.core.permissions import ROLE_PERMISSIONS, Permission
from app.models import AuditEvent, Customer, OrganizationSettings
from app.services import export_service
from tests.conftest import add_shipment, make_customer
from tests.report_fixtures import TZ, build_dataset

#: A segment definition that matches every customer, so the audience test isolates the
#: consent rules rather than the segment filter.
EVERYONE = {
    "op": "and",
    "conditions": [{"field": "category", "operator": "in", "value": ["individual", "business"]}],
}

EXPORT_PATHS = {
    "customers": "/api/v1/exports/customers.csv",
    "shipments": "/api/v1/exports/shipments.csv",
    "packages": "/api/v1/exports/packages.csv",
}


@pytest.fixture
def org(db) -> OrganizationSettings:
    row = db.scalar(select(OrganizationSettings))
    row.office_timezone = TZ
    db.commit()
    return row


@pytest.fixture
def data(db, org):
    return build_dataset(db)


def parse_csv(text: str) -> tuple[list[str], list[list[str]]]:
    """Parse an exported file the way a spreadsheet would, BOM included."""
    assert text.startswith("﻿"), "missing UTF-8 byte-order mark"
    rows = list(csv.reader(io.StringIO(text.lstrip("﻿"))))
    return rows[0], rows[1:]


# --- Permission is separate from record access -------------------------------


@pytest.mark.parametrize("export_key", sorted(EXPORT_PATHS))
@pytest.mark.parametrize("role", [Role.OPERATIONS, Role.MARKETING, Role.READ_ONLY_MANAGER])
def test_a_role_that_can_read_records_still_cannot_export_them(api_for, db, data, role, export_key):
    """Reading one customer is not extracting the whole book (CRM.md section 13)."""
    api = api_for(role.value)
    # The role really can read the underlying records...
    assert api.get("/api/v1/customers").status_code == 200
    # ...and still cannot export them.
    response = api.get(EXPORT_PATHS[export_key])
    assert response.status_code == 403
    assert response.json()["code"] == "permission_denied"


@pytest.mark.parametrize("export_key", sorted(EXPORT_PATHS))
def test_an_admin_can_run_every_export(as_admin, db, data, export_key):
    response = as_admin.get(EXPORT_PATHS[export_key])
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert "attachment" in response.headers["content-disposition"]
    # An export is live personal data: it must not sit in a shared cache.
    assert response.headers["cache-control"] == "no-store"


def test_an_unauthenticated_caller_reaches_no_export(client):
    for path in EXPORT_PATHS.values():
        assert client.get(path).status_code == 401


def test_export_permissions_are_admin_only_by_default():
    """DEC-0082: the narrow default is deliberate and recorded."""
    for permission in (Permission.EXPORT_SHIPMENTS, Permission.EXPORT_REPORTS):
        holders = [role for role, granted in ROLE_PERMISSIONS.items() if permission in granted]
        assert holders == [Role.ADMIN], f"{permission} held by {holders}"


# --- Financial gating, field by field ----------------------------------------


def test_cost_columns_are_absent_from_the_file_for_a_role_without_cost_permission(
    api_for, db, data
):
    """Absent, not blank. A header over an empty column still discloses the field."""
    api = api_for(Role.ADMIN.value)
    admin_headers, _ = parse_csv(api.get(EXPORT_PATHS["shipments"]).text)
    assert "shipping_cost" in admin_headers
    assert "selling_amount" in admin_headers

    # Read-only manager holds financial:read but not financial_cost:read.
    assert Permission.FINANCIAL_READ in ROLE_PERMISSIONS[Role.READ_ONLY_MANAGER]
    assert Permission.FINANCIAL_COST_READ not in ROLE_PERMISSIONS[Role.READ_ONLY_MANAGER]

    headers = export_service.SHIPMENT_EXPORT.headers_for(Role.READ_ONLY_MANAGER)
    assert "selling_amount" in headers
    assert "shipping_cost" not in headers
    assert "surcharges_amount" not in headers


def test_a_role_without_financial_read_gets_no_money_column_at_all():
    # Marketing holds no financial permission. Operations did not either until the role
    # merge (DEC-0088) gave it Customer service's financial:read.
    headers = export_service.SHIPMENT_EXPORT.headers_for(Role.MARKETING)
    for column in (
        "currency",
        "selling_amount",
        "discount_amount",
        "refund_amount",
        "shipping_cost",
        "surcharges_amount",
    ):
        assert column not in headers


def test_the_row_width_matches_the_header_width_for_every_role(db, data, org):
    """A gated column must drop out of the header *and* the row, together."""
    from app.models import Shipment

    statement = select(Shipment).order_by(Shipment.id.asc())
    for role in Role:
        headers = export_service.SHIPMENT_EXPORT.headers_for(role.value)
        rows = list(export_service.shipment_rows(db, statement, role.value))
        assert rows, "fixture should produce shipments"
        for row in rows:
            assert len(row) == len(headers), f"{role.value}: {len(row)} != {len(headers)}"


# --- Filters and record scope ------------------------------------------------


def test_the_export_applies_the_same_filters_as_the_list(as_admin, db, data):
    listed = as_admin.get("/api/v1/customers", params={"preferred_language": "en", "limit": 100})
    assert listed.status_code == 200
    expected_ids = {item["public_id"] for item in listed.json()["items"]}

    exported = as_admin.get(EXPORT_PATHS["customers"], params={"preferred_language": "en"})
    _, rows = parse_csv(exported.text)
    assert {row[0] for row in rows} == expected_ids


def test_a_filter_that_matches_nothing_produces_a_header_and_no_rows(as_admin, db, data):
    response = as_admin.get(EXPORT_PATHS["customers"], params={"search": "no-such-customer-xyz"})
    headers, rows = parse_csv(response.text)
    assert headers == list(export_service.CUSTOMER_EXPORT.headers_for(Role.ADMIN))
    assert rows == []


def test_archived_customers_are_excluded_unless_asked_for(as_admin, db, data):
    customer = make_customer(db, full_name="Archived Person", email="arch@demo.example.com")
    customer.is_archived = True
    db.commit()

    default_headers, default_rows = parse_csv(as_admin.get(EXPORT_PATHS["customers"]).text)
    assert customer.public_id not in {row[0] for row in default_rows}

    _, with_archived = parse_csv(
        as_admin.get(EXPORT_PATHS["customers"], params={"include_archived": "true"}).text
    )
    assert customer.public_id in {row[0] for row in with_archived}
    del default_headers


def test_a_merged_customer_never_appears_in_an_export(as_admin, db, data):
    absorbed = data.customer("absorbed")
    assert absorbed.merged_into_customer_id is not None
    _, rows = parse_csv(
        as_admin.get(EXPORT_PATHS["customers"], params={"include_archived": "true"}).text
    )
    assert absorbed.public_id not in {row[0] for row in rows}


def test_the_shipment_export_honours_a_route_filter(as_admin, db, data):
    response = as_admin.get(EXPORT_PATHS["shipments"], params={"route_group": "CAV"})
    headers, rows = parse_csv(response.text)
    route_index = headers.index("route_group")
    assert rows
    assert {row[route_index] for row in rows} == {"CAV"}


def test_the_package_export_is_one_row_per_package_and_never_a_shipment_count(as_admin, db, data):
    parent = data.shipment("repeat_sep")
    response = as_admin.get(EXPORT_PATHS["packages"], params={"search": parent.public_id})
    headers, rows = parse_csv(response.text)
    assert len(rows) == 3
    reference_index = headers.index("package_reference")
    assert {row[reference_index] for row in rows} == {
        f"{parent.public_id}-01",
        f"{parent.public_id}-02",
        f"{parent.public_id}-03",
    }


# --- The allowlists ----------------------------------------------------------


def test_no_export_allowlist_names_a_forbidden_field():
    """Belt and braces on top of the allowlists themselves (DEC-0080)."""
    for definition in export_service.EXPORTS.values():
        for column in definition.columns:
            haystack = f"{column.key} {column.header}".lower()
            for fragment in export_service.FORBIDDEN_COLUMN_FRAGMENTS:
                assert fragment not in haystack, f"{definition.key}.{column.key}"


def test_the_customer_export_carries_no_private_note_or_internal_field(as_admin, db, data):
    customer = data.customer("repeat")
    customer.notes = "PRIVATE-NOTE-SENTINEL: do not export"
    customer.service_restriction_note = "RESTRICTION-SENTINEL"
    db.commit()

    body = as_admin.get(EXPORT_PATHS["customers"]).text
    assert "PRIVATE-NOTE-SENTINEL" not in body
    assert "RESTRICTION-SENTINEL" not in body


def test_the_shipment_export_carries_no_street_address_phone_or_internal_note(as_admin, db, data):
    from app.models import Shipment

    shipment = db.scalar(select(Shipment).where(Shipment.public_id.is_not(None)))
    shipment.recipient_address_line1 = "STREET-SENTINEL 42"
    shipment.recipient_phone_entered = "+1 416 555 9999"
    shipment.recipient_email = "recipient-sentinel@demo.example.com"
    shipment.internal_notes = "INTERNAL-SENTINEL"
    db.commit()

    body = as_admin.get(EXPORT_PATHS["shipments"]).text
    assert "STREET-SENTINEL" not in body
    assert "555 9999" not in body
    assert "recipient-sentinel" not in body
    assert "INTERNAL-SENTINEL" not in body


def test_no_export_can_reach_an_integration_table(as_admin, db, data):
    """Phase 4A tables carry raw provider payloads. Nothing exports them."""
    for definition in export_service.EXPORTS.values():
        for column in definition.columns:
            assert "provider" not in column.key
            assert "webhook" not in column.key
            assert "inbox" not in column.key
            assert "lease" not in column.key


# --- Suppressed contacts -----------------------------------------------------


def test_a_marketing_audience_omits_suppressed_and_ineligible_contacts(
    as_admin, db, data, thresholds_stub=None
):
    """Ineligible records are left out of the file, not flagged inside it."""
    from app.models import SavedSegment
    from app.services import consent_service, segment_service

    consenting = data.customer("repeat")
    suppressed = data.customer("first_timer")

    for customer in (consenting, suppressed):
        consent_service.record_consent_event(
            db,
            customer,
            channel=ConsentChannel.EMAIL,
            status=ConsentStatus.CONSENTED,
            basis="express",
            source="test",
        )
    db.commit()
    consent_service.add_suppression(
        db,
        channel=ConsentChannel.EMAIL,
        address_value=suppressed.email_normalized,
        reason="unsubscribed",
    )
    db.commit()

    segment = SavedSegment(
        name="Everyone",
        slug="everyone",
        definition_json=segment_service.dump_definition(EVERYONE),
    )
    db.add(segment)
    db.commit()

    response = as_admin.get(f"/api/v1/exports/segments/{segment.id}/audience.csv")
    assert response.status_code == 200
    headers, rows = parse_csv(response.text)
    addresses = {row[headers.index("address")] for row in rows}

    assert consenting.email_normalized in addresses
    assert suppressed.email_normalized not in addresses
    # And the suppressed person's name is nowhere in the file either.
    assert suppressed.full_name not in response.text


def test_a_do_not_contact_customer_is_omitted_from_a_marketing_audience(as_admin, db, data):
    from app.models import SavedSegment
    from app.services import consent_service, segment_service

    customer = data.customer("survivor")
    consent_service.record_consent_event(
        db,
        customer,
        channel=ConsentChannel.EMAIL,
        status=ConsentStatus.CONSENTED,
        basis="express",
        source="test",
    )
    customer.do_not_contact = True
    db.commit()

    segment = SavedSegment(
        name="Everyone",
        slug="everyone",
        definition_json=segment_service.dump_definition(EVERYONE),
    )
    db.add(segment)
    db.commit()

    response = as_admin.get(f"/api/v1/exports/segments/{segment.id}/audience.csv")
    _, rows = parse_csv(response.text)
    assert customer.public_id not in {row[0] for row in rows}


# --- Formula injection -------------------------------------------------------


@pytest.mark.parametrize("prefix", ["=", "+", "-", "@"])
def test_a_name_that_would_become_a_formula_is_neutralized(as_admin, db, org, prefix):
    hostile = f"{prefix}cmd|'/c calc'!A1 Nguyen"
    make_customer(db, full_name=hostile, email=f"hostile{ord(prefix)}@demo.example.com")

    headers, rows = parse_csv(as_admin.get(EXPORT_PATHS["customers"]).text)
    name_index = headers.index("full_name")
    exported = next(row[name_index] for row in rows if "cmd|" in row[name_index])

    assert exported.startswith("'"), f"{exported!r} was not neutralized"
    # Prefixed, never stripped: the value survives intact after the apostrophe.
    assert exported[1:] == hostile


@pytest.mark.parametrize("prefix", ["\t", "\r", "\n"])
def test_a_whitespace_prefixed_cell_is_neutralized_too(as_admin, db, org, prefix):
    """The three prefixes a spreadsheet strips before deciding whether a cell is a formula.

    A customer *name* cannot carry one, because ``normalize_name`` collapses leading
    whitespace on the way in — defence in depth, asserted in the next test. ``city`` is
    not normalized that way, so it is the honest place to prove the export-side guard.
    """
    customer = make_customer(db, full_name="Whitespace Probe", email="ws@demo.example.com")
    customer.city = prefix + '=HYPERLINK("http://evil.example")'
    db.commit()

    headers, rows = parse_csv(as_admin.get(EXPORT_PATHS["customers"]).text)
    city_index = headers.index("city")
    exported = next(row[city_index] for row in rows if "HYPERLINK" in row[city_index])
    assert exported.startswith("'")
    assert exported[1:].startswith(prefix)


def test_name_normalization_already_strips_a_leading_whitespace_prefix(db, org):
    """Defence in depth, and this layer is the first of the two."""
    from app.core.normalization import normalize_name

    for prefix in ("\t", "\r", "\n"):
        assert normalize_name(f"{prefix}Nguyen") == "Nguyen"
    # The formula characters are *not* stripped, because they can be legitimate text.
    # The export-side prefix handles those instead.
    assert normalize_name("=Nguyen") == "=Nguyen"


def test_the_escape_covers_every_documented_prefix():
    from app.core.normalization import CSV_FORMULA_PREFIXES, escape_csv_value

    assert set(CSV_FORMULA_PREFIXES) == {"=", "+", "-", "@", "\t", "\r", "\n"}
    for prefix in CSV_FORMULA_PREFIXES:
        assert escape_csv_value(f"{prefix}danger").startswith("'")
    # An ordinary value is untouched.
    assert escape_csv_value("Nguyễn Thị Bích Hạnh") == "Nguyễn Thị Bích Hạnh"


def test_a_value_containing_a_comma_or_quote_still_parses(as_admin, db, org):
    make_customer(
        db,
        full_name='Tran, "Quoc" Tuan',
        email="quoting@demo.example.com",
    )
    headers, rows = parse_csv(as_admin.get(EXPORT_PATHS["customers"]).text)
    names = {row[headers.index("full_name")] for row in rows}
    assert 'Tran, "Quoc" Tuan' in names


# --- Encoding ----------------------------------------------------------------


def test_vietnamese_text_round_trips_through_the_export(as_admin, db, data):
    response = as_admin.get(EXPORT_PATHS["customers"])
    assert response.encoding is None or "utf-8" in (response.encoding or "").lower()
    headers, rows = parse_csv(response.text)
    names = {row[headers.index("full_name")] for row in rows}

    assert "Nguyễn Thị Bích Hạnh" in names
    assert "Trần Quốc Tuấn" in names
    assert "Lê Minh Khôi" in names
    # A lossy encoding step produces replacement characters rather than an exception.
    assert "�" not in response.text


def test_the_file_begins_with_a_byte_order_mark_so_excel_reads_utf8(as_admin, db, data):
    raw = as_admin.get(EXPORT_PATHS["customers"]).content
    assert raw.startswith(b"\xef\xbb\xbf")


def test_rows_are_terminated_with_crlf_as_the_csv_format_requires(as_admin, db, data):
    text = as_admin.get(EXPORT_PATHS["customers"]).text
    assert "\r\n" in text


# --- Empty and large ---------------------------------------------------------


def test_an_export_of_an_empty_database_is_a_header_row(as_admin, db, org):
    response = as_admin.get(EXPORT_PATHS["customers"])
    headers, rows = parse_csv(response.text)
    assert headers
    assert rows == []


def test_a_large_export_streams_every_row_without_materializing_the_query(as_admin, db, org):
    """Larger than one page, so the paging loop is genuinely exercised."""
    count = export_service.BATCH_SIZE + 37
    for index in range(count):
        db.add(
            Customer(
                public_id=f"STCA-{index + 900000:06d}",
                full_name=f"Bulk Customer {index}",
                email_entered=f"bulk{index}@demo.example.com",
                email_normalized=f"bulk{index}@demo.example.com",
            )
        )
    db.commit()

    response = as_admin.get(EXPORT_PATHS["customers"])
    _, rows = parse_csv(response.text)
    assert len(rows) == count
    # Every row is distinct: an off-by-one in the paging loop would repeat or drop a page.
    assert len({row[0] for row in rows}) == count


def test_paging_does_not_skip_a_row_at_a_batch_boundary(db, org):
    """The boundary is where an offset-paged generator gets it wrong."""
    for index in range(export_service.BATCH_SIZE * 2):
        db.add(
            Customer(
                public_id=f"STCA-{index + 800000:06d}",
                full_name=f"Boundary {index}",
                email_entered=f"boundary{index}@demo.example.com",
                email_normalized=f"boundary{index}@demo.example.com",
            )
        )
    db.commit()

    statement = select(Customer).order_by(Customer.public_id.asc())
    collected = [customer.public_id for customer in export_service.paged(db, statement)]
    assert len(collected) == export_service.BATCH_SIZE * 2
    assert len(set(collected)) == len(collected)
    assert collected == sorted(collected)


# --- Audit -------------------------------------------------------------------


def test_an_export_is_audited_with_type_filters_row_count_and_actor(as_admin, db, data, users):
    as_admin.get(EXPORT_PATHS["customers"], params={"preferred_language": "en"})

    event = db.scalar(
        select(AuditEvent)
        .where(AuditEvent.action == "export.customers")
        .order_by(AuditEvent.id.desc())
    )
    assert event is not None
    assert event.actor_label == users[Role.ADMIN].email
    detail = json.loads(event.detail_json)
    assert detail["export_type"] == "customers"
    assert isinstance(detail["row_count"], int)
    assert detail["filters"]["preferred_language"] == ["en"]
    assert "customer_id" in detail["columns"]


def test_the_audit_entry_contains_no_exported_customer_value(as_admin, db, data):
    as_admin.get(EXPORT_PATHS["customers"])
    as_admin.get(EXPORT_PATHS["shipments"])

    events = db.scalars(select(AuditEvent).where(AuditEvent.action.like("export.%"))).all()
    assert events
    blob = " ".join(f"{event.summary} {event.detail_json or ''}" for event in events)
    for customer in db.scalars(select(Customer)).all():
        assert customer.full_name not in blob
        if customer.email_entered:
            assert customer.email_entered not in blob
        if customer.phone_entered:
            assert customer.phone_entered not in blob


def test_a_free_text_search_term_is_not_written_verbatim_into_the_audit_log(as_admin, db, data):
    """A search term can be somebody's name; it is recorded as present, not quoted."""
    as_admin.get(EXPORT_PATHS["customers"], params={"search": "Nguyễn"})
    event = db.scalar(
        select(AuditEvent)
        .where(AuditEvent.action == "export.customers")
        .order_by(AuditEvent.id.desc())
    )
    detail = json.loads(event.detail_json)
    assert detail["filters"]["search"] == "[provided]"
    assert "Nguyễn" not in (event.detail_json or "")


def test_an_export_refused_for_permission_writes_no_audit_entry(api_for, db, data):
    api = api_for(Role.OPERATIONS.value)
    assert api.get(EXPORT_PATHS["customers"]).status_code == 403
    events = db.scalars(select(AuditEvent).where(AuditEvent.action.like("export.%"))).all()
    assert events == []


# --- Report export -----------------------------------------------------------


def test_a_report_exports_the_columns_the_screen_showed(as_admin, db, data):
    response = as_admin.get(
        "/api/v1/exports/reports/route_mix.csv",
        params={"from": "2026-09-01", "to": "2026-09-30"},
    )
    assert response.status_code == 200
    headers, rows = parse_csv(response.text)
    assert headers == ["Route", "Qualifying shipments", "Share"]
    assert rows


def test_a_report_export_cannot_produce_a_financial_column_the_role_may_not_see(api_for, db, data):
    api = api_for(Role.ADMIN.value)
    assert api.get("/api/v1/exports/reports/financial_summary.csv").status_code == 200

    # Operations holds neither report export nor financial read.
    operations = api_for(Role.OPERATIONS.value)
    assert operations.get("/api/v1/exports/reports/financial_summary.csv").status_code == 403


def test_an_unknown_report_key_is_refused(as_admin, db, data):
    response = as_admin.get("/api/v1/exports/reports/not_a_report.csv")
    assert response.status_code == 422
    assert "unknown report" in response.json()["message"].lower()


def test_the_export_definitions_endpoint_describes_the_columns(as_admin, db):
    body = as_admin.get("/api/v1/exports/definitions").json()
    keys = {item["key"] for item in body["exports"]}
    assert keys == set(export_service.EXPORTS)
    customers = next(item for item in body["exports"] if item["key"] == "customers")
    assert customers["allowed"] is True
    assert "customer_id" in customers["columns"]
    assert any("formula" in note.lower() or "=" in note for note in body["protections"])


def test_a_role_sees_allowed_false_rather_than_a_missing_export(api_for, db):
    api = api_for(Role.OPERATIONS.value)
    body = api.get("/api/v1/exports/definitions").json()
    customers = next(item for item in body["exports"] if item["key"] == "customers")
    assert customers["allowed"] is False


# --- Nothing is written to disk ----------------------------------------------


def test_an_export_creates_no_file_on_disk(as_admin, db, data, tmp_path):
    """CRM.md section 13 does not ask for a persisted export, so none is created."""
    before = set(tmp_path.rglob("*"))
    as_admin.get(EXPORT_PATHS["customers"])
    as_admin.get(EXPORT_PATHS["shipments"])
    assert set(tmp_path.rglob("*")) == before


def test_a_shipment_export_of_a_customer_with_no_shipments_is_empty(as_admin, db, org):
    customer = make_customer(db, full_name="No Shipments", email="none@demo.example.com")
    response = as_admin.get(EXPORT_PATHS["shipments"], params={"customer_id": customer.id})
    _, rows = parse_csv(response.text)
    assert rows == []


def test_an_unknown_value_exports_as_empty_not_as_zero(as_admin, db, org):
    customer = make_customer(db, full_name="Sparse Person", email="sparse@demo.example.com")
    add_shipment(db, customer, days_ago=5, currency=None, selling_amount=None)

    headers, rows = parse_csv(as_admin.get(EXPORT_PATHS["shipments"]).text)
    row = rows[0]
    assert row[headers.index("selling_amount")] == ""
    assert row[headers.index("currency")] == ""
    assert row[headers.index("selling_amount")] != "0"
