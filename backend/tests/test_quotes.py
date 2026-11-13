"""Fee lines, estimates and versioned quotes over the service and HTTP (Phase 13C).

The engine's arithmetic is covered by ``test_pricing_golden.py`` (written independently from
the handoff's acceptance cases) and ``test_pricing_engine.py``; this module covers the
workflow around it: the owner decisions OD-44 to OD-48, confirmation and its revocation,
finalisation and its refusals, immutability of a finalised version, permissions, and privacy.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from app.core.enums import Role, RouteGroup
from app.core.time_utils import utcnow
from app.models import AuditEvent, QuoteVersion, ShipmentPackage
from app.services import consolidation_service as cs
from app.services import fx_service
from app.services import pricing_method_service as pms
from app.services import pricing_service as ps
from app.services import shipment_item_service as items
from app.services import tariff_import_service as tis
from app.services.errors import ConflictError, NotFoundError, ValidationError
from tests.conftest import booked_shipment, make_customer, see_committed_changes
from tests.test_fx_service import SAMPLE_XML

WORKBOOK = (
    Path(__file__).resolve().parent / "fixtures" / "kango_canada_rates_2026-10-12_sanitized.xlsx"
)


@pytest.fixture
def priced_world(db):
    """Active tariff, a live exchange rate, and a booked-style 21 kg master with 3/6/12 kg
    children (handoff section 5)."""
    version = tis.import_workbook(
        db,
        WORKBOOK.read_bytes(),
        file_name="k.xlsx",
        effective_from=date(2026, 10, 12),
        label=None,
        actor=None,
    )
    tis.activate_version(db, version, actor=None)
    fx_service.sync_once(db, fetcher=lambda _u: SAMPLE_XML, clock=utcnow, worker_name="t")
    db.commit()
    kids = []
    for i, kg in enumerate((3, 6, 12)):
        shipment = booked_shipment(
            db, make_customer(db, email=f"c{i}@demo.example.com"), RouteGroup.VCA
        )
        for package in db.query(ShipmentPackage).filter_by(shipment_id=shipment.id):
            package.weight_kg = Decimal(kg)
            package.weight_value = Decimal(kg)
            package.length_cm = package.width_cm = package.height_cm = None
        kids.append(shipment)
    db.commit()
    con = cs.create_consolidation(
        db,
        {
            "solaris_service": "air_standard",
            "origin": "HCM",
            "vendor_reference": "AAAAA",
            "actual_weight_kg": "21",
        },
        actor=None,
    )
    for shipment in kids:
        cs.add_member(db, con, shipment, actor=None)
    db.commit()
    return con, kids


def _fee(db, shipment, section, stt, **extra):
    item = items.add_item(
        db, shipment, {"description": extra.pop("description", "goods")}, actor=None
    )
    line = ps.add_fee_line(
        db, shipment, {"item_id": item.id, "section": section, "stt": stt, **extra}, actor=None
    )
    db.commit()
    return line


# --- OD-46: one delivery point ---------------------------------------------------------------------


def test_vendor_cost_is_zoned_at_l5a_3k6_whatever_the_customer_address(db, priced_world):
    con, _kids = priced_world
    est, _ = ps.estimate_for(db, con)
    assert est.delivery_postal_code == "L5A3K6"
    assert est.zone == 2  # L5A, Ground
    assert not any(i.code.startswith("delivery_") for i in est.blocking + est.provisional)
    # 21 kg x the 21-44 tier, Ground zone 2, HCM.
    assert est.base_freight_vnd == Decimal("243000") * 21


# --- OD-58: pharmaceuticals are priced, not blocked ------------------------------------------------


def test_a_pharmaceutical_line_is_charged_200000_per_kg_and_does_not_block(db, priced_world):
    """OD-58 supersedes OD-47: 200,000 VND/kg from the surcharge sheet, on the item's own
    kilograms only (owner, 2026-10-20, OD-70), so it is that customer's alone."""
    con, kids = priced_world
    _fee(db, kids[2], "hcm_air", 39, description="Thuốc tây", weight_kg="1.2")
    est, _ = ps.estimate_for(db, con)
    assert not [i for i in est.blocking if i.code.startswith("fee_")]
    pharma = next(f for f in est.fees if f.stt == 39)
    assert not pharma.master_wide
    # 1.2 kg rounds to 1.5 kg (OD-50): 300,000 VND, all on the trigger.
    assert pharma.vendor_fee_vnd == Decimal("300000.00")
    assert pharma.cost_alloc_vnd == {kids[2].id: Decimal("300000.00")}
    ps.confirm_rate(db, kids[2], rate=None, reason=None, actor=None)
    db.commit()
    final = ps.finalize(
        db, kids[2], negative_margin_reason="pass-through, policy pending (OD-44)", actor=None
    )
    assert final.status == "finalized"


