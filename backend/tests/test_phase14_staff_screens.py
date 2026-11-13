"""Phase 14: the two backend additions behind the new staff screens.

1. ``GET /shipments/{id}/quotes/{version}/document`` -- the printable customer quote for a
   finalised version: the company's details (OD-64), the customer, the Solaris service and
   the customer's charges before tax. Revenue only: no vendor cost, exchange rate, markup,
   margin, vendor name, product code or tariff version. Same permissions as reading a quote.
2. ``review_decision`` on tariff versions, so the tariff browser can say that a draft was
   rejected by the approver (it stays ``draft`` and can never be activated, 13H).

Test data only (the sanitized fixture workbook and demo addresses).
"""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal

from app.core.enums import Role
from app.services import pricing_service as ps
from app.services import shipment_item_service as items
from app.services import tariff_import_service as tis
from app.services import tariff_intake_service
from tests.test_quote_offers import FORBIDDEN
from tests.test_quotes import WORKBOOK, priced_world  # noqa: F401 - fixture


def _finalize_with_fee(db, shipment):
    item = items.add_item(db, shipment, {"description": "Watch"}, actor=None)
    ps.add_fee_line(
        db,
        shipment,
        {"item_id": item.id, "section": "hcm_air", "stt": 18, "quantity": 1},
        actor=None,
    )
    ps.reprice(db, shipment, actor=None)
    ps.confirm_rate(db, shipment, rate=None, reason=None, actor=None)
    version = ps.finalize(db, shipment, negative_margin_reason="test", actor=None)
    db.commit()
    return version


# --- The printable quote -------------------------------------------------------------------


def test_quote_document_is_revenue_only_with_company_details(api_for, db, priced_world):  # noqa: F811
    _con, kids = priced_world
    shipment = kids[2]
    version = _finalize_with_fee(db, shipment)
    ops = api_for(Role.OPERATIONS)

    response = ops.get(f"/api/v1/shipments/{shipment.id}/quotes/{version.version}/document")
    assert response.status_code == 200, response.text
    body = response.json()
    # DEC-0235 (owner Ben, 2026-10-24) -- AS-43 in SUPERSEDED_ASSERTIONS.md: the Solaris
    # Invoicing desk's company details.
    assert body["company_name"] == "Solaris Express Inc."
    assert body["company_business_number"] == "795093756RT0001"
    assert body["company_address"] == "2446 Cawthra Rd Building 1 Unit 8, Mississauga ON L5A 3K6"
    assert body["company_email"] == "solarisexpressinc@gmail.com"
    assert body["service"] == "Air Standard"
    assert body["currency"] == "CAD" and body["tax_included"] is False
    assert body["shipment_reference"] == shipment.public_id
    assert body["version"] == version.version
    assert body["customer_name"] == "Test Customer"
    total = Decimal(body["base_charge_cad"]) + sum(
        Decimal(s["amount_cad"]) for s in body["surcharges"]
    )
    assert Decimal(body["total_cad"]) == total == version.total_revenue_cad
    assert body["surcharges"], "the watch surcharge is billed to the customer"

    # The exact allowlist, and no cost word anywhere in the payload's keys.
    assert set(body) == {
        "company_name",
        "company_trade_name",
        "company_business_number",
        "company_address",
        # DEC-0235 -- AS-43 in SUPERSEDED_ASSERTIONS.md.
        "company_email",
        "customer_name",
        "customer_reference",
        "shipment_reference",
        "version",
        "finalized_at",
        "service",
        "billable_weight_kg",
        "rate_per_kg_cad",
        "base_charge_cad",
        "surcharges",
        "total_cad",
        "currency",
        "tax_included",
        "status",
        "superseded_by_version",
        # RC-UAT-21 (P-9 stand-in): the GST/HST wording -- AS-41 in SUPERSEDED_ASSERTIONS.md.
        "tax",
    }
    assert body["status"] == "finalized" and body["superseded_by_version"] is None
    keys = json.dumps(sorted(body)).lower()
    for word in FORBIDDEN:
        assert word not in keys, word
    values = json.dumps(
        {k: v for k, v in body.items() if k not in {"surcharges", "customer_name"}}
    ).lower()
    for word in ("kango", "air-cad", "tariff", "markup", "cash_buy"):
        assert word not in values, word


