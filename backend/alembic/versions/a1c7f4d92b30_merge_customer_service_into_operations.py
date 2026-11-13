"""Merge the Customer service role into Operations, reversibly.

The two roles were never independent. ``Operations`` held twelve permissions, every one of
which ``Customer service`` also held, so the Operations set was a strict subset and no
staff member could do anything as Operations that Customer service could not. Merging them
therefore invents no permission: the surviving ``operations`` role carries the former
Customer service set unchanged, and ``financial_cost:read`` stays out of it, Admin's alone.

**The role each affected account holds widens.** A user who was ``customer_service``
already held these permissions and keeps them. A user who was ``operations`` before this
migration ran now holds seventeen more, including ``financial:read``, ``financial:write``,
``shipment:cancel``, ``consent:write``, ``duplicate:review`` and the segment permissions.
That widening is the decision this migration implements (DEC-0088), not a side effect of
it.

**Why a provenance table.** Once both roles are the single value ``operations``, the column
no longer records which accounts were which. A downgrade that sent every ``operations`` row
back to ``customer_service`` would hand former Operations staff a role they never had; one
that left them all alone would silently strip seventeen permissions from former Customer
service staff. Neither is a rollback. So the upgrade writes down, *before* it changes a
single row, the role each affected account held, and the downgrade reads that back. The
table is owned by this migration: no ORM model maps it, nothing in the application reads
it, and the downgrade deletes only the rows it wrote.

**What the table holds, and what it must never hold.** A user id, the previous role, the
migration that recorded it, and when. No password hash, no session token, no email, no
name, no profile field. A rollback needs a role and an id; anything more would be a second
copy of the staff table sitting outside the access controls that protect the first one.

**The contract for accounts created after the upgrade.** They have no provenance row,
because they never had a pre-merge role -- they were created into a world where Operations
is the merged role. The downgrade leaves them ``operations``. This is deliberate and is the
only safe rule: the alternative is to invent a pre-merge role for an account that never had
one. An operator who downgrades gets a count of exactly this case so the situation is
visible rather than inferred.

**Interruption.** Capture and remap happen in one transaction. Alembic runs a SQLite
migration inside one, so a process killed midway either wrote both or neither; there is no
state in which some rows are remapped and the provenance for them is missing.

Revision ID: a1c7f4d92b30
Revises: e5623fcf8018
Create Date: 2026-09-19
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa

from alembic import op

revision: str = "a1c7f4d92b30"
down_revision: str | Sequence[str] | None = "e5623fcf8018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: The table this migration owns. Deliberately not mapped by any model in ``app.models``:
#: it is migration bookkeeping, not application data, and nothing in the running
#: application may read or write it.
PROVENANCE_TABLE = "role_merge_provenance"

#: Roles whose rows this migration is allowed to touch. Marketing, Admin and the read-only
#: manager are outside the merge entirely and are neither captured nor remapped.
AFFECTED_ROLES = ("customer_service", "operations")


def _utcnow() -> datetime:
    """Naive UTC, matching how every other timestamp in this database is stored.

    Deliberately not imported from ``app.core.time_utils``: a migration has to keep
    running against a tree whose application code has moved on, so it carries its own
    two-line copy rather than a dependency on a module that may be refactored.
    """
    return datetime.now(UTC).replace(tzinfo=None)


def upgrade() -> None:
    op.create_table(
        PROVENANCE_TABLE,
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("previous_role", sa.String(length=40), nullable=False),
        sa.Column("migration_id", sa.String(length=32), nullable=False),
        sa.Column("recorded_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f(f"fk_{PROVENANCE_TABLE}_user_id_users"),
            # The row exists to restore a user. If the user is deleted the row has nothing
            # left to restore, and keeping it would leave a dangling reference that
            # ``PRAGMA foreign_key_check`` would report.
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{PROVENANCE_TABLE}")),
        # One record per user per migration. This is what makes a repeated
        # upgrade/downgrade cycle deterministic instead of accumulating a second opinion
        # about the same account on every pass.
        sa.UniqueConstraint(
            "migration_id", "user_id", name=f"uq_{PROVENANCE_TABLE}_migration_id_user_id"
        ),
    )

    connection = op.get_bind()

    # Capture first, remap second. Reversing the order would mean reading the roles back
    # out of a column that had already been overwritten.
    captured = connection.execute(
        sa.text(
            f"""
            INSERT INTO {PROVENANCE_TABLE} (user_id, previous_role, migration_id, recorded_at)
            SELECT id, role, :migration_id, :recorded_at
            FROM users
            WHERE role IN :affected_roles
            """
        ).bindparams(sa.bindparam("affected_roles", expanding=True)),
        {
            "migration_id": revision,
            "recorded_at": _utcnow(),
            "affected_roles": list(AFFECTED_ROLES),
        },
    ).rowcount

    remapped = connection.execute(
        sa.text("UPDATE users SET role = 'operations' WHERE role = 'customer_service'")
    ).rowcount

    print(
        f"  captured pre-merge role for {captured} account(s); "
        f"remapped {remapped} customer_service account(s) to operations"
    )


def downgrade() -> None:
    connection = op.get_bind()

    # Restore each account to the exact role its provenance row records. Accounts with no
    # provenance row -- anything created after the upgrade, and every Admin, Marketing and
    # read-only manager account -- are not touched at all.
    restored = connection.execute(
        sa.text(
            f"""
            UPDATE users
            SET role = (
                SELECT p.previous_role
                FROM {PROVENANCE_TABLE} p
                WHERE p.user_id = users.id AND p.migration_id = :migration_id
            )
            WHERE EXISTS (
                SELECT 1
                FROM {PROVENANCE_TABLE} p
                WHERE p.user_id = users.id AND p.migration_id = :migration_id
            )
            """
        ),
        {"migration_id": revision},
    ).rowcount

    # Everything still holding the merged role that this migration never recorded. Reported
    # rather than guessed at: these are accounts created after the upgrade, and the
    # contract is that they stay Operations.
    created_after = connection.execute(
        sa.text(
            f"""
            SELECT COUNT(*) FROM users
            WHERE role = 'operations'
              AND id NOT IN (
                  SELECT user_id FROM {PROVENANCE_TABLE} WHERE migration_id = :migration_id
              )
            """
        ),
        {"migration_id": revision},
    ).scalar_one()

    # Remove only this migration's rows, and only now that the restore above has succeeded.
    connection.execute(
        sa.text(f"DELETE FROM {PROVENANCE_TABLE} WHERE migration_id = :migration_id"),
        {"migration_id": revision},
    )

    # Drop the table only if no other migration has left rows in it. Owning the table is
    # not the same as owning every row that might one day be in it.
    leftover = connection.execute(sa.text(f"SELECT COUNT(*) FROM {PROVENANCE_TABLE}")).scalar_one()
    if leftover == 0:
        op.drop_table(PROVENANCE_TABLE)

    print(
        f"  restored {restored} account(s) to their pre-merge role; "
        f"{created_after} account(s) created after the upgrade keep 'operations'"
    )