# --- OD-56: manual quotes prefilled with the minimum ---------------------------------------------


def test_a_manual_quote_uses_the_minimum_until_the_vendor_price_is_entered(db, priced_world):
    con, kids = priced_world
    prefilled = _fee(db, kids[0], "hcm_air", 5, description="Loa", quantity=2)
    quoted = _fee(
        db, kids[1], "hcm_air", 5, description="Loa", quantity=2, manual_unit_price_vnd="650000"
    )
    assert quoted.manual_unit_price_vnd == Decimal("650000.00")
    est, _ = ps.estimate_for(db, con)
    assert not [i for i in est.blocking if i.code.startswith("fee_")]
    by_line = {f.triggers[next(iter(f.triggers))][0]: f for f in est.fees if f.stt == 5}
    assert by_line[prefilled.id].vendor_fee_vnd == Decimal(1_000_000)
    assert by_line[quoted.id].vendor_fee_vnd == Decimal(1_300_000)
    flagged = [i.fee_line_id for i in est.provisional if i.code == "manual_quote_prefilled_minimum"]
    assert flagged == [prefilled.id]


# --- OD-59: battery groups -----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("weight", "expected"),
    [("3.0", 300_000), ("3.5", 300_000), ("3.6", 700_000), ("3.9", 700_000), ("8", 700_000)],
)
def test_battery_cartons_fall_in_the_owners_groups(db, priced_world, weight, expected):
    con, kids = priced_world
    _fee(db, kids[0], "hcm_air", 2, description="Pin", weight_kg=weight)
    est, _ = ps.estimate_for(db, con)
    battery = next(f for f in est.fees if f.stt == 2)
    assert battery.vendor_fee_vnd == Decimal(expected)


def test_a_battery_carton_above_8_kg_needs_the_vendor_quote(db, priced_world):
    con, kids = priced_world
    line = _fee(db, kids[0], "hcm_air", 3, description="Pin", weight_kg="8.4")
    est, _ = ps.estimate_for(db, con)
    assert any(i.fee_line_id == line.id for i in est.blocking)
    ps.remove_fee_line(db, kids[0], line.id, actor=None)
    _fee(
        db,
        kids[0],
        "hcm_air",
        3,
        description="Pin",
        weight_kg="8.4",
        manual_unit_price_vnd="900000",
    )
    est, _ = ps.estimate_for(db, con)
    assert not [i for i in est.blocking if i.code.startswith("fee_")]
    assert next(f for f in est.fees if f.stt == 3).vendor_fee_vnd == Decimal(900_000)


def test_nail_polish_above_30_kg_uses_the_top_tier(db, priced_world):
    con, kids = priced_world
    _fee(db, kids[0], "hcm_air", 1, description="Sơn móng", weight_kg="34")
    _fee(db, kids[1], "hcm_air", 1, description="Sơn móng", weight_kg="5.1")
    est, _ = ps.estimate_for(db, con)
    # DEC-0276: one master piece, 34 + 5.1 = 39.1 kg of nail polish → the top tier, once, and
    # flagged; each customer is quoted on its own kg (34 kg → top tier; 5.1 → 5.0 → 300,000).
    (nail,) = [f for f in est.fees if f.stt == 1]
    assert nail.vendor_fee_vnd == Decimal(700_000)
    assert "piece_type_over_top_band" in {i.code for i in est.provisional}
    line = next(ln for ln in est.method_detail["lines"] if ln["stt"] == 1)
    assert line["quote_vnd"] == {kids[0].id: Decimal(700_000), kids[1].id: Decimal(300_000)}


