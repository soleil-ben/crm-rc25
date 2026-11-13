"""phase 4a provider neutral integration foundation

Adds **five** tables and touches nothing that already exists. Phases 1 to 3 are extended,
never rewritten: ``shipments`` and its Phase 2 children are untouched, no column is added
to them, and a Phase 3 database upgrades in place.

* ``integration_connections`` -- a provider account. **No row is created by this
  migration or by the seed command.** No provider is configured, so the health service
  reports ``not_configured``, which is the only truthful answer.
* ``integration_webhook_inbox`` -- durable storage for an inbound notification, written
  and committed before anything is parsed. Deduplication is enforced by
  ``uq_integration_webhook_inbox_dedupe`` over ``(provider_key, connection_key,
  dedupe_key)``, so two concurrent deliveries of one event cannot both insert.
* ``integration_provider_events`` -- the normalized mapping layer. Preserves the raw
  provider status for audit while the rest of the application sees only Solaris
  vocabulary, and keeps ``occurred_at`` and ``received_at`` apart.
* ``integration_jobs`` -- the durable queue. ``active_dedupe_key`` is unique and nullable:
  it holds a claim while a job is pending or running and is nulled when the job stops, so
  concurrent enqueues collide in the database while completed work stops constraining.
* ``integration_worker_heartbeats`` -- written only by a worker that actually ran.

**Nothing here can hold a credential.** There is no column for an authorization header,
an API key, a cookie, or a request header set. ``integration_connections.credential_ref``
holds the *name* of an environment variable and never its value.

The downgrade drops all five in dependency order and restores a Phase 3 database exactly,
because nothing outside these tables was modified.

Revision ID: 9d7dc78dd25c
Revises: 6b767a8a58fe
Create Date: 2026-09-09 18:07:32.049611
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "9d7dc78dd25c"
down_revision: str | None = "6b767a8a58fe"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "integration_worker_heartbeats",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("worker_name", sa.String(length=80), nullable=False),
        sa.Column("mode", sa.String(length=20), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(), nullable=False),
        sa.Column("jobs_claimed", sa.Integer(), nullable=False),
        sa.Column("jobs_succeeded", sa.Integer(), nullable=False),
        sa.Column("jobs_failed", sa.Integer(), nullable=False),
        sa.Column("stopped_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_integration_worker_heartbeats")),
        sa.UniqueConstraint(
            "worker_name", name=op.f("uq_integration_worker_heartbeats_worker_name")
        ),
    )
    with op.batch_alter_table("integration_worker_heartbeats", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_integration_worker_heartbeats_created_at"), ["created_at"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_integration_worker_heartbeats_last_seen_at"),
            ["last_seen_at"],
            unique=False,
        )

    op.create_table(
        "integration_connections",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("provider_key", sa.String(length=40), nullable=False),
        sa.Column("provider_api_version", sa.String(length=40), nullable=True),
        sa.Column("connection_key", sa.String(length=80), nullable=False),
        sa.Column("display_label", sa.String(length=120), nullable=True),
        sa.Column("state", sa.String(length=30), nullable=False),
        sa.Column("is_enabled", sa.Boolean(), nullable=False),
        sa.Column("credential_ref", sa.String(length=120), nullable=True),
        sa.Column("last_success_at", sa.DateTime(), nullable=True),
        sa.Column("last_success_operation", sa.String(length=60), nullable=True),
        sa.Column("last_error_at", sa.DateTime(), nullable=True),
        sa.Column("last_error_code", sa.String(length=40), nullable=True),
        sa.Column("last_error_summary", sa.String(length=400), nullable=True),
        sa.Column("disabled_at", sa.DateTime(), nullable=True),
        sa.Column("disabled_reason", sa.String(length=255), nullable=True),
        sa.Column("disabled_by_user_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["disabled_by_user_id"],
            ["users.id"],
            name=op.f("fk_integration_connections_disabled_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_integration_connections")),
        sa.UniqueConstraint(
            "provider_key", "connection_key", name="uq_integration_connections_provider_connection"
        ),
    )
    with op.batch_alter_table("integration_connections", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_integration_connections_created_at"), ["created_at"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_integration_connections_provider_key"), ["provider_key"], unique=False
        )

    op.create_table(
        "integration_webhook_inbox",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("provider_key", sa.String(length=40), nullable=False),
        sa.Column("provider_api_version", sa.String(length=40), nullable=True),
        sa.Column("connection_key", sa.String(length=80), nullable=False),
        sa.Column("connection_id", sa.Integer(), nullable=True),
        sa.Column("received_at", sa.DateTime(), nullable=False),
        sa.Column("content_type", sa.String(length=120), nullable=True),
        sa.Column("payload_bytes", sa.Integer(), nullable=False),
        sa.Column("payload_text", sa.Text(), nullable=True),
        sa.Column("payload_omitted", sa.Boolean(), nullable=False),
        sa.Column("payload_sha256", sa.String(length=64), nullable=False),
        sa.Column("provider_event_id", sa.String(length=200), nullable=True),
        sa.Column("payload_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("dedupe_key", sa.String(length=200), nullable=False),
        sa.Column("dedupe_basis", sa.String(length=30), nullable=False),
        sa.Column("verification_state", sa.String(length=30), nullable=False),
        sa.Column("verification_detail", sa.String(length=255), nullable=True),
        sa.Column("verified_at", sa.DateTime(), nullable=True),
        sa.Column("processing_state", sa.String(length=30), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(), nullable=True),
        sa.Column("processed_at", sa.DateTime(), nullable=True),
        sa.Column("rejected_at", sa.DateTime(), nullable=True),
        sa.Column("failed_at", sa.DateTime(), nullable=True),
        sa.Column("error_code", sa.String(length=40), nullable=True),
        sa.Column("error_summary", sa.String(length=400), nullable=True),
        sa.Column("lease_owner", sa.String(length=80), nullable=True),
        sa.Column("lease_token", sa.String(length=64), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["connection_id"],
            ["integration_connections.id"],
            name=op.f("fk_integration_webhook_inbox_connection_id_integration_connections"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_integration_webhook_inbox")),
        sa.UniqueConstraint(
            "provider_key",
            "connection_key",
            "dedupe_key",
            name="uq_integration_webhook_inbox_dedupe",
        ),
    )
    with op.batch_alter_table("integration_webhook_inbox", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_integration_webhook_inbox_connection_id"),
            ["connection_id"],
            unique=False,
        )
        batch_op.create_index(
            batch_op.f("ix_integration_webhook_inbox_created_at"), ["created_at"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_integration_webhook_inbox_processing_state"),
            ["processing_state"],
            unique=False,
        )
        batch_op.create_index(
            batch_op.f("ix_integration_webhook_inbox_provider_key"), ["provider_key"], unique=False
        )
        batch_op.create_index(
            "ix_integration_webhook_inbox_provider_received",
            ["provider_key", "received_at"],
            unique=False,
        )
        batch_op.create_index(
            batch_op.f("ix_integration_webhook_inbox_received_at"), ["received_at"], unique=False
        )
        batch_op.create_index(
            "ix_integration_webhook_inbox_state_next_attempt",
            ["processing_state", "next_attempt_at"],
            unique=False,
        )
        batch_op.create_index(
            batch_op.f("ix_integration_webhook_inbox_verification_state"),
            ["verification_state"],
            unique=False,
        )

    op.create_table(
        "integration_jobs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("job_type", sa.String(length=50), nullable=False),
        sa.Column("provider_key", sa.String(length=40), nullable=False),
        sa.Column("connection_key", sa.String(length=80), nullable=False),
        sa.Column("connection_id", sa.Integer(), nullable=True),
        sa.Column("tracking_assignment_id", sa.Integer(), nullable=True),
        sa.Column("inbox_item_id", sa.Integer(), nullable=True),
        sa.Column("shipment_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("available_at", sa.DateTime(), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("dedupe_key", sa.String(length=200), nullable=True),
        sa.Column("active_dedupe_key", sa.String(length=200), nullable=True),
        sa.Column("lease_owner", sa.String(length=80), nullable=True),
        sa.Column("lease_token", sa.String(length=64), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(), nullable=True),
        sa.Column("last_attempt_at", sa.DateTime(), nullable=True),
        sa.Column("next_retry_at", sa.DateTime(), nullable=True),
        sa.Column("provider_retry_after_seconds", sa.Integer(), nullable=True),
        sa.Column("error_code", sa.String(length=40), nullable=True),
        sa.Column("error_summary", sa.String(length=400), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("failed_at", sa.DateTime(), nullable=True),
        sa.Column("requires_review", sa.Boolean(), nullable=False),
        sa.Column("manual_retry_count", sa.Integer(), nullable=False),
        sa.Column("last_manual_retry_at", sa.DateTime(), nullable=True),
        sa.Column("last_manual_retry_by_user_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["connection_id"],
            ["integration_connections.id"],
            name=op.f("fk_integration_jobs_connection_id_integration_connections"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["inbox_item_id"],
            ["integration_webhook_inbox.id"],
            name=op.f("fk_integration_jobs_inbox_item_id_integration_webhook_inbox"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["last_manual_retry_by_user_id"],
            ["users.id"],
            name=op.f("fk_integration_jobs_last_manual_retry_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["shipment_id"],
            ["shipments.id"],
            name=op.f("fk_integration_jobs_shipment_id_shipments"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tracking_assignment_id"],
            ["leg_tracking_references.id"],
            name=op.f("fk_integration_jobs_tracking_assignment_id_leg_tracking_references"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_integration_jobs")),
        sa.UniqueConstraint("active_dedupe_key", name="uq_integration_jobs_active_dedupe_key"),
    )
    with op.batch_alter_table("integration_jobs", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_integration_jobs_available_at"), ["available_at"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_integration_jobs_created_at"), ["created_at"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_integration_jobs_dedupe_key"), ["dedupe_key"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_integration_jobs_inbox_item_id"), ["inbox_item_id"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_integration_jobs_job_type"), ["job_type"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_integration_jobs_lease_expires_at"), ["lease_expires_at"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_integration_jobs_provider_key"), ["provider_key"], unique=False
        )
        batch_op.create_index(
            "ix_integration_jobs_provider_status", ["provider_key", "status"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_integration_jobs_requires_review"), ["requires_review"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_integration_jobs_shipment_id"), ["shipment_id"], unique=False
        )
        batch_op.create_index(batch_op.f("ix_integration_jobs_status"), ["status"], unique=False)
        batch_op.create_index(
            "ix_integration_jobs_status_available",
            ["status", "available_at", "priority"],
            unique=False,
        )
        batch_op.create_index(
            batch_op.f("ix_integration_jobs_tracking_assignment_id"),
            ["tracking_assignment_id"],
            unique=False,
        )

    op.create_table(
        "integration_provider_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("provider_key", sa.String(length=40), nullable=False),
        sa.Column("provider_api_version", sa.String(length=40), nullable=True),
        sa.Column("connection_key", sa.String(length=80), nullable=False),
        sa.Column("provider_event_id", sa.String(length=200), nullable=True),
        sa.Column("provider_event_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("tracking_assignment_id", sa.Integer(), nullable=True),
        sa.Column("shipment_id", sa.Integer(), nullable=True),
        sa.Column("package_id", sa.Integer(), nullable=True),
        sa.Column("leg_id", sa.Integer(), nullable=True),
        sa.Column("raw_status", sa.String(length=120), nullable=True),
        sa.Column("raw_status_detail", sa.String(length=1000), nullable=True),
        sa.Column("normalized_event_type", sa.String(length=40), nullable=False),
        sa.Column("normalized_state", sa.String(length=30), nullable=False),
        sa.Column("occurred_at", sa.DateTime(), nullable=True),
        sa.Column("occurred_at_timezone", sa.String(length=60), nullable=True),
        sa.Column("occurred_time_provenance", sa.String(length=30), nullable=False),
        sa.Column("received_at", sa.DateTime(), nullable=False),
        sa.Column("verification_source", sa.String(length=30), nullable=False),
        sa.Column("mapping_version", sa.String(length=40), nullable=False),
        sa.Column("inbox_item_id", sa.Integer(), nullable=True),
        sa.Column("application_state", sa.String(length=30), nullable=False),
        sa.Column("applied_shipment_event_id", sa.Integer(), nullable=True),
        sa.Column("applied_at", sa.DateTime(), nullable=True),
        sa.Column("application_detail", sa.String(length=255), nullable=True),
        sa.Column("corrects_event_id", sa.Integer(), nullable=True),
        sa.Column("is_voided", sa.Boolean(), nullable=False),
        sa.Column("voided_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["applied_shipment_event_id"],
            ["shipment_events.id"],
            name=op.f("fk_integration_provider_events_applied_shipment_event_id_shipment_events"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["corrects_event_id"],
            ["integration_provider_events.id"],
            name=op.f(
                "fk_integration_provider_events_corrects_event_id_integration_provider_events"
            ),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["inbox_item_id"],
            ["integration_webhook_inbox.id"],
            name=op.f("fk_integration_provider_events_inbox_item_id_integration_webhook_inbox"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["leg_id"],
            ["shipment_legs.id"],
            name=op.f("fk_integration_provider_events_leg_id_shipment_legs"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["package_id"],
            ["shipment_packages.id"],
            name=op.f("fk_integration_provider_events_package_id_shipment_packages"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["shipment_id"],
            ["shipments.id"],
            name=op.f("fk_integration_provider_events_shipment_id_shipments"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tracking_assignment_id"],
            ["leg_tracking_references.id"],
            name=op.f(
                "fk_integration_provider_events_tracking_assignment_id_leg_tracking_references"
            ),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_integration_provider_events")),
        sa.UniqueConstraint("inbox_item_id", name="uq_integration_provider_events_inbox_item_id"),
        sa.UniqueConstraint(
            "provider_key",
            "connection_key",
            "provider_event_fingerprint",
            name="uq_integration_provider_events_fingerprint",
        ),
    )
    with op.batch_alter_table("integration_provider_events", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_integration_provider_events_application_state"),
            ["application_state"],
            unique=False,
        )
        batch_op.create_index(
            "ix_integration_provider_events_assignment_occurred",
            ["tracking_assignment_id", "occurred_at"],
            unique=False,
        )
        batch_op.create_index(
            batch_op.f("ix_integration_provider_events_created_at"), ["created_at"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_integration_provider_events_provider_key"),
            ["provider_key"],
            unique=False,
        )
        batch_op.create_index(
            batch_op.f("ix_integration_provider_events_received_at"), ["received_at"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_integration_provider_events_shipment_id"), ["shipment_id"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_integration_provider_events_tracking_assignment_id"),
            ["tracking_assignment_id"],
            unique=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("integration_provider_events", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_integration_provider_events_tracking_assignment_id"))
        batch_op.drop_index(batch_op.f("ix_integration_provider_events_shipment_id"))
        batch_op.drop_index(batch_op.f("ix_integration_provider_events_received_at"))
        batch_op.drop_index(batch_op.f("ix_integration_provider_events_provider_key"))
        batch_op.drop_index(batch_op.f("ix_integration_provider_events_created_at"))
        batch_op.drop_index("ix_integration_provider_events_assignment_occurred")
        batch_op.drop_index(batch_op.f("ix_integration_provider_events_application_state"))

    op.drop_table("integration_provider_events")
    with op.batch_alter_table("integration_jobs", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_integration_jobs_tracking_assignment_id"))
        batch_op.drop_index("ix_integration_jobs_status_available")
        batch_op.drop_index(batch_op.f("ix_integration_jobs_status"))
        batch_op.drop_index(batch_op.f("ix_integration_jobs_shipment_id"))
        batch_op.drop_index(batch_op.f("ix_integration_jobs_requires_review"))
        batch_op.drop_index("ix_integration_jobs_provider_status")
        batch_op.drop_index(batch_op.f("ix_integration_jobs_provider_key"))
        batch_op.drop_index(batch_op.f("ix_integration_jobs_lease_expires_at"))
        batch_op.drop_index(batch_op.f("ix_integration_jobs_job_type"))
        batch_op.drop_index(batch_op.f("ix_integration_jobs_inbox_item_id"))
        batch_op.drop_index(batch_op.f("ix_integration_jobs_dedupe_key"))
        batch_op.drop_index(batch_op.f("ix_integration_jobs_created_at"))
        batch_op.drop_index(batch_op.f("ix_integration_jobs_available_at"))

    op.drop_table("integration_jobs")
    with op.batch_alter_table("integration_webhook_inbox", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_integration_webhook_inbox_verification_state"))
        batch_op.drop_index("ix_integration_webhook_inbox_state_next_attempt")
        batch_op.drop_index(batch_op.f("ix_integration_webhook_inbox_received_at"))
        batch_op.drop_index("ix_integration_webhook_inbox_provider_received")
        batch_op.drop_index(batch_op.f("ix_integration_webhook_inbox_provider_key"))
        batch_op.drop_index(batch_op.f("ix_integration_webhook_inbox_processing_state"))
        batch_op.drop_index(batch_op.f("ix_integration_webhook_inbox_created_at"))
        batch_op.drop_index(batch_op.f("ix_integration_webhook_inbox_connection_id"))

    op.drop_table("integration_webhook_inbox")
    with op.batch_alter_table("integration_connections", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_integration_connections_provider_key"))
        batch_op.drop_index(batch_op.f("ix_integration_connections_created_at"))

    op.drop_table("integration_connections")
    with op.batch_alter_table("integration_worker_heartbeats", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_integration_worker_heartbeats_last_seen_at"))
        batch_op.drop_index(batch_op.f("ix_integration_worker_heartbeats_created_at"))

    op.drop_table("integration_worker_heartbeats")
