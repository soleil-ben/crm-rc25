"""Owner answers 8, 9, 9a (2026-10-21): master edit lock, quote expiry, draft invoices.

Revision ID: d4f7a2c9e1b8
Revises: c5e8a1f3d7b9
Create Date: 2026-10-21

Three new tables: ``master_edit_unlocks`` (an Admin's audited, temporary unlock of a booked
master's items and fee lines, and when it was locked again), ``invoice_drafts`` (the invoice
prepared as a draft when a customer accepts a quote, editable until staff send it) and
``quote_expiries`` (a finalised quote version that expired when a new tariff version became
active before the goods were received). Nothing existing is altered (DEC-0181): an expired
offer's ``expired`` is a new value of the existing string ``quote_offers.status``.

**Downgrade** maps ``quote_offers.status`` ``expired`` back to ``withdrawn`` (the older
code's closed state), then drops all three.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "d4f7a2c9e1b8"
down_revision: str | None = "c5e8a1f3d7b9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _fk(table: str, column: str, target: str, ondelete: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        [column],
        [f"{target}.id"],
        name=op.f(f"fk_{table}_{column}_{target}"),
        ondelete=ondelete,
    )


def upgrade() -> None:
    op.create_table(
        "master_edit_unlocks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("consolidation_id", sa.Integer(), nullable=False),
        sa.Column("unlocked_by_user_id", sa.Integer(), nullable=True),
        sa.Column("reason", sa.String(length=400), nullable=False),
        sa.Column("unlocked_at", sa.DateTime(), nullable=False),
        sa.Column("relocked_at", sa.DateTime(), nullable=True),
        sa.Column("relocked_by_user_id", sa.Integer(), nullable=True),
        sa.Column("relock_reason", sa.String(length=400), nullable=True),
        _fk("master_edit_unlocks", "consolidation_id", "consolidations", "CASCADE"),
        _fk("master_edit_unlocks", "unlocked_by_user_id", "users", "SET NULL"),
        _fk("master_edit_unlocks", "relocked_by_user_id", "users", "SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_master_edit_unlocks")),
    )
    with op.batch_alter_table("master_edit_unlocks", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_master_edit_unlocks_consolidation_id"),
            ["consolidation_id"],
            unique=False,
        )
        batch_op.create_index(
            "uq_master_edit_unlocks_open_consolidation",
            ["consolidation_id"],
            unique=True,
            sqlite_where=sa.text("relocked_at IS NULL"),
            postgresql_where=sa.text("relocked_at IS NULL"),
        )

    op.create_table(
        "invoice_drafts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("shipment_id", sa.Integer(), nullable=False),
        sa.Column("customer_id", sa.Integer(), nullable=False),
        sa.Column("quote_version_id", sa.Integer(), nullable=False),
        sa.Column("offer_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=12), nullable=False),
        sa.Column("bill_to_name", sa.String(length=200), nullable=True),
        sa.Column("bill_to_address", sa.Text(), nullable=True),
        sa.Column("customer_reference", sa.String(length=120), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("tax_rate_percent", sa.Integer(), nullable=False),
        sa.Column("lines_json", sa.Text(), nullable=False),
        sa.Column("quote_total_cad", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("total_change_reason", sa.String(length=400), nullable=True),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
        sa.Column("created_by_identity_id", sa.Integer(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("updated_by_user_id", sa.Integer(), nullable=True),
        sa.Column("issued_invoice_id", sa.Integer(), nullable=True),
        sa.Column("issued_at", sa.DateTime(), nullable=True),
        sa.Column("discarded_at", sa.DateTime(), nullable=True),
        sa.Column("discard_reason", sa.String(length=400), nullable=True),
        sa.Column("email_status", sa.String(length=20), nullable=True),
        _fk("invoice_drafts", "shipment_id", "shipments", "RESTRICT"),
        _fk("invoice_drafts", "customer_id", "customers", "RESTRICT"),
        _fk("invoice_drafts", "quote_version_id", "quote_versions", "RESTRICT"),
        _fk("invoice_drafts", "offer_id", "quote_offers", "SET NULL"),
        _fk("invoice_drafts", "created_by_user_id", "users", "SET NULL"),
        _fk("invoice_drafts", "created_by_identity_id", "customer_identities", "SET NULL"),
        _fk("invoice_drafts", "updated_by_user_id", "users", "SET NULL"),
        _fk("invoice_drafts", "issued_invoice_id", "customer_invoices", "SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_invoice_drafts")),
    )
    with op.batch_alter_table("invoice_drafts", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_invoice_drafts_shipment_id"), ["shipment_id"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_invoice_drafts_customer_id"), ["customer_id"], unique=False
        )
        batch_op.create_index(
            "uq_invoice_drafts_live_shipment",
            ["shipment_id"],
            unique=True,
            sqlite_where=sa.text("status = 'draft'"),
            postgresql_where=sa.text("status = 'draft'"),
        )

    op.create_table(
        "quote_expiries",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("quote_version_id", sa.Integer(), nullable=False),
        sa.Column("shipment_id", sa.Integer(), nullable=False),
        sa.Column("tariff_version_id", sa.Integer(), nullable=True),
        sa.Column("offer_id", sa.Integer(), nullable=True),
        sa.Column("previous_offer_status", sa.String(length=12), nullable=True),
        sa.Column("invoice_draft_id", sa.Integer(), nullable=True),
        sa.Column("reason", sa.String(length=400), nullable=False),
        sa.Column("expired_at", sa.DateTime(), nullable=False),
        _fk("quote_expiries", "quote_version_id", "quote_versions", "CASCADE"),
        _fk("quote_expiries", "shipment_id", "shipments", "CASCADE"),
        _fk("quote_expiries", "tariff_version_id", "tariff_versions", "SET NULL"),
        _fk("quote_expiries", "offer_id", "quote_offers", "SET NULL"),
        _fk("quote_expiries", "invoice_draft_id", "invoice_drafts", "SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_quote_expiries")),
        sa.UniqueConstraint("quote_version_id", name=op.f("uq_quote_expiries_quote_version_id")),
    )
    with op.batch_alter_table("quote_expiries", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_quote_expiries_shipment_id"), ["shipment_id"], unique=False
        )


def downgrade() -> None:
    # The older code knows no ``expired`` offer: it reads as ``withdrawn`` (closed, cannot be
    # answered), which is what an expired offer is to that code.
    op.execute(
        sa.text(
            "UPDATE quote_offers SET status = 'withdrawn', "
            "withdrawn_at = COALESCE(withdrawn_at, updated_at) WHERE status = 'expired'"
        )
    )
    with op.batch_alter_table("quote_expiries", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_quote_expiries_shipment_id"))
    op.drop_table("quote_expiries")
    with op.batch_alter_table("invoice_drafts", schema=None) as batch_op:
        batch_op.drop_index("uq_invoice_drafts_live_shipment")
        batch_op.drop_index(batch_op.f("ix_invoice_drafts_customer_id"))
        batch_op.drop_index(batch_op.f("ix_invoice_drafts_shipment_id"))
    op.drop_table("invoice_drafts")
    with op.batch_alter_table("master_edit_unlocks", schema=None) as batch_op:
        batch_op.drop_index("uq_master_edit_unlocks_open_consolidation")
        batch_op.drop_index(batch_op.f("ix_master_edit_unlocks_consolidation_id"))
    op.drop_table("master_edit_unlocks")
