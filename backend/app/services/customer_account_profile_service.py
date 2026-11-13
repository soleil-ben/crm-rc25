"""The Customer Account profile: what a linked customer may read and change about themselves.

Fix pack 2 (UAT round 2, 2026-10-14). CA-PRF-01, -02 and -04 were blocked because no
profile existed; `DEC-0095` had deferred it. This module is `FIELD_MATRIX.md` §3 and §4
as code, and nothing more:

* **Direct** (§3.1): preferred language. Applied at once, audited, no proposal.
* **Proposal** (§3.2): legal name, display name, phone, and the pickup address. Written to
  `customer_data_proposals` as a `profile_update`; **nothing canonical changes** until an
  Operations or Admin reviewer approves it, per field group. A newer submission supersedes
  the pending one, carrying forward any field it did not resubmit (`STATE_MACHINES.md` §4).
* **Marketing consent** (§4): grant or withdraw, appended to `consent_events`, audited. A
  grant against a suppressed address is recorded as the customer's own choice and changes
  nothing about the suppression, which still decides eligibility (CA-PRF-04, DEC-0123).
  Since UAT round 3 a grant that cannot be delivered says so with one boolean,
  ``delivery_blocked``, and nothing else: never the suppression, its reason or its source.
* **Never** (§3.4): nothing in this module reads a tag, a note, an interaction, an owner,
  a lifecycle status, a financial value, a match key, a suppression record or an internal
  id into anything a customer route returns. The read model is built field by field.

Email is **not** proposable here. It is the account's own login address, and
`STATE_MACHINES.md` §6 requires a verification step before a change can land; that flow
is not built, so the field is refused by name rather than half-supported.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.account_enums import IdentityStatus, ProposalKind, ProposalStatus
from app.core.account_fields import FieldRejected, NormalizedField, normalize_field
from app.core.enums import (
    AddressRole,
    ConsentBasis,
    ConsentChannel,
    ConsentStatus,
    CustomerCategory,
    PreferredLanguage,
)
from app.core.time_utils import utcnow
from app.models import (
    ConsentEvent,
    Customer,
    CustomerAddress,
    CustomerDataProposal,
    CustomerDataProposalField,
    CustomerIdentity,
    User,
)
from app.services import consent_service, customer_address_service, customer_service
from app.services import customer_account_audit as audit
from app.services.errors import ConflictError, NotFoundError, ValidationError

# --- The field vocabulary -----------------------------------------------------------

#: Direct fields (FIELD_MATRIX §3.1). One today; operational notification preferences are
#: the other §3.1 row and have no screen in release 1.
DIRECT_FIELDS: frozenset[str] = frozenset({"preferred_language"})

#: The pickup address the profile proposes against: one address, the default sender.
_ADDRESS_PARTS = (
    "contact_name",
    "address_line1",
    "address_line2",
    "city",
    "province_state",
    "postal_code",
    "country_code",
    "phone",
    "delivery_note",
)
_ADDRESS_PREFIX = "pickup_address.1."

#: Proposal groups. A reviewer decides a **group**, because half an address is not an
#: address and a phone without its region is not a phone; every field row in the group is
#: marked `applied` together.
PROPOSAL_GROUPS: dict[str, tuple[str, ...]] = {
    "legal_name": ("legal_name",),
    "display_name": ("display_name",),
    "phone": ("phone", "phone_country_code"),
    "pickup_address": tuple(f"{_ADDRESS_PREFIX}{part}" for part in _ADDRESS_PARTS),
}

PROPOSAL_FIELDS: frozenset[str] = frozenset(
    key for keys in PROPOSAL_GROUPS.values() for key in keys
)

#: Bounded decline codes, never prose (the registration review's rule).
DECLINE_REASON_CODES: tuple[str, ...] = (
    "could_not_verify",
    "incomplete",
    "not_a_correction",
    "customer_request",
)

#: Address parts a pickup-address proposal must carry to be an address at all.
_ADDRESS_REQUIRED = ("address_line1", "city", "country_code")


def group_of(field_key: str) -> str | None:
    for group, keys in PROPOSAL_GROUPS.items():
        if field_key in keys:
            return group
    return None


# --- Reading ------------------------------------------------------------------------


def default_pickup_address(db: Session, customer: Customer) -> CustomerAddress | None:
    """The address a pickup-address proposal is a correction to."""
    rows = list(
        db.scalars(
            select(CustomerAddress)
            .where(
                CustomerAddress.customer_id == customer.id,
                CustomerAddress.is_archived.is_(False),
                CustomerAddress.role.in_([AddressRole.SENDER.value, AddressRole.BOTH.value]),
            )
            .order_by(CustomerAddress.is_default_sender.desc(), CustomerAddress.id.asc())
        ).all()
    )
    return rows[0] if rows else None


def _legal_name(customer: Customer) -> str | None:
    if customer.legal_name:
        return customer.legal_name
    if customer.category == CustomerCategory.BUSINESS.value and customer.business_name:
        return customer.business_name
    return customer.full_name


def current_values(db: Session, customer: Customer) -> dict[str, str | None]:
    """The canonical value each proposal field is a correction to. Proposal fields only."""
    values: dict[str, str | None] = {
        "legal_name": _legal_name(customer),
        "display_name": customer.display_name,
        "phone": customer.phone_entered,
        "phone_country_code": customer.phone_region,
    }
    address = default_pickup_address(db, customer)
    for part in _ADDRESS_PARTS:
        column = "phone_entered" if part == "phone" else part
        values[f"{_ADDRESS_PREFIX}{part}"] = getattr(address, column, None) if address else None
    return values


@dataclass
class MarketingState:
    #: ``granted``, ``withdrawn`` or ``not_given``. Never ``suppressed``: a customer may not
    #: learn that a suppression exists (FIELD_MATRIX §3.4, §4).
    status: str
    changed_at: datetime | None
    #: True only when the customer has opted in and marketing email still cannot be sent to
    #: the address on file. One bit, so a screen can say so plainly (UAT round 3); it never
    #: says why -- a suppression, its reason and its source stay staff-facing.
    delivery_blocked: bool = False


def _delivery_blocked(db: Session, customer: Customer, status: str) -> bool:
    """Whether an opt-in is in place that marketing email cannot honour.

    Answered by ``consent_service.marketing_eligible``, the same rule an export applies, so
    the note on the customer's screen and what staff can actually send cannot disagree.
    Always False without an opt-in: a customer who has not opted in learns nothing.
    """
    if status != "granted":
        return False
    return not consent_service.marketing_eligible(db, customer, ConsentChannel.EMAIL.value)


def marketing_state(db: Session, customer: Customer) -> MarketingState:
    state = consent_service.current_state(db, customer, ConsentChannel.EMAIL.value)
    if state.status == ConsentStatus.CONSENTED:
        status = "granted"
    elif state.status == ConsentStatus.WITHDRAWN:
        status = "withdrawn"
    else:
        # `unknown`, and also `suppressed`: a consent row a staff member recorded with the
        # suppressed status would otherwise announce the suppression.
        status = "not_given"
    changed_at = state.recorded_at if status != "not_given" else None
    return MarketingState(
        status=status,
        changed_at=changed_at,
        delivery_blocked=_delivery_blocked(db, customer, status),
    )


def marketing_history(db: Session, customer: Customer) -> list[tuple[str, datetime]]:
    """The customer's own marketing-consent history: status and time, nothing else."""
    out: list[tuple[str, datetime]] = []
    for event in consent_service.history(db, customer):
        if event.channel != ConsentChannel.EMAIL.value:
            continue
        if event.status == ConsentStatus.CONSENTED:
            out.append(("granted", event.recorded_at))
        elif event.status == ConsentStatus.WITHDRAWN:
            out.append(("withdrawn", event.recorded_at))
    return out


