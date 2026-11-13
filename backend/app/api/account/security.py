"""Customer Account: change password; the sign-in email is read-only (RC-UAT-21 Phase B,
RC-UAT-25 item 2).

``GET  /api/v1/account/security``                   the sign-in email (a pending change is closed)
``POST /api/v1/account/password/change``            signed in; current password required
``POST /api/v1/account/email/change``               refused: only an Admin changes the email
``POST /api/v1/account/email/change/cancel``        signed in; closes a pre-RC-UAT-25 request
``POST /api/v1/account/email/change/confirm``       refused: every link, the same sentence

Any signed-in identity may use them (``pending_approval`` or ``active``): a password is the
account's, not the linked customer's, so no link is required.

**The sign-in email is changed by an Admin only** (RC-UAT-25 item 2, Ben 2026-10-25). The two
email routes stay mounted so an old page or an old link gets a clear answer rather than a
404: the request route refuses (403, one sentence) after the session and CSRF checks and
before reading the body; the confirmation route refuses every link with the token sentence
and closes the request a live link belonged to. The staff route is
``POST /api/v1/customer-account/identities/{reference}/sign-in-email``.

The order of operations is ``routes.py``'s: the session (with its CSRF check on every POST),
then the per-account rate limit **before the body is read**, then the body, then the service.
The confirmation route has no session -- the link is the proof -- so it takes the origin check
and the per-caller token limit that ``/verify-email`` takes, and answers every failure with
the same sentence.
"""

from __future__ import annotations

from fastapi import APIRouter, Request, Response

from app.api.account.deps import (
    AccountClientKey,
    AccountDb,
    CurrentAccountSession,
    account_client_ip,
)
from app.api.account.routes import (
    _check_origin,
    _limit,
    _parse,
    _read_json,
    _set_session_cookies,
    _throttled,
)
from app.api.account.shipments import RATE_LIMIT_MESSAGE, _apply_headers
from app.core.account_security import token_ip_bucket
from app.core.config import settings
from app.core.db import commit_with_retry
from app.core.security import rate_limiter
from app.schemas.account import AccountMessageResponse
from app.schemas.account_security import (
    AccountSecurityResponse,
    EmailChangeConfirmRequest,
    PasswordChangedResponse,
    PasswordChangeRequest,
    PendingEmailChange,
)
from app.services import customer_account_security_service as security
from app.services import customer_identity_service
from app.services.errors import RateLimitedError, ValidationError

router = APIRouter(tags=["customer-account"])

#: Five attempts a quarter hour per account: a person mistyping, not a script guessing the
#: current password through a stolen session.
PASSWORD_CHANGE_ATTEMPTS = 5
PASSWORD_CHANGE_WINDOW_SECONDS = 900
CANCEL_ATTEMPTS = 30
CANCEL_WINDOW_SECONDS = 3600


def password_change_bucket(identity_public_id: str) -> str:
    return f"account:password_change:{identity_public_id}"


def _limit_account(bucket: str, attempts: int, window: int) -> None:
    allowed, retry_after = rate_limiter.check(bucket, attempts, window)
    if not allowed:
        raise RateLimitedError(RATE_LIMIT_MESSAGE, retry_after=retry_after)


def _security_response(db, identity, message: str | None = None) -> AccountSecurityResponse:
    pending = security.pending_email_change(db, identity)
    return AccountSecurityResponse(
        email=identity.email_entered,
        pending_email_change=(
            PendingEmailChange(
                new_email=pending.new_email_entered,
                requested_at=pending.requested_at,
                expires_at=pending.expires_at,
            )
            if pending is not None
            else None
        ),
        min_password_length=settings.account_min_password_length,
        message=message,
    )


@router.get("/security", response_model=AccountSecurityResponse, summary="Sign-in details")
def read_security(
    response: Response, db: AccountDb, session: CurrentAccountSession
) -> AccountSecurityResponse:
    _apply_headers(response)
    identity, _ = session
    # RC-UAT-25 item 2: a change asked for before the customer path was withdrawn is closed
    # here, and its link killed, so the page never shows a pending change again.
    security.withdraw_pending_email_changes(db, identity, ip_address=None)
    result = _security_response(db, identity)
    commit_with_retry(db)
    return result


@router.post(
    "/password/change", response_model=PasswordChangedResponse, summary="Change your password"
)
async def change_password(
    request: Request,
    response: Response,
    db: AccountDb,
    session: CurrentAccountSession,
) -> PasswordChangedResponse:
    _apply_headers(response)
    identity, record = session
    _limit_account(
        password_change_bucket(identity.public_id),
        PASSWORD_CHANGE_ATTEMPTS,
        PASSWORD_CHANGE_WINDOW_SECONDS,
    )
    payload = _parse(PasswordChangeRequest, await _read_json(request))
    try:
        rotated = security.change_password(
            db,
            identity=identity,
            session=record,
            current_password=payload.current_password,
            new_password=payload.new_password,
            new_password_confirmation=payload.new_password_confirmation,
            ip_address=account_client_ip(request),
            user_agent=request.headers.get("user-agent"),
        )
    except ValidationError:
        # The refusal's audit row is what the refusal is for; keep it.
        commit_with_retry(db)
        raise
    commit_with_retry(db)
    _set_session_cookies(response, rotated.session_token, rotated.csrf_token)
    return PasswordChangedResponse(
        message=security.PASSWORD_CHANGED_MESSAGE, csrf_token=rotated.csrf_token
    )


@router.post(
    "/email/change",
    response_model=AccountSecurityResponse,
    summary="Change your sign-in email (refused: Admin only)",
)
def request_email_change(
    response: Response,
    db: AccountDb,
    session: CurrentAccountSession,
) -> AccountSecurityResponse:
    """Always 403 with one sentence (RC-UAT-25 item 2). The body is never read."""
    _apply_headers(response)
    identity, _ = session
    security.request_email_change(db, identity=identity)
    raise AssertionError("unreachable")  # pragma: no cover - the service always raises


@router.post(
    "/email/change/cancel",
    response_model=AccountSecurityResponse,
    summary="Cancel a pending email change",
)
def cancel_email_change(
    request: Request,
    response: Response,
    db: AccountDb,
    session: CurrentAccountSession,
) -> AccountSecurityResponse:
    _apply_headers(response)
    identity, _ = session
    _limit_account(
        f"account:email_change_cancel:{identity.public_id}", CANCEL_ATTEMPTS, CANCEL_WINDOW_SECONDS
    )
    security.cancel_email_change(db, identity=identity, ip_address=account_client_ip(request))
    commit_with_retry(db)
    return _security_response(db, identity, security.EMAIL_CHANGE_CANCELLED_MESSAGE)


@router.post(
    "/email/change/confirm",
    response_model=AccountMessageResponse,
    summary="Confirm a new sign-in email",
)
async def confirm_email_change(
    request: Request,
    db: AccountDb,
    client_key: AccountClientKey,
) -> AccountMessageResponse:
    """Refuse every link (RC-UAT-25 item 2) with the one token sentence. A live link is
    consumed and its request closed, so it cannot be tried again."""
    _check_origin(request)
    if not _limit(
        token_ip_bucket(client_key),
        settings.account_token_ip_attempts,
        settings.account_token_ip_window_seconds,
    ):
        raise _throttled(getattr(_limit, "last_retry_after", 60))
    payload = _parse(EmailChangeConfirmRequest, await _read_json(request))
    security.confirm_email_change(db, token=payload.token, ip_address=account_client_ip(request))
    commit_with_retry(db)
    raise ValidationError(customer_identity_service.GENERIC_TOKEN_FAILURE, field="token")
