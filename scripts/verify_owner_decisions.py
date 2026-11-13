"""Verify the owner-decision register, and keep its displayed totals honest.

Why this exists
---------------
The register's identifiers were being cited before the register itself was committed.
``OD-01``, ``OD-06``, ``OD-07``, ``OD-08``, ``OD-09``, ``OD-17``, ``OD-18``, ``OD-19`` and
``OD-20`` appeared across the UAT materials and the RC baseline while no document **in
this repository** defined any of them: a reviewer told "OD-19 - open" had nothing to look
up. The register existed in owner-provided conversation material; it had not been
committed. A count written by hand into prose drifts the same way, and for the same
reason -- nothing recomputes it.

So this command recomputes every number from the records themselves, and refuses to agree
that a total is right merely because somebody typed it.

What it checks
--------------
1. **OD-01 through OD-22 all exist.** Every identifier from 1 to ``highest_identifier``
   resolves to a decision record. There is no longer such a thing as a declared-unrecorded
   identifier: a hole is a failure, not a footnote.
2. **Identifiers are contiguous**, appear exactly once, and none sits above
   ``highest_identifier``.
3. **Every identifier resolves to a complete record.** Each record carries every field in
   ``REQUIRED_FIELDS``, each of the four consequence dimensions, and no required field is
   left empty. A record that names a decision without saying what it costs is not a
   record.
4. **No duplicate exists**, by identifier or by title.
5. **Category totals are derived**, from the records, per category. Nothing is typed.
6. **A provisional disposition is not a final answer.** A record carrying one must still be
   ``open`` and must still have a null ``owner_answer`` and a null ``date_decided``. A
   disposed record is counted under "open", never under "answered".
7. **OD-21 is provider-only**: ``provider_only`` and ``blocks_provider_integration_only``
   are both true, it blocks neither local UAT nor production, it carries the nine
   ShipStation questions, and **none of them is answered**.
8. **OD-22 is represented and open**, carries the return-policy questions established by
   ``docs/RETURNS_REQUIREMENT_MATRIX.md``, and is unanswered.
9. **Displayed totals match the records.** The generated block in
   ``docs/OWNER_DECISIONS.md`` must equal the computed figures exactly; ``--write``
   regenerates it.
10. Every ``OD-NN`` reference anywhere in the repository resolves to a record. A reference
    to an identifier the register does not know **fails**. That is the check that would
    have caught the original defect.

Usage, from the repository root (on Linux and macOS the interpreter is
``backend/.venv/bin/python`` rather than ``backend/.venv/Scripts/python``)::

    backend/.venv/Scripts/python scripts/verify_owner_decisions.py
    backend/.venv/Scripts/python scripts/verify_owner_decisions.py --write

Exit status 0 means every check passed; 1 means something is inconsistent and the output
names it. It makes no network request and starts no server.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
REGISTER_JSON = REPO_ROOT / "docs" / "OWNER_DECISIONS.json"
REGISTER_MD = REPO_ROOT / "docs" / "OWNER_DECISIONS.md"
RETURNS_MATRIX = REPO_ROOT / "docs" / "RETURNS_REQUIREMENT_MATRIX.md"

BEGIN = (
    "<!-- BEGIN GENERATED COUNTS -- edit OWNER_DECISIONS.json, then run "
    "scripts/verify_owner_decisions.py --write -->"
)
END = "<!-- END GENERATED COUNTS -->"

#: Every field a record must carry. The list is the brief's, in the brief's order, and a
#: record missing any one of them is not a decision record.
REQUIRED_FIELDS = (
    "id",
    "title",
    "category",
    "decision_required",
    "affected_feature",
    "current_implemented_behavior",
    "safest_temporary_behavior",
    "options",
    "consequences",
    "blocks_local_uat",
    "blocks_uat_case_or_section",
    "blocks_production",
    "blocks_provider_integration_only",
    "may_require_migration",
    "status",
    "provisional_uat_disposition",
    "provider_only",
    "owner_answer",
    "date_decided",
    "implementation_status",
    "cited_in",
    "basis",
)

#: Fields that must carry real prose. ``options`` and ``cited_in`` must be non-empty lists.
NON_EMPTY_TEXT = (
    "title",
    "category",
    "decision_required",
    "affected_feature",
    "current_implemented_behavior",
    "safest_temporary_behavior",
    "implementation_status",
    "basis",
)
NON_EMPTY_LISTS = ("options", "cited_in")

CONSEQUENCE_DIMENSIONS = ("security", "privacy", "operational", "user_experience")

#: Fields that may legitimately be ``false`` or empty and so are not length-checked:
#: every boolean flag, ``blocks_uat_case_or_section`` (a decision may block no case),
#: ``provisional_uat_disposition``, ``owner_answer`` and ``date_decided``.

MIGRATION_VALUES = {"yes", "no", "undecided"}
STATUS_VALUES = {"open", "answered"}

PROVIDER_ONLY_ID = 21
RETURNS_ID = 22
EXPECTED_PROVIDER_QUESTIONS = 9
#: ``docs/RETURNS_REQUIREMENT_MATRIX.md`` section 3 establishes twelve questions.
EXPECTED_RETURN_QUESTIONS = 12

#: The trees walked looking for ``OD-NN`` citations. Limited so that a citation inside a
#: virtual environment, `node_modules`, or a generated artifact cannot create a false
#: failure. ``.`` is included for the repository-root documents -- `PROJECT_STATUS.md`
#: cites decisions too, and leaving it out was how this check first passed while the
#: project record named an identifier that did not exist.
CITATION_ROOTS = (".", "docs", "scripts", "backend/app", "frontend/src")
CITATION_SUFFIXES = {".md", ".py", ".js", ".jsx", ".json"}
CITATION_PATTERN = re.compile(r"\bOD-(\d{2})\b")


class RegisterError(Exception):
    """A consistency failure worth stopping for."""


def load_register() -> dict:
    if not REGISTER_JSON.exists():
        raise RegisterError(f"{REGISTER_JSON} does not exist")
    return json.loads(REGISTER_JSON.read_text(encoding="utf-8"))


def _label(decision: dict) -> str:
    return f"OD-{int(decision['id']):02d}"


def check_completeness(decisions: list[dict]) -> list[str]:
    """Check 3: every identifier resolves to a *complete* record."""
    problems: list[str] = []
    for decision in decisions:
        name = _label(decision)
        for field in REQUIRED_FIELDS:
            if field not in decision:
                problems.append(f"{name} is missing the required field {field!r}")

        for field in NON_EMPTY_TEXT:
            value = decision.get(field)
            if not isinstance(value, str) or not value.strip():
                problems.append(f"{name} has an empty or non-text {field!r}")

        for field in NON_EMPTY_LISTS:
            value = decision.get(field)
            if not isinstance(value, list) or not value:
                problems.append(f"{name} has an empty {field!r}; it must list at least one")

        consequences = decision.get("consequences")
        if not isinstance(consequences, dict):
            problems.append(f"{name} has no consequences object")
        else:
            for dimension in CONSEQUENCE_DIMENSIONS:
                value = consequences.get(dimension)
                if not isinstance(value, str) or not value.strip():
                    problems.append(
                        f"{name} records no {dimension} consequence. State it, or state "
                        "that there is none."
                    )

        for field in (
            "blocks_local_uat",
            "blocks_production",
            "provider_only",
            "blocks_provider_integration_only",
        ):
            if not isinstance(decision.get(field), bool):
                problems.append(f"{name} has a non-boolean {field!r}")

        if not isinstance(decision.get("blocks_uat_case_or_section"), list):
            problems.append(f"{name} has a non-list blocks_uat_case_or_section")

        if decision.get("may_require_migration") not in MIGRATION_VALUES:
            problems.append(
                f"{name} has may_require_migration="
                f"{decision.get('may_require_migration')!r}; expected one of "
                f"{sorted(MIGRATION_VALUES)}"
            )

        if decision.get("status") not in STATUS_VALUES:
            problems.append(f"{name} has unknown status {decision.get('status')!r}")

    return problems


def check_dispositions(decisions: list[dict]) -> list[str]:
    """Check 6: a temporary disposition is a way of proceeding, not an answer."""
    problems: list[str] = []
    for decision in decisions:
        name = _label(decision)
        disposed = bool(decision.get("provisional_uat_disposition"))
        answered = decision.get("status") == "answered"

        if disposed and answered:
            problems.append(
                f"{name} carries a temporary UAT disposition but is marked answered. "
                "A disposition is not an answer."
            )
        if disposed and decision.get("owner_answer") is not None:
            problems.append(
                f"{name} carries a temporary UAT disposition and a non-null owner_answer. "
                "A disposition must not be recorded as the owner's answer."
            )
        if not answered and decision.get("owner_answer") is not None:
            problems.append(f"{name} is open but records an owner_answer")
        if not answered and decision.get("date_decided") is not None:
            problems.append(f"{name} is open but records a date_decided")
        if answered and decision.get("owner_answer") is None:
            problems.append(f"{name} is marked answered with no owner_answer")
        if answered and decision.get("date_decided") is None:
            problems.append(f"{name} is marked answered with no date_decided")
    return problems


def check_provider_only(decisions: list[dict]) -> list[str]:
    """Check 7: OD-21 is provider-only, and its nine questions are still questions."""
    problems: list[str] = []
    by_id = {int(d["id"]): d for d in decisions}

    record = by_id.get(PROVIDER_ONLY_ID)
    if record is None:
        return [f"OD-{PROVIDER_ONLY_ID:02d} is absent; it must exist and be provider-only"]

    name = _label(record)
    if not record.get("provider_only"):
        problems.append(f"{name} must be classified provider_only")
    if not record.get("blocks_provider_integration_only"):
        problems.append(f"{name} must set blocks_provider_integration_only")
    if record.get("blocks_local_uat"):
        problems.append(f"{name} is provider-only and must not block local UAT")
    if record.get("blocks_production"):
        problems.append(
            f"{name} is provider-only; provider work is deferred by DEC-0075, so it must "
            "not be recorded as blocking production"
        )
    if record.get("status") != "open":
        problems.append(f"{name} must remain open; the nine questions are not answered")

    questions = record.get("provider_questions")
    if not isinstance(questions, list) or len(questions) != EXPECTED_PROVIDER_QUESTIONS:
        problems.append(
            f"{name} must carry exactly {EXPECTED_PROVIDER_QUESTIONS} ShipStation "
            f"questions; found {len(questions) if isinstance(questions, list) else 'none'}"
        )
    else:
        for index, question in enumerate(questions, start=1):
            if not isinstance(question, str) or not question.strip().endswith("?"):
                problems.append(
                    f"{name} question {index} is not a question. The nine are recorded "
                    "unanswered, not resolved."
                )

    # Any other record claiming provider-only is a classification error.
    for decision in decisions:
        if int(decision["id"]) == PROVIDER_ONLY_ID:
            continue
        if decision.get("provider_only"):
            problems.append(f"{_label(decision)} claims provider_only; only OD-21 is")

    # A record cannot be provider-only-blocking without being provider-only.
    for decision in decisions:
        if decision.get("blocks_provider_integration_only") and not decision.get("provider_only"):
            problems.append(
                f"{_label(decision)} blocks only provider integration but is not "
                "classified provider_only"
            )
    return problems


def check_returns(decisions: list[dict]) -> list[str]:
    """Check 8: OD-22 is present, open, and still asks its questions."""
    by_id = {int(d["id"]): d for d in decisions}
    record = by_id.get(RETURNS_ID)
    if record is None:
        return [f"OD-{RETURNS_ID:02d} is absent; the return-workflow decision must exist"]

    problems: list[str] = []
    name = _label(record)
    if record.get("status") != "open":
        problems.append(f"{name} must remain open. The return workflow is not decided.")
    if record.get("owner_answer") is not None:
        problems.append(f"{name} records an owner_answer; the return policy is unanswered")

    questions = record.get("return_questions")
    if not isinstance(questions, list) or len(questions) != EXPECTED_RETURN_QUESTIONS:
        problems.append(
            f"{name} must carry the {EXPECTED_RETURN_QUESTIONS} return-policy questions "
            f"established by {RETURNS_MATRIX.name}; found "
            f"{len(questions) if isinstance(questions, list) else 'none'}"
        )
    if not RETURNS_MATRIX.exists():
        problems.append(f"{RETURNS_MATRIX.name} is absent; {name} cites it as its trace")
    return problems


def compute(register: dict) -> dict:
    """Every figure, derived from the records. Nothing here is read from prose."""
    decisions = register["decisions"]
    highest = int(register["highest_identifier"])

    problems: list[str] = []

    record_ids = [int(d["id"]) for d in decisions]

    # --- 2 and 4. Each identifier exactly once, each title once -------------------
    duplicates = sorted({i for i in record_ids if record_ids.count(i) > 1})
    if duplicates:
        problems.append(f"decision identifier(s) appear more than once: {duplicates}")

    titles = [str(d.get("title", "")).strip().lower() for d in decisions]
    duplicate_titles = sorted({t for t in titles if t and titles.count(t) > 1})
    if duplicate_titles:
        problems.append(f"duplicate decision title(s): {duplicate_titles}")

    # --- 1 and 2. Contiguity, with no hole permitted ------------------------------
    covered = set(record_ids)
    expected = set(range(1, highest + 1))
    missing = sorted(expected - covered)
    if missing:
        problems.append(
            "identifier(s) with no decision record: "
            f"{[f'OD-{i:02d}' for i in missing]}. Every identifier must resolve to a "
            "complete record."
        )
    beyond = sorted(covered - expected)
    if beyond:
        problems.append(f"identifier(s) above highest_identifier={highest}: {beyond}")

    # A register/2 declares no unrecorded identifiers. If one reappears, say so.
    stale_unrecorded = register.get("unrecorded_identifiers") or []
    if stale_unrecorded:
        problems.append(
            f"{len(stale_unrecorded)} identifier(s) are still declared unrecorded. "
            "Every subject was supplied; write the record instead."
        )

    # --- 3, 6, 7, 8 ---------------------------------------------------------------
    problems += check_completeness(decisions)
    problems += check_dispositions(decisions)
    problems += check_provider_only(decisions)
    problems += check_returns(decisions)

    answered = [d for d in decisions if d.get("status") == "answered"]
    open_ = [d for d in decisions if d.get("status") == "open"]
    provisional = [d for d in decisions if d.get("provisional_uat_disposition")]

    if len(answered) + len(open_) != len(decisions):
        problems.append("answered + open does not equal the number of records")

    # --- 5. Category totals, derived ----------------------------------------------
    categories: dict[str, int] = {}
    for decision in decisions:
        category = str(decision.get("category", "")).strip()
        if category:
            categories[category] = categories.get(category, 0) + 1
    if sum(categories.values()) != len(decisions):
        problems.append("category totals do not sum to the number of records")

    declared_categories = register.get("categories")
    if declared_categories is not None and sorted(declared_categories) != sorted(categories):
        problems.append(
            "the register's declared category list does not match the categories the "
            "records actually use"
        )

    counts = {
        "total": len(decisions),
        "answered": len(answered),
        "provisionally_disposed": len(provisional),
        "open": len(open_),
        "uat_blocking": sum(1 for d in decisions if d.get("blocks_local_uat")),
        "production_blocking": sum(1 for d in decisions if d.get("blocks_production")),
        "provider_only": sum(1 for d in decisions if d.get("provider_only")),
        "migration_producing": sum(1 for d in decisions if d.get("may_require_migration") == "yes"),
        "migration_undecided": sum(
            1 for d in decisions if d.get("may_require_migration") == "undecided"
        ),
        "highest_identifier": highest,
    }

    if counts["total"] != highest:
        problems.append(
            f"records ({counts['total']}) != highest_identifier ({highest}); every "
            "identifier must resolve to a record"
        )

    return {
        "counts": counts,
        "categories": categories,
        "problems": problems,
        "record_ids": set(record_ids),
    }


def render_block(counts: dict, categories: dict) -> str:
    """The canonical counts table. The Markdown must contain exactly this."""
    lines = [
        BEGIN,
        "",
        "| Figure | Count |",
        "|---|---|",
        f"| **Decisions recorded** | **{counts['total']}** |",
        f"| Highest identifier in use | OD-{counts['highest_identifier']:02d} |",
        f"| Identifiers with no record | {counts['highest_identifier'] - counts['total']} |",
        f"| Answered | {counts['answered']} |",
        f"| Open | {counts['open']} |",
        "| Of the open, carrying a temporary UAT disposition "
        f"| {counts['provisionally_disposed']} |",
        f"| Blocking human UAT | {counts['uat_blocking']} |",
        f"| Blocking production | {counts['production_blocking']} |",
        f"| Provider-only | {counts['provider_only']} |",
        f"| Known to produce a migration | {counts['migration_producing']} |",
        f"| Migration impact undecided | {counts['migration_undecided']} |",
        "",
        "By category:",
        "",
        "| Category | Count |",
        "|---|---|",
    ]
    for category in sorted(categories):
        lines.append(f"| `{category}` | {categories[category]} |")
    lines += [
        f"| **Total** | **{sum(categories.values())}** |",
        "",
        "A decision may block both UAT and production, so those two rows are independent",
        "tallies and are not expected to sum to the total. A temporary UAT disposition is",
        "not an answer: a disposed decision is counted under **Open**.",
        "",
        END,
    ]
    return "\n".join(lines)


def check_markdown(counts: dict, categories: dict, write: bool) -> list[str]:
    if not REGISTER_MD.exists():
        return [f"{REGISTER_MD} does not exist"]

    text = REGISTER_MD.read_text(encoding="utf-8")
    if BEGIN not in text or END not in text:
        return [
            f"{REGISTER_MD.name} has no generated-counts block. "
            "Insert the BEGIN/END markers and run with --write."
        ]

    start = text.index(BEGIN)
    finish = text.index(END) + len(END)
    current = text[start:finish]
    wanted = render_block(counts, categories)

    if current == wanted:
        return []
    if write:
        REGISTER_MD.write_text(text[:start] + wanted + text[finish:], encoding="utf-8")
        print(f"  rewrote the generated counts block in {REGISTER_MD.name}")
        return []
    return [f"{REGISTER_MD.name} displays stale totals. Run with --write to regenerate the block."]


def check_citations(record_ids: set[int]) -> list[str]:
    """Every ``OD-NN`` cited anywhere must resolve to a record.

    Now that no identifier is declared-unrecorded, there is no tolerated middle case: a
    citation either names a record or it fails. That is the typo, or the reference to a
    decision nobody wrote down -- which is exactly how nine identifiers came to be cited
    with nothing behind them.
    """
    problems: list[str] = []
    for root in CITATION_ROOTS:
        base = REPO_ROOT / root
        if not base.exists():
            continue
        for path in base.glob("*") if root == "." else base.rglob("*"):
            if path.suffix not in CITATION_SUFFIXES or not path.is_file():
                continue
            # The register defines the identifiers; it does not cite them.
            if path.name in {REGISTER_JSON.name, REGISTER_MD.name}:
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            where = path.relative_to(REPO_ROOT).as_posix()
            for match in sorted(set(CITATION_PATTERN.findall(text))):
                if int(match) not in record_ids:
                    problems.append(
                        f"{where} cites OD-{match}, which the register does not know at all"
                    )
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--write",
        action="store_true",
        help="regenerate the counts block in OWNER_DECISIONS.md instead of only checking it",
    )
    parser.add_argument("--json", type=Path, help="write the computed counts to this file")
    args = parser.parse_args()

    try:
        register = load_register()
    except (RegisterError, json.JSONDecodeError) as error:
        print(f"FAIL  {error}")
        return 1

    result = compute(register)
    problems = list(result["problems"])
    problems += check_markdown(result["counts"], result["categories"], args.write)
    problems += check_citations(result["record_ids"])

    print("Owner-decision register")
    for name, value in result["counts"].items():
        print(f"  {name:<24} {value}")
    print("  categories")
    for category in sorted(result["categories"]):
        print(f"    {category:<38} {result['categories'][category]}")

    if args.json:
        args.json.write_text(
            json.dumps({"counts": result["counts"], "categories": result["categories"]}, indent=2),
            encoding="utf-8",
        )

    if problems:
        print(f"\n{len(problems)} problem(s):")
        for problem in problems:
            print(f"  FAIL  {problem}")
        return 1

    print("\nEvery check passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
