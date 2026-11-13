"""Phase 13H: vendor rate-email intake (OD-76).

Revision ID: c5e8a1f3d7b9
Revises: b7d2e9a4c1f6
Create Date: 2026-10-20

Three new tables: ``tariff_intake_settings`` (one row, created when an administrator saves:
the approvers and the sender domains imported without review) and ``tariff_email_intakes``
(one row per rate email received: provenance, outcome, the draft version it produced, the
approver's review) and ``tariff_version_reviews`` (the approver's decision per version,
whatever its source). Nothing existing is altered (DEC-0181); a rejected draft stays
``draft`` in ``tariff_versions``.

**Downgrade** drops all three.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c5e8a1f3d7b9"
down_revision: str | None = "b7d2e9a4c1f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tariff_intake_settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("mailbox_address", sa.String(length=320), nullable=False),
        sa.Column("approver_emails", sa.JSON(), nullable=False),
        sa.Column("allowed_sender_domains", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("updated_by_user_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["updated_by_user_id"],
            ["users.id"],
            name=op.f("fk_tariff_intake_settings_updated_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tariff_intake_settings")),
    )
    op.create_table(
        "tariff_email_intakes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("message_id", sa.String(length=255), nullable=False),
        sa.Column("source_sha256", sa.String(length=64), nullable=True),
        sa.Column("stored_file", sa.String(length=255), nullable=True),
        sa.Column("sender", sa.String(length=320), nullable=True),
        sa.Column("subject", sa.String(length=300), nullable=True),
        sa.Column("received_at", sa.DateTime(), nullable=True),
        sa.Column("source", sa.String(length=10), nullable=False),
        sa.Column("attachment_name", sa.String(length=255), nullable=True),
        sa.Column("attachment_sha256", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("tariff_version_id", sa.Integer(), nullable=True),
        sa.Column("warning", sa.String(length=300), nullable=True),
        sa.Column("error", sa.String(length=500), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(), nullable=True),
        sa.Column("reviewed_by_user_id", sa.Integer(), nullable=True),
        sa.Column("review_note", sa.String(length=400), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["reviewed_by_user_id"],
            ["users.id"],
            name=op.f("fk_tariff_email_intakes_reviewed_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["tariff_version_id"],
            ["tariff_versions.id"],
            name=op.f("fk_tariff_email_intakes_tariff_version_id_tariff_versions"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tariff_email_intakes")),
        sa.UniqueConstraint(
            "message_id", "sender", name="uq_tariff_email_intakes_message_id_sender"
        ),
    )
    with op.batch_alter_table("tariff_email_intakes", schema=None) as batch_op:
        batch_op.create_index("ix_tariff_email_intakes_status", ["status"], unique=False)
        batch_op.create_index(
            "ix_tariff_email_intakes_source_sha256", ["source_sha256"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_tariff_email_intakes_tariff_version_id"),
            ["tariff_version_id"],
            unique=False,
        )
    op.create_table(
        "tariff_version_reviews",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tariff_version_id", sa.Integer(), nullable=False),
        sa.Column("decision", sa.String(length=10), nullable=False),
        sa.Column("reviewed_by_user_id", sa.Integer(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(), nullable=False),
        sa.Column("note", sa.String(length=400), nullable=True),
        sa.ForeignKeyConstraint(
            ["reviewed_by_user_id"],
            ["users.id"],
            name=op.f("fk_tariff_version_reviews_reviewed_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["tariff_version_id"],
            ["tariff_versions.id"],
            name=op.f("fk_tariff_version_reviews_tariff_version_id_tariff_versions"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tariff_version_reviews")),
        sa.UniqueConstraint(
            "tariff_version_id", name="uq_tariff_version_reviews_tariff_version_id"
        ),
    )


def downgrade() -> None:
    op.drop_table("tariff_version_reviews")
    with op.batch_alter_table("tariff_email_intakes", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_tariff_email_intakes_tariff_version_id"))
        batch_op.drop_index("ix_tariff_email_intakes_source_sha256")
        batch_op.drop_index("ix_tariff_email_intakes_status")
    op.drop_table("tariff_email_intakes")
    op.drop_table("tariff_intake_settings")
