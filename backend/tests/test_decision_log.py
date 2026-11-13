"""The decision log holds each identifier exactly once, and the guard that says so works.

``DEC-0083`` was cited for the role merge while it already belonged to the public-update
default, and nothing objected. ``scripts/verify_decision_log.py`` is the objection. These
tests check both halves: that the real log is clean, and that the checks fail on a log that
is not — a validator that has never rejected anything is not known to reject anything.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "verify_decision_log.py"
DECISION_LOG = REPO_ROOT / "docs" / "DECISIONS.md"


def _load_module():
    spec = importlib.util.spec_from_file_location("verify_decision_log", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


verify = _load_module()


# --- The real log -----------------------------------------------------------


def test_the_decision_log_passes_every_check():
    result = subprocess.run(
        [sys.executable, str(SCRIPT)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Every check passed." in result.stdout


def test_no_identifier_is_defined_twice_in_the_real_log():
    records = verify.load_records()
    identifiers = [identifier for identifier, _title, _line in records]
    assert len(identifiers) == len(set(identifiers))


def test_the_role_merge_decision_exists_and_is_not_the_public_update_one():
    """The specific confusion this whole check exists because of."""
    titles = {identifier: title for identifier, title, _line in verify.load_records()}

    assert 88 in titles
    assert "Merge Customer Service into Operations" in titles[88]

    # DEC-0083 and DEC-0084 still belong to the work that claimed them first.
    assert "publishes to the customer by default" in titles[83]
    assert "approved template key" in titles[84]


#: The files whose *subject* is the mis-citation. They name the wrong identifier alongside
#: the words "role merge" on purpose, because that is what they are explaining. Everywhere
#: else, that combination is the defect itself.
#:
#: ``PROJECT_STATUS.md`` joined this set after the fact, and how it did is worth recording:
#: the Phase 7 completion record narrates the mistake in section 15.2 -- "the merge was
#: initially written up as DEC-0083" -- and that sentence tripped this guard the moment it
#: was committed. The suite had been measured before the record was written, so the record's
#: own "0 failed" was true when measured and stale by the time it landed. Exempting a whole
#: file is a real widening, so ``test_the_project_record_only_narrates_the_mis_citation``
#: below keeps the exemption honest: a *new* pairing in that file, without the narrative
#: markers, still fails.
MISCITATION_EXPLAINERS = {
    "scripts/verify_decision_log.py",
    "backend/tests/test_decision_log.py",
    "PROJECT_STATUS.md",
}

#: Phrases that mark a ``DEC-0083`` mention in the project record as narrative *about* the
#: mistake rather than a citation making it again.
NARRATIVE_MARKERS = ("initially written up as", "legitimate DEC-0083")


def test_no_role_merge_citation_still_points_at_dec_0083():
    """Every role-merge reference was moved; the public-update ones were left alone."""
    offenders = []
    for path in verify._scannable_files():
        where = path.relative_to(REPO_ROOT).as_posix()
        if where in MISCITATION_EXPLAINERS:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for line_number, line in enumerate(text.splitlines(), start=1):
            if "DEC-0083" not in line:
                continue
            lowered = line.lower()
            if "merge" in lowered or "customer service" in lowered:
                offenders.append(f"{where}:{line_number}")
    assert offenders == []


def test_the_project_record_only_narrates_the_mis_citation():
    """The price of exempting a whole file, charged back as a test.

    ``PROJECT_STATUS.md`` may say that the merge was *once* filed under DEC-0083. It may not
    contain a line that pairs that identifier with the merge in any other way, which is what
    a fresh mis-citation would look like.
    """
    text = (REPO_ROOT / "PROJECT_STATUS.md").read_text(encoding="utf-8")

    offenders = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        if "DEC-0083" not in line:
            continue
        lowered = line.lower()
        if "merge" not in lowered and "customer service" not in lowered:
            continue
        if not any(marker.lower() in lowered for marker in NARRATIVE_MARKERS):
            offenders.append(f"PROJECT_STATUS.md:{line_number}")

    assert offenders == []


def test_the_public_update_citations_were_not_swept_up():
    """The opposite error: renumbering every DEC-0083 in the repository indiscriminately."""
    survivors = set()
    for path in verify._scannable_files():
        where = path.relative_to(REPO_ROOT).as_posix()
        if where in MISCITATION_EXPLAINERS:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if "DEC-0083" in text:
            survivors.add(where)

    assert "backend/app/services/public_update_templates.py" in survivors
    assert "frontend/src/shared/publicUpdateTemplates.js" in survivors
    assert "docs/DECISIONS.md" in survivors


# --- The guard itself -------------------------------------------------------


def test_a_duplicate_identifier_is_rejected():
    records = [(1, "First", 1), (2, "Second", 10), (2, "Second again", 20)]

    problems = verify.check_duplicates(records)

    assert len(problems) == 1
    assert "DEC-0002 is defined twice" in problems[0]
    assert "line 10" in problems[0] and "line 20" in problems[0]


def test_a_clean_log_produces_no_duplicate_problems():
    records = [(1, "First", 1), (2, "Second", 10), (3, "Third", 20)]

    assert verify.check_duplicates(records) == []


def test_a_gap_is_rejected():
    """The check that makes 'the next number' the only correct choice for a new record."""
    records = [(1, "First", 1), (2, "Second", 10), (4, "Fourth", 20)]

    problems = verify.check_contiguity(records)

    assert len(problems) == 1
    assert "DEC-0003 is missing" in problems[0]


def test_a_record_without_a_title_is_rejected():
    records = [(1, "", 5)]

    problems = verify.check_records_are_complete(records)

    assert len(problems) == 1
    assert "has no title" in problems[0]


def test_next_unused_identifier_is_reported():
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--next"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    identifiers = sorted({i for i, _t, _l in verify.load_records()})
    assert result.stdout.strip() == f"DEC-{identifiers[-1] + 1:04d}"


#: Identifiers for synthetic fixtures are assembled at runtime rather than written as
#: literals. An out-of-range identifier spelled out in this file would itself be a citation
#: of a record that does not exist, and the repository-wide citation check would rightly
#: fail on it -- as it did, once, on this very comment.
def _tag(number: int) -> str:
    return f"DEC-{number:04d}"


@pytest.mark.parametrize(
    ("body_template", "expected"),
    [
        ("### {tag} — A title\n\nBody.\n", [(1, "A title", 1)]),
        ("### {tag} — Another\n", [(1, "Another", 1)]),
        ("Not a heading: {tag} cited in prose.\n", []),
    ],
)
def test_only_headings_define_a_record(tmp_path, monkeypatch, body_template, expected):
    """A citation in prose is a citation, not a definition."""
    log = tmp_path / "DECISIONS.md"
    log.write_text(body_template.format(tag=_tag(1)), encoding="utf-8")
    monkeypatch.setattr(verify, "DECISION_LOG", log)

    assert verify.load_records() == expected


def test_a_citation_of_an_undefined_decision_is_rejected(tmp_path, monkeypatch):
    """The check that would have caught a comment citing a record nobody committed."""
    log = tmp_path / "DECISIONS.md"
    log.write_text(f"### {_tag(1)} — Only this one exists\n\nBody.\n", encoding="utf-8")
    source = tmp_path / "somewhere.py"
    source.write_text(f"# implements {_tag(4242)}\n", encoding="utf-8")

    monkeypatch.setattr(verify, "DECISION_LOG", log)
    monkeypatch.setattr(verify, "REPO_ROOT", tmp_path)

    problems = verify.check_citations(verify.load_records())

    assert len(problems) == 1
    assert "somewhere.py" in problems[0]
    assert "does not define" in problems[0]
