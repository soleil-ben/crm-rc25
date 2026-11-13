"""UAT round 7: the owner's answers to PROJECT_STATUS section 37.4 (2026-10-16).

1. Staff cannot change the email of a customer whose Customer Account is active or
   suspended; the account must be deactivated first. The customer detail says so, so the
   edit form can show the rule before anybody types (see ``uatRound7.test.jsx``).
2. A suppression blocks marketing email only. Account, shipment and other operational
   email keeps sending; no module that sends email reads a suppression.
3. No notice goes to the former holder when a new registration takes over their customer;
   the takeover is audited only.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

from app.core.enums import Role
from app.models import AuditEvent, Customer, CustomerIdentity
from app.services.customer_service import LINKED_EMAIL_MESSAGE
from tests.approval_fixtures import (
    acknowledged_preview,
    approve_create,
    approve_link,
    pending_identity,
    staff,
)
from tests.conftest import make_customer, see_committed_changes

FIRST = "hanh@demo.example.com"
SECOND = "minh@demo.example.com"
CUSTOMERS = "/api/v1/customers"
IDENTITIES = "/api/v1/customer-account/identities"
APP_ROOT = Path(__file__).resolve().parents[1] / "app"


def _admin(account_client, account_users):
    return staff(account_client, account_users[Role.ADMIN].email)


def _linked_customer(account_client, account_db, account_users, captured_mail):
    reference = pending_identity(account_client, captured_mail, FIRST)
    admin = _admin(account_client, account_users)
    fingerprint = acknowledged_preview(admin, reference, "create_new")
    approved = approve_create(admin, reference, fingerprint)
    assert approved.status_code == 200, approved.text
    see_committed_changes(account_db)
    customer = (
        account_db.query(Customer).filter_by(public_id=approved.json()["customer_public_id"]).one()
    )
    return reference, customer, admin


def _detail(api, customer_id):
    response = api.get(f"{CUSTOMERS}/{customer_id}")
    assert response.status_code == 200, response.text
    return response.json()


def _patch(api, customer_id, body):
    return api.client.patch(f"{CUSTOMERS}/{customer_id}", headers=api.headers, json=body)


# --- 1. A held email is changed only after the account is deactivated -------------------


def test_the_detail_says_when_an_account_holds_the_email(
    account_client, account_db, account_users, captured_mail
):
    reference, customer, admin = _linked_customer(
        account_client, account_db, account_users, captured_mail
    )
    assert _detail(admin, customer.id)["email_held_by_account"] is True

    assert (
        admin.post(f"{IDENTITIES}/{reference}/suspend", json={"reason_code": "security_concern"})
    ).status_code == 200
    assert _detail(admin, customer.id)["email_held_by_account"] is True

    assert (
        admin.post(f"{IDENTITIES}/{reference}/deactivate", json={"reason_code": "customer_request"})
    ).status_code == 200
    assert _detail(admin, customer.id)["email_held_by_account"] is False


def test_a_customer_without_an_account_has_an_editable_email(
    account_client, account_db, account_users
):
    customer = make_customer(account_db, full_name="No Account", email="plain@demo.example.com")
    admin = _admin(account_client, account_users)
    assert _detail(admin, customer.id)["email_held_by_account"] is False
    response = _patch(admin, customer.id, {"email": "moved@demo.example.com"})
    assert response.status_code == 200
    assert response.json()["email_held_by_account"] is False


def test_the_refusal_names_the_way_out(account_client, account_db, account_users, captured_mail):
    _, customer, admin = _linked_customer(account_client, account_db, account_users, captured_mail)
    response = _patch(admin, customer.id, {"email": "other@demo.example.com"})
    assert response.status_code == 409
    body = response.json()
    assert body["field"] == "email"
    assert body["message"] == LINKED_EMAIL_MESSAGE
    assert "active or suspended" in LINKED_EMAIL_MESSAGE
    assert "Deactivate the account first" in LINKED_EMAIL_MESSAGE
    # Nothing about the address leaks into the message.
    assert FIRST not in body["message"]


def test_other_fields_of_a_held_customer_stay_editable(
    account_client, account_db, account_users, captured_mail
):
    _, customer, admin = _linked_customer(account_client, account_db, account_users, captured_mail)
    response = _patch(
        admin, customer.id, {"email": FIRST, "city": "Hue", "phone": "+1 416 555 0177"}
    )
    assert response.status_code == 200, response.text
    assert response.json()["city"] == "Hue"
    assert response.json()["email_held_by_account"] is True


def test_after_deactivation_the_email_changes_and_the_customer_record_is_audited(
    account_client, account_db, account_users, captured_mail
):
    reference, customer, admin = _linked_customer(
        account_client, account_db, account_users, captured_mail
    )
    assert (
        admin.post(f"{IDENTITIES}/{reference}/deactivate", json={"reason_code": "customer_request"})
    ).status_code == 200
    response = _patch(admin, customer.id, {"email": "moved@demo.example.com"})
    assert response.status_code == 200, response.text

    see_committed_changes(account_db)
    assert account_db.get(Customer, customer.id).email_normalized == "moved@demo.example.com"
    # The deactivated account's own sign-in email is untouched by the customer edit.
    identity = account_db.query(CustomerIdentity).filter_by(public_id=reference).one()
    assert identity.email_normalized == FIRST


# --- 2. A suppression blocks marketing email only ---------------------------------------

#: The names through which code can read a suppression.
SUPPRESSION_NAMES = {"ContactSuppression", "is_suppressed", "marketing_eligible"}


def _code_names(tree: ast.AST) -> set[str]:
    """Names and attributes used in code; docstrings and comments do not count."""
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            found.add(node.id)
        elif isinstance(node, ast.Attribute):
            found.add(node.attr)
        elif isinstance(node, ast.alias):
            found.add(node.name.rsplit(".", 1)[-1])
    return found


def _sends_email(tree: ast.AST) -> bool:
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom):
            continue
        if node.module == "app.services.account_email_service":
            return True
        if node.module == "app.services" and any(
            alias.name == "account_email_service" for alias in node.names
        ):
            return True
    return False


#: The one sender that reads a suppression, by the owner's instruction of 2026-10-20 (OD-72,
#: DEC-0209): milestone notification email respects suppressions. Account email still does not.
SUPPRESSION_READING_SENDERS = {"notification_service.py"}


def test_no_module_that_sends_email_reads_a_suppression():
    """Account email is operational and ignores marketing suppressions (owner, 2026-10-15/16).
    Milestone notification email is the named exception (owner, 2026-10-20)."""
    senders = []
    for path in sorted(APP_ROOT.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        if not _sends_email(tree) and path.name != "account_email_service.py":
            continue
        senders.append(path.name)
        if path.name in SUPPRESSION_READING_SENDERS:
            assert _code_names(tree) & SUPPRESSION_NAMES, path  # and it really does
            continue
        assert not (_code_names(tree) & SUPPRESSION_NAMES), path
    # The scan found the senders, so a passing test is not an empty one.
    assert "account_email_service.py" in senders
    assert "customer_identity_service.py" in senders
    assert "customer_account_approval_service.py" in senders
    assert "notification_service.py" in senders


# --- 3. A takeover sends nothing to the former holder ------------------------------------


def test_a_takeover_sends_nothing_to_the_former_holder(
    account_client, account_db, account_users, captured_mail
):
    first, customer, admin = _linked_customer(
        account_client, account_db, account_users, captured_mail
    )
    assert (
        admin.post(f"{IDENTITIES}/{first}/deactivate", json={"reason_code": "customer_request"})
    ).status_code == 200
    second = pending_identity(account_client, captured_mail, SECOND)
    api = staff(account_client, account_users[Role.OPERATIONS].email)
    fingerprint = acknowledged_preview(api, second, "link_existing", customer.public_id)

    before = len(captured_mail.messages)
    response = approve_link(api, second, customer.public_id, fingerprint)
    assert response.status_code == 200, response.text

    sent = captured_mail.messages[before:]
    assert [(m["to_email"], m["template_key"]) for m in sent] == [(SECOND, "account.approved")]
    for message in sent:
        assert first not in json.dumps(message)
        assert FIRST not in json.dumps(message)

    # Audited only: the unlink row against the old account is the record of it.
    see_committed_changes(account_db)
    [unlink] = account_db.query(AuditEvent).filter_by(action="customer_account.unlink").all()
    assert unlink.entity_id == first
    assert json.loads(unlink.detail_json)["reason_code"] == "taken_over_by_new_account"
