"""Phase 13A: vendor tariffs and bank exchange rates.

Revision ID: f53efaa7773e
Revises: 6af30fcdd3a8
Create Date: 2026-10-19

Twelve new tables. **Nothing existing is altered, dropped, or rewritten**, and no row of
any existing table is read, so every deployment at ``6af30fcdd3a8`` upgrades in place.

**Why these tables exist.** The B2C merge adds what the vendor charges Solaris, as
versioned, provenance-bearing data (``docs/b2c_merge/06_MERGE_PLAN.md`` phase 13A):
``vendors`` and ``tariff_versions``; under a version, ``tariff_products``,
``tariff_rate_brackets``, ``tariff_zone_fsas``, ``tariff_beyond_postal_codes``,
``tariff_beyond_rates``, ``tariff_accessorials``, ``tariff_surcharge_rules`` and
``tariff_surcharge_rule_tiers``. Beside them, ``fx_rate_snapshots`` (every verified
reading of the bank's CAD row) and ``fx_sync_attempts`` (every attempt, failed or not).

**Why nothing on ``shipments``.** No shipment is priced in this phase; the pricing engine
(13C) will reference a tariff version and an FX snapshot from the quotation it creates.
Adding a column now would be a column nothing writes.

**Why the per-row provenance columns.** Every priced row names the sheet and cell it was
read from, so a number in the database can be traced to a cell the vendor wrote
(handoff section 16). They are plain strings and cost nothing to carry.

**Deletion behaviour is declared on every foreign key**, as in every earlier phase: a
version's child rows cascade with the version, a user or snapshot reference is set to
NULL, and a vendor with versions cannot be deleted.

**Downgrade** drops the twelve tables in dependency order. No data in any other table is
touched either way.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "f53efaa7773e"
down_revision: str | None = "6af30fcdd3a8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "fx_rate_snapshots",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("bank", sa.String(length=30), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("cash_buy_vnd", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("transfer_buy_vnd", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("sell_vnd", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("bank_published_raw", sa.String(length=60), nullable=True),
        sa.Column("bank_published_at", sa.DateTime(), nullable=True),
        sa.Column("retrieved_at", sa.DateTime(), nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column("source_url", sa.String(length=255), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_fx_rate_snapshots")),
    )
    with op.batch_alter_table("fx_rate_snapshots", schema=None) as batch_op:
        batch_op.create_index(
            "ix_fx_rate_snapshots_bank_currency_retrieved_at",
            ["bank", "currency", "retrieved_at"],
            unique=False,
        )

    op.create_table(
        "vendors",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("key", sa.String(length=40), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_vendors")),
        sa.UniqueConstraint("key", name="uq_vendors_key"),
    )
    with op.batch_alter_table("vendors", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_vendors_created_at"), ["created_at"], unique=False)

    op.create_table(
        "fx_sync_attempts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("bank", sa.String(length=30), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("attempted_at", sa.DateTime(), nullable=False),
        sa.Column("outcome", sa.String(length=10), nullable=False),
        sa.Column("error_summary", sa.String(length=300), nullable=True),
        sa.Column("snapshot_id", sa.Integer(), nullable=True),
        sa.Column("worker_name", sa.String(length=60), nullable=False),
        sa.ForeignKeyConstraint(
            ["snapshot_id"],
            ["fx_rate_snapshots.id"],
            name=op.f("fk_fx_sync_attempts_snapshot_id_fx_rate_snapshots"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_fx_sync_attempts")),
    )
    with op.batch_alter_table("fx_sync_attempts", schema=None) as batch_op:
        batch_op.create_index(
            "ix_fx_sync_attempts_bank_attempted_at", ["bank", "attempted_at"], unique=False
        )

    op.create_table(
        "tariff_versions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("public_id", sa.String(length=20), nullable=False),
        sa.Column("vendor_id", sa.Integer(), nullable=False),
        sa.Column("label", sa.String(length=120), nullable=False),
        sa.Column("source_file_name", sa.String(length=255), nullable=True),
        sa.Column("source_sha256", sa.String(length=64), nullable=False),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("effective_to", sa.Date(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("imported_at", sa.DateTime(), nullable=False),
        sa.Column("imported_by_user_id", sa.Integer(), nullable=True),
        sa.Column("activated_at", sa.DateTime(), nullable=True),
        sa.Column("activated_by_user_id", sa.Integer(), nullable=True),
        sa.Column("dim_divisor_default", sa.Integer(), nullable=False),
        sa.Column("fixed_fx_vnd_per_cad", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("cost_currency", sa.String(length=3), nullable=False),
        sa.Column("import_report_json", sa.Text(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["activated_by_user_id"],
            ["users.id"],
            name=op.f("fk_tariff_versions_activated_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["imported_by_user_id"],
            ["users.id"],
            name=op.f("fk_tariff_versions_imported_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["vendor_id"],
            ["vendors.id"],
            name=op.f("fk_tariff_versions_vendor_id_vendors"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tariff_versions")),
        sa.UniqueConstraint("public_id", name="uq_tariff_versions_public_id"),
        sa.UniqueConstraint(
            "vendor_id", "source_sha256", name="uq_tariff_versions_vendor_id_source_sha256"
        ),
    )
    with op.batch_alter_table("tariff_versions", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_tariff_versions_created_at"), ["created_at"], unique=False
        )
        batch_op.create_index(
            "ix_tariff_versions_vendor_id_status", ["vendor_id", "status"], unique=False
        )

    op.create_table(
        "tariff_accessorials",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("version_id", sa.Integer(), nullable=False),
        sa.Column("key", sa.String(length=60), nullable=False),
        sa.Column("description", sa.String(length=300), nullable=False),
        sa.Column("amount", sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("basis", sa.String(length=30), nullable=False),
        sa.Column("applies_to_modes", sa.String(length=20), nullable=False),
        sa.Column("source_sheet", sa.String(length=60), nullable=False),
        sa.Column("source_cell", sa.String(length=12), nullable=False),
        sa.ForeignKeyConstraint(
            ["version_id"],
            ["tariff_versions.id"],
            name=op.f("fk_tariff_accessorials_version_id_tariff_versions"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tariff_accessorials")),
        sa.UniqueConstraint("version_id", "key", name="uq_tariff_accessorials_version_id_key"),
    )
    op.create_table(
        "tariff_beyond_postal_codes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("version_id", sa.Integer(), nullable=False),
        sa.Column("postal_code", sa.String(length=6), nullable=False),
        sa.Column("city", sa.String(length=80), nullable=True),
        sa.Column("province", sa.String(length=2), nullable=True),
        sa.Column("beyond_code", sa.String(length=6), nullable=False),
        sa.ForeignKeyConstraint(
            ["version_id"],
            ["tariff_versions.id"],
            name=op.f("fk_tariff_beyond_postal_codes_version_id_tariff_versions"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tariff_beyond_postal_codes")),
        sa.UniqueConstraint(
            "version_id", "postal_code", name="uq_tariff_beyond_postal_codes_version_id_postal_code"
        ),
    )
    op.create_table(
        "tariff_beyond_rates",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("version_id", sa.Integer(), nullable=False),
        sa.Column("beyond_code", sa.String(length=6), nullable=False),
        sa.Column("status", sa.String(length=10), nullable=False),
        sa.Column("base_cad", sa.Numeric(precision=8, scale=2), nullable=True),
        sa.Column("per_lb_cad", sa.Numeric(precision=8, scale=2), nullable=True),
        sa.Column("source_sheet", sa.String(length=60), nullable=True),
        sa.Column("source_cell", sa.String(length=12), nullable=True),
        sa.ForeignKeyConstraint(
            ["version_id"],
            ["tariff_versions.id"],
            name=op.f("fk_tariff_beyond_rates_version_id_tariff_versions"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tariff_beyond_rates")),
        sa.UniqueConstraint(
            "version_id", "beyond_code", name="uq_tariff_beyond_rates_version_id_beyond_code"
        ),
    )
    op.create_table(
        "tariff_products",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("version_id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(length=40), nullable=False),
        sa.Column("origin", sa.String(length=3), nullable=False),
        sa.Column("mode", sa.String(length=10), nullable=False),
        sa.Column("last_mile", sa.String(length=30), nullable=False),
        sa.Column("dim_divisor", sa.Integer(), nullable=False),
        sa.Column("per_kg_from_kg", sa.Numeric(precision=7, scale=2), nullable=True),
        sa.Column("piece_min_weight_kg", sa.Numeric(precision=7, scale=2), nullable=True),
        sa.Column("piece_min_fee_vnd", sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column("piece_min_applies_above_kg", sa.Numeric(precision=7, scale=2), nullable=True),
        sa.Column("min_chargeable_kg", sa.Numeric(precision=7, scale=2), nullable=True),
        sa.Column("customs_surcharges_waived", sa.Boolean(), nullable=False),
        sa.Column("transit_text", sa.String(length=200), nullable=True),
        sa.Column("source_sheet", sa.String(length=60), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["version_id"],
            ["tariff_versions.id"],
            name=op.f("fk_tariff_products_version_id_tariff_versions"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tariff_products")),
        sa.UniqueConstraint(
            "version_id", "origin", "code", name="uq_tariff_products_version_id_origin_code"
        ),
    )
    with op.batch_alter_table("tariff_products", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_tariff_products_created_at"), ["created_at"], unique=False
        )

    op.create_table(
        "tariff_surcharge_rules",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("version_id", sa.Integer(), nullable=False),
        sa.Column("section", sa.String(length=20), nullable=False),
        sa.Column("section_label", sa.String(length=200), nullable=False),
        sa.Column("stt", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=300), nullable=False),
        sa.Column("raw_price_text", sa.String(length=200), nullable=False),
        sa.Column("raw_note", sa.Text(), nullable=True),
        sa.Column("basis", sa.String(length=20), nullable=False),
        sa.Column("scope", sa.String(length=20), nullable=False),
        sa.Column("pricing_status", sa.String(length=30), nullable=False),
        sa.Column("unit_price_vnd", sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column("per_unit_price_vnd", sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column("per_unit_label", sa.String(length=20), nullable=True),
        sa.Column("min_charge_kg", sa.Numeric(precision=7, scale=2), nullable=True),
        sa.Column("max_kg_per_shipment", sa.Numeric(precision=7, scale=2), nullable=True),
        sa.Column("applies_to_canada", sa.Boolean(), nullable=False),
        sa.Column("semantics_source", sa.String(length=10), nullable=False),
        sa.Column("semantics_note", sa.String(length=500), nullable=True),
        sa.Column("source_sheet", sa.String(length=60), nullable=False),
        sa.Column("source_row", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["version_id"],
            ["tariff_versions.id"],
            name=op.f("fk_tariff_surcharge_rules_version_id_tariff_versions"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tariff_surcharge_rules")),
        sa.UniqueConstraint(
            "version_id", "section", "stt", name="uq_tariff_surcharge_rules_version_id_section_stt"
        ),
    )
    with op.batch_alter_table("tariff_surcharge_rules", schema=None) as batch_op:
        batch_op.create_index(
            "ix_tariff_surcharge_rules_version_id_section", ["version_id", "section"], unique=False
        )

    op.create_table(
        "tariff_zone_fsas",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("version_id", sa.Integer(), nullable=False),
        sa.Column("fsa", sa.String(length=3), nullable=False),
        sa.Column("province", sa.String(length=2), nullable=True),
        sa.Column("ground_zone", sa.Integer(), nullable=False),
        sa.Column("express_zone", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["version_id"],
            ["tariff_versions.id"],
            name=op.f("fk_tariff_zone_fsas_version_id_tariff_versions"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tariff_zone_fsas")),
        sa.UniqueConstraint("version_id", "fsa", name="uq_tariff_zone_fsas_version_id_fsa"),
    )
    op.create_table(
        "tariff_rate_brackets",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=10), nullable=False),
        sa.Column("zone", sa.Integer(), nullable=False),
        sa.Column("label", sa.String(length=20), nullable=False),
        sa.Column("weight_from_kg", sa.Numeric(precision=7, scale=2), nullable=True),
        sa.Column("weight_to_kg", sa.Numeric(precision=7, scale=2), nullable=True),
        sa.Column("price_vnd", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("source_sheet", sa.String(length=60), nullable=False),
        sa.Column("source_cell", sa.String(length=12), nullable=False),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["tariff_products.id"],
            name=op.f("fk_tariff_rate_brackets_product_id_tariff_products"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tariff_rate_brackets")),
    )
    with op.batch_alter_table("tariff_rate_brackets", schema=None) as batch_op:
        batch_op.create_index(
            "ix_tariff_rate_brackets_product_id_kind_zone",
            ["product_id", "kind", "zone"],
            unique=False,
        )

    op.create_table(
        "tariff_surcharge_rule_tiers",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("rule_id", sa.Integer(), nullable=False),
        sa.Column("weight_from_kg", sa.Numeric(precision=7, scale=2), nullable=False),
        sa.Column("weight_to_kg", sa.Numeric(precision=7, scale=2), nullable=True),
        sa.Column("price_vnd", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.ForeignKeyConstraint(
            ["rule_id"],
            ["tariff_surcharge_rules.id"],
            name=op.f("fk_tariff_surcharge_rule_tiers_rule_id_tariff_surcharge_rules"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tariff_surcharge_rule_tiers")),
    )
    with op.batch_alter_table("tariff_surcharge_rule_tiers", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_tariff_surcharge_rule_tiers_rule_id"), ["rule_id"], unique=False
        )


def downgrade() -> None:
    with op.batch_alter_table("tariff_surcharge_rule_tiers", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_tariff_surcharge_rule_tiers_rule_id"))

    op.drop_table("tariff_surcharge_rule_tiers")
    with op.batch_alter_table("tariff_rate_brackets", schema=None) as batch_op:
        batch_op.drop_index("ix_tariff_rate_brackets_product_id_kind_zone")

    op.drop_table("tariff_rate_brackets")
    op.drop_table("tariff_zone_fsas")
    with op.batch_alter_table("tariff_surcharge_rules", schema=None) as batch_op:
        batch_op.drop_index("ix_tariff_surcharge_rules_version_id_section")

    op.drop_table("tariff_surcharge_rules")
    with op.batch_alter_table("tariff_products", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_tariff_products_created_at"))

    op.drop_table("tariff_products")
    op.drop_table("tariff_beyond_rates")
    op.drop_table("tariff_beyond_postal_codes")
    op.drop_table("tariff_accessorials")
    with op.batch_alter_table("tariff_versions", schema=None) as batch_op:
        batch_op.drop_index("ix_tariff_versions_vendor_id_status")
        batch_op.drop_index(batch_op.f("ix_tariff_versions_created_at"))

    op.drop_table("tariff_versions")
    with op.batch_alter_table("fx_sync_attempts", schema=None) as batch_op:
        batch_op.drop_index("ix_fx_sync_attempts_bank_attempted_at")

    op.drop_table("fx_sync_attempts")
    with op.batch_alter_table("vendors", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_vendors_created_at"))

    op.drop_table("vendors")
    with op.batch_alter_table("fx_rate_snapshots", schema=None) as batch_op:
        batch_op.drop_index("ix_fx_rate_snapshots_bank_currency_retrieved_at")

    op.drop_table("fx_rate_snapshots")
