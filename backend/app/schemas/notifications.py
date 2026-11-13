"""Staff notification schemas (Phase 13F). No address and no message body, by construction."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, StrictBool


class NotificationOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int
    shipment_id: int
    shipment_reference: str | None
    customer_id: int | None
    customer_reference: str | None
    customer_name: str | None
    milestone: str
    channel: str
    language: str
    template_key: str
    status: str
    skip_reason: str | None
    transport: str | None
    attempts: int
    last_error: str | None
    created_at: datetime
    processed_at: datetime | None


class NotificationListOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[NotificationOut]
    total: int


class PreferencesIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: Strict: "yes" or 1 is refused rather than read as on.
    preferences: dict[str, StrictBool]


class PreferencesOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    preferences: dict[str, bool]
