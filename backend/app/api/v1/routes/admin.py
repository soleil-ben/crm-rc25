"""Dashboard, global search, settings, staff administration, audit, and metadata."""

from __future__ import annotations

from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import select

from app.api import presenters
from app.api.deps import (
    CurrentUser,
    DbSession,
    OrgSettings,
    Thresholds,
    client_ip,
    get_org_settings,
    require,
)
from app.core.config import settings as app_settings
from app.core.db import commit_with_retry
from app.core.enums import (
    ROUTE_GROUP_LABELS,
    ConsentBasis,
    ConsentChannel,
    ConsentStatus,
    ContactChannel,
    CustomerCategory,
    LifecycleStatus,
    PreferredLanguage,
    RouteGroup,
    ShippingFrequency,
    ShippingPurpose,
    TaskPriority,
    TaskPurpose,
    TaskStatus,
    value_label,
)
from app.core.permissions import ROLE_LABELS, Permission, permissions_for
from app.core.time_utils import is_known_timezone, utcnow
from app.models import User
from app.schemas.auth import (
    AuditChangeOut,
    AuditEventOut,
    SettingsOut,
    SettingsUpdate,
    StaffCreate,
    StaffOut,
    StaffUpdate,
)
from app.schemas.common import Page
from app.schemas.customer import CustomerListItem
from app.schemas.engagement import DashboardSummaryOut
from app.services import (
    audit_service,
    auth_service,
    customer_service,
    dashboard_service,
    staff_grant_service,
    task_service,
)
from app.services.activity_service import LifecycleThresholds
from app.services.errors import NotFoundError, ValidationError

router = APIRouter(tags=["operations"])


# --- Dashboard ------------------------------------------------------------


@router.get("/dashboard/summary", response_model=DashboardSummaryOut)
def dashboard_summary(
    db: DbSession,
    org: OrgSettings,
    user: CurrentUser,
    _guard: Annotated[User, Depends(require(Permission.DASHBOARD_READ))],
    days: int = Query(default=30, ge=1, le=365),
) -> DashboardSummaryOut:
    period_end = utcnow()
    period_start = period_end - timedelta(days=days)
    summary = dashboard_service.build_summary(
        db, org=org, period_start=period_start, period_end=period_end, viewer_user_id=user.id
    )
    commit_with_retry(db)
    return DashboardSummaryOut(**summary.to_dict())


# --- Global search --------------------------------------------------------


@router.get("/search", response_model=Page[CustomerListItem])
def global_search(
    db: DbSession,
    thresholds: Thresholds,
    _guard: Annotated[User, Depends(require(Permission.CUSTOMER_READ))],
    q: str = Query(min_length=1, max_length=120),
    limit: int = Query(default=8, ge=1, le=25),
) -> Page[CustomerListItem]:
    """Top-bar search across name, customer ID, email, and phone (Design.md section 4).

    Barcode scanners type into this field, so an exact identifier match is prioritized.
    """
    exact = customer_service.get_customer_by_public_id(db, q)
    rows = customer_service.search_customers_quick(db, q, limit=limit)
    if exact is not None:
        rows = [exact] + [row for row in rows if row.id != exact.id]
    items = presenters.customer_list_items(db, rows[:limit], thresholds)
    return Page[CustomerListItem](items=items, total=len(items), limit=limit, offset=0)


# --- Settings -------------------------------------------------------------


def _settings_out(org, thresholds: LifecycleThresholds) -> SettingsOut:
    payload = SettingsOut.model_validate(org)
    payload.lifecycle_definitions = thresholds.describe()
    return payload


@router.get("/settings", response_model=SettingsOut)
def read_settings(
    db: DbSession,
    org: OrgSettings,
    thresholds: Thresholds,
    _guard: Annotated[User, Depends(require(Permission.SETTINGS_READ))],
) -> SettingsOut:
    commit_with_retry(db)
    return _settings_out(org, thresholds)


