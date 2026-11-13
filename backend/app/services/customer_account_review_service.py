"""Reading a pending registration, and computing the preview an approval is checked against.

Everything in this module is a **read**, with one exception: `acknowledge` writes the row
that records a reviewer saw the disclosure figures. Nothing here creates a customer, an
address, a consent event or a link, and nothing here activates an identity. That is
`customer_account_approval_service`, deliberately a separate module, so that the code a
reviewer's browsing hits cannot write canonical data however wrong it is.

**The preview is the safety property this phase turns on.** A reviewer decides using
figures the server computed; the approval then recomputes every one of them and refuses if
any has moved. The mechanism is a fingerprint over the facts, and what it covers is listed
in `_fingerprint_parts` rather than described here, because a list in a docstring drifts
from the list in the code and the code is the one that runs.

**What a preview may not contain**, and does not: a shipment row, reference, package,
event or date beyond the two bounds; recipient data; a financial value; an internal note;
a password hash, token digest, session digest or CSRF value; a customer unrelated to the
duplicate review. `tests/test_account_review_privacy.py` asserts it recursively over the
serialized body with planted values.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session, selectinload

from app.core import account_field_mapping as mapping
from app.core.account_enums import (
    ApprovalAction,
    DuplicateClassification,
    IdentityStatus,
    LinkStatus,
    ProposalStatus,
)
from app.core.account_security import fingerprint as compute_fingerprint
from app.core.time_utils import utcnow
from app.models import (
    Customer,
    CustomerAccountDisclosureAcknowledgement,
    CustomerDataProposal,
    CustomerIdentity,
    CustomerIdentityLink,
    User,
)
from app.services import customer_account_audit as audit
from app.services import customer_account_disclosure_service as disclosure
from app.services import duplicate_service
from app.services.customer_account_disclosure_service import DisclosureSummary
from app.services.errors import ConflictError, NotFoundError, ValidationError

#: Server-enforced page size. A queue endpoint with an unbounded limit is a bulk export of
#: everybody who ever registered, reachable by anyone who can read the queue.
DEFAULT_PAGE_SIZE = 25
MAX_PAGE_SIZE = 100

#: How many duplicate candidates a reviewer is shown. The existing service already caps
#: at ten; this names the number the review path asks for rather than inheriting a default.
DUPLICATE_CANDIDATE_LIMIT = 10

#: Ordering options, as a closed map. A sort key from a query string is a column name from
#: a query string unless the mapping is explicit.
SORT_COLUMNS = {
    "submitted_at": CustomerDataProposal.submitted_at,
    "account_reference": CustomerIdentity.public_id,
    "verified_at": CustomerIdentity.email_verified_at,
}

#: States a registration may be reviewed from. ``pending_approval`` and nothing else: an
#: unverified identity has not proved mailbox control (OD-23), and an approved, rejected,
#: suspended or deactivated one has already been decided.
REVIEWABLE_STATUSES = (IdentityStatus.PENDING_APPROVAL.value,)


@dataclass(frozen=True)
class QueueRow:
    """One line of the pending queue. Enough to choose a row; nothing more.

    No email address, no phone number, no address and no duplicate result. The queue is a
    list of *applications*, and a reviewer opens one to see what it says. Putting the
    submitted contact details on the list page would make the queue itself a contact
    export for anybody who can read it.
    """

    account_reference: str
    status: str
    submitted_at: datetime
    email_verified_at: datetime | None
    proposal_id: int
    field_count: int


@dataclass(frozen=True)
class DuplicateCandidateRow:
    """One candidate, with only what a linking decision needs.

    `FIELD_MATRIX.md` section 5 says the reviewer sees duplicate *implications*. That is
    the customer's own reference, its display-level name, the coarse location, why it
    matched and how confidently -- plus whether it is already linked or merged, which is
    the difference between "you may link this" and "you may not". Not its notes, not its
    owner, not its tags, not its lifecycle, not its shipments, not its money.
    """

    customer_public_id: str
    full_name: str
    display_name: str | None
    city: str | None
    country_code: str | None
    matched_on: list[str]
    confidence: int
    is_archived: bool
    is_merged: bool
    has_active_identity_link: bool
    linkable: bool


@dataclass(frozen=True)
class ApprovalPreview:
    """What the server calculated, and the fingerprint an approval is checked against."""

    account_reference: str
    action: str
    proposal_id: int
    proposed: dict[str, str | None]
    current: dict[str, str | None] | None
    differences: list[dict[str, str | None]]
    duplicate_classification: str
    candidate_references: list[str]
    target_customer_public_id: str | None
    disclosure: DisclosureSummary
    fingerprint: str
    #: Set when the proposal cannot be mapped to a canonical customer at all. The preview
    #: still renders, so a reviewer can see *why* an approval would be refused instead of
    #: pressing the button and reading an error.
    mapping_refusal: str | None
    #: Link-existing only: the customer's email will become the account's verified sign-in
    #: email (the single email rule, owner decision 2026-10-15). ``{"current", "new"}``, or
    #: ``None`` when they already agree. Shown to the reviewer before they confirm.
    email_change: dict[str, str | None] | None = None
    #: Link-existing only: the reference of a **deactivated** account whose link to this
    #: customer the approval will end (owner decision, 2026-10-15). ``None`` otherwise.
    ends_link_of: str | None = None


# --- Reading the queue --------------------------------------------------------


def _pending_proposal_subquery() -> Select:
    """The newest pending registration proposal per identity.

    An identity may have a chain of superseded proposals; the queue and the review are
    about the one that is still pending. ``max(id)`` rather than ``max(submitted_at)``
    because two submissions in the same second are possible and an id is total.
    """
    return (
        select(
            CustomerDataProposal.identity_id.label("identity_id"),
            func.max(CustomerDataProposal.id).label("proposal_id"),
        )
        .where(CustomerDataProposal.status == ProposalStatus.PENDING.value)
        .group_by(CustomerDataProposal.identity_id)
        .subquery()
    )


def list_pending(
    db: Session,
    *,
    limit: int = DEFAULT_PAGE_SIZE,
    offset: int = 0,
    account_reference: str | None = None,
    submitted_from: datetime | None = None,
    submitted_to: datetime | None = None,
    sort: str = "submitted_at",
    descending: bool = False,
) -> tuple[list[QueueRow], int]:
    """The pending queue, bounded, filtered and totally ordered.

    Ordered by the requested column **and then by ``public_id``**, always. A partial order
    lets two rows swap between page one and page two, which silently hides an application
    from a reviewer paging through -- the same reason the shipment list has a tie-break
    (`SHIPMENT_ALLOWLISTS.md` section 3.2).

    Filtering is by account reference and submission date only. There is no free-text
    search over submitted names or addresses: that would be a contact search over people
    who are not customers yet, which is a different power from reviewing an application.
    """
    limit = max(1, min(limit, MAX_PAGE_SIZE))
    offset = max(0, offset)
    newest = _pending_proposal_subquery()

    conditions = [
        CustomerIdentity.status.in_(REVIEWABLE_STATUSES),
        CustomerDataProposal.id == newest.c.proposal_id,
    ]
    if account_reference:
        conditions.append(CustomerIdentity.public_id == account_reference.strip().upper())
    if submitted_from is not None:
        conditions.append(CustomerDataProposal.submitted_at >= submitted_from)
    if submitted_to is not None:
        conditions.append(CustomerDataProposal.submitted_at <= submitted_to)

    base = (
        select(CustomerIdentity, CustomerDataProposal)
        .join(newest, newest.c.identity_id == CustomerIdentity.id)
        .join(CustomerDataProposal, CustomerDataProposal.identity_id == CustomerIdentity.id)
        .where(*conditions)
    )

    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0

    column = SORT_COLUMNS.get(sort, CustomerDataProposal.submitted_at)
    ordering = column.desc() if descending else column.asc()
    rows = db.execute(
        base.options(selectinload(CustomerDataProposal.fields))
        .order_by(ordering, CustomerIdentity.public_id.asc())
        .limit(limit)
        .offset(offset)
    ).all()

    return [
        QueueRow(
            account_reference=identity.public_id,
            status=identity.status,
            submitted_at=proposal.submitted_at,
            email_verified_at=identity.email_verified_at,
            proposal_id=proposal.id,
            field_count=len(proposal.fields),
        )
        for identity, proposal in rows
    ], int(total)


def load_identity(db: Session, account_reference: str) -> CustomerIdentity:
    """One identity by its public reference, or a plain not-found.

    By ``public_id``, never by row id: an integer primary key in a staff URL is an
    invitation to walk the table, and ``CA-000001`` is the reference a person quotes.
    """
    identity = db.scalar(
        select(CustomerIdentity).where(
            CustomerIdentity.public_id == account_reference.strip().upper()
        )
    )
    if identity is None:
        raise NotFoundError("No Customer Account registration with that reference.")
    return identity


def current_proposal(db: Session, identity: CustomerIdentity) -> CustomerDataProposal:
    """The identity's newest pending proposal, or a refusal that says what is wrong."""
    proposal = db.scalar(
        select(CustomerDataProposal)
        .options(selectinload(CustomerDataProposal.fields))
        .where(
            CustomerDataProposal.identity_id == identity.id,
            CustomerDataProposal.status == ProposalStatus.PENDING.value,
        )
        .order_by(CustomerDataProposal.id.desc())
    )
    if proposal is None:
        raise ConflictError("This registration has no proposal waiting for review.")
    return proposal


