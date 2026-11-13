"""Customer Account routes.

Eight endpoints, and the order of operations inside each one is as much of the design as
the endpoint itself.

**Rate limits run before the body is parsed.** Every public handler here takes the raw
``Request``. A FastAPI body model would be validated *before* the endpoint function runs,
which means a malformed request would answer with a detailed 422 naming the constraint and
would never touch the limiter -- so an attacker who wanted unlimited attempts would simply
send invalid JSON. Phase 3 corrected exactly this on the public surface (DEC-0059), and the
correction is reused rather than rediscovered. The consequence worth stating: a refused
request issues **zero** database statements, which
`tests/test_account_rate_limits.py` asserts by counting statements on the engine.

**Every answer on the enumeration-sensitive paths is the same answer.** Register, resend and
forgot-password return one status code and one body whether the address is new, already
registered, verified, approved, suspended, suppressed, or refused by the per-address bucket.
The per-address refusal deliberately returns the *ordinary generic body* rather than a 429:
a 429 that only appeared for addresses that exist would itself be the enumeration oracle
(`RATE_LIMITS_AND_ABUSE.md` section 3).

**No route reads a shipment, writes a canonical customer, or links an identity.** There is
no code path from here to `customers`, and `tests/test_account_no_canonical_write.py` asserts
it against a populated database rather than against this sentence.
"""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlsplit

from fastapi import APIRouter, Request, Response, status
from pydantic import ValidationError as PydanticValidationError

from app.api.account.deps import (
    AccountClientKey,
    AccountDb,
    CurrentAccountSession,
    account_client_ip,
)
from app.core.account_enums import CUSTOMER_SETTABLE_TOPIC_VALUES, LinkStatus
from app.core.account_fields import (
    ABSOLUTE_MAX_VALUE_LENGTH,
    ALLOWED_FIELD_KEYS,
    FieldRejected,
    NormalizedField,
    normalize_field,
)
from app.core.account_security import (
    register_address_bucket,
    register_ip_bucket,
    resend_address_bucket,
    resend_ip_bucket,
    reset_address_bucket,
    reset_ip_bucket,
    token_ip_bucket,
)
from app.core.config import account_delivery_blockers, account_registration_blockers, settings
from app.core.db import commit_with_retry
from app.core.normalization import INVALID_EMAIL_MESSAGE, normalize_email
from app.core.security import generate_token, rate_limiter
from app.models import CustomerDataProposal, CustomerIdentityLink
from app.schemas.account import (
    AccountMeResponse,
    AccountMessageResponse,
    AccountSessionResponse,
    PasswordForgotRequest,
    PasswordResetRequest,
    RegistrationRequest,
    ResendVerificationRequest,
    SignInRequest,
    VerifyEmailRequest,
)
from app.services import customer_account_audit as audit
from app.services import (
    customer_account_link_policy,
    customer_account_profile_service,
    customer_auth_service,
    customer_identity_service,
)
from app.services.errors import (
    AuthenticationError,
    DomainError,
    RateLimitedError,
    ValidationError,
)

router = APIRouter(tags=["customer-account"])

#: Returned when the surface is configured such that mail cannot be delivered. A 503 rather
#: than a 500: the request was fine, the deployment is not ready, and the distinction is
#: what an operator needs. The body says nothing about *why*, because the reason is a
#: deployment internal (OD-34, OD-37).
UNAVAILABLE_MESSAGE = "Customer accounts are not available yet. Please contact Solaris Express."


class _AccountUnavailable(DomainError):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    code = "account_unavailable"


class _BadRequest(DomainError):
    """A malformed body, answered without saying which part was malformed.

    Distinct from ``ValidationError``: that one names a field, and naming a field is safe
    only for a *format* problem on a field the caller sent. A body that is not JSON at all
    gets no detail, because there is nothing safe to be detailed about.
    """

    status_code = status.HTTP_400_BAD_REQUEST
    code = "invalid_request"


# --- Request plumbing ---------------------------------------------------------


