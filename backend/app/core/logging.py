"""Structured, correlated, redacted application logging.

Three problems, and each is solved in a way that does not depend on the caller having
remembered anything.

**Structure.** Records are emitted as one JSON object per line, so a log shipper can index
them without a regular expression that breaks the first time a message changes.

**Correlation.** Every request is assigned an identifier held in a context variable, so
each record written while handling it carries the same `correlation_id` without any
function having to thread it through its arguments. The same value is returned in the
`X-Correlation-ID` response header, which is what makes "the operator's report" and "the
log lines" joinable during an incident.

**Redaction.** This is the part that matters. `CRM.md` section 10 and section 11 forbid a
tracking reference, a customer detail, or a credential reaching a log file -- and a log
file is precisely where such a value ends up without anybody deciding to put it there,
because it arrived inside an exception message or a formatted string.

Two independent mechanisms, because one is not enough:

1. **A field-name allowlist.** A structured field survives only if its name is in
   `SAFE_FIELDS`. Anything else is dropped, and only its *name* is recorded, in
   `dropped_fields`, so a developer can see that a field was refused without its value
   being written down. An allowlist rather than a blocklist, because a blocklist is a
   list of the field names somebody thought of.
2. **Value redaction.** Every surviving string, including the message itself, goes
   through `redact_text` -- the same function the integration layer has used since
   Phase 4A for provider error summaries. It strips URLs, authorization values,
   `key=value` secrets, email addresses, Solaris identifiers, carrier-reference shapes,
   long digit runs, and secret-shaped tokens.

The second is what catches a sentinel planted in a place the first was never going to
look, which is exactly what `test_phase5b_logging.py` plants.

**Exceptions are never rendered.** `record.exc_info` is discarded and replaced by the
exception's *type name*. A traceback's final line is the exception's `str()`, and for a
database driver, an HTTP client, or a validation library that string routinely contains
the query, the URL, or the offending value -- which is to say, the customer's data. The
type name is the part that is reliably safe, and the application already records a
deliberate, redacted summary wherever more detail is genuinely useful.

`redact_text` is imported from `app.integrations.redaction`. That module is named for
where it was first needed, not for what it couples to: at module level it imports only
`hashlib`, `re`, and `urllib.parse`, registers no provider, and opens no socket.
`test_phase5b_no_provider_registered.py` asserts that this import cannot become a route
to the provider layer.
"""

from __future__ import annotations

import json
import logging
import re
import sys
import uuid
from contextvars import ContextVar
from datetime import UTC, datetime

from app.integrations.redaction import redact_text

#: The correlation identifier for the request being handled on this task.
_correlation_id: ContextVar[str | None] = ContextVar("solaris_correlation_id", default=None)

#: What an inbound `X-Correlation-ID` must look like before it is believed. A caller-
#: supplied value is echoed into every log line for the request, so it is accepted only
#: when it is short, opaque, and made of characters that cannot break a JSON field or
#: forge a second log entry.
_SAFE_CORRELATION_ID = re.compile(r"\A[A-Za-z0-9._-]{8,64}\Z")

#: A structured event name: lower snake_case, chosen by the application, never
#: interpolated. Such a token is exempt from value redaction.
#:
#: The exemption is not a convenience. `redact_text` treats any unbroken run of 24 or
#: more word characters as secret-shaped -- which is correct for a token and wrong for
#: `configuration_incomplete`, a 24-character event name that was being replaced with
#: `[redacted]` and taking the only routable field in the record with it. The pattern is
#: narrow enough to be safe on its own terms: a customer name has spaces or capitals, an
#: email has an `@`, a Solaris identifier and a carrier reference are uppercase with
#: digits, and none of them can match `^[a-z][a-z0-9_]*$`.
_EVENT_NAME = re.compile(r"\A[a-z][a-z0-9_]{0,63}\Z")

#: Loggers this application owns. Their messages are held to the strict rule below.
_OWN_LOGGER_PREFIX = "solaris"

#: What replaces a free-text message on one of this application's own loggers.
SUPPRESSED_MESSAGE = "[non-event message suppressed]"

