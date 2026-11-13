"""Produce the test-fixture copy of a Kango tariff workbook.

The vendor's workbook carries two things the repository must not: a sheet listing the
vendor's own operations staff by name with personal mobile numbers, and a corporate
contact block (addresses, mailboxes, hotlines) repeated in the header of every rate sheet.
Neither is tariff data. The importer skips the staff sheet outright and never reads the
header block, but a fixture committed to git is copied to every clone, so the fixture is
made from a sanitized copy rather than the original.

What this removes:

* the sheet whose name starts with ``DS SDT`` (the staff directory), entirely;
* the corporate header cell ``B1`` on every remaining sheet, blanked;
* nothing else. Every rate, zone, postal code, surcharge row and note is left exactly as
  the vendor wrote it, so a test against the fixture is a test against the real tariff.

The output file's SHA-256 is printed; the importer records the hash of whatever file it is
given, so a version imported from the fixture is distinguishable from one imported from the
vendor's original.

Usage (from the repository root)::

    backend/.venv/Scripts/python scripts/sanitize_kango_workbook.py \
        "<path to KANGO-CANADA RATES APPLY 12OCT 2026.xlsx>" \
        backend/tests/fixtures/kango_canada_rates_2026-10-12_sanitized.xlsx
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import openpyxl

STAFF_SHEET_PREFIX = "DS SDT"
HEADER_CELL = "B1"


def sanitize(source: Path, destination: Path) -> str:
    workbook = openpyxl.load_workbook(source)
    removed = [name for name in workbook.sheetnames if name.upper().startswith(STAFF_SHEET_PREFIX)]
    for name in removed:
        del workbook[name]
    for sheet in workbook.worksheets:
        if sheet[HEADER_CELL].value is not None:
            sheet[HEADER_CELL].value = None
    destination.parent.mkdir(parents=True, exist_ok=True)
    workbook.save(destination)
    digest = hashlib.sha256(destination.read_bytes()).hexdigest()
    # Sheet names are Vietnamese; a Windows console may not be able to print them, and the
    # count is what matters.
    print(f"removed {len(removed)} staff-directory sheet(s)")
    print(f"blanked {HEADER_CELL} on {len(workbook.worksheets)} sheets")
    print(f"{destination} sha256 {digest}")
    return digest


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(__doc__)
        return 2
    sanitize(Path(argv[1]), Path(argv[2]))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
