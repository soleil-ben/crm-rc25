"""Staff-facing integration schemas.

Every field here is a count, a timestamp, an application enum value, or an explicit
``None``. **No secret-bearing field exists in this module** -- there is no credential, no
API key, no signature, no authorization header, no raw payload, and no provider URL, and
``backend/tests/test_integration_privacy.py`` walks these models to assert that a field
with such a name never appears.

``credential_ref`` is deliberately absent too, even though it holds only the *name* of an
environment variable. A staff response has no use for it, and a field that looks like it
might be a credential is a field somebody will eventually put one in.

Several values are ``None`` rather than a number, and that is the design:

* ``stale_assignment_count`` -- no freshness rule exists, so "we cannot tell" is the
  truthful answer and ``0`` would be a claim that everything is fresh;
* ``provider_api_version`` -- unverified;
* ``last_success_at`` -- nothing has ever succeeded, because nothing has ever run;
* ``worker`` -- absent unless a worker actually wrote a heartbeat.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class IntegrationModel(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")


class ConnectionHealthOut(IntegrationModel):
    """One provider connection, or the honest absence of any.

    With nothing configured this carries ``provider_key: null`` and
    ``state: "not_configured"`` -- not a card describing a provider that does not exist.
    """

    provider_key: str | None = None
    #: ``not_configured`` | ``disabled`` | ``verification_required`` | ``connected`` |
    #: ``error``. Today it is always the first.
    state: str
    #: Only when genuinely known.
    provider_api_version: str | None = None
    display_label: str | None = None
    connection_id: int | None = None
    is_enabled: bool = False
    last_success_at: datetime | None = None
    last_success_operation: str | None = None
    last_error_at: datetime | None = None
    #: An application error category, never a provider status code.
    last_error_code: str | None = None
    #: Redacted before it was stored, and redacted again on the way in.
    last_error_summary: str | None = None


class WorkerHealthOut(IntegrationModel):
    """Present only when a worker has genuinely reported in."""

    worker_name: str
    mode: str
    last_seen_at: datetime
    seconds_since_last_seen: int
    stopped_at: datetime | None = None
    jobs_claimed: int
    jobs_succeeded: int
    jobs_failed: int


class IntegrationHealthOut(IntegrationModel):
    """The integration health payload."""

    any_provider_configured: bool
    connections: list[ConnectionHealthOut] = []

    jobs_pending: int
    jobs_running: int
    jobs_failed: int
    jobs_failed_terminal: int
    jobs_requiring_review: int
    #: ``None`` when nothing is waiting.
    oldest_pending_job_age_seconds: int | None = None

    inbox_pending: int
    inbox_awaiting_verification: int
    inbox_rejected: int
    inbox_failed_terminal: int

    #: ``None``, not zero. No freshness rule exists to measure against.
    stale_assignment_count: int | None = None
    stale_rule_description: str

    worker: WorkerHealthOut | None = None
    summary: str


class IntegrationJobOut(IntegrationModel):
    """One job in the review queue.

    Carries identifiers, counts, and an error *category*. The provider payload that
    produced the failure is not here and is not reachable from here.
    """

    id: int
    job_type: str
    provider_key: str
    status: str
    attempt_count: int
    max_attempts: int
    priority: int
    available_at: datetime
    last_attempt_at: datetime | None = None
    next_retry_at: datetime | None = None
    provider_retry_after_seconds: int | None = None
    error_code: str | None = None
    error_summary: str | None = None
    requires_review: bool
    manual_retry_count: int
    last_manual_retry_at: datetime | None = None
    completed_at: datetime | None = None
    failed_at: datetime | None = None
    shipment_id: int | None = None
    tracking_assignment_id: int | None = None
    inbox_item_id: int | None = None


class IntegrationJobListOut(IntegrationModel):
    items: list[IntegrationJobOut] = []
    total: int


class DisableConnectionIn(IntegrationModel):
    reason: str
