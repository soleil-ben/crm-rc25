"""What a Customer Account response may contain, scanned rather than reviewed.

Two scans run over the **raw JSON**, recursively, at every depth, and they are the same two
`test_public_privacy.py` already runs over the public surface:

* a **forbidden-key** scan, which catches a field named after something internal wherever it
  appears -- nested, inside a list, or at the top level;
* a **planted-sentinel** scan, which fills the database with values nobody could produce by
  accident and then searches the serialized response for them. This is the one that catches a
  value smuggled through under an innocent key, or concatenated into a string.

A third test plants a leak deliberately and asserts the scan *fails*. Without it, a scan
that silently stopped working would look exactly like a scan that found nothing.

The audit scan is the same idea applied to a different table: after a full registration,
verification, sign-in, reset cycle, no audit row and no log line may hold a password, a
token, a digest, a session id, a CSRF token or a raw address.
"""

from __future__ import annotations

import json
import logging

from app.core.config import settings
from app.core.time_utils import utcnow
from app.models import AuditEvent, CustomerAuthToken, CustomerIdentity, CustomerSession
from app.services import customer_service
from tests.account_fixtures import (
    ACCOUNT_PASSWORD,
    csrf_headers,
    registered_and_verified,
    registration,
    reset_token,
    sign_in,
    verification_token,
)

ADDRESS = "hanh@demo.example.com"
REGISTER = "/api/v1/account/register"
FORGOT = "/api/v1/account/password/forgot"
RESET = "/api/v1/account/password/reset"
ME = "/api/v1/account/me"

#: Key names that must not appear anywhere in a Customer Account response, at any depth.
#: Drawn from `FIELD_MATRIX.md` section 3.4 ("Never"), from the credential material this
#: surface handles, and from the internals `THREAT_MODEL.md` T-13 and T-17 forbid.
FORBIDDEN_KEYS = frozenset(
    {
        # Credential material
        "password",
        "password_hash",
        "token_hash",
        "token_digest",
        "csrf_token_hash",
        "session_token",
        "session_token_hash",
        "secret",
        "api_key",
        # Internal identifiers
        "id",
        "identity_id",
        "customer_id",
        "user_id",
        "proposal_id",
        "session_id",
        "owner_user_id",
        "actor_user_id",
        # Duplicate review and linking (T-02)
        "duplicate_score",
        "duplicate_review_outcome",
        "match_count",
        "matches",
        "candidates",
        "link_candidates",
        # FIELD_MATRIX "Never"
        "internal_notes",
        "notes",
        "lifecycle_status",
        "tags",
        "interactions",
        "referral_source",
        "assigned_staff",
        "is_demo_record",
        "do_not_contact",
        "service_restriction_note",
        "name_match_key",
        "phone_match_key",
        "email_normalized",
        "merged_into_customer_id",
        "archive_reason",
        # Financial (OD-32)
        "selling_amount",
        "shipping_cost",
        "surcharges_amount",
        "discount_amount",
        "refund_amount",
        "payment_state",
        "declared_value",
        "currency",
        # Staff and integration
        "role",
        "permissions",
        "integration_state",
        "credential_ref",
        "provider_key",
        # Audit internals
        "audit_events",
        "detail_json",
        "actor_label",
    }
)

#: Fragments that make a key suspicious wherever they appear. Broader than the exact set, so
#: a field named `customer_duplicate_score_v2` is caught too.
FORBIDDEN_KEY_FRAGMENTS = (
    "password",
    "secret",
    "hash",
    "digest",
    "duplicate",
    "score",
    "internal",
    "audit",
    "permission",
    "suppress",
    "shipment",
    "invoice",
    "balance",
    "revenue",
    "profit",
    "cost",
)

#: Keys this surface legitimately uses that a fragment above would otherwise trip.
ALLOWED_EXACT_KEYS = frozenset({"shipment_history_available"})


def walk(node, path="$"):
    if isinstance(node, dict):
        for key, value in node.items():
            yield f"{path}.{key}", key, value
            yield from walk(value, f"{path}.{key}")
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from walk(value, f"{path}[{index}]")


