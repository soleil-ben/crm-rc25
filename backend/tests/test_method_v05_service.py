"""Method v0.5 wired through the pricing service (Louis, 2026-11-02).

The arithmetic is pinned by ``test_method_v05_golden.py`` (case study S1–S5); this module covers
the switch and the database side: RC-UAT-25 stays the default, the settings and per-master
inputs are read from the five new tables, a quote version priced under v0.5 is confirmed and
finalised with Kango's fixed rate and snapshots the method it used, and the migration adds and
removes exactly its tables.
"""

from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from decimal import Decimal
from pathlib import Path

import pytest

from app.models import PricingMethodSettings, SurchargeAllocationClass
from app.services import pricing_method_service as pms
from app.services import pricing_service as ps
from app.services.errors import ValidationError
from tests.test_quotes import _fee, priced_world  # noqa: F401  (fixture)

D = Decimal
BACKEND_ROOT = Path(__file__).resolve().parent.parent
V05_TABLES = {
    "pricing_method_settings",
    "sea_vendor_rates",
    "sea_surcharge_rules",
    "consolidation_package_notes",
    "consolidation_package_members",
    "consolidation_package_flags",
    "consolidation_manual_pricing",
    "ups_rate_bands",
    "surcharge_allocation_classes",
}


def _switch_on(db, **extra):
    pms.seed_allocation_classes(db)
    pms.update_method_settings(db, {"pricing_method": "v0_5", **extra}, actor=None)
    db.commit()


def _row(est, shipment):
    return est.method_detail["members"][shipment.id]


def test_v05_is_the_default(db, priced_world):  # noqa: F811
    """DEC-0252 / DEC-0253: the owner's confirmed method (v0.6) is the default."""
    con, _kids = priced_world
    assert pms.get_method_settings(db).pricing_method == "confirmed"
    est, _ = ps.estimate_for(db, con)
    assert est.method == "confirmed" and est.method_detail is not None


def test_rc25_stays_available_and_its_snapshot_keys_are_unchanged(db, priced_world):  # noqa: F811
    con, _kids = priced_world
    pms.update_method_settings(db, {"pricing_method": "rc25"}, actor=None)
    db.commit()
    est, _ = ps.estimate_for(db, con)
    assert est.method == "rc25" and est.method_detail is None
    assert est.base_freight_vnd == D(243_000) * 21
    assert "method_detail" not in ps.estimate_dict(est) and "method" not in ps.estimate_dict(est)


def test_v05_prices_the_case_study_on_the_active_tariff(db, priced_world):  # noqa: F811
    """S4 on the repository's 2026-10-12 tariff (243,000 VND/kg): nail polish on the 3 kg
    customer, fake clothing on the 6 kg customer only."""
    con, kids = priced_world
    _fee(db, kids[0], "hcm_air", 1, description="Sơn móng tay", weight_kg="3")
    _fee(db, kids[1], "hcm_air", 14, description="Quần áo fake", weight_kg="4")
    _switch_on(db)
    est, _ = ps.estimate_for(db, con)
    assert est.method == "confirmed"
    assert not est.blocking, est.blocking
    v = est.method_detail
    assert v["fx"]["cost_source"] == v["fx"]["quote_source"] == "kango_fixed"
    assert v["fx"]["cost_rate_vnd"] == D(19_500)
    assert v["bill_kg"] == D(21) and v["base_vnd"] == D(243_000) * 21
    fake = next(ln for ln in v["lines"] if ln["stt"] == 14)
    assert fake["class"] == "WHOLE_PACKAGE" and fake["vendor_vnd"] == D(630_000)
    assert fake["cost_alloc_vnd"] == {
        kids[0].id: D(105_000),
        kids[1].id: D(420_000),
        kids[2].id: D(105_000),
    }
    expected = {  # cost CAD, quote CAD, rate
        kids[0].id: (D("58.15"), D("77.77"), D(19)),
        kids[1].id: (D("96.31"), D("135.54"), D(19)),
        kids[2].id: (D("154.92"), D("233.38"), D(19)),
    }
    for sid, (cost, quote, rate) in expected.items():
        row = v["members"][sid]
        assert (row["cost_cad"], row["quote_cad"], row["rate_cad_kg"]) == (cost, quote, rate)
    assert v["totals"]["cost_cad"] == D("309.38") and v["reconciled"] is True


