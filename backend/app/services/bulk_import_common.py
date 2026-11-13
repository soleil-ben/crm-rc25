"""What the shipment import and the legacy history baseline share (RC-UAT-21, DEC-0230).

Both follow the customer import's pattern (``customer_import_service``): the same
untrusted-file reader and limits (``csv_safety``: 2 MiB, 5,000 rows, OD-14), a dry run that
writes no business record, and a commit that re-parses and re-validates the exact bytes.

**Commit only from a matching dry run.** The customer import trusts the digest the browser
sends back. These two kinds go one step further: the commit is refused unless *the same
staff member* dry-ran *the same bytes with the same options* within the last
``DRY_RUN_VALID_HOURS``. The proof is the dry run's own audit entry -- the one row a dry run
writes, exactly as the customer preview records that a file was looked at -- so no staging
table and no copy of the file is needed.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.normalization import CSV_FORMULA_PREFIXES, collapse_whitespace
from app.core.time_utils import utcnow
from app.models import AuditEvent, Customer, User
from app.services import audit_service, customer_service
from app.services.errors import ConflictError, ValidationError
from app.services.identifier_service import _next_counter_value

#: How long a dry run stays good for a commit (stand-in A-3).
DRY_RUN_VALID_HOURS = 24

#: The import-batch identifier counter is shared with the customer import, so every batch of
#: every kind has one ``IMP-`` sequence.
IMPORT_BATCH_COUNTER = "import_batch_public_id"

CREATED = "created"
MATCHED = "matched"
SKIPPED = "skipped"
REJECTED = "rejected"

#: Dry-run classifications.
READY = "ready"
ALREADY_IMPORTED = "already_imported"


@dataclass
class RowIssue:
    field_name: str
    code: str
    message: str


@dataclass
class DryRunRow:
    row_number: int
    #: ``ready`` | ``already_imported`` | ``rejected``.
    classification: str
    reference: str | None
    customer_public_id: str | None = None
    summary: dict[str, Any] = field(default_factory=dict)
    issues: list[RowIssue] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class DryRun:
    kind: str
    content_sha256: str
    options: dict[str, Any]
    file_name: str | None
    row_count: int
    headers: list[str]
    unmapped_headers: list[str]
    rows: list[DryRunRow]
    counts: dict[str, int]
    notes: list[str]
    #: A stable code per note, same order, so the staff UI can show it in Vietnamese.
    note_codes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "kind": self.kind,
            "content_sha256": self.content_sha256,
            "options": self.options,
            "file_name": self.file_name,
            "row_count": self.row_count,
            "headers": self.headers,
            "unmapped_headers": self.unmapped_headers,
            "rows": [row.to_dict() for row in self.rows],
            "counts": self.counts,
            "notes": self.notes,
            "note_codes": self.note_codes,
        }


@dataclass
class CommitResult:
    kind: str
    batch_public_id: str
    created: int
    matched: int
    skipped: int
    rejected: int
    row_count: int
    rows: list[dict]

    def to_dict(self) -> dict:
        return asdict(self)


def content_digest(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def synonyms_to_known(synonyms: dict[str, tuple[str, ...]]) -> dict[str, str]:
    return {
        spelling: canonical for canonical, spellings in synonyms.items() for spelling in spellings
    }


def clean_file_name(file_name: str | None) -> str | None:
    text = collapse_whitespace(file_name)
    return text[:255] if text else None


def next_batch_public_id(db: Session) -> str:
    return f"IMP-{_next_counter_value(db, IMPORT_BATCH_COUNTER):06d}"


# --- Cell parsing ----------------------------------------------------------------


def reference_value(raw: str | None, field_name: str, issues: list[RowIssue]) -> str | None:
    """An identifier cell: required, at most 120 characters, and never formula-like.

    Free text is stored as text and escaped on every export (DEC-0081), as the customer
    import does. An *identifier* is stricter: it is matched, shown in lists and copied into
    other systems, so one that a spreadsheet would read as a formula is refused outright.
    """
    value = collapse_whitespace(raw or "")
    if not value:
        issues.append(RowIssue(field_name, "missing_value", f"{field_name} is required."))
        return None
    if value[:1] in CSV_FORMULA_PREFIXES:
        issues.append(
            RowIssue(
                field_name,
                "formula_like_value",
                f"{field_name} starts with a character a spreadsheet treats as a formula.",
            )
        )
        return None
    if len(value) > 120:
        issues.append(
            RowIssue(field_name, "too_long", f"{field_name} is longer than 120 characters.")
        )
        return None
    return value


#: ISO dates only. A slash date is ambiguous (01/02/2024 is 1 February in Vietnam and
#: 2 January in the United States), and a silent guess would misdate history.
DATE_PATTERN = "%Y-%m-%d"
_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def date_value(raw: str | None, field_name: str, issues: list[RowIssue]) -> date | None:
    value = collapse_whitespace(raw or "")
    if not value:
        return None
    if _ISO_DATE.match(value):
        try:
            return datetime.strptime(value, DATE_PATTERN).date()
        except ValueError:
            pass
    issues.append(
        RowIssue(
            field_name,
            "invalid_date",
            f"'{value}' is not a date this import recognizes. Use YYYY-MM-DD.",
        )
    )
    return None


#: Returned by ``resolve_customer`` when a source ID names more than one customer.
AMBIGUOUS = "ambiguous"


def resolve_customer(db: Session, reference: str) -> Customer | str | None:
    """Find an existing customer by Solaris customer ID (or a former ID), else by the
    ``source_record_id`` a customer import gave them. Never creates one.

    ``source_record_id`` is unique only together with ``source_system``, so two customers
    imported from two systems may share one. Then the row cannot say which customer it
    means, and ``AMBIGUOUS`` is returned rather than an arbitrary one of them.
    """
    customer = customer_service.get_customer_by_public_id(db, reference)
    if customer is None:
        matches = db.scalars(
            select(Customer)
            .where(
                Customer.source_record_id == reference,
                Customer.merged_into_customer_id.is_(None),
            )
            .limit(2)
        ).all()
        if len(matches) > 1:
            return AMBIGUOUS
        customer = matches[0] if matches else None
    if customer is None or customer.merged_into_customer_id is not None:
        return None
    return customer


def customer_for_row(db: Session, reference: str | None, issues: list[RowIssue]) -> Customer | None:
    """Resolve ``customer_ref`` for one row, adding the row issue when it cannot."""
    if not reference:
        return None
    found = resolve_customer(db, reference)
    if found == AMBIGUOUS:
        issues.append(
            RowIssue(
                "customer_ref",
                "ambiguous_customer",
                f"More than one customer has the source ID '{reference}'. Use the Solaris "
                "customer ID instead.",
            )
        )
        return None
    if found is None:
        issues.append(
            RowIssue(
                "customer_ref",
                "unknown_customer",
                f"No existing customer has the reference '{reference}'. An import never "
                "creates a customer: import or create the customer first.",
            )
        )
        return None
    if found.is_archived:
        issues.append(RowIssue("customer_ref", "archived_customer", "That customer is archived."))
        return None
    return found


# --- Dry-run proof ---------------------------------------------------------------


def _dry_run_action(kind: str) -> str:
    return f"{kind}.import_dry_run"


def _options_text(options: dict[str, Any]) -> str:
    return json.dumps(options, sort_keys=True, default=str)


def record_dry_run(
    db: Session, dry_run: DryRun, *, actor: User, ip_address: str | None
) -> AuditEvent:
    """The one row a dry run writes: who looked at which bytes, and the counts.

    Counts and the digest only -- never a value from the file (CRM.md section 11).
    """
    return audit_service.record_audit(
        db,
        action=_dry_run_action(dry_run.kind),
        entity_type="import_dry_run",
        entity_id=dry_run.content_sha256[:48],
        summary=(
            f"Dry run of a {dry_run.kind.replace('_', ' ')} import of {dry_run.row_count} row(s)"
        ),
        actor=actor,
        ip_address=ip_address,
        detail={
            "kind": dry_run.kind,
            "content_sha256": dry_run.content_sha256,
            "options": _options_text(dry_run.options),
            "row_count": dry_run.row_count,
            **{f"count_{key}": value for key, value in dry_run.counts.items()},
        },
    )


#: The audit action of a successful commit, per kind. A commit's audit entry names the dry
#: run it used (``dry_run_event_id``), which is how a dry run is consumed.
COMMIT_ACTIONS = {
    "shipments": "shipment.import_commit",
    "legacy_history": "legacy_history.import_commit",
}


def _consumed_dry_runs(db: Session, *, kind: str, content_sha256: str, since) -> set[int]:
    consumed: set[int] = set()
    for detail_json in db.scalars(
        select(AuditEvent.detail_json).where(
            AuditEvent.action == COMMIT_ACTIONS[kind], AuditEvent.occurred_at >= since
        )
    ).all():
        try:
            detail = json.loads(detail_json or "{}")
        except ValueError:
            continue
        if detail.get("content_sha256") == content_sha256 and detail.get("dry_run_event_id"):
            consumed.add(int(detail["dry_run_event_id"]))
    return consumed


def require_matching_dry_run(
    db: Session,
    *,
    kind: str,
    content_sha256: str,
    options: dict[str, Any],
    actor: User,
) -> int:
    """Refuse a commit that no unused dry run of these bytes, options and operator precedes.

    Returns the id of the dry run's audit entry. The caller writes it into the commit's
    audit entry, which consumes the dry run: a second commit needs a new dry run.
    """
    since = utcnow() - timedelta(hours=DRY_RUN_VALID_HOURS)
    consumed = _consumed_dry_runs(db, kind=kind, content_sha256=content_sha256, since=since)
    candidates = db.scalars(
        select(AuditEvent)
        .where(
            AuditEvent.action == _dry_run_action(kind),
            AuditEvent.entity_id == content_sha256[:48],
            AuditEvent.actor_user_id == actor.id,
            AuditEvent.occurred_at >= since,
        )
        .order_by(AuditEvent.id.desc())
        .limit(20)
    ).all()
    wanted = _options_text(options)
    for event in candidates:
        if event.id in consumed:
            continue
        try:
            detail = json.loads(event.detail_json or "{}")
        except ValueError:
            continue
        if detail.get("content_sha256") == content_sha256 and detail.get("options") == wanted:
            return event.id
    raise ConflictError(
        "There is no unused matching dry run for this file (each dry run allows one "
        "import). Run the dry run again, review the "
        "report, and then import. Nothing has been imported."
    )


def check_digest(content: bytes, expected_sha256: str) -> str:
    actual = content_digest(content)
    if actual != (expected_sha256 or "").strip().lower():
        raise ConflictError(
            "This file is not the one that was dry-run. Run the dry run again and review "
            "the result before importing. Nothing has been imported."
        )
    return actual


def require_confirm(confirm: bool) -> None:
    if not confirm:
        raise ValidationError(
            "Confirm the import before it can be committed. Nothing has been imported.",
            field="confirm",
        )
