"""Staff tariff and exchange-rate routes (Phase 13A).

All on the **staff** router, all behind the permission matrix, none on the public or
account routers. ``tariff:read`` sees versions, products, rules, accessorials and the
exchange-rate state; ``tariff:manage`` (Admin) imports a workbook and activates a version.

**No route here contacts the bank or the vendor.** The exchange-rate routes read rows the
worker wrote; the import route reads a file the operator uploaded. There is deliberately
no "fetch the rate now" button: the worker is the only thing that talks to the bank, so a
request can never be made to wait on it, and a rate can never appear that the attempt log
does not account for.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from fastapi.encoders import jsonable_encoder
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.api.deps import CurrentUser, DbSession, require
from app.core.config import settings
from app.core.db import commit_with_retry, run_unit_with_retry
from app.core.permissions import Permission
from app.models import (
    FxRateSnapshot,
    FxSyncAttempt,
    TariffAccessorial,
    TariffBeyondRate,
    TariffEmailIntake,
    TariffIntakeSettings,
    TariffProduct,
    TariffSurchargeRule,
    TariffVersion,
    TariffVersionReview,
    User,
    Vendor,
)
from app.schemas.tariff import (
    FxAttemptOut,
    FxHistoryOut,
    FxLatestOut,
    FxSnapshotOut,
    TariffAccessorialOut,
    TariffBeyondRateOut,
    TariffConfirmedPriceStepOut,
    TariffImportWarningOut,
    TariffImportWarningsOut,
    TariffIntakeListOut,
    TariffIntakeOut,
    TariffIntakeSettingsOut,
    TariffIntakeSettingsUpdate,
    TariffIntakeUploadOut,
    TariffPendingCountOut,
    TariffProductDetailOut,
    TariffProductOut,
    TariffRejectIn,
    TariffSurchargeRuleListOut,
    TariffSurchargeRuleOut,
    TariffVersionDetailOut,
    TariffVersionDiffOut,
    TariffVersionListOut,
    TariffVersionOut,
)
from app.services import (
    fx_service,
    pricing_method_service,
    pricing_service,
    quote_expiry_service,
    rate_sheet_service,
    tariff_import_service,
    tariff_intake_service,
)
from app.services.errors import NotFoundError, ValidationError

router = APIRouter(tags=["tariffs"])

XLSX_MAGIC = b"PK\x03\x04"


def _version_out(version: TariffVersion, review_decision: str | None = None) -> TariffVersionOut:
    return TariffVersionOut(
        id=version.id,
        public_id=version.public_id,
        vendor_key=version.vendor.key,
        label=version.label,
        source_file_name=version.source_file_name,
        source_sha256=version.source_sha256,
        effective_from=version.effective_from,
        effective_to=version.effective_to,
        status=version.status,
        imported_at=version.imported_at,
        activated_at=version.activated_at,
        dim_divisor_default=version.dim_divisor_default,
        fixed_fx_vnd_per_cad=version.fixed_fx_vnd_per_cad,
        cost_currency=version.cost_currency,
        review_decision=review_decision,
    )


def _review_decisions(db, version_ids: list[int]) -> dict[int, str]:
    if not version_ids:
        return {}
    rows = db.execute(
        select(TariffVersionReview.tariff_version_id, TariffVersionReview.decision).where(
            TariffVersionReview.tariff_version_id.in_(version_ids)
        )
    ).all()
    return {row.tariff_version_id: row.decision for row in rows}


def _fx_out(snapshot) -> FxSnapshotOut:
    out = FxSnapshotOut.model_validate(snapshot)
    return out.model_copy(update={"is_demo": (snapshot.source_url or "").startswith("demo://")})


@router.get("/tariffs/versions", response_model=TariffVersionListOut)
def list_versions(
    db: DbSession,
    _guard: Annotated[User, Depends(require(Permission.TARIFF_READ))],
    vendor: str | None = Query(default=None, max_length=40),
) -> TariffVersionListOut:
    query = select(TariffVersion).join(Vendor).options(selectinload(TariffVersion.vendor))
    if vendor:
        query = query.where(Vendor.key == vendor)
    rows = db.scalars(
        query.order_by(TariffVersion.effective_from.desc(), TariffVersion.id.desc())
    ).all()
    decisions = _review_decisions(db, [v.id for v in rows])
    return TariffVersionListOut(
        items=[_version_out(v, decisions.get(v.id)) for v in rows], total=len(rows)
    )


@router.get("/tariffs/versions/{version_id}", response_model=TariffVersionDetailOut)
def version_detail(
    version_id: int,
    db: DbSession,
    _guard: Annotated[User, Depends(require(Permission.TARIFF_READ))],
) -> TariffVersionDetailOut:
    version = tariff_import_service.get_version(db, version_id)
    base = _version_out(version, _review_decisions(db, [version.id]).get(version.id))
    return TariffVersionDetailOut(
        **base.model_dump(),
        counts=tariff_import_service.version_counts(db, version),
        report=tariff_import_service.report(version),
    )


@router.get("/tariffs/versions/{version_id}/warnings", response_model=TariffImportWarningsOut)
def version_warnings(
    version_id: int,
    db: DbSession,
    _guard: Annotated[User, Depends(require(Permission.TARIFF_READ))],
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> TariffImportWarningsOut:
    """RC-20: the importer's warnings for one version, as stored in its import report, a
    page at a time. ``count`` is every warning (the anomalies); the owner-confirmed price
    steps (DEC-0222) are returned apart in ``confirmed_price_steps`` and are not counted."""
    version = tariff_import_service.get_version(db, version_id)
    report = tariff_import_service.report(version)
    anomalies = [a for a in report.get("anomalies") or [] if isinstance(a, dict)]
    by_code: dict[str, int] = {}
    for anomaly in anomalies:
        code = str(anomaly.get("code") or "")
        by_code[code] = by_code.get(code, 0) + 1
    steps = [s for s in report.get("confirmed_price_steps") or [] if isinstance(s, dict)]
    return TariffImportWarningsOut(
        version_id=version.id,
        version_public_id=version.public_id,
        count=len(anomalies),
        counts_by_code=by_code,
        limit=limit,
        offset=offset,
        items=[
            TariffImportWarningOut(
                code=str(a.get("code") or ""),
                message=str(a.get("message") or ""),
                sheet=a.get("sheet"),
                cell=a.get("cell"),
            )
            for a in anomalies[offset : offset + limit]
        ],
        confirmed_price_steps=[
            TariffConfirmedPriceStepOut(
                **{k: s.get(k) for k in TariffConfirmedPriceStepOut.model_fields if k in s}
            )
            for s in steps
        ],
    )


@router.get("/tariffs/versions/{version_id}/products", response_model=list[TariffProductOut])
def version_products(
    version_id: int,
    db: DbSession,
    _guard: Annotated[User, Depends(require(Permission.TARIFF_READ))],
) -> list[TariffProductOut]:
    version = tariff_import_service.get_version(db, version_id)
    rows = db.scalars(
        select(TariffProduct)
        .where(TariffProduct.version_id == version.id)
        .order_by(TariffProduct.origin, TariffProduct.code)
    ).all()
    return [TariffProductOut.model_validate(r) for r in rows]


@router.get(
    "/tariffs/versions/{version_id}/products/{product_id}", response_model=TariffProductDetailOut
)
def product_detail(
    version_id: int,
    product_id: int,
    db: DbSession,
    _guard: Annotated[User, Depends(require(Permission.TARIFF_READ))],
) -> TariffProductDetailOut:
    version = tariff_import_service.get_version(db, version_id)
    product = db.scalar(
        select(TariffProduct)
        .where(TariffProduct.version_id == version.id, TariffProduct.id == product_id)
        .options(selectinload(TariffProduct.brackets))
    )
    if product is None:
        raise NotFoundError("Tariff product not found.")
    return TariffProductDetailOut.model_validate(product)


@router.get("/tariffs/versions/{version_id}/surcharges", response_model=TariffSurchargeRuleListOut)
def version_surcharges(
    version_id: int,
    db: DbSession,
    _guard: Annotated[User, Depends(require(Permission.TARIFF_READ))],
    section: str | None = Query(default=None, max_length=20),
    canada_only: bool = Query(default=True),
    q: str | None = Query(default=None, max_length=64),
) -> TariffSurchargeRuleListOut:
    """The surcharge catalogue for the fee picker. ``q`` is a plain substring over the
    vendor's name, folded for accents by the caller's choice of query; ``canada_only``
    hides the USA section and the EU/UK-only rows."""
    version = tariff_import_service.get_version(db, version_id)
    conditions = [TariffSurchargeRule.version_id == version.id]
    if section:
        conditions.append(TariffSurchargeRule.section == section)
    if canada_only:
        conditions.append(TariffSurchargeRule.applies_to_canada.is_(True))
    if q:
        conditions.append(func.lower(TariffSurchargeRule.name).contains(q.lower()))
    rows = db.scalars(
        select(TariffSurchargeRule)
        .where(*conditions)
        .options(selectinload(TariffSurchargeRule.tiers))
        .order_by(TariffSurchargeRule.section, TariffSurchargeRule.stt)
    ).all()
    classes = pricing_method_service.allocation_class_map(db)
    return TariffSurchargeRuleListOut(
        items=[
            TariffSurchargeRuleOut.model_validate(r).model_copy(
                update={
                    "above_top_tier": pricing_service.above_top_tier(r.section, r.stt),
                    "allocation_class": classes.get((r.section, r.stt)),
                }
            )
            for r in rows
        ],
        total=len(rows),
    )


@router.get(
    "/tariffs/versions/{version_id}/accessorials", response_model=list[TariffAccessorialOut]
)
def version_accessorials(
    version_id: int,
    db: DbSession,
    _guard: Annotated[User, Depends(require(Permission.TARIFF_READ))],
) -> list[TariffAccessorialOut]:
    version = tariff_import_service.get_version(db, version_id)
    rows = db.scalars(
        select(TariffAccessorial)
        .where(TariffAccessorial.version_id == version.id)
        .order_by(TariffAccessorial.id)
    ).all()
    return [TariffAccessorialOut.model_validate(r) for r in rows]


@router.get("/tariffs/versions/{version_id}/beyond-rates", response_model=list[TariffBeyondRateOut])
def version_beyond_rates(
    version_id: int,
    db: DbSession,
    _guard: Annotated[User, Depends(require(Permission.TARIFF_READ))],
) -> list[TariffBeyondRateOut]:
    version = tariff_import_service.get_version(db, version_id)
    rows = db.scalars(
        select(TariffBeyondRate)
        .where(TariffBeyondRate.version_id == version.id)
        .order_by(TariffBeyondRate.beyond_code)
    ).all()
    return [TariffBeyondRateOut.model_validate(r) for r in rows]


async def _read_upload(file: UploadFile) -> bytes:
    limit = settings.tariff_import_max_bytes
    chunk = await file.read(limit + 1)
    if len(chunk) > limit:
        raise ValidationError(
            f"The workbook is larger than the {limit // (1024 * 1024)} MB limit.", field="file"
        )
    if not chunk.startswith(XLSX_MAGIC):
        raise ValidationError("The file is not an .xlsx workbook.", field="file")
    return chunk


@router.post("/tariffs/versions/import", response_model=TariffVersionDetailOut, status_code=201)
async def import_version(
    db: DbSession,
    user: CurrentUser,
    _guard: Annotated[User, Depends(require(Permission.TARIFF_READ, Permission.TARIFF_MANAGE))],
    file: Annotated[UploadFile, File()],
    effective_from: Annotated[date, Form()],
    label: Annotated[str | None, Form(max_length=120)] = None,
) -> TariffVersionDetailOut:
    """Import a vendor workbook as a **draft** tariff version.

    The file is parsed in memory; the framework may spool a part larger than 1 MiB to a
    temporary file that is deleted when the request ends, and nothing is written under the
    application's control. A file already imported (same SHA-256) is refused with 409 and
    the existing version's identifier.
    """
    content = await _read_upload(file)
    version = tariff_import_service.import_workbook(
        db,
        content,
        file_name=file.filename,
        effective_from=effective_from,
        label=label,
        actor=user,
    )
    commit_with_retry(db)
    db.refresh(version)
    base = _version_out(version)
    return TariffVersionDetailOut(
        **base.model_dump(),
        counts=tariff_import_service.version_counts(db, version),
        report=tariff_import_service.report(version),
    )


@router.post("/tariffs/versions/{version_id}/activate", response_model=TariffVersionOut)
def activate_version(
    version_id: int,
    db: DbSession,
    user: CurrentUser,
    _guard: Annotated[User, Depends(require(Permission.TARIFF_READ, Permission.TARIFF_MANAGE))],
) -> TariffVersionOut:
    """Activate a draft. Since Phase 13H only a designated approver may (OD-76), the same
    rule as ``POST /tariffs/versions/{id}/approve``. Service calls without an actor (seed
    and demo scripts) are not routes and are unaffected."""
    version = tariff_import_service.get_version(db, version_id)
    tariff_intake_service.check_can_activate(db, version, user)
    tariff_import_service.activate_version(db, version, actor=user)
    # Owner decision 9: quotes for goods not yet received expire (idempotent).
    quote_expiry_service.expire_for_new_tariff(db, version, actor=user)
    commit_with_retry(db)
    db.refresh(version)
    return _version_out(version)


# --- Admin "Import Kango rate sheet" (method v0.7, DEC-0264) ---------------------------------
#
# Upload → draft + diff (nothing changes) → explicit confirm through the approve route
# (``POST /tariffs/versions/{id}/approve``) → history; rollback re-activates an earlier version.


@router.post("/tariffs/rate-sheet/import", status_code=201)
async def import_rate_sheet(
    db: DbSession,
    user: CurrentUser,
    _guard: Annotated[User, Depends(require(Permission.TARIFF_READ, Permission.TARIFF_MANAGE))],
    file: Annotated[UploadFile, File()],
    effective_from: Annotated[date, Form()],
    label: Annotated[str | None, Form(max_length=120)] = None,
) -> dict:
    """Parse a Kango sheet into a **draft** and return its diff against the active version.
    Nothing prices differently until the draft is confirmed (approved)."""
    content = await _read_upload(file)
    version, diff = rate_sheet_service.import_sheet(
        db, content, file_name=file.filename, effective_from=effective_from, label=label,
        actor=user,
    )  # fmt: skip
    commit_with_retry(db)
    db.refresh(version)
    return {
        "version": _version_out(version).model_dump(mode="json"),
        "diff": jsonable_encoder(diff),
        "next_step": "confirm",
    }


@router.get("/tariffs/versions/{version_id}/rate-sheet-diff")
def rate_sheet_diff(
    version_id: int,
    db: DbSession,
    _guard: Annotated[User, Depends(require(Permission.TARIFF_READ))],
) -> dict:
    version = tariff_import_service.get_version(db, version_id)
    return jsonable_encoder(rate_sheet_service.sheet_diff(db, version))


@router.get("/tariffs/rate-sheet/history")
def rate_sheet_history(
    db: DbSession,
    _guard: Annotated[User, Depends(require(Permission.TARIFF_READ))],
) -> dict:
    return {"versions": jsonable_encoder(rate_sheet_service.history(db))}


@router.post("/tariffs/versions/{version_id}/rollback", response_model=TariffVersionOut)
def rollback_version(
    version_id: int,
    db: DbSession,
    user: CurrentUser,
    _guard: Annotated[User, Depends(require(Permission.TARIFF_READ, Permission.TARIFF_MANAGE))],
) -> TariffVersionOut:
    """Re-activate an earlier (superseded) version. The same approver rule as activation."""

    def work():
        version = tariff_import_service.get_version(db, version_id)
        tariff_intake_service.check_can_activate(db, version, user)
        return rate_sheet_service.rollback(db, version, actor=user)

    version = run_unit_with_retry(db, work)
    db.refresh(version)
    return _version_out(version)


# --- Vendor rate-email intake and approval (Phase 13H, OD-76) ------------------------------
#
# No route here connects to a mailbox: an email arrives as an uploaded ``.eml`` or through
# the folder worker. Responses carry provenance (sender address, subject, attachment name
# and digest, status) and never the email body.

TariffManager = Annotated[User, Depends(require(Permission.TARIFF_READ, Permission.TARIFF_MANAGE))]


def _intake_out(db, intake: TariffEmailIntake) -> TariffIntakeOut:
    version = db.get(TariffVersion, intake.tariff_version_id) if intake.tariff_version_id else None
    return TariffIntakeOut(
        id=intake.id,
        message_id=intake.message_id,
        sender=intake.sender,
        subject=intake.subject,
        received_at=intake.received_at,
        source=intake.source,
        attachment_name=intake.attachment_name,
        attachment_sha256=intake.attachment_sha256,
        status=intake.status,
        tariff_version_id=intake.tariff_version_id,
        tariff_version_public_id=version.public_id if version else None,
        tariff_version_status=version.status if version else None,
        error=intake.error,
        warning=intake.warning,
        reviewed_at=intake.reviewed_at,
        review_note=intake.review_note,
        created_at=intake.created_at,
    )


def _intake_settings_out(db) -> TariffIntakeSettingsOut:
    saved = db.get(TariffIntakeSettings, 1)
    row = saved or tariff_intake_service.get_settings(db)
    return TariffIntakeSettingsOut(
        mailbox_address=row.mailbox_address,
        approver_emails=list(row.approver_emails or []),
        allowed_sender_domains=list(row.allowed_sender_domains or []),
        updated_at=row.updated_at if saved else None,
        is_default=saved is None,
    )


@router.post("/tariffs/intake/upload", response_model=TariffIntakeUploadOut, status_code=201)
async def upload_rate_email(
    db: DbSession,
    user: TariffManager,
    file: Annotated[UploadFile, File()],
) -> TariffIntakeUploadOut:
    """Receive one vendor rate email (``.eml``). A qualifying workbook becomes a **draft**;
    nothing is activated. An email already received (same Message-ID) answers with the
    first record and ``created: false``."""
    if not (file.filename or "").lower().endswith(".eml"):
        raise ValidationError("Upload the vendor's email as an .eml file.", field="file")
    limit = settings.tariff_intake_max_eml_bytes
    raw = await file.read(limit + 1)
    if len(raw) > limit:
        raise ValidationError(
            f"The email is larger than the {limit // (1024 * 1024)} MB limit.", field="file"
        )
    result = tariff_intake_service.ingest_and_commit(db, raw, source="upload", actor=user)
    out = _intake_out(db, result.intake)
    return TariffIntakeUploadOut(**out.model_dump(), created=result.created)


@router.get("/tariffs/intake", response_model=TariffIntakeListOut)
def list_rate_emails(
    db: DbSession,
    user: TariffManager,
    status: str | None = Query(default=None, max_length=20),
    limit: int = Query(default=100, ge=1, le=500),
) -> TariffIntakeListOut:
    query = select(TariffEmailIntake)
    if status:
        query = query.where(TariffEmailIntake.status == status)
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = db.scalars(
        query.order_by(TariffEmailIntake.created_at.desc(), TariffEmailIntake.id.desc()).limit(
            limit
        )
    ).all()
    return TariffIntakeListOut(
        items=[_intake_out(db, r) for r in rows],
        total=total,
        viewer_is_approver=tariff_intake_service.is_approver(db, user),
    )


@router.get("/tariffs/intake/pending-count", response_model=TariffPendingCountOut)
def pending_count(
    db: DbSession, user: Annotated[User, Depends(require(Permission.TARIFF_READ))]
) -> TariffPendingCountOut:
    """Phase 15: the approver badge -- drafts awaiting a decision and held-sender rate emails,
    with whether the viewer is a designated approver (the screen shows the badge only then).
    Counts only, and only to an approver: anyone else gets zeros (Phase 15 review); nothing
    is emailed."""
    if not tariff_intake_service.is_approver(db, user):
        return TariffPendingCountOut(
            viewer_is_approver=False, drafts_awaiting=0, held_senders=0, total=0
        )
    drafts, held = tariff_intake_service.pending_counts(db)
    return TariffPendingCountOut(
        viewer_is_approver=True,
        drafts_awaiting=drafts,
        held_senders=held,
        total=drafts + held,
    )


@router.get("/tariffs/intake/settings", response_model=TariffIntakeSettingsOut)
def read_intake_settings(db: DbSession, _user: TariffManager) -> TariffIntakeSettingsOut:
    return _intake_settings_out(db)


@router.patch("/tariffs/intake/settings", response_model=TariffIntakeSettingsOut)
def update_intake_settings(
    payload: TariffIntakeSettingsUpdate,
    db: DbSession,
    user: Annotated[
        User,
        Depends(
            require(Permission.TARIFF_READ, Permission.TARIFF_MANAGE, Permission.SETTINGS_MANAGE)
        ),
    ],
) -> TariffIntakeSettingsOut:
    run_unit_with_retry(
        db,
        lambda: tariff_intake_service.update_settings(
            db,
            approver_emails=payload.approver_emails,
            allowed_sender_domains=payload.allowed_sender_domains,
            actor=user,
        ),
    )
    return _intake_settings_out(db)


@router.post("/tariffs/intake/{intake_id}/release", response_model=TariffIntakeOut)
def release_rate_email(intake_id: int, db: DbSession, user: TariffManager) -> TariffIntakeOut:
    """An approver releases a held sender's email; its workbook is imported as a draft."""

    def work():
        intake = tariff_intake_service.get_intake(db, intake_id)
        return tariff_intake_service.release(db, intake, user)

    intake = run_unit_with_retry(db, work)
    tariff_intake_service.archive_held(intake.id)
    return _intake_out(db, intake)


