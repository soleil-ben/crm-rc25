"""Customer Account authentication and sessions. A separate realm, not a shared one.

This module is a deliberate near-twin of ``app.services.auth_service`` rather than a reuse
of it, and the duplication is the feature. ``auth_service.resolve_session`` reads
``user_sessions`` and returns a ``User``; nothing here can produce a ``User``, and nothing
there can produce a ``CustomerIdentity``. A cookie from one realm presented to the other
authenticates nothing -- not because a check rejects it, but because the code that would
resolve it reads a different table (T-01, DEC-0090).

What *is* shared is policy, from ``app.core.security``: the Argon2 hasher and its
rehash-on-sign-in rule, the session-token digest, the constant-time comparison, and the
sliding-window limiter. Two hashers would mean one of them was weaker. Two limiters would
be two bugs. The **key space** of the limiter is not shared: every bucket here is in the
``account:`` namespace, so a customer-side flood cannot consume the staff login allowance
during exactly the incident operations needs to respond to.

Three properties this file exists to hold:

* **One refusal message.** Wrong password, unknown address, unverified, suspended, rejected,
  deactivated and locked all produce the same sentence. The distinctions matter to the audit
  log; none of them is a sentence the customer reads (`STATE_MACHINES.md` section 7).
* **Comparable work on the miss path.** An unknown address still performs an Argon2
  verification against a dummy hash, so failure timing does not separate a known address
  from an unknown one (T-16). The control is the work performed; a numeric latency assertion
  on a shared CI machine is a flaky test, not a security control.
* **No cached grant.** The session row holds no status, no role and no linked customer, so a
  suspension takes effect on the **next request** rather than at the next sign-in.
"""

from __future__ import annotations

import hmac
from datetime import timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.account_enums import AUTHENTICATABLE_STATUSES
from app.core.account_security import signin_address_bucket, signin_ip_bucket
from app.core.config import settings
from app.core.security import (
    generate_token,
    hash_password,
    hash_token,
    needs_rehash,
    rate_limiter,
    verify_password,
)
from app.core.time_utils import utcnow
from app.models import CustomerIdentity, CustomerSession
from app.services import customer_account_audit as audit
from app.services.errors import AuthenticationError, RateLimitedError, ValidationError

#: The single refusal. Every failed sign-in says this and only this.
GENERIC_SIGN_IN_FAILURE = "Email or password is incorrect."

#: An Argon2 hash of a value nobody knows, verified against on the miss path so that an
#: unknown address costs the same as a known one. Computed once at import rather than per
#: request: hashing on every miss would be a denial-of-service lever, while *verifying* is
#: the operation whose cost must match.
_DUMMY_PASSWORD_HASH = hash_password("solaris-account-miss-path-placeholder")


def _refuse(
    db: Session,
    *,
    email_normalized: str,
    reason_code: str,
    identity: CustomerIdentity | None,
    ip_address: str | None,
) -> AuthenticationError:
    """Record why, then return the one message the caller is allowed to say."""
    audit.sign_in_failed(
        db,
        email_normalized=email_normalized,
        reason_code=reason_code,
        identity=identity,
        ip_address=ip_address,
    )
    return AuthenticationError(GENERIC_SIGN_IN_FAILURE)


def check_sign_in_rate_limits(client_key: str, email_normalized: str) -> None:
    """Both buckets, before any database work. Raises ``RateLimitedError`` on refusal.

    Separated from ``authenticate`` so the route can call it before it has parsed a body:
    a malformed request must still consume the limit, and a refused request must issue no
    query (instruction section 12).
    """
    for bucket, limit, window in (
        (
            signin_ip_bucket(client_key),
            settings.account_signin_ip_attempts,
            settings.account_signin_ip_window_seconds,
        ),
        (
            signin_address_bucket(email_normalized),
            settings.account_signin_address_attempts,
            settings.account_signin_address_window_seconds,
        ),
    ):
        allowed, retry_after = rate_limiter.check(bucket, limit, window)
        if not allowed:
            raise RateLimitedError(
                "Too many sign-in attempts. Wait a moment and try again.",
                retry_after=retry_after,
            )


