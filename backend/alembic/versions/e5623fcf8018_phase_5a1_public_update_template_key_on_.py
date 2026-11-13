"""Phase 5A1: public update template key on shipment events.

A public milestone used to be one typed sentence, which meant a customer reading the
tracking page in Vietnamese got whatever language the staff member was working in. The
event now stores an approved *template key* instead, and each surface renders that key in
its reader's language.

Additive and reversible. Existing events keep their ``public_update_text`` untouched and
continue to render exactly as before — the column is nullable with no default and no
backfill, because guessing which template an already-typed sentence corresponds to would
put words in a customer's mouth.

Revision ID: e5623fcf8018
Revises: c4a1f27b93de
Create Date: 2026-09-13
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "e5623fcf8018"
down_revision: str | Sequence[str] | None = "c4a1f27b93de"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "shipment_events",
        sa.Column("public_update_template_key", sa.String(length=80), nullable=True),
    )


def downgrade() -> None:
    # Dropping the column discards the template choice on any event recorded since the
    # upgrade. Those events keep their flag and their occurred time, so the milestone
    # itself survives; only the approved wording is lost, and the tracking page falls back
    # to showing no message for them. That is the honest outcome of a downgrade, and it is
    # why nothing backfills text into the old column on the way down: inventing a sentence
    # attributed to Solaris would be worse than an empty one.
    op.drop_column("shipment_events", "public_update_template_key")
