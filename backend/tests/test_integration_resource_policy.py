"""The resource-fetch policy: what a provider URL may never make this server do.

AC-10: *arbitrary external resource URLs cannot cause server-side requests with provider
credentials.* CRM.md section 9 spells out how: exact documented HTTPS hosts and paths,
private and loopback destinations blocked, unsafe redirects refused, and no URL fetched
with credentials.

**No test here makes a network request, and neither does the code under test.** The DNS
resolver and the transport are injected, which is not merely convenient -- a host that
resolves to a private address, a host that answers differently on the second lookup, and a
redirect chain that walks off the allowlist cannot be demonstrated against real DNS and a
real server at all.

The allowlist used throughout is synthetic (``resources.fake-provider.test``). **The
production allowlist is empty and stays empty** until official documentation and the real
account confirm which hosts and paths a fetch would need -- an empty allowlist refuses
everything, which is correct for a provider nobody has verified.
"""

from __future__ import annotations

import pytest

from app.core.config import settings
from app.integrations.adapter import ResourceHostPolicy
from app.integrations.resource_policy import (
    FetchResult,
    ResolvedTarget,
    ResourcePolicyDecision,
    ResourcePolicyError,
    TrustLevel,
    describe_refusal,
    fetch_guarded,
    is_public_address,
    validate_redirect,
    validate_url,
)

APPROVED_HOST = "resources.fake-provider.test"
APPROVED_PATH = "/fake/v0/events/"
APPROVED_URL = f"https://{APPROVED_HOST}{APPROVED_PATH}abc123"

#: One globally routable address every approved host resolves to, unless a test says
#: otherwise.
#:
#: Deliberately **not** an RFC 5737 documentation address such as ``203.0.113.10``, and
#: this is worth stating because that is the obvious choice. Python classifies the
#: documentation ranges -- ``192.0.2.0/24``, ``198.51.100.0/24``, ``203.0.113.0/24``, and
#: ``2001:db8::/32`` -- as ``is_private``, because they are not globally routable, and the
#: policy refuses them for exactly the reason it refuses ``10.0.0.0/8``. Writing the
#: positive case against one of those would have made every "allowed" test fail, and the
#: temptation would then have been to loosen ``is_public_address``. These addresses are
#: never contacted: the resolver is injected and no transport exists.
PUBLIC_V4 = "93.184.216.34"
PUBLIC_V6 = "2606:4700::1111"

#: The documentation ranges, which the policy correctly treats as not public.
DOCUMENTATION_ADDRESSES = ("192.0.2.1", "198.51.100.5", "203.0.113.10", "2001:db8::1")


def policy(**overrides) -> ResourceHostPolicy:
    base = {
        "allowed_hosts": frozenset({APPROVED_HOST}),
        "allowed_path_prefixes": (APPROVED_PATH,),
        "allowed_ports": frozenset({443}),
        "max_redirects": 2,
        "max_response_bytes": 4096,
        "allowed_content_types": frozenset({"application/json"}),
    }
    base.update(overrides)
    return ResourceHostPolicy(**base)


def resolver_returning(*addresses: str):
    def _resolve(_host: str):
        return addresses

    return _resolve


PUBLIC_RESOLVER = resolver_returning(PUBLIC_V4)


def refusal(callable_, *args, **kwargs) -> ResourcePolicyDecision:
    """Run something expected to be refused and hand back the decision code."""
    with pytest.raises(ResourcePolicyError) as caught:
        callable_(*args, **kwargs)
    return caught.value.decision


# --- The approved case ------------------------------------------------------


def test_an_approved_synthetic_host_and_path_is_allowed():
    """The positive case, so every refusal below means something."""
    target = validate_url(
        APPROVED_URL, policy=policy(), trust=TrustLevel.VERIFIED, resolver=PUBLIC_RESOLVER
    )

    assert target.host == APPROVED_HOST
    assert target.port == 443
    assert target.path.startswith(APPROVED_PATH)
    assert target.addresses == (PUBLIC_V4,)


def test_an_approved_host_resolving_to_a_public_ipv6_address_is_allowed():
    target = validate_url(
        APPROVED_URL,
        policy=policy(),
        trust=TrustLevel.VERIFIED,
        resolver=resolver_returning(PUBLIC_V6),
    )

    assert target.addresses == (PUBLIC_V6,)


# --- The rule that makes the others secondary -------------------------------


