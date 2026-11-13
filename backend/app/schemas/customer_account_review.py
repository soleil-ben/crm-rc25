"""Staff-facing request and response models for Customer Account review. Phase 10.

These are **staff** schemas -- the caller is an authenticated Operations or Admin user, not
a customer -- and they still obey the four rules `app/schemas/account.py` sets out, for a
reason that is not symmetry:

* **inherit from nothing.** Not from ``ApiModel``, which sets ``from_attributes=True``, and
  not from any staff customer or shipment schema. A model that inherits one gains its
  fields the day somebody adds one.
* **``from_attributes=False``**, so a ``Customer``, a ``CustomerIdentity``, a
  ``CustomerDataProposal`` or a ``Shipment`` can never be handed to one of these and
  serialized wholesale. Every value below is assigned by a route, by name.
* **``extra="forbid"``**, so a field a service starts returning is an error rather than a
  disclosure.
* every response is an **allowlist**, and the list is short on purpose.

What is deliberately absent from every model here: a password hash; a verification, reset
or session token or any digest of one; a CSRF value; a raw captured message; internal
limiter state; any customer that is not a duplicate candidate for this proposal; any
shipment reference, package, event, recipient or financial value; any integration
credential or state; any internal row id except the proposal's, which is opaque and
appears because a reviewer needs to know which submission they are looking at.

The disclosure figures **are** here -- a count and two dates -- and they are the one place
this phase publishes a number about shipments. They are staff-facing only; no Customer
Account route returns any of them, which `tests/test_account_privacy.py` asserts.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ReviewModel(BaseModel):
    """Base for every model in this module. Forbidding, and never ORM-populated."""

    model_config = ConfigDict(from_attributes=False, extra="forbid")


# --- Responses ----------------------------------------------------------------


class PendingRegistrationRow(ReviewModel):
    """One line of the queue. No contact detail of any kind.

    A reviewer chooses a row and opens it; the list itself is not a place to read who has
    applied. Six fields, and ``field_count`` is there so a reviewer can see at a glance
    that a submission is substantial without the submission being on the page.
    """

    account_reference: str
    status: str
    submitted_at: datetime
    email_verified_at: datetime | None
    proposal_id: int
    field_count: int


class PendingRegistrationPage(ReviewModel):
    """A bounded page. ``limit`` and ``offset`` are echoed back as the server applied them."""

    items: list[PendingRegistrationRow]
    total: int
    limit: int
    offset: int


class ProposalFieldOut(ReviewModel):
    """One submitted field, as typed and as normalized.

    Both forms, because OD-28 requires the approver to see "the proposed value" and "the
    normalized value where relevant" -- and because the normalized form is what duplicate
    review compared, so a reviewer wondering why something matched needs to see it.

    ``applied`` is false for every field of a pending proposal and stays false for every
    field of a link-existing approval. It is not decoration: it is how the record says
    whether canonical data actually moved.
    """

    field_key: str
    value_type: str
    proposed_value: str | None
    proposed_value_normalized: str | None
    applied: bool


class PendingRegistrationDetail(ReviewModel):
    """One application, in full, and nothing about any other record.

    No duplicate result here. Duplicates are their own request and their own audit action,
    because looking at an application and looking at other people's records next to it are
    two different accesses and the log should be able to tell them apart.
    """

    account_reference: str
    status: str
    #: The applicant's login address, entered and normalized. It is **not** a proposal
    #: field row: a registration supplies its address once, at the top level, and Phase 9
    #: stores it on the identity. It is published here because it is part of the
    #: application a reviewer is deciding about, and because it is the address an approval
    #: would put on the customer record (`FIELD_MATRIX.md` section 2).
    account_email_entered: str
    account_email_normalized: str
    email_verified_at: datetime | None
    preferred_language: str
    submitted_at: datetime
    proposal_id: int
    proposal_status: str
    fields: list[ProposalFieldOut]
    #: Whether this identity already holds an active link. Always false for a reviewable
    #: application; present so a reviewer reading a decided one sees why it is decided.
    has_active_link: bool


class DuplicateCandidateOut(ReviewModel):
    """A candidate customer, with only what a linking decision needs.

    Name, preferred name, coarse location, why it matched, how confidently, and whether it
    can be linked at all. **Not** its email, phone or address: the reviewer is deciding
    whether this is the same party, and the match reasons already say which fields agreed
    without reprinting the other person's contact details onto the screen.
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


