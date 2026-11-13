"""Age a Customer Account link past its expiry, for UAT case CA-REG-07.

`CA-REG-07` asks a tester to open a verification link "older than its expiry". The
verification lifetime is 24 hours, and nobody waits a day to run one case. This makes the
outstanding link for one address expired *now*, so the case can be run in the same sitting
as the registration that produced it.

What it changes, and how
------------------------
Only ``customer_auth_tokens.expires_at`` (and ``issued_at``, moved back by the same amount
so the token keeps its original lifetime) on the address's **outstanding** links -- not yet
used and not superseded. It goes through the ORM models and the application's own engine
settings, never a hand-written ``UPDATE``, and it records an audit event naming the account
reference and the purposes aged. It never reads, prints or stores a token: the link in the
captured message stays exactly what it was, and the server now refuses it as expired, which
is the behaviour under test.

Password-reset links can be aged the same way with ``--purpose password_reset``; ``all``
ages both.

Safety, in the order the checks run
-----------------------------------
1. ``ENVIRONMENT`` must be ``development`` or ``uat``. Production, ``e2e``, ``test`` and
   anything else are refused, before any application module is imported. Unset counts as
   ``development``, which is the application's own default and how the UAT stack is
   started (`docs/UAT/ENVIRONMENT.md` section 3).
2. The database must already exist. This never creates one.
3. An ``.e2e.db``, anything in the end-to-end scratch directory and anything under
   ``backups/`` are refused by name, on the resolved path.
4. The target must then be either a ``.uat.db`` inside ``data/uat/`` -- the default -- or
   the repository development database, and the development database only while
   ``ENVIRONMENT=development``. Any other path is refused: a database this script does not
   recognise is one it cannot rule out being somebody's real data.
5. The address must be on a reserved test domain (``example.com`` and the rest of
   ``app.core.demo_identity``). Every UAT registration uses one; an address that is not is
   a sign of being pointed at the wrong database.

Usage, from the repository root (on Linux and macOS the interpreter is
``backend/.venv/bin/python`` rather than ``backend/.venv/Scripts/python``)::

    backend/.venv/Scripts/python scripts/expire_account_link.py new@example.com
    backend/.venv/Scripts/python scripts/expire_account_link.py new@example.com --purpose all

Exit status: 0 when at least one link was aged, 1 when the address has no account or no
outstanding link, 2 when a safety check refused.
"""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "backend"

#: The same locations `scripts/uat_env.py` and `app.core.e2e_guard` name. Spelled here
#: rather than imported because importing the application reads its configuration, and the
#: environment check has to refuse production before that happens.
UAT_DIR = REPO_ROOT / "data" / "uat"
UAT_DB = UAT_DIR / "solaris_uat.uat.db"
UAT_DB_SUFFIX = ".uat.db"
DEV_DB = REPO_ROOT / "data" / "solaris_crm.db"
E2E_DIR = REPO_ROOT / "data" / "e2e"
E2E_DB_SUFFIX = ".e2e.db"
BACKUP_DIR = REPO_ROOT / "backups"

ALLOWED_ENVIRONMENTS = ("development", "uat")

#: ``--purpose`` value -> the token purposes it ages.
PURPOSES = {
    "verification": ("email_verification",),
    "password_reset": ("password_reset",),
    "all": ("email_verification", "password_reset"),
}

#: How far in the past the new expiry sits. A minute, not a second, so a clock a little
#: behind on the machine running the backend cannot make the link valid again.
EXPIRED_BY = timedelta(minutes=1)

AUDIT_ACTION = "customer_account.link_aged_for_testing"


class SafetyError(RuntimeError):
    """A precondition failed. Nothing was read or changed."""


@dataclass(frozen=True)
class AgedLinks:
    """What was changed. Counts and the account reference; never a token, never an address."""

    identity_public_id: str | None
    aged: dict[str, int]

    @property
    def total(self) -> int:
        return sum(self.aged.values())


# --- Safety --------------------------------------------------------------------------


def current_environment() -> str:
    return os.environ.get("ENVIRONMENT", "development").strip().lower()


def refuse_environment(environment: str) -> None:
    if environment not in ALLOWED_ENVIRONMENTS:
        raise SafetyError(
            f"ENVIRONMENT={environment!r}. This only runs in "
            f"{' or '.join(ALLOWED_ENVIRONMENTS)}; it never runs against production, an "
            "end-to-end run, or anything else."
        )


def _canonical(path: Path) -> Path:
    # ``realpath`` rather than ``Path.resolve``: on Windows it also resolves directory
    # junctions, which is the same reason `app.core.e2e_guard.canonical` uses it.
    return Path(os.path.realpath(path))


def _is_within(child: Path, parent: Path) -> bool:
    # Segment-wise, so `data/uat-old` is not taken for `data/uat`; case-folded only where
    # the filesystem folds case.
    child_parts = Path(os.path.normcase(child)).parts
    parent_parts = Path(os.path.normcase(_canonical(parent))).parts
    return child_parts[: len(parent_parts)] == parent_parts and len(child_parts) > len(parent_parts)


