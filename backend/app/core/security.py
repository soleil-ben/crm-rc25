"""Password hashing, session tokens, CSRF tokens, and a bounded rate limiter."""

from __future__ import annotations

import hashlib
import hmac
import secrets
import threading
import time
from dataclasses import dataclass, field

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

_hasher = PasswordHasher()

SESSION_TOKEN_BYTES = 32
CSRF_TOKEN_BYTES = 32


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, InvalidHashError, ValueError):
        return False


def needs_rehash(password_hash: str) -> bool:
    try:
        return _hasher.check_needs_rehash(password_hash)
    except (InvalidHashError, ValueError):
        return True


def generate_token(num_bytes: int = SESSION_TOKEN_BYTES) -> str:
    return secrets.token_urlsafe(num_bytes)


def hash_token(token: str) -> str:
    """Session and CSRF tokens are stored as digests, never in plaintext."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def tokens_match(left: str, right: str) -> bool:
    return hmac.compare_digest(left, right)


@dataclass
class _Bucket:
    hits: list[float] = field(default_factory=list)


class SlidingWindowRateLimiter:
    """In-process sliding-window limiter.

    Adequate for the documented single-server deployment (CRM.md section 3). If the
    application is ever run as multiple processes this must move to a shared store;
    the limitation is recorded in docs/DECISIONS.md (DEC-0006) and in
    docs/OPERATIONS.md as a gate before horizontal scaling.

    **Bounded storage.** The public tracking endpoint is reachable by anyone, so the key
    space is "every address that has ever made a request" -- unbounded, and a plain
    dictionary of buckets would grow for as long as the process lives. Two mechanisms
    keep it bounded, and neither weakens the limit:

    * every ``check`` prunes buckets whose most recent hit is older than the widest
      window seen so far, amortized so the sweep runs at most once a minute;
    * if the map still exceeds ``max_buckets`` -- a burst from many addresses inside one
      window -- the least recently touched entries are dropped.

    Dropping a bucket can only ever *forget* hits, never invent them, so the worst case is
    that an address which stopped long enough to be pruned gets a fresh allowance. That is
    the same thing the sliding window would have given it anyway.
    """

    #: Ceiling on tracked keys. At roughly a hundred bytes per bucket this is a few
    #: megabytes in the pathological case, and far more addresses than this deployment
    #: will genuinely see inside one window.
    DEFAULT_MAX_BUCKETS = 20_000
    #: Minimum seconds between amortized sweeps.
    SWEEP_INTERVAL_SECONDS = 60

    def __init__(self, max_buckets: int = DEFAULT_MAX_BUCKETS) -> None:
        self._buckets: dict[str, _Bucket] = {}
        self._lock = threading.Lock()
        self._max_buckets = max_buckets
        self._widest_window = 0
        self._last_sweep = time.monotonic()

    def check(self, key: str, limit: int, window_seconds: int) -> tuple[bool, int]:
        """Return ``(allowed, retry_after_seconds)`` and record the hit when allowed."""
        now = time.monotonic()
        cutoff = now - window_seconds
        with self._lock:
            self._widest_window = max(self._widest_window, window_seconds)
            bucket = self._buckets.setdefault(key, _Bucket())
            bucket.hits = [hit for hit in bucket.hits if hit > cutoff]
            # Re-inserting keeps the dictionary in least-recently-touched order, which is
            # what makes the overflow eviction drop the right entries. Done for a refused
            # request too, so a caller who keeps hitting the limit is not evicted first
            # and handed a fresh allowance.
            self._buckets[key] = self._buckets.pop(key)
            if len(bucket.hits) >= limit:
                retry_after = max(1, int(bucket.hits[0] + window_seconds - now) + 1)
                self._prune(now, protect=key)
                return False, retry_after
            bucket.hits.append(now)
            self._prune(now, protect=key)
            return True, 0

    def _prune(self, now: float, *, protect: str) -> None:
        """Drop expired and, if still over the ceiling, least recently touched buckets.

        Called with the lock held. ``protect`` is the key just touched, which must
        survive the sweep -- evicting it would hand the current caller a fresh allowance.
        """
        if now - self._last_sweep >= self.SWEEP_INTERVAL_SECONDS:
            self._last_sweep = now
            expiry = now - self._widest_window
            for key in [
                key
                for key, bucket in self._buckets.items()
                if key != protect and (not bucket.hits or bucket.hits[-1] <= expiry)
            ]:
                del self._buckets[key]

        overflow = len(self._buckets) - self._max_buckets
        if overflow > 0:
            for key in [key for key in self._buckets if key != protect][:overflow]:
                del self._buckets[key]

    def bucket_count(self) -> int:
        """Currently tracked keys. Used by the tests that assert the bound holds."""
        with self._lock:
            return len(self._buckets)

    def reset(self, key: str | None = None) -> None:
        with self._lock:
            if key is None:
                self._buckets.clear()
                self._widest_window = 0
                self._last_sweep = time.monotonic()
            else:
                self._buckets.pop(key, None)


rate_limiter = SlidingWindowRateLimiter()
