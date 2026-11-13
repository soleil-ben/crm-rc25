"""The owner's answers of 21 October 2026 (Louis Tong; DEC-0222), pinned.

* HCM meat / egg / dairy / honey (HCM air row 41): 20,000 VND/kg for route VN-CA, on the full
  carton (the current scope). Hà Nội row 2 stays 15,000 as printed.
* Every per-kg air rule keeps its current scope (research: each rule's note agrees or is
  silent); the table below makes a future change deliberate.
* Air Express has no default rate: each quote takes a manual rate with a typed reason.
* Vendor rate emails go to benjamin.le@soleiltransportation.com (D-12, OD-76): the intake
  defaults; the UAT seed overrides them with demo addresses.

The Express 16 kg step (answer 1) is in ``test_tariff_workbook.py`` and
``test_tariff_import.py``; the vendor-name rule (answer 4) in ``test_customer_labels.py``.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from app.core.enums import RouteGroup, SurchargeSection
from app.core.time_utils import utcnow
from app.models import ShipmentPackage, TariffSurchargeRule
from app.pricing.kango_semantics import CURATED_RULES, PRICED_ROUTE
from app.pricing.kango_workbook import parse_workbook
from app.services import consolidation_service as cs
from app.services import fx_service
from app.services import pricing_method_service as pms
from app.services import pricing_service as ps
from app.services import tariff_import_service as tis
from app.services.errors import ConflictError, ValidationError
from tests.conftest import booked_shipment, make_customer
from tests.test_fx_service import SAMPLE_XML
from tests.test_quotes import WORKBOOK, _fee, priced_world  # noqa: F401 - fixture

REPO_ROOT = Path(__file__).resolve().parents[2]

# --- Answer 2: HCM meat, egg, dairy, honey -------------------------------------------------


def test_hcm_meat_row_is_curated_for_route_vn_ca_and_cites_the_owner():
    sem = CURATED_RULES[(SurchargeSection.HCM_AIR, 41)]
    assert PRICED_ROUTE == "VN-CA"
    assert sem.route == PRICED_ROUTE
    assert sem.unit_price_vnd == Decimal(20_000) and sem.scope == "full_carton"
    assert "VN-CA" in sem.note and "DEC-0222" in sem.note and "V-14" not in sem.note


def test_a_vn_ca_quote_prices_meat_at_20000_per_kg_on_the_full_carton(db, priced_world):  # noqa: F811
    """The RC-UAT-25 method (DEC-0222): full carton. Method v0.5 prices row 41 on the item's
    own kilograms (the allocation CSV, DEC-0252, open question M-3): see the next test."""
    con, kids = priced_world
    pms.update_method_settings(db, {"pricing_method": "rc25"}, actor=None)
    db.commit()
    assert kids[2].route_group == RouteGroup.VCA  # Vietnam to Canada
    rule = (
        db.query(TariffSurchargeRule)
        .filter_by(version_id=tis.active_version(db).id, section="hcm_air", stt=41)
        .one()
    )
    assert (rule.unit_price_vnd, rule.scope, rule.semantics_source) == (
        Decimal(20_000),
        "full_carton",
        "curated",
    )
    _fee(db, kids[2], "hcm_air", 41, description="Thịt bò khô")
    est, _ = ps.estimate_for(db, con)
    meat = next(f for f in est.fees if f.section == "hcm_air" and f.stt == 41)
    # The 21 kg master is one carton: 21 x 20,000.
    assert meat.vendor_fee_vnd == Decimal(21 * 20_000)


def test_under_v05_meat_is_priced_on_the_items_own_kilograms(db, priced_world):  # noqa: F811
    con, kids = priced_world
    _fee(db, kids[2], "hcm_air", 41, description="Thịt bò khô")
    est, _ = ps.estimate_for(db, con)
    assert "fee_unpriced" in {i.code for i in est.blocking}  # the item weight is required
    _fee(db, kids[2], "hcm_air", 41, description="Thịt bò khô 2", weight_kg="4")
    est, _ = ps.estimate_for(db, con)
    meat = [f for f in est.fees if f.section == "hcm_air" and f.stt == 41]
    assert sorted(f.vendor_fee_vnd or 0 for f in meat) == [0, Decimal(4 * 20_000)]


def test_hanoi_meat_row_stays_15000_as_printed(db):
    version = tis.import_workbook(
        db, WORKBOOK.read_bytes(), file_name="k.xlsx", effective_from=date(2026, 10, 12),
        label=None, actor=None,
    )  # fmt: skip
    rule = db.query(TariffSurchargeRule).filter_by(version_id=version.id, section="han_air", stt=2)
    rule = rule.one()
    assert (rule.unit_price_vnd, rule.semantics_source) == (Decimal(15_000), "parsed")


# --- Answer 3: every per-kg air rule's scope, pinned ---------------------------------------

#: (section, stt) -> scope for every per-kg air rule, as imported from the 12 October 2026
#: workbook. Pharmaceuticals (HCM 39, HN 1) stay on the item's own kilograms (OD-58, OD-70).
#: HCM 27 (costume jewellery) is no longer per kg: since the owner's answer of 2026-10-22 it is
#: a manual amount per line (DEC-0225, ``test_owner_answers_2026_10_22.py``). Changing a scope
#: must change this table.
PER_KG_AIR_SCOPES = {
    ("hcm_air", 14): "full_carton",
    ("hcm_air", 21): "full_carton",
    ("hcm_air", 22): "full_carton",
    ("hcm_air", 23): "full_carton",
    ("hcm_air", 24): "full_carton",
    ("hcm_air", 25): "full_carton",
    ("hcm_air", 32): "full_carton",
    ("hcm_air", 35): "full_carton",
    ("hcm_air", 37): "full_carton",
    ("hcm_air", 38): "full_carton",
    ("hcm_air", 39): "item_weight",
    ("hcm_air", 40): "full_carton",
    ("hcm_air", 41): "full_carton",
    ("hcm_air", 42): "full_carton",
    ("hcm_air", 43): "full_carton",
    ("hcm_air", 44): "full_carton",
    ("hcm_air", 46): "full_carton",
    ("hcm_air", 48): "full_carton",
    ("hcm_air", 49): "full_carton",
    ("hcm_air", 51): "full_carton",
    ("han_air", 1): "item_weight",
    ("han_air", 2): "full_carton",
    ("han_air", 3): "full_carton",
    ("han_air", 4): "full_carton",
    ("han_air", 5): "full_carton",
    ("han_air", 8): "full_carton",
}


def test_every_per_kg_air_rule_keeps_its_current_scope():
    parsed = parse_workbook(WORKBOOK.read_bytes())
    scopes = {}
    for row in parsed.surcharge_rows:
        if row.section.value not in ("hcm_air", "han_air"):
            continue
        resolved = tis.resolve_rule(row, [])
        if resolved["basis"] == "per_kg":
            scopes[(row.section.value, row.stt)] = resolved["scope"]
    assert scopes == PER_KG_AIR_SCOPES


# --- Answer 6: Air Express has no default rate ---------------------------------------------


@pytest.fixture
def express_world(db):
    version = tis.import_workbook(
        db, WORKBOOK.read_bytes(), file_name="k.xlsx", effective_from=date(2026, 10, 12),
        label=None, actor=None,
    )  # fmt: skip
    tis.activate_version(db, version, actor=None)
    fx_service.sync_once(db, fetcher=lambda _u: SAMPLE_XML, clock=utcnow, worker_name="t")
    db.commit()
    shipment = booked_shipment(db, make_customer(db, email="x0@demo.example.com"), RouteGroup.VCA)
    for package in db.query(ShipmentPackage).filter_by(shipment_id=shipment.id):
        package.weight_kg = package.weight_value = Decimal(21)
        package.length_cm = package.width_cm = package.height_cm = None
    db.commit()
    con = cs.create_consolidation(
        db,
        {
            "solaris_service": "air_express",
            "origin": "HCM",
            "vendor_reference": "EXPRS",
            "actual_weight_kg": "21",
        },
        actor=None,
    )
    cs.add_member(db, con, shipment, actor=None)
    db.commit()
    return shipment


def test_air_express_needs_a_manual_rate_and_a_reason_on_every_quote(db, express_world):
    shipment = express_world
    assert ps.get_settings(db).air_express_default_rate_cad is None
    draft, _ = ps.reprice(db, shipment, actor=None)
    db.commit()
    assert draft.default_rate_cad is None and draft.rate_confirmed_at is None

    with pytest.raises(ConflictError) as refused:
        ps.finalize(db, shipment, negative_margin_reason=None, actor=None)
    db.rollback()
    assert "rate_not_confirmed" in [p["code"] for p in refused.value.detail["problems"]]

    with pytest.raises(ValidationError) as no_rate:
        ps.confirm_rate(db, shipment, rate=None, reason=None, actor=None)
    db.rollback()
    assert no_rate.value.field == "rate"
    with pytest.raises(ValidationError) as no_reason:
        ps.confirm_rate(db, shipment, rate=Decimal("26.00"), reason="   ", actor=None)
    db.rollback()
    assert no_reason.value.field == "reason"

    confirmed = ps.confirm_rate(
        db, shipment, rate=Decimal("26.00"), reason="Air Express rate for this lot", actor=None
    )
    db.commit()
    assert confirmed.selling_rate_cad == Decimal("26.00")
    assert confirmed.override_reason == "Air Express rate for this lot"
    # DEC-0271: Kango Air Express vendor cost comes from the rate sheet (Express zone 3), so
    # the confirmed rate is all a finalisation needs.
    final = ps.finalize(db, shipment, negative_margin_reason="test", actor=None)
    db.commit()
    assert final.status == "finalized"


def shipment_consolidation(db, shipment) -> int:
    from app.models.consolidation import ConsolidationMembership

    row = db.query(ConsolidationMembership).filter_by(shipment_id=shipment.id, removed_at=None)
    return row.one().consolidation_id


# --- Answer 7: the intake mailbox and approver ---------------------------------------------


def test_intake_defaults_are_bens_mailbox_and_the_uat_seed_overrides_them(db):
    from app.models.tariff_intake import DEFAULT_APPROVER_EMAILS, DEFAULT_INTAKE_MAILBOX
    from app.services import tariff_intake_service as intake

    owner = "benjamin.le@soleiltransportation.com"
    defaults = (DEFAULT_INTAKE_MAILBOX, DEFAULT_APPROVER_EMAILS)
    assert defaults == (owner, (owner,))
    settings = intake.get_settings(db)
    assert settings.mailbox_address == owner and settings.approver_emails == [owner]

    seed = (REPO_ROOT / "scripts" / "uat_seed_phase13.py").read_text(encoding="utf-8")
    assert 'ADMIN_EMAIL = "admin@demo.example.com"' in seed
    assert 'INTAKE_MAILBOX = "tariffs@demo.example.com"' in seed
    assert "approver_emails=[ADMIN_EMAIL]" in seed and "mailbox_address=INTAKE_MAILBOX" in seed
    assert "soleiltransportation" not in seed.lower()
    # The seed sets no Air Express default either: UAT quotes take a manual rate (answer 6).
    assert "air_express_default_rate_cad" not in seed