def test_a_url_from_an_untrusted_payload_is_never_followed():
    """The most important refusal, and the first one checked.

    A URL in an unverified webhook is an instruction from an unauthenticated stranger. No
    amount of host validation makes acting on it sensible, so it is refused before the
    host is even looked at (CRM.md section 9).
    """
    decision = refusal(
        validate_url,
        APPROVED_URL,
        policy=policy(),
        trust=TrustLevel.UNTRUSTED,
        resolver=PUBLIC_RESOLVER,
    )

    assert decision is ResourcePolicyDecision.UNTRUSTED_SOURCE


def test_an_unconfigured_policy_refuses_even_a_plausible_url():
    """An empty allowlist refuses everything. This is the production configuration."""
    empty = ResourceHostPolicy()
    assert empty.is_configured is False

    decision = refusal(
        validate_url,
        APPROVED_URL,
        policy=empty,
        trust=TrustLevel.VERIFIED,
        resolver=PUBLIC_RESOLVER,
    )

    assert decision is ResourcePolicyDecision.POLICY_NOT_CONFIGURED


def test_the_production_allowlist_is_empty():
    """A production gate expressed as a test.

    If somebody adds a guessed ShipStation host before the documentation and the account
    confirm it, this fails. The hosts are unknown (docs/INTEGRATIONS.md section 3), and a
    plausible guess in an allowlist is worse than an empty one.
    """
    assert settings.integration_resource_host_list == []
    assert settings.integration_resource_path_prefix_list == []


# --- Scheme, credentials, fragment, port ------------------------------------


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        (f"http://{APPROVED_HOST}{APPROVED_PATH}a", ResourcePolicyDecision.SCHEME_NOT_HTTPS),
        (f"ftp://{APPROVED_HOST}{APPROVED_PATH}a", ResourcePolicyDecision.SCHEME_NOT_HTTPS),
        (f"file://{APPROVED_HOST}{APPROVED_PATH}a", ResourcePolicyDecision.SCHEME_NOT_HTTPS),
        (
            f"gopher://{APPROVED_HOST}{APPROVED_PATH}a",
            ResourcePolicyDecision.SCHEME_NOT_HTTPS,
        ),
    ],
)
def test_only_https_is_accepted(url, expected):
    """Anything else could carry a credential in clear text, or is not a fetch at all."""
    assert (
        refusal(
            validate_url, url, policy=policy(), trust=TrustLevel.VERIFIED, resolver=PUBLIC_RESOLVER
        )
        is expected
    )


@pytest.mark.parametrize(
    "url",
    [
        f"https://user:pass@{APPROVED_HOST}{APPROVED_PATH}a",
        f"https://user@{APPROVED_HOST}{APPROVED_PATH}a",
        f"https://:pass@{APPROVED_HOST}{APPROVED_PATH}a",
        # The classic confusion: everything before the last @ is user-info, so this is a
        # request to the approved host carrying an attacker string as a username -- or, on
        # a parser that reads it the other way, a request to attacker.test.
        f"https://{APPROVED_HOST}@attacker.test{APPROVED_PATH}a",
    ],
)
def test_a_url_carrying_credentials_is_refused_rather_than_stripped(url):
    """Refused whole. A URL written with credentials was not written by a friend, and
    guessing at the intent behind it is not this layer's job."""
    decision = refusal(
        validate_url, url, policy=policy(), trust=TrustLevel.VERIFIED, resolver=PUBLIC_RESOLVER
    )

    assert decision in {
        ResourcePolicyDecision.URL_CREDENTIALS,
        ResourcePolicyDecision.HOST_NOT_ALLOWED,
    }


def test_a_fragment_is_refused():
    """A server never needs a fragment, and it is a common smuggling device."""
    assert (
        refusal(
            validate_url,
            f"{APPROVED_URL}#fragment",
            policy=policy(),
            trust=TrustLevel.VERIFIED,
            resolver=PUBLIC_RESOLVER,
        )
        is ResourcePolicyDecision.FRAGMENT_PRESENT
    )


@pytest.mark.parametrize("port", [80, 8080, 8443, 22, 3306, 6379, 11211])
def test_an_unapproved_port_is_refused(port):
    """Redis, memcached, MySQL, and SSH are the usual SSRF destinations."""
    assert (
        refusal(
            validate_url,
            f"https://{APPROVED_HOST}:{port}{APPROVED_PATH}a",
            policy=policy(),
            trust=TrustLevel.VERIFIED,
            resolver=PUBLIC_RESOLVER,
        )
        is ResourcePolicyDecision.PORT_NOT_ALLOWED
    )


