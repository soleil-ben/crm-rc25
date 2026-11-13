"""Per-account permission grants (DEC-0268): give, take and check ``tariff:approve``.

An Admin (``staff:manage``) grants or revokes; every change is audited. The legacy approver
e-mail list in the tariff intake settings (``approver_emails``, Phase 13H) is kept as a way to
set the same grants: saving it grants ``tariff:approve`` to each listed staff account and
revokes it from the accounts no longer listed (``sync_holders``). Authorisation reads the
grants only, never an address.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.time_utils import utcnow
from app.models import StaffPermissionGrant, User
from app.services import audit_service
from app.services.errors import NotFoundError, ValidationError

#: Confirm or roll back a Kango rate sheet (and approve / reject a draft tariff).
TARIFF_APPROVE = "tariff:approve"
GRANTABLE = (TARIFF_APPROVE,)


def _check(permission: str) -> None:
    if permission not in GRANTABLE:
        raise ValidationError(
            f"permission must be one of {', '.join(GRANTABLE)}.", field="permission"
        )


def has_grant(db: Session, user: User | None, permission: str) -> bool:
    if user is None or not user.is_active:
        return False
    return (
        db.scalar(
            select(StaffPermissionGrant.id).where(
                StaffPermissionGrant.user_id == user.id,
                StaffPermissionGrant.permission == permission,
            )
        )
        is not None
    )


def holders(db: Session, permission: str) -> list[User]:
    _check(permission)
    return list(
        db.scalars(
            select(User)
            .join(StaffPermissionGrant, StaffPermissionGrant.user_id == User.id)
            .where(StaffPermissionGrant.permission == permission)
            .order_by(User.full_name, User.id)
        )
    )


def grant(db: Session, user: User, permission: str, *, actor: User | None) -> bool:
    """Give ``permission`` to ``user``; False when it was already held."""
    _check(permission)
    if has_grant(db, user, permission):
        return False
    db.add(
        StaffPermissionGrant(
            user_id=user.id,
            permission=permission,
            granted_at=utcnow(),
            granted_by_user_id=actor.id if actor else None,
        )
    )
    db.flush()
    audit_service.record_audit(
        db,
        action="staff.permission_granted",
        entity_type="user",
        entity_id=user.id,
        summary=f"Granted {permission} to {user.full_name}",
        actor=actor,
        detail={"permission": permission, "user_id": user.id},
    )
    return True


def revoke(db: Session, user: User, permission: str, *, actor: User | None) -> bool:
    _check(permission)
    row = db.scalar(
        select(StaffPermissionGrant).where(
            StaffPermissionGrant.user_id == user.id,
            StaffPermissionGrant.permission == permission,
        )
    )
    if row is None:
        return False
    db.delete(row)
    db.flush()
    audit_service.record_audit(
        db,
        action="staff.permission_revoked",
        entity_type="user",
        entity_id=user.id,
        summary=f"Revoked {permission} from {user.full_name}",
        actor=actor,
        detail={"permission": permission, "user_id": user.id},
    )
    return True


def get_user(db: Session, user_id: int) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise NotFoundError("No staff account with that id.")
    return user


def sync_holders(db: Session, permission: str, emails: list[str], *, actor: User | None) -> None:
    """Make the holders exactly the staff accounts with these addresses (the legacy list)."""
    wanted = {e.strip().lower() for e in emails}
    accounts = (
        list(db.scalars(select(User).where(func.lower(User.email).in_(wanted)))) if wanted else []
    )
    keep = {u.id for u in accounts}
    for user in accounts:
        grant(db, user, permission, actor=actor)
    for user in holders(db, permission):
        if user.id not in keep:
            revoke(db, user, permission, actor=actor)
