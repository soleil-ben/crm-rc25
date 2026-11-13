"""RC-UAT-21 golden tests (independent tester): black box over HTTP.

1. Shipment CSV import (DEC-0230): dry run, matching-dry-run commit gate, per-row results,
   duplicates, unknown customer, formula-like cell, limits, permissions, nothing but shipments.
2. Legacy history baseline (DEC-0230): milestones, never operational/finance/Customer Account,
   staff read, whole-baseline void (audited), idempotent re-run.
3. Customer and staff password change (DEC-0231).
4. Sign-in email change: Admin only since RC-UAT-25 item 2 (Ben, 2026-10-25); the customer's
   own change is refused (registered in docs/customer_account/SUPERSEDED_ASSERTIONS.md).
5. Admin reinstatement of a deactivated account (DEC-0231).
6. Quote GST/HST wording follows the invoice rule (DEC-0232).
7. Admin soft delete / restore of a quote version (DEC-0233).
8. Retention machinery off by default; enabling gated; a real run in the test DB (DEC-0233).

The CSV files are built here (synthetic, demo addresses). The pricing world reuses the
RC-UAT-20 golden builder. Capture transport only; air only.
"""

from __future__ import annotations

import io
import json
import re
from datetime import date, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.core.account_enums import TokenPurpose
from app.core.config import settings
from app.core.enums import Role
from app.core.time_utils import utcnow
from app.main import app
from app.models import (
    AuditEvent,
    Customer,
    CustomerAuthToken,
    CustomerInvoice,
    CustomerPayment,
    CustomerSession,
    DataRetentionRun,
    ImportBatch,
    InvoiceDraft,
    LegacyShipment,
    NotificationOutbox,
    QuoteVersion,
    QuoteVersionDeletion,
    Shipment,
    ShipmentEvent,
    UserSession,
)
from app.services import account_email_service as email
from app.services import auth_service
from app.workers import retention_worker
from tests.account_fixtures import ACCOUNT_PASSWORD
from tests.approval_fixtures import pending_identity
from tests.conftest import TEST_PASSWORD, make_customer, see_committed_changes
from tests.test_account_profile import APPLICANT, _activate
from tests.test_rc18_golden import Me, Staff
from tests.test_rc20_golden import _build, _finalize, _route

ACCOUNT = "/api/v1/account"
REVIEW = "/customer-account"
REPO = Path(__file__).resolve().parents[2]
NEW_PASSWORD = "SolarisGolden!2027"
NEW_ADDRESS = "hanh.golden@demo.example.com"


# --- Helpers ------------------------------------------------------------------------------------


def _count(db, model) -> int:
    see_committed_changes(db)
    return int(db.scalar(select(func.count()).select_from(model)) or 0)


def _counts(db, *models) -> dict[str, int]:
    return {m.__tablename__: _count(db, m) for m in models}


def _audits(db, action: str) -> list[AuditEvent]:
    see_committed_changes(db)
    return db.query(AuditEvent).filter_by(action=action).order_by(AuditEvent.id).all()


def _csv(rows: list[list[str]]) -> bytes:
    out = io.StringIO()
    import csv

    csv.writer(out, lineterminator="\n").writerows(rows)
    return out.getvalue().encode("utf-8")


def _upload(content: bytes, name: str = "golden.csv") -> dict:
    return {"file": (name, io.BytesIO(content), "text/csv")}


def _dry(api: Staff, kind: str, content: bytes, **data):
    return api.post(f"/imports/{kind}/dry-run", files=_upload(content), data=data)


def _commit(api: Staff, kind: str, content: bytes, digest: str, **data):
    form = {"content_sha256": digest, "confirm": "true", **data}
    return api.post(f"/imports/{kind}/commit", files=_upload(content), data=form)


def _owner(db) -> Customer:
    see_committed_changes(db)
    return db.query(Customer).filter_by(email_normalized=APPLICANT).one()


class Account:
    """A signed-in customer on its own TestClient; CSRF read from the cookie each call (the
    session may be rotated)."""

    def __init__(self, address: str = APPLICANT, password: str = ACCOUNT_PASSWORD) -> None:
        self.client = TestClient(app)
        response = self.client.post(
            f"{ACCOUNT}/sign-in", json={"email": address, "password": password}
        )
        assert response.status_code == 200, response.text

    def get(self, path: str):
        return self.client.get(f"{ACCOUNT}{path}")

    def post(self, path: str, body=None):
        token = self.client.cookies.get(settings.account_csrf_cookie_name)
        return self.client.post(
            f"{ACCOUNT}{path}", json=body, headers={settings.account_csrf_header_name: token}
        )


