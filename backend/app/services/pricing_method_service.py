"""The confirmed method's settings and per-master inputs (Louis, from 2026-11-02).

Reads and writes the method tables (``app/models/pricing_method.py``) and turns them into the
pure engine's inputs (``app/pricing/cost_method.py``). The pricing switch lives here:
``pricing_method`` ``confirmed`` (the owner's method; version-neutral since DEC-0267) or
``rc25`` (the RC-UAT-25 engine). ``v0_5`` / ``v0_6`` / ``v0_7`` are stored as ``confirmed``.

v0.6 (Louis, 2026-11-03) adds: the sea vendor's rate (``sea_vendor_rates``) and surcharges
(``sea_surcharge_rules``), the package customer note and the customer ↔ package record.

Reading never writes (DEC-0204): with no saved row the defaults are an unsaved object.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.time_utils import utcnow
from app.models import (
    Consolidation,
    ConsolidationManualPricing,
    ConsolidationPackageFlag,
    ConsolidationPackageMember,
    ConsolidationPackageNote,
    PricingMethodSettings,
    PricingSettings,
    SeaSurchargeRule,
    SeaVendorRate,
    SurchargeAllocationClass,
    UpsRateBand,
    User,
)
from app.models.pricing_method import (
    ALLOCATION_CLASSES,
    FX_SOURCES,
    KANGO_FIXED_RATE_VND,
    LEGACY_METHOD_NAMES,
    MARKUP_KINDS,
    PARCEL_BAND_COST_BASES,
    PARCEL_QUOTE_MODES,
    PKG_SURCHARGE_BILLINGS,
    PRICING_METHODS,
    RESIDUAL_MODES,
    SEA_COST_VND_PER_KG,
    THRESHOLD_BASES,
    VENDOR_BILL_ROUNDINGS,
)
from app.pricing import allocation_classes
from app.pricing import cost_method as mv
from app.services import audit_service
from app.services.errors import ValidationError

CHOICES: dict[str, tuple[str, ...]] = {
    "pricing_method": PRICING_METHODS,
    "threshold_basis": THRESHOLD_BASES,
    "markup_kind": MARKUP_KINDS,
    "fx_source_cost": FX_SOURCES,
    "fx_source_quote": FX_SOURCES,
    "residual_mode": RESIDUAL_MODES,
    "pkg_surcharge_billing": PKG_SURCHARGE_BILLINGS,
    "parcel_band_cost_basis": PARCEL_BAND_COST_BASES,
    "parcel_quote_mode": PARCEL_QUOTE_MODES,
    "vendor_bill_rounding": VENDOR_BILL_ROUNDINGS,
}
#: Numeric settings and their bounds (inclusive).
NUMBERS: dict[str, tuple[Decimal, Decimal]] = {
    "air_std_rate_low_cad": (Decimal("0.01"), Decimal("1000")),
    "air_std_threshold_kg": (Decimal("0.5"), Decimal("1000")),
    "sea_rate_cad": (Decimal("0.01"), Decimal("1000")),
    "markup_value": (Decimal("0"), Decimal("1000")),
    "kango_fixed_rate_vnd": (Decimal("1000"), Decimal("100000")),
}


def get_method_settings(db: Session) -> PricingMethodSettings:
    row = db.scalar(select(PricingMethodSettings).order_by(PricingMethodSettings.id).limit(1))
    if row is None:
        row = PricingMethodSettings(
            pricing_method="confirmed",  # DEC-0252 / 0253 / 0260 / 0267: the owner's method
            air_std_rate_low_cad=Decimal("19.00"),
            air_std_threshold_kg=Decimal("21"),
            threshold_basis="customer",
            sea_rate_cad=Decimal("8.00"),
            markup_kind="none",
            markup_value=Decimal("0"),
            fx_source_cost="kango_fixed",
            fx_source_quote="kango_fixed",
            kango_fixed_rate_vnd=KANGO_FIXED_RATE_VND,
            residual_mode="prorata",
            pkg_surcharge_billing="same_as_cost",
            parcel_band_cost_basis="box",
            parcel_quote_mode="each",
            vendor_bill_rounding="kango",
            updated_at=utcnow(),
        )
    return row


def uses_confirmed_method(db: Session) -> bool:
    """True when the confirmed method (v0.6; the module keeps its v0.5 name) prices."""
    return get_method_settings(db).pricing_method != "rc25"


def update_method_settings(
    db: Session, payload: dict[str, Any], *, actor: User | None
) -> PricingMethodSettings:
    row = get_method_settings(db)
    changed: dict[str, str] = {}
    for key, choices in CHOICES.items():
        if key in payload and payload[key] is not None:
            value = str(payload[key])
            if key == "pricing_method":
                value = LEGACY_METHOD_NAMES.get(value, value)
            if value not in choices:
                raise ValidationError(f"{key} must be one of {', '.join(choices)}.", field=key)
            if getattr(row, key) != value:
                setattr(row, key, value)
                changed[key] = value
    for key, (low, high) in NUMBERS.items():
        if key in payload and payload[key] is not None:
            try:
                value = Decimal(str(payload[key]))
            except InvalidOperation as error:
                raise ValidationError(f"{key} must be a number.", field=key) from error
            if not low <= value <= high:
                raise ValidationError(f"{key} must be between {low} and {high}.", field=key)
            if getattr(row, key) != value:
                setattr(row, key, value)
                changed[key] = str(value)
    if row.markup_kind == "none":
        row.markup_value = Decimal("0")
    row.updated_at = utcnow()
    row.updated_by_user_id = actor.id if actor else None
    if row.id is None:
        row.id = 1
        db.add(row)
    db.flush()
    if changed:
        audit_service.record_audit(
            db,
            action="pricing.method_settings_update",
            entity_type="pricing_settings",
            entity_id=row.id,
            summary="Updated the method pricing settings: " + ", ".join(sorted(changed)),
            actor=actor,
            detail=changed,
        )
    return row


def engine_settings(
    db: Session, pricing: PricingSettings, *, on: date | None = None
) -> mv.MethodSettings:
    """The engine's settings; ``on`` dates the effective-dated sea vendor rate (the master's
    booking or creation date, so an old master keeps its rate)."""
    row = get_method_settings(db)
    return mv.MethodSettings(
        air_std_rate_high_cad=pricing.air_standard_default_rate_cad,
        air_std_rate_low_cad=row.air_std_rate_low_cad,
        air_std_threshold_kg=row.air_std_threshold_kg,
        threshold_basis=row.threshold_basis,
        sea_rate_cad=row.sea_rate_cad,
        markup_kind=row.markup_kind,
        markup_value=row.markup_value,
        fx_source_cost=row.fx_source_cost,
        fx_source_quote=row.fx_source_quote,
        kango_fixed_rate_vnd=row.kango_fixed_rate_vnd,
        residual_mode=row.residual_mode,
        pkg_surcharge_billing=row.pkg_surcharge_billing,
        parcel_band_cost_basis=row.parcel_band_cost_basis,
        parcel_quote_mode=row.parcel_quote_mode,
        vendor_bill_rounding=row.vendor_bill_rounding,
        sea_cost_vnd_per_kg=sea_cost_vnd_per_kg(db, on),
        air_express_rate_cad=pricing.air_express_default_rate_cad,
    )


# --- Sea (v0.6) -------------------------------------------------------------------------------


def sea_cost_vnd_per_kg(db: Session, on: date | None = None) -> Decimal:
    """The sea vendor's cost per kg in force on ``on`` (default today): the latest row with
    ``effective_from`` on or before it; 60,000 where no row is loaded (Louis, 2026-11-03)."""
    on = on or utcnow().date()
    row = db.scalar(
        select(SeaVendorRate)
        .where(SeaVendorRate.effective_from <= on)
        .order_by(SeaVendorRate.effective_from.desc())
        .limit(1)
    )
    return row.sea_cost_vnd_per_kg if row is not None else SEA_COST_VND_PER_KG


#: The two sea vendor surcharges, used where the table is empty (a database built without
#: Alembic): (id, code, Vietnamese name, English name, VND per kg, minimum VND per package).
SEA_RULE_DEFAULTS = (
    (1, "SEA-FOOD", "Hàng thực phẩm", "Food", Decimal(30000), Decimal(400000)),
    (2, "SEA-FUNCFOOD", "Hàng thực phẩm chức năng", "Functional food / supplements",
     Decimal(40000), Decimal(500000)),
)  # fmt: skip


def sea_cost_rows(db: Session) -> list[dict]:
    return [
        {
            "effective_from": r.effective_from,
            "sea_cost_vnd_per_kg": r.sea_cost_vnd_per_kg,
            "source": r.source,
        }
        for r in db.scalars(select(SeaVendorRate).order_by(SeaVendorRate.effective_from))
    ]


def sea_rule_map(db: Session) -> dict[int, mv.SeaRule]:
    rows = list(db.scalars(select(SeaSurchargeRule).order_by(SeaSurchargeRule.id)))
    if rows:
        return {
            r.id: mv.SeaRule(r.id, r.code, r.name_vi, r.rate_vnd_per_kg, r.min_vnd_per_package)
            for r in rows
            if r.is_active
        }
    return {
        rid: mv.SeaRule(rid, code, name_vi, rate, minimum)
        for rid, code, name_vi, _en, rate, minimum in SEA_RULE_DEFAULTS
    }


def seed_sea_rules(db: Session) -> int:
    """Load the two sea rules and the 60,000 rate where missing (a database built without
    Alembic, e.g. the test suite); the migration seeds them otherwise."""
    added = 0
    if db.scalar(select(SeaSurchargeRule).limit(1)) is None:
        for rid, code, name_vi, name_en, rate, minimum in SEA_RULE_DEFAULTS:
            db.add(
                SeaSurchargeRule(
                    id=rid, code=code, name_vi=name_vi, name_en=name_en, rate_vnd_per_kg=rate,
                    min_vnd_per_package=minimum, is_active=True,
                    effective_from=date(2026, 11, 3), source="Louis 2026-11-03",
                )
            )  # fmt: skip
            added += 1
    if db.scalar(select(SeaVendorRate).limit(1)) is None:
        db.add(
            SeaVendorRate(
                sea_cost_vnd_per_kg=SEA_COST_VND_PER_KG,
                effective_from=date(2026, 11, 3),
                source="Louis 2026-11-03",
            )
        )
        added += 1
    db.flush()
    return added


def set_sea_cost(
    db: Session, value: Any, effective_from: date, *, actor: User | None
) -> SeaVendorRate:
    """Record a new sea vendor rate from a date; earlier rates stay for earlier masters."""
    amount = _positive(value, "sea_cost_vnd_per_kg")
    if amount is None:
        raise ValidationError("Enter the sea vendor's cost per kg.", field="sea_cost_vnd_per_kg")
    row = db.scalar(select(SeaVendorRate).where(SeaVendorRate.effective_from == effective_from))
    if row is None:
        row = SeaVendorRate(effective_from=effective_from, source="Settings")
        db.add(row)
    row.sea_cost_vnd_per_kg = amount
    db.flush()
    audit_service.record_audit(
        db,
        action="pricing.sea_cost_set",
        entity_type="pricing_settings",
        entity_id=row.id,
        summary=f"Sea vendor cost {amount} VND/kg from {effective_from.isoformat()}",
        actor=actor,
        detail={"sea_cost_vnd_per_kg": str(amount), "effective_from": effective_from.isoformat()},
    )
    return row


# --- Allocation classes -------------------------------------------------------------------------


def allocation_class_map(db: Session) -> dict[tuple[str, int], str]:
    """The loaded classes; the CSV's own rows where none are loaded (a database built without
    Alembic), so v0.5 classes the same everywhere. Loaded rows win."""
    loaded = {
        (r.section, r.stt): r.allocation_class for r in db.scalars(select(SurchargeAllocationClass))
    }
    if loaded:
        return loaded
    return {(row[0], row[1]): row[3] for row in allocation_classes.ALLOCATION_ROWS}


def seed_allocation_classes(db: Session) -> int:
    """Load the CSV's classes where a row is missing (a database built without Alembic)."""
    have = {(r.section, r.stt) for r in db.scalars(select(SurchargeAllocationClass))}
    added = 0
    for section, stt, code, cls, basis, products, flags in allocation_classes.ALLOCATION_ROWS:
        if (section, stt) in have:
            continue
        db.add(
            SurchargeAllocationClass(
                section=section,
                stt=stt,
                kango_code=code,
                allocation_class=cls,
                basis=basis,
                products=products,
                flags=flags,
                source=allocation_classes.SOURCE,
            )
        )
        added += 1
    db.flush()
    return added


