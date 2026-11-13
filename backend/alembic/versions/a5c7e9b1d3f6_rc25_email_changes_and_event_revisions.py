"""RC-UAT-25: Admin sign-in email changes and timeline event edits (Ben, 2026-10-25).

Revision ID: a5c7e9b1d3f6
Revises: e7a9c1d3f5b6
Create Date: 2026-10-25

Two new tables; nothing existing is altered:

* ``customer_account_email_changes`` -- an Admin changed a Customer Account's sign-in email
  (item 2: customers can no longer change it themselves). Keeps the address before and after,
  the linked customer that followed, the Admin's bounded reason and optional note, the number
  of sessions ended, when and by whom.
* ``shipment_event_revisions`` -- staff edited an operational timeline event (item 6). Keeps
  the edited fields before and after (JSON), the event rows touched, the reason, whether the
  event was published and whether its customer-visible wording changed, when and by whom.

**Downgrade** drops both tables. Sign-in emails and event rows already changed stay as they
are (the change is on the ordinary rows); only the history of who changed them and why is
lost (the audit rows remain).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a5c7e9b1d3f6"
down_revision: str | None = "e7a9c1d3f5b6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "customer_account_email_changes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("identity_id", sa.Integer(), nullable=False),
        sa.Column("customer_id", sa.Integer(), nullable=True),
        sa.Column("previous_email_entered", sa.String(length=320), nullable=False),
        sa.Column("new_email_entered", sa.String(length=320), nullable=False),
        sa.Column("reason_code", sa.String(length=40), nullable=False),
        sa.Column("note", sa.String(length=500), nullable=True),
        sa.Column("sessions_revoked", sa.Integer(), nullable=False),
        sa.Column("changed_at", sa.DateTime(), nullable=False),
        sa.Column("changed_by_user_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["identity_id"],
            ["customer_identities.id"],
            name=op.f("fk_customer_account_email_changes_identity_id_customer_identities"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["customer_id"],
            ["customers.id"],
            name=op.f("fk_customer_account_email_changes_customer_id_customers"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["changed_by_user_id"],
            ["users.id"],
            name=op.f("fk_customer_account_email_changes_changed_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_customer_account_email_changes")),
    )
    op.create_index(
        op.f("ix_customer_account_email_changes_identity_id"),
        "customer_account_email_changes",
        ["identity_id"],
        unique=False,
    )
    op.create_table(
        "shipment_event_revisions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("shipment_id", sa.Integer(), nullable=False),
        sa.Column("event_ids_before", sa.Text(), nullable=False),
        sa.Column("event_ids_after", sa.Text(), nullable=False),
        sa.Column("before_json", sa.Text(), nullable=False),
        sa.Column("after_json", sa.Text(), nullable=False),
        sa.Column("reason", sa.String(length=255), nullable=False),
        sa.Column("was_published", sa.Boolean(), nullable=False),
        sa.Column("public_wording_changed", sa.Boolean(), nullable=False),
        sa.Column("edited_at", sa.DateTime(), nullable=False),
        sa.Column("edited_by_user_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["shipment_id"],
            ["shipments.id"],
            name=op.f("fk_shipment_event_revisions_shipment_id_shipments"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["edited_by_user_id"],
            ["users.id"],
            name=op.f("fk_shipment_event_revisions_edited_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_shipment_event_revisions")),
    )
    op.create_index(
        op.f("ix_shipment_event_revisions_shipment_id"),
        "shipment_event_revisions",
        ["shipment_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_shipment_event_revisions_shipment_id"), table_name="shipment_event_revisions"
    )
    op.drop_table("shipment_event_revisions")
    op.drop_index(
        op.f("ix_customer_account_email_changes_identity_id"),
        table_name="customer_account_email_changes",
    )
    op.drop_table("customer_account_email_changes")
