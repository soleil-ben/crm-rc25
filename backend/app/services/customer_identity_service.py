"""Registration, verification, resend, password recovery, and the identity lifecycle.

The rule that shapes every function here: **this surface has no canonical write path**
(OD-23, DEC-0092). Registration writes ``customer_identities``, ``customer_data_proposals``,
``customer_data_proposal_fields``, ``customer_terms_acknowledgements``,
``customer_notification_preferences`` and ``customer_registration_attempts``. It does not
write ``customers``, ``customer_addresses``, ``consent_events`` or ``contact_suppressions``,
not even when the submitted email matches an existing customer exactly. The worst a bug in
here can do is create a bad proposal that a person then declines.

The second rule: **every outcome looks the same from outside.** A new address, an address
that already has an unverified account, one that is verified and waiting, one that was
approved, one that was suspended, and a refused rate limit all produce one response with
one status code and one body (OD-23, T-02). The distinctions are real and
are recorded in the audit log; none of them is a sentence the registrant reads. Functions
here therefore return an internal ``RegistrationOutcome`` and the route discards it.

The third rule, since UAT round 6: **a suppression blocks marketing email and nothing
else.** Every message sent from here -- verification, the registration-attempt notice,
password reset -- is transactional account email, and none of them reads
``contact_suppressions`` (owner decision, 2026-10-15). A suppressed address registers,
verifies and recovers like any other; the suppression keeps its effect on marketing
eligibility, and nothing here mentions it.

The fourth rule: **duplicate detection is reused and never reported.**
``app.core.normalization`` produces the same ``email_normalized``, ``phone_e164`` and
``name_match_key`` for a proposal that the Staff Portal produces for a staff-entered
customer, which is what makes "the same customer" mean the same thing on both surfaces. What
this surface may never do is *report* the result: scores, matches and counts are staff-facing
only (T-02), and nothing in this module so much as computes one -- Phase 10's reviewer runs
the existing duplicate review against the stored normalized values.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.account_enums import (
    CUSTOMER_SETTABLE_TOPIC_VALUES,
    IdentityStatus,
    LinkStatus,
    NotificationChannel,
    ProposalKind,
    ProposalStatus,
    RegistrationOutcome,
    TermsDocumentKind,
    TokenPurpose,
)
from app.core.account_fields import NormalizedField
from app.core.account_security import (
    auth_token_digest,
    generate_auth_token,
    opaque_digest,
)
from app.core.config import settings
from app.core.time_utils import utcnow
from app.models import (
    CustomerAuthToken,
    CustomerDataProposal,
    CustomerDataProposalField,
    CustomerIdentity,
    CustomerIdentityLink,
    CustomerNotificationPreference,
    CustomerRegistrationAttempt,
    CustomerTermsAcknowledgement,
)
from app.services import account_email_service as email
from app.services import customer_account_audit as audit
from app.services import customer_auth_service, identifier_service
from app.services.errors import ConflictError

#: What every registration, resend and password-reset request is told, whatever happened.
#: One sentence, one status code, one body (T-02).
GENERIC_REGISTRATION_MESSAGE = "If that address can be registered, we have sent a message to it."
GENERIC_RECOVERY_MESSAGE = "If that address has an account, we have sent a message to it."
#: The single answer to every failed token redemption: unknown, malformed, expired,
#: already used, or invalidated (`STATE_MACHINES.md` section 5).
GENERIC_TOKEN_FAILURE = "That link is no longer valid. Request a new one."


@dataclass(frozen=True)
class IssuedToken:
    """A token that has just been created. The plaintext exists here and nowhere else."""

    plaintext: str
    record: CustomerAuthToken


# --- Tokens -------------------------------------------------------------------


def issue_token(
    db: Session,
    identity: CustomerIdentity,
    *,
    purpose: TokenPurpose,
    request_ip: str | None,
    invalidate_existing: bool = True,
    issued_to_email_normalized: str | None = None,
) -> IssuedToken:
    """Mint a single-use, expiring, purpose-bound token and store only its digest.

    Issuing a new token of a purpose **invalidates the outstanding ones of that purpose**
    (`STATE_MACHINES.md` section 5). The alternative -- letting several live at once --
    means a resend does not actually replace anything, and an attacker who obtained an
    earlier link keeps it working while the customer believes they have refreshed it.

    ``issued_to_email_normalized`` records the address it was sent to, so a later address
    change cannot redirect an outstanding token to a mailbox its holder does not control.
    """
    now = utcnow()
    if invalidate_existing:
        db.execute(
            update(CustomerAuthToken)
            .where(
                CustomerAuthToken.identity_id == identity.id,
                CustomerAuthToken.purpose == purpose.value,
                CustomerAuthToken.consumed_at.is_(None),
                CustomerAuthToken.invalidated_at.is_(None),
            )
            .values(invalidated_at=now, invalidated_reason_code="superseded")
        )

    # An email-change link proves a mailbox exactly as a verification link does, so it lives
    # for the same OD-36 verification period (RC-UAT-21, DEC-0231).
    hours = (
        settings.account_verification_token_hours
        if purpose in (TokenPurpose.EMAIL_VERIFICATION, TokenPurpose.EMAIL_CHANGE)
        else settings.account_password_reset_token_hours
    )
    plaintext = generate_auth_token()
    record = CustomerAuthToken(
        identity_id=identity.id,
        purpose=purpose.value,
        token_digest=auth_token_digest(plaintext, purpose),
        issued_at=now,
        expires_at=now + timedelta(hours=hours),
        issued_to_email_normalized=issued_to_email_normalized or identity.email_normalized,
        request_ip=request_ip,
    )
    db.add(record)
    db.flush()
    return IssuedToken(plaintext=plaintext, record=record)


@dataclass(frozen=True)
class TokenRedemption:
    """The result of trying to redeem a token. ``identity`` is None on every failure."""

    ok: bool
    reason_code: str
    identity: CustomerIdentity | None = None
    token: CustomerAuthToken | None = None


def redeem_token(db: Session, *, token: str, purpose: TokenPurpose) -> TokenRedemption:
    """Consume a token atomically, or explain to the audit log why not.

    **The lookup is by digest only.** There is no path that searches by identity or by
    address, which is what makes a redemption unable to confirm that an account exists.

    Consumption is a conditional ``UPDATE ... WHERE consumed_at IS NULL`` whose affected-row
    count decides the outcome. SQLite has no ``SELECT ... FOR UPDATE``, so this is how two
    simultaneous redemptions are made to resolve to exactly one success: both read the same
    unconsumed row, both issue the update, and the second one changes nothing (T-05).

    Every failure returns a distinct ``reason_code`` for the audit log and the **same**
    generic message for the caller.
    """
    digest = auth_token_digest(token, purpose)
    record = db.scalar(select(CustomerAuthToken).where(CustomerAuthToken.token_digest == digest))
    if record is None:
        # Covers unknown, malformed, and a token minted for the *other* purpose: the purpose
        # is part of the signed message, so a verification link simply does not digest to
        # anything the reset lookup can find.
        return TokenRedemption(ok=False, reason_code="unknown")

    now = utcnow()
    if record.consumed_at is not None:
        return TokenRedemption(ok=False, reason_code="already_used", token=record)
    if record.invalidated_at is not None:
        return TokenRedemption(ok=False, reason_code="invalidated", token=record)
    if record.expires_at <= now:
        return TokenRedemption(ok=False, reason_code="expired", token=record)

    claimed = db.execute(
        update(CustomerAuthToken)
        .where(CustomerAuthToken.id == record.id, CustomerAuthToken.consumed_at.is_(None))
        .values(consumed_at=now)
    )
    if not claimed.rowcount:
        # Another request consumed it between the read and the write. Exactly one wins.
        return TokenRedemption(ok=False, reason_code="already_used", token=record)

    identity = db.get(CustomerIdentity, record.identity_id)
    if identity is None:  # pragma: no cover - cascade makes this unreachable
        return TokenRedemption(ok=False, reason_code="unknown", token=record)
    return TokenRedemption(ok=True, reason_code="ok", identity=identity, token=record)


def invalidate_tokens(
    db: Session, identity: CustomerIdentity, *, purpose: TokenPurpose, reason_code: str
) -> int:
    """Invalidate every outstanding token of one purpose. Returns how many."""
    result = db.execute(
        update(CustomerAuthToken)
        .where(
            CustomerAuthToken.identity_id == identity.id,
            CustomerAuthToken.purpose == purpose.value,
            CustomerAuthToken.consumed_at.is_(None),
            CustomerAuthToken.invalidated_at.is_(None),
        )
        .values(invalidated_at=utcnow(), invalidated_reason_code=reason_code)
    )
    return int(result.rowcount or 0)


# --- Registration -------------------------------------------------------------


@dataclass(frozen=True)
class RegistrationResult:
    """Internal only. The route reads nothing from this except that it did not raise."""

    outcome: RegistrationOutcome
    identity: CustomerIdentity | None = None


def register(
    db: Session,
    *,
    email_normalized: str,
    email_entered: str,
    password: str,
    fields: list[NormalizedField],
    notification_topics: dict[str, bool],
    terms_version: str,
    privacy_version: str,
    presented_language: str,
    idempotency_key: str,
    request_ip: str | None,
) -> RegistrationResult:
    """Create a pending identity and a pending proposal, or do nothing, indistinguishably.

    The caller has already checked the rate limits and validated the fields against the
    allowlist. What is left is the part that must be atomic and must not disclose.

    **Idempotency and concurrency** are one mechanism: a unique
    ``customer_registration_attempts.idempotency_key_digest`` is claimed first, inside the
    caller's transaction. A replay of the same key with the same data finds its own row and
    returns; the same key with *different* data is a conflict rather than a silent replay of
    an unrelated registration -- the rule ``booking_confirmations`` already follows
    (DEC-0031). Two concurrent equivalent requests race on the address uniqueness constraint
    and exactly one wins; the loser takes the existing-address path, which is the same
    response.
    """
    key_digest = opaque_digest(idempotency_key)
    fingerprint = _fingerprint(email_normalized, fields, notification_topics)

    existing_attempt = db.scalar(
        select(CustomerRegistrationAttempt).where(
            CustomerRegistrationAttempt.idempotency_key_digest == key_digest
        )
    )
    if existing_attempt is not None and _is_suppression_refusal(existing_attempt):
        # Written before UAT round 6, when a suppression stopped registration outright. A
        # replay of that key must not replay "nothing happened": the attempt row is dropped
        # and the request takes the registration the suppression wrongly refused.
        if existing_attempt.request_fingerprint != fingerprint:
            raise ConflictError(
                "That request identifier has already been used for different details.",
                field="idempotency_key",
            )
        db.delete(existing_attempt)
        db.flush()
        existing_attempt = None
    if existing_attempt is not None:
        if existing_attempt.request_fingerprint != fingerprint:
            raise ConflictError(
                "That request identifier has already been used for different details.",
                field="idempotency_key",
            )
        return RegistrationResult(
            outcome=RegistrationOutcome.REPLAYED,
            identity=(
                db.get(CustomerIdentity, existing_attempt.identity_id)
                if existing_attempt.identity_id
                else None
            ),
        )

    # No suppression check. Verification is account email, not marketing, and an address
    # that could not be verified could never finish signing up (UAT round 6).
    existing = db.scalar(
        select(CustomerIdentity).where(CustomerIdentity.email_normalized == email_normalized)
    )
    if existing is not None:
        return _existing_address(
            db,
            identity=existing,
            key_digest=key_digest,
            email_normalized=email_normalized,
            fingerprint=fingerprint,
            request_ip=request_ip,
        )

    identity = CustomerIdentity(
        public_id=identifier_service.next_account_public_id(db),
        email_entered=email_entered,
        email_normalized=email_normalized,
        password_hash="",
        status=IdentityStatus.PENDING_VERIFICATION,
        failed_sign_in_count=0,
        preferred_language=_preferred_language(fields),
    )
    customer_auth_service.set_password(db, identity, password=password)
    db.add(identity)
    try:
        db.flush()
    except IntegrityError:
        # Lost the race against a concurrent equivalent registration. The winner created the
        # identity; this request takes the existing-address path and says the same thing.
        db.rollback()
        existing = db.scalar(
            select(CustomerIdentity).where(CustomerIdentity.email_normalized == email_normalized)
        )
        if existing is None:  # pragma: no cover - the constraint is the only failure here
            raise
        return _existing_address(
            db,
            identity=existing,
            key_digest=key_digest,
            email_normalized=email_normalized,
            fingerprint=fingerprint,
            request_ip=request_ip,
        )

    _write_acknowledgements(
        db,
        identity,
        terms_version=terms_version,
        privacy_version=privacy_version,
        presented_language=presented_language,
        request_ip=request_ip,
    )
    _write_notification_preferences(db, identity, notification_topics)
    proposal = create_registration_proposal(db, identity, fields=fields, request_ip=request_ip)

    issued = issue_token(
        db, identity, purpose=TokenPurpose.EMAIL_VERIFICATION, request_ip=request_ip
    )
    email.send(
        email.OutboundEmail(
            to_email=identity.email_entered,
            template_key=email.TEMPLATE_VERIFY_EMAIL,
            language=presented_language,
            parameters={
                "verification_url": verification_url(issued.plaintext),
                "expires_after": email.hours_phrase(settings.account_verification_token_hours),
            },
        )
    )
    audit.verification_issued(db, identity=identity, resent=False, ip_address=request_ip)

    outcome = RegistrationOutcome.CREATED
    _record_attempt(db, key_digest, email_normalized, fingerprint, outcome, identity.id, request_ip)
    audit.registration_received(
        db,
        identity=identity,
        email_normalized=email_normalized,
        outcome=outcome.value,
        field_keys=[field.key for field in fields],
        ip_address=request_ip,
    )
    audit.proposal_submitted(
        db,
        identity=identity,
        proposal_id=proposal.id,
        field_keys=[field.key for field in fields],
        ip_address=request_ip,
    )
    return RegistrationResult(outcome=outcome, identity=identity)


def _existing_address(
    db: Session,
    *,
    identity: CustomerIdentity,
    key_digest: str,
    email_normalized: str,
    fingerprint: str,
    request_ip: str | None,
) -> RegistrationResult:
    """The address already has an account. Create nothing; notify the real owner once.

    The notice goes to the address that is already registered, not to whoever submitted the
    form -- they are the same string, but the distinction matters: the message says an
    attempt was made and offers a reset, and carries **no account details**, because the
    person reading it may not be the person who typed it (`EMAIL_DELIVERY.md` section 3).

    The address bucket the route already consumed is what limits this to one notice per
    window, so a repeated registration against somebody else's address is not a way to mail
    them repeatedly (T-11).
    """
    outcome = RegistrationOutcome.EXISTING_ADDRESS
    issued = issue_token(db, identity, purpose=TokenPurpose.PASSWORD_RESET, request_ip=request_ip)
    email.send(
        email.OutboundEmail(
            to_email=identity.email_entered,
            template_key=email.TEMPLATE_REGISTRATION_ATTEMPT_NOTICE,
            language=identity.preferred_language,
            parameters={"reset_url": password_reset_url(issued.plaintext)},
        )
    )
    _record_attempt(db, key_digest, email_normalized, fingerprint, outcome, identity.id, request_ip)
    audit.registration_received(
        db,
        identity=identity,
        email_normalized=email_normalized,
        outcome=outcome.value,
        field_keys=[],
        ip_address=request_ip,
    )
    return RegistrationResult(outcome=outcome, identity=identity)


def _is_suppression_refusal(attempt: CustomerRegistrationAttempt) -> bool:
    """An attempt a suppression refused. Only rows written before UAT round 6 can be one."""
    return attempt.outcome == RegistrationOutcome.SUPPRESSED.value


def _record_attempt(
    db: Session,
    key_digest: str,
    email_normalized: str,
    fingerprint: str,
    outcome: RegistrationOutcome,
    identity_id: int | None,
    request_ip: str | None,
) -> None:
    from app.core.account_security import address_key

    db.add(
        CustomerRegistrationAttempt(
            idempotency_key_digest=key_digest,
            email_key=address_key(email_normalized),
            request_fingerprint=fingerprint,
            outcome=outcome.value,
            identity_id=identity_id,
            created_at=utcnow(),
            request_ip=request_ip,
        )
    )
    db.flush()


def _fingerprint(
    email_normalized: str, fields: list[NormalizedField], topics: dict[str, bool]
) -> str:
    """A digest of the canonicalized submission. Enough to compare, not enough to read back.

    The password is deliberately **not** in it. Two requests that differ only by password
    are the same registration for idempotency purposes, and putting a password-derived value
    here would put a password-derived value in a column.
    """
    parts = [f"email={email_normalized}"]
    parts += [f"{field.key}={field.entered}" for field in sorted(fields, key=lambda f: f.key)]
    parts += [f"topic:{key}={value}" for key, value in sorted(topics.items())]
    return opaque_digest("\x1f".join(parts))


def preferred_language_of(fields: list[NormalizedField]) -> str:
    """The language a registration was made in: the one its emails are written in."""
    return _preferred_language(fields)


def _preferred_language(fields: list[NormalizedField]) -> str:
    """The submitted language if it is one the account serves, else Vietnamese (OD-71,
    superseding OD-39's English)."""
    for field in fields:
        if (
            field.key == "preferred_language"
            and field.normalized
            and field.normalized in settings.account_supported_language_list
        ):
            return field.normalized
    return "vi"


def _write_acknowledgements(
    db: Session,
    identity: CustomerIdentity,
    *,
    terms_version: str,
    privacy_version: str,
    presented_language: str,
    request_ip: str | None,
) -> None:
    """Two append-only rows: which version of which document, in which language, when.

    Required during registration (OD-37). There is no update path and no delete path; a
    later acknowledgement is a later row.
    """
    now = utcnow()
    for kind, version in (
        (TermsDocumentKind.TERMS, terms_version),
        (TermsDocumentKind.PRIVACY, privacy_version),
    ):
        db.add(
            CustomerTermsAcknowledgement(
                identity_id=identity.id,
                document_kind=kind.value,
                document_version=version,
                presented_language=presented_language,
                acknowledged_at=now,
                request_ip=request_ip,
            )
        )


def _write_notification_preferences(
    db: Session, identity: CustomerIdentity, topics: dict[str, bool]
) -> None:
    """One row per topic the customer chose. Unchecked by default means no row (OD-38).

    ``account_security`` is not settable and cannot arrive here: a preference that could
    switch off a verification or reset message would lock people out of their own account.
    """
    now = utcnow()
    for topic, enabled in topics.items():
        if topic not in CUSTOMER_SETTABLE_TOPIC_VALUES:  # pragma: no cover - boundary refuses
            continue
        db.add(
            CustomerNotificationPreference(
                identity_id=identity.id,
                channel=NotificationChannel.EMAIL.value,
                topic=topic,
                enabled=bool(enabled),
                updated_at=now,
            )
        )


def create_registration_proposal(
    db: Session,
    identity: CustomerIdentity,
    *,
    fields: list[NormalizedField],
    request_ip: str | None,
) -> CustomerDataProposal:
    """The pending customer-data proposal. ``customer_id`` is null, and that is the point.

    There is no customer yet and registration will not create one. A previous pending
    proposal from the same identity is superseded rather than edited: the field rows are
    never rewritten, so the reviewer in Phase 10 reads an immutable submission and can
    follow the chain back (`STATE_MACHINES.md` section 4).
    """
    now = utcnow()
    previous = db.scalar(
        select(CustomerDataProposal)
        .where(
            CustomerDataProposal.identity_id == identity.id,
            CustomerDataProposal.status == ProposalStatus.PENDING.value,
        )
        .order_by(CustomerDataProposal.id.desc())
    )

    proposal = CustomerDataProposal(
        identity_id=identity.id,
        customer_id=None,
        kind=ProposalKind.REGISTRATION.value,
        status=ProposalStatus.PENDING.value,
        submitted_at=now,
        supersedes_proposal_id=previous.id if previous else None,
    )
    db.add(proposal)
    db.flush()

    for field in fields:
        db.add(
            CustomerDataProposalField(
                proposal_id=proposal.id,
                field_key=field.key,
                value_type=field.value_type.value,
                proposed_value=field.entered,
                proposed_value_normalized=field.normalized,
                current_value_at_submission=None,
                applied=False,
            )
        )

    if previous is not None:
        previous.status = ProposalStatus.SUPERSEDED.value
        audit.proposal_superseded(
            db, identity=identity, proposal_id=proposal.id, superseded_id=previous.id
        )
    db.flush()
    return proposal


# --- Verification and resend --------------------------------------------------


def verify_email(db: Session, *, token: str, request_ip: str | None) -> CustomerIdentity | None:
    """Redeem a verification token. ``None`` means refused, for every reason.

    Verification changes **one thing**: the email-verification state. It does not approve the
    account, does not link a customer, and grants no access to shipment data (OD-23). An
    identity that is already past ``pending_verification`` has its ``email_verified_at``
    stamped if it was somehow absent and its status left alone -- a verification link must
    never move an approved account backwards.
    """
    redemption = redeem_token(db, token=token, purpose=TokenPurpose.EMAIL_VERIFICATION)
    if not redemption.ok or redemption.identity is None:
        audit.verification_refused(
            db,
            identity=None,
            reason_code=redemption.reason_code,
            purpose=TokenPurpose.EMAIL_VERIFICATION.value,
            ip_address=request_ip,
        )
        return None

    identity = redemption.identity
    if identity.email_verified_at is None:
        identity.email_verified_at = utcnow()
    if identity.status == IdentityStatus.PENDING_VERIFICATION.value:
        identity.status = IdentityStatus.PENDING_APPROVAL.value
    audit.email_verified(db, identity=identity, ip_address=request_ip)
    return identity


def resend_verification(
    db: Session, *, email_normalized: str, request_ip: str | None
) -> RegistrationOutcome:
    """Issue a replacement verification token, or quietly do nothing.

    The caller has already consumed the rate limit. The return value is internal: the route
    answers with the same body and status whether the address is unknown, unverified,
    verified, approved or suspended (`STATE_MACHINES.md` section 1, transition 3). A
    suppression is not consulted: it blocks marketing, not account email (UAT round 6).
    """
    identity = db.scalar(
        select(CustomerIdentity).where(CustomerIdentity.email_normalized == email_normalized)
    )
    if identity is None:
        return RegistrationOutcome.EXISTING_ADDRESS

    if identity.status != IdentityStatus.PENDING_VERIFICATION.value:
        # Already verified, approved, rejected, suspended or deactivated. Nothing is issued
        # and nothing is said -- a resend that behaved differently here would report the
        # account's state to anyone who typed the address.
        return RegistrationOutcome.EXISTING_ADDRESS

    issued = issue_token(
        db, identity, purpose=TokenPurpose.EMAIL_VERIFICATION, request_ip=request_ip
    )
    email.send(
        email.OutboundEmail(
            to_email=identity.email_entered,
            template_key=email.TEMPLATE_VERIFY_EMAIL,
            language=identity.preferred_language,
            parameters={
                "verification_url": verification_url(issued.plaintext),
                "expires_after": email.hours_phrase(settings.account_verification_token_hours),
            },
        )
    )
    audit.verification_issued(db, identity=identity, resent=True, ip_address=request_ip)
    return RegistrationOutcome.CREATED


# --- Password reset -----------------------------------------------------------


def request_password_reset(
    db: Session, *, email_normalized: str, request_ip: str | None
) -> RegistrationOutcome:
    """Issue a reset token if there is an account to issue one for. Says nothing either way.

    A reset request for an unknown address produces the same response as one for a known
    address (`STATE_MACHINES.md` section 5). A deactivated or rejected account is treated as
    unknown: there is nothing to reset into. A suppression is not consulted: a reset is
    account email, not marketing (UAT round 6).
    """
    identity = db.scalar(
        select(CustomerIdentity).where(CustomerIdentity.email_normalized == email_normalized)
    )
    outcome = RegistrationOutcome.EXISTING_ADDRESS
    if identity is not None and identity.status in {
        IdentityStatus.PENDING_VERIFICATION.value,
        IdentityStatus.PENDING_APPROVAL.value,
        IdentityStatus.ACTIVE.value,
    }:
        issued = issue_token(
            db, identity, purpose=TokenPurpose.PASSWORD_RESET, request_ip=request_ip
        )
        email.send(
            email.OutboundEmail(
                to_email=identity.email_entered,
                template_key=email.TEMPLATE_PASSWORD_RESET,
                language=identity.preferred_language,
                parameters={
                    "reset_url": password_reset_url(issued.plaintext),
                    "expires_after": email.hours_phrase(
                        settings.account_password_reset_token_hours
                    ),
                },
            )
        )
        outcome = RegistrationOutcome.CREATED

    audit.password_reset_requested(
        db,
        identity=identity,
        email_normalized=email_normalized,
        outcome=outcome.value,
        ip_address=request_ip,
    )
    return outcome


def complete_password_reset(
    db: Session, *, token: str, password: str, request_ip: str | None
) -> CustomerIdentity | None:
    """Redeem a reset token and set the password. ``None`` means refused, for every reason.

    Four things happen together or not at all: the token is consumed, the password is
    replaced, **every** Customer Account session for that identity is revoked, and every
    other outstanding reset token is invalidated. Revoking all sessions is the point of a
    reset -- somebody resetting a password may be doing it because an attacker holds a live
    session, and leaving that session alive would make the reset cosmetic (T-14).

    Staff sessions are untouched, because they live in a different table that nothing here
    can reach.
    """
    redemption = redeem_token(db, token=token, purpose=TokenPurpose.PASSWORD_RESET)
    if not redemption.ok or redemption.identity is None:
        audit.verification_refused(
            db,
            identity=None,
            reason_code=redemption.reason_code,
            purpose=TokenPurpose.PASSWORD_RESET.value,
            ip_address=request_ip,
        )
        return None

    identity = redemption.identity
    customer_auth_service.set_password(db, identity, password=password)
    invalidate_tokens(
        db, identity, purpose=TokenPurpose.PASSWORD_RESET, reason_code="password_reset"
    )
    revoked = customer_auth_service.revoke_all_sessions(db, identity, reason_code="password_reset")
    # RC-UAT-21 (review HIGH 1): a pending email change dies with the reset.
    from app.services import customer_account_security_service  # noqa: PLC0415

    customer_account_security_service.close_pending_email_changes(
        db, identity, reason_code="password_reset", ip_address=request_ip
    )
    email.send(
        email.OutboundEmail(
            to_email=identity.email_entered,
            template_key=email.TEMPLATE_PASSWORD_CHANGED,
            language=identity.preferred_language,
            parameters={},
        )
    )
    audit.password_reset_completed(
        db, identity=identity, sessions_revoked=revoked, ip_address=request_ip
    )
    return identity


# --- Service-level lifecycle ---------------------------------------------------
#
# Reached by the staff routes in `app/api/v1/routes/customer_account_review.py` since the
# 2026-10-14 fix pack (Sprint 13 Lane A, A-1). The transition guards live here, beside the
# transitions, so a route stays a thin caller that names no identity state.

#: A suspension ends sessions, so it applies to the two states that can hold one.
SUSPENDABLE_STATUSES = frozenset(
    {IdentityStatus.PENDING_APPROVAL.value, IdentityStatus.ACTIVE.value}
)


def can_suspend(identity: CustomerIdentity) -> bool:
    return identity.status in SUSPENDABLE_STATUSES


def can_reinstate(identity: CustomerIdentity) -> bool:
    return identity.status == IdentityStatus.SUSPENDED.value


def can_deactivate(identity: CustomerIdentity) -> bool:
    """Any account not already deactivated. Deactivation is the one terminal state."""
    return identity.status != IdentityStatus.DEACTIVATED.value


def suspend(
    db: Session, identity: CustomerIdentity, *, reason_code: str, actor=None
) -> CustomerIdentity:
    """Suspend an account and end its sessions. Takes effect on the next request.

    No route calls this in Phase 9; the Phase 10 staff screen will. It exists now because
    instruction section 8 requires administrative and security revocation at the service
    layer, and because "we can suspend an account" should not first become true on the day
    somebody needs it.
    """
    identity.status = IdentityStatus.SUSPENDED.value
    identity.suspended_at = utcnow()
    identity.suspended_by_user_id = actor.id if actor else None
    identity.status_reason_code = reason_code
    customer_auth_service.revoke_all_sessions(db, identity, reason_code="suspended")
    audit.status_changed(
        db, identity=identity, action=audit.ACTION_SUSPEND, reason_code=reason_code, actor=actor
    )
    return identity


def reinstate(
    db: Session, identity: CustomerIdentity, *, reason_code: str, actor=None
) -> CustomerIdentity:
    """Return a suspended account to the state it was in. Never to ``active`` by itself.

    A suspended account that had not been approved returns to ``pending_approval``, not to
    ``active``: only an explicit staff approval with a link reaches ``active`` (OD-24), and
    reinstatement must not become a second door into it.

    **Corrected in Phase 10.** ``approved_at`` alone was the test, and once Phase 10
    started writing links that became insufficient: an account approved, then suspended,
    then unlinked would come back ``active`` with **no active link** -- an identity in the
    one state that reaches shipment data, with no customer to reach it through. The
    invariant is "active implies exactly one active link", so reinstatement now checks the
    link rather than the history of one. Without a live link the account returns to
    ``pending_approval``, which is a state a person then has to decide about.

    No route reaches this function in Phase 10 -- transition 7 of `STATE_MACHINES.md` is
    not in this phase's scope -- but the invariant is enforced here anyway, because a
    guard that only exists once a route exists is a guard added under time pressure.
    """
    has_active_link = (
        db.scalar(
            select(CustomerIdentityLink.id)
            .where(
                CustomerIdentityLink.identity_id == identity.id,
                CustomerIdentityLink.status == LinkStatus.ACTIVE.value,
            )
            .limit(1)
        )
        is not None
    )
    identity.status = (
        IdentityStatus.ACTIVE.value
        if identity.approved_at is not None and has_active_link
        else IdentityStatus.PENDING_APPROVAL.value
    )
    identity.suspended_at = None
    identity.suspended_by_user_id = None
    identity.status_reason_code = reason_code
    audit.status_changed(
        db,
        identity=identity,
        action=audit.ACTION_REINSTATE,
        reason_code=reason_code,
        actor=actor,
    )
    return identity


def restore_after_deactivation(
    db: Session, identity: CustomerIdentity, *, status: str, reason_code: str
) -> CustomerIdentity:
    """Write the status an Admin reinstatement restores (RC-UAT-21, DEC-0231).

    Lives here, beside transition 7, so the activation invariant keeps its two writers. The
    decision is ``customer_account_security_service.reactivate``'s; this function refuses to
    write ``active`` without exactly one live link (never a linkless active identity) and
    clears the deactivation.
    """
    if identity.status != IdentityStatus.DEACTIVATED.value:
        raise ConflictError("Only a deactivated account can be reinstated.")
    if status == IdentityStatus.ACTIVE.value:
        live = db.scalar(
            select(func.count(CustomerIdentityLink.id)).where(
                CustomerIdentityLink.identity_id == identity.id,
                CustomerIdentityLink.status == LinkStatus.ACTIVE.value,
            )
        )
        if live != 1 or identity.approved_at is None:
            raise ConflictError("This account cannot return to active without its one link.")
        identity.status = IdentityStatus.ACTIVE.value
    elif status in {
        IdentityStatus.PENDING_APPROVAL.value,
        IdentityStatus.PENDING_VERIFICATION.value,
        IdentityStatus.SUSPENDED.value,
    }:
        identity.status = status
    else:
        raise ConflictError("That is not a status a reinstatement restores.")
    identity.deactivated_at = None
    identity.deactivated_by_user_id = None
    identity.status_reason_code = reason_code
    identity.failed_sign_in_count = 0
    identity.locked_until = None
    return identity


def activate_relinked(
    db: Session, identity: CustomerIdentity, *, reason_code: str
) -> CustomerIdentity:
    """Return an orphaned account to ``active`` once staff have re-linked it (B-13).

    The third and last writer of ``active`` sits here, beside transition 7, because this
    module owns the activation invariant: the identity must already have been approved
    (``approved_at`` set -- a re-link is never a first approval) and must hold **exactly one**
    live link, which ``customer_account_relink_service`` writes through the approval
    service's one link constructor just before calling this. Anything else is refused and
    nothing is written.

    A conditional update on ``pending_approval`` with the row count checked, as the approval
    does, so a re-link racing a close, an approval or a second re-link has one winner.
    ``approved_at`` is kept: the original approval stands, and the re-link is recorded on its
    own row (stand-in B-15).
    """
    live = db.scalar(
        select(func.count(CustomerIdentityLink.id)).where(
            CustomerIdentityLink.identity_id == identity.id,
            CustomerIdentityLink.status == LinkStatus.ACTIVE.value,
        )
    )
    if live != 1 or identity.approved_at is None:
        raise ConflictError("This account cannot become active without exactly one link.")
    result = db.execute(
        update(CustomerIdentity)
        .where(
            CustomerIdentity.id == identity.id,
            CustomerIdentity.status == IdentityStatus.PENDING_APPROVAL.value,
            CustomerIdentity.approved_at.is_not(None),
        )
        .values(
            status=IdentityStatus.ACTIVE.value,
            status_reason_code=reason_code,
            failed_sign_in_count=0,
            locked_until=None,
            updated_at=utcnow(),
        )
    )
    if result.rowcount != 1:
        raise ConflictError(
            "This account was changed by somebody else while you were working on it."
        )
    db.expire(identity)
    return identity


def deactivate(
    db: Session, identity: CustomerIdentity, *, reason_code: str, actor=None
) -> CustomerIdentity:
    """Deactivate an account: sessions and tokens die, the record stays.

    **Not a deletion.** No self-service hard delete exists, and a privacy request is
    staff-executed and audited (OD-35).
    """
    identity.status = IdentityStatus.DEACTIVATED.value
    identity.deactivated_at = utcnow()
    identity.deactivated_by_user_id = actor.id if actor else None
    identity.status_reason_code = reason_code
    customer_auth_service.revoke_all_sessions(db, identity, reason_code="deactivated")
    for purpose in TokenPurpose:
        invalidate_tokens(db, identity, purpose=purpose, reason_code="deactivated")
    audit.status_changed(
        db,
        identity=identity,
        action=audit.ACTION_DEACTIVATE,
        reason_code=reason_code,
        actor=actor,
    )
    return identity


# --- Links in outbound messages ----------------------------------------------


#: The fragment key both landing pages read. `frontend/src/account/linkToken.js` is the
#: other half of this contract.
LINK_TOKEN_FRAGMENT = "#token="


def verification_url(token: str) -> str:
    """Where a verification link points.

    The token travels in the URL **fragment**, not the query string (CA-SEC-07, fix pack
    of 2026-10-14). A fragment is never sent to a server, so the token reaches neither
    this application's access log, nor the reverse proxy's, nor the ``Referer`` of
    anything the landing page loads -- a query string reaches all three. The landing page
    then copies the token into memory and rewrites the address bar with
    ``history.replaceState`` before React mounts, so the address bar, the session history
    and the Back button never hold it.

    What this does **not** do is keep the committed URL out of the browser's global
    history database: Chromium records the URL at navigation commit, fragment included,
    before any script runs, and no client-side technique removes that entry. The
    remaining layers are the ones that bound the exposure -- the token is single-use,
    short-lived, purpose-bound, and invalidated by the next one issued.

    ``?token=`` links already sent keep working: both landing pages accept either shape.
    """
    return f"{_account_base_url()}/verify-email{LINK_TOKEN_FRAGMENT}{token}"


def password_reset_url(token: str) -> str:
    """Same shape as ``verification_url``, for the same reasons."""
    return f"{_account_base_url()}/reset-password{LINK_TOKEN_FRAGMENT}{token}"


def account_sign_in_url() -> str:
    """Where the approval notice points. No token, because there is nothing to redeem.

    An approval message is not a credential: the person already has a password. Putting a
    token in it would turn a courtesy notice into a bearer credential nobody asked for
    (`EMAIL_DELIVERY.md` section 3).
    """
    return f"{_account_base_url()}/sign-in"


def account_page_url(path: str) -> str:
    """A page of the Customer Account, without any token (Phase 13G: the quotes page)."""
    return f"{_account_base_url()}/{path.lstrip('/')}"


def _account_base_url() -> str:
    """The Customer Account origin, derived from the configured tracking base URL.

    There is no Customer Account frontend in Phase 9, so there is no separate configured
    origin to read and inventing one would be asserting a hostname nobody has chosen. The
    tracking base URL already names the customer-facing application, so its origin is
    borrowed and the path replaced. Phase 12 gives this its own setting.
    """
    base = settings.tracking_base_url.rstrip("/")
    if base.endswith("/track"):
        base = base[: -len("/track")]
    return f"{base}/account"