# --- OD-62: the under-12 kg piece fee ------------------------------------------------------------


def test_cartons_under_12_kg_on_a_21_kg_lot_pay_the_piece_fee(db, priced_world):
    con, _kids = priced_world
    est, _ = ps.estimate_for(db, con)
    assert est.piece_fee_vnd == 0
    ps.replace_cartons(
        db,
        con,
        [{"weight_kg": "3"}, {"weight_kg": "6"}, {"weight_kg": "12"}],
        actor=None,
    )
    db.commit()
    est, _ = ps.estimate_for(db, con)
    # Two cartons under 12 kg, Ground: 2 x 300,000 on top of 21 x 243,000. Under method v0.5
    # (DEC-0252) the piece fee is its own fee line (key PIECE), not part of the base freight.
    assert est.piece_fee_vnd == 0
    assert _piece(est) == Decimal(600_000)
    assert est.total_cost_vnd == Decimal(243_000) * 21 + Decimal(600_000)
    assert sum(m.base_cost_vnd for m in est.members.values()) == Decimal(5_103_000)
    # A light carton that is large counts at its volumetric weight.
    ps.replace_cartons(
        db,
        con,
        [
            {"weight_kg": "3", "length_cm": "60", "width_cm": "50", "height_cm": "50"},
            {"weight_kg": "6"},
            {"weight_kg": "12"},
        ],
        actor=None,
    )
    db.commit()
    est, _ = ps.estimate_for(db, con)
    assert _piece(est) == Decimal(300_000)
    actions = [a.action for a in db.query(AuditEvent)]
    assert actions.count("consolidation.cartons_replace") == 2


def _piece(est) -> Decimal:
    return sum((f.vendor_fee_vnd or 0 for f in est.fees if f.key == "PIECE"), Decimal(0))


def test_rc25_method_keeps_the_piece_fee_in_the_base(db, priced_world):
    con, _kids = priced_world
    pms.update_method_settings(db, {"pricing_method": "rc25"}, actor=None)
    ps.replace_cartons(
        db, con, [{"weight_kg": "3"}, {"weight_kg": "6"}, {"weight_kg": "12"}], actor=None
    )
    db.commit()
    est, _ = ps.estimate_for(db, con)
    assert est.piece_fee_vnd == Decimal(600_000)
    assert sum(m.base_cost_vnd for m in est.members.values()) == Decimal(5_703_000)


# --- OD-48: configurable defaults, flagged --------------------------------------------------------


def test_defaults_are_confirmed_and_still_configurable(db, priced_world, users):
    """OD-48 confirmed by the owner on 2026-10-20: no pending flag by default; the values
    stay settings, and an administrator can mark them unconfirmed again."""
    con, kids = priced_world
    draft, est = ps.reprice(db, kids[0], actor=None)
    db.commit()
    # Method v0.5 (DEC-0252): a 3 kg customer is under 21 kg, so CAD 19/kg.
    assert draft.default_rate_cad == Decimal("19.00") and draft.selling_rate_cad == Decimal("19.00")
    assert "pricing_defaults_pending_owner_confirmation" not in [i.code for i in est.provisional]
    ps.update_settings(db, {"defaults_owner_confirmed": False}, actor=users[Role.ADMIN])
    db.commit()
    est, _ = ps.estimate_for(db, con)
    assert "pricing_defaults_pending_owner_confirmation" in [i.code for i in est.provisional]

    admin = users[Role.ADMIN]
    ps.update_settings(
        db,
        {
            "air_standard_default_rate_cad": "19.50",
            "trigger_share_numerator": 1,
            "trigger_share_denominator": 2,
        },
        actor=admin,
    )
    db.commit()
    _fee(db, kids[1], "hcm_air", 14, description="Fake clothing")
    est, _ = ps.estimate_for(db, con)
    fake = next(f for f in est.fees if f.stt == 14)
    # Trigger share 1/2: 630,000 -> 315,000 to the trigger, 157,500 to each other member.
    assert sorted(fake.cost_alloc_vnd.values()) == [
        Decimal("157500.00"),
        Decimal("157500.00"),
        Decimal("315000.00"),
    ]
    assert fake.cost_alloc_vnd[kids[1].id] == Decimal("315000.00")

    ps.update_settings(db, {"defaults_owner_confirmed": True}, actor=admin)
    db.commit()
    est, _ = ps.estimate_for(db, con)
    assert "pricing_defaults_pending_owner_confirmation" not in [i.code for i in est.provisional]
    actions = [a.action for a in db.query(AuditEvent)]
    assert actions.count("pricing.settings_update") == 3


