"""Consent history and suppression (CRM.md section 11).

Rules enforced here:

* consent is an append-only event log per channel + normalized address, never a
  single overwritten checkbox;
* suppression is global to the channel/address pair, so it survives merges and
  re-imports and cannot be cleared by writing a new consent event;
* unknown or imported contact information is not marketing eligible by default;
* promotional eligibility is separate from operational contact preferences.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.enums import ConsentBasis, ConsentChannel, ConsentStatus
from app.core.normalization import normalize_email, normalize_phone, phone_match_key
from app.core.permissions import Permission, permissions_for
from app.core.time_utils import utcnow
from app.models import ConsentEvent, ContactSuppression, Customer, User
from app.services import audit_service
from app.services.errors import ConflictError, PermissionDeniedError, ValidationError


@dataclass
class ChannelConsentState:
    channel: str
    address_value: str | None
    status: str
    basis: str
    obtained_at: datetime | None
    withdrawn_at: datetime | None
    expires_at: datetime | None
    recorded_at: datetime | None
    source: str | None
    is_suppressed: bool
    suppression_reason: str | None

    @property
    def is_marketing_eligible(self) -> bool:
        """Eligible only with a current, unexpired, unsuppressed express-style consent."""
        if self.is_suppressed or self.address_value is None:
            return False
        if self.status != ConsentStatus.CONSENTED:
            return False
        return not (self.expires_at is not None and self.expires_at <= utcnow())


def normalized_address_for(customer: Customer, channel: str) -> str | None:
    if channel == ConsentChannel.EMAIL:
        return customer.email_normalized
    if channel == ConsentChannel.SMS:
        return phone_match_key(customer.phone_entered, customer.phone_e164)
    return None


def _normalize_input_address(channel: str, value: str | None) -> str | None:
    if not value:
        return None
    if channel == ConsentChannel.EMAIL:
        _, normalized = normalize_email(value)
        return normalized
    entered, e164, _ = normalize_phone(value, None)
    return phone_match_key(entered, e164)


def normalized_input_address(channel: str, value: str | None) -> str | None:
    """The normalized form ``record_consent_event`` would store for ``value``."""
    return _normalize_input_address(channel, value)


def is_suppressed(
    db: Session, channel: str, address_value: str | None
) -> ContactSuppression | None:
    if not address_value:
        return None
    return db.scalar(
        select(ContactSuppression).where(
            ContactSuppression.channel == channel,
            ContactSuppression.address_value == address_value,
            ContactSuppression.released_at.is_(None),
        )
    )


def current_state(db: Session, customer: Customer, channel: str) -> ChannelConsentState:
    address_value = normalized_address_for(customer, channel)
    latest = None
    if address_value:
        latest = db.scalar(
            select(ConsentEvent)
            .where(
                ConsentEvent.customer_id == customer.id,
                ConsentEvent.channel == channel,
                ConsentEvent.address_value == address_value,
            )
            .order_by(ConsentEvent.recorded_at.desc(), ConsentEvent.id.desc())
            .limit(1)
        )
    suppression = is_suppressed(db, channel, address_value)
    return ChannelConsentState(
        channel=channel,
        address_value=address_value,
        status=(latest.status if latest else ConsentStatus.UNKNOWN),
        basis=(latest.basis if latest else ConsentBasis.NOT_RECORDED),
        obtained_at=latest.obtained_at if latest else None,
        withdrawn_at=latest.withdrawn_at if latest else None,
        expires_at=latest.expires_at if latest else None,
        recorded_at=latest.recorded_at if latest else None,
        source=latest.source if latest else None,
        is_suppressed=suppression is not None,
        suppression_reason=suppression.reason if suppression else None,
    )


def all_states(db: Session, customer: Customer) -> list[ChannelConsentState]:
    return [current_state(db, customer, channel) for channel in ConsentChannel]


def history(db: Session, customer: Customer) -> list[ConsentEvent]:
    return list(
        db.scalars(
            select(ConsentEvent)
            .where(ConsentEvent.customer_id == customer.id)
            .order_by(ConsentEvent.recorded_at.desc(), ConsentEvent.id.desc())
        ).all()
    )


def record_consent_event(
    db: Session,
    customer: Customer,
    *,
    channel: str,
    status: str,
    basis: str = ConsentBasis.NOT_RECORDED,
    address_value: str | None = None,
    obtained_at: datetime | None = None,
    expires_at: datetime | None = None,
    source: str | None = None,
    evidence_reference: str | None = None,
    note: str | None = None,
    actor: User | None = None,
    ip_address: str | None = None,
) -> ConsentEvent:
    normalized = _normalize_input_address(channel, address_value) or normalized_address_for(
        customer, channel
    )
    if not normalized:
        raise ValidationError(
            "This customer has no usable address for that channel, so consent cannot be recorded.",
            field="address_value",
        )
    if (
        status == ConsentStatus.SUPPRESSED
        and actor is not None
        and Permission.SUPPRESSION_ADD not in permissions_for(actor.role)
    ):
        # Suppressing is Marketing's and Admin's (owner decision, 2026-10-15). A consent
        # event with status "suppressed" writes the global suppression, so `consent:write`
        # alone must not reach it, or Operations would hold suppression by another door.
        raise PermissionDeniedError(
            "Only Marketing and Admin can suppress an address.",
            field="status",
            detail={"required_permission": Permission.SUPPRESSION_ADD},
        )
    if status == ConsentStatus.CONSENTED and basis == ConsentBasis.NOT_RECORDED:
        raise ValidationError(
            "Recording consent requires a consent basis and an evidence reference.", field="basis"
        )

    suppression = is_suppressed(db, channel, normalized)
    if suppression is not None and status == ConsentStatus.CONSENTED:
        # Staff must not be able to clear a suppression by writing a consent event
        # (CRM.md section 11). Releasing a suppression is a separate, audited action.
        raise ConflictError(
            "This address is suppressed. Release the suppression first if that is correct."
        )

    now = utcnow()
    event = ConsentEvent(
        customer_id=customer.id,
        channel=channel,
        address_value=normalized,
        status=status,
        basis=basis,
        obtained_at=obtained_at if status == ConsentStatus.CONSENTED else None,
        withdrawn_at=now if status == ConsentStatus.WITHDRAWN else None,
        expires_at=expires_at,
        source=source,
        evidence_reference=evidence_reference,
        note=note,
        recorded_at=now,
        recorded_by_user_id=actor.id if actor else None,
    )
    db.add(event)

    if status == ConsentStatus.SUPPRESSED:
        add_suppression(
            db,
            channel=channel,
            address_value=normalized,
            reason=note or "Recorded from consent history",
            actor=actor,
        )

    audit_service.record_audit(
        db,
        action="consent.record",
        entity_type="customer",
        entity_id=customer.public_id,
        summary=f"Recorded {channel} consent status '{status}' for {customer.public_id}",
        actor=actor,
        ip_address=ip_address,
        detail={"channel": channel, "status": status, "basis": basis},
    )
    return event


def add_suppression(
    db: Session,
    *,
    channel: str,
    address_value: str,
    reason: str,
    actor: User | None = None,
) -> ContactSuppression:
    existing = db.scalar(
        select(ContactSuppression).where(
            ContactSuppression.channel == channel,
            ContactSuppression.address_value == address_value,
        )
    )
    if existing is not None:
        existing.released_at = None
        existing.released_by_user_id = None
        existing.release_reason = None
        existing.reason = reason
        return existing
    suppression = ContactSuppression(
        channel=channel,
        address_value=address_value,
        reason=reason,
        created_at=utcnow(),
        created_by_user_id=actor.id if actor else None,
    )
    db.add(suppression)
    return suppression


#: The ``source`` a staff suppression writes on its consent event, so the history row says
#: where it came from.
SUPPRESSION_SOURCE_STAFF = "staff_suppression"


def suppress_address(
    db: Session,
    customer: Customer,
    *,
    channel: str,
    evidence_reference: str,
    reason: str,
    actor: User | None = None,
    ip_address: str | None = None,
) -> ContactSuppression:
    """Suppress the customer's address on one channel. Explicit and audited (UAT round 4).

    The block is global to the channel and normalized address, like every suppression, so
    it survives merges and re-imports. Three records, one transaction: an append-only
    consent event with ``status=suppressed`` carrying the evidence reference and the
    reason, the ``contact_suppressions`` row, and a ``suppression.add`` audit row that
    names the actor, the customer, the channel and the evidence reference (UAT round 5:
    Audit access showed nothing to trace the suppression back to). The detail carries no
    address and no reason prose: the reason is free text typed by staff and stays in the
    consent history, which is where a reviewer reads it.

    Requires ``suppression:add`` (Marketing and Admin). Releasing stays Admin's alone.
    """
    normalized = normalized_address_for(customer, channel)
    if not normalized:
        raise ValidationError(
            "This customer has no address on that channel, so there is nothing to suppress.",
            field="channel",
        )
    if is_suppressed(db, channel, normalized) is not None:
        raise ConflictError("This address is already suppressed.")

    now = utcnow()
    event = ConsentEvent(
        customer_id=customer.id,
        channel=channel,
        address_value=normalized,
        status=ConsentStatus.SUPPRESSED,
        basis=ConsentBasis.NOT_RECORDED,
        source=SUPPRESSION_SOURCE_STAFF,
        evidence_reference=evidence_reference,
        note=reason,
        recorded_at=now,
        recorded_by_user_id=actor.id if actor else None,
    )
    db.add(event)
    suppression = add_suppression(
        db, channel=channel, address_value=normalized, reason=reason, actor=actor
    )
    db.flush()
    audit_service.record_audit(
        db,
        action="suppression.add",
        entity_type="customer",
        entity_id=customer.public_id,
        summary=f"Suppressed the {channel} address of {customer.public_id}",
        actor=actor,
        ip_address=ip_address,
        detail={
            "channel": channel,
            "customer_public_id": customer.public_id,
            "consent_event_id": event.id,
            "evidence_recorded": True,
            "evidence_reference": evidence_reference,
        },
    )
    return suppression


def release_suppression(
    db: Session,
    *,
    channel: str,
    address_value: str,
    reason: str,
    actor: User | None = None,
    ip_address: str | None = None,
) -> ContactSuppression:
    """Explicit, audited release. Requires the ``suppression:release`` permission."""
    suppression = db.scalar(
        select(ContactSuppression).where(
            ContactSuppression.channel == channel,
            ContactSuppression.address_value == address_value,
            ContactSuppression.released_at.is_(None),
        )
    )
    if suppression is None:
        raise ValidationError("No active suppression found for that channel and address.")
    suppression.released_at = utcnow()
    suppression.released_by_user_id = actor.id if actor else None
    suppression.release_reason = reason
    audit_service.record_audit(
        db,
        action="suppression.release",
        entity_type="suppression",
        entity_id=f"{channel}:{address_value}",
        summary=f"Released {channel} suppression",
        actor=actor,
        ip_address=ip_address,
        detail={"reason": reason},
    )
    return suppression


def marketing_eligible(db: Session, customer: Customer, channel: str) -> bool:
    if customer.do_not_contact or customer.is_archived:
        return False
    return current_state(db, customer, channel).is_marketing_eligible