def authenticate(
    db: Session,
    *,
    email_normalized: str,
    password: str,
    ip_address: str | None,
    user_agent: str | None,
) -> tuple[CustomerIdentity, str, str]:
    """Verify credentials and open a session. Returns ``(identity, session_token, csrf_token)``.

    Every refusal raises ``AuthenticationError`` carrying ``GENERIC_SIGN_IN_FAILURE``. The
    order of the checks below is chosen so that the miss path and the hit path do the same
    kind of work: the password is verified *before* the status is consulted, so a suspended
    account and a wrong password are not separated by whether Argon2 ran.
    """
    identity = db.scalar(
        select(CustomerIdentity).where(CustomerIdentity.email_normalized == email_normalized)
    )

    if identity is None:
        # Comparable work, then the same refusal. Without this, an unknown address returns
        # in microseconds and a known one in the tens of milliseconds Argon2 costs.
        verify_password(password, _DUMMY_PASSWORD_HASH)
        raise _refuse(
            db,
            email_normalized=email_normalized,
            reason_code="unknown_address",
            identity=None,
            ip_address=ip_address,
        )

    now = utcnow()
    if identity.locked_until is not None and identity.locked_until > now:
        verify_password(password, _DUMMY_PASSWORD_HASH)
        raise _refuse(
            db,
            email_normalized=email_normalized,
            reason_code="locked",
            identity=identity,
            ip_address=ip_address,
        )

    if not verify_password(password, identity.password_hash):
        _record_failure(db, identity, now=now)
        raise _refuse(
            db,
            email_normalized=email_normalized,
            reason_code="bad_password",
            identity=identity,
            ip_address=ip_address,
        )

    if identity.status not in AUTHENTICATABLE_STATUSES:
        # `pending_verification`, `rejected`, `suspended`, `deactivated`. The customer is
        # told none of these apart (`STATE_MACHINES.md` section 7).
        raise _refuse(
            db,
            email_normalized=email_normalized,
            reason_code=f"status_{identity.status}",
            identity=identity,
            ip_address=ip_address,
        )

    if needs_rehash(identity.password_hash):
        identity.password_hash = hash_password(password)

    identity.failed_sign_in_count = 0
    identity.locked_until = None
    identity.last_sign_in_at = now

    session_token, csrf_token = open_session(
        db, identity, ip_address=ip_address, user_agent=user_agent
    )
    audit.sign_in_succeeded(db, identity=identity, ip_address=ip_address)
    return identity, session_token, csrf_token


def _record_failure(db: Session, identity: CustomerIdentity, *, now) -> None:
    """Count the failure and lock the account if it has crossed the threshold.

    Bounded in time and never permanent: a permanent lockout would hand an attacker a way to
    disable any customer whose address they can guess, which is a denial of service dressed
    as a control (`RATE_LIMITS_AND_ABUSE.md` section 3.1).
    """
    identity.failed_sign_in_count = (identity.failed_sign_in_count or 0) + 1
    if identity.failed_sign_in_count >= settings.account_lockout_threshold:
        identity.locked_until = now + timedelta(minutes=settings.account_lockout_minutes)
        identity.failed_sign_in_count = 0
        audit.locked(db, identity=identity)


def open_session(
    db: Session,
    identity: CustomerIdentity,
    *,
    ip_address: str | None,
    user_agent: str | None,
) -> tuple[str, str]:
    """Mint a new session. **Always a new token** -- this is the rotation of T-14.

    There is no path that reuses an existing session row on authentication, which is what
    makes session fixation impossible rather than unlikely.
    """
    session_token = generate_token()
    csrf_token = generate_token()
    now = utcnow()
    db.add(
        CustomerSession(
            identity_id=identity.id,
            session_token_hash=hash_token(session_token),
            csrf_token_hash=hash_token(csrf_token),
            created_at=now,
            last_seen_at=now,
            expires_at=now + timedelta(hours=settings.account_session_absolute_hours),
            ip_address=ip_address,
            user_agent=(user_agent or "")[:255] or None,
        )
    )
    return session_token, csrf_token


#: How stale ``last_seen_at`` may be before a request writes it again.
SESSION_TOUCH_INTERVAL = timedelta(seconds=60)


def resolve_session(
    db: Session, session_token: str | None
) -> tuple[CustomerIdentity, CustomerSession] | None:
    """Resolve a cookie token to a live session, applying idle and absolute expiry.

    Re-reads the identity every time and re-checks its status, because the session row holds
    no cached grant. A suspension therefore takes effect on the **next request**, not at the
    next sign-in -- the property Phase 7 established for staff roles, kept deliberately.
    """
    if not session_token:
        return None
    record = db.scalar(
        select(CustomerSession).where(
            CustomerSession.session_token_hash == hash_token(session_token)
        )
    )
    if record is None or record.revoked_at is not None:
        return None

    now = utcnow()
    if record.expires_at <= now:
        return None
    if now - record.last_seen_at > timedelta(minutes=settings.account_session_idle_minutes):
        # Committed here rather than left pending. The request this runs in is about to fail
        # with a 401 and will never reach `commit_with_retry`, so an uncommitted mark would
        # be a write that silently does nothing -- the row would stay unrevoked for ever
        # while the code read as though it had been revoked. Nothing else has been written
        # at this point in the request, so committing one row is safe.
        record.revoked_at = now
        db.commit()
        return None

    identity = db.get(CustomerIdentity, record.identity_id)
    if identity is None or identity.status not in AUTHENTICATABLE_STATUSES:
        return None

    # Throttled (Phase 17): written at most once a minute, far inside the idle timeout, so
    # ordinary page loads do not each take SQLite's write lock.
    if now - record.last_seen_at >= SESSION_TOUCH_INTERVAL:
        record.last_seen_at = now
    return identity, record