def test_v05_quote_is_confirmed_and_finalised_with_the_kango_rate(db, priced_world):  # noqa: F811
    con, kids = priced_world
    _fee(db, kids[0], "hcm_air", 1, description="Sơn móng tay", weight_kg="3")
    _switch_on(db)
    draft, est = ps.reprice(db, kids[0], actor=None)
    assert draft.default_rate_cad == D("19.00") and draft.selling_rate_cad == D("19.00")
    ps.confirm_rate(db, kids[0], rate=None, reason=None, actor=None)
    db.commit()
    final = ps.finalize(db, kids[0], negative_margin_reason=None, actor=None)
    db.commit()
    assert final.status == "finalized"
    assert final.total_revenue_cad == _row(est, kids[0])["quote_cad"] == D("72.38")
    assert final.allocated_cost_cad == _row(est, kids[0])["cost_cad"]
    assert final.fx_snapshot_id is None  # no bank snapshot is used under Kango's fixed rate
    snapshot = json.loads(final.snapshot_json)
    assert snapshot["estimate"]["method"] == "confirmed"
    assert snapshot["estimate"]["method_detail"]["fx"]["cost_source"] == "kango_fixed"
    lines = sum(D(str(ln.revenue_cad)) for ln in final.lines)
    assert lines == final.total_revenue_cad


def test_nail_polish_is_charged_once_per_master_piece_flag_or_not(db, priced_world):  # noqa: F811
    """DEC-0276 supersedes the per-small-box reading: Kango charges once per master piece, the
    band on the nail polish kg in the piece (3 + 6 = 9 kg → 500,000), with or without the
    "packed as one box" flag; each customer is quoted on its own kg."""
    con, kids = priced_world
    _fee(db, kids[0], "hcm_air", 1, description="Sơn móng tay", weight_kg="3")
    _fee(db, kids[1], "hcm_air", 1, description="Sơn móng tay", weight_kg="6")
    _switch_on(db)
    for packed in (False, True):
        if packed:
            ps.replace_cartons(
                db, con, [{"weight_kg": "21", "packed_as_one_box": True}], actor=None
            )
            db.commit()
            assert pms.package_flags(db, con.id) == {1: True}
        est, _ = ps.estimate_for(db, con)
        (nail,) = [ln for ln in est.method_detail["lines"] if ln["stt"] == 1]
        assert nail["vendor_vnd"] == D(500_000)
        assert nail["cost_alloc_vnd"] == {
            kids[0].id: D("166666.67"), kids[1].id: D("333333.33")
        }  # fmt: skip
        assert nail["quote_vnd"] == {kids[0].id: D(300_000), kids[1].id: D(500_000)}


def test_sea_and_express_settings(db, priced_world):  # noqa: F811
    con, _kids = priced_world
    _switch_on(db)
    con.solaris_service = "air_express"
    db.commit()
    est, _ = ps.estimate_for(db, con)
    # DEC-0271: Kango Air Express is priced on the rate sheet, no longer by hand.
    assert "express_manual_cost_missing" not in {i.code for i in est.blocking}
    # Overriding the rate-sheet cost needs a reason.
    with pytest.raises(ValidationError, match="reason"):
        pms.set_manual_pricing(db, con.id, {"manual_cost_vnd_per_kg": "330000"}, actor=None)
    db.rollback()
    pms.set_manual_pricing(
        db,
        con.id,
        {
            "manual_cost_vnd_per_kg": "330000",
            "manual_sell_cad_per_kg": "25",
            "reason": "Kango quoted a special rate",
        },
        actor=None,
    )
    db.commit()
    est, _ = ps.estimate_for(db, con)
    assert not est.blocking, est.blocking
    assert "base_cost_overridden" in {i.code for i in est.provisional}
    assert est.method_detail["base_vnd"] == D(330_000) * 21
    assert {r["rate_cad_kg"] for r in est.method_detail["members"].values()} == {D(25)}
    con.solaris_service = "sea"
    db.commit()
    est, _ = ps.estimate_for(db, con)
    assert {r["rate_cad_kg"] for r in est.method_detail["members"].values()} == {D(8)}


def test_settings_validation_and_audit(db):
    with pytest.raises(Exception, match="fx_source_cost"):
        pms.update_method_settings(db, {"fx_source_cost": "ecb"}, actor=None)
    row = pms.update_method_settings(
        db, {"fx_source_quote": "vcb_sell", "sea_rate_cad": "8.50"}, actor=None
    )
    db.commit()
    assert db.get(PricingMethodSettings, row.id).fx_source_quote == "vcb_sell"
    assert pms.engine_settings(db, ps.get_settings(db)).sea_rate_cad == D("8.50")


