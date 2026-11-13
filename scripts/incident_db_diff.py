"""Read-only difference report between two Solaris databases.

Written for the 2026-09-20 incident, and kept because the next one will want it too.

**It opens both databases read-only** (``file:...?mode=ro``), writes nothing, creates
nothing, and deletes nothing. It is safe to run against the development database while
deciding what to do about it, which is the only reason it exists: the decision needs
evidence, and getting the evidence must not be another write.

What it reports, and what it refuses to
---------------------------------------
For every table in either database it reports **counts and classifications, never values**:
inserted, deleted and updated row counts; the earliest and latest timestamp among the
inserted rows; whether those rows carry a deterministic end-to-end marker; whether they are
reachable from a marked row through a foreign key; and how many could not be attributed
either way.

It never prints a name, an address, an email address, a phone number, a tracking reference,
a session token, an IP address, a CSV cell or an audit summary. The one identifier it will
print is a *public id* of a marked row, and only under ``--show-marked-ids``, which is off
by default -- a public id is what an operator needs to act on a decision, and it is still
not something to leave sitting in a committed report.

How attribution works
---------------------
The browser suite leaves a deterministic mark. Each staff spec mints a per-run token --
``E2E<base36>``, ``A11Y<base36>`` or ``KB<base36>`` -- and stamps it into every row it
writes: appended to ``full_name``, and, for rows created through the CSV import, as the
prefix of ``source_record_id``. Nothing else in the application produces that shape: the
seed does not, the UAT fixture does not, and a person typing a customer in would have to
type it deliberately.

An inserted row is then counted in exactly one of four classes, the strongest that reaches
it:

``marker``
    the row carries a run token itself. The strongest evidence there is.
``closure``
    the row does not, but a foreign key or a public identifier leads from it to one that
    does -- an import row pointing at a marked customer, an audit event naming a marked
    customer's public id, a batch every one of whose rows is marked.
``session``
    the row references no entity at all, so nothing in it can carry or reach a marker. A
    CSV *preview* audit, an export audit and a login audit are all of this kind. These are
    attributed by actor and time: a reserved demo identity, acting inside a window the
    marked rows themselves define. **This is inference, not proof**, which is why it has
    its own column and is never added to the two above.
``unattributed``
    none of the above reached it. Reported on its own and never folded into a neighbour,
    because the difference between "we know" and "we assume" is the whole value of this
    report -- and because a single unattributed row is what closes off a targeted deletion.

Usage (on Linux and macOS the interpreter is ``backend/.venv/bin/python`` rather
than ``backend/.venv/Scripts/python``)::

    backend/.venv/Scripts/python scripts/incident_db_diff.py \
        --before backups/<pre-incident>.db \
        --after  data/solaris_crm.db \
        --out    docs/incidents/<name>-diff.md
"""

from __future__ import annotations

import argparse
import hashlib
import sqlite3
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

#: Column names that carry a time, in the order they are preferred for a table's summary.
TIMESTAMP_COLUMNS = (
    "occurred_at",
    "created_at",
    "committed_at",
    "started_at",
    "recorded_at",
    "updated_at",
    "last_seen_at",
)

#: The per-run tokens the browser specs stamp into everything they create.
#:
#: Each staff spec mints one at startup and puts it in two places: appended to every
#: ``full_name`` it writes, and, for the rows it creates through the CSV import, as the
#: prefix of ``source_record_id``. The three prefixes are the three specs that write:
#:
#: * ``E2E``  -- ``staffImportExport.spec.js``
#: * ``A11Y`` -- ``staffAccessibility.spec.js``
#: * ``KB``   -- ``staffKeyboard.spec.js``
#:
#: The name suffix is the stronger of the two, because it is the only one the keyboard
#: spec's directly-created customer carries -- that row is typed into the form, so it has
#: no ``source_record_id`` at all. Both are checked, and a row matching either is marked.
RUN_TOKEN_PREFIXES = ("E2E", "A11Y", "KB")

#: ``GLOB`` rather than ``LIKE``: it is case-sensitive in SQLite, and the token is upper
#: case by construction. A lower-case "kb" inside somebody's genuine note is not this.
#: ``[0-9A-Z]`` after the prefix, so the token shape has to follow, not just the letters.
CUSTOMER_MARKER = " OR ".join(
    [
        *(f"full_name GLOB '* {prefix}[0-9A-Z]*'" for prefix in RUN_TOKEN_PREFIXES),
        *(f"source_record_id GLOB '{prefix}[0-9A-Z]*'" for prefix in RUN_TOKEN_PREFIXES),
    ]
)

