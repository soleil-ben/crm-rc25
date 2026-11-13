"""Booking, package, transport leg, manual event, and label schemas.

Financial visibility is expressed in the *shape* of the response, not by nulling values:
``ShipmentDetail.financials`` is absent for a caller without ``financial:read``, and
``ShipmentFinancialsOut.costs`` is absent without ``financial_cost:read``. A role without
cost permission therefore never receives a cost field at all (CRM.md section 11).
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.core.enums import (
    DimensionUnit,
    LegStatus,
    LegType,
    RouteGroup,
    ServiceType,
    ShipmentDirection,
    ShipmentEventType,
    TrackingSourceMode,
    TransportMode,
    WeightUnit,
)
from app.schemas.common import ApiModel
from app.schemas.consolidation import ConsolidationSummaryOut, ShipmentItemOut
from app.schemas.customer import StaffSummary

# --- Address snapshots ----------------------------------------------------


class AddressSnapshotIn(BaseModel):
    """Either a saved address to copy from, or typed details, or both.

    ``address_id`` seeds the snapshot from the customer's address book; any field set
    alongside it overrides that line. The result is copied into the shipment, so a later
    edit to the address book cannot reach it (AC-5).
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    address_id: int | None = None
    name: str | None = Field(default=None, max_length=200)
    company: str | None = Field(default=None, max_length=200)
    phone_entered: str | None = Field(default=None, max_length=60)
    email: str | None = Field(default=None, max_length=320)
    address_line1: str | None = Field(default=None, max_length=255)
    address_line2: str | None = Field(default=None, max_length=255)
    city: str | None = Field(default=None, max_length=120)
    province_state: str | None = Field(default=None, max_length=120)
    postal_code: str | None = Field(default=None, max_length=30)
    country_code: str | None = Field(default=None, max_length=80)
    country_input: str | None = Field(default=None, max_length=80)
    delivery_note: str | None = Field(default=None, max_length=400)


class AddressSnapshotOut(BaseModel):
    name: str | None
    company: str | None
    phone_entered: str | None
    email: str | None
    address_line1: str | None
    address_line2: str | None
    city: str | None
    province_state: str | None
    postal_code: str | None
    country_code: str | None
    country_input: str | None
    delivery_note: str | None = None
    source_address_id: int | None = None


# --- Packages -------------------------------------------------------------


class PackageIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    length_value: Decimal | None = None
    width_value: Decimal | None = None
    height_value: Decimal | None = None
    dimension_unit: DimensionUnit = DimensionUnit.CM
    weight_value: Decimal | None = None
    weight_unit: WeightUnit = WeightUnit.KG
    contents_summary: str | None = Field(default=None, max_length=400)
    handling_note: str | None = Field(default=None, max_length=200)
    warehouse_location: str | None = Field(default=None, max_length=60)


class PackageUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    length_value: Decimal | None = None
    width_value: Decimal | None = None
    height_value: Decimal | None = None
    dimension_unit: DimensionUnit | None = None
    weight_value: Decimal | None = None
    weight_unit: WeightUnit | None = None
    contents_summary: str | None = Field(default=None, max_length=400)
    handling_note: str | None = Field(default=None, max_length=200)
    warehouse_location: str | None = Field(default=None, max_length=60)


class PackageOut(ApiModel):
    id: int
    shipment_id: int
    sequence: int
    package_reference: str | None
    position_label: str
    is_active: bool
    cancelled_at: datetime | None
    cancellation_reason: str | None
    length_value: Decimal | None
    width_value: Decimal | None
    height_value: Decimal | None
    dimension_unit: str
    length_cm: Decimal | None
    width_cm: Decimal | None
    height_cm: Decimal | None
    weight_value: Decimal | None
    weight_unit: str
    weight_kg: Decimal | None
    contents_summary: str | None
    handling_note: str | None
    warehouse_location: str | None
    operational_state: str
    delivered_to_recipient_at: datetime | None
    created_at: datetime


class PackageProgressOut(BaseModel):
    """Derived from package rows; never a stored counter."""

    total: int
    active: int
    cancelled: int
    delivered: int
    summary: str


class CancelRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    reason: str = Field(min_length=1, max_length=255)


# --- Bookings -------------------------------------------------------------


class ShipmentDraftCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    customer_id: int
    #: Who pays, when not the booking customer (Phase 13B). Omit or repeat customer_id
    #: for "the booking customer pays".
    payer_customer_id: int | None = None
    route_group: RouteGroup
    direction: ShipmentDirection | None = None
    service_type: ServiceType = ServiceType.STANDARD_PARCEL
    transport_mode: TransportMode = TransportMode.UNSPECIFIED
    booking_reference: str | None = Field(default=None, max_length=60)
    contents_description: str | None = Field(default=None, max_length=400)
    declared_value: Decimal | None = None
    declared_value_currency: str | None = Field(default=None, max_length=3)
    estimated_delivery_at: datetime | None = None
    owner_user_id: int | None = None
    internal_notes: str | None = None
    sender: AddressSnapshotIn | None = None
    recipient: AddressSnapshotIn | None = None
    packages: list[PackageIn] = Field(default_factory=list)


class ShipmentUpdate(BaseModel):
    """Draft edits accept anything; after confirmation the route fields are refused."""

    model_config = ConfigDict(str_strip_whitespace=True)

    route_group: RouteGroup | None = None
    payer_customer_id: int | None = None
    direction: ShipmentDirection | None = None
    service_type: ServiceType | None = None
    transport_mode: TransportMode | None = None
    booking_reference: str | None = Field(default=None, max_length=60)
    contents_description: str | None = Field(default=None, max_length=400)
    declared_value: Decimal | None = None
    declared_value_currency: str | None = Field(default=None, max_length=3)
    estimated_delivery_at: datetime | None = None
    owner_user_id: int | None = None
    internal_notes: str | None = None
    sender: AddressSnapshotIn | None = None
    recipient: AddressSnapshotIn | None = None


class ConfirmBookingRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    idempotency_key: str = Field(
        min_length=8,
        max_length=120,
        description=(
            "Client-generated key for this confirmation attempt. Retrying with the same "
            "key returns the original booking; reusing it for different data is a 409."
        ),
    )


class RebookRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    reason: str = Field(min_length=1, max_length=255)
    route_group: RouteGroup | None = None
    direction: ShipmentDirection | None = None
    service_type: ServiceType | None = None
    transport_mode: TransportMode | None = None
    sender: AddressSnapshotIn | None = None
    recipient: AddressSnapshotIn | None = None


class ShipmentFinancialCostsOut(BaseModel):
    """Carrier and direct costs. Present only with ``financial_cost:read``."""

    shipping_cost: Decimal | None
    surcharges_amount: Decimal | None
    #: Selling amount less discount, refund, shipping cost and surcharges, in the
    #: shipment's one currency. ``None`` -- never zero -- when either the selling amount or
    #: the shipping cost is unrecorded, so an unknown figure cannot read as a loss or a
    #: break-even. Lives in the cost block because it discloses the cost (fix pack item 7).
    gross_profit: Decimal | None = None


class ShipmentFinancialsOut(BaseModel):
    """Recorded amounts. Present only with ``financial:read``.

    A missing value means Unknown, never zero, and currencies are never combined.
    """

    currency: str | None
    selling_amount: Decimal | None
    discount_amount: Decimal | None
    refund_amount: Decimal | None
    declared_value: Decimal | None
    declared_value_currency: str | None
    payment_state: str
    #: Omitted from the payload, not sent as ``null``, for a role without
    #: ``financial_cost:read``: the key itself says a cost exists (UAT round 3).
    costs: ShipmentFinancialCostsOut | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    coverage_note: str


class ShipmentFinancialsUpdate(BaseModel):
    currency: str | None = Field(default=None, max_length=3)
    selling_amount: Decimal | None = None
    discount_amount: Decimal | None = None
    refund_amount: Decimal | None = None
    shipping_cost: Decimal | None = None
    surcharges_amount: Decimal | None = None
    payment_state: str | None = None


class CustomerSummary(BaseModel):
    id: int
    public_id: str
    full_name: str
    preferred_language: str