def scan_keys(payload) -> list[str]:
    offences = []
    for path, key, _ in walk(payload):
        if key in ALLOWED_EXACT_KEYS:
            continue
        if key in FORBIDDEN_KEYS:
            offences.append(f"forbidden key {key} at {path}")
        for fragment in FORBIDDEN_KEY_FRAGMENTS:
            if fragment in key.lower():
                offences.append(f"forbidden fragment '{fragment}' in key at {path}")
    return offences


def scan_values(payload, sentinels: dict[str, str]) -> list[str]:
    """Find any sentinel anywhere in the serialized payload.

    Serializing the whole tree and searching it catches a value hidden in a key name, in a
    nested list, or in a string concatenated from private parts -- all of which a
    field-by-field comparison would miss.
    """
    raw = json.dumps(payload, ensure_ascii=False, default=str)
    return [f"{label} leaked: {value!r}" for label, value in sentinels.items() if value in raw]


def _loaded_account(client, db, mail):
    """A signed-in identity with everything private that could possibly exist behind it.

    A matching canonical customer with internal fields populated, a proposal holding the
    submitted values, live tokens, and a session. Absence is only worth asserting against a
    record that *has* the thing being looked for.
    """
    customer = customer_service.create_customer(
        db,
        {
            "full_name": "Nguyễn Thị Bích Hạnh",
            "email": ADDRESS,
            "phone": "+84 90 123 4567",
            "country_code": "VN",
            "notes": "SENTINEL-INTERNAL-NOTE-9Q4",
        },
    )
    db.commit()

    registered_and_verified(client, mail, ADDRESS)
    response = sign_in(client, ADDRESS)
    client.post(FORGOT, json={"email": ADDRESS})

    identity = db.query(CustomerIdentity).filter_by(email_normalized=ADDRESS).one()
    session_row = db.query(CustomerSession).filter_by(identity_id=identity.id).first()
    tokens = db.query(CustomerAuthToken).filter_by(identity_id=identity.id).all()

    sentinels = {
        "password": ACCOUNT_PASSWORD,
        "password_hash": identity.password_hash,
        "session_token_hash": session_row.session_token_hash,
        "csrf_token_hash": session_row.csrf_token_hash,
        "internal_note": "SENTINEL-INTERNAL-NOTE-9Q4",
        "customer_public_id": customer.public_id,
        "identity_row_id": f'"{identity.id}"',
    }
    for index, token in enumerate(tokens):
        sentinels[f"token_digest_{index}"] = token.token_digest

    return response, sentinels, identity, customer


# --- The scans ----------------------------------------------------------------


def test_no_forbidden_key_appears_at_any_depth(account_client, account_db, captured_mail):
    response, _, _, _ = _loaded_account(account_client, account_db, captured_mail)

    for payload in (response.json(), account_client.get(ME).json()):
        offences = scan_keys(payload)
        assert offences == [], offences


def test_no_private_value_appears_anywhere_in_the_raw_json(
    account_client, account_db, captured_mail
):
    response, sentinels, _, _ = _loaded_account(account_client, account_db, captured_mail)

    for payload in (response.json(), account_client.get(ME).json()):
        offences = scan_values(payload, sentinels)
        assert offences == [], offences


def test_the_scan_itself_detects_a_planted_leak(account_client, account_db, captured_mail):
    """Without this, a scan that stopped working looks like a scan that found nothing."""
    _, sentinels, _, _ = _loaded_account(account_client, account_db, captured_mail)

    planted = {"account_reference": "CA-000001", "leaked": {"deep": [sentinels["password_hash"]]}}
    assert scan_values(planted, sentinels) != []
    assert scan_keys({"ok": 1, "nested": {"password_hash": "x"}}) != []


