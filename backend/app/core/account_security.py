"""Digests, keys and limiter buckets for the Customer Account realm.

Argon2 password hashing, session-token digests and the sliding-window limiter itself are
reused from ``app.core.security``: those are *policies*, and having two of them would mean
one of them was weaker. What is **not** shared is the key space -- every bucket name here
is prefixed ``account:``, so a customer-side flood cannot consume the staff login or public
tracking allowance (`RATE_LIMITS_AND_ABUSE.md` section 2).

Two digest constructions live here, and the difference between them is deliberate.

**Session tokens** use the plain SHA-256 of ``app.core.security.hash_token``, the same
construction the staff realm uses. The input is 32 bytes of ``secrets`` output, so there is
no dictionary to run and no benefit from a key.

**Auth tokens** -- verification and password reset -- use a *keyed* HMAC-SHA256 whose
message includes the token's purpose. The key buys nothing against brute force either, and
that is not why it is there. It buys two things:

* **purpose binding by construction.** The same random token digests differently for
  ``email_verification`` and ``password_reset``, so a verification link presented to the
  reset endpoint does not match a stored row even if a query forgot its ``WHERE purpose``
  clause. The filter is still written; this is what makes forgetting it survivable.
* **deployment binding.** A token issued against one ``SECRET_KEY`` is unusable against
  another, so a restored database copy does not carry live password-reset links into a
  second environment.

The cost is stated plainly: rotating ``SECRET_KEY`` invalidates every outstanding
verification and reset token. For credentials that live hours rather than days that is an
acceptable, and arguably desirable, consequence (DEC-0097).

**Address keys** are keyed digests too, for a different reason: the limiter holds its keys
in memory and a diagnostic dump of them must not be a list of the addresses that have tried
to sign in (`RATE_LIMITS_AND_ABUSE.md` section 2, T-13).
"""

from __future__ import annotations

import hashlib
import hmac

from app.core.account_enums import TokenPurpose
from app.core.config import settings
from app.core.security import generate_token

#: Bytes of randomness in a verification or reset token. The same width as a session token:
#: both are bearer credentials and there is no reason for the emailed one to be weaker.
AUTH_TOKEN_BYTES = 32

#: Prefix on every Customer Account limiter key. The separation is the whole point, so it is
#: a named constant a test can assert every bucket starts with.
BUCKET_NAMESPACE = "account"


def generate_auth_token() -> str:
    """A fresh single-use token. The plaintext is returned once and never stored."""
    return generate_token(AUTH_TOKEN_BYTES)


def auth_token_digest(token: str, purpose: TokenPurpose | str) -> str:
    """Keyed, purpose-bound digest of a verification or reset token.

    The purpose is part of the signed message rather than a separate column comparison, so
    a token minted for one purpose cannot produce a row that matches the other.
    """
    message = f"{TokenPurpose(purpose).value}:{token}".encode()
    return hmac.new(settings.secret_key.encode("utf-8"), message, hashlib.sha256).hexdigest()


def address_key(email_normalized: str) -> str:
    """A keyed digest of a normalized address, for limiter buckets and audit payloads.

    Stable, so repeated attempts against one address land in one bucket and correlate in the
    audit log; non-reversible, so neither the limiter's memory nor the audit table becomes a
    list of who has a Solaris account (T-02, T-13).
    """
    return hmac.new(
        settings.secret_key.encode("utf-8"),
        email_normalized.strip().lower().encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def opaque_digest(value: str) -> str:
    """A plain digest for a value that is not a credential -- an idempotency key, a payload.

    Unkeyed on purpose: these are compared for equality across requests and nothing is
    gained by binding them to the deployment secret. Digested rather than stored verbatim
    because a caller-supplied idempotency key is caller-supplied text, and storing arbitrary
    caller text is how personal data arrives in a column nobody thought to check.
    """
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def fingerprint(parts: list[str]) -> str:
    """A keyed digest over an ordered list of facts. Phase 10's drift detector.

    Used for the approval preview and for the approval idempotency claim. The parts are
    joined with a separator that cannot occur inside one, so ``["ab", "c"]`` and
    ``["a", "bc"]`` do not collide -- the whole value of a fingerprint is that two
    different worlds produce two different strings, and a naive concatenation throws that
    away for a class of inputs nobody thinks about until it matters.

    Keyed rather than plain, for the reason `auth_token_digest` is keyed: a value a client
    could compute for itself is a value a client can present. This one is only ever
    compared against a row the server wrote, so forging it buys nothing today -- but it
    costs nothing to make that true by construction rather than by argument.

    **Not a credential and not secret.** It appears in a staff-facing response, because a
    reviewer's client has to send back the fingerprint it was shown. It is a comparison
    value over facts the reviewer is already looking at.
    """
    message = "\x1f".join(parts).encode("utf-8")
    return hmac.new(settings.secret_key.encode("utf-8"), message, hashlib.sha256).hexdigest()


# --- Bucket names ------------------------------------------------------------
#
# Every one of these starts with `account:`. Nothing in this module may produce a key that
# a staff or public limiter check would also produce, and `tests/test_account_rate_limits.py`
# asserts it over the limiter's live key set rather than over this file.


def register_ip_bucket(client_key: str) -> str:
    return f"{BUCKET_NAMESPACE}:register:ip:{client_key}"


def register_address_bucket(email_normalized: str) -> str:
    return f"{BUCKET_NAMESPACE}:register:addr:{address_key(email_normalized)}"


def resend_ip_bucket(client_key: str) -> str:
    return f"{BUCKET_NAMESPACE}:resend:ip:{client_key}"


def resend_address_bucket(email_normalized: str) -> str:
    return f"{BUCKET_NAMESPACE}:resend:addr:{address_key(email_normalized)}"


def signin_ip_bucket(client_key: str) -> str:
    return f"{BUCKET_NAMESPACE}:signin:ip:{client_key}"


def signin_address_bucket(email_normalized: str) -> str:
    return f"{BUCKET_NAMESPACE}:signin:addr:{address_key(email_normalized)}"


def reset_ip_bucket(client_key: str) -> str:
    return f"{BUCKET_NAMESPACE}:reset:ip:{client_key}"


def reset_address_bucket(email_normalized: str) -> str:
    return f"{BUCKET_NAMESPACE}:reset:addr:{address_key(email_normalized)}"


def token_ip_bucket(client_key: str) -> str:
    """Token redemption, keyed by caller. Brute force against the digest space (T-05)."""
    return f"{BUCKET_NAMESPACE}:token:ip:{client_key}"


def token_identity_bucket(identity_public_id: str) -> str:
    """Failed redemptions against one account. Keyed by the public id, never the address."""
    return f"{BUCKET_NAMESPACE}:token:identity:{identity_public_id}"


def read_identity_bucket(identity_public_id: str) -> str:
    """Authenticated shipment reads, keyed by the account.

    `RATE_LIMITS_AND_ABUSE.md` §2's ``account:read:<identity>``. Keyed by the account rather
    than by the peer address because the thing being defended against is **scraping through
    a compromised session** (§1): an attacker holding a stolen cookie can change address far
    more easily than they can change whose history the cookie opens, so the account is the
    stable side of that attack.

    Its own bucket, separate from `signin_*` as well as from the staff and public
    namespaces: sign-in and reading are different activities with different normal rates,
    and sharing a bucket would let ordinary paging eat the allowance a person needs to sign
    in again. The limit is set high enough that normal pagination never reaches it.
    """
    return f"{BUCKET_NAMESPACE}:read:identity:{identity_public_id}"