def _sign_in_status(address: str, password: str) -> int:
    return (
        TestClient(app)
        .post(f"{ACCOUNT}/sign-in", json={"email": address, "password": password})
        .status_code
    )


def _staff_login_status(address: str, password: str) -> int:
    return (
        TestClient(app)
        .post("/api/v1/auth/login", json={"email": address, "password": password})
        .status_code
    )


def _mail(mail, template: str, to: str | None = None) -> list[dict]:
    return [
        m
        for m in mail.messages
        if m["template_key"] == template and (to is None or m["to_email"].lower() == to)
    ]


def _token(message: dict) -> str:
    return message["body"].split("token=")[1].split()[0]


@pytest.fixture
def acct(account_client, account_db, account_users, captured_mail):
    reference = _activate(account_client, account_users, captured_mail)
    return {
        "db": account_db,
        "mail": captured_mail,
        "users": account_users,
        "reference": reference,
        "client": account_client,
    }


# === 1. Shipment import ===========================================================================

SHIP_HEADER = [
    "external_reference",
    "customer_ref",
    "recipient_name",
    "recipient_city",
    "recipient_country_code",
    "contents_description",
    "package_weights_kg",
    "booking_state",
    "items",
]


def _shipment_file(owner_ref: str) -> bytes:
    return _csv(
        [
            SHIP_HEADER,
            # 2, 3: valid (one draft, one confirmed)
            [
                "GT21-SHP-001",
                owner_ref,
                "Trần Thị Mẫu",
                "Toronto",
                "CA",
                "Quà tặng gia đình",
                "12.5;8",
                "draft",
                "Áo dài|2|piece|80",
            ],
            [
                "GT21-SHP-002",
                owner_ref,
                "Lê Văn Demo",
                "Mississauga",
                "CA",
                "Cà phê",
                "3",
                "confirmed",
                "",
            ],
            # 4: bad weight
            ["GT21-SHP-003", owner_ref, "Bad Row", "Toronto", "CA", "Sách", "abc", "draft", ""],
            # 5: duplicate external reference within the file
            ["GT21-SHP-001", owner_ref, "Dup Row", "Toronto", "CA", "Trà", "2", "draft", ""],
            # 6: unknown customer
            ["GT21-SHP-004", "STCA-999999", "Nobody", "Toronto", "CA", "Bánh", "1", "draft", ""],
            # 7: formula injection in an identifier cell
            ["=SUM(A1:A2)", owner_ref, "Formula", "Toronto", "CA", "Kẹo", "1", "draft", ""],
        ]
    )


IMPORT_TABLES = (Shipment, QuoteVersion, InvoiceDraft, CustomerInvoice, NotificationOutbox)


