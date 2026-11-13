"""RC-UAT-24: the legal entity is Solaris Express Inc. (owner Ben, 2026-10-24; DEC-0236).

Revision ID: e7a9c1d3f5b6
Revises: d4f6b8c0e2a5
Create Date: 2026-10-24

Data only; no table or column is added or altered (DEC-0181). ``organization_settings`` rows
created before RC-UAT-24 took the old model default "Soleil Global Transportation Inc." as their
legal-entity name; the Settings screen shows it read-only, so nobody could correct it. A row still
holding **exactly** that old default becomes "Solaris Express Inc.", matching the invoices
(DEC-0235). A row holding anything else was set on purpose and is left alone.

**Downgrade** puts the old default back on rows holding exactly the new name.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "e7a9c1d3f5b6"
down_revision: str | None = "d4f6b8c0e2a5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD = "Soleil Global Transportation Inc."
NEW = "Solaris Express Inc."


def _rename(source: str, target: str) -> None:
    op.execute(
        sa.text(
            "UPDATE organization_settings SET legal_entity_name = :target "
            "WHERE legal_entity_name = :source"
        ).bindparams(source=source, target=target)
    )


def upgrade() -> None:
    _rename(OLD, NEW)


def downgrade() -> None:
    _rename(NEW, OLD)
