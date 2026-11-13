"""Pricing settings, surcharge policies, fee lines and quote versions (Phase 13C).

Six new tables; no existing table is altered (the lesson of DEC-0181).

* ``pricing_settings`` -- one row: the Air Standard default selling rate (CAD 18.00/kg) and
  the full-master trigger share (2/3), both configurable defaults flagged pending owner
  confirmation (OD-48); the vendor's delivery postal code (L5A 3K6, OD-46).
* ``surcharge_rule_policies`` -- the owner's commercial policy per surcharge rule: markup
  (pass-through, fixed CAD or percent, OD-44) and an optional scope override. Keyed by the
  vendor's section and row number, not by a tariff-version row id, so a policy survives a
  new tariff version.
* ``shipment_fee_lines`` -- the surcharges staff attached to a shipment's items through the
  fee picker. Also keyed by section and row number. Removal keeps the row.
* ``consolidation_cartons`` -- each carton of a master consolidation: weight and
  dimensions, for the under-12 kg piece fee on lots of 21 kg and over (OD-62).
* ``quote_versions`` -- a customer quote for one shipment, versioned. One open draft at a
  time; a finalised version is immutable and carries the full pricing snapshot it was priced
  with, so later tariff or exchange-rate changes cannot alter it (SC-07, SC-10).
* ``quote_lines`` -- the lines of a version: base freight and each surcharge, with the
  internal cost beside the customer revenue.

**Internal.** Vendor cost and margin live here beside the customer price; these tables are
read only through staff routes behind ``tariff:read`` and the financial permissions, never by
the public or Customer Account routers.
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

from app.models.base import Base, TimestampMixin

#: Soleil's warehouse: where Kango delivers every consolidation (OD-46).
DEFAULT_VENDOR_DELIVERY_POSTAL_CODE = "L5A3K6"


class PricingSettings(Base):
    """The single pricing settings row."""

    __tablename__ = "pricing_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    air_standard_default_rate_cad: Mapped[Decimal] = mapped_column(
        Numeric(8, 2), nullable=False, default=Decimal("18.00")
    )
    #: No default for Air Express: staff enter a rate, with a reason, every time.
    air_express_default_rate_cad: Mapped[Decimal | None] = mapped_column(
        Numeric(8, 2), nullable=True
    )
    #: The trigger's share of a full-master surcharge when exactly one of several shipments
    #: triggers it, as a fraction (handoff section 5: 2/3).
    trigger_share_numerator: Mapped[int] = mapped_column(Integer, nullable=False, default=2)
    trigger_share_denominator: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    #: The owner confirmed both defaults on 2026-10-20 (OD-48); still a setting.
    defaults_owner_confirmed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    vendor_delivery_postal_code: Mapped[str] = mapped_column(
        String(6), nullable=False, default=DEFAULT_VENDOR_DELIVERY_POSTAL_CODE
    )
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class MarkupDefault(Base):
    """The markup on every surcharge that has no policy of its own (owner, 2026-10-20: 2 %).

    One row, created when an administrator first saves it; until then the service answers
    with the owner's default. A per-rule policy still overrides it.
    """

    __tablename__ = "markup_defaults"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    #: pass_through | fixed_cad | percent
    markup_kind: Mapped[str] = mapped_column(String(20), nullable=False, default="percent")
    markup_value: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False, default=2)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class SurchargeRulePolicy(Base):
    """The owner's policy for one surcharge rule. No row = pass-through at the tariff's scope."""

    __tablename__ = "surcharge_rule_policies"
    __table_args__ = (
        UniqueConstraint("section", "stt", name="uq_surcharge_rule_policies_section_stt"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    section: Mapped[str] = mapped_column(String(20), nullable=False)
    stt: Mapped[int] = mapped_column(Integer, nullable=False)
    #: pass_through | fixed_cad | percent
    markup_kind: Mapped[str] = mapped_column(String(20), nullable=False, default="pass_through")
    markup_value: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False, default=0)
    #: Overrides the tariff's scope, for example ``item_weight`` where the owner decides a
    #: per-kilogram rule is charged on the item's own kilograms (V-20).
    scope_override: Mapped[str | None] = mapped_column(String(20), nullable=True)
    note: Mapped[str | None] = mapped_column(String(400), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class ShipmentFeeLine(Base):
    """A surcharge staff attached to an item through the fee picker."""

    __tablename__ = "shipment_fee_lines"
    __table_args__ = (
        Index("ix_shipment_fee_lines_shipment_id_removed_at", "shipment_id", "removed_at"),
        # One active line per item and rule; a second click is a correction, not a second fee.
        Index(
            "uq_shipment_fee_lines_active_item_rule",
            "item_id",
            "section",
            "stt",
            unique=True,
            sqlite_where=text("removed_at IS NULL"),
            postgresql_where=text("removed_at IS NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    shipment_id: Mapped[int] = mapped_column(
        ForeignKey("shipments.id", ondelete="CASCADE"), nullable=False
    )
    item_id: Mapped[int] = mapped_column(
        ForeignKey("shipment_items.id", ondelete="CASCADE"), nullable=False
    )
    section: Mapped[str] = mapped_column(String(20), nullable=False)
    stt: Mapped[int] = mapped_column(Integer, nullable=False)
    #: Units, pairs, boxes, bottles or cartons, by the rule's basis.
    quantity: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False, default=1)
    #: The carton weight for a tiered rule; the kilograms for an item-weight rule.
    weight_kg: Mapped[Decimal | None] = mapped_column(Numeric(8, 3), nullable=True)
    #: The vendor's quoted unit price in VND for a manual-quote rule (OD-56) or a carton
    #: above a rule's top tier (OD-59). Null = the file's minimum is used, provisionally.
    manual_unit_price_vnd: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    created_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    removed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    removed_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class ConsolidationCarton(Base):
    """One carton of a master consolidation (OD-62). Replaced as a set, never edited in place."""

    __tablename__ = "consolidation_cartons"
    __table_args__ = (
        UniqueConstraint(
            "consolidation_id", "sequence", name="uq_consolidation_cartons_consolidation_sequence"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    consolidation_id: Mapped[int] = mapped_column(
        ForeignKey("consolidations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    weight_kg: Mapped[Decimal] = mapped_column(Numeric(8, 3), nullable=False)
    length_cm: Mapped[Decimal | None] = mapped_column(Numeric(8, 2), nullable=True)
    width_cm: Mapped[Decimal | None] = mapped_column(Numeric(8, 2), nullable=True)
    height_cm: Mapped[Decimal | None] = mapped_column(Numeric(8, 2), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    created_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class QuoteVersion(TimestampMixin, Base):
    """One version of a shipment's customer quote."""

    __tablename__ = "quote_versions"
    __table_args__ = (
        UniqueConstraint("shipment_id", "version", name="uq_quote_versions_shipment_id_version"),
        # One open draft per shipment.
        Index(
            "uq_quote_versions_open_draft",
            "shipment_id",
            unique=True,
            sqlite_where=text("status = 'draft'"),
            postgresql_where=text("status = 'draft'"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    #: Finalised quotes are financial records: a shipment carrying one cannot be deleted.
    shipment_id: Mapped[int] = mapped_column(
        ForeignKey("shipments.id", ondelete="RESTRICT"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    #: draft | finalized | superseded
    status: Mapped[str] = mapped_column(String(12), nullable=False, default="draft")
    consolidation_id: Mapped[int | None] = mapped_column(
        ForeignKey("consolidations.id", ondelete="SET NULL"), nullable=True
    )
    tariff_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("tariff_versions.id", ondelete="SET NULL"), nullable=True
    )
    fx_snapshot_id: Mapped[int | None] = mapped_column(
        ForeignKey("fx_rate_snapshots.id", ondelete="SET NULL"), nullable=True
    )
    solaris_service: Mapped[str] = mapped_column(String(20), nullable=False)

    #: The rate in force and where it came from.
    default_rate_cad: Mapped[Decimal | None] = mapped_column(Numeric(8, 2), nullable=True)
    selling_rate_cad: Mapped[Decimal | None] = mapped_column(Numeric(8, 2), nullable=True)
    override_reason: Mapped[str | None] = mapped_column(String(400), nullable=True)
    rate_confirmed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    rate_confirmed_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    #: The inputs fingerprint at confirmation. A later change to any input revokes the
    #: confirmation (SC-07: changing input invalidates confirmation).
    confirmed_inputs_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    inputs_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    negative_margin_reason: Mapped[str | None] = mapped_column(String(400), nullable=True)

    billable_weight_kg: Mapped[Decimal | None] = mapped_column(Numeric(8, 3), nullable=True)
    base_revenue_cad: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    surcharge_revenue_cad: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    total_revenue_cad: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    allocated_cost_cad: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    gross_profit_cad: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)

    blocking_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    provisional_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    #: The whole estimate this version was priced with. Written at every re-price of a draft
    #: and frozen at finalisation.
    snapshot_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")

    created_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    finalized_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finalized_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    lines: Mapped[list[QuoteLine]] = relationship(
        back_populates="version", cascade="all, delete-orphan", order_by="QuoteLine.sequence"
    )


class QuoteLine(Base):
    """A line of a quote version: base freight, or one surcharge."""

    __tablename__ = "quote_lines"
    __table_args__ = (
        UniqueConstraint("version_id", "sequence", name="uq_quote_lines_version_id_sequence"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    version_id: Mapped[int] = mapped_column(
        ForeignKey("quote_versions.id", ondelete="CASCADE"), nullable=False
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    #: base_freight | surcharge
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    #: Customer-facing wording (a Solaris service name or the commodity), never a vendor name.
    description: Mapped[str] = mapped_column(String(300), nullable=False)
    section: Mapped[str | None] = mapped_column(String(20), nullable=True)
    stt: Mapped[int | None] = mapped_column(Integer, nullable=True)
    quantity: Mapped[Decimal | None] = mapped_column(Numeric(10, 3), nullable=True)
    unit: Mapped[str | None] = mapped_column(String(20), nullable=True)
    #: Customer side.
    revenue_cad: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    #: Internal side: this shipment's share of the vendor charge.
    cost_vnd: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    cost_cad: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    is_trigger: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    markup_kind: Mapped[str | None] = mapped_column(String(20), nullable=True)
    markup_value: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)

    version: Mapped[QuoteVersion] = relationship(back_populates="lines")
