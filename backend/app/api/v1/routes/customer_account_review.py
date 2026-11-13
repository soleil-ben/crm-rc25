"""Staff routes for reviewing, approving, linking and rejecting Customer Accounts.

**These are Staff Portal routes.** They live under ``/api/v1``, they resolve a staff
session through ``app.api.deps``, and they are guarded by ``require(...)`` like the other
ninety-odd guarded routes -- which is what puts them into
``tests/test_route_permissions.py``'s sweep automatically, per route and per role, the day
they exist.

They are **not** Customer Account routes and must never become them. Nothing here is
reachable with a customer session: a customer cookie has a different name, resolves
against a different table, and produces no ``User`` for ``require`` to check
(`IDENTITY_AND_AUTHORIZATION.md` section 2, T-01, T-12).

**Two permissions, and mutation asks for both.**
``customer_account:review`` reads the queue, one application, its duplicate candidates and
a preview. ``customer_account:approve`` acknowledges, approves, links and rejects, and
every one of those also requires the read permission -- so the power to activate an
account cannot be held without the power to look at what is being activated. Neither is
``duplicate:review``, which Marketing and the read-only manager already hold and which
must reach none of this.

**Every read is audited.** Listing the queue, opening an application, running the
duplicate calculation and taking a preview each write an audit row, because each is an
access to personal data about somebody who is not yet a customer, and "who has been
reading the applications" should be answerable.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request

from app.api.deps import DbSession, client_ip, require
from app.core.db import commit_with_retry, persist_refusal_audit
from app.core.permissions import Permission
from app.models import Customer, User
from app.schemas.customer_account_review import (
    DEACTIVATE_REASON_CODES,
    REINSTATE_REASON_CODES,
    SUSPEND_REASON_CODES,
    AcknowledgeDisclosureRequest,
    AcknowledgementOut,
    ApprovalPreviewOut,
    ApproveCreateNewRequest,
    ApproveLinkExistingRequest,
    CloseOrphanRequest,
    DeactivatedAccountList,
    DeactivatedAccountRow,
    DecisionOut,
    DisclosureOut,
    DuplicateCandidateOut,
    DuplicateReviewOut,
    FieldDifferenceOut,
    IdentityReactivateRequest,
    IdentitySignInEmailChangeRequest,
    IdentityStatusChangeRequest,
    IdentityStatusOut,
    OrphanedAccountList,
    OrphanedAccountRow,
    PendingRegistrationDetail,
    PendingRegistrationPage,
    PendingRegistrationRow,
    ProfileDecisionRequest,
    ProfileProposalQueue,
    ProfileProposalRow,
    ProfileReviewFieldOut,
    ProfileReviewOut,
    ProposalFieldOut,
    RejectRegistrationRequest,
    RelinkPreviewOut,
    RelinkRequest,
)
from app.services import customer_account_approval_service as approval
from app.services import customer_account_audit as audit
from app.services import customer_account_profile_service as profile_review
from app.services import customer_account_relink_service as relink_service
from app.services import customer_account_review_service as review
from app.services import customer_account_security_service as account_security
from app.services import customer_identity_service
from app.services.customer_account_review_service import ApprovalPreview
from app.services.errors import ConflictError, DomainError, ValidationError

router = APIRouter(prefix="/customer-account", tags=["customer-account-review"])

#: Read and mutate, named separately so each route says which it is. A mutating route
#: lists both; `tests/test_account_review_permissions.py` asserts that every one does.
ReviewUser = Annotated[User, Depends(require(Permission.CUSTOMER_ACCOUNT_REVIEW))]
ApproveUser = Annotated[
    User,
    Depends(require(Permission.CUSTOMER_ACCOUNT_REVIEW, Permission.CUSTOMER_ACCOUNT_APPROVE)),
]
#: Deactivation is Admin-only (DEC-0126): review to see the account, plus a permission no
#: role but Admin holds.
DeactivateUser = Annotated[
    User,
    Depends(require(Permission.CUSTOMER_ACCOUNT_REVIEW, Permission.CUSTOMER_ACCOUNT_DEACTIVATE)),
]


def _disclosure_out(preview: ApprovalPreview) -> DisclosureOut:
    summary = preview.disclosure
    return DisclosureOut(
        shipment_count=summary.shipment_count,
        oldest_booked_at=summary.oldest_booked_at,
        newest_booked_at=summary.newest_booked_at,
        includes_cancelled=summary.includes_cancelled,
        includes_rebooked=summary.includes_rebooked,
        definition_version=summary.definition_version,
    )


def _preview_out(preview: ApprovalPreview) -> ApprovalPreviewOut:
    """Copy the preview across field by field. No ``model_validate`` of a dataclass.

    Spelled out rather than mapped, because the point of an allowlist is that adding a
    field to the service does not add it to the response.
    """
    return ApprovalPreviewOut(
        account_reference=preview.account_reference,
        action=preview.action,
        proposal_id=preview.proposal_id,
        proposed=preview.proposed,
        current=preview.current,
        differences=[
            FieldDifferenceOut(
                field=str(row["field"]), proposed=row["proposed"], current=row["current"]
            )
            for row in preview.differences
        ],
        duplicate_classification=preview.duplicate_classification,
        candidate_references=list(preview.candidate_references),
        target_customer_public_id=preview.target_customer_public_id,
        disclosure=_disclosure_out(preview),
        fingerprint=preview.fingerprint,
        mapping_refusal=preview.mapping_refusal,
        email_change=dict(preview.email_change) if preview.email_change else None,
        ends_link_of=preview.ends_link_of,
    )


def _decision_out(result: approval.DecisionResult) -> DecisionOut:
    return DecisionOut(
        account_reference=result.account_reference,
        status=result.status,
        customer_public_id=result.customer_public_id,
        outcome=result.outcome,
        replayed=result.replayed,
    )


# --- Reading ------------------------------------------------------------------


@router.get("/registrations", response_model=PendingRegistrationPage)
def list_pending_registrations(
    request: Request,
    db: DbSession,
    user: ReviewUser,
    limit: int = Query(review.DEFAULT_PAGE_SIZE, ge=1, le=review.MAX_PAGE_SIZE),
    offset: int = Query(0, ge=0),
    account_reference: str | None = Query(None, max_length=20),
    submitted_from: datetime | None = Query(None),
    submitted_to: datetime | None = Query(None),
    sort: str = Query("submitted_at"),
    descending: bool = Query(False),
) -> PendingRegistrationPage:
    """The pending queue: bounded, filtered, totally ordered.

    ``limit`` is capped by the route signature *and* again by the service, because a cap
    that exists only in a FastAPI annotation is a cap that a second caller of the service
    does not have.
    """
    rows, total = review.list_pending(
        db,
        limit=limit,
        offset=offset,
        account_reference=account_reference,
        submitted_from=submitted_from,
        submitted_to=submitted_to,
        sort=sort,
        descending=descending,
    )
    audit.queue_reviewed(db, actor=user, count=len(rows), ip_address=client_ip(request))
    commit_with_retry(db)
    return PendingRegistrationPage(
        items=[
            PendingRegistrationRow(
                account_reference=row.account_reference,
                status=row.status,
                submitted_at=row.submitted_at,
                email_verified_at=row.email_verified_at,
                proposal_id=row.proposal_id,
                field_count=row.field_count,
            )
            for row in rows
        ],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/registrations/{account_reference}", response_model=PendingRegistrationDetail)
def read_pending_registration(
    account_reference: str,
    request: Request,
    db: DbSession,
    user: ReviewUser,
) -> PendingRegistrationDetail:
    """One application and its submitted fields. No duplicate result, no shipment data."""
    identity = review.load_identity(db, account_reference)
    proposal = review.current_proposal(db, identity)
    audit.registration_opened(
        db,
        identity=identity,
        actor=user,
        field_keys=[row.field_key for row in proposal.fields],
        ip_address=client_ip(request),
    )
    commit_with_retry(db)
    return PendingRegistrationDetail(
        account_reference=identity.public_id,
        status=identity.status,
        account_email_entered=identity.email_entered,
        account_email_normalized=identity.email_normalized,
        email_verified_at=identity.email_verified_at,
        preferred_language=identity.preferred_language,
        submitted_at=proposal.submitted_at,
        proposal_id=proposal.id,
        proposal_status=proposal.status,
        fields=[
            ProposalFieldOut(
                field_key=row.field_key,
                value_type=row.value_type,
                proposed_value=row.proposed_value,
                proposed_value_normalized=row.proposed_value_normalized,
                applied=row.applied,
            )
            for row in sorted(proposal.fields, key=lambda row: row.field_key)
        ],
        has_active_link=review.active_link_for_identity(db, identity.id) is not None,
    )


@router.get(
    "/registrations/{account_reference}/duplicate-candidates",
    response_model=DuplicateReviewOut,
)
def read_duplicate_candidates(
    account_reference: str,
    request: Request,
    db: DbSession,
    user: ReviewUser,
) -> DuplicateReviewOut:
    """Candidates from the **existing** duplicate service, and the derived classification.

    Also requires ``duplicate:review``? No -- and deliberately. Holding
    ``duplicate:review`` is not sufficient for account approval, and the converse is the
    same statement: this route is part of the approval decision and is gated by the
    approval-review permission. A reviewer who may activate an account may see the
    candidates that decision turns on.
    """
    identity = review.load_identity(db, account_reference)
    proposal = review.current_proposal(db, identity)
    candidates = review.duplicate_candidates(db, identity, proposal)
    classification = review.classification_for(candidates)
    audit.duplicates_reviewed(
        db,
        identity=identity,
        actor=user,
        classification=classification,
        candidate_public_ids=[row.customer_public_id for row in candidates],
        ip_address=client_ip(request),
    )
    commit_with_retry(db)
    return DuplicateReviewOut(
        account_reference=identity.public_id,
        duplicate_classification=classification,
        candidates=[
            DuplicateCandidateOut(
                customer_public_id=row.customer_public_id,
                full_name=row.full_name,
                display_name=row.display_name,
                city=row.city,
                country_code=row.country_code,
                matched_on=row.matched_on,
                confidence=row.confidence,
                is_archived=row.is_archived,
                is_merged=row.is_merged,
                has_active_identity_link=row.has_active_identity_link,
                linkable=row.linkable,
            )
            for row in candidates
        ],
    )


@router.get("/registrations/{account_reference}/preview", response_model=ApprovalPreviewOut)
def read_approval_preview(
    account_reference: str,
    request: Request,
    db: DbSession,
    user: ReviewUser,
    action: str = Query(..., max_length=20),
    customer_public_id: str | None = Query(None, max_length=20),
) -> ApprovalPreviewOut:
    """Compute the preview for an intended action, server-side.

    A ``GET`` that writes an audit row. That is deliberate: computing a preview is the
    moment a reviewer is shown how much history an approval would disclose, and OD-29
    makes that a thing worth recording. It is otherwise a pure read -- it creates no
    acknowledgement and authorizes nothing.
    """
    identity = review.load_identity(db, account_reference)
    preview, _proposal, target = review.preview_for(
        db, identity=identity, action=action, customer_public_id=customer_public_id
    )
    audit.preview_created(
        db,
        identity=identity,
        actor=user,
        action=preview.action,
        customer_public_id=target.public_id if target else None,
        summary_detail=preview.disclosure.as_audit_detail(),
        fingerprint=preview.fingerprint,
        ip_address=client_ip(request),
    )
    commit_with_retry(db)
    return _preview_out(preview)


# --- Deciding -----------------------------------------------------------------


@router.post(
    "/registrations/{account_reference}/disclosure-acknowledgement",
    response_model=AcknowledgementOut,
)
def acknowledge_disclosure(
    account_reference: str,
    payload: AcknowledgeDisclosureRequest,
    request: Request,
    db: DbSession,
    user: ApproveUser,
) -> AcknowledgementOut:
    """Record that this reviewer saw these figures for this intended action.

    The preview is recomputed here rather than trusted from the request. A fingerprint
    that does not match the freshly computed one is refused, so acknowledging a preview
    that has already gone stale is not a way to pre-authorize an approval.
    """
    identity = review.load_identity(db, account_reference)
    preview, proposal, target = review.preview_for(
        db,
        identity=identity,
        action=payload.action,
        customer_public_id=payload.customer_public_id,
    )
    if preview.fingerprint != payload.fingerprint:
        audit.preview_stale_refused(
            db,
            identity=identity,
            actor=user,
            action=preview.action,
            presented_fingerprint=payload.fingerprint,
            current_fingerprint=preview.fingerprint,
            ip_address=client_ip(request),
        )
        commit_with_retry(db)
        from app.services.errors import ConflictError

        raise ConflictError(
            "This preview is out of date. Take a new one, read it, and acknowledge that.",
            detail={"code": "preview_stale"},
            field="fingerprint",
        )
    row = review.acknowledge(
        db,
        identity=identity,
        preview=preview,
        proposal=proposal,
        target=target,
        actor=user,
        ip_address=client_ip(request),
    )
    commit_with_retry(db)
    return AcknowledgementOut(
        account_reference=identity.public_id,
        action=preview.action,
        target_customer_public_id=preview.target_customer_public_id,
        disclosure=_disclosure_out(preview),
        fingerprint=preview.fingerprint,
        acknowledged_at=row.acknowledged_at,
    )


@router.post("/registrations/{account_reference}/approve/create-new", response_model=DecisionOut)
def approve_by_creating(
    account_reference: str,
    payload: ApproveCreateNewRequest,
    request: Request,
    db: DbSession,
    user: ApproveUser,
) -> DecisionOut:
    """Approve by creating a new canonical customer, linking it and activating the account.

    One transaction. If anything in it fails there is no customer, no address, no consent
    event, no link and no active identity -- the commit is the last thing that happens.
    """
    identity = review.load_identity(db, account_reference)
    try:
        result = approval.approve_create_new(
            db,
            identity=identity,
            actor=user,
            preview_fingerprint=payload.preview_fingerprint,
            idempotency_key=payload.idempotency_key,
            override_reason_code=payload.override_reason_code,
            ip_address=client_ip(request),
        )
    except DomainError as exc:
        # A refused decision writes nothing. The record of the refusal rides on the
        # exception and is written afterwards, on a session rolled back clean, so the
        # audit row survives a rollback that correctly discards everything else
        # (DEC-0111). A refusal carrying no hook is left exactly as it was.
        persist_refusal_audit(db, exc)
        raise
    commit_with_retry(db)
    return _decision_out(result)


@router.post("/registrations/{account_reference}/approve/link-existing", response_model=DecisionOut)
def approve_by_linking(
    account_reference: str,
    payload: ApproveLinkExistingRequest,
    request: Request,
    db: DbSession,
    user: ApproveUser,
) -> DecisionOut:
    """Approve by linking to the named customer. Writes no canonical customer value."""
    identity = review.load_identity(db, account_reference)
    try:
        result = approval.approve_link_existing(
            db,
            identity=identity,
            actor=user,
            customer_public_id=payload.customer_public_id,
            preview_fingerprint=payload.preview_fingerprint,
            idempotency_key=payload.idempotency_key,
            ip_address=client_ip(request),
        )
    except DomainError as exc:
        # A refused decision writes nothing. The record of the refusal rides on the
        # exception and is written afterwards, on a session rolled back clean, so the
        # audit row survives a rollback that correctly discards everything else
        # (DEC-0111). A refusal carrying no hook is left exactly as it was.
        persist_refusal_audit(db, exc)
        raise
    commit_with_retry(db)
    return _decision_out(result)


@router.post("/registrations/{account_reference}/reject", response_model=DecisionOut)
def reject_registration(
    account_reference: str,
    payload: RejectRegistrationRequest,
    request: Request,
    db: DbSession,
    user: ApproveUser,
) -> DecisionOut:
    """Decline an application. No customer, no link, and every session and token dies.

    ``internal_detail`` is validated and **discarded**: there is no reviewed store for
    prose about an applicant in this release, and the existing redaction rules keep it out
    of the audit payload. The field is accepted so the contract does not change when a
    place to put it exists.
    """
    identity = review.load_identity(db, account_reference)
    try:
        result = approval.reject(
            db,
            identity=identity,
            actor=user,
            reason_code=payload.reason_code,
            idempotency_key=payload.idempotency_key,
            internal_detail=payload.internal_detail,
            ip_address=client_ip(request),
        )
    except DomainError as exc:
        # A refused decision writes nothing. The record of the refusal rides on the
        # exception and is written afterwards, on a session rolled back clean, so the
        # audit row survives a rollback that correctly discards everything else
        # (DEC-0111). A refusal carrying no hook is left exactly as it was.
        persist_refusal_audit(db, exc)
        raise
    commit_with_retry(db)
    return _decision_out(result)


# --- Identity lifecycle -------------------------------------------------------
#
# Sprint 13 Lane A, item A-1 (`docs/DECISION_REGISTER.md` section 2, finding A8): the
# service functions for suspending and reinstating a Customer Account existed since Phase
# 9 with no route reaching them, so after launch the only way to suspend an account would
# have been the database. These routes are the staff surface for them. Deactivation was
# left unwired until the owner decided who may perform it: Admin only (DEC-0126), routed in
# UAT round 4 (DEC-0131).
#
# Addressed as `/identities/...` rather than `/registrations/...`: a suspension acts on an
# account that may have been approved months ago, and the registration routes refuse an
# identity with no pending proposal.


def _identity_status_out(db, identity) -> IdentityStatusOut:
    link = review.active_link_for_identity(db, identity.id)
    linked_public_id = None
    if link is not None:
        customer = db.get(Customer, link.customer_id)
        linked_public_id = customer.public_id if customer else None
    return IdentityStatusOut(
        account_reference=identity.public_id,
        status=identity.status,
        status_reason_code=identity.status_reason_code,
        account_email_entered=identity.email_entered,
        email_verified=identity.email_verified_at is not None,
        approved_at=identity.approved_at,
        suspended_at=identity.suspended_at,
        deactivated_at=identity.deactivated_at,
        linked_customer_public_id=linked_public_id,
        can_suspend=customer_identity_service.can_suspend(identity),
        can_reinstate=customer_identity_service.can_reinstate(identity),
        can_deactivate=customer_identity_service.can_deactivate(identity),
        can_reactivate=account_security.can_reactivate(identity),
        can_change_sign_in_email=account_security.can_change_sign_in_email(identity),
    )


@router.get("/identities/{account_reference}", response_model=IdentityStatusOut)
def read_identity_status(
    account_reference: str,
    request: Request,
    db: DbSession,
    user: ReviewUser,
) -> IdentityStatusOut:
    """One account's lifecycle state, whatever that state is. Audited as a read."""
    identity = review.load_identity(db, account_reference)
    audit.identity_status_read(db, identity=identity, actor=user, ip_address=client_ip(request))
    commit_with_retry(db)
    return _identity_status_out(db, identity)


