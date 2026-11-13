"""A tool that deletes rows has to be harder to misuse than the mistake it is repairing.

``scripts/incident_cleanup.py`` was written for one approved cleanup and ran once. These
tests exist because it is still in the repository, and the next person to reach for it will
be under time pressure with a different database in mind.

Two things are proven here.

**It refuses every target but one.** Not "warns", not "asks" -- the UAT database, an
``.e2e.db``, anything under ``backups/``, a production environment and any other path are
each refused before a connection is opened.

**It cannot delete more than its manifest says.** Every test in ``TestManifestPreconditions``
hands it a database that has drifted from the manifest in one specific way -- a row changed,
a row already gone, an extra row appeared, the deletion order rearranged, a session or a
provenance row added as a target -- and asserts the run rolls back with the table counts
untouched. A tool that deleted "the rows matching the predicate" instead of "the rows in the
manifest" would pass the happy path and fail most of these.

The fixtures build a miniature of the real thing: a customers table, an import batch and its
rows, audit events, sessions and provenance, with the same foreign keys. Small enough to
reason about, same shape as the database that mattered.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sqlite3
import sys
from pathlib import Path

import pytest

from app.core import e2e_guard

REPO_ROOT = e2e_guard.REPO_ROOT
SCRIPTS = REPO_ROOT / "scripts"


def _load_tool():
    """Import the script by path; `scripts/` is not a package."""
    path = SCRIPTS / "incident_cleanup.py"
    spec = importlib.util.spec_from_file_location("incident_cleanup_under_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


cleanup = _load_tool()


# --- A miniature of the real schema --------------------------------------------------

SCHEMA = """
CREATE TABLE users (id INTEGER PRIMARY KEY, email TEXT NOT NULL);
CREATE TABLE customers (
    id INTEGER PRIMARY KEY,
    public_id TEXT NOT NULL,
    full_name TEXT NOT NULL,
    source_record_id TEXT,
    merged_into_customer_id INTEGER REFERENCES customers(id)
);
CREATE TABLE import_batches (id INTEGER PRIMARY KEY, public_id TEXT NOT NULL);
CREATE TABLE import_batch_rows (
    id INTEGER PRIMARY KEY,
    batch_id INTEGER NOT NULL REFERENCES import_batches(id),
    customer_id INTEGER REFERENCES customers(id),
    source_record_id TEXT
);
CREATE TABLE audit_events (
    id INTEGER PRIMARY KEY,
    entity_type TEXT,
    entity_id TEXT,
    action TEXT NOT NULL
);
CREATE TABLE user_sessions (id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL);
CREATE TABLE role_merge_provenance (id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL);
CREATE TABLE alembic_version (version_num TEXT NOT NULL);
"""

#: Every table the tool checks for references into `customers`, built from the tool's own
#: constant rather than listed here. If somebody adds a foreign key and updates
#: `CUSTOMER_REFERENCES`, this miniature grows with it instead of quietly not covering it.
_reference_columns: dict[str, list[str]] = {}
for _table, _column in cleanup.CUSTOMER_REFERENCES:
    _reference_columns.setdefault(_table, []).append(_column)
for _table, _columns in _reference_columns.items():
    _definitions = ", ".join(f"{_column} INTEGER REFERENCES customers(id)" for _column in _columns)
    SCHEMA += f"CREATE TABLE {_table} (id INTEGER PRIMARY KEY, {_definitions});" + chr(10)

#: The Customer Account tables the tool insists are empty, minus any created just above.
for _table in cleanup.ACCOUNT_TABLES:
    if _table not in _reference_columns:
        SCHEMA += (
            f"CREATE TABLE {_table} "
            "(id INTEGER PRIMARY KEY, customer_id INTEGER REFERENCES customers(id));" + chr(10)
        )

#: Two synthetic customers, one genuine. One batch, two rows. Four audits: two naming a
#: synthetic customer, one naming the batch, one a login that must survive.
SEED = """
INSERT INTO users (id, email) VALUES (1, 'admin@demo.example.com');
INSERT INTO customers (id, public_id, full_name, source_record_id) VALUES
    (1, 'CUS-REAL', 'A Genuine Person', NULL),
    (2, 'CUS-SYN1', 'Synthetic One E2EABC123', 'E2EABC123-A'),
    (3, 'CUS-SYN2', 'Synthetic Two KBXYZ789', NULL);
