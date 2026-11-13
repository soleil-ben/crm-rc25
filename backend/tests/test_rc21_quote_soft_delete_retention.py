"""RC-UAT-21 Phase D (DEC-0233): Admin soft delete of old quotes, and retention machinery.

* Soft delete: Admin only, reason required, audited; refused for drafts, open offers, accepted
  quotes of a shipment not invoiced, live draft invoices and issued invoices, and versions
  younger than the minimum age; the rows stay; deleted versions disappear from the staff
  lists, the printable document, the Customer Account and accepted-not-invoiced; they cannot
  be sent or invoiced; restore (Admin, reason, audited) brings them back.
* Retention: off by default and the worker then does nothing at all (even ``--once``); a dry
  run counts and changes nothing; enabling needs the typed confirmation, then a class needs
  a period; a real run touches only eligible rows of enabled classes, in batches, never
  financial or audit records, and records a run row and an audit event. Admin only.
"""

from __future__ import annotations

import json
from datetime import timedelta
from uuid import uuid4

import pytest

from app.core.enums import Role
from app.core.time_utils import utcnow
from app.models import (
    AuditEvent,
    Customer,
    CustomerInvoice,
    DataRetentionPolicy,
    DataRetentionRun,
    NotificationOutbox,
    QuoteLine,
    QuoteOffer,
    QuoteVersion,
    QuoteVersionDeletion,
    UserSession,
)
from app.services import data_retention_service as drs
from app.services import finance_service as fs
from app.services import invoice_draft_service as drafts
from app.services import pricing_service as ps
from app.services import quote_deletion_service as qds
from app.services import quote_offer_service as qos
from app.services.errors import ConflictError, NotFoundError, ValidationError
from app.workers import retention_worker
from tests.conftest import add_shipment, make_customer, see_committed_changes
from tests.test_migrations_phase13c import _alembic, _tables
from tests.test_quote_offers import _fee, _finalize, _identity_for, _send
from tests.test_quotes import priced_world  # noqa: F401 - fixture


def _audits(db, action):
    return db.query(AuditEvent).filter_by(action=action).all()


def _superseded(db, shipment):
    """v1 finalised then superseded by v2; returns (v1, v2)."""
    v1 = _finalize(db, shipment)
    _fee(db, shipment, quantity=1)
    v2 = _finalize(db, shipment)
    db.refresh(v1)
    assert v1.status == "superseded"
    return v1, v2


# === Soft delete ===============================================================================


def test_a_superseded_version_is_soft_deleted_with_a_reason_and_audited(db, priced_world):  # noqa: F811
    _con, kids = priced_world
    v1, _v2 = _superseded(db, kids[2])
    with pytest.raises(ValidationError, match="reason"):
        qds.soft_delete(db, v1, reason="  ", actor=None)
    row = qds.soft_delete(db, v1, reason="Old superseded quote", actor=None)
    db.commit()
    assert row.quote_version_id == v1.id and row.version == 1 and row.restored_at is None
    # The quote record stays, lines and all.
    assert db.get(QuoteVersion, v1.id) is not None
    assert db.query(QuoteLine).filter_by(version_id=v1.id).count() > 0
    audit = _audits(db, "quote.soft_delete")[-1]
    assert audit.entity_id == str(v1.id)
    assert json.loads(audit.detail_json)["reason"] == "Old superseded quote"
    with pytest.raises(ConflictError) as caught:
        qds.soft_delete(db, v1, reason="again", actor=None)
    assert caught.value.detail["code"] == "already_deleted"


