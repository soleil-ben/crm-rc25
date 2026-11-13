"""Cost and quote method v0.5 (Louis, 2026-11-02): pricing settings, package flag, manual pricing,
UPS placeholder bands and surcharge allocation classes.

Revision ID: b8d1f3a5c7e9
Revises: a5c7e9b1d3f6
Create Date: 2026-11-02

Five new tables; nothing existing is altered (DEC-0181):

* ``pricing_method_settings`` -- one row (id 1) seeded with the v0.5 defaults: FX source Kango
  fixed 19,500 VND/CAD (cost and quote), leftover freight spread by weight, per-box surcharges
  costed per small box and quoted in full to each trigger, whole-package surcharges quoted with
  the cost share, markup none / 0, Air Standard CAD 19/kg under 21 kg of the customer's own
  rounded weight (CAD 18/kg at or above stays in ``pricing_settings``), Sea CAD 8/kg. The
  ``pricing_method`` switch is seeded ``rc25``: every master keeps the RC-UAT-25 pricing until
  the switch is set to ``v0_5``.
* ``consolidation_package_flags`` -- "packed as one box for Kango", per package of a master.
* ``consolidation_manual_pricing`` -- manual cost / sell for Air Express and UPS masters.
* ``ups_rate_bands`` -- five placeholder bands, cost and sell empty.
* ``surcharge_allocation_classes`` -- 70 Kango rows (115 product lines of
  ``data/surcharge_allocation_rules.csv``), one class per section and row number.

**Downgrade** drops the five tables. No existing row is touched in either direction.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

import sqlalchemy as sa

from alembic import op

revision: str = "b8d1f3a5c7e9"
down_revision: str | None = "a5c7e9b1d3f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: (section, stt, kango code, class, "charged per" basis, products, flags) -- from
#: data/surcharge_allocation_rules.csv (115 lines, 70 Kango rows). Kept literal so the
#: migration never depends on application code or a file outside alembic/.
ALLOCATION_ROWS = [
    (
        "han_air",
        1,
        "HAN-01",
        "ITEM",
        "product_kg_min_1",
        "Western medicine / pharmaceuticals",
        None,
    ),
    (
        "han_air",
        2,
        "HAN-02",
        "ITEM",
        "product_kg",
        "Foods containing eggs; Foods containing honey; Foods containing meat; Foods containing milk",
        None,
    ),
    ("han_air", 3, "HAN-03", "ITEM", "product_kg", "Edible bird's nest", None),
    ("han_air", 4, "HAN-04", "ITEM", "product_kg", "Seeds", None),
    ("han_air", 5, "HAN-05", "ITEM", "product_kg", "International-brand fashion goods (HAN)", None),
    ("han_air", 6, "HAN-06", "NONE", "none", "False eyelashes", None),
    (
        "han_air",
        7,
        "HAN-07",
        "PARCEL",
        "per_parcel",
        "Nail polish; Perfume; Battery products",
        "QUOTE: each triggering customer pays the full fee (band on own weight), + markup (0 now), ÷ FX (Kango 19,500). Difference = surcharge margin.",
    ),
    (
        "han_air",
        9,
        "HAN-09",
        "PARCEL",
        "per_parcel",
        "Speaker with accumulator battery",
        "QUOTE: each triggering customer pays the full fee (band on own weight), + markup (0 now), ÷ FX (Kango 19,500). Difference = surcharge margin.",
    ),
    (
        "han_air",
        10,
        "HAN-10",
        "PARCEL",
        "per_parcel",
        "Speaker without accumulator battery",
        "QUOTE: each triggering customer pays the full fee (band on own weight), + markup (0 now), ÷ FX (Kango 19,500). Difference = surcharge margin.",
    ),
    (
        "hcm_air",
        1,
        "HCM-01",
        "PARCEL",
        "parcel_kg_tier",
        "Nail polish",
        "QUOTE: each triggering customer pays the full fee (band on own weight), + markup (0 now), ÷ FX (Kango 19,500). Difference = surcharge margin.",
    ),
    (
        "hcm_air",
        2,
        "HCM-02",
        "PARCEL",
        "per_parcel",
        "Equipment with battery, 1–3 kg",
        "QUOTE: each triggering customer pays the full fee (band on own weight), + markup (0 now), ÷ FX (Kango 19,500). Difference = surcharge margin.",
    ),
    (
        "hcm_air",
        3,
        "HCM-03",
        "PARCEL",
        "per_parcel",
        "Equipment with battery, 4–8 kg",
        "QUOTE: each triggering customer pays the full fee (band on own weight), + markup (0 now), ÷ FX (Kango 19,500). Difference = surcharge margin.",
    ),
    (
        "hcm_air",
        4,
        "HCM-04",
        "PARCEL",
        "per_parcel",
        "Large equipment with battery; Power bank",
        "QUOTE: each triggering customer pays the full fee (band on own weight), + markup (0 now), ÷ FX (Kango 19,500). Difference = surcharge margin.",
    ),
    (
        "hcm_air",
        5,
        "HCM-05",
        "ITEM",
        "per_speaker",
        "Speaker without battery",
        "range: priced at minimum until confirmed",
    ),
    ("hcm_air", 6, "HCM-06", "ITEM", "per_speaker", "Speaker with battery, under 7 kg", None),
    ("hcm_air", 7, "HCM-07", "ITEM", "per_speaker", "Speaker with battery, 7–25 kg", None),
    ("hcm_air", 8, "HCM-08", "ITEM", "per_speaker", "Speaker with battery, 25–35 kg", None),
    ("hcm_air", 9, "HCM-09", "ITEM", "per_camera", "Camera without battery", None),
    (
        "hcm_air",
        10,
        "HCM-10",
        "ITEM",
        "per_camera",
        "Camera with battery",
        "estimate: priced at minimum until confirmed",
    ),
    (
        "hcm_air",
        11,
        "HCM-11",
        "PARCEL",
        "parcel_kg_tier_plus_bottle",
        "Perfume",
        "QUOTE: each triggering customer pays the full fee (band on own weight), + markup (0 now), ÷ FX (Kango 19,500). Difference = surcharge margin.",
    ),
    (
        "hcm_air",
        12,
        "HCM-12",
        "PARCEL",
        "per_parcel",
        "Pressurized spray / aerosol",
        "QUOTE: each triggering customer pays the full fee (band on own weight), + markup (0 now), ÷ FX (Kango 19,500). Difference = surcharge margin.",
    ),
    (
        "hcm_air",
        13,
        "HCM-13",
        "PARCEL",
        "per_parcel",
        "Fish sauce (liquid); Syrup (liquid); Shampoo (liquid); Other liquid products (not otherwise listed)",
        "QUOTE: each triggering customer pays the full fee (band on own weight), + markup (0 now), ÷ FX (Kango 19,500). Difference = surcharge margin.",
    ),
    (
        "hcm_air",
        14,
        "HCM-14",
        "WHOLE_PACKAGE",
        "full_carton_kg",
        "International-brand clothing",
        None,
    ),
    (
        "hcm_air",
        15,
        "HCM-15",
        "ITEM",
        "per_item",
        "International-brand handbag / bag; International-brand belt; International-brand glasses / sunglasses",
        None,
    ),
    ("hcm_air", 16, "HCM-16", "ITEM", "per_pair", "International-brand shoes / sandals", None),
    (
        "hcm_air",
        17,
        "HCM-17",
        "ITEM",
        "per_item",
        "Crocodile-leather bag; Crocodile-leather shoes; Crocodile-leather wallet",
        None,
    ),
    ("hcm_air", 18, "HCM-18", "ITEM", "per_watch", "Ordinary watch", None),
    ("hcm_air", 19, "HCM-19", "ITEM", "per_watch", "Imitation branded watch", None),
    ("hcm_air", 20, "HCM-20", "ITEM", "per_box", "Branded / imitation watch box", None),
    (
        "hcm_air",
        21,
        "HCM-21",
        "ITEM",
        "product_kg",
        "Agarwood incense; Agarwood powder; Other agarwood products",
        None,
    ),
    ("hcm_air", 22, "HCM-22", "ITEM", "product_kg", "Books; Magazines; Newspapers; Paper", None),
    ("hcm_air", 23, "HCM-23", "ITEM", "product_kg", "Edible bird's nest", None),
    ("hcm_air", 24, "HCM-24", "ITEM", "product_kg", "Saffron (listed as Safaron); Cordyceps", None),
    ("hcm_air", 25, "HCM-25", "ITEM", "product_kg", "Bottled bird's nest drink", None),
    ("hcm_air", 26, "HCM-26", "ITEM", "per_box", "Sexual-health medicines", None),
    (
        "hcm_air",
        27,
        "HCM-27",
        "ITEM",
        "product_kg",
        "Costume / imitation jewellery",
        "range: priced at minimum until confirmed",
    ),
    (
        "hcm_air",
        28,
        "HCM-28",
        "PARCEL",
        "per_parcel",
        "Hair dye; Tattoo ink",
        "QUOTE: each triggering customer pays the full fee (band on own weight), + markup (0 now), ÷ FX (Kango 19,500). Difference = surcharge margin.",
    ),
    ("hcm_air", 29, "HCM-29", "ITEM", "per_box", "Elasten (collagen / filter)", None),
    ("hcm_air", 30, "HCM-30", "ITEM", "per_box", "Korean ginseng products", None),
    (
        "hcm_air",
        31,
        "HCM-31",
        "ITEM",
        "per_machine",
        "Machinery with motor",
        "range: priced at minimum until confirmed",
    ),
    ("hcm_air", 32, "HCM-32", "ITEM", "product_kg", "Traditional herbal medicine", None),
    (
        "hcm_air",
        33,
        "HCM-33",
        "ITEM",
        "per_machine",
        "Hair-removal machine; Medical equipment",
        "range: priced at minimum until confirmed",
    ),
    (
        "hcm_air",
        34,
        "HCM-34",
        "ITEM",
        "per_camera",
        "Photo camera with battery; Photo camera without battery",
        "range: priced at minimum until confirmed",
    ),
    ("hcm_air", 35, "HCM-35", "ITEM", "product_kg", "False eyelashes; Wig / hairpiece", None),
    (
        "hcm_air",
        36,
        "HCM-36",
        "ITEM",
        "per_item",
        "Agarwood bracelet; Jade bracelet; Stone bracelet",
        None,
    ),
    ("hcm_air", 37, "HCM-37", "ITEM", "product_kg", "Imitation jewellery stones", None),
    ("hcm_air", 38, "HCM-38", "ITEM", "product_kg", "Powdered milk", None),
    ("hcm_air", 39, "HCM-39", "ITEM", "product_kg", "Western medicine / pharmaceuticals", None),
    ("hcm_air", 40, "HCM-40", "ITEM", "product_kg", "Rice; Seeds", None),
    (
        "hcm_air",
        41,
        "HCM-41",
        "ITEM",
        "product_kg",
        "Foods containing eggs; Foods containing honey; Foods containing meat; Foods containing milk",
        None,
    ),
    (
        "hcm_air",
        42,
        "HCM-42",
        "ITEM",
        "product_kg",
        "Imported / Chinese-language herbal medicines",
        None,
    ),
    (
        "hcm_air",
        43,
        "HCM-43",
        "ITEM",
        "product_kg",
        "Imported supplements (TPCN); Imported cosmetics",
        None,
    ),
    (
        "hcm_air",
        45,
        "HCM-45",
        "ITEM",
        "per_figure",
        "Labubu collectible figure",
        "range: priced at minimum until confirmed",
    ),
    ("hcm_air", 46, "HCM-46", "ITEM", "product_kg", "Medicinal rubbing oil", None),
    ("hcm_air", 47, "HCM-47", "WHOLE_MASTER", "per_lot", "Wood fumigation service", None),
    ("hcm_air", 48, "HCM-48", "ITEM", "product_kg", "Non-electronic machinery", None),
    ("hcm_air", 49, "HCM-49", "ITEM", "product_kg", "Medical test strips; Salonpas patches", None),
    ("hcm_air", 50, "HCM-50", "ITEM", "per_pair", "Contact lenses", None),
    ("hcm_air", 51, "HCM-51", "ITEM", "product_kg", "Wood products / timber", None),
    (
        "sea_ca_au_uk_eu",
        1,
        "SEA-01",
        "WHOLE_PACKAGE",
        "full_lot_or_parcel_kg",
        "Branded perfume; International-brand shoes / sandals; International-brand fashion goods",
        None,
    ),
    (
        "sea_ca_au_uk_eu",
        2,
        "SEA-02",
        "WHOLE_PACKAGE",
        "full_parcel_kg",
        "Batteries; Speakers; Machinery",
        None,
    ),
    (
        "sea_ca_au_uk_eu",
        3,
        "SEA-03",
        "WHOLE_PACKAGE",
        "full_parcel_kg",
        "Nail polish; Regular perfume",
        None,
    ),
    (
        "sea_ca_au_uk_eu",
        4,
        "SEA-04",
        "WHOLE_PACKAGE",
        "full_parcel_kg",
        "Dry food; Dietary supplements (TPCN); Cosmetics",
        None,
    ),
    (
        "sea_ca_au_uk_eu",
        5,
        "SEA-05",
        "WHOLE_PACKAGE",
        "full_parcel_kg",
        "Egg products; Meat products; Milk products; Seeds",
        None,
    ),
    (
        "sea_ca_au_uk_eu",
        6,
        "SEA-06",
        "WHOLE_MASTER",
        "shipment_chargeable_kg",
        "Labubu collectible figure",
        None,
    ),
    ("sea_ca_au_uk_eu", 7, "SEA-07", "WHOLE_PACKAGE", "full_parcel_kg", "Agarwood incense", None),
    (
        "sea_ca_au_uk_eu",
        8,
        "SEA-08",
        "WHOLE_PACKAGE",
        "full_parcel_kg",
        "Traditional / herbal medicines; Western medicine / pharmaceuticals",
        None,
    ),
    (
        "sea_ca_au_uk_eu",
        9,
        "SEA-09",
        "CONFIRM",
        "per_kg_basis_unstated",
        "Books; Newspapers / press materials; Printed documents",
        None,
    ),
    (
        "sea_ca_au_uk_eu",
        10,
        "SEA-10",
        "CONFIRM",
        "per_kg_basis_unstated",
        "Medical test strips; Salonpas patches",
        None,
    ),
    ("sea_ca_au_uk_eu", 11, "SEA-11", "CONFIRM", "per_kg_basis_unstated", "Jewellery", None),
]

UPS_BANDS = [("0.5", "5"), ("5.5", "10"), ("10.5", "20"), ("20.5", "30"), ("30.5", None)]


def upgrade() -> None:
    op.create_table(
        "pricing_method_settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("pricing_method", sa.String(length=10), nullable=False),
        sa.Column("air_std_rate_low_cad", sa.Numeric(precision=8, scale=2), nullable=False),
        sa.Column("air_std_threshold_kg", sa.Numeric(precision=7, scale=2), nullable=False),
        sa.Column("threshold_basis", sa.String(length=10), nullable=False),
        sa.Column("sea_rate_cad", sa.Numeric(precision=8, scale=2), nullable=False),
        sa.Column("markup_kind", sa.String(length=10), nullable=False),
        sa.Column("markup_value", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column("fx_source_cost", sa.String(length=15), nullable=False),
        sa.Column("fx_source_quote", sa.String(length=15), nullable=False),
        sa.Column("kango_fixed_rate_vnd", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("residual_mode", sa.String(length=12), nullable=False),
        sa.Column("pkg_surcharge_billing", sa.String(length=15), nullable=False),
        sa.Column("parcel_band_cost_basis", sa.String(length=10), nullable=False),
        sa.Column("parcel_quote_mode", sa.String(length=10), nullable=False),
        sa.Column("vendor_bill_rounding", sa.String(length=10), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("updated_by_user_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["updated_by_user_id"],
            ["users.id"],
            name=op.f("fk_pricing_method_settings_updated_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_pricing_method_settings")),
    )
    op.create_table(
        "consolidation_package_flags",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("consolidation_id", sa.Integer(), nullable=False),
        sa.Column("carton_sequence", sa.Integer(), nullable=False),
        sa.Column("packed_as_one_box", sa.Boolean(), nullable=False),
        sa.Column("set_at", sa.DateTime(), nullable=False),
        sa.Column("set_by_user_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["consolidation_id"],
            ["consolidations.id"],
            name=op.f("fk_consolidation_package_flags_consolidation_id_consolidations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["set_by_user_id"],
            ["users.id"],
            name=op.f("fk_consolidation_package_flags_set_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_consolidation_package_flags")),
        sa.UniqueConstraint(
            "consolidation_id",
            "carton_sequence",
            name=op.f("uq_consolidation_package_flags_consolidation_id_carton_sequence"),
        ),
    )
    op.create_index(
        op.f("ix_consolidation_package_flags_consolidation_id"),
        "consolidation_package_flags",
        ["consolidation_id"],
        unique=False,
    )
    op.create_table(
        "consolidation_manual_pricing",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("consolidation_id", sa.Integer(), nullable=False),
        sa.Column("manual_cost_vnd_per_kg", sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column("manual_cost_vnd_total", sa.Numeric(precision=16, scale=2), nullable=True),
        sa.Column("manual_sell_cad_per_kg", sa.Numeric(precision=8, scale=2), nullable=True),
        sa.Column("reason", sa.String(length=400), nullable=True),
        sa.Column("set_at", sa.DateTime(), nullable=False),
        sa.Column("set_by_user_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["consolidation_id"],
            ["consolidations.id"],
            name=op.f("fk_consolidation_manual_pricing_consolidation_id_consolidations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["set_by_user_id"],
            ["users.id"],
            name=op.f("fk_consolidation_manual_pricing_set_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_consolidation_manual_pricing")),
        sa.UniqueConstraint(
            "consolidation_id", name=op.f("uq_consolidation_manual_pricing_consolidation_id")
        ),
    )
    op.create_table(
        "ups_rate_bands",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("band_from_kg", sa.Numeric(precision=7, scale=2), nullable=False),
        sa.Column("band_to_kg", sa.Numeric(precision=7, scale=2), nullable=True),
        sa.Column("cost_vnd", sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column("sell_cad_per_kg", sa.Numeric(precision=8, scale=2), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("effective_from", sa.Date(), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ups_rate_bands")),
    )
    op.create_table(
        "surcharge_allocation_classes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("section", sa.String(length=20), nullable=False),
        sa.Column("stt", sa.Integer(), nullable=False),
        sa.Column("kango_code", sa.String(length=10), nullable=False),
        sa.Column("allocation_class", sa.String(length=15), nullable=False),
        sa.Column("basis", sa.String(length=40), nullable=False),
        sa.Column("products", sa.Text(), nullable=False),
        sa.Column("flags", sa.String(length=300), nullable=True),
        sa.Column("source", sa.String(length=60), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_surcharge_allocation_classes")),
        sa.UniqueConstraint(
            "section", "stt", name=op.f("uq_surcharge_allocation_classes_section_stt")
        ),
    )

    now = datetime(2026, 11, 2)
    settings = sa.table(
        "pricing_method_settings",
        *(
            sa.column(name)
            for name in (
                "id",
                "pricing_method",
                "air_std_rate_low_cad",
                "air_std_threshold_kg",
                "threshold_basis",
                "sea_rate_cad",
                "markup_kind",
                "markup_value",
                "fx_source_cost",
                "fx_source_quote",
                "kango_fixed_rate_vnd",
                "residual_mode",
                "pkg_surcharge_billing",
                "parcel_band_cost_basis",
                "parcel_quote_mode",
                "vendor_bill_rounding",
                "updated_at",
            )
        ),
    )
    op.bulk_insert(
        settings,
        [
            {
                "id": 1,
                "pricing_method": "rc25",
                "air_std_rate_low_cad": 19,
                "air_std_threshold_kg": 21,
                "threshold_basis": "customer",
                "sea_rate_cad": 8,
                "markup_kind": "none",
                "markup_value": 0,
                "fx_source_cost": "kango_fixed",
                "fx_source_quote": "kango_fixed",
                "kango_fixed_rate_vnd": 19500,
                "residual_mode": "prorata",
                "pkg_surcharge_billing": "same_as_cost",
                "parcel_band_cost_basis": "box",
                "parcel_quote_mode": "each",
                "vendor_bill_rounding": "kango",
                "updated_at": now,
            }
        ],
    )
    bands = sa.table(
        "ups_rate_bands", sa.column("band_from_kg"), sa.column("band_to_kg"), sa.column("currency")
    )
    op.bulk_insert(
        bands, [{"band_from_kg": a, "band_to_kg": b, "currency": "VND"} for a, b in UPS_BANDS]
    )
    classes = sa.table(
        "surcharge_allocation_classes",
        *(
            sa.column(name)
            for name in (
                "section",
                "stt",
                "kango_code",
                "allocation_class",
                "basis",
                "products",
                "flags",
                "source",
            )
        ),
    )
    op.bulk_insert(
        classes,
        [
            {
                "section": section,
                "stt": stt,
                "kango_code": code,
                "allocation_class": cls,
                "basis": basis,
                "products": products,
                "flags": flags,
                "source": "surcharge_allocation_rules.csv v0.5",
            }
            for section, stt, code, cls, basis, products, flags in ALLOCATION_ROWS
        ],
    )


def downgrade() -> None:
    op.drop_table("surcharge_allocation_classes")
    op.drop_table("ups_rate_bands")
    op.drop_table("consolidation_manual_pricing")
    op.drop_index(
        op.f("ix_consolidation_package_flags_consolidation_id"),
        table_name="consolidation_package_flags",
    )
    op.drop_table("consolidation_package_flags")
    op.drop_table("pricing_method_settings")
