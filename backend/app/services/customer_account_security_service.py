"""Signed-in password change, self-service email change, and reinstating a deactivated
account (RC-UAT-21 Phase B, DEC-0231).

Built on the Customer Account's existing pieces rather than beside them: the Argon2 hasher
and password policy of ``customer_auth_service``, the purpose-bound, hashed, single-use,
expiring tokens of ``customer_identity_service`` (a new purpose, ``email_change``, valid for
the OD-36 verification period), the account email seam (null or capture; nothing is sent
anywhere else), and the closed audit vocabulary of ``customer_account_audit``.

**Password change.** The current password is required; the new one must satisfy the account
policy (``ACCOUNT_MIN_PASSWORD_LENGTH``, no leading or trailing space, not a common password),
be typed twice, and differ from the current one. On success every *other* session of the
identity is revoked and the caller's own session is **rotated** (revoked and re-issued, so a
copy of the old cookie is worthless), outstanding reset links die, a "your password was
changed" notice goes to the account's address in the customer's language, and the change is
audited. A wrong current password is refused and audited; the route rate-limits the attempts
per account.

**Email change: Admin only** (RC-UAT-25 item 2, Ben 2026-10-25). The customer can no longer
change the sign-in email from the Customer Account. ``request_email_change`` refuses every
request before reading it, and ``confirm_email_change`` refuses every link -- including one
sent before the change: a live link is consumed and its request closed ``refused``
(``self_service_withdrawn``), and the account is untouched. A request still pending is also
closed when the customer next opens "Sign-in and security"
(``withdraw_pending_email_changes``); one never read expires with its link (the OD-36
verification period), so no data step is needed.

An **Admin** changes it instead (``change_sign_in_email_by_staff``, the deactivation
permission): the new address is normalized, the single email rule refuses an address held by
another account or another customer record (``address_refusal``), the unique index on
``customer_identities.email_normalized`` decides a true race inside a savepoint, the linked
customer's email follows (the same write the approval makes), every session ends, every
outstanding link dies, any pending customer request closes, the **old** address is told and
the **new** one is told how to sign in, and the change is audited and recorded in
``customer_account_email_changes`` with the Admin's bounded reason and optional note.

**Reinstatement.** Admin only (the deactivation permission), a bounded reason code required
and an optional note. The identity returns to the usable status it had before deactivation;
old sessions stay revoked, so the customer signs in again; a notice is sent; the reversal is
recorded in ``customer_account_reinstatements`` and audited. A deactivation for a privacy
request, or of an application that had been rejected, is not reversible (stand-in B-5).

**Never back onto a history the account did not see** (review HIGH 2). While an account is
deactivated its link holds nothing, so the linked customer may have been merged away,
archived, or become the survivor of a merge (absorbing another record's shipments). If any of
that happened -- the customer is merged or archived, or any customer was merged *into* it at
or after ``deactivated_at`` -- the link is **ended** (audited ``customer_account.unlink``,
reason ``merged_since_deactivation`` / ``archived_since_deactivation``) and the account comes
back as ``pending_approval`` (or ``suspended`` if it was suspended), never ``active``: staff
re-review it and link it afresh, acknowledging the history as an approval does (stand-in
B-13). The status itself is written by ``customer_identity_service.restore_after_deactivation``
-- the module that already owns transition 7 -- which refuses ``active`` without exactly the
live link the activation invariant demands.

**Email change and password.** A password change or a reset still cancels any pending email
change and kills its link (review HIGH 1), which matters only for a request made before
RC-UAT-25.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.account_enums import (
    AUTHENTICATABLE_STATUSES,
    IdentityStatus,
    LinkStatus,
    TokenPurpose,
)
from app.core.normalization import INVALID_EMAIL_MESSAGE, normalize_email
from app.core.security import verify_password
from app.core.time_utils import utcnow
from app.models import (
    Customer,
    CustomerAccountEmailChange,
    CustomerAccountReinstatement,
    CustomerEmailChangeRequest,
    CustomerIdentity,
    CustomerIdentityLink,
    CustomerSession,
)
from app.services import account_email_service as email
from app.services import customer_account_audit as audit
from app.services import customer_auth_service, customer_identity_service
from app.services.errors import ConflictError, PermissionDeniedError, ValidationError

# --- Sentences ----------------------------------------------------------------------------

CURRENT_PASSWORD_WRONG = "The current password is not correct."
SAME_PASSWORD = "Choose a new password that is different from the current one."
PASSWORD_CHANGED_MESSAGE = (
    "Password changed. You are still signed in here; every other session was signed out."
)
#: The one answer to every customer request to change the sign-in email (RC-UAT-25 item 2):
#: the same words whatever address was typed, and nothing is sent anywhere.
EMAIL_CHANGE_STAFF_ONLY = (
    "Your sign-in email can only be changed by Solaris Express. Contact us and we will "
    "change it for you."
)
SAME_EMAIL = "That is already this account's sign-in email."
EMAIL_CHANGE_CANCELLED_MESSAGE = "The email change was cancelled."
#: Why a pre-RC-UAT-25 request or link was closed.
REASON_SELF_SERVICE_WITHDRAWN = "self_service_withdrawn"

# --- Email change states --------------------------------------------------------------------

PENDING = "pending"
COMPLETED = "completed"
SUPERSEDED = "superseded"
CANCELLED = "cancelled"
REFUSED = "refused"

REASON_IN_USE_IDENTITY = "address_in_use_identity"
REASON_IN_USE_CUSTOMER = "address_in_use_customer"

#: Where the (withdrawn) confirmation link pointed. The page still exists, to say the link no
#: longer works.
CONFIRM_EMAIL_CHANGE_PATH = "confirm-email-change"


def _authenticatable(identity: CustomerIdentity) -> bool:
    return identity.status in AUTHENTICATABLE_STATUSES


# --- Password change ------------------------------------------------------------------------


@dataclass(frozen=True)
class RotatedSession:
    session_token: str
    csrf_token: str
    sessions_revoked: int


def change_password(
    db: Session,
    *,
    identity: CustomerIdentity,
    session: CustomerSession,
    current_password: str,
    new_password: str,
    new_password_confirmation: str | None,
    ip_address: str | None,
    user_agent: str | None,
) -> RotatedSession:
    """Change the password of a signed-in identity. Raises ``ValidationError`` on refusal.

    The current password is checked **before** the new one, so a caller who does not know it
    learns nothing about the policy from the answer. Its refusal is audited; the caller must
    commit it (the route does) so the record survives the error.
    """
    if not isinstance(current_password, str) or not verify_password(
        current_password, identity.password_hash
    ):
        audit.password_change_refused(
            db, identity=identity, reason_code="bad_current_password", ip_address=ip_address
        )
        raise ValidationError(CURRENT_PASSWORD_WRONG, field="current_password")
    customer_auth_service.validate_password(new_password)
    customer_auth_service.confirm_password(new_password, new_password_confirmation)
    if verify_password(new_password, identity.password_hash):
        audit.password_change_refused(
            db, identity=identity, reason_code="same_password", ip_address=ip_address
        )
        raise ValidationError(SAME_PASSWORD, field="password")

    customer_auth_service.set_password(db, identity, password=new_password)
    customer_identity_service.invalidate_tokens(
        db, identity, purpose=TokenPurpose.PASSWORD_RESET, reason_code="password_changed"
    )
    # A pending email change dies with the old password (review HIGH 1): a stolen session
    # that asked to move the account to its own mailbox must not survive the owner's fix.
    close_pending_email_changes(db, identity, reason_code="password_changed", ip_address=ip_address)
    others = customer_auth_service.revoke_all_sessions(
        db, identity, reason_code="password_changed", except_session_id=session.id
    )
    # The caller's own session is rotated rather than kept: a copy of its cookie taken before
    # the change is worthless after it, and the browser carries on with the new one.
    customer_auth_service.revoke_session(db, session, reason_code="password_changed_rotated")
    session_token, csrf_token = customer_auth_service.open_session(
        db, identity, ip_address=ip_address, user_agent=user_agent
    )
    email.send(
        email.OutboundEmail(
            to_email=identity.email_entered,
            template_key=email.TEMPLATE_PASSWORD_CHANGED_HERE,
            language=_language(db, identity),
            parameters={},
        )
    )
    audit.password_changed(db, identity=identity, sessions_revoked=others, ip_address=ip_address)
    return RotatedSession(session_token, csrf_token, others)


def _language(db: Session, identity: CustomerIdentity) -> str:
    """The customer's language: the linked customer's preference, else the identity's."""
    from app.services import customer_account_profile_service  # noqa: PLC0415

    return customer_account_profile_service.account_language(
        identity, linked_customer(db, identity)
    )


