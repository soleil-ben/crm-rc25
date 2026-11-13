"""Verify the decision log, so a decision identifier cannot be used twice.

Why this exists
---------------
The role merge was first written up as ``DEC-0083``. ``DEC-0083`` was already taken — it
is the decision that a timeline event publishes to the customer by default — and so was
``DEC-0084``, both claimed by the customer public-update and template work between Phase 5A
and Phase 5B. The wrong number reached a migration docstring, two core modules and five
test files before anybody read the log.

Nothing in the repository would have objected. The log is prose, the citations are
comments, and neither knew about the other.

What it checks
--------------
1. **No identifier is defined twice.** Two ``### DEC-0083`` headings is the failure this
   command exists to make impossible, and it is checked first.
2. **Identifiers are contiguous from 0001**, with no gaps. This is the check that actually
   prevents the mistake that happened: a new decision has exactly one correct number, the
   one after the highest, and a gap is the only thing that could make a *used* number look
   free. A hole is a failure, not a footnote.
3. **Every ``DEC-NNNN`` cited anywhere in the repository resolves** to a heading in the
   log. A comment citing a decision nobody can look up is the same defect as a missing
   record.
4. **Every heading is a real record** — it has a title after the em dash, and a body.

What it deliberately does not check
-----------------------------------
That a citation cites the *right* decision. ``DEC-0083`` resolved perfectly well; it was
simply about something else, and no parser can see that. Check 2 is the structural guard —
it makes "take the next number" the only way to add a record — and the coverage table in
``docs/UAT/UAT_SUMMARY.md`` plus review are what catch a citation aimed at the wrong record.
Recording the limit here is better than implying a guarantee this cannot give.

Usage
-----

From the repository root (on Linux and macOS the interpreter is
``backend/.venv/bin/python`` rather than ``backend/.venv/Scripts/python``)::

    backend/.venv/Scripts/python scripts/verify_decision_log.py
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DECISION_LOG = REPO_ROOT / "docs" / "DECISIONS.md"

#: A decision record: a level-3 heading, the identifier, an em dash, and a title.
HEADING_PATTERN = re.compile(r"^### DEC-(\d{4})\s*(?:—\s*(.*))?$", re.MULTILINE)

#: Any citation of a decision, anywhere.
CITATION_PATTERN = re.compile(r"DEC-(\d{4})")

#: Directories whose contents are generated, vendored, or not ours to police.
SKIPPED_DIRECTORIES = {
    ".git",
    ".ruff_cache",
    ".pytest_cache",
    "__pycache__",
    "node_modules",
    ".venv",
    "dist",
    "build",
    "coverage",
    "artifacts",
    "backups",
    "data",
}

#: Binary and archive suffixes a text scan has no business opening.
SKIPPED_SUFFIXES = {
    ".pyc",
    ".db",
    ".zip",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".pdf",
    ".ico",
    ".woff",
    ".woff2",
    ".ttf",
    ".map",
}


class DecisionLogError(RuntimeError):
    """The decision log could not be read at all."""


def load_records() -> list[tuple[int, str, int]]:
    """Every record as ``(identifier, title, line number)``, in file order."""
    if not DECISION_LOG.exists():
        raise DecisionLogError(f"{DECISION_LOG} does not exist")
    text = DECISION_LOG.read_text(encoding="utf-8")
    records = []
    for match in HEADING_PATTERN.finditer(text):
        identifier = int(match.group(1))
        title = (match.group(2) or "").strip()
        line = text.count("\n", 0, match.start()) + 1
        records.append((identifier, title, line))
    return records


def check_duplicates(records: list[tuple[int, str, int]]) -> list[str]:
    """The check this command exists for."""
    problems = []
    seen: dict[int, int] = {}
    for identifier, _title, line in records:
        if identifier in seen:
            problems.append(
                f"DEC-{identifier:04d} is defined twice, at line {seen[identifier]} and "
                f"line {line}. A decision identifier is used once and never reused."
            )
        else:
            seen[identifier] = line
    return problems


def check_contiguity(records: list[tuple[int, str, int]]) -> list[str]:
    identifiers = sorted({identifier for identifier, _title, _line in records})
    if not identifiers:
        return ["the decision log defines no records at all"]

    problems = []
    if identifiers[0] != 1:
        problems.append(f"the log starts at DEC-{identifiers[0]:04d}, not DEC-0001")

    expected = set(range(1, identifiers[-1] + 1))
    for missing in sorted(expected - set(identifiers)):
        problems.append(
            f"DEC-{missing:04d} is missing. Identifiers are contiguous, so a gap means "
            f"either a record was deleted or a number was skipped -- and a gap is how a "
            f"used number comes to look free."
        )
    return problems


def check_records_are_complete(records: list[tuple[int, str, int]]) -> list[str]:
    problems = []
    for identifier, title, line in records:
        if not title:
            problems.append(
                f"DEC-{identifier:04d} (line {line}) has no title. The heading is "
                f"'### DEC-NNNN — <what was decided>'."
            )
    return problems


def _scannable_files() -> list[Path]:
    files = []
    for path in REPO_ROOT.rglob("*"):
        if not path.is_file():
            continue
        if any(part in SKIPPED_DIRECTORIES for part in path.relative_to(REPO_ROOT).parts):
            continue
        if path.suffix.lower() in SKIPPED_SUFFIXES:
            continue
        files.append(path)
    return files


def check_citations(records: list[tuple[int, str, int]]) -> list[str]:
    known = {identifier for identifier, _title, _line in records}
    problems = []
    for path in _scannable_files():
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        where = path.relative_to(REPO_ROOT).as_posix()
        for match in sorted({int(m) for m in CITATION_PATTERN.findall(text)}):
            if match not in known:
                problems.append(
                    f"{where} cites DEC-{match:04d}, which docs/DECISIONS.md does not define"
                )
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--next",
        action="store_true",
        help="print the next unused decision identifier and exit",
    )
    args = parser.parse_args()

    try:
        records = load_records()
    except DecisionLogError as error:
        print(f"FAIL  {error}")
        return 1

    identifiers = sorted({identifier for identifier, _title, _line in records})

    if args.next:
        print(f"DEC-{(identifiers[-1] + 1) if identifiers else 1:04d}")
        return 0

    problems = check_duplicates(records)
    problems += check_contiguity(records)
    problems += check_records_are_complete(records)
    problems += check_citations(records)

    print("Decision log")
    print(f"  records                  {len(records)}")
    print(f"  distinct identifiers     {len(identifiers)}")
    if identifiers:
        print(f"  range                    DEC-{identifiers[0]:04d} .. DEC-{identifiers[-1]:04d}")
        print(f"  next unused identifier   DEC-{identifiers[-1] + 1:04d}")

    if problems:
        print(f"\n{len(problems)} problem(s):")
        for problem in problems:
            print(f"  FAIL  {problem}")
        return 1

    print("\nEvery check passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