def own_profile_proposals(db: Session, identity: CustomerIdentity) -> list[CustomerDataProposal]:
    return list(
        db.scalars(
            select(CustomerDataProposal)
            .options(selectinload(CustomerDataProposal.fields))
            .where(
                CustomerDataProposal.identity_id == identity.id,
                CustomerDataProposal.kind == ProposalKind.PROFILE_UPDATE.value,
            )
            .order_by(CustomerDataProposal.submitted_at.desc(), CustomerDataProposal.id.desc())
            .limit(20)
        ).all()
    )


def pending_profile_proposal(
    db: Session, identity: CustomerIdentity
) -> CustomerDataProposal | None:
    return db.scalar(
        select(CustomerDataProposal)
        .options(selectinload(CustomerDataProposal.fields))
        .where(
            CustomerDataProposal.identity_id == identity.id,
            CustomerDataProposal.kind == ProposalKind.PROFILE_UPDATE.value,
            CustomerDataProposal.status == ProposalStatus.PENDING.value,
        )
        .order_by(CustomerDataProposal.id.desc())
    )


# --- Direct edit ----------------------------------------------------------------------


def _selectable_languages() -> set[str]:
    return {language.value for language in PreferredLanguage} - {"unknown"}


def account_language(identity: CustomerIdentity, customer: Customer | None) -> str:
    """The preferred language this account reports, wherever it is read.

    **One source of truth** (UAT round 3): ``customers.preferred_language`` is the field
    FIELD_MATRIX §3.1 names and the one ``update_direct`` writes, so once an account reads
    a linked customer, that is the answer for ``GET /account/me`` and ``GET
    /account/profile`` alike. The identity's own value is only the fallback -- the language
    captured at registration, for an account with no readable customer yet, or a customer
    row staff left as ``unknown``. Before this, ``/me`` read the identity and the profile
    read the customer, and a language change showed up on one and not the other.
    """
    if customer is not None and customer.preferred_language in _selectable_languages():
        return customer.preferred_language
    return identity.preferred_language


