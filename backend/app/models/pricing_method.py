"""Cost and quote method v0.5 (Louis, 2026-11-02): five new tables; nothing existing is altered
(DEC-0181). Revision ``b8d1f3a5c7e9``.

* ``pricing_method_settings`` -- one row (id 1): which method prices a master (``rc25``, the
  behaviour up to RC-UAT-25, or ``v0_5``), and the v0.5 settings with Louis's defaults:
  FX source Kango fixed 19,500 VND/CAD for cost and quote; leftover base freight spread by
  weight; per-box (band) surcharges costed on the small box Kango sees and quoted in full to
  each triggering customer; whole-package surcharges quoted with the same 2/3 / weight share as
  cost; no markup; Air Standard CAD 18/kg from 21 kg of the customer's own rounded weight and
  CAD 19/kg below; Sea CAD 8/kg. The high Air Standard rate stays in
  ``pricing_settings.air_standard_default_rate_cad`` (18.00) and the trigger share in
  ``pricing_settings.trigger_share_*`` (2/3): v0.5 reuses both.
* ``consolidation_package_flags`` -- per package (kiện) of a master, keyed by the
  consolidation and the carton sequence so it survives ``replace_cartons``: "packed as one box
  for Kango". When set, a per-box surcharge is charged by Kango once for the package (band on
  the package weight) and split by weight among the customers with the item.
* ``consolidation_manual_pricing`` -- per master: the manual vendor cost (VND per kg or a
  total) and the manual selling rate (CAD per kg) for Air Express and UPS.
* ``ups_rate_bands`` -- the UPS placeholder rate table (bands 0.5–5, 5.5–10, 10.5–20,
  20.5–30, 30.5+ kg); cost and sell are empty until UPS's rates arrive.
* ``surcharge_allocation_classes`` -- the allocation class of each Kango surcharge row (ITEM /
  PARCEL / WHOLE_PACKAGE / WHOLE_MASTER / CONFIRM / NONE), loaded from
  ``surcharge_allocation_rules.csv``. Keyed by the vendor's section and row number, like
  ``surcharge_rule_policies``, so it survives a new tariff version.
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
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

#: Kango's fixed rate on the rate file (HCM-AIR-CAD A58, HN-AIR-CAD A56, SEA B39).
KANGO_FIXED_RATE_VND = Decimal("19500")

#: ``confirmed`` is the owner's cost and quote method (cost-quote-method.md, now v0.7:
#: DEC-0252, 0253, 0260; the version-neutral name since DEC-0267). ``v0_5`` / ``v0_6`` /
#: ``v0_7`` are accepted as older names and stored as ``confirmed``. ``rc25`` keeps the
#: RC-UAT-25 engine.
PRICING_METHODS = ("rc25", "confirmed")
LEGACY_METHOD_NAMES = {"v0_5": "confirmed", "v0_6": "confirmed", "v0_7": "confirmed"}
#: Section of the sea vendor's own surcharges (``sea_surcharge_rules``) on a fee line (v0.6).
SEA_VENDOR_SECTION = "sea_vendor"
#: The sea vendor's rate (Louis, 2026-11-03): no Kango sheet, any weight.
SEA_COST_VND_PER_KG = Decimal("60000")
FX_SOURCES = ("kango_fixed", "vcb_cash_buy", "vcb_sell")
THRESHOLD_BASES = ("customer", "package")
MARKUP_KINDS = ("none", "fixed_cad", "percent")
RESIDUAL_MODES = ("prorata", "unallocated")
PKG_SURCHARGE_BILLINGS = ("same_as_cost", "triggers_only")
PARCEL_BAND_COST_BASES = ("box", "parcel")
PARCEL_QUOTE_MODES = ("each", "share")
VENDOR_BILL_ROUNDINGS = ("kango", "od50")
ALLOCATION_CLASSES = ("ITEM", "PARCEL", "WHOLE_PACKAGE", "WHOLE_MASTER", "CONFIRM", "NONE")


class PricingMethodSettings(Base):
    """The single v0.5 settings row (id 1)."""

    __tablename__ = "pricing_method_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    #: ``confirmed`` (default; DEC-0252 / 0253 / 0260 / 0267) prices with the
    #: confirmed method; ``rc25`` keeps the RC-UAT-25 engine available.
    pricing_method: Mapped[str] = mapped_column(String(10), nullable=False, default="confirmed")
    air_std_rate_low_cad: Mapped[Decimal] = mapped_column(
        Numeric(8, 2), nullable=False, default=Decimal("19.00")
    )
    air_std_threshold_kg: Mapped[Decimal] = mapped_column(
        Numeric(7, 2), nullable=False, default=Decimal("21")
    )
    threshold_basis: Mapped[str] = mapped_column(String(10), nullable=False, default="customer")
    sea_rate_cad: Mapped[Decimal] = mapped_column(
        Numeric(8, 2), nullable=False, default=Decimal("8.00")
    )
    markup_kind: Mapped[str] = mapped_column(String(10), nullable=False, default="none")
    markup_value: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), nullable=False, default=Decimal("0")
    )
    fx_source_cost: Mapped[str] = mapped_column(String(15), nullable=False, default="kango_fixed")
    fx_source_quote: Mapped[str] = mapped_column(String(15), nullable=False, default="kango_fixed")
    kango_fixed_rate_vnd: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False, default=KANGO_FIXED_RATE_VND
    )
    residual_mode: Mapped[str] = mapped_column(String(12), nullable=False, default="prorata")
    pkg_surcharge_billing: Mapped[str] = mapped_column(
        String(15), nullable=False, default="same_as_cost"
    )
    parcel_band_cost_basis: Mapped[str] = mapped_column(String(10), nullable=False, default="box")
    parcel_quote_mode: Mapped[str] = mapped_column(String(10), nullable=False, default="each")
    vendor_bill_rounding: Mapped[str] = mapped_column(String(10), nullable=False, default="kango")
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class ConsolidationPackageFlag(Base):
    """Per package of a master: packed as one box for Kango."""

    __tablename__ = "consolidation_package_flags"
    __table_args__ = (UniqueConstraint("consolidation_id", "carton_sequence"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    consolidation_id: Mapped[int] = mapped_column(
        ForeignKey("consolidations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    #: The carton's ``consolidation_cartons.sequence``; 1 for a master with one package.
    carton_sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    packed_as_one_box: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    set_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    set_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class ConsolidationManualPricing(Base):
    """Manual vendor cost and selling rate for one master (Air Express, UPS)."""

    __tablename__ = "consolidation_manual_pricing"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    consolidation_id: Mapped[int] = mapped_column(
        ForeignKey("consolidations.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    manual_cost_vnd_per_kg: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    manual_cost_vnd_total: Mapped[Decimal | None] = mapped_column(Numeric(16, 2), nullable=True)
    manual_sell_cad_per_kg: Mapped[Decimal | None] = mapped_column(Numeric(8, 2), nullable=True)
    reason: Mapped[str | None] = mapped_column(String(400), nullable=True)
    set_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    set_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class UpsRateBand(Base):
    """One band of the UPS placeholder table. Cost and sell are empty until rates arrive."""

    __tablename__ = "ups_rate_bands"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    band_from_kg: Mapped[Decimal] = mapped_column(Numeric(7, 2), nullable=False)
    #: None = open-ended top band (30.5 kg +).
    band_to_kg: Mapped[Decimal | None] = mapped_column(Numeric(7, 2), nullable=True)
    #: Vendor cost for the whole band (VND), when known.
    cost_vnd: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    sell_cad_per_kg: Mapped[Decimal | None] = mapped_column(Numeric(8, 2), nullable=True)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="VND")
    effective_from: Mapped[date | None] = mapped_column(Date, nullable=True)


class SurchargeAllocationClass(Base):
    """How one Kango surcharge row is allocated (from ``surcharge_allocation_rules.csv``)."""

    __tablename__ = "surcharge_allocation_classes"
    __table_args__ = (UniqueConstraint("section", "stt"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    section: Mapped[str] = mapped_column(String(20), nullable=False)
    stt: Mapped[int] = mapped_column(Integer, nullable=False)
    kango_code: Mapped[str] = mapped_column(String(10), nullable=False)
    allocation_class: Mapped[str] = mapped_column(String(15), nullable=False)
    #: The list's "charged per" basis (product_kg, per_parcel, full_carton_kg, ...).
    basis: Mapped[str] = mapped_column(String(40), nullable=False)
    products: Mapped[str] = mapped_column(Text, nullable=False)
    flags: Mapped[str | None] = mapped_column(String(300), nullable=True)
    source: Mapped[str] = mapped_column(String(60), nullable=False)


# --- Method v0.6 (Louis, 2026-11-03; DEC-0253..0258). New tables only (DEC-0181). ------------


class SeaVendorRate(Base):
    """The sea vendor's cost per kg, effective-dated (v0.6: 60,000 VND/kg, no Kango sheet).
    The row with the latest ``effective_from`` on or before the master's date applies."""

    __tablename__ = "sea_vendor_rates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sea_cost_vnd_per_kg: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    effective_from: Mapped[date] = mapped_column(Date, nullable=False, unique=True)
    source: Mapped[str] = mapped_column(String(200), nullable=False)