def verify_csrf(record: CustomerSession, header_token: str | None) -> bool:
    """Double-submit, compared against the digest stored on **this** session row.

    A staff CSRF token cannot satisfy this: it was never hashed onto a
    ``customer_sessions`` row, so there is nothing for it to equal (DEC-0005).
    """
    if not header_token:
        return False
    return hmac.compare_digest(record.csrf_token_hash, hash_token(header_token))


def revoke_session(db: Session, record: CustomerSession, *, reason_code: str) -> None:
    """Revoke one session server-side.

    Clearing the cookie is not a sign-out: a copy of the value taken before it was cleared
    would still resolve. This is the revocation that makes the copy useless.
    """
    if record.revoked_at is None:
        record.revoked_at = utcnow()
    audit.session_revoked(db, identity_id=record.identity_id, reason_code=reason_code, count=1)


def revoke_all_sessions(
    db: Session,
    identity: CustomerIdentity,
    *,
    reason_code: str,
    except_session_id: int | None = None,
) -> int:
    """Revoke every live session for an identity. Returns how many.

    A single ``UPDATE`` rather than a load-and-loop, so a concurrent request cannot slip a
    session past between the read and the write.
    """
    conditions = [
        CustomerSession.identity_id == identity.id,
        CustomerSession.revoked_at.is_(None),
    ]
    if except_session_id is not None:
        conditions.append(CustomerSession.id != except_session_id)
    result = db.execute(update(CustomerSession).where(*conditions).values(revoked_at=utcnow()))
    count = int(result.rowcount or 0)
    audit.session_revoked(db, identity_id=identity.id, reason_code=reason_code, count=count)
    return count


def validate_password(password: str) -> None:
    """Length, and a refusal of the handful of passwords everybody tries first.

    Length only, plus a rejected-common-password check. No composition rules: they push
    people toward ``Password1!``, which is in every breach corpus
    (`RATE_LIMITS_AND_ABUSE.md` section 5).
    """
    if len(password) < settings.account_min_password_length:
        raise ValidationError(
            f"Use at least {settings.account_min_password_length} characters.", field="password"
        )
    if password.strip() != password:
        raise ValidationError("Password cannot start or end with a space.", field="password")
    if password.strip().lower() in COMMON_PASSWORDS:
        raise ValidationError("Choose a less common password.", field="password")


#: The sentences the registration and reset forms show beside the second password box, so
#: the screen and the server say the same thing (UAT round 8).
PASSWORD_CONFIRMATION_MISSING = "Type the password again to confirm it."
PASSWORD_CONFIRMATION_MISMATCH = "The two passwords do not match."


def confirm_password(password: str, confirmation: str | None) -> None:
    """The password typed twice must match. Checked after ``validate_password``.

    After, so a short password is reported as short rather than as a mismatch. Compared
    exactly, as the password itself is: no trimming, no case folding.
    """
    if not confirmation:
        raise ValidationError(PASSWORD_CONFIRMATION_MISSING, field="password_confirmation")
    if confirmation != password:
        raise ValidationError(PASSWORD_CONFIRMATION_MISMATCH, field="password_confirmation")


#: A deliberately short list of the passwords that survive a twelve-character minimum and
#: are still first in every spraying dictionary. Not a corpus: a real one is a data file and
#: a maintenance commitment, and this is the cheap half of the benefit. Recorded as a known
#: limitation rather than presented as a policy.
COMMON_PASSWORDS = frozenset(
    {
        "password1234",
        "passw0rd1234",
        "qwertyuiop12",
        "123456789012",
        "letmein12345",
        "iloveyou1234",
        "welcome12345",
        "adminadmin12",
        "solarisexpress",
        "solaris12345",
    }
)


def set_password(db: Session, identity: CustomerIdentity, *, password: str) -> None:
    """Hash and store a new password. The plaintext is never retained."""
    validate_password(password)
    identity.password_hash = hash_password(password)
    identity.failed_sign_in_count = 0
    identity.locked_until = None
