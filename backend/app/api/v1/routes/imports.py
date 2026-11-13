"""CSV customer import routes (CRM.md section 13).

Four endpoints, three permissions, and one rule: the endpoint that writes is the last one
and it requires an explicit confirmation.

| Endpoint | Permission | Writes |
|---|---|---|
| `GET /imports/customers/template.csv` | `import:template` | no |
| `GET /imports/customers/fields` | `import:preview` | no |
| `POST /imports/customers/preview` | `import:preview` + `duplicate:review` | **no** |
| `POST /imports/customers/commit` | `import:commit` + `customer:create` | yes |
| `GET /imports/batches` | `import:preview` | no |

Preview additionally requires ``duplicate:review``, because that is exactly what a preview
does: it puts an uploaded person and an existing customer side by side and asks whether
they are the same. Commit additionally requires ``customer:create``, because that is what
it performs.

The upload is read into memory once, bounded before anything is parsed, and never written
to disk. The preview's audit entry records that a file was previewed and how many rows it
held — never a value from it.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Query, Request, Response, UploadFile

from app.api.deps import DbSession, client_ip, require
from app.core.db import commit_with_retry
from app.core.permissions import Permission
from app.models import User
from app.schemas.common import Page
from app.schemas.imports import (
    ImportBatchOut,
    ImportBatchRowOut,
    ImportCommitOut,
    ImportFieldsOut,
    ImportPreviewOut,
)
from app.services import audit_service, customer_import_service
from app.services.csv_safety import MAX_CELL_CHARS, MAX_COLUMNS, MAX_FILE_BYTES, MAX_ROWS
from app.services.errors import NotFoundError, ValidationError

router = APIRouter(prefix="/imports", tags=["imports"])

TemplateReader = Annotated[User, Depends(require(Permission.IMPORT_TEMPLATE))]
Previewer = Annotated[
    User, Depends(require(Permission.IMPORT_PREVIEW, Permission.DUPLICATE_REVIEW))
]
Committer = Annotated[User, Depends(require(Permission.IMPORT_COMMIT, Permission.CUSTOMER_CREATE))]
HistoryReader = Annotated[User, Depends(require(Permission.IMPORT_PREVIEW))]


async def _read_upload(file: UploadFile) -> bytes:
    """Read the upload with a hard byte ceiling.

    The bound is applied while reading rather than after, so an oversized upload never
    occupies memory proportional to its size. ``UploadFile`` spools to a temporary file
    above a threshold; reading a bounded prefix and refusing means a hostile upload is
    rejected before the rest of it matters.
    """
    chunk = await file.read(MAX_FILE_BYTES + 1)
    if len(chunk) > MAX_FILE_BYTES:
        raise ValidationError(
            f"The file is larger than the {MAX_FILE_BYTES // 1024} kB limit. Split it "
            "into smaller files and import each.",
            field="file",
        )
    return chunk


@router.get("/customers/template.csv")
def customer_template(_user: TemplateReader) -> Response:
    """A blank template with two rows of clearly synthetic sample data.

    The samples exercise the hard cases on purpose — a Vietnamese name with diacritics, an
    international phone number — because a template whose examples avoid them teaches the
    operator the wrong lesson. They use the reserved ``example.com`` domain and fictional
    555 numbers, and contain no real person's details.
    """
    return Response(
        content=customer_import_service.template_csv(),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": 'attachment; filename="solaris-customer-import-template.csv"',
            "Cache-Control": "no-store",
        },
    )


@router.get("/customers/fields", response_model=ImportFieldsOut)
def customer_import_fields(_user: Previewer) -> ImportFieldsOut:
    """The fields an import may write, the headers that map to them, and the limits.

    Published through the API so the interface can render the mapping explanation from the
    same definition the parser uses, rather than a copy that drifts.
    """
    return ImportFieldsOut(
        fields=[
            {
                "field": canonical,
                "headers": list(spellings),
                "required": canonical in customer_import_service.REQUIRED_FIELDS,
                "allowed_values": list(customer_import_service.ENUM_FIELDS.get(canonical, ()) or [])
                or None,
            }
            for canonical, spellings in customer_import_service.FIELD_SYNONYMS.items()
        ],
        template_headers=list(customer_import_service.TEMPLATE_HEADERS),
        conflict_policies=list(customer_import_service.CONFLICT_POLICIES),
        limits={
            "max_file_bytes": MAX_FILE_BYTES,
            "max_rows": MAX_ROWS,
            "max_columns": MAX_COLUMNS,
            "max_cell_characters": MAX_CELL_CHARS,
        },
        notes=[
            "Only the fields listed here are imported. Any other column in the file is "
            "reported as unrecognized and its values are ignored.",
            "Consent is never imported. Imported contact details are not marketing "
            "eligible until consent is recorded in the CRM with its evidence.",
            "An existing value is never overwritten. The most an import will do to a "
            "record it already created is fill fields that are empty.",
            "Probable duplicates are never merged automatically. Each one waits for a decision.",
        ],
    )


@router.post("/customers/preview", response_model=ImportPreviewOut)
async def preview_customer_import(
    request: Request,
    db: DbSession,
    user: Previewer,
    file: Annotated[UploadFile, File()],
) -> ImportPreviewOut:
    """Parse, validate and classify an uploaded file. **Creates and changes nothing.**"""
    content = await _read_upload(file)
    preview = customer_import_service.build_preview(db, content, file_name=file.filename)

    # Audited because somebody looked at a file of contact details, which is worth
    # recording. The entry carries counts and a digest -- never a value from the file, and
    # never the file itself (CRM.md section 11).
    audit_service.record_audit(
        db,
        action="customer.import_preview",
        entity_type="import_preview",
        entity_id=preview.content_sha256[:16],
        summary=f"Previewed a customer import of {preview.row_count} row(s)",
        actor=user,
        ip_address=client_ip(request),
        detail={
            "row_count": preview.row_count,
            "content_sha256": preview.content_sha256,
            "new": preview.counts.get(customer_import_service.NEW, 0),
            "exact_match": preview.counts.get(customer_import_service.EXACT_MATCH, 0),
            "duplicate_review": preview.counts.get(customer_import_service.DUPLICATE_REVIEW, 0),
            "rejected": preview.counts.get(customer_import_service.REJECTED, 0),
            "unrecognized_column_count": len(preview.unmapped_headers),
        },
    )
    commit_with_retry(db)
    return ImportPreviewOut(**preview.to_dict())


@router.post("/customers/commit", response_model=ImportCommitOut)
async def commit_customer_import(
    request: Request,
    db: DbSession,
    user: Committer,
    file: Annotated[UploadFile, File()],
    content_sha256: Annotated[str, Form()],
    confirm: Annotated[bool, Form()] = False,
    conflict_policy: Annotated[str, Form()] = customer_import_service.POLICY_SKIP,
    decisions_json: Annotated[str | None, Form()] = None,
) -> ImportCommitOut:
    """Commit a previewed import.

    The same file is uploaded again and re-validated from scratch. ``content_sha256`` is
    the digest the preview returned: if the file has changed since, the commit is refused,
    because the operator reviewed a different set of rows from the one about to be
    written.

    ``confirm`` must be explicitly true. A commit is not something to arrive at by
    default.
    """
    if not confirm:
        raise ValidationError(
            "Confirm the import before it can be committed. Nothing has been imported.",
            field="confirm",
        )

    decisions = _parse_decisions(decisions_json)
    content = await _read_upload(file)

    result = customer_import_service.commit_import(
        db,
        content,
        expected_sha256=content_sha256,
        actor=user,
        file_name=file.filename,
        conflict_policy=conflict_policy,
        decisions=decisions,
        ip_address=client_ip(request),
    )
    # One transaction for the whole batch: either every accepted row landed or none did
    # (DEC-0079).
    commit_with_retry(db)
    return ImportCommitOut(**result.to_dict())


def _parse_decisions(raw: str | None) -> dict[int, str]:
    """Parse the per-row duplicate decisions.

    Sent as JSON in a form field because the request is multipart -- the file and the
    decisions have to travel together so the commit can re-validate the exact bytes the
    decisions refer to.
    """
    if not raw:
        return {}
    import json

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValidationError("Row decisions could not be read.", field="decisions") from exc
    if not isinstance(parsed, dict):
        raise ValidationError(
            "Row decisions must be an object keyed by row number.", field="decisions"
        )
    if len(parsed) > MAX_ROWS:
        raise ValidationError("Too many row decisions.", field="decisions")
    decisions: dict[int, str] = {}
    for key, value in parsed.items():
        try:
            row_number = int(key)
        except (TypeError, ValueError) as exc:
            raise ValidationError(f"'{key}' is not a row number.", field="decisions") from exc
        if not isinstance(value, str):
            raise ValidationError(f"Row {row_number}: decision must be text.", field="decisions")
        decisions[row_number] = value
    return decisions


@router.get("/batches", response_model=Page[ImportBatchOut])
def list_import_batches(
    db: DbSession,
    _user: HistoryReader,
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    kind: str | None = Query(default=None, pattern="^(customers|shipments|legacy_history)$"),
) -> Page[ImportBatchOut]:
    """Committed imports, newest first. Counts and outcomes only; ``kind`` filters."""
    rows, total = customer_import_service.list_batches(db, limit=limit, offset=offset, kind=kind)
    return Page[ImportBatchOut](
        items=[ImportBatchOut.model_validate(row, from_attributes=True) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/batches/{public_id}", response_model=ImportBatchOut)
def read_import_batch(db: DbSession, _user: HistoryReader, public_id: str) -> ImportBatchOut:
    """One committed import, with the outcome of every row.

    Row numbers, outcomes, reason codes, and the customers created. No cell values: the
    file was never stored, and this is the durable record of what it did rather than of
    what it said.
    """
    batch = customer_import_service.batch_detail(db, public_id)
    if batch is None:
        raise NotFoundError("Import batch not found.")
    out = ImportBatchOut.model_validate(batch, from_attributes=True)
    out.rows = [
        ImportBatchRowOut.model_validate(row, from_attributes=True)
        for row in sorted(batch.rows, key=lambda item: item.row_number)
    ]
    return out
