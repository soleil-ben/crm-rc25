"""Authenticated Customer Account shipment routes.

``GET /api/v1/account/shipments``
``GET /api/v1/account/shipments/{reference}``

Two routes, both reads, and **no mutation route exists on this surface**. Phase 11 adds no
``POST``, ``PATCH``, ``PUT`` or ``DELETE``, here or anywhere else: a customer cannot book,
cancel, edit or claim anything, and the absence is asserted by walking the route table
rather than by this paragraph.

**The order of operations is the contract**, and it is the same order the public surface
settled on in Phase 3 (DEC-0059) with one gate added:

1. **Privacy headers first**, so a response carries them whatever produced it.
2. **Session and identity** -- the existing Customer Account resolver, unchanged. A staff
   cookie resolves nothing here: different name, different table, different resolver.
3. **Rate limit**, keyed by the account, *before* the reference is parsed and before any
   ownership query runs. A malformed reference therefore cannot bypass the limiter, and a
   refused request issues **zero** database statements.
4. **Authorization** -- identity state, the effective link, and the linked customer's own
   state -- through the shared policy helper. Re-evaluated on every request; nothing is
   cached on the session row, so a suspension or a link revocation takes effect on the next
   request rather than at the next sign-in.
5. **Only then** the query, with ownership inside it.

**One failure shape.** A malformed reference, an unknown one, another customer's, a merged
or alias identifier, and an ineligible one all produce the same 404 with the same body and
the same headers. An unauthorized *account* -- pending, unlinked, archived customer -- gets
a 403 instead, and that distinction is safe because it is a fact about the caller's own
account, which they already know, and says nothing about whether any shipment exists.

**No cookie is set by either route.** Not a staff cookie, not a public one, not a Customer
Account one. These are reads; the session they run under was established elsewhere.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Query, Request, Response
from sqlalchemy.exc import OperationalError

from app.api.account.deps import (
    AccountClientKey,
    AccountDb,
    CurrentAccountSession,
    account_client_ip,
)
from app.core.account_security import opaque_digest, read_identity_bucket
from app.core.config import settings
from app.core.db import commit_with_retry
from app.core.logging import log_event
from app.core.public_reference import normalize_public_reference, reference_digest
from app.core.security import rate_limiter
from app.schemas.account_shipments import AccountShipmentDetail, AccountShipmentListPage
from app.services import customer_account_audit as audit
from app.services import customer_account_link_policy as link_policy
from app.services import customer_account_shipment_service as shipments
from app.services import public_tracking_service
from app.services.errors import NotFoundError, PermissionDeniedError, RateLimitedError

router = APIRouter(tags=["customer-account"])

logger = logging.getLogger("solaris.account_shipments")

#: Applied to every response on these two routes, success or failure. ``no-store`` is the
#: one that matters and is required by AC-CA-8.6: an authenticated shipment page must not
#: sit in a shared cache or a browser's back-forward cache where the next person at the
#: machine can read it. The rest repeat the application-wide headers at the route so a
#: failure raised before the handler -- a rate-limit refusal, a dependency error -- still
#: carries them.
ACCOUNT_HEADERS = {
    "Cache-Control": "no-store, no-cache, must-revalidate, private",
    "Pragma": "no-cache",
    "Referrer-Policy": "no-referrer",
    "X-Robots-Tag": "noindex, nofollow, noarchive",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Permissions-Policy": "geolocation=(), camera=(), microphone=(), interest-cohort=()",
}

#: What a caller whose account may not read shipment history is told. One sentence for every
#: reason -- pending approval, no link, a suspended identity whose session has not yet been
#: used, an archived or merged linked customer. The *reason* is an operational fact about
#: the CRM, and this surface does not narrate it (T-17).
NOT_AUTHORIZED_MESSAGE = (
    "Your account cannot view shipment history yet. Solaris Express will be in touch once "
    "your account review is complete."
)

RATE_LIMIT_MESSAGE = "Too many requests. Wait a moment and try again."

#: Outcome categories for the structured log. Aggregate metric names, never a reference.
OUTCOME_OK = "ok"
OUTCOME_NOT_AUTHORIZED = "not_authorized"
OUTCOME_NOT_FOUND = "not_found"
OUTCOME_RATE_LIMITED = "rate_limited"


def _apply_headers(response: Response) -> None:
    for header, value in ACCOUNT_HEADERS.items():
        response.headers[header] = value


def _log(
    *,
    identity_public_id: str,
    surface: str,
    outcome: str,
    digest: str | None = None,
    page_size: int | None = None,
    returned: int | None = None,
) -> None:
    """One structured line per request. Safe fields only, and the allowlist enforces it.

    What is here: a **digest** of the account reference, a bounded surface name, an outcome
    category, a keyed reference digest where there was a reference, and page-size metadata.
    What is deliberately not: the raw reference, the account reference itself, any carrier
    tracking number, any address, email or phone, any session or CSRF value, any part of the
    response body, any financial value, and **any filter value** -- OD-41's reference
    filter carries a Solaris reference, which is exactly the thing `_digest` exists to keep
    out of a log, and the route-group filter is a facet whose distribution says something
    about a customer's business.

    The account reference is digested rather than written out, although
    ``DATA_MODEL.md`` §9 permits it in an *audit payload*. The two artefacts travel
    differently: an audit row is staff-facing and access-controlled, while a log line goes
    to a file, a shipper and quite possibly a third-party search index. A stable,
    non-reversible digest correlates one session's requests exactly as well, which is the
    only thing an operator needs it for (instruction §13, "safe identity fingerprints").

    ``SafetyFilter`` drops any field not on ``app.core.logging.SAFE_FIELDS``, so this is not
    the only thing standing between these names and a log line -- but a field added here and
    not there would simply vanish, which is the right failure.
    """
    log_event(
        logger,
        logging.INFO,
        "account_shipment_read",
        identity_digest=opaque_digest(identity_public_id),
        surface=surface,
        outcome=outcome,
        reference_digest=digest or "none",
        page_size=page_size if page_size is not None else -1,
        returned=returned if returned is not None else -1,
    )


def _digest(raw_reference: str | None) -> str:
    """A keyed digest of a submitted reference, or ``"empty"``.

    The same construction the public surface uses, so the two can be correlated by an
    operator investigating a probe that hit both, and so neither writes an identifier into a
    log file, a log shipper, or somebody's log search index.
    """
    normalized = normalize_public_reference(raw_reference)
    return reference_digest(normalized, secret=settings.secret_key) if normalized else "empty"


def _commit_refusal_audit(db, *, identity_public_id: str, surface: str) -> bool:
    """Land a refusal's audit row, or say loudly that it could not be landed.

    **The refusal is the response; the audit row is a record of it.** If the record cannot
    be written the response must still be the one the design promises — one 404 for every
    way of asking wrongly, one 403 for every unauthorized account. A lock that turned a
    404 into a 500 would lose the audit row *and* break the property the whole route is
    built around, which is strictly worse than losing the row alone (DEC-0116).

    So a lock here is caught, the session is rolled back, and an operator-facing ERROR is
    logged carrying the same safe fields the audit row would have carried — identity
    digest, surface, outcome — so the loss is visible in the place somebody investigating
    a probe is already looking. Nothing else is swallowed: any other database error
    propagates, because it is not a timing problem and hiding it would hide a defect.

    The rows this can lose are the aggregate signal behind T-03's "repeated not-found
    results for one identity is a probing signal". Losing one under contention does not
    blunt an aggregate; returning a 500 instead would tell a prober something the 404
    does not.
    """
    try:
        commit_with_retry(db)
    except OperationalError:
        db.rollback()
        log_event(
            logger,
            logging.ERROR,
            "account_shipment_audit_unwritten",
            identity_digest=opaque_digest(identity_public_id),
            surface=surface,
            outcome="audit_write_failed",
            reference_digest="none",
            page_size=-1,
            returned=-1,
        )
        return False
    return True


def _limit_or_refuse(identity_public_id: str, surface: str) -> None:
    """The read bucket, consumed before anything else costs a query.

    Placed after the session resolves -- the bucket is keyed by the account, so there has to
    be one -- and before the link resolution, the reference parsing and every query. A
    refused request has therefore performed exactly the statements the session resolver
    needed and nothing more, which is what lets the "zero further statements" assertion be
    written at all.
    """
    allowed, retry_after = rate_limiter.check(
        read_identity_bucket(identity_public_id),
        settings.account_read_identity_attempts,
        settings.account_read_identity_window_seconds,
    )
    if not allowed:
        _log(identity_public_id=identity_public_id, surface=surface, outcome=OUTCOME_RATE_LIMITED)
        raise RateLimitedError(RATE_LIMIT_MESSAGE, retry_after=retry_after)


def _authorized_customer(db, request: Request, identity, surface: str):
    """Resolve the one canonical customer this identity may read, or refuse.

    Delegates entirely to ``customer_account_link_policy.resolve_readable_customer``: the
    ``status == 'active'`` predicate is written once, in that module, and this route does
    not hold a second copy of it.

    A refusal is audited and then raised. The audit row carries the *category*
    ``not_authorized``; the specific reason -- no link, two links, archived, merged --
    travels in the operator-facing log and never in the response.

    The audit write is committed on its own. A read request that refuses must still leave a
    record, and the session has nothing else pending, so this commits one row and nothing
    else. It is the only write either route performs, and it writes to ``audit_events``
    alone: no canonical table, and no Customer Account link mutation (T-07).
    """
    resolved = link_policy.resolve_readable_customer(db, identity)
    if resolved.authorized:
        return resolved.customer

    # Roll back before writing, which is `persist_refusal_audit`'s order and is here for
    # the same reason plus one more (DEC-0116).
    #
    # This transaction has already read -- the session, the identity, the link -- so it
    # holds a read snapshot. Adding the audit row and committing asks SQLite to *upgrade*
    # that to a write, and SQLite refuses an upgrade with `database is locked`
    # **immediately**, without consulting `busy_timeout`, if any other connection has
    # written since the read began. The refusal then leaves as a 500 rather than as the
    # 403 it is. Phase 12's browser suite hit it repeatedly with two contexts in play.
    #
    # `rollback()` discards the read snapshot and the courtesy `last_seen_at` touch, and
    # nothing else: this path has written nothing worth keeping. The audit row is then the
    # transaction's first statement, so there is no upgrade and `busy_timeout` applies as
    # documented.
    db.rollback()
    audit.shipment_access_denied(
        db,
        identity=identity,
        surface=surface,
        reason_code=audit.REASON_NOT_AUTHORIZED,
        ip_address=account_client_ip(request),
    )
    _commit_refusal_audit(db, identity_public_id=identity.public_id, surface=surface)
    _log(
        identity_public_id=identity.public_id,
        surface=surface,
        # The link-resolution reason is operator-facing and bounded; it is one of
        # `link_policy.REFUSAL_REASONS` and names no customer.
        outcome=f"{OUTCOME_NOT_AUTHORIZED}:{resolved.reason}",
    )
    raise PermissionDeniedError(NOT_AUTHORIZED_MESSAGE)


@router.get(
    "/shipments",
    response_model=AccountShipmentListPage,
    summary="The signed-in customer's own shipment history",
)
def list_shipments(
    request: Request,
    response: Response,
    db: AccountDb,
    session: CurrentAccountSession,
    client_key: AccountClientKey,
    status_group: str | None = Query(default=None),
    booked_from: str | None = Query(default=None),
    booked_to: str | None = Query(default=None),
    reference: str | None = Query(default=None),
    route_group: str | None = Query(default=None),
    q: str | None = Query(default=None),
    limit: int | None = Query(default=None),
    offset: int | None = Query(default=None),
) -> AccountShipmentListPage:
    """One page of the caller's own shipments.

    ``client_key`` is declared and unused on purpose: it is the dependency that reads the
    peer address without believing a forwarding header, and declaring it keeps the route's
    dependency graph the same shape as the rest of this surface's. The **bucket** is keyed
    by the account rather than the address, for the reason ``read_identity_bucket`` gives.

    Query parameters are the filters `SHIPMENT_ALLOWLISTS.md` §3.2 to §3.4 approve, plus
    paging. There is no sort parameter and no column a caller can name: the ordering and
    the searched columns are fixed in the service, so there is nothing to inject into.

    ``reference`` and ``route_group`` are OD-41's two additions and are **exact match**: a
    value that is not a Solaris shipment reference matches nothing rather than matching
    partially, and a value outside the route vocabulary is refused before a statement is
    built. ``q`` is UAT round 10's keyword search (DEC-0156): partial, case- and
    accent-insensitive, over the Solaris Shipment ID, the booking reference and the origin
    and destination cities, with its ``LIKE`` wildcards escaped and the value bound as a
    parameter. All three are validated by ``parse_filters`` for the reason the other two
    are, and all are applied *after* the ownership clause, so a filter can only narrow the
    caller's own rows. The keyword is never logged.

    The string parameters carry **no** FastAPI length constraint, for the reason the path
    parameter carries none. A query constraint is validated before the handler runs and
    answers with FastAPI's own 422 -- a body shaped ``{"detail": [...]}`` that echoes the
    submitted value back, rather than this surface's ``{"code", "message", "field"}``. Two
    different malformed-filter shapes on one route is the same defect as two different
    not-found shapes, and the first version of this file had it: a nineteen-character date
    tripped the length constraint while a nine-character one reached the parser.

    The bound did not disappear. ``parse_filters`` rejects anything oversized before it
    parses anything, so the answer is one shape and the parser never sees a megabyte of
    query string.
    """
    _apply_headers(response)
    identity, _ = session
    _limit_or_refuse(identity.public_id, "list")
    customer = _authorized_customer(db, request, identity, "list")

    timezone_name = public_tracking_service.display_timezone(db)
    filters = shipments.parse_filters(
        status_group=status_group,
        booked_from=booked_from,
        booked_to=booked_to,
        reference=reference,
        route_group=route_group,
        q=q,
        limit=limit,
        offset=offset,
        timezone_name=timezone_name,
    )
    page = shipments.list_shipments(
        db, customer=customer, filters=filters, timezone_name=timezone_name
    )
    _log(
        identity_public_id=identity.public_id,
        surface="list",
        outcome=OUTCOME_OK,
        page_size=filters.limit,
        returned=len(page.items),
    )
    return page


@router.get(
    "/shipments/{reference:path}",
    response_model=AccountShipmentDetail,
    summary="One of the signed-in customer's own shipments",
)
def shipment_detail(
    request: Request,
    response: Response,
    db: AccountDb,
    session: CurrentAccountSession,
    client_key: AccountClientKey,
    reference: str,
) -> AccountShipmentDetail:
    """One shipment, by Solaris Shipment ID, if and only if it belongs to the caller.

    ``reference`` is a **catch-all path parameter with no length or pattern constraint**,
    and both halves of that are Phase 3's correction (DEC-0059) applied here rather than
    rediscovered.

    *No constraint*, because a FastAPI path constraint is validated before the handler body
    runs and answers with a detailed 422 naming the constraint -- a different body from the
    generic 404, and therefore a way to tell "malformed" from "unknown" apart without
    reaching the application's policy at all. The bound did not disappear: it lives in
    ``parse_public_reference``, where exceeding it means *not a Solaris reference*.

    *Catch-all*, because ``{reference}`` does not match a value containing a separator.
    ``/shipments/a/b`` and ``/shipments/`` would miss the route entirely and fall through to
    Starlette's router 404, whose body is ``{"detail": "Not Found"}`` -- a second, different
    failure shape, reachable for free, on a route whose whole design is that every failure
    looks identical. The first version of this file had exactly that defect and
    ``tests/test_account_shipment_detail.py`` found it.

    The catch-all is scoped to ``/shipments/`` inside a router mounted at
    ``/api/v1/account``, so it cannot shadow another route; the test suite asserts that
    rather than trusting it.

    A refusal is audited with a keyed digest of the reference and no reference.
    """
    _apply_headers(response)
    identity, _ = session
    _limit_or_refuse(identity.public_id, "detail")
    customer = _authorized_customer(db, request, identity, "detail")

    digest = _digest(reference)
    try:
        shipment = shipments.resolve_owned_shipment(db, customer=customer, raw_reference=reference)
    except NotFoundError:
        # "No such shipment", "that one is a draft", "that one is somebody else's" and
        # "that is not a reference at all" arrive here as one exception and leave as one
        # response. The audit row records the category and the digest; it records neither
        # which of them happened nor anything about the row that was not returned.
        #
        # Rolled back first, for the reason `_authorized_customer` gives: this request has
        # read and the audit row must not be a lock upgrade (DEC-0116). Nothing is lost —
        # a lookup that found nothing has nothing to discard.
        db.rollback()
        audit.shipment_access_denied(
            db,
            identity=identity,
            surface="detail",
            reason_code=audit.REASON_SHIPMENT_NOT_FOUND,
            reference_digest=digest,
            ip_address=account_client_ip(request),
        )
        _commit_refusal_audit(db, identity_public_id=identity.public_id, surface="detail")
        _log(
            identity_public_id=identity.public_id,
            surface="detail",
            outcome=OUTCOME_NOT_FOUND,
            digest=digest,
        )
        raise

    timezone_name = public_tracking_service.display_timezone(db)
    detail = shipments.build_detail(db, shipment, timezone_name=timezone_name)
    _log(
        identity_public_id=identity.public_id,
        surface="detail",
        outcome=OUTCOME_OK,
        digest=digest,
    )
    return detail