def set_allocation_class(
    db: Session, section: str, stt: int, allocation_class: str, *, actor: User | None
) -> SurchargeAllocationClass:
    if allocation_class not in ALLOCATION_CLASSES:
        raise ValidationError(
            f"allocation_class must be one of {', '.join(ALLOCATION_CLASSES)}.",
            field="allocation_class",
        )
    row = db.scalar(
        select(SurchargeAllocationClass).where(
            SurchargeAllocationClass.section == section, SurchargeAllocationClass.stt == stt
        )
    )
    before = row.allocation_class if row else None
    if row is None:
        row = SurchargeAllocationClass(
            section=section,
            stt=stt,
            kango_code=f"{section}-{stt}",
            basis="owner",
            products="",
            source="owner override",
        )
        db.add(row)
    row.allocation_class = allocation_class
    db.flush()
    audit_service.record_audit(
        db,
        action="pricing.allocation_class_set",
        entity_type="pricing_settings",
        entity_id=row.id,
        summary=f"Allocation class of {section} row {stt}: {before} → {allocation_class}",
        actor=actor,
        detail={"section": section, "stt": stt, "before": before, "after": allocation_class},
    )
    return row


# --- Per master: package flags and manual pricing ------------------------------------------------


def package_flags(db: Session, consolidation_id: int) -> dict[int, bool]:
    return {
        f.carton_sequence: f.packed_as_one_box
        for f in db.scalars(
            select(ConsolidationPackageFlag).where(
                ConsolidationPackageFlag.consolidation_id == consolidation_id
            )
        )
    }


