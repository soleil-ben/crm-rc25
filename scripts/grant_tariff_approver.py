"""Give (or, with --revoke, take) the ``tariff:approve`` permission for one staff account.

``tariff:approve`` = may confirm or roll back a Kango rate sheet (DEC-0268). The account also
needs a role with ``tariff:manage`` (Admin). Audited as ``staff.permission_granted`` /
``staff.permission_revoked``.

Usage (from the repository root, against the database in ``DATABASE_URL``)::

    backend/.venv/Scripts/python scripts/grant_tariff_approver.py <staff login email>
    backend/.venv/Scripts/python scripts/grant_tariff_approver.py <staff login email> --revoke
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from sqlalchemy import func, select  # noqa: E402

from app.core.db import SessionLocal  # noqa: E402
from app.models import User  # noqa: E402
from app.services import staff_grant_service as grants  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("email")
    parser.add_argument("--revoke", action="store_true")
    args = parser.parse_args(argv)
    with SessionLocal() as db:
        user = db.scalar(select(User).where(func.lower(User.email) == args.email.strip().lower()))
        if user is None:
            print(f"No staff account with the login {args.email!r}.")
            return 1
        if args.revoke:
            changed = grants.revoke(db, user, grants.TARIFF_APPROVE, actor=None)
        else:
            changed = grants.grant(db, user, grants.TARIFF_APPROVE, actor=None)
        db.commit()
        state = ("revoked" if args.revoke else "granted") if changed else "unchanged"
        print(f"tariff:approve {state} for {user.full_name} ({user.role}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