def test_shipment_import_dry_run_gate_commit_and_rerun(acct):
    db, mail, users = acct["db"], acct["mail"], acct["users"]
    owner = _owner(db).public_id
    content = _shipment_file(owner)
    admin = Staff(users[Role.ADMIN].email)
    before = _counts(db, *IMPORT_TABLES, ShipmentEvent, ImportBatch)
    mail_before = len(mail.messages)

    # Dry run: per-row report, nothing written.
    dry = _dry(admin, "shipments", content)
    assert dry.status_code == 200, dry.text
    report = dry.json()
    rows = {r["row_number"]: r for r in report["rows"]}
    codes = {n: {i["code"] for i in r["issues"]} for n, r in rows.items()}
    assert rows[2]["classification"] == rows[3]["classification"] == "ready", rows
    assert rows[4]["classification"] == "rejected", rows[4]
    assert rows[5]["classification"] == "duplicate", rows[5]
    assert rows[6]["classification"] == "rejected" and "unknown_customer" in codes[6], rows[6]
    assert rows[7]["classification"] == "rejected" and "formula_like_value" in codes[7], rows[7]
    assert report["counts"] == {"ready": 2, "duplicate": 1, "rejected": 3}, report["counts"]
    assert _counts(db, *IMPORT_TABLES, ShipmentEvent, ImportBatch) == before
    digest = report["content_sha256"]

    # Commit gates: no dry run, a different file, a different user, no confirmation.
    other = content.replace(b"GT21-SHP-002", b"GT21-SHP-099")
    assert _commit(admin, "shipments", other, digest).status_code == 409
    from app.services import bulk_import_common

    other_digest = bulk_import_common.content_digest(other)
    assert _commit(admin, "shipments", other, other_digest).status_code == 409
    auth_service.create_user(
        db,
        email="admin2@demo.example.com",
        full_name="Second Admin",
        password=TEST_PASSWORD,
        role=Role.ADMIN.value,
    )
    db.commit()
    second = Staff("admin2@demo.example.com")
    assert _commit(second, "shipments", content, digest).status_code == 409
    unconfirmed = _commit(admin, "shipments", content, digest, confirm="false")
    assert unconfirmed.status_code == 422, unconfirmed.text
    ops = Staff(users[Role.OPERATIONS].email)
    assert _dry(ops, "shipments", content).status_code == 403
    assert _commit(ops, "shipments", content, digest).status_code == 403
    assert _count(db, Shipment) == before["shipments"]

    # Commit after the matching dry run: exactly the two valid shipments, nothing else.
    done = _commit(admin, "shipments", content, digest)
    assert done.status_code == 200, done.text
    result = done.json()
    assert (result["created"], result["skipped"], result["rejected"]) == (2, 1, 3), result
    after = _counts(db, *IMPORT_TABLES, ShipmentEvent)
    assert after["shipments"] == before["shipments"] + 2
    for model in (QuoteVersion, InvoiceDraft, CustomerInvoice, NotificationOutbox, ShipmentEvent):
        assert after[model.__tablename__] == before[model.__tablename__], model.__tablename__
    assert len(mail.messages) == mail_before, [m["template_key"] for m in mail.messages]
    created = db.query(Shipment).filter(Shipment.source_system == "csv_shipment_import").all()
    assert sorted(s.source_record_id for s in created) == ["GT21-SHP-001", "GT21-SHP-002"]
    assert {s.transport_mode for s in created} == {"air"}
    assert _audits(db, "shipment.import_commit")

    # Re-running the same file creates nothing.
    again = _dry(admin, "shipments", content).json()
    assert again["counts"]["ready"] == 0, again["counts"]
    rerun = _commit(admin, "shipments", content, again["content_sha256"])
    assert rerun.status_code == 200 and rerun.json()["created"] == 0, rerun.text
    assert _count(db, Shipment) == before["shipments"] + 2


def test_shipment_import_size_and_row_limits(acct):
    owner = _owner(acct["db"]).public_id
    admin = Staff(acct["users"][Role.ADMIN].email)
    row = ["GT21-L", owner, "Lim", "Toronto", "CA", "Quà", "1", "draft", ""]
    many = _csv([SHIP_HEADER] + [[f"GT21-L{i}", *row[1:]] for i in range(5001)])
    assert len(many) < 2 * 1024 * 1024  # the row limit, not the size, refuses it
    assert _dry(admin, "shipments", many).status_code == 422
    big = _csv([SHIP_HEADER]) + b"x" * (2 * 1024 * 1024 + 1)
    assert _dry(admin, "shipments", big).status_code == 422
    exactly = _csv([SHIP_HEADER] + [[f"GT21-M{i}", *row[1:]] for i in range(5000)])
    ok = _dry(admin, "shipments", exactly)
    assert ok.status_code == 200 and ok.json()["row_count"] == 5000, ok.text[:300]


# === 2. Legacy history baseline ====================================================================


def _legacy_file(owner_ref: str) -> bytes:
    return _csv(
        [
            [
                "legacy_reference",
                "customer_ref",
                "booked_on",
                "final_status",
                "received_on",
                "departed_on",
                "arrived_on",
                "delivered_on",
                "cancelled_on",
                "recipient_name",
                "recipient_city",
                "recipient_country_code",
            ],
            [
                "GT21-OLD-001",
                owner_ref,
                "2024-03-01",
                "delivered",
                "2024-03-02",
                "2024-03-06",
                "2024-03-10",
                "2024-03-12",
                "",
                "Trần Thị Cũ",
                "Toronto",
                "CA",
            ],
            [
                "GT21-OLD-002",
                owner_ref,
                "2024-05-01",
                "cancelled",
                "",
                "",
                "",
                "",
                "2024-05-03",
                "Lê Văn Cũ",
                "Ottawa",
                "CA",
            ],
        ]
    )


