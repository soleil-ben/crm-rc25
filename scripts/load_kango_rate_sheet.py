"""Load a Kango rate sheet as a new, effective-dated tariff version (method v0.6, DEC-0254).

Imports the workbook through the normal tariff importer (every product, both origins, every
zone, prices as the sheet shows them; the import is audited and its SHA-256 recorded) and, with
``--activate``, makes it the version that new masters price against. Booked masters keep the
version they were booked under; older versions are superseded, never deleted.

Usage (from the repository root, against the database in ``DATABASE_URL``)::

    backend/.venv/bin/python scripts/load_kango_rate_sheet.py \
        backend/tests/fixtures/kango_canada_rates_2026-11-03_sanitized.xlsx \
        --effective 2026-11-03 --activate

The 2026-11-03 sheet: HCM Air Standard zone 2 21-44 kg 260,000 VND/kg (HCM-AIR-CAD!C50), 5 kg
bill 1,629,138.1 (C17); HAN zone 2 21-44 kg 268,000 (HN-AIR-CAD!C49); fixed FX 19,500.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.core.db import SessionLocal  # noqa: E402
from app.services import tariff_import_service as tis  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("workbook", type=Path)
    parser.add_argument("--effective", required=True, type=date.fromisoformat)
    parser.add_argument("--label", default=None)
    parser.add_argument("--activate", action="store_true")
    args = parser.parse_args(argv)
    with SessionLocal() as db:
        version = tis.import_workbook(
            db,
            args.workbook.read_bytes(),
            file_name=args.workbook.name,
            effective_from=args.effective,
            label=args.label,
            actor=None,
        )
        if args.activate:
            tis.activate_version(db, version, actor=None)
        db.commit()
        print(f"{version.public_id} effective {args.effective} status {version.status}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