#: How a table's rows are recognised as the browser suite's work *on their own evidence*,
#: with no join and no inference. This is the strongest class the report has.
DIRECT_MARKERS = {
    "customers": CUSTOMER_MARKER,
    "import_batch_rows": " OR ".join(
        f"source_record_id GLOB '{prefix}[0-9A-Z]*'" for prefix in RUN_TOKEN_PREFIXES
    ),
}

#: Tables whose rows are attributed by following a foreign key *into* a marked customer.
#: ``table -> column``.
REACHABLE_FROM_CUSTOMER = {
    "import_batch_rows": "customer_id",
    "customer_tags": "customer_id",
    "customer_addresses": "customer_id",
    "consent_events": "customer_id",
    "customer_id_aliases": "customer_id",
    "follow_up_tasks": "customer_id",
    "interactions": "customer_id",
    "customer_route_interests": "customer_id",
    "shipments": "customer_id",
    "customer_identities": "customer_id",
    "customer_identity_links": "customer_id",
    "customer_data_proposals": "customer_id",
}

#: An import batch is attributed when it has rows and *every* row of it is attributed.
#: Deliberately "every" rather than "any": a batch holding one marked row and one genuine
#: one would be a batch a person and a test both wrote into, and that is a finding, not an
#: attribution.
BATCH_CLOSURE = {"import_batches": ("import_batch_rows", "batch_id")}

#: ``audit_events.entity_id`` holds a *public* identifier, so attribution there is a
#: membership test against the marked customers' and batches' public ids rather than a join.
PUBLIC_ID_REFERENCES = {"audit_events": "entity_id"}

#: Tables whose rows record an action rather than an entity, so nothing in the row points
#: at anything that can carry a marker. ``audit_events`` rows for a CSV *preview*, an
#: export, and a login are all of this kind: the preview is never persisted, an export
#: produces a file rather than a row, and a login names a user.
#:
#: These are attributed by *session*: same actor, and inside the wall-clock interval the
#: marked rows themselves define. That is weaker than a marker, and the report says so --
#: they are counted in their own column and never folded in with the marked ones.
SESSION_ATTRIBUTED = {
    "audit_events": ("occurred_at", "actor_user_id"),
    "user_sessions": ("created_at", "user_id"),
}

#: The order tables appear in the report. Everything not listed is appended alphabetically,
#: so a table added later still appears rather than being silently dropped.
REPORT_ORDER = [
    "users",
    "user_sessions",
    "customers",
    "customer_id_aliases",
    "customer_addresses",
    "customer_route_interests",
    "customer_tags",
    "tags",
    "referrals",
    "consent_events",
    "contact_suppressions",
    "shipments",
    "shipment_packages",
    "shipment_events",
    "shipment_legs",
    "shipment_leg_packages",
    "leg_tracking_references",
    "booking_confirmations",
    "label_print_jobs",
    "label_print_job_packages",
    "follow_up_tasks",
    "interactions",
    "saved_segments",
    "service_issues",
    "import_batches",
    "import_batch_rows",
    "audit_events",
    "customer_identities",
    "customer_identity_links",
    "customer_sessions",
    "customer_auth_tokens",
    "customer_data_proposals",
    "customer_data_proposal_fields",
    "customer_registration_attempts",
    "customer_terms_acknowledgements",
    "customer_notification_preferences",
    "customer_account_approval_attempts",
    "customer_account_disclosure_acknowledgements",
    "integration_connections",
    "integration_jobs",
    "integration_provider_events",
    "integration_webhook_inbox",
    "integration_worker_heartbeats",
    "role_merge_provenance",
    "organization_settings",
    "counters",
    "alembic_version",
]


@dataclass
class TableDiff:
    """One table's difference, in counts and classes. Never in values."""

    name: str
    before_count: int | None
    after_count: int | None
    inserted: int = 0
    deleted: int = 0
    updated: int = 0
    #: Rows carrying a per-run token of their own.
    marked: int = 0
    #: Rows reached by foreign key, or by public id, from a marked row.
    closure: int = 0
    #: Rows attributed by actor and time window because they reference no entity at all.
    session: int = 0
    #: Rows none of the above reached. The number that decides whether Option B is open.
    unattributed: int = 0
    earliest: str | None = None
    latest: str | None = None
    note: str = ""

    @property
    def changed(self) -> bool:
        return bool(self.inserted or self.deleted or self.updated or self.note)

    @property
    def classification(self) -> str:
        if self.before_count is None:
            return "added by a migration after the backup"
        if self.after_count is None:
            return "dropped by a migration after the backup"
        if not self.inserted and not self.deleted and not self.updated:
            return "unchanged"
        if self.deleted:
            return f"{self.deleted} row(s) DELETED"
        if self.unattributed:
            return f"{self.unattributed} row(s) NOT ATTRIBUTED"
        if self.inserted and not self.marked and not self.closure and self.session:
            return "attributed by session window only"
        if self.inserted:
            return "every inserted row attributed to the affected runs"
        return "updated in place"