def test_legacy_baseline_is_staff_only_history_voidable_and_idempotent(acct):
    db, mail, users = acct["db"], acct["mail"], acct["users"]
    owner = _owner(db)
    content = _legacy_file(owner.public_id)
    admin = Staff(users[Role.ADMIN].email)
    ops = Staff(users[Role.OPERATIONS].email)
    mail_before = len(mail.messages)

    dry = _dry(admin, "legacy-history", content)
    assert dry.status_code == 200, dry.text
    assert dry.json()["counts"]["ready"] == 2, dry.json()["counts"]
    assert _count(db, LegacyShipment) == 0
    assert _dry(ops, "legacy-history", content).status_code == 403
    done = _commit(admin, "legacy-history", content, dry.json()["content_sha256"])
    assert done.status_code == 200, done.text
    batch = done.json()["batch_public_id"]
    assert done.json()["created"] == 2

    # Never a customer email, notification, operational shipment or event.
    assert len(mail.messages) == mail_before
    assert _count(db, NotificationOutbox) == 0
    assert _count(db, Shipment) == 0 and _count(db, ShipmentEvent) == 0
    for path in (
        "/shipments",
        "/shipments?search=GT21-OLD-001",
        "/finance/accepted-not-invoiced",
        "/finance/ar-aging",
        "/finance/profitability?month=2024-03",
        "/invoices",
    ):
        response = ops.get(path)
        assert response.status_code == 200, (path, response.text)
        assert "GT21-OLD" not in response.text, path
    me = Me(APPLICANT)
    shipments = me.get("/shipments")
    assert shipments.status_code == 200 and "GT21-OLD" not in shipments.text
    assert me.get("/shipments/GT21-OLD-001").status_code in (404, 422)

    # Staff read them, with dated milestones.
    listed = ops.get("/legacy-shipments", params={"customer_id": owner.id})
    assert listed.status_code == 200 and listed.json()["total"] == 2, listed.text
    first = next(i for i in listed.json()["items"] if i["legacy_reference"] == "GT21-OLD-001")
    detail = ops.get(f"/legacy-shipments/{first['id']}").json()
    assert [(e["event_type"], e["occurred_on"]) for e in detail["events"]] == [
        ("booked", "2024-03-01"),
        ("received_at_solaris", "2024-03-02"),
        ("departed_origin", "2024-03-06"),
        ("arrived_destination", "2024-03-10"),
        ("delivered_to_recipient", "2024-03-12"),
    ], detail["events"]
    assert detail["final_status"] == "delivered" and detail["completed_on"] == "2024-03-12"

    # Re-run: matched, never duplicated.
    again = _dry(admin, "legacy-history", content).json()
    rerun = _commit(admin, "legacy-history", content, again["content_sha256"])
    assert rerun.status_code == 200 and rerun.json()["created"] == 0, rerun.text
    assert rerun.json()["matched"] == 2
    assert _count(db, LegacyShipment) == 2

    # Void: Admin only, audited; hidden afterwards.
    void = f"/imports/legacy-history/baselines/{batch}/void"
    assert ops.post(void, {"reason": "Wrong file", "confirm": True}).status_code == 403
    voided = admin.post(void, {"reason": "Wrong source file", "confirm": True})
    assert voided.status_code == 200, voided.text
    assert ops.get("/legacy-shipments").json()["total"] == 0
    assert ops.get("/legacy-shipments", params={"include_voided": True}).json()["total"] == 2
    assert [a.entity_id for a in _audits(db, "legacy_history.baseline_void")] == [batch]


# === 3. Password change ===========================================================================


def _pw(account: Account, **overrides):
    body = {
        "current_password": ACCOUNT_PASSWORD,
        "new_password": NEW_PASSWORD,
        "new_password_confirmation": NEW_PASSWORD,
        **overrides,
    }
    return account.post("/password/change", body)


def test_customer_password_change(acct):
    db, mail = acct["db"], acct["mail"]
    other, me = Account(), Account()
    wrong = _pw(me, current_password="NotMyPassword!2026")
    assert wrong.status_code == 422 and wrong.json()["field"] == "current_password", wrong.text
    for weak in ("short!1", "password1234"):
        refused = _pw(me, new_password=weak, new_password_confirmation=weak)
        assert refused.status_code == 422, (weak, refused.text)
    assert other.get("/me").status_code == 200  # refusals changed nothing
    mail.messages.clear()

    # A Vietnamese customer gets the notice in Vietnamese.
    owner = _owner(db)
    owner.preferred_language = "vi"
    db.commit()
    done = _pw(me)
    assert done.status_code == 200, done.text
    assert NEW_PASSWORD not in done.text
    assert me.get("/me").status_code == 200  # this browser continues (rotated session)
    assert other.get("/me").status_code == 401  # the other is signed out
    assert _sign_in_status(APPLICANT, ACCOUNT_PASSWORD) == 401
    assert _sign_in_status(APPLICANT, NEW_PASSWORD) == 200
    notices = _mail(mail, email.TEMPLATE_PASSWORD_CHANGED_HERE, APPLICANT)
    assert len(notices) == 1 and notices[0]["language"] == "vi", notices
    assert NEW_PASSWORD not in notices[0]["body"]
    assert _audits(db, "customer_account.password_changed")