class ShipmentListItem(BaseModel):
    id: int
    public_id: str | None
    booking_reference: str | None
    customer: CustomerSummary | None
    route_group: str
    route_label: str
    direction: str | None
    direction_label: str | None
    booking_state: str
    operational_state: str
    payment_state: str
    service_type: str
    transport_mode: str
    package_progress: PackageProgressOut
    carrier_summary: str | None
    latest_update: str | None
    latest_update_at: datetime | None
    owner: StaffSummary | None
    booking_date: datetime | None
    recipient_name: str | None
    destination_city: str | None
    destination_country_code: str | None
    is_demo_record: bool


class ShipmentDetail(ShipmentListItem):
    sender: AddressSnapshotOut
    recipient: AddressSnapshotOut
    contents_description: str | None
    estimated_delivery_at: datetime | None
    first_handoff_at: datetime | None
    delivered_at: datetime | None
    confirmed_at: datetime | None
    cancelled_at: datetime | None
    cancellation_reason: str | None
    rebooked_from_shipment_id: int | None
    rebooked_to_shipment_id: int | None
    rebooked_from_public_id: str | None = None
    rebooked_to_public_id: str | None = None
    route_is_locked: bool
    internal_notes: str | None = None
    packages: list[PackageOut] = Field(default_factory=list)
    financials: ShipmentFinancialsOut | None = None
    #: Phase 13B. None when the booking customer pays.
    payer: CustomerSummary | None = None
    #: Phase 13B. The master this shipment rides in, if any.
    consolidation: ConsolidationSummaryOut | None = None
    items: list[ShipmentItemOut] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class ConfirmBookingResponse(BaseModel):
    shipment: ShipmentDetail
    created: bool = Field(
        description="False when an idempotent retry returned the original booking."
    )
    id_generation_attempts: int


# --- Transport legs -------------------------------------------------------


class LegIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    leg_type: LegType
    sequence: int | None = None
    provider_name: str | None = Field(default=None, max_length=80)
    service_display: str | None = Field(default=None, max_length=120)
    origin_label: str | None = Field(default=None, max_length=160)
    origin_country_code: str | None = Field(default=None, max_length=80)
    destination_label: str | None = Field(default=None, max_length=160)
    destination_country_code: str | None = Field(default=None, max_length=80)
    is_final_recipient_delivery: bool = False
    consolidation_reference: str | None = Field(default=None, max_length=60)
    status: LegStatus = LegStatus.PLANNED
    scheduled_at: datetime | None = None
    internal_notes: str | None = None
    package_ids: list[int] = Field(default_factory=list)


class LegUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    sequence: int | None = None
    provider_name: str | None = Field(default=None, max_length=80)
    service_display: str | None = Field(default=None, max_length=120)
    origin_label: str | None = Field(default=None, max_length=160)
    origin_country_code: str | None = Field(default=None, max_length=80)
    destination_label: str | None = Field(default=None, max_length=160)
    destination_country_code: str | None = Field(default=None, max_length=80)
    is_final_recipient_delivery: bool | None = None
    consolidation_reference: str | None = Field(default=None, max_length=60)
    status: LegStatus | None = None
    scheduled_at: datetime | None = None
    internal_notes: str | None = None
    package_ids: list[int] | None = None


class TrackingReferenceIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    carrier_name: str = Field(min_length=1, max_length=80)
    tracking_number: str = Field(min_length=1, max_length=120)
    public_url: str | None = Field(default=None, max_length=500)
    source_mode: TrackingSourceMode = TrackingSourceMode.MANUAL
    package_id: int | None = None


class TrackingReferenceOut(ApiModel):
    id: int
    leg_id: int
    package_id: int | None
    package_reference: str | None = None
    carrier_name: str
    tracking_number: str
    public_url: str | None
    source_mode: str
    source_mode_label: str
    is_active: bool
    retired_at: datetime | None
    retired_reason: str | None
    created_at: datetime


class LegOut(ApiModel):
    id: int
    shipment_id: int
    sequence: int
    leg_type: str
    leg_type_label: str
    #: The leg's generic tracking name as customers read it (``master_tracking`` or
    #: ``last_mile_tracking``, DEC-0224); staff see it next to the stored provider (RC-20).
    tracking_name_key: str
    provider_name: str | None
    service_display: str | None
    origin_label: str | None
    origin_country_code: str | None
    destination_label: str | None
    destination_country_code: str | None
    is_final_recipient_delivery: bool
    consolidation_reference: str | None
    status: str
    scheduled_at: datetime | None
    completed_at: datetime | None
    internal_notes: str | None
    package_ids: list[int] = Field(default_factory=list)
    package_references: list[str] = Field(default_factory=list)
    tracking_references: list[TrackingReferenceOut] = Field(default_factory=list)


