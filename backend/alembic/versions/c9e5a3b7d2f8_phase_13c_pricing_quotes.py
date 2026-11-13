"""Phase 13C: pricing settings, surcharge policies, fee lines, cartons, quote versions.

Revision ID: c9e5a3b7d2f8
Revises: b8d4f2a6c1e7
Create Date: 2026-10-19

Six new tables. **No existing table is altered and no existing row is read or rewritten**
(the lesson of DEC-0181: a foreign-key column on an existing SQLite table rebuilds it).

* ``pricing_settings`` -- one row, created on first use: the Air Standard default rate
  (CAD 18.00/kg) and the full-master trigger share (2/3), both configurable defaults pending
  owner confirmation (OD-48), and the vendor delivery postal code L5A 3K6 (OD-46).
* ``surcharge_rule_policies`` -- per-rule markup and scope override, keyed by the vendor's
  section and row number so a policy outlives a tariff version (OD-44).
* ``shipment_fee_lines`` -- surcharges attached to items by staff; one active line per item
  and rule (partial unique index); removal keeps the row. ``manual_unit_price_vnd`` holds
  the vendor's quoted price for a manual-quote rule (OD-56).
* ``consolidation_cartons`` -- each carton of a master (weight, dimensions) for the
  under-12 kg piece fee on lots of 21 kg and over (OD-62). CASCADE with the consolidation.
* ``quote_versions`` -- versioned customer quotes with the full pricing snapshot; one open
  draft per shipment (partial unique index). ``shipment_id`` is RESTRICT: a finalised quote
  is a financial record, so its shipment cannot be deleted under it.
* ``quote_lines`` -- base freight and surcharge lines, customer revenue beside internal cost.

**Downgrade** drops the six tables in dependency order.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c9e5a3b7d2f8"
down_revision: str | None = "b8d4f2a6c1e7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "pricing_settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "air_standard_default_rate_cad", sa.Numeric(precision=8, scale=2), nullable=False
        ),
        sa.Column("air_express_default_rate_cad", sa.Numeric(precision=8, scale=2), nullable=True),
        sa.Column("trigger_share_numerator", sa.Integer(), nullable=False),
        sa.Column("trigger_share_denominator", sa.Integer(), nullable=False),
        sa.Column("defaults_owner_confirmed", sa.Boolean(), nullable=False),
        sa.Column("vendor_delivery_postal_code", sa.String(length=6), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("updated_by_user_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["updated_by_user_id"],
            ["users.id"],
            name=op.f("fk_pricing_settings_updated_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_pricing_settings")),
    )
    op.create_table(
        "surcharge_rule_policies",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("section", sa.String(length=20), nullable=False),
        sa.Column("stt", sa.Integer(), nullable=False),
        sa.Column("markup_kind", sa.String(length=20), nullable=False),
        sa.Column("markup_value", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column("scope_override", sa.String(length=20), nullable=True),
        sa.Column("note", sa.String(length=400), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("updated_by_user_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["updated_by_user_id"],
            ["users.id"],
            name=op.f("fk_surcharge_rule_policies_updated_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_surcharge_rule_policies")),
        sa.UniqueConstraint("section", "stt", name="uq_surcharge_rule_policies_section_stt"),
    )
    op.create_table(
        "consolidation_cartons",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("consolidation_id", sa.Integer(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("weight_kg", sa.Numeric(precision=8, scale=3), nullable=False),
        sa.Column("length_cm", sa.Numeric(precision=8, scale=2), nullable=True),
        sa.Column("width_cm", sa.Numeric(precision=8, scale=2), nullable=True),
        sa.Column("height_cm", sa.Numeric(precision=8, scale=2), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["consolidation_id"],
            ["consolidations.id"],
            name=op.f("fk_consolidation_cartons_consolidation_id_consolidations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            name=op.f("fk_consolidation_cartons_created_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_consolidation_cartons")),
        sa.UniqueConstraint(
            "consolidation_id", "sequence", name="uq_consolidation_cartons_consolidation_sequence"
        ),
    )
    with op.batch_alter_table("consolidation_cartons", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_consolidation_cartons_consolidation_id"),
            ["consolidation_id"],
            unique=False,
        )

    op.create_table(
        "quote_versions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("shipment_id", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=12), nullable=False),
        sa.Column("consolidation_id", sa.Integer(), nullable=True),
        sa.Column("tariff_version_id", sa.Integer(), nullable=True),
        sa.Column("fx_snapshot_id", sa.Integer(), nullable=True),
        sa.Column("solaris_service", sa.String(length=20), nullable=False),
        sa.Column("default_rate_cad", sa.Numeric(precision=8, scale=2), nullable=True),
        sa.Column("selling_rate_cad", sa.Numeric(precision=8, scale=2), nullable=True),
        sa.Column("override_reason", sa.String(length=400), nullable=True),
        sa.Column("rate_confirmed_at", sa.DateTime(), nullable=True),
        sa.Column("rate_confirmed_by_user_id", sa.Integer(), nullable=True),
        sa.Column("confirmed_inputs_sha256", sa.String(length=64), nullable=True),
        sa.Column("inputs_sha256", sa.String(length=64), nullable=False),
        sa.Column("negative_margin_reason", sa.String(length=400), nullable=True),
        sa.Column("billable_weight_kg", sa.Numeric(precision=8, scale=3), nullable=True),
        sa.Column("base_revenue_cad", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("surcharge_revenue_cad", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("total_revenue_cad", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("allocated_cost_cad", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("gross_profit_cad", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("blocking_json", sa.Text(), nullable=False),
        sa.Column("provisional_json", sa.Text(), nullable=False),
        sa.Column("snapshot_json", sa.Text(), nullable=False),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
        sa.Column("finalized_at", sa.DateTime(), nullable=True),
        sa.Column("finalized_by_user_id", sa.Integer(), nullable=True),
        sa.Column("superseded_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["consolidation_id"],
            ["consolidations.id"],
            name=op.f("fk_quote_versions_consolidation_id_consolidations"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            name=op.f("fk_quote_versions_created_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["finalized_by_user_id"],
            ["users.id"],
            name=op.f("fk_quote_versions_finalized_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["fx_snapshot_id"],
            ["fx_rate_snapshots.id"],
            name=op.f("fk_quote_versions_fx_snapshot_id_fx_rate_snapshots"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["rate_confirmed_by_user_id"],
            ["users.id"],
            name=op.f("fk_quote_versions_rate_confirmed_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["shipment_id"],
            ["shipments.id"],
            name=op.f("fk_quote_versions_shipment_id_shipments"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tariff_version_id"],
            ["tariff_versions.id"],
            name=op.f("fk_quote_versions_tariff_version_id_tariff_versions"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_quote_versions")),
        sa.UniqueConstraint("shipment_id", "version", name="uq_quote_versions_shipment_id_version"),
    )
    with op.batch_alter_table("quote_versions", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_quote_versions_created_at"), ["created_at"], unique=False
        )
        batch_op.create_index(
            "uq_quote_versions_open_draft",
            ["shipment_id"],
            unique=True,
            sqlite_where=sa.text("status = 'draft'"),
            postgresql_where=sa.text("status = 'draft'"),
        )

    op.create_table(
        "quote_lines",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("version_id", sa.Integer(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("description", sa.String(length=300), nullable=False),
        sa.Column("section", sa.String(length=20), nullable=True),
        sa.Column("stt", sa.Integer(), nullable=True),
        sa.Column("quantity", sa.Numeric(precision=10, scale=3), nullable=True),
        sa.Column("unit", sa.String(length=20), nullable=True),
        sa.Column("revenue_cad", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("cost_vnd", sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column("cost_cad", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("is_trigger", sa.Boolean(), nullable=False),
        sa.Column("markup_kind", sa.String(length=20), nullable=True),
        sa.Column("markup_value", sa.Numeric(precision=10, scale=2), nullable=True),
        sa.ForeignKeyConstraint(
            ["version_id"],
            ["quote_versions.id"],
            name=op.f("fk_quote_lines_version_id_quote_versions"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_quote_lines")),
        sa.UniqueConstraint("version_id", "sequence", name="uq_quote_lines_version_id_sequence"),
    )
    op.create_table(
        "shipment_fee_lines",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("shipment_id", sa.Integer(), nullable=False),
        sa.Column("item_id", sa.Integer(), nullable=False),
        sa.Column("section", sa.String(length=20), nullable=False),
        sa.Column("stt", sa.Integer(), nullable=False),
        sa.Column("quantity", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column("weight_kg", sa.Numeric(precision=8, scale=3), nullable=True),
        sa.Column("manual_unit_price_vnd", sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
        sa.Column("removed_at", sa.DateTime(), nullable=True),
        sa.Column("removed_by_user_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            name=op.f("fk_shipment_fee_lines_created_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["item_id"],
            ["shipment_items.id"],
            name=op.f("fk_shipment_fee_lines_item_id_shipment_items"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["removed_by_user_id"],
            ["users.id"],
            name=op.f("fk_shipment_fee_lines_removed_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["shipment_id"],
            ["shipments.id"],
            name=op.f("fk_shipment_fee_lines_shipment_id_shipments"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_shipment_fee_lines")),
    )
    with op.batch_alter_table("shipment_fee_lines", schema=None) as batch_op:
        batch_op.create_index(
            "ix_shipment_fee_lines_shipment_id_removed_at",
            ["shipment_id", "removed_at"],
            unique=False,
        )
        batch_op.create_index(
            "uq_shipment_fee_lines_active_item_rule",
            ["item_id", "section", "stt"],
            unique=True,
            sqlite_where=sa.text("removed_at IS NULL"),
            postgresql_where=sa.text("removed_at IS NULL"),
        )


def downgrade() -> None:
    with op.batch_alter_table("shipment_fee_lines", schema=None) as batch_op:
        batch_op.drop_index(
            "uq_shipment_fee_lines_active_item_rule",
            sqlite_where=sa.text("removed_at IS NULL"),
            postgresql_where=sa.text("removed_at IS NULL"),
        )
        batch_op.drop_index("ix_shipment_fee_lines_shipment_id_removed_at")

    op.drop_table("shipment_fee_lines")
    op.drop_table("quote_lines")
    with op.batch_alter_table("quote_versions", schema=None) as batch_op:
        batch_op.drop_index(
            "uq_quote_versions_open_draft",
            sqlite_where=sa.text("status = 'draft'"),
            postgresql_where=sa.text("status = 'draft'"),
        )
        batch_op.drop_index(batch_op.f("ix_quote_versions_created_at"))

    op.drop_table("quote_versions")
    with op.batch_alter_table("consolidation_cartons", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_consolidation_cartons_consolidation_id"))

    op.drop_table("consolidation_cartons")
    op.drop_table("surcharge_rule_policies")
    op.drop_table("pricing_settings")