def set_package_flag(
    db: Session, consolidation_id: int, carton_sequence: int, packed: bool, *, actor: User | None
) -> ConsolidationPackageFlag:
    if carton_sequence < 1:
        raise ValidationError("The package sequence starts at 1.", field="carton_sequence")
    if packed:
        from app.models import ConsolidationCarton  # noqa: PLC0415

        cartons = db.scalars(
            select(ConsolidationCarton.sequence).where(
                ConsolidationCarton.consolidation_id == consolidation_id
            )
        ).all()
        if len(cartons) > 1 or carton_sequence > max(cartons or [1]):
            raise ValidationError(
                "'Packed as one box for Kango' is allowed only on a master with one package.",
                field="packed_as_one_box",
            )
    row = db.scalar(
        select(ConsolidationPackageFlag).where(
            ConsolidationPackageFlag.consolidation_id == consolidation_id,
            ConsolidationPackageFlag.carton_sequence == carton_sequence,
        )
    )
    before = row.packed_as_one_box if row else False
    if row is None:
        row = ConsolidationPackageFlag(
            consolidation_id=consolidation_id, carton_sequence=carton_sequence
        )
        db.add(row)
    row.packed_as_one_box = bool(packed)
    row.set_at = utcnow()
    row.set_by_user_id = actor.id if actor else None
    db.flush()
    if before != row.packed_as_one_box:
        audit_service.record_audit(
            db,
            action="consolidation.package_packed_as_one_box",
            entity_type="consolidation",
            entity_id=consolidation_id,
            summary=(
                f"Package {carton_sequence} {'marked' if packed else 'unmarked'} as packed as "
                "one box for Kango"
            ),
            actor=actor,
            detail={"carton_sequence": carton_sequence, "packed_as_one_box": bool(packed)},
        )
    return row


