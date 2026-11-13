"""Demo pricing data for the workspace (Phase 13D): a tariff, an exchange rate, a master.

    python -m app.seed_pricing                  # tariff + exchange rate
    python -m app.seed_pricing --with-master    # ... and an open air master with 3 members
    python -m app.seed_pricing --refresh-fx     # only a fresh demo exchange-rate reading

Runs after ``app.seed`` against a scratch database (the end-to-end run, or the workspace demo
built by ``scripts/workspace_demo_env.py``). Refused in production and wherever demo seeding
is off, exactly like ``app.seed``.

**No network.** The tariff is the sanitized Kango fixture committed with the tests (no staff
directory sheet). The exchange rate is a fixed demo reading parsed by the real Vietcombank
parser, recorded with source ``demo://fixture`` so it can never be mistaken for a bank
reading; nothing here calls the bank or the vendor. A reading counts as live for
``FX_STALE_AFTER_MINUTES`` (a day by default); ``--refresh-fx`` adds a new one.

Air only (OD-49): the master is Air Standard from Hồ Chí Minh City.
"""

from __future__ import annotations

import argparse
from datetime import date
from decimal import Decimal
from pathlib import Path

from sqlalchemy import select

from app.core.config import settings
from app.core.db import SessionLocal
from app.core.enums import RouteGroup
from app.core.time_utils import utcnow
from app.models import Consolidation, Shipment
from app.services import consolidation_service, fx_service, shipment_item_service
from app.services import tariff_import_service as tis
from app.services.errors import ConflictError, ValidationError

#: The sanitized workbook: the vendor's rates without the staff phone directory. Since method
#: v0.7 (Louis, 2026-11-03; DEC-0264) the 2026-11-03 sheet is the demo / UAT active version.
WORKBOOK = (
    Path(__file__).resolve().parents[1]
    / "tests"
    / "fixtures"
    / "kango_canada_rates_2026-11-03_sanitized.xlsx"
)
DEMO_FX_SOURCE = "demo://fixture"
DEMO_MASTER_REFERENCE = "DEMO-AWB-0001"

#: (description, quantity, unit, kg) per demo member; one surcharge-worthy line each.
DEMO_ITEMS = (
    ("Quần áo (demo)", Decimal(4), "piece", Decimal("2.5")),
    ("Đồng hồ (demo)", Decimal(1), "piece", Decimal("0.4")),
    ("Sơn móng tay (demo)", Decimal(12), "bottle", Decimal("1.8")),
)


#: The only databases this module writes to: an end-to-end scratch database or the
#: workspace demo database. A demo exchange rate in the development database would become
#: "the latest rate" there, so anything else is refused by name.
ALLOWED_SUFFIXES = (".e2e.db", ".demo.db")


def _guard() -> None:
    if settings.is_production or not settings.allow_demo_seed:
        raise SystemExit(
            "Refusing to seed: demo data is disabled for this environment. "
            "Set ENVIRONMENT=development and ALLOW_DEMO_SEED=true to seed a local database."
        )
    path = settings.sqlite_path
    if path is None or not path.name.endswith(ALLOWED_SUFFIXES):
        raise SystemExit(
            f"Refusing to seed demo pricing into {path or settings.database_url}: only an "
            "end-to-end (.e2e.db) or workspace demo (.demo.db) database may hold it."
        )


def _demo_xml(now) -> bytes:
    stamp = now.strftime("%m/%d/%Y %I:%M:%S %p")
    return (
        '<?xml version="1.0" encoding="utf-8"?><ExrateList>'
        f"<DateTime>{stamp}</DateTime>"
        '<Exrate CurrencyCode="CAD" CurrencyName="CANADIAN DOLLAR" Buy="17,886.61" '
        'Transfer="18,067.28" Sell="18,645.39"/><Source>demo</Source></ExrateList>'
    ).encode()


def add_demo_fx(db) -> None:
    now = utcnow()
    result = fx_service.sync_once(
        db,
        fetcher=lambda _url: _demo_xml(now),
        clock=lambda: now,
        worker_name="demo-seed",
        url=DEMO_FX_SOURCE,
    )
    if result.snapshot is None:
        raise SystemExit(f"The demo exchange rate was refused: {result.error}")


def import_tariff(db) -> None:
    if tis.active_version(db, tis.KANGO_VENDOR_KEY) is not None:
        return
    version = tis.import_workbook(
        db,
        WORKBOOK.read_bytes(),
        file_name=WORKBOOK.name,
        effective_from=date(2026, 11, 3),
        label="Kango 2026-11-03 (sanitized demo)",
        actor=None,
    )
    tis.activate_version(db, version, actor=None)


def add_demo_master(db) -> Consolidation | None:
    existing = db.scalar(
        select(Consolidation).where(Consolidation.vendor_reference == DEMO_MASTER_REFERENCE)
    )
    if existing is not None:
        return existing
    master = consolidation_service.create_consolidation(
        db,
        {
            "solaris_service": "air_standard",
            "origin": "HCM",
            "vendor_reference": DEMO_MASTER_REFERENCE,
            "actual_weight_kg": "21",
            "length_cm": "60",
            "width_cm": "40",
            "height_cm": "40",
            "carton_count": 3,
        },
        actor=None,
    )
    candidates = db.scalars(
        select(Shipment)
        .where(Shipment.route_group == RouteGroup.VCA, Shipment.public_id.is_not(None))
        .order_by(Shipment.id)
    )
    members: list[Shipment] = []
    for shipment in candidates:
        try:
            with db.begin_nested():
                consolidation_service.add_member(db, master, shipment, actor=None)
        except (ConflictError, ValidationError):
            continue
        members.append(shipment)
        if len(members) == len(DEMO_ITEMS):
            break
    for shipment, (description, quantity, unit, kg) in zip(members, DEMO_ITEMS, strict=False):
        shipment_item_service.add_item(
            db,
            shipment,
            {"description": description, "quantity": quantity, "unit": unit, "weight_kg": kg},
            actor=None,
        )
    return master


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--with-master", action="store_true")
    parser.add_argument("--refresh-fx", action="store_true")
    args = parser.parse_args(argv)
    _guard()
    with SessionLocal() as db:
        if args.refresh_fx:
            add_demo_fx(db)
            db.commit()
            print("Added a fresh demo exchange-rate reading (source demo://fixture).")
            return 0
        import_tariff(db)
        add_demo_fx(db)
        db.commit()
        print("Activated the sanitized Kango tariff and recorded a demo exchange rate.")
        if args.with_master:
            master = add_demo_master(db)
            db.commit()
            if master is not None:
                print(f"Open air master {master.public_id} ({DEMO_MASTER_REFERENCE}) is ready.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
