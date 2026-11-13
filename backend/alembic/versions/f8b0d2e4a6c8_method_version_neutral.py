"""The method switch value becomes version-neutral: ``confirmed`` (owner, 2026-11-04; DEC-0267).

Revision ID: f8b0d2e4a6c8
Revises: e6a8c0e2b4d6
Create Date: 2026-11-04

Data only: ``pricing_method_settings.pricing_method`` ``v0_5`` / ``v0_6`` / ``v0_7`` →
``confirmed``. The method document version is recorded on each estimate instead
(``method_version``). Finalised quote snapshots are frozen and are not rewritten: a snapshot
taken before this revision keeps ``"method": "v0_5" / "v0_6" / "v0_7"`` and its detail under
``"v05"``; readers accept both (``pricing_service.snapshot_method_detail``).
**Downgrade** sets ``confirmed`` back to ``v0_7``.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "f8b0d2e4a6c8"
down_revision: str | None = "e6a8c0e2b4d6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "UPDATE pricing_method_settings SET pricing_method = 'confirmed' "
        "WHERE pricing_method IN ('v0_5', 'v0_6', 'v0_7')"
    )


def downgrade() -> None:
    op.execute(
        "UPDATE pricing_method_settings SET pricing_method = 'v0_7' "
        "WHERE pricing_method = 'confirmed'"
    )