# --- Email change -----------------------------------------------------------------------------


def linked_customer(db: Session, identity: CustomerIdentity) -> Customer | None:
    """The customer the identity's one active link names, whatever the identity's status."""
    link = db.scalar(
        select(CustomerIdentityLink).where(
            CustomerIdentityLink.identity_id == identity.id,
            CustomerIdentityLink.status == LinkStatus.ACTIVE.value,
        )
    )
    return db.get(Customer, link.customer_id) if link is not None else None


def address_refusal(
    db: Session, identity: CustomerIdentity, new_email_normalized: str
) -> str | None:
    """Why the single email rule refuses this address for this identity, or ``None``.

    Another **account** holding it (any status: the unique index would refuse it anyway), or
    another **customer record** holding it -- not the identity's own linked customer, and not
    a merged tombstone, which no longer stands for anybody (stand-in B-3).
    """
    other_identity = db.scalar(
        select(CustomerIdentity.id).where(
            CustomerIdentity.email_normalized == new_email_normalized,
            CustomerIdentity.id != identity.id,
        )
    )
    if other_identity is not None:
        return REASON_IN_USE_IDENTITY
    own = linked_customer(db, identity)
    query = select(Customer.id).where(
        Customer.email_normalized == new_email_normalized,
        Customer.merged_into_customer_id.is_(None),
    )
    if own is not None:
        query = query.where(Customer.id != own.id)
    if db.scalar(query.limit(1)) is not None:
        return REASON_IN_USE_CUSTOMER
    return None