# --- Host matching ----------------------------------------------------------


@pytest.mark.parametrize(
    "host",
    [
        "localhost",
        "localhost.localdomain",
        "attacker.test",
        # Host-suffix confusion: this *ends with* the approved host and is a completely
        # different server. ``endswith`` matching is how that becomes a breach.
        f"{APPROVED_HOST}.attacker.test",
        f"evil-{APPROVED_HOST}",
        f"{APPROVED_HOST}x",
        f"x{APPROVED_HOST}",
        # A subdomain of the approved host is still not the approved host.
        f"internal.{APPROVED_HOST}",
        "RESOURCES.FAKE-PROVIDER.TEST.attacker.test",
    ],
)
def test_host_matching_is_exact_and_never_a_suffix(host):
    assert (
        refusal(
            validate_url,
            f"https://{host}{APPROVED_PATH}a",
            policy=policy(),
            trust=TrustLevel.VERIFIED,
            resolver=PUBLIC_RESOLVER,
        )
        is ResourcePolicyDecision.HOST_NOT_ALLOWED
    )


def test_the_approved_host_is_matched_case_insensitively_and_with_a_trailing_dot():
    """A hostname is case-insensitive and may be fully qualified with a trailing dot.

    Refusing these would be a correctness bug rather than a safety feature: they are the
    same host, and a provider that sends one form on Tuesday is not an attack.
    """
    for variant in (APPROVED_HOST.upper(), f"{APPROVED_HOST}."):
        target = validate_url(
            f"https://{variant}{APPROVED_PATH}a",
            policy=policy(),
            trust=TrustLevel.VERIFIED,
            resolver=PUBLIC_RESOLVER,
        )
        assert target.host == APPROVED_HOST


@pytest.mark.parametrize(
    "host",
    [
        "127.0.0.1",
        "127.1",
        "0.0.0.0",
        "[::1]",
        "[::ffff:127.0.0.1]",
        "10.0.0.1",
        "192.168.1.1",
        "172.16.0.1",
        "169.254.169.254",  # the cloud metadata address
        "[fd00::1]",
        "[fe80::1]",
        # Numeric and encoded host tricks: all of these resolve to loopback.
        "2130706433",
        "0x7f000001",
        "0177.0.0.1",
        "017700000001",
    ],
)
def test_an_address_literal_is_never_an_allowed_host(host):
    """Refused twice over: not on the allowlist, and recognized as an address literal.

    The numeric forms matter because they read like hostnames. ``2130706433`` is
    ``127.0.0.1`` written as an integer, and a resolver will happily accept it.
    """
    assert refusal(
        validate_url,
        f"https://{host}{APPROVED_PATH}a",
        policy=policy(),
        trust=TrustLevel.VERIFIED,
        resolver=PUBLIC_RESOLVER,
    ) in {
        ResourcePolicyDecision.HOST_IS_IP_LITERAL,
        ResourcePolicyDecision.HOST_NOT_ALLOWED,
        ResourcePolicyDecision.MALFORMED_URL,
    }


@pytest.mark.parametrize(
    "url",
    [
        f"https://{APPROVED_HOST}{APPROVED_PATH}a\nX-Injected: 1",
        f"https://{APPROVED_HOST}{APPROVED_PATH}a\r\nHost: attacker.test",
        f"https://{APPROVED_HOST}{APPROVED_PATH}a b",
        "https://",
        "",
        "   ",
        "not a url at all",
    ],
)
def test_a_malformed_or_tampered_url_is_refused(url):
    assert refusal(
        validate_url, url, policy=policy(), trust=TrustLevel.VERIFIED, resolver=PUBLIC_RESOLVER
    ) in {
        ResourcePolicyDecision.MALFORMED_URL,
        ResourcePolicyDecision.SCHEME_NOT_HTTPS,
        ResourcePolicyDecision.HOST_NOT_ALLOWED,
        ResourcePolicyDecision.PATH_NOT_ALLOWED,
    }