def require_reviewable(identity: CustomerIdentity) -> None:
    """Refuse an identity that is not waiting for a decision, and say which way it went.

    Staff-facing, so it may name the state -- the rule that a refusal must not disclose is
    about the *customer-facing* surface. A reviewer who is told only "no" cannot tell a
    colleague's decision from a bug.
    """
    if identity.status in REVIEWABLE_STATUSES:
        return
    if identity.status == IdentityStatus.PENDING_VERIFICATION.value:
        raise ConflictError(
            "This applicant has not confirmed their email address yet, so there is "
            "nothing to approve."
        )
    raise ConflictError(f"This registration has already been decided: it is {identity.status}.")


# --- Duplicate review ---------------------------------------------------------


def effective_values(identity: CustomerIdentity, proposal: CustomerDataProposal) -> dict[str, str]:
    """The proposal's submitted values, plus the applicant's own address.

    A registration does not submit its email twice. The address is the account's login
    identifier, it arrives at the top level of the registration body, and Phase 9 stores
    it on ``customer_identities`` rather than copying it into the proposal -- so a
    proposal read on its own has a name, a phone and addresses and **no email at all**.

    `FIELD_MATRIX.md` section 2 nonetheless lists email as a registration field whose
    canonical target is ``customers.email_entered``, and it is the strongest contact
    detail the application carries: mailbox control over it has actually been proved,
    which is not true of anything else in the submission. So the review path treats the
    identity's address as the proposal's email wherever the proposal did not supply one.

    This is why an exact duplicate match works at all: without it, an applicant
    registering with the address of an existing customer would produce no candidate, and
    the strongest duplicate signal the CRM has would be the one the approval never saw.

    Since UAT round 6 the identity's address **replaces** any ``email`` the proposal
    carries. A customer has one email, and once an account exists it is the verified
    sign-in address (owner decision, 2026-10-15); a second address typed into the form is
    not a second email for the record, and the registration form never sends one that
    differs.
    """
    values = mapping.values_by_key(list(proposal.fields))
    values["email"] = identity.email_entered
    return values