def pending_email_change(
    db: Session, identity: CustomerIdentity
) -> CustomerEmailChangeRequest | None:
    """The identity's open request, if any and not expired. Read-only."""
    row = db.scalar(
        select(CustomerEmailChangeRequest)
        .where(
            CustomerEmailChangeRequest.identity_id == identity.id,
            CustomerEmailChangeRequest.status == PENDING,
        )
        .order_by(CustomerEmailChangeRequest.id.desc())
        .limit(1)
    )
    if row is None or row.expires_at <= utcnow():
        return None
    return row


def _close_open_requests(db: Session, identity: CustomerIdentity, *, status: str) -> int:
    now = utcnow()
    closed = 0
    for row in db.scalars(
        select(CustomerEmailChangeRequest).where(
            CustomerEmailChangeRequest.identity_id == identity.id,
            CustomerEmailChangeRequest.status == PENDING,
        )
    ):
        row.status = status
        row.closed_at = now
        closed += 1
    if closed:
        db.flush()  # the next read in this request must not find them pending
    return closed


def request_email_change(db: Session, *, identity: CustomerIdentity) -> None:
    """Refuse a customer's own request to change the sign-in email. Always raises.

    RC-UAT-25 item 2 (Ben, 2026-10-25): only an Admin changes a sign-in email. The refusal is
    the same sentence whatever was asked -- the route does not even read the body -- so it
    says nothing about any address, and nothing is sent anywhere.
    """
    del db, identity  # the refusal depends on nothing the caller sent
    raise PermissionDeniedError(EMAIL_CHANGE_STAFF_ONLY)


def cancel_email_change(db: Session, *, identity: CustomerIdentity, ip_address: str | None) -> None:
    close_pending_email_changes(db, identity, reason_code="cancelled", ip_address=ip_address)


def withdraw_pending_email_changes(
    db: Session, identity: CustomerIdentity, *, ip_address: str | None
) -> None:
    """Close a request made before RC-UAT-25 and kill its link. Audited only when one was open.

    Called on the read of "Sign-in and security": the page no longer offers the change, so a
    request still waiting there must not keep a working link in somebody's mailbox.
    """
    close_pending_email_changes(
        db, identity, reason_code=REASON_SELF_SERVICE_WITHDRAWN, ip_address=ip_address
    )