def test_staff_password_change(acct):
    user = acct["users"][Role.MARKETING]
    other = Staff(user.email)
    me = Staff(user.email)
    body = {
        "current_password": TEST_PASSWORD,
        "new_password": "StaffGolden!2027x",
        "new_password_confirmation": "StaffGolden!2027x",
    }
    bad = me.post("/auth/password/change", {**body, "current_password": "Wrong!Password2026"})
    assert bad.status_code == 422, bad.text
    done = me.post("/auth/password/change", body)
    assert done.status_code == 200, done.text
    assert me.get("/auth/me").status_code == 200
    assert other.get("/auth/me").status_code == 401
    assert _staff_login_status(user.email, TEST_PASSWORD) == 401
    assert _staff_login_status(user.email, "StaffGolden!2027x") == 200


# === 4. Email change ==============================================================================
#
# RC-UAT-25 item 2 (Ben, 2026-10-25): the customer can no longer change the sign-in email; an
# Admin does. The two tests of the customer's own change were superseded and rewritten; both
# are registered in docs/customer_account/SUPERSEDED_ASSERTIONS.md (AS-56, AS-57).


def _ask(account: Account, address: str):
    return account.post(
        "/email/change", {"current_password": ACCOUNT_PASSWORD, "new_email": address}
    )


def _admin_sets(admin: Staff, reference: str, address: str):
    return admin.post(
        f"{REVIEW}/identities/{reference}/sign-in-email",
        {"new_email": address, "reason_code": "customer_request"},
    )


def test_admin_sign_in_email_change_round_trip(acct):
    """Superseded: see SUPERSEDED_ASSERTIONS.md AS-56 (was: the customer's change round trip
    and its token rules)."""
    db, mail, users, ref = acct["db"], acct["mail"], acct["users"], acct["reference"]
    me = Account()
    mail.messages.clear()
    refused = _ask(me, NEW_ADDRESS)
    assert refused.status_code == 403, refused.text
    assert mail.messages == []
    assert _sign_in_status(APPLICANT, ACCOUNT_PASSWORD) == 200

    ops = Staff(users[Role.OPERATIONS].email)
    assert _admin_sets(ops, ref, NEW_ADDRESS).status_code == 403
    admin = Staff(users[Role.ADMIN].email)
    done = _admin_sets(admin, ref, NEW_ADDRESS)
    assert done.status_code == 200, done.text
    assert _sign_in_status(NEW_ADDRESS, ACCOUNT_PASSWORD) == 200
    assert _sign_in_status(APPLICANT, ACCOUNT_PASSWORD) == 401
    assert me.get("/me").status_code == 401
    assert len(_mail(mail, email.TEMPLATE_EMAIL_CHANGED_NOTICE, APPLICANT)) == 1
    assert len(_mail(mail, email.TEMPLATE_SIGN_IN_EMAIL_SET_BY_STAFF, NEW_ADDRESS)) == 1
    assert _mail(mail, email.TEMPLATE_EMAIL_CHANGE_CONFIRM) == []
    assert _owner_by(db, NEW_ADDRESS) is not None
    assert len(_audits(db, "customer_account.sign_in_email_changed_by_staff")) == 1
    see_committed_changes(db)
    assert (
        db.query(CustomerAuthToken).filter_by(purpose=TokenPurpose.EMAIL_CHANGE.value).count() == 0
    )


def _owner_by(db, address: str) -> Customer | None:
    see_committed_changes(db)
    return db.query(Customer).filter_by(email_normalized=address).one_or_none()


