"""Shipment import and the legacy history baseline (RC-UAT-21 Phase A, DEC-0230).

Four new tables; nothing existing is altered (DEC-0181). Revision ``a1c3e5f7b9d2``.

* ``shipment_import_links`` -- which committed import batch created which shipment, from
  which row, under which external reference. The unique ``(source_system,
  external_reference)`` pair is what refuses a second import of the same shipment; the
  unique ``shipment_id`` makes every imported shipment traceable to exactly one batch.
* ``legacy_baselines`` -- one per committed legacy-history import: its batch, the source
  system, an optional cutoff date, and its soft-void state. A baseline is voided as a whole
  (audited, with a reason); nothing is deleted.
* ``legacy_shipments`` -- one historical shipment, **read-only and separate from**
  ``shipments`` on purpose. Because it is another table, no operational queue, quote,
  invoice, master lock, quote expiry, notification or finance report can reach it: none of
  them reads this table. ``active_key`` carries ``source_system|legacy_reference`` while the
  row is live and NULL once voided, so a re-run of the same baseline matches instead of
  duplicating, and a voided baseline can be imported again.
* ``legacy_shipment_events`` -- the dated milestone history of one legacy shipment, in the
  normal event-type vocabulary. Never published, never a notification.

No table here stores the uploaded file. Shipment and recipient values written are the ones
the operator chose to import, exactly as a typed booking would hold them.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

#: Default ``source_system`` for a shipment import that names none.
SHIPMENT_IMPORT_SOURCE = "csv_shipment_import"
#: Default ``source_system`` for a legacy-history baseline that names none.
LEGACY_IMPORT_SOURCE = "legacy_csv"


class ShipmentImportLink(Base):
    """One shipment created by one row of one committed shipment import."""

    __tablename__ = "shipment_import_links"
    __table_args__ = (
        UniqueConstraint("source_system", "external_reference"),
        UniqueConstraint("shipment_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    batch_id: Mapped[int] = mapped_column(
        ForeignKey("import_batches.id", ondelete="CASCADE"), nullable=False, index=True
    )
    #: 1-based spreadsheet row (the header is row 1).
    row_number: Mapped[int] = mapped_column(Integer, nullable=False)
    shipment_id: Mapped[int] = mapped_column(
        ForeignKey("shipments.id", ondelete="CASCADE"), nullable=False
    )
    source_system: Mapped[str] = mapped_column(String(60), nullable=False)
    external_reference: Mapped[str] = mapped_column(String(120), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class LegacyBaseline(Base):
    """One committed legacy-history import, and whether it still stands."""

    __tablename__ = "legacy_baselines"
    __table_args__ = (UniqueConstraint("batch_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    batch_id: Mapped[int] = mapped_column(
        ForeignKey("import_batches.id", ondelete="CASCADE"), nullable=False
    )
    source_system: Mapped[str] = mapped_column(String(60), nullable=False)
    #: Every legacy shipment in the baseline was booked on or before this day, when given.
    cutoff_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    #: ``active`` | ``voided``.
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    created_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    voided_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    voided_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    void_reason: Mapped[str | None] = mapped_column(String(400), nullable=True)


class LegacyShipment(Base):
    """A historical shipment imported as a read-only record (never operational)."""

    __tablename__ = "legacy_shipments"
    __table_args__ = (UniqueConstraint("active_key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    baseline_id: Mapped[int] = mapped_column(
        ForeignKey("legacy_baselines.id", ondelete="CASCADE"), nullable=False, index=True
    )
    row_number: Mapped[int] = mapped_column(Integer, nullable=False)
    customer_id: Mapped[int] = mapped_column(
        ForeignKey("customers.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    source_system: Mapped[str] = mapped_column(String(60), nullable=False)
    legacy_reference: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    #: ``source_system|legacy_reference`` while live; NULL once voided.
    active_key: Mapped[str | None] = mapped_column(String(190), nullable=True)

    route_group: Mapped[str] = mapped_column(String(3), nullable=False)
    direction: Mapped[str] = mapped_column(String(20), nullable=False)
    #: Always ``air`` in this release (sea is out of scope).
    transport_mode: Mapped[str] = mapped_column(String(20), nullable=False, default="air")
    booked_on: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    #: ``delivered`` | ``returned`` | ``cancelled`` | ``lost``.
    final_status: Mapped[str] = mapped_column(String(20), nullable=False)
    completed_on: Mapped[date | None] = mapped_column(Date, nullable=True)

    recipient_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    recipient_city: Mapped[str | None] = mapped_column(String(120), nullable=True)
    recipient_province_state: Mapped[str | None] = mapped_column(String(120), nullable=True)
    recipient_country_code: Mapped[str | None] = mapped_column(String(2), nullable=True)
    package_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_weight_kg: Mapped[Decimal | None] = mapped_column(Numeric(10, 3), nullable=True)
    contents_description: Mapped[str | None] = mapped_column(String(400), nullable=True)
    #: Staff-only note carried over from the old system. Never customer-facing.
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    is_voided: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    voided_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    events: Mapped[list[LegacyShipmentEvent]] = relationship(
        back_populates="legacy_shipment",
        cascade="all, delete-orphan",
        order_by="LegacyShipmentEvent.sequence",
    )


class LegacyShipmentEvent(Base):
    """One dated milestone of a legacy shipment. Never published, never notified."""

    __tablename__ = "legacy_shipment_events"
    __table_args__ = (UniqueConstraint("legacy_shipment_id", "sequence"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    legacy_shipment_id: Mapped[int] = mapped_column(
        ForeignKey("legacy_shipments.id", ondelete="CASCADE"), nullable=False, index=True
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    #: A ``ShipmentEventType`` value (or ``cancelled`` / ``lost`` for a closing record).
    event_type: Mapped[str] = mapped_column(String(40), nullable=False)
    occurred_on: Mapped[date] = mapped_column(Date, nullable=False)

    legacy_shipment: Mapped[LegacyShipment] = relationship(back_populates="events")