def test_refusals_draft_open_offer_draft_invoice_accepted_and_issued(db, priced_world):  # noqa: F811
    _con, kids = priced_world
    shipment = kids[2]
    ps.reprice(db, shipment, actor=None)
    db.commit()
    draft = ps.open_draft(db, shipment.id)
    assert qds.refusal(db, draft) == "draft"
    ps.confirm_rate(db, shipment, rate=None, reason=None, actor=None)
    version = ps.finalize(db, shipment, negative_margin_reason="test", actor=None)
    db.commit()
    assert qds.refusal(db, version) is None  # finalised, never sent: allowed
    offer = _send(db, shipment)
    assert qds.refusal(db, version) == "open_offer"
    qos.accept(db, offer, _identity_for(db, db.get(Customer, shipment.customer_id)))
    db.commit()
    assert qds.refusal(db, version) == "live_draft_invoice"
    drafts.withdraw(db, drafts.live_for_shipment(db, shipment.id), reason="test", actor=None)
    db.commit()
    assert qds.refusal(db, version) == "accepted_not_invoiced"
    with pytest.raises(ConflictError) as caught:
        qds.soft_delete(db, version, reason="x", actor=None)
    assert caught.value.detail["code"] == "accepted_not_invoiced"

    other = kids[1]
    unsent = _finalize(db, other)
    invoice = fs.issue_invoice(db, other, actor=None)
    db.commit()
    assert qds.refusal(db, unsent) == "issued_invoice"
    fs.void_invoice(db, invoice, "issued in error", actor=None)
    db.commit()
    assert qds.refusal(db, unsent) is None


def test_the_minimum_age_is_configurable_and_defaults_to_zero(db, priced_world):  # noqa: F811
    _con, kids = priced_world
    version = _finalize(db, kids[0])
    assert drs.read_settings(db).quote_delete_min_age_days == 0
    assert qds.refusal(db, version) is None
    drs.update_settings(db, {"quote_delete_min_age_days": 30}, actor=None)
    db.commit()
    assert qds.refusal(db, version) == "too_recent"
    assert qds.refusal(db, version, now=utcnow() + timedelta(days=31)) is None
    with pytest.raises(ValidationError):
        drs.update_settings(db, {"quote_delete_min_age_days": -1}, actor=None)


def test_deleted_versions_disappear_and_cannot_be_sent_or_invoiced(db, priced_world, api_for):  # noqa: F811
    _con, kids = priced_world
    shipment = kids[2]
    v1 = _finalize(db, shipment)
    first = _send(db, shipment)
    _fee(db, shipment, quantity=1)
    v2 = _finalize(db, shipment)  # withdraws the v1 offer
    db.refresh(first)
    assert first.status == "withdrawn"
    customer_id = shipment.customer_id
    assert [o.id for o in qos.list_for_customer(db, customer_id)] == [first.id]
    qds.soft_delete(db, v1, reason="old", actor=None)
    db.commit()
    see_committed_changes(db)

    admin = api_for(Role.ADMIN)
    quotes = admin.get(f"/api/v1/shipments/{shipment.id}/quotes").json()
    assert [q["version"] for q in quotes] == [2]
    assert admin.get(f"/api/v1/shipments/{shipment.id}/quote-offers").json() == []
    assert admin.get(f"/api/v1/shipments/{shipment.id}/quotes/1/document").status_code == 404
    assert admin.get(f"/api/v1/shipments/{shipment.id}/quotes/2/document").status_code == 200
    # The Customer Account: as for an unknown quote.
    assert qos.list_for_customer(db, customer_id) == []
    with pytest.raises(NotFoundError):
        qos.owned_offer(db, first.id, customer_id)
    # The history shows it only on request.
    history = admin.get(f"/api/v1/shipments/{shipment.id}/quote-history").json()
    assert [r["version"] for r in history["items"]] == [2]
    history = admin.get(
        f"/api/v1/shipments/{shipment.id}/quote-history", params={"include_deleted": True}
    ).json()
    deleted = [r for r in history["items"] if r["deleted"]]
    assert [r["version"] for r in deleted] == [1] and deleted[0]["deleted"]["reason"] == "old"

    # The latest finalised version deleted: neither sent nor invoiced until restored.
    see_committed_changes(db)
    qds.soft_delete(db, v2, reason="abandoned", actor=None)
    db.commit()
    with pytest.raises(ConflictError) as caught:
        qos.send_quote(db, shipment, actor=None)
    assert caught.value.detail["code"] == "quote_deleted"
    db.rollback()
    with pytest.raises(ConflictError) as caught:
        fs.issue_invoice(db, shipment, actor=None)
    assert caught.value.detail["code"] == "quote_deleted"
    db.rollback()
    qds.restore(db, v2, reason="needed after all", actor=None)
    db.commit()
    assert _send(db, shipment).quote_version_id == v2.id