class DuplicateReviewOut(ReviewModel):
    account_reference: str
    duplicate_classification: str
    candidates: list[DuplicateCandidateOut]


class DisclosureOut(ReviewModel):
    """The five OD-29 figures, and the version of the rule that produced them.

    A count and two dates. There is no shipment reference here, no package, no event, no
    recipient and no money -- and no code path that could add one, because the calculation
    never loads a shipment row.

    ``definition_version`` is published rather than kept internal so that a reviewer's
    acknowledgement is an acknowledgement of a *stated* rule, and so a later change to the
    rule is visible in the record rather than only in a migration note.
    """

    shipment_count: int
    oldest_booked_at: datetime | None
    newest_booked_at: datetime | None
    includes_cancelled: bool
    includes_rebooked: bool
    definition_version: str


class FieldDifferenceOut(ReviewModel):
    """One canonical column where the proposal and the customer disagree.

    Reported, never applied. A link-existing approval writes no canonical value, so this
    is a record for the reviewer and for Phase 12 change-proposal handling (OD-28).
    """

    field: str
    proposed: str | None
    current: str | None


class ApprovalPreviewOut(ReviewModel):
    """Everything the server calculated, plus the fingerprint approval is checked against.

    ``fingerprint`` is not a credential. It is a digest over the facts below, and the
    reviewer's client sends it back so the server can prove those facts have not moved. A
    stale one produces a ``409``; a forged one matches no recomputed value and produces
    the same ``409``.
    """

    account_reference: str
    action: str
    proposal_id: int
    proposed: dict[str, str | None]
    current: dict[str, str | None] | None
    differences: list[FieldDifferenceOut]
    duplicate_classification: str
    candidate_references: list[str]
    target_customer_public_id: str | None
    disclosure: DisclosureOut
    fingerprint: str
    #: Why an approval would be refused, when the proposal cannot become a customer at all.
    #: Present so a reviewer reads the reason instead of discovering it by pressing approve.
    mapping_refusal: str | None
    #: Link-existing: the record's email becomes the account's sign-in email (single email
    #: rule, owner decision 2026-10-15). ``{"current", "new"}``, or null when they agree.
    email_change: dict[str, str | None] | None = None
    #: Link-existing: the deactivated account whose link this approval ends, or null.
    ends_link_of: str | None = None


class DecisionOut(ReviewModel):
    """What a decision did.

    ``replayed`` is true when an idempotency key arrived a second time. The outcome is the
    original one and nothing was written again -- reporting success without saying it was
    a replay would make a retry indistinguishable from a second approval.
    """

    account_reference: str
    status: str
    customer_public_id: str | None
    outcome: str
    replayed: bool


class AcknowledgementOut(ReviewModel):
    """Confirmation that the disclosure was acknowledged, echoing what was acknowledged."""

    account_reference: str
    action: str
    target_customer_public_id: str | None
    disclosure: DisclosureOut
    fingerprint: str
    acknowledged_at: datetime


# --- Requests -----------------------------------------------------------------


class AcknowledgeDisclosureRequest(ReviewModel):
    """Acknowledge a preview by its fingerprint.

    The fingerprint is required and is re-derived server-side before the row is written,
    so acknowledging a preview the client made up acknowledges nothing.
    """

    action: str = Field(max_length=20)
    customer_public_id: str | None = Field(default=None, max_length=20)
    fingerprint: str = Field(max_length=64)