def test_quote_document_refuses_a_draft_and_an_unknown_version(api_for, db, priced_world):  # noqa: F811
    _con, kids = priced_world
    shipment = kids[1]
    ps.reprice(db, shipment, actor=None)
    db.commit()
    ops = api_for(Role.OPERATIONS)
    assert ops.get(f"/api/v1/shipments/{shipment.id}/quotes/1/document").status_code == 409
    assert ops.get(f"/api/v1/shipments/{shipment.id}/quotes/9/document").status_code == 404
    assert ops.get("/api/v1/shipments/999999/quotes/1/document").status_code == 404


def test_quote_document_needs_quote_read_permissions(api_for, db, priced_world):  # noqa: F811
    _con, kids = priced_world
    shipment = kids[0]
    version = _finalize_with_fee(db, shipment)
    url = f"/api/v1/shipments/{shipment.id}/quotes/{version.version}/document"
    assert api_for(Role.ADMIN).get(url).status_code == 200
    for role in (Role.MARKETING, Role.READ_ONLY_MANAGER):
        assert api_for(role).get(url).status_code == 403, role


def test_a_superseded_version_stays_printable_and_says_by_which(api_for, db, priced_world):  # noqa: F811
    _con, kids = priced_world
    shipment = kids[2]
    first = _finalize_with_fee(db, shipment)
    ps.reprice(db, shipment, actor=None)
    ps.confirm_rate(db, shipment, rate="19", reason="Review fix test", actor=None)
    second = ps.finalize(db, shipment, negative_margin_reason="test", actor=None)
    db.commit()
    ops = api_for(Role.OPERATIONS)
    old = ops.get(f"/api/v1/shipments/{shipment.id}/quotes/{first.version}/document")
    assert old.status_code == 200, old.text
    assert old.json()["status"] == "superseded"
    assert old.json()["superseded_by_version"] == second.version
    new = ops.get(f"/api/v1/shipments/{shipment.id}/quotes/{second.version}/document").json()
    assert new["status"] == "finalized" and new["superseded_by_version"] is None
    assert new["rate_per_kg_cad"] == "19.00"


def test_finance_settings_patch_without_a_change_is_not_audited(as_admin, db):
    from app.models import AuditEvent
    from tests.conftest import see_committed_changes

    url = "/api/v1/finance/settings"
    current = as_admin.get(url).json()["invoice_due_days"]
    same = as_admin.patch(url, json={"invoice_due_days": current})
    assert same.status_code == 200 and same.json()["invoice_due_days"] == current
    assert as_admin.patch(url, json={}).status_code == 200
    see_committed_changes(db)
    assert db.query(AuditEvent).filter_by(action="finance.settings_update").count() == 0
    changed = as_admin.patch(url, json={"invoice_due_days": current + 7})
    assert changed.json()["invoice_due_days"] == current + 7
    see_committed_changes(db)
    assert db.query(AuditEvent).filter_by(action="finance.settings_update").count() == 1


# --- Tariff versions carry the approver's decision ----------------------------------------


def test_versions_carry_the_review_decision(as_admin, db, admin_is_tariff_approver):
    active = tis.import_workbook(
        db,
        WORKBOOK.read_bytes(),
        file_name="k.xlsx",
        effective_from=date(2026, 10, 12),
        label=None,
        actor=None,
    )
    tis.activate_version(db, active, actor=None)
    db.commit()
    # A second, distinct workbook: the same bytes with a zip comment (a new SHA-256).
    data = WORKBOOK.read_bytes()
    comment = b"phase14"
    data = data[:-2] + len(comment).to_bytes(2, "little") + comment
    draft = tis.import_workbook(
        db,
        data,
        file_name="k2.xlsx",
        effective_from=date(2026, 10, 19),
        label="Manual import",
        actor=None,
    )
    db.commit()

    listed = {v["id"]: v for v in as_admin.get("/api/v1/tariffs/versions").json()["items"]}
    assert listed[draft.id]["review_decision"] is None
    assert listed[draft.id]["status"] == "draft"

    tariff_intake_service.reject(db, draft, admin_is_tariff_approver, "Wrong file")
    db.commit()
    listed = {v["id"]: v for v in as_admin.get("/api/v1/tariffs/versions").json()["items"]}
    assert listed[draft.id]["review_decision"] == "rejected"
    assert listed[draft.id]["status"] == "draft"
    assert listed[active.id]["review_decision"] is None
    detail = as_admin.get(f"/api/v1/tariffs/versions/{draft.id}").json()
    assert detail["review_decision"] == "rejected"
    # Still refused over the old activate route (13H), whatever the screen shows.
    refused = as_admin.post(f"/api/v1/tariffs/versions/{draft.id}/activate")
    assert refused.status_code == 409
