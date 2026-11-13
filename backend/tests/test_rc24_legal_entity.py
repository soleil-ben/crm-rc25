"""RC-UAT-24 (owner Ben, 2026-10-24; DEC-0236, I-10): the legal entity is Solaris Express Inc.

Settings shows it (read-only), the login footer and the demo label sender carry it, and an
existing database whose settings row still holds the old model default is renamed by migration
``e7a9c1d3f5b6`` -- a name set to anything else is left alone.
"""

from __future__ import annotations

import importlib.util
import sqlite3
from pathlib import Path

from app import seed
from app.models import OrganizationSettings
from tests.test_migrations_phase13c import _alembic

NEW = "Solaris Express Inc."
OLD = "Soleil Global Transportation Inc."
BEFORE = "d4f6b8c0e2a5"
HEAD = "e7a9c1d3f5b6"
REPO = Path(__file__).resolve().parents[2]


def test_settings_show_solaris_express_inc(as_admin):
    body = as_admin.get("/api/v1/settings")
    assert body.status_code == 200, body.text
    assert body.json()["legal_entity_name"] == NEW


def test_a_new_settings_row_defaults_to_solaris_express_inc(db):
    row = OrganizationSettings()
    db.add(row)
    db.flush()
    assert row.legal_entity_name == NEW


def test_the_label_senders_are_solaris_express_inc():
    assert seed.DEMO_SENDER_CA["company"] == NEW
    spec = importlib.util.spec_from_file_location(
        "render_sample_labels", REPO / "scripts" / "render_sample_labels.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.SENDER_CA["company"] == NEW


def _insert_settings(path: Path, name: str) -> None:
    with sqlite3.connect(path) as c:
        c.execute(
            "INSERT INTO organization_settings (brand_name, legal_entity_name, office_timezone, "
            "default_currency, tracking_base_url, lifecycle_new_days, lifecycle_active_days, "
            "lifecycle_at_risk_days, rule_first_delivery_follow_up_enabled, "
            "rule_first_delivery_follow_up_days, rule_at_risk_task_enabled, "
            "rule_exception_task_enabled, is_demo_environment, created_at, updated_at) "
            "VALUES ('Solaris Express', ?, 'America/Toronto', 'CAD', 'https://t.example.test', "
            "30, 90, 180, 0, 7, 0, 0, 0, '2026-10-01 00:00:00', '2026-10-01 00:00:00')",
            (name,),
        )


def _names(path: Path) -> list[str]:
    with sqlite3.connect(path) as c:
        rows = c.execute("SELECT legal_entity_name FROM organization_settings ORDER BY id")
        return [row[0] for row in rows]


def test_the_migration_renames_only_the_old_default_and_downgrades(tmp_path):
    path = tmp_path / "org.db"
    url = f"sqlite:///{path.as_posix()}"
    assert _alembic(url, "upgrade", BEFORE).returncode == 0
    _insert_settings(path, OLD)
    _insert_settings(path, "Somebody Typed This Ltd.")
    upgraded = _alembic(url, "upgrade", HEAD)
    assert upgraded.returncode == 0, upgraded.stdout + upgraded.stderr
    assert _names(path) == [NEW, "Somebody Typed This Ltd."]
    assert _alembic(url, "downgrade", BEFORE).returncode == 0
    assert _names(path) == [OLD, "Somebody Typed This Ltd."]
