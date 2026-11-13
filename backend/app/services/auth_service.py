"""Staff authentication with server-managed sessions (CRM.md sections 3 and 11).

The browser only ever holds an opaque session token in an HTTP-only cookie plus a
readable CSRF token. Neither is a staff access token, and neither is stored in
localStorage. Session records can be revoked server-side at any time.
"""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.demo_identity import is_reserved_demo_email
from app.core.security import (
    generate_token,
    hash_password,
    hash_token,
    needs_rehash,
    rate_limiter,
    tokens_match,
    verify_password,
)
from app.core.time_utils import utcnow
from app.models import User, UserSession
from app.services import audit_service
from app.services.errors import AuthenticationError, RateLimitedError, ValidationError

GENERIC_LOGIN_FAILURE = "Email or password is incorrect."


def authenticate(
    db: Session,
    *,
    email: str,
    password: str,
    ip_address: str | None,
    user_agent: str | None,
) -> tuple[User, str, str]:
    """Verify credentials and open a session.

    Returns ``(user, session_token, csrf_token)``. Failures are rate limited per IP and
    per email, and every failure returns the same message so the endpoint cannot be used
    to enumerate staff accounts.
    """
    normalized_email = email.strip().lower()
    for bucket in (f"login:ip:{ip_address or 'unknown'}", f"login:email:{normalized_email}"):
        allowed, retry_after = rate_limiter.check(
            bucket, settings.login_rate_limit_attempts, settings.login_rate_limit_window_seconds
        )
        if not allowed:
            raise RateLimitedError(
                "Too many sign-in attempts. Wait a moment and try again.", retry_after=retry_after
            )

    # A demo or UAT identity is never a production login.
    #
    # Checked before the password, and answered with the same generic failure, so a
    # production deployment that still holds seeded accounts cannot be used to confirm
    # which of them exist -- and so the well-known seed password is worthless there.
    # `app.main` refuses to start in production while such an account is active, so this
    # should be unreachable; it is here because "should be unreachable" is not a control.
    if settings.is_production and is_reserved_demo_email(normalized_email):
        raise AuthenticationError(GENERIC_LOGIN_FAILURE)

    user = db.scalar(select(User).where(User.email == normalized_email))
    if user is None or not verify_password(password, user.password_hash):
        raise AuthenticationError(GENERIC_LOGIN_FAILURE)
    if not user.is_active:
        # Same message as a bad password: a deactivated account is not confirmed to callers.
        raise AuthenticationError(GENERIC_LOGIN_FAILURE)

    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(password)

    session_token = generate_token()
    csrf_token = generate_token()
    now = utcnow()
    record = UserSession(
        user_id=user.id,
        session_token_hash=hash_token(session_token),
        csrf_token_hash=hash_token(csrf_token),
        created_at=now,
        last_seen_at=now,
        expires_at=now + timedelta(hours=settings.session_absolute_hours),
        ip_address=ip_address,
        user_agent=(user_agent or "")[:255] or None,
    )
    db.add(record)
    user.last_login_at = now

    audit_service.record_audit(
        db,
        action="auth.login",
        entity_type="user",
        entity_id=user.id,
        summary=f"{user.email} signed in",
        actor=user,
        ip_address=ip_address,
    )
    return user, session_token, csrf_token


def resolve_session(db: Session, session_token: str | None) -> tuple[User, UserSession] | None:
    """Return the live session for a cookie token, applying idle and absolute expiry."""
    if not session_token:
        return None
    record = db.scalar(
        select(UserSession).where(UserSession.session_token_hash == hash_token(session_token))
    )
    if record is None or record.revoked_at is not None:
        return None

    now = utcnow()
    if record.expires_at <= now:
        return None
    if now - record.last_seen_at > timedelta(minutes=settings.session_idle_minutes):
        record.revoked_at = now
        return None

    user = db.get(User, record.user_id)
    if user is None or not user.is_active:
        return None

    record.last_seen_at = now
    return user, record


def verify_csrf(record: UserSession, header_token: str | None) -> bool:
    if not header_token:
        return False
    return tokens_match(record.csrf_token_hash, hash_token(header_token))


def revoke_session(db: Session, record: UserSession, *, actor: User | None = None) -> None:
    record.revoked_at = utcnow()
    audit_service.record_audit(
        db,
        action="auth.logout",
        entity_type="user",
        entity_id=record.user_id,
        summary="Session revoked",
        actor=actor,
    )


def revoke_all_sessions(db: Session, user: User, *, actor: User | None = None) -> int:
    records = db.scalars(
        select(UserSession).where(UserSession.user_id == user.id, UserSession.revoked_at.is_(None))
    ).all()
    now = utcnow()
    for record in records:
        record.revoked_at = now
    audit_service.record_audit(
        db,
        action="auth.revoke_all",
        entity_type="user",
        entity_id=user.id,
        summary=f"Revoked {len(records)} session(s) for {user.email}",
        actor=actor,
    )
    return len(records)


MIN_PASSWORD_LENGTH = 12


def validate_password(password: str) -> None:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValidationError(
            f"Use at least {MIN_PASSWORD_LENGTH} characters for a staff password.", field="password"
        )
    if password.strip() != password:
        raise ValidationError("Password cannot start or end with a space.", field="password")


