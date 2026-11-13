"""Safe server-side fetching of a provider resource URL.

CRM.md section 9: *if a payload contains resource_url, allowlist the exact documented
HTTPS hosts and paths before server-side retrieval; block private/loopback destinations
and unsafe redirects. Never fetch arbitrary URLs with credentials.* AC-10 states the
property this has to deliver: **arbitrary external resource URLs cannot cause
server-side requests with provider credentials.**

**No real network request is made anywhere in this file, or anywhere in Phase 4A.** The
policy is built and tested; the transport is injected, and production supplies none, so
``fetch_guarded`` refuses. That is not a stub standing in for a missing implementation:
the allowlist a real fetch would need is empty because the provider's documented hosts
and paths have not been read, and a fetch layer with an empty allowlist correctly refuses
everything.

The URL in a webhook payload is attacker-controlled input. Somebody who can post to the
webhook endpoint chooses that string, so every decision here is made against the value as
found rather than the value as intended:

* **HTTPS only**, so a credential cannot be sent in clear text.
* **Exact host match**, never a suffix. ``provider.example.test.attacker.test`` ends with
  the allowed host and is a completely different server; suffix matching is the classic
  way that becomes a breach.
* **Exact path prefix**, so an allowed host cannot be turned into an open proxy through a
  path the provider never documented.
* **No credentials in the URL.** ``https://user:pass@host/`` is refused rather than
  stripped; a URL that carries credentials was not written by anyone whose intent should
  be guessed at.
* **No fragment**, which a server never needs and which is a common smuggling device.
* **Approved ports only.**
* **DNS resolution is checked**, for IPv4 and IPv6, and loopback, private, link-local,
  multicast, reserved, and unspecified destinations are refused. A hostname on the
  allowlist that resolves to ``127.0.0.1`` is the whole SSRF problem in one line.
* **Revalidation after resolution and on every redirect.** A redirect is a fresh URL
  chosen by whoever answered, and it gets the same scrutiny as the first one.
* **A strict redirect limit.**
* **Credentials are never carried to a changed origin.** Not the same host, not the same
  request.
* **Response size, timeout, and content type are bounded.**
* **A URL that came straight from an untrusted payload is not followed at all** until the
  event is verified. This is the rule the others exist to support: the safest fetch is the
  one that does not happen because the payload asking for it was never authenticated.

The DNS resolver is injected, so the tests can simulate a host that resolves to a private
address and a rebinding host that answers differently on the second lookup -- neither of
which can be demonstrated against real DNS.
"""

from __future__ import annotations

import ipaddress
import socket
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from urllib.parse import urlparse, urlsplit

from app.integrations.adapter import ResourceHostPolicy
from app.integrations.redaction import redact_url

#: Resolves a hostname to the addresses it points at. Injected so a private address, a
#: rebinding host, and an unresolvable name are all testable.
Resolver = Callable[[str], Sequence[str]]


class TrustLevel(StrEnum):
    """Where the URL came from.

    ``UNTRUSTED`` is a URL lifted out of a notification whose authenticity has not been
    established. It is refused outright, before any other check runs, because no amount
    of host validation makes it sensible to act on an instruction from an unauthenticated
    stranger (CRM.md section 9).
    """

    #: Straight out of an unverified payload. Never fetched.
    UNTRUSTED = "untrusted"
    #: The payload carrying it verified, or the URL came from an authenticated read.
    VERIFIED = "verified"