def get_manual_pricing(db: Session, consolidation_id: int) -> ConsolidationManualPricing | None:
    return db.scalar(
        select(ConsolidationManualPricing).where(
            ConsolidationManualPricing.consolidation_id == consolidation_id
        )
    )


def _positive(value: Any, field: str) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        number = Decimal(str(value))
    except InvalidOperation as error:
        raise ValidationError(f"{field} must be a number.", field=field) from error
    if number <= 0:
        raise ValidationError(f"{field} must be positive.", field=field)
    return number


def set_manual_pricing(
    db: Session, consolidation_id: int, payload: dict[str, Any], *, actor: User | None
) -> ConsolidationManualPricing:
    per_kg = _positive(payload.get("manual_cost_vnd_per_kg"), "manual_cost_vnd_per_kg")
    total = _positive(payload.get("manual_cost_vnd_total"), "manual_cost_vnd_total")
    sell = _positive(payload.get("manual_sell_cad_per_kg"), "manual_sell_cad_per_kg")
    if per_kg is not None and total is not None:
        raise ValidationError(
            "Enter the vendor cost per kg or as a total, not both.", field="manual_cost_vnd_total"
        )
    reason = str(payload.get("reason") or "").strip() or None
    consolidation = db.get(Consolidation, consolidation_id)
    if (
        consolidation is not None
        and consolidation.solaris_service not in mv.MANUAL_SERVICES
        and (per_kg is not None or total is not None)
        and reason is None
    ):
        # DEC-0271: overriding a rate-sheet base cost needs a reason, kept with the audit row.
        raise ValidationError(
            "Give a reason for entering the vendor base cost instead of the rate sheet.",
            field="reason",
        )
    row = get_manual_pricing(db, consolidation_id)
    if row is None:
        row = ConsolidationManualPricing(consolidation_id=consolidation_id)
        db.add(row)
    row.manual_cost_vnd_per_kg = per_kg
    row.manual_cost_vnd_total = total
    row.manual_sell_cad_per_kg = sell
    row.reason = reason
    row.set_at = utcnow()
    row.set_by_user_id = actor.id if actor else None
    db.flush()
    audit_service.record_audit(
        db,
        action="consolidation.manual_pricing_set",
        entity_type="consolidation",
        entity_id=consolidation_id,
        summary="Set the manual vendor cost / selling rate",
        actor=actor,
        detail={
            "manual_cost_vnd_per_kg": str(per_kg) if per_kg is not None else None,
            "manual_cost_vnd_total": str(total) if total is not None else None,
            "manual_sell_cad_per_kg": str(sell) if sell is not None else None,
            "reason": reason,
        },
    )
    return row


