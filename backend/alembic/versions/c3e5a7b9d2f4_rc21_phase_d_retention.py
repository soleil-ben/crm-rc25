"""RC-UAT-21 Phase D: quote soft delete and retention machinery.

Revision ID: c3e5a7b9d2f4
Revises: b2d4f6a8c1e3
Create Date: 2026-10-24

Four new tables; nothing existing is altered (DEC-0181, DEC-0233).

* ``quote_version_deletions`` -- an Admin's soft delete of an old quote version (reason
  required, audited), and its restore. The quote rows stay; at most one open deletion per
  version (partial unique index on ``restored_at IS NULL``).
* ``data_retention_settings`` -- one row, seeded **off**: the global retention switch, the
  minimum age (days, 0) before a quote may be soft-deleted, and the worker's batch size.
* ``data_retention_policies`` -- one row per record class, seeded **disabled with no period**
  (undecided: OD-01, OD-36), with the action each class allows.
* ``data_retention_runs`` -- the run log (dry runs and real runs): counts only.

**Downgrade** drops the four tables: soft-deleted quotes reappear everywhere (their rows were
never removed), and the retention machinery is gone (it was off).
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

import sqlalchemy as sa

from alembic import op

revision: str = "c3e5a7b9d2f4"
down_revision: str | None = "b2d4f6a8c1e3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SEEDED_AT = datetime(2026, 10, 24)
#: Record class and the action it allows, all disabled with no period. Kept literally here:
#: a migration never imports app code (``data_retention_service.RECORD_CLASSES``).
SEED_POLICIES = (
    ("soft_deleted_quotes", "delete"),
    ("closed_quote_offers", "anonymise"),
    ("notification_outbox_processed", "delete"),
    ("customer_auth_tokens_spent", "delete"),
    ("customer_sessions_ended", "delete"),
    ("staff_sessions_ended", "delete"),
    ("customer_registration_attempts", "delete"),
    ("tariff_intake_emails", "anonymise"),
)


def _user_fk(table: str, column: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        [column], ["users.id"], name=op.f(f"fk_{table}_{column}_users"), ondelete="SET NULL"
    )


def upgrade() -> None:
    op.create_table(
        "quote_version_deletions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("quote_version_id", sa.Integer(), nullable=True),
        sa.Column("shipment_id", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("reason", sa.String(length=400), nullable=False),
        sa.Column("deleted_at", sa.DateTime(), nullable=False),
        sa.Column("deleted_by_user_id", sa.Integer(), nullable=True),
        sa.Column("restored_at", sa.DateTime(), nullable=True),
        sa.Column("restored_by_user_id", sa.Integer(), nullable=True),
        sa.Column("restore_reason", sa.String(length=400), nullable=True),
        sa.Column("purged_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["quote_version_id"],
            ["quote_versions.id"],
            name=op.f("fk_quote_version_deletions_quote_version_id_quote_versions"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["shipment_id"],
            ["shipments.id"],
            name=op.f("fk_quote_version_deletions_shipment_id_shipments"),
            ondelete="CASCADE",
        ),
        _user_fk("quote_version_deletions", "deleted_by_user_id"),
        _user_fk("quote_version_deletions", "restored_by_user_id"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_quote_version_deletions")),
    )
    with op.batch_alter_table("quote_version_deletions", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_quote_version_deletions_quote_version_id"),
            ["quote_version_id"],
            unique=False,
        )
        batch_op.create_index(
            batch_op.f("ix_quote_version_deletions_shipment_id"), ["shipment_id"], unique=False
        )
        batch_op.create_index(
            "uq_quote_version_deletions_open_version",
            ["quote_version_id"],
            unique=True,
            sqlite_where=sa.text("restored_at IS NULL"),
            postgresql_where=sa.text("restored_at IS NULL"),
        )

    settings = op.create_table(
        "data_retention_settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("enabled_at", sa.DateTime(), nullable=True),
        sa.Column("enabled_by_user_id", sa.Integer(), nullable=True),
        sa.Column("quote_delete_min_age_days", sa.Integer(), nullable=False),
        sa.Column("batch_size", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("updated_by_user_id", sa.Integer(), nullable=True),
        _user_fk("data_retention_settings", "enabled_by_user_id"),
        _user_fk("data_retention_settings", "updated_by_user_id"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_data_retention_settings")),
    )
    op.bulk_insert(
        settings,
        [
            {
                "id": 1,
                "enabled": False,
                "enabled_at": None,
                "enabled_by_user_id": None,
                "quote_delete_min_age_days": 0,
                "batch_size": 200,
                "updated_at": SEEDED_AT,
                "updated_by_user_id": None,
            }
        ],
    )

    policies = op.create_table(
        "data_retention_policies",
        sa.Column("record_class", sa.String(length=40), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("period_days", sa.Integer(), nullable=True),
        sa.Column("action", sa.String(length=10), nullable=False),
        sa.Column("last_run_at", sa.DateTime(), nullable=True),
        sa.Column("last_run_affected", sa.Integer(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("updated_by_user_id", sa.Integer(), nullable=True),
        _user_fk("data_retention_policies", "updated_by_user_id"),
        sa.PrimaryKeyConstraint("record_class", name=op.f("pk_data_retention_policies")),
    )
    op.bulk_insert(
        policies,
        [
            {
                "record_class": key,
                "enabled": False,
                "period_days": None,
                "action": action,
                "last_run_at": None,
                "last_run_affected": None,
                "updated_at": SEEDED_AT,
                "updated_by_user_id": None,
            }
            for key, action in SEED_POLICIES
        ],
    )

    op.create_table(
        "data_retention_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("dry_run", sa.Boolean(), nullable=False),
        sa.Column("trigger", sa.String(length=10), nullable=False),
        sa.Column("actor_user_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=12), nullable=False),
        sa.Column("counts_json", sa.Text(), nullable=False),
        sa.Column("error", sa.String(length=300), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        _user_fk("data_retention_runs", "actor_user_id"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_data_retention_runs")),
    )
    with op.batch_alter_table("data_retention_runs", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_data_retention_runs_started_at"), ["started_at"], unique=False
        )


def downgrade() -> None:
    with op.batch_alter_table("data_retention_runs", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_data_retention_runs_started_at"))
    op.drop_table("data_retention_runs")
    op.drop_table("data_retention_policies")
    op.drop_table("data_retention_settings")
    with op.batch_alter_table("quote_version_deletions", schema=None) as batch_op:
        batch_op.drop_index("uq_quote_version_deletions_open_version")
        batch_op.drop_index(batch_op.f("ix_quote_version_deletions_shipment_id"))
        batch_op.drop_index(batch_op.f("ix_quote_version_deletions_quote_version_id"))
    op.drop_table("quote_version_deletions")
