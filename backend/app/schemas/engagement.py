"""Interaction, task, consent, segment, and dashboard schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.core.enums import (
    ConsentBasis,
    ConsentChannel,
    ConsentStatus,
    ContactChannel,
    InteractionDirection,
    InteractionVisibility,
    TaskPriority,
    TaskPurpose,
    TaskStatus,
)
from app.schemas.common import ApiModel
from app.schemas.customer import StaffSummary

# --- Interactions ---------------------------------------------------------


class InteractionCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    occurred_at: datetime | None = None
    channel: ContactChannel = ContactChannel.PHONE
    direction: InteractionDirection = InteractionDirection.OUTBOUND
    subject: str = Field(min_length=1, max_length=200)
    body: str | None = None
    outcome: str | None = Field(default=None, max_length=200)
    shipment_id: int | None = None


class InteractionOut(ApiModel):
    id: int
    customer_id: int
    shipment_id: int | None
    task_id: int | None
    occurred_at: datetime
    channel: str
    direction: str
    subject: str
    body: str | None
    outcome: str | None
    visibility: str = InteractionVisibility.INTERNAL
    is_follow_up_completion: bool
    author: StaffSummary | None = None
    created_at: datetime


# --- Follow-up tasks ------------------------------------------------------


class TaskCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    customer_id: int
    subject: str = Field(min_length=1, max_length=200)
    detail: str | None = None
    purpose: TaskPurpose = TaskPurpose.GENERAL
    priority: TaskPriority = TaskPriority.NORMAL
    status: TaskStatus = TaskStatus.SCHEDULED
    due_at: datetime | None = None
    assignee_user_id: int | None = None
    shipment_id: int | None = None


class TaskUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    subject: str | None = Field(default=None, min_length=1, max_length=200)
    detail: str | None = None
    purpose: TaskPurpose | None = None
    priority: TaskPriority | None = None
    status: TaskStatus | None = None
    due_at: datetime | None = None
    assignee_user_id: int | None = None
    shipment_id: int | None = None
    cancelled_reason: str | None = Field(default=None, max_length=400)


class NextTaskRequest(BaseModel):
    subject: str = Field(min_length=1, max_length=200)
    due_at: datetime | None = None
    assignee_user_id: int | None = None
    purpose: TaskPurpose | None = None
    priority: TaskPriority = TaskPriority.NORMAL
    detail: str | None = None


class TaskCompleteRequest(BaseModel):
    outcome: str = Field(min_length=1, max_length=400)
    completed_at: datetime | None = None
    channel: ContactChannel = ContactChannel.PHONE
    log_interaction: bool = True
    next_task: NextTaskRequest | None = None


class TaskCustomerSummary(BaseModel):
    id: int
    public_id: str
    full_name: str
    preferred_language: str


class TaskOut(ApiModel):
    id: int
    customer: TaskCustomerSummary
    shipment_id: int | None
    subject: str
    detail: str | None
    purpose: str
    priority: str
    status: str
    due_at: datetime | None
    is_overdue: bool
    assignee: StaffSummary | None = None
    created_by: StaffSummary | None = None
    completed_at: datetime | None
    outcome: str | None
    cancelled_reason: str | None
    source_rule: str | None
    created_at: datetime


class TaskCompleteResponse(BaseModel):
    task: TaskOut
    next_task: TaskOut | None = None


# --- Consent --------------------------------------------------------------


class ConsentEventCreate(BaseModel):
    channel: ConsentChannel
    status: ConsentStatus
    basis: ConsentBasis = ConsentBasis.NOT_RECORDED
    address_value: str | None = None
    obtained_at: datetime | None = None
    expires_at: datetime | None = None
    source: str | None = Field(default=None, max_length=120)
    evidence_reference: str | None = Field(default=None, max_length=255)
    note: str | None = Field(default=None, max_length=400)


class ConsentEventOut(ApiModel):
    id: int
    channel: str
    address_value: str
    status: str
    basis: str
    obtained_at: datetime | None
    withdrawn_at: datetime | None
    expires_at: datetime | None
    source: str | None
    evidence_reference: str | None
    note: str | None
    recorded_at: datetime
    recorded_by: StaffSummary | None = None
    #: ``customer_account:CA-...`` when the customer recorded it from their own account
    #: (UAT round 8). Null for a staff, import or seeded row.
    recorded_by_account: str | None = None


class ConsentStateOut(BaseModel):
    channel: str
    address_value: str | None
    status: str
    basis: str
    obtained_at: datetime | None
    withdrawn_at: datetime | None
    expires_at: datetime | None
    recorded_at: datetime | None
    source: str | None
    is_suppressed: bool
    suppression_reason: str | None
    is_marketing_eligible: bool


class ConsentOverview(BaseModel):
    states: list[ConsentStateOut]
    history: list[ConsentEventOut]
    do_not_contact: bool
    note: str = (
        "Operational messages about a shipment are separate from promotional consent. "
        "A shipment, referral, or delivery does not create marketing consent."
    )


class SuppressionCreateRequest(BaseModel):
    """Suppress a customer's address on one channel (UAT round 4).

    The evidence reference and the reason are both required: a block on contacting
    somebody should say where the request came from and why.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    channel: ConsentChannel = ConsentChannel.EMAIL
    evidence_reference: str = Field(min_length=3, max_length=255)
    reason: str = Field(min_length=3, max_length=200)


