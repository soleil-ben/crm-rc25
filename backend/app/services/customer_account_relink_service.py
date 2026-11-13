"""Staff re-link or close of an orphaned Customer Account (RC-UAT-22, B-13, DEC-0234 draft).

**The gap this closes.** An Admin reinstatement of a deactivated account whose customer was
merged or archived meanwhile ends the link and returns the account to ``pending_approval``
(``customer_account_security_service.reactivate``, review HIGH 2). The approval flow then
cannot help: it decides a **pending proposal**, and an account approved long ago has none. The
account is stuck -- it can sign in, it reaches nothing, and no screen can move it.

**Orphaned, by state.** An identity is orphaned when it is ``pending_approval``, has been
approved before (``approved_at`` set), holds no active link, and has no pending proposal.
Defined by what the rows say rather than by how they got there, so any future path that
leaves an approved account linkless lands here too.

**Two ways out, both Admin-only** (``customer_account:deactivate``, the reinstatement
permission -- this is the second half of a reinstatement, so it is held by the same hands):

* **Re-link** to a customer the Admin names. The target is checked by
  ``customer_account_review_service.resolve_link_target`` -- the approval's own rules: not a
  merged tombstone (the survivor is named instead), not archived -- and must hold no live
  link of any kind (stand-in B-16: unlike an approval, a re-link never takes over a
  deactivated account's link). The Admin must first be shown the target's history and
  acknowledge it, as an approval demands (OD-29). The approval's acknowledgement machinery
  cannot be reused as it stands: its table requires a ``proposal_id`` and its fingerprint is
  built over the proposal, and an orphan has no proposal. So this module reuses the parts
  that are not tied to one -- the OD-29 disclosure calculation, the fingerprint digest and the
  single-email preview -- and the re-link must carry **both** ``history_acknowledged: true``
  and the fingerprint of a preview that still matches; the acknowledged figures are kept on
  the ``customer_account_relinks`` row (stand-in B-17). Effect, in one transaction: the
  single email rule (the record takes the account's sign-in email, as ``reactivate`` and the
  approval do), a new link through the approval service's one link constructor, ``active``
  through ``customer_identity_service.activate_relinked`` (which refuses without exactly one
  live link and a prior approval), the row, the audit, and an "account ready" notice
  (test capture only; the approval's template, stand-in B-18).
* **Close** the account: an ordinary deactivation with reason ``orphan_closed``, so sessions
  and tokens die and the record stays. No message to the customer (stand-in B-19). The
  closure is reversible through the existing reinstatement, which returns the account to
  ``pending_approval`` and so back to this list (stand-in B-20).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import exists, func, select
from sqlalchemy.orm import Session

from app.core.account_enums import IdentityStatus, LinkRole, LinkStatus, ProposalStatus
from app.core.account_security import fingerprint as compute_fingerprint
from app.core.time_utils import utcnow
from app.models import (
    Customer,
    CustomerAccountRelink,
    CustomerDataProposal,
    CustomerIdentity,
    CustomerIdentityLink,
    User,
)
from app.services import account_email_service as email
from app.services import customer_account_approval_service as approval
from app.services import customer_account_audit as audit
from app.services import customer_account_disclosure_service as disclosure
from app.services import customer_account_review_service as review
from app.services import customer_identity_service
from app.services.customer_account_disclosure_service import DisclosureSummary
from app.services.errors import ConflictError, ValidationError

#: Bounded, like every lifecycle reason here (mirrored in the staff screen).
RELINK_REASON_CODES: tuple[str, ...] = ("merge_survivor", "correct_customer", "other")
CLOSE_REASON_CODES: tuple[str, ...] = ("no_customer", "duplicate", "other")
#: The deactivation reason a closure writes. Not in the reinstatement's irreversible set.
CLOSE_DEACTIVATION_REASON = "orphan_closed"
ACTION_RELINK = "relink"
ACTION_CLOSE = "close"
NOTE_MAX_LENGTH = 500
LIST_LIMIT = 200


# --- Eligibility --------------------------------------------------------------------------------


def _has_live_link():
    return exists().where(
        CustomerIdentityLink.identity_id == CustomerIdentity.id,
        CustomerIdentityLink.status == LinkStatus.ACTIVE.value,
    )


def _has_pending_proposal():
    return exists().where(
        CustomerDataProposal.identity_id == CustomerIdentity.id,
        CustomerDataProposal.status == ProposalStatus.PENDING.value,
    )


def _orphan_conditions() -> list:
    return [
        CustomerIdentity.status == IdentityStatus.PENDING_APPROVAL.value,
        CustomerIdentity.approved_at.is_not(None),
        ~_has_live_link(),
        ~_has_pending_proposal(),
    ]


def is_orphaned(db: Session, identity: CustomerIdentity) -> bool:
    found = db.scalar(
        select(CustomerIdentity.id).where(CustomerIdentity.id == identity.id, *_orphan_conditions())
    )
    return found is not None


def require_orphaned(db: Session, identity: CustomerIdentity) -> None:
    """Refuse an account that is not orphaned, and say why (staff-facing, so it may)."""
    if is_orphaned(db, identity):
        return
    if identity.status != IdentityStatus.PENDING_APPROVAL.value:
        raise ConflictError(
            f"Only an account waiting for a customer can be re-linked or closed here; this "
            f"one is {identity.status}."
        )
    if identity.approved_at is None:
        raise ConflictError(
            "This account was never approved. Review its registration in the approval queue."
        )
    raise ConflictError(
        "This account has a link or a pending proposal. Use the approval queue instead."
    )


def last_link(db: Session, identity: CustomerIdentity) -> CustomerIdentityLink | None:
    """The identity's most recent link, live or ended. ``id`` orders it: links are only added."""
    return db.scalar(
        select(CustomerIdentityLink)
        .where(CustomerIdentityLink.identity_id == identity.id)
        .order_by(CustomerIdentityLink.id.desc())
        .limit(1)
    )