def test_the_me_response_is_exactly_the_declared_allowlist(
    account_client, account_db, captured_mail
):
    """Eight fields, by name. A ninth appearing is a disclosure nobody reviewed."""
    _loaded_account(account_client, account_db, captured_mail)
    body = account_client.get(ME).json()
    assert set(body) == {
        "account_reference",
        "status",
        "email_verified",
        "linked",
        "shipment_history_available",
        "preferred_language",
        "status_reason_code",
        "has_pending_proposal",
    }


def test_the_sign_in_response_is_exactly_the_declared_allowlist(
    account_client, account_db, captured_mail
):
    registered_and_verified(account_client, captured_mail, ADDRESS)
    body = sign_in(account_client, ADDRESS).json()
    assert set(body) == {"account_reference", "status", "email_verified", "csrf_token"}


def test_no_response_carries_an_internal_row_id(account_client, account_db, captured_mail):
    """References are public; row ids are not (`FIELD_MATRIX.md` section 3.4)."""
    response, _, identity, customer = _loaded_account(account_client, account_db, captured_mail)
    for payload in (response.json(), account_client.get(ME).json()):
        raw = json.dumps(payload)
        assert f'"{identity.id}"' not in raw
        assert f'"id":{identity.id}' not in raw.replace(" ", "")
        assert customer.public_id not in raw


def test_no_response_says_whether_an_address_is_registered(
    account_client, account_db, captured_mail
):
    registered_and_verified(account_client, captured_mail, ADDRESS)
    from app.core.security import rate_limiter

    for path, body in (
        (REGISTER, registration(email=ADDRESS)),
        (FORGOT, {"email": ADDRESS}),
        ("/api/v1/account/verification/resend", {"email": ADDRESS}),
    ):
        rate_limiter.reset()
        known = account_client.post(path, json=body)
        rate_limiter.reset()
        unknown_body = dict(body)
        unknown_body["email"] = "nobody-at-all@demo.example.com"
        if path == REGISTER:
            unknown_body = registration(email="nobody-at-all@demo.example.com")
        unknown = account_client.post(path, json=unknown_body)
        assert (known.status_code, known.json()) == (unknown.status_code, unknown.json()), path


def test_an_error_response_carries_no_internals(account_client, account_db, captured_mail):
    """T-17: one error shape, no ids, no table names, no query fragments, no stack trace."""
    _loaded_account(account_client, account_db, captured_mail)

    failures = [
        account_client.post(
            REGISTER, content=b"{bad", headers={"content-type": "application/json"}
        ),
        account_client.post("/api/v1/account/verify-email", json={"token": "a" * 43}),
        account_client.post(
            RESET,
            json={
                "token": "a" * 43,
                "password": "Whatever!2026xx",
                "password_confirmation": "Whatever!2026xx",
            },
        ),
    ]
    # `_loaded_account` leaves the client signed in, so the unauthenticated probe needs a
    # clean jar -- otherwise it would answer 200 and prove nothing about error shapes.
    account_client.cookies.clear()
    failures.append(account_client.get(ME))

    for response in failures:
        body = response.json()
        assert set(body) == {"code", "message", "field"}, body
        raw = json.dumps(body).lower()
        for internal in (
            "traceback",
            "sqlalchemy",
            "select ",
            "customer_identities",
            "customer_sessions",
            "app/",
            "app\\\\",
        ):
            assert internal not in raw, (internal, body)


# --- Audit and logs -----------------------------------------------------------


def _full_cycle(client, db, mail):
    """Register, verify, sign in, sign out, request a reset, complete it.

    Every event in `DATA_MODEL.md` section 9 that Phase 9 can produce, so the audit scan
    below runs against the whole vocabulary rather than one event.
    """
    registered_and_verified(client, mail, ADDRESS)
    response = sign_in(client, ADDRESS)
    client.post("/api/v1/account/sign-out", headers=csrf_headers(response))
    client.post(FORGOT, json={"email": ADDRESS})
    token = reset_token(mail, ADDRESS)
    client.post(
        RESET,
        json={
            "token": token,
            "password": "ReplacementPass!2026",
            "password_confirmation": "ReplacementPass!2026",
        },
    )
    return token