def connect(path: Path) -> sqlite3.Connection:
    """Read-only, and it stays that way. A `?mode=ro` URI cannot be written through."""
    if not path.exists():
        raise SystemExit(f"No database at {path}")
    return sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)


def table_names(connection: sqlite3.Connection) -> set[str]:
    return {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
    }


def columns(connection: sqlite3.Connection, table: str) -> list[str]:
    return [row[1] for row in connection.execute(f'PRAGMA table_info("{table}")')]


def primary_key(connection: sqlite3.Connection, table: str) -> list[str]:
    return [row[1] for row in connection.execute(f'PRAGMA table_info("{table}")') if row[5]]


def row_digest(values: tuple) -> str:
    """A stable fingerprint of a row, used to tell "changed" from "same".

    The values go into a hash and never into the report. That is the point: an update has
    to be *counted* without being *shown*.
    """
    joined = "\x1f".join("\x00" if value is None else str(value) for value in values)
    return hashlib.sha256(joined.encode("utf-8", "replace")).hexdigest()


def keyed_digests(
    connection: sqlite3.Connection, table: str, key: list[str], shared: list[str]
) -> dict[tuple, str]:
    """``{primary key -> digest}`` over the columns both databases have.

    Only the shared columns, because a column added by a migration would otherwise make
    every row in the table look updated -- which is true of the schema and false of the
    data, and this report is about the data.
    """
    selected = ", ".join(f'"{name}"' for name in [*key, *shared])
    out: dict[tuple, str] = {}
    for row in connection.execute(f'SELECT {selected} FROM "{table}"'):  # noqa: S608
        out[tuple(row[: len(key)])] = row_digest(tuple(row[len(key) :]))
    return out


def marked_keys(connection: sqlite3.Connection, table: str) -> set[tuple]:
    """Primary keys in ``table`` whose row carries a per-run token of its own."""
    predicate = DIRECT_MARKERS.get(table)
    if predicate is None or table not in table_names(connection):
        return set()
    key = primary_key(connection, table)
    if not key:
        return set()
    selected = ", ".join(f'"{name}"' for name in key)
    try:
        rows = connection.execute(
            f'SELECT {selected} FROM "{table}" WHERE {predicate}'  # noqa: S608
        ).fetchall()
    except sqlite3.Error:
        return set()
    return {tuple(row) for row in rows}


def marked_public_ids(connection: sqlite3.Connection, marked: dict[str, set]) -> set[str]:
    """Public identifiers of marked customers, and of the batches wholly made of them."""
    out: set[str] = set()
    names = table_names(connection)

    if "customers" in names:
        out |= {
            row[0]
            for row in connection.execute(
                f"SELECT public_id FROM customers WHERE {CUSTOMER_MARKER}"  # noqa: S608
            )
            if row[0]
        }

    if {"import_batches", "import_batch_rows"} <= names:
        marked_customers = {value[0] for value in marked.get("customers", set())}
        if marked_customers:
            rows = connection.execute(
                "SELECT b.public_id, r.customer_id FROM import_batches b "
                "JOIN import_batch_rows r ON r.batch_id = b.id"
            ).fetchall()
            per_batch: dict[str, list] = {}
            for public_id, customer_id in rows:
                per_batch.setdefault(public_id, []).append(customer_id)
            out |= {
                public_id
                for public_id, customer_ids in per_batch.items()
                if public_id
                and customer_ids
                and all(value in marked_customers for value in customer_ids)
            }
    return out