def update_direct(
    db: Session,
    *,
    identity: CustomerIdentity,
    customer: Customer,
    submitted: dict[str, Any],
    ip_address: str | None,
) -> None:
    """Apply direct fields. Any other key is refused by name (FIELD_MATRIX §7.3)."""
    if not submitted:
        raise ValidationError("Choose something to change.", field=None)
    for key in submitted:
        if key in PROPOSAL_FIELDS:
            raise ValidationError(
                "That change needs a staff review. Use the change request form.", field=key
            )
        if key not in DIRECT_FIELDS:
            raise ValidationError("That field cannot be changed here.", field=key)

    raw = submitted["preferred_language"]
    choices = _selectable_languages()
    if not isinstance(raw, str) or raw.strip().lower() not in choices:
        raise ValidationError(
            f"Choose one of: {', '.join(sorted(choices))}.", field="preferred_language"
        )
    customer.preferred_language = raw.strip().lower()
    # The account's own language follows, so its emails (password reset, approval) and the
    # screens at sign-in use the language the customer just chose (OD-71).
    if customer.preferred_language in ("vi", "en"):
        identity.preferred_language = customer.preferred_language
    db.flush()
    audit.profile_direct_updated(
        db,
        identity=identity,
        customer_public_id=customer.public_id,
        field_keys=["preferred_language"],
        ip_address=ip_address,
    )


# --- Proposals --------------------------------------------------------------------