@router.post("/tariffs/intake/{intake_id}/reprocess", response_model=TariffIntakeOut)
def reprocess_rate_email(intake_id: int, db: DbSession, user: TariffManager) -> TariffIntakeOut:
    """An approver reprocesses a failed folder email from its kept file (``failed/``)."""
    result = tariff_intake_service.reprocess_and_commit(db, intake_id, user)
    return _intake_out(db, result.intake)


@router.get("/tariffs/versions/{version_id}/diff", response_model=TariffVersionDiffOut)
def version_diff(
    version_id: int,
    db: DbSession,
    _guard: Annotated[User, Depends(require(Permission.TARIFF_READ))],
) -> TariffVersionDiffOut:
    version = tariff_import_service.get_version(db, version_id)
    return TariffVersionDiffOut(**tariff_intake_service.version_diff(db, version))


@router.post("/tariffs/versions/{version_id}/approve", response_model=TariffVersionOut)
def approve_version(version_id: int, db: DbSession, user: TariffManager) -> TariffVersionOut:
    """The designated approver activates a draft (OD-76); the active version is superseded."""

    def work():
        version = tariff_import_service.get_version(db, version_id)
        return tariff_intake_service.approve(db, version, user)

    version = run_unit_with_retry(db, work)
    db.refresh(version)
    return _version_out(version)


