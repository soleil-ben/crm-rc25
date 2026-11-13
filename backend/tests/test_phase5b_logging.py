"""Logs carry categories and opaque identifiers, and nothing a customer told us.

Redaction is tested two ways on purpose, because each catches what the other misses.

**By field name.** A structured field survives only if it is on the allowlist. This
catches the developer who adds `customer_email=...` to a log call: the field is dropped
whatever its value happens to be, and only its name is kept.

**By planted sentinel.** Distinctive values are pushed through fields and messages that
*are* allowed, and the rendered line is searched for them. This catches the case the
allowlist cannot -- a private value arriving inside a field that is legitimately named,
such as a customer's name interpolated into an error message.

A test that only did the first would pass while leaking; a test that only did the second
would pass while the allowlist rotted.
"""

from __future__ import annotations

import json
import logging

import pytest

from app.core.logging import (
    SAFE_FIELDS,
    SUPPRESSED_MESSAGE,
    JsonFormatter,
    SafetyFilter,
    accept_correlation_id,
    log_event,
    new_correlation_id,
    reset_correlation_id,
    set_correlation_id,
)

#: Values planted into log calls. Each stands for one of the things `CRM.md` sections 10
#: and 11 forbid recording, and each is distinctive enough that a substring search cannot
#: match it by accident.
SENTINELS = {
    "customer_name": "Nguyễn Thị Bích Hạnh",
    "street_address": "1234 Zzyzx Parkway Unit 9B",
    "email": "hanh.sentinel@demo.example.com",
    "phone": "+14165550199",
    "private_note": "SENTINELNOTE-customer-disputes-the-charge",
    "csv_cell": "SENTINELCELL,Bich Hanh,hanh@demo.example.com",
    "solaris_reference": "SX-CAV-7K9D2M4R8T6W",
    "package_reference": "SX-CAV-7K9D2M4R8T6W-02",
    "carrier_reference": "1Z999AA10123456784",
    "bearer_token": "Bearer sentinel-session-token-value",
    "session_token": "solaris_session=SENTINELSESSIONTOKENVALUE0123456789",
    "csrf_token": "SENTINELCSRFTOKENVALUE0123456789",
    "api_key": "api_key=SENTINELPROVIDERCREDENTIAL01234",
    "request_body": '{"full_name": "Nguyễn Thị Bích Hạnh", "email": "hanh@demo.example.com"}',
}


