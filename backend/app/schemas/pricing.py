"""Staff-facing pricing schemas (Phase 13C).

**Internal.** These carry vendor cost and margin beside the customer price. They are returned
only by staff routes behind ``tariff:read`` and the financial permissions; nothing in this
module is imported by the public or Customer Account routers.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.shipment import AddressSnapshotIn


class PricingModel(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")


class PricingSettingsOut(PricingModel):
    air_standard_default_rate_cad: Decimal
    air_express_default_rate_cad: Decimal | None
    trigger_share_numerator: int
    trigger_share_denominator: int
    defaults_owner_confirmed: bool
    vendor_delivery_postal_code: str
    updated_at: datetime
    #: The markup on a surcharge with no policy of its own (owner, 2026-10-20: 2 %).
    default_markup_kind: str = "percent"
    default_markup_value: Decimal = Decimal("2.00")
    #: Owner, 2026-11-03: the default markup is kept but prices under the RC-UAT-25 method
    #: only; OD-74 is retired for the confirmed method (markup = the method setting, 0).
    default_markup_label: str = "RC25 method only"
    default_markup_in_effect: bool = False


class PricingSettingsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    air_standard_default_rate_cad: Decimal | None = Field(default=None, gt=0)
    air_express_default_rate_cad: Decimal | None = Field(default=None, gt=0)
    trigger_share_numerator: int | None = Field(default=None, ge=1)
    trigger_share_denominator: int | None = Field(default=None, ge=1)
    defaults_owner_confirmed: bool | None = None
    vendor_delivery_postal_code: str | None = Field(default=None, max_length=7)
    default_markup_kind: str | None = Field(default=None, max_length=20)
    default_markup_value: Decimal | None = Field(default=None, ge=0, le=100)


class SurchargePolicyOut(PricingModel):
    section: str
    stt: int
    markup_kind: str
    markup_value: Decimal
    scope_override: str | None
    note: str | None
    updated_at: datetime


class SurchargePolicyIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: None = inherit the default markup (OD-74)
    markup_kind: str | None = Field(default=None, max_length=20)
    markup_value: Decimal = Decimal(0)
    scope_override: str | None = Field(default=None, max_length=20)
    note: str | None = Field(default=None, max_length=400)


#: The largest VND amount a fee line stores (``shipment_fee_lines.manual_unit_price_vnd`` is
#: Numeric(14, 2)).
MAX_VND_AMOUNT = Decimal("999999999999")
#: The largest customer price (CAD) a line stores (``fee_line_manual_prices.customer_price_cad``
#: is Numeric(12, 2)).
MAX_CAD_PRICE = Decimal("9999999999.99")


class FeeLineIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    item_id: int
    section: str = Field(max_length=20)
    stt: int = Field(ge=1)
    quantity: Decimal = Field(default=Decimal(1), gt=0)
    weight_kg: Decimal | None = Field(default=None, gt=0)
    #: The vendor's quoted unit price (VND) for a manual-quote rule (OD-56); the line's amount
    #: for a rule quoted case by case. Finite, at most what Numeric(14, 2) holds; the service
    #: rounds to the cent before requiring it to be more than zero.
    manual_unit_price_vnd: Decimal | None = Field(
        default=None, gt=0, le=MAX_VND_AMOUNT, allow_inf_nan=False
    )
    #: The customer price (CAD) of a line quoted case by case (DEC-0228); refused on any other
    #: rule. Same rules as the VND amount, capped at what Numeric(12, 2) holds.
    customer_price_cad: Decimal | None = Field(
        default=None, gt=0, le=MAX_CAD_PRICE, allow_inf_nan=False
    )


class FeeLineAmountIn(BaseModel):
    """The vendor's cost (VND) and/or the customer price (CAD) for a line quoted case by case
    (DEC-0225, DEC-0228). At least one; an explicit null is refused (nothing is cleared)."""

    model_config = ConfigDict(extra="forbid")

    manual_unit_price_vnd: Decimal | None = Field(
        default=None, gt=0, le=MAX_VND_AMOUNT, allow_inf_nan=False
    )
    customer_price_cad: Decimal | None = Field(
        default=None, gt=0, le=MAX_CAD_PRICE, allow_inf_nan=False
    )

    @model_validator(mode="after")
    def _one_value_at_least(self) -> FeeLineAmountIn:
        given = {name: getattr(self, name) for name in self.model_fields_set}
        if not given or any(value is None for value in given.values()):
            raise ValueError(
                "Enter the vendor's cost (VND) and/or the customer price (CAD) for this line."
            )
        return self


class FeeLineOut(PricingModel):
    id: int
    item_id: int
    section: str
    stt: int
    quantity: Decimal
    weight_kg: Decimal | None
    manual_unit_price_vnd: Decimal | None
    #: The customer price (CAD) entered on a line quoted case by case (DEC-0228), else None.
    customer_price_cad: Decimal | None = None
    created_at: datetime
    removed_at: datetime | None


class CartonIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    weight_kg: Decimal = Field(gt=0)
    length_cm: Decimal | None = Field(default=None, gt=0)
    width_cm: Decimal | None = Field(default=None, gt=0)
    height_cm: Decimal | None = Field(default=None, gt=0)


class CartonsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cartons: list[CartonIn] = Field(max_length=500)


class CartonOut(PricingModel):
    sequence: int
    weight_kg: Decimal
    length_cm: Decimal | None
    width_cm: Decimal | None
    height_cm: Decimal | None


class ManualPricingIn(BaseModel):
    """Air Express / UPS per master (method v0.5+): vendor cost per kg or total, sell per kg."""

    model_config = ConfigDict(extra="forbid")

    manual_cost_vnd_per_kg: Decimal | None = Field(
        default=None, gt=0, max_digits=14, decimal_places=2
    )
    manual_cost_vnd_total: Decimal | None = Field(
        default=None, gt=0, max_digits=16, decimal_places=2
    )
    manual_sell_cad_per_kg: Decimal | None = Field(
        default=None, gt=0, max_digits=8, decimal_places=2
    )
    reason: str | None = Field(default=None, max_length=400)


class MethodSettingsUpdate(BaseModel):
    """The confirmed method's settings (``pricing_method_settings``); validated by the service."""

    model_config = ConfigDict(extra="forbid")

    pricing_method: str | None = Field(default=None, max_length=10)
    air_std_rate_low_cad: Decimal | None = None
    air_std_threshold_kg: Decimal | None = None
    threshold_basis: str | None = Field(default=None, max_length=10)
    sea_rate_cad: Decimal | None = None
    markup_kind: str | None = Field(default=None, max_length=10)
    markup_value: Decimal | None = None
    fx_source_cost: str | None = Field(default=None, max_length=15)
    fx_source_quote: str | None = Field(default=None, max_length=15)
    kango_fixed_rate_vnd: Decimal | None = None
    residual_mode: str | None = Field(default=None, max_length=12)
    pkg_surcharge_billing: str | None = Field(default=None, max_length=15)
    parcel_band_cost_basis: str | None = Field(default=None, max_length=10)
    parcel_quote_mode: str | None = Field(default=None, max_length=10)
    vendor_bill_rounding: str | None = Field(default=None, max_length=10)


class PackedFlagIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    packed_as_one_box: bool


class SeaCostIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sea_cost_vnd_per_kg: Decimal = Field(gt=0, max_digits=14, decimal_places=2)
    effective_from: date


class PackageNoteIn(BaseModel):
    """``packages.customer_note`` (method v0.6, Louis Q7); empty removes it."""

    model_config = ConfigDict(extra="forbid")

    customer_note: str | None = Field(default=None, max_length=200)


class PackageMemberIn(BaseModel):
    """Which package of its master a customer shipment rides in (v0.6); null removes it."""

    model_config = ConfigDict(extra="forbid")

    carton_sequence: int | None = Field(default=None, ge=1)


class PackagesOut(BaseModel):
    notes: dict[int, str]
    members: dict[int, int]
    packed: dict[int, bool] = {}
    #: DEC-0272: last-mile tracking per master piece (optional).
    tracking: dict[int, str] = {}


class PieceTrackingIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    last_mile_tracking: str | None = Field(default=None, max_length=60)


class WorkspaceItemIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    description: str = Field(min_length=1, max_length=300)
    quantity: Decimal | None = Field(default=None, gt=0)
    unit: str | None = Field(default=None, max_length=20)
    weight_kg: Decimal | None = Field(default=None, gt=0)


class WorkspaceCustomerIn(BaseModel):
    """Add a customer to a master piece from the workspace (DEC-0272)."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    customer_id: int
    carton_sequence: int | None = Field(default=None, ge=1)
    reference_code: str | None = Field(default=None, max_length=60)
    weight_kg: Decimal = Field(gt=0)
    length_cm: Decimal | None = Field(default=None, gt=0)
    width_cm: Decimal | None = Field(default=None, gt=0)
    height_cm: Decimal | None = Field(default=None, gt=0)
    #: Built from the item names when left out (owner, 2026-11-05).
    contents_description: str | None = Field(default=None, max_length=400)
    items: list[WorkspaceItemIn] = Field(default_factory=list, max_length=100)
    sender: AddressSnapshotIn | None = None
    recipient: AddressSnapshotIn | None = None


class WorkspaceCustomerUpdate(BaseModel):
    """Edit a customer from the workspace (DEC-0273): only the fields sent change."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    reference_code: str | None = Field(default=None, max_length=60)
    weight_kg: Decimal | None = Field(default=None, gt=0)
    length_cm: Decimal | None = Field(default=None, gt=0)
    width_cm: Decimal | None = Field(default=None, gt=0)
    height_cm: Decimal | None = Field(default=None, gt=0)
    carton_sequence: int | None = Field(default=None, ge=1)