def classify(matched_on: list[str]) -> str:
    """Turn the existing service's ``matched_on`` list into a classification.

    Derived, never a second scoring rule. An email match is the strongest signal the CRM
    has that two records are one party, so it is ``exact``; a phone or name match without
    it is ``probable``, because families share a phone and names repeat -- which is the
    reason `duplicate_service` refuses to merge anything automatically in the first place.
    """
    if "email" in matched_on:
        return DuplicateClassification.EXACT.value
    if matched_on:
        return DuplicateClassification.PROBABLE.value
    return DuplicateClassification.NONE.value


def duplicate_candidates(
    db: Session, identity: CustomerIdentity, proposal: CustomerDataProposal
) -> list[DuplicateCandidateRow]:
    """Candidates for this proposal, from the **existing** duplicate service.

    The proposal's submitted name, email and phone go in; the same scoring every other
    surface uses comes out. There is no Customer Account duplicate rule, no Customer
    Account weighting and no Customer Account threshold, which is what makes "the same
    customer" mean the same thing here as it does on an import or in the Staff Portal
    (`IDENTITY_AND_AUTHORIZATION.md` section 6).
    """
    entered = effective_values(identity, proposal)
    name = entered.get("legal_name") or entered.get("primary_contact_name")
    candidates = duplicate_service.find_duplicate_candidates(
        db,
        full_name=name,
        email=entered.get("email"),
        phone=entered.get("phone"),
        country_code=entered.get("phone_country_code"),
        limit=DUPLICATE_CANDIDATE_LIMIT,
    )

    linked_customer_ids = set(
        db.scalars(
            select(CustomerIdentityLink.customer_id).where(
                CustomerIdentityLink.status == LinkStatus.ACTIVE.value
            )
        ).all()
    )
    # A link held by a deactivated account can be taken over by an approval (owner decision,
    # 2026-10-15), so it is shown and does not make the candidate unlinkable.
    takeover_customer_ids = set(
        db.scalars(
            select(CustomerIdentityLink.customer_id)
            .join(CustomerIdentity, CustomerIdentity.id == CustomerIdentityLink.identity_id)
            .where(
                CustomerIdentityLink.status == LinkStatus.ACTIVE.value,
                CustomerIdentity.status == IdentityStatus.DEACTIVATED.value,
            )
        ).all()
    )

    rows: list[DuplicateCandidateRow] = []
    for candidate in candidates:
        customer = candidate.customer
        is_merged = customer.merged_into_customer_id is not None
        has_link = customer.id in linked_customer_ids
        rows.append(
            DuplicateCandidateRow(
                customer_public_id=customer.public_id,
                full_name=customer.full_name,
                display_name=customer.display_name,
                city=customer.city,
                country_code=customer.country_code,
                matched_on=list(candidate.matched_on),
                confidence=candidate.confidence,
                is_archived=customer.is_archived,
                is_merged=is_merged,
                has_active_identity_link=has_link,
                linkable=not (
                    is_merged
                    or customer.is_archived
                    or (has_link and customer.id not in takeover_customer_ids)
                ),
            )
        )
    return rows


