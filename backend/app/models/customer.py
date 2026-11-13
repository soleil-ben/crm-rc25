"""Customer, address book, tags, route interests, and identifier aliases."""

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
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import (
    AddressRole,
    CustomerCategory,
    PreferredLanguage,
    ShippingFrequency,
    ShippingPurpose,
)
from app.models.base import Base, TimestampMixin


class Customer(TimestampMixin, Base):
    """A CRM customer record.

    ``public_id`` (STCA-000001; issued as ``CUS-`` before DEC-0174 and kept as aliases) is
    the immutable human-readable identifier and is separate from the internal primary key
    (CRM.md section 4). Declared preferences are
    stored here; observed behaviour is derived from shipment records instead.
    """

    __tablename__ = "customers"
    __table_args__ = (
        CheckConstraint(
            "email_normalized IS NOT NULL OR phone_match_key IS NOT NULL",
            name="contactable",
        ),
        Index("ix_customers_email_normalized", "email_normalized"),
        Index("ix_customers_phone_match_key", "phone_match_key"),
        Index("ix_customers_name_match_key", "name_match_key"),
        # Import idempotency (Phase 5A, DEC-0078). A second import of the same source row
        # must find the customer it created the first time rather than creating another.
        # Partial, because most customers are created by hand and carry neither column;
        # without the predicate every hand-created record would collide on (NULL, NULL)
        # under a database that treats NULLs as equal.
        Index(
            "uq_customers_source_record",
            "source_system",
            "source_record_id",
            unique=True,
            sqlite_where=text("source_system IS NOT NULL AND source_record_id IS NOT NULL"),
            postgresql_where=text("source_system IS NOT NULL AND source_record_id IS NOT NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    public_id: Mapped[str] = mapped_column(String(20), nullable=False, unique=True, index=True)

    # --- Identity and contact -------------------------------------------
    #
    # ``full_name`` is unchanged and still required: the name of the person to talk to.
    # For an individual that is the individual; for a business it is the primary contact.
    # Phase 10 added the two columns below rather than overloading it, because a column
    # that means two things is the thing `FIELD_MATRIX.md` section 6 asked not to create.
    full_name: Mapped[str] = mapped_column(String(200), nullable=False)
    #: The registered or legal name, as submitted. For a business it is also copied to
    #: ``business_name``; they are separate columns so a later trading-name change does
    #: not rewrite the legal one. Null for every row created before Phase 10 and for
    #: every row nobody gave one to -- there is no backfill and no default (Phase 10).
    legal_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    #: What the customer prefers to be called. Presentation only: it feeds no match key,
    #: no duplicate rule and no uniqueness constraint (Phase 10).
    display_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    name_match_key: Mapped[str | None] = mapped_column(String(200), nullable=True)
    phone_entered: Mapped[str | None] = mapped_column(String(60), nullable=True)
    phone_e164: Mapped[str | None] = mapped_column(String(30), nullable=True)
    phone_region: Mapped[str | None] = mapped_column(String(4), nullable=True)
    phone_match_key: Mapped[str | None] = mapped_column(String(30), nullable=True)
    email_entered: Mapped[str | None] = mapped_column(String(320), nullable=True)
    email_normalized: Mapped[str | None] = mapped_column(String(320), nullable=True)

    # --- Location and language ------------------------------------------
    city: Mapped[str | None] = mapped_column(String(120), nullable=True)
    province_state: Mapped[str | None] = mapped_column(String(120), nullable=True)
    country_code: Mapped[str | None] = mapped_column(String(2), nullable=True, index=True)
    preferred_language: Mapped[str] = mapped_column(
        String(10), nullable=False, default=PreferredLanguage.UNKNOWN
    )

    # --- Segmentation (declared, not observed) ---------------------------
    category: Mapped[str] = mapped_column(
        String(20), nullable=False, default=CustomerCategory.INDIVIDUAL
    )
    business_type: Mapped[str | None] = mapped_column(String(30), nullable=True)
    business_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    primary_shipping_purpose: Mapped[str] = mapped_column(
        String(30), nullable=False, default=ShippingPurpose.UNKNOWN
    )
    primary_route_group: Mapped[str | None] = mapped_column(String(3), nullable=True, index=True)
    shipping_frequency: Mapped[str] = mapped_column(
        String(20), nullable=False, default=ShippingFrequency.UNKNOWN
    )
    estimated_monthly_shipments: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)

    # --- Contact preferences --------------------------------------------
    preferred_contact_channel: Mapped[str | None] = mapped_column(String(20), nullable=True)
    best_contact_time: Mapped[str | None] = mapped_column(String(120), nullable=True)
    contact_timezone: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # --- Ownership and lifecycle ----------------------------------------
    owner_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    is_archived: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    archive_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Service restriction / do-not-contact is stored independently of lifecycle status
    # (CRM.md section 4).
    do_not_contact: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    service_restriction_note: Mapped[str | None] = mapped_column(String(400), nullable=True)

    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # --- Provenance ------------------------------------------------------
    source_system: Mapped[str | None] = mapped_column(String(60), nullable=True)
    source_record_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    source_created_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    is_demo_record: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)

    # --- Merge bookkeeping ----------------------------------------------
    merged_into_customer_id: Mapped[int | None] = mapped_column(
        ForeignKey("customers.id", ondelete="SET NULL"), nullable=True, index=True
    )
    merged_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    addresses: Mapped[list[CustomerAddress]] = relationship(
        back_populates="customer", cascade="all, delete-orphan"
    )
    route_interests: Mapped[list[CustomerRouteInterest]] = relationship(
        back_populates="customer", cascade="all, delete-orphan"
    )
    tag_links: Mapped[list[CustomerTag]] = relationship(
        back_populates="customer", cascade="all, delete-orphan"
    )
    aliases: Mapped[list[CustomerIdAlias]] = relationship(
        back_populates="customer", cascade="all, delete-orphan"
    )


class CustomerIdAlias(Base):
    """Former public customer IDs retained after a merge (CRM.md section 13)."""

    __tablename__ = "customer_id_aliases"
    __table_args__ = (
        UniqueConstraint("alias_public_id", name="uq_customer_id_aliases_alias_public_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    customer_id: Mapped[int] = mapped_column(
        ForeignKey("customers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    alias_public_id: Mapped[str] = mapped_column(String(20), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    reason: Mapped[str] = mapped_column(String(120), nullable=False, default="merge")

    customer: Mapped[Customer] = relationship(back_populates="aliases")


class CustomerRouteInterest(Base):
    """Additional route interests, kept relational so segments can filter on them."""

    __tablename__ = "customer_route_interests"
    __table_args__ = (
        UniqueConstraint(
            "customer_id", "route_group", name="uq_customer_route_interests_customer_id_route_group"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    customer_id: Mapped[int] = mapped_column(
        ForeignKey("customers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    route_group: Mapped[str] = mapped_column(String(3), nullable=False, index=True)

    customer: Mapped[Customer] = relationship(back_populates="route_interests")


class CustomerAddress(TimestampMixin, Base):
    """Address-book contact owned by a customer.

    Confirmed shipments copy these values into an immutable snapshot, so editing an
    address here never rewrites shipment history (CRM.md section 7, AC-5).
    """

    __tablename__ = "customer_addresses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    customer_id: Mapped[int] = mapped_column(
        ForeignKey("customers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    label: Mapped[str | None] = mapped_column(String(120), nullable=True)
    role: Mapped[str] = mapped_column(String(20), nullable=False, default=AddressRole.BOTH)
    contact_name: Mapped[str] = mapped_column(String(200), nullable=False)
    company_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    phone_entered: Mapped[str | None] = mapped_column(String(60), nullable=True)
    phone_e164: Mapped[str | None] = mapped_column(String(30), nullable=True)
    email_entered: Mapped[str | None] = mapped_column(String(320), nullable=True)
    address_line1: Mapped[str | None] = mapped_column(String(255), nullable=True)
    address_line2: Mapped[str | None] = mapped_column(String(255), nullable=True)
    city: Mapped[str | None] = mapped_column(String(120), nullable=True)
    province_state: Mapped[str | None] = mapped_column(String(120), nullable=True)
    postal_code: Mapped[str | None] = mapped_column(String(30), nullable=True)
    country_code: Mapped[str | None] = mapped_column(String(2), nullable=True)
    delivery_note: Mapped[str | None] = mapped_column(String(400), nullable=True)
    is_default_sender: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_default_recipient: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_archived: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    customer: Mapped[Customer] = relationship(back_populates="addresses")


class Tag(TimestampMixin, Base):
    """Manual tag vocabulary (CRM.md section 4)."""

    __tablename__ = "tags"
    __table_args__ = (UniqueConstraint("slug", name="uq_tags_slug"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    slug: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)
    color_token: Mapped[str] = mapped_column(String(30), nullable=False, default="neutral")
    created_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    customer_links: Mapped[list[CustomerTag]] = relationship(
        back_populates="tag", cascade="all, delete-orphan"
    )


class CustomerTag(Base):
    __tablename__ = "customer_tags"
    __table_args__ = (
        UniqueConstraint("customer_id", "tag_id", name="uq_customer_tags_customer_id_tag_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    customer_id: Mapped[int] = mapped_column(
        ForeignKey("customers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    tag_id: Mapped[int] = mapped_column(
        ForeignKey("tags.id", ondelete="CASCADE"), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    created_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    customer: Mapped[Customer] = relationship(back_populates="tag_links")
    tag: Mapped[Tag] = relationship(back_populates="customer_links")


class Referral(TimestampMixin, Base):
    """Referral relationship. Self-referrals are rejected (CRM.md section 4)."""

    __tablename__ = "referrals"
    __table_args__ = (
        UniqueConstraint("referred_customer_id", name="uq_referrals_referred_customer_id"),
        CheckConstraint("referrer_customer_id <> referred_customer_id", name="no_self_referral"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    referrer_customer_id: Mapped[int] = mapped_column(
        ForeignKey("customers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    referred_customer_id: Mapped[int] = mapped_column(
        ForeignKey("customers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    recorded_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    note: Mapped[str | None] = mapped_column(String(400), nullable=True)