@router.patch("/settings", response_model=SettingsOut)
def update_settings(
    payload: SettingsUpdate,
    request: Request,
    db: DbSession,
    user: Annotated[User, Depends(require(Permission.SETTINGS_MANAGE))],
) -> SettingsOut:
    org = get_org_settings(db)
    data = payload.model_dump(exclude_unset=True)
    # An unresolvable timezone is refused here rather than stored. Everything downstream
    # cuts report periods and renders operational timestamps in this zone, and a value
    # nothing can resolve would either raise on every page or, worse, silently become UTC
    # while still being labelled Toronto (DEC-0076).
    if data.get("office_timezone") is not None and not is_known_timezone(data["office_timezone"]):
        raise ValidationError(
            f"{data['office_timezone']!r} is not a recognized IANA timezone name. "
            "Use a name such as America/Toronto or Asia/Ho_Chi_Minh.",
            field="office_timezone",
        )
    for key, value in data.items():
        setattr(org, key, value)
    if not (org.lifecycle_new_days <= org.lifecycle_active_days <= org.lifecycle_at_risk_days):
        raise ValidationError(
            "Lifecycle thresholds must increase: new days <= active days <= at-risk days.",
            field="lifecycle_active_days",
        )
    audit_service.record_audit(
        db,
        action="settings.update",
        entity_type="organization_settings",
        entity_id=org.id,
        summary="Updated organization settings",
        actor=user,
        ip_address=client_ip(request),
        detail={"changed": sorted(data.keys())},
    )
    commit_with_retry(db)
    return _settings_out(org, LifecycleThresholds.from_settings(org))


@router.post("/settings/run-retention-rules")
def run_retention_rules(
    db: DbSession,
    user: Annotated[User, Depends(require(Permission.SETTINGS_MANAGE))],
) -> dict:
    """Create internal retention tasks. This never sends a customer message."""
    org = get_org_settings(db)
    created = task_service.run_retention_rules(db, org)
    commit_with_retry(db)
    return {"created": created, "note": "Internal follow-up tasks only. No messages were sent."}


# --- Staff ----------------------------------------------------------------


@router.get("/staff", response_model=list[StaffOut])
def list_staff(
    db: DbSession, _guard: Annotated[User, Depends(require(Permission.STAFF_READ))]
) -> list[StaffOut]:
    rows = db.scalars(select(User).order_by(User.full_name.asc())).all()
    return [StaffOut.model_validate(row) for row in rows]


@router.get("/staff/assignable", response_model=list[StaffOut])
def list_assignable_staff(
    db: DbSession, _guard: Annotated[User, Depends(require(Permission.TASK_READ))]
) -> list[StaffOut]:
    """Active staff who can own records or receive tasks. Visible to any signed-in role."""
    rows = db.scalars(
        select(User).where(User.is_active.is_(True)).order_by(User.full_name.asc())
    ).all()
    return [StaffOut.model_validate(row) for row in rows]


@router.post("/staff", response_model=StaffOut, status_code=201)
def create_staff(
    payload: StaffCreate,
    db: DbSession,
    user: Annotated[User, Depends(require(Permission.STAFF_MANAGE))],
) -> StaffOut:
    created = auth_service.create_user(
        db,
        email=payload.email,
        full_name=payload.full_name,
        password=payload.password,
        role=payload.role.value,
        actor=user,
    )
    commit_with_retry(db)
    return StaffOut.model_validate(created)


@router.patch("/staff/{user_id}", response_model=StaffOut)
def update_staff(
    user_id: int,
    payload: StaffUpdate,
    db: DbSession,
    user: Annotated[User, Depends(require(Permission.STAFF_MANAGE))],
) -> StaffOut:
    target = db.get(User, user_id)
    if target is None:
        raise NotFoundError("Staff account not found.")
    if payload.full_name is not None:
        target.full_name = payload.full_name
    if payload.role is not None and payload.role.value != target.role:
        if target.id == user.id:
            raise ValidationError("You cannot change your own role.", field="role")
        auth_service.change_role(db, target, role=payload.role.value, actor=user)
    if payload.is_active is not None and payload.is_active != target.is_active:
        if target.id == user.id:
            raise ValidationError("You cannot deactivate your own account.", field="is_active")
        auth_service.set_user_active(db, target, is_active=payload.is_active, actor=user)
    commit_with_retry(db)
    return StaffOut.model_validate(target)