def close_pending_email_changes(
    db: Session, identity: CustomerIdentity, *, reason_code: str, ip_address: str | None
) -> None:
    """Cancel every open email-change request and kill every ``email_change`` token. Audited.

    Called by the customer's own cancel, by a password change or reset (review HIGH 1), by
    the read of the security page and by an Admin's change of the sign-in email.
    """
    closed = _close_open_requests(db, identity, status=CANCELLED)
    killed = customer_identity_service.invalidate_tokens(
        db, identity, purpose=TokenPurpose.EMAIL_CHANGE, reason_code=reason_code
    )
    # The customer's own cancel is always recorded; anything else records it only when there
    # was something to cancel.
    if closed or killed or reason_code == "cancelled":
        audit.email_change_cancelled(
            db, identity=identity, ip_address=ip_address, reason_code=reason_code
        )


def confirm_email_change(db: Session, *, token: object, ip_address: str | None) -> None:
    """Refuse a confirmation link. Every link, valid or not, gets the same answer.

    RC-UAT-25 item 2: a link sent before the customer path was withdrawn no longer changes
    anything. A live one is consumed (it cannot be tried again) and its request is closed
    ``refused`` with ``self_service_withdrawn``; unknown, malformed, expired and used links are
    audited as before. The account, its sessions and its linked customer are untouched.
    """
    if not isinstance(token, str) or not token or len(token) > 200:
        audit.verification_refused(
            db,
            identity=None,
            reason_code="malformed",
            purpose=TokenPurpose.EMAIL_CHANGE.value,
            ip_address=ip_address,
        )
        return
    redemption = customer_identity_service.redeem_token(
        db, token=token, purpose=TokenPurpose.EMAIL_CHANGE
    )
    if not redemption.ok or redemption.identity is None or redemption.token is None:
        audit.verification_refused(
            db,
            identity=None,
            reason_code=redemption.reason_code,
            purpose=TokenPurpose.EMAIL_CHANGE.value,
            ip_address=ip_address,
        )
        return
    row = db.scalar(
        select(CustomerEmailChangeRequest).where(
            CustomerEmailChangeRequest.token_id == redemption.token.id
        )
    )
    if row is not None and row.status == PENDING:
        row.status, row.closed_at = REFUSED, utcnow()
        row.refused_reason_code = REASON_SELF_SERVICE_WITHDRAWN
    audit.email_change_refused(
        db,
        identity=redemption.identity,
        reason_code=REASON_SELF_SERVICE_WITHDRAWN,
        ip_address=ip_address,
    )


# --- Admin changes a customer's sign-in email (RC-UAT-25 item 2) ----------------------------

#: Bounded, like every lifecycle reason here (mirrored in the staff screen).
CHANGE_EMAIL_REASON_CODES: tuple[str, ...] = (
    "customer_request",
    "mailbox_lost",
    "entered_in_error",
)
#: The statuses whose sign-in email an Admin may change. Not ``pending_verification`` (the
#: address was never proved; the applicant registers again with the right one), not
#: ``rejected`` or ``deactivated`` (closed accounts: reinstate first) -- stand-in RC25-B2.
EMAIL_CHANGEABLE_STATUSES = frozenset(
    {
        IdentityStatus.PENDING_APPROVAL.value,
        IdentityStatus.ACTIVE.value,
        IdentityStatus.SUSPENDED.value,
    }
)
ADDRESS_HELD_BY_ACCOUNT = "That address is already the sign-in email of another Customer Account."
ADDRESS_HELD_BY_CUSTOMER = "That address is already the email of another customer record."


def can_change_sign_in_email(identity: CustomerIdentity) -> bool:
    return identity.status in EMAIL_CHANGEABLE_STATUSES


def sign_in_email_change_refusal(identity: CustomerIdentity) -> str | None:
    if can_change_sign_in_email(identity):
        return None
    return (
        "Only the sign-in email of a pending-approval, active or suspended account can be "
        f"changed; this one is {identity.status}."
    )


@dataclass(frozen=True)
class StaffEmailChange:
    record: CustomerAccountEmailChange
    sessions_revoked: int


