"""Redaction for integration logs, stored error summaries, and audit entries.

Three kinds of value must never reach a log file, an error column, or an audit row:

* **credentials** -- API keys, bearer tokens, signatures, cookies;
* **customer data** -- names, addresses, emails, phone numbers, and the raw provider
  payloads that carry them;
* **tracking references** -- Solaris identifiers are privacy-sensitive (CRM.md
  section 10, DEC-0057), and so are carrier tracking numbers, which are lookup keys on
  somebody else's system.

The approach is **allowlist-shaped**: an error summary is a category and a short phrase
chosen by the application, never a provider message passed through. The functions here
are the second line rather than the first -- ``safe_summary`` is applied on the way to the
database even when the caller already believes the value is safe, because a boundary
enforced at one end is enforced nowhere.

``redact_url`` deserves its own note. A provider URL can carry a tracking number in its
path and a token in its query, so nothing keeps the path or the query. What survives is
the scheme, the host, and a short digest, which is enough to tell two hosts apart in a log
without writing down where anybody's parcel is.
"""

from __future__ import annotations

import hashlib
import re
from urllib.parse import urlparse

#: Longest stored summary. Anything longer is a payload in disguise.
MAX_SUMMARY_LENGTH = 240

_REPLACEMENT = "[redacted]"

#: A Solaris Shipment ID or package reference, in any case. Matched loosely on purpose:
#: this exists to catch a value that slipped into a message, so over-matching costs a few
#: characters of a log line and under-matching costs a privacy guarantee.
_SOLARIS_REFERENCE = re.compile(r"\bSX[-_ ]?[A-Z]{3}[-_ ]?[A-Z0-9]{8,}(?:[-_ ]?\d{2})?\b", re.I)

#: An email address.
_EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")

#: A run of digits long enough to be a carrier tracking number, a phone number, or an
#: account identifier. Short runs -- attempt counts, status codes, seconds -- survive.
_LONG_DIGITS = re.compile(r"\b\d{7,}\b")

#: Anything URL-shaped. Replaced wholesale by ``redact_url``.
_URL = re.compile(r"\b[a-zA-Z][a-zA-Z0-9+.-]*://\S+")

#: Values that look like a key, token, or signature: long unbroken runs of
#: base64/hex-ish characters.
_SECRET_SHAPED = re.compile(r"\b[A-Za-z0-9+/=_-]{24,}\b")

#: An authorization value, with whatever follows the scheme.
#:
#: Added because a length-based rule was not enough, and a test caught it:
#: ``Bearer super-secret-token`` is eighteen characters of token and sailed past
#: ``_SECRET_SHAPED``. The scheme word is the reliable signal, so everything after it goes,
#: however short it is.
_AUTH_VALUE = re.compile(r"\b(?:bearer|basic|digest)\s+\S+", re.I)

#: ``key=value`` where the key names something secret. Covers ``token=``, ``api_key=``,
#: ``signature=``, ``password=``, and the query-string forms of each.
_KEYED_SECRET = re.compile(
    r"\b(?:api[_-]?key|apikey|access[_-]?token|auth[_-]?token|token|secret|password|"
    r"passwd|signature|sig|session)\s*[=:]\s*\S+",
    re.I,
)

#: A carrier or provider tracking reference: a run of uppercase letters, digits, and
#: hyphens, at least eight characters long, containing at least one digit.
#:
#: Also caught by a test rather than by foresight. ``FAKE-TRACK-0001`` and
#: ``1Z999AA10123456784`` are both tracking references and neither is a long digit run or a
#: Solaris identifier, so both survived every earlier pattern. Requiring a digit is what
#: keeps ordinary words and enum values -- which are lowercase in every log line this
#: application writes -- out of the way.
_REFERENCE_SHAPED = re.compile(r"\b(?=[A-Z0-9-]{8,}\b)(?=[A-Z0-9-]*\d)[A-Z0-9]+(?:-[A-Z0-9]+)*\b")

#: Header names whose values are never recorded anywhere, in any form.
FORBIDDEN_HEADERS = frozenset(
    {
        "authorization",
        "proxy-authorization",
        "cookie",
        "set-cookie",
        "x-api-key",
        "api-key",
        "apikey",
        "x-auth-token",
        "x-access-token",
        "x-signature",
        "signature",
        "x-hub-signature",
        "x-hub-signature-256",
    }
)

