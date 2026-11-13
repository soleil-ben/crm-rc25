"""RC-UAT-21 Phase B: self-service email change and account reinstatement (DEC-0231).

Two new tables; nothing existing is altered (DEC-0181). Revision ``b2d4f6a8c1e3``.

* ``customer_email_change_requests`` -- a signed-in customer asked to move their sign-in
  email to a new address. The **old** address stays the account's address until the new one
  is proved: the request holds the new address, and the single-use token that proves it is
  an ordinary ``customer_auth_tokens`` row (purpose ``email_change``, hashed, expiring after
  the OD-36 verification period, issued to the new address). One pending request per
  identity at a time: a new request supersedes the previous one.

  A request the single-email rule refuses (the new address already belongs to another
  account or another customer record) is **still written**, with ``refused_reason_code`` set
  and no token. The customer is told exactly what they would have been told on success and
  sees the same pending state, so the screen cannot be used to learn whether an address is
  known to Solaris Express (T-02). ``refused_reason_code`` is never serialized.

* ``customer_account_reinstatements`` -- an Admin returned a **deactivated** account to use.
  The row is the history the identity's own columns cannot hold: the deactivation it
  reversed (when, by whom, why), the status it was restored to, and the Admin's reason. The
  identity's ``deactivated_*`` columns are cleared by the reinstatement; this row keeps them.

Credential material is not here: the token's plaintext exists only in the outbound message,
its digest only on ``customer_auth_tokens``.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class CustomerEmailChangeRequest(Base):
    """A customer's request to change their sign-in email (DEC-0231)."""

    __tablename__ = "customer_email_change_requests"
    __table_args__ = (
        Index("ix_customer_email_change_requests_identity_status", "identity_id", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    identity_id: Mapped[int] = mapped_column(
        ForeignKey("customer_identities.id", ondelete="CASCADE"), nullable=False
    )
    #: The proving token, when one was sent. Null for a refused request (no message sent).
    token_id: Mapped[int | None] = mapped_column(
        ForeignKey("customer_auth_tokens.id", ondelete="SET NULL"), nullable=True
    )
    #: The new address as typed and as normalized. The old one is still the identity's.
    new_email_entered: Mapped[str] = mapped_column(String(320), nullable=False)
    new_email_normalized: Mapped[str] = mapped_column(String(320), nullable=False)
    #: pending | completed | superseded | cancelled | refused | expired
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    #: Internal only, never serialized: why the single-email rule refused the request or its
    #: confirmation (``address_in_use_identity``, ``address_in_use_customer``).
    refused_reason_code: Mapped[str | None] = mapped_column(String(40), nullable=True)
    requested_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    request_ip: Mapped[str | None] = mapped_column(String(64), nullable=True)


class CustomerAccountReinstatement(Base):
    """An Admin reinstated a deactivated Customer Account (DEC-0231)."""

    __tablename__ = "customer_account_reinstatements"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    identity_id: Mapped[int] = mapped_column(
        ForeignKey("customer_identities.id", ondelete="CASCADE"), nullable=False, index=True
    )
    #: The deactivation this reversed, copied before the identity's columns are cleared.
    deactivated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    deactivated_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    deactivation_reason_code: Mapped[str | None] = mapped_column(String(40), nullable=True)
    #: The status the account returned to: active | pending_approval | pending_verification
    #: | suspended.
    restored_status: Mapped[str] = mapped_column(String(30), nullable=False)
    #: A bounded reason code (``REACTIVATE_REASON_CODES``) and an optional short note.
    reason_code: Mapped[str] = mapped_column(String(40), nullable=False)
    note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    reinstated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    reinstated_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