async def _read_json(request: Request) -> dict[str, Any]:
    """Read and parse the body, bounded, after the rate limits have already been checked.

    The bound is enforced here rather than by a middleware constraint for the same reason
    the limiter runs first: a body refused before the handler starts is a body that never
    consumed an attempt.
    """
    raw = await request.body()
    if len(raw) > settings.account_max_body_bytes:
        raise _BadRequest("That request is too large.")
    if not raw:
        raise _BadRequest("A request body is required.")
    try:
        parsed = json.loads(raw)
    except (ValueError, UnicodeDecodeError) as exc:
        raise _BadRequest("That request could not be read.") from exc
    if not isinstance(parsed, dict):
        raise _BadRequest("That request could not be read.")
    return parsed


def _parse(model: type, payload: dict[str, Any]):
    """Validate a parsed body against a schema, turning Pydantic's report into ours.

    Pydantic's default error body is a list of dictionaries carrying the input value back to
    the caller. On this surface that would echo a password into a response, so the errors are
    re-shaped to ``(field, message)`` pairs and the input is dropped.
    """
    try:
        return model(**payload)
    except PydanticValidationError as exc:
        first = exc.errors()[0]
        field = ".".join(str(part) for part in first.get("loc", ())) or None
        raise ValidationError("That submission could not be accepted.", field=field) from exc
    except TypeError as exc:
        raise _BadRequest("That request could not be read.") from exc


def _check_origin(request: Request) -> None:
    """Refuse a cross-origin browser POST to an unauthenticated route.

    Register, sign-in, forgot-password and token redemption carry no session, so there is no
    session row to bind a CSRF token to and issuing a pre-session CSRF cookie to anonymous
    visitors would add a cookie for every visitor and protect nothing
    (`SESSION_COOKIES_AND_CSRF.md` section 5.1).

    A **present** ``Origin`` or ``Referer`` must match the configured application origin. An
    **absent** one is allowed: browsers send ``Origin`` on cross-origin POSTs, so absence
    means a non-browser client, and a non-browser client is not a CSRF vector -- CSRF needs
    ambient cookie authority, and none of these routes has any.
    """
    allowed = {origin.rstrip("/") for origin in settings.cors_origin_list}
    if not allowed:
        return
    for header in ("origin", "referer"):
        value = request.headers.get(header)
        if not value:
            continue
        split = urlsplit(value)
        if not split.scheme or not split.netloc:
            continue
        if f"{split.scheme}://{split.netloc}" not in allowed:
            raise _BadRequest("That request could not be read.")
        return


def _limit(bucket: str, limit: int, window: int) -> bool:
    """Consume one attempt. ``False`` means refused."""
    allowed, retry_after = rate_limiter.check(bucket, limit, window)
    if not allowed:
        _limit.last_retry_after = retry_after  # type: ignore[attr-defined]
    return allowed


def _throttled(bucket_retry_after: int = 60) -> RateLimitedError:
    return RateLimitedError(
        "Too many requests. Wait a moment and try again.", retry_after=bucket_retry_after
    )


def _require_delivery(blockers: list[str]) -> None:
    if blockers:
        raise _AccountUnavailable(UNAVAILABLE_MESSAGE)


def _normalized_email_or_refuse(raw: object) -> tuple[str, str]:
    """``(entered, normalized)``. A format failure only -- this performs no lookup."""
    if not isinstance(raw, str):
        raise ValidationError(INVALID_EMAIL_MESSAGE, field="email")
    try:
        entered, normalized = normalize_email(raw)
    except ValueError as exc:
        raise ValidationError(INVALID_EMAIL_MESSAGE, field="email") from exc
    if entered is None or normalized is None:
        raise ValidationError(INVALID_EMAIL_MESSAGE, field="email")
    return entered, normalized


def _normalize_customer_fields(submitted: dict[str, Any]) -> list[NormalizedField]:
    """Check every submitted key against the allowlist and normalize what survives.

    A key outside the allowlist is refused by name, which is safe: the allowlist is a
    property of the form, not of any account, so saying "that field is not accepted here"
    discloses nothing about anybody.
    """
    if len(submitted) > len(ALLOWED_FIELD_KEYS):
        raise _BadRequest("That submission could not be accepted.")
    context = {
        key: value
        for key, value in submitted.items()
        if isinstance(value, str) and len(value) <= ABSOLUTE_MAX_VALUE_LENGTH
    }
    normalized: list[NormalizedField] = []
    for key, value in submitted.items():
        if not isinstance(key, str):
            raise _BadRequest("That submission could not be accepted.")
        try:
            field = normalize_field(key, value, context=context)
        except FieldRejected as exc:
            raise ValidationError(exc.message, field=exc.field_key) from exc
        if field is not None:
            normalized.append(field)
    return normalized


