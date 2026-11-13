"""Owner answers of 2026-10-23 (RC-UAT-20): GST/HST by route, costume jewellery customer price.

Revision ID: f7c2d9e3a1b5
Revises: e6b1c4a8d2f3
Create Date: 2026-10-23

Three new tables; nothing existing is altered (DEC-0181).

* ``tax_rates`` -- the GST/HST rate per Canadian province or territory, seeded here (DEC-0227):
  ON 13 % HST; NS 14 % HST; NB, NL, PE 15 % HST; AB, BC, MB, QC, SK, NT, NU, YT 5 % GST.
  A domestic shipment's draft invoice auto-fills its destination province's rate, included in
  the price; an international shipment is zero-rated. Admin edits the rows on Settings.
* ``invoice_draft_tax_route`` -- what a draft invoice's GST/HST was auto-filled from (route
  band, countries, destination province, suggested rate and mode), and whether staff must
  choose the rate because a domestic shipment's province is unknown.
* ``fee_line_manual_prices`` -- the customer price (CAD) staff enter for a ``manual_amount``
  fee line (costume jewellery, DEC-0228); the vendor's VND cost stays in
  ``shipment_fee_lines.manual_unit_price_vnd``.

**Downgrade** drops the three tables: drafts then read without a route (the rate saved on the
draft stands), the province rates fall back to the code's defaults, and a costume-jewellery
line loses its customer price (finalising is blocked again until it is re-entered).
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

import sqlalchemy as sa

from alembic import op

revision: str = "f7c2d9e3a1b5"
down_revision: str | None = "e6b1c4a8d2f3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Seeded rates (owner, 2026-10-23). Kept literally here: a migration never imports app code.
SEED_RATES = (
    ("ON", 13, "HST"),
    ("NS", 14, "HST"),
    ("NB", 15, "HST"),
    ("NL", 15, "HST"),
    ("PE", 15, "HST"),
    ("AB", 5, "GST"),
    ("BC", 5, "GST"),
    ("MB", 5, "GST"),
    ("QC", 5, "GST"),
    ("SK", 5, "GST"),
    ("NT", 5, "GST"),
    ("NU", 5, "GST"),
    ("YT", 5, "GST"),
)
SEEDED_AT = datetime(2026, 10, 23)


def upgrade() -> None:
    tax_rates = op.create_table(
        "tax_rates",
        sa.Column("province_code", sa.String(length=2), nullable=False),
        sa.Column("rate_percent", sa.Integer(), nullable=False),
        sa.Column("tax_label", sa.String(length=10), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("updated_by_user_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["updated_by_user_id"],
            ["users.id"],
            name=op.f("fk_tax_rates_updated_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("province_code", name=op.f("pk_tax_rates")),
    )
    op.bulk_insert(
        tax_rates,
        [
            {
                "province_code": code,
                "rate_percent": rate,
                "tax_label": label,
                "updated_at": SEEDED_AT,
                "updated_by_user_id": None,
            }
            for code, rate, label in SEED_RATES
        ],
    )
    op.create_table(
        "invoice_draft_tax_route",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("draft_id", sa.Integer(), nullable=False),
        sa.Column("route_band", sa.String(length=16), nullable=False),
        sa.Column("origin_country_code", sa.String(length=2), nullable=True),
        sa.Column("destination_country_code", sa.String(length=2), nullable=True),
        sa.Column("destination_province", sa.String(length=2), nullable=True),
        sa.Column("suggested_rate_percent", sa.Integer(), nullable=True),
        sa.Column("suggested_mode", sa.String(length=10), nullable=False),
        sa.Column("rate_required", sa.Boolean(), nullable=False),
        sa.Column("rate_chosen_at", sa.DateTime(), nullable=True),
        sa.Column("rate_chosen_by_user_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["draft_id"],
            ["invoice_drafts.id"],
            name=op.f("fk_invoice_draft_tax_route_draft_id_invoice_drafts"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["rate_chosen_by_user_id"],
            ["users.id"],
            name=op.f("fk_invoice_draft_tax_route_rate_chosen_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_invoice_draft_tax_route")),
        sa.UniqueConstraint("draft_id", name=op.f("uq_invoice_draft_tax_route_draft_id")),
    )
    op.create_table(
        "fee_line_manual_prices",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("fee_line_id", sa.Integer(), nullable=False),
        sa.Column("customer_price_cad", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("updated_by_user_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["fee_line_id"],
            ["shipment_fee_lines.id"],
            name=op.f("fk_fee_line_manual_prices_fee_line_id_shipment_fee_lines"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["updated_by_user_id"],
            ["users.id"],
            name=op.f("fk_fee_line_manual_prices_updated_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_fee_line_manual_prices")),
        sa.UniqueConstraint("fee_line_id", name=op.f("uq_fee_line_manual_prices_fee_line_id")),
    )


def downgrade() -> None:
    op.drop_table("fee_line_manual_prices")
    op.drop_table("invoice_draft_tax_route")
    op.drop_table("tax_rates")