def session_windows(
    connection: sqlite3.Connection, marked: dict[str, set], margin_minutes: int = 5
) -> list[tuple[str, str]]:
    """Wall-clock intervals the marked rows themselves define, widened by a small margin.

    A run's exports, previews and logins carry no marker, so the only honest way to reach
    them is "this happened while the marked rows were being written". The windows are
    derived from the data rather than typed in, and the margin covers the sign-in that
    precedes a run's first write and the export that follows its last.
    """
    keys = {value[0] for value in marked.get("customers", set())}
    if not keys or "customers" not in table_names(connection):
        return []

    placeholders = ", ".join("?" for _ in keys)
    stamps = sorted(
        row[0]
        for row in connection.execute(
            f"SELECT created_at FROM customers WHERE id IN ({placeholders})",  # noqa: S608
            list(keys),
        )
        if row[0]
    )
    if not stamps:
        return []

    # Group into runs: a gap of more than an hour between two marked writes is a different
    # sitting, and merging them would widen the window over hours nobody was testing in.
    windows: list[list[str]] = [[stamps[0], stamps[0]]]
    for stamp in stamps[1:]:
        if _minutes_between(windows[-1][1], stamp) > 60:
            windows.append([stamp, stamp])
        else:
            windows[-1][1] = stamp
    return [(_shift(low, -margin_minutes), _shift(high, margin_minutes)) for low, high in windows]


def _parse(stamp: str) -> datetime | None:
    try:
        return datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


def _minutes_between(first: str, second: str) -> float:
    left, right = _parse(first), _parse(second)
    if left is None or right is None:
        return 0.0
    return abs((right - left).total_seconds()) / 60


def _shift(stamp: str, minutes: int) -> str:
    moment = _parse(stamp)
    if moment is None:
        return stamp
    return (moment + timedelta(minutes=minutes)).isoformat(sep=" ")


def timestamp_range(
    connection: sqlite3.Connection, table: str, key: list[str], inserted: set
) -> tuple[str | None, str | None]:
    """Earliest and latest timestamp among the inserted rows, or ``(None, None)``.

    A timestamp says when something happened, not who it happened to, so it is the one
    row-level detail this report prints.
    """
    available = columns(connection, table)
    column = next((name for name in TIMESTAMP_COLUMNS if name in available), None)
    if column is None or not inserted or len(key) != 1:
        return (None, None)

    placeholders = ", ".join("?" for _ in inserted)
    row = connection.execute(
        f'SELECT MIN("{column}"), MAX("{column}") FROM "{table}" '  # noqa: S608
        f'WHERE "{key[0]}" IN ({placeholders})',
        [value[0] for value in inserted],
    ).fetchone()
    return (row[0], row[1]) if row else (None, None)


def _select_inserted(
    connection: sqlite3.Connection, table: str, key: str, inserted: set, *columns_wanted: str
) -> list[tuple]:
    selected = ", ".join(f'"{name}"' for name in columns_wanted)
    placeholders = ", ".join("?" for _ in inserted)
    return connection.execute(
        f'SELECT {selected} FROM "{table}" WHERE "{key}" IN ({placeholders})',  # noqa: S608
        [value[0] for value in inserted],
    ).fetchall()


def attribute(
    after: sqlite3.Connection,
    table: str,
    key: list[str],
    inserted: set,
    marked: dict[str, set],
    public_ids: set[str],
    windows: list[tuple[str, str]],
) -> tuple[int, int, int]:
    """``(marked, closure, session)`` counts for the inserted rows of one table.

    Each row is counted once, in the strongest class that reaches it. A row no class
    reaches is left out of all three, and the caller records it as unattributed.
    """
    if not inserted or len(key) != 1:
        return (0, 0, 0)

    key_name = key[0]
    remaining = set(inserted)

    direct = remaining & marked.get(table, set())
    remaining -= direct

    closure: set = set()

    if table in REACHABLE_FROM_CUSTOMER and remaining:
        column = REACHABLE_FROM_CUSTOMER[table]
        parents = {value[0] for value in marked.get("customers", set())}
        if parents and column in columns(after, table):
            rows = _select_inserted(after, table, key_name, remaining, key_name, column)
            closure |= {(identity,) for identity, parent in rows if parent in parents}

    if table in BATCH_CLOSURE and remaining:
        child_table, child_column = BATCH_CLOSURE[table]
        child_marked = marked.get(child_table, set())
        if child_marked and child_table in table_names(after):
            wanted = {value[0] for value in child_marked}
            rows = after.execute(
                f'SELECT "{child_column}", id FROM "{child_table}"'  # noqa: S608
            ).fetchall()
            per_parent: dict[object, list] = {}
            for parent, child_id in rows:
                per_parent.setdefault(parent, []).append(child_id)
            closure |= {
                (identity,)
                for (identity,) in remaining
                if per_parent.get(identity)
                and all(child in wanted for child in per_parent[identity])
            }

    if table in PUBLIC_ID_REFERENCES and public_ids and remaining:
        column = PUBLIC_ID_REFERENCES[table]
        if column in columns(after, table):
            rows = _select_inserted(after, table, key_name, remaining, key_name, column)
            closure |= {(identity,) for identity, value in rows if value in public_ids}

    remaining -= closure

    session: set = set()
    if table in SESSION_ATTRIBUTED and windows and remaining:
        time_column, actor_column = SESSION_ATTRIBUTED[table]
        available = columns(after, table)
        if time_column in available and actor_column in available:
            actors = _marked_actor_ids(after)
            rows = _select_inserted(
                after, table, key_name, remaining, key_name, time_column, actor_column
            )
            for identity, stamp, actor in rows:
                if actor in actors and any(low <= str(stamp) <= high for low, high in windows):
                    session.add((identity,))

    return (len(direct), len(closure), len(session))


