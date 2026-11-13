"""Backup a populated database and rehearse a restore into a scratch directory.

`scripts/backup_db.py` proves a backup can be *taken*. This proves one can be *used*: the
copy is restored into a throwaway location, migrated to the current head, checked for
structural damage, and then reconciled row by row against the source it came from.

**A restore that has never been rehearsed is not a backup.** That sentence has been in
`docs/OPERATIONS.md` since Phase 1 as an unclosed production gate. This script is what
closes the local half of it.

What this is not
----------------
This is a **local restore rehearsal against a scratch copy**. It is not a production
disaster-recovery exercise: there is no production host, no off-site copy, no second
machine, and no restoration of service to real users. `docs/BACKUP_RESTORE.md` sets out
the difference in full, and neither this docstring nor the report this script prints may
be quoted as evidence of the latter.

Safety
------
The live database is opened **read-only** and is never written, renamed, moved, migrated,
or deleted. Every destination is resolved and validated *before* anything is created, and
a destination is accepted only when it sits inside the scratch root this run made for
itself. The live database, the repository, the home directory, and any file that already
exists are refused by name as well, so a mistake has to defeat two independent checks
rather than one.

Only artefacts this run created are cleaned up, and cleanup refuses to touch a directory
it did not make.

Usage, from the repository root (on Linux and macOS the interpreter is
``backend/.venv/bin/python`` rather than ``backend/.venv/Scripts/python``)::

    backend/.venv/Scripts/python scripts/restore_rehearsal.py
    backend/.venv/Scripts/python scripts/restore_rehearsal.py --source data/solaris_crm.db
    backend/.venv/Scripts/python scripts/restore_rehearsal.py --keep   # leave the scratch tree
    backend/.venv/Scripts/python scripts/restore_rehearsal.py --json report.json
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "backend"
DEFAULT_SOURCE = REPO_ROOT / "data" / "solaris_crm.db"

#: Prefix for the scratch root. Named so an abandoned directory is identifiable.
SCRATCH_PREFIX = "solaris-restore-rehearsal-"

#: A destination must carry this suffix. A plain `.db` in a scratch directory is still a
#: database somebody could later mistake for a real one; this makes the throwaway obvious
#: in a file listing, in a process list, and in an error message.
SCRATCH_DB_SUFFIX = ".rehearsal.db"


class SafetyError(RuntimeError):
    """A path was refused before anything was written."""


# --- Path validation ------------------------------------------------------------------
#
# Every function here runs before a single byte is created, and each returns a resolved
# path or raises. Validation that happens after a mkdir is validation that has already
# lost.


def resolve_source(explicit: str | None) -> Path:
    """Resolve the database to back up, preferring an explicit path then DATABASE_URL."""
    if explicit:
        candidate = Path(explicit)
    else:
        url = os.environ.get("DATABASE_URL", "")
        prefix = "sqlite:///"
        if url.startswith(prefix) and url[len(prefix) :] not in ("", ":memory:"):
            candidate = Path(url[len(prefix) :])
        else:
            candidate = DEFAULT_SOURCE

    source = candidate.expanduser().resolve()
    if not source.exists():
        raise SafetyError(f"Source database does not exist: {source}")
    if not source.is_file():
        raise SafetyError(f"Source is not a file: {source}")
    return source


def assert_sqlite_database(path: Path) -> None:
    """Refuse a source that is not actually a SQLite database.

    Backing up a text file produces a file that looks like a backup and restores into
    nothing, which is the kind of failure that is only discovered during an incident.
    """
    with path.open("rb") as handle:
        header = handle.read(16)
    if header != b"SQLite format 3\x00":
        raise SafetyError(f"Source is not a SQLite database: {path}")


def make_scratch_root() -> Path:
    """Create this run's scratch root in the system temporary directory."""
    return Path(tempfile.mkdtemp(prefix=SCRATCH_PREFIX)).resolve()


