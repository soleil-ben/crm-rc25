"""Vendor tariffs (Phase 13A).

What a vendor charges Solaris, as versioned, provenance-bearing data. Nine tables under
one ``tariff_versions`` row: products, rate brackets, FSA zones, beyond-area postal codes
and rates, accessorials, surcharge rules and their weight tiers.

Three properties this module is built around:

* **A version is immutable once imported.** Every row carries its version id; a new
  workbook is a new version, never an edit. A quotation records the version it was priced
  against, so it can be reproduced after the tariff moves (handoff §6, §16).
* **Provenance is per row.** Every priced row names the sheet and cell (or row) it was
  read from, and the version carries the SHA-256 of the exact file. A number in this
  database can always be traced to a cell the vendor wrote.
* **Ambiguity is a stored state, not a guess.** ``pricing_status`` and ``beyond_rate.status``
  exist so that "the vendor prices this case by case" and "no rate exists for this code"
  survive import as refusals the pricing engine must honour (`04_ISSUE_REGISTER.md`
  H-02, H-07).

**This is vendor cost data and is strictly internal** (directive v2.1 §1). Nothing here is
exposed by the public or account routers, and ``tariff:read`` is the staff permission that
gates it. The vendor's staff directory sheet is never read, and no table here has a
column for a person's name or telephone.

Money is ``Numeric``: VND unit prices as written (the vendor stores computed floats such
as 1,292,966.4; they are kept to the cent, and rounding is the pricing engine's decision,
recorded separately -- open decision D-05).
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    Date,
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
    AccessorialBasis,
    BeyondRateStatus,
    RateBracketKind,
    SemanticsSource,
    SurchargeBasis,
    SurchargePricingStatus,
    SurchargeScope,
    SurchargeSection,
    TariffLastMile,
    TariffOrigin,
    TariffProductMode,
    TariffVersionStatus,
)
from app.models.base import Base, TimestampMixin

#: The one vendor whose tariff exists today. A key, not a display string: customer-facing
#: documents never carry it (directive v2.1 §2, §4).
KANGO_VENDOR_KEY = "kango"


class Vendor(TimestampMixin, Base):
    """A transportation vendor Solaris buys from. Internal."""

    __tablename__ = "vendors"
    __table_args__ = (UniqueConstraint("key", name="uq_vendors_key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(40), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    tariff_versions: Mapped[list[TariffVersion]] = relationship(back_populates="vendor")


class TariffVersion(TimestampMixin, Base):
    """One imported workbook, in full, with the file it came from."""

    __tablename__ = "tariff_versions"
    __table_args__ = (
        UniqueConstraint("public_id", name="uq_tariff_versions_public_id"),
        # The same bytes are the same tariff. Re-importing a file is refused, not duplicated.
        UniqueConstraint(
            "vendor_id", "source_sha256", name="uq_tariff_versions_vendor_id_source_sha256"
        ),
        Index("ix_tariff_versions_vendor_id_status", "vendor_id", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    public_id: Mapped[str] = mapped_column(String(20), nullable=False)
    vendor_id: Mapped[int] = mapped_column(
        ForeignKey("vendors.id", ondelete="RESTRICT"), nullable=False
    )

    label: Mapped[str] = mapped_column(String(120), nullable=False)
    #: Operator-supplied metadata about the upload, not content from it.
    source_file_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    #: From the workbook title ("APPLY 12 OCT 2026"), confirmed by the importer's caller.
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    effective_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=TariffVersionStatus.DRAFT
    )

    imported_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    imported_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    activated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    activated_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    #: cm³ per kg for dimensional weight on Purolator-delivered products. Trucking
    #: overrides it per product. Workbook: 6000.
    dim_divisor_default: Mapped[int] = mapped_column(Integer, nullable=False, default=6000)
    #: The vendor's fixed CAD rate for its CAD-denominated fees (workbook: 19,500). Not a
    #: bank rate and never used for Solaris's own conversions.
    fixed_fx_vnd_per_cad: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    cost_currency: Mapped[str] = mapped_column(String(3), nullable=False, default="VND")

    #: The importer's findings as JSON text: counts per table, anomalies flagged for vendor
    #: review (non-monotonic prices, duplicate FSAs, unrated beyond codes), and the
    #: checksum. Read by the staff detail route; never by the pricing engine.
    import_report_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    vendor: Mapped[Vendor] = relationship(back_populates="tariff_versions")
    products: Mapped[list[TariffProduct]] = relationship(
        back_populates="version", cascade="all, delete-orphan"
    )
    surcharge_rules: Mapped[list[TariffSurchargeRule]] = relationship(
        back_populates="version", cascade="all, delete-orphan"
    )


class TariffProduct(TimestampMixin, Base):
    """One sellable vendor product per origin: ``AIR-CAD`` from HCM, and so on.

    The product decides the zone column (Ground or Express), the dimensional divisor, the
    weight at which pricing switches from per-bill to per-kg, the per-piece minimum rule,
    and whether customs surcharges are waived (the insured sea product).
    """

    __tablename__ = "tariff_products"
    __table_args__ = (
        UniqueConstraint(
            "version_id", "origin", "code", name="uq_tariff_products_version_id_origin_code"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    version_id: Mapped[int] = mapped_column(
        ForeignKey("tariff_versions.id", ondelete="CASCADE"), nullable=False
    )
    #: The vendor's own product code, exactly as the sheet names it.
    code: Mapped[str] = mapped_column(String(40), nullable=False)
    origin: Mapped[str] = mapped_column(String(3), nullable=False)
    mode: Mapped[str] = mapped_column(String(10), nullable=False)
    last_mile: Mapped[str] = mapped_column(String(30), nullable=False)
    dim_divisor: Mapped[int] = mapped_column(Integer, nullable=False)
    #: Above this chargeable weight the per-kg tiers apply (air: 21). NULL = per-kg only.
    per_kg_from_kg: Mapped[Decimal | None] = mapped_column(Numeric(7, 2), nullable=True)
    #: Pieces lighter than this, in a lot heavier than ``piece_min_applies_above_kg``, pay
    #: ``piece_min_fee_vnd`` each (air: 12 kg / 300,000 Ground, 700,000 Express).
    piece_min_weight_kg: Mapped[Decimal | None] = mapped_column(Numeric(7, 2), nullable=True)
    piece_min_fee_vnd: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    piece_min_applies_above_kg: Mapped[Decimal | None] = mapped_column(Numeric(7, 2), nullable=True)
    #: Minimum chargeable weight for the product as a whole (trucking: 100 kg).
    min_chargeable_kg: Mapped[Decimal | None] = mapped_column(Numeric(7, 2), nullable=True)
    customs_surcharges_waived: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    transit_text: Mapped[str | None] = mapped_column(String(200), nullable=True)
    source_sheet: Mapped[str] = mapped_column(String(60), nullable=False)

    version: Mapped[TariffVersion] = relationship(back_populates="products")
    brackets: Mapped[list[TariffRateBracket]] = relationship(
        back_populates="product", cascade="all, delete-orphan"
    )

    @property
    def origin_enum(self) -> TariffOrigin:
        return TariffOrigin(self.origin)

    @property
    def mode_enum(self) -> TariffProductMode:
        return TariffProductMode(self.mode)

    @property
    def last_mile_enum(self) -> TariffLastMile:
        return TariffLastMile(self.last_mile)


class TariffRateBracket(Base):
    """One price cell.

    ``per_bill`` rows: ``weight_to_kg`` is the band's upper bound (0.5, 1.0 … 20.5) and
    ``weight_from_kg`` the previous band's bound; whether the band is closed above is the
    vendor's answer to V-01 and is not encoded here. ``per_kg`` rows: ``weight_from_kg`` and
    ``weight_to_kg`` are the tier's labelled bounds, ``weight_to_kg`` NULL for the open top
    tier ("300KGS+").
    """

    __tablename__ = "tariff_rate_brackets"
    __table_args__ = (
        Index("ix_tariff_rate_brackets_product_id_kind_zone", "product_id", "kind", "zone"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_id: Mapped[int] = mapped_column(
        ForeignKey("tariff_products.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(10), nullable=False)
    zone: Mapped[int] = mapped_column(Integer, nullable=False)
    #: The vendor's row label, verbatim ("0.5", "21-44", "300KGS+", "1000kG+").
    label: Mapped[str] = mapped_column(String(20), nullable=False)
    weight_from_kg: Mapped[Decimal | None] = mapped_column(Numeric(7, 2), nullable=True)
    weight_to_kg: Mapped[Decimal | None] = mapped_column(Numeric(7, 2), nullable=True)
    price_vnd: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    source_sheet: Mapped[str] = mapped_column(String(60), nullable=False)
    source_cell: Mapped[str] = mapped_column(String(12), nullable=False)

    product: Mapped[TariffProduct] = relationship(back_populates="brackets")

    @property
    def kind_enum(self) -> RateBracketKind:
        return RateBracketKind(self.kind)


class TariffZoneFsa(Base):
    """Forward sortation area → delivery zone, one column per last-mile service."""

    __tablename__ = "tariff_zone_fsas"
    __table_args__ = (
        UniqueConstraint("version_id", "fsa", name="uq_tariff_zone_fsas_version_id_fsa"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    version_id: Mapped[int] = mapped_column(
        ForeignKey("tariff_versions.id", ondelete="CASCADE"), nullable=False
    )
    fsa: Mapped[str] = mapped_column(String(3), nullable=False)
    province: Mapped[str | None] = mapped_column(String(2), nullable=True)
    ground_zone: Mapped[int] = mapped_column(Integer, nullable=False)
    express_zone: Mapped[int] = mapped_column(Integer, nullable=False)


class TariffBeyondPostalCode(Base):
    """A full postal code the vendor's last-mile carrier treats as beyond area."""

    __tablename__ = "tariff_beyond_postal_codes"
    __table_args__ = (
        UniqueConstraint(
            "version_id", "postal_code", name="uq_tariff_beyond_postal_codes_version_id_postal_code"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    version_id: Mapped[int] = mapped_column(
        ForeignKey("tariff_versions.id", ondelete="CASCADE"), nullable=False
    )
    #: Six characters, upper case, no space.
    postal_code: Mapped[str] = mapped_column(String(6), nullable=False)
    city: Mapped[str | None] = mapped_column(String(80), nullable=True)
    province: Mapped[str | None] = mapped_column(String(2), nullable=True)
    beyond_code: Mapped[str] = mapped_column(String(6), nullable=False)


class TariffBeyondRate(Base):
    """Beyond-area fee per piece in CAD: ``base + ceil(lb) × per_lb``.

    A code that appears in the postal code list but has no rate row anywhere in the
    workbook is stored with ``status = no_rate`` and NULL amounts (code 180, 123 postal
    codes). The vendor's own calculator prices these at zero; this database does not.
    """

    __tablename__ = "tariff_beyond_rates"
    __table_args__ = (
        UniqueConstraint(
            "version_id", "beyond_code", name="uq_tariff_beyond_rates_version_id_beyond_code"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    version_id: Mapped[int] = mapped_column(
        ForeignKey("tariff_versions.id", ondelete="CASCADE"), nullable=False
    )
    beyond_code: Mapped[str] = mapped_column(String(6), nullable=False)
    status: Mapped[str] = mapped_column(String(10), nullable=False, default=BeyondRateStatus.PRICED)
    base_cad: Mapped[Decimal | None] = mapped_column(Numeric(8, 2), nullable=True)
    per_lb_cad: Mapped[Decimal | None] = mapped_column(Numeric(8, 2), nullable=True)
    source_sheet: Mapped[str | None] = mapped_column(String(60), nullable=True)
    source_cell: Mapped[str | None] = mapped_column(String(12), nullable=True)


class TariffAccessorial(Base):
    """A vendor fee written in the sheet's notes rather than in a table.

    Saturday delivery, address correction, oversized piece, storage per week, return
    re-delivery, and so on. These are read from free text, so each row cites the cell it
    was taken from and the importer's reviewed table (``kango_semantics.py``) is the
    reader; nothing here is produced by a regex over prose.
    """

    __tablename__ = "tariff_accessorials"
    __table_args__ = (
        UniqueConstraint("version_id", "key", name="uq_tariff_accessorials_version_id_key"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    version_id: Mapped[int] = mapped_column(
        ForeignKey("tariff_versions.id", ondelete="CASCADE"), nullable=False
    )
    key: Mapped[str] = mapped_column(String(60), nullable=False)
    description: Mapped[str] = mapped_column(String(300), nullable=False)
    amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    basis: Mapped[str] = mapped_column(String(30), nullable=False)
    #: Comma-separated ``TariffProductMode`` values this fee can apply to.
    applies_to_modes: Mapped[str] = mapped_column(String(20), nullable=False)
    source_sheet: Mapped[str] = mapped_column(String(60), nullable=False)
    source_cell: Mapped[str] = mapped_column(String(12), nullable=False)

    @property
    def basis_enum(self) -> AccessorialBasis:
        return AccessorialBasis(self.basis)


class TariffSurchargeRule(Base):
    """One row of the vendor's customs/handling surcharge sheet, with its meaning.

    The vendor's text is kept verbatim (``raw_price_text``, ``raw_note``) **and** the
    structured reading beside it, so a reviewer can always compare the two. The structured
    reading comes either from the strict parser (``semantics_source = parsed``) or from the
    reviewed table (``curated``); in both cases ``pricing_status`` says whether the engine
    may use it.
    """

    __tablename__ = "tariff_surcharge_rules"
    __table_args__ = (
        UniqueConstraint(
            "version_id", "section", "stt", name="uq_tariff_surcharge_rules_version_id_section_stt"
        ),
        Index("ix_tariff_surcharge_rules_version_id_section", "version_id", "section"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    version_id: Mapped[int] = mapped_column(
        ForeignKey("tariff_versions.id", ondelete="CASCADE"), nullable=False
    )
    section: Mapped[str] = mapped_column(String(20), nullable=False)
    #: The vendor's section heading, verbatim, for display to staff.
    section_label: Mapped[str] = mapped_column(String(200), nullable=False)
    #: The vendor's row number within the section (restarts per section).
    stt: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    raw_price_text: Mapped[str] = mapped_column(String(200), nullable=False)
    raw_note: Mapped[str | None] = mapped_column(Text, nullable=True)

    basis: Mapped[str] = mapped_column(String(20), nullable=False)
    scope: Mapped[str] = mapped_column(String(20), nullable=False)
    pricing_status: Mapped[str] = mapped_column(String(30), nullable=False)
    unit_price_vnd: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    #: The per-unit half of a ``compound`` rule (perfume: 50,000 per bottle).
    per_unit_price_vnd: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    per_unit_label: Mapped[str | None] = mapped_column(String(20), nullable=True)
    #: "Min thu 1Kg": charge at least this many kilograms.
    min_charge_kg: Mapped[Decimal | None] = mapped_column(Numeric(7, 2), nullable=True)
    #: Weight cap the vendor states ("max 1 kg per bill"); the engine warns above it.
    max_kg_per_shipment: Mapped[Decimal | None] = mapped_column(Numeric(7, 2), nullable=True)
    applies_to_canada: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    semantics_source: Mapped[str] = mapped_column(String(10), nullable=False)
    #: Our own one-line reading of the vendor's note, for staff. Never customer-facing.
    semantics_note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    source_sheet: Mapped[str] = mapped_column(String(60), nullable=False)
    source_row: Mapped[int] = mapped_column(Integer, nullable=False)

    version: Mapped[TariffVersion] = relationship(back_populates="surcharge_rules")
    tiers: Mapped[list[TariffSurchargeRuleTier]] = relationship(
        back_populates="rule", cascade="all, delete-orphan", order_by="TariffSurchargeRuleTier.id"
    )

    @property
    def section_enum(self) -> SurchargeSection:
        return SurchargeSection(self.section)

    @property
    def basis_enum(self) -> SurchargeBasis:
        return SurchargeBasis(self.basis)

    @property
    def scope_enum(self) -> SurchargeScope:
        return SurchargeScope(self.scope)

    @property
    def pricing_status_enum(self) -> SurchargePricingStatus:
        return SurchargePricingStatus(self.pricing_status)

    @property
    def semantics_source_enum(self) -> SemanticsSource:
        return SemanticsSource(self.semantics_source)


class TariffSurchargeRuleTier(Base):
    """A weight tier of a ``tiered`` or ``compound`` rule.

    Bounds are stored as the vendor wrote them; where the vendor's tiers overlap at a
    boundary (nail polish: "1–5 kg … 5–22 kg") both rows carry the shared bound and the
    pricing engine applies the recorded convention (open decision V-11) rather than this
    table pretending the vendor was unambiguous.
    """

    __tablename__ = "tariff_surcharge_rule_tiers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    rule_id: Mapped[int] = mapped_column(
        ForeignKey("tariff_surcharge_rules.id", ondelete="CASCADE"), nullable=False, index=True
    )
    weight_from_kg: Mapped[Decimal] = mapped_column(Numeric(7, 2), nullable=False)
    weight_to_kg: Mapped[Decimal | None] = mapped_column(Numeric(7, 2), nullable=True)
    price_vnd: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)

    rule: Mapped[TariffSurchargeRule] = relationship(back_populates="tiers")
