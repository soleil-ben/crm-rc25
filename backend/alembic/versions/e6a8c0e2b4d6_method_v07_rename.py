"""Method v0.7 (Louis, 2026-11-03 PM; DEC-0260..0264): the method switch value becomes ``v0_7``.

Revision ID: e6a8c0e2b4d6
Revises: d4f6a8c0e2b4
Create Date: 2026-11-03

Data only: ``pricing_method_settings.pricing_method`` ``v0_6`` → ``v0_7``. No table or column
changes (the v0.7 sea minimum, the packed-as-one-box scope and the rate-sheet rollback need
none). **Downgrade** sets ``v0_7`` back to ``v0_6``.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "e6a8c0e2b4d6"
down_revision: str | None = "d4f6a8c0e2b4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "UPDATE pricing_method_settings SET pricing_method = 'v0_7' WHERE pricing_method = 'v0_6'"
    )


def downgrade() -> None:
    op.execute(
        "UPDATE pricing_method_settings SET pricing_method = 'v0_6' WHERE pricing_method = 'v0_7'"
    )