def test_accepted_not_invoiced_leaves_out_a_deleted_version(db, priced_world):  # noqa: F811
    _con, kids = priced_world
    shipment = kids[0]
    version = _finalize(db, shipment)
    offer = _send(db, shipment)
    qos.accept(db, offer, _identity_for(db, db.get(Customer, shipment.customer_id)))
    db.commit()
    rows, total = qos.accepted_not_invoiced(db)
    assert total == 1 and rows[0][0].id == offer.id
    # Not reachable through soft_delete (refused); the list still leaves a deleted one out.
    db.add(
        QuoteVersionDeletion(
            quote_version_id=version.id,
            shipment_id=shipment.id,
            version=version.version,
            reason="direct",
            deleted_at=utcnow(),
        )
    )
    db.commit()
    assert qos.accepted_not_invoiced(db) == ([], 0)


def test_restore_needs_a_reason_is_audited_and_history_is_kept(db, priced_world):  # noqa: F811
    _con, kids = priced_world
    v1, _v2 = _superseded(db, kids[1])
    with pytest.raises(ConflictError):
        qds.restore(db, v1, reason="nothing to restore", actor=None)
    qds.soft_delete(db, v1, reason="first", actor=None)
    db.commit()
    with pytest.raises(ValidationError):
        qds.restore(db, v1, reason="", actor=None)
    qds.restore(db, v1, reason="mistake", actor=None)
    db.commit()
    assert not qds.is_deleted(db, v1.id)
    assert json.loads(_audits(db, "quote.restore")[-1].detail_json)["reason"] == "mistake"
    qds.soft_delete(db, v1, reason="second", actor=None)
    db.commit()
    rows = db.query(QuoteVersionDeletion).filter_by(quote_version_id=v1.id).all()
    assert sorted(r.reason for r in rows) == ["first", "second"]
    assert sum(1 for r in rows if r.restored_at is None) == 1


def test_only_admin_deletes_restores_or_reads_the_history(db, priced_world, api_for):  # noqa: F811
    _con, kids = priced_world
    v1, _v2 = _superseded(db, kids[2])
    see_committed_changes(db)
    sid = kids[2].id
    for role in (Role.OPERATIONS, Role.MARKETING, Role.READ_ONLY_MANAGER):
        api = api_for(role)
        assert api.get(f"/api/v1/shipments/{sid}/quote-history").status_code == 403
        assert (
            api.post(f"/api/v1/quote-versions/{v1.id}/delete", json={"reason": "x"}).status_code
            == 403
        )
        assert (
            api.post(f"/api/v1/quote-versions/{v1.id}/restore", json={"reason": "x"}).status_code
            == 403
        )
    admin = api_for(Role.ADMIN)
    assert admin.post(f"/api/v1/quote-versions/{v1.id}/delete", json={}).status_code == 422
    assert (
        admin.post("/api/v1/quote-versions/999999/delete", json={"reason": "x"}).status_code == 404
    )
    done = admin.post(f"/api/v1/quote-versions/{v1.id}/delete", json={"reason": "Old v1"})
    assert done.status_code == 200, done.text
    assert [r["version"] for r in done.json()["items"] if r["deleted"]] == [1]
    again = admin.post(f"/api/v1/quote-versions/{v1.id}/delete", json={"reason": "Old v1"})
    assert again.status_code == 409
    back = admin.post(f"/api/v1/quote-versions/{v1.id}/restore", json={"reason": "Back"})
    assert back.status_code == 200 and not any(r["deleted"] for r in back.json()["items"])
    latest = next(r for r in back.json()["items"] if r["version"] == 2)
    assert latest["status"] == "finalized" and latest["deletable"] is True