def test_admin_change_to_an_address_in_use_is_refused_and_never_switches(acct):
    """Superseded: see SUPERSEDED_ASSERTIONS.md AS-57 (was: the customer's change to an address
    in use gets a generic answer and never switches)."""
    db, mail, client, ref = acct["db"], acct["mail"], acct["client"], acct["reference"]
    pending_identity(client, mail, "taken.golden@demo.example.com")
    make_customer(db, email="record.golden@demo.example.com")
    admin = Staff(acct["users"][Role.ADMIN].email)
    for address in ("taken.golden@demo.example.com", "record.golden@demo.example.com"):
        mail.messages.clear()
        response = _admin_sets(admin, ref, address)
        assert response.status_code == 409, (address, response.text)
        assert mail.messages == []
    assert _sign_in_status(APPLICANT, ACCOUNT_PASSWORD) == 200
    assert _owner(db).email_normalized == APPLICANT
    # The customer's own attempt at the same addresses: one refusal, whatever the address.
    me = Account()
    answers = {
        _ask(me, a).text for a in ("free.golden@demo.example.com", "taken.golden@demo.example.com")
    }
    assert len(answers) == 1


# === 5. Reinstatement ===========================================================================


def test_reinstatement_after_deactivation(acct):
    db, users, ref, mail = acct["db"], acct["users"], acct["reference"], acct["mail"]
    before = Account()
    admin = Staff(users[Role.ADMIN].email)
    ops = Staff(users[Role.OPERATIONS].email)
    off = admin.post(f"{REVIEW}/identities/{ref}/deactivate", {"reason_code": "customer_request"})
    assert off.status_code == 200, off.text
    assert _sign_in_status(APPLICANT, ACCOUNT_PASSWORD) != 200
    assert before.get("/me").status_code == 401

    url = f"{REVIEW}/identities/{ref}/reactivate"
    assert ops.post(url, {"reason_code": "deactivated_in_error"}).status_code == 403
    assert admin.post(url, {}).status_code == 422  # a reason is required
    mail.messages.clear()
    back = admin.post(url, {"reason_code": "deactivated_in_error", "note": "Phone mix-up"})
    assert back.status_code == 200 and back.json()["status"] == "active", back.text
    assert before.get("/me").status_code == 401  # old sessions stay revoked
    assert Account().get("/me").status_code == 200
    assert _mail(mail, email.TEMPLATE_ACCOUNT_REINSTATED, APPLICANT)
    events = _audits(db, "customer_account.reactivate")
    assert len(events) == 1 and events[0].actor_user_id == users[Role.ADMIN].id


# === 6. Quote tax wording =======================================================================


def _js_strings(path: Path) -> dict[str, str]:
    text = path.read_text(encoding="utf-8")
    return dict(re.findall(r"'(quotes\.[\w.]+)':\s*'([^']*)'", text))


def _sentence(strings: dict[str, str], tax: dict) -> str:
    """The tester's own rendering of the account sentence from the shipped strings."""
    if tax["band"] == "international":
        return strings["quotes.taxZeroRated"]
    if tax["rate_percent"] is None:
        return strings["quotes.taxIncludedNoRate"]
    return (
        strings["quotes.taxIncluded"]
        .replace("{label}", tax["label"])
        .replace("{rate}", str(tax["rate_percent"]))
    )


@pytest.fixture
def quote_world(account_client, account_db, account_users, captured_mail):
    return _build(
        account_client, account_db, account_users, captured_mail, ["on", "ns", "ab", "vnca", "x"]
    )


