"""Bank exchange rates (Phase 13A).

Two tables. ``fx_rate_snapshots`` holds every **verified** reading of the bank's CAD row:
cash buying, transfer buying and selling, with the bank's own publication stamp and the
time Solaris retrieved it. ``fx_sync_attempts`` records every attempt, successful or not,
so an outage is visible as a run of failures rather than as silence.

Why both buying and selling: vendor COST is converted VND→CAD at the bank's **cash buying**
rate and a customer-facing surcharge at the bank's **selling** rate (handoff owner decision
10; directive v2.0 §12). A snapshot that lacked either would be unusable, so both are
``NOT NULL``.

Why snapshots are never updated or deleted: a quotation records the snapshot it used, and
reproducing that quotation later requires the row to still say what it said (handoff §6:
"preserve immutable snapshots").

What is never written here: a rate from any source other than the configured bank. A
failed retrieval produces a failed attempt, not a substitute number (directive v2.0 §12).
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Index, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import FxSyncOutcome
from app.models.base import Base

VIETCOMBANK_KEY = "vietcombank"


class FxRateSnapshot(Base):
    """One verified reading of the bank's published CAD rates, in VND per CAD."""

    __tablename__ = "fx_rate_snapshots"
    __table_args__ = (
        Index(
            "ix_fx_rate_snapshots_bank_currency_retrieved_at", "bank", "currency", "retrieved_at"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bank: Mapped[str] = mapped_column(String(30), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    cash_buy_vnd: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    transfer_buy_vnd: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    sell_vnd: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    #: The bank's stamp exactly as published, and its parsed value when it parsed.
    bank_published_raw: Mapped[str | None] = mapped_column(String(60), nullable=True)
    bank_published_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    #: Digest of the bytes the bank returned, so a snapshot can be shown to be unchanged.
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    source_url: Mapped[str] = mapped_column(String(255), nullable=False)

    attempts: Mapped[list[FxSyncAttempt]] = relationship(back_populates="snapshot")


class FxSyncAttempt(Base):
    """One run of the exchange-rate job. Written whether or not it succeeded."""

    __tablename__ = "fx_sync_attempts"
    __table_args__ = (Index("ix_fx_sync_attempts_bank_attempted_at", "bank", "attempted_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bank: Mapped[str] = mapped_column(String(30), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    attempted_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    outcome: Mapped[str] = mapped_column(String(10), nullable=False)
    #: A redacted category and short message, never the response body.
    error_summary: Mapped[str | None] = mapped_column(String(300), nullable=True)
    snapshot_id: Mapped[int | None] = mapped_column(
        ForeignKey("fx_rate_snapshots.id", ondelete="SET NULL"), nullable=True
    )
    worker_name: Mapped[str] = mapped_column(String(60), nullable=False)

    snapshot: Mapped[FxRateSnapshot | None] = relationship(back_populates="attempts")

    @property
    def outcome_enum(self) -> FxSyncOutcome:
        return FxSyncOutcome(self.outcome)
