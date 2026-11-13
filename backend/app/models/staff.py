"""Staff users, sessions, organization settings, and the audit log."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import Role
from app.models.base import Base, TimestampMixin


class User(TimestampMixin, Base):
    """A named staff account. Shared accounts are discouraged (CRM.md section 11)."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(200), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(40), nullable=False, default=Role.OPERATIONS)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="America/Toronto")
    locale: Mapped[str] = mapped_column(String(8), nullable=False, default="en")
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    deactivated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    must_change_password: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    sessions: Mapped[list[UserSession]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )

    @property
    def initials(self) -> str:
        parts = [part for part in self.full_name.split() if part]
        if not parts:
            return "?"
        if len(parts) == 1:
            return parts[0][:2].upper()
        return (parts[0][0] + parts[-1][0]).upper()


class UserSession(Base):
    """Server-managed session. The cookie carries an opaque token; only its digest is stored."""

    __tablename__ = "user_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    session_token_hash: Mapped[str] = mapped_column(
        String(64), nullable=False, unique=True, index=True
    )
    csrf_token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(255), nullable=True)

    user: Mapped[User] = relationship(back_populates="sessions")


class OrganizationSettings(TimestampMixin, Base):
    """Single-brand settings row, including configurable lifecycle thresholds."""

    __tablename__ = "organization_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    brand_name: Mapped[str] = mapped_column(String(120), nullable=False, default="Solaris Express")
    legal_entity_name: Mapped[str] = mapped_column(
        String(200), nullable=False, default="Solaris Express Inc."
    )
    office_timezone: Mapped[str] = mapped_column(
        String(64), nullable=False, default="America/Toronto"
    )
    default_currency: Mapped[str] = mapped_column(String(3), nullable=False, default="CAD")
    tracking_base_url: Mapped[str] = mapped_column(
        String(255), nullable=False, default="http://localhost:5173/track"
    )

    # Lifecycle thresholds are initial business assumptions and are admin-editable
    # (CRM.md section 4).
    lifecycle_new_days: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    lifecycle_active_days: Mapped[int] = mapped_column(Integer, nullable=False, default=60)
    lifecycle_at_risk_days: Mapped[int] = mapped_column(Integer, nullable=False, default=90)

    # Internal retention task rules (CRM.md section 5) - internal tasks only.
    rule_first_delivery_follow_up_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True
    )
    rule_first_delivery_follow_up_days: Mapped[int] = mapped_column(
        Integer, nullable=False, default=3
    )
    rule_at_risk_task_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    rule_exception_task_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    is_demo_environment: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class AuditEvent(Base):
    """Append-only record of material changes (CRM.md section 11).

    Secrets and unnecessary personal information are redacted before writing.
    """

    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    actor_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    actor_label: Mapped[str] = mapped_column(String(200), nullable=False, default="system")
    action: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    entity_type: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    entity_id: Mapped[str | None] = mapped_column(String(60), nullable=True, index=True)
    summary: Mapped[str] = mapped_column(String(400), nullable=False)
    detail_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)


class Counter(Base):
    """Durable allocator for human-readable identifiers such as STCA-000001."""

    __tablename__ = "counters"
    __table_args__ = (UniqueConstraint("name", name="uq_counters_name"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(60), nullable=False)
    value: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
