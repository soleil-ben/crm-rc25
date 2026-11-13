"""Which staff accounts are demo or UAT identities, and why that is knowable.

DEC-0027 put every seeded identity on the reserved `example.com` domain, and the UAT
environment follows it. That convention is what makes this check possible: a demo account
is recognisable from its address alone, with no column to set, no flag to forget, and
nothing for a database copied between environments to lose on the way.

The `users` table has no `is_demo_record` column -- `customers` and `shipments` do, staff
accounts do not -- so the address is not merely the convenient signal here, it is the only
one that exists. Adding a column would not have helped: a flag can be edited, and an
account promoted out of demo by an UPDATE is exactly the account this is meant to stop.

Reserved names, from RFC 2606 and RFC 6761. None of them can be registered by anyone, so
no real member of staff can ever hold an address in one, and no legitimate account is
caught by this rule:

* `example.com`, `example.net`, `example.org`, and any subdomain -- `demo.example.com`,
  `uat.example.com`;
* the `.example`, `.invalid`, `.test` and `.localhost` top-level domains.

Used in two places, deliberately: `app.services.auth_service` refuses to authenticate one
of these in production, and `app.main` refuses to *start* in production when the database
holds an active one. The second makes the first almost unreachable, which is the point --
a login-time refusal alone would leave a production database quietly holding usable demo
credentials until somebody tried them.
"""

from __future__ import annotations

#: Registrable domains reserved by RFC 2606. Matched exactly or as a parent of a subdomain.
RESERVED_DEMO_DOMAINS = frozenset({"example.com", "example.net", "example.org"})

#: Reserved top-level domains (RFC 2606, RFC 6761). Matched as a suffix.
RESERVED_DEMO_TLDS = frozenset({"example", "invalid", "test", "localhost"})


def is_reserved_demo_email(email: str | None) -> bool:
    """True when this address belongs to a reserved demo or UAT namespace.

    Case and surrounding whitespace are ignored. An address with no `@`, or with nothing
    after it, is not a demo identity -- it is malformed, and answering "yes" here would
    turn a validation problem into a silent authentication refusal.
    """
    if not email:
        return False

    _, separator, domain = email.strip().lower().rpartition("@")
    if not separator or not domain:
        return False

    if domain in RESERVED_DEMO_DOMAINS:
        return True
    if any(domain.endswith(f".{reserved}") for reserved in RESERVED_DEMO_DOMAINS):
        return True

    return domain.rpartition(".")[2] in RESERVED_DEMO_TLDS
