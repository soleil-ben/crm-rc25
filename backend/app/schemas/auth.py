"""Authentication, staff, and settings schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.core.enums import Role
from app.schemas.common import ApiModel


class LoginRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    email: EmailStr
    password: str = Field(min_length=1, max_length=256)


class SessionUser(ApiModel):
    id: int
    email: str
    full_name: str
    role: str
    initials: str
    timezone: str
    locale: str
    last_login_at: datetime | None = None


class LoginResponse(BaseModel):
    user: SessionUser
    permissions: list[str]
    csrf_token: str


class MeResponse(BaseModel):
    user: SessionUser
    permissions: list[str]
    environment: str
    is_demo_environment: bool


class CsrfResponse(BaseModel):
    csrf_token: str


class StaffCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    email: EmailStr
    full_name: str = Field(min_length=1, max_length=200)
    password: str = Field(min_length=12, max_length=256)
    role: Role = Role.OPERATIONS


class StaffUpdate(BaseModel):
    full_name: str | None = Field(default=None, min_length=1, max_length=200)
    role: Role | None = None
    is_active: bool | None = None


class StaffOut(ApiModel):
    id: int
    email: str
    full_name: str
    role: str
    is_active: bool
    timezone: str
    last_login_at: datetime | None
    created_at: datetime


class SettingsOut(ApiModel):
    brand_name: str
    legal_entity_name: str
    office_timezone: str
    default_currency: str
    tracking_base_url: str
    lifecycle_new_days: int
    lifecycle_active_days: int
    lifecycle_at_risk_days: int
    rule_first_delivery_follow_up_enabled: bool
    rule_first_delivery_follow_up_days: int
    rule_at_risk_task_enabled: bool
    rule_exception_task_enabled: bool
    is_demo_environment: bool
    lifecycle_definitions: dict[str, str] = {}


class SettingsUpdate(BaseModel):
    office_timezone: str | None = None
    default_currency: str | None = Field(default=None, min_length=3, max_length=3)
    tracking_base_url: str | None = None
    lifecycle_new_days: int | None = Field(default=None, ge=1, le=3650)
    lifecycle_active_days: int | None = Field(default=None, ge=1, le=3650)
    lifecycle_at_risk_days: int | None = Field(default=None, ge=1, le=3650)
    rule_first_delivery_follow_up_enabled: bool | None = None
    rule_first_delivery_follow_up_days: int | None = Field(default=None, ge=0, le=365)
    rule_at_risk_task_enabled: bool | None = None
    rule_exception_task_enabled: bool | None = None


class AuditChangeOut(ApiModel):
    field: str
    old: str | None = None
    new: str | None = None


class AuditEventOut(ApiModel):
    id: int
    occurred_at: datetime
    actor_label: str
    action: str
    entity_type: str
    entity_id: str | None
    summary: str
    detail_json: str | None
    # Derived for the audit screen: a reason *code* and the *names* of the fields that
    # changed. Never a value (``audit_service.audit_display_fields``).
    reason_code: str | None = None
    changed_fields: list[str] = Field(default_factory=list)
    # True when Admin took a decision that is Operations' by default (OD-24, CA-APR-05).
    admin_override: bool = False
    # The reference a suppression was recorded against (UAT round 5). Shape-checked: a
    # ticket or form reference, never an address or prose.
    evidence_reference: str | None = None
    # The old and new values an approved Customer Account change request applied (UAT
    # round 8). Empty for every other row.
    changes: list[AuditChangeOut] = Field(default_factory=list)