def validated_database(path: Path, environment: str) -> Path:
    """The database this script may change, or a refusal naming why not."""
    refuse_environment(environment)
    resolved = _canonical(path)

    if not resolved.is_file():
        raise SafetyError(f"No database at {resolved.as_posix()}. This never creates one.")
    if resolved.name.lower().endswith(E2E_DB_SUFFIX) or _is_within(resolved, E2E_DIR):
        raise SafetyError("That is an end-to-end scratch database. The browser suite owns it.")
    if _is_within(resolved, BACKUP_DIR):
        raise SafetyError("That is inside the backup directory. A backup is never a target.")

    if _is_within(resolved, UAT_DIR) and resolved.name.lower().endswith(UAT_DB_SUFFIX):
        return resolved
    if os.path.normcase(resolved) == os.path.normcase(_canonical(DEV_DB)):
        if environment != "development":
            raise SafetyError(
                f"That is the development database and ENVIRONMENT={environment!r}. Use "
                "the UAT database, or run with ENVIRONMENT=development."
            )
        return resolved
    raise SafetyError(
        f"{resolved.as_posix()} is neither a {UAT_DB_SUFFIX} database inside {UAT_DIR} nor "
        "the repository development database. This will not be pointed anywhere else."
    )


# --- The change ----------------------------------------------------------------------


def expire_links(db, email_address: str, purposes: tuple[str, ...]) -> AgedLinks:
    """Age every outstanding link of ``purposes`` for one address. The caller commits.

    Outstanding means not used and not superseded: those are already refused for their
    own reason, and ageing them would change which reason the audit log records.
    """
    from app.core.demo_identity import is_reserved_demo_email
    from app.core.normalization import normalize_email
    from app.core.time_utils import utcnow
    from app.models import CustomerAuthToken, CustomerIdentity
    from app.services import audit_service
    from sqlalchemy import select

    try:
        _, normalized = normalize_email(email_address)
    except ValueError:
        normalized = None
    if not normalized:
        raise SafetyError("That is not an email address.")
    if not is_reserved_demo_email(normalized):
        raise SafetyError(
            "That address is not on a reserved test domain. UAT registrations use "
            "example.com addresses; a real-looking one means the wrong database."
        )

    identity = db.scalar(
        select(CustomerIdentity).where(CustomerIdentity.email_normalized == normalized)
    )
    if identity is None:
        return AgedLinks(identity_public_id=None, aged=dict.fromkeys(purposes, 0))

    now = utcnow()
    target_expiry = now - EXPIRED_BY
    aged: dict[str, int] = {}
    for purpose in purposes:
        tokens = db.scalars(
            select(CustomerAuthToken).where(
                CustomerAuthToken.identity_id == identity.id,
                CustomerAuthToken.purpose == purpose,
                CustomerAuthToken.consumed_at.is_(None),
                CustomerAuthToken.invalidated_at.is_(None),
                CustomerAuthToken.expires_at > target_expiry,
            )
        ).all()
        for token in tokens:
            # Moved back as a whole, so the token keeps the lifetime it was issued with and
            # ``issued_at`` never lands after ``expires_at``.
            shift = token.expires_at - target_expiry
            token.issued_at = token.issued_at - shift
            token.expires_at = target_expiry
        aged[purpose] = len(tokens)

    if any(aged.values()):
        audit_service.record_audit(
            db,
            action=AUDIT_ACTION,
            entity_type="customer_identity",
            entity_id=identity.public_id,
            summary="Customer Account link aged past its expiry by a UAT operator script",
            detail={
                "identity_public_id": identity.public_id,
                "purposes": sorted(purpose for purpose, count in aged.items() if count),
                "count": sum(aged.values()),
            },
        )
    db.flush()
    return AgedLinks(identity_public_id=identity.public_id, aged=aged)


def run(path: Path, email_address: str, purposes: tuple[str, ...]) -> AgedLinks:
    """Open the validated database through the application's engine and age the links."""
    if str(BACKEND_ROOT) not in sys.path:
        sys.path.insert(0, str(BACKEND_ROOT))
    from app.core.db import build_engine
    from sqlalchemy.orm import sessionmaker

    engine = build_engine(f"sqlite:///{path.as_posix()}")
    try:
        factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)
        with factory() as db:
            result = expire_links(db, email_address, purposes)
            db.commit()
        return result
    finally:
        engine.dispose()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Age a Customer Account link past its expiry (UAT case CA-REG-07)."
    )
    parser.add_argument("email", help="The address the link was sent to.")
    parser.add_argument(
        "--purpose",
        choices=sorted(PURPOSES),
        default="verification",
        help="Which links to age. Default: verification.",
    )
    parser.add_argument("--path", type=Path, default=UAT_DB, help=f"Default: {UAT_DB}")
    args = parser.parse_args(argv)

    try:
        target = validated_database(args.path, current_environment())
        result = run(target, args.email, PURPOSES[args.purpose])
    except SafetyError as refused:
        print(f"Refused: {refused}", file=sys.stderr)
        return 2

    if result.identity_public_id is None:
        print("No Customer Account has that address in this database. Nothing changed.")
        return 1
    if not result.total:
        print(
            f"{result.identity_public_id} has no outstanding link of that kind (already "
            "used, superseded or expired). Nothing changed."
        )
        return 1
    for purpose, count in result.aged.items():
        print(f"{result.identity_public_id}: {count} {purpose} link(s) now expired")
    print("Open the link from the newest captured message: it is refused as expired.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
