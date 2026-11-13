"""The provider adapter contract.

This file is the boundary CRM.md section 9 requires: *the rest of the application must
not depend on raw provider status codes.* Everything a provider integration needs to do
is expressed here as capabilities and application vocabulary, and nothing outside
``app/integrations/`` may import a provider response structure, a provider status string,
a provider HTTP code, or a provider header name.

**What this deliberately does not do.** It does not describe ShipStation. The account's
product, API generation, entitlements, authentication scheme, webhook event types,
signature mechanism, rate limits, external-label tracking support, and resource hosts are
all unverified (``docs/INTEGRATIONS.md`` section 3), and legacy ShipStation,
ShipStation V2, and ShipStation API / ShipEngine must not be treated as interchangeable.
So the contract asks an adapter to *declare* what it can do rather than assuming it:

* Does it verify signatures at all? -- ``ProviderCapabilities.verifies_signatures``
* Can it track a label it did not purchase? -- ``tracks_external_labels``
* Does it emit event identifiers? -- ``supplies_event_ids``
* Which hosts and paths may a resource URL use? -- ``resource_policy()``

A capability answered honestly as "no" is the useful case, not the degraded one. If a
provider turns out not to sign its webhooks, ``verifies_signatures = False`` is what makes
the worker refuse to mutate state from a notification and enqueue an authenticated read
instead. If it cannot track an externally purchased label, saying so is what lets the
interface tell staff the truth rather than showing a permanently empty timeline.

**The only implementation is a fake, and it lives in the test suite.**
``app/integrations/registry.py`` ships empty and refuses to register anything while the
environment is production. See ``backend/tests/fakes/fake_provider_adapter.py``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol, runtime_checkable

from app.core.enums import OccurredTimeProvenance, ProviderErrorKind


class ProviderAdapterError(Exception):
    """A failure an adapter raises, already classified for the worker.

    The adapter owns classification because only the adapter knows what a given
    provider's failure means. The worker owns the response, and reads nothing but
    ``kind`` and ``retry_after_seconds`` -- which is what keeps the retry policy free of
    provider status codes.

    ``summary`` must already be safe to store: no payload, no credential, no URL, no
    tracking reference. ``integration_redaction.safe_summary`` is applied again on the way
    to the database, because a boundary that is only enforced at one end is enforced
    nowhere.
    """

    def __init__(
        self,
        kind: ProviderErrorKind,
        summary: str,
        *,
        retry_after_seconds: int | None = None,
    ) -> None:
        super().__init__(summary)
        self.kind = kind
        self.summary = summary
        #: What the provider asked for, when it asked. Honoured for a rate limit.
        self.retry_after_seconds = retry_after_seconds


@dataclass(frozen=True)
class ProviderCapabilities:
    """What an adapter can actually do, declared rather than assumed.

    Every field defaults to the conservative answer. An adapter that forgets to declare a
    capability is treated as not having it, which fails closed: an undeclared signature
    capability means notifications stay untrusted, and an undeclared external-label
    capability means the interface does not promise tracking it cannot deliver.
    """

    #: The adapter identity used in ``provider_key`` columns.
    provider_key: str
    #: The provider API generation this adapter speaks. Explicit because CRM.md section 9
    #: forbids treating provider generations as interchangeable.
    provider_api_version: str
    #: Revision of the status mapping. Stored on every normalized event, so a mapping
    #: change is auditable against the history it produced.
    mapping_version: str

    #: Whether the provider signs webhooks in a way this adapter can verify. **False
    #: means every notification is untrusted** and may only enqueue an authenticated read
    #: (CRM.md section 9).
    verifies_signatures: bool = False
    #: Whether the provider supplies a stable event identifier. False means deduplication
    #: falls back to a fingerprint over the immutable event fields.
    supplies_event_ids: bool = False
    #: Whether the provider can report tracking for a label bought elsewhere. False is a
    #: limitation to display, not to hide (CRM.md section 9).
    tracks_external_labels: bool = False
    #: Whether an authoritative authenticated read is available at all. Without it an
    #: unsigned notification can never be promoted, and the honest answer is manual mode.
    supports_authenticated_read: bool = False
    #: Whether the provider delivers webhooks. False means reconciliation only.
    supports_webhooks: bool = False
    #: Whether payloads may carry a resource URL the server would have to fetch.
    supplies_resource_urls: bool = False
    #: Documented request budget, when the provider documents one. ``None`` means
    #: unverified, and the worker paces itself conservatively rather than guessing.
    documented_requests_per_minute: int | None = None


@dataclass(frozen=True)
class ProviderEventIdentity:
    """How one delivered event is recognized again.

    Deduplication is independent of authenticity: a forged replay must still be
    recognized as a replay, so identity is extracted from an unverified payload and the
    verification result is recorded separately.
    """

    #: The provider identifier, when the provider supplies one.
    event_id: str | None
    #: A digest over the fields that cannot change for a given real-world event. The
    #: adapter chooses which those are, because only it knows which fields the provider
    #: rewrites between deliveries -- a fingerprint over a retry counter or a delivery
    #: timestamp would defeat the entire mechanism.
    fingerprint: str


@dataclass(frozen=True)
class ParsedNotification:
    """What an untrusted notification claims, with nothing acted on yet.

    Every field is a claim. Nothing here has been verified against the provider, and
    nothing here may mutate business state on its own.
    """

    identity: ProviderEventIdentity
    #: The provider tracking number or label identifier the notification refers to, used
    #: to find the Solaris tracking assignment. A claim like any other.
    provider_reference: str | None = None
    raw_status: str | None = None
    raw_status_detail: str | None = None
    occurred_at: datetime | None = None
    occurred_at_timezone: str | None = None
    occurred_time_provenance: OccurredTimeProvenance = OccurredTimeProvenance.MISSING
    #: A URL the payload asks the server to fetch. **Never followed before verification**
    #: and never followed outside ``resource_policy``.
    resource_url: str | None = None


@dataclass(frozen=True)
class AuthoritativeTrackingState:
    """What the provider says when asked directly, over an authenticated channel.

    This is the only thing besides a verified signature that may become a normalized
    event, because it is the only other thing whose origin is established.
    """

    provider_reference: str
    raw_status: str | None
    raw_status_detail: str | None = None
    occurred_at: datetime | None = None
    occurred_at_timezone: str | None = None
    occurred_time_provenance: OccurredTimeProvenance = OccurredTimeProvenance.MISSING
    #: Present when the read produced a recognizable event identity.
    identity: ProviderEventIdentity | None = None


@dataclass(frozen=True)
class NormalizedProviderEvent:
    """A provider event expressed entirely in Solaris vocabulary.

    ``raw_status`` rides along for audit and for debugging a mapping. It is stored, never
    published: ``public_tracking_service`` builds its response from an allowlist that does
    not include it.
    """

    #: A ``ShipmentEventType`` value.
    event_type: str
    #: The ``OperationalState`` that event type maps to.
    operational_state: str
    identity: ProviderEventIdentity
    raw_status: str | None = None
    raw_status_detail: str | None = None
    occurred_at: datetime | None = None
    occurred_at_timezone: str | None = None
    occurred_time_provenance: OccurredTimeProvenance = OccurredTimeProvenance.MISSING
    #: True only for a genuine final-recipient delivery. A warehouse receipt and a
    #: collection-point handover are separate event types and must not set this
    #: (CRM.md section 7, DEC-0036).
    is_final_recipient_delivery: bool = False
    #: The event this one corrects, by provider identity. Explicit correction semantics
    #: rather than status ranking (CRM.md section 9).
    corrects_event_id: str | None = None
    #: Whether this event withdraws the one it corrects.
    is_void: bool = False
    location_label: str | None = None
    location_country_code: str | None = None


@dataclass(frozen=True)
class ResourceHostPolicy:
    """The exact hosts and paths an adapter is permitted to fetch from.

    An adapter supplies this; it does not get to fetch anything else. Both lists default
    to empty, and empty means **nothing may be fetched** -- the correct state for a
    provider whose documentation has not been read. See
    ``app/integrations/resource_policy.py`` for what is done with it.
    """

    #: Exact hostnames, lowercased. Never a suffix, never a wildcard: matching by suffix
    #: is how ``api.provider.com.attacker.test`` gets treated as the provider.
    allowed_hosts: frozenset[str] = field(default_factory=frozenset)
    #: Exact path prefixes, each beginning with ``/``.
    allowed_path_prefixes: tuple[str, ...] = ()
    #: Ports that may be named explicitly. 443 is the only sensible member.
    allowed_ports: frozenset[int] = field(default_factory=lambda: frozenset({443}))
    max_redirects: int = 2
    max_response_bytes: int = 256 * 1024
    timeout_seconds: float = 10.0
    allowed_content_types: frozenset[str] = field(
        default_factory=lambda: frozenset({"application/json"})
    )

    @property
    def is_configured(self) -> bool:
        """Whether this policy permits anything at all.

        An unconfigured policy is not a bug to route around. It is the state a provider
        stays in until its documentation and the real account have been checked, and the
        fetch layer refuses on it deliberately.
        """
        return bool(self.allowed_hosts) and bool(self.allowed_path_prefixes)


@runtime_checkable
class ProviderAdapter(Protocol):
    """What a provider integration must supply.

    Narrow on purpose. Every method is something the infrastructure genuinely needs, and
    nothing here presumes an HTTP shape, an authentication scheme, an endpoint, or an
    event name.
    """

    def capabilities(self) -> ProviderCapabilities:
        """Identity, API generation, mapping revision, and what this adapter can do."""

    def verify_webhook(self, *, body: bytes, headers: dict[str, str]) -> tuple[bool, str]:
        """Whether this payload is genuinely from the provider.

        Returns ``(verified, reason)``. ``reason`` is stored, so it must name a category
        and never a signature value, a header, or a secret.

        An adapter declaring ``verifies_signatures`` **must** return ``False`` for a
        missing, malformed, or invalid signature. An adapter that does not declare the
        capability is never asked: its notifications stay untrusted by construction, which
        is the honest outcome rather than a degraded one.
        """

    def extract_identity(self, *, body: bytes, headers: dict[str, str]) -> ProviderEventIdentity:
        """Recognize which event this is, without trusting it.

        Called before verification, because replay detection and authenticity are
        independent: a forged replay of a genuine event must still deduplicate.
        """

    def parse_notification(self, *, body: bytes, headers: dict[str, str]) -> ParsedNotification:
        """Read an untrusted notification into claims. Nothing is acted on."""

    def fetch_authoritative_state(self, *, provider_reference: str) -> AuthoritativeTrackingState:
        """Ask the provider directly, over an authenticated channel.

        The only way an unsigned notification can become something that moves a parcel.
        Raises ``ProviderAdapterError`` with a classified ``kind``.
        """

    def normalize(
        self, source: ParsedNotification | AuthoritativeTrackingState
    ) -> NormalizedProviderEvent:
        """Map a verified provider event into Solaris vocabulary.

        Raises ``ProviderAdapterError`` with ``ProviderErrorKind.MAPPING`` when the
        provider reports something this adapter has no honest mapping for. Inventing a
        plausible state would be worse than failing loudly: it would put a milestone in
        front of a customer that nobody reported.
        """

    def classify_error(self, error: Exception) -> ProviderErrorKind:
        """Turn a transport or protocol failure into the worker vocabulary."""

    def resource_policy(self) -> ResourceHostPolicy:
        """The exact hosts and paths this adapter may fetch from. Empty until verified."""