class ResourcePolicyDecision(StrEnum):
    """Why a URL was refused. Stable codes, safe to log, never containing the URL."""

    ALLOWED = "allowed"
    UNTRUSTED_SOURCE = "untrusted_source"
    POLICY_NOT_CONFIGURED = "policy_not_configured"
    MALFORMED_URL = "malformed_url"
    SCHEME_NOT_HTTPS = "scheme_not_https"
    URL_CREDENTIALS = "url_credentials"
    FRAGMENT_PRESENT = "fragment_present"
    PORT_NOT_ALLOWED = "port_not_allowed"
    HOST_NOT_ALLOWED = "host_not_allowed"
    HOST_IS_IP_LITERAL = "host_is_ip_literal"
    PATH_NOT_ALLOWED = "path_not_allowed"
    DNS_FAILED = "dns_failed"
    DESTINATION_NOT_PUBLIC = "destination_not_public"
    TOO_MANY_REDIRECTS = "too_many_redirects"
    REDIRECT_NOT_ALLOWED = "redirect_not_allowed"
    RESPONSE_TOO_LARGE = "response_too_large"
    CONTENT_TYPE_NOT_ALLOWED = "content_type_not_allowed"
    FETCH_DISABLED = "fetch_disabled"


class ResourcePolicyError(Exception):
    """A URL was refused. Carries a decision code and never the URL itself."""

    def __init__(self, decision: ResourcePolicyDecision, *, detail: str | None = None) -> None:
        super().__init__(decision.value if detail is None else f"{decision.value}: {detail}")
        self.decision = decision
        self.detail = detail


@dataclass(frozen=True)
class ResolvedTarget:
    """A URL that passed every check, with the addresses it resolved to."""

    url: str
    host: str
    port: int
    path: str
    addresses: tuple[str, ...] = field(default_factory=tuple)


def default_resolver(host: str) -> Sequence[str]:
    """Real DNS. Never called by the test suite, which injects its own."""
    infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    return tuple({info[4][0] for info in infos})


def is_public_address(value: str) -> bool:
    """Whether an address is somewhere on the public internet.

    Everything not obviously public is refused, for IPv4 and IPv6 alike. IPv4-mapped and
    6to4 IPv6 forms are unwrapped first: ``::ffff:127.0.0.1`` is loopback wearing a
    different notation, and a check that only looked at the outer form would pass it.
    """
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        return False

    # Unwrap the notations that hide an IPv4 address inside an IPv6 one.
    mapped = getattr(address, "ipv4_mapped", None)
    if mapped is not None:
        address = mapped
    sixtofour = getattr(address, "sixtofour", None)
    if sixtofour is not None:
        address = sixtofour
    teredo = getattr(address, "teredo", None)
    if teredo is not None:
        # (server, client); the client address is the one traffic reaches.
        address = teredo[1]

    return not (
        address.is_loopback
        or address.is_private
        or address.is_link_local
        or address.is_multicast
        or address.is_reserved
        or address.is_unspecified
        or getattr(address, "is_site_local", False)
    )


def _host_is_ip_literal(host: str) -> bool:
    """Whether a hostname is really an address written in some notation.

    Covers dotted quads, IPv6 literals, and the integer and hexadecimal forms
    (``2130706433``, ``0x7f000001``, ``0177.0.0.1``) that resolvers accept and that read
    like a hostname. A host on the exact allowlist would already have to be a name, so
    this is belt and braces -- but it is the kind of belt that is cheap and the kind of
    braces that has failed before.
    """
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        pass

    stripped = host.strip("[]")
    try:
        ipaddress.ip_address(stripped)
        return True
    except ValueError:
        pass

    candidate = host.replace(".", "")
    for base, prefix in ((16, "0x"), (8, "0o"), (10, "")):
        text = candidate.lower()
        if prefix and not text.startswith(prefix):
            continue
        try:
            value = int(text, base)
        except ValueError:
            continue
        if 0 <= value <= 0xFFFFFFFF and (prefix or text.isdigit()):
            return True
    return False


