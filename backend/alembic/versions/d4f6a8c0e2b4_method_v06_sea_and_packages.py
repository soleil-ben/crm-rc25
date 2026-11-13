"""Cost and quote method v0.6 (Louis, 2026-11-03; DEC-0253..0258): sea vendor rate and sea
surcharges, package customer note, package membership; the method switch renamed ``v0_6``.

Revision ID: d4f6a8c0e2b4
Revises: c2e4a6b8d0f1
Create Date: 2026-11-03

Four new tables; nothing existing is altered (DEC-0181):

* ``sea_vendor_rates`` -- the sea vendor's cost per kg, effective-dated; seeded 60,000 VND/kg
  from 2026-11-03 (``sea_cost_vnd_per_kg``). Sea no longer uses the Kango sea sheet.
* ``sea_surcharge_rules`` -- the sea vendor's two surcharges, at cost, on item kg, with a
  minimum per package (kiện) per type: SEA-FOOD 30,000/kg min 400,000; SEA-FUNCFOOD
  40,000/kg min 500,000.
* ``consolidation_package_notes`` -- ``packages.customer_note`` (Louis Q7), optional text.
* ``consolidation_package_members`` -- which package of its master a customer shipment rides
  in (optional; used by per-package rules on a master with several packages).

Data: ``pricing_method_settings.pricing_method`` ``v0_5`` → ``v0_6``.

**Downgrade** drops the four tables and sets ``v0_6`` back to ``v0_5``.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date

import sqlalchemy as sa

from alembic import op

revision: str = "d4f6a8c0e2b4"
down_revision: str | None = "c2e4a6b8d0f1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SOURCE = "Louis 2026-11-03 (photo): sea vendor rate and surcharges"


def upgrade() -> None:
    rates = op.create_table(
        "sea_vendor_rates",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("sea_cost_vnd_per_kg", sa.Numeric(14, 2), nullable=False),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("source", sa.String(200), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sea_vendor_rates")),
        sa.UniqueConstraint("effective_from", name=op.f("uq_sea_vendor_rates_effective_from")),
    )
    rules = op.create_table(
        "sea_surcharge_rules",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(20), nullable=False),
        sa.Column("name_vi", sa.String(120), nullable=False),
        sa.Column("name_en", sa.String(120), nullable=False),
        sa.Column("rate_vnd_per_kg", sa.Numeric(14, 2), nullable=False),
        sa.Column("min_vnd_per_package", sa.Numeric(14, 2), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("source", sa.String(200), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sea_surcharge_rules")),
        sa.UniqueConstraint("code", name=op.f("uq_sea_surcharge_rules_code")),
    )
    for table in ("consolidation_package_notes", "consolidation_package_members"):
        extra = (
            [sa.Column("customer_note", sa.String(200), nullable=False)]
            if table == "consolidation_package_notes"
            else [
                sa.Column("shipment_id", sa.Integer(), nullable=False),
                sa.Column("carton_sequence", sa.Integer(), nullable=False),
            ]
        )
        unique = (
            ("consolidation_id", "carton_sequence")
            if table == "consolidation_package_notes"
            else ("consolidation_id", "shipment_id")
        )
        fks = [
            sa.ForeignKeyConstraint(
                ["consolidation_id"],
                ["consolidations.id"],
                name=op.f(f"fk_{table}_consolidation_id_consolidations"),
                ondelete="CASCADE",
            ),
            sa.ForeignKeyConstraint(
                ["set_by_user_id"],
                ["users.id"],
                name=op.f(f"fk_{table}_set_by_user_id_users"),
                ondelete="SET NULL",
            ),
        ]
        if table == "consolidation_package_members":
            fks.append(
                sa.ForeignKeyConstraint(
                    ["shipment_id"],
                    ["shipments.id"],
                    name=op.f(f"fk_{table}_shipment_id_shipments"),
                    ondelete="CASCADE",
                )
            )
        op.create_table(
            table,
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("consolidation_id", sa.Integer(), nullable=False),
            *(
                [sa.Column("carton_sequence", sa.Integer(), nullable=False)]
                if table == "consolidation_package_notes"
                else []
            ),
            *extra,
            sa.Column("set_at", sa.DateTime(), nullable=False),
            sa.Column("set_by_user_id", sa.Integer(), nullable=True),
            *fks,
            sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{table}")),
            sa.UniqueConstraint(*unique, name=op.f(f"uq_{table}_{'_'.join(unique)}")),
        )
        op.create_index(
            op.f(f"ix_{table}_consolidation_id"), table, ["consolidation_id"], unique=False
        )
    op.bulk_insert(
        rates,
        [{"id": 1, "sea_cost_vnd_per_kg": 60000, "effective_from": date(2026, 11, 3),
          "source": SOURCE}],
    )  # fmt: skip
    op.bulk_insert(
        rules,
        [
            {
                "id": 1,
                "code": "SEA-FOOD",
                "name_vi": "Hàng thực phẩm",
                "name_en": "Food",
                "rate_vnd_per_kg": 30000,
                "min_vnd_per_package": 400000,
                "is_active": True,
                "effective_from": date(2026, 11, 3),
                "source": SOURCE,
            },
            {
                "id": 2,
                "code": "SEA-FUNCFOOD",
                "name_vi": "Hàng thực phẩm chức năng",
                "name_en": "Functional food / supplements",
                "rate_vnd_per_kg": 40000,
                "min_vnd_per_package": 500000,
                "is_active": True,
                "effective_from": date(2026, 11, 3),
                "source": SOURCE,
            },
        ],
    )
    op.execute(
        "UPDATE pricing_method_settings SET pricing_method = 'v0_6' WHERE pricing_method = 'v0_5'"
    )


def downgrade() -> None:
    op.execute(
        "UPDATE pricing_method_settings SET pricing_method = 'v0_5' WHERE pricing_method = 'v0_6'"
    )
    for table in ("consolidation_package_members", "consolidation_package_notes"):
        op.drop_index(op.f(f"ix_{table}_consolidation_id"), table_name=table)
        op.drop_table(table)
    op.drop_table("sea_surcharge_rules")
    op.drop_table("sea_vendor_rates")