class SeaSurchargeRule(Base):
    """A sea vendor surcharge (v0.6): VND per item kg, with a minimum per package (kiện) per
    type, not per customer (Louis, 2026-11-03). Charged at cost. ``id`` is the fee line's
    ``stt`` under section ``sea_vendor``."""

    __tablename__ = "sea_surcharge_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)
    name_vi: Mapped[str] = mapped_column(String(120), nullable=False)
    name_en: Mapped[str] = mapped_column(String(120), nullable=False)
    rate_vnd_per_kg: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    min_vnd_per_package: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    source: Mapped[str] = mapped_column(String(200), nullable=False)


class ConsolidationPackageNote(Base):
    """``packages.customer_note`` (Louis Q7): an optional short text per package of a master,
    e.g. "STCA-000201, -202, -203". Display only; never used for pricing."""

    __tablename__ = "consolidation_package_notes"
    __table_args__ = (UniqueConstraint("consolidation_id", "carton_sequence"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    consolidation_id: Mapped[int] = mapped_column(
        ForeignKey("consolidations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    carton_sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    customer_note: Mapped[str] = mapped_column(String(200), nullable=False)
    set_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    set_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class ConsolidationPackageMember(Base):
    """Which package (kiện) of its master a customer shipment rides in. Optional: needed only
    when a master has several packages and a per-package rule applies (sea minimum per
    package, whole-package surcharges, the piece fee of a light carton, packed-as-one-box)."""

    __tablename__ = "consolidation_package_members"
    __table_args__ = (UniqueConstraint("consolidation_id", "shipment_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    consolidation_id: Mapped[int] = mapped_column(
        ForeignKey("consolidations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    shipment_id: Mapped[int] = mapped_column(
        ForeignKey("shipments.id", ondelete="CASCADE"), nullable=False
    )
    carton_sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    set_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    set_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
