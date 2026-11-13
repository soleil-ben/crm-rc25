"""Schemas for the Admin quote soft delete and Settings > Retention (RC-UAT-21 Phase D)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ReasonIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1, max_length=400)


class QuoteDeletedOut(BaseModel):
    deleted_at: datetime
    deleted_by: str | None
    reason: str


class QuoteHistoryRowOut(BaseModel):
    quote_version_id: int
    version: int
    status: str
    created_at: datetime
    finalized_at: datetime | None
    total_revenue_cad: Decimal | None
    offer_status: str | None
    expired: bool
    deletable: bool
    refusal: str | None
    refusal_message: str | None
    deleted: QuoteDeletedOut | None


class QuoteHistoryOut(BaseModel):
    shipment_id: int
    include_deleted: bool
    min_age_days: int
    items: list[QuoteHistoryRowOut]


class RetentionSettingsOut(BaseModel):
    enabled: bool
    enabled_at: datetime | None
    enabled_by: str | None
    quote_delete_min_age_days: int
    batch_size: int
    confirmation_phrase: str
    updated_at: datetime | None
    updated_by: str | None


class RetentionSettingsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool | None = None
    confirmation: str | None = Field(default=None, max_length=60)
    quote_delete_min_age_days: int | None = None
    batch_size: int | None = None
    reason: str | None = Field(default=None, max_length=400)


class RetentionPolicyOut(BaseModel):
    record_class: str
    label: str
    description: str
    enabled: bool
    period_days: int | None
    action: str
    allowed_actions: list[str]
    last_run_at: datetime | None
    last_run_affected: int | None
    updated_at: datetime | None
    updated_by: str | None


class RetentionPolicyIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool | None = None
    #: ``null`` sets the period back to undecided.
    period_days: int | None = None
    action: str | None = None
    reason: str | None = Field(default=None, max_length=400)


class RetentionRunOut(BaseModel):
    id: int
    dry_run: bool
    trigger: str
    status: str
    counts: dict[str, Any]
    error: str | None
    started_at: datetime
    finished_at: datetime | None


class RetentionOverviewOut(BaseModel):
    settings: RetentionSettingsOut
    policies: list[RetentionPolicyOut]
    runs: list[RetentionRunOut]
