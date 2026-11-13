"""The workspace demo data (Phase 13D): no network, demo-labelled, refused where it must be."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from app import seed_pricing
from app.core.enums import RouteGroup
from app.models import Consolidation, FxRateSnapshot, ShipmentItem
from app.services import fx_service
from app.services import tariff_import_service as tis
from tests.conftest import booked_shipment, make_customer

REPO_ROOT = Path(__file__).resolve().parents[2]


def _demo_env_module():
    spec = importlib.util.spec_from_file_location(
        "workspace_demo_env", REPO_ROOT / "scripts" / "workspace_demo_env.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["workspace_demo_env"] = module
    spec.loader.exec_module(module)
    return module


def test_the_seeder_never_calls_the_bank(db, monkeypatch):
    def refuse(_url):
        raise AssertionError("the demo seed must not fetch anything")

    monkeypatch.setattr(fx_service, "default_fetcher", refuse)
    seed_pricing.import_tariff(db)
    seed_pricing.add_demo_fx(db)
    db.commit()
    assert tis.active_version(db, tis.KANGO_VENDOR_KEY) is not None
    snapshot = db.query(FxRateSnapshot).one()
    assert snapshot.source_url == seed_pricing.DEMO_FX_SOURCE
    assert fx_service.freshness(snapshot).value == "live"
    # Importing again is a no-op, not a duplicate-file refusal.
    seed_pricing.import_tariff(db)


def test_the_demo_master_is_air_and_takes_eligible_shipments_only(db):
    seed_pricing.import_tariff(db)
    db.commit()
    for i in range(4):
        booked_shipment(db, make_customer(db, email=f"ws{i}@demo.example.com"), RouteGroup.VCA)
    booked_shipment(db, make_customer(db, email="cav@demo.example.com"), RouteGroup.CAV)
    db.commit()
    master = seed_pricing.add_demo_master(db)
    db.commit()
    assert (master.solaris_service, master.origin) == ("air_standard", "HCM")
    assert db.query(ShipmentItem).count() == 3
    # Idempotent: a second run finds the same master.
    assert seed_pricing.add_demo_master(db).id == master.id
    assert db.query(Consolidation).count() == 1


def test_the_seeder_refuses_where_demo_data_is_off(monkeypatch):
    monkeypatch.setattr(seed_pricing.settings, "allow_demo_seed", False)
    with pytest.raises(SystemExit, match="Refusing"):
        seed_pricing._guard()


@pytest.mark.parametrize(
    ("url", "allowed"),
    [
        ("sqlite:///C:/x/data/solaris_crm.db", False),
        ("sqlite:///C:/x/data/uat/solaris_uat.uat.db", False),
        ("sqlite:///C:/x/data/e2e/ab/solaris.e2e.db", True),
        ("sqlite:///C:/x/data/workspace_demo/solaris_workspace.demo.db", True),
    ],
)
def test_the_seeder_writes_only_to_a_scratch_or_demo_database(monkeypatch, url, allowed):
    monkeypatch.setattr(seed_pricing.settings, "allow_demo_seed", True)
    monkeypatch.setattr(seed_pricing.settings, "database_url", url)
    if allowed:
        seed_pricing._guard()
    else:
        with pytest.raises(SystemExit, match="only an"):
            seed_pricing._guard()


def test_the_demo_database_target_is_fenced(monkeypatch):
    env = _demo_env_module()
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("ENVIRONMENT", "development")
    assert env.validated_target(env.DEMO_DB) == env.DEMO_DB.resolve()
    for refused in (
        env.DEV_DB,
        env.UAT_DIR / "solaris_uat.demo.db",
        env.DEMO_DIR / "elsewhere.db",
        REPO_ROOT / "solaris_workspace.demo.db",
    ):
        with pytest.raises(env.SafetyError):
            env.validated_target(refused)
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{env.DEMO_DB.as_posix()}")
    with pytest.raises(env.SafetyError, match="DATABASE_URL"):
        env.validated_target(env.DEMO_DB)
    monkeypatch.delenv("DATABASE_URL")
    monkeypatch.setenv("ENVIRONMENT", "production")
    with pytest.raises(env.SafetyError, match="production"):
        env.validated_target(env.DEMO_DB)