def test_allocation_classes_load_from_the_csv(db):
    # Without loaded rows the CSV's own classes are used (a create_all database).
    assert pms.allocation_class_map(db)[("hcm_air", 14)] == "WHOLE_PACKAGE"
    assert pms.seed_allocation_classes(db) == 70
    assert pms.seed_allocation_classes(db) == 0
    classes = pms.allocation_class_map(db)
    assert classes[("hcm_air", 1)] == "PARCEL"
    assert classes[("hcm_air", 14)] == "WHOLE_PACKAGE"
    assert classes[("hcm_air", 47)] == "WHOLE_MASTER"
    assert classes[("han_air", 6)] == "NONE"
    assert classes[("sea_ca_au_uk_eu", 6)] == "WHOLE_MASTER"
    assert db.query(SurchargeAllocationClass).count() == 70


def _alembic(url: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=BACKEND_ROOT,
        env={
            "PATH": "",
            "SYSTEMROOT": "C:\\Windows",
            "DATABASE_URL": url,
            "SECRET_KEY": "test-only-secret",
        },
        capture_output=True,
        text=True,
        check=False,
    )


def _tables(path: Path) -> set[str]:
    with sqlite3.connect(path) as conn:
        return {r[0] for r in conn.execute("select name from sqlite_master where type='table'")}


def test_migration_adds_and_removes_only_its_tables(tmp_path):
    path = tmp_path / "m.db"
    url = f"sqlite:///{path.as_posix()}"
    assert _alembic(url, "upgrade", "a5c7e9b1d3f6").returncode == 0
    before = _tables(path)
    up = _alembic(url, "upgrade", "head")
    assert up.returncode == 0, up.stderr
    # Head also carries DEC-0268's grant table, which is not a pricing table.
    later = {"staff_permission_grants", "consolidation_piece_tracking"}
    assert _tables(path) - before - later == V05_TABLES
    # head: b8d1f3a5c7e9 seeds rc25, c2e4a6b8d0f1 sets v0_5, d4f6a8c0e2b4 renames it v0_6,
    # e6a8c0e2b4d6 v0_7, f8b0d2e4a6c8 confirmed
    with sqlite3.connect(path) as conn:
        assert conn.execute(
            "select pricing_method, fx_source_cost, fx_source_quote, kango_fixed_rate_vnd, "
            "air_std_rate_low_cad, air_std_threshold_kg, sea_rate_cad, markup_kind, "
            "residual_mode, pkg_surcharge_billing, parcel_band_cost_basis, parcel_quote_mode "
            "from pricing_method_settings"
        ).fetchall() == [
            (
                "confirmed",
                "kango_fixed",
                "kango_fixed",
                19500,
                19,
                21,
                8,
                "none",
                "prorata",
                "same_as_cost",
                "box",
                "each",
            )
        ]
        assert conn.execute("select count(*) from surcharge_allocation_classes").fetchone() == (70,)
        assert conn.execute("select count(*) from ups_rate_bands").fetchone() == (5,)
        assert conn.execute(
            "select code, rate_vnd_per_kg, min_vnd_per_package from sea_surcharge_rules"
        ).fetchall() == [("SEA-FOOD", 30000, 400000), ("SEA-FUNCFOOD", 40000, 500000)]
        assert conn.execute("select sea_cost_vnd_per_kg from sea_vendor_rates").fetchall() == [
            (60000,)
        ]
    check = _alembic(url, "check")
    assert check.returncode == 0, check.stdout + check.stderr
    assert _alembic(url, "downgrade", "e6a8c0e2b4d6").returncode == 0
    with sqlite3.connect(path) as conn:
        assert conn.execute("select pricing_method from pricing_method_settings").fetchone() == (
            "v0_7",
        )
    assert _alembic(url, "downgrade", "d4f6a8c0e2b4").returncode == 0
    with sqlite3.connect(path) as conn:
        assert conn.execute("select pricing_method from pricing_method_settings").fetchone() == (
            "v0_6",
        )
    assert _alembic(url, "downgrade", "c2e4a6b8d0f1").returncode == 0
    with sqlite3.connect(path) as conn:
        assert conn.execute("select pricing_method from pricing_method_settings").fetchone() == (
            "v0_5",
        )
    assert _alembic(url, "downgrade", "b8d1f3a5c7e9").returncode == 0
    with sqlite3.connect(path) as conn:
        assert conn.execute("select pricing_method from pricing_method_settings").fetchone() == (
            "rc25",
        )
    assert _alembic(url, "downgrade", "a5c7e9b1d3f6").returncode == 0
    assert _tables(path) == before