def validate_url(
    url: str | None,
    *,
    policy: ResourceHostPolicy,
    trust: TrustLevel,
    resolver: Resolver | None = None,
) -> ResolvedTarget:
    """Check a URL against the policy and resolve it. Raises ``ResourcePolicyError``.

    The order matters. Trust is checked first, because a URL from an unverified payload
    is refused whatever it says. Configuration is checked second, so a provider whose
    documentation has not been read refuses everything rather than falling through to
    per-URL judgement.
    """
    if trust is not TrustLevel.VERIFIED:
        raise ResourcePolicyError(ResourcePolicyDecision.UNTRUSTED_SOURCE)

    if not policy.is_configured:
        raise ResourcePolicyError(ResourcePolicyDecision.POLICY_NOT_CONFIGURED)

    if not url or not url.strip():
        raise ResourcePolicyError(ResourcePolicyDecision.MALFORMED_URL)

    candidate = url.strip()
    # A URL with control characters or whitespace in it has already been tampered with.
    if any(character.isspace() or ord(character) < 0x20 for character in candidate):
        raise ResourcePolicyError(ResourcePolicyDecision.MALFORMED_URL)

    try:
        parsed = urlsplit(candidate)
    except ValueError as error:
        raise ResourcePolicyError(ResourcePolicyDecision.MALFORMED_URL) from error

    if parsed.scheme.lower() != "https":
        raise ResourcePolicyError(ResourcePolicyDecision.SCHEME_NOT_HTTPS)

    # Read credentials off the raw netloc rather than trusting the parsed fields: an
    # empty username with a password still means the URL carried credentials.
    if "@" in parsed.netloc or parsed.username or parsed.password:
        raise ResourcePolicyError(ResourcePolicyDecision.URL_CREDENTIALS)

    if parsed.fragment:
        raise ResourcePolicyError(ResourcePolicyDecision.FRAGMENT_PRESENT)

    try:
        port = parsed.port or 443
    except ValueError as error:
        raise ResourcePolicyError(ResourcePolicyDecision.PORT_NOT_ALLOWED) from error
    if port not in policy.allowed_ports:
        raise ResourcePolicyError(ResourcePolicyDecision.PORT_NOT_ALLOWED)

    host = (parsed.hostname or "").lower().rstrip(".")
    if not host:
        raise ResourcePolicyError(ResourcePolicyDecision.MALFORMED_URL)

    if _host_is_ip_literal(host):
        raise ResourcePolicyError(ResourcePolicyDecision.HOST_IS_IP_LITERAL)

    # Exact membership. Never a suffix comparison: ``endswith`` here is how
    # ``provider.example.test.attacker.test`` becomes the provider.
    if host not in policy.allowed_hosts:
        raise ResourcePolicyError(ResourcePolicyDecision.HOST_NOT_ALLOWED)

    path = parsed.path or "/"
    if ".." in path.split("/"):
        raise ResourcePolicyError(ResourcePolicyDecision.PATH_NOT_ALLOWED)
    if not any(path.startswith(prefix) for prefix in policy.allowed_path_prefixes):
        raise ResourcePolicyError(ResourcePolicyDecision.PATH_NOT_ALLOWED)

    resolve = resolver or default_resolver
    try:
        addresses = tuple(resolve(host))
    except Exception as error:  # noqa: BLE001 - any resolver failure is the same answer
        raise ResourcePolicyError(ResourcePolicyDecision.DNS_FAILED) from error

    if not addresses:
        raise ResourcePolicyError(ResourcePolicyDecision.DNS_FAILED)

    # **Every** address must be public, not merely the first. A name that resolves to one
    # public address and one loopback address is a rebinding attempt, and picking the
    # first would make the outcome depend on resolver ordering.
    if not all(is_public_address(address) for address in addresses):
        raise ResourcePolicyError(ResourcePolicyDecision.DESTINATION_NOT_PUBLIC)

    return ResolvedTarget(url=candidate, host=host, port=port, path=path, addresses=addresses)


