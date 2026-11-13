"""Phase 5A: import batch provenance and a source-record uniqueness index.

Revision ID: c4a1f27b93de
Revises: 9d7dc78dd25c
Create Date: 2026-09-10

Two new tables and one index. Nothing existing is altered, dropped, or rewritten.

**Why a migration is necessary at all.** ``CRM.md`` section 13 requires that a repeated
import does not double-count customers, and that provenance is kept as "source system plus
source record ID". The columns for that already exist on ``customers``; what did not exist
was anything *enforcing* uniqueness on them, so two imports of the same file would happily
create two of every person. The unique index is the enforcement. The two batch tables are
what make a completion summary durable — ``CRM.md`` section 13 asks for "explicit
confirmation before commit" and a useful result, and a summary that lives only in an HTTP
response is gone the moment the operator closes the tab.

**Why nothing more.** No column is added to ``customers``: ``import_batch_rows`` already
links a batch to the customers it created, so a column on ``customers`` would be a second
way to express the same fact. No staging table is created for previewed rows, because a
preview writes nothing (DEC-0078) — a table of un-reviewed personal data would be a second
copy of the customer database with none of its access controls.

**Why the index is partial.** Most customers are created by hand and carry neither
``source_system`` nor ``source_record_id``. A plain unique index over two nullable columns
is safe on SQLite, which treats NULLs as distinct, but is *not* safe on every database, and
``CRM.md`` section 3 requires that a PostgreSQL migration stays practical. The predicate
makes the intent explicit and portable: the constraint applies to imported rows only.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "c4a1f27b93de"
down_revision: str | None = "9d7dc78dd25c"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "import_batches",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("public_id", sa.String(length=20), nullable=False),
        sa.Column("kind", sa.String(length=30), nullable=False),
        sa.Column("file_name", sa.String(length=255), nullable=True),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column("source_system", sa.String(length=60), nullable=False),
        sa.Column("conflict_policy", sa.String(length=30), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=False),
        sa.Column("created_count", sa.Integer(), nullable=False),
        sa.Column("matched_count", sa.Integer(), nullable=False),
        sa.Column("skipped_count", sa.Integer(), nullable=False),
        sa.Column("rejected_count", sa.Integer(), nullable=False),
        sa.Column("committed_at", sa.DateTime(), nullable=False),
        sa.Column("committed_by_user_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["committed_by_user_id"],
            ["users.id"],
            name=op.f("fk_import_batches_committed_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_import_batches")),
        sa.UniqueConstraint("public_id", name="uq_import_batches_public_id"),
    )
    op.create_index(
        "ix_import_batches_committed_at", "import_batches", ["committed_at"], unique=False
    )
    op.create_index(
        op.f("ix_import_batches_created_at"), "import_batches", ["created_at"], unique=False
    )

    op.create_table(
        "import_batch_rows",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("batch_id", sa.Integer(), nullable=False),
        sa.Column("row_number", sa.Integer(), nullable=False),
        sa.Column("outcome", sa.String(length=20), nullable=False),
        sa.Column("reason_code", sa.String(length=60), nullable=True),
        sa.Column("customer_id", sa.Integer(), nullable=True),
        sa.Column("source_record_id", sa.String(length=120), nullable=True),
        sa.ForeignKeyConstraint(
            ["batch_id"],
            ["import_batches.id"],
            name=op.f("fk_import_batch_rows_batch_id_import_batches"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["customer_id"],
            ["customers.id"],
            name=op.f("fk_import_batch_rows_customer_id_customers"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_import_batch_rows")),
        sa.UniqueConstraint(
            "batch_id", "row_number", name="uq_import_batch_rows_batch_id_row_number"
        ),
    )
    op.create_index(
        op.f("ix_import_batch_rows_batch_id"), "import_batch_rows", ["batch_id"], unique=False
    )
    op.create_index(
        op.f("ix_import_batch_rows_customer_id"),
        "import_batch_rows",
        ["customer_id"],
        unique=False,
    )
    op.create_index(
        "ix_import_batch_rows_outcome", "import_batch_rows", ["batch_id", "outcome"], unique=False
    )

    # Import idempotency. Partial so hand-created customers, which carry neither column,
    # do not all collide on (NULL, NULL) under a database that treats NULLs as equal.
    op.create_index(
        "uq_customers_source_record",
        "customers",
        ["source_system", "source_record_id"],
        unique=True,
        sqlite_where=sa.text("source_system IS NOT NULL AND source_record_id IS NOT NULL"),
        postgresql_where=sa.text("source_system IS NOT NULL AND source_record_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_customers_source_record", table_name="customers")
    op.drop_index("ix_import_batch_rows_outcome", table_name="import_batch_rows")
    op.drop_index(op.f("ix_import_batch_rows_customer_id"), table_name="import_batch_rows")
    op.drop_index(op.f("ix_import_batch_rows_batch_id"), table_name="import_batch_rows")
    op.drop_table("import_batch_rows")
    op.drop_index(op.f("ix_import_batches_created_at"), table_name="import_batches")
    op.drop_index("ix_import_batches_committed_at", table_name="import_batches")
    op.drop_table("import_batches")
