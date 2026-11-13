"""The tariff importer, its routes, and the privacy boundary around vendor cost data.

Service tests use the per-test database; route tests go through the real application
with a signed-in staff user, the way the frontend will. The privacy tests are the ones
that matter most: vendor prices are strictly internal (directive v2.1 §1), so no tariff or
exchange-rate field name may ever appear on the public or Customer Account routers.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.routing import APIRoute

from app.core.enums import (
    BeyondRateStatus,
    Role,
    SurchargePricingStatus,
    TariffVersionStatus,
)
from app.main import app
from app.models import (
    AuditEvent,
    TariffBeyondRate,
    TariffProduct,
    TariffSurchargeRule,
)
from app.schemas import account_shipments, public_tracking
from app.services import tariff_import_service as svc
from app.services.errors import ConflictError, ValidationError

FIXTURES = Path(__file__).resolve().parent / "fixtures"
WORKBOOK = FIXTURES / "kango_canada_rates_2026-10-12_sanitized.xlsx"
EFFECTIVE = date(2026, 10, 12)


@pytest.fixture(scope="module")
def workbook_bytes() -> bytes:
    return WORKBOOK.read_bytes()


@pytest.fixture
def imported(db, workbook_bytes):
    version = svc.import_workbook(
        db, workbook_bytes, file_name="kango.xlsx", effective_from=EFFECTIVE, label=None, actor=None
    )
    db.commit()
    return version


# --- Import -----------------------------------------------------------------------------------


def test_import_writes_every_table_and_a_report(db, imported):
    assert imported.public_id == "TRF-000001"
    assert imported.status == TariffVersionStatus.DRAFT
    assert imported.fixed_fx_vnd_per_cad == Decimal("19500")
    assert len(imported.source_sha256) == 64
    assert svc.version_counts(db, imported) == {
        "products": 10,
        "rate_brackets": 616,
        "zone_fsas": 1674,
        "beyond_postal_codes": 16200,
        "beyond_rates": 9,  # 8 priced codes plus 180 as no_rate
        "accessorials": 16,
        "surcharge_rules": 85,
    }
    report = svc.report(imported)
    assert report["surcharge_rows_by_status"] == {
        "priced": 69,
        "tiered": 4,
        "manual_quote": 9,
        "not_applicable_canada": 2,
        "free": 1,
    }
    assert report["anomaly_counts"]["beyond_code_without_rate"] == 1
    # D-07 answered (DEC-0222): the Express 16 kg drops are confirmed steps, not anomalies.
    assert "price_falls_with_weight" not in report["anomaly_counts"]
    assert {(s["sheet"], s["cell"]) for s in report["confirmed_price_steps"]} == {
        ("HCM-AIR-CAD", "F39"),
        ("HN-AIR-CAD", "F38"),
        ("HN-AIR-CAD", "G38"),
    }
    assert "20.5 kg" in report["rules_in_prose"]["rounding"]
    audit = db.query(AuditEvent).filter_by(action="tariff_version.imported").one()
    assert audit.entity_id == "TRF-000001"


def test_beyond_code_180_is_stored_as_no_rate_not_zero(db, imported):
    """Issue H-07: the vendor's own calculator prices these 123 postal codes at CAD 0."""
    row = db.query(TariffBeyondRate).filter_by(version_id=imported.id, beyond_code="180").one()
    assert row.status == BeyondRateStatus.NO_RATE
    assert row.base_cad is None and row.per_lb_cad is None
    priced = db.query(TariffBeyondRate).filter_by(version_id=imported.id, beyond_code="100").one()
    assert (priced.base_cad, priced.per_lb_cad) == (Decimal("2.95"), Decimal("0.55"))


