"""Customer public identifiers: ``CUS-`` becomes ``STCA-``, former identifiers kept as aliases.

Revision ID: a7c3e1d9b2f4
Revises: f53efaa7773e
Create Date: 2026-10-19

A data migration. **No table, column, index or constraint changes.** It does two things, in
one transaction:

1. For every customer whose ``public_id`` starts with ``CUS-``, inserts a
   ``customer_id_aliases`` row holding the former identifier (``reason =
   'prefix_change_2026_10_19'``), unless an alias with that value already exists.
2. Rewrites that ``public_id`` to ``STCA-`` plus the same digits.

The alias is what keeps the promise CRM.md section 6 makes about identifiers: a former
``CUS-000001`` typed into any lookup still resolves, through the same path a merged
customer's former identifier does (``customer_service.get_customer_by_public_id``). The
counter is untouched, so the next customer continues the sequence under the new prefix.

**Why a rename rather than two prefixes.** OD-42 (DEC-0174) was taken while no production
customer exists. Two live formats would have been the lasting cost of a decision that is
cheap exactly once.

**What is not rewritten.** Aliases created by merges; audit rows whose summary quotes a
former identifier (history); the Customer Account identity prefix ``CA-``; shipment IDs.

**Downgrade** reverses both steps from the alias rows this revision wrote: each customer whose
alias carries this revision's reason gets that alias value back as its ``public_id``, and
those alias rows are deleted. Aliases from merges are left alone, as are customers created
under ``STCA-`` after this revision with no such alias (they keep their identifier; the
former code resolves it like any other string).
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa

from alembic import op

revision: str = "a7c3e1d9b2f4"
down_revision: str | None = "f53efaa7773e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_PREFIX = "CUS-"
NEW_PREFIX = "STCA-"
REASON = "prefix_change_2026_10_19"


def upgrade() -> None:
    bind = op.get_bind()
    now = datetime.now(UTC).replace(tzinfo=None)
    rows = bind.execute(
        sa.text("SELECT id, public_id FROM customers WHERE public_id LIKE :pattern"),
        {"pattern": f"{OLD_PREFIX}%"},
    ).fetchall()
    renamed = 0
    for customer_id, old_id in rows:
        new_id = NEW_PREFIX + old_id[len(OLD_PREFIX) :]
        exists = bind.execute(
            sa.text("SELECT 1 FROM customer_id_aliases WHERE alias_public_id = :alias"),
            {"alias": old_id},
        ).fetchone()
        if exists is None:
            bind.execute(
                sa.text(
                    "INSERT INTO customer_id_aliases (customer_id, alias_public_id, created_at, reason) "
                    "VALUES (:customer_id, :alias, :created_at, :reason)"
                ),
                {"customer_id": customer_id, "alias": old_id, "created_at": now, "reason": REASON},
            )
        bind.execute(
            sa.text("UPDATE customers SET public_id = :new_id WHERE id = :customer_id"),
            {"new_id": new_id, "customer_id": customer_id},
        )
        renamed += 1
    print(f"  renamed {renamed} customer identifier(s) from {OLD_PREFIX} to {NEW_PREFIX}")


def downgrade() -> None:
    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            "SELECT id, customer_id, alias_public_id FROM customer_id_aliases WHERE reason = :reason"
        ),
        {"reason": REASON},
    ).fetchall()
    for alias_id, customer_id, former_id in rows:
        bind.execute(
            sa.text("UPDATE customers SET public_id = :former WHERE id = :customer_id"),
            {"former": former_id, "customer_id": customer_id},
        )
        bind.execute(sa.text("DELETE FROM customer_id_aliases WHERE id = :id"), {"id": alias_id})
    print(f"  restored {len(rows)} customer identifier(s) to {OLD_PREFIX}")