#: The address parts "billing is the same as the address above" copies. The pickup-only parts --
#: who the driver asks for, a phone, a note -- have no billing counterpart.
_BILLING_COPIED_PARTS = (
    "address_line1",
    "address_line2",
    "city",
    "province_state",
    "postal_code",
    "country_code",
)
_SHIPPING_PREFIX = "pickup_address.1."
_BILLING_PREFIX = "billing_address."

BILLING_SAME_WITH_BILLING = (
    "Send either a billing address or “Billing address is the same as the address above”, not both."
)

#: The parts of an address registration requires (UAT round 9), in screen order, so the
#: first one missing is the first one a person would reach. Line 2 stays optional, and so,
#: since UAT round 11, does the postal code, for every country (DEC-0159): a blank one is
#: never refused, and one that is typed is held only to the field's 30-character bound.
REQUIRED_ADDRESS_PARTS = ("country_code", "address_line1", "city", "province_state")


def address_part_missing_message(part: str, *, billing: bool) -> str:
    """The sentence shown beside a required address part left empty (UAT rounds 9, 11).

    The registration form says the same words (``RegisterPage.jsx``). A billing part says
    "billing" so the error summary, which lists both blocks, is unambiguous.
    """
    which = "billing " if billing else ""
    if part == "country_code":
        return f"Choose the {which}country."
    if part == "address_line1":
        return f"Enter the {which}street address (address line 1)."
    if part == "city":
        return f"Enter the {which}city."
    if part == "province_state":
        return f"Enter the {which}province or state."
    raise ValueError(f"{part} is not a required address part")