def test_product_rules_come_from_the_reviewed_table(db, imported):
    """Issue H-06 and the per-piece minimums the JSON never carried."""
    products = {
        (p.origin, p.code): p
        for p in db.query(TariffProduct).filter_by(version_id=imported.id).all()
    }
    ground = products[("HCM", "AIR-CAD")]
    express = products[("HCM", "AIR-CAD EXPRESS")]
    trucking = products[("HAN", "KSN-SEA-CAD-TRUCKING")]
    insured = products[("HCM", "KSN-SEA-CAD-PURO-BH")]
    assert (ground.dim_divisor, ground.per_kg_from_kg) == (6000, Decimal(21))
    assert (ground.piece_min_weight_kg, ground.piece_min_fee_vnd) == (Decimal(12), Decimal(300_000))
    assert express.piece_min_fee_vnd == Decimal(700_000)
    assert (trucking.dim_divisor, trucking.min_chargeable_kg) == (5000, Decimal(100))
    assert trucking.piece_min_fee_vnd == Decimal(500_000)
    assert insured.customs_surcharges_waived is True and ground.customs_surcharges_waived is False


def _rule(db, version, section: str, stt: int) -> TariffSurchargeRule:
    return (
        db.query(TariffSurchargeRule)
        .filter_by(version_id=version.id, section=section, stt=stt)
        .one()
    )


def test_surcharge_semantics_golden_rows(db, imported):
    """One assertion per issue-register row the import must get right."""
    # H-01: "10.000/1kg" is 10,000 per kg, not 1.
    r = _rule(db, imported, "hcm_air", 48)
    assert (r.pricing_status, r.unit_price_vnd) == (SurchargePricingStatus.PRICED, Decimal(10_000))
    for section, stt in (("han_air", 9), ("han_air", 10)):
        assert _rule(db, imported, section, stt).unit_price_vnd >= Decimal(500_000)
    # H-02 / OD-56: the vendor's estimates are manual quotes prefilled with the file's minimum.
    for stt, minimum in (
        (4, 700_000),
        (5, 500_000),
        (10, 100_000),
        (13, 100_000),
        (31, 500_000),
        (33, 1_000_000),
        (34, 200_000),
        (45, 50_000),
    ):
        r = _rule(db, imported, "hcm_air", stt)
        assert r.pricing_status == SurchargePricingStatus.MANUAL_QUOTE, stt
        assert r.unit_price_vnd == Decimal(minimum), stt
    # Row 27 (costume jewellery) has no prefill since the owner's answer of 2026-10-22
    # (DEC-0225): a manual amount staff enter for the line.
    jewellery = _rule(db, imported, "hcm_air", 27)
    assert jewellery.pricing_status == SurchargePricingStatus.MANUAL_QUOTE
    assert (jewellery.basis, jewellery.scope, jewellery.unit_price_vnd) == (
        "manual_amount",
        "per_unit",
        None,
    )
    # H-03: perfume keeps its per-bottle half and its tiers; nail polish is tiered.
    perfume = _rule(db, imported, "hcm_air", 11)
    assert perfume.pricing_status == SurchargePricingStatus.TIERED
    assert (perfume.per_unit_price_vnd, perfume.per_unit_label) == (Decimal(50_000), "bottle")
    assert [(t.weight_from_kg, t.weight_to_kg, t.price_vnd) for t in perfume.tiers] == [
        (Decimal(0), Decimal(5), Decimal(300_000)),
        (Decimal(5), Decimal(22), Decimal(500_000)),
        (Decimal(22), Decimal(30), Decimal(700_000)),
    ]
    assert len(_rule(db, imported, "hcm_air", 1).tiers) == 3
    # OD-59: rows 2 and 3 are one battery rule: up to 3.5 kg 300k, over 3.5 up to 8 kg 700k.
    for stt in (2, 3):
        battery = _rule(db, imported, "hcm_air", stt)
        assert battery.pricing_status == SurchargePricingStatus.TIERED
        assert [(t.weight_from_kg, t.weight_to_kg, t.price_vnd) for t in battery.tiers] == [
            (Decimal(0), Decimal("3.5"), Decimal(300_000)),
            (Decimal("3.5"), Decimal(8), Decimal(700_000)),
        ]
    # Per-kg surcharges are on the full carton (sheet footer); Labubu at sea on the whole lot.
    assert _rule(db, imported, "hcm_air", 14).scope == "full_carton"
    assert _rule(db, imported, "sea_ca_au_uk_eu", 6).scope == "full_master"
    # H-08: meat/egg/dairy on HCM air is 20,000 for Canada, not the 10,000 printed.
    meat = _rule(db, imported, "hcm_air", 41)
    assert (meat.unit_price_vnd, meat.semantics_source) == (Decimal(20_000), "curated")
    # H-09: plants are EU/UK only; Hà Nội eyelashes are free.
    for section, stt in (("hcm_air", 44), ("han_air", 8)):
        r = _rule(db, imported, section, stt)
        assert r.pricing_status == SurchargePricingStatus.NOT_APPLICABLE_CANADA
        assert r.applies_to_canada is False
    lashes = _rule(db, imported, "han_air", 6)
    assert (lashes.pricing_status, lashes.unit_price_vnd) == (SurchargePricingStatus.FREE, None)
    # Pharmaceuticals (OD-58): carried and charged at the surcharge sheet's 200,000 VND/kg.
    for section, stt in (("hcm_air", 39), ("han_air", 1)):
        r = _rule(db, imported, section, stt)
        assert r.pricing_status == SurchargePricingStatus.PRICED
        assert r.unit_price_vnd == Decimal(200_000)
    assert _rule(db, imported, "han_air", 1).min_charge_kg == Decimal(1)
    # Only a priced row or a manual quote's prefilled minimum carries a unit price.
    for r in db.query(TariffSurchargeRule).filter_by(version_id=imported.id):
        if r.pricing_status not in {
            SurchargePricingStatus.PRICED,
            SurchargePricingStatus.MANUAL_QUOTE,
        }:
            assert r.unit_price_vnd is None, (r.section, r.stt, r.pricing_status)
    # The USA sea section never applies to Canada.
    assert all(
        not r.applies_to_canada
        for r in db.query(TariffSurchargeRule).filter_by(version_id=imported.id, section="sea_usa")
    )
    # Every row keeps the vendor's text beside the reading.
    assert perfume.raw_price_text == "300.000/Kiện + 50.000/Chai"
    assert perfume.source_row == 20