#: Why the strict rule exists, in one place, because it is the least obvious decision in
#: this module.
#:
#: A sentinel test plants a customer name and a street address into a log message and
#: asserts neither survives. Both survived. `redact_text` is thorough about everything
#: with a *detectable shape* -- emails, Solaris identifiers, carrier references, long
#: digit runs, `key=value` secrets, authorization values, URLs -- and there is no shape
#: that distinguishes "Nguyễn Thị Bích Hạnh" or "1234 Zzyzx Parkway Unit 9B" from prose.
#: No regular expression can catch a name, and pretending otherwise would be the most
#: dangerous kind of guarantee: one that reads as complete.
#:
#: So the guarantee is structural instead. On a `solaris.*` logger a message must be a
#: bare event name; free text is replaced entirely, and the values that would have been
#: interpolated into it belong in allowlisted structured fields where the field name
#: decides. An `f`-string with a customer's name in it cannot reach a log file, not
#: because the name was recognized but because the sentence was never allowed through.
#:
#: Third-party loggers are treated differently and more leniently -- see `filter`.
_STRICT_MESSAGE_RULE = True

#: Fields that carry a value from a fixed vocabulary rather than free text: an outcome,
#: an error category, an enum, an HTTP method, a role. Their values are constrained to a
#: safe token shape, and anything else is replaced with `[invalid]`.
#:
#: This closes the last gap the sentinel tests found. A customer name planted into
#: `outcome` survived both earlier defences -- the field is allowlisted, so the name
#: check passed it, and a name has no detectable shape, so redaction passed it too. The
#: field's *contract* was the only thing saying it could not happen, and a contract
#: nothing enforces is a comment. `Nguyễn Thị Bích Hạnh` has spaces, capitals and
#: diacritics; `not_found` does not.
_VOCABULARY_FIELDS = frozenset(
    {
        "outcome",
        "surface",
        "error_code",
        "error_category",
        "error_type",
        "reason_code",
        "check",
        "role",
        "entity_type",
        "job_type",
        "provider_key",
        "method",
        "signal",
    }
)

#: What an application constant actually looks like, in the three shapes this codebase
#: produces. Anything matching is kept verbatim; anything else is redacted and then
#: required to still look like a token, and replaced outright if it does not.
#:
#: The shapes are deliberately narrow, and the narrowness is doing the work:
#:
#: * `not_found`, `rate_limited`, `public_help_url_empty`, `database,migrations` -- lower
#:   snake_case, optionally joined. `_SECRET_SHAPED` would otherwise eat any of these
#:   that reaches 24 characters, which `public_carrier_link_hosts_empty` does.
#: * `GET`, `POST`, `OPTIONS` -- an HTTP method, capped at seven characters so a long
#:   all-caps sentinel cannot pose as one.
#: * `ValueError`, `OperationalError` -- an exception class name. Requires lowercase
#:   after each capital, so `SENTINELCSRFTOKENVALUE0123456789` does not qualify.
_SAFE_CONSTANT = re.compile(
    r"\A(?:"
    r"[a-z][a-z0-9_]*(?:[,.:][a-z][a-z0-9_]*)*"
    r"|[A-Z]{3,7}"
    r"|[A-Z][a-z0-9]+(?:[A-Z][a-z0-9]+)*"
    r")\Z"
)

#: A vocabulary token, checked *after* redaction. Commas are allowed because the
#: readiness event joins failing check names into one value.
_VOCABULARY_TOKEN = re.compile(r"\A[A-Za-z0-9_.:,+-]{1,80}\Z")

#: What replaces a vocabulary field whose value is not a vocabulary token.
INVALID_VALUE = "[invalid]"

#: Fields whose values are exempt from value redaction, because they are generated by
#: this application, are non-reversible by construction, and exist precisely so that
#: something unloggable can still be correlated.
#:
#: This exemption was forced by a real failure rather than chosen up front.
#: `reference_digest=1a2b3c4d5e6f` is a 29-character run of `[A-Za-z0-9=_-]` once the key
#: and the `=` are counted, so `redact_text` classified the whole pair as secret-shaped
#: and replaced it -- silently removing the one field Phase 3 added so that repeated
#: probing of a single reference could be noticed (DEC-0057). Redacting a keyed HMAC
#: digest protects nothing and costs the signal it was created for.
#:
#: Membership here is narrow on purpose. A field qualifies only if the application
#: produced its value and that value cannot be turned back into anything private.
_OPAQUE_FIELDS = frozenset(
    {"correlation_id", "reference_digest", "payload_digest", "identity_digest"}
)

