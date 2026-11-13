"""RC-UAT-25 (Ben's live UAT answers of 2026-10-25): two new tables; nothing existing is
altered. Revision ``a5c7e9b1d3f6``.

* ``customer_account_email_changes`` -- an **Admin** changed a Customer Account's sign-in
  email (item 2: customers can no longer change it themselves). The identity's own columns
  hold only the current address; this row keeps the history: the address before and after,
  the linked customer that followed, the Admin's bounded reason and optional note (never in
  the audit payload), how many sessions were ended, when and by whom.

* ``shipment_event_revisions`` -- staff edited an operational timeline event (item 6),
  usually one already published to the customer. The event rows are corrected in place so
  the timeline, the derived status and the customer's view read the corrected values; this
  row keeps what they said before and after, the rows the edit touched (an edit that removes
  a package voids that package's row; one that adds a package writes a row for it), the
  editor's reason, and whether the customer-visible wording changed.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class CustomerAccountEmailChange(Base):
    """An Admin changed a Customer Account's sign-in email (RC-UAT-25 item 2)."""

    __tablename__ = "customer_account_email_changes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    identity_id: Mapped[int] = mapped_column(
        ForeignKey("customer_identities.id", ondelete="CASCADE"), nullable=False, index=True
    )
    #: The linked customer whose email followed, when the account had one.
    customer_id: Mapped[int | None] = mapped_column(
        ForeignKey("customers.id", ondelete="SET NULL"), nullable=True
    )
    previous_email_entered: Mapped[str] = mapped_column(String(320), nullable=False)
    new_email_entered: Mapped[str] = mapped_column(String(320), nullable=False)
    #: ``CHANGE_EMAIL_REASON_CODES`` and an optional short note.
    reason_code: Mapped[str] = mapped_column(String(40), nullable=False)
    note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    sessions_revoked: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    changed_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    changed_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class ShipmentEventRevision(Base):
    """Staff edited a timeline event (RC-UAT-25 item 6). Before and after, never overwritten."""

    __tablename__ = "shipment_event_revisions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    shipment_id: Mapped[int] = mapped_column(
        ForeignKey("shipments.id", ondelete="CASCADE"), nullable=False, index=True
    )
    #: JSON lists of ``shipment_events.id``: the rows of the recording before the edit, and
    #: the live rows after it (kept and added; a removed package's row is voided).
    event_ids_before: Mapped[str] = mapped_column(Text, nullable=False)
    event_ids_after: Mapped[str] = mapped_column(Text, nullable=False)
    #: JSON objects of the edited fields (``event_service.EDITABLE_FIELDS``) before and after.
    before_json: Mapped[str] = mapped_column(Text, nullable=False)
    after_json: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str] = mapped_column(String(255), nullable=False)
    #: The event was published to the customer when it was edited.
    was_published: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    #: The customer-visible sentence (template key or own wording) changed.
    public_wording_changed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    edited_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    edited_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
