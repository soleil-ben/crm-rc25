"""What gets written when a shipment is read, and what must never be written with it.

The granularity is the security architecture's: a denial writes an audit row, a success
writes a log line. Both are asserted over the **written artefacts** -- the rows in
`audit_events`, the records the logger emitted -- rather than over the call sites, because
"we reviewed the call sites" is not a mechanism (T-13, AC-CA-10.2).
"""

from __future__ import annotations

import json
import logging

from app.core.config import settings
from app.core.public_reference import normalize_public_reference, reference_digest
from app.models import AuditEvent
from app.services import customer_account_audit as audit
from tests.shipment_history_fixtures import (
    LIST_URL,
    detail_url,
    linked_and_signed_in,
    shipment,
)
from tests.shipment_history_fixtures import customer as make

MINE = "hanh@demo.example.com"

#: Values that must appear in no audit payload and no log line.
FORBIDDEN_IN_RECORDS = (
    MINE,
    "SolarisCustomer!2026",
    "hanh.canonical@demo.example.com",
    "+15559990001",
    "SENTINEL-RECIPIENT",
)


def _mine(account_db):
    return make(account_db, full_name="Hanh Nguyen", email="hanh.canonical@demo.example.com")


def _rows(account_db, action: str) -> list[AuditEvent]:
    account_db.rollback()
    return account_db.query(AuditEvent).filter(AuditEvent.action == action).all()


def _signed_in(account_client, account_db, account_users, captured_mail, owner):
    return linked_and_signed_in(
        account_client, captured_mail, account_users, email_address=MINE, customer=owner
    )


# --- Denials are audited ------------------------------------------------------------


def test_a_refused_detail_writes_one_audit_row_with_a_digest_and_no_reference(
    account_client, account_db, account_users, captured_mail
):
    owner = _mine(account_db)
    other = make(account_db, full_name="Other", email="other@demo.example.com")
    foreign = shipment(account_db, other, days_ago=3)
    client = _signed_in(account_client, account_db, account_users, captured_mail, owner)

    assert client.get(detail_url(foreign.public_id)).status_code == 404

    rows = _rows(account_db, audit.ACTION_SHIPMENT_ACCESS_DENIED)
    assert len(rows) == 1
    detail = json.loads(rows[0].detail_json)

    assert detail["surface"] == "detail"
    assert detail["reason_code"] == audit.REASON_SHIPMENT_NOT_FOUND
    assert detail["identity_public_id"].startswith("CA-")
    # The digest is the *keyed* one the public surface uses, so a probe that hit both can be
    # correlated by an operator and neither wrote an identifier down.
    expected = reference_digest(
        normalize_public_reference(foreign.public_id), secret=settings.secret_key
    )
    assert detail["reference_digest"] == expected
    assert foreign.public_id not in json.dumps(detail)
    assert foreign.public_id not in (rows[0].summary or "")


def test_a_refused_list_writes_a_row_with_no_digest_to_write(
    account_client, account_db, account_users, captured_mail
):
    """There is no reference on a list request, so there is nothing to digest."""
    from app.core.account_enums import LinkStatus
    from app.models import CustomerIdentityLink

    owner = _mine(account_db)
    client = _signed_in(account_client, account_db, account_users, captured_mail, owner)
    account_db.query(CustomerIdentityLink).one().status = LinkStatus.REVOKED.value
    account_db.commit()

    assert client.get(LIST_URL).status_code == 403

    rows = _rows(account_db, audit.ACTION_SHIPMENT_ACCESS_DENIED)
    assert len(rows) == 1
    detail = json.loads(rows[0].detail_json)
    assert detail["surface"] == "list"
    assert detail["reason_code"] == audit.REASON_NOT_AUTHORIZED
    assert "reference_digest" not in detail


