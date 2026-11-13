"""Saved dynamic segment routes."""

from __future__ import annotations

import re
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import select

from app.api import presenters
from app.api.deps import CurrentUser, DbSession, Thresholds, client_ip, has, require
from app.core.db import commit_with_retry
from app.core.permissions import Permission
from app.models import SavedSegment, User
from app.schemas.common import OkResponse, Page
from app.schemas.customer import CustomerListItem
from app.schemas.engagement import (
    SegmentCreate,
    SegmentOut,
    SegmentPreviewRequest,
    SegmentPreviewResponse,
    SegmentUpdate,
)
from app.services import audit_service, segment_service
from app.services.errors import ConflictError, NotFoundError

router = APIRouter(prefix="/segments", tags=["segments"])


def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")
    return slug or "segment"


def _unique_slug(db, name: str, exclude_id: int | None = None) -> str:
    base = _slugify(name)
    slug = base
    counter = 2
    while True:
        existing = db.scalar(select(SavedSegment).where(SavedSegment.slug == slug))
        if existing is None or existing.id == exclude_id:
            return slug
        slug = f"{base}-{counter}"
        counter += 1


def _load_segment(db, segment_id: int) -> SavedSegment:
    segment = db.get(SavedSegment, segment_id)
    if segment is None:
        raise NotFoundError("Segment not found.")
    return segment


@router.get("/fields")
def segment_fields(
    _user: Annotated[User, Depends(require(Permission.SEGMENT_READ))],
) -> dict:
    """Field/operator catalogue driving the segment builder UI."""
    return {
        "fields": segment_service.field_catalog(),
        "note": (
            "Marketing eligibility is not a filter field. Consent and suppression are applied "
            "as a separate export filter with their own count."
        ),
    }


@router.get("", response_model=list[SegmentOut])
def list_segments(
    db: DbSession,
    thresholds: Thresholds,
    user: CurrentUser,
    _guard: Annotated[User, Depends(require(Permission.SEGMENT_READ))],
) -> list[SegmentOut]:
    rows = db.scalars(
        select(SavedSegment).order_by(SavedSegment.is_system.desc(), SavedSegment.name.asc())
    ).all()
    include_marketing = has(user, Permission.EXPORT_MARKETING_SEGMENT)
    return [
        presenters.segment_out(db, segment, thresholds, include_marketing_count=include_marketing)
        for segment in rows
    ]


@router.post("/preview", response_model=SegmentPreviewResponse)
def preview_segment(
    payload: SegmentPreviewRequest,
    db: DbSession,
    thresholds: Thresholds,
    user: CurrentUser,
    _guard: Annotated[User, Depends(require(Permission.SEGMENT_READ))],
) -> SegmentPreviewResponse:
    definition = segment_service.validate_definition(payload.definition.model_dump())
    members = segment_service.list_members(db, definition, thresholds, limit=payload.limit)
    items = presenters.customer_list_items(db, members, thresholds)
    tag_names = segment_service.resolve_tag_names(db)
    staff_names = {row.id: row.full_name for row in db.scalars(select(User)).all()}
    return SegmentPreviewResponse(
        member_count=segment_service.count_members(db, definition, thresholds),
        plain_language=segment_service.describe(definition, tag_names, staff_names),
        sample=[item.model_dump() for item in items],
        marketing_eligible_email_count=(
            segment_service.marketing_eligible_count(db, definition, thresholds)
            if has(user, Permission.EXPORT_MARKETING_SEGMENT)
            else None
        ),
    )