#: Third-party loggers whose INFO output is noise at best and a privacy question at
#: worst. `httpx` logs the full request URL; `alembic.runtime` narrates every migration
#: plugin on startup. Neither is an operational signal, and the redaction filter should
#: not be the only thing standing between a library's idea of a useful log line and the
#: log file. Raised to WARNING rather than silenced, so genuine problems still surface.
_NOISY_LOGGERS = ("httpx", "httpcore", "alembic.runtime", "multipart")

#: Attributes the logging module puts on every record. Never treated as caller extras.
_RESERVED = frozenset(
    {
        "args",
        "asctime",
        "created",
        "exc_info",
        "exc_text",
        "filename",
        "funcName",
        "levelname",
        "levelno",
        "lineno",
        "module",
        "msecs",
        "message",
        "msg",
        "name",
        "pathname",
        "process",
        "processName",
        "relativeCreated",
        "stack_info",
        "stacklevel",
        "taskName",
        "thread",
        "threadName",
    }
)

#: Structured fields a log record may carry. Every one of these is either a category the
#: application chose, a count, a duration, a boolean, or an opaque identifier. None of
#: them is a customer value, a free-text field, a file path, or anything a caller typed.
#:
#: Adding a name here is a privacy decision. The question to ask is not "is this useful?"
#: but "could this field ever hold something a customer told us, or something that would
#: let somebody look up a parcel?"
SAFE_FIELDS = frozenset(
    {
        # Identity of the record
        "event",
        "correlation_id",
        "outcome",
        # HTTP. `route` is the *template* -- `/api/v1/public/track/{reference}` -- never
        # the resolved path, which for public tracking contains the reference itself.
        "method",
        "route",
        "status_code",
        "duration_ms",
        "request_bytes",
        "response_bytes",
        # Who, coarsely. A user id and a role, never a name or an email address.
        "user_id",
        "role",
        "client_key",
        # What, coarsely. An entity type and its internal integer id; never its public
        # identifier, which is a lookup key on the public tracking page.
        "entity_type",
        "entity_id",
        "count",
        # Keyed, non-reversible stand-ins.
        "reference_digest",
        "payload_digest",
        # Errors, as categories.
        "error_code",
        "error_category",
        "error_type",
        "retry_after",
        # The integration worker (Phase 4A vocabulary, unchanged).
        "worker",
        "worker_name",
        "job_id",
        "job_type",
        "provider_key",
        "attempt",
        "claimed",
        "succeeded",
        "failed",
        "reclaimed",
        # Startup, shutdown, readiness.
        "environment",
        "check",
        "ready",
        "reason_code",
        "signal",
        # The authenticated Customer Account read surface (Phase 11). Four fields, and
        # each one is here because it answers an operational question -- "is this session
        # paging or scraping?" -- without carrying anything a customer told us.
        #
        # `identity_digest` is a **keyed** stand-in for the account reference, not the
        # reference itself. The account holder's `CA-` id is safe in an audit row, which is
        # staff-facing and access-controlled; a log line travels further, through shippers
        # and search indexes, and a stable non-reversible digest correlates a session's
        # requests just as well without putting an identifier in any of them.
        "identity_digest",
        "surface",
        "page_size",
        "returned",
        # Diagnostics about the filter itself.
        "dropped_fields",
    }
)


def new_correlation_id() -> str:
    """A fresh opaque identifier. Carries no meaning and no caller input."""
    return uuid.uuid4().hex


def accept_correlation_id(supplied: str | None) -> str:
    """Believe a caller's correlation id only if it is safe, otherwise mint one.

    Accepting arbitrary caller text would let a caller write whatever they liked into
    every log line for the request -- including a newline and a convincing second record.
    """
    if supplied and _SAFE_CORRELATION_ID.match(supplied):
        return supplied
    return new_correlation_id()


def set_correlation_id(value: str | None) -> object:
    return _correlation_id.set(value)


def reset_correlation_id(token: object) -> None:
    _correlation_id.reset(token)  # type: ignore[arg-type]


def current_correlation_id() -> str | None:
    return _correlation_id.get()


