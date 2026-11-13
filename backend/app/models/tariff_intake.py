"""Vendor rate-email intake (Phase 13H, OD-76).

A vendor rate email (an ``.eml`` with the tariff workbook attached) becomes a **draft**
tariff version through the existing importer; only a designated approver activates it.
Two new tables; nothing existing is altered (DEC-0181).

* ``tariff_intake_settings`` -- one row (id 1), created only when an administrator saves;
  readers answer with an unsaved default and never write (DEC-0204). The mailbox address is
  informational: **there is no live mailbox connection**. Emails arrive by staff upload or
  by the folder worker (``app/workers/tariff_intake_worker.py``).
* ``tariff_email_intakes`` -- one row per distinct email (by Message-ID): provenance
  (sender, subject, received time, attachment name and SHA-256), the outcome, the draft
  version it produced, and the approver's review. **No email body is stored**, and no
  workbook content: the version tables hold what the importer read.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

#: OD-76 (owner, 2026-10-20): vendor rate emails arrive in Ben's Soleil mailbox, and Ben
#: approves new tariff versions. Defaults only; an administrator may change both.
DEFAULT_INTAKE_MAILBOX = "benjamin.le@soleiltransportation.com"
DEFAULT_APPROVER_EMAILS: tuple[str, ...] = ("benjamin.le@soleiltransportation.com",)


class TariffIntakeSettings(Base):
    """Who approves a new tariff version, and which senders are imported without review."""

    __tablename__ = "tariff_intake_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    #: Informational only: no connection to any mailbox exists (stand-in, OD-76).
    mailbox_address: Mapped[str] = mapped_column(
        String(320), nullable=False, default=DEFAULT_INTAKE_MAILBOX
    )
    #: Normalised (lower-case) staff email addresses allowed to approve or reject a version.
    approver_emails: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    #: Sender domains imported straight to a draft. Empty: every sender is held for review.
    allowed_sender_domains: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class TariffEmailIntake(Base):
    """One rate email received, and what became of it."""

    __tablename__ = "tariff_email_intakes"
    __table_args__ = (
        # One row per (Message-ID, sender): an outside sender cannot pre-empt the vendor's id.
        UniqueConstraint("message_id", "sender", name="uq_tariff_email_intakes_message_id_sender"),
        Index("ix_tariff_email_intakes_status", "status"),
        Index("ix_tariff_email_intakes_source_sha256", "source_sha256"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    #: The email's Message-ID; ``sha256:<digest of the file>`` when it has none or it is
    #: unreadable. One row per id: a second copy of the same email is not a new intake.
    message_id: Mapped[str] = mapped_column(String(255), nullable=False)
    #: SHA-256 of the whole ``.eml`` file; the folder worker skips a file it has seen.
    source_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    #: For a folder email: where the worker moved it (relative to the intake folder), so an
    #: approver can reprocess a failed one.
    stored_file: Mapped[str | None] = mapped_column(String(255), nullable=True)
    #: Lower-case address from ``From``. NULL when the file is not a readable email.
    sender: Mapped[str | None] = mapped_column(String(320), nullable=True)
    #: Plain text, single line, bounded. Never interpreted.
    subject: Mapped[str | None] = mapped_column(String(300), nullable=True)
    #: The email's ``Date``, UTC.
    received_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    #: upload | folder
    source: Mapped[str] = mapped_column(String(10), nullable=False)
    attachment_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    attachment_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    #: received | imported | duplicate | rejected | failed | no_attachment | held_sender
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="received")
    tariff_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("tariff_versions.id", ondelete="SET NULL"), nullable=True, index=True
    )
    #: A note that did not stop the import (e.g. the email's Date was implausible).
    warning: Mapped[str | None] = mapped_column(String(300), nullable=True)
    #: A bounded, plain reason; never a stack trace.
    error: Mapped[str | None] = mapped_column(String(500), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    reviewed_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    review_note: Mapped[str | None] = mapped_column(String(400), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class TariffVersionReview(Base):
    """The approver's decision on a tariff version, whatever its source (email or manual).

    A rejected version can never be approved or activated. ``tariff_versions`` itself is not
    altered (DEC-0181): it has no rejected state, so the decision lives here.
    """

    __tablename__ = "tariff_version_reviews"
    __table_args__ = (
        UniqueConstraint("tariff_version_id", name="uq_tariff_version_reviews_tariff_version_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tariff_version_id: Mapped[int] = mapped_column(
        ForeignKey("tariff_versions.id", ondelete="CASCADE"), nullable=False
    )
    #: approved | rejected
    decision: Mapped[str] = mapped_column(String(10), nullable=False)
    reviewed_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    reviewed_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    note: Mapped[str | None] = mapped_column(String(400), nullable=True)
