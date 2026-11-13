"""Staff-facing consolidation and commodity-item schemas (Phase 13B).

Internal. These models are returned only by routes on the staff router; the vendor's
booking reference and the master weights are vendor cost data by another name and never
reach the public or Customer Account routers (``tests/test_consolidations.py`` asserts it).
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.core.enums import ConsolidationState, ShipmentEventType, SolarisService, TariffOrigin


class ConsolidationModel(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")


class ConsolidationCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    solaris_service: SolarisService
    origin: TariffOrigin
    vendor_reference: str | None = Field(default=None, max_length=60)
    actual_weight_kg: Decimal | None = None
    length_cm: Decimal | None = None
    width_cm: Decimal | None = None
    height_cm: Decimal | None = None
    carton_count: int = Field(default=1, ge=1, le=999)
    cutoff_at: datetime | None = None
    handed_over_at: datetime | None = None
    internal_notes: str | None = Field(default=None, max_length=4000)


class ConsolidationUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    solaris_service: SolarisService | None = None
    origin: TariffOrigin | None = None
    vendor_reference: str | None = Field(default=None, max_length=60)
    actual_weight_kg: Decimal | None = None
    length_cm: Decimal | None = None
    width_cm: Decimal | None = None
    height_cm: Decimal | None = None
    carton_count: int | None = Field(default=None, ge=1, le=999)
    cutoff_at: datetime | None = None
    handed_over_at: datetime | None = None
    internal_notes: str | None = Field(default=None, max_length=4000)


class MemberShipmentOut(ConsolidationModel):
    shipment_id: int
    public_id: str | None
    customer_public_id: str | None
    customer_name: str | None
    booking_state: str
    operational_state: str
    package_count: int
    added_at: datetime


class ConsolidationSummaryOut(ConsolidationModel):
    """The few facts a shipment page shows about the master it rides in."""

    id: int
    public_id: str
    state: str
    solaris_service: str
    origin: str
    vendor_reference: str | None


class ConsolidationOut(ConsolidationModel):
    id: int
    public_id: str
    vendor_key: str
    solaris_service: str
    solaris_service_label: str
    origin: str
    state: str
    vendor_reference: str | None
    tariff_version_public_id: str | None
    vendor_product_code: str | None
    actual_weight_kg: Decimal | None
    length_cm: Decimal | None
    width_cm: Decimal | None
    height_cm: Decimal | None
    carton_count: int
    dim_divisor: int | None
    volumetric_weight_kg: Decimal | None
    chargeable_weight_kg: Decimal | None
    handed_over_at: datetime | None
    cutoff_at: datetime | None
    booked_at: datetime | None
    completed_at: datetime | None
    cancelled_at: datetime | None
    cancellation_reason: str | None
    internal_notes: str | None
    member_count: int
    created_at: datetime
    updated_at: datetime
    #: Owner decision 8: ``locked`` (booked or completed, no open unlock), ``lockable`` (the
    #: state locks items and fees) and the open ``unlock`` (id, reason, when, by whom).
    edit_lock: EditLockOut | None = None


class ConsolidationDetailOut(ConsolidationOut):
    members: list[MemberShipmentOut]


class ConsolidationListOut(ConsolidationModel):
    items: list[ConsolidationOut]
    total: int


class MemberAddIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    shipment_id: int


class EditUnlockOut(BaseModel):
    id: int
    reason: str
    unlocked_at: datetime
    unlocked_by_user_id: int | None


class EditLockOut(BaseModel):
    locked: bool
    lockable: bool
    unlock: EditUnlockOut | None


class UnlockIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1, max_length=400)


class RelockIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str | None = Field(default=None, max_length=400)


class ReasonIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    reason: str = Field(min_length=1, max_length=255)


class MasterEventIn(BaseModel):
    """A milestone recorded once on the master, inherited by every member shipment."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    event_type: ShipmentEventType
    occurred_at: datetime | None = None
    location_label: str | None = Field(default=None, max_length=160)
    location_country_code: str | None = Field(default=None, max_length=2)
    internal_detail: str | None = Field(default=None, max_length=2000)
    is_public_update: bool = False
    public_update_text: str | None = Field(default=None, max_length=400)
    public_update_template_key: str | None = Field(default=None, max_length=80)


class MasterEventResultOut(ConsolidationModel):
    event_type: str
    occurred_at: datetime
    applied: list[str]
    duplicates: list[str]
    refused: list[dict[str, str]]


class ShipmentItemIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    description: str = Field(min_length=1, max_length=300)
    quantity: Decimal = Field(default=Decimal(1), gt=0)
    unit: str = Field(default="piece", max_length=20)
    weight_kg: Decimal | None = Field(default=None, gt=0)
    declared_value: Decimal | None = Field(default=None, ge=0)
    declared_value_currency: str | None = Field(default=None, min_length=3, max_length=3)
    package_id: int | None = None
    notes: str | None = Field(default=None, max_length=400)


class ShipmentItemUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    description: str | None = Field(default=None, min_length=1, max_length=300)
    quantity: Decimal | None = Field(default=None, gt=0)
    unit: str | None = Field(default=None, max_length=20)
    weight_kg: Decimal | None = Field(default=None, gt=0)
    declared_value: Decimal | None = Field(default=None, ge=0)
    declared_value_currency: str | None = Field(default=None, min_length=3, max_length=3)
    package_id: int | None = None
    notes: str | None = Field(default=None, max_length=400)


class ShipmentItemOut(ConsolidationModel):
    id: int
    sequence: int
    description: str
    quantity: Decimal
    unit: str
    weight_kg: Decimal | None
    declared_value: Decimal | None
    declared_value_currency: str | None
    package_id: int | None
    is_active: bool
    notes: str | None


__all__ = [
    "ConsolidationCreate",
    "ConsolidationDetailOut",
    "ConsolidationListOut",
    "ConsolidationOut",
    "ConsolidationState",
    "ConsolidationSummaryOut",
    "ConsolidationUpdate",
    "MasterEventIn",
    "MasterEventResultOut",
    "MemberAddIn",
    "MemberShipmentOut",
    "ReasonIn",
    "ShipmentItemIn",
    "ShipmentItemOut",
    "ShipmentItemUpdate",
]