# --- OD-45: confirmation, override, revocation ----------------------------------------------------


def test_the_default_rate_must_be_confirmed_and_an_override_needs_a_reason(db, priced_world):
    _con, kids = priced_world
    draft, _ = ps.reprice(db, kids[0], actor=None)
    db.commit()
    assert draft.rate_confirmed_at is None
    with pytest.raises(ConflictError) as raised:
        ps.finalize(db, kids[0], negative_margin_reason=None, actor=None)
    db.rollback()
    assert [p["code"] for p in raised.value.detail["problems"]] == ["rate_not_confirmed"]
    with pytest.raises(ValidationError, match="reason"):
        ps.confirm_rate(db, kids[0], rate=Decimal("16.00"), reason=None, actor=None)
    db.rollback()
    confirmed = ps.confirm_rate(
        db, kids[0], rate=Decimal("16.00"), reason="loyal customer", actor=None
    )
    db.commit()
    assert (
        confirmed.selling_rate_cad == Decimal("16.00")
        and confirmed.override_reason == "loyal customer"
    )
    assert confirmed.base_revenue_cad == Decimal("48.00")


def test_changing_an_input_revokes_the_confirmation(db, priced_world):
    _con, kids = priced_world
    ps.confirm_rate(db, kids[1], rate=None, reason=None, actor=None)
    db.commit()
    _fee(db, kids[1], "hcm_air", 15, description="Fake handbag", quantity=2)
    draft, _ = ps.reprice(db, kids[1], actor=None)
    db.commit()
    assert draft.rate_confirmed_at is None and draft.confirmed_inputs_sha256 is None


def test_another_members_trigger_on_a_shared_fee_revokes_too(db, priced_world):
    _con, kids = priced_world
    _fee(db, kids[0], "hcm_air", 14, description="Fake clothing")
    ps.confirm_rate(db, kids[0], rate=None, reason=None, actor=None)
    db.commit()
    _fee(db, kids[1], "hcm_air", 14, description="Fake clothing")
    draft, _ = ps.reprice(db, kids[0], actor=None)
    assert draft.rate_confirmed_at is None  # its surcharge share changed


# --- Finalisation and immutability ----------------------------------------------------------------


def test_finalising_freezes_the_version_and_a_later_change_opens_a_new_draft(db, priced_world):
    _con, kids = priced_world
    ps.confirm_rate(db, kids[2], rate=None, reason=None, actor=None)
    final = ps.finalize(db, kids[2], negative_margin_reason=None, actor=None)
    db.commit()
    assert (final.status, final.version, final.total_revenue_cad) == (
        "finalized",
        1,
        Decimal("228.00"),  # 12 kg x CAD 19 (v0.5, under 21 kg)
    )
    frozen_snapshot = final.snapshot_json
    frozen_fx = final.fx_snapshot_id

    # A new bank reading arrives and a fee is added: the finalised version does not move.
    newer = SAMPLE_XML.replace(b"18,645.39", b"19,000.00")
    fx_service.sync_once(
        db, fetcher=lambda _u: newer, clock=lambda: utcnow() + timedelta(minutes=1), worker_name="t"
    )
    _fee(db, kids[2], "hcm_air", 18, description="Watch", quantity=1)
    draft, _ = ps.reprice(db, kids[2], actor=None)
    db.commit()
    db.refresh(final)
    assert (
        final.status == "finalized"
        and final.snapshot_json == frozen_snapshot
        and final.fx_snapshot_id == frozen_fx
    )
    assert (draft.version, draft.status) == (2, "draft")
    ps.confirm_rate(db, kids[2], rate=None, reason=None, actor=None)
    second = ps.finalize(
        db,
        kids[2],
        negative_margin_reason="pass-through surcharge, margin policy pending (OD-44)",
        actor=None,
    )
    db.commit()
    db.refresh(final)
    assert final.status == "superseded" and second.status == "finalized"