@router.post("/identities/{account_reference}/suspend", response_model=IdentityStatusOut)
def suspend_identity(
    account_reference: str,
    payload: IdentityStatusChangeRequest,
    db: DbSession,
    user: ApproveUser,
) -> IdentityStatusOut:
    """Suspend an account: every session ends now, sign-in is refused, the record stays.

    The customer is told nothing that distinguishes suspension from a wrong password
    (`STATE_MACHINES.md` section 1, transition 6); the audit row carries the bounded
    reason code and the actor.
    """
    if payload.reason_code not in SUSPEND_REASON_CODES:
        raise ValidationError("Choose one of the listed reasons.", field="reason_code")
    identity = review.load_identity(db, account_reference)
    if not customer_identity_service.can_suspend(identity):
        raise ConflictError(
            f"Only an active or pending-approval account can be suspended; this one is "
            f"{identity.status}."
        )
    customer_identity_service.suspend(db, identity, reason_code=payload.reason_code, actor=user)
    commit_with_retry(db)
    return _identity_status_out(db, identity)


@router.post("/identities/{account_reference}/reinstate", response_model=IdentityStatusOut)
def reinstate_identity(
    account_reference: str,
    payload: IdentityStatusChangeRequest,
    db: DbSession,
    user: ApproveUser,
) -> IdentityStatusOut:
    """Lift a suspension. Back to ``active`` only with a live link; otherwise to review.

    The service enforces that (transition 7): reinstatement is never a second door into
    ``active`` for an account that was never linked.
    """
    if payload.reason_code not in REINSTATE_REASON_CODES:
        raise ValidationError("Choose one of the listed reasons.", field="reason_code")
    identity = review.load_identity(db, account_reference)
    if not customer_identity_service.can_reinstate(identity):
        raise ConflictError(
            f"Only a suspended account can be reinstated; this one is {identity.status}."
        )
    customer_identity_service.reinstate(db, identity, reason_code=payload.reason_code, actor=user)
    commit_with_retry(db)
    return _identity_status_out(db, identity)