# === Retention =================================================================================


def _session(db, user, *, expires_days: float, revoked_days: float | None = None):
    now = utcnow()
    row = UserSession(
        user_id=user.id,
        session_token_hash=uuid4().hex + uuid4().hex,
        csrf_token_hash="x" * 64,
        created_at=now - timedelta(days=400),
        last_seen_at=now - timedelta(days=400),
        expires_at=now + timedelta(days=expires_days),
        revoked_at=now + timedelta(days=revoked_days) if revoked_days is not None else None,
    )
    db.add(row)
    return row


def _outbox(db, shipment, *, status: str, days_ago: int):
    at = utcnow() - timedelta(days=days_ago)
    row = NotificationOutbox(
        dedup_key=f"{shipment.id}:{uuid4().hex[:20]}",
        shipment_id=shipment.id,
        milestone="received",
        channel="email",
        language="vi",
        template_key="milestone.received.vi",
        template_version="1",
        status=status,
        created_at=at,
        processed_at=None if status == "queued" else at,
    )
    db.add(row)
    return row


@pytest.fixture
def retention_world(db, users):
    admin = users[Role.ADMIN]
    shipment = add_shipment(db, make_customer(db, email="r@demo.example.com"))
    for _ in range(5):
        _session(db, admin, expires_days=-100)  # expired long ago
    _session(db, admin, expires_days=30, revoked_days=-90)  # revoked long ago
    _session(db, admin, expires_days=-1)  # expired yesterday: inside the period
    _session(db, admin, expires_days=30)  # live
    for _ in range(3):
        _outbox(db, shipment, status="sent", days_ago=100)
    _outbox(db, shipment, status="queued", days_ago=100)  # never: still to send
    _outbox(db, shipment, status="skipped", days_ago=5)  # inside the period
    db.commit()
    return shipment


def _counts(db):
    return db.query(UserSession).count(), db.query(NotificationOutbox).count()


def test_defaults_are_all_off_and_undecided(db):
    settings = drs.read_settings(db)
    assert settings.enabled is False and settings.quote_delete_min_age_days == 0
    policies = drs.read_policies(db)
    assert [p.record_class for p in policies] == list(drs.RECORD_CLASSES)
    assert all(p.enabled is False and p.period_days is None for p in policies)


def test_disabled_the_worker_does_nothing_even_with_once(
    db, session_factory, retention_world, capsys
):
    before = _counts(db)
    audits = db.query(AuditEvent).count()
    assert retention_worker.main(["--once"], session_factory=session_factory) == 0
    assert "nothing was done" in capsys.readouterr().out
    see_committed_changes(db)
    assert _counts(db) == before
    assert db.query(DataRetentionRun).count() == 0
    assert db.query(AuditEvent).count() == audits
    # A period alone does not run it either: the switch is off.
    drs.update_policy(db, "staff_sessions_ended", {"period_days": 30}, actor=None)
    db.commit()
    assert drs.run(db) is None
    assert _counts(db) == before
    with pytest.raises(SystemExit):
        retention_worker.main([], session_factory=session_factory)


def test_a_dry_run_counts_and_changes_nothing(db, session_factory, retention_world, capsys):
    drs.update_policy(db, "staff_sessions_ended", {"period_days": 30}, actor=None)
    drs.update_policy(db, "notification_outbox_processed", {"period_days": 30}, actor=None)
    db.commit()
    before = _counts(db)
    assert retention_worker.main(["--once", "--dry-run"], session_factory=session_factory) == 0
    out = json.loads(capsys.readouterr().out)
    see_committed_changes(db)
    assert _counts(db) == before
    counts = out["counts"]
    assert counts["staff_sessions_ended"]["eligible"] == 6
    assert counts["notification_outbox_processed"]["eligible"] == 3
    assert counts["customer_sessions_ended"]["eligible"] is None  # undecided
    assert counts["staff_sessions_ended"]["would_run"] is False  # the switch is off
    run = db.query(DataRetentionRun).one()
    assert run.dry_run is True and run.trigger == "worker"
    assert _audits(db, "data_retention.dry_run")