def _is_within(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def validate_scratch_destination(destination: Path, *, scratch_root: Path, source: Path) -> Path:
    """Accept a write destination only if every one of these holds.

    The positive rule -- it must be inside the scratch root this run created -- is what
    actually makes the destination safe. The named refusals below it are redundant by
    design: they restate the dangerous places explicitly so that a future change which
    loosens the positive rule still cannot write over the live database, and so that the
    refusal message names what was wrong rather than only that something was.
    """
    candidate = Path(destination).expanduser().resolve()
    scratch_root = scratch_root.resolve()

    # 1. The positive rule.
    if not _is_within(candidate, scratch_root):
        raise SafetyError(
            f"Refusing a destination outside this run's scratch root.\n"
            f"  destination: {candidate}\n"
            f"  scratch root: {scratch_root}"
        )

    # 2. Never the live database, whatever route was taken to name it.
    if candidate == source:
        raise SafetyError(f"Refusing to write to the source database: {candidate}")

    # 3. Never inside the repository -- source tree, repository root, data/, backups/.
    if _is_within(candidate, REPO_ROOT):
        raise SafetyError(f"Refusing a destination inside the repository: {candidate}")

    # 4. Never the home directory itself, nor a bare child of it. The system temporary
    #    directory often lives under the home directory on Windows, so this cannot be a
    #    blanket "anywhere under home" rule; it refuses the places a person keeps files.
    home = Path.home().resolve()
    if candidate == home or candidate.parent == home:
        raise SafetyError(f"Refusing a destination in the home directory: {candidate}")

    # 5. Never something that already exists. An existing file at a restore destination
    #    is, by definition, a database this run did not create.
    if candidate.exists():
        raise SafetyError(f"Refusing a destination that already exists: {candidate}")

    # 6. The throwaway must be named as one.
    if not candidate.name.endswith(SCRATCH_DB_SUFFIX):
        raise SafetyError(
            f"Refusing a destination not named as scratch "
            f"(expected a name ending {SCRATCH_DB_SUFFIX}): {candidate}"
        )

    return candidate


# --- Backup and restore ---------------------------------------------------------------


def online_backup(source: Path, destination: Path) -> float:
    """Copy the database through SQLite's online backup API. Returns elapsed seconds.

    The source is opened read-only through a URI, so this cannot modify it even if the
    backup API were asked to. A plain file copy is not an option: in WAL mode part of the
    committed data lives in the `-wal` file, and copying only the main file can produce a
    torn or stale database that still opens.
    """
    started = time.perf_counter()
    source_uri = f"file:{source.as_posix()}?mode=ro"
    src = sqlite3.connect(source_uri, uri=True)
    try:
        dst = sqlite3.connect(destination)
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()
    return time.perf_counter() - started


def restore_copy(backup_path: Path, destination: Path) -> float:
    """Restore the backup into a distinct scratch database. Returns elapsed seconds.

    Deliberately another online backup rather than a file copy. A restore in production
    is a copy of a file at rest and could be `cp`; doing it through the same API here
    means the rehearsal also exercises the reader on the backup, which is where a corrupt
    copy would announce itself.
    """
    started = time.perf_counter()
    src = sqlite3.connect(f"file:{backup_path.as_posix()}?mode=ro", uri=True)
    try:
        dst = sqlite3.connect(destination)
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()
    return time.perf_counter() - started


# --- Verification ---------------------------------------------------------------------

#: What gets counted on both sides. Keys are the names used in the report; values are the
#: SQL that produces the figure. Written as explicit SQL rather than ORM counts so the
#: reconciliation does not depend on the same mapping layer that wrote the data.
RECONCILED_COUNTS: dict[str, str] = {
    "customers": "SELECT COUNT(*) FROM customers",
    "shipments": "SELECT COUNT(*) FROM shipments",
    "packages": "SELECT COUNT(*) FROM shipment_packages",
    "shipment_events": "SELECT COUNT(*) FROM shipment_events",
    "tracking_references": "SELECT COUNT(*) FROM leg_tracking_references",
    "solaris_shipment_ids": "SELECT COUNT(*) FROM shipments WHERE public_id IS NOT NULL",
    "import_batches": "SELECT COUNT(*) FROM import_batches",
    "audit_records": "SELECT COUNT(*) FROM audit_events",
}

#: Relationships and identifiers, not just cardinalities. Two databases can agree on every
#: count and still disagree about which customer owns which shipment, so each of these
#: reduces a *join* to a single comparable value.
RECONCILED_RELATIONSHIPS: dict[str, str] = {
    # Every Solaris ID, in order, hashed into one string. Catches a renamed or reassigned
    # identifier that leaves the count untouched.
    "public_id_fingerprint": (
        "SELECT COALESCE(GROUP_CONCAT(public_id, '|'), '') FROM "
        "(SELECT public_id FROM shipments WHERE public_id IS NOT NULL ORDER BY public_id)"
    ),
    # Which customer each shipment belongs to.
    "shipment_customer_pairs": (
        "SELECT COALESCE(GROUP_CONCAT(pair, '|'), '') FROM "
        "(SELECT id || '>' || customer_id AS pair FROM shipments ORDER BY id)"
    ),
    # Which shipment each package belongs to, and its reference.
    "package_parentage": (
        "SELECT COALESCE(GROUP_CONCAT(pair, '|'), '') FROM "
        "(SELECT shipment_id || '>' || package_reference AS pair "
        " FROM shipment_packages ORDER BY id)"
    ),
    # Events keyed to their shipment and moment.
    "event_spine": (
        "SELECT COALESCE(GROUP_CONCAT(row, '|'), '') FROM "
        "(SELECT shipment_id || '@' || occurred_at AS row FROM shipment_events "
        " ORDER BY shipment_id, occurred_at, id)"
    ),
    # Orphan check: a foreign key that points at nothing. Should be zero on both sides,
    # and a non-zero equal value would still be a finding worth seeing.
    "orphan_shipments": (
        "SELECT COUNT(*) FROM shipments s "
        "LEFT JOIN customers c ON c.id = s.customer_id WHERE c.id IS NULL"
    ),
    "orphan_packages": (
        "SELECT COUNT(*) FROM shipment_packages p "
        "LEFT JOIN shipments s ON s.id = p.shipment_id WHERE s.id IS NULL"
    ),
}


def read_scalars(path: Path, statements: dict[str, str]) -> dict[str, object]:
    """Run each statement against a read-only connection and collect single values."""
    results: dict[str, object] = {}
    con = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    try:
        for name, sql in statements.items():
            try:
                row = con.execute(sql).fetchone()
                results[name] = row[0] if row else None
            except sqlite3.Error as exc:
                results[name] = f"error: {exc.__class__.__name__}"
    finally:
        con.close()
    return results


def structural_checks(path: Path) -> dict[str, object]:
    """`integrity_check` and `foreign_key_check` on the restored database."""
    con = sqlite3.connect(path)
    try:
        con.execute("PRAGMA foreign_keys=ON")
        integrity = con.execute("PRAGMA integrity_check").fetchall()
        foreign_keys = con.execute("PRAGMA foreign_key_check").fetchall()
        page_count = con.execute("PRAGMA page_count").fetchone()[0]
        page_size = con.execute("PRAGMA page_size").fetchone()[0]
    finally:
        con.close()
    return {
        "integrity_check": [row[0] for row in integrity],
        "integrity_ok": len(integrity) == 1 and integrity[0][0] == "ok",
        "foreign_key_violations": [tuple(row) for row in foreign_keys],
        "foreign_keys_ok": not foreign_keys,
        "page_count": page_count,
        "page_size": page_size,
    }


def stamped_revision(path: Path) -> str | None:
    con = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    try:
        row = con.execute("SELECT version_num FROM alembic_version").fetchone()
    except sqlite3.Error:
        return None
    finally:
        con.close()
    return row[0] if row else None


def _alembic(args: list[str], *, database: Path) -> subprocess.CompletedProcess[str]:
    """Run Alembic against a specific database, in a subprocess.

    A subprocess rather than an in-process call because `alembic/env.py` reads the
    cached application settings, and those are bound at import time. Passing
    `DATABASE_URL` to a fresh interpreter is the only way to be certain the migration
    runs against the scratch file and not against whatever the parent process loaded.
    """
    env = dict(os.environ)
    env["DATABASE_URL"] = f"sqlite:///{database.as_posix()}"
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=BACKEND_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def current_head() -> str | None:
    result = _alembic(["heads"], database=Path(os.devnull))
    if result.returncode != 0:
        return None
    first = result.stdout.strip().splitlines()[0] if result.stdout.strip() else ""
    return first.split()[0] if first else None


def upgrade_to_head(database: Path) -> tuple[bool, str]:
    result = _alembic(["upgrade", "head"], database=database)
    output = (result.stdout + result.stderr).strip()
    return result.returncode == 0, output


# --- Report ---------------------------------------------------------------------------


@dataclass
class Rehearsal:
    machine: dict[str, str]
    source: str
    source_bytes: int
    backup_bytes: int = 0
    backup_seconds: float = 0.0
    restore_seconds: float = 0.0
    verify_seconds: float = 0.0
    migration_needed: bool = False
    migration_output: str = ""
    expected_head: str | None = None
    restored_revision_before: str | None = None
    restored_revision_after: str | None = None
    structural: dict[str, object] = field(default_factory=dict)
    counts_source: dict[str, object] = field(default_factory=dict)
    counts_restored: dict[str, object] = field(default_factory=dict)
    relationships_source: dict[str, object] = field(default_factory=dict)
    relationships_restored: dict[str, object] = field(default_factory=dict)
    source_unchanged: bool = False
    cleaned_up: list[str] = field(default_factory=list)
    scratch_root: str = ""

    @property
    def count_mismatches(self) -> list[str]:
        return [
            k for k in RECONCILED_COUNTS if self.counts_source.get(k) != self.counts_restored.get(k)
        ]

    @property
    def relationship_mismatches(self) -> list[str]:
        return [
            k
            for k in RECONCILED_RELATIONSHIPS
            if self.relationships_source.get(k) != self.relationships_restored.get(k)
        ]

    @property
    def ok(self) -> bool:
        return (
            bool(self.structural.get("integrity_ok"))
            and bool(self.structural.get("foreign_keys_ok"))
            and not self.count_mismatches
            and not self.relationship_mismatches
            and self.restored_revision_after == self.expected_head
            and self.source_unchanged
        )

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "machine": self.machine,
            "source": self.source,
            "source_bytes": self.source_bytes,
            "backup_bytes": self.backup_bytes,
            "timings_seconds_measured": {
                "backup": round(self.backup_seconds, 4),
                "restore": round(self.restore_seconds, 4),
                "verify": round(self.verify_seconds, 4),
            },
            "migration_needed": self.migration_needed,
            "expected_head": self.expected_head,
            "restored_revision_before": self.restored_revision_before,
            "restored_revision_after": self.restored_revision_after,
            "structural": self.structural,
            "counts_source": self.counts_source,
            "counts_restored": self.counts_restored,
            "count_mismatches": self.count_mismatches,
            "relationship_mismatches": self.relationship_mismatches,
            "source_unchanged": self.source_unchanged,
            "cleaned_up": self.cleaned_up,
        }


