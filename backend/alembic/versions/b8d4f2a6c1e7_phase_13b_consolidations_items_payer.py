"""Phase 13B: consolidations, memberships, commodity items, the service mapping, the payer.

Revision ID: b8d4f2a6c1e7
Revises: a7c3e1d9b2f4
Create Date: 2026-10-19

Six new tables. **No existing table is altered and no existing row is read or rewritten.**

**The tables.** ``consolidations`` is the vendor booking that carries several customers'
shipments (the handoff's master); ``consolidation_memberships`` says which shipments ride in
it, with a partial unique index so a shipment is in at most one *active* consolidation while
its removed memberships stay as history; ``shipment_items`` holds the commodity lines of a
customer shipment (Phase 13C attaches surcharges to them); ``service_vendor_products`` maps a
Solaris service to the vendor product it is priced through, per tariff version and origin
(OD-43: air only); ``shipment_payers`` names who pays when it is not the booking customer
(handoff section 2; no row means the booking customer pays); ``consolidation_event_links``
marks an event a consolidation fanned out to its members, so an inherited master milestone
is distinguishable from one recorded on the shipment and a repeat can be refused. See
``docs/b2c_merge/06_MERGE_PLAN.md`` phase 13B.

**Why link tables and not two columns.** The first draft added ``payer_customer_id`` to
``shipments`` and ``consolidation_id`` to ``shipment_events``. A foreign-key column cannot
be added to an existing SQLite table in place, so Alembic rebuilds the table -- and with
``PRAGMA foreign_keys`` on for every connection (``app/core/db.py``), dropping the original
cascades into every child row: the Phase 4A populated-database test lost the shipment's
packages. ``PRAGMA foreign_keys`` cannot be turned off inside the transaction Alembic runs
in. Two new tables carry the same facts and cost nothing existing, in either direction.

**Why a partial unique index.** One shipment, one active consolidation -- but a shipment
moved from a cancelled consolidation to a new one keeps both membership rows. A plain unique
constraint would forbid the history; the WHERE keeps the guarantee on the live rows only.
SQLite and PostgreSQL both honour it.

**Deletion behaviour is declared on every foreign key**: a consolidation's memberships and
event links cascade with it, a shipment's items, payer row, memberships and event links
cascade with the shipment, user and tariff references on a consolidation are set to NULL,
a mapping row cascades with its tariff version and product, and a vendor with
consolidations cannot be deleted.

**Backfill.** Tariff versions imported by Phase 13A before this revision have no mapping
rows, so ``upgrade`` writes them for every existing version: Air Standard → ``AIR-CAD``
and Air Express → ``AIR-CAD EXPRESS`` per origin, where that product exists. The same
rows the importer writes from here on.

**Downgrade** drops the six tables in dependency order.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa

from alembic import op

revision: str = "b8d4f2a6c1e7"
down_revision: str | None = "a7c3e1d9b2f4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "consolidations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("public_id", sa.String(length=20), nullable=False),
        sa.Column("vendor_id", sa.Integer(), nullable=False),
        sa.Column("solaris_service", sa.String(length=20), nullable=False),
        sa.Column("origin", sa.String(length=3), nullable=False),
        sa.Column("tariff_version_id", sa.Integer(), nullable=True),
        sa.Column("tariff_product_id", sa.Integer(), nullable=True),
        sa.Column("vendor_reference", sa.String(length=60), nullable=True),
        sa.Column("state", sa.String(length=20), nullable=False),
        sa.Column("actual_weight_kg", sa.Numeric(precision=8, scale=3), nullable=True),
        sa.Column("length_cm", sa.Numeric(precision=7, scale=1), nullable=True),
        sa.Column("width_cm", sa.Numeric(precision=7, scale=1), nullable=True),
        sa.Column("height_cm", sa.Numeric(precision=7, scale=1), nullable=True),
        sa.Column("carton_count", sa.Integer(), nullable=False),
        sa.Column("dim_divisor", sa.Integer(), nullable=True),
        sa.Column("volumetric_weight_kg", sa.Numeric(precision=8, scale=3), nullable=True),
        sa.Column("chargeable_weight_kg", sa.Numeric(precision=8, scale=3), nullable=True),
        sa.Column("handed_over_at", sa.DateTime(), nullable=True),
        sa.Column("cutoff_at", sa.DateTime(), nullable=True),
        sa.Column("booked_at", sa.DateTime(), nullable=True),
        sa.Column("booked_by_user_id", sa.Integer(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(), nullable=True),
        sa.Column("cancellation_reason", sa.String(length=255), nullable=True),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
        sa.Column("internal_notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["booked_by_user_id"],
            ["users.id"],
            name=op.f("fk_consolidations_booked_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            name=op.f("fk_consolidations_created_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["tariff_product_id"],
            ["tariff_products.id"],
            name=op.f("fk_consolidations_tariff_product_id_tariff_products"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["tariff_version_id"],
            ["tariff_versions.id"],
            name=op.f("fk_consolidations_tariff_version_id_tariff_versions"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["vendor_id"],
            ["vendors.id"],
            name=op.f("fk_consolidations_vendor_id_vendors"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_consolidations")),
        sa.UniqueConstraint("public_id", name="uq_consolidations_public_id"),
    )
    with op.batch_alter_table("consolidations", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_consolidations_created_at"), ["created_at"], unique=False
        )
        batch_op.create_index(
            "ix_consolidations_state_created_at", ["state", "created_at"], unique=False
        )
        batch_op.create_index(
            "ix_consolidations_vendor_reference", ["vendor_reference"], unique=False
        )

    op.create_table(
        "service_vendor_products",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tariff_version_id", sa.Integer(), nullable=False),
        sa.Column("solaris_service", sa.String(length=20), nullable=False),
        sa.Column("origin", sa.String(length=3), nullable=False),
        sa.Column("tariff_product_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["tariff_product_id"],
            ["tariff_products.id"],
            name=op.f("fk_service_vendor_products_tariff_product_id_tariff_products"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tariff_version_id"],
            ["tariff_versions.id"],
            name=op.f("fk_service_vendor_products_tariff_version_id_tariff_versions"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_service_vendor_products")),
        sa.UniqueConstraint(
            "tariff_version_id",
            "solaris_service",
            "origin",
            name="uq_service_vendor_products_tariff_version_id_solaris_service_origin",
        ),
    )
    op.create_table(
        "consolidation_memberships",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("consolidation_id", sa.Integer(), nullable=False),
        sa.Column("shipment_id", sa.Integer(), nullable=False),
        sa.Column("added_at", sa.DateTime(), nullable=False),
        sa.Column("added_by_user_id", sa.Integer(), nullable=True),
        sa.Column("removed_at", sa.DateTime(), nullable=True),
        sa.Column("removed_by_user_id", sa.Integer(), nullable=True),
        sa.Column("removal_reason", sa.String(length=255), nullable=True),
        sa.ForeignKeyConstraint(
            ["added_by_user_id"],
            ["users.id"],
            name=op.f("fk_consolidation_memberships_added_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["consolidation_id"],
            ["consolidations.id"],
            name=op.f("fk_consolidation_memberships_consolidation_id_consolidations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["removed_by_user_id"],
            ["users.id"],
            name=op.f("fk_consolidation_memberships_removed_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["shipment_id"],
            ["shipments.id"],
            name=op.f("fk_consolidation_memberships_shipment_id_shipments"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_consolidation_memberships")),
    )
    with op.batch_alter_table("consolidation_memberships", schema=None) as batch_op:
        batch_op.create_index(
            "ix_consolidation_memberships_consolidation_id_removed_at",
            ["consolidation_id", "removed_at"],
            unique=False,
        )
        batch_op.create_index(
            "uq_consolidation_memberships_active_shipment",
            ["shipment_id"],
            unique=True,
            sqlite_where=sa.text("removed_at IS NULL"),
            postgresql_where=sa.text("removed_at IS NULL"),
        )

    op.create_table(
        "shipment_payers",
        sa.Column("shipment_id", sa.Integer(), nullable=False),
        sa.Column("payer_customer_id", sa.Integer(), nullable=False),
        sa.Column("set_at", sa.DateTime(), nullable=False),
        sa.Column("set_by_user_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["payer_customer_id"],
            ["customers.id"],
            name=op.f("fk_shipment_payers_payer_customer_id_customers"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["set_by_user_id"],
            ["users.id"],
            name=op.f("fk_shipment_payers_set_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["shipment_id"],
            ["shipments.id"],
            name=op.f("fk_shipment_payers_shipment_id_shipments"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("shipment_id", name=op.f("pk_shipment_payers")),
    )
    with op.batch_alter_table("shipment_payers", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_shipment_payers_payer_customer_id"), ["payer_customer_id"], unique=False
        )

    op.create_table(
        "shipment_items",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("shipment_id", sa.Integer(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("description", sa.String(length=300), nullable=False),
        sa.Column("quantity", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column("unit", sa.String(length=20), nullable=False),
        sa.Column("weight_kg", sa.Numeric(precision=8, scale=3), nullable=True),
        sa.Column("declared_value", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("declared_value_currency", sa.String(length=3), nullable=True),
        sa.Column("package_id", sa.Integer(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("notes", sa.String(length=400), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["package_id"],
            ["shipment_packages.id"],
            name=op.f("fk_shipment_items_package_id_shipment_packages"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["shipment_id"],
            ["shipments.id"],
            name=op.f("fk_shipment_items_shipment_id_shipments"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_shipment_items")),
        sa.UniqueConstraint(
            "shipment_id", "sequence", name="uq_shipment_items_shipment_id_sequence"
        ),
    )
    with op.batch_alter_table("shipment_items", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_shipment_items_created_at"), ["created_at"], unique=False
        )

    op.create_table(
        "consolidation_event_links",
        sa.Column("event_id", sa.Integer(), nullable=False),
        sa.Column("consolidation_id", sa.Integer(), nullable=False),
        sa.Column("shipment_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["consolidation_id"],
            ["consolidations.id"],
            name=op.f("fk_consolidation_event_links_consolidation_id_consolidations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["event_id"],
            ["shipment_events.id"],
            name=op.f("fk_consolidation_event_links_event_id_shipment_events"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["shipment_id"],
            ["shipments.id"],
            name=op.f("fk_consolidation_event_links_shipment_id_shipments"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("event_id", name=op.f("pk_consolidation_event_links")),
    )
    with op.batch_alter_table("consolidation_event_links", schema=None) as batch_op:
        batch_op.create_index(
            "ix_consolidation_event_links_consolidation_id_shipment_id",
            ["consolidation_id", "shipment_id"],
            unique=False,
        )

    # Backfill the service mapping for tariff versions imported before this revision.
    bind = op.get_bind()
    now = datetime.now(UTC).replace(tzinfo=None)
    products = bind.execute(
        sa.text(
            "SELECT id, version_id, origin, code, last_mile FROM tariff_products "
            "WHERE code IN ('AIR-CAD', 'AIR-CAD EXPRESS')"
        )
    ).fetchall()
    written = 0
    for product_id, version_id, origin, code, last_mile in products:
        service = {
            ("AIR-CAD", "purolator_ground"): "air_standard",
            ("AIR-CAD EXPRESS", "purolator_express"): "air_express",
        }.get((code, last_mile))
        if service is None:
            continue
        bind.execute(
            sa.text(
                "INSERT INTO service_vendor_products "
                "(tariff_version_id, solaris_service, origin, tariff_product_id, created_at) "
                "VALUES (:version_id, :service, :origin, :product_id, :created_at)"
            ),
            {
                "version_id": version_id,
                "service": service,
                "origin": origin,
                "product_id": product_id,
                "created_at": now,
            },
        )
        written += 1
    print(f"  wrote {written} service mapping row(s) for existing tariff versions")


def downgrade() -> None:
    with op.batch_alter_table("consolidation_event_links", schema=None) as batch_op:
        batch_op.drop_index("ix_consolidation_event_links_consolidation_id_shipment_id")

    op.drop_table("consolidation_event_links")
    with op.batch_alter_table("shipment_items", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_shipment_items_created_at"))

    op.drop_table("shipment_items")
    with op.batch_alter_table("shipment_payers", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_shipment_payers_payer_customer_id"))

    op.drop_table("shipment_payers")
    with op.batch_alter_table("consolidation_memberships", schema=None) as batch_op:
        batch_op.drop_index(
            "uq_consolidation_memberships_active_shipment",
            sqlite_where=sa.text("removed_at IS NULL"),
            postgresql_where=sa.text("removed_at IS NULL"),
        )
        batch_op.drop_index("ix_consolidation_memberships_consolidation_id_removed_at")

    op.drop_table("consolidation_memberships")
    op.drop_table("service_vendor_products")
    with op.batch_alter_table("consolidations", schema=None) as batch_op:
        batch_op.drop_index("ix_consolidations_vendor_reference")
        batch_op.drop_index("ix_consolidations_state_created_at")
        batch_op.drop_index(batch_op.f("ix_consolidations_created_at"))

    op.drop_table("consolidations")