def test_enabling_needs_the_typed_confirmation_then_a_period(db):
    with pytest.raises(ValidationError, match="Turn retention deletion on"):
        drs.update_policy(
            db, "staff_sessions_ended", {"enabled": True, "period_days": 5}, actor=None
        )
    db.rollback()
    with pytest.raises(ValidationError, match="ENABLE RETENTION"):
        drs.update_settings(db, {"enabled": True, "confirmation": "yes"}, actor=None)
    db.rollback()
    drs.update_settings(db, {"enabled": True, "confirmation": "ENABLE RETENTION"}, actor=None)
    db.commit()
    assert drs.read_settings(db).enabled and _audits(db, "data_retention.enable")
    with pytest.raises(ValidationError, match="period"):
        drs.update_policy(db, "staff_sessions_ended", {"enabled": True}, actor=None)
    db.rollback()
    with pytest.raises(ValidationError, match="allows"):
        drs.update_policy(db, "staff_sessions_ended", {"action": "anonymise"}, actor=None)
    db.rollback()
    with pytest.raises(NotFoundError):
        drs.update_policy(db, "customer_invoices", {"period_days": 1}, actor=None)
    db.rollback()
    drs.update_policy(db, "staff_sessions_ended", {"enabled": True, "period_days": 5}, actor=None)
    db.commit()
    assert _audits(db, "data_retention.policy_update")
    # Turning the switch off disables every class again.
    drs.update_settings(db, {"enabled": False}, actor=None)
    db.commit()
    assert db.get(DataRetentionPolicy, "staff_sessions_ended").enabled is False
    assert _audits(db, "data_retention.disable")


def _enable(db, **periods):
    drs.update_settings(db, {"enabled": True, "confirmation": drs.CONFIRMATION_PHRASE}, actor=None)
    for key, days in periods.items():
        drs.update_policy(db, key, {"enabled": True, "period_days": days}, actor=None)
    db.commit()


def test_an_enabled_class_deletes_only_eligible_rows_in_batches(
    db, session_factory, retention_world, capsys
):
    _enable(db, staff_sessions_ended=30, notification_outbox_processed=30)
    invoices = db.query(CustomerInvoice).count()
    audits = db.query(AuditEvent).count()
    code = retention_worker.main(["--once", "--batch-size", "2"], session_factory=session_factory)
    assert code == 0
    out = json.loads(capsys.readouterr().out)
    see_committed_changes(db)
    assert out["counts"]["staff_sessions_ended"]["affected"] == 6
    assert out["counts"]["notification_outbox_processed"]["affected"] == 3
    assert out["counts"]["customer_sessions_ended"]["ran"] is False
    # Left: the session expired yesterday, the live one; the queued and the recent outbox row.
    assert _counts(db) == (2, 2)
    assert {r.status for r in db.query(NotificationOutbox)} == {"queued", "skipped"}
    policy = db.get(DataRetentionPolicy, "staff_sessions_ended")
    assert policy.last_run_affected == 6 and policy.last_run_at is not None
    run = db.query(DataRetentionRun).filter_by(dry_run=False).one()
    assert run.status == "completed"
    assert _audits(db, "data_retention.run")
    # Never a financial or an audit record.
    assert db.query(CustomerInvoice).count() == invoices
    assert db.query(AuditEvent).count() > audits


