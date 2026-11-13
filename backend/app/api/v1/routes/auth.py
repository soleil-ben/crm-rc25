"""Authentication routes.

The staff session lives in an HTTP-only cookie; the CSRF token is a separate readable
cookie that the frontend echoes in a header. No staff token is ever placed in
localStorage (CRM.md section 3).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from app.api.deps import CurrentUser, DbSession, client_ip, current_session, get_org_settings
from app.core.config import settings
from app.core.db import commit_with_retry
from app.core.permissions import permissions_for
from app.models import User, UserSession
from app.schemas.auth import CsrfResponse, LoginRequest, LoginResponse, MeResponse, SessionUser
from app.schemas.common import OkResponse
from app.services import auth_service
from app.services.errors import ValidationError

router = APIRouter(prefix="/auth", tags=["auth"])


def _set_session_cookies(response: Response, session_token: str, csrf_token: str) -> None:
    max_age = settings.session_absolute_hours * 3600
    response.set_cookie(
        settings.session_cookie_name,
        session_token,
        max_age=max_age,
        httponly=True,
        secure=settings.cookie_secure,
        samesite=settings.cookie_samesite,
        domain=settings.cookie_domain,
        path="/",
    )
    # Readable by the frontend so it can echo the value in the CSRF header.
    response.set_cookie(
        settings.csrf_cookie_name,
        csrf_token,
        max_age=max_age,
        httponly=False,
        secure=settings.cookie_secure,
        samesite=settings.cookie_samesite,
        domain=settings.cookie_domain,
        path="/",
    )


def _clear_session_cookies(response: Response) -> None:
    for name in (settings.session_cookie_name, settings.csrf_cookie_name):
        response.delete_cookie(name, path="/", domain=settings.cookie_domain)


@router.post("/login", response_model=LoginResponse)
def login(
    payload: LoginRequest, request: Request, response: Response, db: DbSession
) -> LoginResponse:
    user, session_token, csrf_token = auth_service.authenticate(
        db,
        email=payload.email,
        password=payload.password,
        ip_address=client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    commit_with_retry(db)
    _set_session_cookies(response, session_token, csrf_token)
    return LoginResponse(
        user=SessionUser.model_validate(user),
        permissions=sorted(permissions_for(user.role)),
        csrf_token=csrf_token,
    )


@router.post("/logout", response_model=OkResponse)
def logout(
    session: Annotated[tuple[User, UserSession], Depends(current_session)],
    response: Response,
    db: DbSession,
) -> OkResponse:
    user, record = session
    auth_service.revoke_session(db, record, actor=user)
    commit_with_retry(db)
    _clear_session_cookies(response)
    return OkResponse(message="Signed out.")


@router.get("/me", response_model=MeResponse)
def me(user: CurrentUser, db: DbSession) -> MeResponse:
    org = get_org_settings(db)
    commit_with_retry(db)
    return MeResponse(
        user=SessionUser.model_validate(user),
        permissions=sorted(permissions_for(user.role)),
        environment=settings.environment,
        is_demo_environment=org.is_demo_environment,
    )


@router.get("/csrf", response_model=CsrfResponse)
def csrf(
    session: Annotated[tuple[User, UserSession], Depends(current_session)], request: Request
) -> CsrfResponse:
    """Return the CSRF token the browser already holds, for clients that cannot read cookies."""
    return CsrfResponse(csrf_token=request.cookies.get(settings.csrf_cookie_name, ""))


@router.post("/revoke-all", response_model=OkResponse)
def revoke_all(user: CurrentUser, response: Response, db: DbSession) -> OkResponse:
    count = auth_service.revoke_all_sessions(db, user, actor=user)
    commit_with_retry(db)
    _clear_session_cookies(response)
    return OkResponse(message=f"Revoked {count} session(s).")


class StaffPasswordChangeRequest(BaseModel):
    """RC-UAT-21 Phase B (DEC-0231). Never echoed back, never logged."""

    model_config = ConfigDict(extra="forbid")

    current_password: str = Field(max_length=1024)
    new_password: str = Field(max_length=1024)
    new_password_confirmation: str = Field(max_length=1024)


@router.post("/password/change", response_model=OkResponse)
def change_password(
    payload: StaffPasswordChangeRequest,
    session: Annotated[tuple[User, UserSession], Depends(current_session)],
    request: Request,
    response: Response,
    db: DbSession,
) -> OkResponse:
    """Change the signed-in staff member's own password (RC-UAT-21 Phase B, DEC-0231).

    The current password is required; every other session of the user is signed out; this
    one stays, on a rotated session (new cookies). Rate-limited per user; audited, refusals
    included.
    """
    user, record = session
    try:
        revoked, session_token, csrf_token = auth_service.change_own_password(
            db,
            user,
            current_session=record,
            current_password=payload.current_password,
            new_password=payload.new_password,
            new_password_confirmation=payload.new_password_confirmation,
            ip_address=client_ip(request),
            user_agent=request.headers.get("user-agent"),
        )
    except ValidationError:
        commit_with_retry(db)
        raise
    commit_with_retry(db)
    # The session is rotated (review LOW 12): new cookies, so this browser carries on.
    _set_session_cookies(response, session_token, csrf_token)
    return OkResponse(message=f"Password changed. {revoked} other session(s) were signed out.")
