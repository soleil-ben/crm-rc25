"""Delete an owner-approved, frozen set of rows from the development database.

This tool deletes nothing it was not handed by primary key. It takes a manifest naming
every row, re-proves every claim in that manifest **inside the write transaction**, and
rolls back if anything has moved since the manifest was frozen.

Why it works from a manifest rather than from a predicate
---------------------------------------------------------
The predicate that found these rows is in ``scripts/incident_db_diff.py`` and it is a good
predicate. It is still the wrong thing to delete with. A predicate evaluated at deletion
time answers "what matches now", and the thing an owner approved was "these rows, this
many, with these properties, as measured then". Those are the same set only if nothing
changed in between -- which is exactly the assumption a deletion must not make. So the
manifest carries primary keys and a fingerprint per row, and this tool refuses if a single
fingerprint differs.

The same reasoning rules out a marker-only, suffix-only, domain-only or timestamp-only
``DELETE ... WHERE``. Each would be a sentence that *means* the approved set today and
could mean something larger tomorrow.

What it will not do
-------------------
No ``VACUUM``. No sequence reset. No ``last_login_at`` repair. No session deletion. No
trigger or constraint disabled -- ``PRAGMA foreign_keys`` is on for the whole run, so the
database enforces the dependency order rather than trusting this file to get it right. No
Alembic state is touched. It refuses outright to run against a UAT database, an ``.e2e.db``,
anything under ``backups/``, or a production environment.

Usage, from the repository root (on Linux and macOS the interpreter is
``backend/.venv/bin/python`` rather than ``backend/.venv/Scripts/python``)::

    backend/.venv/Scripts/python scripts/incident_cleanup.py --manifest <path>
    backend/.venv/Scripts/python scripts/incident_cleanup.py --manifest <path> --execute
    backend/.venv/Scripts/python scripts/incident_cleanup.py --manifest <path> --verify

``--dry-run`` is the default and is what the first form does. ``--execute`` performs the
deletion in one transaction. ``--verify`` re-checks the retained-row fingerprints after the
fact.

Output is aggregate counts only. The manifest holds primary keys and public identifiers and
is deliberately not committed; nothing in this file writes a customer value anywhere.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "backend"
sys.path.insert(0, str(BACKEND_ROOT))

from app.core import e2e_guard  # noqa: E402  (needs the path above)

#: What the owner approved, per table and in total. Named rather than written inline
#: because the tool compares against it in two places, and two literals that must agree is
#: one literal too many. Changing these is changing what was approved.
APPROVED_TARGETS = {
    "customers": 98,
    "import_batches": 78,
    "import_batch_rows": 88,
    "audit_events": 72,
}
APPROVED_TOTAL = 336

#: Deletion order, children before parents. Read from the manifest's ``order`` field and
#: checked against this, so a manifest cannot quietly reorder the deletion.
EXPECTED_ORDER = ["audit_events", "import_batch_rows", "import_batches", "customers"]


class SafetyError(RuntimeError):
    """A precondition failed. Nothing was deleted."""


# --- Target safety -------------------------------------------------------------------


def validated_database(path: Path) -> Path:
    """The database this tool is allowed to modify: the development one, and only it."""
    environment = os.environ.get("ENVIRONMENT", "development").strip().lower()
    if environment.startswith("prod"):
        raise SafetyError(f"ENVIRONMENT={environment!r}. This never runs against production.")
    if e2e_guard.is_e2e_environment(environment):
        raise SafetyError("ENVIRONMENT=e2e. This tool is not part of a test run.")

    resolved = e2e_guard.canonical(path)
    if not resolved.exists():
        raise SafetyError(f"No database at {resolved.as_posix()}")
    if resolved.name.lower().endswith(e2e_guard.E2E_DB_SUFFIX):
        raise SafetyError("That is an end-to-end scratch database.")
    if e2e_guard.is_within(resolved, e2e_guard.canonical(e2e_guard.E2E_DIR)):
        raise SafetyError("That is inside the end-to-end scratch directory.")
    if e2e_guard.is_within(resolved, e2e_guard.canonical(e2e_guard.UAT_DIR)):
        raise SafetyError("That is the UAT database. Nothing here repairs UAT.")
    if e2e_guard.is_within(resolved, e2e_guard.canonical(e2e_guard.BACKUP_DIR)):
        raise SafetyError("That is inside the backup directory. A backup is never a target.")
    if resolved != e2e_guard.canonical(e2e_guard.DEV_DB):
        raise SafetyError(
            f"{resolved.as_posix()} is not the repository development database. "
            "This tool exists for one approved cleanup and will not be pointed elsewhere."
        )
    return resolved


# --- Fingerprints ---------------------------------------------------------------------


def fingerprint(row: tuple) -> str:
    joined = "\x1f".join("\x00" if value is None else str(value) for value in row)
    return hashlib.sha256(joined.encode("utf-8", "replace")).hexdigest()


def fingerprints_for(connection: sqlite3.Connection, table: str, ids: list[int]) -> dict[int, str]:
    columns = [row[1] for row in connection.execute(f'PRAGMA table_info("{table}")')]
    id_index = columns.index("id")
    selected = ", ".join(f'"{name}"' for name in columns)
    out: dict[int, str] = {}
    for start in range(0, len(ids), 400):
        chunk = ids[start : start + 400]
        placeholders = ", ".join("?" for _ in chunk)
        for row in connection.execute(
            f'SELECT {selected} FROM "{table}" WHERE id IN ({placeholders})',  # noqa: S608
            chunk,
        ):
            out[row[id_index]] = fingerprint(row)
    return out


# --- Preconditions ----------------------------------------------------------------------


def check_manifest(
    connection: sqlite3.Connection, manifest: dict
) -> tuple[list[str], dict[str, int]]:
    """Re-prove every claim. Returns (problems, per-table target counts).

    Run twice: once for the dry run, and once again inside the write transaction. The
    second run is the one that matters -- it is the only check whose result cannot be
    invalidated by something committing between the check and the delete.
    """
    problems: list[str] = []
    counts: dict[str, int] = {}

    tables = list(manifest["targets"])
    ordered = sorted(tables, key=lambda name: manifest["targets"][name]["order"])
    if ordered != EXPECTED_ORDER:
        problems.append(f"deletion order {ordered} is not the expected {EXPECTED_ORDER}")

    missing_total = 0
    mismatch_total = 0
    for table in ordered:
        rows = manifest["targets"][table]["rows"]
        counts[table] = len(rows)
        ids = [row["id"] for row in rows]
        if len(set(ids)) != len(ids):
            problems.append(f"{table}: the manifest lists a primary key twice")

        present = fingerprints_for(connection, table, ids)
        missing = [i for i in ids if i not in present]
        if missing:
            missing_total += len(missing)
            problems.append(f"{table}: {len(missing)} manifest row(s) no longer exist")
        mismatched = [
            row["id"]
            for row in rows
            if row["id"] in present and present[row["id"]] != row["fingerprint"]
        ]
        if mismatched:
            mismatch_total += len(mismatched)
            problems.append(f"{table}: {len(mismatched)} row(s) changed since the manifest")

    counts["_missing"] = missing_total
    counts["_fingerprint_mismatches"] = mismatch_total

    # Nothing retained may reference a targeted customer.
    customer_ids = [row["id"] for row in manifest["targets"]["customers"]["rows"]]
    placeholders = ", ".join("?" for _ in customer_ids)
    retained_references = 0
    for table, column in CUSTOMER_REFERENCES:
        hits = connection.execute(
            f'SELECT COUNT(*) FROM "{table}" WHERE "{column}" IN ({placeholders})',  # noqa: S608
            customer_ids,
        ).fetchone()[0]
        if hits:
            retained_references += hits
            problems.append(f"{hits} retained row(s) in {table}.{column} reference a target")
    merged = connection.execute(
        f"SELECT COUNT(*) FROM customers WHERE merged_into_customer_id IN ({placeholders})",  # noqa: S608
        customer_ids,
    ).fetchone()[0]
    if merged:
        retained_references += merged
        problems.append(f"{merged} customer(s) are merged into a targeted customer")
    counts["_retained_references"] = retained_references

    # The retained audit events must not overlap the targets.
    audit_targets = {row["id"] for row in manifest["targets"]["audit_events"]["rows"]}
    retained_audits = {
        int(key) for key in manifest["retained_proofs"]["audit_events_session_attributed"]
    }
    overlap = audit_targets & retained_audits
    if overlap:
        problems.append(f"{len(overlap)} audit event(s) are both targeted and retained")
    counts["_retained_audits"] = len(retained_audits)

    # Sessions, provenance and the Customer Account tables are not targets at all.
    if "user_sessions" in manifest["targets"]:
        problems.append("the manifest targets user_sessions; it must not")
    if "role_merge_provenance" in manifest["targets"]:
        problems.append("the manifest targets role_merge_provenance; it must not")
    for table in ACCOUNT_TABLES:
        if table in manifest["targets"]:
            problems.append(f"the manifest targets {table}; it must not")
        count = connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]  # noqa: S608
        if count:
            problems.append(f"{table} holds {count} row(s); it must be empty")

    return problems, counts


#: Every foreign key into ``customers``, excluding ``import_batch_rows`` which is itself a
#: target. Mirrors ``PRAGMA foreign_key_list`` output at revision 6af30fcdd3a8; the
#: database enforces the real thing, and this is what produces a readable refusal first.
CUSTOMER_REFERENCES = [
    ("consent_events", "customer_id"),
    ("customer_account_approval_attempts", "customer_id"),
    ("customer_account_disclosure_acknowledgements", "customer_id"),
    ("customer_addresses", "customer_id"),
    ("customer_data_proposals", "customer_id"),
    ("customer_id_aliases", "customer_id"),
    ("customer_identity_links", "customer_id"),
    ("customer_route_interests", "customer_id"),
    ("customer_tags", "customer_id"),
    ("follow_up_tasks", "customer_id"),
    ("interactions", "customer_id"),
    ("referrals", "referred_customer_id"),
    ("referrals", "referrer_customer_id"),
    ("service_issues", "customer_id"),
    ("shipments", "customer_id"),
]

ACCOUNT_TABLES = [
    "customer_identities",
    "customer_identity_links",
    "customer_sessions",
    "customer_auth_tokens",
    "customer_data_proposals",
    "customer_data_proposal_fields",
    "customer_registration_attempts",
    "customer_terms_acknowledgements",
    "customer_notification_preferences",
    "customer_id_aliases",
    "customer_account_approval_attempts",
    "customer_account_disclosure_acknowledgements",
]

#: The counts that must hold before the deletion, and after it. Both are checked; a
#: baseline that has moved means the manifest describes a database that no longer exists.
BASELINE_BEFORE = {
    "customers": 109,
    "import_batches": 78,
    "import_batch_rows": 88,
    "audit_events": 607,
    "user_sessions": 85,
    "role_merge_provenance": 2,
}


def current_counts(connection: sqlite3.Connection, tables) -> dict[str, int]:
    return {
        table: connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]  # noqa: S608
        for table in tables
    }


def report(label: str, actual: dict[str, int], expected: dict[str, int]) -> list[str]:
    problems: list[str] = []
    print(f"  {label}:")
    for table, want in expected.items():
        got = actual.get(table)
        state = "ok  " if got == want else "FAIL"
        print(f"    {state} {table:<24} {got} (expected {want})")
        if got != want:
            problems.append(f"{label}: {table} is {got}, expected {want}")
    return problems


# --- Modes --------------------------------------------------------------------------------


def open_database(path: Path, *, writable: bool) -> sqlite3.Connection:
    if not writable:
        return sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    # `isolation_level=None` hands transaction control to this file rather than to the
    # driver, which is the only way `BEGIN IMMEDIATE` happens where it is written.
    connection = sqlite3.connect(str(path), isolation_level=None)
    connection.execute("PRAGMA foreign_keys=ON")
    enabled = connection.execute("PRAGMA foreign_keys").fetchone()[0]
    if not enabled:
        connection.close()
        raise SafetyError("foreign key enforcement could not be enabled")
    return connection


def summarise(counts: dict[str, int], manifest: dict) -> list[str]:
    problems: list[str] = []
    approved = {table: len(manifest["targets"][table]["rows"]) for table in EXPECTED_ORDER}
    expected_targets = APPROVED_TARGETS
    print("  targets:")
    for table, want in expected_targets.items():
        got = approved.get(table)
        state = "ok  " if got == want else "FAIL"
        print(f"    {state} {table:<24} {got} (approved {want})")
        if got != want:
            problems.append(f"{table} targets {got}, approved {want}")
    total = sum(approved.values())
    total_state = "ok  " if total == APPROVED_TOTAL else "FAIL"
    print(f"    {total_state} {'total':<24} {total} (approved {APPROVED_TOTAL})")
    if total != APPROVED_TOTAL:
        problems.append(f"total targets {total}, approved {APPROVED_TOTAL}")

    for key, label, want in (
        ("_retained_references", "unexpected retained-row references", 0),
        ("_missing", "missing manifest rows", 0),
        ("_fingerprint_mismatches", "fingerprint mismatches", 0),
    ):
        got = counts.get(key, 0)
        state = "ok  " if got == want else "FAIL"
        print(f"    {state} {label:<40} {got}")
        if got != want:
            problems.append(f"{label}: {got}")
    print(f"    ok   retained session-attributed audits      {counts.get('_retained_audits')}")
    return problems


def dry_run(path: Path, manifest: dict) -> int:
    print(f"DRY RUN against {path.name} -- nothing will be written.\n")
    connection = open_database(path, writable=False)
    try:
        problems = report("baseline", current_counts(connection, BASELINE_BEFORE), BASELINE_BEFORE)
        if problems:
            print("\nBaseline has moved. Re-run the read-only incident analysis.")
            for problem in problems:
                print(f"  - {problem}")
            return 1
        manifest_problems, counts = check_manifest(connection, manifest)
        problems += summarise(counts, manifest)
        problems += manifest_problems
        expected_after = dict(manifest["expected_after"])
        print("  expected after cleanup:")
        for table, want in expected_after.items():
            print(f"    -    {table:<24} {want}")
    finally:
        connection.close()

    if problems:
        print(f"\nDRY RUN FAILED: {len(problems)} problem(s).")
        for problem in dict.fromkeys(problems):
            print(f"  - {problem}")
        return 1
    print("\nDRY RUN OK. Every precondition holds. Re-run with --execute to delete.")
    return 0


def execute(path: Path, manifest: dict) -> int:
    print(f"EXECUTING against {path.name}\n")
    connection = open_database(path, writable=True)
    deleted: dict[str, int] = {}
    try:
        # The write lock is taken FIRST, before the final fingerprint check, so that
        # nothing can commit between the check and the delete. A deferred BEGIN would
        # take the lock at the first DELETE instead, leaving exactly that gap.
        connection.execute("BEGIN IMMEDIATE")
        print("  write transaction acquired (BEGIN IMMEDIATE)")

        problems = report("baseline", current_counts(connection, BASELINE_BEFORE), BASELINE_BEFORE)
        manifest_problems, counts = check_manifest(connection, manifest)
        problems += summarise(counts, manifest)
        problems += manifest_problems
        if problems:
            connection.execute("ROLLBACK")
            print(f"\nROLLED BACK: {len(problems)} precondition(s) failed inside the transaction.")
            for problem in dict.fromkeys(problems):
                print(f"  - {problem}")
            return 1

        print("\n  deleting, children before parents:")
        for table in EXPECTED_ORDER:
            ids = [row["id"] for row in manifest["targets"][table]["rows"]]
            removed = 0
            for start in range(0, len(ids), 400):
                chunk = ids[start : start + 400]
                placeholders = ", ".join("?" for _ in chunk)
                cursor = connection.execute(
                    f'DELETE FROM "{table}" WHERE id IN ({placeholders})',  # noqa: S608
                    chunk,
                )
                removed += cursor.rowcount
            deleted[table] = removed
            print(f"    {table:<24} {removed}")
            if removed != len(ids):
                connection.execute("ROLLBACK")
                print(f"\nROLLED BACK: {table} removed {removed}, expected {len(ids)}.")
                return 1

        total = sum(deleted.values())
        print(f"    {'total':<24} {total}")
        if total != APPROVED_TOTAL:
            connection.execute("ROLLBACK")
            print(f"\nROLLED BACK: deleted {total}, approved {APPROVED_TOTAL}.")
            return 1

        after = current_counts(connection, manifest["expected_after"])
        problems = report("after, inside the transaction", after, manifest["expected_after"])
        violations = connection.execute("PRAGMA foreign_key_check").fetchall()
        print(
            f"    {'ok  ' if not violations else 'FAIL'} foreign_key_check "
            f"{len(violations)} violation(s)"
        )
        if violations:
            problems.append(f"{len(violations)} foreign key violation(s)")
        if problems:
            connection.execute("ROLLBACK")
            print(f"\nROLLED BACK: {len(problems)} post-condition(s) failed.")
            for problem in dict.fromkeys(problems):
                print(f"  - {problem}")
            return 1

        connection.execute("COMMIT")
        print("\nCOMMITTED.")
    except Exception as error:  # noqa: BLE001 - any failure must roll back
        try:
            connection.execute("ROLLBACK")
            print(f"\nROLLED BACK on exception: {type(error).__name__}: {error}")
        except sqlite3.Error:
            print(f"\nException with no active transaction: {type(error).__name__}: {error}")
        return 1
    finally:
        connection.close()
    return 0


def verify(path: Path, manifest: dict) -> int:
    """After the fact: targets gone, everything retained byte-for-byte where it was."""
    print(f"VERIFYING {path.name}\n")
    connection = open_database(path, writable=False)
    problems: list[str] = []
    try:
        problems += report(
            "counts",
            current_counts(connection, manifest["expected_after"]),
            manifest["expected_after"],
        )

        print("  targets absent:")
        for table in EXPECTED_ORDER:
            ids = [row["id"] for row in manifest["targets"][table]["rows"]]
            still_there = 0
            for start in range(0, len(ids), 400):
                chunk = ids[start : start + 400]
                placeholders = ", ".join("?" for _ in chunk)
                still_there += connection.execute(
                    f'SELECT COUNT(*) FROM "{table}" WHERE id IN ({placeholders})',  # noqa: S608
                    chunk,
                ).fetchone()[0]
            state = "ok  " if still_there == 0 else "FAIL"
            print(f"    {state} {table:<24} {len(ids)} targeted, {still_there} still present")
            if still_there:
                problems.append(f"{still_there} targeted row(s) remain in {table}")

        print("  retained rows unchanged:")
        for label, table in (
            ("customers", "customers"),
            ("audit_events_session_attributed", "audit_events"),
            ("audit_events_pre_boundary", "audit_events"),
            ("user_sessions", "user_sessions"),
        ):
            expected = {int(k): v for k, v in manifest["retained_proofs"][label].items()}
            actual = fingerprints_for(connection, table, sorted(expected))
            missing = [i for i in expected if i not in actual]
            changed = [i for i, f in expected.items() if i in actual and actual[i] != f]
            state = "ok  " if not missing and not changed else "FAIL"
            print(
                f"    {state} {label:<36} {len(expected)} rows, "
                f"{len(missing)} missing, {len(changed)} changed"
            )
            if missing:
                problems.append(f"{label}: {len(missing)} retained row(s) missing")
            if changed:
                problems.append(f"{label}: {len(changed)} retained row(s) changed")

        print("  integrity:")
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        violations = connection.execute("PRAGMA foreign_key_check").fetchall()
        revision = connection.execute("SELECT version_num FROM alembic_version").fetchone()[0]
        print(f"    {'ok  ' if integrity == 'ok' else 'FAIL'} integrity_check   {integrity}")
        print(
            f"    {'ok  ' if not violations else 'FAIL'} foreign_key_check  "
            f"{len(violations)} violation(s)"
        )
        print(
            f"    {'ok  ' if revision == '6af30fcdd3a8' else 'FAIL'} alembic           {revision}"
        )
        if integrity != "ok":
            problems.append(f"integrity_check: {integrity}")
        if violations:
            problems.append(f"{len(violations)} foreign key violation(s)")
        if revision != "6af30fcdd3a8":
            problems.append(f"alembic revision {revision}")

        links = connection.execute("SELECT COUNT(*) FROM customer_identity_links").fetchone()[0]
        print(
            f"    {'ok  ' if links == 0 else 'FAIL'} customer_identity_links {links} "
            "(no effective link can point at a tombstone: there are none)"
        )
        if links:
            problems.append(f"customer_identity_links holds {links} row(s)")
    finally:
        connection.close()

    if problems:
        print(f"\nVERIFY FAILED: {len(problems)} problem(s).")
        for problem in dict.fromkeys(problems):
            print(f"  - {problem}")
        return 1
    print("\nVERIFY OK.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Apply an approved, frozen row deletion.")
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--database", type=Path, default=e2e_guard.DEV_DB)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", default=True)
    mode.add_argument("--execute", action="store_true")
    mode.add_argument("--verify", action="store_true")
    args = parser.parse_args(argv)

    try:
        database = validated_database(args.database)
    except SafetyError as refused:
        print(f"Refused: {refused}", file=sys.stderr)
        return 2

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    digest = hashlib.sha256(args.manifest.read_bytes()).hexdigest()
    print(f"manifest       : {args.manifest.name}")
    print(f"manifest sha256: {digest}\n")

    if args.verify:
        return verify(database, manifest)
    if args.execute:
        return execute(database, manifest)
    return dry_run(database, manifest)


if __name__ == "__main__":
    raise SystemExit(main())
