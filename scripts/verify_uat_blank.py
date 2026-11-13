#!/usr/bin/env python
"""Verify that no UAT record field has been filled in.

Two kinds of field live in the UAT packs and the review sheets, and the whole point of
this script is that they are never confused:

* **prewritten** -- the case definition, and the content being reviewed. `Evidence to
  capture` belongs here: it tells a tester what to collect and is written in advance.
* **recorded** -- what a human actually observed. `Evidence obtained`, `Result`,
  `Defect`, `Tester`, `Date`, every reviewer response and every sign-off belong here, and
  every one of them must be blank until a person fills it in.

A prewritten instruction is not evidence that a case was executed. Before RC-UAT-4 was
handed to a tester the packs carried a single `Evidence` row holding prewritten text,
which a reader -- or a script counting non-blank cells -- could mistake for a record. The
row was split in two so the distinction is checkable rather than assumed.

Exit status 1 means something has been recorded. That is not automatically wrong -- a pass
in progress will trip it -- but it must never be true of a candidate presented as
unexecuted.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
UAT = REPO_ROOT / "docs" / "UAT"

STAFF_PACK = UAT / "UAT_CASES.md"
ACCOUNT_PACK = UAT / "CUSTOMER_ACCOUNT_UAT_PACK.md"
#: Phase 17: the air pricing, quotes and money pack (Phases 13A to 15).
AIR_PACK = UAT / "AIR_UAT_PACK.md"

EXPECTED_STAFF_CASES = 49
#: 59 by DEC-0136; 60 since CA-SHP-20 was added (DEC-0162).
EXPECTED_ACCOUNT_CASES = 60
#: 36 by DEC-0218: WSQ 7, QAC 4, FIN 8, PRC 4, TAR 5, MLS 4, VIA 4; 53 since RC-UAT-18 added
#: OWN 17 (the owner answers of 2026-10-21, OD-81 to OD-90); 63 since RC-UAT-19 added OWN-18
#: to OWN-27 (the owner answers of 2026-10-22, OD-91 to OD-101); 71 since RC-UAT-20 added
#: OWN-28 to OWN-35 (the owner answers of 2026-10-23, OD-102 to OD-108); 104 since RC-UAT-25
#: added BLD-26 to BLD-33 (Ben's live UAT of 2026-10-25, OD-113: asterisks, the currency list,
#: the saved recipient, the old email-change link, "Received at warehouse", editing a published
#: event, the Financials tab) and withdrew BLD-10 (its heading and blank table are kept, so it
#: still counts); 96 since RC-UAT-24 added BLD-25 (the legal entity, I-10; the draft
#: editor's wording, I-11); 95 since RC-UAT-23 added BLD-20 to BLD-24 (invoices on the
#: Solaris Invoicing layout, OD-111); 90 since RC-UAT-22 added BLD-18 and BLD-19 (B-13, the
#: orphaned-account re-link and close); 88 since RC-UAT-21 added BLD-01 to BLD-17 (the build
#: of 2026-10-24, OD-110: imports, account security, reinstatement, quote tax wording, quote
#: soft delete, retention).
EXPECTED_AIR_CASES = 104
EXPECTED_REVIEW_SHEETS = 5

#: Row labels in a case table that a human fills in. Every one must be blank.
RECORDED_LABELS = {
    "Evidence obtained",
    "Result",
    "Defect",
    "Tester",
    "Date",
    "Executed",
    "Passed",
    "Failed",
    "Blocked",
    "Defects raised",
    "Operations reviewer",
    "Owner acceptance",
}

#: Row labels written in advance. Every one must carry text -- a blank prewritten field
#: means a case lost part of its definition.
PREWRITTEN_LABELS = {
    "Role",
    "Steps",
    "Expected",
    "Privacy / permission",
    "Evidence to capture",
}

#: Column headers in a review sheet that hold prewritten content rather than an answer.
CONTENT_COLUMNS = {
    "",
    "#",
    "Check",
    "Field",
    "Question",
    "Item",
    "Expected",
    "Must never appear",
    "Sent when",
    "Content under review",
    # the field-class legend each sheet carries
    "Class",
    "What it is",
    "State before review",
}

ROW = re.compile(r"^\|\s*\*{0,2}(.+?)\*{0,2}\s*\|(.*)\|\s*$")
#: `CA-XP` is two letters where every other Customer Account group is three; the air
#: pack's groups (`UAT-WSQ`, `UAT-FIN`, ...) are three letters too.
CASE_HEADING = re.compile(r"^#{2,4}\s+((?:UAT|CA)-[A-Z]{2,3}-\d+)")


def is_blank(cell: str) -> bool:
    """True when a row's value side holds nothing.

    The value side of a sign-off row spans several columns -- `| Tester | | | |` -- so a
    bare truth test on the captured text would read the column separators as content.
    """
    return not cell.replace("|", "").strip()


def is_content_column(header: str) -> bool:
    return header in CONTENT_COLUMNS or "(content under review)" in header


class Report:
    def __init__(self) -> None:
        self.problems: list[str] = []
        self.lines: list[str] = []

    def ok(self, label: str, value: object) -> None:
        self.lines.append(f"  ok    {label:<54} {value}")

    def bad(self, label: str, value: object, detail: str) -> None:
        self.lines.append(f"  FAIL  {label:<54} {value}")
        self.problems.append(detail)


def check_pack(path: Path, expected_cases: int, report: Report) -> None:
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()

    cases = [m.group(1) for line in lines if (m := CASE_HEADING.match(line))]
    unique = sorted(set(cases))
    if len(unique) == expected_cases == len(cases):
        report.ok(f"{path.name} cases", len(unique))
    else:
        report.bad(
            f"{path.name} cases",
            f"{len(cases)} headings, {len(unique)} distinct, expected {expected_cases}",
            f"{path.name}: case count changed",
        )

    per_label: dict[str, list[tuple[int, str]]] = {}
    for number, line in enumerate(lines, 1):
        match = ROW.match(line)
        if not match:
            continue
        label, cell = match.group(1).strip(), match.group(2)
        per_label.setdefault(label, []).append((number, cell))

    for label in sorted(RECORDED_LABELS):
        rows = per_label.get(label, [])
        if not rows:
            continue
        filled = [(n, c.strip()) for n, c in rows if not is_blank(c)]
        if filled:
            report.bad(
                f"{path.name} '{label}' rows blank",
                f"{len(filled)} of {len(rows)} filled",
                f"{path.name}: '{label}' recorded at line(s) "
                + ", ".join(str(n) for n, _ in filled[:10]),
            )
        else:
            report.ok(f"{path.name} '{label}' rows blank", f"{len(rows)} rows, 0 filled")

    for label in sorted(PREWRITTEN_LABELS):
        rows = per_label.get(label, [])
        empty = [n for n, c in rows if is_blank(c)]
        if empty:
            report.bad(
                f"{path.name} '{label}' rows written",
                f"{len(empty)} of {len(rows)} empty",
                f"{path.name}: prewritten '{label}' is empty at line(s) "
                + ", ".join(str(n) for n in empty[:10]),
            )
        else:
            report.ok(f"{path.name} '{label}' rows written", f"{len(rows)} rows, 0 empty")

    capture = len(per_label.get("Evidence to capture", []))
    obtained = len(per_label.get("Evidence obtained", []))
    if capture == obtained == expected_cases:
        report.ok(
            f"{path.name} evidence rows paired",
            f"{capture} to capture / {obtained} obtained",
        )
    else:
        report.bad(
            f"{path.name} evidence rows paired",
            f"{capture} to capture / {obtained} obtained, expected {expected_cases} of each",
            f"{path.name}: every case needs one 'Evidence to capture' and one blank "
            "'Evidence obtained'",
        )

    if "| **Evidence** |" in text:
        report.bad(
            f"{path.name} no bare 'Evidence' row",
            "found",
            f"{path.name}: a bare 'Evidence' row is ambiguous -- it must be "
            "'Evidence to capture' or 'Evidence obtained'",
        )
    else:
        report.ok(f"{path.name} no bare 'Evidence' row", "none")


def check_review_sheet(path: Path, report: Report) -> None:
    header: list[str] | None = None
    cells = 0
    filled: list[tuple[int, str, str]] = []

    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        stripped = line.strip()
        if not stripped.startswith("|"):
            header = None
            continue
        columns = [c.strip() for c in stripped.strip("|").split("|")]
        if set("".join(columns)) <= set("-: "):
            continue
        if header is None:
            header = columns
            continue
        for index, cell in enumerate(columns):
            name = header[index] if index < len(header) else ""
            if is_content_column(name):
                continue
            cells += 1
            if not is_blank(cell):
                filled.append((number, name, cell.strip()[:60]))

    if filled:
        report.bad(
            f"{path.name} response cells blank",
            f"{len(filled)} of {cells} filled",
            f"{path.name}: recorded at line(s) " + ", ".join(str(n) for n, _, _ in filled[:10]),
        )
    else:
        report.ok(f"{path.name} response cells blank", f"{cells} cells, 0 filled")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify that no UAT result, evidence or sign-off field has been filled in."
    )
    parser.parse_args()

    report = Report()

    check_pack(STAFF_PACK, EXPECTED_STAFF_CASES, report)
    check_pack(ACCOUNT_PACK, EXPECTED_ACCOUNT_CASES, report)
    check_pack(AIR_PACK, EXPECTED_AIR_CASES, report)

    sheets = sorted(UAT.glob("REVIEW_*.md"))
    if len(sheets) == EXPECTED_REVIEW_SHEETS:
        report.ok("review sheets present", len(sheets))
    else:
        report.bad(
            "review sheets present",
            f"{len(sheets)}, expected {EXPECTED_REVIEW_SHEETS}",
            "the set of review sheets changed",
        )
    for sheet in sheets:
        check_review_sheet(sheet, report)

    print("UAT record fields")
    print()
    for line in report.lines:
        print(line)
    print()

    if report.problems:
        print(f"{len(report.problems)} problem(s):")
        for problem in report.problems:
            print(f"  - {problem}")
        return 1

    print("Every recorded field is blank and every prewritten field is written.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