class SafetyFilter(logging.Filter):
    """Drops unsafe fields, redacts what is left, and discards exception text.

    A filter rather than a formatter so it applies once per record, before any handler
    sees it. A second handler added later -- a file, a syslog socket -- inherits the same
    guarantees without having to be told about them.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        record.correlation_id = current_correlation_id()

        try:
            rendered = record.getMessage()
        except Exception:  # pragma: no cover - a broken format string
            rendered = str(record.msg)

        is_event_name = not record.args and bool(_EVENT_NAME.match(rendered))
        if is_event_name:
            # Application-chosen, uninterpolated, kept verbatim.
            record.msg = rendered
        elif record.name.split(".")[0] == _OWN_LOGGER_PREFIX:
            # One of ours, and not an event name. Suppressed rather than redacted: a
            # name or an address has no shape to match on, so redaction cannot be
            # trusted here and the sentence is dropped whole. The call site should be
            # using `log_event` with structured fields.
            record.msg = SUPPRESSED_MESSAGE
        else:
            # Third-party. Its message is prose this application does not control, and
            # suppressing it would discard genuinely useful failures -- a port already
            # in use, a TLS handshake error. Redacted on a best-effort basis, and the
            # noisiest of these loggers are raised to WARNING in `configure_logging`.
            record.msg = redact_text(rendered) or ""
        record.args = ()

        dropped: list[str] = []
        for key in list(record.__dict__):
            if key in _RESERVED or key == "correlation_id":
                continue
            if key not in SAFE_FIELDS:
                dropped.append(key)
                del record.__dict__[key]
                continue
            value = record.__dict__[key]
            if not isinstance(value, str) or key in _OPAQUE_FIELDS:
                continue
            if key in _VOCABULARY_FIELDS:
                # Both defences, in order. A recognized application constant is kept as
                # it is; anything else is redacted *and then* required to still look like
                # a token. Shape-checking alone would have passed `SX-CAV-7K9D2M4R8T6W`
                # and a CSRF token, both of which are perfectly well-formed tokens.
                if _SAFE_CONSTANT.match(value):
                    continue
                cleaned = redact_text(value) or ""
                record.__dict__[key] = (
                    cleaned if _VOCABULARY_TOKEN.match(cleaned) else INVALID_VALUE
                )
            else:
                record.__dict__[key] = redact_text(value)

        # A traceback ends in the exception's str(), which routinely carries the query,
        # the URL, or the value that failed validation. Keep the type, discard the rest.
        if record.exc_info:
            exc_type = record.exc_info[0]
            record.error_type = exc_type.__name__ if exc_type else "unknown"
            record.exc_info = None
            record.exc_text = None

        if dropped:
            record.dropped_fields = sorted(dropped)

        return True


class JsonFormatter(logging.Formatter):
    """One JSON object per line.

    Only fields that survived `SafetyFilter` are serialized. The formatter does not
    redact: doing it in two places would invite the belief that either one alone is
    sufficient.
    """

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "event": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key in _RESERVED or key == "event":
                continue
            if (key in SAFE_FIELDS or key == "correlation_id") and value is not None:
                payload[key] = value
        return json.dumps(payload, ensure_ascii=False, default=str, sort_keys=True)


def configure_logging(*, level: str = "INFO", json_output: bool = True) -> None:
    """Install the filter and formatter on the root logger.

    Idempotent: calling it twice replaces the handler rather than adding a second one,
    which would double every line.
    """
    handler = logging.StreamHandler(stream=sys.stdout)
    handler.setFormatter(
        JsonFormatter()
        if json_output
        else logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    )
    handler.addFilter(SafetyFilter())

    root = logging.getLogger()
    for existing in list(root.handlers):
        root.removeHandler(existing)
    root.addHandler(handler)
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    # Uvicorn installs its own access logger whose message is the raw request line --
    # including the resolved path, which for public tracking is the tracking reference.
    # The application logs its own `http_request` event with the route *template*
    # instead, so the duplicate is turned off rather than filtered.
    logging.getLogger("uvicorn.access").handlers = []
    logging.getLogger("uvicorn.access").propagate = False

    for name in _NOISY_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)


def log_event(logger: logging.Logger, level: int, event: str, **fields: object) -> None:
    """Emit a structured record.

    `event` is a stable name -- `http_request`, `startup_complete`, `readiness_failed` --
    chosen so an operator can alert on it without matching prose that may be reworded.
    """
    logger.log(level, event, extra=fields)
