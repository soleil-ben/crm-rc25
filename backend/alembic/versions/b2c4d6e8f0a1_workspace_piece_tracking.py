"""Workspace redesign: last-mile tracking per master piece (owner, 2026-11-04; DEC-0272).

Revision ID: b2c4d6e8f0a1
Revises: a1b3c5d7e9f2
Create Date: 2026-11-04

One new table, ``consolidation_piece_tracking`` (nothing altered, DEC-0181). No data.
**Downgrade** drops the table.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b2c4d6e8f0a1"
down_revision: str | None = "a1b3c5d7e9f2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "consolidation_piece_tracking",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("consolidation_id", sa.Integer(), nullable=False),
        sa.Column("carton_sequence", sa.Integer(), nullable=False),
        sa.Column("last_mile_tracking", sa.String(60), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("updated_by_user_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["consolidation_id"], ["consolidations.id"],
            name=op.f("fk_consolidation_piece_tracking_consolidation_id_consolidations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["updated_by_user_id"], ["users.id"],
            name=op.f("fk_consolidation_piece_tracking_updated_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_consolidation_piece_tracking")),
        sa.UniqueConstraint(
            "consolidation_id", "carton_sequence",
            name=op.f("uq_consolidation_piece_tracking_consolidation_id_carton_sequence"),
        ),
    )  # fmt: skip
    op.create_index(
        op.f("ix_consolidation_piece_tracking_consolidation_id"),
        "consolidation_piece_tracking",
        ["consolidation_id"],
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_consolidation_piece_tracking_consolidation_id"),
        table_name="consolidation_piece_tracking",
    )
    op.drop_table("consolidation_piece_tracking")