def classification_for(candidates: list[DuplicateCandidateRow]) -> str:
    """The strongest classification across the candidate set."""
    classifications = {classify(row.matched_on) for row in candidates}
    if DuplicateClassification.EXACT.value in classifications:
        return DuplicateClassification.EXACT.value
    if DuplicateClassification.PROBABLE.value in classifications:
        return DuplicateClassification.PROBABLE.value
    return DuplicateClassification.NONE.value


# --- Link targets -------------------------------------------------------------


def resolve_link_target(db: Session, customer_public_id: str) -> Customer:
    """Find the customer a reviewer named, and refuse the ones that must not be linked.

    A **merged** id is refused rather than followed. The alias chain exists and this
    function reads it, but only to tell the reviewer which record survived: silently
    retargeting the link would mean the account was linked to a customer nobody selected,
    which is exactly the implicit closest-match selection OD-28 forbids.

    An **archived** customer is refused because archiving is how this CRM says "stop using
    this record", and handing it an account holder would restart it by the back door.

    A customer that **already has an active identity** is refused by this check and again
    by the partial unique index, which is the one that wins a race (OD-25).
    """
    reference = customer_public_id.strip().upper()
    customer = db.scalar(select(Customer).where(Customer.public_id == reference))
    if customer is None:
        # An alias is a former public id retained after a merge. Resolving it here turns
        # "no such customer" into "that record was merged, here is the one to use".
        from app.models import CustomerIdAlias

        alias = db.scalar(
            select(CustomerIdAlias).where(CustomerIdAlias.alias_public_id == reference)
        )
        if alias is not None:
            survivor = db.get(Customer, alias.customer_id)
            raise ConflictError(
                f"{reference} was merged. Select {survivor.public_id} explicitly if that "
                "is the right record.",
                field="customer_public_id",
            )
        raise NotFoundError("No customer with that reference.")

    if customer.merged_into_customer_id is not None:
        survivor = db.get(Customer, customer.merged_into_customer_id)
        surviving_reference = survivor.public_id if survivor else "the surviving record"
        raise ConflictError(
            f"{reference} was merged into {surviving_reference}. Select that record "
            "explicitly if it is the right one.",
            field="customer_public_id",
        )
    if customer.is_archived:
        raise ConflictError(
            f"{reference} is archived and cannot be linked to an account.",
            field="customer_public_id",
        )
    return customer


