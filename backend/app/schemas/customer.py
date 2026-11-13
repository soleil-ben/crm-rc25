"""Customer request/response schemas."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.enums import (
    AddressRole,
    BusinessType,
    ContactChannel,
    CustomerCategory,
    PreferredLanguage,
    RouteGroup,
    ShippingFrequency,
    ShippingPurpose,
)
from app.schemas.common import ApiModel


class CustomerBase(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    full_name: str = Field(min_length=1, max_length=200)
    phone: str | None = Field(default=None, max_length=60)
    email: str | None = Field(default=None, max_length=320)
    city: str | None = Field(default=None, max_length=120)
    province_state: str | None = Field(default=None, max_length=120)
    country_code: str | None = Field(default=None, min_length=2, max_length=2)
    preferred_language: PreferredLanguage = PreferredLanguage.UNKNOWN
    category: CustomerCategory = CustomerCategory.INDIVIDUAL
    business_type: BusinessType | None = None
    business_name: str | None = Field(default=None, max_length=200)
    primary_shipping_purpose: ShippingPurpose = ShippingPurpose.UNKNOWN
    primary_route_group: RouteGroup | None = None
    additional_route_interests: list[RouteGroup] | None = None
    shipping_frequency: ShippingFrequency = ShippingFrequency.UNKNOWN
    estimated_monthly_shipments: Decimal | None = Field(default=None, ge=0)
    preferred_contact_channel: ContactChannel | None = None
    best_contact_time: str | None = Field(default=None, max_length=120)
    contact_timezone: str | None = Field(default=None, max_length=64)
    owner_user_id: int | None = None
    do_not_contact: bool = False
    service_restriction_note: str | None = Field(default=None, max_length=400)
    notes: str | None = None

    @field_validator("country_code")
    @classmethod
    def _upper_country(cls, value: str | None) -> str | None:
        return value.upper() if value else value


class CustomerCreate(CustomerBase):
    tag_ids: list[int] | None = None
    # Set only by an explicit staff decision after reviewing duplicate candidates.
    acknowledge_duplicates: bool = False


class CustomerUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    full_name: str | None = Field(default=None, min_length=1, max_length=200)
    phone: str | None = Field(default=None, max_length=60)
    email: str | None = Field(default=None, max_length=320)
    city: str | None = None
    province_state: str | None = None
    country_code: str | None = Field(default=None, min_length=2, max_length=2)
    preferred_language: PreferredLanguage | None = None
    category: CustomerCategory | None = None
    business_type: BusinessType | None = None
    business_name: str | None = None
    primary_shipping_purpose: ShippingPurpose | None = None
    primary_route_group: RouteGroup | None = None
    additional_route_interests: list[RouteGroup] | None = None
    shipping_frequency: ShippingFrequency | None = None
    estimated_monthly_shipments: Decimal | None = Field(default=None, ge=0)
    preferred_contact_channel: ContactChannel | None = None
    best_contact_time: str | None = None
    contact_timezone: str | None = None
    owner_user_id: int | None = None
    do_not_contact: bool | None = None
    service_restriction_note: str | None = None
    notes: str | None = None
    tag_ids: list[int] | None = None


class TagCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    slug: str = Field(min_length=1, max_length=60)
    name: str = Field(min_length=1, max_length=80)
    description: str | None = Field(default=None, max_length=255)
    color_token: str = Field(default="neutral", max_length=30)


class TagOut(ApiModel):
    id: int
    slug: str
    name: str
    color_token: str
    description: str | None = None


class StaffSummary(ApiModel):
    id: int
    full_name: str
    email: str
    role: str


class CustomerActivityOut(BaseModel):
    total_qualifying_shipments: int
    total_bookings: int
    delivered_shipments: int
    first_shipment_at: datetime | None
    last_shipment_at: datetime | None
    is_repeat_customer: bool
    observed_primary_route_group: str | None
    route_counts: dict[str, int]
    lifecycle_status: str
    days_since_last_shipment: int | None
    referral_count: int
    qualified_referral_count: int
    open_task_count: int
    overdue_task_count: int
    next_follow_up_at: datetime | None
    last_follow_up_at: datetime | None
    unresolved_issue_count: int
    has_service_issue: bool


class CurrencyTotalsOut(BaseModel):
    currency: str
    recorded_revenue: Decimal
    recorded_cost: Decimal | None = None
    gross_profit: Decimal | None = None
    shipments_with_revenue: int
    shipments_with_cost: int


class CustomerFinancialSummaryOut(BaseModel):
    """Financial coverage is always reported so partial data cannot look complete."""

    by_currency: list[CurrencyTotalsOut]
    qualifying_shipments: int
    shipments_with_any_financial_record: int
    coverage_share: float | None
    includes_costs: bool
    note: str


class CustomerListItem(ApiModel):
    id: int
    public_id: str
    full_name: str
    phone_entered: str | None
    email_entered: str | None
    city: str | None
    province_state: str | None
    country_code: str | None
    preferred_language: str
    category: str
    primary_route_group: str | None
    owner: StaffSummary | None = None
    tags: list[TagOut] = Field(default_factory=list)
    is_archived: bool
    do_not_contact: bool
    created_at: datetime

    lifecycle_status: str
    total_qualifying_shipments: int
    last_shipment_at: datetime | None
    next_follow_up_at: datetime | None
    has_overdue_task: bool
    has_service_issue: bool
    has_duplicate_candidates: bool = False


class CustomerDetail(CustomerListItem):
    phone_e164: str | None
    email_normalized: str | None
    business_type: str | None
    business_name: str | None
    primary_shipping_purpose: str
    shipping_frequency: str
    estimated_monthly_shipments: Decimal | None
    preferred_contact_channel: str | None
    best_contact_time: str | None
    contact_timezone: str | None
    service_restriction_note: str | None
    notes: str | None
    additional_route_interests: list[str] = Field(default_factory=list)
    archived_at: datetime | None
    archive_reason: str | None
    merged_into_customer_id: int | None
    former_public_ids: list[str] = Field(default_factory=list)
    is_demo_record: bool
    activity: CustomerActivityOut
    #: True while an active or suspended Customer Account holds the link, so the email is
    #: that account's sign-in email and a staff edit may not change it; the account must be
    #: deactivated first (owner decision, 2026-10-16). The edit form shows the rule from it.
    email_held_by_account: bool = False


class DuplicateCandidateOut(BaseModel):
    customer: CustomerListItem
    matched_on: list[str]
    confidence: int
    requires_review: bool = True


class DuplicateCheckRequest(BaseModel):
    full_name: str | None = None
    email: str | None = None
    phone: str | None = None
    country_code: str | None = None
    exclude_customer_id: int | None = None


class DuplicateCheckResponse(BaseModel):
    candidates: list[DuplicateCandidateOut]
    guidance: str = (
        "Review each candidate before deciding. Families often share a phone number or email, "
        "so records are never merged automatically."
    )


class MergeRequest(BaseModel):
    source_customer_id: int
    target_customer_id: int
    confirmation: str = Field(description="Type the source customer ID to confirm the merge.")


class ArchiveRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=255)


# --- Address book ---------------------------------------------------------


class AddressBase(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    label: str | None = Field(default=None, max_length=120)
    role: AddressRole = AddressRole.BOTH
    contact_name: str = Field(min_length=1, max_length=200)
    company_name: str | None = Field(default=None, max_length=200)
    phone: str | None = Field(default=None, max_length=60)
    email: str | None = Field(default=None, max_length=320)
    address_line1: str | None = Field(default=None, max_length=255)
    address_line2: str | None = Field(default=None, max_length=255)
    city: str | None = Field(default=None, max_length=120)
    province_state: str | None = Field(default=None, max_length=120)
    postal_code: str | None = Field(default=None, max_length=30)
    country_code: str | None = Field(default=None, min_length=2, max_length=2)
    delivery_note: str | None = Field(default=None, max_length=400)
    is_default_sender: bool = False
    is_default_recipient: bool = False


class AddressCreate(AddressBase):
    pass


class AddressUpdate(AddressBase):
    contact_name: str | None = Field(default=None, min_length=1, max_length=200)
    role: AddressRole | None = None
    is_default_sender: bool | None = None
    is_default_recipient: bool | None = None
    is_archived: bool | None = None


class AddressOut(ApiModel):
    id: int
    customer_id: int
    label: str | None
    role: str
    contact_name: str
    company_name: str | None
    phone_entered: str | None
    email_entered: str | None
    address_line1: str | None
    address_line2: str | None
    city: str | None
    province_state: str | None
    postal_code: str | None
    country_code: str | None
    delivery_note: str | None
    is_default_sender: bool
    is_default_recipient: bool
    is_archived: bool
    updated_at: datetime


# --- Referrals ------------------------------------------------------------


class ReferralCreate(BaseModel):
    referred_customer_id: int
    note: str | None = Field(default=None, max_length=400)


class ReferralOut(BaseModel):
    id: int
    referrer: CustomerListItem | None = None
    referred: CustomerListItem | None = None
    note: str | None
    created_at: datetime
    referred_has_qualifying_shipment: bool = False
    #: Who recorded the relationship. Null for a seeded or imported row with no actor, or
    #: when the staff account has since been removed (fix pack item 6).
    recorded_by: StaffSummary | None = None
