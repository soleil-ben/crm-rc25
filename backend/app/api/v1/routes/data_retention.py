"""Admin quote soft delete and Settings > Retention (RC-UAT-21 Phase D, DEC-0233).

Every route here is Admin's alone: ``quote:delete`` and ``retention:manage`` are in no role
set, and Admin holds every permission. Staff routes only; nothing here is on the public or
Customer Account routers. The retention worker itself is never started from here: the only
run an Admin can start is a **dry run**, which changes nothing.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.api.deps import DbSession, require
from app.core.db import run_unit_with_retry
from app.core.permissions import Permission
from app.models import User
from app.schemas.rc21_retention import (
    QuoteHistoryOut,
    QuoteHistoryRowOut,
    ReasonIn,
    RetentionOverviewOut,
    RetentionPolicyIn,
    RetentionPolicyOut,
    RetentionRunOut,
    RetentionSettingsIn,
    RetentionSettingsOut,
)
from app.services import booking_service, data_retention_service, quote_deletion_service

router = APIRouter(tags=["data-retention"])

P = Permission
QuoteDeleter = Annotated[User, Depends(require(P.SHIPMENT_READ, P.FINANCIAL_READ, P.QUOTE_DELETE))]
RetentionManager = Annotated[User, Depends(require(P.RETENTION_MANAGE))]


# --- Quote soft delete ---------------------------------------------------------------------------


def _history(db, shipment, include_deleted: bool) -> QuoteHistoryOut:
    return QuoteHistoryOut(
        shipment_id=shipment.id,
        include_deleted=include_deleted,
        min_age_days=quote_deletion_service.min_age_days(db),
        items=[
            QuoteHistoryRowOut(**row)
            for row in quote_deletion_service.history(db, shipment, include_deleted=include_deleted)
        ],
    )


@router.get("/shipments/{shipment_id}/quote-history", response_model=QuoteHistoryOut)
def quote_history(
    shipment_id: int,
    db: DbSession,
    _user: QuoteDeleter,
    include_deleted: Annotated[bool, Query()] = False,
) -> QuoteHistoryOut:
    """Every version with whether it may be deleted (and why not); deleted ones on request."""
    shipment = booking_service.get_shipment(db, shipment_id)
    return _history(db, shipment, include_deleted)


@router.post("/quote-versions/{version_id}/delete", response_model=QuoteHistoryOut)
def delete_quote_version(
    version_id: int, payload: ReasonIn, db: DbSession, user: QuoteDeleter
) -> QuoteHistoryOut:
    def work():
        version = quote_deletion_service.get_version(db, version_id)
        quote_deletion_service.soft_delete(db, version, reason=payload.reason, actor=user)
        return version.shipment_id

    shipment_id = run_unit_with_retry(db, work)
    return _history(db, booking_service.get_shipment(db, shipment_id), True)


@router.post("/quote-versions/{version_id}/restore", response_model=QuoteHistoryOut)
def restore_quote_version(
    version_id: int, payload: ReasonIn, db: DbSession, user: QuoteDeleter
) -> QuoteHistoryOut:
    def work():
        version = quote_deletion_service.get_version(db, version_id)
        quote_deletion_service.restore(db, version, reason=payload.reason, actor=user)
        return version.shipment_id

    shipment_id = run_unit_with_retry(db, work)
    return _history(db, booking_service.get_shipment(db, shipment_id), True)


# --- Settings > Retention ------------------------------------------------------------------------


def _overview(db) -> RetentionOverviewOut:
    return RetentionOverviewOut(
        settings=RetentionSettingsOut(**data_retention_service.settings_view(db)),
        policies=[
            RetentionPolicyOut(**data_retention_service.policy_view(db, p))
            for p in data_retention_service.read_policies(db)
        ],
        runs=[
            RetentionRunOut(**data_retention_service.run_view(r))
            for r in data_retention_service.recent_runs(db)
        ],
    )


@router.get("/admin/data-retention", response_model=RetentionOverviewOut)
def read_retention(db: DbSession, _user: RetentionManager) -> RetentionOverviewOut:
    return _overview(db)


@router.patch("/admin/data-retention/settings", response_model=RetentionOverviewOut)
def update_retention_settings(
    payload: RetentionSettingsIn, db: DbSession, user: RetentionManager
) -> RetentionOverviewOut:
    changes = payload.model_dump(exclude_unset=True)

    def work():
        data_retention_service.update_settings(db, changes, actor=user)

    run_unit_with_retry(db, work)
    return _overview(db)


@router.patch("/admin/data-retention/policies/{record_class}", response_model=RetentionPolicyOut)
def update_retention_policy(
    record_class: str, payload: RetentionPolicyIn, db: DbSession, user: RetentionManager
) -> RetentionPolicyOut:
    changes = payload.model_dump(exclude_unset=True)

    def work():
        return data_retention_service.update_policy(db, record_class, changes, actor=user)

    row = run_unit_with_retry(db, work)
    return RetentionPolicyOut(**data_retention_service.policy_view(db, row))


@router.post("/admin/data-retention/dry-run", response_model=RetentionRunOut)
def retention_dry_run(db: DbSession, user: RetentionManager) -> RetentionRunOut:
    """Counts per record class of what a real run would change. Nothing is changed."""

    def work():
        return data_retention_service.dry_run(db, trigger="admin", actor=user)

    row = run_unit_with_retry(db, work)
    return RetentionRunOut(**data_retention_service.run_view(row))