class ApproveCreateNewRequest(ReviewModel):
    """Approve by creating a new canonical customer.

    ``override_reason_code`` is required when a duplicate candidate exists and refused
    when none does. A bounded code, never prose: the reason goes into an audit payload
    that other people read (OD-28).
    """

    preview_fingerprint: str = Field(max_length=64)
    idempotency_key: str = Field(max_length=120)
    override_reason_code: str | None = Field(default=None, max_length=40)


class ApproveLinkExistingRequest(ReviewModel):
    """Approve by linking to a customer the reviewer names.

    ``customer_public_id`` is required. There is no "closest match", no default and no
    inference: OD-28 forbids an implicit selection, so the absence of this field is a
    refusal rather than a prompt for the server to choose.
    """

    customer_public_id: str = Field(max_length=20)
    preview_fingerprint: str = Field(max_length=64)
    idempotency_key: str = Field(max_length=120)


class RejectRegistrationRequest(ReviewModel):
    """Decline an application.

    ``internal_detail`` is accepted and bounded but **not retained** in this release: the
    existing audit redaction rules keep prose about a person out of the audit trail, and
    there is no other reviewed store for it. The field stays in the contract so the shape
    does not change when one exists; the route says so in its response documentation.
    """

    reason_code: str = Field(max_length=40)
    idempotency_key: str = Field(max_length=120)
    internal_detail: str | None = Field(default=None, max_length=500)


# --- Identity lifecycle (Sprint 13 Lane A, item A-1; fix pack of 2026-10-14) -----------

#: Bounded reason codes, never prose. The codes are what the audit row records and what
#: the Staff Portal offers; a sentence about a person would be a sentence in the log.
SUSPEND_REASON_CODES: tuple[str, ...] = (
    "security_concern",
    "customer_request",
    "staff_review",
    "abuse_or_test",
)
REINSTATE_REASON_CODES: tuple[str, ...] = (
    "review_complete",
    "customer_request",
    "suspended_in_error",
)
#: Deactivation is Admin-only and permanent for the account (DEC-0126, DEC-0131).
DEACTIVATE_REASON_CODES: tuple[str, ...] = (
    "customer_request",
    "privacy_request",
    "security_concern",
    "duplicate_account",
    "abuse_or_test",
)


class IdentityStatusChangeRequest(ReviewModel):
    """Suspend, reinstate or deactivate a Customer Account. One bounded code, nothing else."""

    reason_code: str = Field(max_length=40)


class IdentityStatusOut(ReviewModel):
    """An account's lifecycle state, for the staff screen that may change it.

    No proposal fields, no shipment data, no password material. ``linked_customer_public_id``
    is the one cross-reference a staff member needs to find the customer record; it is a
    staff-facing value and never reaches the account holder.
    """

    account_reference: str
    status: str
    status_reason_code: str | None
    account_email_entered: str
    email_verified: bool
    approved_at: datetime | None
    suspended_at: datetime | None
    deactivated_at: datetime | None = None
    linked_customer_public_id: str | None
    can_suspend: bool
    can_reinstate: bool
    #: The account's state allows deactivation. Whether the *caller* may is the
    #: ``customer_account:deactivate`` permission, which only Admin holds.
    can_deactivate: bool = False
    #: RC-UAT-21 (DEC-0231): the account is deactivated and the deactivation is reversible.
    #: Whether the *caller* may is the same Admin-only permission as deactivation.
    can_reactivate: bool = False
    #: RC-UAT-25 item 2: the account's status lets an Admin change its sign-in email
    #: (pending approval, active, suspended). Whether the *caller* may is the same Admin-only
    #: permission as deactivation.
    can_change_sign_in_email: bool = False


class IdentitySignInEmailChangeRequest(ReviewModel):
    """An Admin changes the sign-in email (RC-UAT-25 item 2): the new address, a bounded
    reason code, and an optional short note kept on the change row (never in the audit)."""

    new_email: str = Field(max_length=320)
    reason_code: str = Field(max_length=40)
    note: str | None = Field(default=None, max_length=500)


