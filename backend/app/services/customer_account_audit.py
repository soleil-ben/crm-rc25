"""Customer Account audit events: one function per event, and no free-form payload path.

Every security event this surface produces goes through a named function here. That is the
control. A service that could call ``audit_service.record_audit`` directly with a dictionary
it assembled is a service that can write a password into the audit table by accident, and
"we reviewed the call sites" is not a mechanism. So the call sites are these functions, the
payloads they build are closed, and ``tests/test_account_audit_privacy.py`` asserts over the
written rows rather than over this file.

**What a payload may contain** (`DATA_MODEL.md` section 9): the identity ``public_id``, the
customer ``public_id``, affected field keys, reason codes, counts, and the actor.

**What it may never contain:** a password, a password hash, a token, a token digest, a
session identifier, a CSRF token, a raw email or phone in a security-event payload, a
duplicate score, or an unbounded copy of a submitted payload.

Where an address is genuinely needed for correlation -- "is one attacker working through a
list, or is one customer having a bad morning?" -- a **keyed digest** of the normalized
address is written instead (`account_security.address_key`). Stable enough to group by,
non-reversible, so the audit table does not become a list of who has a Solaris account
(T-02, T-13).

The identity is recorded by ``public_id`` rather than by row id for the same reason a
customer is: ``CA-000001`` is the reference a person quotes, and an integer primary key is
an internal detail that means nothing to whoever reads the log.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.core.account_security import address_key
from app.core.enums import Role
from app.models import CustomerIdentity
from app.services import audit_service

ENTITY_IDENTITY = "customer_identity"
ENTITY_PROPOSAL = "customer_data_proposal"

# Actions, from `DATA_MODEL.md` section 9. Named constants rather than string literals at
# the call sites, so the vocabulary is enumerable and a typo is an import error.
ACTION_REGISTER = "customer_account.register"
ACTION_VERIFICATION_ISSUED = "customer_account.verification_issued"
ACTION_VERIFICATION_RESENT = "customer_account.verification_resent"
ACTION_VERIFY_EMAIL = "customer_account.verify_email"
ACTION_VERIFICATION_REFUSED = "customer_account.verification_refused"
ACTION_SIGN_IN = "customer_account.sign_in"
ACTION_SIGN_IN_FAILED = "customer_account.sign_in_failed"
ACTION_SIGN_OUT = "customer_account.sign_out"
ACTION_LOCKED = "customer_account.locked"
ACTION_SESSION_REVOKED = "customer_account.session_revoked"
ACTION_PASSWORD_RESET_REQUESTED = "customer_account.password_reset_requested"
ACTION_PASSWORD_RESET_COMPLETED = "customer_account.password_reset_completed"
ACTION_SUSPEND = "customer_account.suspend"
ACTION_REINSTATE = "customer_account.reinstate"
ACTION_DEACTIVATE = "customer_account.deactivate"
ACTION_IDENTITY_STATUS_READ = "customer_account.status_read"
ACTION_PROPOSAL_SUBMIT = "customer_data_proposal.submit"
ACTION_PROPOSAL_SUPERSEDE = "customer_data_proposal.supersede"

# --- Phase 10: staff review, approval, linking and rejection -----------------
#
# Every one of these carries an ``actor``, which the Phase 9 events deliberately do not:
# there is a staff user behind each of them, and the whole point of auditing an approval
# is being able to name who performed it (OD-24, T-18).
ACTION_QUEUE_REVIEWED = "customer_account.queue_reviewed"
ACTION_REGISTRATION_OPENED = "customer_account.registration_opened"
ACTION_DUPLICATES_REVIEWED = "customer_account.duplicates_reviewed"
ACTION_PREVIEW_CREATED = "customer_account.preview_created"
ACTION_DISCLOSURE_ACKNOWLEDGED = "customer_account.disclosure_acknowledged"
ACTION_APPROVE = "customer_account.approve"
ACTION_LINK = "customer_account.link"
ACTION_SEPARATE_CUSTOMER_OVERRIDE = "customer_account.separate_customer_override"
ACTION_REJECT = "customer_account.reject"
ACTION_PREVIEW_STALE = "customer_account.preview_stale_refused"
ACTION_APPROVAL_CONFLICT = "customer_account.approval_conflict"
ACTION_APPROVAL_REPLAYED = "customer_account.approval_replayed"
# UAT round 6 (owner decisions, 2026-10-15).
ACTION_UNLINK = "customer_account.unlink"
ACTION_SIGN_IN_EMAIL_APPLIED = "customer_account.sign_in_email_applied"
#: Why a link was ended: a new account took over a customer whose account was deactivated.
REASON_TAKEN_OVER = "taken_over_by_new_account"
#: Why a linked customer's email changed: it is the account's verified sign-in email.
REASON_SINGLE_EMAIL = "single_email_rule"

# --- Phase 10: the customer-merge gate (OD-40) --------------------------------
#
# A merge refused because a Customer Account link is in the way. Written by the *customer*
# merge service rather than by any account route, which is why it lives here: the payload
# rules are the Customer Account's, and a merge refusal that recorded an email address or a
# shipment count would break them from a module nobody thinks of as customer-facing.
ACTION_MERGE_REFUSED = "customer_account.merge_refused_linked_customer"

#: Why a merge was refused. One code today; bounded so a second one is a decision.
REASON_LINK_PRESENT = "customer_account_link_present"

#: Why a preview went stale. ``merge_state_changed`` is the OD-40 case: the customer the
#: preview named was merged, or became the survivor of a merge, between the reviewer
#: reading it and acting on it. Bounded, like every other reason code here.
REASON_PREVIEW_DRIFT = "preview_facts_changed"
REASON_PREVIEW_MERGE_DRIFT = "merge_state_changed"


def _record(
    db: Session,
    *,
    action: str,
    entity_type: str,
    entity_id: str | int | None,
    summary: str,
    detail: dict[str, Any] | None = None,
    ip_address: str | None = None,
    customer_actor: CustomerIdentity | None = None,
) -> None:
    """The only call into ``audit_service`` this surface makes.

    ``actor`` is deliberately never passed. Every event here is produced by an
    unauthenticated or customer-authenticated request, and the actor column is for staff
    users; a customer is identified by the ``identity_public_id`` in the payload, which is
    a different population and should read as one. Phase 10's staff actions will pass an
    actor, because there there is one.

    ``customer_actor`` is passed by the events a signed-in customer causes on their own
    profile and consent (UAT round 8) and by their own sign-in and sign-out (UAT round 9),
    so the row's actor reads ``customer_account:CA-000001`` rather than ``system``. No
    staff user id is written for it. A refused sign-in keeps ``system``: whoever typed the
    password is not known to be the customer.
    """
    audit_service.record_audit(
        db,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        summary=summary,
        detail=detail,
        ip_address=ip_address,
        actor_label=customer_actor_label(customer_actor) if customer_actor else None,
    )


def customer_actor_label(identity: CustomerIdentity) -> str:
    """How an audit row names a customer acting through their own account (UAT round 8)."""
    return f"customer_account:{identity.public_id}"


def _identity_id(identity: CustomerIdentity | None) -> str | None:
    return identity.public_id if identity is not None else None


def _admin_override(actor) -> bool:
    """Whether a staff decision was taken by Admin rather than by Operations.

    OD-24 makes approval Operations' work and lets Admin override. An Admin decision is
    therefore an override by definition, and the audit row says so explicitly
    (``admin_override``) rather than leaving a reader to infer it from the actor's address
    (UAT round 4, CA-APR-05). Decided from the actor's role at the moment of the decision.
    """
    return actor is not None and getattr(actor, "role", None) == Role.ADMIN.value


def _override_suffix(actor) -> str:
    return " (Admin override)" if _admin_override(actor) else ""


# --- Registration and verification -------------------------------------------


def registration_received(
    db: Session,
    *,
    identity: CustomerIdentity | None,
    email_normalized: str,
    outcome: str,
    field_keys: list[str],
    ip_address: str | None,
) -> None:
    """A registration arrived. ``outcome`` is the internal category, never the response.

    The submitted values are **not** here. They are stored once, on the proposal field rows,
    and duplicating them into an append-only table with different access controls would be a
    second copy of the customer's personal data for no operational gain. The field *keys*
    are enough to answer "what did they try to change".
    """
    _record(
        db,
        action=ACTION_REGISTER,
        entity_type=ENTITY_IDENTITY,
        entity_id=_identity_id(identity),
        summary="Customer Account registration received",
        detail={
            "identity_public_id": _identity_id(identity),
            "outcome": outcome,
            "address_key": address_key(email_normalized),
            "field_keys": sorted(field_keys),
            "field_count": len(field_keys),
        },
        ip_address=ip_address,
    )


def verification_issued(
    db: Session, *, identity: CustomerIdentity, resent: bool, ip_address: str | None
) -> None:
    """A verification token was issued. Its purpose and nothing of its value."""
    _record(
        db,
        action=ACTION_VERIFICATION_RESENT if resent else ACTION_VERIFICATION_ISSUED,
        entity_type=ENTITY_IDENTITY,
        entity_id=identity.public_id,
        summary="Verification message issued",
        detail={"identity_public_id": identity.public_id, "purpose": "email_verification"},
        ip_address=ip_address,
    )


def email_verified(db: Session, *, identity: CustomerIdentity, ip_address: str | None) -> None:
    _record(
        db,
        action=ACTION_VERIFY_EMAIL,
        entity_type=ENTITY_IDENTITY,
        entity_id=identity.public_id,
        summary="Email address confirmed",
        detail={"identity_public_id": identity.public_id, "status": "pending_approval"},
        ip_address=ip_address,
    )


def verification_refused(
    db: Session,
    *,
    identity: CustomerIdentity | None,
    reason_code: str,
    purpose: str,
    ip_address: str | None,
) -> None:
    """A token redemption failed, by category: replayed, expired, invalidated, unknown.

    The customer sees one response for all four (`STATE_MACHINES.md` section 5). The
    category is recorded because the operator watching for token brute force needs to tell
    "somebody clicked an old link twice" from "somebody is guessing".
    """
    _record(
        db,
        action=ACTION_VERIFICATION_REFUSED,
        entity_type=ENTITY_IDENTITY,
        entity_id=_identity_id(identity),
        summary="Token redemption refused",
        detail={
            "identity_public_id": _identity_id(identity),
            "reason_code": reason_code,
            "purpose": purpose,
        },
        ip_address=ip_address,
    )


# --- Sign-in, sessions --------------------------------------------------------


def sign_in_succeeded(db: Session, *, identity: CustomerIdentity, ip_address: str | None) -> None:
    _record(
        db,
        action=ACTION_SIGN_IN,
        entity_type=ENTITY_IDENTITY,
        entity_id=identity.public_id,
        summary="Customer signed in",
        detail={"identity_public_id": identity.public_id, "status": identity.status},
        ip_address=ip_address,
        customer_actor=identity,
    )


def sign_in_failed(
    db: Session,
    *,
    email_normalized: str,
    reason_code: str,
    identity: CustomerIdentity | None,
    ip_address: str | None,
) -> None:
    """A refusal, by category, against a hashed address key rather than the address.

    Note what this records for an *unknown* address: a hashed key and
    ``reason_code="unknown_address"``, with no identity. That is the whole value of the
    hashed key -- an address nobody has registered can still be counted, so spraying is
    visible, without the audit table accumulating a list of addresses somebody tried.
    """
    _record(
        db,
        action=ACTION_SIGN_IN_FAILED,
        entity_type=ENTITY_IDENTITY,
        entity_id=_identity_id(identity),
        summary="Customer sign-in refused",
        detail={
            "identity_public_id": _identity_id(identity),
            "reason_code": reason_code,
            "address_key": address_key(email_normalized),
        },
        ip_address=ip_address,
    )


def signed_out(db: Session, *, identity: CustomerIdentity, ip_address: str | None) -> None:
    _record(
        db,
        action=ACTION_SIGN_OUT,
        entity_type=ENTITY_IDENTITY,
        entity_id=identity.public_id,
        summary="Customer signed out",
        detail={"identity_public_id": identity.public_id},
        ip_address=ip_address,
        customer_actor=identity,
    )


def locked(db: Session, *, identity: CustomerIdentity) -> None:
    _record(
        db,
        action=ACTION_LOCKED,
        entity_type=ENTITY_IDENTITY,
        entity_id=identity.public_id,
        summary="Customer Account temporarily locked after repeated failures",
        detail={"identity_public_id": identity.public_id, "reason_code": "failed_sign_ins"},
    )


def session_revoked(db: Session, *, identity_id: int, reason_code: str, count: int) -> None:
    """Sessions were revoked. A count and a reason; never a token or a session id.

    ``identity_id`` is the row id here rather than the public id, because a bulk revocation
    happens in paths that hold the id and not the row. It is resolved to the public id
    before it is written, and if the row has gone the event still records the count.
    """
    from app.models import CustomerIdentity as _Identity

    identity = db.get(_Identity, identity_id)
    _record(
        db,
        action=ACTION_SESSION_REVOKED,
        entity_type=ENTITY_IDENTITY,
        entity_id=identity.public_id if identity else None,
        summary=f"Revoked {count} Customer Account session(s)",
        detail={
            "identity_public_id": identity.public_id if identity else None,
            "reason_code": reason_code,
            "count": count,
        },
    )


# --- Password reset -----------------------------------------------------------


def password_reset_requested(
    db: Session,
    *,
    identity: CustomerIdentity | None,
    email_normalized: str,
    outcome: str,
    ip_address: str | None,
) -> None:
    _record(
        db,
        action=ACTION_PASSWORD_RESET_REQUESTED,
        entity_type=ENTITY_IDENTITY,
        entity_id=_identity_id(identity),
        summary="Password reset requested",
        detail={
            "identity_public_id": _identity_id(identity),
            "outcome": outcome,
            "address_key": address_key(email_normalized),
        },
        ip_address=ip_address,
    )


def password_reset_completed(
    db: Session, *, identity: CustomerIdentity, sessions_revoked: int, ip_address: str | None
) -> None:
    _record(
        db,
        action=ACTION_PASSWORD_RESET_COMPLETED,
        entity_type=ENTITY_IDENTITY,
        entity_id=identity.public_id,
        summary="Password reset completed",
        detail={
            "identity_public_id": identity.public_id,
            "count": sessions_revoked,
            "reason_code": "password_reset",
        },
        ip_address=ip_address,
    )


# --- Service-level lifecycle (no route reaches these in Phase 9) --------------


#: Past-tense wording for the lifecycle summaries, keyed by action.
_STATUS_VERBS = {
    ACTION_SUSPEND: "suspended",
    ACTION_REINSTATE: "reinstated",
    ACTION_DEACTIVATE: "deactivated",
}


def status_changed(
    db: Session, *, identity: CustomerIdentity, action: str, reason_code: str, actor=None
) -> None:
    """Suspend, reinstate or deactivate, performed at the service layer.

    Phase 9 exposes **no route** that calls this. It exists because instruction section 8
    requires administrative and security revocation support at the service layer, and
    because a suspension has to be reachable during an incident before the Phase 10 staff
    screen exists. ``actor`` is a staff user when one performed it.
    """
    audit_service.record_audit(
        db,
        action=action,
        entity_type=ENTITY_IDENTITY,
        entity_id=identity.public_id,
        # The reference is in the summary itself (UAT round 5): Audit access shows the
        # summary, and "Customer Account deactivate" alone did not say which account.
        summary=f"Customer Account {identity.public_id} {_STATUS_VERBS.get(action, action)}",
        actor=actor,
        detail={
            "identity_public_id": identity.public_id,
            "reason_code": reason_code,
            "status": identity.status,
        },
    )


# --- Proposals ----------------------------------------------------------------


def proposal_submitted(
    db: Session,
    *,
    identity: CustomerIdentity,
    proposal_id: int,
    field_keys: list[str],
    ip_address: str | None,
) -> None:
    """Field **keys** only. The values live on the proposal rows and stay there."""
    _record(
        db,
        action=ACTION_PROPOSAL_SUBMIT,
        entity_type=ENTITY_PROPOSAL,
        entity_id=proposal_id,
        summary="Customer data proposal submitted",
        detail={
            "identity_public_id": identity.public_id,
            "field_keys": sorted(field_keys),
            "field_count": len(field_keys),
            "status": "pending",
        },
        ip_address=ip_address,
        customer_actor=identity,
    )


def proposal_superseded(
    db: Session, *, identity: CustomerIdentity, proposal_id: int, superseded_id: int
) -> None:
    _record(
        db,
        action=ACTION_PROPOSAL_SUPERSEDE,
        entity_type=ENTITY_PROPOSAL,
        entity_id=superseded_id,
        summary="Customer data proposal superseded by a newer submission",
        detail={
            "identity_public_id": identity.public_id,
            "superseded_by_proposal_id": proposal_id,
            "status": "superseded",
        },
        customer_actor=identity,
    )


# --- Phase 10: staff review ---------------------------------------------------
#
# These take a staff ``actor`` and pass it through, so ``audit_events.actor_user_id`` and
# ``actor_label`` name the person who acted. The payload rules are unchanged and are the
# reason this module exists: an identity by ``public_id``, a customer by ``public_id``,
# field **keys**, reason codes, counts and fingerprints. Never a submitted value, never an
# address, never a phone number, never a shipment reference.
#
# The disclosure figures *are* written, and are the one place a count appears in an audit
# payload. That is deliberate: OD-29 and AC-CA-10.4 require the approval record to carry
# what the approver was shown, and a count of shipments for a named customer is a fact
# staff already have. It is still never returned to a customer-facing route.


def queue_reviewed(db: Session, *, actor, count: int, ip_address: str | None) -> None:
    """Somebody listed the pending queue. Counts, never the applicants.

    Audited because reading a queue of people who have applied is itself an access to
    personal data, and "who has been reading the applications" is a question the audit log
    should be able to answer. The row names no applicant, because the answer to that
    question does not need one.
    """
    audit_service.record_audit(
        db,
        action=ACTION_QUEUE_REVIEWED,
        entity_type=ENTITY_IDENTITY,
        entity_id=None,
        summary="Customer Account approval queue listed",
        actor=actor,
        ip_address=ip_address,
        detail={"returned_count": count},
    )


def registration_opened(
    db: Session, *, identity: CustomerIdentity, actor, field_keys: list[str], ip_address: str | None
) -> None:
    """One application was opened for review. Field keys, never the submitted values."""
    audit_service.record_audit(
        db,
        action=ACTION_REGISTRATION_OPENED,
        entity_type=ENTITY_IDENTITY,
        entity_id=identity.public_id,
        summary=f"Customer Account registration {identity.public_id} opened for review",
        actor=actor,
        ip_address=ip_address,
        detail={
            "identity_public_id": identity.public_id,
            "field_keys": sorted(field_keys),
            "status": identity.status,
        },
    )


def identity_status_read(
    db: Session, *, identity: CustomerIdentity, actor, ip_address: str | None
) -> None:
    """A staff member read an account's lifecycle state. Audited like opening an application:
    it is an access to a record about a person, and "who looked" should be answerable."""
    audit_service.record_audit(
        db,
        action=ACTION_IDENTITY_STATUS_READ,
        entity_type=ENTITY_IDENTITY,
        entity_id=identity.public_id,
        summary=f"Customer Account {identity.public_id} status read",
        actor=actor,
        ip_address=ip_address,
        detail={"identity_public_id": identity.public_id, "status": identity.status},
    )


def duplicates_reviewed(
    db: Session,
    *,
    identity: CustomerIdentity,
    actor,
    classification: str,
    candidate_public_ids: list[str],
    ip_address: str | None,
) -> None:
    """The duplicate calculation was run and shown.

    The classification is the **reason code** the instruction asks to be audited, and the
    candidate references are the records a reviewer was shown side by side -- which is the
    thing worth being able to reconstruct later if a link turns out to be wrong. Scores
    are not written: a number that varies with a weighting table is not evidence.
    """
    audit_service.record_audit(
        db,
        action=ACTION_DUPLICATES_REVIEWED,
        entity_type=ENTITY_IDENTITY,
        entity_id=identity.public_id,
        summary=f"Duplicate candidates reviewed for {identity.public_id}",
        actor=actor,
        ip_address=ip_address,
        detail={
            "identity_public_id": identity.public_id,
            "duplicate_classification": classification,
            "candidate_public_ids": sorted(candidate_public_ids),
            "candidate_count": len(candidate_public_ids),
        },
    )


def preview_created(
    db: Session,
    *,
    identity: CustomerIdentity,
    actor,
    action: str,
    customer_public_id: str | None,
    summary_detail: dict[str, Any],
    fingerprint: str,
    ip_address: str | None,
) -> None:
    """A preview was computed. The figures and the fingerprint, so drift is reconstructible."""
    audit_service.record_audit(
        db,
        action=ACTION_PREVIEW_CREATED,
        entity_type=ENTITY_IDENTITY,
        entity_id=identity.public_id,
        summary=f"Approval preview computed for {identity.public_id}",
        actor=actor,
        ip_address=ip_address,
        detail={
            "identity_public_id": identity.public_id,
            "intended_action": action,
            "customer_public_id": customer_public_id,
            "preview_fingerprint": fingerprint,
            **summary_detail,
        },
    )


def disclosure_acknowledged(
    db: Session,
    *,
    identity: CustomerIdentity,
    actor,
    action: str,
    customer_public_id: str | None,
    summary_detail: dict[str, Any],
    fingerprint: str,
    ip_address: str | None,
) -> None:
    """A reviewer acknowledged the disclosure. The evidence OD-29 asks for."""
    audit_service.record_audit(
        db,
        action=ACTION_DISCLOSURE_ACKNOWLEDGED,
        entity_type=ENTITY_IDENTITY,
        entity_id=identity.public_id,
        summary=f"History disclosure acknowledged for {identity.public_id}",
        actor=actor,
        ip_address=ip_address,
        detail={
            "identity_public_id": identity.public_id,
            "intended_action": action,
            "customer_public_id": customer_public_id,
            "preview_fingerprint": fingerprint,
            **summary_detail,
        },
    )


def approved(
    db: Session,
    *,
    identity: CustomerIdentity,
    actor,
    action: str,
    customer_public_id: str,
    applied_field_keys: list[str],
    summary_detail: dict[str, Any],
    fingerprint: str,
    reason_code: str | None,
    ip_address: str | None,
) -> None:
    """The approval itself: actor, identity, customer, preview figures, reason code.

    That list is AC-CA-10.4, and it is the record a later question about a wrong link is
    answered from. ``applied_field_keys`` is empty for a link-existing approval, which is
    how the log says "no canonical value was written" rather than leaving it to be
    inferred from the absence of a customer-update row.
    """
    audit_service.record_audit(
        db,
        action=ACTION_APPROVE,
        entity_type=ENTITY_IDENTITY,
        entity_id=identity.public_id,
        summary=f"Customer Account {identity.public_id} approved and linked to "
        f"{customer_public_id}{_override_suffix(actor)}",
        actor=actor,
        ip_address=ip_address,
        detail={
            "identity_public_id": identity.public_id,
            "customer_public_id": customer_public_id,
            "approval_action": action,
            "applied_field_keys": sorted(applied_field_keys),
            "reason_code": reason_code,
            "admin_override": _admin_override(actor),
            "preview_fingerprint": fingerprint,
            **summary_detail,
        },
    )


def linked(
    db: Session,
    *,
    identity: CustomerIdentity,
    actor,
    customer_public_id: str,
    link_role: str,
    differing_field_keys: list[str],
    ip_address: str | None,
) -> None:
    """The link row was written.

    Separate from ``approved`` because they are two facts: one account was approved, and
    one account now reaches one customer's data. ``differing_field_keys`` records what the
    applicant said that the customer record does not -- **keys only**, and applied to
    nothing. It is the trail Phase 12 change-proposal handling will pick up (OD-28).
    """
    audit_service.record_audit(
        db,
        action=ACTION_LINK,
        entity_type=ENTITY_IDENTITY,
        entity_id=identity.public_id,
        summary=f"Customer Account {identity.public_id} linked to {customer_public_id}",
        actor=actor,
        ip_address=ip_address,
        detail={
            "identity_public_id": identity.public_id,
            "customer_public_id": customer_public_id,
            "link_role": link_role,
            "link_status": "active",
            "differing_field_keys": sorted(differing_field_keys),
        },
    )


def link_ended_by_takeover(
    db: Session,
    *,
    previous_identity_public_id: str,
    new_identity_public_id: str,
    actor,
    customer_public_id: str,
    ip_address: str | None,
) -> None:
    """A deactivated account's link was ended because a new account took the customer over.

    Owner decision, 2026-10-15: a customer whose only account was deactivated may be linked
    to a new registration, and only by a staff approval that ends the old link. Recorded
    against the **old** identity, because that is the account whose access record changed;
    the new one is named in the payload so the two rows can be read together.
    """
    audit_service.record_audit(
        db,
        action=ACTION_UNLINK,
        entity_type=ENTITY_IDENTITY,
        entity_id=previous_identity_public_id,
        summary=f"Customer Account {previous_identity_public_id} (deactivated) unlinked from "
        f"{customer_public_id}; taken over by {new_identity_public_id}",
        actor=actor,
        ip_address=ip_address,
        detail={
            "identity_public_id": previous_identity_public_id,
            "customer_public_id": customer_public_id,
            "replaced_by_identity_public_id": new_identity_public_id,
            "link_status": "revoked",
            "reason_code": REASON_TAKEN_OVER,
        },
    )


def sign_in_email_applied(
    db: Session,
    *,
    identity: CustomerIdentity,
    actor,
    customer_public_id: str,
    previous_email_present: bool,
    ip_address: str | None,
) -> None:
    """The linked customer's email became the account's verified sign-in email.

    The single email rule (owner decision, 2026-10-15): a customer has one email, and once
    an account is linked it is the address the account holder proved they control. **No
    address in the payload**, old or new -- the customer record and the identity hold them,
    and an audit row is read by people who need to know that it changed, not what to.
    """
    audit_service.record_audit(
        db,
        action=ACTION_SIGN_IN_EMAIL_APPLIED,
        entity_type=ENTITY_IDENTITY,
        entity_id=identity.public_id,
        summary=f"Email of {customer_public_id} set to the sign-in email of Customer Account "
        f"{identity.public_id}",
        actor=actor,
        ip_address=ip_address,
        detail={
            "identity_public_id": identity.public_id,
            "customer_public_id": customer_public_id,
            "previous_email_present": previous_email_present,
            "reason_code": REASON_SINGLE_EMAIL,
        },
    )


def separate_customer_override(
    db: Session,
    *,
    identity: CustomerIdentity,
    actor,
    classification: str,
    candidate_public_ids: list[str],
    reason_code: str,
    ip_address: str | None,
) -> None:
    """A new customer was created although a candidate existed.

    Its own action rather than a field on the approval, because "how often does this
    happen, and who does it" is a review question with an answer that should not require
    reading every approval payload (T-18).
    """
    audit_service.record_audit(
        db,
        action=ACTION_SEPARATE_CUSTOMER_OVERRIDE,
        entity_type=ENTITY_IDENTITY,
        entity_id=identity.public_id,
        summary=f"Separate customer created for {identity.public_id} despite a "
        f"{classification} duplicate candidate",
        actor=actor,
        ip_address=ip_address,
        detail={
            "identity_public_id": identity.public_id,
            "duplicate_classification": classification,
            "candidate_public_ids": sorted(candidate_public_ids),
            "override_reason_code": reason_code,
        },
    )


def rejected(
    db: Session,
    *,
    identity: CustomerIdentity,
    actor,
    reason_code: str,
    sessions_revoked: int,
    tokens_invalidated: int,
    ip_address: str | None,
) -> None:
    """The application was declined. A reason **code**, and two counts.

    The optional internal note a reviewer may add is **not** here. It is bounded prose
    about a person, the existing redaction rules treat prose about a person as something
    to keep out of the audit trail, and a code plus the counts is what an auditor needs.
    """
    audit_service.record_audit(
        db,
        action=ACTION_REJECT,
        entity_type=ENTITY_IDENTITY,
        entity_id=identity.public_id,
        summary=f"Customer Account {identity.public_id} rejected{_override_suffix(actor)}",
        actor=actor,
        ip_address=ip_address,
        detail={
            "identity_public_id": identity.public_id,
            "reason_code": reason_code,
            "admin_override": _admin_override(actor),
            "sessions_revoked": sessions_revoked,
            "tokens_invalidated": tokens_invalidated,
            "status": identity.status,
        },
    )


def preview_stale_refused(
    db: Session,
    *,
    identity: CustomerIdentity,
    actor,
    action: str,
    presented_fingerprint: str,
    current_fingerprint: str,
    ip_address: str | None,
    reason_code: str = REASON_PREVIEW_DRIFT,
) -> None:
    """An approval was refused because the world moved under it.

    Audited rather than silently returned, because a burst of these is the signal that two
    reviewers are working the same queue -- or that something is rewriting customers while
    approvals are in flight.

    ``reason_code`` separates the ordinary case from the one OD-40 asks to be able to see:
    a preview invalidated because the customer it named was **merged** while the reviewer
    was reading it. Both are stale previews and both refuse identically; only the log tells
    them apart, which is the point -- "approvals keep going stale" and "approvals keep
    going stale because merges are running underneath them" are different operational
    problems with different answers.
    """
    audit_service.record_audit(
        db,
        action=ACTION_PREVIEW_STALE,
        entity_type=ENTITY_IDENTITY,
        entity_id=identity.public_id,
        summary=f"Approval of {identity.public_id} refused: the preview was stale",
        actor=actor,
        ip_address=ip_address,
        detail={
            "identity_public_id": identity.public_id,
            "intended_action": action,
            "presented_fingerprint": presented_fingerprint,
            "current_fingerprint": current_fingerprint,
            "reason_code": reason_code,
        },
    )


def approval_conflict(
    db: Session,
    *,
    identity: CustomerIdentity,
    actor,
    action: str,
    reason_code: str,
    ip_address: str | None,
) -> None:
    """Two decisions raced and this one lost. One final outcome, and a record of the other."""
    audit_service.record_audit(
        db,
        action=ACTION_APPROVAL_CONFLICT,
        entity_type=ENTITY_IDENTITY,
        entity_id=identity.public_id,
        summary=f"Concurrent decision on {identity.public_id} refused",
        actor=actor,
        ip_address=ip_address,
        detail={
            "identity_public_id": identity.public_id,
            "intended_action": action,
            "reason_code": reason_code,
        },
    )


def approval_replayed(
    db: Session,
    *,
    identity: CustomerIdentity,
    actor,
    action: str,
    outcome: str,
    ip_address: str | None,
) -> None:
    """The same idempotency key arrived again. Nothing else was written.

    The replay is audited and the original approval is not repeated, which is the
    distinction AC-CA-4.5 asks for: one canonical change and one approval record, plus a
    record that somebody retried.
    """
    audit_service.record_audit(
        db,
        action=ACTION_APPROVAL_REPLAYED,
        entity_type=ENTITY_IDENTITY,
        entity_id=identity.public_id,
        summary=f"Idempotent replay of a decision on {identity.public_id}",
        actor=actor,
        ip_address=ip_address,
        detail={
            "identity_public_id": identity.public_id,
            "intended_action": action,
            "original_outcome": outcome,
        },
    )


# --- The customer-merge gate --------------------------------------------------


def merge_refused_linked_customer(
    db: Session,
    *,
    source_public_id: str,
    target_public_id: str,
    blocked_side: str,
    actor,
    ip_address: str | None,
) -> None:
    """Record that a customer merge was refused because a link is in the way (OD-40).

    **What goes in, and why it is this little.** The two customer references, which side
    blocked, and a reason code. That is enough for a reviewer to find the two records and
    take them to reconciliation, and for an operator to see a burst of refusals and ask
    why merges are being attempted against linked customers.

    **What deliberately does not go in.** The identity: naming ``CA-000017`` here would put
    "this customer has an account, and here is its reference" into a row written by the
    *customer* surface, readable by everyone who can read customer audit -- a wider
    population than the approval queue, and a disclosure the merge did not need to make.
    Nor the email address, the session state, the proposal, the disclosure figures or any
    shipment reference: a refusal discloses nothing, and the whole point of the refusal is
    that no disclosure was acknowledged.

    ``blocked_side`` is one of ``source``, ``target`` or ``both``. It says which record to
    look at without saying anything about what is on it.
    """
    audit_service.record_audit(
        db,
        action=ACTION_MERGE_REFUSED,
        entity_type="customer",
        entity_id=target_public_id,
        summary=(
            f"Merge of {source_public_id} into {target_public_id} refused: "
            "a Customer Account link is present"
        ),
        actor=actor,
        ip_address=ip_address,
        detail={
            "source_public_id": source_public_id,
            "target_public_id": target_public_id,
            "blocked_side": blocked_side,
            "reason_code": REASON_LINK_PRESENT,
        },
    )


# --- Phase 11: authenticated shipment reads -----------------------------------
#
# **Denials are audited; successes are not.** That asymmetry is the granularity the
# security architecture approved and is worth stating rather than discovering: T-03's
# detection line is "repeated not-found results for one identity is a probing signal", and
# `RATE_LIMITS_AND_ABUSE.md` §7 watches "not-found rates per identity on shipment routes".
# Neither asks for a row per successful read, and a row per successful read would be an
# audit table that grows with ordinary browsing and a second copy of a customer's history
# written in summaries. Successful reads are recorded as a bounded structured **log** event
# instead (`customer_account_shipment_service` has no logging of its own; the route does).
#
# T-03's audit line asks for "the requested reference". The Phase 11 instruction forbids a
# raw shipment reference in an audit payload, and the stricter rule wins: what is written
# is the **keyed digest** the public surface already uses, which correlates repeated probes
# against one reference without putting an identifier in the table.

ACTION_SHIPMENT_ACCESS_DENIED = "customer_account.shipment_access_denied"

#: Why a read was refused. Bounded, and each one describes the *account* or the request --
#: never the shipment, and never whether one exists.
REASON_NOT_AUTHORIZED = "not_authorized"
REASON_SHIPMENT_NOT_FOUND = "shipment_not_found"

#: Every Phase 11 denial reason, for a test that asserts the set is closed.
SHIPMENT_DENIAL_REASONS = frozenset({REASON_NOT_AUTHORIZED, REASON_SHIPMENT_NOT_FOUND})


def shipment_access_denied(
    db: Session,
    *,
    identity: CustomerIdentity,
    surface: str,
    reason_code: str,
    reference_digest: str | None = None,
    ip_address: str | None = None,
) -> None:
    """An authenticated shipment read was refused.

    ``surface`` is ``"list"`` or ``"detail"`` -- a bounded action name, not a path.
    ``reason_code`` is one of ``SHIPMENT_DENIAL_REASONS`` and is the *category*, not the
    internal detail: a request refused because the identity holds no effective link and one
    refused because its linked customer was archived both record ``not_authorized``, because
    the difference is a fact about the CRM's state and the audit trail for a customer-facing
    refusal is not where that belongs. The link-resolution reason travels in the
    application log, which is operator-facing.

    ``reference_digest`` is a keyed digest and is present only for a detail refusal. There
    is no reference on a list request to digest.

    **Not written:** the raw reference, a carrier tracking number, an email, a phone number,
    recipient information, a session or CSRF value, any response payload, or any figure
    about how much history exists -- a count is the enumeration oracle
    `SHIPMENT_ALLOWLISTS.md` §6 keeps off customer-facing paths, and writing it into an
    audit row would put it one export away from one.
    """
    detail: dict[str, Any] = {
        "identity_public_id": identity.public_id,
        "surface": surface,
        "reason_code": reason_code,
    }
    if reference_digest:
        detail["reference_digest"] = reference_digest
    _record(
        db,
        action=ACTION_SHIPMENT_ACCESS_DENIED,
        entity_type=ENTITY_IDENTITY,
        entity_id=identity.public_id,
        summary=f"Shipment {surface} access refused for {identity.public_id}",
        detail=detail,
        ip_address=ip_address,
    )


# --- Fix pack 2: the Customer Account profile (CA-PRF-01 ... CA-PRF-04) -------------
#
# Customer-side events keep this module's payload rule: field **keys**, statuses and
# reason codes; never a submitted value. The staff decision passes its actor.

ACTION_PROFILE_DIRECT = "customer_account.profile_direct_update"
ACTION_PROPOSAL_WITHDRAW = "customer_data_proposal.withdraw"
ACTION_MARKETING_CHOICE = "customer_account.marketing_choice"
ACTION_PROFILE_PROPOSAL_OPENED = "customer_data_proposal.opened"
ACTION_PROFILE_PROPOSAL_DECIDED = "customer_data_proposal.decide"


def profile_direct_updated(
    db: Session,
    *,
    identity: CustomerIdentity,
    customer_public_id: str,
    field_keys: list[str],
    ip_address: str | None,
) -> None:
    """A direct field (FIELD_MATRIX §3.1) changed by the customer. Keys only."""
    _record(
        db,
        action=ACTION_PROFILE_DIRECT,
        entity_type="customer",
        entity_id=customer_public_id,
        summary="Customer changed a direct profile field",
        detail={"identity_public_id": identity.public_id, "field_keys": sorted(field_keys)},
        ip_address=ip_address,
        customer_actor=identity,
    )


def proposal_withdrawn(
    db: Session, *, identity: CustomerIdentity, proposal_id: int, ip_address: str | None
) -> None:
    _record(
        db,
        action=ACTION_PROPOSAL_WITHDRAW,
        entity_type=ENTITY_PROPOSAL,
        entity_id=proposal_id,
        summary="Customer withdrew a pending profile change",
        detail={"identity_public_id": identity.public_id, "status": "withdrawn"},
        ip_address=ip_address,
        customer_actor=identity,
    )


def marketing_choice_recorded(
    db: Session,
    *,
    identity: CustomerIdentity,
    customer_public_id: str,
    status: str,
    suppressed: bool,
    ip_address: str | None,
) -> None:
    """The customer's own marketing choice.

    ``address_suppressed`` is staff-facing context -- the audit log is not a customer
    surface -- so an operator reading the row knows the grant did not make the address
    contactable. Nothing in the customer's response carries it (FIELD_MATRIX §4 rule 2).
    """
    _record(
        db,
        action=ACTION_MARKETING_CHOICE,
        entity_type="customer",
        entity_id=customer_public_id,
        summary=f"Customer recorded marketing consent: {status}",
        detail={
            "identity_public_id": identity.public_id,
            "channel": "email",
            "status": status,
            "address_suppressed": suppressed,
        },
        ip_address=ip_address,
        customer_actor=identity,
    )


def profile_proposal_opened(
    db: Session, *, identity: CustomerIdentity, proposal_id: int, actor, ip_address: str | None
) -> None:
    audit_service.record_audit(
        db,
        action=ACTION_PROFILE_PROPOSAL_OPENED,
        entity_type=ENTITY_PROPOSAL,
        entity_id=proposal_id,
        summary=f"Profile change from {identity.public_id} opened for review",
        actor=actor,
        ip_address=ip_address,
        detail={"identity_public_id": identity.public_id},
    )


def profile_proposal_decided(
    db: Session,
    *,
    identity: CustomerIdentity,
    customer_public_id: str,
    proposal_id: int,
    approved_groups: list[str],
    declined_groups: list[str],
    reason_code: str | None,
    actor,
    ip_address: str | None,
) -> None:
    audit_service.record_audit(
        db,
        action=ACTION_PROFILE_PROPOSAL_DECIDED,
        entity_type=ENTITY_PROPOSAL,
        entity_id=proposal_id,
        summary=(
            f"Profile change from {identity.public_id} decided: "
            f"{len(approved_groups)} approved, {len(declined_groups)} declined"
        ),
        actor=actor,
        ip_address=ip_address,
        detail={
            "identity_public_id": identity.public_id,
            "customer_public_id": customer_public_id,
            "approved": sorted(approved_groups),
            "declined": sorted(declined_groups),
            "reason_code": reason_code,
        },
    )


# --- RC-UAT-21 Phase B: password change, email change, reinstatement (DEC-0231) ----------
#
# The same payload rules as every event above: the identity ``public_id``, reason codes,
# counts and the actor. **No address** -- the new address of an email change is recorded as
# its keyed ``address_key`` so repeated requests for one address correlate without the audit
# table holding it -- and never a password, hash or token.

ACTION_PASSWORD_CHANGED = "customer_account.password_changed"
ACTION_PASSWORD_CHANGE_REFUSED = "customer_account.password_change_refused"
ACTION_EMAIL_CHANGE_REQUESTED = "customer_account.email_change_requested"
ACTION_EMAIL_CHANGE_CANCELLED = "customer_account.email_change_cancelled"
ACTION_EMAIL_CHANGED = "customer_account.email_changed"
ACTION_EMAIL_CHANGE_REFUSED = "customer_account.email_change_refused"
ACTION_REACTIVATE = "customer_account.reactivate"
ACTION_DEACTIVATED_LIST_READ = "customer_account.deactivated_list_read"


def password_changed(
    db: Session, *, identity: CustomerIdentity, sessions_revoked: int, ip_address: str | None
) -> None:
    """The customer changed their own password while signed in."""
    _record(
        db,
        action=ACTION_PASSWORD_CHANGED,
        entity_type=ENTITY_IDENTITY,
        entity_id=identity.public_id,
        summary=f"Customer Account {identity.public_id} changed its password",
        detail={
            "identity_public_id": identity.public_id,
            "count": sessions_revoked,
            "reason_code": "password_changed",
        },
        ip_address=ip_address,
        customer_actor=identity,
    )


def password_change_refused(
    db: Session, *, identity: CustomerIdentity, reason_code: str, ip_address: str | None
) -> None:
    """A signed-in password change was refused: ``bad_current_password``, ``same_password``."""
    _record(
        db,
        action=ACTION_PASSWORD_CHANGE_REFUSED,
        entity_type=ENTITY_IDENTITY,
        entity_id=identity.public_id,
        summary=f"Password change refused for Customer Account {identity.public_id}",
        detail={"identity_public_id": identity.public_id, "reason_code": reason_code},
        ip_address=ip_address,
        customer_actor=identity,
    )


def email_change_requested(
    db: Session,
    *,
    identity: CustomerIdentity,
    new_email_normalized: str,
    outcome: str,
    ip_address: str | None,
) -> None:
    """``outcome`` is ``sent`` or a refusal code; the customer was told the same either way."""
    _record(
        db,
        action=ACTION_EMAIL_CHANGE_REQUESTED,
        entity_type=ENTITY_IDENTITY,
        entity_id=identity.public_id,
        summary=f"Customer Account {identity.public_id} asked to change its sign-in email",
        detail={
            "identity_public_id": identity.public_id,
            "outcome": outcome,
            "address_key": address_key(new_email_normalized),
        },
        ip_address=ip_address,
        customer_actor=identity,
    )


def email_change_cancelled(
    db: Session,
    *,
    identity: CustomerIdentity,
    ip_address: str | None,
    reason_code: str = "cancelled",
) -> None:
    """``cancelled`` by the customer, or ``password_changed`` / ``password_reset``."""
    _record(
        db,
        action=ACTION_EMAIL_CHANGE_CANCELLED,
        entity_type=ENTITY_IDENTITY,
        entity_id=identity.public_id,
        summary=f"Email change of Customer Account {identity.public_id} cancelled ({reason_code})",
        detail={"identity_public_id": identity.public_id, "reason_code": reason_code},
        ip_address=ip_address,
        customer_actor=identity,
    )


def email_changed(
    db: Session,
    *,
    identity: CustomerIdentity,
    customer_public_id: str | None,
    ip_address: str | None,
) -> None:
    """The new address was proved and is now the sign-in email (and, when linked, the
    customer record's email under the single email rule)."""
    _record(
        db,
        action=ACTION_EMAIL_CHANGED,
        entity_type=ENTITY_IDENTITY,
        entity_id=identity.public_id,
        summary=f"Customer Account {identity.public_id} sign-in email changed",
        detail={
            "identity_public_id": identity.public_id,
            "customer_public_id": customer_public_id,
            "reason_code": REASON_SINGLE_EMAIL if customer_public_id else "email_changed",
        },
        ip_address=ip_address,
        customer_actor=identity,
    )


def email_change_refused(
    db: Session, *, identity: CustomerIdentity | None, reason_code: str, ip_address: str | None
) -> None:
    """A confirmation link was refused at redemption time (the address was taken meanwhile)."""
    _record(
        db,
        action=ACTION_EMAIL_CHANGE_REFUSED,
        entity_type=ENTITY_IDENTITY,
        entity_id=_identity_id(identity),
        summary="Email change confirmation refused",
        detail={"identity_public_id": _identity_id(identity), "reason_code": reason_code},
        ip_address=ip_address,
    )


def reactivated(
    db: Session,
    *,
    identity: CustomerIdentity,
    reason_code: str,
    deactivation_reason_code: str | None,
    actor,
    ip_address: str | None,
    link_ended_reason: str | None = None,
) -> None:
    """An Admin reinstated a deactivated account. The note stays on the reinstatement row."""
    audit_service.record_audit(
        db,
        action=ACTION_REACTIVATE,
        entity_type=ENTITY_IDENTITY,
        entity_id=identity.public_id,
        summary=f"Customer Account {identity.public_id} reinstated after deactivation",
        actor=actor,
        ip_address=ip_address,
        detail={
            "identity_public_id": identity.public_id,
            "reason_code": reason_code,
            "deactivation_reason_code": deactivation_reason_code,
            "status": identity.status,
            "link_ended_reason": link_ended_reason,
        },
    )


def link_ended_on_reinstatement(
    db: Session,
    *,
    identity: CustomerIdentity,
    customer_public_id: str,
    reason_code: str,
    actor,
    ip_address: str | None,
) -> None:
    """A reinstatement ended the link: the customer was merged or archived meanwhile."""
    audit_service.record_audit(
        db,
        action=ACTION_UNLINK,
        entity_type=ENTITY_IDENTITY,
        entity_id=identity.public_id,
        summary=f"Customer Account {identity.public_id} unlinked from {customer_public_id} on "
        f"reinstatement ({reason_code})",
        actor=actor,
        ip_address=ip_address,
        detail={
            "identity_public_id": identity.public_id,
            "customer_public_id": customer_public_id,
            "link_status": "revoked",
            "reason_code": reason_code,
        },
    )


def deactivated_list_read(db: Session, *, actor, count: int, ip_address: str | None) -> None:
    audit_service.record_audit(
        db,
        action=ACTION_DEACTIVATED_LIST_READ,
        entity_type=ENTITY_IDENTITY,
        entity_id=None,
        summary=f"Listed {count} deactivated Customer Account(s)",
        actor=actor,
        ip_address=ip_address,
        detail={"count": count},
    )


# --- RC-UAT-22: orphaned accounts, re-link or close (B-13, DEC-0234 draft) ---------------------
#
# An orphaned account was approved once and has no live link and no pending proposal, so the
# approval flow has nothing to decide (an RC-UAT-21 reinstatement onto a merged or archived
# customer ends the link and leaves exactly that). Admin-only, like reinstatement. The same
# payload rules as above: references, bounded codes, counts and the actor; the Admin's note
# stays on the ``customer_account_relinks`` row.

ACTION_ORPHANED_LIST_READ = "customer_account.orphaned_list_read"
ACTION_RELINK_PREVIEWED = "customer_account.relink_previewed"
ACTION_RELINK = "customer_account.relink"
ACTION_ORPHAN_CLOSED = "customer_account.orphan_closed"


def orphaned_list_read(db: Session, *, actor, count: int, ip_address: str | None) -> None:
    audit_service.record_audit(
        db,
        action=ACTION_ORPHANED_LIST_READ,
        entity_type=ENTITY_IDENTITY,
        entity_id=None,
        summary=f"Listed {count} Customer Account(s) needing a customer",
        actor=actor,
        ip_address=ip_address,
        detail={"count": count},
    )


def relink_previewed(
    db: Session,
    *,
    identity: CustomerIdentity,
    actor,
    customer_public_id: str,
    summary_detail: dict[str, Any],
    fingerprint: str,
    ip_address: str | None,
) -> None:
    """An Admin was shown the history a re-link would open, as an approval preview is."""
    audit_service.record_audit(
        db,
        action=ACTION_RELINK_PREVIEWED,
        entity_type=ENTITY_IDENTITY,
        entity_id=identity.public_id,
        summary=f"Re-link preview for Customer Account {identity.public_id} to "
        f"{customer_public_id}",
        actor=actor,
        ip_address=ip_address,
        detail={
            "identity_public_id": identity.public_id,
            "customer_public_id": customer_public_id,
            "preview_fingerprint": fingerprint,
            **summary_detail,
        },
    )


def relinked(
    db: Session,
    *,
    identity: CustomerIdentity,
    actor,
    customer_public_id: str,
    previous_customer_public_id: str | None,
    previous_link_end_reason: str | None,
    reason_code: str,
    summary_detail: dict[str, Any],
    fingerprint: str,
    ip_address: str | None,
) -> None:
    """An orphaned account was linked to a customer and returned to ``active``."""
    audit_service.record_audit(
        db,
        action=ACTION_RELINK,
        entity_type=ENTITY_IDENTITY,
        entity_id=identity.public_id,
        summary=f"Customer Account {identity.public_id} re-linked to {customer_public_id}",
        actor=actor,
        ip_address=ip_address,
        detail={
            "identity_public_id": identity.public_id,
            "customer_public_id": customer_public_id,
            "previous_customer_public_id": previous_customer_public_id,
            "previous_link_end_reason": previous_link_end_reason,
            "reason_code": reason_code,
            "status": identity.status,
            "preview_fingerprint": fingerprint,
            **summary_detail,
        },
    )


def orphan_closed(
    db: Session,
    *,
    identity: CustomerIdentity,
    actor,
    previous_customer_public_id: str | None,
    reason_code: str,
    ip_address: str | None,
) -> None:
    """An orphaned account was closed (deactivated, reason ``orphan_closed``)."""
    audit_service.record_audit(
        db,
        action=ACTION_ORPHAN_CLOSED,
        entity_type=ENTITY_IDENTITY,
        entity_id=identity.public_id,
        summary=f"Customer Account {identity.public_id} closed: no customer to link",
        actor=actor,
        ip_address=ip_address,
        detail={
            "identity_public_id": identity.public_id,
            "previous_customer_public_id": previous_customer_public_id,
            "reason_code": reason_code,
            "status": identity.status,
        },
    )


# --- RC-UAT-25 item 2 (Ben, 2026-10-25): an Admin changes the sign-in email ---------------------
#
# Customers can no longer change it themselves. The same payload rules as above: references,
# a bounded reason code, a count and the actor; both addresses only as keyed ``address_key``
# digests; the Admin's note stays on the ``customer_account_email_changes`` row.

ACTION_SIGN_IN_EMAIL_CHANGED_BY_STAFF = "customer_account.sign_in_email_changed_by_staff"


def sign_in_email_changed_by_staff(
    db: Session,
    *,
    identity: CustomerIdentity,
    actor,
    customer_public_id: str | None,
    reason_code: str,
    previous_email_normalized: str,
    new_email_normalized: str,
    sessions_revoked: int,
    ip_address: str | None,
) -> None:
    """An Admin moved the account to a new sign-in email (the linked customer's followed)."""
    audit_service.record_audit(
        db,
        action=ACTION_SIGN_IN_EMAIL_CHANGED_BY_STAFF,
        entity_type=ENTITY_IDENTITY,
        entity_id=identity.public_id,
        summary=f"Customer Account {identity.public_id} sign-in email changed by staff",
        actor=actor,
        ip_address=ip_address,
        detail={
            "identity_public_id": identity.public_id,
            "customer_public_id": customer_public_id,
            "reason_code": reason_code,
            "count": sessions_revoked,
            "previous_address_key": address_key(previous_email_normalized),
            "address_key": address_key(new_email_normalized),
        },
    )