def manual_view(db: Session, consolidation_id: int) -> mv.ManualPricing:
    row = get_manual_pricing(db, consolidation_id)
    if row is None:
        return mv.ManualPricing()
    return mv.ManualPricing(
        row.manual_cost_vnd_per_kg,
        row.manual_cost_vnd_total,
        row.manual_sell_cad_per_kg,
        row.reason,
    )


def ups_bands(db: Session) -> list[mv.UpsBand]:
    return [
        mv.UpsBand(b.band_from_kg, b.band_to_kg, b.cost_vnd, b.sell_cad_per_kg)
        for b in db.scalars(select(UpsRateBand).order_by(UpsRateBand.band_from_kg))
    ]


# --- Packages: customer note and customer ↔ package (v0.6) ----------------------------------------


def package_notes(db: Session, consolidation_id: int) -> dict[int, str]:
    return {
        n.carton_sequence: n.customer_note
        for n in db.scalars(
            select(ConsolidationPackageNote).where(
                ConsolidationPackageNote.consolidation_id == consolidation_id
            )
        )
    }


def set_package_note(
    db: Session, consolidation_id: int, carton_sequence: int, note: str | None, *,
    actor: User | None,
) -> ConsolidationPackageNote | None:  # fmt: skip
    """``packages.customer_note`` (Louis Q7): optional short text, e.g. "STCA-000201, -202".
    An empty note removes it. Display only."""
    if carton_sequence < 1:
        raise ValidationError("The package sequence starts at 1.", field="carton_sequence")
    text = " ".join(str(note or "").split())
    if len(text) > 200:
        raise ValidationError("Keep the note under 200 characters.", field="customer_note")
    row = db.scalar(
        select(ConsolidationPackageNote).where(
            ConsolidationPackageNote.consolidation_id == consolidation_id,
            ConsolidationPackageNote.carton_sequence == carton_sequence,
        )
    )
    if not text:
        if row is not None:
            db.delete(row)
            db.flush()
        return None
    if row is None:
        row = ConsolidationPackageNote(
            consolidation_id=consolidation_id, carton_sequence=carton_sequence
        )
        db.add(row)
    row.customer_note = text
    row.set_at = utcnow()
    row.set_by_user_id = actor.id if actor else None
    db.flush()
    audit_service.record_audit(
        db,
        action="consolidation.package_note_set",
        entity_type="consolidation",
        entity_id=consolidation_id,
        summary=f"Package {carton_sequence} note: {text}",
        actor=actor,
        detail={"carton_sequence": carton_sequence, "customer_note": text},
    )
    return row