class SuppressionReleaseRequest(BaseModel):
    channel: ConsentChannel
    address_value: str
    reason: str = Field(min_length=3, max_length=200)


# --- Segments -------------------------------------------------------------


class SegmentDefinitionIn(BaseModel):
    match: str = "all"
    conditions: list[dict[str, Any]]


class SegmentCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=400)
    definition: SegmentDefinitionIn
    is_shared: bool = True


class SegmentUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=400)
    definition: SegmentDefinitionIn | None = None
    is_shared: bool | None = None


class SegmentPreviewRequest(BaseModel):
    definition: SegmentDefinitionIn
    limit: int = Field(default=10, ge=1, le=50)


class SegmentOut(ApiModel):
    id: int
    slug: str
    name: str
    description: str | None
    definition: dict[str, Any]
    plain_language: str
    member_count: int
    marketing_eligible_email_count: int | None = None
    is_system: bool
    is_shared: bool
    owner: StaffSummary | None = None
    created_at: datetime
    updated_at: datetime
    eligibility_note: str = (
        "The member count is the full segment. A marketing export additionally requires "
        "eligible consent and no suppression, so the eligible count is usually smaller."
    )


class SegmentPreviewResponse(BaseModel):
    member_count: int
    plain_language: str
    sample: list[dict[str, Any]]
    marketing_eligible_email_count: int | None = None


# --- Dashboard ------------------------------------------------------------


class KpiCardOut(BaseModel):
    key: str
    label: str
    value: int
    definition: str
    link: str
    scope: str
    comparison_value: int | None
    comparison_label: str | None
    tone: str


class DashboardSummaryOut(BaseModel):
    period_start: datetime
    period_end: datetime
    previous_period_available: bool
    kpis: list[KpiCardOut]
    queues: list[KpiCardOut]
    shipment_trend: list[dict[str, Any]]
    route_mix: list[dict[str, Any]]
    lifecycle_mix: list[dict[str, Any]]
    follow_up_queue: list[dict[str, Any]]
    recent_customers: list[dict[str, Any]]
    repeat_shipper_share: dict[str, Any] | None
    data_notes: list[str]


# --- Service issues -------------------------------------------------------


class ServiceIssueCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    detail: str | None = None
    shipment_id: int | None = None


class ServiceIssueOut(ApiModel):
    id: int
    customer_id: int
    shipment_id: int | None
    title: str
    detail: str | None
    status: str
    opened_at: datetime
    resolved_at: datetime | None
