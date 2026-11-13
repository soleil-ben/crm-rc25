"""Phase 17 UAT dry-run fixes.

* A master milestone recorded unpublished and then published records the published one and
  queues its email once (UAT-MLS-04); a published repeat is still a repeat.
* The Customer Account session's last-seen touch is best effort for every account route: a
  lock on the touch is skipped and never fails the request; the expiry and idle checks still
  run before it.
* An invoice for a quote version whose offer staff withdrew stays allowed, and the issue
  audit notes the offer's state.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy.exc import OperationalError

from app.api.account import deps as account_deps
from app.core.config import settings
from app.core.time_utils import utcnow
from app.models import AuditEvent, CustomerSession, NotificationOutbox, ShipmentEvent
from app.services import consolidation_service as cs
from app.services import finance_service as fs
from app.services import pricing_service as ps
from app.services import public_update_templates as templates
from app.services import quote_offer_service as qos
from tests.account_fixtures import registered_and_verified, sign_in
from tests.test_consolidations import _consolidation, active_tariff, three_children  # noqa: F401
from tests.test_quotes import priced_world  # noqa: F401

# --- P1: published after unpublished -------------------------------------------------------------


def _received(published: bool) -> dict:
    payload = {"event_type": "received_at_solaris", "is_public_update": published}
    if published:
        payload["public_update_template_key"] = templates.keys_for_event_type(
            "received_at_solaris"
        )[0]
    return payload


def test_a_published_master_milestone_is_not_a_repeat_of_an_unpublished_one(
    db,
    active_tariff,  # noqa: F811
    three_children,  # noqa: F811
):
    con = _consolidation(db)
    for child in three_children[:2]:
        cs.add_member(db, con, child, actor=None)
    db.commit()

    hidden = cs.record_master_event(db, con, _received(False), actor=None)
    db.commit()
    assert len(hidden["applied"]) == 2
    assert db.query(NotificationOutbox).count() == 0  # unpublished notifies nobody

    shown = cs.record_master_event(db, con, _received(True), actor=None)
    db.commit()
    assert len(shown["applied"]) == 2 and shown["duplicates"] == []
    rows = db.query(NotificationOutbox).filter_by(milestone="received").all()
    assert len(rows) == 2  # one per shipment

    again = cs.record_master_event(db, con, _received(True), actor=None)
    db.commit()
    assert again["applied"] == [] and len(again["duplicates"]) == 2
    assert db.query(NotificationOutbox).filter_by(milestone="received").count() == 2
    published = db.query(ShipmentEvent).filter_by(
        event_type="received_at_solaris", is_public_update=True
    )
    assert published.count() == 2


def test_an_unpublished_repeat_of_a_published_milestone_is_still_a_repeat(
    db,
    active_tariff,  # noqa: F811
    three_children,  # noqa: F811
):
    con = _consolidation(db)
    cs.add_member(db, con, three_children[0], actor=None)
    db.commit()
    cs.record_master_event(db, con, _received(True), actor=None)
    db.commit()
    hidden = cs.record_master_event(db, con, _received(False), actor=None)
    assert hidden["applied"] == [] and len(hidden["duplicates"]) == 1


# --- P2: the session touch is best effort ------------------------------------------------------

ADDRESS = "touch@demo.example.com"
ME = "/api/v1/account/me"


def _locked(*_args, **_kwargs):
    raise OperationalError("UPDATE customer_sessions", {}, Exception("database is locked"))


def test_a_lock_on_the_touch_never_fails_the_request(
    account_client, account_db, captured_mail, monkeypatch
):
    registered_and_verified(account_client, captured_mail, ADDRESS)
    assert sign_in(account_client, ADDRESS).status_code == 200
    row = account_db.query(CustomerSession).one()
    row.last_seen_at = utcnow() - timedelta(minutes=5)  # stale, so the touch is attempted
    account_db.commit()
    before = row.last_seen_at

    monkeypatch.setattr(account_deps, "commit_with_retry", _locked)
    response = account_client.get(ME)
    assert response.status_code == 200, response.text
    account_db.expire_all()
    assert account_db.query(CustomerSession).one().last_seen_at == before  # touch skipped


def test_the_touch_is_committed_when_there_is_no_lock(account_client, account_db, captured_mail):
    registered_and_verified(account_client, captured_mail, ADDRESS)
    sign_in(account_client, ADDRESS)
    row = account_db.query(CustomerSession).one()
    row.last_seen_at = utcnow() - timedelta(minutes=5)
    account_db.commit()
    stale = row.last_seen_at

    assert account_client.get(ME).status_code == 200
    account_db.expire_all()
    assert account_db.query(CustomerSession).one().last_seen_at > stale


def test_the_idle_check_still_runs_before_the_touch(
    account_client, account_db, captured_mail, monkeypatch
):
    registered_and_verified(account_client, captured_mail, ADDRESS)
    sign_in(account_client, ADDRESS)
    row = account_db.query(CustomerSession).one()
    row.last_seen_at = utcnow() - timedelta(minutes=settings.account_session_idle_minutes + 1)
    account_db.commit()

    monkeypatch.setattr(account_deps, "commit_with_retry", _locked)
    assert account_client.get(ME).status_code == 401


def test_any_other_database_error_on_the_touch_propagates(monkeypatch):
    class Session:
        rolled_back = False
        dirty = {"a pending touch"}

        def rollback(self):
            self.rolled_back = True

    def broken(*_args, **_kwargs):
        raise OperationalError("UPDATE", {}, Exception("disk I/O error"))

    monkeypatch.setattr(account_deps, "commit_with_retry", broken)
    session = Session()
    with pytest.raises(OperationalError):
        account_deps.keep_session_alive(session)
    assert not session.rolled_back

    monkeypatch.setattr(account_deps, "commit_with_retry", _locked)
    account_deps.keep_session_alive(session)
    assert session.rolled_back


# --- P3: an invoice for a withdrawn offer is noted ---------------------------------------------


def _finalize(db, shipment):
    ps.confirm_rate(db, shipment, rate=None, reason=None, actor=None)
    db.commit()
    version = ps.finalize(db, shipment, negative_margin_reason="test", actor=None)
    db.commit()
    return version


def test_an_invoice_for_a_withdrawn_offer_is_allowed_and_audited(db, priced_world):  # noqa: F811
    _con, kids = priced_world
    version = _finalize(db, kids[0])
    offer = qos.send_quote(db, kids[0], actor=None)
    db.commit()
    qos.withdraw(db, offer, reason="Wrong weight", actor=None)
    db.commit()
    assert fs.closed_offer_state(db, version.id) == "withdrawn"

    invoice = fs.issue_invoice(db, kids[0], actor=None)
    db.commit()
    audit = (
        db.query(AuditEvent).filter_by(action="invoice.issue", entity_id=invoice.public_id).one()
    )
    assert "withdrawn" in audit.summary
    assert '"offer_state": "withdrawn"' in (audit.detail_json or "")


def test_an_invoice_without_a_closed_offer_notes_nothing(db, priced_world):  # noqa: F811
    _con, kids = priced_world
    version = _finalize(db, kids[1])
    assert fs.closed_offer_state(db, version.id) is None
    invoice = fs.issue_invoice(db, kids[1], actor=None)
    db.commit()
    audit = (
        db.query(AuditEvent).filter_by(action="invoice.issue", entity_id=invoice.public_id).one()
    )
    assert "withdrawn" not in audit.summary and "declined" not in audit.summary


# --- S1: the intake mailbox can be set; the first save keeps the defaults out of the audit ------


def test_the_intake_mailbox_is_set_and_the_defaults_never_reach_the_audit(db):
    from app.services import tariff_intake_service as intake
    from app.services.errors import ValidationError

    intake.update_settings(
        db,
        approver_emails=["admin@demo.example.com"],
        mailbox_address=" Tariffs@Demo.Example.com ",
        actor=None,
    )
    db.commit()
    assert intake.get_settings(db).mailbox_address == "tariffs@demo.example.com"
    detail = db.query(AuditEvent).filter_by(action="tariff_intake.settings_updated").one()
    assert "soleiltransportation" not in (detail.detail_json or "")
    assert '"old": "owner default"' in detail.detail_json
    with pytest.raises(ValidationError):
        intake.update_settings(db, mailbox_address="not an address", actor=None)


def test_the_session_touch_is_written_at_most_once_a_minute(
    account_client, account_db, captured_mail, monkeypatch
):
    """Phase 17 gate finding: an unthrottled touch made every account read take SQLite's
    write lock. Within the interval no commit is attempted at all."""
    registered_and_verified(account_client, captured_mail, ADDRESS)
    assert sign_in(account_client, ADDRESS).status_code == 200
    row = account_db.query(CustomerSession).one()
    row.last_seen_at = utcnow() - timedelta(seconds=10)
    account_db.commit()
    fresh = row.last_seen_at

    calls = []
    monkeypatch.setattr(account_deps, "commit_with_retry", lambda *a, **k: calls.append(1))
    for _ in range(3):
        assert account_client.get(ME).status_code == 200
    assert calls == []
    account_db.expire_all()
    assert account_db.query(CustomerSession).one().last_seen_at == fresh
