"""Shipment, package, transport leg, manual event, and label records.

Phase 1 created ``shipments`` with only the columns its derivation rules needed. Phase 2
**extends** that table with booking reference, sender and recipient address snapshots,
declared value, and the cancel/rebook links, and adds the child tables the booking
workflow needs (DEC-0009, DEC-0030).

Three state dimensions stay independent throughout: booking state, operational state,
and payment state. Package progress and the overall operational state are *derived* from
package rows and manual events rather than stored in a counter, for the same reason
customer activity is derived (CRM.md section 4).
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import (
    BookingState,
    DimensionUnit,
    LabelJobKind,
    LegStatus,
    OperationalState,
    PaymentState,
    ServiceType,
    TrackingSourceMode,
    TransportMode,
    WeightUnit,
)
from app.models.base import Base, TimestampMixin


class Shipment(TimestampMixin, Base):
    __tablename__ = "shipments"
    __table_args__ = (
        UniqueConstraint("public_id", name="uq_shipments_public_id"),
        UniqueConstraint("idempotency_key", name="uq_shipments_idempotency_key"),
        Index("ix_shipments_customer_id_first_handoff_at", "customer_id", "first_handoff_at"),
        Index("ix_shipments_booking_state_operational_state", "booking_state", "operational_state"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    # Customer-facing Solaris Shipment ID. NULL until a booking is confirmed, so drafts
    # never expose a customer-facing identifier (CRM.md section 6).
    public_id: Mapped[str | None] = mapped_column(String(30), nullable=True, index=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(120), nullable=True)

    customer_id: Mapped[int] = mapped_column(
        ForeignKey("customers.id", ondelete="RESTRICT"), nullable=False, index=True
    )

    route_group: Mapped[str] = mapped_column(String(3), nullable=False, index=True)
    direction: Mapped[str | None] = mapped_column(String(20), nullable=True)
    service_type: Mapped[str] = mapped_column(
        String(30), nullable=False, default=ServiceType.STANDARD_PARCEL
    )
    transport_mode: Mapped[str] = mapped_column(
        String(20), nullable=False, default=TransportMode.UNSPECIFIED
    )

    # Three independent state fields; never overloaded into one column (CRM.md section 7).
    booking_state: Mapped[str] = mapped_column(
        String(20), nullable=False, default=BookingState.DRAFT, index=True
    )
    operational_state: Mapped[str] = mapped_column(
        String(30), nullable=False, default=OperationalState.BOOKED, index=True
    )
    payment_state: Mapped[str] = mapped_column(
        String(20), nullable=False, default=PaymentState.UNRECORDED
    )

    origin_country_code: Mapped[str | None] = mapped_column(String(2), nullable=True)
    origin_city: Mapped[str | None] = mapped_column(String(120), nullable=True)
    destination_country_code: Mapped[str | None] = mapped_column(String(2), nullable=True)
    destination_city: Mapped[str | None] = mapped_column(String(120), nullable=True)

    # --- Phase 2: booking reference and address snapshots ------------------
    # Snapshots are copied from the address book at draft/confirmation time and are
    # never rewritten when the address-book entry is edited afterwards (AC-5). The
    # *_address_id columns record provenance only; the snapshot is authoritative.
    booking_reference: Mapped[str | None] = mapped_column(String(60), nullable=True)

    sender_address_id: Mapped[int | None] = mapped_column(
        ForeignKey("customer_addresses.id", ondelete="SET NULL"), nullable=True
    )
    sender_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    sender_company: Mapped[str | None] = mapped_column(String(200), nullable=True)
    sender_phone_entered: Mapped[str | None] = mapped_column(String(60), nullable=True)
    sender_phone_e164: Mapped[str | None] = mapped_column(String(30), nullable=True)
    sender_email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    sender_address_line1: Mapped[str | None] = mapped_column(String(255), nullable=True)
    sender_address_line2: Mapped[str | None] = mapped_column(String(255), nullable=True)
    sender_city: Mapped[str | None] = mapped_column(String(120), nullable=True)
    sender_province_state: Mapped[str | None] = mapped_column(String(120), nullable=True)
    sender_postal_code: Mapped[str | None] = mapped_column(String(30), nullable=True)
    sender_country_code: Mapped[str | None] = mapped_column(String(2), nullable=True)
    # What the staff member typed for the country, kept alongside the normalized code.
    sender_country_input: Mapped[str | None] = mapped_column(String(80), nullable=True)

    recipient_address_id: Mapped[int | None] = mapped_column(
        ForeignKey("customer_addresses.id", ondelete="SET NULL"), nullable=True
    )
    recipient_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    recipient_company: Mapped[str | None] = mapped_column(String(200), nullable=True)
    recipient_phone_entered: Mapped[str | None] = mapped_column(String(60), nullable=True)
    recipient_phone_e164: Mapped[str | None] = mapped_column(String(30), nullable=True)
    recipient_email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    recipient_address_line1: Mapped[str | None] = mapped_column(String(255), nullable=True)
    recipient_address_line2: Mapped[str | None] = mapped_column(String(255), nullable=True)
    recipient_city: Mapped[str | None] = mapped_column(String(120), nullable=True)
    recipient_province_state: Mapped[str | None] = mapped_column(String(120), nullable=True)
    recipient_postal_code: Mapped[str | None] = mapped_column(String(30), nullable=True)
    recipient_country_code: Mapped[str | None] = mapped_column(String(2), nullable=True)
    recipient_country_input: Mapped[str | None] = mapped_column(String(80), nullable=True)
    recipient_delivery_note: Mapped[str | None] = mapped_column(String(400), nullable=True)

    # Declared value is separate from the selling amount: it describes the goods, not
    # what the customer paid. No customs classification is derived from it.
    declared_value: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    declared_value_currency: Mapped[str | None] = mapped_column(String(3), nullable=True)

    booking_date: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # First physical handoff/custody timestamp: the qualifying-shipment trigger.
    first_handoff_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    estimated_delivery_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    cancellation_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Denormalized count of active packages, maintained inside the same transaction as
    # every package change. Delivered progress is *derived* from package rows so there is
    # only one source of truth for it (DEC-0030).
    package_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    contents_description: Mapped[str | None] = mapped_column(String(400), nullable=True)

    # Returns stay linked but do not count as another outbound purchase (CRM.md section 4).
    is_return: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    return_of_shipment_id: Mapped[int | None] = mapped_column(
        ForeignKey("shipments.id", ondelete="SET NULL"), nullable=True
    )
    # Cancel-and-rebook keeps both records and the link between them. The original ID
    # never changes meaning and is never reused (CRM.md section 6).
    rebooked_from_shipment_id: Mapped[int | None] = mapped_column(
        ForeignKey("shipments.id", ondelete="SET NULL"), nullable=True
    )
    rebooked_to_shipment_id: Mapped[int | None] = mapped_column(
        ForeignKey("shipments.id", ondelete="SET NULL"), nullable=True
    )
    cancelled_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    confirmed_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    # Optional, manually entered, permission-controlled financials. NULL means Unknown,
    # never zero (CRM.md section 12, AC-17).
    currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    selling_amount: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    shipping_cost: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    surcharges_amount: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    discount_amount: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    refund_amount: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)

    owner_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    internal_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    source_system: Mapped[str | None] = mapped_column(String(60), nullable=True)
    source_record_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    is_demo_record: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)

    packages: Mapped[list[ShipmentPackage]] = relationship(
        back_populates="shipment",
        cascade="all, delete-orphan",
        order_by="ShipmentPackage.sequence",
    )
    legs: Mapped[list[ShipmentLeg]] = relationship(
        back_populates="shipment",
        cascade="all, delete-orphan",
        order_by="ShipmentLeg.sequence",
    )
    events: Mapped[list[ShipmentEvent]] = relationship(
        back_populates="shipment",
        cascade="all, delete-orphan",
        order_by="ShipmentEvent.occurred_at",
    )

    @property
    def route_is_locked(self) -> bool:
        """Route group and route-defining direction lock once a booking is confirmed."""
        return self.booking_state != BookingState.DRAFT

    @property
    def is_qualifying(self) -> bool:
        """A qualifying shipment per CRM.md section 4.

        Outbound, confirmed, with a first physical handoff, not cancelled or voided.
        Drafts and label-only records do not qualify; returns are excluded by default.
        """
        return (
            self.booking_state == BookingState.CONFIRMED
            and self.first_handoff_at is not None
            and self.cancelled_at is None
            and not self.is_return
        )


class BookingConfirmation(Base):
    """One row per confirmed booking: the concurrency and idempotency claim.

    SQLite has no ``SELECT ... FOR UPDATE``, so confirmation is serialized by database
    uniqueness instead of row locks (DEC-0031):

    * ``shipment_id`` unique — a draft can be confirmed exactly once, which is what stops
      a double-click or two concurrent requests from producing two bookings;
    * ``idempotency_key`` unique — a retried request finds the original confirmation and
      returns the original shipment;
    * ``request_fingerprint`` — reusing one key for materially different booking data is
      a conflict, not a silent return of an unrelated booking.
    """

    __tablename__ = "booking_confirmations"
    __table_args__ = (
        UniqueConstraint("shipment_id", name="uq_booking_confirmations_shipment_id"),
        UniqueConstraint("idempotency_key", name="uq_booking_confirmations_idempotency_key"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    shipment_id: Mapped[int] = mapped_column(
        ForeignKey("shipments.id", ondelete="CASCADE"), nullable=False
    )
    idempotency_key: Mapped[str] = mapped_column(String(120), nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    public_id: Mapped[str] = mapped_column(String(30), nullable=False)
    confirmed_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    confirmed_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    generation_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class ShipmentPackage(TimestampMixin, Base):
    """One physical package.

    Both the entered measurement and its canonical value are stored (CRM.md section 7).
    Measurements and money use ``Numeric``/``Decimal`` so comparison and rounding are
    exact rather than binary-float approximations.

    A package reference such as ``SX-VCA-7K9D2M4R8T6W-01`` is stable for the life of the
    record: cancelling a package or reprinting its label never changes or reuses it.
    """

    __tablename__ = "shipment_packages"
    __table_args__ = (
        UniqueConstraint("package_reference", name="uq_shipment_packages_package_reference"),
        UniqueConstraint(
            "shipment_id", "sequence", name="uq_shipment_packages_shipment_id_sequence"
        ),
        # A supplied measurement must be positive; NULL means "not recorded".
        CheckConstraint(
            "(length_cm IS NULL OR length_cm > 0) AND (width_cm IS NULL OR width_cm > 0)"
            " AND (height_cm IS NULL OR height_cm > 0) AND (weight_kg IS NULL OR weight_kg > 0)",
            name="positive_measurements",
        ),
        Index("ix_shipment_packages_shipment_id_is_active", "shipment_id", "is_active"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    shipment_id: Mapped[int] = mapped_column(
        ForeignKey("shipments.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Stable sequence: the "-01" in the reference and the "Package 1 of 3" position.
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    # NULL until the parent booking is confirmed, so a draft exposes no public reference.
    package_reference: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    cancellation_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Entered values plus their original unit.
    length_value: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    width_value: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    height_value: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    dimension_unit: Mapped[str] = mapped_column(String(4), nullable=False, default=DimensionUnit.CM)
    # Canonical centimetres, derived once on write.
    length_cm: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    width_cm: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    height_cm: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)

    weight_value: Mapped[float | None] = mapped_column(Numeric(10, 3), nullable=True)
    weight_unit: Mapped[str] = mapped_column(String(4), nullable=False, default=WeightUnit.KG)
    weight_kg: Mapped[float | None] = mapped_column(Numeric(10, 3), nullable=True)

    contents_summary: Mapped[str | None] = mapped_column(String(400), nullable=True)
    handling_note: Mapped[str | None] = mapped_column(String(200), nullable=True)
    warehouse_location: Mapped[str | None] = mapped_column(String(60), nullable=True)

    # Derived from this package's manual events and written back so list queries stay
    # cheap; ``event_service`` is the only writer.
    operational_state: Mapped[str] = mapped_column(
        String(30), nullable=False, default=OperationalState.BOOKED
    )
    delivered_to_recipient_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    created_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    shipment: Mapped[Shipment] = relationship(back_populates="packages")
    leg_links: Mapped[list[ShipmentLegPackage]] = relationship(
        back_populates="package", cascade="all, delete-orphan"
    )


class ShipmentLeg(TimestampMixin, Base):
    """An ordered transport leg (CRM.md section 7).

    Carrier references live on ``LegTrackingReference`` rather than a single
    ``tracking_number`` column, so one package can carry several sequential references
    and a voided one is retired instead of overwritten.
    """

    __tablename__ = "shipment_legs"
    __table_args__ = (
        UniqueConstraint("shipment_id", "sequence", name="uq_shipment_legs_shipment_id_sequence"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    shipment_id: Mapped[int] = mapped_column(
        ForeignKey("shipments.id", ondelete="CASCADE"), nullable=False, index=True
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    leg_type: Mapped[str] = mapped_column(String(30), nullable=False)

    # Display fields only. Selecting a carrier name never implies an integration exists.
    provider_name: Mapped[str | None] = mapped_column(String(80), nullable=True)
    service_display: Mapped[str | None] = mapped_column(String(120), nullable=True)

    origin_label: Mapped[str | None] = mapped_column(String(160), nullable=True)
    origin_country_code: Mapped[str | None] = mapped_column(String(2), nullable=True)
    destination_label: Mapped[str | None] = mapped_column(String(160), nullable=True)
    destination_country_code: Mapped[str | None] = mapped_column(String(2), nullable=True)

    # Whether completing this leg means the parcel reached the final consignee. A leg
    # ending at a Solaris warehouse is false, which is what keeps an intermediate
    # delivery from marking a Vietnam-bound shipment Delivered (CRM.md section 7).
    is_final_recipient_delivery: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    consolidation_reference: Mapped[str | None] = mapped_column(String(60), nullable=True)

    status: Mapped[str] = mapped_column(String(20), nullable=False, default=LegStatus.PLANNED)
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    internal_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    shipment: Mapped[Shipment] = relationship(back_populates="legs")
    package_links: Mapped[list[ShipmentLegPackage]] = relationship(
        back_populates="leg", cascade="all, delete-orphan"
    )
    tracking_references: Mapped[list[LegTrackingReference]] = relationship(
        back_populates="leg", cascade="all, delete-orphan"
    )


class ShipmentLegPackage(Base):
    """Which packages travel on which leg."""

    __tablename__ = "shipment_leg_packages"
    __table_args__ = (
        UniqueConstraint("leg_id", "package_id", name="uq_shipment_leg_packages_leg_id_package_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    leg_id: Mapped[int] = mapped_column(
        ForeignKey("shipment_legs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    package_id: Mapped[int] = mapped_column(
        ForeignKey("shipment_packages.id", ondelete="CASCADE"), nullable=False, index=True
    )

    leg: Mapped[ShipmentLeg] = relationship(back_populates="package_links")
    package: Mapped[ShipmentPackage] = relationship(back_populates="leg_links")


class LegTrackingReference(TimestampMixin, Base):
    """A carrier tracking reference placeholder.

    Phase 2 stores what staff type and, optionally, a validated public carrier link. No
    provider is contacted: ``source_mode`` is restricted to manual or external-link until
    Phase 4 verifies a real account (``docs/INTEGRATIONS.md``). A superseded reference is
    retired, never overwritten, so the audit trail survives a relabel.
    """

    __tablename__ = "leg_tracking_references"
    __table_args__ = (Index("ix_leg_tracking_references_leg_id_is_active", "leg_id", "is_active"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    leg_id: Mapped[int] = mapped_column(
        ForeignKey("shipment_legs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # NULL means the reference covers the whole leg (a consolidated master reference).
    package_id: Mapped[int | None] = mapped_column(
        ForeignKey("shipment_packages.id", ondelete="SET NULL"), nullable=True, index=True
    )

    carrier_name: Mapped[str] = mapped_column(String(80), nullable=False)
    tracking_number: Mapped[str] = mapped_column(String(120), nullable=False)
    public_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    source_mode: Mapped[str] = mapped_column(
        String(20), nullable=False, default=TrackingSourceMode.MANUAL
    )

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    retired_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    retired_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)

    created_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    leg: Mapped[ShipmentLeg] = relationship(back_populates="tracking_references")


class ShipmentEvent(Base):
    """A manually recorded operational event.

    ``occurred_at`` (when it happened) and ``recorded_at`` (when staff entered it) are
    stored separately, so a late entry cannot masquerade as a fresh scan.

    ``internal_detail`` is never customer-facing. A public update requires the separate
    ``is_public_update`` flag *and* its own text, so an internal note can never leak into
    a tracking timeline (CRM.md section 10).
    """

    __tablename__ = "shipment_events"
    __table_args__ = (
        Index("ix_shipment_events_shipment_id_occurred_at", "shipment_id", "occurred_at"),
        Index("ix_shipment_events_package_id_occurred_at", "package_id", "occurred_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    shipment_id: Mapped[int] = mapped_column(
        ForeignKey("shipments.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # NULL means the event applies to every active package on the shipment.
    package_id: Mapped[int | None] = mapped_column(
        ForeignKey("shipment_packages.id", ondelete="CASCADE"), nullable=True
    )
    leg_id: Mapped[int | None] = mapped_column(
        ForeignKey("shipment_legs.id", ondelete="SET NULL"), nullable=True
    )

    event_type: Mapped[str] = mapped_column(String(40), nullable=False)
    operational_state: Mapped[str] = mapped_column(String(30), nullable=False)

    occurred_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    location_label: Mapped[str | None] = mapped_column(String(160), nullable=True)
    location_country_code: Mapped[str | None] = mapped_column(String(2), nullable=True)

    internal_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_public_update: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    public_update_text: Mapped[str | None] = mapped_column(String(400), nullable=True)
    # An approved template key instead of a typed sentence, so the tracking page can render
    # the milestone in whichever language the customer chose rather than the language the
    # staff member happened to be working in (DEC-0084). Mutually exclusive with
    # ``public_update_text``: an event carries one or the other, never both.
    public_update_template_key: Mapped[str | None] = mapped_column(String(80), nullable=True)

    # Only a true final-recipient completion may close a package.
    is_final_recipient_delivery: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )

    # Phase 2 records manual events only; provider sources arrive in Phase 4.
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="manual")

    # Corrections void an event rather than deleting it, preserving audit history.
    is_voided: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    voided_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    voided_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)

    recorded_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    shipment: Mapped[Shipment] = relationship(back_populates="events")


class LabelPrintJob(Base):
    """A record that label PDFs were generated and downloaded.

    This records *generation*, not printing: nothing here claims a physical printer
    produced a label, because no print system reports back (CRM.md section 8).
    """

    __tablename__ = "label_print_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    shipment_id: Mapped[int] = mapped_column(
        ForeignKey("shipments.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(String(20), nullable=False, default=LabelJobKind.ALL_ACTIVE)
    is_reprint: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    page_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    document_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    generated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    generated_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    package_links: Mapped[list[LabelPrintJobPackage]] = relationship(
        back_populates="job", cascade="all, delete-orphan"
    )


class LabelPrintJobPackage(Base):
    """Which package appeared on which generated label sheet."""

    __tablename__ = "label_print_job_packages"
    __table_args__ = (
        UniqueConstraint(
            "job_id", "package_id", name="uq_label_print_job_packages_job_id_package_id"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[int] = mapped_column(
        ForeignKey("label_print_jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    package_id: Mapped[int] = mapped_column(
        ForeignKey("shipment_packages.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # The reference as printed, so a reprint can be proven to carry the same identifier.
    package_reference: Mapped[str] = mapped_column(String(40), nullable=False)

    job: Mapped[LabelPrintJob] = relationship(back_populates="package_links")