def suggested_target(db: Session, customer: Customer | None) -> Customer | None:
    """The customer a re-link most likely means, or ``None`` (a suggestion, never applied).

    A merged-away customer suggests its survivor, following the chain as a staff lookup of
    the old reference does. A customer that absorbed others is itself the survivor and is
    suggested as it stands. An archived customer, or an archived survivor, suggests nothing.
    """
    if customer is None:
        return None
    from app.services import customer_service  # noqa: PLC0415

    survivor = (
        customer_service.get_customer_by_public_id(db, customer.public_id)
        if customer.merged_into_customer_id is not None
        else customer
    )
    if survivor is None or survivor.is_archived or survivor.merged_into_customer_id is not None:
        return None
    return survivor


@dataclass(frozen=True)
class OrphanRow:
    identity: CustomerIdentity
    last_customer_public_id: str | None
    last_link_end_reason: str | None
    last_link_ended_at: datetime | None
    last_customer_merged: bool
    suggested_customer_public_id: str | None


def orphaned_identities(db: Session, *, limit: int = LIST_LIMIT) -> list[OrphanRow]:
    identities = db.scalars(
        select(CustomerIdentity)
        .where(*_orphan_conditions())
        .order_by(CustomerIdentity.updated_at.desc(), CustomerIdentity.id.desc())
        .limit(limit)
    ).all()
    rows = []
    for identity in identities:
        link = last_link(db, identity)
        customer = db.get(Customer, link.customer_id) if link is not None else None
        suggestion = suggested_target(db, customer)
        rows.append(
            OrphanRow(
                identity=identity,
                last_customer_public_id=customer.public_id if customer else None,
                last_link_end_reason=link.revoke_reason_code if link else None,
                last_link_ended_at=link.revoked_at if link else None,
                last_customer_merged=bool(customer and customer.merged_into_customer_id),
                suggested_customer_public_id=suggestion.public_id if suggestion else None,
            )
        )
    return rows


# --- The preview ------------------------------------------------------------------------------


@dataclass(frozen=True)
class RelinkPreview:
    account_reference: str
    target_customer_public_id: str
    disclosure: DisclosureSummary
    #: The single email rule: ``{"current", "new"}`` when the record's email will change.
    email_change: dict[str, str | None] | None
    fingerprint: str