def _marked_actor_ids(connection: sqlite3.Connection) -> set:
    """Users whose address is a reserved demo identity -- the only accounts a suite uses.

    ``app.core.demo_identity`` reserves these domains precisely so a seeded account cannot
    authenticate in production; here the same fact makes "acted as one of these" evidence
    rather than a guess.
    """
    if "users" not in table_names(connection):
        return set()
    return {
        row[0]
        for row in connection.execute(
            "SELECT id FROM users WHERE email LIKE '%@demo.example.com' "
            "OR email LIKE '%@example.com' OR email LIKE '%@example.net' "
            "OR email LIKE '%@example.org'"
        )
    }


def diff_table(
    before: sqlite3.Connection,
    after: sqlite3.Connection,
    table: str,
    marked: dict[str, set],
    public_ids: set[str],
    windows: list[tuple[str, str]],
) -> TableDiff:
    before_tables = table_names(before)
    after_tables = table_names(after)

    if table not in after_tables:
        count = before.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]  # noqa: S608
        return TableDiff(table, count, None, note="table absent from the current database")

    after_count = after.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]  # noqa: S608
    if table not in before_tables:
        return TableDiff(
            table, None, after_count, note="created by a migration after the backup was taken"
        )

    before_count = before.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]  # noqa: S608

    if table == "alembic_version":
        # Its single row *is* the schema version, so a changed revision reads as one
        # insert and one delete. Reported as what it is rather than as data loss.
        current = after.execute("SELECT version_num FROM alembic_version").fetchone()
        previous = before.execute("SELECT version_num FROM alembic_version").fetchone()
        moved = current != previous
        return TableDiff(
            table,
            before_count,
            after_count,
            note=(
                f"schema moved from {previous[0]} to {current[0]} by migration"
                if moved
                else "same revision"
            ),
        )

    key = primary_key(after, table)
    if not key or key != primary_key(before, table):
        result = TableDiff(table, before_count, after_count)
        result.note = "no comparable primary key; counts only"
        result.inserted = max(0, after_count - before_count)
        result.unattributed = result.inserted
        return result

    shared = [
        name for name in columns(after, table) if name in columns(before, table) and name not in key
    ]

    before_rows = keyed_digests(before, table, key, shared)
    after_rows = keyed_digests(after, table, key, shared)

    inserted = set(after_rows) - set(before_rows)
    deleted = set(before_rows) - set(after_rows)
    updated = {
        identity
        for identity in set(before_rows) & set(after_rows)
        if before_rows[identity] != after_rows[identity]
    }

    result = TableDiff(table, before_count, after_count)
    result.inserted = len(inserted)
    result.deleted = len(deleted)
    result.updated = len(updated)
    result.marked, result.closure, result.session = attribute(
        after, table, key, inserted, marked, public_ids, windows
    )
    result.unattributed = result.inserted - result.marked - result.closure - result.session
    result.earliest, result.latest = timestamp_range(after, table, key, inserted)

    added = len(columns(after, table)) - len(columns(before, table))
    if added:
        result.note = (
            f"{added} column(s) added by a migration; compared on the {len(shared)} shared"
        )
    return result