def _filled(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _require_address(submitted: dict[str, Any], prefix: str, *, billing: bool) -> None:
    for part in REQUIRED_ADDRESS_PARTS:
        key = f"{prefix}{part}"
        if not _filled(submitted.get(key)):
            raise ValidationError(address_part_missing_message(part, billing=billing), field=key)


def _apply_billing_choice(submitted: dict[str, Any], *, same: bool) -> dict[str, Any]:
    """Check the two registration addresses and resolve the billing box (UAT rounds 8-11).

    Checked here, before the allowlist, so what reaches the proposal is an ordinary set of
    ``billing_address.*`` keys and nothing downstream has to know the box existed:

    * the address (``pickup_address.1``) must have a country, street line, city and
      province or state (UAT round 9); the postal code is optional (UAT round 11). The
      first part missing is refused by name;
    * **same**: no billing key may arrive with it -- a hidden billing field still being
      sent is a client defect, and silently preferring one would hide it -- and the
      address parts are copied over;
    * **not same**: the billing address needs the same four parts, because the customer
      has said the two differ.
    """
    _require_address(submitted, _SHIPPING_PREFIX, billing=False)
    if same:
        if any(isinstance(key, str) and key.startswith(_BILLING_PREFIX) for key in submitted):
            raise ValidationError(BILLING_SAME_WITH_BILLING, field="billing_same_as_shipping")
        resolved = dict(submitted)
        for part in _BILLING_COPIED_PARTS:
            value = submitted.get(f"{_SHIPPING_PREFIX}{part}")
            if value is not None:
                resolved[f"{_BILLING_PREFIX}{part}"] = value
        return resolved
    _require_address(submitted, _BILLING_PREFIX, billing=True)
    return submitted


def _notification_topics(submitted: list[Any]) -> dict[str, bool]:
    """Topics the customer switched on. Anything not settable is refused, not ignored.

    Silently dropping an unsettable topic would let a form claim to have switched off
    ``account_security`` and appear to succeed. Refusing says what actually happened.
    """
    topics: dict[str, bool] = {}
    if len(submitted) > len(CUSTOMER_SETTABLE_TOPIC_VALUES):
        raise ValidationError("That preference is not available.", field="notification_topics")
    for topic in submitted:
        if not isinstance(topic, str) or topic not in CUSTOMER_SETTABLE_TOPIC_VALUES:
            raise ValidationError("That preference is not available.", field="notification_topics")
        topics[topic] = True
    return topics


# --- Cookies ------------------------------------------------------------------


def _set_session_cookies(response: Response, session_token: str, csrf_token: str) -> None:
    """Both Customer Account cookies, under their own names.

    ``Path`` is ``/`` rather than ``/api/v1/account``: a narrower path looks like defence in
    depth and is not -- same-origin script can read cookies for any path -- while breaking
    the verification and reset landing pages, which are not under the API prefix. Separation
    is enforced by the distinct names and the distinct server-side store, neither of which
    depends on the browser honouring anything (`SESSION_COOKIES_AND_CSRF.md` section 3).
    """
    max_age = settings.account_session_absolute_hours * 3600
    response.set_cookie(
        settings.account_session_cookie_name,
        session_token,
        max_age=max_age,
        httponly=True,
        secure=settings.cookie_secure,
        samesite=settings.cookie_samesite,
        domain=settings.cookie_domain,
        path="/",
    )
    # Readable, because the page has to echo it in a header (DEC-0005).
    response.set_cookie(
        settings.account_csrf_cookie_name,
        csrf_token,
        max_age=max_age,
        httponly=False,
        secure=settings.cookie_secure,
        samesite=settings.cookie_samesite,
        domain=settings.cookie_domain,
        path="/",
    )


def _clear_session_cookies(response: Response) -> None:
    for name in (settings.account_session_cookie_name, settings.account_csrf_cookie_name):
        response.delete_cookie(name, path="/", domain=settings.cookie_domain)


# --- Routes -------------------------------------------------------------------


@router.post("/register", response_model=AccountMessageResponse)
async def register(
    request: Request,
    db: AccountDb,
    client_key: AccountClientKey,
) -> AccountMessageResponse:
    """Create a pending identity and a pending proposal, or do nothing, indistinguishably.

    Order: origin check, per-IP limit, body, field allowlist, per-address limit, then the
    service. The per-IP limit is consumed before the body is read, so a malformed body still
    costs an attempt; the per-address limit is consumed before any query runs, so a refused
    request touches no table.
    """
    _check_origin(request)
    _require_delivery(account_registration_blockers(settings))

    if not _limit(
        register_ip_bucket(client_key),
        settings.account_register_ip_attempts,
        settings.account_register_ip_window_seconds,
    ):
        # Still a 429 with ``Retry-After`` (RATE_LIMITS_AND_ABUSE.md §3, "429, generic
        # body"), but the message is the registration sentence itself, not "Too many
        # requests" (UAT round 3). The screen sends a refused registration to the same
        # confirmation as an accepted one, so what a person reads never says whether the
        # limit, the address or nothing at all decided the outcome.
        raise RateLimitedError(
            customer_identity_service.GENERIC_REGISTRATION_MESSAGE,
            retry_after=getattr(_limit, "last_retry_after", 60),
        )

    payload = _parse(RegistrationRequest, await _read_json(request))
    entered, normalized_email = _normalized_email_or_refuse(payload.email)

    if not (payload.accept_terms and payload.accept_privacy):
        # Required, and refused when absent (OD-37). Not a default, not a pre-check.
        raise ValidationError(
            "Accept the terms and the privacy notice to continue.", field="accept_terms"
        )

    customer_auth_service.validate_password(payload.password)
    customer_auth_service.confirm_password(payload.password, payload.password_confirmation)
    fields = _normalize_customer_fields(
        _apply_billing_choice(payload.customer, same=payload.billing_same_as_shipping)
    )
    topics = _notification_topics(payload.notification_topics)

    if not _limit(
        register_address_bucket(normalized_email),
        settings.account_register_address_attempts,
        settings.account_register_address_window_seconds,
    ):
        # The ordinary body, no message sent, no query issued. A 429 here would appear only
        # for addresses somebody kept trying, which is an oracle by another name.
        return AccountMessageResponse(
            message=customer_identity_service.GENERIC_REGISTRATION_MESSAGE
        )

    customer_identity_service.register(
        db,
        email_normalized=normalized_email,
        email_entered=entered,
        password=payload.password,
        fields=fields,
        notification_topics=topics,
        terms_version=settings.account_terms_version,
        privacy_version=settings.account_privacy_version,
        # OD-71: the emails of a registration are in the language it was made in.
        presented_language=customer_identity_service.preferred_language_of(fields),
        idempotency_key=payload.idempotency_key or generate_token(),
        request_ip=account_client_ip(request),
    )
    commit_with_retry(db)
    return AccountMessageResponse(message=customer_identity_service.GENERIC_REGISTRATION_MESSAGE)


@router.post("/verify-email", response_model=AccountMessageResponse)
async def verify_email(
    request: Request,
    db: AccountDb,
    client_key: AccountClientKey,
) -> AccountMessageResponse:
    """Redeem a verification token. One answer for success, one for every kind of failure.

    A POST rather than a GET, and the token in the body rather than the path: a GET that
    mutates is a CSRF hole no token can close, and a token in a path is a token in every
    proxy log and browser history entry between the customer and here.
    """
    _check_origin(request)
    if not _limit(
        token_ip_bucket(client_key),
        settings.account_token_ip_attempts,
        settings.account_token_ip_window_seconds,
    ):
        raise _throttled(getattr(_limit, "last_retry_after", 60))

    payload = _parse(VerifyEmailRequest, await _read_json(request))
    identity = customer_identity_service.verify_email(
        db, token=payload.token, request_ip=account_client_ip(request)
    )
    commit_with_retry(db)
    if identity is None:
        raise ValidationError(customer_identity_service.GENERIC_TOKEN_FAILURE, field="token")
    return AccountMessageResponse(message="Email confirmed. Your account is waiting for review.")


@router.post("/verification/resend", response_model=AccountMessageResponse)
async def resend_verification(
    request: Request,
    db: AccountDb,
    client_key: AccountClientKey,
) -> AccountMessageResponse:
    """Issue a replacement verification token, or quietly do nothing. Same answer either way.

    Nothing in the response, the status code or the headers differs between an unknown
    address, an unverified one, a verified one, an approved one, a suspended one and a
    suppressed one.
    """
    _check_origin(request)
    _require_delivery(account_delivery_blockers(settings))

    if not _limit(
        resend_ip_bucket(client_key),
        settings.account_resend_ip_attempts,
        settings.account_resend_ip_window_seconds,
    ):
        # A 429 with ``Retry-After`` carrying the resend's own ordinary sentence, as
        # registration and reset do (owner decision, 2026-10-15). The screen goes to the
        # same confirmation as an accepted request; nothing on it says "too many".
        raise RateLimitedError(
            customer_identity_service.GENERIC_REGISTRATION_MESSAGE,
            retry_after=getattr(_limit, "last_retry_after", 60),
        )

    payload = _parse(ResendVerificationRequest, await _read_json(request))
    _, normalized_email = _normalized_email_or_refuse(payload.email)

    if _limit(
        resend_address_bucket(normalized_email),
        settings.account_resend_address_attempts,
        settings.account_resend_address_window_seconds,
    ):
        customer_identity_service.resend_verification(
            db, email_normalized=normalized_email, request_ip=account_client_ip(request)
        )
        commit_with_retry(db)
    return AccountMessageResponse(message=customer_identity_service.GENERIC_REGISTRATION_MESSAGE)


@router.post("/sign-in", response_model=AccountSessionResponse)
async def sign_in(
    request: Request,
    response: Response,
    db: AccountDb,
    client_key: AccountClientKey,
) -> AccountSessionResponse:
    """Open a Customer Account session. Every refusal says the same thing.

    The session token is always new -- there is no path that reuses an existing row -- which
    is the rotation session fixation needs (T-14).
    """
    _check_origin(request)
    payload = _parse(SignInRequest, await _read_json(request))
    _, normalized_email = _normalized_email_or_refuse(payload.email)

    # Both buckets, before the identity lookup.
    customer_auth_service.check_sign_in_rate_limits(client_key, normalized_email)

    try:
        identity, session_token, csrf_token = customer_auth_service.authenticate(
            db,
            email_normalized=normalized_email,
            password=payload.password,
            ip_address=account_client_ip(request),
            user_agent=request.headers.get("user-agent"),
        )
    except AuthenticationError:
        # A refusal is still committed: its ``sign_in_failed`` audit row, the identity's
        # failure count and any lockout are what the refusal is *for*. Without this the
        # session closed uncommitted and all three were rolled back, so the per-identity
        # lockout never engaged over HTTP (found in UAT round 9).
        commit_with_retry(db)
        raise
    commit_with_retry(db)
    _set_session_cookies(response, session_token, csrf_token)
    return AccountSessionResponse(
        account_reference=identity.public_id,
        status=identity.status,
        email_verified=identity.email_verified_at is not None,
        csrf_token=csrf_token,
    )


@router.post("/sign-out", response_model=AccountMessageResponse)
def sign_out(
    request: Request,
    response: Response,
    db: AccountDb,
    session: CurrentAccountSession,
) -> AccountMessageResponse:
    """Revoke the session server-side, then clear the cookies.

    In that order, and both halves. Clearing a cookie is not a sign-out: a copy of the value
    taken before it was cleared would still resolve (`SESSION_COOKIES_AND_CSRF.md` section 8).
    """
    identity, record = session
    customer_auth_service.revoke_session(db, record, reason_code="sign_out")
    audit.signed_out(db, identity=identity, ip_address=account_client_ip(request))
    commit_with_retry(db)
    _clear_session_cookies(response)
    return AccountMessageResponse(message="Signed out.")


@router.post("/password/forgot", response_model=AccountMessageResponse)
async def password_forgot(
    request: Request,
    db: AccountDb,
    client_key: AccountClientKey,
) -> AccountMessageResponse:
    """Request a password reset. Identical response for a known and an unknown address."""
    _check_origin(request)
    _require_delivery(account_delivery_blockers(settings))

    if not _limit(
        reset_ip_bucket(client_key),
        settings.account_reset_ip_attempts,
        settings.account_reset_ip_window_seconds,
    ):
        # A 429 with ``Retry-After``, carrying the ordinary recovery sentence rather than
        # "Too many requests" (UAT round 4, as registration since UAT round 3). The screen
        # sends it to the same confirmation as an accepted request.
        raise RateLimitedError(
            customer_identity_service.GENERIC_RECOVERY_MESSAGE,
            retry_after=getattr(_limit, "last_retry_after", 60),
        )

    payload = _parse(PasswordForgotRequest, await _read_json(request))
    _, normalized_email = _normalized_email_or_refuse(payload.email)

    if _limit(
        reset_address_bucket(normalized_email),
        settings.account_reset_address_attempts,
        settings.account_reset_address_window_seconds,
    ):
        customer_identity_service.request_password_reset(
            db, email_normalized=normalized_email, request_ip=account_client_ip(request)
        )
        commit_with_retry(db)
    return AccountMessageResponse(message=customer_identity_service.GENERIC_RECOVERY_MESSAGE)


@router.post("/password/reset", response_model=AccountMessageResponse)
async def password_reset(
    request: Request,
    response: Response,
    db: AccountDb,
    client_key: AccountClientKey,
) -> AccountMessageResponse:
    """Complete a password reset: consume the token, set the password, end every session.

    All four together or none: the token is consumed, the password replaced, every Customer
    Account session revoked, and every other outstanding reset token invalidated. Revoking
    the sessions is the point -- somebody resetting a password may be doing it because an
    attacker holds a live one, and leaving it alive would make the reset cosmetic.

    Staff sessions are untouched. Not by a check: by there being no code path from here to
    ``user_sessions``.
    """
    _check_origin(request)
    if not _limit(
        token_ip_bucket(client_key),
        settings.account_token_ip_attempts,
        settings.account_token_ip_window_seconds,
    ):
        raise _throttled(getattr(_limit, "last_retry_after", 60))

    payload = _parse(PasswordResetRequest, await _read_json(request))
    customer_auth_service.validate_password(payload.password)
    customer_auth_service.confirm_password(payload.password, payload.password_confirmation)

    identity = customer_identity_service.complete_password_reset(
        db,
        token=payload.token,
        password=payload.password,
        request_ip=account_client_ip(request),
    )
    commit_with_retry(db)
    if identity is None:
        raise ValidationError(customer_identity_service.GENERIC_TOKEN_FAILURE, field="token")
    # The caller is not signed in by this. A reset proves control of a mailbox, and turning
    # that straight into a session would make the mailbox the credential.
    _clear_session_cookies(response)
    return AccountMessageResponse(message="Password updated. Sign in with your new password.")


@router.get("/me", response_model=AccountMeResponse)
def account_me(db: AccountDb, session: CurrentAccountSession) -> AccountMeResponse:
    """The caller's own account state. **No customer data and no shipment data.**

    This is the pending-account status page `IDENTITY_AND_AUTHORIZATION.md` section 4
    describes: a signed-in customer waiting for review needs to be told where their
    application stands, and telling them requires authenticating them. It reaches exactly
    two things -- their account state, and whether a proposal of theirs is waiting.

    **Phase 10 made ``linked`` real; Phase 11 makes ``shipment_history_available`` real.**
    Both are now answered rather than asserted, and the second is deliberately **not**
    derived from the first: ``linked`` is "a link row names me", while availability is the
    full authorization the shipment routes actually apply -- an ``active`` identity, exactly
    one effective link, and a linked customer that is neither archived nor merged. Deriving
    one from the other would let this endpoint report "available" for an account the
    shipment routes then refuse, which is the response telling a lie a screen would repeat.

    It is answered by the same helper the routes use, so the two cannot disagree. It is a
    boolean about the caller's own account and carries no count, no date and no customer
    reference -- a count of matching shipments is itself an enumeration oracle
    (`SHIPMENT_ALLOWLISTS.md` §6), and the disclosure figures stay staff-facing.

    **``status`` already distinguishes all five lifecycle states**, so nothing here needed
    widening for them. In practice only two are reachable: a session exists only for
    ``pending_approval`` and ``active``, and rejection, suspension and deactivation each
    revoke every session and refuse sign-in. A rejected applicant therefore reads no
    status at all -- and deliberately gets no unauthenticated endpoint to read one from,
    because "tell me the state of the account for this address" is an enumeration oracle
    whatever it answers (T-02). The deferred need is recorded in `PROJECT_STATUS.md`.

    ``status_reason_code`` is **not** the rejection reason. A rejected identity holds one,
    and it is never read here because a rejected identity cannot authenticate; the field
    carries a code a screen turns into a neutral sentence, never prose about another
    record (`STATE_MACHINES.md` section 1, transition 5).
    """
    identity, _ = session
    pending = db.scalar(
        CustomerDataProposal.__table__.select()
        .with_only_columns(CustomerDataProposal.id)
        .where(
            CustomerDataProposal.identity_id == identity.id,
            CustomerDataProposal.status == "pending",
        )
        .limit(1)
    )
    # A boolean about the caller's own account. **Not** the customer id, which OD-27 and
    # the Phase 10 instruction both keep off this surface: the account holder has no use
    # for an internal CRM reference and publishing one would make it a value to guess at.
    linked = (
        db.scalar(
            CustomerIdentityLink.__table__.select()
            .with_only_columns(CustomerIdentityLink.id)
            .where(
                CustomerIdentityLink.identity_id == identity.id,
                CustomerIdentityLink.status == LinkStatus.ACTIVE.value,
            )
            .limit(1)
        )
        is not None
    )
    readable = customer_account_link_policy.resolve_readable_customer(db, identity)
    return AccountMeResponse(
        account_reference=identity.public_id,
        status=identity.status,
        email_verified=identity.email_verified_at is not None,
        linked=linked,
        shipment_history_available=readable.authorized,
        # The same helper the profile reads, so the two cannot disagree (UAT round 3). The
        # language is the only thing taken from the customer row; nothing else of it is
        # read onto this response.
        preferred_language=customer_account_profile_service.account_language(
            identity, readable.customer
        ),
        status_reason_code=identity.status_reason_code,
        has_pending_proposal=pending is not None,
    )