def test_no_audit_payload_holds_credential_or_token_material(
    account_client, account_db, captured_mail
):
    reset = _full_cycle(account_client, account_db, captured_mail)
    verification = verification_token(captured_mail, ADDRESS)

    account_db.expire_all()
    identity = account_db.query(CustomerIdentity).filter_by(email_normalized=ADDRESS).one()
    digests = [row.token_digest for row in account_db.query(CustomerAuthToken).all()]
    sessions = [row.session_token_hash for row in account_db.query(CustomerSession).all()]
    csrf = [row.csrf_token_hash for row in account_db.query(CustomerSession).all()]

    events = account_db.query(AuditEvent).all()
    assert events
    for event in events:
        blob = f"{event.summary}|{event.detail_json or ''}|{event.actor_label}"
        assert ACCOUNT_PASSWORD not in blob
        assert "ReplacementPass!2026" not in blob
        assert identity.password_hash not in blob
        assert "$argon2" not in blob
        assert reset not in blob
        assert verification not in blob
        for value in (*digests, *sessions, *csrf):
            assert value not in blob


def test_no_audit_payload_holds_a_raw_address_or_phone(account_client, account_db, captured_mail):
    _full_cycle(account_client, account_db, captured_mail)
    for event in account_db.query(AuditEvent).all():
        payload = event.detail_json or ""
        assert ADDRESS not in payload
        assert "+84901234567" not in payload
        assert "0901234567" not in payload


def test_no_audit_payload_holds_the_raw_proposal(account_client, account_db, captured_mail):
    """Field keys, never values: the values are stored once, on the proposal rows."""
    _full_cycle(account_client, account_db, captured_mail)
    for event in account_db.query(AuditEvent).all():
        payload = event.detail_json or ""
        assert "Nguyễn Thị Bích Hạnh" not in payload
        assert "4120 Dixie Road" not in payload
        assert "125 Đường Nguyễn Huệ" not in payload
    # But the keys are there, so a reviewer can still see what was proposed.
    submitted = [
        event
        for event in account_db.query(AuditEvent).all()
        if event.action == "customer_data_proposal.submit"
    ]
    assert submitted
    assert "legal_name" in (submitted[0].detail_json or "")


def test_the_registration_audit_row_carries_a_hashed_address_key(
    account_client, account_db, captured_mail
):
    from app.core.account_security import address_key

    _full_cycle(account_client, account_db, captured_mail)
    events = [
        event
        for event in account_db.query(AuditEvent).all()
        if event.action == "customer_account.register"
    ]
    assert events
    payload = json.loads(events[0].detail_json)
    assert payload["address_key"] == address_key(ADDRESS)
    assert ADDRESS not in events[0].detail_json


def test_every_phase_9_transition_writes_an_audit_row(account_client, account_db, captured_mail):
    """AC-CA-10.1, for the transitions Phase 9 can actually reach."""
    _full_cycle(account_client, account_db, captured_mail)
    actions = {event.action for event in account_db.query(AuditEvent).all()}
    assert {
        "customer_account.register",
        "customer_account.verification_issued",
        "customer_account.verify_email",
        "customer_account.sign_in",
        "customer_account.sign_out",
        "customer_account.session_revoked",
        "customer_account.password_reset_requested",
        "customer_account.password_reset_completed",
        "customer_data_proposal.submit",
    } <= actions


