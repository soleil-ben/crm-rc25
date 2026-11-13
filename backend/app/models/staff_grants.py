"""Per-account permission grants (owner, 2026-11-04; DEC-0268). New table (DEC-0181).

Roles carry most permissions (``app/core/permissions.py``). A few powers belong to named
people rather than to every holder of a role: today only ``tariff:approve`` -- confirming or
rolling back a Kango rate sheet -- which the owner gives to Ben and to Louis T (Assistant
Manager). A grant is a row here, given and taken by an Admin and audited; it adds to the
role's permissions and never replaces them (an approver still needs ``tariff:manage``).
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class StaffPermissionGrant(Base):
    __tablename__ = "staff_permission_grants"
    __table_args__ = (UniqueConstraint("user_id", "permission"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    permission: Mapped[str] = mapped_column(String(60), nullable=False)
    granted_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    granted_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
