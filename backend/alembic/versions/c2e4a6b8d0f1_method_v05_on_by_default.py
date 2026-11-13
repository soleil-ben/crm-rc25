"""Method v0.5 becomes the default pricing method (owner, 2026-11-03; DEC-0252).

Revision ID: c2e4a6b8d0f1
Revises: b8d1f3a5c7e9
Create Date: 2026-11-03

Data only: the ``pricing_method_settings`` row is set to ``v0_5``. No table or column changes.
**Downgrade** sets it back to ``rc25``.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "c2e4a6b8d0f1"
down_revision: str | None = "b8d1f3a5c7e9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("UPDATE pricing_method_settings SET pricing_method = 'v0_5'")


def downgrade() -> None:
    op.execute("UPDATE pricing_method_settings SET pricing_method = 'rc25'")
