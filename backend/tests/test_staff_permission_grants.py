"""``tariff:approve`` as a per-account permission (owner, 2026-11-04; DEC-0268).

Ben and Louis T may confirm or roll back a Kango rate sheet. The power is a grant an Admin
gives to a named account (and takes away), audited -- not an address on a list.
"""

from __future__ import annotations

import sqlite3
import subprocess
import sys
from datetime import date
from pathlib import Path

from app.core.enums import Role
from app.models import AuditEvent
from app.services import staff_grant_service as grants
from app.services import tariff_import_service as tis
from app.services import tariff_intake_service as intake
from tests.conftest import see_committed_changes
from tests.test_quotes import WORKBOOK as OCT_12

NOV_03 = Path(__file__).parent / "fixtures" / "kango_canada_rates_2026-11-03_sanitized.xlsx"
BACKEND_ROOT = Path(__file__).resolve().parent.parent


def _draft(db):
    old = tis.import_workbook(
        db, OCT_12.read_bytes(), file_name="a.xlsx", effective_from=date(2026, 10, 12),
        label=None, actor=None,
    )  # fmt: skip
    tis.activate_version(db, old, actor=None)
    new = tis.import_workbook(
        db, NOV_03.read_bytes(), file_name="b.xlsx", effective_from=date(2026, 11, 3),
        label=None, actor=None,
    )  # fmt: skip
    db.commit()
    return old, new


def test_an_admin_grants_and_revokes_the_approver_permission(as_admin, api_for, db, users):
    admin = users[Role.ADMIN]
    old, new = _draft(db)
    assert as_admin.post(f"/api/v1/tariffs/versions/{new.id}/approve").status_code == 403
    granted = as_admin.post(f"/api/v1/staff/{admin.id}/grants/tariff:approve")
    assert granted.status_code == 200, granted.text
    assert [h["user_id"] for h in granted.json()["tariff:approve"]] == [admin.id]
    assert as_admin.post(f"/api/v1/tariffs/versions/{new.id}/approve").status_code == 200
    assert as_admin.post(f"/api/v1/tariffs/versions/{old.id}/rollback").status_code == 200
    revoked = as_admin.delete(f"/api/v1/staff/{admin.id}/grants/tariff:approve")
    assert revoked.status_code == 200 and revoked.json()["tariff:approve"] == []
    assert as_admin.post(f"/api/v1/tariffs/versions/{new.id}/rollback").status_code == 403
    see_committed_changes(db)
    actions = [e.action for e in db.query(AuditEvent)]
    assert "staff.permission_granted" in actions and "staff.permission_revoked" in actions
    # Unknown permissions are refused; only an Admin manages grants.
    assert as_admin.post(f"/api/v1/staff/{admin.id}/grants/customer:merge").status_code == 422
    ops = api_for(Role.OPERATIONS)
    assert ops.post(f"/api/v1/staff/{admin.id}/grants/tariff:approve").status_code == 403


def test_two_named_approvers_and_the_role_still_matters(db, users):
    """Both holders may approve; a grant without ``tariff:manage`` (Operations) does not."""
    admin, ops = users[Role.ADMIN], users[Role.OPERATIONS]
    grants.grant(db, admin, grants.TARIFF_APPROVE, actor=None)
    grants.grant(db, ops, grants.TARIFF_APPROVE, actor=None)
    db.commit()
    assert intake.is_approver(db, admin) is True
    assert intake.is_approver(db, ops) is False
    # The address list does not authorise on its own any more.
    assert intake.is_approver(db, users[Role.MARKETING]) is False


def test_the_legacy_approver_list_sets_the_grants(db, users):
    admin = users[Role.ADMIN]
    intake.update_settings(db, approver_emails=[admin.email], actor=None)
    db.commit()
    assert grants.has_grant(db, admin, grants.TARIFF_APPROVE)
    intake.update_settings(db, approver_emails=["nobody@demo.example.com"], actor=None)
    db.commit()
    assert not grants.has_grant(db, admin, grants.TARIFF_APPROVE)


def _alembic(url: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=BACKEND_ROOT,
        env={"PATH": "", "SYSTEMROOT": "C:\\Windows", "DATABASE_URL": url,
             "SECRET_KEY": "test-only-secret"},
        capture_output=True, text=True, check=False,
    )  # fmt: skip


def test_the_migration_seeds_the_grant_for_ben_only(tmp_path):
    path = tmp_path / "g.db"
    url = f"sqlite:///{path.as_posix()}"
    assert _alembic(url, "upgrade", "f8b0d2e4a6c8").returncode == 0
    with sqlite3.connect(path) as conn:
        for uid, email in ((1, "benjamin.le@soleiltransportation.com"), (2, "x@demo.example.com")):
            conn.execute(
                "INSERT INTO users (id, email, full_name, password_hash, role, is_active, "
                "timezone, locale, must_change_password, created_at, updated_at) VALUES "
                "(?, ?, 'N', 'h', 'admin', 1, 'America/Toronto', 'en', 0, "
                "'2026-11-04', '2026-11-04')",
                (uid, email),
            )
        # Even with another admin on a saved approver list, only Ben is seeded (owner,
        # 2026-11-04): everyone else is added later by an Admin.
        conn.execute(
            "INSERT INTO tariff_intake_settings (id, mailbox_address, approver_emails, "
            "allowed_sender_domains, updated_at) VALUES (1, 'm@demo.example.com', ?, '[]', "
            "'2026-11-04')",
            ('["benjamin.le@soleiltransportation.com", "x@demo.example.com"]',),
        )
    up = _alembic(url, "upgrade", "head")
    assert up.returncode == 0, up.stderr
    with sqlite3.connect(path) as conn:
        rows = conn.execute("select user_id, permission from staff_permission_grants").fetchall()
    assert rows == [(1, "tariff:approve")]  # Ben only
    assert _alembic(url, "downgrade", "f8b0d2e4a6c8").returncode == 0