#: Header names it is safe to keep for diagnosis. An allowlist rather than a blocklist,
#: because a blocklist is a list of the header names somebody thought of.
SAFE_HEADERS = frozenset({"content-type", "content-length", "user-agent", "date"})


def redact_url(value: str | None) -> str:
    """Reduce a URL to scheme, host, and a digest of the rest.

    The path can carry a tracking number and the query can carry a token, so neither is
    kept. The digest is stable, so two log lines about the same URL can still be
    correlated without the URL being written down.
    """
    if not value:
        return _REPLACEMENT
    try:
        parsed = urlparse(value.strip())
    except ValueError:
        return _REPLACEMENT
    host = (parsed.hostname or "unknown").lower()
    digest = hashlib.sha256(value.strip().encode("utf-8")).hexdigest()[:8]
    return f"{parsed.scheme or 'unknown'}://{host}/[path:{digest}]"


def redact_text(value: str | None) -> str | None:
    """Strip identifiers, addresses, secrets, and URLs out of free text.

    Used on anything that might have come from a provider, an exception, or a caller who
    was not thinking about privacy at the time.
    """
    if value is None:
        return None
    # Order matters. URLs go first, because a URL contains characters every later pattern
    # would otherwise chew on; authorization values go before the shape-based rules,
    # because the scheme word is a far more reliable signal than any length threshold.
    cleaned = _URL.sub(lambda match: redact_url(match.group(0)), value)
    cleaned = _AUTH_VALUE.sub(_REPLACEMENT, cleaned)
    cleaned = _KEYED_SECRET.sub(_REPLACEMENT, cleaned)
    cleaned = _EMAIL.sub(_REPLACEMENT, cleaned)
    cleaned = _SOLARIS_REFERENCE.sub(_REPLACEMENT, cleaned)
    cleaned = _SECRET_SHAPED.sub(_REPLACEMENT, cleaned)
    cleaned = _REFERENCE_SHAPED.sub(_REPLACEMENT, cleaned)
    cleaned = _LONG_DIGITS.sub(_REPLACEMENT, cleaned)
    return cleaned


def safe_summary(value: str | None) -> str | None:
    """Redact, collapse whitespace, and bound. What goes into an ``error_summary``."""
    cleaned = redact_text(value)
    if cleaned is None:
        return None
    cleaned = " ".join(cleaned.split())
    if not cleaned:
        return None
    if len(cleaned) > MAX_SUMMARY_LENGTH:
        cleaned = cleaned[: MAX_SUMMARY_LENGTH - 1].rstrip() + "…"
    return cleaned


def safe_exception_summary(error: BaseException) -> str:
    """A summary of an exception that cannot leak what the exception was carrying.

    Deliberately not ``str(error)`` by default. A provider client raises exceptions whose
    text contains the request URL, and sometimes the request headers -- which is how a
    credential ends up in a log without anybody having decided to put it there. The type
    name is the reliable part; anything the adapter genuinely wants recorded it passes as
    a ``ProviderAdapterError.summary``, which it chose deliberately.
    """
    from app.integrations.adapter import ProviderAdapterError

    if isinstance(error, ProviderAdapterError):
        return safe_summary(error.summary) or type(error).__name__
    return type(error).__name__


def safe_headers(headers: dict[str, str] | None) -> dict[str, str]:
    """The headers it is safe to keep, with the rest dropped rather than masked.

    Dropped, not masked: a masked entry still records that the request carried a
    particular header, and the stored value has no use that would justify keeping even
    that. ``FORBIDDEN_HEADERS`` exists as a named list so the intent is greppable, but the
    allowlist is what actually decides.
    """
    if not headers:
        return {}
    return {
        key.lower(): value
        for key, value in headers.items()
        if key.lower() in SAFE_HEADERS and key.lower() not in FORBIDDEN_HEADERS
    }


def payload_digest(body: bytes) -> str:
    """SHA-256 of exactly the bytes received.

    Survives the body itself being refused for size, so an oversized delivery that is
    sent again is still recognizable as the same delivery.
    """
    return hashlib.sha256(body).hexdigest()


def reference_token(value: str | None, *, secret: str) -> str:
    """A keyed, truncated token standing in for a tracking reference in a log.

    The same device DEC-0057 uses on the public surface, for the same reason: an operator
    needs to see that one reference keeps failing, and does not need the reference to do
    it. Not reversible without the application secret.
    """
    import hmac

    if not value:
        return "empty"
    return hmac.new(secret.encode("utf-8"), value.encode("utf-8"), hashlib.sha256).hexdigest()[:12]