def _fmt_bytes(value: int) -> str:
    return f"{value / (1024 * 1024):.2f} MiB ({value:,} bytes)"


def print_report(r: Rehearsal) -> None:
    line = "=" * 78
    print(line)
    print("SOLARIS CRM - BACKUP AND SCRATCH-RESTORE REHEARSAL")
    print(line)
    print()
    print("This is a LOCAL restore rehearsal against a scratch copy.")
    print("It is NOT a production disaster-recovery exercise: no production host, no")
    print("off-site copy, no second machine, and no restoration of service to users.")
    print()
    print("-- Machine context (every timing below was measured here) " + "-" * 20)
    for key, value in r.machine.items():
        print(f"  {key:20s} {value}")
    print()
    print("-- Backup " + "-" * 68)
    print(f"  source               {r.source}")
    print(f"  source size          {_fmt_bytes(r.source_bytes)}")
    print(f"  backup size          {_fmt_bytes(r.backup_bytes)}   [MEASURED]")
    print("  source opened        read-only (file:...?mode=ro)")
    print("  mechanism            sqlite3.Connection.backup (online backup API)")
    print(f"  source unchanged     {'yes' if r.source_unchanged else 'NO - INVESTIGATE'}")
    print()
    print("-- Timings (MEASURED on the machine above, not estimates) " + "-" * 20)
    print(f"  backup               {r.backup_seconds:8.3f} s   [MEASURED]")
    print(f"  restore              {r.restore_seconds:8.3f} s   [MEASURED]")
    print(f"  verification         {r.verify_seconds:8.3f} s   [MEASURED]")
    total = r.backup_seconds + r.restore_seconds + r.verify_seconds
    print(f"  total                {total:8.3f} s   [MEASURED]")
    print()
    print("-- Migration " + "-" * 65)
    print(f"  expected head        {r.expected_head}")
    print(f"  restored, as copied  {r.restored_revision_before}")
    print(f"  upgrade required     {'yes' if r.migration_needed else 'no (already at head)'}")
    print(f"  restored, after      {r.restored_revision_after}")
    if r.migration_output:
        for out in r.migration_output.splitlines():
            print(f"    | {out}")
    print()
    print("-- Structural checks on the restored database " + "-" * 32)
    integrity = r.structural.get("integrity_check")
    print(f"  PRAGMA integrity_check      {integrity}")
    print(f"  PRAGMA foreign_key_check    {r.structural.get('foreign_key_violations') or 'clean'}")
    print(
        f"  pages                       {r.structural.get('page_count')}"
        f" x {r.structural.get('page_size')} bytes"
    )
    print()
    print("-- Reconciliation: counts " + "-" * 52)
    print(f"  {'metric':28s} {'source':>10s} {'restored':>10s}   result")
    for key in RECONCILED_COUNTS:
        a = r.counts_source.get(key)
        b = r.counts_restored.get(key)
        mark = "match" if a == b else "*** MISMATCH ***"
        note = ""
        if a == 0 and b == 0:
            note = "  (both zero - see note)"
        print(f"  {key:28s} {a!s:>10s} {b!s:>10s}   {mark}{note}")
    print()
    print("-- Reconciliation: relationships and identifiers " + "-" * 29)
    for key in RECONCILED_RELATIONSHIPS:
        a = r.relationships_source.get(key)
        b = r.relationships_restored.get(key)
        mark = "match" if a == b else "*** MISMATCH ***"
        shown = str(a)
        if len(shown) > 28:
            shown = f"{len(shown)} chars, digest-compared"
        print(f"  {key:28s} {shown:>34s}   {mark}")
    print()
    print("-- Cleanup " + "-" * 67)
    for path in r.cleaned_up:
        print(f"  removed              {path}")
    if not r.cleaned_up:
        print(f"  kept                 {r.scratch_root}")
    print()
    print(line)
    print("RESULT: " + ("PASS - restore rehearsed and reconciled" if r.ok else "FAIL - see above"))
    print(line)