# --- Path matching ----------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    [
        "/",
        "/admin",
        "/fake/v0/labels/1",  # right host, undocumented path
        "/fake/v0/event/1",  # one character off the prefix
        "/other/fake/v0/events/1",  # the prefix appears, but not at the start
        "/fake/v0/events/../../admin",
    ],
)
def test_an_unapproved_path_is_refused(path):
    """An allowed host must not become an open proxy through an undocumented path."""
    assert (
        refusal(
            validate_url,
            f"https://{APPROVED_HOST}{path}",
            policy=policy(),
            trust=TrustLevel.VERIFIED,
            resolver=PUBLIC_RESOLVER,
        )
        is ResourcePolicyDecision.PATH_NOT_ALLOWED
    )


# --- DNS --------------------------------------------------------------------


@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",
        "10.1.2.3",
        "192.168.0.5",
        "172.20.1.1",
        "169.254.169.254",
        "0.0.0.0",
        "224.0.0.1",
        "240.0.0.1",
        "::1",
        "fd00::1",
        "fe80::1",
        "ff02::1",
        "::",
        "::ffff:127.0.0.1",
        "::ffff:10.0.0.1",
    ],
)
def test_an_allowed_host_resolving_to_a_private_address_is_refused(address):
    """The heart of SSRF: the host is on the allowlist and the destination is internal.

    ``169.254.169.254`` is the cloud metadata endpoint, which is the reason this check
    exists at all. ``::ffff:...`` is IPv4 wearing IPv6 notation, and a check that only
    looked at the outer form would let it through.
    """
    assert (
        refusal(
            validate_url,
            APPROVED_URL,
            policy=policy(),
            trust=TrustLevel.VERIFIED,
            resolver=resolver_returning(address),
        )
        is ResourcePolicyDecision.DESTINATION_NOT_PUBLIC
    )


def test_every_resolved_address_must_be_public_not_merely_the_first():
    """A name resolving to one public and one private address is a rebinding attempt.

    Checking only the first would make the outcome depend on resolver ordering, which is
    not a security property.
    """
    assert (
        refusal(
            validate_url,
            APPROVED_URL,
            policy=policy(),
            trust=TrustLevel.VERIFIED,
            resolver=resolver_returning(PUBLIC_V4, "127.0.0.1"),
        )
        is ResourcePolicyDecision.DESTINATION_NOT_PUBLIC
    )


def test_dns_rebinding_is_caught_on_the_second_lookup():
    """A host that answers public once and private afterwards.

    Real rebinding turns on the *second* resolution -- validation passes, then the actual
    connection resolves again and lands somewhere internal. Revalidating on every hop is
    what closes it, and this simulates the flip that real DNS cannot be made to perform on
    demand.
    """
    answers = iter([(PUBLIC_V4,), ("127.0.0.1",), ("127.0.0.1",)])

    def rebinding(_host: str):
        return next(answers)

    first = validate_url(
        APPROVED_URL, policy=policy(), trust=TrustLevel.VERIFIED, resolver=rebinding
    )
    assert first.addresses == (PUBLIC_V4,)

    # The same URL, re-validated as any redirect or retry would be.
    assert (
        refusal(
            validate_url,
            APPROVED_URL,
            policy=policy(),
            trust=TrustLevel.VERIFIED,
            resolver=rebinding,
        )
        is ResourcePolicyDecision.DESTINATION_NOT_PUBLIC
    )


def test_a_resolver_failure_refuses_rather_than_proceeding():
    def broken(_host: str):
        raise OSError("dns is down")

    assert (
        refusal(
            validate_url,
            APPROVED_URL,
            policy=policy(),
            trust=TrustLevel.VERIFIED,
            resolver=broken,
        )
        is ResourcePolicyDecision.DNS_FAILED
    )


def test_an_empty_resolver_answer_refuses():
    assert (
        refusal(
            validate_url,
            APPROVED_URL,
            policy=policy(),
            trust=TrustLevel.VERIFIED,
            resolver=resolver_returning(),
        )
        is ResourcePolicyDecision.DNS_FAILED
    )


@pytest.mark.parametrize(
    ("address", "public"),
    [
        ("93.184.216.34", True),
        ("2606:4700::1111", True),
        ("8.8.8.8", True),
        # Documentation ranges are not globally routable, so they are not public.
        ("203.0.113.10", False),
        ("2001:db8::1", False),
        ("127.0.0.1", False),
        ("::1", False),
        ("10.0.0.1", False),
        ("169.254.169.254", False),
        ("::ffff:192.168.1.1", False),
        ("not-an-address", False),
    ],
)
def test_is_public_address(address, public):
    assert is_public_address(address) is public