def test_the_same_file_cannot_be_imported_twice(db, imported, workbook_bytes):
    with pytest.raises(ConflictError, match="TRF-000001"):
        svc.import_workbook(
            db,
            workbook_bytes,
            file_name="again.xlsx",
            effective_from=EFFECTIVE,
            label=None,
            actor=None,
        )


def test_an_unreadable_file_is_a_validation_error(db):
    with pytest.raises(ValidationError, match="could not be read"):
        svc.import_workbook(
            db,
            b"PK\x03\x04 not really",
            file_name="x.xlsx",
            effective_from=EFFECTIVE,
            label=None,
            actor=None,
        )


def test_activation_supersedes_the_previous_version_and_keeps_it(db, imported, workbook_bytes):
    assert svc.active_version(db) is None
    svc.activate_version(db, imported, actor=None, now=datetime(2026, 10, 19, 12, 0))
    db.commit()
    assert svc.active_version(db).id == imported.id
    assert imported.activated_at == datetime(2026, 10, 19, 12, 0)

    # A second workbook: the same tariff with one byte of metadata changed is a new file.
    second = svc.import_workbook(
        db,
        workbook_bytes + b"\n",
        file_name="v2.xlsx",
        effective_from=date(2026, 11, 1),
        label="v2",
        actor=None,
    )
    db.commit()
    assert second.public_id == "TRF-000002" and second.status == TariffVersionStatus.DRAFT
    svc.activate_version(db, second, actor=None)
    db.commit()
    db.refresh(imported)
    assert imported.status == TariffVersionStatus.SUPERSEDED
    assert imported.effective_to == date(2026, 11, 1)
    assert svc.active_version(db).id == second.id
    with pytest.raises(ConflictError):
        svc.activate_version(db, imported, actor=None)
    actions = [a.action for a in db.query(AuditEvent).order_by(AuditEvent.id)]
    assert actions.count("tariff_version.activated") == 2


# --- Routes -------------------------------------------------------------------------------------


