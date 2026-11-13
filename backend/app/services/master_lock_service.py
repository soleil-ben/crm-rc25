"""A booked master's items and fee lines are locked (owner decision 8, Louis Tong, 2026-10-21).

Once a master is **booked** (handed to the vendor) -- and after, when it is **completed** --
the commodity items and the surcharge fee lines of every shipment riding in it are frozen:
adding, editing or removing an item, and adding or removing a fee line, is refused with a
409 that says why and who can lift it. An **open** master is unaffected, and a **cancelled**
one has released its members, so their items are theirs again.

Stand-in (until the owner says otherwise): an **Admin** may unlock the master for edits with
a reason (required, at most 400 characters), audited ``master.unlocked``. While it is
unlocked the edits are allowed and each one's audit row names the unlock. It locks again
when Admin or Operations press **Lock again** (``master.relocked``), or by itself when a
quote for one of its shipments is finalised after the unlock (the re-priced figures are
the reason the unlock existed). At most one unlock is open per master.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.enums import ConsolidationState
from app.core.time_utils import utcnow
from app.models import Consolidation, MasterEditUnlock, Shipment, User
from app.services import audit_service
from app.services.errors import ConflictError, ValidationError

#: The master states in which members' items and fee lines are locked.
LOCKED_STATES = (ConsolidationState.BOOKED, ConsolidationState.COMPLETED)
REASON_MAX = 400


def is_locked_state(consolidation: Consolidation | None) -> bool:
    return consolidation is not None and consolidation.state in LOCKED_STATES


def open_unlock(db: Session, consolidation_id: int) -> MasterEditUnlock | None:
    return db.scalar(
        select(MasterEditUnlock).where(
            MasterEditUnlock.consolidation_id == consolidation_id,
            MasterEditUnlock.relocked_at.is_(None),
        )
    )


def master_for_shipment(db: Session, shipment_id: int) -> Consolidation | None:
    """The master the shipment currently rides in, or None."""
    from app.services import consolidation_service  # noqa: PLC0415 - avoids an import cycle

    membership = consolidation_service.active_membership_for_shipment(db, shipment_id)
    return db.get(Consolidation, membership.consolidation_id) if membership else None


def lock_view(db: Session, consolidation: Consolidation) -> dict[str, Any]:
    """What the workspace shows: locked or not, and the open unlock when there is one."""
    unlock = open_unlock(db, consolidation.id) if is_locked_state(consolidation) else None
    return {
        "locked": is_locked_state(consolidation) and unlock is None,
        "lockable": is_locked_state(consolidation),
        "unlock": (
            {
                "id": unlock.id,
                "reason": unlock.reason,
                "unlocked_at": unlock.unlocked_at,
                "unlocked_by_user_id": unlock.unlocked_by_user_id,
            }
            if unlock
            else None
        ),
    }


def require_editable(db: Session, shipment: Shipment) -> MasterEditUnlock | None:
    """Refuse an item or fee change on a locked master; return the open unlock, if any.

    None means the shipment is not on a locked master (nothing to note in the audit).
    """
    master = master_for_shipment(db, shipment.id)
    if not is_locked_state(master):
        return None
    unlock = open_unlock(db, master.id)
    if unlock is None:
        raise ConflictError(
            f"{master.public_id} is {master.state}, so the items and fees of its shipments "
            "are locked. An Admin can unlock it for edits, with a reason.",
            detail={
                "code": "master_locked",
                "consolidation_id": master.id,
                "consolidation_state": master.state,
            },
        )
    return unlock


def audit_detail(unlock: MasterEditUnlock | None) -> dict[str, Any]:
    """The extra audit detail of an edit made while the master was unlocked."""
    return {"master_unlock_id": unlock.id} if unlock is not None else {}


def _reason(value: Any, *, required: bool = True) -> str | None:
    if value is not None and not isinstance(value, str):
        raise ValidationError("A reason must be text.", field="reason")
    text = " ".join((value or "").split())
    if not text:
        if required:
            raise ValidationError("Give a reason to unlock the master for edits.", field="reason")
        return None
    if len(text) > REASON_MAX:
        raise ValidationError(f"At most {REASON_MAX} characters.", field="reason")
    return text


def unlock(
    db: Session,
    consolidation: Consolidation,
    *,
    reason: Any,
    actor: User | None,
    now: datetime | None = None,
) -> MasterEditUnlock:
    """Open a temporary unlock (the route allows Admin only)."""
    text = _reason(reason)
    if not is_locked_state(consolidation):
        raise ConflictError(
            f"{consolidation.public_id} is {consolidation.state}; only a booked or completed "
            "master is locked, so there is nothing to unlock."
        )
    if open_unlock(db, consolidation.id) is not None:
        raise ConflictError(f"{consolidation.public_id} is already unlocked for edits.")
    row = MasterEditUnlock(
        consolidation_id=consolidation.id,
        unlocked_by_user_id=actor.id if actor else None,
        reason=text,
        unlocked_at=now or utcnow(),
    )
    label = consolidation.public_id
    try:
        # ``begin_nested`` flushes what is pending first, so the row is added inside it.
        with db.begin_nested():
            db.add(row)
            db.flush()
    except IntegrityError as error:
        # Two Admins unlocked at once; the partial unique index decided (409, not 500).
        raise ConflictError(f"{label} is already unlocked for edits.") from error
    audit_service.record_audit(
        db,
        action="master.unlocked",
        entity_type="consolidation",
        entity_id=consolidation.public_id,
        summary=f"Unlocked {consolidation.public_id} for item and fee edits: {text}"[:400],
        actor=actor,
        detail={"unlock_id": row.id, "reason": text, "state": consolidation.state},
    )
    return row


def relock(
    db: Session,
    consolidation: Consolidation,
    *,
    actor: User | None,
    reason: Any = None,
    automatic: str | None = None,
    now: datetime | None = None,
) -> MasterEditUnlock:
    """Close the open unlock. ``automatic`` is the system's reason (a quote was finalised)."""
    now = now or utcnow()
    row = open_unlock(db, consolidation.id)
    if row is None:
        raise ConflictError(f"{consolidation.public_id} is not unlocked; it is already locked.")
    text = automatic or _reason(reason, required=False) or "Locked again by staff."
    # Conditional: two people pressing Lock again at once close it once.
    changed = db.execute(
        update(MasterEditUnlock)
        .where(MasterEditUnlock.id == row.id, MasterEditUnlock.relocked_at.is_(None))
        .values(
            relocked_at=now,
            relocked_by_user_id=actor.id if actor else None,
            relock_reason=text[:REASON_MAX],
        )
        .execution_options(synchronize_session=False)
    ).rowcount
    if changed != 1:
        raise ConflictError(f"{consolidation.public_id} is not unlocked; it is already locked.")
    db.refresh(row)
    audit_service.record_audit(
        db,
        action="master.relocked",
        entity_type="consolidation",
        entity_id=consolidation.public_id,
        summary=(
            f"Locked {consolidation.public_id} again"
            + (" automatically" if automatic else "")
            + f": {text}"
        )[:400],
        actor=actor,
        detail={"unlock_id": row.id, "reason": text, "automatic": bool(automatic)},
    )
    return row


def on_quote_finalized(
    db: Session,
    consolidation_id: int | None,
    *,
    shipment: Shipment,
    version: int,
    actor: User | None,
    now: datetime | None = None,
) -> MasterEditUnlock | None:
    """A member's quote was finalised: an open unlock closes by itself (owner decision 8)."""
    if consolidation_id is None:
        return None
    consolidation = db.get(Consolidation, consolidation_id)
    row = open_unlock(db, consolidation_id) if consolidation else None
    if row is None:
        return None
    return relock(
        db,
        consolidation,
        actor=actor,
        automatic=f"quote v{version} finalised for {shipment.public_id}",
        now=now,
    )