def active_link_for_customer(db: Session, customer_id: int) -> CustomerIdentityLink | None:
    return db.scalar(
        select(CustomerIdentityLink).where(
            CustomerIdentityLink.customer_id == customer_id,
            CustomerIdentityLink.status == LinkStatus.ACTIVE.value,
        )
    )


def deactivated_link_for_customer(
    db: Session, customer_id: int
) -> tuple[CustomerIdentityLink, CustomerIdentity] | None:
    """The customer's active link, when the account holding it is **deactivated**.

    The one link an approval may end (owner decision, 2026-10-15): deactivation is terminal,
    so the old account can never use the link again, and a new registration may take the
    customer over -- by a staff approval, never by itself. A link held by an active or
    suspended account is not returned, and still refuses a second link.
    """
    row = db.execute(
        select(CustomerIdentityLink, CustomerIdentity)
        .join(CustomerIdentity, CustomerIdentity.id == CustomerIdentityLink.identity_id)
        .where(
            CustomerIdentityLink.customer_id == customer_id,
            CustomerIdentityLink.status == LinkStatus.ACTIVE.value,
            CustomerIdentity.status == IdentityStatus.DEACTIVATED.value,
        )
    ).first()
    return (row[0], row[1]) if row is not None else None


def sign_in_email_change(
    identity: CustomerIdentity, customer: Customer
) -> dict[str, str | None] | None:
    """What a link would do to the customer's email under the single email rule.

    ``None`` when the record already holds the account's address (compared normalized).
    Otherwise the current and the new value, as entered, for the reviewer to read before
    confirming -- the approval then writes the new one.
    """
    if customer.email_normalized == identity.email_normalized:
        return None
    return {"current": customer.email_entered, "new": identity.email_entered}


def active_link_for_identity(db: Session, identity_id: int) -> CustomerIdentityLink | None:
    return db.scalar(
        select(CustomerIdentityLink).where(
            CustomerIdentityLink.identity_id == identity_id,
            CustomerIdentityLink.status == LinkStatus.ACTIVE.value,
        )
    )


# --- The preview --------------------------------------------------------------


