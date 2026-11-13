"""Customer domain rules: creation, validation, update, archive, and merge.

Route handlers stay thin; the rules that matter live here (build prompt, CRM.md section 3).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session

from app.core.enums import CustomerCategory, LifecycleStatus, RouteGroup
from app.core.normalization import (
    INVALID_EMAIL_MESSAGE,
    collapse_whitespace,
    name_match_key,
    normalize_email,
    normalize_name,
    normalize_phone,
    phone_match_key,
)
from app.core.time_utils import utcnow
from app.models import (
    ConsentEvent,
    Customer,
    CustomerAddress,
    CustomerIdAlias,
    CustomerRouteInterest,
    CustomerTag,
    FollowUpTask,
    Interaction,
    Referral,
    ServiceIssue,
    Shipment,
    ShipmentPayer,
    User,
)
from app.services import audit_service
from app.services import customer_account_audit as account_audit
from app.services import customer_account_link_policy as link_policy
from app.services.errors import ConflictError, NotFoundError, ValidationError
from app.services.identifier_service import next_customer_public_id

CONTACT_REQUIRED_MESSAGE = "Provide at least one usable phone number or email address."


def _apply_contact_fields(customer: Customer, data: dict[str, Any]) -> None:
    """Normalize name/phone/email onto the record, preserving what was entered."""
    if "full_name" in data and data["full_name"] is not None:
        try:
            customer.full_name = normalize_name(data["full_name"])
        except ValueError as exc:
            raise ValidationError(str(exc), field="full_name") from exc
        customer.name_match_key = name_match_key(customer.full_name)

    if "phone" in data:
        entered, e164, region = normalize_phone(
            data.get("phone"), data.get("country_code") or customer.country_code
        )
        customer.phone_entered = entered
        customer.phone_e164 = e164
        customer.phone_region = region
        customer.phone_match_key = phone_match_key(entered, e164)

    if "email" in data:
        try:
            entered, normalized = normalize_email(data.get("email"))
        except ValueError as exc:
            raise ValidationError(INVALID_EMAIL_MESSAGE, field="email") from exc
        customer.email_entered = entered
        customer.email_normalized = normalized


#: The single email rule (owner decisions, 2026-10-15 and 2026-10-16), as the edit form
#: reads it. Staff cannot change it while the account is active or suspended; the account
#: must be deactivated first.
LINKED_EMAIL_MESSAGE = (
    "This email is the sign-in email of the customer's account, so it cannot be changed "
    "while the account is active or suspended. Deactivate the account first."
)


def _refuse_email_change_on_linked_customer(
    db: Session, customer: Customer, data: dict[str, Any]
) -> None:
    """A linked customer's email is the account's verified sign-in email. It does not move.

    A customer has one email (owner decision, 2026-10-15). An edit that keeps the same
    address -- the whole form is sent on every save -- passes; one that changes or clears it
    is refused while an active or suspended account holds the link. A deactivated account's
    link does not hold it, as it does not hold a merge.
    """
    if "email" not in data or customer.id is None:
        return
    try:
        _, normalized = normalize_email(data.get("email"))
    except ValueError:
        return  # the format error is reported by the normal path
    if normalized == customer.email_normalized:
        return
    if link_policy.has_live_account_link(db, customer.id):
        raise ConflictError(LINKED_EMAIL_MESSAGE, field="email")


def _validate_contactable(customer: Customer) -> None:
    if not customer.email_normalized and not customer.phone_match_key:
        raise ValidationError(CONTACT_REQUIRED_MESSAGE, field="phone")


def _validate_business_fields(customer: Customer) -> None:
    if customer.category != CustomerCategory.BUSINESS:
        # Business-only fields are cleared rather than silently retained.
        customer.business_type = None
        customer.business_name = None


def _set_route_interests(db: Session, customer: Customer, routes: list[str] | None) -> None:
    if routes is None:
        return
    valid = {route.value for route in RouteGroup}
    unknown = [route for route in routes if route not in valid]
    if unknown:
        raise ValidationError(
            f"Unknown route group(s): {', '.join(sorted(unknown))}",
            field="additional_route_interests",
        )
    wanted = {route for route in routes if route != customer.primary_route_group}
    existing = {interest.route_group: interest for interest in customer.route_interests}
    for route_group, interest in existing.items():
        if route_group not in wanted:
            db.delete(interest)
            customer.route_interests.remove(interest)
    for route_group in wanted - set(existing):
        customer.route_interests.append(CustomerRouteInterest(route_group=route_group))


def create_customer(
    db: Session,
    data: dict[str, Any],
    *,
    actor: User | None = None,
    ip_address: str | None = None,
    is_demo_record: bool = False,
) -> Customer:
    customer = Customer(is_demo_record=is_demo_record)
    _apply_contact_fields(customer, data)

    for field_name in (
        # Phase 10 added these two columns beside `full_name`, which keeps its
        # meaning. Neither feeds a match key or a duplicate rule; they are the
        # registered name and the preferred one (`FIELD_MATRIX.md` section 6).
        "legal_name",
        "display_name",
        "city",
        "province_state",
        "country_code",
        "preferred_language",
        "category",
        "business_type",
        "business_name",
        "primary_shipping_purpose",
        "primary_route_group",
        "shipping_frequency",
        "estimated_monthly_shipments",
        "preferred_contact_channel",
        "best_contact_time",
        "contact_timezone",
        "owner_user_id",
        "do_not_contact",
        "service_restriction_note",
        "notes",
        "source_system",
        "source_record_id",
        "source_created_at",
    ):
        if field_name in data and data[field_name] is not None:
            setattr(customer, field_name, data[field_name])

    if customer.country_code:
        customer.country_code = customer.country_code.upper()

    _validate_contactable(customer)
    _validate_business_fields(customer)
    if (
        customer.estimated_monthly_shipments is not None
        and customer.estimated_monthly_shipments < 0
    ):
        raise ValidationError(
            "Estimated monthly shipments cannot be negative.", field="estimated_monthly_shipments"
        )

    customer.public_id = next_customer_public_id(db)
    db.add(customer)
    db.flush()

    _set_route_interests(db, customer, data.get("additional_route_interests"))

    audit_service.record_audit(
        db,
        action="customer.create",
        entity_type="customer",
        entity_id=customer.public_id,
        summary=f"Created customer {customer.public_id}",
        actor=actor,
        ip_address=ip_address,
        detail={"category": customer.category, "primary_route_group": customer.primary_route_group},
    )
    return customer


#: The ``source`` an approved Customer Account change request writes on its audit row.
PROFILE_PROPOSAL_SOURCE = "customer_account_profile_proposal"


def update_customer(
    db: Session,
    customer: Customer,
    data: dict[str, Any],
    *,
    actor: User | None = None,
    ip_address: str | None = None,
    changes: list[dict[str, Any]] | None = None,
    source: str | None = None,
) -> Customer:
    """Apply an edit and write one ``customer.update`` audit row.

    ``changes`` comes from a caller that knows the old and new value of each field it
    applied -- today the approval of a Customer Account change request (UAT round 8). The
    row then carries them and lists those field names instead of the ``contact``
    pseudo-field, which says only that the email or phone moved. A plain staff edit still
    writes names only.
    """
    if customer.merged_into_customer_id is not None:
        raise ConflictError("This record was merged into another customer and is read-only.")

    changed_fields: list[str] = []
    before_contact = (customer.email_normalized, customer.phone_match_key)

    _refuse_email_change_on_linked_customer(db, customer, data)
    _apply_contact_fields(customer, data)

    for field_name in (
        "city",
        "province_state",
        "country_code",
        "preferred_language",
        "category",
        "business_type",
        "business_name",
        "primary_shipping_purpose",
        "primary_route_group",
        "shipping_frequency",
        "estimated_monthly_shipments",
        "preferred_contact_channel",
        "best_contact_time",
        "contact_timezone",
        "owner_user_id",
        "do_not_contact",
        "service_restriction_note",
        "notes",
    ):
        if field_name in data:
            new_value = data[field_name]
            if getattr(customer, field_name) != new_value:
                changed_fields.append(field_name)
            setattr(customer, field_name, new_value)

    if customer.country_code:
        customer.country_code = customer.country_code.upper()

    _validate_contactable(customer)
    _validate_business_fields(customer)
    if (
        customer.estimated_monthly_shipments is not None
        and customer.estimated_monthly_shipments < 0
    ):
        raise ValidationError(
            "Estimated monthly shipments cannot be negative.", field="estimated_monthly_shipments"
        )

    _set_route_interests(db, customer, data.get("additional_route_interests"))

    if before_contact != (customer.email_normalized, customer.phone_match_key):
        changed_fields.append("contact")

    detail: dict[str, Any] = {"changed_fields": sorted(set(changed_fields))}
    summary = f"Updated customer {customer.public_id}"
    if changes is not None:
        named = {change["field"] for change in changes}
        detail["changed_fields"] = sorted((set(changed_fields) - {"contact"}) | named)
        detail["changes"] = changes
    if source == PROFILE_PROPOSAL_SOURCE:
        detail["source"] = source
        summary = f"Updated customer {customer.public_id} from an approved change request"
    audit_service.record_audit(
        db,
        action="customer.update",
        entity_type="customer",
        entity_id=customer.public_id,
        summary=summary,
        actor=actor,
        ip_address=ip_address,
        detail=detail,
    )
    return customer


def archive_customer(
    db: Session,
    customer: Customer,
    *,
    reason: str | None,
    actor: User | None = None,
    ip_address: str | None = None,
) -> Customer:
    """Archiving is a lifecycle marker only.

    Shipment history is never cascade-deleted because a customer is archived
    (CRM.md section 15).
    """
    customer.is_archived = True
    customer.archived_at = utcnow()
    customer.archive_reason = collapse_whitespace(reason)
    audit_service.record_audit(
        db,
        action="customer.archive",
        entity_type="customer",
        entity_id=customer.public_id,
        summary=f"Archived customer {customer.public_id}",
        actor=actor,
        ip_address=ip_address,
        detail={"reason": customer.archive_reason},
    )
    return customer


def restore_customer(
    db: Session, customer: Customer, *, actor: User | None = None, ip_address: str | None = None
) -> Customer:
    customer.is_archived = False
    customer.archived_at = None
    customer.archive_reason = None
    audit_service.record_audit(
        db,
        action="customer.restore",
        entity_type="customer",
        entity_id=customer.public_id,
        summary=f"Restored customer {customer.public_id}",
        actor=actor,
        ip_address=ip_address,
    )
    return customer


def get_customer(db: Session, customer_id: int) -> Customer:
    customer = db.get(Customer, customer_id)
    if customer is None:
        raise NotFoundError("Customer not found.")
    return customer


def get_customer_by_public_id(db: Session, public_id: str) -> Customer | None:
    """Resolve a public customer ID, following merges and former-ID aliases.

    A former ID always leads to the surviving record so old paperwork keeps working
    (CRM.md section 13).
    """
    normalized = public_id.strip().upper()
    customer = db.scalar(select(Customer).where(Customer.public_id == normalized))
    if customer is None:
        alias = db.scalar(
            select(CustomerIdAlias).where(CustomerIdAlias.alias_public_id == normalized)
        )
        customer = alias.customer if alias else None
    return _follow_merge_chain(db, customer)


def _follow_merge_chain(
    db: Session, customer: Customer | None, max_hops: int = 10
) -> Customer | None:
    seen: set[int] = set()
    while customer is not None and customer.merged_into_customer_id is not None:
        if customer.id in seen or len(seen) >= max_hops:
            break
        seen.add(customer.id)
        customer = db.get(Customer, customer.merged_into_customer_id)
    return customer


def _refusal(
    block: link_policy.LinkBlock,
    *,
    source: Customer,
    target: Customer,
    actor: User | None,
    ip_address: str | None,
) -> link_policy.LinkedCustomerMergeRefused:
    """Build the refusal, with the record of it attached rather than written.

    Attached, because writing it here would write it into the transaction that is about to
    be discarded -- so the record of the refusal would vanish along with the changes the
    refusal prevented. ``app.core.db.persist_refusal_audit`` rolls the session back first
    and writes the row into a clean one, which is how "no mutation on refusal" and "audit
    the refusal" are both true (OD-40, DEC-0111).
    """
    error = link_policy.LinkedCustomerMergeRefused(block)
    source_public_id = source.public_id
    target_public_id = target.public_id

    def _write(session: Session) -> None:
        account_audit.merge_refused_linked_customer(
            session,
            source_public_id=source_public_id,
            target_public_id=target_public_id,
            blocked_side=block.side,
            actor=actor,
            ip_address=ip_address,
        )

    error.audit_refusal = _write
    return error


def _claim_source(db: Session, *, source: Customer, target: Customer) -> None:
    """Tombstone the source with a conditional write, and check that it landed.

    This is the merge's **claim**: the first write of the transaction and therefore the
    statement that takes SQLite's writer lock, and a conditional one, so a second merge of
    the same source affects no row and is told so rather than merging it twice.

    It is emphatically not a decorative lock. The ``WHERE`` clause is re-evaluated against
    committed data at the moment the lock is acquired, which is exactly the property a
    ``SELECT`` taken a line earlier does not have.

    ``updated_at`` is set explicitly because a Core ``UPDATE`` applies column-level
    ``onupdate`` and the ORM object is expired afterwards anyway -- the expire is what
    keeps the rest of the merge from reading a ``source`` whose tombstone columns are
    still the pre-claim ones.
    """
    now = utcnow()
    result = db.execute(
        update(Customer)
        .where(Customer.id == source.id, Customer.merged_into_customer_id.is_(None))
        .values(
            merged_into_customer_id=target.id,
            merged_at=now,
            is_archived=True,
            archived_at=now,
            archive_reason=f"Merged into {target.public_id}",
            updated_at=now,
        )
    )
    if result.rowcount != 1:
        raise ConflictError("The source record has already been merged.")
    db.expire(source)


def _recheck_under_claim(
    db: Session,
    *,
    source: Customer,
    target: Customer,
    actor: User | None,
    ip_address: str | None,
) -> None:
    """Re-decide, now that the writer lock is held, what was decided before it was.

    Three things can have changed between the unprotected checks and the claim, and each
    of them is a way the invariant would otherwise break:

    * an approval linked the **source** -- an active link pointing at a record this
      transaction has just tombstoned;
    * an approval linked the **target** -- an identity whose shipment history is about to
      grow by everything the source owns, with nothing acknowledged;
    * another merge tombstoned the **target** -- a merge into a record that is itself gone.

    Raising here rolls the claim back with the rest of the transaction, so a refusal at
    this point is as complete as a refusal before it.
    """
    block = link_policy.inspect_merge(db, source=source, target=target)
    if block.blocked:
        raise _refusal(block, source=source, target=target, actor=actor, ip_address=ip_address)

    still_open = db.scalar(select(Customer.merged_into_customer_id).where(Customer.id == target.id))
    if still_open is not None:
        raise ConflictError("The target record has already been merged into another customer.")


def merge_customers(
    db: Session,
    *,
    source: Customer,
    target: Customer,
    actor: User | None = None,
    ip_address: str | None = None,
) -> Customer:
    """Merge ``source`` into ``target`` inside one transaction.

    Shipment ownership, tasks, referral links, notes, consent history, suppression, and
    the former customer ID (kept as an alias) are all preserved (CRM.md section 13).
    Suppression lives on a global channel/address list and is untouched by a merge, so it
    cannot be dropped here.

    **A linked customer is not merged (OD-40, DEC-0107).** If either side holds an
    effective Customer Account link the whole merge is refused, here rather than in the
    route, so that every caller -- route, script, future bulk tool -- gets the same answer.
    ``customer_account_link_policy`` holds the definition of "effective"; this function
    holds the consequence.

    **How the concurrency guard works**, given that this database permits write skew.
    ``SELECT`` on pysqlite opens no transaction, so a check made before the first write is
    a check made outside any transaction and a link committed a microsecond later would not
    be seen. The order below is therefore load-bearing:

    1. every cheap refusal, while nothing has been written;
    2. ``_claim_source`` -- a **conditional** ``UPDATE`` of the source's tombstone columns
       whose affected-row count is checked. This is the first write of the transaction, so
       it is the statement that takes SQLite's writer lock, and it is the statement a
       second merge of the same record loses;
    3. **every check again**, now under that lock, where a read is current and no other
       connection can commit until this transaction ends;
    4. the merge itself.

    Step 3 is the one that closes the race with an approval: an approval's own first write
    is its idempotency claim, so the two operations cannot both be inside their write
    transactions at once, and whichever arrives second sees the other's committed work.
    """
    if source.id == target.id:
        raise ValidationError("Cannot merge a customer into itself.")
    if source.merged_into_customer_id is not None:
        raise ConflictError("The source record has already been merged.")
    if target.merged_into_customer_id is not None:
        raise ConflictError("The target record has already been merged into another customer.")

    # The OD-40 gate, before anything is written, so the refusal a reviewer sees costs
    # nothing and leaves nothing behind. The audit row is the single deliberate exception
    # and the route is what persists it.
    block = link_policy.inspect_merge(db, source=source, target=target)
    if block.blocked:
        raise _refusal(block, source=source, target=target, actor=actor, ip_address=ip_address)

    _claim_source(db, source=source, target=target)

    # Under the writer lock now. Everything decided above is decided again, because
    # everything above was decided outside a transaction.
    _recheck_under_claim(db, source=source, target=target, actor=actor, ip_address=ip_address)

    moved: dict[str, int] = {}
    # Phase 13G: quote offers follow the shipments. An unanswered one is withdrawn ("customer
    # merged"); answered ones are re-pointed so the history stays with the shipment.
    from app.services import quote_offer_service  # noqa: PLC0415

    moved["quote_offers"] = quote_offer_service.move_for_merge(
        db, source_id=source.id, target_id=target.id, actor=actor
    )
    for model in (Shipment, FollowUpTask, Interaction, ConsentEvent, ServiceIssue, CustomerAddress):
        rows = db.scalars(select(model).where(model.customer_id == source.id)).all()
        for row in rows:
            row.customer_id = target.id
        moved[model.__tablename__] = len(rows)
    # Phase 13B: a payer row names a customer too. Re-point it, and drop it where the merge
    # makes the payer the booking customer (no row means "the booking customer pays").
    payer_rows = db.scalars(
        select(ShipmentPayer).where(ShipmentPayer.payer_customer_id == source.id)
    ).all()
    for payer_row in payer_rows:
        shipment = db.get(Shipment, payer_row.shipment_id)
        if shipment is not None and shipment.customer_id == target.id:
            db.delete(payer_row)
        else:
            payer_row.payer_customer_id = target.id
    moved[ShipmentPayer.__tablename__] = len(payer_rows)
    # RC-UAT-21 Phase A: legacy history follows the customer, voided or not, so a merge
    # never leaves a historical shipment pointing at a merged-away record (DEC-0230).
    from app.models import LegacyShipment  # noqa: PLC0415

    legacy_rows = db.scalars(
        select(LegacyShipment).where(LegacyShipment.customer_id == source.id)
    ).all()
    for legacy_row in legacy_rows:
        legacy_row.customer_id = target.id
    moved[LegacyShipment.__tablename__] = len(legacy_rows)

    # Referrals: move both directions, dropping links that would become self-referrals
    # or would violate the one-referrer-per-customer rule.
    referral_rows = db.scalars(
        select(Referral).where(
            or_(
                Referral.referrer_customer_id == source.id,
                Referral.referred_customer_id == source.id,
            )
        )
    ).all()
    dropped_referrals = 0
    for referral in referral_rows:
        if referral.referrer_customer_id == source.id:
            referral.referrer_customer_id = target.id
        if referral.referred_customer_id == source.id:
            existing = db.scalar(
                select(Referral).where(
                    Referral.referred_customer_id == target.id, Referral.id != referral.id
                )
            )
            if existing is not None:
                db.delete(referral)
                dropped_referrals += 1
                continue
            referral.referred_customer_id = target.id
        if referral.referrer_customer_id == referral.referred_customer_id:
            db.delete(referral)
            dropped_referrals += 1
    moved["referrals"] = len(referral_rows) - dropped_referrals

    # Tags are a set union.
    target_tag_ids = {link.tag_id for link in target.tag_links}
    for link in list(source.tag_links):
        if link.tag_id in target_tag_ids:
            db.delete(link)
        else:
            link.customer_id = target.id

    # Route interests are a set union too.
    target_routes = {interest.route_group for interest in target.route_interests}
    for interest in list(source.route_interests):
        if (
            interest.route_group in target_routes
            or interest.route_group == target.primary_route_group
        ):
            db.delete(interest)
        else:
            interest.customer_id = target.id

    # Preserve the former customer ID as a searchable alias.
    db.add(
        CustomerIdAlias(
            customer_id=target.id,
            alias_public_id=source.public_id,
            created_at=utcnow(),
            reason="merge",
        )
    )
    for alias in list(source.aliases):
        alias.customer_id = target.id

    # Fill blanks on the target without overwriting values it already holds.
    for field_name in (
        # Filled from the source when the target has none, like every other column
        # here: a merge must not silently lose a legal or preferred name.
        "legal_name",
        "display_name",
        "city",
        "province_state",
        "country_code",
        "business_name",
        "business_type",
        "best_contact_time",
        "contact_timezone",
        "preferred_contact_channel",
        "owner_user_id",
        "primary_route_group",
    ):
        if getattr(target, field_name) in (None, "") and getattr(source, field_name) not in (
            None,
            "",
        ):
            setattr(target, field_name, getattr(source, field_name))
    if source.notes:
        target.notes = f"{target.notes}\n\n{source.notes}".strip() if target.notes else source.notes
    # A restriction on either record survives the merge.
    target.do_not_contact = target.do_not_contact or source.do_not_contact

    # The tombstone is not written here. `_claim_source` wrote it before any of the work
    # above, because it is this transaction's claim as well as its result, and writing it
    # twice would make the conditional ``WHERE`` clause decorative.

    audit_service.record_audit(
        db,
        action="customer.merge",
        entity_type="customer",
        entity_id=target.public_id,
        summary=f"Merged {source.public_id} into {target.public_id}",
        actor=actor,
        ip_address=ip_address,
        detail={
            "source_public_id": source.public_id,
            "moved": moved,
            "dropped_referrals": dropped_referrals,
        },
    )
    return target


def add_referral(
    db: Session,
    *,
    referrer: Customer,
    referred: Customer,
    note: str | None,
    actor: User | None = None,
) -> Referral:
    if referrer.id == referred.id:
        raise ValidationError("A customer cannot refer themselves.")
    existing = db.scalar(select(Referral).where(Referral.referred_customer_id == referred.id))
    if existing is not None:
        raise ConflictError("This customer is already recorded as referred by someone else.")
    referral = Referral(
        referrer_customer_id=referrer.id,
        referred_customer_id=referred.id,
        note=collapse_whitespace(note),
        recorded_by_user_id=actor.id if actor else None,
    )
    db.add(referral)
    audit_service.record_audit(
        db,
        action="referral.create",
        entity_type="customer",
        entity_id=referrer.public_id,
        summary=f"Recorded referral {referrer.public_id} -> {referred.public_id}",
        actor=actor,
    )
    return referral


def set_customer_tags(
    db: Session, customer: Customer, tag_ids: list[int], *, actor: User | None = None
) -> None:
    current = {link.tag_id: link for link in customer.tag_links}
    wanted = set(tag_ids)
    for tag_id, link in current.items():
        if tag_id not in wanted:
            db.delete(link)
    for tag_id in wanted - set(current):
        db.add(
            CustomerTag(
                customer_id=customer.id,
                tag_id=tag_id,
                created_at=utcnow(),
                created_by_user_id=actor.id if actor else None,
            )
        )


def search_customers_quick(db: Session, query: str, limit: int = 8) -> list[Customer]:
    """Global search across name, public ID, email, and phone (Design.md section 4)."""
    text = query.strip()
    if not text:
        return []
    like = f"%{text.lower()}%"
    _, email_normalized = (None, None)
    try:
        _, email_normalized = normalize_email(text)
    except ValueError:
        email_normalized = None
    entered, e164, _ = normalize_phone(text, None)
    phone_key = phone_match_key(entered, e164)
    name_key = name_match_key(text)

    conditions = [
        func.lower(Customer.public_id).like(like),
        func.lower(Customer.full_name).like(like),
    ]
    if name_key:
        conditions.append(Customer.name_match_key.like(f"%{name_key}%"))
    if email_normalized:
        conditions.append(Customer.email_normalized == email_normalized)
    else:
        conditions.append(func.lower(Customer.email_normalized).like(like))
    if phone_key:
        conditions.append(Customer.phone_match_key.like(f"%{phone_key}%"))

    return list(
        db.scalars(
            select(Customer)
            .where(or_(*conditions), Customer.merged_into_customer_id.is_(None))
            .order_by(Customer.full_name.asc())
            .limit(limit)
        ).all()
    )


# --- List filtering ------------------------------------------------------
#
# The customer list and the customer export must apply exactly the same predicates. Two
# copies would drift, and the copy that drifted would be the export -- silently widening
# what leaves the system (CRM.md section 13).


def build_list_conditions(
    db: Session,
    thresholds,
    *,
    search: str | None = None,
    category: list[str] | None = None,
    lifecycle_status: list[str] | None = None,
    preferred_language: list[str] | None = None,
    primary_route: list[str] | None = None,
    observed_route: str | None = None,
    owner_user_id: int | None = None,
    tag_id: list[int] | None = None,
    has_overdue_task: bool | None = None,
    has_service_issue: bool | None = None,
    last_shipment_within_days: int | None = None,
    last_shipment_before_days: int | None = None,
    created_from: date | None = None,
    created_to: date | None = None,
    include_archived: bool = False,
) -> list[Any]:
    """Predicates for the customer list, shared with the customer export."""
    from app.services.activity_service import (
        customer_ids_with_overdue_tasks,
        customer_ids_with_service_issues,
        customers_with_lifecycle,
        qualifying_shipment_filter,
    )

    conditions = [Customer.merged_into_customer_id.is_(None)]
    # Asking for the "archived" lifecycle status *is* asking for archived records. Without
    # this clause the two filters contradicted each other -- the status filter selected
    # archived customers and the default exclusion removed them -- and the filter answered
    # zero for every archived record there was (fix pack item 5).
    asks_for_archived = bool(lifecycle_status) and LifecycleStatus.ARCHIVED in lifecycle_status
    if not include_archived and not asks_for_archived:
        conditions.append(Customer.is_archived.is_(False))
    if search:
        like = f"%{search.strip().lower()}%"
        conditions.append(
            or_(
                func.lower(Customer.full_name).like(like),
                func.lower(Customer.public_id).like(like),
                func.lower(Customer.email_normalized).like(like),
                Customer.phone_match_key.like(like),
                func.lower(Customer.city).like(like),
            )
        )
    if category:
        conditions.append(Customer.category.in_(category))
    if preferred_language:
        conditions.append(Customer.preferred_language.in_(preferred_language))
    if primary_route:
        conditions.append(Customer.primary_route_group.in_(primary_route))
    if owner_user_id is not None:
        conditions.append(Customer.owner_user_id == owner_user_id)
    if created_from:
        conditions.append(
            Customer.created_at >= datetime.combine(created_from, datetime.min.time())
        )
    if created_to:
        conditions.append(Customer.created_at < datetime.combine(created_to, datetime.max.time()))

    if lifecycle_status:
        valid = {status.value for status in LifecycleStatus}
        unknown = [status for status in lifecycle_status if status not in valid]
        if unknown:
            raise ValidationError(f"Unknown lifecycle status: {', '.join(unknown)}")
        matching_ids = customers_with_lifecycle(db, thresholds, lifecycle_status)
        conditions.append(Customer.id.in_(matching_ids or [-1]))
    if has_overdue_task is not None:
        ids = customer_ids_with_overdue_tasks(db)
        conditions.append(
            Customer.id.in_(ids or [-1]) if has_overdue_task else ~Customer.id.in_(ids or [-1])
        )
    if has_service_issue is not None:
        ids = customer_ids_with_service_issues(db)
        conditions.append(
            Customer.id.in_(ids or [-1]) if has_service_issue else ~Customer.id.in_(ids or [-1])
        )
    if tag_id:
        for single_tag in tag_id:
            conditions.append(
                Customer.id.in_(
                    select(CustomerTag.customer_id).where(CustomerTag.tag_id == single_tag)
                )
            )
    if (
        observed_route
        or last_shipment_within_days is not None
        or last_shipment_before_days is not None
    ):
        from app.models import Shipment

        shipment_conditions = list(qualifying_shipment_filter())
        if observed_route:
            shipment_conditions.append(Shipment.route_group == observed_route)
        subquery = select(Shipment.customer_id).where(*shipment_conditions)
        if last_shipment_within_days is not None or last_shipment_before_days is not None:
            grouped = (
                select(Shipment.customer_id, func.max(Shipment.first_handoff_at).label("last_at"))
                .where(*shipment_conditions)
                .group_by(Shipment.customer_id)
                .subquery()
            )
            filters = []
            if last_shipment_within_days is not None:
                filters.append(
                    grouped.c.last_at >= utcnow() - timedelta(days=last_shipment_within_days)
                )
            if last_shipment_before_days is not None:
                filters.append(
                    grouped.c.last_at < utcnow() - timedelta(days=last_shipment_before_days)
                )
            subquery = select(grouped.c.customer_id).where(*filters)
        conditions.append(Customer.id.in_(subquery))
    return conditions
