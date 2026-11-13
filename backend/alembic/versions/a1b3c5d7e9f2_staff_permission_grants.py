"""Per-account permission grants: ``tariff:approve`` (owner, 2026-11-04; DEC-0268).

Revision ID: a1b3c5d7e9f2
Revises: f8b0d2e4a6c8
Create Date: 2026-11-04

One new table, ``staff_permission_grants`` (nothing altered, DEC-0181). Data: the owner
(2026-11-04) asked for the grant to be seeded **only for Ben**, the current approver; anyone
else (Louis T included) is added later by an Admin on Settings → Kango rate sheets or with
``scripts/grant_tariff_approver.py``. No other address is seeded or hard-coded.
Authorisation reads the grants from now on, not the addresses.
**Downgrade** drops the table.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

import sqlalchemy as sa

from alembic import op

revision: str = "a1b3c5d7e9f2"
down_revision: str | None = "f8b0d2e4a6c8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: ``app.models.tariff_intake.DEFAULT_APPROVER_EMAILS``, kept literal.
DEFAULT_APPROVERS = ("benjamin.le@soleiltransportation.com",)


def upgrade() -> None:
    op.create_table(
        "staff_permission_grants",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("permission", sa.String(60), nullable=False),
        sa.Column("granted_at", sa.DateTime(), nullable=False),
        sa.Column("granted_by_user_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"],
            name=op.f("fk_staff_permission_grants_user_id_users"), ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["granted_by_user_id"], ["users.id"],
            name=op.f("fk_staff_permission_grants_granted_by_user_id_users"), ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_staff_permission_grants")),
        sa.UniqueConstraint(
            "user_id", "permission", name=op.f("uq_staff_permission_grants_user_id_permission")
        ),
    )  # fmt: skip
    op.create_index(
        op.f("ix_staff_permission_grants_user_id"), "staff_permission_grants", ["user_id"]
    )
    bind = op.get_bind()
    emails = DEFAULT_APPROVERS
    now = datetime.utcnow()
    for email in emails:
        user = bind.execute(
            sa.text("SELECT id FROM users WHERE lower(email) = :e AND is_active"),
            {"e": str(email).strip().lower()},
        ).fetchone()
        if user is not None:
            bind.execute(
                sa.text(
                    "INSERT INTO staff_permission_grants (user_id, permission, granted_at) "
                    "VALUES (:u, 'tariff:approve', :t)"
                ),
                {"u": user[0], "t": now},
            )


def downgrade() -> None:
    op.drop_index(op.f("ix_staff_permission_grants_user_id"), table_name="staff_permission_grants")
    op.drop_table("staff_permission_grants")