def resolve_target(db: Session, customer_public_id: object) -> Customer:
    """The approval's link-target rules, plus: no live link of any kind (stand-in B-16)."""
    if not isinstance(customer_public_id, str) or not customer_public_id.strip():
        raise ValidationError(
            "Name the customer to link. There is no automatic closest match.",
            field="customer_public_id",
        )
    customer = review.resolve_link_target(db, customer_public_id)
    if review.active_link_for_customer(db, customer.id) is not None:
        raise ConflictError(
            f"{customer.public_id} already has a Customer Account linked. Release 1 allows one.",
            field="customer_public_id",
        )
    return customer


def _fingerprint_parts(
    db: Session, identity: CustomerIdentity, target: Customer, summary: DisclosureSummary
) -> list[str]:
    """Every fact that, if it moved, makes an earlier acknowledgement the wrong one.

    The account (its state, its address, whether it got a link meanwhile) and the target
    (edited, merged either way, archived, linked by somebody else) and the five figures.
    """
    absorbed = db.scalar(
        select(func.count(Customer.id)).where(Customer.merged_into_customer_id == target.id)
    )
    return [
        "purpose=relink",
        f"identity={identity.public_id}",
        f"identity_status={identity.status}",
        f"identity_email={identity.email_normalized}",
        f"identity_linked={int(review.active_link_for_identity(db, identity.id) is not None)}",
        f"target={target.public_id}",
        f"target_updated={target.updated_at.isoformat() if target.updated_at else ''}",
        f"target_email={target.email_normalized or ''}",
        f"target_merged={target.merged_into_customer_id or ''}",
        f"target_absorbed={absorbed or 0}",
        f"target_archived={int(target.is_archived)}",
        f"target_linked={int(review.active_link_for_customer(db, target.id) is not None)}",
        *summary.fingerprint_parts(),
    ]


def build_preview(
    db: Session, identity: CustomerIdentity, customer_public_id: object
) -> tuple[RelinkPreview, Customer]:
    """What a re-link would open, computed from the database and nothing else."""
    require_orphaned(db, identity)
    target = resolve_target(db, customer_public_id)
    summary = disclosure.summarize(db, target.id)
    preview = RelinkPreview(
        account_reference=identity.public_id,
        target_customer_public_id=target.public_id,
        disclosure=summary,
        email_change=review.sign_in_email_change(identity, target),
        fingerprint=compute_fingerprint(_fingerprint_parts(db, identity, target, summary)),
    )
    return preview, target


# --- Re-link and close --------------------------------------------------------------------------


def _bounded(reason_code: object, allowed: tuple[str, ...], note: str | None) -> str | None:
    """Check the bounded reason and return the trimmed note (``None`` when blank)."""
    if reason_code not in allowed:
        raise ValidationError("Choose one of the listed reasons.", field="reason_code")
    note = (note or "").strip() or None
    if note is not None and len(note) > NOTE_MAX_LENGTH:
        raise ValidationError(f"Keep the note under {NOTE_MAX_LENGTH} characters.", field="note")
    return note


def _previous(db: Session, identity: CustomerIdentity) -> tuple[Customer | None, str | None]:
    link = last_link(db, identity)
    if link is None:
        return None, None
    return db.get(Customer, link.customer_id), link.revoke_reason_code