@router.post("/identities/{account_reference}/deactivate", response_model=IdentityStatusOut)
def deactivate_identity(
    account_reference: str,
    payload: IdentityStatusChangeRequest,
    db: DbSession,
    user: DeactivateUser,
) -> IdentityStatusOut:
    """Deactivate an account. Admin only (DEC-0126); permanent for the account.

    Every session ends and every outstanding verification or reset token dies; the record,
    its link and its history stay. Not a deletion (OD-35). The audit row carries the actor
    and the bounded reason code, as suspend and reinstate do.
    """
    if payload.reason_code not in DEACTIVATE_REASON_CODES:
        raise ValidationError("Choose one of the listed reasons.", field="reason_code")
    identity = review.load_identity(db, account_reference)
    if not customer_identity_service.can_deactivate(identity):
        raise ConflictError("This account is already deactivated.")
    customer_identity_service.deactivate(db, identity, reason_code=payload.reason_code, actor=user)
    commit_with_retry(db)
    return _identity_status_out(db, identity)


# --- Reinstating a deactivated account (RC-UAT-21 Phase B, DEC-0231) ------------------------
#
# Deactivation was terminal until RC-UAT-21. Reversing it is Admin's alone, as deactivating
# is (the same permission), with a bounded reason code. The account returns to the usable
# status it had; its old sessions stay revoked, so the customer signs in again.


