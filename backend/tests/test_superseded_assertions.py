"""The guard on `docs/customer_account/SUPERSEDED_ASSERTIONS.md`.

An assertion that becomes false in a later phase is either a deferral ending or a guard
being weakened, and the two are indistinguishable in a diff. The register is how they are
told apart: an assertion may change when an entry names the decision that authorised it,
states what the original said, and states which guarantee survives.

This module makes the register cost something. Without it the document is prose, and prose
does not object when a test quietly disappears -- which is exactly how
``DEC-0083`` reached five files before anybody read the decision log
(`scripts/verify_decision_log.py`).

What is checked:

1. every registered test **still exists**, under the name the register records, in the file
   the register names -- so deleting a superseded test, or renaming it again without
   coming back here, fails;
2. every entry is **complete**: all six fields, none of them empty;
3. every entry **cites a decision** that the owner-decision register or the decision log
   actually defines -- an ``OD-NN`` or a ``DEC-NNNN`` nobody can look up is the same defect
   as no citation at all;
4. every test whose docstring **names the register** is registered in it, so a test cannot
   authorise itself by gesturing at the document;
5. the identifiers are contiguous from ``AS-01``, which is what makes "take the next
   number" the only way to add one.

What is deliberately **not** checked: whether the replacement assertion is as strong as the
original. No parser can see that. Review is what catches it, and the register is what gives
review something to review.
"""

from __future__ import annotations

import ast
import json
import pathlib
import re

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
REGISTER = REPO_ROOT / "docs" / "customer_account" / "SUPERSEDED_ASSERTIONS.md"
BACKEND = REPO_ROOT / "backend"
OWNER_DECISIONS = REPO_ROOT / "docs" / "OWNER_DECISIONS.json"
DECISION_LOG = REPO_ROOT / "docs" / "DECISIONS.md"

ENTRY_PATTERN = re.compile(r"^### (AS-\d{2}) — `(.+?)`$", re.MULTILINE)

#: The fields every entry carries, as they are written.
REQUIRED_FIELDS = (
    "**File:**",
    "**Original assertion.**",
    "**Why it became false.**",
    "**Replacement assertion.**",
    "**Guarantee still protected.**",
    "**Authorised by:**",
)

#: How a test declares itself superseded. Deliberately the **register's own identifier
#: format** rather than the word "superseded": `ProposalStatus.SUPERSEDED` is an ordinary
#: part of this domain's vocabulary, and a test about a replaced proposal says "superseded"
#: for reasons that have nothing to do with this document. A test claims a supersession by
#: naming the register, which is unambiguous and is also the thing a reader needs.
SUPERSESSION_MARKER = "SUPERSEDED_ASSERTIONS.md"


def _entries() -> list[dict[str, str]]:
    """Parse the register into records. The document is the source; this is just a reader."""
    text = REGISTER.read_text(encoding="utf-8")
    body = text.split("## The register", 1)[1].split("## Rules for adding an entry", 1)[0]
    matches = list(ENTRY_PATTERN.finditer(body))
    records = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(body)
        chunk = body[match.start() : end]
        now_named = re.search(r"\*\*Now named:\*\* `(.+?)`", chunk)
        file_match = re.search(r"\*\*File:\*\* `(.+?)`", chunk)
        authorised = re.search(r"\*\*Authorised by:\*\* (.+)", chunk)
        records.append(
            {
                "id": match.group(1),
                "original_name": match.group(2),
                "current_name": now_named.group(1) if now_named else match.group(2),
                "file": file_match.group(1) if file_match else "",
                "authorised_by": authorised.group(1).strip() if authorised else "",
                "body": chunk,
            }
        )
    return records


def _test_names(path: pathlib.Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name.startswith("test_")
    }


def _test_files() -> list[pathlib.Path]:
    return [
        path for path in (BACKEND / "tests").rglob("test_*.py") if "__pycache__" not in path.parts
    ]


def test_the_register_has_entries():
    """A register nobody has written to is a register nobody is using."""
    assert _entries(), "SUPERSEDED_ASSERTIONS.md records no entries"


def test_identifiers_are_contiguous_and_unique():
    ids = [entry["id"] for entry in _entries()]
    assert len(ids) == len(set(ids)), f"duplicate identifier in {ids}"
    assert ids == [f"AS-{number:02d}" for number in range(1, len(ids) + 1)], ids


@pytest.mark.parametrize("entry", _entries(), ids=lambda entry: entry["id"])
def test_every_entry_is_complete(entry):
    for field in REQUIRED_FIELDS:
        assert field in entry["body"], f"{entry['id']} is missing {field}"
    assert entry["file"], f"{entry['id']} names no file"
    assert entry["authorised_by"], f"{entry['id']} names no decision"


@pytest.mark.parametrize("entry", _entries(), ids=lambda entry: entry["id"])
def test_every_registered_test_still_exists_under_its_recorded_name(entry):
    """The check that makes deleting a superseded test fail rather than pass quietly."""
    path = REPO_ROOT / entry["file"]
    assert path.exists(), f"{entry['id']} names a file that does not exist: {entry['file']}"
    names = _test_names(path)
    assert entry["current_name"] in names, (
        f"{entry['id']} records {entry['current_name']} in {entry['file']}, which does not "
        "define it. A rename has to come back to the register."
    )


@pytest.mark.parametrize("entry", _entries(), ids=lambda entry: entry["id"])
def test_every_entry_cites_a_decision_that_exists(entry):
    """An ``OD-NN`` or ``DEC-NNNN`` nobody can look up is the same defect as no citation."""
    cited_owner = set(re.findall(r"OD-(\d{2})", entry["authorised_by"]))
    cited_dec = set(re.findall(r"DEC-(\d{4})", entry["authorised_by"]))
    assert cited_owner or cited_dec, f"{entry['id']} cites no decision identifier"

    if cited_owner:
        register = json.loads(OWNER_DECISIONS.read_text(encoding="utf-8"))
        known = {f"{decision['id']:02d}" for decision in register["decisions"]}
        assert cited_owner <= known, f"{entry['id']} cites unknown owner decisions"

    if cited_dec:
        log = DECISION_LOG.read_text(encoding="utf-8")
        known = set(re.findall(r"^### DEC-(\d{4})", log, re.MULTILINE))
        assert cited_dec <= known, f"{entry['id']} cites unknown decision-log entries"


def test_no_test_claims_a_supersession_the_register_does_not_record():
    """A test cannot authorise its own weakening by saying so in its docstring."""
    registered = {entry["current_name"] for entry in _entries()}
    unregistered: list[str] = []
    for path in _test_files():
        if path.name == pathlib.Path(__file__).name:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef) or not node.name.startswith("test_"):
                continue
            doc = ast.get_docstring(node) or ""
            if SUPERSESSION_MARKER in doc and node.name not in registered:
                unregistered.append(f"{path.relative_to(REPO_ROOT).as_posix()}::{node.name}")
    assert not unregistered, (
        "these tests describe themselves as superseded but are not in "
        f"SUPERSEDED_ASSERTIONS.md: {unregistered}"
    )


def test_the_register_is_cited_from_the_tests_it_governs():
    """Each registered test points back at the register, so a reader of the test finds it.

    A register nothing links to is a register nobody opens when they are about to change
    the assertion it governs, which is the only moment it matters.
    """
    missing = []
    for entry in _entries():
        source = (REPO_ROOT / entry["file"]).read_text(encoding="utf-8")
        if "SUPERSEDED_ASSERTIONS.md" not in source:
            missing.append(entry["file"])
    assert not missing, (
        f"these files hold superseded assertions and never name the register: {missing}"
    )