def test_quote_tax_wording_domestic_included_and_international_zero(quote_world):
    g = quote_world
    ops, me = g["ops"], g["me"]
    plan = {
        "on": ("CA", "CA", "ON", ("HST", 13)),
        "ns": ("CA", "CA", "NS", ("HST", 14)),
        "ab": ("CA", "CA", "AB", ("GST", 5)),
        "vnca": ("VN", "CA", "ON", (None, 0)),
    }
    en = _js_strings(REPO / "frontend/src/account/i18n/en.js")
    vi = _js_strings(REPO / "frontend/src/account/i18n/vi.js")
    expected_en = {
        "on": "Prices include HST 13 %",
        "ns": "Prices include HST 14 %",
        "ab": "Prices include GST 5 %",
        "vnca": "Zero-rated (0 %)",
    }
    expected_vi = {
        "on": "Giá đã bao gồm HST 13 %",
        "ns": "Giá đã bao gồm HST 14 %",
        "ab": "Giá đã bao gồm GST 5 %",
        "vnca": "Thuế suất 0 (0 %)",
    }
    for kid, (origin, destination, province, (label, rate)) in plan.items():
        _route(g, kid, origin, destination, province)
        sid, _ref = g["kids"][kid]
        assert _finalize(ops, sid).status_code == 200
        sent = ops.post(f"/shipments/{sid}/quotes/send")
        assert sent.status_code == 201, sent.text
        detail = me.get(f"/quotes/{sent.json()['id']}")
        assert detail.status_code == 200, detail.text
        tax = detail.json()["tax"]
        band = "international" if origin != destination else "domestic"
        assert tax == {"band": band, "label": label, "rate_percent": rate}, (kid, tax)
        listed = {q["id"]: q for q in me.get("/quotes").json()["items"]}
        assert listed[sent.json()["id"]]["tax"] == tax
        doc = ops.get(f"/shipments/{sid}/quotes/1/document")
        assert doc.status_code == 200 and doc.json()["tax"] == tax, doc.text
        assert _sentence(en, tax) == expected_en[kid]
        assert _sentence(vi, tax) == expected_vi[kid]
        for body in (detail.text, doc.text):
            assert "added on the invoice" not in body and "tính trên hóa đơn" not in body
    # Neither the account nor the staff print strings keep the old note.
    for path in (
        "frontend/src/account/i18n/en.js",
        "frontend/src/account/i18n/vi.js",
        "frontend/src/i18n/en.js",
        "frontend/src/i18n/vi.js",
    ):
        text = (REPO / path).read_text(encoding="utf-8")
        assert "added on the invoice" not in text and "sẽ được tính trên hóa đơn" not in text, path
    printed = (REPO / "frontend/src/features/workspace/QuotePrintPage.jsx").read_text("utf-8")
    assert "quoteDoc.taxIncluded" in printed and "quoteDoc.taxZeroRated" in printed


# === 7. Quote soft delete ========================================================================


def _versions(ops: Staff, sid: int) -> dict[int, int]:
    return {q["version"]: q["id"] for q in ops.get(f"/shipments/{sid}/quotes").json()}


def _superseded_and_sent(g, kid: str) -> tuple[int, int, int]:
    """v1 sent to the customer, then re-priced (v2): returns (shipment id, v1 id, offer id)."""
    ops = g["ops"]
    sid, _ = g["kids"][kid]
    assert _finalize(ops, sid).status_code == 200
    sent = ops.post(f"/shipments/{sid}/quotes/send")
    assert sent.status_code == 201, sent.text
    again = _finalize(ops, sid)
    assert again.status_code == 200, again.text
    versions = _versions(ops, sid)
    assert set(versions) == {1, 2}, versions
    return sid, versions[1], sent.json()["id"]


@pytest.fixture
def small(account_client, account_db, account_users, captured_mail):
    return _build(account_client, account_db, account_users, captured_mail, ["s1", "s2", "s3"])


def test_quote_soft_delete_and_restore(small):
    g = small
    ops, admin, me, db = g["ops"], g["admin"], g["me"], g["db"]
    sid, v1, offer = _superseded_and_sent(g, "s1")
    assert me.get(f"/quotes/{offer}").status_code == 200

    assert ops.post(f"/quote-versions/{v1}/delete", {"reason": "Old"}).status_code == 403
    assert admin.post(f"/quote-versions/{v1}/delete", {}).status_code == 422
    done = admin.post(f"/quote-versions/{v1}/delete", {"reason": "Old superseded quote"})
    assert done.status_code == 200, done.text
    assert set(_versions(ops, sid)) == {2}
    assert me.get(f"/quotes/{offer}").status_code == 404
    assert offer not in {q["id"] for q in me.get("/quotes").json()["items"]}
    assert ops.get(f"/shipments/{sid}/quotes/1/document").status_code == 404
    assert [a.entity_id for a in _audits(db, "quote.soft_delete")] == [str(v1)]

    assert ops.post(f"/quote-versions/{v1}/restore", {"reason": "Back"}).status_code == 403
    back = admin.post(f"/quote-versions/{v1}/restore", {"reason": "Needed after all"})
    assert back.status_code == 200, back.text
    assert set(_versions(ops, sid)) == {1, 2}
    assert ops.get(f"/shipments/{sid}/quotes/1/document").status_code == 200
    assert me.get(f"/quotes/{offer}").status_code == 200
    assert len(_audits(db, "quote.restore")) == 1

    # A version with an issued invoice is refused.
    s2, _ = g["kids"]["s2"]
    assert _finalize(ops, s2).status_code == 200
    assert ops.post(f"/shipments/{s2}/invoice").status_code == 201
    v = _versions(ops, s2)[1]
    refused = admin.post(f"/quote-versions/{v}/delete", {"reason": "Try"})
    assert refused.status_code == 409, refused.text
    assert refused.json()["detail"]["code"] == "issued_invoice"


