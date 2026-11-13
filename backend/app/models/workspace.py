"""Workspace redesign (owner, 2026-11-04; DEC-0272). New table only (DEC-0181).

A master's **master tracking** is ``consolidations.vendor_reference`` and covers every piece.
Each master piece (a carton of the master, ``consolidation_cartons.sequence``) may carry its
own **last-mile tracking**; it is optional and may repeat between pieces.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class ConsolidationPieceTracking(Base):
    __tablename__ = "consolidation_piece_tracking"
    __table_args__ = (UniqueConstraint("consolidation_id", "carton_sequence"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    consolidation_id: Mapped[int] = mapped_column(
        ForeignKey("consolidations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    carton_sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    last_mile_tracking: Mapped[str] = mapped_column(String(60), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