def test_soft_deleted_quotes_are_purged_unless_an_invoice_refers_to_them(db, priced_world):  # noqa: F811
    _con, kids = priced_world
    v1, _v2 = _superseded(db, kids[2])
    other = kids[1]
    invoiced = _finalize(db, other)
    invoice = fs.issue_invoice(db, other, actor=None)
    db.commit()
    fs.void_invoice(db, invoice, "issued in error", actor=None)
    db.commit()
    old = utcnow() - timedelta(days=60)
    for version in (v1, invoiced):
        qds.soft_delete(db, version, reason="old", actor=None, now=old)
    db.commit()
    _enable(db, soft_deleted_quotes=30)
    run = drs.run(db)
    see_committed_changes(db)
    assert json.loads(run.counts_json)["soft_deleted_quotes"]["affected"] == 1
    assert db.get(QuoteVersion, v1.id) is None
    assert db.query(QuoteLine).filter_by(version_id=v1.id).count() == 0
    purged = db.query(QuoteVersionDeletion).filter_by(version=1, shipment_id=kids[2].id).one()
    assert purged.quote_version_id is None and purged.purged_at is not None
    # Referenced by a (void) invoice: a financial record, so the version stays.
    assert db.get(QuoteVersion, invoiced.id) is not None
    assert db.get(CustomerInvoice, invoice.id) is not None


def test_no_record_class_reaches_a_financial_or_audit_table():
    for spec in drs.RECORD_CLASSES.values():
        assert not set(spec.tables) & drs.FORBIDDEN_TABLES, spec.key
        assert set(spec.allowed_actions) <= {"delete", "anonymise"}
    for forbidden in ("customer_invoices", "customer_payments", "vendor_invoices", "audit_events"):
        assert forbidden in drs.FORBIDDEN_TABLES


def test_closed_offers_are_anonymised_not_deleted(db, priced_world):  # noqa: F811
    _con, kids = priced_world
    _finalize(db, kids[0])
    offer = _send(db, kids[0])
    qos.withdraw(db, offer, reason="Wrong weight for Nguyễn", actor=None)
    db.commit()
    offer.updated_at = utcnow() - timedelta(days=90)
    db.commit()
    _enable(db, closed_quote_offers=30)
    drs.run(db)
    see_committed_changes(db)
    kept = db.get(QuoteOffer, offer.id)
    assert kept is not None and kept.status == "withdrawn" and kept.withdrawn_reason is None


def test_only_admin_reads_or_changes_retention(api_for, db):
    for role in (Role.OPERATIONS, Role.MARKETING, Role.READ_ONLY_MANAGER):
        api = api_for(role)
        assert api.get("/api/v1/admin/data-retention").status_code == 403
        assert api.patch("/api/v1/admin/data-retention/settings", json={}).status_code == 403
        assert (
            api.patch(
                "/api/v1/admin/data-retention/policies/staff_sessions_ended", json={}
            ).status_code
            == 403
        )
        assert api.post("/api/v1/admin/data-retention/dry-run").status_code == 403
    admin = api_for(Role.ADMIN)
    body = admin.get("/api/v1/admin/data-retention").json()
    assert body["settings"]["enabled"] is False
    assert len(body["policies"]) == len(drs.RECORD_CLASSES)
    assert all(not p["enabled"] and p["period_days"] is None for p in body["policies"])
    refused = admin.patch(
        "/api/v1/admin/data-retention/settings", json={"enabled": True, "confirmation": "no"}
    )
    assert refused.status_code == 422
    period = admin.patch(
        "/api/v1/admin/data-retention/policies/staff_sessions_ended", json={"period_days": 90}
    )
    assert period.status_code == 200 and period.json()["period_days"] == 90
    cleared = admin.patch(
        "/api/v1/admin/data-retention/policies/staff_sessions_ended", json={"period_days": None}
    )
    assert cleared.json()["period_days"] is None
    assert (
        admin.patch("/api/v1/admin/data-retention/policies/audit_events", json={}).status_code
        == 404
    )
    dry = admin.post("/api/v1/admin/data-retention/dry-run")
    assert dry.status_code == 200 and dry.json()["dry_run"] is True
    assert admin.get("/api/v1/admin/data-retention").json()["runs"][0]["trigger"] == "admin"