def test_a_direct_surcharge_carries_the_default_markup_and_never_bills_below_cost(db, priced_world):
    """OD-73/OD-74 (owner, 2026-10-20): cost and revenue both convert at the buy rate, and a
    surcharge with no policy of its own carries the 2 % default markup. RC-UAT-25 method only;
    under v0.5 see ``test_v05_direct_surcharge_has_no_markup_and_bills_at_cost``."""
    _con, kids = priced_world
    pms.update_method_settings(db, {"pricing_method": "rc25"}, actor=None)
    _fee(db, kids[0], "hcm_air", 18, description="Watch", quantity=2)
    ps.confirm_rate(db, kids[0], rate=None, reason=None, actor=None)
    final = ps.finalize(db, kids[0], negative_margin_reason=None, actor=None)
    db.commit()
    watch = next(line for line in final.lines if line.stt == 18)
    assert watch.markup_kind == "percent" and Decimal(watch.markup_value) == Decimal("2.00")
    assert watch.revenue_cad > watch.cost_cad
    # A pass-through policy on the rule recovers exactly the cost: no margin, no refusal.
    ps.set_policy(db, "hcm_air", 18, {"markup_kind": "pass_through"}, actor=None)
    ps.reprice(db, kids[0], actor=None)
    ps.confirm_rate(db, kids[0], rate=None, reason=None, actor=None)
    again = ps.finalize(db, kids[0], negative_margin_reason=None, actor=None)
    db.commit()
    watch = next(line for line in again.lines if line.stt == 18)
    assert watch.markup_kind == "pass_through" and watch.revenue_cad == watch.cost_cad


def test_v05_direct_surcharge_has_no_markup_and_bills_at_cost(db, priced_world):
    _con, kids = priced_world
    _fee(db, kids[0], "hcm_air", 18, description="Watch", quantity=2)
    ps.confirm_rate(db, kids[0], rate=None, reason=None, actor=None)
    final = ps.finalize(db, kids[0], negative_margin_reason=None, actor=None)
    db.commit()
    watch = next(line for line in final.lines if line.stt == 18)
    assert watch.markup_kind == "none" and Decimal(watch.markup_value) == 0
    assert watch.revenue_cad == watch.cost_cad == Decimal("5.13")  # 100,000 / 19,500


def test_the_default_markup_is_a_setting(db, priced_world):
    con, kids = priced_world
    assert ps.get_markup_default(db) not in db  # reading never writes
    ps.update_markup_default(db, "fixed_cad", "3.00", actor=None)
    db.commit()
    with pytest.raises(ValidationError):
        ps.update_markup_default(db, "bonus", None, actor=None)
    db.rollback()
    with pytest.raises(ValidationError):
        ps.update_markup_default(db, None, "-1", actor=None)
    db.rollback()
    _fee(db, kids[0], "hcm_air", 18, description="Watch", quantity=2)
    # The RC-UAT-25 default markup row prices under the rc25 method only (DEC-0252) ...
    est, _version = ps.estimate_for(db, con)
    fee = next(f for f in est.fees if f.stt == 18)
    assert fee.customer_total_cad == fee.customer_base_cad
    pms.update_method_settings(db, {"pricing_method": "rc25"}, actor=None)
    db.commit()
    est, _version = ps.estimate_for(db, con)
    fee = next(f for f in est.fees if f.stt == 18)
    assert fee.customer_total_cad == fee.customer_base_cad + Decimal("3.00")
    # ... and under v0.5 the markup is the method's own setting.
    pms.update_method_settings(
        db,
        {"pricing_method": "v0_6", "markup_kind": "fixed_cad", "markup_value": "3.00"},
        actor=None,
    )
    db.commit()
    est, _version = ps.estimate_for(db, con)
    fee = next(f for f in est.fees if f.stt == 18)
    assert fee.customer_total_cad == fee.customer_base_cad + Decimal("3.00")