@router.post("/tariffs/versions/{version_id}/reject", response_model=TariffVersionOut)
def reject_version(
    version_id: int, payload: TariffRejectIn, db: DbSession, user: TariffManager
) -> TariffVersionOut:
    """The designated approver rejects a draft. It stays a draft and can never be activated."""

    def work():
        version = tariff_import_service.get_version(db, version_id)
        return tariff_intake_service.reject(db, version, user, payload.reason)

    version = run_unit_with_retry(db, work)
    db.refresh(version)
    return _version_out(version)


# --- Exchange rates -------------------------------------------------------------------------


@router.get("/fx/latest", response_model=FxLatestOut)
def fx_latest(
    db: DbSession,
    _guard: Annotated[User, Depends(require(Permission.TARIFF_READ))],
) -> FxLatestOut:
    snapshot = fx_service.latest_snapshot(db)
    attempt = fx_service.latest_attempt(db)
    return FxLatestOut(
        freshness=fx_service.freshness(snapshot).value,
        stale_after_minutes=settings.fx_stale_after_minutes,
        snapshot=_fx_out(snapshot) if snapshot else None,
        last_attempt=FxAttemptOut.model_validate(attempt) if attempt else None,
    )


@router.get("/fx/history", response_model=FxHistoryOut)
def fx_history(
    db: DbSession,
    _guard: Annotated[User, Depends(require(Permission.TARIFF_READ))],
    limit: int = Query(default=50, ge=1, le=500),
) -> FxHistoryOut:
    snapshots = db.scalars(
        select(FxRateSnapshot)
        .where(
            FxRateSnapshot.bank == fx_service.VIETCOMBANK_KEY,
            FxRateSnapshot.currency == fx_service.CURRENCY,
        )
        .order_by(FxRateSnapshot.retrieved_at.desc(), FxRateSnapshot.id.desc())
        .limit(limit)
    ).all()
    attempts = db.scalars(
        select(FxSyncAttempt)
        .where(
            FxSyncAttempt.bank == fx_service.VIETCOMBANK_KEY,
            FxSyncAttempt.currency == fx_service.CURRENCY,
        )
        .order_by(FxSyncAttempt.attempted_at.desc(), FxSyncAttempt.id.desc())
        .limit(limit)
    ).all()
    return FxHistoryOut(
        snapshots=[_fx_out(s) for s in snapshots],
        attempts=[FxAttemptOut.model_validate(a) for a in attempts],
    )
