"""Admin soft delete of old quote records, and the retention machinery (RC-UAT-21 Phase D).

Four new tables; nothing existing is altered (DEC-0181). Revision ``c3e5a7b9d2f4``.

* ``quote_version_deletions`` -- an Admin's soft delete of one quote version (OD-95, OD-98,
  OD-107; DEC-0233), with the reason, and its restore (Admin, with a reason). The quote rows
  stay: a soft-deleted version only disappears from the staff quote lists, the Customer
  Account and the accepted-not-invoiced list. One row per delete; a restore closes the row
  (``restored_at``), and a later delete opens a new one, so the history of both is kept. At
  most one open (``restored_at IS NULL``) row per version. ``purged_at`` is set when the
  retention worker later removed the version itself (only when a retention period was set
  and enabled by the owner); ``quote_version_id`` is then NULL and ``shipment_id`` and
  ``version`` still say what it was.
* ``data_retention_settings`` -- one row: the global switch (off; turning it on needs Admin
  and a typed confirmation), the soft-delete minimum age and the worker's batch size.
* ``data_retention_policies`` -- one row per record class the worker may clean up: enabled
  (false), the period in days (NULL: undecided, OD-01 and OD-36) and the action (``delete`` or
  ``anonymise``). Financial records, payments, vendor bills and audit events are **not**
  record classes: the worker cannot reach them.
* ``data_retention_runs`` -- one row per dry run or real run: when, who, and the counts per
  record class (``counts_json``). Never the records themselves.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

RETENTION_ACTIONS = ("delete", "anonymise")


class QuoteVersionDeletion(Base):
    """An Admin's soft delete of one quote version, and its restore (DEC-0233)."""

    __tablename__ = "quote_version_deletions"
    __table_args__ = (
        # One open soft delete per version: deleting twice is refused, a restore closes it.
        Index(
            "uq_quote_version_deletions_open_version",
            "quote_version_id",
            unique=True,
            sqlite_where=text("restored_at IS NULL"),
            postgresql_where=text("restored_at IS NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    #: NULL once the retention worker purged the version (``purged_at``).
    quote_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("quote_versions.id", ondelete="SET NULL"), nullable=True, index=True
    )
    shipment_id: Mapped[int] = mapped_column(
        ForeignKey("shipments.id", ondelete="CASCADE"), nullable=False, index=True
    )
    #: The version number, kept so a purged row still says what it was.
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    #: Required, at most 400 characters.
    reason: Mapped[str] = mapped_column(String(400), nullable=False)
    deleted_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    deleted_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    restored_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    restored_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    restore_reason: Mapped[str | None] = mapped_column(String(400), nullable=True)
    purged_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class DataRetentionSettings(Base):
    """The global retention switch and its knobs. One row (``id = 1``)."""

    __tablename__ = "data_retention_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    #: Off by default. Nothing is ever deleted while this is false, whatever a class says.
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    enabled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    enabled_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    #: How old (days) a quote version must be before an Admin may soft-delete it. 0: any
    #: eligible version (stand-in D-3).
    quote_delete_min_age_days: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    #: Rows changed per batch by the worker (each batch is its own transaction).
    batch_size: Mapped[int] = mapped_column(Integer, nullable=False, default=200)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class DataRetentionPolicy(Base):
    """What the retention worker may do to one record class. Disabled, period undecided."""

    __tablename__ = "data_retention_policies"

    #: The record class key, e.g. ``notification_outbox_processed``.
    record_class: Mapped[str] = mapped_column(String(40), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    #: NULL: undecided (OD-01, OD-36). A class without a period never runs.
    period_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    #: delete | anonymise (each class allows only some).
    action: Mapped[str] = mapped_column(String(10), nullable=False)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_run_affected: Mapped[int | None] = mapped_column(Integer, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class DataRetentionRun(Base):
    """One dry run or real run of the retention worker: counts only."""

    __tablename__ = "data_retention_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    dry_run: Mapped[bool] = mapped_column(Boolean, nullable=False)
    #: worker | admin
    trigger: Mapped[str] = mapped_column(String(10), nullable=False)
    actor_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    #: completed | failed
    status: Mapped[str] = mapped_column(String(12), nullable=False)
    #: ``{record_class: {"eligible": n, "affected": n, "action": ..., "ran": bool}}``.
    counts_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    #: A bounded, plain reason; never a stack trace.
    error: Mapped[str | None] = mapped_column(String(300), nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
