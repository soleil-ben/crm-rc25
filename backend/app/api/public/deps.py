"""Dependencies for the public surface.

Deliberately a separate, much smaller file than ``app/api/deps.py``. The staff
dependencies resolve a session, enforce CSRF, and check a permission matrix; none of
those belong on a customer-facing route, and importing that module here would be the
easy way to attach one by accident.

What a public route is allowed to depend on is exactly two things: a database session,
and the directly observed client address. Nothing else.

**A dependency that reads a row is not allowed here, and that is a correction.** Phase 3
resolved the organization settings row as ``PublicOrgSettings``, purely for its display
timezone. FastAPI resolves dependencies before the endpoint body, so every public
request -- including one the rate limiter was about to refuse -- performed that query
first. The limiter statement was the first line of the handler and still ran second.
The read now happens inside ``public_tracking_service`` after a reference has resolved,
which is the only point at which a timezone is needed (DEC-0059).

The session dependency stays, because ``SessionLocal()`` opens no connection until a
statement is executed: a refused request closes an unused session and issues no query.
``tests/test_public_tracking.py`` counts statements on the engine to prove it.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import get_db


def public_db_session() -> Iterator[Session]:
    yield from get_db()


PublicDb = Annotated[Session, Depends(public_db_session)]


#: Headers that claim to carry an originating address. None of them is believed unless a
#: trusted proxy has been explicitly configured.
FORWARDING_HEADERS = ("x-forwarded-for", "x-real-ip", "forwarded", "x-client-ip")

#: The single bucket every unverified forwarded request shares.
UNTRUSTED_FORWARDED_KEY = "untrusted-forwarded"


def public_client_key(request: Request) -> str:
    """The rate-limit key: the directly observed peer address, and only that.

    ``X-Forwarded-For`` is not believed. No trusted reverse proxy is configured yet, so
    honouring the header would let any caller pick their own bucket by sending a new
    value per request -- which is to say, remove the rate limit entirely (DEC-0007).

    **Ignoring the header is not enough on its own, and that is the interesting part.**
    Uvicorn ships with ``--proxy-headers`` enabled and trusts ``127.0.0.1`` by default,
    so it rewrites ``request.client`` from ``X-Forwarded-For`` *before this function
    runs*. An application that simply declined to read the header would still have been
    handed a spoofed peer address and would still have bucketed by it. The public
    end-to-end suite caught exactly this.

    So the defence does not depend on the server being configured correctly. When
    ``trust_proxy_headers`` is false, any request carrying a forwarding header is keyed
    into **one shared bucket** rather than into a bucket of the caller's choosing. A
    spoofer therefore cannot mint a fresh allowance per request whatever the ASGI server
    did to the scope, and a direct caller -- who sends no such header -- keeps their own
    bucket and is unaffected.

    Running the server with ``--no-proxy-headers`` remains the correct configuration and
    is what the documented commands use; this is the belt to that pair of braces. Both
    are recorded in ``docs/OPERATIONS.md`` as gates before the application runs behind
    anything (DEC-0048).
    """
    if not settings.trust_proxy_headers:
        for header in FORWARDING_HEADERS:
            if header in request.headers:
                return UNTRUSTED_FORWARDED_KEY

    host = request.client.host if request.client else None
    return host or "unknown"


PublicClientKey = Annotated[str, Depends(public_client_key)]
