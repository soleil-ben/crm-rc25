"""A deterministic fake provider adapter, for tests only.

**This is not ShipStation, and it is not a model of ShipStation.** Its provider key is
``fake``, its statuses are invented words chosen precisely because no real carrier uses
them, and its "signature" is an HMAC this file made up. It exists to exercise the
infrastructure -- deduplication, leasing, retries, authenticity gating, mapping, the
resource policy -- not to anticipate a provider nobody has verified.

Building a "shipstation" adapter here against guessed fixtures would have been worse than
having none. It would encode assumptions about a product, an API generation, an
authentication scheme, an event vocabulary, and a signature algorithm that
``docs/INTEGRATIONS.md`` section 3 lists as *unknown*, and the tests passing against those
guesses would read as evidence that the integration works.

It cannot reach production. It lives under ``tests/``, which is not packaged; its key is
``fake``; and ``AdapterRegistry.register`` refuses outright while the environment is
production. Three independent reasons, because the cost of being wrong is a synthetic
provider answering a real customer.

Every behaviour is switchable, so one class covers success, duplicate delivery, timeout,
rate limiting with ``Retry-After``, provider server errors, malformed payloads,
authentication failure, invalid signature, unsigned notification, and mapping failure --
each of which is a case CRM.md section 9 requires to be handled and therefore a case that
has to be reachable in a test.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime

from app.core.enums import (
    OccurredTimeProvenance,
    ProviderErrorKind,
    ShipmentEventType,
)
from app.integrations.adapter import (
    AuthoritativeTrackingState,
    NormalizedProviderEvent,
    ParsedNotification,
    ProviderAdapterError,
    ProviderCapabilities,
    ProviderEventIdentity,
    ResourceHostPolicy,
)

#: Visibly a fake, in the one field that reaches every database row.
FAKE_PROVIDER_KEY = "fake"
FAKE_API_VERSION = "fake-v0"
FAKE_MAPPING_VERSION = "fake-map-1"

#: The secret the fake signs with. A test constant, and obviously so.
FAKE_SIGNING_SECRET = "fake-adapter-signing-secret-not-a-real-credential"
FAKE_SIGNATURE_HEADER = "x-fake-signature"

#: Invented status words. Deliberately not the vocabulary of any real carrier, so a
#: reader cannot mistake this mapping for one that was researched.
FAKE_STATUS_MAP: dict[str, tuple[str, bool]] = {
    "FAKE_PICKED_UP": (ShipmentEventType.RECEIVED_AT_SOLARIS, False),
    "FAKE_MOVING": (ShipmentEventType.IN_TRANSIT, False),
    "FAKE_AT_BORDER": (ShipmentEventType.CUSTOMS_PROCESSING, False),
    "FAKE_ARRIVED": (ShipmentEventType.ARRIVED_DESTINATION, False),
    "FAKE_ON_VAN": (ShipmentEventType.OUT_FOR_DELIVERY, False),
    "FAKE_HANDED_TO_RECIPIENT": (ShipmentEventType.DELIVERED_TO_RECIPIENT, True),
    "FAKE_LEFT_AT_LOCKER": (ShipmentEventType.DELIVERED_TO_COLLECTION_POINT, False),
    "FAKE_AT_OUR_WAREHOUSE": (ShipmentEventType.RECEIVED_AT_SOLARIS, False),
    "FAKE_PROBLEM": (ShipmentEventType.EXCEPTION, False),
    "FAKE_GOING_BACK": (ShipmentEventType.RETURN_IN_PROGRESS, False),
}


def sign(body: bytes, *, secret: str = FAKE_SIGNING_SECRET) -> str:
    """The fake signature scheme. Invented here; no provider uses it."""
    return hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


def make_payload(
    *,
    event_id: str | None = "fake-event-1",
    reference: str = "FAKE-TRACK-0001",
    status: str = "FAKE_MOVING",
    occurred_at: str | None = "2026-09-01T10:00:00+00:00",
    detail: str = "Fake provider narrative text",
    resource_url: str | None = None,
) -> bytes:
    """A synthetic delivery body. JSON, because the fake declares JSON."""
    payload = {
        "eventId": event_id,
        "reference": reference,
        "status": status,
        "occurredAt": occurred_at,
        "detail": detail,
    }
    if resource_url is not None:
        payload["resourceUrl"] = resource_url
    return json.dumps(payload, sort_keys=True).encode("utf-8")


def signed_headers(body: bytes, *, secret: str = FAKE_SIGNING_SECRET) -> dict[str, str]:
    return {"content-type": "application/json", FAKE_SIGNATURE_HEADER: sign(body, secret=secret)}


def unsigned_headers() -> dict[str, str]:
    return {"content-type": "application/json"}


@dataclass
class FakeProviderAdapter:
    """A provider adapter whose every behaviour is a switch.

    The defaults describe the most demanding honest provider: it signs its webhooks and it
    supports an authenticated read. Turning ``verifies_signatures`` off is how the
    unsigned-notification path is exercised, which is the case CRM.md section 9 spends the
    most words on and the one a real provider may well turn out to be.
    """

    verifies_signatures: bool = True
    supports_authenticated_read: bool = True
    supplies_event_ids: bool = True
    tracks_external_labels: bool = False
    supports_webhooks: bool = True
    supplies_resource_urls: bool = False

    #: Raise this from ``fetch_authoritative_state``. Set per test.
    read_error: ProviderAdapterError | None = None
    #: What an authenticated read returns when it succeeds.
    read_status: str = "FAKE_MOVING"
    read_occurred_at: datetime | None = None
    read_event_id: str | None = "fake-read-1"
    #: Raise a mapping failure regardless of status.
    fail_mapping: bool = False
    #: Signing secret the verifier checks against. Change it to simulate a forgery.
    signing_secret: str = FAKE_SIGNING_SECRET
    #: How many authenticated reads have happened. A count, so a test can prove that a
    #: notification caused exactly one provider question -- or none at all.
    read_calls: list[str] = field(default_factory=list)
    #: Hosts and paths this fake would permit a resource fetch from.
    allowed_hosts: frozenset[str] = field(
        default_factory=lambda: frozenset({"resources.fake-provider.test"})
    )
    allowed_path_prefixes: tuple[str, ...] = ("/fake/v0/events/",)

    # --- Contract ----------------------------------------------------------

    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            provider_key=FAKE_PROVIDER_KEY,
            provider_api_version=FAKE_API_VERSION,
            mapping_version=FAKE_MAPPING_VERSION,
            verifies_signatures=self.verifies_signatures,
            supplies_event_ids=self.supplies_event_ids,
            tracks_external_labels=self.tracks_external_labels,
            supports_authenticated_read=self.supports_authenticated_read,
            supports_webhooks=self.supports_webhooks,
            supplies_resource_urls=self.supplies_resource_urls,
            documented_requests_per_minute=None,
        )

    def verify_webhook(self, *, body: bytes, headers: dict[str, str]) -> tuple[bool, str]:
        supplied = headers.get(FAKE_SIGNATURE_HEADER)
        if not supplied:
            # Distinguished from "invalid" so the inbox can record which happened. Both
            # refuse to apply; only the reason differs, and an operator wants the reason.
            return False, "signature_missing"
        expected = sign(body, secret=self.signing_secret)
        if not hmac.compare_digest(supplied, expected):
            return False, "signature did not match"
        return True, "signature verified"

    def extract_identity(self, *, body: bytes, headers: dict[str, str]) -> ProviderEventIdentity:
        data = json.loads(body.decode("utf-8"))
        event_id = data.get("eventId") if self.supplies_event_ids else None

        # The fingerprint covers only fields that cannot change for one real-world event.
        # ``detail`` is excluded deliberately: providers reword narrative text between
        # deliveries, and a fingerprint that moved with it would fail to recognize a
        # replay of the same event -- which is exactly what it exists to catch.
        material = "\x1f".join(
            str(data.get(key, "")) for key in ("reference", "status", "occurredAt")
        )
        fingerprint = hashlib.sha256(material.encode("utf-8")).hexdigest()
        return ProviderEventIdentity(event_id=event_id, fingerprint=fingerprint)

    def parse_notification(self, *, body: bytes, headers: dict[str, str]) -> ParsedNotification:
        try:
            data = json.loads(body.decode("utf-8"))
        except json.JSONDecodeError as error:
            raise ProviderAdapterError(
                ProviderErrorKind.MALFORMED_PAYLOAD, "body is not valid JSON"
            ) from error

        occurred_at, provenance, zone = _read_time(data.get("occurredAt"))
        return ParsedNotification(
            identity=self.extract_identity(body=body, headers=headers),
            provider_reference=data.get("reference"),
            raw_status=data.get("status"),
            raw_status_detail=data.get("detail"),
            occurred_at=occurred_at,
            occurred_at_timezone=zone,
            occurred_time_provenance=provenance,
            resource_url=data.get("resourceUrl"),
        )

    def fetch_authoritative_state(self, *, provider_reference: str) -> AuthoritativeTrackingState:
        self.read_calls.append(provider_reference)
        if self.read_error is not None:
            raise self.read_error
        occurred = self.read_occurred_at or datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
        material = f"{provider_reference}\x1f{self.read_status}\x1f{occurred.isoformat()}"
        return AuthoritativeTrackingState(
            provider_reference=provider_reference,
            raw_status=self.read_status,
            raw_status_detail="Fake authoritative read",
            occurred_at=occurred.replace(tzinfo=None),
            occurred_at_timezone="UTC",
            occurred_time_provenance=OccurredTimeProvenance.PROVIDER_UTC,
            identity=ProviderEventIdentity(
                event_id=self.read_event_id,
                fingerprint=hashlib.sha256(material.encode("utf-8")).hexdigest(),
            ),
        )

    def normalize(
        self, source: ParsedNotification | AuthoritativeTrackingState
    ) -> NormalizedProviderEvent:
        if self.fail_mapping:
            raise ProviderAdapterError(
                ProviderErrorKind.MAPPING, "fake adapter was told to fail mapping"
            )

        raw = source.raw_status
        mapped = FAKE_STATUS_MAP.get(raw or "")
        if mapped is None:
            # An unmapped status is a mapping failure, never a guess. Inventing a
            # plausible state would put a milestone in front of a customer that nobody
            # reported.
            raise ProviderAdapterError(
                ProviderErrorKind.MAPPING,
                "the fake adapter has no mapping for this status",
            )

        event_type, is_final = mapped
        identity = source.identity
        if identity is None:
            raise ProviderAdapterError(ProviderErrorKind.MAPPING, "no event identity was available")

        from app.core.enums import EVENT_TYPE_TO_OPERATIONAL_STATE

        return NormalizedProviderEvent(
            event_type=event_type,
            operational_state=EVENT_TYPE_TO_OPERATIONAL_STATE[event_type],
            identity=identity,
            raw_status=raw,
            raw_status_detail=source.raw_status_detail,
            occurred_at=source.occurred_at,
            occurred_at_timezone=source.occurred_at_timezone,
            occurred_time_provenance=source.occurred_time_provenance,
            is_final_recipient_delivery=is_final,
        )

    def classify_error(self, error: Exception) -> ProviderErrorKind:
        if isinstance(error, ProviderAdapterError):
            return error.kind
        if isinstance(error, TimeoutError):
            return ProviderErrorKind.RETRYABLE
        return ProviderErrorKind.RETRYABLE

    def resource_policy(self) -> ResourceHostPolicy:
        return ResourceHostPolicy(
            allowed_hosts=self.allowed_hosts,
            allowed_path_prefixes=self.allowed_path_prefixes,
            allowed_ports=frozenset({443}),
            max_redirects=2,
            max_response_bytes=64 * 1024,
            timeout_seconds=5.0,
            allowed_content_types=frozenset({"application/json"}),
        )


def _read_time(
    value: str | None,
) -> tuple[datetime | None, OccurredTimeProvenance, str | None]:
    """Parse a provider timestamp, recording how much is actually known about it.

    Three genuinely different cases, kept apart because CRM.md section 9 requires missing
    timezone information to be explicit:

    * an explicit UTC instant -- trustworthy;
    * an explicit offset -- converted, and recorded as having come with an offset;
    * a bare wall-clock time -- stored, flagged ``local_no_timezone``, and **not** assumed
      to be UTC. A four-hour error in a delivery time is a customer complaint.
    """
    if not value:
        return None, OccurredTimeProvenance.MISSING, None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None, OccurredTimeProvenance.MISSING, None

    if parsed.tzinfo is None:
        return parsed, OccurredTimeProvenance.LOCAL_NO_TIMEZONE, None
    if parsed.utcoffset() == UTC.utcoffset(None):
        return (
            parsed.astimezone(UTC).replace(tzinfo=None),
            OccurredTimeProvenance.PROVIDER_UTC,
            "UTC",
        )
    return (
        parsed.astimezone(UTC).replace(tzinfo=None),
        OccurredTimeProvenance.PROVIDER_OFFSET,
        str(parsed.tzinfo),
    )


# --- Ready-made failures ----------------------------------------------------
#
# Named so a test reads as the scenario it is exercising rather than as a construction of
# an exception, and so the classification each one carries is stated once.

TIMEOUT = ProviderAdapterError(ProviderErrorKind.RETRYABLE, "provider request timed out")
RATE_LIMITED = ProviderAdapterError(
    ProviderErrorKind.RATE_LIMITED, "provider asked us to slow down", retry_after_seconds=120
)
SERVER_ERROR = ProviderAdapterError(ProviderErrorKind.RETRYABLE, "provider reported a server error")
AUTH_FAILED = ProviderAdapterError(
    ProviderErrorKind.AUTHENTICATION, "provider rejected the credential"
)
MALFORMED = ProviderAdapterError(
    ProviderErrorKind.MALFORMED_PAYLOAD, "provider sent something unparseable"
)
PERMANENT = ProviderAdapterError(ProviderErrorKind.PERMANENT, "provider says this is settled")