def _normalize_submission(submitted: dict[str, Any]) -> list[NormalizedField]:
    for key in submitted:
        if not isinstance(key, str):
            raise ValidationError("That submission could not be accepted.", field=None)
        if key in DIRECT_FIELDS:
            raise ValidationError(
                "That change applies directly. Use the language setting instead.", field=key
            )
        if key not in PROPOSAL_FIELDS:
            # A never field, an unknown key, or email (not proposable until a verified
            # email-change flow exists). Refused by name: the allowlist is a property of
            # the form, not of any record, so naming the key discloses nothing.
            raise ValidationError("That field cannot be changed here.", field=key)

    context = {key: value for key, value in submitted.items() if isinstance(value, str)}
    fields: list[NormalizedField] = []
    for key, value in submitted.items():
        try:
            normalized = normalize_field(key, value, context=context)
        except FieldRejected as exc:
            raise ValidationError(exc.message, field=exc.field_key) from exc
        if normalized is not None:
            fields.append(normalized)

    if not fields:
        raise ValidationError("Enter at least one change.", field=None)

    submitted_parts = {
        item.key.removeprefix(_ADDRESS_PREFIX)
        for item in fields
        if item.key.startswith(_ADDRESS_PREFIX)
    }
    if submitted_parts:
        for part in _ADDRESS_REQUIRED:
            if part not in submitted_parts:
                raise ValidationError(
                    "A new pickup address needs a street address, a city and a country.",
                    field=f"{_ADDRESS_PREFIX}{part}",
                )
    if any(item.key == "phone_country_code" for item in fields) and not any(
        item.key == "phone" for item in fields
    ):
        raise ValidationError("Enter the phone number as well.", field="phone")
    return fields


def submit_proposal(
    db: Session,
    *,
    identity: CustomerIdentity,
    customer: Customer,
    submitted: dict[str, Any],
    ip_address: str | None,
) -> CustomerDataProposal:
    """A profile-update proposal. Writes no canonical value (FIELD_MATRIX §3.2)."""
    fields = _normalize_submission(submitted)
    now = utcnow()
    current = current_values(db, customer)

    previous = pending_profile_proposal(db, identity)
    proposal = CustomerDataProposal(
        identity_id=identity.id,
        customer_id=customer.id,
        kind=ProposalKind.PROFILE_UPDATE.value,
        status=ProposalStatus.PENDING.value,
        submitted_at=now,
        supersedes_proposal_id=previous.id if previous else None,
    )
    db.add(proposal)
    db.flush()

    keys = {item.key for item in fields}
    rows: list[tuple[str, str, str, str | None]] = [
        (item.key, item.value_type.value, item.entered, item.normalized) for item in fields
    ]
    if previous is not None:
        # Supersede the older pending proposal, carrying forward what this one did not
        # resubmit, so a second request does not quietly drop the first. Whole groups are
        # carried or replaced together: a new address replaces the old address entirely.
        new_groups = {group_of(key) for key in keys}
        for row in previous.fields:
            if row.field_key in keys or group_of(row.field_key) in new_groups:
                continue
            rows.append(
                (row.field_key, row.value_type, row.proposed_value, row.proposed_value_normalized)
            )
            keys.add(row.field_key)
        previous.status = ProposalStatus.SUPERSEDED.value
        audit.proposal_superseded(
            db, identity=identity, proposal_id=proposal.id, superseded_id=previous.id
        )

    for key, value_type, entered, normalized in rows:
        db.add(
            CustomerDataProposalField(
                proposal_id=proposal.id,
                field_key=key,
                value_type=value_type,
                proposed_value=entered,
                proposed_value_normalized=normalized,
                current_value_at_submission=current.get(key),
                applied=False,
            )
        )
    db.flush()
    audit.proposal_submitted(
        db,
        identity=identity,
        proposal_id=proposal.id,
        field_keys=sorted(keys),
        ip_address=ip_address,
    )
    db.refresh(proposal)
    return proposal


def withdraw_proposal(
    db: Session, *, identity: CustomerIdentity, ip_address: str | None
) -> CustomerDataProposal:
    proposal = pending_profile_proposal(db, identity)
    if proposal is None:
        raise NotFoundError("You have no change request waiting for review.")
    proposal.status = ProposalStatus.WITHDRAWN.value
    db.flush()
    audit.proposal_withdrawn(db, identity=identity, proposal_id=proposal.id, ip_address=ip_address)
    return proposal