def _collecting_logger():
    """A collector on the application logger, wired exactly as production is.

    `caplog` attaches to the root logger and would measure records that never passed the
    safety filter, which is the thing under test. This installs the production
    `SafetyFilter` and `JsonFormatter`, so what is collected is what would actually be
    written -- the technique `test_phase5b_logging.py` already uses.
    """
    from app.core.logging import JsonFormatter, SafetyFilter

    lines: list[str] = []

    class Collector(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            lines.append(self.format(record))

    handler = Collector()
    handler.setFormatter(JsonFormatter())
    handler.addFilter(SafetyFilter())

    logger = logging.getLogger("solaris.crm")
    previous, previous_propagate = logger.handlers, logger.propagate
    logger.handlers = [handler]
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    return logger, lines, (previous, previous_propagate)


def _restore_logger(logger, previous):
    logger.handlers, logger.propagate = previous


def test_no_log_line_holds_a_token_password_or_address(account_client, account_db, captured_mail):
    """The redaction filter already covers the staff surface; this extends it to this one."""
    logger, lines, previous = _collecting_logger()
    try:
        reset = _full_cycle(account_client, account_db, captured_mail)
    finally:
        _restore_logger(logger, previous)
    verification = verification_token(captured_mail, ADDRESS)

    emitted = "\n".join(lines)
    assert emitted, "nothing was logged, so this proved nothing"
    assert ACCOUNT_PASSWORD not in emitted
    assert reset not in emitted
    assert verification not in emitted
    assert ADDRESS not in emitted
    assert "$argon2" not in emitted


def test_the_route_template_is_logged_and_never_a_token_bearing_path(
    account_client, account_db, captured_mail
):
    logger, lines, previous = _collecting_logger()
    try:
        _full_cycle(account_client, account_db, captured_mail)
    finally:
        _restore_logger(logger, previous)

    events = [json.loads(line) for line in lines]
    routes = [event.get("route") for event in events if event.get("event") == "http_request"]
    assert routes, "no http_request event was logged"
    for route in routes:
        assert "token=" not in str(route)
        assert ADDRESS not in str(route)
    # The Customer Account routes really were exercised, so the assertion had something to
    # check rather than passing over an empty set.
    assert any("register" in str(route) for route in routes)


# --- The public boundary is unmoved -------------------------------------------


def test_public_tracking_still_answers_and_still_carries_no_correlation_header(
    account_client, account_db, captured_mail
):
    registered_and_verified(account_client, captured_mail, ADDRESS)
    sign_in(account_client, ADDRESS)

    # A customer session must change nothing about the public surface.
    response = account_client.get("/api/v1/public/track/SX-CAV-7K9D2M4R8T6W")
    assert response.status_code == 404
    assert set(response.json()) == {"code", "message"}
    assert response.json()["code"] == "tracking_not_found"
    assert "x-correlation-id" not in {key.lower() for key in response.headers}


def test_the_public_contract_is_still_exactly_24_fields():
    """The existing assertion, repeated here so a Customer Account change trips it too.

    Registered in `SUPERSEDED_ASSERTIONS.md` (AS-31): twenty-four fields until RC-UAT-19
    added ``carrier_links`` (2026-10-22); the name keeps the historical count.
    """
    from app.schemas.public_tracking import PublicTrackingResult

    assert (
        len(PublicTrackingResult.model_fields) == 25
    )  # 24 until RC-UAT-19 added carrier_links (2026-10-22)


def test_no_customer_account_schema_touches_the_public_or_staff_ones():
    from app.schemas import account as account_schemas

    assert account_schemas.AccountMeResponse.model_config["from_attributes"] is False
    assert account_schemas.AccountMeResponse.model_config["extra"] == "forbid"


def test_the_account_cookie_names_are_absent_from_a_public_response(
    account_client, account_db, captured_mail
):
    response = account_client.get("/api/v1/public/track/SX-CAV-7K9D2M4R8T6W")
    assert settings.account_session_cookie_name not in response.headers.get("set-cookie", "")
    assert not response.cookies


def test_a_status_reason_code_is_a_code_and_never_prose(account_client, account_db, captured_mail):
    """`STATE_MACHINES.md`: a reason code, never prose that describes another record."""
    from app.services import customer_identity_service

    registered_and_verified(account_client, captured_mail, ADDRESS)
    identity = account_db.query(CustomerIdentity).filter_by(email_normalized=ADDRESS).one()
    identity.suspended_at = utcnow()
    customer_identity_service.suspend(account_db, identity, reason_code="abuse_investigation")
    account_db.commit()

    # Bounded, tokenized, and short enough that a sentence cannot fit.
    assert identity.status_reason_code == "abuse_investigation"
    assert " " not in identity.status_reason_code
    assert len(identity.status_reason_code) <= 40