class IdentityReactivateRequest(ReviewModel):
    """Reinstate a deactivated account (RC-UAT-21, DEC-0231): a bounded reason code, required,
    and an optional short note kept on the reinstatement row (never in the audit payload)."""

    reason_code: str = Field(max_length=40)
    note: str | None = Field(default=None, max_length=500)


class DeactivatedAccountRow(ReviewModel):
    account_reference: str
    account_email_entered: str
    deactivated_at: datetime | None
    status_reason_code: str | None
    linked_customer_public_id: str | None
    can_reactivate: bool


class DeactivatedAccountList(ReviewModel):
    items: list[DeactivatedAccountRow]


# --- RC-UAT-22: orphaned accounts, re-link or close (B-13, DEC-0234 draft) -------------------


class OrphanedAccountRow(ReviewModel):
    """An approved account with no customer and nothing for the approval queue to decide.

    The login address is shown as the deactivated list shows it: the Admin is about to choose
    which customer record this person is. ``last_customer_public_id`` and its end reason say
    where the account was linked before; ``suggested_customer_public_id`` is the merge
    survivor (or the same record when it is still usable) -- a suggestion, never applied.
    """

    account_reference: str
    account_email_entered: str
    approved_at: datetime | None
    last_customer_public_id: str | None
    last_link_end_reason: str | None
    last_link_ended_at: datetime | None
    last_customer_merged: bool
    suggested_customer_public_id: str | None


class OrphanedAccountList(ReviewModel):
    items: list[OrphanedAccountRow]
    relink_reason_codes: list[str]
    close_reason_codes: list[str]


class RelinkPreviewOut(ReviewModel):
    """The history a re-link would open (the five OD-29 figures) and the email it would set.

    ``fingerprint`` goes back with the re-link, which is refused (409, ``preview_stale``)
    when the recomputed one differs.
    """

    account_reference: str
    target_customer_public_id: str
    disclosure: DisclosureOut
    email_change: dict[str, str | None] | None
    fingerprint: str


class RelinkRequest(ReviewModel):
    """Re-link an orphaned account. ``history_acknowledged`` must be ``true``: the approval's
    acknowledgement row needs a proposal, which an orphan does not have (stand-in B-17)."""

    customer_public_id: str = Field(max_length=20)
    reason_code: str = Field(max_length=40)
    note: str | None = Field(default=None, max_length=500)
    history_acknowledged: bool = False
    preview_fingerprint: str = Field(max_length=64)


class CloseOrphanRequest(ReviewModel):
    """Close an orphaned account (deactivated, ``orphan_closed``). A bounded code and a note."""

    reason_code: str = Field(max_length=40)
    note: str | None = Field(default=None, max_length=500)


# --- Fix pack 2: post-approval profile-change review (FIELD_MATRIX.md §5) -------------


class ProfileProposalRow(ReviewModel):
    account_reference: str
    customer_public_id: str
    submitted_at: datetime
    field_count: int
    groups: list[str]


class ProfileProposalQueue(ReviewModel):
    items: list[ProfileProposalRow]
    total: int


class ProfileReviewFieldOut(ReviewModel):
    """Proposed, current and normalized, side by side (OD-28 / FIELD_MATRIX §5)."""

    field_key: str
    group: str
    proposed_value: str | None
    proposed_value_normalized: str | None
    current_value_at_submission: str | None
    current_value_now: str | None
    drifted: bool
    applied: bool


class ProfileReviewOut(ReviewModel):
    account_reference: str
    customer_public_id: str
    status: str
    submitted_at: datetime
    reviewed_at: datetime | None
    decision_reason_code: str | None
    groups: list[str]
    fields: list[ProfileReviewFieldOut]
    decline_reason_codes: list[str]


class ProfileDecisionRequest(ReviewModel):
    #: ``{group: "approve" | "decline"}`` for every group in the request.
    decisions: dict[str, str]
    reason_code: str | None = Field(default=None, max_length=40)