# --- Marketing consent ---------------------------------------------------------------


def record_marketing_choice(
    db: Session,
    *,
    identity: CustomerIdentity,
    customer: Customer,
    granted: bool,
    ip_address: str | None,
) -> MarketingState:
    """Append the customer's marketing choice. A suppression is untouched and unnamed.

    Written here rather than through ``consent_service.record_consent_event``, which
    refuses a grant against a suppressed address. That refusal protects a *staff* path --
    a staff member must not clear a suppression by typing a consent -- and a consent row
    never clears a suppression anyway: eligibility reads the suppression first
    (``ChannelConsentState.is_marketing_eligible``). For a customer, refusing would be the
    one response that differs for a suppressed address, which is exactly what
    FIELD_MATRIX §4 rule 2 forbids. So the choice is recorded, append-only, and the
    suppression keeps deciding (DEC-0123). The one thing the response adds is
    ``delivery_blocked`` -- a single boolean, set only on a grant -- so the customer is
    told plainly that the opt-in cannot be honoured yet (UAT round 3, superseding the
    "never mentioned" part of DEC-0123).
    """
    address = consent_service.normalized_address_for(customer, ConsentChannel.EMAIL.value)
    if not address:
        raise ValidationError(
            "We have no email address on file to record this against. Contact Solaris "
            "Express to add one.",
            field="granted",
        )
    suppressed = consent_service.is_suppressed(db, ConsentChannel.EMAIL.value, address) is not None
    now = utcnow()
    status = ConsentStatus.CONSENTED if granted else ConsentStatus.WITHDRAWN
    db.add(
        ConsentEvent(
            customer_id=customer.id,
            channel=ConsentChannel.EMAIL.value,
            address_value=address,
            status=status.value,
            basis=ConsentBasis.EXPRESS.value if granted else ConsentBasis.NOT_RECORDED.value,
            obtained_at=now if granted else None,
            withdrawn_at=None if granted else now,
            source="customer_account",
            evidence_reference=f"customer_account:{identity.public_id}",
            recorded_at=now,
            recorded_by_user_id=None,
        )
    )
    db.flush()
    audit.marketing_choice_recorded(
        db,
        identity=identity,
        customer_public_id=customer.public_id,
        status="granted" if granted else "withdrawn",
        suppressed=suppressed,
        ip_address=ip_address,
    )
    status_out = "granted" if granted else "withdrawn"
    return MarketingState(
        status=status_out,
        changed_at=now,
        delivery_blocked=_delivery_blocked(db, customer, status_out),
    )


# --- Staff review ----------------------------------------------------------------------


@dataclass
class ReviewRow:
    field_key: str
    group: str
    proposed_value: str | None
    proposed_value_normalized: str | None
    current_value_at_submission: str | None
    current_value_now: str | None
    drifted: bool
    applied: bool


@dataclass
class ProfileReview:
    proposal: CustomerDataProposal
    identity: CustomerIdentity
    customer: Customer
    rows: list[ReviewRow] = field(default_factory=list)

    @property
    def groups(self) -> list[str]:
        seen: list[str] = []
        for row in self.rows:
            if row.group not in seen:
                seen.append(row.group)
        return seen


def _comparable(value: str | None) -> str | None:
    if value is None:
        return None
    text = " ".join(str(value).split()).casefold()
    return text or None


def _drifted(row: CustomerDataProposalField, now: str | None) -> bool:
    """Whether the record moved under this field for a reason other than this request.

    A value that differs from the one on file at submission is drift, **unless** this row
    was applied and the record now holds exactly what it proposed: that change is the
    approval itself, not somebody else's (UAT round 8). A later edit by anyone else moves
    the value away from the proposed one, and is flagged again.
    """
    current = _comparable(now)
    if current == _comparable(row.current_value_at_submission):
        return False
    approved_values = {
        _comparable(row.proposed_value),
        _comparable(row.proposed_value_normalized),
    }
    return not (row.applied and current in approved_values)