def render(diffs: list[TableDiff], windows: list[tuple[str, str]]) -> str:
    lines = [
        "| table | before | after | +ins | -del | ~upd | marker | closure | session | "
        "unattributed |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    blank = lambda value: str(value) if value else ""  # noqa: E731
    for diff in diffs:
        lines.append(
            f"| `{diff.name}` "
            f"| {diff.before_count if diff.before_count is not None else '--'} "
            f"| {diff.after_count if diff.after_count is not None else '--'} "
            f"| {blank(diff.inserted)} | {blank(diff.deleted)} | {blank(diff.updated)} "
            f"| {blank(diff.marked)} | {blank(diff.closure)} | {blank(diff.session)} "
            f"| {blank(diff.unattributed)} |"
        )

    totals = TableDiff("(total)", None, None)
    for diff in diffs:
        if diff.name == "alembic_version":
            continue
        totals.inserted += diff.inserted
        totals.deleted += diff.deleted
        totals.updated += diff.updated
        totals.marked += diff.marked
        totals.closure += diff.closure
        totals.session += diff.session
        totals.unattributed += diff.unattributed
    lines.append(
        f"| **total** |  |  | **{totals.inserted}** | **{totals.deleted}** "
        f"| **{totals.updated}** | **{totals.marked}** | **{totals.closure}** "
        f"| **{totals.session}** | **{totals.unattributed}** |"
    )

    lines.append("")
    if windows:
        lines.append("## Session windows")
        lines.append("")
        lines.extend(
            [
                "Derived from the marked rows themselves, not typed in: a gap of more than",
                "an hour between two marked writes starts a new window, and each is widened",
                "by five minutes so it covers the sign-in before a run's first write and the",
                "export after its last. **Windows earlier than the `before` database belong",
                "to runs that predate it** -- they are listed because the same marker found",
                "them, and they attribute nothing in the table above.",
            ]
        )
        lines.append("")
        for low, high in windows:
            lines.append(f"* `{low}` to `{high}`")
        lines.append("")

    lines.append("### Every table that changed")
    lines.append("")
    changed = [diff for diff in diffs if diff.changed]
    if not changed:
        lines.append("None.")
    for diff in changed:
        lines.append(f"**`{diff.name}`** -- {diff.classification}")
        if diff.earliest or diff.latest:
            lines.append(f"  * inserted rows span `{diff.earliest}` to `{diff.latest}`")
        if diff.note:
            lines.append(f"  * {diff.note}")
        lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only difference report.")
    parser.add_argument("--before", type=Path, required=True)
    parser.add_argument("--after", type=Path, required=True)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)

    before = connect(args.before)
    after = connect(args.after)
    try:
        marked = {table: marked_keys(after, table) for table in DIRECT_MARKERS}
        public_ids = marked_public_ids(after, marked)
        windows = session_windows(after, marked)

        tables = sorted(table_names(before) | table_names(after))
        ordered = [name for name in REPORT_ORDER if name in tables]
        ordered += [name for name in tables if name not in REPORT_ORDER]

        diffs = [diff_table(before, after, name, marked, public_ids, windows) for name in ordered]
        marked_before = {table: marked_keys(before, table) for table in DIRECT_MARKERS}
    finally:
        before.close()
        after.close()

    header = "\n".join(
        [
            "# Difference report",
            "",
            "Generated by `scripts/incident_db_diff.py`, which opens both databases",
            "read-only and writes nothing to either. Counts and classifications only: no",
            "name, address, email address, phone number, tracking reference, session",
            "token, IP address, CSV cell or audit summary appears anywhere below.",
            "",
            "The narrative, the recovery options and the recommendation are in",
            "[`2026-09-20-e2e-wrote-to-the-development-database.md`]"
            "(2026-09-20-e2e-wrote-to-the-development-database.md).",
            "",
            "Each inserted row is counted once, in the strongest class that reaches it:",
            "**marker** -- the row carries a per-run token of its own; **closure** -- a",
            "foreign key or a public identifier leads from it to one that does;",
            "**session** -- the row references no entity at all, so it is attributed by",
            "actor and by a time window the marked rows themselves define, which is",
            "inference rather than proof; **unattributed** -- nothing reached it.",
            "",
            "## Inputs",
            "",
            f"* before: `{args.before.name}`",
            f"* after: `{args.after.name}`",
            f"* marked customers in the before database: {len(marked_before.get('customers', ()))}",
            f"* marked customers in the after database: {len(marked.get('customers', ()))}",
            f"* marked public ids (customers, and batches wholly made of them): {len(public_ids)}",
            "",
            "## Every table, side by side",
            "",
            "",
        ]
    )
    output = header + render(diffs, windows)

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(output + "\n", encoding="utf-8")
        print(f"Wrote {args.out}")
    else:
        sys.stdout.write(output + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