def test_a_shipment_outside_a_consolidation_cannot_be_quoted(db, priced_world):
    loose = booked_shipment(db, make_customer(db, email="loose@demo.example.com"), RouteGroup.VCA)
    with pytest.raises(ConflictError, match="consolidation"):
        ps.reprice(db, loose, actor=None)


def test_a_stale_rate_blocks_finalisation(db, priced_world):
    """A bank rate can go stale; Kango's fixed rate (the v0.5 default) cannot, so the quote
    source is set to Vietcombank here (DEC-0252)."""
    _con, kids = priced_world
    pms.update_method_settings(
        db, {"fx_source_cost": "vcb_cash_buy", "fx_source_quote": "vcb_cash_buy"}, actor=None
    )
    db.commit()
    ps.confirm_rate(db, kids[0], rate=None, reason=None, actor=None)
    db.commit()
    later = utcnow() + timedelta(days=3)
    with pytest.raises(ConflictError) as raised:
        ps.finalize(db, kids[0], negative_margin_reason=None, actor=None, now=later)
    assert "fx_stale" in [p["code"] for p in raised.value.detail["problems"]]


# --- Fee lines ------------------------------------------------------------------------------------


def test_fee_line_rules(db, priced_world):
    _con, kids = priced_world
    item = items.add_item(db, kids[0], {"description": "Cây xanh"}, actor=None)
    db.commit()
    with pytest.raises(ConflictError, match="does not apply to Canada"):
        ps.add_fee_line(
            db, kids[0], {"item_id": item.id, "section": "hcm_air", "stt": 44}, actor=None
        )
    db.rollback()
    with pytest.raises(NotFoundError):
        ps.add_fee_line(
            db, kids[0], {"item_id": item.id, "section": "hcm_air", "stt": 999}, actor=None
        )
    db.rollback()
    with pytest.raises(ValidationError, match="air"):
        ps.add_fee_line(
            db, kids[0], {"item_id": item.id, "section": "sea_ca_au_uk_eu", "stt": 1}, actor=None
        )
    db.rollback()
    line = ps.add_fee_line(
        db,
        kids[0],
        {"item_id": item.id, "section": "hcm_air", "stt": 22, "weight_kg": "2"},
        actor=None,
    )
    db.commit()
    with pytest.raises(ConflictError, match="already on this item"):
        ps.add_fee_line(
            db, kids[0], {"item_id": item.id, "section": "hcm_air", "stt": 22}, actor=None
        )
    db.rollback()
    ps.remove_fee_line(db, kids[0], line.id, actor=None)
    db.commit()
    assert ps.active_fee_lines(db, kids[0].id) == []


# --- HTTP, permissions, privacy -------------------------------------------------------------------


def test_the_quote_flow_over_http(as_admin, db, priced_world):
    con, kids = priced_world
    item = as_admin.post(
        f"/api/v1/shipments/{kids[1].id}/items", json={"description": "Fake clothing"}
    ).json()
    added = as_admin.post(
        f"/api/v1/shipments/{kids[1].id}/fee-lines",
        json={"item_id": item["id"], "section": "hcm_air", "stt": 14},
    )
    assert added.status_code == 201, added.text
    estimate = as_admin.get(f"/api/v1/consolidations/{con.id}/pricing")
    assert estimate.status_code == 200
    fee = estimate.json()["estimate"]["fees"][0]
    assert fee["vendor_fee_vnd"] == "630000.00"

    draft = as_admin.post(f"/api/v1/shipments/{kids[1].id}/quotes")
    assert draft.status_code == 201 and draft.json()["rate_confirmed"] is False
    refused = as_admin.post(f"/api/v1/shipments/{kids[1].id}/quotes/finalize", json={})
    assert refused.status_code == 409
    confirmed = as_admin.post(f"/api/v1/shipments/{kids[1].id}/quotes/confirm-rate", json={})
    assert confirmed.status_code == 200 and confirmed.json()["rate_confirmed"] is True
    final = as_admin.post(f"/api/v1/shipments/{kids[1].id}/quotes/finalize", json={})
    assert final.status_code == 200, final.text
    body = final.json()
    assert body["status"] == "finalized" and body["base_revenue_cad"] == "114.00"  # 6 kg x 19
    assert any(line["kind"] == "surcharge" and line["is_trigger"] for line in body["lines"])
    listed = as_admin.get(f"/api/v1/shipments/{kids[1].id}/quotes").json()
    assert [v["status"] for v in listed] == ["finalized"]

    settings = as_admin.get("/api/v1/pricing/settings").json()
    assert (
        settings["air_standard_default_rate_cad"] == "18.00"
        and settings["defaults_owner_confirmed"] is True
    )
    policy = as_admin.patch(
        "/api/v1/pricing/surcharge-policies/hcm_air/14",
        json={"markup_kind": "percent", "markup_value": "10"},
    )
    assert policy.status_code == 200
    # The default markup on surcharges (owner, 2026-10-20: 2 %) is a setting too.
    assert (settings["default_markup_kind"], settings["default_markup_value"]) == (
        "percent",
        "2.00",
    )
    changed = as_admin.patch(
        "/api/v1/pricing/settings",
        json={"default_markup_kind": "fixed_cad", "default_markup_value": "1.50"},
    )
    assert changed.status_code == 200, changed.text
    assert changed.json()["default_markup_kind"] == "fixed_cad"
    assert changed.json()["default_markup_value"] == "1.50"
    assert (
        as_admin.patch(
            "/api/v1/pricing/settings", json={"default_markup_kind": "bonus"}
        ).status_code
        == 422
    )
    assert (
        as_admin.patch("/api/v1/pricing/settings", json={"default_markup_value": "-1"}).status_code
        == 422
    )


