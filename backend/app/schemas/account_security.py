"""Customer Account: password change and the read-only sign-in email (RC-UAT-21 Phase B;
RC-UAT-25 item 2: only an Admin changes the email).

Allowlisted like every other Customer Account model (``AccountModel``: no ORM objects, extra
fields forbidden). Requests are parsed by hand inside the routes, after the rate limit, as
``routes.py`` does. Nothing here carries a password, a token, a session id or anything that
says whether an address belongs to somebody else.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import Field

from app.schemas.account import AccountModel


class PasswordChangeRequest(AccountModel):
    current_password: str = Field(max_length=1024)
    new_password: str = Field(max_length=1024)
    new_password_confirmation: str | None = Field(default=None, max_length=1024)


class EmailChangeConfirmRequest(AccountModel):
    token: str = Field(max_length=200)


class PendingEmailChange(AccountModel):
    """The address the customer asked to move to, as they typed it. Their own data."""

    new_email: str
    requested_at: datetime
    expires_at: datetime


class AccountSecurityResponse(AccountModel):
    """The signed-in account's own sign-in email. ``pending_email_change`` is always null since
    RC-UAT-25 item 2 (the read closes a request made before it); kept so the shape is stable."""

    email: str
    pending_email_change: PendingEmailChange | None
    min_password_length: int
    message: str | None = None


class PasswordChangedResponse(AccountModel):
    """``csrf_token`` is the rotated session's, as sign-in returns one."""

    message: str
    csrf_token: str