def test_the_denial_payload_carries_the_category_not_the_internal_reason(
    account_client, account_db, account_users, captured_mail
):
    """An archived customer and a missing link are both ``not_authorized`` in the audit row.

    Which of them applies is a fact about the CRM's state -- both are ``FIELD_MATRIX.md``
    §3.4 never-fields -- and the operator-facing log carries the distinction instead.
    """
    from app.core.account_enums import LinkStatus
    from app.models import CustomerIdentityLink

    owner = _mine(account_db)
    client = _signed_in(account_client, account_db, account_users, captured_mail, owner)

    owner.is_archived = True
    account_db.commit()
    client.get(LIST_URL)

    owner.is_archived = False
    account_db.query(CustomerIdentityLink).one().status = LinkStatus.REVOKED.value
    account_db.commit()
    client.get(LIST_URL)

    rows = _rows(account_db, audit.ACTION_SHIPMENT_ACCESS_DENIED)
    assert len(rows) == 2
    reasons = set()
    for row in rows:
        detail = json.loads(row.detail_json)
        reasons.add(detail["reason_code"])
        assert "archiv" not in json.dumps(detail).lower()
        assert "link" not in json.dumps(detail).lower()
    assert reasons == {audit.REASON_NOT_AUTHORIZED}


def test_a_successful_read_writes_no_audit_row(
    account_client, account_db, account_users, captured_mail
):
    """The approved granularity: an audit row per successful read is not what was asked for.

    It would grow the audit table with ordinary browsing and would build a second copy of a
    customer's history in summaries. `RATE_LIMITS_AND_ABUSE.md` §7 watches *not-found* rates,
    not read rates, and T-03's detection line says the same.
    """
    owner = _mine(account_db)
    row = shipment(account_db, owner, days_ago=3)
    client = _signed_in(account_client, account_db, account_users, captured_mail, owner)

    before = account_db.query(AuditEvent).count()
    assert client.get(LIST_URL).status_code == 200
    assert client.get(detail_url(row.public_id)).status_code == 200
    account_db.rollback()

    assert account_db.query(AuditEvent).count() == before
    assert _rows(account_db, audit.ACTION_SHIPMENT_ACCESS_DENIED) == []


def test_the_denial_reason_vocabulary_is_closed():
    assert {"not_authorized", "shipment_not_found"} == audit.SHIPMENT_DENIAL_REASONS
    assert audit.ACTION_SHIPMENT_ACCESS_DENIED == "customer_account.shipment_access_denied"


def test_no_audit_row_from_a_read_carries_a_forbidden_value(
    account_client, account_db, account_users, captured_mail
):
    owner = _mine(account_db)
    other = make(account_db, full_name="Other", email="other@demo.example.com")
    foreign = shipment(
        account_db,
        other,
        days_ago=3,
        recipient_name="SENTINEL-RECIPIENT-NAME",
        recipient_phone_e164="+15559990001",
        selling_amount=999888.77,
    )
    client = _signed_in(account_client, account_db, account_users, captured_mail, owner)
    client.get(detail_url(foreign.public_id))
    client.get(LIST_URL)

    account_db.rollback()
    for row in account_db.query(AuditEvent).all():
        blob = json.dumps(
            {
                "summary": row.summary,
                "detail": row.detail_json,
                "action": row.action,
                "entity_id": row.entity_id,
                "actor_label": row.actor_label,
            },
            default=str,
        )
        for forbidden in FORBIDDEN_IN_RECORDS:
            assert forbidden not in blob, (row.action, forbidden)
        assert "999888" not in blob
        assert foreign.public_id not in blob


# --- Successes are logged, safely ----------------------------------------------------