def change_sign_in_email_by_staff(
    db: Session,
    identity: CustomerIdentity,
    *,
    new_email: object,
    reason_code: str,
    note: str | None,
    actor,
    ip_address: str | None,
) -> StaffEmailChange:
    """An Admin moves the account to a new sign-in email. Raises on refusal; changes nothing then.

    The route holds the Admin-only permission. Refusals: a reason outside
    ``CHANGE_EMAIL_REASON_CODES``, a note over ``NOTE_MAX_LENGTH``, a malformed address, the
    account's own address, an account in a status that cannot change (``ConflictError``), an
    address held by another account or another customer record (``ConflictError``, which
    names which -- staff may know, the customer was never asked).
    """
    if reason_code not in CHANGE_EMAIL_REASON_CODES:
        raise ValidationError("Choose one of the listed reasons.", field="reason_code")
    note = (note or "").strip() or None
    if note is not None and len(note) > NOTE_MAX_LENGTH:
        raise ValidationError(f"Keep the note under {NOTE_MAX_LENGTH} characters.", field="note")
    if not isinstance(new_email, str):
        raise ValidationError(INVALID_EMAIL_MESSAGE, field="new_email")
    try:
        entered, normalized = normalize_email(new_email)
    except ValueError as exc:
        raise ValidationError(INVALID_EMAIL_MESSAGE, field="new_email") from exc
    if not entered or not normalized:
        raise ValidationError(INVALID_EMAIL_MESSAGE, field="new_email")
    if normalized == identity.email_normalized:
        raise ValidationError(SAME_EMAIL, field="new_email")
    refusal = sign_in_email_change_refusal(identity)
    if refusal is not None:
        raise ConflictError(refusal)
    held = address_refusal(db, identity, normalized)
    if held is not None:
        raise ConflictError(
            ADDRESS_HELD_BY_ACCOUNT if held == REASON_IN_USE_IDENTITY else ADDRESS_HELD_BY_CUSTOMER
        )

    old_entered, old_normalized = identity.email_entered, identity.email_normalized
    customer = linked_customer(db, identity)
    try:
        # A true race (a registration committing the same address between the check and
        # this write) is decided by the unique index, inside a savepoint.
        with db.begin_nested():
            identity.email_entered = entered
            identity.email_normalized = normalized
            db.flush()
    except IntegrityError as exc:
        db.refresh(identity)
        raise ConflictError(ADDRESS_HELD_BY_ACCOUNT) from exc

    if customer is not None and customer.email_normalized != normalized:
        # The single email rule: a linked customer's email is the account's sign-in email.
        # Written directly, as the approval and the old confirmation did, because
        # ``customer_service.update_customer`` refuses an email change on a linked customer.
        customer.email_entered = entered
        customer.email_normalized = normalized
    # Links went to the old address (reset, verification) or to an address nobody chose here
    # (a pre-RC-UAT-25 change request): none survives the change.
    # (Closed here rather than through ``close_pending_email_changes``, whose audit row names
    # the customer as the actor; this change is the Admin's and is audited below.)
    _close_open_requests(db, identity, status=CANCELLED)
    for purpose in (
        TokenPurpose.EMAIL_CHANGE,
        TokenPurpose.PASSWORD_RESET,
        TokenPurpose.EMAIL_VERIFICATION,
    ):
        customer_identity_service.invalidate_tokens(
            db, identity, purpose=purpose, reason_code="email_changed_by_staff"
        )
    # Every session ends: whoever is signed in signs in again with the new address.
    revoked = customer_auth_service.revoke_all_sessions(
        db, identity, reason_code="email_changed_by_staff"
    )
    record = CustomerAccountEmailChange(
        identity_id=identity.id,
        customer_id=customer.id if customer is not None else None,
        previous_email_entered=old_entered,
        new_email_entered=entered,
        reason_code=reason_code,
        note=note,
        sessions_revoked=revoked,
        changed_at=utcnow(),
        changed_by_user_id=actor.id if actor is not None else None,
    )
    db.add(record)
    db.flush()
    language = _language(db, identity)
    email.send(
        email.OutboundEmail(
            to_email=old_entered,
            template_key=email.TEMPLATE_EMAIL_CHANGED_NOTICE,
            language=language,
            parameters={},
        )
    )
    email.send(
        email.OutboundEmail(
            to_email=entered,
            template_key=email.TEMPLATE_SIGN_IN_EMAIL_SET_BY_STAFF,
            language=language,
            parameters={"sign_in_url": customer_identity_service.account_sign_in_url()},
        )
    )
    audit.sign_in_email_changed_by_staff(
        db,
        identity=identity,
        actor=actor,
        customer_public_id=customer.public_id if customer is not None else None,
        reason_code=reason_code,
        previous_email_normalized=old_normalized,
        new_email_normalized=normalized,
        sessions_revoked=revoked,
        ip_address=ip_address,
    )
    return StaffEmailChange(record=record, sessions_revoked=revoked)


