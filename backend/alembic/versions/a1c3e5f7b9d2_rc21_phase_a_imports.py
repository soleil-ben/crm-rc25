"""RC-UAT-21 Phase A: shipment import and legacy history baseline.

Revision ID: a1c3e5f7b9d2
Revises: f7c2d9e3a1b5
Create Date: 2026-10-24

Four new tables; nothing existing is altered (DEC-0181). DEC-0230.

* ``shipment_import_links`` -- which committed import batch (``import_batches``, kind
  ``shipments``) created which shipment, from which row, under which external reference.
  Unique ``(source_system, external_reference)`` refuses a duplicate import; unique
  ``shipment_id`` ties each imported shipment to exactly one batch.
* ``legacy_baselines`` -- one per committed legacy-history import (``import_batches`` kind
  ``legacy_history``): source system, optional cutoff date, and soft-void state.
* ``legacy_shipments`` -- read-only historical shipments, kept apart from ``shipments`` so no
  queue, quote, invoice, lock, expiry, notification or finance report reaches them.
  ``active_key`` (unique; NULL once voided) makes a re-run idempotent.
* ``legacy_shipment_events`` -- the dated milestones of a legacy shipment.

**Downgrade** drops the four tables: imported shipments stay ordinary shipments (they keep
``source_system`` / ``source_record_id``) but lose their batch link, and every legacy record
is gone. The ``import_batches`` rows of both kinds remain.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a1c3e5f7b9d2"
down_revision: str | None = "f7c2d9e3a1b5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "legacy_baselines",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("batch_id", sa.Integer(), nullable=False),
        sa.Column("source_system", sa.String(length=60), nullable=False),
        sa.Column("cutoff_date", sa.Date(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("created_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("voided_at", sa.DateTime(), nullable=True),
        sa.Column("voided_by_user_id", sa.Integer(), nullable=True),
        sa.Column("void_reason", sa.String(length=400), nullable=True),
        sa.ForeignKeyConstraint(
            ["batch_id"],
            ["import_batches.id"],
            name=op.f("fk_legacy_baselines_batch_id_import_batches"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["voided_by_user_id"],
            ["users.id"],
            name=op.f("fk_legacy_baselines_voided_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_legacy_baselines")),
        sa.UniqueConstraint("batch_id", name=op.f("uq_legacy_baselines_batch_id")),
    )
    op.create_table(
        "legacy_shipments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("baseline_id", sa.Integer(), nullable=False),
        sa.Column("row_number", sa.Integer(), nullable=False),
        sa.Column("customer_id", sa.Integer(), nullable=False),
        sa.Column("source_system", sa.String(length=60), nullable=False),
        sa.Column("legacy_reference", sa.String(length=120), nullable=False),
        sa.Column("active_key", sa.String(length=190), nullable=True),
        sa.Column("route_group", sa.String(length=3), nullable=False),
        sa.Column("direction", sa.String(length=20), nullable=False),
        sa.Column("transport_mode", sa.String(length=20), nullable=False),
        sa.Column("booked_on", sa.Date(), nullable=False),
        sa.Column("final_status", sa.String(length=20), nullable=False),
        sa.Column("completed_on", sa.Date(), nullable=True),
        sa.Column("recipient_name", sa.String(length=200), nullable=True),
        sa.Column("recipient_city", sa.String(length=120), nullable=True),
        sa.Column("recipient_province_state", sa.String(length=120), nullable=True),
        sa.Column("recipient_country_code", sa.String(length=2), nullable=True),
        sa.Column("package_count", sa.Integer(), nullable=True),
        sa.Column("total_weight_kg", sa.Numeric(precision=10, scale=3), nullable=True),
        sa.Column("contents_description", sa.String(length=400), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("is_voided", sa.Boolean(), nullable=False),
        sa.Column("voided_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["baseline_id"],
            ["legacy_baselines.id"],
            name=op.f("fk_legacy_shipments_baseline_id_legacy_baselines"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["customer_id"],
            ["customers.id"],
            name=op.f("fk_legacy_shipments_customer_id_customers"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_legacy_shipments")),
        sa.UniqueConstraint("active_key", name=op.f("uq_legacy_shipments_active_key")),
    )
    with op.batch_alter_table("legacy_shipments", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_legacy_shipments_baseline_id"), ["baseline_id"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_legacy_shipments_booked_on"), ["booked_on"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_legacy_shipments_customer_id"), ["customer_id"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_legacy_shipments_legacy_reference"), ["legacy_reference"], unique=False
        )

    op.create_table(
        "legacy_shipment_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("legacy_shipment_id", sa.Integer(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=40), nullable=False),
        sa.Column("occurred_on", sa.Date(), nullable=False),
        sa.ForeignKeyConstraint(
            ["legacy_shipment_id"],
            ["legacy_shipments.id"],
            name=op.f("fk_legacy_shipment_events_legacy_shipment_id_legacy_shipments"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_legacy_shipment_events")),
        sa.UniqueConstraint(
            "legacy_shipment_id",
            "sequence",
            name=op.f("uq_legacy_shipment_events_legacy_shipment_id_sequence"),
        ),
    )
    with op.batch_alter_table("legacy_shipment_events", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_legacy_shipment_events_legacy_shipment_id"),
            ["legacy_shipment_id"],
            unique=False,
        )

    op.create_table(
        "shipment_import_links",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("batch_id", sa.Integer(), nullable=False),
        sa.Column("row_number", sa.Integer(), nullable=False),
        sa.Column("shipment_id", sa.Integer(), nullable=False),
        sa.Column("source_system", sa.String(length=60), nullable=False),
        sa.Column("external_reference", sa.String(length=120), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["batch_id"],
            ["import_batches.id"],
            name=op.f("fk_shipment_import_links_batch_id_import_batches"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["shipment_id"],
            ["shipments.id"],
            name=op.f("fk_shipment_import_links_shipment_id_shipments"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_shipment_import_links")),
        sa.UniqueConstraint("shipment_id", name=op.f("uq_shipment_import_links_shipment_id")),
        sa.UniqueConstraint(
            "source_system",
            "external_reference",
            name=op.f("uq_shipment_import_links_source_system_external_reference"),
        ),
    )
    with op.batch_alter_table("shipment_import_links", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_shipment_import_links_batch_id"), ["batch_id"], unique=False
        )


def downgrade() -> None:
    with op.batch_alter_table("shipment_import_links", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_shipment_import_links_batch_id"))
    op.drop_table("shipment_import_links")

    with op.batch_alter_table("legacy_shipment_events", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_legacy_shipment_events_legacy_shipment_id"))
    op.drop_table("legacy_shipment_events")

    with op.batch_alter_table("legacy_shipments", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_legacy_shipments_legacy_reference"))
        batch_op.drop_index(batch_op.f("ix_legacy_shipments_customer_id"))
        batch_op.drop_index(batch_op.f("ix_legacy_shipments_booked_on"))
        batch_op.drop_index(batch_op.f("ix_legacy_shipments_baseline_id"))
    op.drop_table("legacy_shipments")
    op.drop_table("legacy_baselines")