@router.get("/identities-deactivated", response_model=DeactivatedAccountList)
def list_deactivated_identities(
    request: Request,
    db: DbSession,
    user: DeactivateUser,
) -> DeactivatedAccountList:
    """Deactivated accounts, newest first, for the Admin's reinstatement list. Audited."""
    rows = account_security.deactivated_identities(db)
    items = []
    for identity in rows:
        link = review.active_link_for_identity(db, identity.id)
        customer = db.get(Customer, link.customer_id) if link is not None else None
        items.append(
            DeactivatedAccountRow(
                account_reference=identity.public_id,
                account_email_entered=identity.email_entered,
                deactivated_at=identity.deactivated_at,
                status_reason_code=identity.status_reason_code,
                linked_customer_public_id=customer.public_id if customer else None,
                can_reactivate=account_security.can_reactivate(identity),
            )
        )
    audit.deactivated_list_read(db, actor=user, count=len(items), ip_address=client_ip(request))
    commit_with_retry(db)
    return DeactivatedAccountList(items=items)


@router.post("/identities/{account_reference}/reactivate", response_model=IdentityStatusOut)
def reactivate_identity(
    account_reference: str,
    payload: IdentityReactivateRequest,
    request: Request,
    db: DbSession,
    user: DeactivateUser,
) -> IdentityStatusOut:
    """Reinstate a deactivated account. Admin only; reason code required; audited.

    Refused (409) for an account that is not deactivated, one deactivated on a privacy
    request, and an application that was rejected before it was deactivated.
    """
    identity = review.load_identity(db, account_reference)
    account_security.reactivate(
        db,
        identity,
        reason_code=payload.reason_code,
        note=payload.note,
        actor=user,
        ip_address=client_ip(request),
    )
    commit_with_retry(db)
    return _identity_status_out(db, identity)


