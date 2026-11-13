"""Owner answer of 2026-10-22: GST/HST on the draft invoice, its mode and its confirmation.

Revision ID: e6b1c4a8d2f3
Revises: d4f7a2c9e1b8
Create Date: 2026-10-22

One new table, ``invoice_draft_tax``: for a draft invoice, whether its GST/HST is
**included** in the line amounts (backed out of the all-in total) or **added** on top, the
rate as last saved (a mirror of ``invoice_drafts.tax_rate_percent``, which stays the rate's
source of truth), and the staff confirmation that the tax was checked -- valid for one saved
revision of the draft only. Nothing existing is altered (DEC-0181). A draft with no row is
read as mode ``added`` at its saved rate, unconfirmed.

**Downgrade** drops the table; a draft's mode and confirmation are lost and the older code
reads every draft as tax added on top (its only behaviour).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "e6b1c4a8d2f3"
down_revision: str | None = "d4f7a2c9e1b8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "invoice_draft_tax",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("draft_id", sa.Integer(), nullable=False),
        sa.Column("mode", sa.String(length=10), nullable=False),
        sa.Column("rate_percent", sa.Integer(), nullable=False),
        sa.Column("confirmed_revision", sa.Integer(), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(), nullable=True),
        sa.Column("confirmed_by_user_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["draft_id"],
            ["invoice_drafts.id"],
            name=op.f("fk_invoice_draft_tax_draft_id_invoice_drafts"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["confirmed_by_user_id"],
            ["users.id"],
            name=op.f("fk_invoice_draft_tax_confirmed_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_invoice_draft_tax")),
        sa.UniqueConstraint("draft_id", name=op.f("uq_invoice_draft_tax_draft_id")),
    )


def downgrade() -> None:
    op.drop_table("invoice_draft_tax")