def list_pending(
    db: Session, *, limit: int = 50
) -> list[tuple[CustomerDataProposal, CustomerIdentity, Customer]]:
    rows = db.execute(
        select(CustomerDataProposal, CustomerIdentity, Customer)
        .join(CustomerIdentity, CustomerIdentity.id == CustomerDataProposal.identity_id)
        .join(Customer, Customer.id == CustomerDataProposal.customer_id)
        .options(selectinload(CustomerDataProposal.fields))
        .where(
            CustomerDataProposal.kind == ProposalKind.PROFILE_UPDATE.value,
            CustomerDataProposal.status == ProposalStatus.PENDING.value,
        )
        .order_by(CustomerDataProposal.submitted_at.asc(), CustomerDataProposal.id.asc())
        .limit(limit)
    ).all()
    return [(proposal, identity, customer) for proposal, identity, customer in rows]


def latest_profile_proposal(db: Session, identity: CustomerIdentity) -> CustomerDataProposal:
    proposal = db.scalar(
        select(CustomerDataProposal)
        .options(selectinload(CustomerDataProposal.fields))
        .where(
            CustomerDataProposal.identity_id == identity.id,
            CustomerDataProposal.kind == ProposalKind.PROFILE_UPDATE.value,
            CustomerDataProposal.status.in_(
                [
                    ProposalStatus.PENDING.value,
                    ProposalStatus.APPROVED.value,
                    ProposalStatus.REJECTED.value,
                ]
            ),
        )
        .order_by(CustomerDataProposal.id.desc())
    )
    if proposal is None:
        raise NotFoundError("This account has no profile change to review.")
    return proposal


def build_review(db: Session, identity: CustomerIdentity) -> ProfileReview:
    proposal = latest_profile_proposal(db, identity)
    customer = db.get(Customer, proposal.customer_id) if proposal.customer_id else None
    if customer is None:
        raise NotFoundError("The customer this change was proposed against no longer exists.")
    current = current_values(db, customer)
    rows: list[ReviewRow] = []
    order = {key: index for index, key in enumerate(sorted(PROPOSAL_FIELDS))}
    for row in sorted(proposal.fields, key=lambda item: order.get(item.field_key, 999)):
        group = group_of(row.field_key) or row.field_key
        now = current.get(row.field_key)
        rows.append(
            ReviewRow(
                field_key=row.field_key,
                group=group,
                proposed_value=row.proposed_value,
                proposed_value_normalized=row.proposed_value_normalized,
                current_value_at_submission=row.current_value_at_submission,
                current_value_now=now,
                drifted=_drifted(row, now),
                applied=row.applied,
            )
        )
    return ProfileReview(proposal=proposal, identity=identity, customer=customer, rows=rows)