def test_the_read_log_line_carries_safe_fields_only(
    account_client, account_db, account_users, captured_mail, caplog
):
    owner = _mine(account_db)
    row = shipment(account_db, owner, days_ago=3)
    client = _signed_in(account_client, account_db, account_users, captured_mail, owner)

    with caplog.at_level(logging.INFO, logger="solaris.account_shipments"):
        client.get(LIST_URL, params={"limit": 5})
        client.get(detail_url(row.public_id))

    records = [record for record in caplog.records if record.name == "solaris.account_shipments"]
    assert len(records) == 2

    listed, detail = records
    assert listed.surface == "list"
    assert listed.outcome == "ok"
    assert listed.page_size == 5
    assert listed.returned == 1
    # A keyed digest, never the `CA-` reference itself.
    assert listed.identity_digest and not listed.identity_digest.startswith("CA-")
    assert len(listed.identity_digest) == 64
    assert detail.surface == "detail"
    assert detail.reference_digest != row.public_id
    assert detail.reference_digest.isalnum()
    # The same keyed construction the public surface uses, so a probe that hit both
    # correlates for an operator and neither log holds an identifier.
    assert detail.reference_digest == reference_digest(
        normalize_public_reference(row.public_id), secret=settings.secret_key
    )


def test_no_log_line_from_a_read_carries_a_reference_or_an_address(
    account_client, account_db, account_users, captured_mail, caplog
):
    """The reference travels as a keyed digest, on this surface as on the public one.

    Logging an identifier puts it in a file, a log shipper and quite possibly a third-party
    log index -- which is what `CRM.md` section 10 forbids and what the digest exists for.
    """
    owner = _mine(account_db)
    row = shipment(account_db, owner, days_ago=3)
    client = _signed_in(account_client, account_db, account_users, captured_mail, owner)

    with caplog.at_level(logging.INFO):
        client.get(LIST_URL)
        client.get(detail_url(row.public_id))
        client.get(detail_url("SX-CAV-AAAAAAAAAAAA"))

    for record in caplog.records:
        rendered = json.dumps({key: str(value) for key, value in vars(record).items()}, default=str)
        assert row.public_id not in rendered, record.name
        for forbidden in FORBIDDEN_IN_RECORDS:
            assert forbidden not in rendered, (record.name, forbidden)


def test_a_refusal_log_line_names_the_bounded_reason_and_nothing_else(
    account_client, account_db, account_users, captured_mail, caplog
):
    """The operator-facing half: which refusal it was, as a bounded code and no more."""
    from app.services import customer_account_link_policy as policy

    owner = _mine(account_db)
    client = _signed_in(account_client, account_db, account_users, captured_mail, owner)
    owner.is_archived = True
    account_db.commit()

    with caplog.at_level(logging.INFO, logger="solaris.account_shipments"):
        assert client.get(LIST_URL).status_code == 403

    record = next(r for r in caplog.records if r.name == "solaris.account_shipments")
    assert record.outcome == f"not_authorized:{policy.REASON_CUSTOMER_ARCHIVED}"
    assert record.outcome.split(":")[1] in policy.REFUSAL_REASONS
    assert owner.public_id not in json.dumps(vars(record), default=str)


def test_a_rate_limited_read_is_logged_as_a_category_with_no_reference(
    account_client, account_db, account_users, captured_mail, caplog, monkeypatch
):
    monkeypatch.setattr(settings, "account_read_identity_attempts", 1)
    from app.core.security import rate_limiter

    owner = _mine(account_db)
    row = shipment(account_db, owner, days_ago=3)
    client = _signed_in(account_client, account_db, account_users, captured_mail, owner)
    rate_limiter.reset()

    with caplog.at_level(logging.INFO, logger="solaris.account_shipments"):
        client.get(LIST_URL)
        assert client.get(detail_url(row.public_id)).status_code == 429

    refused = [
        record
        for record in caplog.records
        if record.name == "solaris.account_shipments" and record.outcome == "rate_limited"
    ]
    assert len(refused) == 1
    # Refused before the reference was even looked at, so there is nothing to digest.
    assert refused[0].reference_digest == "none"
    assert row.public_id not in json.dumps(vars(refused[0]), default=str)