def test_permissions(api_for, db, priced_world):
    _con, kids = priced_world
    operations = api_for(Role.OPERATIONS)
    assert operations.post(f"/api/v1/shipments/{kids[0].id}/quotes").status_code == 201
    assert (
        operations.post(
            f"/api/v1/shipments/{kids[0].id}/quotes/confirm-rate",
            json={"rate": "17", "reason": "volume"},
        ).status_code
        == 200
    )
    # Operations may not change the defaults or the markups.
    assert (
        operations.patch(
            "/api/v1/pricing/settings", json={"air_standard_default_rate_cad": "20"}
        ).status_code
        == 403
    )
    assert (
        operations.patch("/api/v1/pricing/surcharge-policies/hcm_air/14", json={}).status_code
        == 403
    )
    assert (
        operations.patch("/api/v1/pricing/settings", json={"default_markup_value": "5"}).status_code
        == 403
    )
    for role in (Role.MARKETING, Role.READ_ONLY_MANAGER):
        client = api_for(role)
        assert client.get(f"/api/v1/shipments/{kids[0].id}/quotes").status_code == 403
        assert client.get("/api/v1/pricing/settings").status_code == 403
        assert client.post(f"/api/v1/shipments/{kids[0].id}/quotes").status_code == 403


def test_no_quote_figure_reaches_the_public_page(client, db, priced_world):
    _con, kids = priced_world
    ps.confirm_rate(db, kids[0], rate=None, reason=None, actor=None)
    ps.finalize(db, kids[0], negative_margin_reason=None, actor=None)
    db.commit()
    see_committed_changes(db)
    client.cookies.clear()
    text = client.get(f"/api/v1/public/track/{kids[0].public_id}").text
    for forbidden in ("selling_rate", "revenue", "18.00", "54.00", "quote", "margin", "cost"):
        assert forbidden not in text, forbidden


def test_finalised_quotes_hold_their_shipment(db, priced_world):
    """A finalised quote is a financial record: its shipment cannot be deleted under it."""
    from sqlalchemy.exc import IntegrityError  # noqa: PLC0415

    _con, kids = priced_world
    ps.confirm_rate(db, kids[0], rate=None, reason=None, actor=None)
    ps.finalize(db, kids[0], negative_margin_reason=None, actor=None)
    db.commit()
    assert db.query(QuoteVersion).filter_by(shipment_id=kids[0].id).count() == 1
    db.delete(kids[0])
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()


# --- Independent review, 2026-10-20 ----------------------------------------------------------------


