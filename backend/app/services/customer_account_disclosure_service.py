"""How much shipment history an approval would make visible. OD-29, and only OD-29.

Before a person is linked to a canonical customer, staff must see **how many** historical
shipments become visible, the **oldest** and **newest** of them, and whether **cancelled**
and **rebooked** ones are included. This module computes those five figures and nothing
else.

**What qualifies, stated exactly**, and identical to the rule Phase 11 will serve rows
under (`SHIPMENT_ALLOWLISTS.md` sections 2 and 5):

```
shipments.customer_id = <candidate customer id>
  AND shipments.booking_state != 'draft'
  AND shipments.is_demo_record = 0
```

Three clauses, and the first is the whole of ownership. **Not** an email match on the
shipment, not a phone match, not recipient information, not address similarity, not
possession of a tracking reference, and never a customer id supplied by a browser. A
registration that names the same email as a shipment's sender field discloses nothing;
only the canonical shipper relationship does (OD-29, OD-30, T-04).

Drafts are excluded because a draft is internal work in progress with no customer-facing
identifier, and Public Tracking already refuses it. Demo records are excluded because they
are not this customer's shipments. Cancelled and rebooked shipments are **included and
labelled**, because OD-29 says they stay visible with safe states and because a count that
quietly dropped them would understate the disclosure -- which is the one direction this
number must never be wrong in.

OD-22 is open, so nothing here creates, infers or follows a return-shipment link. A return
record is counted when, and only when, its own ``customer_id`` is the candidate, exactly
like any other row.

**No shipment row leaves this module.** It returns two dates, a count and two booleans.
There is no code path from here to a reference, a package, an event, a recipient, a
financial value or an internal note, which is why the preview cannot leak one.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.enums import BookingState
from app.models import Shipment

#: The identifier of the rule above. Stored on every acknowledgement and mixed into the
#: preview fingerprint, so if the definition ever changes, an acknowledgement taken under
#: the old one stops matching instead of authorizing a disclosure nobody reviewed.
DISCLOSURE_DEFINITION_VERSION = "od29-shipper-link-v1"


@dataclass(frozen=True)
class DisclosureSummary:
    """The five OD-29 figures. Staff-facing only; never returned to a customer route.

    A count of matching shipments is itself an enumeration oracle
    (`SHIPMENT_ALLOWLISTS.md` section 6), so this object is built only inside the staff
    review path and `tests/test_account_privacy.py` asserts no customer-facing response
    carries any of its values.
    """

    shipment_count: int
    oldest_booked_at: datetime | None
    newest_booked_at: datetime | None
    includes_cancelled: bool
    includes_rebooked: bool
    definition_version: str = DISCLOSURE_DEFINITION_VERSION

    def as_audit_detail(self) -> dict[str, object]:
        """The figures, shaped for an audit payload. Counts and dates, never a reference."""
        return {
            "disclosed_shipment_count": self.shipment_count,
            "oldest_booked_at": self.oldest_booked_at.isoformat()
            if self.oldest_booked_at
            else None,
            "newest_booked_at": self.newest_booked_at.isoformat()
            if self.newest_booked_at
            else None,
            "includes_cancelled": self.includes_cancelled,
            "includes_rebooked": self.includes_rebooked,
            "disclosure_definition_version": self.definition_version,
        }

    def fingerprint_parts(self) -> list[str]:
        """The figures as fingerprint material, in a fixed order."""
        return [
            f"count={self.shipment_count}",
            f"oldest={self.oldest_booked_at.isoformat() if self.oldest_booked_at else ''}",
            f"newest={self.newest_booked_at.isoformat() if self.newest_booked_at else ''}",
            f"cancelled={int(self.includes_cancelled)}",
            f"rebooked={int(self.includes_rebooked)}",
            f"definition={self.definition_version}",
        ]


def qualifying_conditions(customer_id: int):
    """The three clauses, in one place, so no caller can write a fourth version of them.

    **Public since Phase 11**, and that is the whole point. The staff preview counts the
    rows an approval would disclose; the authenticated list and detail serve those same
    rows. Two copies of the rule would be two chances for the number a reviewer
    acknowledged to stop matching the rows a customer can actually read -- and the
    direction that drift would take is the one that matters, because the reviewer would
    have acknowledged less than was disclosed.

    So there is one definition, it is this one, and
    ``tests/test_account_shipments_inclusion.py`` asserts the preview count and the list
    total agree over the same data rather than trusting this paragraph.
    """
    return (
        Shipment.customer_id == customer_id,
        Shipment.booking_state != BookingState.DRAFT,
        Shipment.is_demo_record.is_(False),
    )


def summarize(db: Session, customer_id: int) -> DisclosureSummary:
    """Compute the five figures for one candidate customer.

    Two aggregate statements, no row loading. ``booking_date`` is the date the list will
    order and display by, so ``min`` and ``max`` of it are the dates the reviewer is being
    asked about; a shipment with no booking date contributes to the count and to neither
    bound, which is correct -- it is disclosed, and it has no date to state.
    """
    conditions = qualifying_conditions(customer_id)

    totals = db.execute(
        select(
            func.count(Shipment.id),
            func.min(Shipment.booking_date),
            func.max(Shipment.booking_date),
        ).where(*conditions)
    ).one()

    flags = db.execute(
        select(
            func.count(Shipment.id).filter(Shipment.booking_state == BookingState.CANCELLED),
            func.count(Shipment.id).filter(
                Shipment.rebooked_to_shipment_id.is_not(None)
                | Shipment.rebooked_from_shipment_id.is_not(None)
            ),
        ).where(*conditions)
    ).one()

    return DisclosureSummary(
        shipment_count=int(totals[0] or 0),
        oldest_booked_at=totals[1],
        newest_booked_at=totals[2],
        includes_cancelled=bool(flags[0]),
        includes_rebooked=bool(flags[1]),
    )


def empty() -> DisclosureSummary:
    """The disclosure for a customer that does not exist yet.

    A create-new approval discloses **nothing**: the customer is created by the approval,
    so it has no history. The figures are still computed, still shown and still
    acknowledged, because OD-29 requires the acknowledgement "even if the count is zero" --
    a reviewer who never sees a zero has not learned to read the number.
    """
    return DisclosureSummary(
        shipment_count=0,
        oldest_booked_at=None,
        newest_booked_at=None,
        includes_cancelled=False,
        includes_rebooked=False,
    )