def package_members(db: Session, consolidation_id: int) -> dict[int, int]:
    """shipment id → package sequence, as recorded."""
    return {
        m.shipment_id: m.carton_sequence
        for m in db.scalars(
            select(ConsolidationPackageMember).where(
                ConsolidationPackageMember.consolidation_id == consolidation_id
            )
        )
    }


def set_package_member(
    db: Session, consolidation_id: int, shipment_id: int, carton_sequence: int | None, *,
    actor: User | None,
) -> ConsolidationPackageMember | None:  # fmt: skip
    """Place a customer shipment in a package of its master (None removes the record)."""
    row = db.scalar(
        select(ConsolidationPackageMember).where(
            ConsolidationPackageMember.consolidation_id == consolidation_id,
            ConsolidationPackageMember.shipment_id == shipment_id,
        )
    )
    if carton_sequence is None:
        if row is not None:
            db.delete(row)
            db.flush()
        return None
    if int(carton_sequence) < 1:
        raise ValidationError("The package sequence starts at 1.", field="carton_sequence")
    if row is None:
        row = ConsolidationPackageMember(consolidation_id=consolidation_id, shipment_id=shipment_id)
        db.add(row)
    before = row.carton_sequence
    row.carton_sequence = int(carton_sequence)
    row.set_at = utcnow()
    row.set_by_user_id = actor.id if actor else None
    db.flush()
    if before != row.carton_sequence:
        audit_service.record_audit(
            db,
            action="consolidation.package_member_set",
            entity_type="consolidation",
            entity_id=consolidation_id,
            summary=f"Shipment {shipment_id} placed in package {row.carton_sequence}",
            actor=actor,
            detail={"shipment_id": shipment_id, "carton_sequence": row.carton_sequence},
        )
    return row
