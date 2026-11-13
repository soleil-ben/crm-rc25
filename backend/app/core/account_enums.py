"""Vocabularies for the Customer Account surface.

Deliberately a separate module from ``app.core.enums``. That module is the Staff Portal
and Public Tracking vocabulary; a customer identity state has nothing to do with a staff
role, and putting the two in one namespace is the first step toward somebody writing
``Role.CUSTOMER`` because it was already imported (OD-23, DEC-0090).

Every value here is a state a *document* names. A value nobody wrote down does not exist:
`docs/customer_account/STATE_MACHINES.md` is the authority for the identity lifecycle and
the proposal lifecycle, and `docs/customer_account/DATA_MODEL.md` for the rest.
"""

from __future__ import annotations

from enum import StrEnum


class IdentityStatus(StrEnum):
    """The identity lifecycle of ``STATE_MACHINES.md`` §1.

    Only ``PENDING_APPROVAL`` and ``ACTIVE`` may authenticate, and only ``ACTIVE`` plus an
    active link ever reaches shipment data -- which nothing in Phase 9 serves.
    """

    #: Registered, mailbox control not yet proven. Cannot sign in.
    PENDING_VERIFICATION = "pending_verification"
    #: Mailbox proven, waiting for a person. Signs in; sees account state and nothing else.
    PENDING_APPROVAL = "pending_approval"
    #: Approved and linked by staff. **Phase 9 never writes this value.**
    ACTIVE = "active"
    #: Application declined by staff. Cannot sign in.
    REJECTED = "rejected"
    #: Suspended by staff. Cannot sign in; refusal is the generic one.
    SUSPENDED = "suspended"
    #: Deactivated by staff, including on a privacy request. Cannot sign in.
    DEACTIVATED = "deactivated"


#: States in which a correct password opens a session. Everything else is refused with the
#: same generic message, so the refusal does not say which state the account is in.
AUTHENTICATABLE_STATUSES = frozenset({IdentityStatus.PENDING_APPROVAL, IdentityStatus.ACTIVE})


class LinkStatus(StrEnum):
    ACTIVE = "active"
    REVOKED = "revoked"


class LinkRole(StrEnum):
    """Release 1 writes only ``OWNER``.

    ``MEMBER`` and ``ADMIN`` are where company access lands later (OD-26). They are named
    now because OD-25 requires that relaxing the release-1 rule later must not mean
    rebuilding identity ownership -- and a role column with one legal value is a column
    somebody would later replace rather than extend.
    """

    OWNER = "owner"
    MEMBER = "member"
    ADMIN = "admin"


class TokenPurpose(StrEnum):
    """What a ``customer_auth_tokens`` row may be redeemed for.

    The purpose is mixed into the digest as well as stored in a column, so a verification
    token cannot be presented to the reset endpoint even if a query forgot to filter on
    it (``THREAT_MODEL.md`` T-05).
    """

    EMAIL_VERIFICATION = "email_verification"
    PASSWORD_RESET = "password_reset"
    #: RC-UAT-21 (DEC-0231): proves control of the **new** address of a self-service email
    #: change. Issued to that address; valid for the OD-36 verification period.
    EMAIL_CHANGE = "email_change"


class ProposalKind(StrEnum):
    REGISTRATION = "registration"
    PROFILE_UPDATE = "profile_update"


