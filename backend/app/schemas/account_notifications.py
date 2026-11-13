"""Customer Account notification schemas (Phase 13F). Customer-facing: an allowlist."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class AccountNotificationItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    milestone: str
    shipment_reference: str | None
    created_at: datetime
    #: pending | sent | not_sent
    state: str


class AccountNotificationsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    channel: str
    #: milestone -> on/off
    preferences: dict[str, bool]
    history: list[AccountNotificationItem]
