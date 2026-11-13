"""Follow-up task rules, address-book isolation, dashboard honesty, and migrations."""

from __future__ import annotations

import subprocess
import sys
from datetime import timedelta
from pathlib import Path

from sqlalchemy import select

from app.core.enums import TaskStatus
from app.core.time_utils import utcnow
from app.models import CustomerAddress, FollowUpTask, Interaction
from app.services import task_service
from tests.conftest import add_shipment, make_customer


def _iso(dt):
    return dt.replace(microsecond=0).isoformat()


def test_completing_one_task_leaves_others_open(as_admin, db):
    customer = make_customer(db)
    first = as_admin.post(
        "/api/v1/tasks",
        json={
            "customer_id": customer.id,
            "subject": "Call about documents",
            "due_at": _iso(utcnow() + timedelta(days=1)),
        },
    ).json()
    second = as_admin.post(
        "/api/v1/tasks",
        json={
            "customer_id": customer.id,
            "subject": "Send quote",
            "due_at": _iso(utcnow() + timedelta(days=2)),
        },
    ).json()

    response = as_admin.post(
        f"/api/v1/tasks/{first['id']}/complete", json={"outcome": "Spoke with customer"}
    )
    assert response.status_code == 200
    assert response.json()["task"]["status"] == TaskStatus.COMPLETED

    still_open = db.get(FollowUpTask, second["id"])
    assert still_open.status == TaskStatus.SCHEDULED


def test_overdue_is_derived_not_stored(as_admin, db):
    customer = make_customer(db)
    task = as_admin.post(
        "/api/v1/tasks",
        json={
            "customer_id": customer.id,
            "subject": "Overdue task",
            "due_at": _iso(utcnow() - timedelta(days=2)),
        },
    ).json()
    assert task["is_overdue"] is True
    assert "is_overdue" not in {column.name for column in FollowUpTask.__table__.columns}

    completed = as_admin.post(
        f"/api/v1/tasks/{task['id']}/complete", json={"outcome": "Done late"}
    ).json()["task"]
    assert completed["is_overdue"] is False


def test_completion_logs_an_interaction_and_updates_last_follow_up(as_admin, db):
    customer = make_customer(db)
    task = as_admin.post(
        "/api/v1/tasks",
        json={
            "customer_id": customer.id,
            "subject": "Service follow-up",
            "due_at": _iso(utcnow() - timedelta(days=1)),
        },
    ).json()
    as_admin.post(f"/api/v1/tasks/{task['id']}/complete", json={"outcome": "Customer happy"})

    interaction = db.scalar(
        select(Interaction).where(
            Interaction.customer_id == customer.id, Interaction.is_follow_up_completion.is_(True)
        )
    )
    assert interaction is not None

    detail = as_admin.get(f"/api/v1/customers/{customer.id}").json()
    assert detail["activity"]["last_follow_up_at"] is not None
    assert detail["activity"]["open_task_count"] == 0


def test_next_follow_up_is_the_earliest_open_task(as_admin, db):
    customer = make_customer(db)
    later = utcnow() + timedelta(days=10)
    sooner = utcnow() + timedelta(days=2)
    as_admin.post(
        "/api/v1/tasks",
        json={"customer_id": customer.id, "subject": "Later", "due_at": _iso(later)},
    )
    as_admin.post(
        "/api/v1/tasks",
        json={"customer_id": customer.id, "subject": "Sooner", "due_at": _iso(sooner)},
    )
    detail = as_admin.get(f"/api/v1/customers/{customer.id}").json()
    assert detail["activity"]["next_follow_up_at"].startswith(_iso(sooner)[:16])


def test_completion_can_schedule_exactly_one_next_task(as_admin, db):
    customer = make_customer(db)
    task = as_admin.post(
        "/api/v1/tasks",
        json={
            "customer_id": customer.id,
            "subject": "First",
            "due_at": _iso(utcnow() + timedelta(days=1)),
        },
    ).json()
    response = as_admin.post(
        f"/api/v1/tasks/{task['id']}/complete",
        json={
            "outcome": "Needs another call",
            "next_task": {"subject": "Second call", "due_at": _iso(utcnow() + timedelta(days=5))},
        },
    )
    assert response.status_code == 200
    assert response.json()["next_task"]["subject"] == "Second call"
    assert db.scalar(select(FollowUpTask).where(FollowUpTask.subject == "Second call")) is not None


def test_completed_task_cannot_be_completed_twice(as_admin, db):
    customer = make_customer(db)
    task = as_admin.post(
        "/api/v1/tasks",
        json={"customer_id": customer.id, "subject": "Once", "due_at": _iso(utcnow())},
    ).json()
    as_admin.post(f"/api/v1/tasks/{task['id']}/complete", json={"outcome": "Done"})
    again = as_admin.post(f"/api/v1/tasks/{task['id']}/complete", json={"outcome": "Done again"})
    assert again.status_code == 409