# --- Orchestration --------------------------------------------------------------------


def run(source_arg: str | None, *, keep: bool) -> Rehearsal:
    source = resolve_source(source_arg)
    assert_sqlite_database(source)

    # Fingerprint the source before and after so "never modified" is demonstrated rather
    # than asserted. mtime_ns and size together catch any write that landed.
    before_stat = source.stat()

    rehearsal = Rehearsal(
        machine={
            "host os": f"{platform.system()} {platform.release()}",
            "machine": platform.machine(),
            "python": platform.python_version(),
            "sqlite": sqlite3.sqlite_version,
            "run at (UTC)": datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%SZ"),
        },
        source=str(source),
        source_bytes=before_stat.st_size,
    )

    scratch_root = make_scratch_root()
    rehearsal.scratch_root = str(scratch_root)
    created_root = scratch_root

    try:
        backup_dir = scratch_root / "backup"
        restore_dir = scratch_root / "restore"
        backup_dir.mkdir()
        restore_dir.mkdir()

        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        backup_path = validate_scratch_destination(
            backup_dir / f"solaris_crm-{stamp}{SCRATCH_DB_SUFFIX}",
            scratch_root=scratch_root,
            source=source,
        )
        restore_path = validate_scratch_destination(
            restore_dir / f"restored-{stamp}{SCRATCH_DB_SUFFIX}",
            scratch_root=scratch_root,
            source=source,
        )

        rehearsal.backup_seconds = online_backup(source, backup_path)
        rehearsal.backup_bytes = backup_path.stat().st_size

        rehearsal.restore_seconds = restore_copy(backup_path, restore_path)

        verify_started = time.perf_counter()

        rehearsal.expected_head = current_head()
        rehearsal.restored_revision_before = stamped_revision(restore_path)
        rehearsal.migration_needed = rehearsal.restored_revision_before != rehearsal.expected_head
        if rehearsal.migration_needed:
            ok, output = upgrade_to_head(restore_path)
            rehearsal.migration_output = output
            if not ok:
                raise RuntimeError(f"Alembic upgrade failed against the scratch copy:\n{output}")
        rehearsal.restored_revision_after = stamped_revision(restore_path)

        rehearsal.structural = structural_checks(restore_path)
        rehearsal.counts_source = read_scalars(source, RECONCILED_COUNTS)
        rehearsal.counts_restored = read_scalars(restore_path, RECONCILED_COUNTS)
        rehearsal.relationships_source = read_scalars(source, RECONCILED_RELATIONSHIPS)
        rehearsal.relationships_restored = read_scalars(restore_path, RECONCILED_RELATIONSHIPS)

        rehearsal.verify_seconds = time.perf_counter() - verify_started

        after_stat = source.stat()
        rehearsal.source_unchanged = (
            after_stat.st_size == before_stat.st_size
            and after_stat.st_mtime_ns == before_stat.st_mtime_ns
        )
        return rehearsal
    finally:
        if keep:
            print(f"\n[--keep] scratch tree left at {created_root}\n")
        else:
            rehearsal.cleaned_up = cleanup(created_root)