# --- An Admin changes the sign-in email (RC-UAT-25 item 2, Ben 2026-10-25) -----------------
#
# Customers can no longer change it from the Customer Account. Admin only (the deactivation
# permission); the service applies the single email rule, moves the linked customer's email
# with it, ends every session, kills every outstanding link, tells both addresses, and keeps
# the history on ``customer_account_email_changes``.


@router.post("/identities/{account_reference}/sign-in-email", response_model=IdentityStatusOut)
def change_sign_in_email(
    account_reference: str,
    payload: IdentitySignInEmailChangeRequest,
    request: Request,
    db: DbSession,
    user: DeactivateUser,
) -> IdentityStatusOut:
    """Change a Customer Account's sign-in email. Admin only; reason code required; audited.

    422 for a malformed address, the account's own address or an unlisted reason; 409 for an
    account that is not pending approval, active or suspended, and for an address held by
    another account or another customer record.
    """
    identity = review.load_identity(db, account_reference)
    account_security.change_sign_in_email_by_staff(
        db,
        identity,
        new_email=payload.new_email,
        reason_code=payload.reason_code,
        note=payload.note,
        actor=user,
        ip_address=client_ip(request),
    )
    commit_with_retry(db)
    return _identity_status_out(db, identity)


# --- Orphaned accounts: re-link or close (RC-UAT-22, B-13, DEC-0234 draft) ------------------
#
# A reinstatement onto a merged or archived customer ends the link and leaves the account in
# ``pending_approval`` with no proposal, which the approval routes above cannot decide. These
# routes resolve it: re-link to a named customer after reading its history, or close it. Admin
# only, the reinstatement permission; every read and write audited.