class ProposalStatus(StrEnum):
    """``STATE_MACHINES.md`` §4. Phase 9 writes only ``PENDING`` and ``SUPERSEDED``."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"
    WITHDRAWN = "withdrawn"


class TermsDocumentKind(StrEnum):
    TERMS = "terms"
    PRIVACY = "privacy"


class NotificationChannel(StrEnum):
    #: The only channel in release 1. Named rather than assumed so a second one is a
    #: decision rather than a string appearing in a service.
    EMAIL = "email"


class NotificationTopic(StrEnum):
    """Operational topics only. Marketing is a ``consent_events`` row, never a topic here."""

    SHIPMENT_MILESTONES = "shipment_milestones"
    DELIVERY_OUTCOME = "delivery_outcome"
    ACCOUNT_SECURITY = "account_security"


#: Topics a customer may switch off. ``ACCOUNT_SECURITY`` is deliberately absent: a
#: verification or password-reset message is what makes the account recoverable, and a
#: preference that could suppress it would be a preference that locks people out
#: (`EMAIL_DELIVERY.md` §4, OD-38).
CUSTOMER_SETTABLE_TOPICS = frozenset(
    {NotificationTopic.SHIPMENT_MILESTONES, NotificationTopic.DELIVERY_OUTCOME}
)


class RegistrationOutcome(StrEnum):
    """What a registration attempt did, for the idempotency row and the audit reason code.

    **Never serialized to the caller.** Every one of these produces the identical generic
    response; the distinction exists for the audit log and for the tests that prove the
    responses really are identical (``THREAT_MODEL.md`` T-02).
    """

    #: A new identity and a new proposal were created.
    CREATED = "created"
    #: The address already has an identity. Nothing was created; a notice may have been
    #: sent to the existing address instead.
    EXISTING_ADDRESS = "existing_address"
    #: A rate limit refused the work. The response is unchanged.
    THROTTLED = "throttled"
    #: The same idempotency key had already been claimed by an equivalent request.
    REPLAYED = "replayed"
    #: Written before UAT round 6, when a suppression refused registration outright. No
    #: longer produced: a suppression blocks marketing email only (owner decision,
    #: 2026-10-15). Kept so the rows already written still read, and so a replay of one
    #: can be recognised and given the registration it was refused.
    SUPPRESSED = "suppressed"


#: The same set as string values, for a boundary check that compares against submitted text
#: rather than against enum members.
CUSTOMER_SETTABLE_TOPIC_VALUES = frozenset(topic.value for topic in CUSTOMER_SETTABLE_TOPICS)


class ApprovalAction(StrEnum):
    """What a staff reviewer intends to do with a pending registration.

    Two actions, and the difference between them is the difference between writing
    canonical data and not writing it. ``CREATE_NEW`` creates a ``customers`` row from the
    proposal; ``LINK_EXISTING`` writes no canonical customer value at all (OD-28).

    The action is part of the preview fingerprint and part of the idempotency
    fingerprint, so one key reused for the other action is a conflict rather than a
    replay.
    """

    CREATE_NEW = "create_new"
    LINK_EXISTING = "link_existing"


class DuplicateClassification(StrEnum):
    """The staff-facing result of the **existing** duplicate review, never a new rule.

    Derived from ``duplicate_service``'s ``matched_on`` list and nothing else: an email
    match is ``EXACT``, a phone or name match without an email match is ``PROBABLE``, no
    candidate at all is ``NONE``. **Never serialized to a customer** -- a classification is
    a statement that another record exists (T-02).
    """

    EXACT = "exact"
    PROBABLE = "probable"
    NONE = "none"


#: Classifications that make creating a *separate* customer a decision rather than a
#: default. Creating one anyway requires an explicit bounded override reason code (OD-28).
CLASSIFICATIONS_REQUIRING_OVERRIDE = frozenset(
    {DuplicateClassification.EXACT, DuplicateClassification.PROBABLE}
)


class SeparateCustomerReason(StrEnum):
    """Why a reviewer created a new customer despite a candidate. A closed vocabulary.

    Bounded rather than free text for the reason every other reason code here is bounded:
    a sentence about a person ends up in an audit payload, and an audit payload is read by
    people who were not in the conversation. Three codes cover the three real answers, and
    a fourth would be a decision to add here.
    """

    #: Same or similar name, established as a different person or business.
    DIFFERENT_PARTY = "different_party"
    #: The candidate is stale, archived-in-spirit, or otherwise not the record to use.
    CANDIDATE_NOT_USABLE = "candidate_not_usable"
    #: The match is on a shared household or company contact detail only.
    SHARED_CONTACT_DETAIL = "shared_contact_detail"


class RejectionReason(StrEnum):
    """Why an application was declined. Bounded, and **never shown to the customer**.

    `STATE_MACHINES.md` section 1 transition 5: the customer sees a neutral statement that
    the account cannot be used, and "no reason that describes another record". These codes
    exist for the audit trail and for the staff who read it.
    """

    #: The submitted details do not identify a party Solaris can serve.
    UNVERIFIABLE_DETAILS = "unverifiable_details"
    #: Duplicate of an application already decided.
    DUPLICATE_APPLICATION = "duplicate_application"
    #: The applicant is not the customer they claim to be, or the claim cannot be checked.
    IDENTITY_NOT_ESTABLISHED = "identity_not_established"
    #: An operational restriction applies to this party.
    SERVICE_RESTRICTION = "service_restriction"
    #: Abuse, automation or a test submission.
    ABUSE_OR_TEST = "abuse_or_test"


class ApprovalOutcome(StrEnum):
    """What an approval attempt did. Internal; the reason code on the attempt row.

    ``REPLAYED`` is a success from the caller's point of view and writes nothing: the
    idempotency key had already been claimed by an equivalent request, so the original
    outcome is reported again (`STATE_MACHINES.md` section 3, "Idempotent").
    """

    APPROVED_CREATED = "approved_created"
    APPROVED_LINKED = "approved_linked"
    REJECTED = "rejected"
    REPLAYED = "replayed"
    CONFLICT = "conflict"
