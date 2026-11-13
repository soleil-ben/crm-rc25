"""Legacy history baseline: past shipments as read-only records (RC-UAT-21, DEC-0230).

OD-15/OD-16 stand-in. A baseline imports **historical** shipments, with their dated
milestone history, from a CSV -- one row per past shipment -- through the same dry-run-first
pattern as every other import (``bulk_import_common``).

What makes a legacy record safe is where it lives. It is written to ``legacy_shipments`` and
``legacy_shipment_events``, never to ``shipments`` or ``shipment_events``, so by
construction it:

* never notifies anyone -- the notification outbox reads ``shipment_events`` only;
* is never quoted, invoiced, locked on a master or expired -- every one of those works on a
  ``shipments`` row;
* is absent from every operational queue, dashboard, shipment list, finance report and
  export, none of which read these tables;
* is visible to staff only (``shipment:read``), through its own read-only endpoints. The
  Customer Account timeline does not read it (stand-in A-7).

A baseline can be **re-run idempotently**: a row whose ``(source_system, legacy_reference)``
is already live in an active baseline is matched, never duplicated or overwritten. A baseline
can be **voided as a whole** (soft, audited, with a reason): its rows stay in the table,
flagged voided, and drop out of every list; the same history can then be imported again.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.countries import normalize_country_code
from app.core.enums import RouteGroup, ShipmentEventType, TransportMode
from app.core.normalization import collapse_whitespace
from app.core.time_utils import utcnow
from app.models import (
    LEGACY_IMPORT_SOURCE,
    Customer,
    ImportBatch,
    ImportBatchRow,
    LegacyBaseline,
    LegacyShipment,
    LegacyShipmentEvent,
    User,
)
from app.services import audit_service, booking_service, csv_safety
from app.services import bulk_import_common as common
from app.services.bulk_import_common import RowIssue
from app.services.errors import ConflictError, NotFoundError, ValidationError
from app.services.shipment_import_service import ROUTE_ALIASES

KIND = "legacy_history"

FINAL_STATUSES = ("delivered", "returned", "cancelled", "lost")

#: Milestone date columns, in journey order, and the event type each records.
MILESTONE_COLUMNS: tuple[tuple[str, str], ...] = (
    ("received_on", ShipmentEventType.RECEIVED_AT_SOLARIS),
    ("departed_on", ShipmentEventType.DEPARTED_ORIGIN),
    ("customs_on", ShipmentEventType.CUSTOMS_PROCESSING),
    ("arrived_on", ShipmentEventType.ARRIVED_DESTINATION),
    ("out_for_delivery_on", ShipmentEventType.OUT_FOR_DELIVERY),
    ("delivered_on", ShipmentEventType.DELIVERED_TO_RECIPIENT),
    ("returned_on", ShipmentEventType.RETURNED),
    ("cancelled_on", "cancelled"),
)
#: The closing milestone each final status requires.
CLOSING_COLUMN = {
    "delivered": "delivered_on",
    "returned": "returned_on",
    "cancelled": "cancelled_on",
}

FIELD_SYNONYMS: dict[str, tuple[str, ...]] = {
    "legacy_reference": ("legacy_reference", "legacy_ref", "old_reference", "reference"),
    "customer_ref": ("customer_ref", "customer_id", "customer", "ma_khach_hang"),
    "booked_on": ("booked_on", "booking_date"),
    "final_status": ("final_status", "status"),
    "route_group": ("route_group", "route"),
    "direction": ("direction",),
    "transport_mode": ("transport_mode", "mode"),
    "recipient_name": ("recipient_name",),
    "recipient_city": ("recipient_city",),
    "recipient_province_state": ("recipient_province_state", "recipient_province"),
    "recipient_country_code": ("recipient_country_code", "recipient_country"),
    "package_count": ("package_count", "packages"),
    "total_weight_kg": ("total_weight_kg", "weight_kg"),
    "contents_description": ("contents_description", "contents"),
    "notes": ("notes", "internal_notes"),
    **{column: (column,) for column, _event in MILESTONE_COLUMNS},
}
KNOWN_HEADERS = common.synonyms_to_known(FIELD_SYNONYMS)
REQUIRED_FIELDS: tuple[str, ...] = ("legacy_reference", "customer_ref", "booked_on", "final_status")

TEMPLATE_HEADERS: tuple[str, ...] = (
    "legacy_reference",
    "customer_ref",
    "booked_on",
    "final_status",
    "route_group",
    "recipient_name",
    "recipient_city",
    "recipient_province_state",
    "recipient_country_code",
    "package_count",
    "total_weight_kg",
    "contents_description",
    *(column for column, _event in MILESTONE_COLUMNS),
    "notes",
)

TEXT_LIMITS = {
    "recipient_name": 200,
    "recipient_city": 120,
    "recipient_province_state": 120,
    "contents_description": 400,
    "notes": 1000,
}

ALREADY_IMPORTED = common.ALREADY_IMPORTED
DUPLICATE = "duplicate"


@dataclass
class LegacyPlan:
    row_number: int
    reference: str | None
    customer_id: int | None = None
    customer_public_id: str | None = None
    record: dict[str, Any] = field(default_factory=dict)
    events: list[tuple[str, date]] = field(default_factory=list)
    issues: list[RowIssue] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        return not self.issues


def template_csv() -> str:
    import csv
    import io

    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\r\n")
    writer.writerow(TEMPLATE_HEADERS)
    milestones_delivered = ["2024-03-04", "2024-03-06", "2024-03-09", "2024-03-10", "2024-03-11"]
    writer.writerow(
        [
            "SAMPLE-OLD-0001",
            "STCA-000001",
            "2024-03-01",
            "delivered",
            "VCA",
            "Trần Thị Mẫu",
            "Toronto",
            "ON",
            "CA",
            "2",
            "18.5",
            "Quà Tết (sample)",
            *milestones_delivered,
            "2024-03-12",
            "",
            "",
            "Sample row - safe to delete",
        ]
    )
    writer.writerow(
        [
            "SAMPLE-OLD-0002",
            "STCA-000002",
            "2024-05-02",
            "cancelled",
            "VCA",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "2024-05-03",
            "",
        ]
    )
    return "﻿" + buffer.getvalue()


def _text(values: dict[str, str], name: str, issues: list[RowIssue]) -> str | None:
    value = collapse_whitespace(values.get(name, ""))
    if not value:
        return None
    if len(value) > TEXT_LIMITS[name]:
        issues.append(
            RowIssue(name, "too_long", f"{name} is longer than {TEXT_LIMITS[name]} characters.")
        )
        return None
    return value


def build_plan(
    db: Session, row: csv_safety.ParsedRow, *, cutoff: date | None, today: date
) -> LegacyPlan:
    """Validate one row into a legacy record. **Writes nothing.**"""
    values = row.values
    issues: list[RowIssue] = []
    reference = common.reference_value(values.get("legacy_reference"), "legacy_reference", issues)
    plan = LegacyPlan(row_number=row.row_number, reference=reference, issues=issues)

    customer_ref = common.reference_value(values.get("customer_ref"), "customer_ref", issues)
    customer = common.customer_for_row(db, customer_ref, issues)
    if customer is not None:
        plan.customer_id = customer.id
        plan.customer_public_id = customer.public_id

    mode = collapse_whitespace(values.get("transport_mode", "")) or TransportMode.AIR
    if mode.casefold() != TransportMode.AIR:
        issues.append(
            RowIssue(
                "transport_mode",
                "air_only",
                f"'{mode}' cannot be imported. Only air shipments are imported in this release.",
            )
        )

    status = (collapse_whitespace(values.get("final_status", "")) or "").lower()
    if status not in FINAL_STATUSES:
        issues.append(
            RowIssue(
                "final_status",
                "unknown_value",
                f"'{status}' is not a final status. Use one of: {', '.join(FINAL_STATUSES)}.",
            )
        )

    booked_on = common.date_value(values.get("booked_on"), "booked_on", issues)
    if booked_on is None and not any(issue.field_name == "booked_on" for issue in issues):
        issues.append(RowIssue("booked_on", "missing_value", "booked_on is required."))

    route_raw = collapse_whitespace(values.get("route_group", "")) or RouteGroup.VCA
    route_group = (
        route_raw.upper()
        if route_raw.upper() in set(RouteGroup)
        else ROUTE_ALIASES.get(route_raw.casefold())
    )
    if route_group is None:
        issues.append(
            RowIssue("route_group", "unknown_value", f"'{route_raw}' is not a route group.")
        )

    destination = None
    try:
        destination = normalize_country_code(values.get("recipient_country_code"))
    except ValueError as exc:
        issues.append(RowIssue("recipient_country_code", "unknown_country", str(exc)))

    direction = collapse_whitespace(values.get("direction", "")) or None
    if route_group:
        try:
            direction = booking_service.validate_route(
                route_group, direction, destination_country=destination
            )
        except ValidationError as exc:
            issues.append(RowIssue(exc.field or "route_group", "invalid_route", exc.message))

    package_count = None
    count_raw = (values.get("package_count") or "").strip()
    if count_raw:
        if count_raw.isdigit() and 0 < int(count_raw) <= 99:
            package_count = int(count_raw)
        else:
            issues.append(
                RowIssue("package_count", "invalid_number", "package_count must be 1 to 99.")
            )
    weight = None
    weight_raw = (values.get("total_weight_kg") or "").strip().replace(",", "")
    if weight_raw:
        try:
            weight = Decimal(weight_raw)
            if not weight.is_finite() or weight <= 0:
                raise InvalidOperation
        except InvalidOperation:
            issues.append(
                RowIssue("total_weight_kg", "invalid_number", "total_weight_kg must be above 0.")
            )
            weight = None

    # --- The dated milestone history -----------------------------------------------
    events: list[tuple[str, date]] = []
    if booked_on is not None:
        events.append((ShipmentEventType.BOOKED, booked_on))
        if booked_on > today:
            issues.append(
                RowIssue(
                    "booked_on",
                    "future_date",
                    "A legacy shipment cannot be booked later than today.",
                )
            )
        if cutoff is not None and booked_on > cutoff:
            issues.append(
                RowIssue(
                    "booked_on",
                    "after_cutoff",
                    f"Booked after the baseline cutoff date {cutoff.isoformat()}.",
                )
            )
    previous: tuple[str, date] | None = ("booked_on", booked_on) if booked_on else None
    for column, event_type in MILESTONE_COLUMNS:
        day = common.date_value(values.get(column), column, issues)
        if day is None:
            continue
        if day > today:
            issues.append(RowIssue(column, "future_date", f"{column} is in the future."))
        if previous is not None and day < previous[1]:
            issues.append(
                RowIssue(
                    column,
                    "out_of_order",
                    f"{column} ({day.isoformat()}) is earlier than {previous[0]} "
                    f"({previous[1].isoformat()}). Milestones must follow the journey order.",
                )
            )
        previous = (column, day)
        events.append((event_type, day))

    completed_on = None
    if status in FINAL_STATUSES:
        closing = CLOSING_COLUMN.get(status)
        for column, _event in MILESTONE_COLUMNS:
            if (
                column in CLOSING_COLUMN.values()
                and column != closing
                and values.get(column, "").strip()
            ):
                issues.append(
                    RowIssue(
                        column,
                        "conflicting_status",
                        f"{column} is filled in but the final status is '{status}'.",
                    )
                )
        if closing:
            completed_on = common.date_value(values.get(closing), closing, [])
            if completed_on is None:
                issues.append(
                    RowIssue(
                        closing,
                        "missing_value",
                        f"A '{status}' shipment needs its {closing} date.",
                    )
                )
    if status == "lost":
        events.append(("lost", previous[1] if previous else booked_on or today))

    texts = {name: _text(values, name, issues) for name in TEXT_LIMITS}
    plan.events = events
    if plan.is_valid and customer is not None:
        plan.record = {
            "customer_id": customer.id,
            "legacy_reference": reference,
            "route_group": route_group,
            "direction": direction,
            "transport_mode": TransportMode.AIR,
            "booked_on": booked_on,
            "final_status": status,
            "completed_on": completed_on,
            "recipient_name": texts["recipient_name"],
            "recipient_city": texts["recipient_city"],
            "recipient_province_state": texts["recipient_province_state"],
            "recipient_country_code": destination,
            "package_count": package_count,
            "total_weight_kg": weight,
            "contents_description": texts["contents_description"],
            "notes": texts["notes"],
        }
    return plan


def _active_key(reference: str) -> str:
    return f"{LEGACY_IMPORT_SOURCE}|{reference}"


def _live_record(db: Session, reference: str) -> LegacyShipment | None:
    return db.scalar(
        select(LegacyShipment).where(LegacyShipment.active_key == _active_key(reference))
    )


def _parse(content: bytes) -> csv_safety.ParsedFile:
    return csv_safety.parse(content, known_fields=KNOWN_HEADERS, required_headers=REQUIRED_FIELDS)


def parse_cutoff(raw: str | None) -> date | None:
    issues: list[RowIssue] = []
    cutoff = common.date_value(raw, "cutoff_date", issues)
    if issues:
        raise ValidationError(issues[0].message, field="cutoff_date")
    if cutoff is not None and cutoff > utcnow().date():
        raise ValidationError("The cutoff date cannot be in the future.", field="cutoff_date")
    return cutoff


def _options(cutoff: date | None) -> dict[str, Any]:
    return {"cutoff_date": cutoff.isoformat() if cutoff else None}


def _summary(plan: LegacyPlan) -> dict[str, Any]:
    record = plan.record
    if not record:
        return {}
    return {
        "route_group": record["route_group"],
        "booked_on": record["booked_on"].isoformat(),
        "final_status": record["final_status"],
        "recipient_name": record["recipient_name"],
        "milestone_count": len(plan.events),
    }


# --- Dry run --------------------------------------------------------------------------


def dry_run(
    db: Session, content: bytes, *, cutoff: date | None = None, file_name: str | None = None
) -> common.DryRun:
    """Validate every row and report what a commit would do. **Writes nothing.**"""
    parsed = _parse(content)
    today = utcnow().date()
    counts = {common.READY: 0, ALREADY_IMPORTED: 0, DUPLICATE: 0, common.REJECTED: 0}
    rows: list[common.DryRunRow] = []
    seen: dict[str, int] = {}
    for parsed_row in parsed.rows:
        plan = build_plan(db, parsed_row, cutoff=cutoff, today=today)
        out = common.DryRunRow(
            row_number=plan.row_number,
            classification=common.REJECTED,
            reference=plan.reference,
            customer_public_id=plan.customer_public_id,
            summary=_summary(plan),
            issues=list(plan.issues),
        )
        if plan.reference and plan.reference in seen:
            out.classification = DUPLICATE
            out.issues.append(
                RowIssue(
                    "legacy_reference",
                    "duplicate_within_file",
                    f"This reference repeats row {seen[plan.reference]}.",
                )
            )
        elif plan.is_valid and _live_record(db, plan.reference) is not None:
            out.classification = ALREADY_IMPORTED
        elif plan.is_valid:
            out.classification = common.READY
        if plan.reference and plan.reference not in seen:
            seen[plan.reference] = plan.row_number
        counts[out.classification] += 1
        rows.append(out)

    notes = [
        ("dry_run_only_legacy", "Dry run only: no legacy record and no baseline has been created."),
        (
            "legacy_read_only",
            "Legacy shipments are read-only history. They never notify a customer, are never "
            "quoted, invoiced, locked or expired, and stay out of every operational queue and "
            "finance report.",
        ),
        (
            "rerun_is_safe",
            "Re-running a baseline is safe: a shipment already in an active baseline is "
            "matched, never duplicated or overwritten.",
        ),
    ]
    if parsed.unmapped_headers:
        notes.append(
            (
                "unmapped_columns",
                "These columns were not recognized and are ignored: "
                + ", ".join(parsed.unmapped_headers)
                + ".",
            )
        )
    return common.DryRun(
        kind=KIND,
        content_sha256=common.content_digest(content),
        options=_options(cutoff),
        file_name=common.clean_file_name(file_name),
        row_count=len(parsed.rows),
        headers=parsed.headers,
        unmapped_headers=parsed.unmapped_headers,
        rows=rows,
        counts=counts,
        notes=[text for _code, text in notes],
        note_codes=[code for code, _text in notes],
    )


# --- Commit -----------------------------------------------------------------------------


def commit(
    db: Session,
    content: bytes,
    *,
    expected_sha256: str,
    actor: User,
    cutoff: date | None = None,
    file_name: str | None = None,
    ip_address: str | None = None,
) -> common.CommitResult:
    digest = common.check_digest(content, expected_sha256)
    dry_run_event_id = common.require_matching_dry_run(
        db, kind=KIND, content_sha256=digest, options=_options(cutoff), actor=actor
    )
    parsed = _parse(content)
    now = utcnow()
    today = now.date()

    batch = ImportBatch(
        public_id=common.next_batch_public_id(db),
        kind=KIND,
        file_name=common.clean_file_name(file_name),
        content_sha256=digest,
        source_system=LEGACY_IMPORT_SOURCE,
        conflict_policy="match_existing",
        row_count=len(parsed.rows),
        committed_at=now,
        committed_by_user_id=actor.id,
    )
    db.add(batch)
    db.flush()
    baseline = LegacyBaseline(
        batch_id=batch.id,
        source_system=LEGACY_IMPORT_SOURCE,
        cutoff_date=cutoff,
        status="active",
        created_at=now,
    )
    db.add(baseline)
    db.flush()

    counts = {common.CREATED: 0, common.MATCHED: 0, common.SKIPPED: 0, common.REJECTED: 0}
    result_rows: list[dict] = []
    seen: set[str] = set()
    for parsed_row in parsed.rows:
        plan = build_plan(db, parsed_row, cutoff=cutoff, today=today)
        record: LegacyShipment | None = None
        if not plan.is_valid:
            outcome = common.REJECTED
            reason = ",".join(sorted({issue.code for issue in plan.issues}))[:60]
        elif plan.reference in seen:
            outcome, reason = common.SKIPPED, "duplicate_within_file"
        else:
            seen.add(plan.reference)
            record = _live_record(db, plan.reference)
            if record is not None:
                outcome, reason = common.MATCHED, "already_in_baseline"
            else:
                record = LegacyShipment(
                    baseline_id=baseline.id,
                    row_number=plan.row_number,
                    source_system=LEGACY_IMPORT_SOURCE,
                    active_key=_active_key(plan.reference),
                    is_voided=False,
                    created_at=now,
                    **plan.record,
                )
                record.events = [
                    LegacyShipmentEvent(sequence=index, event_type=event_type, occurred_on=day)
                    for index, (event_type, day) in enumerate(plan.events, start=1)
                ]
                db.add(record)
                db.flush()
                outcome, reason = common.CREATED, "created_from_import"
        counts[outcome] += 1
        db.add(
            ImportBatchRow(
                batch_id=batch.id,
                row_number=plan.row_number,
                outcome=outcome,
                reason_code=reason,
                customer_id=plan.customer_id,
                source_record_id=plan.reference,
            )
        )
        result_rows.append(
            {
                "row_number": plan.row_number,
                "outcome": outcome,
                "reason_code": reason,
                "reference": plan.reference,
                "record_id": record.id if record is not None else None,
                "record_label": plan.reference if record is not None else None,
            }
        )

    batch.created_count = counts[common.CREATED]
    batch.matched_count = counts[common.MATCHED]
    batch.skipped_count = counts[common.SKIPPED]
    batch.rejected_count = counts[common.REJECTED]
    baseline.created_count = counts[common.CREATED]
    db.flush()

    audit_service.record_audit(
        db,
        action="legacy_history.import_commit",
        entity_type="import_batch",
        entity_id=batch.public_id,
        summary=(
            f"Legacy history baseline: {counts[common.CREATED]} historical shipment(s) added; "
            f"{counts[common.MATCHED]} already present, {counts[common.REJECTED]} rejected"
        ),
        actor=actor,
        ip_address=ip_address,
        detail={
            "batch_public_id": batch.public_id,
            "row_count": batch.row_count,
            "created": counts[common.CREATED],
            "matched": counts[common.MATCHED],
            "skipped": counts[common.SKIPPED],
            "rejected": counts[common.REJECTED],
            "cutoff_date": cutoff.isoformat() if cutoff else None,
            "content_sha256": digest,
            # Consumes the dry run: a second commit needs a new one (bulk_import_common).
            "dry_run_event_id": dry_run_event_id,
        },
    )
    return common.CommitResult(
        kind=KIND,
        batch_public_id=batch.public_id,
        created=counts[common.CREATED],
        matched=counts[common.MATCHED],
        skipped=counts[common.SKIPPED],
        rejected=counts[common.REJECTED],
        row_count=batch.row_count,
        rows=result_rows,
    )


# --- Void ------------------------------------------------------------------------------


def _baseline_for(db: Session, batch_public_id: str) -> tuple[LegacyBaseline, ImportBatch]:
    row = db.execute(
        select(LegacyBaseline, ImportBatch)
        .join(ImportBatch, ImportBatch.id == LegacyBaseline.batch_id)
        .where(ImportBatch.public_id == batch_public_id.strip().upper())
    ).first()
    if row is None:
        raise NotFoundError("Legacy baseline not found.")
    return row[0], row[1]


def void_baseline(
    db: Session,
    batch_public_id: str,
    *,
    reason: str,
    actor: User,
    ip_address: str | None = None,
) -> LegacyBaseline:
    """Soft-void a whole baseline: every record it created is flagged voided, nothing is
    deleted, and the history it carried can be imported again."""
    cleaned = collapse_whitespace(reason)
    if not cleaned or len(cleaned) < 5:
        raise ValidationError("Give a reason of at least 5 characters.", field="reason")
    baseline, batch = _baseline_for(db, batch_public_id)
    if baseline.status == "voided":
        raise ConflictError(f"Baseline {batch.public_id} is already voided.")
    now = utcnow()
    records = db.scalars(
        select(LegacyShipment).where(
            LegacyShipment.baseline_id == baseline.id, LegacyShipment.is_voided.is_(False)
        )
    ).all()
    for record in records:
        record.is_voided = True
        record.voided_at = now
        record.active_key = None
    baseline.status = "voided"
    baseline.voided_at = now
    baseline.voided_by_user_id = actor.id
    baseline.void_reason = cleaned[:400]
    db.flush()
    audit_service.record_audit(
        db,
        action="legacy_history.baseline_void",
        entity_type="import_batch",
        entity_id=batch.public_id,
        summary=f"Voided legacy baseline {batch.public_id} ({len(records)} record(s))",
        actor=actor,
        ip_address=ip_address,
        detail={
            "batch_public_id": batch.public_id,
            "voided_records": len(records),
            "reason": cleaned[:400],
        },
    )
    return baseline


# --- Reads (staff only) -----------------------------------------------------------------


def list_baselines(db: Session) -> list[tuple[LegacyBaseline, ImportBatch]]:
    return [
        (row[0], row[1])
        for row in db.execute(
            select(LegacyBaseline, ImportBatch)
            .join(ImportBatch, ImportBatch.id == LegacyBaseline.batch_id)
            .order_by(LegacyBaseline.id.desc())
            .limit(100)
        ).all()
    ]


def list_records(
    db: Session,
    *,
    customer_id: int | None = None,
    search: str | None = None,
    include_voided: bool = False,
    limit: int = 25,
    offset: int = 0,
) -> tuple[list[tuple[LegacyShipment, Customer]], int]:
    conditions = []
    if not include_voided:
        conditions.append(LegacyShipment.is_voided.is_(False))
    if customer_id is not None:
        conditions.append(LegacyShipment.customer_id == customer_id)
    term = collapse_whitespace(search)
    if term:
        # The term is literal text: ``%`` and ``_`` are escaped so they match themselves
        # rather than acting as LIKE wildcards.
        escaped = term.lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        like = f"%{escaped}%"
        conditions.append(
            or_(
                func.lower(LegacyShipment.legacy_reference).like(like, escape="\\"),
                func.lower(LegacyShipment.recipient_name).like(like, escape="\\"),
                func.lower(Customer.full_name).like(like, escape="\\"),
                func.lower(Customer.public_id).like(like, escape="\\"),
            )
        )
    base = select(LegacyShipment, Customer).join(
        Customer, Customer.id == LegacyShipment.customer_id
    )
    total = int(
        db.scalar(
            select(func.count(LegacyShipment.id))
            .join(Customer, Customer.id == LegacyShipment.customer_id)
            .where(*conditions)
        )
        or 0
    )
    rows = db.execute(
        base.where(*conditions)
        .order_by(LegacyShipment.booked_on.desc(), LegacyShipment.id.desc())
        .limit(limit)
        .offset(offset)
    ).all()
    return [(row[0], row[1]) for row in rows], total


def get_record(db: Session, record_id: int) -> tuple[LegacyShipment, Customer]:
    record = db.get(LegacyShipment, record_id)
    if record is None:
        raise NotFoundError("Legacy shipment not found.")
    return record, db.get(Customer, record.customer_id)