@router.get("/identities-orphaned", response_model=OrphanedAccountList)
def list_orphaned_identities(
    request: Request,
    db: DbSession,
    user: DeactivateUser,
) -> OrphanedAccountList:
    """Approved accounts with no customer and no pending proposal, newest first. Audited."""
    rows = relink_service.orphaned_identities(db)
    items = [
        OrphanedAccountRow(
            account_reference=row.identity.public_id,
            account_email_entered=row.identity.email_entered,
            approved_at=row.identity.approved_at,
            last_customer_public_id=row.last_customer_public_id,
            last_link_end_reason=row.last_link_end_reason,
            last_link_ended_at=row.last_link_ended_at,
            last_customer_merged=row.last_customer_merged,
            suggested_customer_public_id=row.suggested_customer_public_id,
        )
        for row in rows
    ]
    audit.orphaned_list_read(db, actor=user, count=len(items), ip_address=client_ip(request))
    commit_with_retry(db)
    return OrphanedAccountList(
        items=items,
        relink_reason_codes=list(relink_service.RELINK_REASON_CODES),
        close_reason_codes=list(relink_service.CLOSE_REASON_CODES),
    )


@router.get("/identities/{account_reference}/relink-preview", response_model=RelinkPreviewOut)
def read_relink_preview(
    account_reference: str,
    request: Request,
    db: DbSession,
    user: DeactivateUser,
    customer_public_id: str = Query(..., max_length=20),
) -> RelinkPreviewOut:
    """The target's history (the five OD-29 figures) and the email a re-link would set.

    A ``GET`` that writes an audit row, as the approval preview does: it is the moment an
    Admin is shown how much history the link would open.
    """
    identity = review.load_identity(db, account_reference)
    preview, target = relink_service.build_preview(db, identity, customer_public_id)
    audit.relink_previewed(
        db,
        identity=identity,
        actor=user,
        customer_public_id=target.public_id,
        summary_detail=preview.disclosure.as_audit_detail(),
        fingerprint=preview.fingerprint,
        ip_address=client_ip(request),
    )
    commit_with_retry(db)
    summary = preview.disclosure
    return RelinkPreviewOut(
        account_reference=preview.account_reference,
        target_customer_public_id=preview.target_customer_public_id,
        disclosure=DisclosureOut(
            shipment_count=summary.shipment_count,
            oldest_booked_at=summary.oldest_booked_at,
            newest_booked_at=summary.newest_booked_at,
            includes_cancelled=summary.includes_cancelled,
            includes_rebooked=summary.includes_rebooked,
            definition_version=summary.definition_version,
        ),
        email_change=dict(preview.email_change) if preview.email_change else None,
        fingerprint=preview.fingerprint,
    )