def test_admin_imports_reads_and_activates_over_http(
    as_admin, workbook_bytes, admin_is_tariff_approver
):
    """The Admin is the designated approver here: activation over HTTP needs one (13H)."""
    files = {
        "file": (
            "kango.xlsx",
            workbook_bytes,
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    }
    response = as_admin.post(
        "/api/v1/tariffs/versions/import", files=files, data={"effective_from": "2026-10-12"}
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["public_id"] == "TRF-000001" and body["status"] == "draft"
    assert body["counts"]["surcharge_rules"] == 85
    assert body["report"]["anomaly_counts"]["beyond_code_without_rate"] == 1
    version_id = body["id"]

    again = as_admin.post(
        "/api/v1/tariffs/versions/import", files=files, data={"effective_from": "2026-10-12"}
    )
    assert again.status_code == 409

    listed = as_admin.get("/api/v1/tariffs/versions").json()
    assert listed["total"] == 1 and listed["items"][0]["vendor_key"] == "kango"

    products = as_admin.get(f"/api/v1/tariffs/versions/{version_id}/products").json()
    assert len(products) == 10
    detail = as_admin.get(
        f"/api/v1/tariffs/versions/{version_id}/products/{products[0]['id']}"
    ).json()
    assert detail["brackets"] and all("source_cell" in b for b in detail["brackets"])

    surcharges = as_admin.get(f"/api/v1/tariffs/versions/{version_id}/surcharges").json()
    assert surcharges["total"] == 85 - 13 - 2  # Canada only: no USA section, no EU/UK-only rows
    hanoi = as_admin.get(
        f"/api/v1/tariffs/versions/{version_id}/surcharges",
        params={"section": "han_air", "q": "lông"},
    ).json()
    assert [r["stt"] for r in hanoi["items"]] == [6]
    everything = as_admin.get(
        f"/api/v1/tariffs/versions/{version_id}/surcharges", params={"canada_only": "false"}
    ).json()
    assert everything["total"] == 85

    assert len(as_admin.get(f"/api/v1/tariffs/versions/{version_id}/accessorials").json()) == 16
    beyond = as_admin.get(f"/api/v1/tariffs/versions/{version_id}/beyond-rates").json()
    assert {b["beyond_code"]: b["status"] for b in beyond}["180"] == "no_rate"

    activated = as_admin.post(f"/api/v1/tariffs/versions/{version_id}/activate")
    assert activated.status_code == 200 and activated.json()["status"] == "active"


def test_operations_may_read_but_not_import_or_activate(api_for, workbook_bytes):
    operations = api_for(Role.OPERATIONS)
    assert operations.get("/api/v1/tariffs/versions").status_code == 200
    assert operations.get("/api/v1/fx/latest").status_code == 200
    files = {"file": ("kango.xlsx", workbook_bytes, "application/octet-stream")}
    denied = operations.post(
        "/api/v1/tariffs/versions/import", files=files, data={"effective_from": "2026-10-12"}
    )
    assert denied.status_code == 403
    assert operations.post("/api/v1/tariffs/versions/1/activate").status_code == 403


def test_marketing_and_read_only_manager_see_no_vendor_prices(api_for):
    for role in (Role.MARKETING, Role.READ_ONLY_MANAGER):
        client = api_for(role)
        assert client.get("/api/v1/tariffs/versions").status_code == 403
        assert client.get("/api/v1/fx/latest").status_code == 403


def test_the_import_route_refuses_non_xlsx_and_oversized_files(as_admin, monkeypatch):
    not_xlsx = {"file": ("rates.csv", b"a,b,c\n1,2,3\n", "text/csv")}
    response = as_admin.post(
        "/api/v1/tariffs/versions/import", files=not_xlsx, data={"effective_from": "2026-10-12"}
    )
    assert response.status_code == 422
    from app.core.config import settings  # noqa: PLC0415

    monkeypatch.setattr(settings, "tariff_import_max_bytes", 100)
    big = {"file": ("big.xlsx", b"PK\x03\x04" + b"0" * 200, "application/octet-stream")}
    response = as_admin.post(
        "/api/v1/tariffs/versions/import", files=big, data={"effective_from": "2026-10-12"}
    )
    assert response.status_code == 422
    assert "limit" in response.text


def test_fx_routes_report_none_until_a_snapshot_exists(as_admin, db):
    latest = as_admin.get("/api/v1/fx/latest").json()
    assert latest == {
        "freshness": "none",
        "stale_after_minutes": latest["stale_after_minutes"],
        "snapshot": None,
        "last_attempt": None,
    }
    from app.services import fx_service  # noqa: PLC0415
    from tests.test_fx_service import SAMPLE_XML  # noqa: PLC0415

    fx_service.sync_once(db, fetcher=lambda _u: SAMPLE_XML, worker_name="t")
    db.commit()
    latest = as_admin.get("/api/v1/fx/latest").json()
    assert latest["freshness"] == "live"
    assert latest["snapshot"]["cash_buy_vnd"] == "17886.61"
    assert latest["snapshot"]["sell_vnd"] == "18645.39"
    history = as_admin.get("/api/v1/fx/history").json()
    assert len(history["snapshots"]) == 1 and history["attempts"][0]["outcome"] == "ok"


# --- Privacy: vendor cost data never reaches a customer-facing surface ----------------------------

#: Words that only a tariff or exchange-rate field would carry. If one of these ever
#: appears in a public or account schema, vendor cost has leaked.
TARIFF_VOCABULARY = (
    "tariff",
    "vendor",
    "price_vnd",
    "cash_buy",
    "sell_vnd",
    "beyond",
    "surcharge_rule",
    "accessorial",
    "fx_",
    "kango",
)


def _field_names(module) -> set[str]:
    names: set[str] = set()
    for value in vars(module).values():
        fields = getattr(value, "model_fields", None)
        if isinstance(fields, dict):
            names.update(fields)
    return names


#: Staff-only schema modules that legitimately carry vendor vocabulary: the tariff itself,
#: the consolidation (the vendor's booking reference and billed weight, behind
#: ``tariff:read``), and the staff shipment detail that embeds the consolidation summary.
#: Everything else -- above all every public and Customer Account module -- is scanned.
VENDOR_FACING_STAFF_MODULES = frozenset(
    {"tariff", "consolidation", "shipment", "pricing", "vendor_bills"}
)


def _scanned_schema_modules():
    """Every module under ``app.schemas`` except the staff-only vendor modules."""
    import importlib  # noqa: PLC0415
    import pkgutil  # noqa: PLC0415

    import app.schemas as package  # noqa: PLC0415

    for info in pkgutil.iter_modules(package.__path__):
        if info.name not in VENDOR_FACING_STAFF_MODULES:
            yield importlib.import_module(f"app.schemas.{info.name}")


def test_no_customer_facing_or_general_schema_carries_a_tariff_or_fx_field():
    modules = list(_scanned_schema_modules())
    assert public_tracking in modules and account_shipments in modules
    # Every public and account module is scanned, whatever it is called.
    scanned = {m.__name__.rsplit(".", 1)[-1] for m in modules}
    import pkgutil  # noqa: PLC0415

    import app.schemas as package  # noqa: PLC0415

    for info in pkgutil.iter_modules(package.__path__):
        if info.name.startswith(("public", "account")):
            assert info.name in scanned, info.name
    for module in modules:
        for name in _field_names(module):
            assert not any(word in name.lower() for word in TARIFF_VOCABULARY), (
                module.__name__,
                name,
            )


def test_no_tariff_or_fx_route_is_mounted_outside_the_staff_router():
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        path = route.path.lower()
        if "tariff" in path or "/fx" in path:
            assert path.startswith("/api/v1/tariffs") or path.startswith("/api/v1/fx"), path
            assert not path.startswith("/api/v1/public") and not path.startswith("/api/v1/account")


def test_the_import_report_holds_no_person(imported):
    """The sanitized fixture has no staff sheet, so this is a guard on the report's shape:
    counts, anomalies, cells and tariff rule text only."""
    report = json.dumps(svc.report(imported), ensure_ascii=False).lower()
    for forbidden in ("zalo", "sđt", "nhân viên", "@"):
        assert forbidden not in report
