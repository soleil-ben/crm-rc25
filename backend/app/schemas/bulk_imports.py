"""Shipment import and legacy history baseline schemas (RC-UAT-21 Phase A, DEC-0230)."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field

from app.schemas.imports import RowIssueOut


class BulkFieldsOut(BaseModel):
    kind: str
    fields: list[dict[str, Any]]
    template_headers: list[str]
    limits: dict[str, int]
    notes: list[str]


class DryRunRowOut(BaseModel):
    row_number: int
    classification: str
    reference: str | None = None
    customer_public_id: str | None = None
    summary: dict[str, Any] = Field(default_factory=dict)
    issues: list[RowIssueOut] = Field(default_factory=list)


class DryRunOut(BaseModel):
    """The result of a dry run. **No business record has been written.**"""

    kind: str
    content_sha256: str
    options: dict[str, Any]
    file_name: str | None = None
    row_count: int
    headers: list[str]
    unmapped_headers: list[str]
    rows: list[DryRunRowOut]
    counts: dict[str, int]
    notes: list[str]
    #: Stable code per note (same order), for a translated rendering in the staff UI.
    note_codes: list[str] = Field(default_factory=list)


class BulkCommitRowOut(BaseModel):
    row_number: int
    outcome: str
    reason_code: str | None = None
    reference: str | None = None
    record_id: int | None = None
    record_label: str | None = None


class BulkCommitOut(BaseModel):
    kind: str
    batch_public_id: str
    created: int
    matched: int
    skipped: int
    rejected: int
    row_count: int
    rows: list[BulkCommitRowOut]


class BaselineOut(BaseModel):
    batch_public_id: str
    file_name: str | None = None
    status: str
    cutoff_date: date | None = None
    row_count: int
    created_count: int
    matched_count: int
    rejected_count: int
    committed_at: datetime
    voided_at: datetime | None = None
    void_reason: str | None = None


class VoidBaselineIn(BaseModel):
    reason: str = Field(min_length=1, max_length=400)
    confirm: bool = False


class LegacyEventOut(BaseModel):
    sequence: int
    event_type: str
    occurred_on: date


class LegacyShipmentOut(BaseModel):
    id: int
    legacy_reference: str
    customer_id: int
    customer_public_id: str
    customer_name: str
    route_group: str
    direction: str
    transport_mode: str
    booked_on: date
    final_status: str
    completed_on: date | None = None
    recipient_name: str | None = None
    recipient_city: str | None = None
    recipient_province_state: str | None = None
    recipient_country_code: str | None = None
    package_count: int | None = None
    total_weight_kg: Decimal | None = None
    contents_description: str | None = None
    notes: str | None = None
    is_voided: bool
    batch_public_id: str | None = None
    #: Always true: the record is history, not an operational shipment.
    is_legacy: bool = True
    events: list[LegacyEventOut] = Field(default_factory=list)
