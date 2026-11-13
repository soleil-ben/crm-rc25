"""Milestone notifications (Phase 13F): per-customer preferences and the outbox.

Two new tables; nothing existing is altered (DEC-0181).

* ``notification_preferences`` -- one row per customer and milestone the customer (or staff on
  their behalf) has set. No row means the default (on, OD-72 opt-out model).
* ``notification_outbox`` -- one row per (shipment, milestone, template version): the dedup
  key makes a repeated or fanned-out milestone notify once. It records what was decided and
  why (sent through the test transport, or skipped: opted out, suppressed, no address), with
  attempts and a bounded error for a retry. **No email address and no body are stored**: the
  address is read from the customer when the message is handed to the transport, and the
  body is the catalogue's.

Email only for now (a mobile app later, OD-72); the transport is the account email seam,
which has no production implementation, so nothing leaves the system (test capture only).
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class NotificationPreference(Base):
    __tablename__ = "notification_preferences"
    __table_args__ = (
        UniqueConstraint("customer_id", "milestone", name="uq_notification_preferences_milestone"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    customer_id: Mapped[int] = mapped_column(
        ForeignKey("customers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    #: received | in_transit | out_for_delivery | delivered
    milestone: Mapped[str] = mapped_column(String(24), nullable=False)
    enabled: Mapped[bool] = mapped_column(nullable=False)
    #: account | staff
    updated_via: Mapped[str] = mapped_column(String(10), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class NotificationOutbox(Base):
    __tablename__ = "notification_outbox"
    __table_args__ = (Index("ix_notification_outbox_status_created", "status", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    #: ``{shipment_id}:{milestone}:{template_version}`` -- one notification per milestone.
    dedup_key: Mapped[str] = mapped_column(String(80), nullable=False, unique=True)
    shipment_id: Mapped[int] = mapped_column(
        ForeignKey("shipments.id", ondelete="CASCADE"), nullable=False, index=True
    )
    customer_id: Mapped[int | None] = mapped_column(
        ForeignKey("customers.id", ondelete="SET NULL"), nullable=True, index=True
    )
    event_id: Mapped[int | None] = mapped_column(
        ForeignKey("shipment_events.id", ondelete="SET NULL"), nullable=True
    )
    milestone: Mapped[str] = mapped_column(String(24), nullable=False)
    channel: Mapped[str] = mapped_column(String(10), nullable=False, default="email")
    language: Mapped[str] = mapped_column(String(5), nullable=False)
    template_key: Mapped[str] = mapped_column(String(80), nullable=False)
    template_version: Mapped[str] = mapped_column(String(10), nullable=False)
    #: queued | sent | recorded | skipped | failed
    #: ``sent``: handed to the capture transport; ``recorded``: the null transport noted it.
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="queued")
    #: opted_out | suppressed | no_email | voided | closed (returned / cancelled, Phase 15)
    skip_reason: Mapped[str | None] = mapped_column(String(20), nullable=True)
    transport: Mapped[str | None] = mapped_column(String(12), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