@router.post("", response_model=SegmentOut, status_code=201)
def create_segment(
    payload: SegmentCreate,
    request: Request,
    db: DbSession,
    thresholds: Thresholds,
    user: Annotated[User, Depends(require(Permission.SEGMENT_WRITE))],
) -> SegmentOut:
    definition = segment_service.validate_definition(payload.definition.model_dump())
    segment = SavedSegment(
        slug=_unique_slug(db, payload.name),
        name=payload.name,
        description=payload.description,
        definition_json=segment_service.dump_definition(definition),
        is_shared=payload.is_shared,
        owner_user_id=user.id,
    )
    db.add(segment)
    db.flush()
    audit_service.record_audit(
        db,
        action="segment.create",
        entity_type="saved_segment",
        entity_id=segment.id,
        summary=f"Created segment '{segment.name}'",
        actor=user,
        ip_address=client_ip(request),
    )
    commit_with_retry(db)
    return presenters.segment_out(
        db,
        segment,
        thresholds,
        include_marketing_count=has(user, Permission.EXPORT_MARKETING_SEGMENT),
    )


@router.get("/{segment_id}", response_model=SegmentOut)
def get_segment(
    segment_id: int,
    db: DbSession,
    thresholds: Thresholds,
    user: CurrentUser,
    _guard: Annotated[User, Depends(require(Permission.SEGMENT_READ))],
) -> SegmentOut:
    segment = _load_segment(db, segment_id)
    return presenters.segment_out(
        db,
        segment,
        thresholds,
        include_marketing_count=has(user, Permission.EXPORT_MARKETING_SEGMENT),
    )


@router.patch("/{segment_id}", response_model=SegmentOut)
def update_segment(
    segment_id: int,
    payload: SegmentUpdate,
    request: Request,
    db: DbSession,
    thresholds: Thresholds,
    user: Annotated[User, Depends(require(Permission.SEGMENT_WRITE))],
) -> SegmentOut:
    segment = _load_segment(db, segment_id)
    if segment.is_system:
        raise ConflictError(
            "Built-in segments cannot be edited. Use 'Save as copy' to create your own version."
        )
    if payload.name is not None:
        segment.name = payload.name
        segment.slug = _unique_slug(db, payload.name, exclude_id=segment.id)
    if payload.description is not None:
        segment.description = payload.description
    if payload.definition is not None:
        definition = segment_service.validate_definition(payload.definition.model_dump())
        segment.definition_json = segment_service.dump_definition(definition)
    if payload.is_shared is not None:
        segment.is_shared = payload.is_shared

    audit_service.record_audit(
        db,
        action="segment.update",
        entity_type="saved_segment",
        entity_id=segment.id,
        summary=f"Updated segment '{segment.name}'",
        actor=user,
        ip_address=client_ip(request),
    )
    commit_with_retry(db)
    return presenters.segment_out(
        db,
        segment,
        thresholds,
        include_marketing_count=has(user, Permission.EXPORT_MARKETING_SEGMENT),
    )


@router.delete("/{segment_id}", response_model=OkResponse)
def delete_segment(
    segment_id: int,
    request: Request,
    db: DbSession,
    user: Annotated[User, Depends(require(Permission.SEGMENT_WRITE))],
) -> OkResponse:
    segment = _load_segment(db, segment_id)
    if segment.is_system:
        raise ConflictError("Built-in segments cannot be deleted.")
    name = segment.name
    db.delete(segment)
    audit_service.record_audit(
        db,
        action="segment.delete",
        entity_type="saved_segment",
        entity_id=segment_id,
        summary=f"Deleted segment '{name}'",
        actor=user,
        ip_address=client_ip(request),
    )
    commit_with_retry(db)
    return OkResponse(message="Segment deleted.")


@router.get("/{segment_id}/members", response_model=Page[CustomerListItem])
def segment_members(
    segment_id: int,
    db: DbSession,
    thresholds: Thresholds,
    _user: Annotated[User, Depends(require(Permission.SEGMENT_READ))],
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> Page[CustomerListItem]:
    segment = _load_segment(db, segment_id)
    definition = segment_service.load_definition(segment.definition_json)
    members = segment_service.list_members(db, definition, thresholds, limit=limit, offset=offset)
    return Page[CustomerListItem](
        items=presenters.customer_list_items(db, members, thresholds),
        total=segment_service.count_members(db, definition, thresholds),
        limit=limit,
        offset=offset,
    )