#: RC-UAT-21 Phase B (DEC-0231). Sentences of the staff password change.
CURRENT_PASSWORD_WRONG = "The current password is not correct."
SAME_PASSWORD = "Choose a new password that is different from the current one."
PASSWORD_MISMATCH = "The two passwords do not match."
#: Five attempts a quarter hour per staff account.
PASSWORD_CHANGE_ATTEMPTS = 5
PASSWORD_CHANGE_WINDOW_SECONDS = 900


def change_own_password(
    db: Session,
    user: User,
    *,
    current_session: UserSession,
    current_password: str,
    new_password: str,
    new_password_confirmation: str | None,
    ip_address: str | None,
    user_agent: str | None = None,
) -> tuple[int, str, str]:
    """A signed-in staff member changes their own password.

    Returns ``(other sessions revoked, new session token, new CSRF token)``: the caller's own
    session is **rotated** (review LOW 12), as the Customer Account does.

    The current password is required and checked first; the new one follows the staff policy
    (``validate_password``), is typed twice and must differ from the current one. Every
    **other** session of the user is revoked; the one making the change stays signed in.
    ``must_change_password`` is cleared. Audited ``auth.password_change`` (and
    ``auth.password_change_refused`` on a refusal) -- never with a password in it.
    """
    allowed, retry_after = rate_limiter.check(
        f"auth:password_change:user:{user.id}",
        PASSWORD_CHANGE_ATTEMPTS,
        PASSWORD_CHANGE_WINDOW_SECONDS,
    )
    if not allowed:
        raise RateLimitedError(
            "Too many attempts. Wait a moment and try again.", retry_after=retry_after
        )

    def refuse(reason_code: str, message: str, field: str) -> ValidationError:
        audit_service.record_audit(
            db,
            action="auth.password_change_refused",
            entity_type="user",
            entity_id=user.id,
            summary=f"Password change refused for {user.email}",
            actor=user,
            ip_address=ip_address,
            detail={"reason_code": reason_code},
        )
        return ValidationError(message, field=field)

    if not isinstance(current_password, str) or not verify_password(
        current_password, user.password_hash
    ):
        raise refuse("bad_current_password", CURRENT_PASSWORD_WRONG, "current_password")
    validate_password(new_password)
    if new_password_confirmation != new_password:
        raise ValidationError(PASSWORD_MISMATCH, field="new_password_confirmation")
    if verify_password(new_password, user.password_hash):
        raise refuse("same_password", SAME_PASSWORD, "password")

    user.password_hash = hash_password(new_password)
    user.must_change_password = False
    others = db.scalars(
        select(UserSession).where(
            UserSession.user_id == user.id,
            UserSession.revoked_at.is_(None),
            UserSession.id != current_session.id,
        )
    ).all()
    now = utcnow()
    for record in others:
        record.revoked_at = now
    # Rotate this session: a copy of its cookie taken before the change is worthless after.
    current_session.revoked_at = now
    session_token = generate_token()
    csrf_token = generate_token()
    db.add(
        UserSession(
            user_id=user.id,
            session_token_hash=hash_token(session_token),
            csrf_token_hash=hash_token(csrf_token),
            created_at=now,
            last_seen_at=now,
            expires_at=now + timedelta(hours=settings.session_absolute_hours),
            ip_address=ip_address,
            user_agent=(user_agent or "")[:255] or None,
        )
    )
    audit_service.record_audit(
        db,
        action="auth.password_change",
        entity_type="user",
        entity_id=user.id,
        summary=f"{user.email} changed their password; {len(others)} other session(s) revoked",
        actor=user,
        ip_address=ip_address,
        detail={"sessions_revoked": len(others)},
    )
    return len(others), session_token, csrf_token


def create_user(
    db: Session,
    *,
    email: str,
    full_name: str,
    password: str,
    role: str,
    actor: User | None = None,
    is_active: bool = True,
) -> User:
    normalized_email = email.strip().lower()
    if db.scalar(select(User).where(User.email == normalized_email)) is not None:
        raise ValidationError("A staff account already exists with that email.", field="email")
    validate_password(password)
    user = User(
        email=normalized_email,
        full_name=full_name.strip(),
        password_hash=hash_password(password),
        role=role,
        is_active=is_active,
    )
    db.add(user)
    db.flush()
    audit_service.record_audit(
        db,
        action="staff.create",
        entity_type="user",
        entity_id=user.id,
        summary=f"Created staff account {user.email} with role {role}",
        actor=actor,
        detail={"role": role},
    )
    return user


def set_user_active(db: Session, user: User, *, is_active: bool, actor: User | None = None) -> User:
    user.is_active = is_active
    user.deactivated_at = None if is_active else utcnow()
    if not is_active:
        revoke_all_sessions(db, user, actor=actor)
    audit_service.record_audit(
        db,
        action="staff.activate" if is_active else "staff.deactivate",
        entity_type="user",
        entity_id=user.id,
        summary=f"{'Activated' if is_active else 'Deactivated'} staff account {user.email}",
        actor=actor,
    )
    return user


def change_role(db: Session, user: User, *, role: str, actor: User | None = None) -> User:
    previous = user.role
    user.role = role
    audit_service.record_audit(
        db,
        action="staff.role_change",
        entity_type="user",
        entity_id=user.id,
        summary=f"Changed role for {user.email} from {previous} to {role}",
        actor=actor,
        detail={"from": previous, "to": role},
    )
    return user