# --- Reinstating a deactivated account ----------------------------------------------------------

#: Bounded, like every lifecycle reason here (mirrored in the staff screen).
REACTIVATE_REASON_CODES: tuple[str, ...] = (
    "deactivated_in_error",
    "customer_request",
    "review_complete",
)
#: Deactivations that are not reversed (stand-in B-5): a privacy request is the customer
#: asking to be forgotten, and reinstating it would undo their request.
IRREVERSIBLE_DEACTIVATION_REASONS = frozenset({"privacy_request"})
NOTE_MAX_LENGTH = 500


def reactivation_refusal(identity: CustomerIdentity) -> str | None:
    """Why this account cannot be reinstated, as a staff-facing sentence, or ``None``."""
    if identity.status != IdentityStatus.DEACTIVATED.value:
        return f"Only a deactivated account can be reinstated; this one is {identity.status}."
    if identity.status_reason_code in IRREVERSIBLE_DEACTIVATION_REASONS:
        return "This account was deactivated on a privacy request and cannot be reinstated."
    if identity.rejected_at is not None and identity.approved_at is None:
        return "This application was rejected before it was deactivated; it cannot be reinstated."
    return None


def can_reactivate(identity: CustomerIdentity) -> bool:
    return reactivation_refusal(identity) is None


def merge_exposure(db: Session, identity: CustomerIdentity, customer: Customer) -> str | None:
    """Why the linked customer's history is no longer the one the account was linked to.

    ``merged_since_deactivation`` -- the customer was merged away (it is a tombstone), or any
    customer was merged **into** it at or after the deactivation (it absorbed history the
    account never saw; with no deactivation time on record, any merge into it counts);
    ``archived_since_deactivation`` -- the customer is archived. ``None`` when neither.
    """
    if customer.merged_into_customer_id is not None or customer.merged_at is not None:
        return "merged_since_deactivation"
    incoming = select(Customer.id).where(Customer.merged_into_customer_id == customer.id)
    if identity.deactivated_at is not None:
        incoming = incoming.where(Customer.merged_at >= identity.deactivated_at)
    if db.scalar(incoming.limit(1)) is not None:
        return "merged_since_deactivation"
    if customer.is_archived:
        return "archived_since_deactivation"
    return None


def restored_status(db: Session, identity: CustomerIdentity) -> str:
    """The usable status the account had before it was deactivated.

    Suspended stays suspended (the suspension is lifted separately); approved with its link
    still active returns to ``active``; otherwise the furthest it had got -- verified means
    ``pending_approval`` (a link taken over meanwhile also lands here, for a person to decide),
    unverified ``pending_verification``. Never a second door into ``active``.
    """
    if identity.suspended_at is not None:
        return IdentityStatus.SUSPENDED.value
    if identity.approved_at is not None and linked_customer(db, identity) is not None:
        return IdentityStatus.ACTIVE.value
    if identity.email_verified_at is not None:
        return IdentityStatus.PENDING_APPROVAL.value
    return IdentityStatus.PENDING_VERIFICATION.value