def test_the_migration_adds_four_tables_seeded_off(tmp_path):
    import sqlite3

    path = tmp_path / "m.db"
    url = f"sqlite:///{path.as_posix()}"
    assert _alembic(url, "upgrade", "head").returncode == 0
    tables = _tables(path)
    for name in (
        "quote_version_deletions",
        "data_retention_settings",
        "data_retention_policies",
        "data_retention_runs",
    ):
        assert name in tables
    with sqlite3.connect(path) as c:
        assert c.execute("select enabled from data_retention_settings").fetchall() == [(0,)]
        rows = c.execute("select record_class, enabled, period_days from data_retention_policies")
        rows = rows.fetchall()
    assert sorted(r[0] for r in rows) == sorted(drs.RECORD_CLASSES)
    assert all(r[1] == 0 and r[2] is None for r in rows)
    assert _alembic(url, "downgrade", "b2d4f6a8c1e3").returncode == 0
    assert "quote_version_deletions" not in _tables(path)


# === Review fixes (L10a, L10b) =================================================================


def test_a_soft_deleted_version_is_never_the_latest_or_superseding_one(db, priced_world):  # noqa: F811
    """L10a: the draft's "newer quote" warning and the invoice's latest finalised version
    ignore a version an Admin soft-deleted."""
    _con, kids = priced_world
    shipment = kids[2]
    _finalize(db, shipment)
    offer = _send(db, shipment)
    qos.accept(db, offer, _identity_for(db, db.get(Customer, shipment.customer_id)))
    db.commit()
    draft = drafts.live_for_shipment(db, shipment.id)
    _fee(db, shipment, quantity=1)
    v2 = _finalize(db, shipment)
    assert drafts.superseding_version(db, draft).id == v2.id
    assert fs._latest_finalized(db, shipment.id).id == v2.id
    qds.soft_delete(db, v2, reason="priced in error", actor=None)
    db.commit()
    assert drafts.superseding_version(db, draft) is None
    assert fs._latest_finalized(db, shipment.id) is None
    qds.restore(db, v2, reason="back", actor=None)
    db.commit()
    assert drafts.superseding_version(db, draft).id == v2.id


def test_the_purge_never_removes_an_accepted_offer_or_a_draft_linked_version(db, priced_world):  # noqa: F811
    """L10b: a soft-deleted version whose offer was accepted, or whose offer a draft invoice
    names, keeps its version, offer and lines; the deletion row is not purged."""
    _con, kids = priced_world
    old = utcnow() - timedelta(days=60)
    shipment = kids[0]
    version = _finalize(db, shipment)
    offer = _send(db, shipment)
    qos.accept(db, offer, _identity_for(db, db.get(Customer, shipment.customer_id)))
    db.commit()
    # Not reachable through soft_delete (refused); written directly to test the purge.
    row = QuoteVersionDeletion(
        quote_version_id=version.id,
        shipment_id=shipment.id,
        version=version.version,
        reason="direct",
        deleted_at=old,
    )
    db.add(row)
    db.commit()
    _enable(db, soft_deleted_quotes=30)
    run = drs.run(db)
    see_committed_changes(db)
    assert json.loads(run.counts_json)["soft_deleted_quotes"]["affected"] == 0
    assert db.get(QuoteVersion, version.id) is not None
    kept = db.get(QuoteOffer, offer.id)
    assert kept is not None and kept.status == "accepted"
    assert db.query(QuoteLine).filter_by(version_id=version.id).count() > 0
    assert db.get(QuoteVersionDeletion, row.id).purged_at is None
    assert drs._count(db, drs.RECORD_CLASSES["soft_deleted_quotes"].eligible(utcnow())) == 0