def test_a_policy_or_default_rate_change_revokes_the_confirmation(db, priced_world, users):
    _con, kids = priced_world
    _fee(db, kids[0], "hcm_air", 18, description="Watch")
    ps.confirm_rate(db, kids[0], rate=None, reason=None, actor=None)
    db.commit()
    ps.set_policy(db, "hcm_air", 18, {"markup_kind": "percent", "markup_value": "50"}, actor=None)
    draft, _ = ps.reprice(db, kids[0], actor=None)
    db.commit()
    assert draft.rate_confirmed_at is None

    ps.confirm_rate(db, kids[0], rate=None, reason=None, actor=None)
    db.commit()
    # Under v0.5 a 3 kg customer takes the under-21 kg rate, a method setting (DEC-0252).
    pms.update_method_settings(db, {"air_std_rate_low_cad": "25.00"}, actor=users[Role.ADMIN])
    draft, _ = ps.reprice(db, kids[0], actor=None)
    db.commit()
    # Unconfirmed and not overridden: the draft follows the new default.
    assert draft.rate_confirmed_at is None and draft.selling_rate_cad == Decimal("25.00")
    actions = [a.action for a in db.query(AuditEvent)]
    assert "quote.draft_open" in actions and actions.count("quote.confirmation_revoked") == 2


def test_a_tiered_or_manual_rule_cannot_be_made_master_wide(db, priced_world):
    for stt in (27, 1):
        with pytest.raises(ValidationError, match="whole master"):
            ps.set_policy(db, "hcm_air", stt, {"scope_override": "full_master"}, actor=None)
        db.rollback()
    with pytest.raises(ValidationError, match="air"):
        ps.set_policy(db, "sea_ca_au_uk_eu", 1, {}, actor=None)
    db.rollback()
    with pytest.raises(NotFoundError):
        ps.set_policy(db, "hcm_air", 999, {}, actor=None)


def test_a_vendor_price_is_refused_on_a_fixed_price_rule(db, priced_world):
    _con, kids = priced_world
    item = items.add_item(db, kids[0], {"description": "Watch"}, actor=None)
    db.commit()
    with pytest.raises(ValidationError, match="fixed price"):
        ps.add_fee_line(
            db,
            kids[0],
            {"item_id": item.id, "section": "hcm_air", "stt": 18, "manual_unit_price_vnd": "1"},
            actor=None,
        )


def test_a_per_piece_tier_is_charged_once_per_master_piece_whatever_the_quantity(db, priced_world):
    """DEC-0276: the kiện is the master piece; a quantity on the line does not multiply it."""
    con, kids = priced_world
    _fee(db, kids[0], "hcm_air", 1, description="Sơn móng", weight_kg="4", quantity=2)
    est, _ = ps.estimate_for(db, con)
    assert next(f for f in est.fees if f.stt == 1).vendor_fee_vnd == Decimal(300_000)


def test_cartons_are_fixed_once_the_master_is_closed(db, priced_world):
    con, _kids = priced_world
    con.state = "completed"
    db.commit()
    with pytest.raises(ConflictError, match="no longer change"):
        ps.replace_cartons(db, con, [{"weight_kg": "3"}], actor=None)


def test_a_scope_only_policy_keeps_the_default_markup(db, priced_world):
    """Review 2026-10-20: a policy that names no markup inherits the default (OD-74). Under
    v0.5 the default it inherits is the method's markup setting (DEC-0252)."""
    con, kids = priced_world
    pms.update_method_settings(db, {"markup_kind": "percent", "markup_value": "2"}, actor=None)
    row = ps.set_policy(db, "hcm_air", 18, {"note": "scope only"}, actor=None)
    assert row.markup_kind == "default"
    _fee(db, kids[0], "hcm_air", 18, description="Watch", quantity=2)
    est, _version = ps.estimate_for(db, con)
    fee = next(f for f in est.fees if f.stt == 18)
    assert (fee.markup_kind, fee.markup_value) == ("percent", Decimal("2.00"))
    assert fee.customer_total_cad > fee.customer_base_cad


def test_the_default_markup_is_bounded_and_rounded(db):
    with pytest.raises(ValidationError):
        ps.update_markup_default(db, "percent", "200", actor=None)
    db.rollback()
    row = ps.update_markup_default(db, "percent", "2.345", actor=None)
    assert row.id == 1 and row.markup_value == Decimal("2.35")