def decide(
    db: Session,
    *,
    identity: CustomerIdentity,
    actor: User,
    decisions: dict[str, str],
    reason_code: str | None,
    ip_address: str | None,
) -> ProfileReview:
    """Approve some groups and decline others, in one transaction (FIELD_MATRIX §5).

    * Every group in the proposal must be decided; a partial decision is refused.
    * A group whose canonical value changed since submission is **refused, not merged** --
      the reviewer sees the drift and the customer can resubmit.
    * A decided proposal is not decided again: the second call is a 409 and writes nothing,
      so approving twice changes canonical data once (§7.5).
    """
    review = build_review(db, identity)
    proposal = review.proposal
    if proposal.status != ProposalStatus.PENDING.value:
        raise ConflictError(
            f"This change request has already been decided: it is {proposal.status}."
        )
    if identity.status != IdentityStatus.ACTIVE.value:
        raise ConflictError("This account is not active, so its profile cannot change.")
    customer = review.customer
    if customer.merged_into_customer_id is not None or customer.is_archived:
        raise ConflictError("The linked customer record is archived or merged.")

    groups = review.groups
    unknown = sorted(set(decisions) - set(groups))
    if unknown:
        raise ValidationError(f"Not part of this request: {', '.join(unknown)}.", field="decisions")
    missing = [group for group in groups if group not in decisions]
    if missing:
        raise ValidationError(f"Decide every change: {', '.join(missing)}.", field="decisions")
    for group, verdict in decisions.items():
        if verdict not in {"approve", "decline"}:
            raise ValidationError("Each change is approved or declined.", field=group)

    approved = [group for group in groups if decisions[group] == "approve"]
    declined = [group for group in groups if decisions[group] == "decline"]
    if declined and reason_code not in DECLINE_REASON_CODES:
        raise ValidationError("Choose a reason for the declined changes.", field="reason_code")

    drifted = sorted({row.group for row in review.rows if row.group in approved and row.drifted})
    if drifted:
        raise ConflictError(
            "The customer record changed since this was submitted: "
            f"{', '.join(drifted)}. Decline it so the customer can resubmit against the "
            "current record."
        )

    proposed = {row.field_key: row.proposed_value for row in review.rows}
    # What the record held before this decision, for the audit row: field names with the
    # old and new values (UAT round 8). Staff reading the audit can already read every one
    # of these values on the customer record, so nothing is masked.
    before = current_values(db, customer)
    changes = [
        {"field": key, "old": before.get(key), "new": proposed[key]}
        for key in sorted(proposed)
        if group_of(key) in approved and before.get(key) != proposed[key]
    ]
    data: dict[str, Any] = {}
    if "legal_name" in approved:
        value = proposed["legal_name"]
        customer.legal_name = value
        if customer.category == CustomerCategory.BUSINESS.value:
            data["business_name"] = value
        else:
            data["full_name"] = value
    if "display_name" in approved:
        customer.display_name = proposed["display_name"]
    if "phone" in approved:
        data["phone"] = proposed.get("phone")
        if proposed.get("phone_country_code") and not customer.country_code:
            data["country_code"] = proposed["phone_country_code"]
    if "pickup_address" in approved:
        parts = {
            key.removeprefix(_ADDRESS_PREFIX): value
            for key, value in proposed.items()
            if key.startswith(_ADDRESS_PREFIX) and value is not None
        }
        contact = parts.pop("contact_name", None) or customer.full_name
        address = customer_address_service.create_address(
            db,
            customer,
            {**parts, "is_default_sender": True, "label": "From the Customer Account"},
            contact_name=contact,
            role=AddressRole.SENDER.value,
        )
        customer_address_service.enforce_single_default(db, address)
    if approved:
        # One ``customer.update`` row for every approval, an address-only one included, so
        # the customer's audit trail says what the request changed (UAT round 8).
        customer_service.update_customer(
            db,
            customer,
            data,
            actor=actor,
            ip_address=ip_address,
            changes=changes,
            source=customer_service.PROFILE_PROPOSAL_SOURCE,
        )

    for row in proposal.fields:
        row.applied = group_of(row.field_key) in approved
    proposal.status = ProposalStatus.APPROVED.value if approved else ProposalStatus.REJECTED.value
    proposal.reviewed_at = utcnow()
    proposal.reviewed_by_user_id = actor.id
    proposal.decision_reason_code = reason_code if declined else None
    db.flush()
    audit.profile_proposal_decided(
        db,
        identity=identity,
        customer_public_id=customer.public_id,
        proposal_id=proposal.id,
        approved_groups=approved,
        declined_groups=declined,
        reason_code=reason_code if declined else None,
        actor=actor,
        ip_address=ip_address,
    )
    return build_review(db, identity)