# --- Manual operational events --------------------------------------------


class EventIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    event_type: ShipmentEventType
    occurred_at: datetime | None = None
    package_id: int | None = None
    leg_id: int | None = None
    location_label: str | None = Field(default=None, max_length=160)
    location_country_code: str | None = Field(default=None, max_length=80)
    internal_detail: str | None = None
    is_public_update: bool = False
    public_update_text: str | None = Field(default=None, max_length=400)
    #: An approved template key, rendered per reader language on the tracking page. Supply
    #: this *or* ``public_update_text``, never both (DEC-0084).
    public_update_template_key: str | None = Field(default=None, max_length=80)
    is_final_recipient_delivery: bool = False


class EventOut(ApiModel):
    id: int
    shipment_id: int
    package_id: int | None
    package_reference: str | None = None
    leg_id: int | None
    event_type: str
    event_type_label: str
    operational_state: str
    occurred_at: datetime
    recorded_at: datetime
    location_label: str | None
    location_country_code: str | None
    internal_detail: str | None
    is_public_update: bool
    public_update_text: str | None
    public_update_template_key: str | None = None
    #: The template rendered in the staff portal's default language, so a staff member
    #: reading the timeline sees the sentence rather than a key. ``None`` for free text.
    public_update_template_text: str | None = None
    is_final_recipient_delivery: bool
    source: str
    is_voided: bool
    voided_reason: str | None
    recorded_by: StaffSummary | None = None


class EventEditIn(BaseModel):
    """Correct one recorded event (RC-UAT-25 item 6): the rows of the recording and the full
    corrected state. ``occurred_at`` omitted keeps it; ``package_ids`` empty means every active
    package, as when recording. Publishing cannot change here (``event_service.edit_event``)."""

    model_config = ConfigDict(str_strip_whitespace=True)

    event_ids: list[int] = Field(min_length=1, max_length=200)
    event_type: ShipmentEventType
    occurred_at: datetime | None = None
    package_ids: list[int] = Field(default_factory=list, max_length=200)
    leg_id: int | None = None
    location_label: str | None = Field(default=None, max_length=160)
    location_country_code: str | None = Field(default=None, max_length=80)
    internal_detail: str | None = None
    public_update_template_key: str | None = Field(default=None, max_length=80)
    public_update_text: str | None = Field(default=None, max_length=400)
    reason: str = Field(max_length=255)


class EventRevisionOut(ApiModel):
    """One edit of a timeline event: what the fields said before and after, and why."""

    id: int
    shipment_id: int
    event_ids_before: list[int]
    event_ids_after: list[int]
    before: dict
    after: dict
    reason: str
    was_published: bool
    public_wording_changed: bool
    edited_at: datetime
    edited_by: StaffSummary | None = None


# --- Labels ---------------------------------------------------------------


class LabelPreviewLabel(BaseModel):
    package_id: int
    package_reference: str
    position_label: str
    shipment_public_id: str
    route_code: str
    route_name: str
    direction_label: str
    booking_date: str
    recipient_name: str
    destination_lines: list[str]
    weight_display: str | None
    handling_note: str | None
    warehouse_location: str | None
    tracking_url: str
    warning: str
    wordmark: str
    has_approved_logo: bool


class LabelPreviewOut(BaseModel):
    shipment_id: int
    shipment_public_id: str | None
    page_width_pt: float
    page_height_pt: float
    print_instruction: str
    tracking_base_url: str
    labels: list[LabelPreviewLabel]


class LabelJobOut(ApiModel):
    id: int
    shipment_id: int
    kind: str
    is_reprint: bool
    page_count: int
    document_sha256: str | None
    generated_at: datetime
    generated_by: StaffSummary | None = None
    package_references: list[str] = Field(default_factory=list)


# --- Reference lookup -----------------------------------------------------


class ReferenceLookupOut(BaseModel):
    kind: str
    matched_value: str
    shipment_id: int
    shipment_public_id: str | None
    package_id: int | None
    package_reference: str | None
    customer_id: int