def _fingerprint_parts(
    db: Session,
    *,
    identity: CustomerIdentity,
    proposal: CustomerDataProposal,
    action: str,
    target: Customer | None,
    classification: str,
    candidate_references: list[str],
    summary: DisclosureSummary,
    identity_linked: bool,
    target_linked: bool,
    ends_link_of: str | None = None,
) -> list[str]:
    """Every fact that, if it changed, makes an earlier decision the wrong decision.

    This list *is* the definition of drift. Each entry answers a specific way the world
    can move under a reviewer between reading a preview and pressing approve:

    * ``identity`` and its status -- another staff member approved or rejected it first;
    * the proposal id and a digest of its rows -- the applicant submitted a replacement;
    * the action -- the reviewer acknowledged a create and is now attempting a link;
    * the target, its ``updated_at``, its merge and archive state, **the reference of the
      record that is canonical for it**, and its mapped values -- somebody edited, merged
      or archived the customer;
    * the classification and the candidate set -- a new customer now matches, or the one
      that did has gone;
    * the five disclosure figures -- a shipment was booked, cancelled or rebooked;
    * both link states -- another identity was linked to this customer, or this identity
      was linked elsewhere.

    ``mapping_version`` is in here too, so a deployment that changes where a field lands
    invalidates outstanding acknowledgements instead of applying the new mapping to a
    decision taken under the old one.
    """
    field_rows = sorted(
        f"{row.field_key}={row.proposed_value or ''}|{row.proposed_value_normalized or ''}"
        for row in proposal.fields
    )
    # The login address is part of what would be applied, so it is part of what must not
    # have moved. It cannot change in this release; it is covered anyway rather than
    # relying on that staying true.
    field_rows.append(f"identity_email={identity.email_normalized}")
    parts = [
        f"mapping={mapping.FIELD_MAPPING_VERSION}",
        f"identity={identity.public_id}",
        f"identity_status={identity.status}",
        f"identity_linked={int(identity_linked)}",
        f"proposal={proposal.id}",
        f"proposal_status={proposal.status}",
        f"fields={compute_fingerprint(field_rows)}",
        f"action={action}",
        f"classification={classification}",
        f"candidates={','.join(sorted(candidate_references))}",
        f"target_linked={int(target_linked)}",
        # Whose deactivated link the approval would end. The deactivation itself moves it.
        f"ends_link_of={ends_link_of or ''}",
    ]
    if target is None:
        parts.append("target=")
    else:
        snapshot = mapping.canonical_snapshot(target)
        parts.extend(
            [
                f"target={target.public_id}",
                f"target_updated={target.updated_at.isoformat() if target.updated_at else ''}",
                f"target_merged={target.merged_into_customer_id or ''}",
                # The record that is *canonical* for the one the reviewer named. Equal to
                # the target's own reference while nothing has merged, and different the
                # moment something has -- which is the fact OD-40 makes material: a
                # preview read against a record that has since become a former identity
                # for another one is a preview of a relationship that no longer exists.
                # By reference rather than by row id, so the fingerprint's inputs stay
                # things a person could be shown.
                f"target_canonical={_canonical_reference(db, target)}",
                f"target_archived={int(target.is_archived)}",
                "target_values="
                + compute_fingerprint(
                    [f"{column}={snapshot[column] or ''}" for column in mapping.CUSTOMER_COLUMNS]
                ),
            ]
        )
    parts.extend(summary.fingerprint_parts())
    return parts


def _canonical_reference(db: Session, customer: Customer) -> str:
    """The public reference of the record that is canonical for this one.

    Its own, unless it has been merged, in which case the survivor's. Follows the chain
    through ``customer_service`` rather than reading ``merged_into_customer_id`` once, so a
    two-step merge resolves the same way a staff lookup of the old reference would.
    """
    if customer.merged_into_customer_id is None:
        return customer.public_id
    from app.services import customer_service

    survivor = customer_service.get_customer_by_public_id(db, customer.public_id)
    return survivor.public_id if survivor is not None else ""


def build_preview(
    db: Session,
    *,
    identity: CustomerIdentity,
    proposal: CustomerDataProposal,
    action: str,
    target: Customer | None,
) -> ApprovalPreview:
    """Compute the whole preview, server-side, from the database and nothing else.

    No figure here comes from a request body. The action and the target reference do --
    they are the reviewer's intent -- and everything the intent implies is looked up
    again. A browser that sent a count, a date range, a classification or an ownership
    claim would be sending a value this function overwrites.
    """
    entered = effective_values(identity, proposal)

    refusal: str | None = None
    try:
        proposed = mapping.proposed_snapshot(entered)
    except mapping.MappingRefused as exc:
        proposed = dict.fromkeys(mapping.CUSTOMER_COLUMNS)
        refusal = exc.message

    candidates = duplicate_candidates(db, identity, proposal)
    classification = classification_for(candidates)

    email_change: dict[str, str | None] | None = None
    ends_link_of: str | None = None
    if target is None:
        current = None
        summary = disclosure.empty()
        target_linked = False
    else:
        current = mapping.canonical_snapshot(target)
        summary = disclosure.summarize(db, target.id)
        target_linked = active_link_for_customer(db, target.id) is not None
        email_change = sign_in_email_change(identity, target)
        takeover = deactivated_link_for_customer(db, target.id)
        ends_link_of = takeover[1].public_id if takeover is not None else None

    return ApprovalPreview(
        account_reference=identity.public_id,
        action=action,
        proposal_id=proposal.id,
        proposed=proposed,
        current=current,
        differences=mapping.differences(proposed, current) if current is not None else [],
        duplicate_classification=classification,
        candidate_references=[row.customer_public_id for row in candidates],
        target_customer_public_id=target.public_id if target else None,
        disclosure=summary,
        fingerprint=compute_fingerprint(
            _fingerprint_parts(
                db,
                identity=identity,
                proposal=proposal,
                action=action,
                target=target,
                classification=classification,
                candidate_references=[row.customer_public_id for row in candidates],
                summary=summary,
                identity_linked=active_link_for_identity(db, identity.id) is not None,
                target_linked=target_linked,
                ends_link_of=ends_link_of,
            )
        ),
        mapping_refusal=refusal,
        email_change=email_change,
        ends_link_of=ends_link_of,
    )