def validate_redirect(
    *,
    current: ResolvedTarget,
    location: str,
    policy: ResourceHostPolicy,
    resolver: Resolver | None = None,
    hops_taken: int,
) -> tuple[ResolvedTarget, bool]:
    """Validate a redirect target. Returns ``(target, keep_credentials)``.

    A redirect is a URL chosen by whoever answered the request, so it is revalidated from
    scratch -- host, path, port, scheme, and DNS -- rather than being trusted because the
    first URL was fine. ``keep_credentials`` is false whenever the origin changes, which
    is the specific thing that turns a permitted fetch into a credential disclosure.

    A relative ``Location`` is resolved against the current URL first, so a redirect to
    ``/etc`` is judged as a path on the same host rather than as a malformed URL.
    """
    if hops_taken >= policy.max_redirects:
        raise ResourcePolicyError(ResourcePolicyDecision.TOO_MANY_REDIRECTS)

    from urllib.parse import urljoin

    absolute = urljoin(current.url, location.strip()) if location else ""
    try:
        target = validate_url(absolute, policy=policy, trust=TrustLevel.VERIFIED, resolver=resolver)
    except ResourcePolicyError as error:
        # Report it as a redirect refusal, keeping the underlying reason as detail so the
        # log says which rule the redirect broke without quoting where it pointed.
        raise ResourcePolicyError(
            ResourcePolicyDecision.REDIRECT_NOT_ALLOWED, detail=error.decision.value
        ) from error

    same_origin = (
        urlparse(current.url).scheme == urlparse(target.url).scheme
        and current.host == target.host
        and current.port == target.port
    )
    return target, same_origin


@dataclass(frozen=True)
class FetchResult:
    """What a guarded fetch produced. Only ever built by an injected transport."""

    status_code: int
    content_type: str | None
    body: bytes
    final_url: str
    redirects: int = 0


#: A transport performs one request and reports the response without following
#: redirects. Injected, so the policy is testable and so production can supply none.
Transport = Callable[[ResolvedTarget, dict[str, str]], FetchResult]


def fetch_guarded(
    url: str | None,
    *,
    policy: ResourceHostPolicy,
    trust: TrustLevel,
    resolver: Resolver | None = None,
    transport: Transport | None = None,
    credentials: dict[str, str] | None = None,
) -> FetchResult:
    """Fetch a resource URL under the policy, following redirects safely.

    **In production ``transport`` is ``None`` and this raises.** No provider has been
    verified, no allowlist has been written, and Phase 4A makes no network request. The
    function exists so the rules are written, tested, and reviewable now rather than
    written in a hurry beside a first real integration.

    Credentials are dropped the moment the origin changes, and the drop is unconditional:
    there is no "same site" or "same registrable domain" allowance, because both of those
    are judgement calls made in a place where being wrong means handing an API key to
    whoever controls the redirect.
    """
    target = validate_url(url, policy=policy, trust=trust, resolver=resolver)

    if transport is None:
        raise ResourcePolicyError(
            ResourcePolicyDecision.FETCH_DISABLED,
            detail="no provider transport is configured",
        )

    headers = dict(credentials or {})
    hops = 0

    while True:
        result = transport(target, headers)

        if result.status_code in {301, 302, 303, 307, 308}:
            location = result.final_url
            target, same_origin = validate_redirect(
                current=target,
                location=location,
                policy=policy,
                resolver=resolver,
                hops_taken=hops,
            )
            if not same_origin:
                headers = {}
            hops += 1
            continue

        if len(result.body) > policy.max_response_bytes:
            raise ResourcePolicyError(ResourcePolicyDecision.RESPONSE_TOO_LARGE)

        media_type = (result.content_type or "").split(";")[0].strip().lower()
        if media_type not in policy.allowed_content_types:
            raise ResourcePolicyError(ResourcePolicyDecision.CONTENT_TYPE_NOT_ALLOWED)

        return FetchResult(
            status_code=result.status_code,
            content_type=result.content_type,
            body=result.body,
            final_url=target.url,
            redirects=hops,
        )


def describe_refusal(error: ResourcePolicyError, url: str | None) -> str:
    """A log line about a refused URL that does not contain the URL.

    The decision code says which rule refused it and the redacted host says roughly
    where it pointed, which is what an operator needs. The path and query -- the parts
    that carry a tracking number or a token -- are digested away by ``redact_url``.
    """
    return f"resource_url refused decision={error.decision.value} target={redact_url(url)}"