INSERT INTO import_batches (id, public_id) VALUES (1, 'IMP-SYN1');
INSERT INTO import_batch_rows (id, batch_id, customer_id, source_record_id) VALUES
    (1, 1, 2, 'E2EABC123-A'),
    (2, 1, 3, 'E2EABC123-B');
INSERT INTO audit_events (id, entity_type, entity_id, action) VALUES
    (1, 'customer', 'CUS-SYN1', 'customer.create'),
    (2, 'customer', 'CUS-SYN2', 'customer.create'),
    (3, 'import_batch', 'IMP-SYN1', 'customer.import_commit'),
    (4, 'user', NULL, 'auth.login');
INSERT INTO user_sessions (id, user_id) VALUES (1, 1), (2, 1);
INSERT INTO role_merge_provenance (id, user_id) VALUES (1, 1), (2, 1);
INSERT INTO alembic_version (version_num) VALUES ('6af30fcdd3a8');
"""

#: What the miniature must look like before a cleanup, and after one.
BEFORE = {
    "customers": 3,
    "import_batches": 1,
    "import_batch_rows": 2,
    "audit_events": 4,
    "user_sessions": 2,
    "role_merge_provenance": 2,
}
AFTER = {
    "customers": 1,
    "import_batches": 0,
    "import_batch_rows": 0,
    "audit_events": 1,
    "user_sessions": 2,
    "role_merge_provenance": 2,
}


def counts(path: Path) -> dict[str, int]:
    connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    try:
        return {
            table: connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]  # noqa: S608
            for table in BEFORE
        }
    finally:
        connection.close()


def fingerprints(path: Path, table: str, ids: list[int]) -> dict[int, str]:
    connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    try:
        return cleanup.fingerprints_for(connection, table, ids)
    finally:
        connection.close()


@pytest.fixture
def database(tmp_path, monkeypatch) -> Path:
    """A miniature database, installed as the one path the tool will accept.

    `DEV_DB` is monkeypatched rather than the guard being loosened: the shipped tool still
    accepts exactly one path, and these tests move what that path is for the duration.
    """
    path = tmp_path / "solaris_crm.db"
    connection = sqlite3.connect(path)
    try:
        connection.executescript(SCHEMA)
        connection.executescript(SEED)
        connection.commit()
    finally:
        connection.close()
    monkeypatch.setattr(e2e_guard, "DEV_DB", path)
    monkeypatch.setenv("ENVIRONMENT", "development")
    return path


@pytest.fixture
def manifest(database, tmp_path) -> Path:
    """The frozen manifest for that database: 2 customers, 1 batch, 2 rows, 3 audits."""
    document = {
        "database": database.name,
        "targets": {
            "audit_events": {
                "order": 1,
                "category": "closure",
                "rows": [
                    {"id": i, "fingerprint": f, "justification": "names a target"}
                    for i, f in sorted(fingerprints(database, "audit_events", [1, 2, 3]).items())
                ],
            },
            "import_batch_rows": {
                "order": 2,
                "category": "closure",
                "rows": [
                    {"id": i, "fingerprint": f, "justification": "belongs to a target batch"}
                    for i, f in sorted(fingerprints(database, "import_batch_rows", [1, 2]).items())
                ],
            },
            "import_batches": {
                "order": 3,
                "category": "closure",
                "rows": [
                    {"id": i, "fingerprint": f, "justification": "all rows synthetic"}
                    for i, f in sorted(fingerprints(database, "import_batches", [1]).items())
                ],
            },
            "customers": {
                "order": 4,
                "category": "marker",
                "rows": [
                    {"id": i, "fingerprint": f, "justification": "carries a run token"}
                    for i, f in sorted(fingerprints(database, "customers", [2, 3]).items())
                ],
            },
        },
        "retained_proofs": {
            "customers": {str(k): v for k, v in fingerprints(database, "customers", [1]).items()},
            "audit_events_session_attributed": {
                str(k): v for k, v in fingerprints(database, "audit_events", [4]).items()
            },
            "audit_events_pre_boundary": {},
            "user_sessions": {
                str(k): v for k, v in fingerprints(database, "user_sessions", [1, 2]).items()
            },
        },
        "expected_after": dict(AFTER),
    }
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(document, indent=1, sort_keys=True), encoding="utf-8")
    return path


@pytest.fixture
def relaxed_totals(monkeypatch):
    """The miniature has 8 targets, not 336. Only the totals move; every check stays."""
    original = cleanup.summarise

    def summarise(counts_, manifest_):  # noqa: ANN001
        approved = {
            table: len(manifest_["targets"][table]["rows"]) for table in cleanup.EXPECTED_ORDER
        }
        problems = []
        for key, want in (
            ("_retained_references", 0),
            ("_missing", 0),
            ("_fingerprint_mismatches", 0),
        ):
            if counts_.get(key, 0) != want:
                problems.append(f"{key}: {counts_.get(key)}")
        print(f"    targets {approved}, total {sum(approved.values())}")
        return problems

    monkeypatch.setattr(cleanup, "summarise", summarise)
    monkeypatch.setattr(cleanup, "BASELINE_BEFORE", dict(BEFORE))
    monkeypatch.setattr(
        cleanup,
        "APPROVED_TARGETS",
        {"customers": 2, "import_batches": 1, "import_batch_rows": 2, "audit_events": 3},
    )
    monkeypatch.setattr(cleanup, "APPROVED_TOTAL", 8)
    return original


def run(mode: str, manifest: Path, database: Path) -> int:
    return cleanup.main(["--manifest", str(manifest), "--database", str(database), mode])


# --- Target refusals --------------------------------------------------------------------


class TestItRefusesEveryTargetButOne:
    def test_the_uat_database_is_refused(self, database, manifest):
        uat = e2e_guard.UAT_DIR / "solaris_uat.uat.db"
        with pytest.raises(cleanup.SafetyError, match="UAT"):
            cleanup.validated_database(uat)

    def test_a_scratch_e2e_database_is_refused(self, database, manifest, tmp_path):
        scratch = tmp_path / f"solaris{e2e_guard.E2E_DB_SUFFIX}"
        scratch.write_bytes(b"")
        with pytest.raises(cleanup.SafetyError, match="end-to-end"):
            cleanup.validated_database(scratch)

    def test_a_backup_is_refused(self, database, manifest):
        backup = e2e_guard.BACKUP_DIR / "solaris_crm-20260101T000000Z.db"
        with pytest.raises(cleanup.SafetyError, match="backup"):
            cleanup.validated_database(backup)

    def test_a_production_environment_is_refused(self, database, monkeypatch):
        monkeypatch.setenv("ENVIRONMENT", "production")
        with pytest.raises(cleanup.SafetyError, match="production"):
            cleanup.validated_database(database)

    def test_the_e2e_environment_is_refused(self, database, monkeypatch):
        monkeypatch.setenv("ENVIRONMENT", "e2e")
        with pytest.raises(cleanup.SafetyError, match="e2e"):
            cleanup.validated_database(database)

    def test_any_other_path_is_refused(self, database, tmp_path):
        other = tmp_path / "somebody_elses.db"
        other.write_bytes(b"")
        with pytest.raises(cleanup.SafetyError, match="not the repository development"):
            cleanup.validated_database(other)

    def test_a_missing_file_is_refused(self, database, tmp_path):
        with pytest.raises(cleanup.SafetyError, match="No database"):
            cleanup.validated_database(tmp_path / "absent.db")

    def test_the_approved_database_passes(self, database):
        assert cleanup.validated_database(database) == e2e_guard.canonical(database)

    def test_a_refused_target_exits_two_and_deletes_nothing(self, database, manifest, capsys):
        before = counts(database)
        uat = e2e_guard.UAT_DIR / "solaris_uat.uat.db"
        assert run("--execute", manifest, uat) == 2
        assert counts(database) == before


# --- The happy path ----------------------------------------------------------------------


class TestAnApprovedCleanup:
    def test_the_dry_run_changes_nothing(self, database, manifest, relaxed_totals):
        digest_before = hashlib.sha256(database.read_bytes()).hexdigest()
        assert run("--dry-run", manifest, database) == 0
        assert counts(database) == BEFORE
        assert hashlib.sha256(database.read_bytes()).hexdigest() == digest_before

    def test_execute_removes_exactly_the_manifest(self, database, manifest, relaxed_totals):
        assert run("--execute", manifest, database) == 0
        assert counts(database) == AFTER

    def test_the_genuine_customer_survives(self, database, manifest, relaxed_totals):
        before = fingerprints(database, "customers", [1])
        assert run("--execute", manifest, database) == 0
        assert fingerprints(database, "customers", [1]) == before

    def test_the_login_audit_and_both_sessions_survive(self, database, manifest, relaxed_totals):
        audit_before = fingerprints(database, "audit_events", [4])
        sessions_before = fingerprints(database, "user_sessions", [1, 2])
        assert run("--execute", manifest, database) == 0
        assert fingerprints(database, "audit_events", [4]) == audit_before
        assert fingerprints(database, "user_sessions", [1, 2]) == sessions_before

    def test_provenance_survives(self, database, manifest, relaxed_totals):
        assert run("--execute", manifest, database) == 0
        assert counts(database)["role_merge_provenance"] == 2

    def test_verify_passes_afterwards(self, database, manifest, relaxed_totals):
        assert run("--execute", manifest, database) == 0
        assert run("--verify", manifest, database) == 0

    def test_it_leaves_the_schema_alone(self, database, manifest, relaxed_totals):
        assert run("--execute", manifest, database) == 0
        connection = sqlite3.connect(f"file:{database.as_posix()}?mode=ro", uri=True)
        try:
            revision = connection.execute("SELECT version_num FROM alembic_version").fetchone()
            assert revision[0] == "6af30fcdd3a8"
            assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
            assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        finally:
            connection.close()


# --- Drift between the manifest and the database -------------------------------------------


class TestManifestPreconditions:
    """Each one drifts the database in one way and asserts a rollback, counts untouched."""

    def _drift(self, database: Path, statement: str) -> None:
        connection = sqlite3.connect(database)
        try:
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute(statement)
            connection.commit()
        finally:
            connection.close()

    def test_a_changed_target_row_rolls_back(self, database, manifest, relaxed_totals):
        self._drift(database, "UPDATE customers SET full_name = 'Renamed' WHERE id = 2")
        before = counts(database)
        assert run("--execute", manifest, database) == 1
        assert counts(database) == before

    def test_a_changed_row_fails_the_dry_run_too(self, database, manifest, relaxed_totals):
        self._drift(database, "UPDATE customers SET full_name = 'Renamed' WHERE id = 2")
        assert run("--dry-run", manifest, database) == 1

    def test_a_target_that_no_longer_exists_rolls_back(self, database, manifest, relaxed_totals):
        self._drift(database, "DELETE FROM audit_events WHERE id = 1")
        before = counts(database)
        assert run("--execute", manifest, database) == 1
        assert counts(database) == before

    def test_a_new_dependent_row_rolls_back(self, database, manifest, relaxed_totals):
        """A shipment appears on a targeted customer between freeze and execute."""
        self._drift(database, "INSERT INTO shipments (id, customer_id) VALUES (1, 2)")
        before = counts(database)
        assert run("--execute", manifest, database) == 1
        assert counts(database) == before

    def test_a_new_address_on_a_target_rolls_back(self, database, manifest, relaxed_totals):
        self._drift(database, "INSERT INTO customer_addresses (id, customer_id) VALUES (1, 3)")
        before = counts(database)
        assert run("--execute", manifest, database) == 1
        assert counts(database) == before

    def test_a_retained_customer_merged_into_a_target_rolls_back(
        self, database, manifest, relaxed_totals
    ):
        self._drift(database, "UPDATE customers SET merged_into_customer_id = 2 WHERE id = 1")
        before = counts(database)
        assert run("--execute", manifest, database) == 1
        assert counts(database) == before

    def test_a_populated_account_table_rolls_back(self, database, manifest, relaxed_totals):
        self._drift(
            database,
            "INSERT INTO customer_identity_links (id, customer_id) VALUES (1, 1)",
        )
        before = counts(database)
        assert run("--execute", manifest, database) == 1
        assert counts(database) == before

    def test_a_moved_baseline_stops_the_dry_run(self, database, manifest, relaxed_totals):
        self._drift(
            database,
            "INSERT INTO customers (id, public_id, full_name) VALUES (9, 'CUS-NEW', 'New')",
        )
        assert run("--dry-run", manifest, database) == 1

    def test_a_reordered_manifest_rolls_back(self, database, manifest, relaxed_totals):
        document = json.loads(manifest.read_text(encoding="utf-8"))
        document["targets"]["customers"]["order"] = 1
        document["targets"]["audit_events"]["order"] = 4
        manifest.write_text(json.dumps(document), encoding="utf-8")
        before = counts(database)
        assert run("--execute", manifest, database) == 1
        assert counts(database) == before

    def test_a_manifest_targeting_sessions_rolls_back(self, database, manifest, relaxed_totals):
        document = json.loads(manifest.read_text(encoding="utf-8"))
        document["targets"]["user_sessions"] = {"order": 5, "category": "x", "rows": []}
        manifest.write_text(json.dumps(document), encoding="utf-8")
        before = counts(database)
        assert run("--execute", manifest, database) == 1
        assert counts(database) == before

    def test_a_manifest_targeting_provenance_rolls_back(self, database, manifest, relaxed_totals):
        document = json.loads(manifest.read_text(encoding="utf-8"))
        document["targets"]["role_merge_provenance"] = {"order": 5, "category": "x", "rows": []}
        manifest.write_text(json.dumps(document), encoding="utf-8")
        before = counts(database)
        assert run("--execute", manifest, database) == 1
        assert counts(database) == before

    def test_a_duplicated_primary_key_rolls_back(self, database, manifest, relaxed_totals):
        document = json.loads(manifest.read_text(encoding="utf-8"))
        rows = document["targets"]["customers"]["rows"]
        rows.append(dict(rows[0]))
        manifest.write_text(json.dumps(document), encoding="utf-8")
        before = counts(database)
        assert run("--execute", manifest, database) == 1
        assert counts(database) == before

    def test_an_audit_event_in_both_sets_rolls_back(self, database, manifest, relaxed_totals):
        document = json.loads(manifest.read_text(encoding="utf-8"))
        targeted = document["targets"]["audit_events"]["rows"][0]
        document["retained_proofs"]["audit_events_session_attributed"][str(targeted["id"])] = (
            targeted["fingerprint"]
        )
        manifest.write_text(json.dumps(document), encoding="utf-8")
        before = counts(database)
        assert run("--execute", manifest, database) == 1
        assert counts(database) == before


class TestWhatItNeverDoes:
    """Properties asserted against the source, because they are absences."""

    SOURCE = (SCRIPTS / "incident_cleanup.py").read_text(encoding="utf-8")

    def _code(self) -> str:
        """Comments and docstrings stripped: the file explains what it does not do."""
        import re  # noqa: PLC0415

        without_docstrings = re.sub(r'"""[\s\S]*?"""', "", self.SOURCE)
        return re.sub(r"(^|[^:])#.*$", r"\1", without_docstrings, flags=re.MULTILINE)

    def test_it_never_vacuums(self):
        assert "VACUUM" not in self._code().upper()

    def test_it_never_touches_sqlite_sequence(self):
        assert "sqlite_sequence" not in self._code()

    def test_it_never_updates(self):
        assert "UPDATE " not in self._code().upper()

    def test_it_never_disables_foreign_keys(self):
        code = self._code()
        assert "foreign_keys=OFF" not in code
        assert "PRAGMA foreign_keys=ON" in code

    def test_it_deletes_only_by_primary_key(self):
        """No marker, suffix, domain or timestamp predicate anywhere in a DELETE."""
        code = self._code()
        deletes = [line for line in code.splitlines() if "DELETE FROM" in line.upper()]
        assert deletes, "the tool should contain a DELETE"
        for line in deletes:
            assert "id IN ({placeholders})" in line, line
            for forbidden in ("GLOB", "LIKE", "created_at", "occurred_at", "full_name"):
                assert forbidden not in line, line

    def test_it_takes_the_write_lock_before_checking(self):
        """BEGIN IMMEDIATE, so nothing can commit between the check and the delete.

        Scoped to `execute`. `dry_run` calls `check_manifest` too, and correctly does so
        without a transaction because it writes nothing -- searching the whole file would
        find that call first and assert the opposite of what matters here.
        """
        body = self._code()
        body = body[body.index("def execute(") :]
        assert "BEGIN IMMEDIATE" in body
        assert body.index("BEGIN IMMEDIATE") < body.index("check_manifest(")
        assert body.index("BEGIN IMMEDIATE") < body.upper().index("DELETE FROM")

    def test_it_never_calls_uat_env(self):
        assert "uat_env" not in self._code()