def reactivate(
    db: Session,
    identity: CustomerIdentity,
    *,
    reason_code: str,
    note: str | None,
    actor,
    ip_address: str | None,
) -> CustomerAccountReinstatement:
    if reason_code not in REACTIVATE_REASON_CODES:
        raise ValidationError("Choose one of the listed reasons.", field="reason_code")
    note = (note or "").strip() or None
    if note is not None and len(note) > NOTE_MAX_LENGTH:
        raise ValidationError(f"Keep the note under {NOTE_MAX_LENGTH} characters.", field="note")
    refusal = reactivation_refusal(identity)
    if refusal is not None:
        raise ConflictError(refusal)

    deactivation_reason = identity.status_reason_code
    deactivated_at = identity.deactivated_at
    deactivated_by = identity.deactivated_by_user_id
    customer = linked_customer(db, identity)
    exposure = merge_exposure(db, identity, customer) if customer is not None else None
    if exposure is not None:
        # Review HIGH 2: never back onto a merged, archived or grown history. The link ends
        # here, so the account cannot reach the customer until staff link it afresh.
        _end_link(db, identity, customer, reason_code=exposure, actor=actor, ip_address=ip_address)
        customer = None
    target = restored_status(db, identity)
    record = CustomerAccountReinstatement(
        identity_id=identity.id,
        deactivated_at=deactivated_at,
        deactivated_by_user_id=deactivated_by,
        deactivation_reason_code=deactivation_reason,
        restored_status=target,
        reason_code=reason_code,
        note=note,
        reinstated_at=utcnow(),
        reinstated_by_user_id=actor.id if actor is not None else None,
    )
    if target == IdentityStatus.ACTIVE.value and customer is not None:
        # The single email rule again: while the account was deactivated its link held
        # nothing, so staff may have changed the customer's email. Returning to `active`
        # puts the sign-in email back on the record, as an approval would (stand-in B-6).
        from app.services import customer_account_review_service as review  # noqa: PLC0415
        from app.services import customer_service  # noqa: PLC0415

        change = review.sign_in_email_change(identity, customer)
        if change is not None:
            customer_service.update_customer(
                db, customer, {"email": identity.email_entered}, actor=actor, ip_address=ip_address
            )
            audit.sign_in_email_applied(
                db,
                identity=identity,
                actor=actor,
                customer_public_id=customer.public_id,
                previous_email_present=bool(change["current"]),
                ip_address=ip_address,
            )
    customer_identity_service.restore_after_deactivation(
        db, identity, status=target, reason_code=reason_code
    )
    db.add(record)
    db.flush()
    audit.reactivated(
        db,
        identity=identity,
        reason_code=reason_code,
        deactivation_reason_code=deactivation_reason,
        actor=actor,
        ip_address=ip_address,
        link_ended_reason=exposure,
    )
    if _authenticatable(identity):
        email.send(
            email.OutboundEmail(
                to_email=identity.email_entered,
                template_key=email.TEMPLATE_ACCOUNT_REINSTATED,
                language=_language(db, identity),
                parameters={"sign_in_url": customer_identity_service.account_sign_in_url()},
            )
        )
    return record


def _end_link(
    db: Session,
    identity: CustomerIdentity,
    customer: Customer,
    *,
    reason_code: str,
    actor,
    ip_address: str | None,
) -> None:
    link = db.scalar(
        select(CustomerIdentityLink).where(
            CustomerIdentityLink.identity_id == identity.id,
            CustomerIdentityLink.customer_id == customer.id,
            CustomerIdentityLink.status == LinkStatus.ACTIVE.value,
        )
    )
    if link is None:  # pragma: no cover - linked_customer found it a moment ago
        return
    link.status = LinkStatus.REVOKED.value
    link.revoked_at = utcnow()
    link.revoked_by_user_id = actor.id if actor is not None else None
    link.revoke_reason_code = reason_code
    db.flush()
    audit.link_ended_on_reinstatement(
        db,
        identity=identity,
        customer_public_id=customer.public_id,
        reason_code=reason_code,
        actor=actor,
        ip_address=ip_address,
    )


def deactivated_identities(db: Session, *, limit: int = 200) -> list[CustomerIdentity]:
    return list(
        db.scalars(
            select(CustomerIdentity)
            .where(CustomerIdentity.status == IdentityStatus.DEACTIVATED.value)
            .order_by(CustomerIdentity.deactivated_at.desc(), CustomerIdentity.id.desc())
            .limit(limit)
        )
    )
