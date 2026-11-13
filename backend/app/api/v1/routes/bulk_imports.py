"""Shipment import and legacy history baseline routes (RC-UAT-21 Phase A, DEC-0230).

Same permission model as the customer import (DEC-0082: the ``import:*`` permissions are
Admin's alone today), plus the shipment permission each step exercises:

| Endpoint | Permission | Writes |
|---|---|---|
| `GET /imports/shipments/template.csv` | `import:template` | no |
| `GET /imports/shipments/fields` | `import:preview` | no |
| `POST /imports/shipments/dry-run` | `import:preview` + `shipment:read` | audit only |
| `POST /imports/shipments/commit` | `import:commit` + `shipment:write` | yes |
| `GET /imports/legacy-history/template.csv` | `import:template` | no |
| `GET /imports/legacy-history/fields` | `import:preview` | no |
| `POST /imports/legacy-history/dry-run` | `import:preview` + `shipment:read` | audit only |
| `POST /imports/legacy-history/commit` | `import:commit` + `shipment:write` | yes |
| `GET /imports/legacy-history/baselines` | `import:preview` | no |
| `POST /imports/legacy-history/baselines/{id}/void` | `import:commit` + `shipment:write` | yes |
| `GET /legacy-shipments`, `GET /legacy-shipments/{id}` | `shipment:read` | no |

A dry run writes only its own audit entry, which is what a commit later checks for.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Query, Request, Response, UploadFile

from app.api.deps import DbSession, client_ip, require
from app.api.v1.routes.imports import _read_upload
from app.core.db import commit_with_retry
from app.core.permissions import Permission
from app.models import ImportBatch, LegacyBaseline, LegacyShipment, User
from app.schemas.bulk_imports import (
    BaselineOut,
    BulkCommitOut,
    BulkFieldsOut,
    DryRunOut,
    LegacyEventOut,
    LegacyShipmentOut,
    VoidBaselineIn,
)
from app.schemas.common import Page
from app.services import bulk_import_common, legacy_history_service, shipment_import_service
from app.services.csv_safety import MAX_CELL_CHARS, MAX_COLUMNS, MAX_FILE_BYTES, MAX_ROWS

router = APIRouter(tags=["imports"])

TemplateReader = Annotated[User, Depends(require(Permission.IMPORT_TEMPLATE))]
FieldsReader = Annotated[User, Depends(require(Permission.IMPORT_PREVIEW))]
DryRunner = Annotated[User, Depends(require(Permission.IMPORT_PREVIEW, Permission.SHIPMENT_READ))]
Committer = Annotated[User, Depends(require(Permission.IMPORT_COMMIT, Permission.SHIPMENT_WRITE))]
LegacyReader = Annotated[User, Depends(require(Permission.SHIPMENT_READ))]

LIMITS = {
    "max_file_bytes": MAX_FILE_BYTES,
    "max_rows": MAX_ROWS,
    "max_columns": MAX_COLUMNS,
    "max_cell_characters": MAX_CELL_CHARS,
}


def _csv_response(content: str, filename: str) -> Response:
    return Response(
        content=content,
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
        },
    )


def _fields(kind: str, synonyms, required, template, notes) -> BulkFieldsOut:
    return BulkFieldsOut(
        kind=kind,
        fields=[
            {"field": name, "headers": list(spellings), "required": name in required}
            for name, spellings in synonyms.items()
        ],
        template_headers=list(template),
        limits=LIMITS,
        notes=notes,
    )


# --- Shipment import -------------------------------------------------------------------


@router.get("/imports/shipments/template.csv")
def shipment_template(_user: TemplateReader) -> Response:
    return _csv_response(
        shipment_import_service.template_csv(), "solaris-shipment-import-template.csv"
    )


@router.get("/imports/shipments/fields", response_model=BulkFieldsOut)
def shipment_fields(_user: FieldsReader) -> BulkFieldsOut:
    return _fields(
        shipment_import_service.KIND,
        shipment_import_service.FIELD_SYNONYMS,
        shipment_import_service.REQUIRED_FIELDS,
        shipment_import_service.TEMPLATE_HEADERS,
        [
            "One row per shipment, for an existing customer (customer_ref: the Solaris "
            "customer ID, or the source ID a customer import gave them).",
            "Air only. route_group defaults to VCA (Vietnam to Canada).",
            "Packages: weights in kg separated by ';'. Items: 'description|quantity|unit|"
            "value' separated by ';'.",
            "No quote, invoice, email or milestone notification is created by an import.",
            "An external_reference already imported is refused as a duplicate.",
        ],
    )


@router.post("/imports/shipments/dry-run", response_model=DryRunOut)
async def shipment_dry_run(
    request: Request,
    db: DbSession,
    user: DryRunner,
    file: Annotated[UploadFile, File()],
) -> DryRunOut:
    content = await _read_upload(file)
    result = shipment_import_service.dry_run(db, content, file_name=file.filename)
    bulk_import_common.record_dry_run(db, result, actor=user, ip_address=client_ip(request))
    commit_with_retry(db)
    return DryRunOut(**result.to_dict())


@router.post("/imports/shipments/commit", response_model=BulkCommitOut)
async def shipment_commit(
    request: Request,
    db: DbSession,
    user: Committer,
    file: Annotated[UploadFile, File()],
    content_sha256: Annotated[str, Form()],
    confirm: Annotated[bool, Form()] = False,
) -> BulkCommitOut:
    bulk_import_common.require_confirm(confirm)
    content = await _read_upload(file)
    result = shipment_import_service.commit(
        db,
        content,
        expected_sha256=content_sha256,
        actor=user,
        file_name=file.filename,
        ip_address=client_ip(request),
    )
    commit_with_retry(db)
    return BulkCommitOut(**result.to_dict())


# --- Legacy history baseline -------------------------------------------------------------


@router.get("/imports/legacy-history/template.csv")
def legacy_template(_user: TemplateReader) -> Response:
    return _csv_response(
        legacy_history_service.template_csv(), "solaris-legacy-history-template.csv"
    )


@router.get("/imports/legacy-history/fields", response_model=BulkFieldsOut)
def legacy_fields(_user: FieldsReader) -> BulkFieldsOut:
    return _fields(
        legacy_history_service.KIND,
        legacy_history_service.FIELD_SYNONYMS,
        legacy_history_service.REQUIRED_FIELDS,
        legacy_history_service.TEMPLATE_HEADERS,
        [
            "One row per past shipment. Dates are YYYY-MM-DD; milestones must follow the "
            "journey order and none may be in the future.",
            "final_status is delivered, returned, cancelled or lost; a delivered, returned "
            "or cancelled shipment needs its closing date.",
            "Legacy records are read-only history for staff. They never notify a customer, "
            "are never quoted, invoiced, locked or expired, and are kept out of operational "
            "queues and finance reports.",
            "Re-running a baseline matches what is already there; a baseline can be voided "
            "as a whole.",
        ],
    )


@router.post("/imports/legacy-history/dry-run", response_model=DryRunOut)
async def legacy_dry_run(
    request: Request,
    db: DbSession,
    user: DryRunner,
    file: Annotated[UploadFile, File()],
    cutoff_date: Annotated[str | None, Form()] = None,
) -> DryRunOut:
    cutoff = legacy_history_service.parse_cutoff(cutoff_date)
    content = await _read_upload(file)
    result = legacy_history_service.dry_run(db, content, cutoff=cutoff, file_name=file.filename)
    bulk_import_common.record_dry_run(db, result, actor=user, ip_address=client_ip(request))
    commit_with_retry(db)
    return DryRunOut(**result.to_dict())


@router.post("/imports/legacy-history/commit", response_model=BulkCommitOut)
async def legacy_commit(
    request: Request,
    db: DbSession,
    user: Committer,
    file: Annotated[UploadFile, File()],
    content_sha256: Annotated[str, Form()],
    confirm: Annotated[bool, Form()] = False,
    cutoff_date: Annotated[str | None, Form()] = None,
) -> BulkCommitOut:
    bulk_import_common.require_confirm(confirm)
    cutoff = legacy_history_service.parse_cutoff(cutoff_date)
    content = await _read_upload(file)
    result = legacy_history_service.commit(
        db,
        content,
        expected_sha256=content_sha256,
        actor=user,
        cutoff=cutoff,
        file_name=file.filename,
        ip_address=client_ip(request),
    )
    commit_with_retry(db)
    return BulkCommitOut(**result.to_dict())


def _baseline_out(baseline: LegacyBaseline, batch: ImportBatch) -> BaselineOut:
    return BaselineOut(
        batch_public_id=batch.public_id,
        file_name=batch.file_name,
        status=baseline.status,
        cutoff_date=baseline.cutoff_date,
        row_count=batch.row_count,
        created_count=batch.created_count,
        matched_count=batch.matched_count,
        rejected_count=batch.rejected_count,
        committed_at=batch.committed_at,
        voided_at=baseline.voided_at,
        void_reason=baseline.void_reason,
    )


@router.get("/imports/legacy-history/baselines", response_model=list[BaselineOut])
def legacy_baselines(db: DbSession, _user: FieldsReader) -> list[BaselineOut]:
    return [_baseline_out(b, batch) for b, batch in legacy_history_service.list_baselines(db)]


@router.post("/imports/legacy-history/baselines/{batch_public_id}/void", response_model=BaselineOut)
def void_legacy_baseline(
    batch_public_id: str,
    payload: VoidBaselineIn,
    request: Request,
    db: DbSession,
    user: Committer,
) -> BaselineOut:
    bulk_import_common.require_confirm(payload.confirm)
    baseline = legacy_history_service.void_baseline(
        db, batch_public_id, reason=payload.reason, actor=user, ip_address=client_ip(request)
    )
    commit_with_retry(db)
    batch = db.get(ImportBatch, baseline.batch_id)
    return _baseline_out(baseline, batch)


# --- Staff reads of legacy records ---------------------------------------------------------


def _legacy_out(db, record: LegacyShipment, customer, *, with_events: bool) -> LegacyShipmentOut:
    baseline = db.get(LegacyBaseline, record.baseline_id)
    batch = db.get(ImportBatch, baseline.batch_id) if baseline else None
    return LegacyShipmentOut(
        id=record.id,
        legacy_reference=record.legacy_reference,
        customer_id=record.customer_id,
        customer_public_id=customer.public_id,
        customer_name=customer.full_name,
        route_group=record.route_group,
        direction=record.direction,
        transport_mode=record.transport_mode,
        booked_on=record.booked_on,
        final_status=record.final_status,
        completed_on=record.completed_on,
        recipient_name=record.recipient_name,
        recipient_city=record.recipient_city,
        recipient_province_state=record.recipient_province_state,
        recipient_country_code=record.recipient_country_code,
        package_count=record.package_count,
        total_weight_kg=record.total_weight_kg,
        contents_description=record.contents_description,
        notes=record.notes,
        is_voided=record.is_voided,
        batch_public_id=batch.public_id if batch else None,
        events=[
            LegacyEventOut(
                sequence=event.sequence, event_type=event.event_type, occurred_on=event.occurred_on
            )
            for event in record.events
        ]
        if with_events
        else [],
    )


@router.get("/legacy-shipments", response_model=Page[LegacyShipmentOut])
def list_legacy_shipments(
    db: DbSession,
    _user: LegacyReader,
    customer_id: int | None = None,
    search: str | None = Query(default=None, max_length=120),
    include_voided: bool = False,
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> Page[LegacyShipmentOut]:
    rows, total = legacy_history_service.list_records(
        db,
        customer_id=customer_id,
        search=search,
        include_voided=include_voided,
        limit=limit,
        offset=offset,
    )
    return Page[LegacyShipmentOut](
        items=[_legacy_out(db, record, customer, with_events=False) for record, customer in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/legacy-shipments/{record_id}", response_model=LegacyShipmentOut)
def read_legacy_shipment(db: DbSession, _user: LegacyReader, record_id: int) -> LegacyShipmentOut:
    record, customer = legacy_history_service.get_record(db, record_id)
    return _legacy_out(db, record, customer, with_events=True)