def preview_for(
    db: Session,
    *,
    identity: CustomerIdentity,
    action: str,
    customer_public_id: str | None,
) -> tuple[ApprovalPreview, CustomerDataProposal, Customer | None]:
    """Validate the requested action, resolve the target, and build the preview."""
    if action not in {member.value for member in ApprovalAction}:
        raise ValidationError("Choose create_new or link_existing.", field="action")
    proposal = current_proposal(db, identity)

    target: Customer | None = None
    if action == ApprovalAction.LINK_EXISTING.value:
        if not customer_public_id:
            raise ValidationError(
                "Linking needs the customer you intend to link to. There is no automatic "
                "closest match.",
                field="customer_public_id",
            )
        target = resolve_link_target(db, customer_public_id)
    elif customer_public_id:
        raise ValidationError(
            "A create_new preview takes no customer reference.", field="customer_public_id"
        )

    return (
        build_preview(db, identity=identity, proposal=proposal, action=action, target=target),
        (proposal),
        target,
    )


# --- The acknowledgement ------------------------------------------------------


def acknowledge(
    db: Session,
    *,
    identity: CustomerIdentity,
    preview: ApprovalPreview,
    proposal: CustomerDataProposal,
    target: Customer | None,
    actor: User,
    ip_address: str | None,
) -> CustomerAccountDisclosureAcknowledgement:
    """Record that this actor saw these figures for this intended action.

    The row stores the figures, not a boolean, because the approval that reads it happens
    in a later request against a world that may have moved. Storing "yes" would record
    that somebody clicked; storing the figures and the fingerprint records **what they
    agreed to**, which is the thing OD-29 is actually asking for.
    """
    row = CustomerAccountDisclosureAcknowledgement(
        identity_id=identity.id,
        proposal_id=proposal.id,
        action=preview.action,
        customer_id=target.id if target else None,
        acknowledged_by_user_id=actor.id,
        acknowledged_at=utcnow(),
        disclosed_shipment_count=preview.disclosure.shipment_count,
        oldest_booked_at=preview.disclosure.oldest_booked_at,
        newest_booked_at=preview.disclosure.newest_booked_at,
        includes_cancelled=preview.disclosure.includes_cancelled,
        includes_rebooked=preview.disclosure.includes_rebooked,
        disclosure_definition_version=preview.disclosure.definition_version,
        preview_fingerprint=preview.fingerprint,
    )
    db.add(row)
    db.flush()
    audit.disclosure_acknowledged(
        db,
        identity=identity,
        actor=actor,
        action=preview.action,
        customer_public_id=target.public_id if target else None,
        summary_detail=preview.disclosure.as_audit_detail(),
        fingerprint=preview.fingerprint,
        ip_address=ip_address,
    )
    return row


def find_acknowledgement(
    db: Session, *, identity: CustomerIdentity, fingerprint_value: str
) -> CustomerAccountDisclosureAcknowledgement | None:
    """The acknowledgement matching a recomputed fingerprint, if one exists.

    Not filtered by actor. OD-24 makes approval an Operations or Admin act, not a
    two-person one, and requiring the same person to acknowledge and approve would be a
    control this project has not been asked for -- while silently making a handover
    between two authorized reviewers fail. The actor of each act is audited separately.
    """
    return db.scalar(
        select(CustomerAccountDisclosureAcknowledgement)
        .where(
            CustomerAccountDisclosureAcknowledgement.identity_id == identity.id,
            CustomerAccountDisclosureAcknowledgement.preview_fingerprint == fingerprint_value,
        )
        .order_by(CustomerAccountDisclosureAcknowledgement.id.desc())
    )
