"""The public tracking endpoint.

``GET /api/v1/public/track/{reference}``

One policy boundary, no authentication, one response model, one failure shape. The order
of operations is spelled out in ``_public_lookup`` and is the contract this file exists
to keep.

**Why the reference is a catch-all path parameter.** Phase 3 declared it as
``Path(min_length=1, max_length=120)``. That looked like defence and was the opposite.
FastAPI validates a path parameter *before* the endpoint body runs, so a 121-character
reference produced a detailed 422 -- naming the constraint and echoing the submitted
value back -- without the rate limiter ever running. Two more shapes escaped even
earlier: ``/track/`` and ``/track/a/b`` never matched the route at all and fell through
to Starlette's router 404, whose body is ``{"detail": "Not Found"}`` rather than the
generic tracking failure. Three distinguishable answers, two of them free of charge, on a
surface whose entire design is that every failure looks identical.

``{reference:path}`` matches everything under ``/track/`` -- the empty string, additional
separators, any length -- so path-shaped invalid input reaches the application's policy
instead of the framework's. The length bound did not disappear; it moved into
``parse_public_reference``, where exceeding it means simply *not a Solaris reference* and
produces the same 404 as any other malformed value.

The catch-all is scoped to ``/track/`` inside a router mounted at ``/api/v1/public``, so
it cannot shadow a staff route. ``tests/test_public_tracking.py`` asserts that rather
than trusting it.

The reference travels in the request **path**, because that is what a QR code on a label
encodes and what a customer can bookmark. That has a consequence worth stating plainly:
the identifier will appear in the reverse proxy's access log unless the deployment is
configured to redact it. Redacting that path is a production gate recorded in
``docs/OPERATIONS.md``. The application itself never writes the reference to a log
(``public_tracking_service.log_lookup`` records an outcome category and a keyed digest).
"""

from __future__ import annotations

from fastapi import APIRouter, Response

from app.api.public.deps import PublicClientKey, PublicDb
from app.core.config import settings
from app.core.security import rate_limiter
from app.schemas.public_tracking import PublicTrackingError, PublicTrackingResult
from app.services import public_tracking_service
from app.services.errors import NotFoundError, RateLimitedError

router = APIRouter(tags=["public tracking"])

#: Rate-limit bucket prefix. Separate from ``login:*`` so a busy tracking page cannot
#: consume a staff member's sign-in allowance, and a login attack cannot lock out
#: customers checking their parcels.
RATE_LIMIT_BUCKET = "public_track:ip"

RATE_LIMIT_MESSAGE = (
    "Too many tracking lookups from this connection. Please wait a moment and try again."
)

#: Applied to every public response, success or failure. ``no-store`` keeps a tracking
#: result out of shared and browser caches; ``noindex, nofollow`` keeps the API out of
#: search results; the rest are the standard content and framing protections
#: (CRM.md section 10, Design.md section 14).
PUBLIC_HEADERS = {
    "Cache-Control": "no-store, no-cache, must-revalidate, private",
    "Pragma": "no-cache",
    "Referrer-Policy": "no-referrer",
    "X-Robots-Tag": "noindex, nofollow, noarchive",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Permissions-Policy": "geolocation=(), camera=(), microphone=(), interest-cohort=()",
}

RESPONSES = {
    404: {"model": PublicTrackingError, "description": "No tracking information"},
    429: {"model": PublicTrackingError, "description": "Rate limited"},
}


def apply_public_headers(response: Response) -> None:
    for header, value in PUBLIC_HEADERS.items():
        response.headers[header] = value


def _public_lookup(
    db: PublicDb,
    client_key: str,
    response: Response,
    reference: str,
) -> PublicTrackingResult:
    """The single public policy boundary. Every public tracking path runs this body.

    No staff session, no permission check, no CSRF token, and no staff cookie is read or
    written anywhere on this path.

    The order is the contract:

    1. **Derive the client key** -- the directly observed peer, or the one shared bucket
       every unverified forwarded request lands in (DEC-0048). This is a dependency
       because it reads only the request scope; it touches nothing else.
    2. **Rate limit**, before the reference is looked at and before anything touches the
       database. Checking the format first would let an attacker learn which of their
       guesses are well formed for free, and would let malformed input bypass the limiter
       entirely.
    3. **Return 429 without a query.** Nothing below this point runs, and no dependency
       above it has read a row -- which is why the organization settings row is no longer
       resolved as a dependency (DEC-0059).
    4. **Normalize and validate strictly**, in application code. Only a complete,
       well-formed Solaris Shipment ID or package reference reaches the database. A value
       that is too long, empty, mis-shaped, or carrying extra separators fails here.
    5. **Answer identically on every failure.** An oversized reference, a malformed one,
       a well-formed unknown one, a draft, and a demo record in production all produce
       the same 404 status, body, message, and headers.
    6. **Only then** resolve against the database and read the organization's display
       timezone.
    """
    apply_public_headers(response)

    allowed, retry_after = rate_limiter.check(
        f"{RATE_LIMIT_BUCKET}:{client_key}",
        settings.public_tracking_rate_limit_attempts,
        settings.public_tracking_rate_limit_window_seconds,
    )
    if not allowed:
        public_tracking_service.log_lookup(
            reference, public_tracking_service.OUTCOME_RATE_LIMITED, client_key=client_key
        )
        raise RateLimitedError(RATE_LIMIT_MESSAGE, retry_after=retry_after)

    try:
        result, outcome = public_tracking_service.track(db, reference)
    except NotFoundError as error:
        public_tracking_service.log_lookup(
            reference,
            public_tracking_service.outcome_for(error),
            client_key=client_key,
        )
        raise error

    public_tracking_service.log_lookup(reference, outcome, client_key=client_key)
    return result


@router.get(
    "/track/{reference:path}",
    response_model=PublicTrackingResult,
    responses=RESPONSES,
    summary="Look up public tracking for a Solaris Shipment ID or package reference",
)
def track(
    db: PublicDb,
    client_key: PublicClientKey,
    response: Response,
    reference: str,
) -> PublicTrackingResult:
    """Public tracking lookup. See ``_public_lookup`` for the order of operations."""
    return _public_lookup(db, client_key, response, reference)


@router.get(
    "/track",
    response_model=PublicTrackingResult,
    responses=RESPONSES,
    include_in_schema=False,
    summary="Public tracking with no reference supplied",
)
def track_without_reference(
    db: PublicDb,
    client_key: PublicClientKey,
    response: Response,
) -> PublicTrackingResult:
    """``/track`` with nothing after it.

    Registered so the bare path answers with the same policy rather than with the
    framework's router 404 -- a different body, which would distinguish "you sent
    nothing" from "you sent something unknown". Excluded from the schema because it
    documents no useful operation: it exists so that one failure shape is genuinely one
    shape.
    """
    return _public_lookup(db, client_key, response, "")