# === 8. Retention ===============================================================================


def test_retention_off_by_default_gated_and_a_real_run(small, account_session_factory, capsys):
    g = small
    db, admin, ops, users = g["db"], g["admin"], g["ops"], g["users"]
    # Records: a soft-deleted superseded version (old), an invoice with a payment, old staff
    # and customer sessions.
    sid, v1, _offer = _superseded_and_sent(g, "s1")
    assert admin.post(f"/quote-versions/{v1}/delete", {"reason": "Old"}).status_code == 200
    s3, _ = g["kids"]["s3"]
    assert _finalize(ops, s3).status_code == 200
    invoice = ops.post(f"/shipments/{s3}/invoice")
    assert invoice.status_code == 201, invoice.text
    paid = ops.post(
        f"/invoices/{invoice.json()['id']}/payments",
        {"amount_cad": "1.00", "method": "cash", "received_at": date.today().isoformat()},
    )
    assert paid.status_code == 201, paid.text
    for _ in range(5):
        Staff(users[Role.MARKETING].email)
    Account()
    see_committed_changes(db)
    old = utcnow() - timedelta(days=100)
    marketing_id = users[Role.MARKETING].id
    for row in db.query(UserSession).filter_by(user_id=marketing_id):
        row.expires_at = old
    for row in db.query(CustomerSession):
        row.expires_at = old
    db.query(QuoteVersionDeletion).filter_by(quote_version_id=v1).one().deleted_at = old
    db.commit()

    tracked = (UserSession, CustomerSession, QuoteVersion, CustomerInvoice, CustomerPayment)
    start = _counts(db, *tracked)
    audits_start = _count(db, AuditEvent)

    # Defaults: off, every class disabled with no period; the worker does nothing.
    state = admin.get("/admin/data-retention").json()
    assert state["settings"]["enabled"] is False
    assert all(not p["enabled"] and p["period_days"] is None for p in state["policies"])
    assert ops.get("/admin/data-retention").status_code == 403
    assert retention_worker.main(["--once"], session_factory=account_session_factory) == 0
    assert (
        retention_worker.main(["--once", "--dry-run"], session_factory=account_session_factory) == 0
    )
    capsys.readouterr()
    assert _counts(db, *tracked) == start
    see_committed_changes(db)
    assert db.query(DataRetentionRun).filter_by(dry_run=False).count() == 0

    # Gates.
    policy = "/admin/data-retention/policies/staff_sessions_ended"
    assert admin.patch(policy, {"enabled": True, "period_days": 30}).status_code == 422
    assert (
        admin.patch(
            "/admin/data-retention/settings", {"enabled": True, "confirmation": "yes"}
        ).status_code
        == 422
    )
    on = admin.patch(
        "/admin/data-retention/settings", {"enabled": True, "confirmation": "ENABLE RETENTION"}
    )
    assert on.status_code == 200, on.text
    assert admin.patch(policy, {"enabled": True}).status_code == 422  # no period
    for key in ("staff_sessions_ended", "soft_deleted_quotes"):
        set_ = admin.patch(
            f"/admin/data-retention/policies/{key}", {"enabled": True, "period_days": 30}
        )
        assert set_.status_code == 200, set_.text

    # A real run in the test database, small batches.
    code = retention_worker.main(
        ["--once", "--batch-size", "2"], session_factory=account_session_factory
    )
    assert code == 0
    capsys.readouterr()
    end = _counts(db, *tracked)
    assert end["user_sessions"] == start["user_sessions"] - 5, (start, end)
    assert end["customer_sessions"] == start["customer_sessions"]  # class not enabled
    assert end["quote_versions"] == start["quote_versions"] - 1
    assert db.get(QuoteVersion, v1) is None
    assert end["customer_invoices"] == start["customer_invoices"]
    assert end["customer_payments"] == start["customer_payments"]
    assert _count(db, AuditEvent) > audits_start
    assert ops.get("/auth/me").status_code == 200  # live sessions untouched
    run = db.query(DataRetentionRun).filter_by(dry_run=False).one()
    assert run.status == "completed"
    counts = json.loads(run.counts_json)
    assert counts["staff_sessions_ended"]["affected"] == 5
    assert counts["soft_deleted_quotes"]["affected"] == 1
    assert _audits(db, "data_retention.run")