# --- Redirects --------------------------------------------------------------


def approved_target() -> ResolvedTarget:
    return validate_url(
        APPROVED_URL, policy=policy(), trust=TrustLevel.VERIFIED, resolver=PUBLIC_RESOLVER
    )


def test_a_redirect_within_the_allowlist_keeps_credentials():
    target, keep = validate_redirect(
        current=approved_target(),
        location=f"https://{APPROVED_HOST}{APPROVED_PATH}other",
        policy=policy(),
        resolver=PUBLIC_RESOLVER,
        hops_taken=0,
    )

    assert target.host == APPROVED_HOST
    assert keep is True


def test_a_relative_redirect_is_resolved_against_the_current_url():
    target, keep = validate_redirect(
        current=approved_target(),
        location="other-event",
        policy=policy(),
        resolver=PUBLIC_RESOLVER,
        hops_taken=0,
    )

    assert target.path.startswith(APPROVED_PATH)
    assert keep is True


@pytest.mark.parametrize(
    "location",
    [
        "https://attacker.test/fake/v0/events/1",
        "http://resources.fake-provider.test/fake/v0/events/1",
        "https://resources.fake-provider.test/admin",
        "https://127.0.0.1/fake/v0/events/1",
        "https://resources.fake-provider.test:8443/fake/v0/events/1",
        "/../../admin",
        "file:///etc/passwd",
    ],
)
def test_an_unsafe_redirect_is_refused(location):
    """A redirect is a URL chosen by whoever answered, so it is revalidated from scratch."""
    decision = refusal(
        validate_redirect,
        current=approved_target(),
        location=location,
        policy=policy(),
        resolver=PUBLIC_RESOLVER,
        hops_taken=0,
    )

    assert decision is ResourcePolicyDecision.REDIRECT_NOT_ALLOWED


def test_the_redirect_limit_is_strict():
    assert (
        refusal(
            validate_redirect,
            current=approved_target(),
            location=f"https://{APPROVED_HOST}{APPROVED_PATH}other",
            policy=policy(max_redirects=2),
            resolver=PUBLIC_RESOLVER,
            hops_taken=2,
        )
        is ResourcePolicyDecision.TOO_MANY_REDIRECTS
    )


def test_credentials_are_dropped_when_the_origin_changes():
    """Two approved hosts, one redirect between them, and the key does not travel."""
    two_hosts = policy(allowed_hosts=frozenset({APPROVED_HOST, "second.fake-provider.test"}))

    target, keep = validate_redirect(
        current=approved_target(),
        location=f"https://second.fake-provider.test{APPROVED_PATH}1",
        policy=two_hosts,
        resolver=PUBLIC_RESOLVER,
        hops_taken=0,
    )

    assert target.host == "second.fake-provider.test"
    assert keep is False, "a changed origin must not receive the provider credential"


# --- The guarded fetch ------------------------------------------------------


def test_production_has_no_transport_so_nothing_is_ever_fetched():
    """Phase 4A makes no network request. This is the assertion that says so."""
    assert (
        refusal(
            fetch_guarded,
            APPROVED_URL,
            policy=policy(),
            trust=TrustLevel.VERIFIED,
            resolver=PUBLIC_RESOLVER,
            transport=None,
        )
        is ResourcePolicyDecision.FETCH_DISABLED
    )


def test_a_guarded_fetch_returns_a_bounded_json_response():
    def transport(target: ResolvedTarget, _headers):
        return FetchResult(
            status_code=200,
            content_type="application/json; charset=utf-8",
            body=b'{"ok": true}',
            final_url=target.url,
        )

    result = fetch_guarded(
        APPROVED_URL,
        policy=policy(),
        trust=TrustLevel.VERIFIED,
        resolver=PUBLIC_RESOLVER,
        transport=transport,
    )

    assert result.status_code == 200
    assert result.redirects == 0


def test_an_oversized_response_is_refused():
    def transport(target: ResolvedTarget, _headers):
        return FetchResult(
            status_code=200,
            content_type="application/json",
            body=b"x" * 9000,
            final_url=target.url,
        )

    assert (
        refusal(
            fetch_guarded,
            APPROVED_URL,
            policy=policy(max_response_bytes=4096),
            trust=TrustLevel.VERIFIED,
            resolver=PUBLIC_RESOLVER,
            transport=transport,
        )
        is ResourcePolicyDecision.RESPONSE_TOO_LARGE
    )