@pytest.fixture
def captured():
    """A logger wired exactly as production is: safety filter, then JSON formatter."""
    records: list[str] = []

    class Collector(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(self.format(record))

    handler = Collector()
    handler.setFormatter(JsonFormatter())
    handler.addFilter(SafetyFilter())

    logger = logging.getLogger("solaris.test.redaction")
    logger.handlers = [handler]
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    yield logger, records
    logger.handlers = []


# --- By planted sentinel ---------------------------------------------------------------


@pytest.mark.parametrize("name,value", sorted(SENTINELS.items()))
def test_a_sentinel_never_survives_in_a_log_message(captured, name, value):
    """The value is interpolated into the message, the way a careless log call would.

    The whole sentence is suppressed on one of our own loggers, rather than redacted.
    Two of these sentinels are why: a person's name and a street address have no
    detectable shape, and both survived every pattern `redact_text` applies. Dropping
    the sentence is the only guarantee that holds for all fourteen.
    """
    logger, records = captured

    logger.info("something happened: %s", value)

    assert records, "nothing was logged"
    assert value not in records[0], f"{name} survived in the message"
    assert json.loads(records[0])["event"] == SUPPRESSED_MESSAGE


@pytest.mark.parametrize("name,value", sorted(SENTINELS.items()))
def test_a_sentinel_in_an_f_string_never_survives_either(captured, name, value):
    """An f-string leaves no `args`, so it cannot be caught by looking for interpolation."""
    logger, records = captured

    logger.info(f"customer record touched: {value}")  # noqa: G004

    assert value not in records[0], f"{name} survived in an f-string message"


def test_free_text_from_a_third_party_logger_is_redacted_rather_than_suppressed(captured):
    """A library's failure is worth keeping; a library's prose is not ours to restructure."""
    handler = captured[0].handlers[0]
    third_party = logging.getLogger("sqlalchemy.engine.Whatever")
    third_party.handlers = [handler]
    third_party.setLevel(logging.DEBUG)
    third_party.propagate = False
    records = captured[1]
    try:
        third_party.error("could not connect: %s", SENTINELS["email"])
    finally:
        third_party.handlers = []

    line = records[-1]
    assert SENTINELS["email"] not in line
    # Kept, not suppressed: the operator still learns a connection failed.
    assert "could not connect" in json.loads(line)["event"]


@pytest.mark.parametrize("name,value", sorted(SENTINELS.items()))
def test_a_sentinel_never_survives_in_an_allowlisted_field(captured, name, value):
    """The value is placed in a field that *is* allowed, so only redaction can catch it."""
    logger, records = captured

    log_event(logger, logging.INFO, "http_request", outcome=value, error_category=value)

    assert value not in records[0], f"{name} survived in an allowlisted field"


@pytest.mark.parametrize("name,value", sorted(SENTINELS.items()))
def test_a_sentinel_never_survives_in_a_rejected_field(captured, name, value):
    """A field name nobody allowlisted is dropped, and its value with it."""
    logger, records = captured

    log_event(logger, logging.INFO, "http_request", customer_email=value, note=value)

    assert value not in records[0], f"{name} survived in a dropped field"


# --- By field name ---------------------------------------------------------------------


def test_a_field_that_is_not_on_the_allowlist_is_dropped(captured):
    logger, records = captured

    log_event(logger, logging.INFO, "http_request", full_name="Someone", route="/x")

    payload = json.loads(records[0])
    assert "full_name" not in payload
    assert payload["route"] == "/x"


def test_the_name_of_a_dropped_field_is_recorded_but_not_its_value(captured):
    """Names help a developer see the field was refused. Values are the thing refused."""
    logger, records = captured

    log_event(logger, logging.INFO, "http_request", internal_note="SENTINELNOTE-private")

    payload = json.loads(records[0])
    assert payload["dropped_fields"] == ["internal_note"]
    assert "SENTINELNOTE-private" not in records[0]


def test_the_allowlist_contains_no_field_that_names_a_customer_value():
    """A guard on the allowlist itself, so adding one is a deliberate act."""
    forbidden = (
        "name",
        "email",
        "phone",
        "address",
        "note",
        "body",
        "payload",
        "reference",
        "token",
        "secret",
        "password",
        "cell",
        "query",
        "path",
    )
    # Each exception is named, with the reason it is not a customer value.
    permitted = {
        # Keyed, non-reversible stand-ins -- the point of them is to be loggable.
        "reference_digest",
        "payload_digest",
        # A route *template*, never a resolved path. `/track/{reference}` names a shape.
        "route",
        # Machine identifiers chosen by the operator, e.g. `integration-worker-1`.
        "worker_name",
    }
    for field in sorted(SAFE_FIELDS):
        for term in forbidden:
            if term in field:
                assert field in permitted, (
                    f"{field!r} reads like a customer value; if it is genuinely safe, "
                    "add it to `permitted` here with the reason"
                )


# --- Exceptions -------------------------------------------------------------------------


def test_an_exception_is_recorded_as_a_type_name_not_as_its_text(captured):
    """A traceback's last line is the exception's str(), and that is where data hides."""
    logger, records = captured

    try:
        raise ValueError(f"failed to parse {SENTINELS['customer_name']} at row 4")
    except ValueError:
        logger.exception("import_failed")

    assert SENTINELS["customer_name"] not in records[0]
    payload = json.loads(records[0])
    assert payload["error_type"] == "ValueError"
    assert "Traceback" not in records[0]


def test_a_stack_trace_is_never_rendered(captured):
    logger, records = captured

    try:
        {}["missing"]
    except KeyError:
        logger.error("lookup_failed", exc_info=True)

    assert "Traceback" not in records[0]
    assert json.loads(records[0])["error_type"] == "KeyError"


# --- Structure and correlation ----------------------------------------------------------


def test_every_record_is_one_json_object(captured):
    logger, records = captured

    log_event(logger, logging.INFO, "http_request", status_code=200)

    payload = json.loads(records[0])
    assert payload["event"] == "http_request"
    assert payload["level"] == "INFO"
    assert payload["status_code"] == 200
    assert "\n" not in records[0]


def test_an_event_name_survives_redaction_intact(captured):
    """`configuration_incomplete` is 24 word characters and was being eaten as a secret."""
    logger, records = captured

    log_event(logger, logging.WARNING, "configuration_incomplete", reason_code="x")

    assert json.loads(records[0])["event"] == "configuration_incomplete"


def test_the_correlation_id_is_attached_to_every_record(captured):
    logger, records = captured
    token = set_correlation_id("abcdef0123456789")
    try:
        log_event(logger, logging.INFO, "http_request")
    finally:
        reset_correlation_id(token)

    assert json.loads(records[0])["correlation_id"] == "abcdef0123456789"


def test_a_keyed_digest_is_not_redacted_away(captured):
    """It is the whole point of the field: opaque, and useless once replaced."""
    logger, records = captured

    log_event(logger, logging.INFO, "public_tracking_lookup", reference_digest="a1b2c3d4e5f6")

    assert json.loads(records[0])["reference_digest"] == "a1b2c3d4e5f6"


def test_a_digest_made_only_of_digits_is_still_not_redacted(captured):
    """A twelve-digit digest would otherwise be caught as a long digit run."""
    logger, records = captured

    log_event(logger, logging.INFO, "public_tracking_lookup", reference_digest="123456789012")

    assert json.loads(records[0])["reference_digest"] == "123456789012"


# --- Correlation identifiers ------------------------------------------------------------


def test_a_generated_correlation_id_is_opaque():
    value = new_correlation_id()
    assert len(value) == 32
    assert value.isalnum()


@pytest.mark.parametrize(
    "supplied",
    [
        "short",
        "has spaces in it",
        'quote"inject',
        "newline\ninjected-value-here",
        "x" * 65,
        "",
        None,
        '{"forged": "record"}',
    ],
)
def test_an_unsafe_inbound_correlation_id_is_replaced(supplied):
    """A caller-supplied id is echoed into every line for the request, so it is vetted."""
    accepted = accept_correlation_id(supplied)

    assert accepted != supplied
    assert accepted.isalnum()


def test_a_safe_inbound_correlation_id_is_honoured():
    """Joining a trace across services is the reason to accept one at all."""
    assert accept_correlation_id("trace-0123456789ab") == "trace-0123456789ab"
