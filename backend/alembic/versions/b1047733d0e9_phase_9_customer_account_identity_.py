"""Phase 9: the Customer Account identity foundation.

Revision ID: b1047733d0e9
Revises: a1c7f4d92b30
Create Date: 2026-09-20

Nine new tables. **Nothing existing is altered, dropped, renamed or rewritten** -- not one
column is added to ``customers``, ``customer_addresses``, ``shipments``, ``users`` or
``consent_events``, and no existing row is touched. That is the single most important
property of this migration and it is asserted rather than described:
``tests/test_migrations_phase9.py`` counts every pre-existing table's rows either side of an
upgrade, a downgrade and a re-upgrade.

**What the nine tables are for.** ``customer_identities`` is the account; it is not a row in
``users``, it holds no role and no permission, and there is no code path from it to a staff
authorization decision (OD-23, DEC-0090). ``customer_identity_links`` is the identity-to-
customer link, created here with its constraints and **written by nothing in this phase** --
linking is a staff act, and staff approval is Phase 10 (OD-24, DEC-0091).
``customer_sessions`` and ``customer_auth_tokens`` hold digests of credentials that exist in
plaintext only in a cookie and in an outbound message. ``customer_terms_acknowledgements``
and ``customer_notification_preferences`` record what a person was shown and what they chose
(OD-37, OD-38). ``customer_data_proposals`` and ``customer_data_proposal_fields`` hold what
the customer says about themselves *before anyone agrees to it*, which is the structural
reason a bug in customer-facing code cannot corrupt the CRM (OD-23, DEC-0092).
``customer_registration_attempts`` is the idempotency and concurrency claim for registration;
it is the one table ``docs/customer_account/DATA_MODEL.md`` does not propose, and the
reconciliation is in ``PROJECT_STATUS.md`` section 17.4 and DEC-0098.

**Why three canonical columns are *not* added.** ``FIELD_MATRIX.md`` section 6 names a
display name, a legal name distinct from it, and a ``billing`` address role as gaps, and
``IMPLEMENTATION_PLAN.md`` expected them to be decided inside this migration. The owner's
Phase 9 instruction says otherwise: do not add canonical columns for them here; carry the
values in the pending-proposal representation until their canonical treatment is
implemented. The owner decision governs. So ``customers`` keeps its current shape, the three
values live as allowlisted proposal field keys, and the decision moves to the phase that
first applies a proposal (DEC-0096).

**Why the two link indexes are partial.** ``uq_customer_identity_links_active_identity`` and
``uq_customer_identity_links_active_customer`` are unique only ``WHERE status = 'active'``.
Release 1 allows one active link per identity and one active identity per customer (OD-25);
a plain unique index would additionally forbid a *second revoked* link, which would make
unlinking and relinking impossible and would turn a normal correction into a data-repair
job. The predicate is the rule, stated exactly. Relaxing to company access later drops the
second index and permits another ``link_role`` -- no ownership check changes and no foreign
key moves, which is the entire reason the link is a table rather than a column.

**What this migration must not touch, and does not.** ``role_merge_provenance`` is owned by
``a1c7f4d92b30`` and by nothing else. It is not dropped, renamed, mapped or repurposed here,
and the autogeneration exclusion in ``alembic/autogenerate_policy.py`` still names exactly
that one table (DEC-0089). This migration was generated against a *copy* of the development
database, never the database itself.

**Reversible.** ``downgrade`` drops the nine tables and their indexes in dependency order and
restores the schema exactly. Tested rather than asserted: the Phase 9 migration test upgrades
a populated Phase 8 database, downgrades it, re-upgrades it, and compares the schema and the
row counts at every step. Because the nine tables are new, a downgrade destroys every
Customer Account identity, session, token, acknowledgement, preference and proposal in the
database it runs against -- which is the correct behaviour for reversing the phase that
introduced them, and a reason not to run it against anything but a development database.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b1047733d0e9"
down_revision: str | None = "a1c7f4d92b30"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "customer_identities",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("public_id", sa.String(length=20), nullable=False),
        sa.Column("email_entered", sa.String(length=320), nullable=False),
        sa.Column("email_normalized", sa.String(length=320), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("email_verified_at", sa.DateTime(), nullable=True),
        sa.Column("approved_at", sa.DateTime(), nullable=True),
        sa.Column("approved_by_user_id", sa.Integer(), nullable=True),
        sa.Column("rejected_at", sa.DateTime(), nullable=True),
        sa.Column("rejected_by_user_id", sa.Integer(), nullable=True),
        sa.Column("suspended_at", sa.DateTime(), nullable=True),
        sa.Column("suspended_by_user_id", sa.Integer(), nullable=True),
        sa.Column("deactivated_at", sa.DateTime(), nullable=True),
        sa.Column("deactivated_by_user_id", sa.Integer(), nullable=True),
        sa.Column("status_reason_code", sa.String(length=40), nullable=True),
        sa.Column("failed_sign_in_count", sa.Integer(), nullable=False),
        sa.Column("locked_until", sa.DateTime(), nullable=True),
        sa.Column("last_sign_in_at", sa.DateTime(), nullable=True),
        sa.Column("preferred_language", sa.String(length=8), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["approved_by_user_id"],
            ["users.id"],
            name=op.f("fk_customer_identities_approved_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["deactivated_by_user_id"],
            ["users.id"],
            name=op.f("fk_customer_identities_deactivated_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["rejected_by_user_id"],
            ["users.id"],
            name=op.f("fk_customer_identities_rejected_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["suspended_by_user_id"],
            ["users.id"],
            name=op.f("fk_customer_identities_suspended_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_customer_identities")),
        sa.UniqueConstraint("email_normalized", name="uq_customer_identities_email_normalized"),
        sa.UniqueConstraint("public_id", name="uq_customer_identities_public_id"),
    )
    with op.batch_alter_table("customer_identities", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_customer_identities_created_at"), ["created_at"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_customer_identities_email_normalized"),
            ["email_normalized"],
            unique=False,
        )
        batch_op.create_index("ix_customer_identities_status", ["status"], unique=False)

    op.create_table(
        "customer_auth_tokens",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("identity_id", sa.Integer(), nullable=False),
        sa.Column("purpose", sa.String(length=30), nullable=False),
        sa.Column("token_digest", sa.String(length=64), nullable=False),
        sa.Column("issued_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("consumed_at", sa.DateTime(), nullable=True),
        sa.Column("invalidated_at", sa.DateTime(), nullable=True),
        sa.Column("invalidated_reason_code", sa.String(length=40), nullable=True),
        sa.Column("issued_to_email_normalized", sa.String(length=320), nullable=False),
        sa.Column("request_ip", sa.String(length=64), nullable=True),
        sa.ForeignKeyConstraint(
            ["identity_id"],
            ["customer_identities.id"],
            name=op.f("fk_customer_auth_tokens_identity_id_customer_identities"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_customer_auth_tokens")),
        sa.UniqueConstraint("token_digest", name="uq_customer_auth_tokens_token_digest"),
    )
    with op.batch_alter_table("customer_auth_tokens", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_customer_auth_tokens_expires_at"), ["expires_at"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_customer_auth_tokens_identity_id"), ["identity_id"], unique=False
        )
        batch_op.create_index(
            "ix_customer_auth_tokens_identity_purpose", ["identity_id", "purpose"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_customer_auth_tokens_token_digest"), ["token_digest"], unique=False
        )

    op.create_table(
        "customer_data_proposals",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("identity_id", sa.Integer(), nullable=False),
        sa.Column("customer_id", sa.Integer(), nullable=True),
        sa.Column("kind", sa.String(length=30), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("submitted_at", sa.DateTime(), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(), nullable=True),
        sa.Column("reviewed_by_user_id", sa.Integer(), nullable=True),
        sa.Column("decision_reason_code", sa.String(length=40), nullable=True),
        sa.Column("duplicate_review_outcome", sa.String(length=30), nullable=True),
        sa.Column("applied_audit_event_id", sa.Integer(), nullable=True),
        sa.Column("supersedes_proposal_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["applied_audit_event_id"],
            ["audit_events.id"],
            name=op.f("fk_customer_data_proposals_applied_audit_event_id_audit_events"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["customer_id"],
            ["customers.id"],
            name=op.f("fk_customer_data_proposals_customer_id_customers"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["identity_id"],
            ["customer_identities.id"],
            name=op.f("fk_customer_data_proposals_identity_id_customer_identities"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["reviewed_by_user_id"],
            ["users.id"],
            name=op.f("fk_customer_data_proposals_reviewed_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["supersedes_proposal_id"],
            ["customer_data_proposals.id"],
            name=op.f("fk_customer_data_proposals_supersedes_proposal_id_customer_data_proposals"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_customer_data_proposals")),
    )
    with op.batch_alter_table("customer_data_proposals", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_customer_data_proposals_identity_id"), ["identity_id"], unique=False
        )
        batch_op.create_index(
            "ix_customer_data_proposals_identity_status", ["identity_id", "status"], unique=False
        )

    op.create_table(
        "customer_identity_links",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("identity_id", sa.Integer(), nullable=False),
        sa.Column("customer_id", sa.Integer(), nullable=False),
        sa.Column("link_role", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("linked_at", sa.DateTime(), nullable=False),
        sa.Column("linked_by_user_id", sa.Integer(), nullable=True),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.Column("revoked_by_user_id", sa.Integer(), nullable=True),
        sa.Column("revoke_reason_code", sa.String(length=40), nullable=True),
        sa.ForeignKeyConstraint(
            ["customer_id"],
            ["customers.id"],
            name=op.f("fk_customer_identity_links_customer_id_customers"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["identity_id"],
            ["customer_identities.id"],
            name=op.f("fk_customer_identity_links_identity_id_customer_identities"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["linked_by_user_id"],
            ["users.id"],
            name=op.f("fk_customer_identity_links_linked_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["revoked_by_user_id"],
            ["users.id"],
            name=op.f("fk_customer_identity_links_revoked_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_customer_identity_links")),
    )
    with op.batch_alter_table("customer_identity_links", schema=None) as batch_op:
        batch_op.create_index(
            "ix_customer_identity_links_customer_id", ["customer_id"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_customer_identity_links_identity_id"), ["identity_id"], unique=False
        )
        batch_op.create_index(
            "uq_customer_identity_links_active_customer",
            ["customer_id"],
            unique=True,
            sqlite_where=sa.text("status = 'active'"),
            postgresql_where=sa.text("status = 'active'"),
        )
        batch_op.create_index(
            "uq_customer_identity_links_active_identity",
            ["identity_id"],
            unique=True,
            sqlite_where=sa.text("status = 'active'"),
            postgresql_where=sa.text("status = 'active'"),
        )

    op.create_table(
        "customer_notification_preferences",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("identity_id", sa.Integer(), nullable=False),
        sa.Column("channel", sa.String(length=20), nullable=False),
        sa.Column("topic", sa.String(length=40), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["identity_id"],
            ["customer_identities.id"],
            name=op.f("fk_customer_notification_preferences_identity_id_customer_identities"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_customer_notification_preferences")),
        sa.UniqueConstraint(
            "identity_id",
            "channel",
            "topic",
            name="uq_customer_notification_preferences_identity_channel_topic",
        ),
    )
    with op.batch_alter_table("customer_notification_preferences", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_customer_notification_preferences_identity_id"),
            ["identity_id"],
            unique=False,
        )

    op.create_table(
        "customer_registration_attempts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("idempotency_key_digest", sa.String(length=64), nullable=False),
        sa.Column("email_key", sa.String(length=64), nullable=False),
        sa.Column("request_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("outcome", sa.String(length=30), nullable=False),
        sa.Column("identity_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("request_ip", sa.String(length=64), nullable=True),
        sa.ForeignKeyConstraint(
            ["identity_id"],
            ["customer_identities.id"],
            name=op.f("fk_customer_registration_attempts_identity_id_customer_identities"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_customer_registration_attempts")),
        sa.UniqueConstraint(
            "idempotency_key_digest",
            name="uq_customer_registration_attempts_idempotency_key_digest",
        ),
    )
    with op.batch_alter_table("customer_registration_attempts", schema=None) as batch_op:
        batch_op.create_index(
            "ix_customer_registration_attempts_created_at", ["created_at"], unique=False
        )
        batch_op.create_index(
            "ix_customer_registration_attempts_email_key", ["email_key"], unique=False
        )

    op.create_table(
        "customer_sessions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("identity_id", sa.Integer(), nullable=False),
        sa.Column("session_token_hash", sa.String(length=64), nullable=False),
        sa.Column("csrf_token_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.Column("ip_address", sa.String(length=64), nullable=True),
        sa.Column("user_agent", sa.String(length=255), nullable=True),
        sa.ForeignKeyConstraint(
            ["identity_id"],
            ["customer_identities.id"],
            name=op.f("fk_customer_sessions_identity_id_customer_identities"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_customer_sessions")),
        sa.UniqueConstraint("session_token_hash", name="uq_customer_sessions_session_token_hash"),
    )
    with op.batch_alter_table("customer_sessions", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_customer_sessions_expires_at"), ["expires_at"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_customer_sessions_identity_id"), ["identity_id"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_customer_sessions_session_token_hash"),
            ["session_token_hash"],
            unique=False,
        )

    op.create_table(
        "customer_terms_acknowledgements",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("identity_id", sa.Integer(), nullable=False),
        sa.Column("document_kind", sa.String(length=30), nullable=False),
        sa.Column("document_version", sa.String(length=40), nullable=False),
        sa.Column("presented_language", sa.String(length=8), nullable=False),
        sa.Column("acknowledged_at", sa.DateTime(), nullable=False),
        sa.Column("request_ip", sa.String(length=64), nullable=True),
        sa.ForeignKeyConstraint(
            ["identity_id"],
            ["customer_identities.id"],
            name=op.f("fk_customer_terms_acknowledgements_identity_id_customer_identities"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_customer_terms_acknowledgements")),
    )
    with op.batch_alter_table("customer_terms_acknowledgements", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_customer_terms_acknowledgements_identity_id"),
            ["identity_id"],
            unique=False,
        )
        batch_op.create_index(
            "ix_customer_terms_acknowledgements_identity_kind",
            ["identity_id", "document_kind"],
            unique=False,
        )

    op.create_table(
        "customer_data_proposal_fields",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("proposal_id", sa.Integer(), nullable=False),
        sa.Column("field_key", sa.String(length=60), nullable=False),
        sa.Column("value_type", sa.String(length=20), nullable=False),
        sa.Column("proposed_value", sa.Text(), nullable=True),
        sa.Column("proposed_value_normalized", sa.Text(), nullable=True),
        sa.Column("current_value_at_submission", sa.Text(), nullable=True),
        sa.Column("applied", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(
            ["proposal_id"],
            ["customer_data_proposals.id"],
            name=op.f("fk_customer_data_proposal_fields_proposal_id_customer_data_proposals"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_customer_data_proposal_fields")),
        sa.UniqueConstraint(
            "proposal_id",
            "field_key",
            name="uq_customer_data_proposal_fields_proposal_id_field_key",
        ),
    )
    with op.batch_alter_table("customer_data_proposal_fields", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_customer_data_proposal_fields_proposal_id"),
            ["proposal_id"],
            unique=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("customer_data_proposal_fields", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_customer_data_proposal_fields_proposal_id"))

    op.drop_table("customer_data_proposal_fields")
    with op.batch_alter_table("customer_terms_acknowledgements", schema=None) as batch_op:
        batch_op.drop_index("ix_customer_terms_acknowledgements_identity_kind")
        batch_op.drop_index(batch_op.f("ix_customer_terms_acknowledgements_identity_id"))

    op.drop_table("customer_terms_acknowledgements")
    with op.batch_alter_table("customer_sessions", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_customer_sessions_session_token_hash"))
        batch_op.drop_index(batch_op.f("ix_customer_sessions_identity_id"))
        batch_op.drop_index(batch_op.f("ix_customer_sessions_expires_at"))

    op.drop_table("customer_sessions")
    with op.batch_alter_table("customer_registration_attempts", schema=None) as batch_op:
        batch_op.drop_index("ix_customer_registration_attempts_email_key")
        batch_op.drop_index("ix_customer_registration_attempts_created_at")

    op.drop_table("customer_registration_attempts")
    with op.batch_alter_table("customer_notification_preferences", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_customer_notification_preferences_identity_id"))

    op.drop_table("customer_notification_preferences")
    with op.batch_alter_table("customer_identity_links", schema=None) as batch_op:
        batch_op.drop_index(
            "uq_customer_identity_links_active_identity",
            sqlite_where=sa.text("status = 'active'"),
            postgresql_where=sa.text("status = 'active'"),
        )
        batch_op.drop_index(
            "uq_customer_identity_links_active_customer",
            sqlite_where=sa.text("status = 'active'"),
            postgresql_where=sa.text("status = 'active'"),
        )
        batch_op.drop_index(batch_op.f("ix_customer_identity_links_identity_id"))
        batch_op.drop_index("ix_customer_identity_links_customer_id")

    op.drop_table("customer_identity_links")
    with op.batch_alter_table("customer_data_proposals", schema=None) as batch_op:
        batch_op.drop_index("ix_customer_data_proposals_identity_status")
        batch_op.drop_index(batch_op.f("ix_customer_data_proposals_identity_id"))

    op.drop_table("customer_data_proposals")
    with op.batch_alter_table("customer_auth_tokens", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_customer_auth_tokens_token_digest"))
        batch_op.drop_index("ix_customer_auth_tokens_identity_purpose")
        batch_op.drop_index(batch_op.f("ix_customer_auth_tokens_identity_id"))
        batch_op.drop_index(batch_op.f("ix_customer_auth_tokens_expires_at"))

    op.drop_table("customer_auth_tokens")
    with op.batch_alter_table("customer_identities", schema=None) as batch_op:
        batch_op.drop_index("ix_customer_identities_status")
        batch_op.drop_index(batch_op.f("ix_customer_identities_email_normalized"))
        batch_op.drop_index(batch_op.f("ix_customer_identities_created_at"))

    op.drop_table("customer_identities")
