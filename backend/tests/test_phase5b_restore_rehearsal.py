"""The restore rehearsal restores what it backed up, and refuses everything else.

Two halves, and the second is the one that matters more.

**It works.** A populated database is backed up through the online API, restored into a
scratch location, and reconciled -- counts, relationships, and identifiers -- against the
source it came from. The fixture deliberately carries a non-zero row in *every* table the
phase brief names, including `import_batches`, which the development database happens to
have none of. A reconciliation of nothing against nothing is not evidence that the table
would survive a restore, so this builds one where it can be.

**It refuses.** Every dangerous destination is rejected *before* anything is written: the
live database, anywhere inside the repository, the home directory, a file that already
exists, a name that is not marked as scratch, and anywhere outside the scratch root the
run created for itself. Cleanup refuses a directory it did not make.

The script under test is loaded from `scripts/` by path because it is an operator tool
rather than an installed module, and it should stay runnable as `python scripts/...`.
"""

from __future__ import annotations

import importlib.util
import sqlite3
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "restore_rehearsal.py"


def _load_script():
    spec = importlib.util.spec_from_file_location("restore_rehearsal", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules["restore_rehearsal"] = module
    spec.loader.exec_module(module)
    return module


rehearsal = _load_script()


# --- A populated database, built to have nothing at zero ------------------------------


def _stamp(con: sqlite3.Connection, revision: str) -> None:
    con.execute("CREATE TABLE IF NOT EXISTS alembic_version (version_num VARCHAR(32) NOT NULL)")
    con.execute("DELETE FROM alembic_version")
    con.execute("INSERT INTO alembic_version (version_num) VALUES (?)", (revision,))


@pytest.fixture
def populated(tmp_path) -> Path:
    """A database with a non-zero row count in every reconciled table.

    The reporting dataset from Phase 5A does most of the work -- it is already awkward on
    purpose, with drafts, cancellations, a rebook pair, a return, a merged customer, and a
    three-package two-leg shipment. On top of it this adds the three things that dataset
    has no reason to carry and the rehearsal has to reconcile anyway: shipment events, an
    audit trail, and committed import batches.

    `import_batches` is the reason this fixture exists at all. The development database
    has never had an import committed against it, so a rehearsal there reconciles that
    table as 0 == 0 -- which is a match that proves nothing.
    """
    from sqlalchemy.orm import sessionmaker

    from app.core.db import build_engine
    from app.core.enums import OperationalState
    from app.models import AuditEvent, Base, ImportBatch, OrganizationSettings, ShipmentEvent
    from tests.report_fixtures import TZ, build_dataset

    path = tmp_path / "populated.db"
    engine = build_engine(f"sqlite:///{path.as_posix()}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)
    db = factory()

    org = OrganizationSettings()
    org.office_timezone = TZ
    db.add(org)
    db.commit()

    data = build_dataset(db)
    db.commit()

    now = datetime.now(UTC).replace(tzinfo=None)
    shipments = list(data.shipments.values())

    for index, shipment in enumerate(shipments):
        db.add(
            ShipmentEvent(
                shipment_id=shipment.id,
                event_type="in_transit",
                operational_state=OperationalState.IN_TRANSIT,
                occurred_at=now - timedelta(days=18, hours=index),
                recorded_at=now - timedelta(days=18, hours=index),
                is_public_update=True,
                public_update_template_key="in_transit.standard",
                source="manual",
            )
        )
        db.add(
            AuditEvent(
                occurred_at=now - timedelta(days=10, hours=index),
                actor_label="rehearsal fixture",
                action="rehearsal.fixture",
                entity_type="shipment",
                entity_id=str(shipment.id),
                summary="Synthetic audit row for the restore rehearsal fixture.",
            )
        )

    for index in range(2):
        db.add(
            ImportBatch(
                public_id=f"IMP-REHEARSAL{index:02d}",
                kind="customers",
                content_sha256=f"{index:064d}",
                source_system="csv_import",
                conflict_policy="skip",
                row_count=4,
                created_count=4,
                committed_at=now - timedelta(days=5, hours=index),
            )
        )

    db.commit()
    db.close()
    engine.dispose()

    con = sqlite3.connect(path)
    head = rehearsal.current_head()
    _stamp(con, head or "e5623fcf8018")
    con.commit()
    con.close()
    return path


# --- It works -------------------------------------------------------------------------


def test_the_rehearsal_restores_and_reconciles_a_populated_database(populated):
    result = rehearsal.run(str(populated), keep=False)

    assert result.ok, (
        f"count mismatches={result.count_mismatches} "
        f"relationship mismatches={result.relationship_mismatches} "
        f"structural={result.structural}"
    )
    assert result.structural["integrity_ok"] is True
    assert result.structural["foreign_keys_ok"] is True
    assert result.source_unchanged is True


def test_every_reconciled_entity_is_actually_non_zero(populated):
    """Guards the guard. A reconciliation of zeros would pass while proving nothing."""
    result = rehearsal.run(str(populated), keep=False)

    for name in rehearsal.RECONCILED_COUNTS:
        assert result.counts_source[name] > 0, f"{name} is zero; the fixture proves nothing"
        assert result.counts_restored[name] == result.counts_source[name]


def test_relationships_are_compared_not_only_cardinalities(populated):
    """Two databases can agree on every count and still disagree about what links to what."""
    result = rehearsal.run(str(populated), keep=False)

    assert result.relationships_source["public_id_fingerprint"]
    assert result.relationships_source["shipment_customer_pairs"]
    assert result.relationships_source["package_parentage"]
    assert not result.relationship_mismatches
    assert result.relationships_restored["orphan_shipments"] == 0
    assert result.relationships_restored["orphan_packages"] == 0


def test_a_corrupted_restore_would_be_noticed(populated, monkeypatch):
    """If the restored copy lost rows, the run must fail rather than report success."""
    real = rehearsal.read_scalars

    def lying(path, statements):
        values = real(path, statements)
        # Pretend the restored side came back a customer short.
        if "customers" in values and path != populated.resolve():
            values["customers"] = values["customers"] - 1
        return values

    monkeypatch.setattr(rehearsal, "read_scalars", lying)
    result = rehearsal.run(str(populated), keep=False)

    assert "customers" in result.count_mismatches
    assert result.ok is False


def test_the_source_is_opened_read_only_and_never_written(populated):
    before = populated.stat()
    rehearsal.run(str(populated), keep=False)
    after = populated.stat()

    assert after.st_size == before.st_size
    assert after.st_mtime_ns == before.st_mtime_ns


def test_scratch_artifacts_are_removed_when_the_run_finishes(populated):
    result = rehearsal.run(str(populated), keep=False)

    assert result.cleaned_up, "the run reported no cleanup"
    for path in result.cleaned_up:
        assert not Path(path).exists()


# --- It refuses -----------------------------------------------------------------------


@pytest.fixture
def scratch_root(tmp_path):
    root = tmp_path / f"{rehearsal.SCRATCH_PREFIX}unit"
    root.mkdir()
    return root.resolve()


def _reject(destination, scratch_root, source):
    with pytest.raises(rehearsal.SafetyError) as caught:
        rehearsal.validate_scratch_destination(
            Path(destination), scratch_root=scratch_root, source=source
        )
    return str(caught.value)


def test_the_live_database_is_refused_as_a_destination(scratch_root):
    live = REPO_ROOT / "data" / "solaris_crm.db"
    message = _reject(live, scratch_root, live.resolve())
    assert "scratch root" in message or "source database" in message


def test_a_destination_inside_the_repository_is_refused(scratch_root, populated):
    message = _reject(REPO_ROOT / "scratch.rehearsal.db", scratch_root, populated)
    assert "scratch root" in message or "repository" in message


def test_the_repository_root_itself_is_refused(scratch_root, populated):
    message = _reject(REPO_ROOT, scratch_root, populated)
    assert "scratch root" in message or "repository" in message


def test_the_source_tree_is_refused(scratch_root, populated):
    message = _reject(REPO_ROOT / "backend" / "app" / "x.rehearsal.db", scratch_root, populated)
    assert "scratch root" in message or "repository" in message


def test_the_home_directory_is_refused(scratch_root, populated):
    message = _reject(Path.home(), scratch_root, populated)
    assert "scratch root" in message or "home directory" in message


def test_a_bare_child_of_the_home_directory_is_refused(scratch_root, populated):
    message = _reject(Path.home() / "solaris.rehearsal.db", scratch_root, populated)
    assert "scratch root" in message or "home directory" in message


def test_an_existing_database_is_refused(scratch_root, populated):
    existing = scratch_root / f"already-here{rehearsal.SCRATCH_DB_SUFFIX}"
    existing.write_bytes(b"SQLite format 3\x00")
    message = _reject(existing, scratch_root, populated)
    assert "already exists" in message


def test_a_destination_outside_the_scratch_root_is_refused(scratch_root, populated, tmp_path):
    outside = tmp_path / "elsewhere" / f"copy{rehearsal.SCRATCH_DB_SUFFIX}"
    message = _reject(outside, scratch_root, populated)
    assert "scratch root" in message


def test_a_destination_not_named_as_scratch_is_refused(scratch_root, populated):
    message = _reject(scratch_root / "solaris_crm.db", scratch_root, populated)
    assert "named as scratch" in message


def test_a_valid_scratch_destination_is_accepted(scratch_root, populated):
    accepted = rehearsal.validate_scratch_destination(
        scratch_root / f"fine{rehearsal.SCRATCH_DB_SUFFIX}",
        scratch_root=scratch_root,
        source=populated,
    )
    assert accepted.parent == scratch_root


def test_cleanup_refuses_a_directory_it_did_not_create(tmp_path):
    someone_elses = tmp_path / "important-data"
    someone_elses.mkdir()
    (someone_elses / "keep.txt").write_text("keep me", encoding="utf-8")

    with pytest.raises(rehearsal.SafetyError):
        rehearsal.cleanup(someone_elses)

    assert (someone_elses / "keep.txt").exists()


# --- Source validation ----------------------------------------------------------------


def test_a_missing_source_is_refused(tmp_path):
    with pytest.raises(rehearsal.SafetyError):
        rehearsal.resolve_source(str(tmp_path / "nope.db"))


def test_a_directory_as_source_is_refused(tmp_path):
    with pytest.raises(rehearsal.SafetyError):
        rehearsal.resolve_source(str(tmp_path))


def test_a_file_that_is_not_a_database_is_refused(tmp_path):
    impostor = tmp_path / "notes.db"
    impostor.write_text("this is not a database", encoding="utf-8")

    with pytest.raises(rehearsal.SafetyError):
        rehearsal.assert_sqlite_database(impostor)


def test_a_real_database_passes_the_header_check(populated):
    rehearsal.assert_sqlite_database(populated)


# --- The report is honest about what it is --------------------------------------------


def test_the_report_labels_every_timing_as_measured(populated, capsys):
    result = rehearsal.run(str(populated), keep=False)
    rehearsal.print_report(result)
    printed = capsys.readouterr().out

    assert "[MEASURED]" in printed
    assert "NOT a production disaster-recovery exercise" in printed


def test_the_report_records_the_machine_context(populated):
    result = rehearsal.run(str(populated), keep=False)

    assert result.machine["host os"]
    assert result.machine["python"]
    assert result.machine["sqlite"]
