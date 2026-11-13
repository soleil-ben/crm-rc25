"""Dependencies for the Customer Account surface.

A separate, smaller file than ``app/api/deps.py``, for the reason
``app/api/public/deps.py`` gives and with more force. The staff dependencies resolve a
``user_sessions`` row, enforce a CSRF header the staff frontend sends, and check a
permission matrix. None of that belongs on a customer route, and importing the module here
would be the easy way to attach one by accident. On the public surface that mistake
produces an obvious error, because a public route has no cookie to resolve; here it would
produce a *working staff session*, which is why this file exists (T-01, T-12).

What a Customer Account route may depend on is exactly four things: a database session, the
directly observed client address, the request body size bound, and -- for an authenticated
route -- the identity and its session row. Nothing else.

**Authorization here is not a permission check.** A customer identity has no role and no
permission set; the only questions these dependencies answer are "is this a live session"
and "is this identity in a state that may make this request". Ownership of a *resource* is
Phase 11's problem and is enforced in the query, not here.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import commit_with_retry, get_db
from app.models import CustomerIdentity, CustomerSession
from app.services import customer_auth_service
from app.services.errors import AuthenticationError, PermissionDeniedError

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def account_db_session() -> Iterator[Session]:
    """Its own session dependency, not the staff one.

    A distinct callable so a test can override this surface's database without touching the
    other two, and so the route table shows a Customer Account route depending on a Customer
    Account dependency. ``SessionLocal()`` opens no connection until a statement runs, so a
    request the rate limiter is about to refuse closes an unused session and issues no query
    -- which is what makes the "zero statements on a refused request" assertion possible.
    """
    yield from get_db()


AccountDb = Annotated[Session, Depends(account_db_session)]


#: Headers that claim to carry an originating address. None is believed unless a trusted
#: proxy has been explicitly configured (DEC-0007, DEC-0048).
FORWARDING_HEADERS = ("x-forwarded-for", "x-real-ip", "forwarded", "x-client-ip")

#: The single bucket every unverified forwarded request shares.
UNTRUSTED_FORWARDED_KEY = "untrusted-forwarded"


def account_client_key(request: Request) -> str:
    """The rate-limit key: the directly observed peer address, and only that.

    Identical in behaviour to ``app.api.public.deps.public_client_key`` and deliberately not
    imported from it. The two surfaces have different lifetimes and different owners, and a
    shared helper is a shared helper one of them will eventually need to change.

    The reasoning is the public surface's, unchanged: Uvicorn ships with ``--proxy-headers``
    enabled and trusts ``127.0.0.1``, so it rewrites ``request.client`` from
    ``X-Forwarded-For`` before this function runs. Declining to *read* the header would not
    help. So when ``trust_proxy_headers`` is false, every request carrying a forwarding
    header is keyed into one shared bucket rather than a bucket of the caller's choosing.
    """
    if not settings.trust_proxy_headers:
        for header in FORWARDING_HEADERS:
            if header in request.headers:
                return UNTRUSTED_FORWARDED_KEY

    host = request.client.host if request.client else None
    return host or "unknown"


AccountClientKey = Annotated[str, Depends(account_client_key)]


def account_client_ip(request: Request) -> str | None:
    """The peer address for an audit row. ``None`` rather than a guess when there is none."""
    return request.client.host if request.client else None


def current_account_session(
    request: Request, db: AccountDb
) -> tuple[CustomerIdentity, CustomerSession]:
    """Resolve the Customer Account session and enforce CSRF on state-changing requests.

    Reads ``settings.account_session_cookie_name``. A staff cookie is not looked for and
    would not be found: the staff cookie has a different name, and even a request that
    presented its value under *this* name would resolve nothing, because
    ``customer_auth_service.resolve_session`` looks it up in ``customer_sessions``.

    CSRF is the staff pattern re-implemented rather than imported: the readable cookie's
    digest is stored on this session row, the header is ``X-Account-CSRF-Token``, and the
    comparison is constant time. A staff CSRF token satisfies nothing here because it was
    never hashed onto a ``customer_sessions`` row.
    """
    token = request.cookies.get(settings.account_session_cookie_name)
    resolved = customer_auth_service.resolve_session(db, token)
    if resolved is None:
        raise AuthenticationError("Sign in to continue.")

    identity, record = resolved
    if request.method not in SAFE_METHODS:
        header_token = request.headers.get(settings.account_csrf_header_name)
        if not customer_auth_service.verify_csrf(record, header_token):
            raise PermissionDeniedError(
                "Your session security token is missing or stale. Reload the page and try again."
            )
    keep_session_alive(db)
    return identity, record


def keep_session_alive(db: Session) -> None:
    """Commit the session's last-seen touch on its own, best effort, for every account route.

    Runs after the expiry, idle, revocation, status and CSRF checks, which are unchanged:
    a refused session never reaches it. The touch is a courtesy. Under SQLite a transaction
    that has already read cannot always take the write lock (another request committed
    meanwhile) and is refused with ``database is locked`` at once; two screens loading
    together hit that (Phase 17 UAT, the Notifications page). So a lock skips the touch and
    never fails the request; the route then starts a fresh transaction for its own work.
    Any other database error propagates (DEC-0116).
    """
    if not db.dirty:
        return  # nothing to touch this minute: the route keeps its transaction
    try:
        commit_with_retry(db)
    except OperationalError as error:
        if "database is locked" not in str(error).lower():
            raise
        db.rollback()


CurrentAccountSession = Annotated[
    tuple[CustomerIdentity, CustomerSession], Depends(current_account_session)
]


def current_identity(session: CurrentAccountSession) -> CustomerIdentity:
    return session[0]


CurrentIdentity = Annotated[CustomerIdentity, Depends(current_identity)]