def relink(
    db: Session,
    identity: CustomerIdentity,
    *,
    customer_public_id: object,
    reason_code: str,
    note: str | None,
    history_acknowledged: object,
    preview_fingerprint: object,
    actor: User,
    ip_address: str | None,
) -> CustomerAccountRelink:
    """Link an orphaned account to the named customer and return it to ``active``."""
    note = _bounded(reason_code, RELINK_REASON_CODES, note)
    if history_acknowledged is not True:
        raise ValidationError(
            "Confirm that you have read the customer's history this link will open.",
            field="history_acknowledged",
        )
    preview, target = build_preview(db, identity, customer_public_id)
    if preview.fingerprint != preview_fingerprint:
        raise ConflictError(
            "The customer or the account changed since the preview. Check it again, read it, "
            "and confirm that.",
            detail={"code": "preview_stale"},
            field="preview_fingerprint",
        )
    previous_customer, previous_reason = _previous(db, identity)

    # The single email rule, before the link exists: ``update_customer`` refuses an email
    # change on a customer a live account holds, and this one is about to be held.
    change = review.sign_in_email_change(identity, target)
    if change is not None:
        from app.services import customer_service  # noqa: PLC0415

        customer_service.update_customer(
            db, target, {"email": identity.email_entered}, actor=actor, ip_address=ip_address
        )
        audit.sign_in_email_applied(
            db,
            identity=identity,
            actor=actor,
            customer_public_id=target.public_id,
            previous_email_present=bool(change["current"]),
            ip_address=ip_address,
        )
    approval.write_link(db, identity=identity, customer=target, actor=actor)
    customer_identity_service.activate_relinked(db, identity, reason_code=reason_code)

    summary = preview.disclosure
    record = CustomerAccountRelink(
        identity_id=identity.id,
        action=ACTION_RELINK,
        previous_customer_id=previous_customer.id if previous_customer else None,
        previous_link_end_reason=previous_reason,
        target_customer_id=target.id,
        reason_code=reason_code,
        note=note,
        disclosed_shipment_count=summary.shipment_count,
        oldest_booked_at=summary.oldest_booked_at,
        newest_booked_at=summary.newest_booked_at,
        includes_cancelled=summary.includes_cancelled,
        includes_rebooked=summary.includes_rebooked,
        disclosure_definition_version=summary.definition_version,
        preview_fingerprint=preview.fingerprint,
        acted_at=utcnow(),
        acted_by_user_id=actor.id if actor is not None else None,
    )
    db.add(record)
    db.flush()
    audit.linked(
        db,
        identity=identity,
        actor=actor,
        customer_public_id=target.public_id,
        link_role=LinkRole.OWNER.value,
        differing_field_keys=[],
        ip_address=ip_address,
    )
    audit.relinked(
        db,
        identity=identity,
        actor=actor,
        customer_public_id=target.public_id,
        previous_customer_public_id=previous_customer.public_id if previous_customer else None,
        previous_link_end_reason=previous_reason,
        reason_code=reason_code,
        summary_detail=summary.as_audit_detail(),
        fingerprint=preview.fingerprint,
        ip_address=ip_address,
    )
    from app.services import customer_account_profile_service  # noqa: PLC0415

    email.send(
        email.OutboundEmail(
            to_email=identity.email_entered,
            template_key=email.TEMPLATE_ACCOUNT_APPROVED,
            language=customer_account_profile_service.account_language(identity, target),
            parameters={"sign_in_url": customer_identity_service.account_sign_in_url()},
        )
    )
    return record


def close_orphan(
    db: Session,
    identity: CustomerIdentity,
    *,
    reason_code: str,
    note: str | None,
    actor: User,
    ip_address: str | None,
) -> CustomerAccountRelink:
    """Close an orphaned account: deactivate it (``orphan_closed``). No message is sent."""
    note = _bounded(reason_code, CLOSE_REASON_CODES, note)
    require_orphaned(db, identity)
    previous_customer, previous_reason = _previous(db, identity)
    customer_identity_service.deactivate(
        db, identity, reason_code=CLOSE_DEACTIVATION_REASON, actor=actor
    )
    record = CustomerAccountRelink(
        identity_id=identity.id,
        action=ACTION_CLOSE,
        previous_customer_id=previous_customer.id if previous_customer else None,
        previous_link_end_reason=previous_reason,
        target_customer_id=None,
        reason_code=reason_code,
        note=note,
        acted_at=utcnow(),
        acted_by_user_id=actor.id if actor is not None else None,
    )
    db.add(record)
    db.flush()
    audit.orphan_closed(
        db,
        identity=identity,
        actor=actor,
        previous_customer_public_id=previous_customer.public_id if previous_customer else None,
        reason_code=reason_code,
        ip_address=ip_address,
    )
    return record