class EstimateOut(PricingModel):
    """The whole consolidation estimate, as the engine returned it."""

    consolidation_id: int
    estimate: dict[str, Any]


class QuoteLineOut(PricingModel):
    sequence: int
    kind: str
    description: str
    section: str | None
    stt: int | None
    quantity: Decimal | None
    unit: str | None
    revenue_cad: Decimal
    cost_vnd: Decimal | None
    cost_cad: Decimal | None
    is_trigger: bool
    markup_kind: str | None
    markup_value: Decimal | None


class QuoteVersionOut(PricingModel):
    id: int
    shipment_id: int
    version: int
    status: str
    solaris_service: str
    consolidation_id: int | None
    tariff_version_id: int | None
    fx_snapshot_id: int | None
    default_rate_cad: Decimal | None
    selling_rate_cad: Decimal | None
    override_reason: str | None
    rate_confirmed: bool
    rate_confirmed_at: datetime | None
    negative_margin_reason: str | None
    billable_weight_kg: Decimal | None
    base_revenue_cad: Decimal | None
    surcharge_revenue_cad: Decimal | None
    total_revenue_cad: Decimal | None
    allocated_cost_cad: Decimal | None
    gross_profit_cad: Decimal | None
    blocking: list[dict[str, Any]]
    provisional: list[dict[str, Any]]
    lines: list[QuoteLineOut]
    finalized_at: datetime | None
    created_at: datetime
    #: Owner decision 9: set when this finalised version expired on a new tariff version
    #: (``expired_at``, ``reason``, ``tariff_version_public_id``, ``previous_offer_status``).
    expiry: dict[str, Any] | None = None


class ConfirmRateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rate: Decimal | None = Field(default=None, gt=0)
    reason: str | None = Field(default=None, max_length=400)


class FinalizeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    negative_margin_reason: str | None = Field(default=None, max_length=400)
