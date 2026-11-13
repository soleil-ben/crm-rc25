"""Request dependencies: session resolution, CSRF, and permission enforcement.

Authorization is applied here on every data route. Hiding a control in the React app is
never treated as an authorization boundary (CRM.md section 11).
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import get_db
from app.core.permissions import permissions_for
from app.models import OrganizationSettings, User, UserSession
from app.services import auth_service
from app.services.activity_service import LifecycleThresholds
from app.services.errors import AuthenticationError, PermissionDeniedError

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def db_session() -> Iterator[Session]:
    yield from get_db()


DbSession = Annotated[Session, Depends(db_session)]


def client_ip(request: Request) -> str | None:
    # Only the direct peer is trusted; forwarded headers are not honoured because no
    # trusted proxy is configured yet (documented in docs/OPERATIONS.md).
    return request.client.host if request.client else None


def _session_pair(request: Request, db: Session) -> tuple[User, UserSession]:
    token = request.cookies.get(settings.session_cookie_name)
    resolved = auth_service.resolve_session(db, token)
    if resolved is None:
        raise AuthenticationError("Sign in to continue.")
    return resolved


def current_session(request: Request, db: DbSession) -> tuple[User, UserSession]:
    """Resolve the session and enforce CSRF on every state-changing request."""
    user, record = _session_pair(request, db)
    if request.method not in SAFE_METHODS:
        header_token = request.headers.get(settings.csrf_header_name)
        if not auth_service.verify_csrf(record, header_token):
            raise PermissionDeniedError(
                "Your session security token is missing or stale. Reload the page and try again."
            )
    return user, record


def current_user(session: Annotated[tuple[User, UserSession], Depends(current_session)]) -> User:
    return session[0]


CurrentUser = Annotated[User, Depends(current_user)]


def require(*permissions: str):
    """Dependency factory enforcing that the caller holds every listed permission."""

    def _dependency(user: CurrentUser) -> User:
        granted = permissions_for(user.role)
        missing = [permission for permission in permissions if permission not in granted]
        if missing:
            raise PermissionDeniedError(
                "Your role does not allow this action.",
                detail={"required": list(permissions), "missing": missing, "role": user.role},
            )
        return user

    # The guard states what it guards. Without this the permissions are captured in a
    # closure and invisible, so a test asking "which routes does the merged Operations role
    # now reach?" has to be a hand-maintained list -- and a hand-maintained list is exactly
    # what fails to mention the route somebody added last week.
    # Read by tests/test_route_permissions.py; the running application does not use it.
    _dependency.required_permissions = frozenset(permissions)
    return _dependency


def has(user: User, permission: str) -> bool:
    return permission in permissions_for(user.role)


def get_org_settings(db: Session) -> OrganizationSettings:
    row = db.query(OrganizationSettings).order_by(OrganizationSettings.id.asc()).first()
    if row is None:
        row = OrganizationSettings(
            office_timezone=settings.default_timezone,
            default_currency=settings.default_currency,
            tracking_base_url=settings.tracking_base_url,
        )
        db.add(row)
        db.flush()
    return row


def org_settings(db: DbSession) -> OrganizationSettings:
    return get_org_settings(db)


OrgSettings = Annotated[OrganizationSettings, Depends(org_settings)]


def lifecycle_thresholds(org: OrgSettings) -> LifecycleThresholds:
    return LifecycleThresholds.from_settings(org)


Thresholds = Annotated[LifecycleThresholds, Depends(lifecycle_thresholds)]