# --- Per-account permission grants (DEC-0268) -----------------------------


def _grants_out(db) -> dict:
    return {
        permission: [
            {"user_id": u.id, "full_name": u.full_name, "email": u.email, "role": u.role,
             "is_active": u.is_active}
            for u in staff_grant_service.holders(db, permission)
        ]
        for permission in staff_grant_service.GRANTABLE
    }  # fmt: skip


@router.get("/staff/permission-grants")
def list_permission_grants(
    db: DbSession, _guard: Annotated[User, Depends(require(Permission.STAFF_READ))]
) -> dict:
    """Who holds each grantable permission (today ``tariff:approve``: confirm or roll back a
    Kango rate sheet)."""
    return _grants_out(db)


@router.post("/staff/{user_id}/grants/{permission}")
def grant_permission(
    user_id: int,
    permission: str,
    db: DbSession,
    user: Annotated[User, Depends(require(Permission.STAFF_MANAGE))],
) -> dict:
    staff_grant_service.grant(db, staff_grant_service.get_user(db, user_id), permission, actor=user)
    commit_with_retry(db)
    return _grants_out(db)


@router.delete("/staff/{user_id}/grants/{permission}")
def revoke_permission(
    user_id: int,
    permission: str,
    db: DbSession,
    user: Annotated[User, Depends(require(Permission.STAFF_MANAGE))],
) -> dict:
    staff_grant_service.revoke(
        db, staff_grant_service.get_user(db, user_id), permission, actor=user
    )
    commit_with_retry(db)
    return _grants_out(db)


# --- Audit ----------------------------------------------------------------


@router.get("/audit", response_model=Page[AuditEventOut])
def list_audit(
    db: DbSession,
    _guard: Annotated[User, Depends(require(Permission.AUDIT_READ))],
    entity_type: str | None = None,
    entity_id: str | None = None,
    action: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> Page[AuditEventOut]:
    rows, total = audit_service.list_audit_events(
        db, entity_type=entity_type, entity_id=entity_id, action=action, limit=limit, offset=offset
    )
    items = []
    for row in rows:
        derived = audit_service.audit_display_fields(row.detail_json)
        if derived["evidence_reference"] is None:
            derived["evidence_reference"] = audit_service.suppression_evidence_fallback(db, row)
        derived["changes"] = [AuditChangeOut(**change) for change in derived["changes"]]
        items.append(AuditEventOut.model_validate(row).model_copy(update=derived))
    return Page[AuditEventOut](
        items=items,
        total=total,
        limit=limit,
        offset=offset,
    )


# --- Metadata -------------------------------------------------------------


def _options(enum_cls) -> list[dict]:
    """English default labels; the frontend keeps its own translation catalogue."""
    return [{"value": member.value, "label": value_label(member.value)} for member in enum_cls]


@router.get("/meta/enums")
def meta_enums(user: CurrentUser) -> dict:
    """Enumerations and role permissions the frontend renders.

    Labels here are English defaults; the frontend keeps its own translation catalogue so
    the internal UI stays localization-ready (CRM.md section 14).
    """
    return {
        "route_groups": [
            {"value": route.value, "label": ROUTE_GROUP_LABELS[route.value]} for route in RouteGroup
        ],
        "preferred_languages": _options(PreferredLanguage),
        "customer_categories": _options(CustomerCategory),
        "shipping_purposes": _options(ShippingPurpose),
        "shipping_frequencies": _options(ShippingFrequency),
        "lifecycle_statuses": _options(LifecycleStatus),
        "contact_channels": _options(ContactChannel),
        "task_statuses": _options(TaskStatus),
        "task_priorities": _options(TaskPriority),
        "task_purposes": _options(TaskPurpose),
        "consent_channels": _options(ConsentChannel),
        "consent_statuses": _options(ConsentStatus),
        "consent_bases": _options(ConsentBasis),
        "roles": [{"value": value, "label": label} for value, label in ROLE_LABELS.items()],
        "your_permissions": sorted(permissions_for(user.role)),
        "environment": app_settings.environment,
    }
