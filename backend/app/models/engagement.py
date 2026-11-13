"""Interactions, follow-up tasks, consent history, suppressions, service issues, segments."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import (
    ConsentBasis,
    ConsentStatus,
    InteractionDirection,
    InteractionVisibility,
    ServiceIssueStatus,
    TaskPriority,
    TaskPurpose,
    TaskStatus,
)
from app.models.base import Base, TimestampMixin


class Interaction(TimestampMixin, Base):
    """Timestamped note or interaction. Internal by default (CRM.md section 4)."""

    __tablename__ = "interactions"
    __table_args__ = (
        Index("ix_interactions_customer_id_occurred_at", "customer_id", "occurred_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    customer_id: Mapped[int] = mapped_column(
        ForeignKey("customers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    shipment_id: Mapped[int | None] = mapped_column(
        ForeignKey("shipments.id", ondelete="SET NULL"), nullable=True, index=True
    )
    task_id: Mapped[int | None] = mapped_column(
        ForeignKey("follow_up_tasks.id", ondelete="SET NULL"), nullable=True
    )
    occurred_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    channel: Mapped[str] = mapped_column(String(20), nullable=False)
    direction: Mapped[str] = mapped_column(
        String(20), nullable=False, default=InteractionDirection.OUTBOUND
    )
    subject: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    outcome: Mapped[str | None] = mapped_column(String(200), nullable=True)
    visibility: Mapped[str] = mapped_column(
        String(20), nullable=False, default=InteractionVisibility.INTERNAL
    )
    is_follow_up_completion: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, index=True
    )
    author_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )


class FollowUpTask(TimestampMixin, Base):
    """Follow-up task. Multiple open tasks per customer are supported; completing one
    never closes another (CRM.md section 4)."""

    __tablename__ = "follow_up_tasks"
    __table_args__ = (
        Index("ix_follow_up_tasks_status_due_at", "status", "due_at"),
        # Automation rules must not create duplicate tasks (CRM.md section 5).
        UniqueConstraint("dedupe_key", name="uq_follow_up_tasks_dedupe_key"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    customer_id: Mapped[int] = mapped_column(
        ForeignKey("customers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    shipment_id: Mapped[int | None] = mapped_column(
        ForeignKey("shipments.id", ondelete="SET NULL"), nullable=True, index=True
    )
    subject: Mapped[str] = mapped_column(String(200), nullable=False)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    purpose: Mapped[str] = mapped_column(String(40), nullable=False, default=TaskPurpose.GENERAL)
    priority: Mapped[str] = mapped_column(String(20), nullable=False, default=TaskPriority.NORMAL)
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default=TaskStatus.SCHEDULED, index=True
    )
    due_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    assignee_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    created_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    outcome: Mapped[str | None] = mapped_column(String(400), nullable=True)
    cancelled_reason: Mapped[str | None] = mapped_column(String(400), nullable=True)
    source_rule: Mapped[str | None] = mapped_column(String(60), nullable=True)
    dedupe_key: Mapped[str | None] = mapped_column(String(160), nullable=True)


class ConsentEvent(Base):
    """Append-only consent history per channel and address (CRM.md section 11).

    A single checkbox is never overwritten; the current state is the latest event for
    the channel/address pair.
    """

    __tablename__ = "consent_events"
    __table_args__ = (
        Index(
            "ix_consent_events_customer_id_channel_recorded_at",
            "customer_id",
            "channel",
            "recorded_at",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    customer_id: Mapped[int] = mapped_column(
        ForeignKey("customers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    channel: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    address_value: Mapped[str] = mapped_column(String(320), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=ConsentStatus.UNKNOWN)
    basis: Mapped[str] = mapped_column(
        String(40), nullable=False, default=ConsentBasis.NOT_RECORDED
    )
    obtained_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    withdrawn_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    source: Mapped[str | None] = mapped_column(String(120), nullable=True)
    evidence_reference: Mapped[str | None] = mapped_column(String(255), nullable=True)
    note: Mapped[str | None] = mapped_column(String(400), nullable=True)
    recorded_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    recorded_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class ContactSuppression(Base):
    """Global suppression keyed by channel and normalized address.

    Suppression is intentionally not customer-scoped so it survives merges and
    re-imports (CRM.md section 11, AC-15).
    """

    __tablename__ = "contact_suppressions"
    __table_args__ = (
        UniqueConstraint(
            "channel", "address_value", name="uq_contact_suppressions_channel_address_value"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    channel: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    address_value: Mapped[str] = mapped_column(String(320), nullable=False, index=True)
    reason: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    created_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    released_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    released_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    release_reason: Mapped[str | None] = mapped_column(String(200), nullable=True)


class ServiceIssue(TimestampMixin, Base):
    """Service issue flag so staff can prioritize service recovery (CRM.md section 4)."""

    __tablename__ = "service_issues"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    customer_id: Mapped[int] = mapped_column(
        ForeignKey("customers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    shipment_id: Mapped[int | None] = mapped_column(
        ForeignKey("shipments.id", ondelete="SET NULL"), nullable=True
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=ServiceIssueStatus.OPEN, index=True
    )
    opened_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    opened_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class SavedSegment(TimestampMixin, Base):
    """Dynamic segment defined by a validated filter tree (CRM.md section 15).

    The definition is stored as JSON but is parsed and validated against a whitelist of
    fields and operators before it is ever compiled into SQL.
    """

    __tablename__ = "saved_segments"
    __table_args__ = (UniqueConstraint("slug", name="uq_saved_segments_slug"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    slug: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(String(400), nullable=True)
    definition_json: Mapped[str] = mapped_column(Text, nullable=False)
    is_system: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_shared: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    owner_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )

    owner: Mapped[object | None] = relationship("User", lazy="joined")