@router.post("/identities/{account_reference}/relink", response_model=IdentityStatusOut)
def relink_identity(
    account_reference: str,
    payload: RelinkRequest,
    request: Request,
    db: DbSession,
    user: DeactivateUser,
) -> IdentityStatusOut:
    """Link an orphaned account to the named customer and return it to ``active``.

    Refused (422) without ``history_acknowledged: true`` or a listed reason; (409) for an
    account that is not orphaned, a merged, archived or already-linked target, and a preview
    that no longer matches (``preview_stale``); (404) for an unknown customer.
    """
    identity = review.load_identity(db, account_reference)
    relink_service.relink(
        db,
        identity,
        customer_public_id=payload.customer_public_id,
        reason_code=payload.reason_code,
        note=payload.note,
        history_acknowledged=payload.history_acknowledged,
        preview_fingerprint=payload.preview_fingerprint,
        actor=user,
        ip_address=client_ip(request),
    )
    commit_with_retry(db)
    return _identity_status_out(db, identity)


@router.post("/identities/{account_reference}/close-orphan", response_model=IdentityStatusOut)
def close_orphaned_identity(
    account_reference: str,
    payload: CloseOrphanRequest,
    request: Request,
    db: DbSession,
    user: DeactivateUser,
) -> IdentityStatusOut:
    """Close an orphaned account: deactivated with reason ``orphan_closed``; no email sent.

    Reversible through the ordinary reinstatement, which returns it to this list.
    """
    identity = review.load_identity(db, account_reference)
    relink_service.close_orphan(
        db,
        identity,
        reason_code=payload.reason_code,
        note=payload.note,
        actor=user,
        ip_address=client_ip(request),
    )
    commit_with_retry(db)
    return _identity_status_out(db, identity)


