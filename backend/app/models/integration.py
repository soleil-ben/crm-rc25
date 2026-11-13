"""Provider-neutral integration infrastructure (Phase 4A).

Five tables: a connection record, a durable webhook inbox, a normalized provider event, a
durable job queue, and a worker heartbeat. **None of them names a provider.** No column,
constraint, or default here encodes a ShipStation product, endpoint, event name,
signature algorithm, or rate limit, because none of those has been verified against the
account (``docs/INTEGRATIONS.md`` section 3). What is built is the part whose correctness
does not depend on those answers.

Three properties are enforced by the **database**, not by application care:

* **One inbox row per delivered event.** ``uq_integration_webhook_inbox_dedupe`` covers
  ``(provider_key, connection_key, dedupe_key)``. Two concurrent deliveries of the same
  event on separate connections cannot both insert, whatever the application believes.
* **One active job per deduplication claim.** ``active_dedupe_key`` is unique and is set
  to NULL the moment a job stops being pending or running, so a completed job never
  blocks a later legitimate reconciliation while two concurrent enqueues still cannot
  both win.
* **One normalized event per provider event.**
  ``uq_integration_provider_events_fingerprint`` covers
  ``(provider_key, connection_key, provider_event_fingerprint)``.

SQLite has no ``SELECT ... FOR UPDATE``, so uniqueness is the only honest serialization
primitive available -- the same reasoning that produced ``booking_confirmations`` in
Phase 2 (DEC-0031). Claiming work uses a conditional ``UPDATE`` whose ``WHERE`` clause is
the guard, which is atomic on a single SQLite writer.

**No credential is stored in any of these tables.** ``credential_ref`` names an
environment variable; it never holds a value. There is no column for an authorization
header, an API key, a cookie, or a complete request header set, and the inbox stores a
bounded body with everything above the configured limit refused rather than truncated
silently.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import (
    InboxProcessingState,
    IntegrationConnectionState,
    IntegrationJobStatus,
    OccurredTimeProvenance,
    ProviderEventApplication,
    WebhookVerificationState,
)
from app.models.base import Base, TimestampMixin

#: Scope value used when a delivery cannot yet be attributed to a connection row.
#:
#: Deduplication is scoped by ``(provider_key, connection_key)``, and a NULL would defeat
#: that: SQLite and PostgreSQL both treat NULLs as distinct in a unique index, so two
#: deliveries of one event would both insert. A non-null sentinel keeps the constraint
#: doing its job before any account exists.
UNASSIGNED_CONNECTION = "unassigned"


class IntegrationConnection(TimestampMixin, Base):
    """A provider account this installation may talk to.

    **There are none.** The production adapter registry is empty and the seed command
    creates no row here, so ``integration_health_service`` reports ``not_configured``,
    which is the only truthful answer (``docs/INTEGRATIONS.md`` section 1).

    The table exists because deduplication has to be *scoped* to an account -- two
    accounts on one provider can legitimately emit the same event id -- and because a
    health panel that can only ever say one thing needs somewhere for the second thing to
    come from later. It stores no secret of any kind.
    """

    __tablename__ = "integration_connections"
    __table_args__ = (
        UniqueConstraint(
            "provider_key", "connection_key", name="uq_integration_connections_provider_connection"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    #: Which adapter handles this connection. An application key, never a product name
    #: guessed from marketing material.
    provider_key: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    #: The provider API generation this connection speaks. Explicit because CRM.md
    #: section 9 forbids treating provider versions as interchangeable.
    provider_api_version: Mapped[str | None] = mapped_column(String(40), nullable=True)
    #: Stable identifier for the account within the provider. Not a credential.
    connection_key: Mapped[str] = mapped_column(
        String(80), nullable=False, default=UNASSIGNED_CONNECTION
    )
    #: What staff call this connection in the interface.
    display_label: Mapped[str | None] = mapped_column(String(120), nullable=True)

    state: Mapped[str] = mapped_column(
        String(30), nullable=False, default=IntegrationConnectionState.NOT_CONFIGURED
    )
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    #: The **name** of the environment variable or secret-store entry holding the
    #: credential -- for example ``SOLARIS_PROVIDER_API_KEY``. Never the value. Nothing
    #: in this application writes a secret to the database, and
    #: ``tests/test_integration_privacy.py`` asserts the column never holds one.
    credential_ref: Mapped[str | None] = mapped_column(String(120), nullable=True)

    last_success_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_success_operation: Mapped[str | None] = mapped_column(String(60), nullable=True)
    last_error_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    #: A ``ProviderErrorKind`` value, not a provider status code.
    last_error_code: Mapped[str | None] = mapped_column(String(40), nullable=True)
    #: Redacted. Never a raw provider message, URL, payload, or tracking reference.
    last_error_summary: Mapped[str | None] = mapped_column(String(400), nullable=True)

    disabled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    disabled_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    disabled_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class IntegrationWebhookInboxItem(TimestampMixin, Base):
    """One durably stored inbound notification.

    The contract CRM.md section 9 asks for is: persist durably, acknowledge promptly,
    process out of band. This row is the durable half. It is written and committed before
    anything is parsed, mapped, or applied, so an acknowledgement is a statement about
    storage rather than a promise about business effect.

    **Authenticity, deduplication, and processing are three independent axes**, and
    keeping them independent is what makes replay handling correct. A forged payload is
    still stored and still deduplicated; it simply never becomes a normalized event. An
    unsigned payload from a provider with no signature mechanism is stored as an
    untrusted notification, and the only thing it may cause is an authenticated read.
    """

    __tablename__ = "integration_webhook_inbox"
    __table_args__ = (
        # The deduplication guarantee, enforced by the database rather than by a check
        # the application performs and hopes to have performed first. Two sessions
        # delivering the same event concurrently: one inserts, the other fails at flush
        # and is converted into an idempotent acknowledgement of the winner.
        UniqueConstraint(
            "provider_key",
            "connection_key",
            "dedupe_key",
            name="uq_integration_webhook_inbox_dedupe",
        ),
        Index(
            "ix_integration_webhook_inbox_state_next_attempt",
            "processing_state",
            "next_attempt_at",
        ),
        Index(
            "ix_integration_webhook_inbox_provider_received",
            "provider_key",
            "received_at",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    provider_key: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    #: The provider API generation that produced this payload. Stored per row, not per
    #: installation: a provider can run two generations at once during a migration, and
    #: a payload has to record which contract it was written against.
    provider_api_version: Mapped[str | None] = mapped_column(String(40), nullable=True)
    connection_key: Mapped[str] = mapped_column(
        String(80), nullable=False, default=UNASSIGNED_CONNECTION
    )
    connection_id: Mapped[int | None] = mapped_column(
        ForeignKey("integration_connections.id", ondelete="SET NULL"), nullable=True, index=True
    )

    received_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    #: Declared content type, kept for audit. Enforced against a configured allowlist on
    #: arrival, so an unexpected type is rejected rather than parsed hopefully.
    content_type: Mapped[str | None] = mapped_column(String(120), nullable=True)
    #: Byte length of the body as received, before any bounding.
    payload_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    #: The bounded body. A payload over the configured limit is refused on arrival rather
    #: than stored truncated, so this is either the whole body or nothing.
    payload_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: True when the body was refused for size and only its digest is retained.
    payload_omitted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    #: SHA-256 of the exact bytes received. Survives the body being omitted, so a refused
    #: oversized delivery can still be recognized if it is sent again.
    payload_sha256: Mapped[str] = mapped_column(String(64), nullable=False)

    #: The provider event id when one was supplied. Preferred for deduplication.
    provider_event_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    #: A stable digest over the immutable fields of the event, computed by the adapter.
    #: Used when no event id exists, and always stored so a later id-bearing delivery can
    #: still be recognized as the same event by an operator.
    payload_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    #: Whichever of the two above is authoritative for this row. Non-null so the unique
    #: constraint actually constrains.
    dedupe_key: Mapped[str] = mapped_column(String(200), nullable=False)
    #: Which one it was: ``provider_event_id`` or ``payload_fingerprint``. Informational,
    #: and deliberately **not** part of the unique key -- including it would let one event
    #: arrive twice, once with an id and once without, and insert twice.
    dedupe_basis: Mapped[str] = mapped_column(String(30), nullable=False)

    verification_state: Mapped[str] = mapped_column(
        String(30), nullable=False, default=WebhookVerificationState.PENDING, index=True
    )
    #: Why verification landed where it did. Redacted: never a signature value, a header,
    #: or a secret.
    verification_detail: Mapped[str | None] = mapped_column(String(255), nullable=True)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    processing_state: Mapped[str] = mapped_column(
        String(30), nullable=False, default=InboxProcessingState.PENDING, index=True
    )
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    rejected_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    failed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    #: A ``ProviderErrorKind`` value. Never a provider status code, never free text from
    #: the provider.
    error_code: Mapped[str | None] = mapped_column(String(40), nullable=True)
    #: Redacted summary. Never a payload, a credential, a URL, or a tracking reference.
    error_summary: Mapped[str | None] = mapped_column(String(400), nullable=True)

    #: Lease held while a worker is processing this item. Expiry is what makes a crashed
    #: worker recoverable without an administrator intervening.
    lease_owner: Mapped[str | None] = mapped_column(String(80), nullable=True)
    lease_token: Mapped[str | None] = mapped_column(String(64), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    #: The normalized event this item produced, if any.
    #:
    #: Stored on the provider-event side rather than duplicated here. A column on both
    #: tables would be a circular foreign key, which SQLite cannot express through
    #: SQLAlchemy metadata ordering and Alembic batch mode; the relationship is navigable
    #: from either end regardless, and one link cannot disagree with itself.
    normalized_event: Mapped[IntegrationProviderEvent | None] = relationship(
        back_populates="inbox_item", uselist=False
    )

    @property
    def resulting_shipment_event_id(self) -> int | None:
        """The shipment event this notification ultimately produced, if it produced one."""
        event = self.normalized_event
        return event.applied_shipment_event_id if event else None


class IntegrationProviderEvent(TimestampMixin, Base):
    """A provider event, normalized into Solaris vocabulary and kept for audit.

    This is the mapping layer CRM.md section 9 asks for, and the reason the rest of the
    application never sees a provider status code. The raw value is preserved here --
    debugging a mapping without it is guesswork -- and never leaves the building:
    ``public_tracking_service`` builds its response field by field from an allowlist that
    does not include this table.

    ``occurred_at`` and ``received_at`` are separate columns and always will be. A late
    delivery is visible as a late delivery, which is what keeps an out-of-order event from
    looking like a fresh scan.
    """

    __tablename__ = "integration_provider_events"
    __table_args__ = (
        UniqueConstraint(
            "provider_key",
            "connection_key",
            "provider_event_fingerprint",
            name="uq_integration_provider_events_fingerprint",
        ),
        UniqueConstraint("inbox_item_id", name="uq_integration_provider_events_inbox_item_id"),
        Index(
            "ix_integration_provider_events_assignment_occurred",
            "tracking_assignment_id",
            "occurred_at",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    provider_key: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    provider_api_version: Mapped[str | None] = mapped_column(String(40), nullable=True)
    connection_key: Mapped[str] = mapped_column(
        String(80), nullable=False, default=UNASSIGNED_CONNECTION
    )

    provider_event_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    #: Always present, so the unique constraint holds even when the provider supplies no
    #: identifier of its own.
    provider_event_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)

    #: The tracking assignment this event is about. ``leg_tracking_references`` is what a
    #: tracking assignment *is* in this schema (Phase 2, DEC-0041).
    tracking_assignment_id: Mapped[int | None] = mapped_column(
        ForeignKey("leg_tracking_references.id", ondelete="SET NULL"), nullable=True, index=True
    )
    shipment_id: Mapped[int | None] = mapped_column(
        ForeignKey("shipments.id", ondelete="CASCADE"), nullable=True, index=True
    )
    package_id: Mapped[int | None] = mapped_column(
        ForeignKey("shipment_packages.id", ondelete="CASCADE"), nullable=True
    )
    leg_id: Mapped[int | None] = mapped_column(
        ForeignKey("shipment_legs.id", ondelete="SET NULL"), nullable=True
    )

    #: Exactly what the provider called it. Preserved for audit and for debugging a
    #: mapping; never published, never shown to a customer.
    raw_status: Mapped[str | None] = mapped_column(String(120), nullable=True)
    #: The provider description, bounded. Internal only, like ``internal_detail``.
    raw_status_detail: Mapped[str | None] = mapped_column(String(1000), nullable=True)

    #: A ``ShipmentEventType`` value. The adapter chooses it; nothing downstream sees the
    #: provider vocabulary.
    normalized_event_type: Mapped[str] = mapped_column(String(40), nullable=False)
    #: The ``OperationalState`` that event type maps to.
    normalized_state: Mapped[str] = mapped_column(String(30), nullable=False)

    #: When the provider says it happened. Nullable: a provider that supplies no time is
    #: recorded as supplying no time, and ``received_at`` is never quietly substituted.
    occurred_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    #: The zone the provider stated, when it stated one.
    occurred_at_timezone: Mapped[str | None] = mapped_column(String(60), nullable=True)
    #: How much the occurred time can be trusted. ``local_no_timezone`` is the explicit
    #: handling CRM.md section 9 requires instead of assuming UTC.
    occurred_time_provenance: Mapped[str] = mapped_column(
        String(30), nullable=False, default=OccurredTimeProvenance.MISSING
    )
    received_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)

    #: How this event earned the right to exist: a verified signature, or an
    #: authenticated read. An unsigned notification never produces a row here.
    verification_source: Mapped[str] = mapped_column(String(30), nullable=False)
    #: Which revision of the adapter mapping produced the normalized values. A mapping
    #: change is a reason to re-examine history, so history has to record which mapping
    #: it was normalized under.
    mapping_version: Mapped[str] = mapped_column(String(40), nullable=False)

    inbox_item_id: Mapped[int | None] = mapped_column(
        ForeignKey("integration_webhook_inbox.id", ondelete="SET NULL"), nullable=True
    )
    inbox_item: Mapped[IntegrationWebhookInboxItem | None] = relationship(
        back_populates="normalized_event"
    )

    application_state: Mapped[str] = mapped_column(
        String(30), nullable=False, default=ProviderEventApplication.PENDING, index=True
    )
    #: The shipment event this produced, when it was applied. NULL when the event was a
    #: duplicate or was superseded -- durable, but with no business effect.
    applied_shipment_event_id: Mapped[int | None] = mapped_column(
        ForeignKey("shipment_events.id", ondelete="SET NULL"), nullable=True
    )
    applied_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    #: Why it was not applied, in application vocabulary. Redacted.
    application_detail: Mapped[str | None] = mapped_column(String(255), nullable=True)

    #: A provider correction pointing at the event it corrects. Explicit semantics rather
    #: than status ranking (CRM.md section 9).
    corrects_event_id: Mapped[int | None] = mapped_column(
        ForeignKey("integration_provider_events.id", ondelete="SET NULL"), nullable=True
    )
    #: Withdrawn by a later correction. The row stays; only its effect is undone.
    is_voided: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    voided_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class IntegrationJob(TimestampMixin, Base):
    """One unit of durable background work.

    **Why leases rather than a status flag.** A worker that dies holding a ``running``
    row would strand that row forever, and "forever" for a delivery notification means a
    customer never sees a delivery. A lease has an expiry, so recovery is the passage of
    time rather than an administrator noticing. A *live* lease cannot be stolen: the claim
    UPDATE requires the lease to be absent or expired, and the database evaluates that
    predicate, not the worker.

    **Why ``active_dedupe_key`` is nullable and unique.** CRM.md section 9 requires at
    most one pending refresh per assignment, so concurrent visitors cannot each trigger a
    chargeable provider call. A plain unique key on the claim would also block the *next*
    legitimate refresh once the first completed. Nulling the column on completion gives
    both: NULLs are distinct in SQLite and PostgreSQL, so terminal rows stop constraining,
    while two live enqueues still collide in the database rather than in a check the
    application hopes it ran first.
    """

    __tablename__ = "integration_jobs"
    __table_args__ = (
        UniqueConstraint("active_dedupe_key", name="uq_integration_jobs_active_dedupe_key"),
        Index(
            "ix_integration_jobs_status_available",
            "status",
            "available_at",
            "priority",
        ),
        Index("ix_integration_jobs_provider_status", "provider_key", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    job_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    provider_key: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    connection_key: Mapped[str] = mapped_column(
        String(80), nullable=False, default=UNASSIGNED_CONNECTION
    )
    connection_id: Mapped[int | None] = mapped_column(
        ForeignKey("integration_connections.id", ondelete="SET NULL"), nullable=True
    )

    tracking_assignment_id: Mapped[int | None] = mapped_column(
        ForeignKey("leg_tracking_references.id", ondelete="CASCADE"), nullable=True, index=True
    )
    inbox_item_id: Mapped[int | None] = mapped_column(
        ForeignKey("integration_webhook_inbox.id", ondelete="CASCADE"), nullable=True, index=True
    )
    shipment_id: Mapped[int | None] = mapped_column(
        ForeignKey("shipments.id", ondelete="CASCADE"), nullable=True, index=True
    )

    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default=IntegrationJobStatus.PENDING, index=True
    )
    available_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    #: Lower runs first. A delivery notification should not queue behind a bulk refresh.
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=100)

    #: The permanent, informational deduplication identity of this job.
    dedupe_key: Mapped[str | None] = mapped_column(String(200), nullable=True, index=True)
    #: The same value while the job is pending or running, NULL once it is not. This is
    #: the column the unique constraint is on; see the class docstring.
    active_dedupe_key: Mapped[str | None] = mapped_column(String(200), nullable=True)

    lease_owner: Mapped[str | None] = mapped_column(String(80), nullable=True)
    lease_token: Mapped[str | None] = mapped_column(String(64), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)

    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    #: What the provider asked for, in seconds, when it asked. Stored as received so the
    #: backoff decision can be audited rather than inferred from the resulting time.
    provider_retry_after_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)

    #: A ``ProviderErrorKind`` value.
    error_code: Mapped[str | None] = mapped_column(String(40), nullable=True)
    #: Redacted. Never a payload, credential, URL, or tracking reference.
    error_summary: Mapped[str | None] = mapped_column(String(400), nullable=True)

    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    failed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    #: The failed-job review queue, as a column rather than a separate table. Set when a
    #: job stops for good; cleared by an audited operator retry, which creates a new
    #: attempt without erasing the failure history that led here.
    requires_review: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, index=True
    )
    #: How many times an operator has manually retried. History, not a counter that
    #: replaces ``attempt_count``.
    manual_retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_manual_retry_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_manual_retry_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class IntegrationWorkerHeartbeat(TimestampMixin, Base):
    """The last time a worker actually reported in.

    A row exists only because a worker wrote it. The health service reports a heartbeat
    only when one is present, so "no worker has run" is displayed as exactly that rather
    than as a stale timestamp or a reassuring default (``Design.md`` section 13 asks for
    honest state; a fabricated uptime is the opposite).
    """

    __tablename__ = "integration_worker_heartbeats"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    worker_name: Mapped[str] = mapped_column(String(80), nullable=False, unique=True)
    #: ``once`` or ``continuous``. Useful when reading a heartbeat left by a test run.
    mode: Mapped[str] = mapped_column(String(20), nullable=False, default="once")
    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    #: Cumulative counts for this worker identity, across runs.
    jobs_claimed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    jobs_succeeded: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    jobs_failed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    #: Set on graceful shutdown, so a stopped worker is distinguishable from a dead one.
    stopped_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