def cleanup(scratch_root: Path) -> list[str]:
    """Remove only a directory this run created, identified by its prefix.

    The prefix check is the guard. Being handed the wrong path is exactly the situation
    where a recursive delete must decline, so it declines rather than reporting success.
    """
    root = scratch_root.resolve()
    if not root.name.startswith(SCRATCH_PREFIX):
        raise SafetyError(f"Refusing to remove a directory this run did not create: {root}")
    if not root.exists():
        return []
    shutil.rmtree(root)
    return [str(root)]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Back up a populated database and rehearse a restore into scratch."
    )
    parser.add_argument("--source", help="Database to rehearse against. Never written to.")
    parser.add_argument(
        "--keep",
        action="store_true",
        help="Leave the scratch tree in place for inspection.",
    )
    parser.add_argument("--json", help="Also write the machine-readable report here.")
    args = parser.parse_args(argv)

    try:
        rehearsal = run(args.source, keep=args.keep)
    except SafetyError as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2

    print_report(rehearsal)

    if args.json:
        target = Path(args.json).expanduser().resolve()
        target.write_text(json.dumps(rehearsal.to_dict(), indent=2), encoding="utf-8")
        print(f"\nJSON report written: {target}")

    return 0 if rehearsal.ok else 1


if __name__ == "__main__":
    sys.exit(main())
