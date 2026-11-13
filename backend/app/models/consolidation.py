"""Consolidations, memberships, commodity line items and the service mapping (Phase 13B).

The handoff's master shipment: one vendor booking that carries several customers'
shipments in one or more cartons (handoff section 2). Six tables, all new:

* ``consolidations`` -- the vendor booking: vendor, Solaris service, origin depot, the
  vendor product and tariff version it will be priced against, the vendor's own reference
  (booking number or AWB), master weight and dimensions, the chargeable weight the vendor
  bills, and a small state machine (open → booked → completed, or cancelled).
* ``consolidation_memberships`` -- which customer shipments ride in it. A shipment is in at
  most one *active* consolidation at a time (partial unique index); a removed membership
  keeps its row with ``removed_at`` set, so the history of a re-routed shipment survives.
* ``shipment_items`` -- the commodity lines of a customer shipment (name, quantity, unit,
  weight, declared value). Phase 13C attaches surcharge rules to these.
* ``service_vendor_products`` -- which vendor product a Solaris service is priced through,
  per tariff version and origin (OD-43: Air Standard → ``AIR-CAD``, Air Express →
  ``AIR-CAD EXPRESS``; sea unmapped). The only place a vendor product name meets a Solaris
  service name.
* ``shipment_payers`` -- who pays, when it is not the booking customer (handoff section 2:
  payer, sender and receiver are distinct roles). One optional row per shipment.
* ``consolidation_event_links`` -- marks an event a consolidation fanned out to its members,
  so an inherited milestone is distinguishable from one recorded on the shipment itself and
  a repeat of the same master milestone can be refused. One row per inherited event.

Both of those are **link tables rather than columns on ``shipments`` and ``shipment_events``**
on purpose. Adding a foreign-key column to an existing SQLite table makes Alembic rebuild
the table, and with foreign keys enforced the rebuild cascades into every child row; the
Phase 4A column guard exists to make that cost visible. New tables cost nothing existing.

**Vendor references are internal.** ``vendor_reference`` and everything else here is staff
data; no column of these tables is read by the public or Customer Account routers, and the
public privacy scan already forbids ``consolidation`` and ``master_reference`` keys.

**Nothing here prices anything.** Weights are recorded; the engine that turns them into
money is Phase 13C.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import ConsolidationState, SolarisService
from app.models.base import Base, TimestampMixin


class ServiceVendorProduct(Base):
    """One Solaris service → one vendor product, per tariff version and origin (OD-43)."""

    __tablename__ = "service_vendor_products"
    __table_args__ = (
        UniqueConstraint(
            "tariff_version_id",
            "solaris_service",
            "origin",
            name="uq_service_vendor_products_tariff_version_id_solaris_service_origin",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tariff_version_id: Mapped[int] = mapped_column(
        ForeignKey("tariff_versions.id", ondelete="CASCADE"), nullable=False
    )
    solaris_service: Mapped[str] = mapped_column(String(20), nullable=False)
    origin: Mapped[str] = mapped_column(String(3), nullable=False)
    tariff_product_id: Mapped[int] = mapped_column(
        ForeignKey("tariff_products.id", ondelete="CASCADE"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    @property
    def solaris_service_enum(self) -> SolarisService:
        return SolarisService(self.solaris_service)


class Consolidation(TimestampMixin, Base):
    """A vendor booking carrying several customer shipments. Internal."""

    __tablename__ = "consolidations"
    __table_args__ = (
        UniqueConstraint("public_id", name="uq_consolidations_public_id"),
        Index("ix_consolidations_state_created_at", "state", "created_at"),
        Index("ix_consolidations_vendor_reference", "vendor_reference"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    #: ``MST-000001``: the Solaris reference for the master. Never the vendor's number.
    public_id: Mapped[str] = mapped_column(String(20), nullable=False)
    vendor_id: Mapped[int] = mapped_column(
        ForeignKey("vendors.id", ondelete="RESTRICT"), nullable=False
    )
    solaris_service: Mapped[str] = mapped_column(String(20), nullable=False)
    origin: Mapped[str] = mapped_column(String(3), nullable=False)
    #: Set when the consolidation is booked, from the active tariff's mapping. NULL on an
    #: open consolidation means "not priced against anything yet", not "free".
    tariff_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("tariff_versions.id", ondelete="SET NULL"), nullable=True
    )
    tariff_product_id: Mapped[int | None] = mapped_column(
        ForeignKey("tariff_products.id", ondelete="SET NULL"), nullable=True
    )
    #: The vendor's booking number or air waybill. Staff-only; never a public identifier
    #: (directive v2.1 section 5).
    vendor_reference: Mapped[str | None] = mapped_column(String(60), nullable=True)
    state: Mapped[str] = mapped_column(String(20), nullable=False, default=ConsolidationState.OPEN)

    #: Measured on the whole master as the vendor weighs it.
    actual_weight_kg: Mapped[Decimal | None] = mapped_column(Numeric(8, 3), nullable=True)
    length_cm: Mapped[Decimal | None] = mapped_column(Numeric(7, 1), nullable=True)
    width_cm: Mapped[Decimal | None] = mapped_column(Numeric(7, 1), nullable=True)
    height_cm: Mapped[Decimal | None] = mapped_column(Numeric(7, 1), nullable=True)
    carton_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    #: The divisor in force when the chargeable weight was computed; copied from the
    #: product so the figure can be reproduced after a tariff change.
    dim_divisor: Mapped[int | None] = mapped_column(Integer, nullable=True)
    volumetric_weight_kg: Mapped[Decimal | None] = mapped_column(Numeric(8, 3), nullable=True)
    #: What the vendor bills: the greater of actual and volumetric, rounded by the recorded
    #: convention (``pricing.chargeable_weight``). Stored at booking, never recomputed.
    chargeable_weight_kg: Mapped[Decimal | None] = mapped_column(Numeric(8, 3), nullable=True)

    #: When the master was handed to the vendor at the Vietnam depot. The revenue period
    #: for management reporting (handoff owner decision 12).
    handed_over_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    cutoff_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    booked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    booked_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    cancellation_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    internal_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    memberships: Mapped[list[ConsolidationMembership]] = relationship(
        back_populates="consolidation", cascade="all, delete-orphan"
    )

    @property
    def state_enum(self) -> ConsolidationState:
        return ConsolidationState(self.state)

    @property
    def solaris_service_enum(self) -> SolarisService:
        return SolarisService(self.solaris_service)


class ConsolidationMembership(Base):
    """A customer shipment's ride in a consolidation. Removal keeps the row."""

    __tablename__ = "consolidation_memberships"
    __table_args__ = (
        # One active consolidation per shipment. Partial so the history of removed
        # memberships can coexist with the current one; SQLite and PostgreSQL both honour
        # a WHERE on a unique index.
        Index(
            "uq_consolidation_memberships_active_shipment",
            "shipment_id",
            unique=True,
            sqlite_where=text("removed_at IS NULL"),
            postgresql_where=text("removed_at IS NULL"),
        ),
        Index(
            "ix_consolidation_memberships_consolidation_id_removed_at",
            "consolidation_id",
            "removed_at",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    consolidation_id: Mapped[int] = mapped_column(
        ForeignKey("consolidations.id", ondelete="CASCADE"), nullable=False
    )
    shipment_id: Mapped[int] = mapped_column(
        ForeignKey("shipments.id", ondelete="CASCADE"), nullable=False
    )
    added_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    added_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    removed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    removed_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    removal_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)

    consolidation: Mapped[Consolidation] = relationship(back_populates="memberships")

    @property
    def is_active(self) -> bool:
        return self.removed_at is None


class ShipmentItem(TimestampMixin, Base):
    """A commodity line of a customer shipment. Surcharges attach here in Phase 13C."""

    __tablename__ = "shipment_items"
    __table_args__ = (
        UniqueConstraint("shipment_id", "sequence", name="uq_shipment_items_shipment_id_sequence"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    shipment_id: Mapped[int] = mapped_column(
        ForeignKey("shipments.id", ondelete="CASCADE"), nullable=False
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    description: Mapped[str] = mapped_column(String(300), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False, default=1)
    unit: Mapped[str] = mapped_column(String(20), nullable=False, default="piece")
    weight_kg: Mapped[Decimal | None] = mapped_column(Numeric(8, 3), nullable=True)
    declared_value: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    declared_value_currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    #: Which of the shipment's packages holds it, when the staff know. Optional.
    package_id: Mapped[int | None] = mapped_column(
        ForeignKey("shipment_packages.id", ondelete="SET NULL"), nullable=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    notes: Mapped[str | None] = mapped_column(String(400), nullable=True)


class ShipmentPayer(Base):
    """The paying customer of a shipment, when it is not the booking customer.

    Absent row = the booking customer pays. Kept as its own table so no column is added
    to ``shipments`` (see the module docstring).
    """

    __tablename__ = "shipment_payers"

    shipment_id: Mapped[int] = mapped_column(
        ForeignKey("shipments.id", ondelete="CASCADE"), primary_key=True
    )
    payer_customer_id: Mapped[int] = mapped_column(
        ForeignKey("customers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    set_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    set_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class ConsolidationEventLink(Base):
    """An event a consolidation fanned out to one of its members."""

    __tablename__ = "consolidation_event_links"
    __table_args__ = (
        Index(
            "ix_consolidation_event_links_consolidation_id_shipment_id",
            "consolidation_id",
            "shipment_id",
        ),
    )

    event_id: Mapped[int] = mapped_column(
        ForeignKey("shipment_events.id", ondelete="CASCADE"), primary_key=True
    )
    consolidation_id: Mapped[int] = mapped_column(
        ForeignKey("consolidations.id", ondelete="CASCADE"), nullable=False
    )
    shipment_id: Mapped[int] = mapped_column(
        ForeignKey("shipments.id", ondelete="CASCADE"), nullable=False
    )
