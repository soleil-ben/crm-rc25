"""The only path to an active Customer Account. Approve, link, reject.

**This module is the sole writer of ``IdentityStatus.ACTIVE``** and the sole writer of a
``customer_identity_links`` row. Phase 9 built the table and wrote nothing into it; this is
the phase that does, and keeping it to one module is what makes
`tests/test_account_activation_invariant.py` able to say so by scanning the source rather
than by hoping.

---

## How the guards work, given SQLite

There is no useful ``SELECT ... FOR UPDATE`` here, so every concurrency guard is a
**conditional write, a unique constraint or a claim**, in this order:

1. **The idempotency claim.** An ``INSERT`` into ``customer_account_approval_attempts``
   whose ``idempotency_key_digest`` is unique. Whoever inserts first owns the operation; a
   second inserter gets an ``IntegrityError``, reads the existing row, and either replays
   its outcome or refuses it as a conflict when the key was reused for different data.
2. **The staleness check.** Every material fact is recomputed and compared with the
   acknowledged fingerprint. This is not a lock and is not pretending to be one -- it
   closes the window between reading a preview and acting on it, and the writes below
   close the window between two simultaneous actions.
3. **The conditional status update.** ``UPDATE customer_identities SET status = ...
   WHERE id = ? AND status = 'pending_approval'``, with the affected row count checked.
   Approve and reject both take this update, so an approve/reject race has exactly one
   winner and the loser gets a conflict rather than a second decision.
4. **The partial unique indexes.** ``uq_customer_identity_links_active_identity`` and
   ``uq_customer_identity_links_active_customer``, from the Phase 9 migration. They are
   the guard that survives two processes and two connections, which an application check
   does not.

The order matters. The link row is inserted **before** the status flip, so a failure of
the unique index leaves an identity that is still pending rather than one that is active
with no link. Both are in one transaction and a failure rolls the whole thing back, so the
ordering is a second line of defence rather than the only one -- which is the point.

---

## What each path writes

**Create-new** writes, in one transaction: the idempotency claim; a ``customers`` row
through ``customer_service.create_customer``; address rows through
``customer_address_service``; a ``consent_events`` row through ``consent_service`` **only**
when the applicant explicitly chose marketing and the address is not suppressed; the
proposal's status and per-field ``applied`` flags; the link row; the identity's status;
and the audit rows. If any of it fails, none of it happened.

**Link-existing** writes the same *except* the canonical customer and its addresses. It
writes **one canonical value and no other**: the customer already exists, somebody else's
judgement is already recorded on it, and OD-28 says proposal values that differ must not
silently overwrite it. The differences are recorded as field **keys** in the audit payload
and left ``applied = false`` on the proposal, which is where Phase 12 change-proposal
handling will pick them up. An explicit marketing choice is carried over (UAT round 5), as
an appended consent event under the same rules as create-new, because consent is the
applicant's own statement rather than a value on somebody else's record.

The one value is the **email** (owner decision, 2026-10-15: a customer has one email).
When the record's address differs from the account's verified sign-in address, the
approval writes the sign-in address to the record, through ``customer_service`` and its
``customer.update`` row, plus ``customer_account.sign_in_email_applied``. The preview
shows the change before the reviewer confirms, and it is in the fingerprint, so it cannot
happen silently. The consent event then lands on the record's own address.

**Takeover.** A customer whose only link belongs to a **deactivated** account may be
linked to a new one. The approval ends the old link (``revoked``, reason
``taken_over_by_new_account``, audited as ``customer_account.unlink``) in the same
transaction, before the new row is inserted, so the partial unique index still holds. A
link held by an active or suspended account still refuses (owner decision, 2026-10-15).
No message is sent to the former holder; the takeover is audited only (owner decision,
2026-10-16).

**Rejection** writes no customer and no link. It moves the identity to ``rejected``, marks
the proposal rejected, revokes every session and invalidates every outstanding token, so
the credential stops working on the next request rather than at the next sign-in.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core import account_field_mapping as mapping
from app.core.account_enums import (
    CLASSIFICATIONS_REQUIRING_OVERRIDE as _OVERRIDE_REQUIRED,
)
from app.core.account_enums import (
    ApprovalAction,
    ApprovalOutcome,
    IdentityStatus,
    LinkRole,
    LinkStatus,
    ProposalStatus,
    RejectionReason,
    SeparateCustomerReason,
    TokenPurpose,
)
from app.core.account_security import fingerprint as compute_fingerprint
from app.core.account_security import opaque_digest
from app.core.config import account_delivery_blockers, settings
from app.core.enums import ConsentBasis, ConsentChannel, ConsentStatus
from app.core.time_utils import utcnow
from app.models import (
    ConsentEvent,
    Customer,
    CustomerAccountApprovalAttempt,
    CustomerDataProposal,
    CustomerIdAlias,
    CustomerIdentity,
    CustomerIdentityLink,
    User,
)
from app.services import account_email_service as email
from app.services import (
    consent_service,
    customer_address_service,
    customer_auth_service,
    customer_service,
)
from app.services import customer_account_audit as audit
from app.services import customer_account_review_service as review
from app.services import customer_identity_service as identity_service
from app.services.errors import ConflictError, ValidationError

#: The action value recorded on an attempt row for a rejection. Not an ``ApprovalAction``:
#: rejection is not an approval, and giving it a member of that enum would make
#: ``ApprovalAction`` mean "decision" while still being called approval.
REJECT_ACTION = "reject"

#: Reason code on an approval that needed no override.
REASON_NO_DUPLICATE = "no_duplicate_candidate"


@dataclass(frozen=True)
class DecisionResult:
    """What a decision did, for the route to serialize and for a test to assert on."""

    account_reference: str
    status: str
    customer_public_id: str | None
    outcome: str
    replayed: bool


# --- The idempotency claim ----------------------------------------------------


def _request_fingerprint(action: str, customer_public_id: str | None, reason_code: str) -> str:
    """What "the same request" means for an idempotency key.

    The action, the target and the reason code. Two requests agreeing on all three are the
    same decision and the second is a replay; disagreeing on any of them means one key is
    being used for two different decisions, which is a conflict rather than something to
    resolve by guessing which one was meant.
    """
    return compute_fingerprint(
        [f"action={action}", f"target={customer_public_id or ''}", f"reason={reason_code}"]
    )


def _claim(
    db: Session,
    *,
    identity: CustomerIdentity,
    actor: User,
    action: str,
    customer_public_id: str | None,
    reason_code: str,
    idempotency_key: str,
    customer_id: int | None,
) -> CustomerAccountApprovalAttempt:
    """Insert the claim, or raise on a key that is already spoken for.

    Uses a ``SAVEPOINT`` so an ``IntegrityError`` from the unique index does not poison the
    surrounding transaction. The alternative -- selecting first and inserting second --
    loses the race this exists to win.
    """
    digest = opaque_digest(idempotency_key)
    request = _request_fingerprint(action, customer_public_id, reason_code)

    attempt = CustomerAccountApprovalAttempt(
        idempotency_key_digest=digest,
        identity_id=identity.id,
        action=action,
        customer_id=customer_id,
        request_fingerprint=request,
        outcome=ApprovalOutcome.CONFLICT.value,
        reason_code=reason_code,
        actor_user_id=actor.id,
        created_at=utcnow(),
    )
    try:
        with db.begin_nested():
            db.add(attempt)
            db.flush()
    except IntegrityError:
        existing = db.scalar(
            select(CustomerAccountApprovalAttempt).where(
                CustomerAccountApprovalAttempt.idempotency_key_digest == digest
            )
        )
        if existing is None:  # pragma: no cover - the index is the only way in here
            raise
        if existing.request_fingerprint != request:
            error = ConflictError(
                "That idempotency key was already used for a different decision. Use a new key.",
                field="idempotency_key",
            )
            error.audit_refusal = _refusal_audit(
                audit.approval_conflict,
                identity_id=identity.id,
                actor=actor,
                action=action,
                reason_code="idempotency_key_reused",
                ip_address=None,
            )
            raise error from None
        raise _Replay(existing) from None
    return attempt


class _Replay(Exception):
    """Internal: this key already completed. Carries the original attempt row."""

    def __init__(self, attempt: CustomerAccountApprovalAttempt) -> None:
        super().__init__("replay")
        self.attempt = attempt


# --- Shared preconditions -----------------------------------------------------


def _verified_and_pending(identity: CustomerIdentity) -> None:
    """Approval needs mailbox control **and** a decision still to make.

    Verification is not approval (OD-23), but approval without it would link a canonical
    customer's whole history to an address nobody has proved they can read -- which is
    T-06 with the one control that makes it hard removed.
    """
    review.require_reviewable(identity)
    if identity.email_verified_at is None:
        raise ConflictError(
            "This applicant has not confirmed their email address, so the account cannot "
            "be approved."
        )


def _refusal_audit(writer, *, identity_id: int, **fields):
    """Defer a refusal's audit row until after its transaction has been discarded.

    The row must survive a refusal that writes nothing else, and writing it inline puts it
    in the transaction that is about to be rolled back. So the call is packaged here and
    `app.core.db.persist_refusal_audit` performs it on a session that has been rolled back
    clean (DEC-0111).

    The identity is carried by **id** rather than by instance: the rollback expires every
    object in the session, and re-loading it inside the hook is what keeps the row's
    ``public_id`` a value read from the database rather than from a detached object.
    """

    def _write(session: Session) -> None:
        identity = session.get(CustomerIdentity, identity_id)
        if identity is None:  # pragma: no cover - the identity cannot vanish mid-request
            return
        writer(session, identity=identity, **fields)

    return _write


def _drift_reason(db: Session, target: Customer | None) -> str:
    """Name the kind of drift for the audit log, without changing the refusal.

    A target that has itself been merged, or that has become the survivor of a merge since
    the preview, is the OD-40 case. Everything else is ordinary drift. The check is a read
    of the customer's own tombstone plus a look for an alias created by a merge into it --
    the two shapes "this record moved" takes.
    """
    if target is None:
        return audit.REASON_PREVIEW_DRIFT
    db.expire(target)
    if target.merged_into_customer_id is not None:
        return audit.REASON_PREVIEW_MERGE_DRIFT
    absorbed = db.scalar(
        select(CustomerIdAlias.id)
        .where(CustomerIdAlias.customer_id == target.id, CustomerIdAlias.reason == "merge")
        .limit(1)
    )
    return audit.REASON_PREVIEW_MERGE_DRIFT if absorbed is not None else audit.REASON_PREVIEW_DRIFT


def _check_preview(
    db: Session,
    *,
    identity: CustomerIdentity,
    proposal: CustomerDataProposal,
    action: str,
    target: Customer | None,
    presented_fingerprint: str,
    actor: User,
    ip_address: str | None,
):
    """Recompute everything and refuse if the world moved. Returns the fresh preview.

    The comparison is against a **recomputed** fingerprint, never against the one stored
    on the acknowledgement: storing a value and comparing it with itself proves only that
    the row exists. The acknowledgement is then looked up by that recomputed value, which
    is what ties "these are the current facts" to "somebody agreed to these facts".
    """
    preview = review.build_preview(
        db, identity=identity, proposal=proposal, action=action, target=target
    )
    if preview.fingerprint != presented_fingerprint:
        # Which kind of drift, for the log only. The refusal is identical either way: a
        # reviewer is told the facts moved, never which fact, because "the customer you
        # named was merged into another one" is a statement about a record the reviewer may
        # have named by guess (OD-40, T-02). Computed here, before the rollback the audit
        # hook performs, because afterwards the target's state is a fresh read of a world
        # that has moved on again.
        reason_code = _drift_reason(db, target)
        error = ConflictError(
            "Something about this registration changed since the preview was taken. "
            "Take a new preview, read it, and acknowledge it again.",
            detail={"code": "preview_stale"},
            field="preview_fingerprint",
        )
        error.audit_refusal = _refusal_audit(
            audit.preview_stale_refused,
            identity_id=identity.id,
            actor=actor,
            action=action,
            presented_fingerprint=presented_fingerprint,
            current_fingerprint=preview.fingerprint,
            ip_address=ip_address,
            reason_code=reason_code,
        )
        raise error
    acknowledged = review.find_acknowledgement(
        db, identity=identity, fingerprint_value=preview.fingerprint
    )
    if acknowledged is None:
        raise ConflictError(
            "The history disclosure for this registration has not been acknowledged. "
            "Read the preview and acknowledge it before approving.",
            field="preview_fingerprint",
        )
    return preview


def _activate(db: Session, identity: CustomerIdentity, *, actor: User) -> None:
    """The conditional update that is the single serialization point for a decision.

    ``WHERE status = 'pending_approval'`` and the row count checked. Two approvals, an
    approval racing a rejection, or an approval of an account somebody already decided all
    land here and exactly one of them affects a row.

    This statement is **the only place in the application that writes ``active``**.
    """
    now = utcnow()
    result = db.execute(
        update(CustomerIdentity)
        .where(
            CustomerIdentity.id == identity.id,
            CustomerIdentity.status == IdentityStatus.PENDING_APPROVAL.value,
        )
        .values(
            status=IdentityStatus.ACTIVE.value,
            approved_at=now,
            approved_by_user_id=actor.id,
            status_reason_code=None,
            updated_at=now,
        )
    )
    if result.rowcount != 1:
        error = ConflictError(
            "This registration was decided by somebody else while you were working on it."
        )
        error.audit_refusal = _refusal_audit(
            audit.approval_conflict,
            identity_id=identity.id,
            actor=actor,
            action="approve",
            reason_code="decided_concurrently",
            ip_address=None,
        )
        raise error
    db.expire(identity)


def _end_deactivated_link(
    db: Session,
    *,
    link: CustomerIdentityLink,
    previous: CustomerIdentity,
    identity: CustomerIdentity,
    customer: Customer,
    actor: User,
    ip_address: str | None,
) -> None:
    """End a deactivated account's link so a new account can take the customer over.

    Conditional on the row still being ``active``: two approvals racing to take over the
    same customer both reach here, one of them ends the link, and the other then loses on
    the unique index when it inserts its own -- a conflict, never two links. The former
    holder is not emailed: the audit row is the whole record (owner decision, 2026-10-16).
    """
    now = utcnow()
    result = db.execute(
        update(CustomerIdentityLink)
        .where(
            CustomerIdentityLink.id == link.id,
            CustomerIdentityLink.status == LinkStatus.ACTIVE.value,
        )
        .values(
            status=LinkStatus.REVOKED.value,
            revoked_at=now,
            revoked_by_user_id=actor.id,
            revoke_reason_code=audit.REASON_TAKEN_OVER,
        )
    )
    if result.rowcount != 1:
        raise ConflictError(
            "This registration was decided by somebody else while you were working on it."
        )
    db.expire(link)
    audit.link_ended_by_takeover(
        db,
        previous_identity_public_id=previous.public_id,
        new_identity_public_id=identity.public_id,
        actor=actor,
        customer_public_id=customer.public_id,
        ip_address=ip_address,
    )


def _apply_sign_in_email(
    db: Session,
    *,
    identity: CustomerIdentity,
    customer: Customer,
    actor: User,
    ip_address: str | None,
) -> bool:
    """Make the customer's email the account's verified sign-in email. ``True`` if it moved.

    The single email rule (owner decision, 2026-10-15). Written through
    ``customer_service.update_customer`` so the record is normalized and audited exactly as
    a staff edit would be, and audited again here to say why.
    """
    change = review.sign_in_email_change(identity, customer)
    if change is None:
        return False
    customer_service.update_customer(
        db,
        customer,
        {"email": identity.email_entered},
        actor=actor,
        ip_address=ip_address,
    )
    audit.sign_in_email_applied(
        db,
        identity=identity,
        actor=actor,
        customer_public_id=customer.public_id,
        previous_email_present=bool(change["current"]),
        ip_address=ip_address,
    )
    return True


def _link(
    db: Session, *, identity: CustomerIdentity, customer: Customer, actor: User
) -> CustomerIdentityLink:
    """Insert the active link, letting the partial unique indexes do the arbitration."""
    link = CustomerIdentityLink(
        identity_id=identity.id,
        customer_id=customer.id,
        link_role=LinkRole.OWNER.value,
        status=LinkStatus.ACTIVE.value,
        linked_at=utcnow(),
        linked_by_user_id=actor.id,
    )
    try:
        with db.begin_nested():
            db.add(link)
            db.flush()
    except IntegrityError as exc:
        raise ConflictError(
            "That customer already has an active Customer Account, or this account is "
            "already linked. Release 1 allows one of each.",
            field="customer_public_id",
        ) from exc
    return link


def write_link(
    db: Session, *, identity: CustomerIdentity, customer: Customer, actor: User
) -> CustomerIdentityLink:
    """The one link constructor, for the staff re-link of an orphaned account (B-13).

    Public so ``customer_account_relink_service`` writes its link through the same insert,
    under the same partial unique indexes, rather than a second construction of the model
    (``tests/test_account_activation_invariant.py`` counts them). It does not activate:
    ``customer_identity_service.activate_relinked`` does, after this.
    """
    return _link(db, identity=identity, customer=customer, actor=actor)


def _close_proposal(
    proposal: CustomerDataProposal,
    *,
    actor: User,
    customer_id: int,
    applied_keys: list[str],
    reason_code: str,
    duplicate_classification: str,
) -> None:
    """Mark the proposal decided, per field.

    ``applied`` is per field because OD-28 makes it per field, and a link-existing approval
    is the case that makes the distinction real: the proposal is approved, and **none** of
    its fields was applied. Setting them all true would be a record that canonical data
    moved when it did not.
    """
    proposal.status = ProposalStatus.APPROVED.value
    proposal.reviewed_at = utcnow()
    proposal.reviewed_by_user_id = actor.id
    proposal.customer_id = customer_id
    proposal.decision_reason_code = reason_code
    proposal.duplicate_review_outcome = duplicate_classification
    applied = set(applied_keys)
    for row in proposal.fields:
        row.applied = row.field_key in applied


def _record_outcome(attempt: CustomerAccountApprovalAttempt, outcome: str, customer_id) -> None:
    attempt.outcome = outcome
    attempt.customer_id = customer_id


def _replay_result(
    db: Session,
    *,
    identity: CustomerIdentity,
    actor: User,
    attempt: CustomerAccountApprovalAttempt,
    ip_address: str | None,
) -> DecisionResult:
    """Report the original outcome again and write nothing else."""
    audit.approval_replayed(
        db,
        identity=identity,
        actor=actor,
        action=attempt.action,
        outcome=attempt.outcome,
        ip_address=ip_address,
    )
    customer = db.get(Customer, attempt.customer_id) if attempt.customer_id else None
    return DecisionResult(
        account_reference=identity.public_id,
        status=identity.status,
        customer_public_id=customer.public_id if customer else None,
        outcome=attempt.outcome,
        replayed=True,
    )


# --- Create-new ---------------------------------------------------------------


def approve_create_new(
    db: Session,
    *,
    identity: CustomerIdentity,
    actor: User,
    preview_fingerprint: str,
    idempotency_key: str,
    override_reason_code: str | None,
    ip_address: str | None,
) -> DecisionResult:
    """Approve by creating a new canonical customer, then linking and activating.

    The customer is created by ``customer_service.create_customer`` and its addresses by
    ``customer_address_service``, not by constructing models here. That is the
    instruction's requirement, and it is also what makes this customer indistinguishable
    from one a staff member typed: same validation, same normalization, same ``public_id``
    allocation, same ``customer.create`` audit row.
    """
    # The claim comes **first**, before any precondition. A retry of an approval that
    # already succeeded arrives at an identity that is now `active`, and a precondition
    # check in front of the claim would call that a conflict -- turning a lost response
    # into an error the caller cannot tell apart from a real one. Idempotency means the
    # second request reports the first one's outcome, so the claim has to be what decides.
    try:
        attempt = _claim(
            db,
            identity=identity,
            actor=actor,
            action=ApprovalAction.CREATE_NEW.value,
            customer_public_id=None,
            reason_code=override_reason_code or REASON_NO_DUPLICATE,
            idempotency_key=idempotency_key,
            customer_id=None,
        )
    except _Replay as replay:
        return _replay_result(
            db, identity=identity, actor=actor, attempt=replay.attempt, ip_address=ip_address
        )

    _verified_and_pending(identity)
    proposal = review.current_proposal(db, identity)

    preview = _check_preview(
        db,
        identity=identity,
        proposal=proposal,
        action=ApprovalAction.CREATE_NEW.value,
        target=None,
        presented_fingerprint=preview_fingerprint,
        actor=actor,
        ip_address=ip_address,
    )

    # A candidate exists and the reviewer is creating a separate record anyway. That is a
    # decision, so it needs a reason code from a closed vocabulary -- not free text, and
    # not silence (OD-28).
    if preview.duplicate_classification in {value.value for value in _OVERRIDE_REQUIRED}:
        if override_reason_code is None:
            raise ConflictError(
                "This registration matches an existing customer. Link to it, or say why "
                "a separate customer is correct.",
                field="override_reason_code",
                detail={"duplicate_classification": preview.duplicate_classification},
            )
        audit.separate_customer_override(
            db,
            identity=identity,
            actor=actor,
            classification=preview.duplicate_classification,
            candidate_public_ids=preview.candidate_references,
            reason_code=override_reason_code,
            ip_address=ip_address,
        )
    elif override_reason_code is not None:
        raise ValidationError(
            "There is no duplicate candidate, so there is nothing to override.",
            field="override_reason_code",
        )

    entered = review.effective_values(identity, proposal)
    try:
        mapped = mapping.resolve_customer_payload(entered)
    except mapping.MappingRefused as exc:
        raise ValidationError(exc.message, field=exc.field_key) from exc

    customer = customer_service.create_customer(
        db, mapped.customer, actor=actor, ip_address=ip_address
    )
    for address in mapped.addresses:
        created = customer_address_service.create_address(
            db,
            customer,
            address.values,
            contact_name=address.contact_name,
            role=address.role,
        )
        if address.is_default_sender:
            created.is_default_sender = True
            customer_address_service.enforce_single_default(db, created)

    _write_marketing_consent(
        db,
        customer=customer,
        identity=identity,
        proposal=proposal,
        chosen=mapped.marketing_consent,
        address=mapped.marketing_address,
        actor=actor,
        ip_address=ip_address,
    )

    _close_proposal(
        proposal,
        actor=actor,
        customer_id=customer.id,
        applied_keys=mapped.applied_field_keys,
        reason_code=override_reason_code or REASON_NO_DUPLICATE,
        duplicate_classification=preview.duplicate_classification,
    )

    _link(db, identity=identity, customer=customer, actor=actor)
    _activate(db, identity, actor=actor)
    _record_outcome(attempt, ApprovalOutcome.APPROVED_CREATED.value, customer.id)

    audit.approved(
        db,
        identity=identity,
        actor=actor,
        action=ApprovalAction.CREATE_NEW.value,
        customer_public_id=customer.public_id,
        applied_field_keys=mapped.applied_field_keys,
        summary_detail=preview.disclosure.as_audit_detail(),
        fingerprint=preview.fingerprint,
        reason_code=override_reason_code or REASON_NO_DUPLICATE,
        ip_address=ip_address,
    )
    audit.linked(
        db,
        identity=identity,
        actor=actor,
        customer_public_id=customer.public_id,
        link_role=LinkRole.OWNER.value,
        differing_field_keys=[],
        ip_address=ip_address,
    )
    _notify_approved(db, identity)

    return DecisionResult(
        account_reference=identity.public_id,
        status=IdentityStatus.ACTIVE.value,
        customer_public_id=customer.public_id,
        outcome=ApprovalOutcome.APPROVED_CREATED.value,
        replayed=False,
    )


#: The ``source`` on a consent event carried from a registration's marketing choice.
REGISTRATION_CONSENT_SOURCE = "customer_account_registration"


def _write_marketing_consent(
    db: Session,
    *,
    customer: Customer,
    identity: CustomerIdentity,
    proposal: CustomerDataProposal,
    chosen: bool,
    address: str | None,
    actor: User,
    ip_address: str | None,
) -> None:
    """Write a consent event **only** when the applicant explicitly chose marketing.

    Both approval paths call this: create-new for the customer it has just made, and
    link-existing for the customer the reviewer named (UAT round 5: the choice was lost on
    a link). The event is express consent for the address the applicant proved they
    control, with the account reference as its evidence and the registration's submission
    time as when it was obtained.

    Four rules hold here, and each of them is a thing that has gone wrong elsewhere:

    * **Absent is not consent.** No row at all unless ``marketing_consent`` is true
      (OD-38). A default-on checkbox would be a row here; there is no checkbox and no row.
    * **Terms acknowledgement is not marketing consent.** They are different tables
      written at different times, and nothing in this function reads the acknowledgement.
    * **A suppression wins.** ``consent_service`` refuses a consent grant against a
      suppressed address and this function lets that refusal stand silently rather than
      failing the whole approval: the account is still approved, the suppression is still
      in force, and nothing reports its existence (OD-27, T-08). The opt-in stays
      ineffective while suppressed; account email is unaffected (UAT round 6).
    * **A later answer wins.** On a linked customer, a consent event for the same address
      recorded after the registration was submitted is newer evidence than the checkbox,
      so the checkbox is not replayed over it.
    """
    if not chosen or not address:
        return
    submitted_at = proposal.submitted_at
    if submitted_at is not None:
        normalized = consent_service.normalized_input_address(ConsentChannel.EMAIL.value, address)
        newer = db.scalar(
            select(ConsentEvent.id)
            .where(
                ConsentEvent.customer_id == customer.id,
                ConsentEvent.channel == ConsentChannel.EMAIL.value,
                ConsentEvent.address_value == normalized,
                ConsentEvent.recorded_at > submitted_at,
            )
            .limit(1)
        )
        if newer is not None:
            return
    try:
        consent_service.record_consent_event(
            db,
            customer,
            channel=ConsentChannel.EMAIL.value,
            status=ConsentStatus.CONSENTED.value,
            basis=ConsentBasis.EXPRESS.value,
            address_value=address,
            obtained_at=submitted_at or utcnow(),
            source=REGISTRATION_CONSENT_SOURCE,
            evidence_reference=f"Customer Account registration {identity.public_id}",
            actor=actor,
            ip_address=ip_address,
        )
    except ConflictError:
        # Suppressed. The suppression stands and the approval continues.
        return


# --- Link-existing ------------------------------------------------------------


def approve_link_existing(
    db: Session,
    *,
    identity: CustomerIdentity,
    actor: User,
    customer_public_id: str,
    preview_fingerprint: str,
    idempotency_key: str,
    ip_address: str | None,
) -> DecisionResult:
    """Approve by linking to a customer the reviewer named. Writes no canonical value.

    Every difference between what the applicant submitted and what the record holds is
    reported and **not applied**. That is OD-28 read literally: a person filling in a
    registration form is not thereby editing a customer record that somebody else
    maintains, and an approval that quietly applied their version would make registration
    a write path into the CRM by another name.
    """
    # Claimed first, for the reason `approve_create_new` gives, and claimed against the
    # **requested** reference rather than a resolved row: resolving can itself refuse --
    # the customer may have been archived or merged since -- and a retry has to reach the
    # replay rather than that refusal.
    requested = customer_public_id.strip().upper()
    try:
        attempt = _claim(
            db,
            identity=identity,
            actor=actor,
            action=ApprovalAction.LINK_EXISTING.value,
            customer_public_id=requested,
            reason_code=REASON_NO_DUPLICATE,
            idempotency_key=idempotency_key,
            customer_id=None,
        )
    except _Replay as replay:
        return _replay_result(
            db, identity=identity, actor=actor, attempt=replay.attempt, ip_address=ip_address
        )

    _verified_and_pending(identity)
    proposal = review.current_proposal(db, identity)
    customer = review.resolve_link_target(db, requested)

    if review.active_link_for_identity(db, identity.id) is not None:
        raise ConflictError("This account is already linked to a customer.")
    # A link held by a deactivated account is the one an approval may end (owner decision,
    # 2026-10-15). Any other active link still refuses.
    takeover = review.deactivated_link_for_customer(db, customer.id)
    if takeover is None and review.active_link_for_customer(db, customer.id) is not None:
        raise ConflictError(
            f"{customer.public_id} already has an active Customer Account. Release 1 allows one.",
            field="customer_public_id",
        )

    preview = _check_preview(
        db,
        identity=identity,
        proposal=proposal,
        action=ApprovalAction.LINK_EXISTING.value,
        target=customer,
        presented_fingerprint=preview_fingerprint,
        actor=actor,
        ip_address=ip_address,
    )

    differing = [str(row["field"]) for row in preview.differences]

    if takeover is not None:
        link, previous = takeover
        _end_deactivated_link(
            db,
            link=link,
            previous=previous,
            identity=identity,
            customer=customer,
            actor=actor,
            ip_address=ip_address,
        )

    # One email (owner decision, 2026-10-15). Shown in the preview the reviewer acknowledged
    # and covered by its fingerprint, so this write is never a surprise.
    email_applied = _apply_sign_in_email(
        db, identity=identity, customer=customer, actor=actor, ip_address=ip_address
    )
    applied_keys = ["email"] if email_applied else []
    reason_code = "linked_existing_email_applied" if email_applied else "linked_existing_no_apply"

    # The marketing choice is not a canonical value: it is the applicant's own consent,
    # with its own evidence, appended to the history rather than overwriting anything
    # (UAT round 5). The address is the one the applicant proved they control, which is
    # now the record's own address too, so the email state row reflects it.
    entered = review.effective_values(identity, proposal)
    _write_marketing_consent(
        db,
        customer=customer,
        identity=identity,
        proposal=proposal,
        chosen=entered.get("marketing_consent") == "true",
        address=identity.email_entered,
        actor=actor,
        ip_address=ip_address,
    )

    _close_proposal(
        proposal,
        actor=actor,
        customer_id=customer.id,
        # Nothing but the email was applied. The proposal is kept whole for Phase 12.
        applied_keys=applied_keys,
        reason_code=reason_code,
        duplicate_classification=preview.duplicate_classification,
    )

    _link(db, identity=identity, customer=customer, actor=actor)
    _activate(db, identity, actor=actor)
    _record_outcome(attempt, ApprovalOutcome.APPROVED_LINKED.value, customer.id)

    audit.approved(
        db,
        identity=identity,
        actor=actor,
        action=ApprovalAction.LINK_EXISTING.value,
        customer_public_id=customer.public_id,
        applied_field_keys=applied_keys,
        summary_detail=preview.disclosure.as_audit_detail(),
        fingerprint=preview.fingerprint,
        reason_code=reason_code,
        ip_address=ip_address,
    )
    audit.linked(
        db,
        identity=identity,
        actor=actor,
        customer_public_id=customer.public_id,
        link_role=LinkRole.OWNER.value,
        differing_field_keys=differing,
        ip_address=ip_address,
    )
    _notify_approved(db, identity)

    return DecisionResult(
        account_reference=identity.public_id,
        status=IdentityStatus.ACTIVE.value,
        customer_public_id=customer.public_id,
        outcome=ApprovalOutcome.APPROVED_LINKED.value,
        replayed=False,
    )


# --- Rejection ----------------------------------------------------------------


def reject(
    db: Session,
    *,
    identity: CustomerIdentity,
    actor: User,
    reason_code: str,
    idempotency_key: str,
    internal_detail: str | None,
    ip_address: str | None,
) -> DecisionResult:
    """Decline an application. No customer, no link, and the credential stops working.

    No preview and no acknowledgement: there is nothing being disclosed, because nothing
    is being linked. The reason code is bounded and **never reaches the customer** --
    ``GET /api/v1/account/me`` reports the state and no reason, because a reason that said
    "duplicate of an existing customer" would confirm that an existing customer exists
    (`STATE_MACHINES.md` section 1, transition 5).

    ``internal_detail`` is accepted, bounded, and deliberately **not written anywhere**
    in this release -- see the note where it is handled.
    """
    if reason_code not in {member.value for member in RejectionReason}:
        raise ValidationError("Choose one of the recorded rejection reasons.", field="reason_code")
    if internal_detail is not None and len(internal_detail) > 500:
        raise ValidationError(
            "Keep the internal note under 500 characters.", field="internal_detail"
        )

    try:
        attempt = _claim(
            db,
            identity=identity,
            actor=actor,
            action=REJECT_ACTION,
            customer_public_id=None,
            reason_code=reason_code,
            idempotency_key=idempotency_key,
            customer_id=None,
        )
    except _Replay as replay:
        return _replay_result(
            db, identity=identity, actor=actor, attempt=replay.attempt, ip_address=ip_address
        )

    # After the claim, for the reason the two approval paths give: a retry of a rejection
    # that already landed must replay rather than be told the account is already decided.
    review.require_reviewable(identity)

    now = utcnow()
    result = db.execute(
        update(CustomerIdentity)
        .where(
            CustomerIdentity.id == identity.id,
            CustomerIdentity.status == IdentityStatus.PENDING_APPROVAL.value,
        )
        .values(
            status=IdentityStatus.REJECTED.value,
            rejected_at=now,
            rejected_by_user_id=actor.id,
            status_reason_code=reason_code,
            updated_at=now,
        )
    )
    if result.rowcount != 1:
        error = ConflictError(
            "This registration was decided by somebody else while you were working on it."
        )
        error.audit_refusal = _refusal_audit(
            audit.approval_conflict,
            identity_id=identity.id,
            actor=actor,
            action=REJECT_ACTION,
            reason_code="decided_concurrently",
            ip_address=ip_address,
        )
        raise error
    db.expire(identity)

    proposal = db.scalar(
        select(CustomerDataProposal)
        .where(
            CustomerDataProposal.identity_id == identity.id,
            CustomerDataProposal.status == ProposalStatus.PENDING.value,
        )
        .order_by(CustomerDataProposal.id.desc())
    )
    if proposal is not None:
        proposal.status = ProposalStatus.REJECTED.value
        proposal.reviewed_at = now
        proposal.reviewed_by_user_id = actor.id
        proposal.decision_reason_code = reason_code

    # The account must stop working now, not at the next sign-in. Sessions hold no cached
    # grant, so revoking the rows is enough; the outstanding verification and reset links
    # go too, because either of them would otherwise be a way back into a declined
    # account.
    sessions_revoked = customer_auth_service.revoke_all_sessions(
        db, identity, reason_code="rejected"
    )
    tokens_invalidated = 0
    for purpose in TokenPurpose:
        tokens_invalidated += identity_service.invalidate_tokens(
            db, identity, purpose=purpose, reason_code="rejected"
        )

    # `internal_detail` is validated and then dropped. The existing audit redaction rules
    # treat prose about a person as something to keep out of the audit trail, and there is
    # no other store for it in this phase. Accepting and discarding it is worse than not
    # accepting it, so the route documents that it is not retained; the parameter stays so
    # the shape does not change when a reviewed place to put it exists.
    _ = internal_detail

    _record_outcome(attempt, ApprovalOutcome.REJECTED.value, None)
    audit.rejected(
        db,
        identity=identity,
        actor=actor,
        reason_code=reason_code,
        sessions_revoked=sessions_revoked or 0,
        tokens_invalidated=tokens_invalidated,
        ip_address=ip_address,
    )
    _notify_rejected(db, identity)

    return DecisionResult(
        account_reference=identity.public_id,
        status=IdentityStatus.REJECTED.value,
        customer_public_id=None,
        outcome=ApprovalOutcome.REJECTED.value,
        replayed=False,
    )


# --- Notification -------------------------------------------------------------
#
# `EMAIL_DELIVERY.md` section 3 lists `account.approved` and `account.rejected`, so the
# approved specification does require a notification and Phase 10 sends one -- through the
# Phase 9 seam, which in development writes a local file and in test records a send and
# produces nothing. **No production transport exists** and selecting one fails at startup
# (OD-34, DEC-0094). Nothing here opens a socket.
#
# The wording carries no customer id, no duplicate result, no staff name, no shipment
# count and no rejection reason, because a message is forwarded and read by people who
# were not party to the decision. English only (OD-39).
#
# Both are sent after the decision is recorded and before the commit, so a failure of the
# surrounding transaction takes the send with it -- and an idempotent replay returns before
# reaching here, which is how "no duplicate email on retry" is achieved rather than
# promised.


def _may_notify(db: Session, identity: CustomerIdentity) -> bool:
    """Whether a decision notice may be sent at all.

    One reason it may not, and it **does not fail the decision**: a production deployment
    with no chosen provider cannot deliver anything (OD-34), and refusing to approve
    accounts because no mailbox can be reached would be the wrong trade -- the account
    state is the fact, the message is a courtesy.

    A suppression is **not** a reason. It blocks marketing email only, and an approval or
    rejection notice is account email (owner decision, 2026-10-15, UAT round 6).
    """
    return not account_delivery_blockers(settings)


def _notify_approved(db: Session, identity: CustomerIdentity) -> None:
    if not _may_notify(db, identity):
        return
    email.send(
        email.OutboundEmail(
            to_email=identity.email_entered,
            template_key=email.TEMPLATE_ACCOUNT_APPROVED,
            language=identity.preferred_language,
            parameters={"sign_in_url": identity_service.account_sign_in_url()},
        )
    )


def _notify_rejected(db: Session, identity: CustomerIdentity) -> None:
    if not _may_notify(db, identity):
        return
    email.send(
        email.OutboundEmail(
            to_email=identity.email_entered,
            template_key=email.TEMPLATE_ACCOUNT_REJECTED,
            language=identity.preferred_language,
            parameters={},
        )
    )


#: Re-exported so a route can validate against the same vocabulary the service enforces.
REJECTION_REASONS = frozenset(member.value for member in RejectionReason)
SEPARATE_CUSTOMER_REASONS = frozenset(member.value for member in SeparateCustomerReason)
