"""RC-UAT-21 Phase B: password change, email change, account reinstatement.

Revision ID: b2d4f6a8c1e3
Revises: a1c3e5f7b9d2
Create Date: 2026-10-24

Two new tables, nothing existing altered (DEC-0181, DEC-0231):

* ``customer_email_change_requests`` -- a signed-in customer's request to move their sign-in
  email; the proving token is an ordinary ``customer_auth_tokens`` row (purpose
  ``email_change``), so no token column is added anywhere.
* ``customer_account_reinstatements`` -- an Admin returned a deactivated account to use; the
  history of the deactivation it reversed.

Password change (customer and staff) needs no table: it writes the existing hash columns and
audit rows.

**Downgrade** drops both tables. Outstanding ``email_change`` tokens stay in
``customer_auth_tokens`` and simply can no longer be redeemed.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b2d4f6a8c1e3"
down_revision: str | None = "a1c3e5f7b9d2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "customer_email_change_requests",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("identity_id", sa.Integer(), nullable=False),
        sa.Column("token_id", sa.Integer(), nullable=True),
        sa.Column("new_email_entered", sa.String(length=320), nullable=False),
        sa.Column("new_email_normalized", sa.String(length=320), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("refused_reason_code", sa.String(length=40), nullable=True),
        sa.Column("requested_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("closed_at", sa.DateTime(), nullable=True),
        sa.Column("request_ip", sa.String(length=64), nullable=True),
        sa.ForeignKeyConstraint(
            ["identity_id"],
            ["customer_identities.id"],
            name=op.f("fk_customer_email_change_requests_identity_id_customer_identities"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["token_id"],
            ["customer_auth_tokens.id"],
            name=op.f("fk_customer_email_change_requests_token_id_customer_auth_tokens"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_customer_email_change_requests")),
    )
    op.create_index(
        "ix_customer_email_change_requests_identity_status",
        "customer_email_change_requests",
        ["identity_id", "status"],
        unique=False,
    )
    op.create_table(
        "customer_account_reinstatements",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("identity_id", sa.Integer(), nullable=False),
        sa.Column("deactivated_at", sa.DateTime(), nullable=True),
        sa.Column("deactivated_by_user_id", sa.Integer(), nullable=True),
        sa.Column("deactivation_reason_code", sa.String(length=40), nullable=True),
        sa.Column("restored_status", sa.String(length=30), nullable=False),
        sa.Column("reason_code", sa.String(length=40), nullable=False),
        sa.Column("note", sa.String(length=500), nullable=True),
        sa.Column("reinstated_at", sa.DateTime(), nullable=False),
        sa.Column("reinstated_by_user_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["identity_id"],
            ["customer_identities.id"],
            name=op.f("fk_customer_account_reinstatements_identity_id_customer_identities"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["deactivated_by_user_id"],
            ["users.id"],
            name=op.f("fk_customer_account_reinstatements_deactivated_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["reinstated_by_user_id"],
            ["users.id"],
            name=op.f("fk_customer_account_reinstatements_reinstated_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_customer_account_reinstatements")),
    )
    op.create_index(
        op.f("ix_customer_account_reinstatements_identity_id"),
        "customer_account_reinstatements",
        ["identity_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_customer_account_reinstatements_identity_id"),
        table_name="customer_account_reinstatements",
    )
    op.drop_table("customer_account_reinstatements")
    op.drop_index(
        "ix_customer_email_change_requests_identity_status",
        table_name="customer_email_change_requests",
    )
    op.drop_table("customer_email_change_requests")
