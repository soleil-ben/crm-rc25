"""RC-UAT-22: staff re-link or close of an orphaned Customer Account (B-13, DEC-0234 draft).

One new table; nothing existing is altered (DEC-0181). Revision ``d4f6b8c0e2a5``.

* ``customer_account_relinks`` -- an Admin resolved an **orphaned** account: one that was
  approved once, has no active link and no pending proposal, and sits in
  ``pending_approval`` with nothing for the approval flow to decide (an RC-UAT-21
  reinstatement ended its link because the customer was merged or archived meanwhile, or
  any other path left it linkless). Two outcomes, one row each:

  - ``relink`` -- the account was linked to the customer the Admin named and returned to
    ``active``. The row keeps the history figures the Admin acknowledged (the five OD-29
    disclosure figures and the preview fingerprint), because the link row itself records
    only who linked it and when.
  - ``close`` -- the account was deactivated (reason ``orphan_closed``). No customer is
    involved; the target columns stay null.

  Both copy the account's **last** link (its customer and why it ended) before acting, so
  the row reads on its own: "was linked to C-1, ended merged_since_deactivation, now linked
  to C-2 because merge_survivor".

The Admin's note stays here and never reaches the audit payload, as on
``customer_account_reinstatements``.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class CustomerAccountRelink(Base):
    """An Admin re-linked or closed an orphaned Customer Account (B-13)."""

    __tablename__ = "customer_account_relinks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    identity_id: Mapped[int] = mapped_column(
        ForeignKey("customer_identities.id", ondelete="CASCADE"), nullable=False, index=True
    )
    #: ``relink`` | ``close``.
    action: Mapped[str] = mapped_column(String(20), nullable=False)
    #: The customer of the account's last link, and why that link ended, copied before acting.
    previous_customer_id: Mapped[int | None] = mapped_column(
        ForeignKey("customers.id", ondelete="SET NULL"), nullable=True
    )
    previous_link_end_reason: Mapped[str | None] = mapped_column(String(40), nullable=True)
    #: ``relink`` only: the customer the account is now linked to.
    target_customer_id: Mapped[int | None] = mapped_column(
        ForeignKey("customers.id", ondelete="SET NULL"), nullable=True
    )
    #: A bounded code (``RELINK_REASON_CODES`` or ``CLOSE_REASON_CODES``) and an optional note.
    reason_code: Mapped[str] = mapped_column(String(40), nullable=False)
    note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    #: ``relink`` only: what the Admin acknowledged -- the OD-29 figures of the target's
    #: history and the preview fingerprint they were shown under.
    disclosed_shipment_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    oldest_booked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    newest_booked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    includes_cancelled: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    includes_rebooked: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    disclosure_definition_version: Mapped[str | None] = mapped_column(String(40), nullable=True)
    preview_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    acted_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    acted_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
