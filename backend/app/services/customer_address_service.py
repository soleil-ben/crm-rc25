"""Address-book writes: normalization, defaulting, creation.

**Extracted in Phase 10, not written for it.** Every line here came out of
``app/api/v1/routes/engagement.py``, where it was two module-private helpers behind the
address routes. It moved because Phase 10 needs the same behaviour from a second caller --
the approval that turns a registration proposal into canonical address rows -- and the
instruction is explicit that approval must "use existing customer/address/contact services
rather than direct model insertion".

There was no address *service* to use. The choice was to copy the normalization into the
approval path or to lift it into one place both callers read, and a copy is how two
surfaces start normalizing a phone number differently. So the route now calls this module
and its behaviour is unchanged: `tests/test_customers.py` and the Phase 2 booking suites
exercise the same code they exercised before, through the same routes.

What this module does **not** do is validate ownership or permissions. A caller has
already decided that this customer may gain this address; this module writes it.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.enums import AddressRole
from app.core.normalization import normalize_email, normalize_phone
from app.models import Customer, CustomerAddress


def apply_address_payload(address: CustomerAddress, data: dict[str, Any]) -> None:
    """Normalize and assign a partial address payload onto a row.

    ``phone`` and ``email`` are normalized through ``app.core.normalization`` -- the same
    module the customer record uses, so a number typed into an address book entry and the
    same number typed into a customer record produce the same E.164 value. The phone's
    region comes from the payload's ``country_code`` when it carries one, and otherwise
    from whatever the row already holds.

    Every other key is assigned as given, with an enum member reduced to its value. The
    caller owns the allowlist: this function trusts its input because the two callers that
    reach it have each validated theirs -- a Pydantic model on the staff route, and
    ``app.core.account_fields`` on the approval path.
    """
    if "phone" in data:
        entered, e164, _ = normalize_phone(
            data.pop("phone"), data.get("country_code") or address.country_code
        )
        address.phone_entered = entered
        address.phone_e164 = e164
    if "email" in data:
        entered, _ = normalize_email(data.pop("email"))
        address.email_entered = entered
    for key, value in data.items():
        if hasattr(value, "value"):
            value = value.value
        setattr(address, key, value)
    if address.country_code:
        address.country_code = address.country_code.upper()


def enforce_single_default(db: Session, address: CustomerAddress) -> None:
    """At most one default sender and one default recipient per customer.

    Enforced by clearing the others rather than by a constraint, because the rule is "the
    most recent choice wins" and a unique index would instead make the second choice an
    error the person has to resolve by hand.
    """
    if address.is_default_sender:
        for other in db.scalars(
            select(CustomerAddress).where(
                CustomerAddress.customer_id == address.customer_id,
                CustomerAddress.id != address.id,
                CustomerAddress.is_default_sender.is_(True),
            )
        ).all():
            other.is_default_sender = False
    if address.is_default_recipient:
        for other in db.scalars(
            select(CustomerAddress).where(
                CustomerAddress.customer_id == address.customer_id,
                CustomerAddress.id != address.id,
                CustomerAddress.is_default_recipient.is_(True),
            )
        ).all():
            other.is_default_recipient = False


def create_address(
    db: Session,
    customer: Customer,
    data: dict[str, Any],
    *,
    contact_name: str,
    role: str = AddressRole.BOTH,
) -> CustomerAddress:
    """Create one address-book row for a customer, normalized and defaulted.

    ``contact_name`` is separate from ``data`` because the column is not nullable and a
    row without one is not an address anybody can hand a driver.

    ``role`` accepts ``AddressRole.BILLING``, added in Phase 10. A billing row is not a
    sender or recipient row with a flag on it: the booking pickers select on role, and a
    billing address must never be offered as a place to collect from or deliver to.
    """
    address = CustomerAddress(customer_id=customer.id, contact_name=contact_name, role=role)
    apply_address_payload(address, dict(data))
    db.add(address)
    db.flush()
    enforce_single_default(db, address)
    return address
