"""What counts as a Customer Account link, and what a link forbids (OD-40).

One module, because "is this customer linked to an account?" is asked from two places that
must not answer it differently: the staff approval path, which refuses to create a second
link, and the customer **merge**, which refuses to run at all. Two copies of the predicate
are two chances for one of them to drift into ``status != 'revoked'``, or into reading the
identity's status instead of the link's.

---

## The definition

    A customer has an **effective link** when a ``customer_identity_links`` row names it
    and that row's ``status`` is ``active``.

The identity's own status is deliberately **not** part of the test, and each of the six
cases the owner asked about falls out of that single rule rather than needing its own
clause:

* **``active`` identity, active link.** Blocks. The account reaches this customer's
  history today.
* **``suspended`` identity, link retained.** Blocks. Suspension revokes sessions and keeps
  the link, and transition 7 of `STATE_MACHINES.md` returns the account to ``active``
  precisely when an active link is still there. The access is paused, not surrendered.
* **``deactivated`` identity.** Keeps its link and does **not** block a merge (owner
  decision, 2026-10-15). ``customer_identity_service.deactivate`` revokes sessions and
  tokens and leaves the link row ``active`` as the record of whose account it was; but
  deactivation is terminal, nothing returns the identity to ``active``, and
  ``resolve_readable_customer`` refuses a non-active identity before it reads a link, so
  the row grants nothing a merge could widen. This is the one exception to "the link
  table alone decides", and it is made only for the merge question
  (``has_merge_blocking_link``); ``has_effective_link`` and the unique indexes still count
  the row.
* **``rejected`` identity.** Does not block, because rejection writes no link. An
  ``active`` row against a rejected identity is a state nothing can produce; if one
  existed it would block, because a guard that reasons about impossible states by
  permitting them is a guard that fails open.
* **``pending_*`` identity with no link.** Does not block. An unlinked customer merges
  exactly as it did before this policy existed.
* **A row retained for audit after deactivation or revocation.** ``revoked``, so it does
  not block. It is a record that access *used* to exist. It is never deleted to permit a
  merge, and it never blocks one.

The rule reads the **link table**, never the identity table, so an identity/link
combination that should be impossible fails closed: any ``active`` row blocks, whatever
the identity says.

That is also the predicate behind the two partial unique indexes
(``uq_customer_identity_links_active_identity`` and ``..._active_customer``), so the guard
and the index cannot disagree about which rows are live.

---

## Why a merge is refused rather than resolved

OD-40 forbids all five of the things a merge could otherwise do to a link, and each is
forbidden for a reason a later workflow has to answer rather than a service guessing:

* **Moving** the link exposes a different -- usually larger -- shipment history, which
  OD-29 says a person must see and acknowledge **before** it becomes visible. A merge
  acknowledges nothing.
* **Preserving** it points a live link at a tombstoned customer, which is the one state
  `tests/test_account_activation_invariant.py` sweeps for.
* **Revoking** it silently removes an account's access with no reason code and no notice.
* **Suspending** the identity punishes an account holder for a staff data-quality action.
* Treating the merge as approval of the new disclosure scope makes a merge an approval
  path, which is exactly what DEC-0092 exists to prevent.

So the merge is refused, whole, with a staff-readable conflict. Refusing is the only one of
the six options that is reversible: nothing has happened, and the reconciliation workflow a
later phase builds can still do any of the others deliberately (DEC-0107).
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.account_enums import IdentityStatus, LinkStatus
from app.models import Customer, CustomerIdentity, CustomerIdentityLink
from app.services.errors import ConflictError

#: The link statuses that make a link *effective*. One member, named rather than inlined so
#: that adding a second status to ``LinkStatus`` is a decision about this set as well.
EFFECTIVE_LINK_STATUSES = frozenset({LinkStatus.ACTIVE.value})

#: The stable conflict code a staff surface switches on. Not prose: the message may be
#: reworded, translated or shortened, and a screen that branched on wording would break
#: when it was. Present in ``detail.code`` on the refusal.
CONFLICT_CODE = "customer_account_link_present"

#: Which side of the merge caused the refusal. Recorded in the audit payload and returned
#: in ``detail.blocked_side`` so a reviewer knows which record to take to reconciliation.
SIDE_SOURCE = "source"
SIDE_TARGET = "target"
SIDE_BOTH = "both"

#: What the reviewer is told. It names the obstacle and the next step and nothing else: no
#: account reference, no email address, no session state, no proposal content and no
#: shipment figure. A merge refusal is read by whoever happened to press the button, and
#: "this customer has an account" is already the most this surface needs to say.
REFUSAL_MESSAGE = (
    "This merge involves a customer with a Customer Account identity link, so it cannot "
    "run. Customer Account reconciliation has to happen first."
)


@dataclass(frozen=True)
class LinkBlock:
    """Which sides of an intended merge hold an effective link."""

    source_linked: bool
    target_linked: bool

    @property
    def blocked(self) -> bool:
        return self.source_linked or self.target_linked

    @property
    def side(self) -> str:
        if self.source_linked and self.target_linked:
            return SIDE_BOTH
        return SIDE_SOURCE if self.source_linked else SIDE_TARGET


class LinkedCustomerMergeRefused(ConflictError):
    """The merge was refused because a Customer Account link is in the way.

    Carries an ``audit_refusal`` hook rather than writing the audit row itself. The
    distinction is the whole of OD-40's "make no mutation on refusal, and audit the
    refusal": the refused transaction writes **nothing at all**, including no audit row,
    and the record is written afterwards on a session that has been rolled back clean
    (`app.core.db.persist_refusal_audit`, DEC-0111).
    """

    def __init__(self, block: LinkBlock) -> None:
        super().__init__(
            REFUSAL_MESSAGE,
            field="source_customer_id" if block.source_linked else "target_customer_id",
            detail={"code": CONFLICT_CODE, "blocked_side": block.side},
        )
        self.block = block


def has_effective_link(db: Session, customer_id: int) -> bool:
    """Whether this customer is linked, by the definition at the top of this module."""
    return (
        db.scalar(
            select(CustomerIdentityLink.id)
            .where(
                CustomerIdentityLink.customer_id == customer_id,
                CustomerIdentityLink.status.in_(EFFECTIVE_LINK_STATUSES),
            )
            .limit(1)
        )
        is not None
    )


def has_merge_blocking_link(db: Session, customer_id: int) -> bool:
    """Whether this customer's link stands in the way of a merge.

    An effective link blocks unless its identity is ``deactivated`` (owner decision,
    2026-10-15). Fails closed: a link whose identity row cannot be found still blocks.
    """
    return has_live_account_link(db, customer_id)


def has_live_account_link(db: Session, customer_id: int) -> bool:
    """An effective link whose account is not deactivated. Fails closed, as above.

    The predicate behind the merge gate and, since UAT round 6, behind the single email
    rule: while such a link exists the customer's email is the account's sign-in email
    and a staff edit may not change it.
    """
    return (
        db.scalar(
            select(CustomerIdentityLink.id)
            .outerjoin(CustomerIdentity, CustomerIdentity.id == CustomerIdentityLink.identity_id)
            .where(
                CustomerIdentityLink.customer_id == customer_id,
                CustomerIdentityLink.status.in_(EFFECTIVE_LINK_STATUSES),
                (CustomerIdentity.id.is_(None))
                | (CustomerIdentity.status != IdentityStatus.DEACTIVATED.value),
            )
            .limit(1)
        )
        is not None
    )


def inspect_merge(db: Session, *, source: Customer, target: Customer) -> LinkBlock:
    """Look at both sides of an intended merge. A read; it decides nothing by itself."""
    return LinkBlock(
        source_linked=has_merge_blocking_link(db, source.id),
        target_linked=has_merge_blocking_link(db, target.id),
    )


# --- The identity side of the same predicate (Phase 11) -----------------------
#
# `has_effective_link` above answers "is this *customer* linked?", which is the question the
# merge asks. Phase 11 asks the mirror question -- "which customer, if any, may this
# *identity* read?" -- and it must not answer differently. So it is written here, against
# the same `EFFECTIVE_LINK_STATUSES` frozenset, rather than as a second
# `status == 'active'` somewhere in a route or a shipment service. That literal appears
# once in this repository and this module is where it lives.
#
# The resolution deliberately does **not** stop at the link. A link row is necessary and
# not sufficient: it can, in principle, name a customer that has since been archived,
# merged or tombstoned. OD-40 makes those states unreachable through any supported path --
# a merge involving an effective link is refused whole -- and they are still checked, and
# still refused, because a guard that permits impossible states is a guard that fails open
# the day one of them becomes possible.


#: Why a resolution failed. Bounded, stable, and safe to put in an audit payload or a log
#: line: each one describes the *account*, never the customer, and never says whether any
#: particular shipment or customer exists.
REASON_OK = "ok"
REASON_IDENTITY_NOT_ACTIVE = "identity_not_active"
REASON_NO_EFFECTIVE_LINK = "no_effective_link"
REASON_MULTIPLE_EFFECTIVE_LINKS = "multiple_effective_links"
REASON_CUSTOMER_MISSING = "linked_customer_missing"
REASON_CUSTOMER_ARCHIVED = "linked_customer_archived"
REASON_CUSTOMER_MERGED = "linked_customer_merged"

#: Every refusal reason, for a test that wants to assert the set is closed.
REFUSAL_REASONS = frozenset(
    {
        REASON_IDENTITY_NOT_ACTIVE,
        REASON_NO_EFFECTIVE_LINK,
        REASON_MULTIPLE_EFFECTIVE_LINKS,
        REASON_CUSTOMER_MISSING,
        REASON_CUSTOMER_ARCHIVED,
        REASON_CUSTOMER_MERGED,
    }
)


@dataclass(frozen=True)
class ResolvedLink:
    """The outcome of asking which canonical customer an identity may read.

    ``customer`` is set only when ``reason`` is ``REASON_OK``. There is no half-resolved
    state and no "customer, but": a caller that reads ``customer`` without checking
    ``authorized`` gets ``None`` and a ``TypeError`` at the first use, which is the right
    failure for a missing check.
    """

    customer: Customer | None
    reason: str

    @property
    def authorized(self) -> bool:
        return self.reason == REASON_OK and self.customer is not None


def effective_links_for_identity(db: Session, identity_id: int) -> list[CustomerIdentityLink]:
    """Every effective link this identity holds, by the definition at the top of this module.

    Returns a **list** rather than a row, although a partial unique index permits at most
    one. The index is the guarantee; reading more than one row is how the guarantee gets
    checked rather than assumed. A caller that found two has found a database that stopped
    enforcing its own constraint, and the right answer to that is to refuse, not to take
    the first one and carry on reading somebody's shipments.
    """
    return list(
        db.scalars(
            select(CustomerIdentityLink)
            .where(
                CustomerIdentityLink.identity_id == identity_id,
                CustomerIdentityLink.status.in_(EFFECTIVE_LINK_STATUSES),
            )
            .order_by(CustomerIdentityLink.id.asc())
        ).all()
    )


def resolve_readable_customer(db: Session, identity) -> ResolvedLink:
    """Which canonical customer this identity may read, or why it may read none.

    Five gates, in this order, and each one is a refusal rather than a repair:

    1. **the identity is ``active``.** ``pending_approval`` holds a real session and reaches
       its own account state and nothing else; the other four states hold no session at all.
       Read from the identity row on this request, never from anything cached on the
       session, so a suspension takes effect on the next request rather than the next
       sign-in (T-14, AC-CA-8.5).
    2. **exactly one effective link.** Zero is the ordinary unapproved case. Two is a
       broken index, and is refused rather than resolved.
    3. **the customer row exists.**
    4. **it is not archived.**
    5. **it is not merged or tombstoned** -- ``merged_into_customer_id`` or ``merged_at``
       set means the row is a tombstone pointing at a survivor, which is exactly what a
       link must never be aimed at. Following the pointer would be retargeting the link,
       which OD-40 forbids and which a *read* request must never do in any case.

    **This function writes nothing.** It does not create, retarget, revoke or repair a link,
    and it does not touch the customer row. It is a read, and a read that finds a state it
    does not like refuses the request and leaves the state exactly where it was for a
    person to look at.
    """

    if identity is None or identity.status != IdentityStatus.ACTIVE.value:
        return ResolvedLink(customer=None, reason=REASON_IDENTITY_NOT_ACTIVE)

    links = effective_links_for_identity(db, identity.id)
    if not links:
        return ResolvedLink(customer=None, reason=REASON_NO_EFFECTIVE_LINK)
    if len(links) > 1:
        return ResolvedLink(customer=None, reason=REASON_MULTIPLE_EFFECTIVE_LINKS)

    customer = db.get(Customer, links[0].customer_id)
    if customer is None:
        return ResolvedLink(customer=None, reason=REASON_CUSTOMER_MISSING)
    if customer.merged_into_customer_id is not None or customer.merged_at is not None:
        return ResolvedLink(customer=None, reason=REASON_CUSTOMER_MERGED)
    if customer.is_archived:
        return ResolvedLink(customer=None, reason=REASON_CUSTOMER_ARCHIVED)

    return ResolvedLink(customer=customer, reason=REASON_OK)