def test_scheduled_task_requires_a_due_date(as_admin, db):
    customer = make_customer(db)
    response = as_admin.post(
        "/api/v1/tasks",
        json={"customer_id": customer.id, "subject": "No due date", "status": "scheduled"},
    )
    assert response.status_code == 422


def test_retention_rules_do_not_create_duplicate_tasks(db):
    from app.api.deps import get_org_settings

    customer = make_customer(db, full_name="At Risk Customer")
    add_shipment(db, customer, days_ago=75)
    org = get_org_settings(db)
    db.commit()

    first = task_service.run_retention_rules(db, org)
    db.commit()
    second = task_service.run_retention_rules(db, org)
    db.commit()

    assert first["at_risk_check_in"] == 1
    assert second["at_risk_check_in"] == 0
    tasks = db.scalars(
        select(FollowUpTask).where(FollowUpTask.source_rule == "at_risk_check_in")
    ).all()
    assert len(tasks) == 1


def test_address_edit_does_not_touch_other_records(as_admin, db):
    """Address-book edits are isolated; shipment snapshots arrive in Phase 2 (AC-5)."""
    customer = make_customer(db)
    created = as_admin.post(
        f"/api/v1/customers/{customer.id}/addresses",
        json={
            "label": "Family in Vietnam",
            "contact_name": "Nguyễn Thị Bích Hạnh",
            "city": "Ho Chi Minh City",
            "country_code": "VN",
            "is_default_recipient": True,
        },
    )
    assert created.status_code == 201, created.text
    address_id = created.json()["id"]

    updated = as_admin.patch(
        f"/api/v1/addresses/{address_id}",
        json={"city": "Da Nang", "contact_name": "Nguyễn Thị Bích Hạnh"},
    )
    assert updated.status_code == 200
    assert updated.json()["city"] == "Da Nang"
    # The stored contact name keeps its diacritics.
    stored = db.get(CustomerAddress, address_id)
    assert stored.contact_name == "Nguyễn Thị Bích Hạnh"


def test_only_one_default_recipient_per_customer(as_admin, db):
    customer = make_customer(db)
    for label in ("First", "Second"):
        as_admin.post(
            f"/api/v1/customers/{customer.id}/addresses",
            json={"label": label, "contact_name": label, "is_default_recipient": True},
        )
    addresses = as_admin.get(f"/api/v1/customers/{customer.id}/addresses").json()
    assert sum(1 for address in addresses if address["is_default_recipient"]) == 1


def test_dashboard_omits_comparison_when_history_is_missing(as_admin, db):
    make_customer(db)
    body = as_admin.get("/api/v1/dashboard/summary?days=30").json()
    new_customers = next(kpi for kpi in body["kpis"] if kpi["key"] == "new_customers")
    assert new_customers["comparison_value"] is None
    assert new_customers["comparison_label"] is None
    assert any("comparison" in note for note in body["data_notes"])


def test_dashboard_queue_cards_are_labelled_current_state(as_admin, db):
    make_customer(db)
    body = as_admin.get("/api/v1/dashboard/summary?days=30").json()
    for key in ("active_shipments", "follow_ups_due", "delivery_exceptions"):
        card = next(kpi for kpi in body["kpis"] if kpi["key"] == key)
        assert card["scope"] == "current"
        assert "current state" in card["definition"].lower()
        assert card["link"]


def test_dashboard_repeat_share_is_none_without_shipments(as_admin, db):
    make_customer(db)
    body = as_admin.get("/api/v1/dashboard/summary?days=30").json()
    assert body["repeat_shipper_share"] is None
    assert any("empty rather than zero" in note for note in body["data_notes"])


def test_dashboard_repeat_share_matches_the_definition(as_admin, db):
    repeat = make_customer(db, full_name="Repeat", email="r@demo.example.com")
    once = make_customer(db, full_name="Once", email="o@demo.example.com")
    add_shipment(db, repeat, days_ago=20)
    add_shipment(db, repeat, days_ago=10)
    add_shipment(db, once, days_ago=15)

    share = as_admin.get("/api/v1/dashboard/summary?days=30").json()["repeat_shipper_share"]
    assert share["shipping_customers"] == 2
    assert share["repeat_customers"] == 1
    assert share["share"] == 0.5
    assert "not a cohort retention rate" in share["definition"]


def test_alembic_migration_runs_on_a_clean_database(tmp_path):
    """AC-20: a clean environment builds the schema from the committed migration."""
    backend_root = Path(__file__).resolve().parents[1]
    database_url = f"sqlite:///{(tmp_path / 'migrated.db').as_posix()}"
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=backend_root,
        env={
            "PATH": "",
            "SYSTEMROOT": "C:\\Windows",
            "DATABASE_URL": database_url,
            "SECRET_KEY": "test-only-secret",
            "ENVIRONMENT": "test",
        },
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr

    import sqlite3

    connection = sqlite3.connect(tmp_path / "migrated.db")
    tables = {
        row[0] for row in connection.execute("select name from sqlite_master where type='table'")
    }
    connection.close()
    assert {
        "customers",
        "follow_up_tasks",
        "consent_events",
        "saved_segments",
        "shipments",
    } <= tables