@pytest.mark.parametrize("content_type", ["text/html", "application/xml", None, "text/plain"])
def test_an_unapproved_content_type_is_refused(content_type):
    def transport(target: ResolvedTarget, _headers):
        return FetchResult(
            status_code=200, content_type=content_type, body=b"{}", final_url=target.url
        )

    assert (
        refusal(
            fetch_guarded,
            APPROVED_URL,
            policy=policy(),
            trust=TrustLevel.VERIFIED,
            resolver=PUBLIC_RESOLVER,
            transport=transport,
        )
        is ResourcePolicyDecision.CONTENT_TYPE_NOT_ALLOWED
    )


def test_a_credential_is_not_carried_across_a_redirect_to_another_origin():
    """The end-to-end version of the credential-stripping rule.

    The transport records the headers it was handed on each hop, so this asserts what the
    second request actually carried rather than what the policy intended.
    """
    two_hosts = policy(allowed_hosts=frozenset({APPROVED_HOST, "second.fake-provider.test"}))
    seen: list[dict[str, str]] = []

    def transport(target: ResolvedTarget, headers):
        seen.append(dict(headers))
        if target.host == APPROVED_HOST:
            return FetchResult(
                status_code=302,
                content_type=None,
                body=b"",
                final_url=f"https://second.fake-provider.test{APPROVED_PATH}1",
            )
        return FetchResult(
            status_code=200, content_type="application/json", body=b"{}", final_url=target.url
        )

    result = fetch_guarded(
        APPROVED_URL,
        policy=two_hosts,
        trust=TrustLevel.VERIFIED,
        resolver=PUBLIC_RESOLVER,
        transport=transport,
        credentials={"authorization": "Bearer fake-token-value"},
    )

    assert result.status_code == 200
    assert result.redirects == 1
    assert seen[0] == {"authorization": "Bearer fake-token-value"}
    assert seen[1] == {}, "the credential must not reach the second origin"


def test_a_credential_survives_a_same_origin_redirect():
    """The counterpart, so the test above is not passing because credentials never travel."""
    seen: list[dict[str, str]] = []
    calls = {"count": 0}

    def transport(target: ResolvedTarget, headers):
        seen.append(dict(headers))
        calls["count"] += 1
        if calls["count"] == 1:
            return FetchResult(
                status_code=302,
                content_type=None,
                body=b"",
                final_url=f"https://{APPROVED_HOST}{APPROVED_PATH}second",
            )
        return FetchResult(
            status_code=200, content_type="application/json", body=b"{}", final_url=target.url
        )

    fetch_guarded(
        APPROVED_URL,
        policy=policy(),
        trust=TrustLevel.VERIFIED,
        resolver=PUBLIC_RESOLVER,
        transport=transport,
        credentials={"authorization": "Bearer fake-token-value"},
    )

    assert seen[1] == {"authorization": "Bearer fake-token-value"}


def test_a_redirect_chain_that_leaves_the_allowlist_is_refused_mid_flight():
    def transport(target: ResolvedTarget, _headers):
        return FetchResult(
            status_code=302,
            content_type=None,
            body=b"",
            final_url="https://attacker.test/fake/v0/events/1",
        )

    assert (
        refusal(
            fetch_guarded,
            APPROVED_URL,
            policy=policy(),
            trust=TrustLevel.VERIFIED,
            resolver=PUBLIC_RESOLVER,
            transport=transport,
        )
        is ResourcePolicyDecision.REDIRECT_NOT_ALLOWED
    )


# --- What a refusal is allowed to say ---------------------------------------


def test_a_refusal_log_line_contains_no_path_query_or_credential():
    """An operator needs to know which rule refused it, not where it pointed."""
    url = "https://attacker.test/fake/v0/events/SX-CAV-7K9D2M4R8T6W?token=SECRETVALUE123456"
    error = ResourcePolicyError(ResourcePolicyDecision.HOST_NOT_ALLOWED)

    line = describe_refusal(error, url)

    assert "host_not_allowed" in line
    assert "attacker.test" in line
    assert "SX-CAV-7K9D2M4R8T6W" not in line
    assert "SECRETVALUE123456" not in line
    assert "token=" not in line
