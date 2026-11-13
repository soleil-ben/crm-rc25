"""RC-UAT-22: staff re-link or close of an orphaned Customer Account (B-13).

Revision ID: d4f6b8c0e2a5
Revises: c3e5a7b9d2f4
Create Date: 2026-10-24

One new table; nothing existing is altered (DEC-0181, DEC-0234 draft):

* ``customer_account_relinks`` -- an Admin re-linked an orphaned account (approved once, no
  active link, no pending proposal) to a customer, or closed it. The new link itself is an
  ordinary ``customer_identity_links`` row and the closure an ordinary deactivation; this
  table keeps what neither holds: the account's last link, the Admin's bounded reason and
  note, and the history figures acknowledged before a re-link.

**Downgrade** drops the table. Links written and accounts closed through it stay as they are
(they are ordinary rows); only the record of why is lost.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "d4f6b8c0e2a5"
down_revision: str | None = "c3e5a7b9d2f4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "customer_account_relinks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("identity_id", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(length=20), nullable=False),
        sa.Column("previous_customer_id", sa.Integer(), nullable=True),
        sa.Column("previous_link_end_reason", sa.String(length=40), nullable=True),
        sa.Column("target_customer_id", sa.Integer(), nullable=True),
        sa.Column("reason_code", sa.String(length=40), nullable=False),
        sa.Column("note", sa.String(length=500), nullable=True),
        sa.Column("disclosed_shipment_count", sa.Integer(), nullable=True),
        sa.Column("oldest_booked_at", sa.DateTime(), nullable=True),
        sa.Column("newest_booked_at", sa.DateTime(), nullable=True),
        sa.Column("includes_cancelled", sa.Boolean(), nullable=True),
        sa.Column("includes_rebooked", sa.Boolean(), nullable=True),
        sa.Column("disclosure_definition_version", sa.String(length=40), nullable=True),
        sa.Column("preview_fingerprint", sa.String(length=64), nullable=True),
        sa.Column("acted_at", sa.DateTime(), nullable=False),
        sa.Column("acted_by_user_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["identity_id"],
            ["customer_identities.id"],
            name=op.f("fk_customer_account_relinks_identity_id_customer_identities"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["previous_customer_id"],
            ["customers.id"],
            name=op.f("fk_customer_account_relinks_previous_customer_id_customers"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["target_customer_id"],
            ["customers.id"],
            name=op.f("fk_customer_account_relinks_target_customer_id_customers"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["acted_by_user_id"],
            ["users.id"],
            name=op.f("fk_customer_account_relinks_acted_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_customer_account_relinks")),
    )
    op.create_index(
        op.f("ix_customer_account_relinks_identity_id"),
        "customer_account_relinks",
        ["identity_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_customer_account_relinks_identity_id"), table_name="customer_account_relinks"
    )
    op.drop_table("customer_account_relinks")