# --- Post-approval profile changes (fix pack 2; FIELD_MATRIX.md §5, CA-PRF-02) ---------
#
# A linked customer's name, phone or pickup-address change arrives as a ``profile_update``
# proposal and changes nothing canonical until a reviewer decides it here. The reviewer
# sees proposed, current-at-submission, current-now and normalized values side by side,
# decides each field group, and a group whose canonical value moved since submission is
# refused rather than merged. Read needs review; deciding needs review and approve.


def _profile_review_out(result) -> ProfileReviewOut:
    proposal = result.proposal
    return ProfileReviewOut(
        account_reference=result.identity.public_id,
        customer_public_id=result.customer.public_id,
        status=proposal.status,
        submitted_at=proposal.submitted_at,
        reviewed_at=proposal.reviewed_at,
        decision_reason_code=proposal.decision_reason_code,
        groups=result.groups,
        fields=[
            ProfileReviewFieldOut(
                field_key=row.field_key,
                group=row.group,
                proposed_value=row.proposed_value,
                proposed_value_normalized=row.proposed_value_normalized,
                current_value_at_submission=row.current_value_at_submission,
                current_value_now=row.current_value_now,
                drifted=row.drifted,
                applied=row.applied,
            )
            for row in result.rows
        ],
        decline_reason_codes=list(profile_review.DECLINE_REASON_CODES),
    )


@router.get("/profile-proposals", response_model=ProfileProposalQueue)
def list_profile_proposals(
    request: Request, db: DbSession, user: ReviewUser
) -> ProfileProposalQueue:
    rows = profile_review.list_pending(db)
    audit.queue_reviewed(db, actor=user, count=len(rows), ip_address=client_ip(request))
    commit_with_retry(db)
    return ProfileProposalQueue(
        items=[
            ProfileProposalRow(
                account_reference=identity.public_id,
                customer_public_id=customer.public_id,
                submitted_at=proposal.submitted_at,
                field_count=len(proposal.fields),
                groups=sorted(
                    {
                        profile_review.group_of(row.field_key) or row.field_key
                        for row in proposal.fields
                    }
                ),
            )
            for proposal, identity, customer in rows
        ],
        total=len(rows),
    )


@router.get("/identities/{account_reference}/profile-proposal", response_model=ProfileReviewOut)
def read_profile_proposal(
    account_reference: str, request: Request, db: DbSession, user: ReviewUser
) -> ProfileReviewOut:
    identity = review.load_identity(db, account_reference)
    result = profile_review.build_review(db, identity)
    audit.profile_proposal_opened(
        db,
        identity=identity,
        proposal_id=result.proposal.id,
        actor=user,
        ip_address=client_ip(request),
    )
    commit_with_retry(db)
    return _profile_review_out(result)


@router.post(
    "/identities/{account_reference}/profile-proposal/decide", response_model=ProfileReviewOut
)
def decide_profile_proposal(
    account_reference: str,
    payload: ProfileDecisionRequest,
    request: Request,
    db: DbSession,
    user: ApproveUser,
) -> ProfileReviewOut:
    identity = review.load_identity(db, account_reference)
    result = profile_review.decide(
        db,
        identity=identity,
        actor=user,
        decisions=payload.decisions,
        reason_code=payload.reason_code,
        ip_address=client_ip(request),
    )
    commit_with_retry(db)
    return _profile_review_out(result)
