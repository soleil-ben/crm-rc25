"""Pricing: load the engine's inputs, manage fee lines, and version customer quotes (Phase 13C).

The arithmetic lives in ``app/pricing/engine.py`` and is pure; this module reads the database
into the engine's dataclasses, writes what it returns, and enforces the workflow:

* **Fee lines** are attached by staff to an item through the fee picker (owner decision 4).
  One active line per item and rule; removal keeps the row.
* **A quote needs a consolidation.** Vendor cost is a share of a master booking (handoff
  section 5), so a shipment is quoted once it rides in one.
* **One open draft per shipment.** Re-pricing rewrites the draft. The selling rate starts at
  the service's default (OD-48) and is **not confirmed** until staff confirm it; any other
  rate needs a typed reason (OD-45). A change to the quote's inputs (billable weight, the
  shipment's fee lines, the triggers it shares a master-wide fee with, the service or the
  consolidation) revokes the confirmation (SC-07).
* **Finalising** re-prices first, then refuses while the confirmation is missing or stale,
  while **any** blocking issue exists anywhere in the consolidation (an unpriced rule can
  move cost onto every member through the master-wide split),
  or while a surcharge line bills below its cost without a reason (OD-44). A finalised
  version is frozen with its full snapshot and supersedes the previous finalised one.

Everything here is internal: vendor cost and margin beside the customer price.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, replace
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from fractions import Fraction
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.enums import (
    BeyondRateStatus,
    ConsolidationState,
    SolarisService,
    SurchargeBasis,
    SurchargePricingStatus,
    SurchargeScope,
    SurchargeSection,
    TariffLastMile,
)
from app.core.time_utils import utcnow
from app.models import (
    DEFAULT_VENDOR_DELIVERY_POSTAL_CODE,
    KANGO_VENDOR_KEY,
    Consolidation,
    ConsolidationCarton,
    FeeLineManualPrice,
    MarkupDefault,
    PricingSettings,
    QuoteLine,
    QuoteVersion,
    Shipment,
    ShipmentFeeLine,
    ShipmentItem,
    SurchargeRulePolicy,
    TariffBeyondPostalCode,
    TariffBeyondRate,
    TariffProduct,
    TariffRateBracket,
    TariffSurchargeRule,
    TariffVersion,
    TariffZoneFsa,
    User,
)
from app.pricing import cost_method as mv
from app.pricing import engine as pe
from app.pricing import kango_semantics
from app.services import (
    audit_service,
    consolidation_service,
    fx_service,
    master_lock_service,
    package_service,
    pricing_method_service,
    quote_offer_service,
    tariff_import_service,
)
from app.services.errors import ConflictError, NotFoundError, ValidationError

MARKUP_KINDS = ("pass_through", "fixed_cad", "percent")
#: A rule's policy may also inherit the default markup while overriding only the scope.
POLICY_MARKUP_KINDS = (*MARKUP_KINDS, "default")
ORIGIN_SECTION = {"HCM": "hcm_air", "HAN": "han_air"}
#: Air only for now (OD-49): sea sections are neither priced nor attachable.
AIR_SECTIONS = frozenset(ORIGIN_SECTION.values())
#: The sea vendor's own surcharges (v0.6): ``stt`` is ``sea_surcharge_rules.id``.
SEA_VENDOR_SECTION = "sea_vendor"


# --- Settings and policies --------------------------------------------------------------------


def get_settings(db: Session) -> PricingSettings:
    """The settings row, or the defaults when none has been saved yet.

    Reading never writes: the defaults are an unsaved object, and the row is created only
    when an administrator saves the settings. Creating it on first read made every screen
    that loads at once race to insert it, and under SQLite's snapshot transactions the
    loser's next write failed with "database is locked" (DEC-0204).
    """
    row = db.scalar(select(PricingSettings).order_by(PricingSettings.id).limit(1))
    if row is None:
        row = PricingSettings(
            air_standard_default_rate_cad=Decimal("18.00"),
            air_express_default_rate_cad=None,
            trigger_share_numerator=2,
            trigger_share_denominator=3,
            defaults_owner_confirmed=True,  # OD-48, confirmed 2026-10-20
            vendor_delivery_postal_code=DEFAULT_VENDOR_DELIVERY_POSTAL_CODE,
            updated_at=utcnow(),
        )
    return row


def update_settings(db: Session, payload: dict[str, Any], *, actor: User | None) -> PricingSettings:
    row = get_settings(db)
    if row.id is None:
        db.add(row)
    changed: dict[str, str] = {}
    if (
        "air_standard_default_rate_cad" in payload
        and payload["air_standard_default_rate_cad"] is not None
    ):
        value = Decimal(str(payload["air_standard_default_rate_cad"]))
        if value <= 0:
            raise ValidationError(
                "The default rate must be positive.", field="air_standard_default_rate_cad"
            )
        row.air_standard_default_rate_cad = value
        changed["air_standard_default_rate_cad"] = str(value)
    if "air_express_default_rate_cad" in payload:
        value = payload["air_express_default_rate_cad"]
        value = Decimal(str(value)) if value is not None else None
        if value is not None and value <= 0:
            raise ValidationError(
                "The default rate must be positive.", field="air_express_default_rate_cad"
            )
        row.air_express_default_rate_cad = value
        changed["air_express_default_rate_cad"] = str(value)
    if "trigger_share_numerator" in payload or "trigger_share_denominator" in payload:
        num = int(payload.get("trigger_share_numerator", row.trigger_share_numerator))
        den = int(payload.get("trigger_share_denominator", row.trigger_share_denominator))
        if den <= 0 or num <= 0 or num > den:
            raise ValidationError(
                "The trigger share is a fraction between 0 and 1.", field="trigger_share_numerator"
            )
        row.trigger_share_numerator, row.trigger_share_denominator = num, den
        changed["trigger_share"] = f"{num}/{den}"
    if "defaults_owner_confirmed" in payload and payload["defaults_owner_confirmed"] is not None:
        row.defaults_owner_confirmed = bool(payload["defaults_owner_confirmed"])
        changed["defaults_owner_confirmed"] = str(row.defaults_owner_confirmed)
    if "vendor_delivery_postal_code" in payload and payload["vendor_delivery_postal_code"]:
        code = str(payload["vendor_delivery_postal_code"]).upper().replace(" ", "")
        if len(code) != 6:
            raise ValidationError(
                "Enter a Canadian postal code.", field="vendor_delivery_postal_code"
            )
        row.vendor_delivery_postal_code = code
        changed["vendor_delivery_postal_code"] = code
    row.updated_at = utcnow()
    row.updated_by_user_id = actor.id if actor else None
    db.flush()
    if changed:
        audit_service.record_audit(
            db,
            action="pricing.settings_update",
            entity_type="pricing_settings",
            entity_id=row.id,
            summary="Updated pricing settings: " + ", ".join(sorted(changed)),
            actor=actor,
            detail=changed,
        )
    return row


def list_policies(db: Session) -> list[SurchargeRulePolicy]:
    return list(
        db.scalars(
            select(SurchargeRulePolicy).order_by(
                SurchargeRulePolicy.section, SurchargeRulePolicy.stt
            )
        )
    )


def set_policy(
    db: Session, section: str, stt: int, payload: dict[str, Any], *, actor: User | None
) -> SurchargeRulePolicy:
    # No markup named = inherit the default markup (OD-74), e.g. a scope-only override.
    kind = payload.get("markup_kind") or "default"
    if kind not in POLICY_MARKUP_KINDS:
        raise ValidationError(
            f"Markup must be one of {', '.join(POLICY_MARKUP_KINDS)}.", field="markup_kind"
        )
    value = Decimal(str(payload.get("markup_value") or 0))
    if kind in {"pass_through", "default"}:
        value = Decimal(0)
    elif value < 0:
        raise ValidationError("A markup cannot be negative.", field="markup_value")
    scope = payload.get("scope_override")
    if scope is not None and scope not in set(SurchargeScope):
        raise ValidationError("Unknown scope.", field="scope_override")
    if section not in AIR_SECTIONS:
        raise ValidationError(
            "Only air surcharges have a policy; sea is not priced for now (OD-49).",
            field="section",
        )
    version = tariff_import_service.active_version(db, KANGO_VENDOR_KEY)
    rule = (
        db.scalar(
            select(TariffSurchargeRule).where(
                TariffSurchargeRule.version_id == version.id,
                TariffSurchargeRule.section == section,
                TariffSurchargeRule.stt == stt,
            )
        )
        if version is not None
        else None
    )
    if version is not None and rule is None:
        raise NotFoundError("That surcharge is not in the active tariff.")
    if (
        rule is not None
        and scope in {SurchargeScope.FULL_MASTER, SurchargeScope.FULL_CARTON}
        and rule.pricing_status
        in {SurchargePricingStatus.MANUAL_QUOTE, SurchargePricingStatus.TIERED}
    ):
        raise ValidationError(
            f"'{rule.name}' is priced per line (tiered or manual quote); it cannot be "
            "charged once on the whole master.",
            field="scope_override",
        )
    row = db.scalar(
        select(SurchargeRulePolicy).where(
            SurchargeRulePolicy.section == section, SurchargeRulePolicy.stt == stt
        )
    )
    if row is None:
        row = SurchargeRulePolicy(section=section, stt=stt, updated_at=utcnow())
        db.add(row)
    row.markup_kind, row.markup_value, row.scope_override = kind, value, scope
    row.note = (payload.get("note") or None) and str(payload["note"])[:400]
    row.updated_at = utcnow()
    row.updated_by_user_id = actor.id if actor else None
    db.flush()
    audit_service.record_audit(
        db,
        action="pricing.policy_update",
        entity_type="surcharge_rule_policy",
        entity_id=f"{section}:{stt}",
        summary=f"Set the pricing policy for surcharge {section} row {stt}: {kind} {value}",
        actor=actor,
        detail={"markup_kind": kind, "markup_value": str(value), "scope_override": scope},
    )
    return row


#: The owner's default markup on surcharges (2026-10-20): 2 % unless an administrator
#: changes it; a per-rule policy overrides it.
DEFAULT_MARKUP_KIND = "percent"
DEFAULT_MARKUP_VALUE = Decimal("2.00")
#: A ceiling against a typo (200 for 2.00); CAD for a fixed markup, percent otherwise.
MAX_DEFAULT_MARKUP = Decimal("100.00")


def get_markup_default(db: Session) -> MarkupDefault:
    """The saved default, or the owner's 2 % as an unsaved row (reading never writes)."""
    # Always row 1, so two first saves at once collide on the key instead of making two rows.
    row = db.get(MarkupDefault, 1)
    if row is None:
        row = MarkupDefault(
            id=1,
            markup_kind=DEFAULT_MARKUP_KIND,
            markup_value=DEFAULT_MARKUP_VALUE,
            updated_at=utcnow(),
        )
    return row


def update_markup_default(
    db: Session, kind: str | None, value: Any, *, actor: User | None
) -> MarkupDefault:
    row = get_markup_default(db)
    if row not in db:
        db.add(row)
    if kind is not None:
        if kind not in MARKUP_KINDS:
            raise ValidationError(
                f"Markup must be one of {', '.join(MARKUP_KINDS)}.", field="default_markup_kind"
            )
        row.markup_kind = kind
    if value is not None:
        number = Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        if number < 0:
            raise ValidationError("A markup cannot be negative.", field="default_markup_value")
        if number > MAX_DEFAULT_MARKUP:
            raise ValidationError(
                f"A default markup above {MAX_DEFAULT_MARKUP} is refused.",
                field="default_markup_value",
            )
        row.markup_value = number
    if row.markup_kind == "pass_through":
        row.markup_value = Decimal(0)
    row.updated_at = utcnow()
    row.updated_by_user_id = actor.id if actor else None
    db.flush()
    audit_service.record_audit(
        db,
        action="pricing.markup_default_update",
        entity_type="pricing_settings",
        entity_id=row.id,
        summary=f"Default surcharge markup set to {row.markup_kind} {row.markup_value}",
        actor=actor,
        detail={"markup_kind": row.markup_kind, "markup_value": str(row.markup_value)},
    )
    return row


def default_rate(settings: PricingSettings, service: str) -> Decimal | None:
    if service == SolarisService.AIR_STANDARD:
        return settings.air_standard_default_rate_cad
    if service == SolarisService.AIR_EXPRESS:
        return settings.air_express_default_rate_cad
    return None


# --- Fee lines ---------------------------------------------------------------------------------


def active_fee_lines(db: Session, shipment_id: int) -> list[ShipmentFeeLine]:
    return list(
        db.scalars(
            select(ShipmentFeeLine)
            .where(ShipmentFeeLine.shipment_id == shipment_id, ShipmentFeeLine.removed_at.is_(None))
            .order_by(ShipmentFeeLine.id)
        )
    )


def _decimal(value: Any, field: str, *, positive: bool = True) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        number = Decimal(str(value))
    except Exception as error:  # noqa: BLE001
        raise ValidationError(f"{field} must be a number.", field=field) from error
    if positive and number <= 0:
        raise ValidationError(f"{field} must be greater than zero.", field=field)
    return number


#: The largest VND amount a fee line stores (Numeric(14, 2)).
MAX_VND_AMOUNT = Decimal("999999999999")


def vnd_amount(value: Any, field: str = "manual_unit_price_vnd") -> Decimal | None:
    """A VND amount typed by staff: finite, rounded to the cent **before** it must be more
    than zero (so 0.001 is refused, not stored as 0.00), at most what the column holds.
    Blank is None. Every refusal is a 422 on ``field``."""
    if value is None or value == "":
        return None
    try:
        number = Decimal(str(value).strip())
    except (InvalidOperation, ValueError) as error:
        raise ValidationError("Enter the amount as a number.", field=field) from error
    if not number.is_finite():
        raise ValidationError("Enter the amount as a number.", field=field)
    if abs(number) > MAX_VND_AMOUNT:
        raise ValidationError(f"An amount above {MAX_VND_AMOUNT:,} VND is refused.", field=field)
    rounded = number.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if rounded <= 0:
        raise ValidationError("The amount must be more than zero.", field=field)
    return rounded


#: The largest customer price (CAD) a line stores (``fee_line_manual_prices.customer_price_cad``
#: is Numeric(12, 2)).
MAX_CAD_PRICE = Decimal("9999999999.99")


def cad_price(value: Any, field: str = "customer_price_cad") -> Decimal | None:
    """A customer price in CAD typed by staff (DEC-0228): the same rules as ``vnd_amount``
    (finite, rounded to the cent before it must be more than zero, at most what the column
    holds). Blank is None. Every refusal is a 422 on ``field``."""
    if value is None or value == "":
        return None
    try:
        number = Decimal(str(value).strip())
    except (InvalidOperation, ValueError) as error:
        raise ValidationError("Enter the price as a number.", field=field) from error
    if not number.is_finite():
        raise ValidationError("Enter the price as a number.", field=field)
    if abs(number) > MAX_CAD_PRICE:
        raise ValidationError(f"A price above {MAX_CAD_PRICE:,} CAD is refused.", field=field)
    rounded = number.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if rounded <= 0:
        raise ValidationError("The price must be more than zero.", field=field)
    return rounded


def manual_prices(db: Session, line_ids: list[int]) -> dict[int, Decimal]:
    """The customer price (CAD) entered on each of these fee lines, by line id (DEC-0228)."""
    if not line_ids:
        return {}
    return {
        row.fee_line_id: row.customer_price_cad
        for row in db.scalars(
            select(FeeLineManualPrice).where(FeeLineManualPrice.fee_line_id.in_(line_ids))
        )
    }


def _store_customer_price(
    db: Session, line: ShipmentFeeLine, price: Decimal, *, actor: User | None
) -> Decimal | None:
    """Write the line's customer price; returns the previous one (None when first entered)."""
    row = db.scalar(select(FeeLineManualPrice).where(FeeLineManualPrice.fee_line_id == line.id))
    old = row.customer_price_cad if row is not None else None
    if row is None:
        row = FeeLineManualPrice(fee_line_id=line.id, customer_price_cad=price, updated_at=utcnow())
        db.add(row)
    row.customer_price_cad = price
    row.updated_at = utcnow()
    row.updated_by_user_id = actor.id if actor else None
    return old


def add_fee_line(
    db: Session, shipment: Shipment, payload: dict[str, Any], *, actor: User | None
) -> ShipmentFeeLine:
    """Attach a surcharge rule to an item. The rule must be an air rule (OD-49: air only),
    exist in the active tariff and apply to Canada; whether it can be priced is the engine's
    question, so an unpriced rule can be attached and will block finalisation. A manual-quote
    rule takes the vendor's quoted price, or the file's minimum until it is known (OD-56).
    Refused on a booked master unless an Admin unlocked it (owner decision 8)."""
    unlock = master_lock_service.require_editable(db, shipment)
    item = db.get(ShipmentItem, payload.get("item_id"))
    if item is None or item.shipment_id != shipment.id or not item.is_active:
        raise NotFoundError("That item does not belong to this shipment.")
    version = tariff_import_service.active_version(db, KANGO_VENDOR_KEY)
    if version is None:
        raise ConflictError("No tariff version is active; import and activate one first.")
    section, stt = str(payload.get("section") or ""), int(payload.get("stt") or 0)
    if section == SEA_VENDOR_SECTION:
        return _add_sea_fee_line(db, shipment, item, stt, payload, unlock=unlock, actor=actor)
    if section not in AIR_SECTIONS:
        raise ValidationError(
            "Only air surcharges can be added; sea is not priced for now (OD-49).",
            field="section",
        )
    rule = db.scalar(
        select(TariffSurchargeRule).where(
            TariffSurchargeRule.version_id == version.id,
            TariffSurchargeRule.section == section,
            TariffSurchargeRule.stt == stt,
        )
    )
    if rule is None:
        raise NotFoundError("That surcharge is not in the active tariff.")
    if not rule.applies_to_canada:
        raise ConflictError(f"'{rule.name}' does not apply to Canada.", field="stt")
    exists = db.scalar(
        select(ShipmentFeeLine).where(
            ShipmentFeeLine.item_id == item.id,
            ShipmentFeeLine.section == section,
            ShipmentFeeLine.stt == stt,
            ShipmentFeeLine.removed_at.is_(None),
        )
    )
    if exists is not None:
        raise ConflictError("That surcharge is already on this item; edit or remove it instead.")
    if payload.get("manual_unit_price_vnd") not in (None, "") and not (
        rule.pricing_status == SurchargePricingStatus.MANUAL_QUOTE
        or (
            rule.pricing_status == SurchargePricingStatus.TIERED
            and above_top_tier(section, stt) == "manual"
        )
    ):
        raise ValidationError(
            f"'{rule.name}' has a fixed price; a vendor quote is not entered for it.",
            field="manual_unit_price_vnd",
        )
    if (
        payload.get("customer_price_cad") not in (None, "")
        and rule.basis != SurchargeBasis.MANUAL_AMOUNT
    ):
        raise ValidationError(
            f"'{rule.name}' is not quoted case by case; a customer price is not entered for it.",
            field="customer_price_cad",
        )
    customer_price = cad_price(payload.get("customer_price_cad"))
    quantity = _decimal(payload.get("quantity", 1), "quantity") or Decimal(1)
    if rule.basis == SurchargeBasis.MANUAL_AMOUNT:
        # Quoted case by case (HCM air row 27, DEC-0225, DEC-0228): staff enter the vendor's
        # cost (VND) and the customer price (CAD); no kilograms, no quantity, no prefilled
        # value. Until both are entered the line blocks finalising.
        quantity = Decimal(1)
        payload = {**payload, "weight_kg": None}
    line = ShipmentFeeLine(
        shipment_id=shipment.id,
        item_id=item.id,
        section=section,
        stt=stt,
        quantity=quantity.quantize(Decimal("0.01")),
        weight_kg=(w := _decimal(payload.get("weight_kg"), "weight_kg"))
        and w.quantize(Decimal("0.001")),
        manual_unit_price_vnd=vnd_amount(payload.get("manual_unit_price_vnd")),
        created_at=utcnow(),
        created_by_user_id=actor.id if actor else None,
    )
    db.add(line)
    db.flush()
    if customer_price is not None:
        _store_customer_price(db, line, customer_price, actor=actor)
        db.flush()
    entered = {
        key: str(value)
        for key, value in (
            ("manual_unit_price_vnd", line.manual_unit_price_vnd),
            ("customer_price_cad", customer_price),
        )
        if value is not None and rule.basis == SurchargeBasis.MANUAL_AMOUNT
    }
    audit_service.record_audit(
        db,
        action="shipment.fee_line_add",
        entity_type="shipment",
        entity_id=shipment.id,
        summary=(
            f"Added surcharge {section} row {stt} to item {item.sequence} on {shipment.public_id}"
        ),
        actor=actor,
        detail={
            "fee_line_id": line.id,
            "item_id": item.id,
            "section": section,
            "stt": stt,
            **entered,
            **master_lock_service.audit_detail(unlock),
        },
    )
    return line


def _add_sea_fee_line(
    db: Session,
    shipment: Shipment,
    item: ShipmentItem,
    stt: int,
    payload: dict[str, Any],
    *,
    unlock: Any,
    actor: User | None,
) -> ShipmentFeeLine:
    """A sea vendor surcharge (v0.6, ``sea_surcharge_rules``): charged on the item's own kg,
    so the weight is required; the per-package minimum is the engine's."""
    rule = pricing_method_service.sea_rule_map(db).get(stt)
    if rule is None:
        raise NotFoundError("That sea surcharge is not active.")
    weight = _decimal(payload.get("weight_kg"), "weight_kg")
    if weight is None or weight <= 0:
        raise ValidationError(
            f"'{rule.name}' is charged per item kilogram; enter the item's weight.",
            field="weight_kg",
        )
    exists = db.scalar(
        select(ShipmentFeeLine).where(
            ShipmentFeeLine.item_id == item.id,
            ShipmentFeeLine.section == SEA_VENDOR_SECTION,
            ShipmentFeeLine.stt == stt,
            ShipmentFeeLine.removed_at.is_(None),
        )
    )
    if exists is not None:
        raise ConflictError("That surcharge is already on this item; edit or remove it instead.")
    line = ShipmentFeeLine(
        shipment_id=shipment.id,
        item_id=item.id,
        section=SEA_VENDOR_SECTION,
        stt=stt,
        quantity=Decimal("1.00"),
        weight_kg=weight.quantize(Decimal("0.001")),
        manual_unit_price_vnd=None,
        created_at=utcnow(),
        created_by_user_id=actor.id if actor else None,
    )
    db.add(line)
    db.flush()
    audit_service.record_audit(
        db,
        action="shipment.fee_line_add",
        entity_type="shipment",
        entity_id=shipment.id,
        summary=f"Added sea surcharge {rule.code} to item {item.sequence} on {shipment.public_id}",
        actor=actor,
        detail={
            "fee_line_id": line.id,
            "item_id": item.id,
            "section": SEA_VENDOR_SECTION,
            "stt": stt,
            "code": rule.code,
            **master_lock_service.audit_detail(unlock),
        },
    )
    return line


def set_fee_line_amount(
    db: Session,
    shipment: Shipment,
    line_id: int,
    amount: Any = None,
    *,
    customer_price_cad: Any = None,
    actor: User | None,
) -> ShipmentFeeLine:
    """Enter the vendor's cost (VND, ``amount``) and/or the customer price (CAD) on a line of
    a rule quoted case by case (HCM air row 27, costume jewellery; DEC-0225, owner 2026-10-23
    DEC-0228). Either or both in one call; at least one is required. Only such lines take
    them; the master lock applies as for adding a line. Each is audited with its old and new
    value (``shipment.fee_line_amount`` for the VND cost, ``shipment.fee_line_customer_price``
    for the CAD price). The customer is billed exactly the CAD price (stand-in: no markup)."""
    unlock = master_lock_service.require_editable(db, shipment)
    line = db.get(ShipmentFeeLine, line_id)
    if line is None or line.shipment_id != shipment.id or line.removed_at is not None:
        raise NotFoundError("That surcharge line does not belong to this shipment.")
    version = tariff_import_service.active_version(db, KANGO_VENDOR_KEY)
    rule = (
        db.scalar(
            select(TariffSurchargeRule).where(
                TariffSurchargeRule.version_id == version.id,
                TariffSurchargeRule.section == line.section,
                TariffSurchargeRule.stt == line.stt,
            )
        )
        if version is not None
        else None
    )
    if rule is None or rule.basis != SurchargeBasis.MANUAL_AMOUNT:
        raise ValidationError(
            "Only a surcharge quoted case by case takes an amount for the line.",
            field="manual_unit_price_vnd" if amount not in (None, "") else "customer_price_cad",
        )
    number = vnd_amount(amount)
    price = cad_price(customer_price_cad)
    if number is None and price is None:
        raise ValidationError(
            "Enter the vendor's cost (VND) or the customer price (CAD) for this line.",
            field="manual_unit_price_vnd",
        )
    if number is not None:
        old = line.manual_unit_price_vnd
        line.manual_unit_price_vnd = number
        # An amount entered for the line has no kilograms; this also clears the review flag of
        # a line priced per kg under an older reading of the rule (S-8).
        line.weight_kg = None
        db.flush()
        audit_service.record_audit(
            db,
            action="shipment.fee_line_amount",
            entity_type="shipment",
            entity_id=shipment.id,
            summary=(
                f"Entered the quoted amount {line.manual_unit_price_vnd} VND on surcharge "
                f"{line.section} row {line.stt} of {shipment.public_id}"
            ),
            actor=actor,
            detail={
                "fee_line_id": line.id,
                "from": str(old) if old is not None else None,
                "to": str(line.manual_unit_price_vnd),
                **master_lock_service.audit_detail(unlock),
            },
        )
    if price is not None:
        old_price = _store_customer_price(db, line, price, actor=actor)
        db.flush()
        audit_service.record_audit(
            db,
            action="shipment.fee_line_customer_price",
            entity_type="shipment",
            entity_id=shipment.id,
            summary=(
                f"Entered the customer price CAD {price} on surcharge "
                f"{line.section} row {line.stt} of {shipment.public_id}"
            ),
            actor=actor,
            detail={
                "fee_line_id": line.id,
                "from": str(old_price) if old_price is not None else None,
                "to": str(price),
                **master_lock_service.audit_detail(unlock),
            },
        )
    return line


def remove_fee_line(
    db: Session, shipment: Shipment, line_id: int, *, actor: User | None
) -> ShipmentFeeLine:
    unlock = master_lock_service.require_editable(db, shipment)
    line = db.get(ShipmentFeeLine, line_id)
    if line is None or line.shipment_id != shipment.id:
        raise NotFoundError("That surcharge line does not belong to this shipment.")
    if line.removed_at is None:
        line.removed_at = utcnow()
        line.removed_by_user_id = actor.id if actor else None
        db.flush()
        audit_service.record_audit(
            db,
            action="shipment.fee_line_remove",
            entity_type="shipment",
            entity_id=shipment.id,
            summary=f"Removed surcharge {line.section} row {line.stt} from {shipment.public_id}",
            actor=actor,
            detail={"fee_line_id": line.id, **master_lock_service.audit_detail(unlock)},
        )
    return line


# --- Master cartons (OD-62) ---------------------------------------------------------------------


def list_cartons(db: Session, consolidation_id: int) -> list[ConsolidationCarton]:
    return list(
        db.scalars(
            select(ConsolidationCarton)
            .where(ConsolidationCarton.consolidation_id == consolidation_id)
            .order_by(ConsolidationCarton.sequence)
        )
    )


def replace_cartons(
    db: Session, consolidation: Consolidation, cartons: list[dict[str, Any]], *, actor: User | None
) -> list[ConsolidationCarton]:
    """Replace the master's carton list. Each carton needs a weight; dimensions are optional
    and, when all three are given, the volumetric weight counts toward the piece fee."""
    if consolidation.state not in {ConsolidationState.OPEN, ConsolidationState.BOOKED}:
        raise ConflictError(
            f"This consolidation is {consolidation.state}; its cartons no longer change."
        )
    if len(cartons) > 500:
        raise ValidationError("At most 500 cartons per master.", field="cartons")
    rows: list[ConsolidationCarton] = []
    now = utcnow()
    for index, carton in enumerate(cartons, start=1):
        weight = _decimal(carton.get("weight_kg"), f"cartons[{index}].weight_kg")
        if weight is None:
            raise ValidationError(f"Carton {index} needs a weight.", field="cartons")
        rows.append(
            ConsolidationCarton(
                consolidation_id=consolidation.id,
                sequence=index,
                weight_kg=weight.quantize(Decimal("0.001")),
                length_cm=_decimal(carton.get("length_cm"), f"cartons[{index}].length_cm"),
                width_cm=_decimal(carton.get("width_cm"), f"cartons[{index}].width_cm"),
                height_cm=_decimal(carton.get("height_cm"), f"cartons[{index}].height_cm"),
                created_at=now,
                created_by_user_id=actor.id if actor else None,
            )
        )
    for old in list_cartons(db, consolidation.id):
        db.delete(old)
    db.flush()
    db.add_all(rows)
    db.flush()
    # Method v0.5: "packed as one box for Kango", when the caller sends it (keyed by sequence,
    # so the flag survives the next replacement when the caller omits it). v0.7 (Louis,
    # DEC-0262): only on a master with exactly one package; a master that now has several
    # packages loses any flag it had.
    if len(cartons) > 1:
        if any(c.get("packed_as_one_box") for c in cartons):
            raise ValidationError(
                "'Packed as one box for Kango' is allowed only on a master with one package.",
                field="cartons",
            )
        for sequence, packed in pricing_method_service.package_flags(db, consolidation.id).items():
            if packed:
                pricing_method_service.set_package_flag(
                    db, consolidation.id, sequence, False, actor=actor
                )
    for index, carton in enumerate(cartons, start=1):
        if "packed_as_one_box" in carton and carton["packed_as_one_box"] is not None:
            pricing_method_service.set_package_flag(
                db, consolidation.id, index, bool(carton["packed_as_one_box"]), actor=actor
            )
    audit_service.record_audit(
        db,
        action="consolidation.cartons_replace",
        entity_type="consolidation",
        entity_id=consolidation.id,
        summary=f"Recorded {len(rows)} cartons on consolidation {consolidation.id}",
        actor=actor,
        detail={"carton_count": len(rows)},
    )
    return rows


# --- Loading the engine's inputs ---------------------------------------------------------------


def _rule_view(rule: TariffSurchargeRule) -> pe.RuleView:
    return pe.RuleView(
        section=rule.section,
        stt=rule.stt,
        name=rule.name,
        pricing_status=SurchargePricingStatus(rule.pricing_status),
        basis=SurchargeBasis(rule.basis),
        scope=SurchargeScope(rule.scope),
        unit_price_vnd=rule.unit_price_vnd,
        per_unit_price_vnd=rule.per_unit_price_vnd,
        tiers=tuple(pe.Tier(t.weight_from_kg, t.weight_to_kg, t.price_vnd) for t in rule.tiers),
        min_charge_kg=rule.min_charge_kg,
        applies_to_canada=rule.applies_to_canada,
        above_top_tier=above_top_tier(rule.section, rule.stt),
    )


def above_top_tier(section: str, stt: int) -> str:
    try:
        semantics = kango_semantics.CURATED_RULES.get((SurchargeSection(section), stt))
    except ValueError:
        return "manual"
    return semantics.above_top_tier if semantics else "manual"


def _product_view(db: Session, product: TariffProduct) -> pe.ProductView:
    brackets = db.scalars(
        select(TariffRateBracket).where(TariffRateBracket.product_id == product.id)
    )
    return pe.ProductView(
        code=product.code,
        last_mile=TariffLastMile(product.last_mile),
        dim_divisor=product.dim_divisor,
        per_kg_from_kg=product.per_kg_from_kg,
        piece_min_weight_kg=product.piece_min_weight_kg,
        piece_min_fee_vnd=product.piece_min_fee_vnd,
        piece_min_applies_above_kg=product.piece_min_applies_above_kg,
        customs_surcharges_waived=product.customs_surcharges_waived,
        brackets=tuple(
            pe.Bracket(b.kind, b.zone, b.weight_from_kg, b.weight_to_kg, b.price_vnd, b.label)
            for b in brackets
        ),
    )


def _delivery_point(db: Session, version: TariffVersion | None, postal: str) -> pe.DeliveryPoint:
    if version is None:
        return pe.DeliveryPoint(postal, None, None, None, None, None, None)
    zone = db.scalar(
        select(TariffZoneFsa).where(
            TariffZoneFsa.version_id == version.id,
            TariffZoneFsa.fsa == postal.replace(" ", "").upper()[:3],
        )
    )
    beyond = db.scalar(
        select(TariffBeyondPostalCode).where(
            TariffBeyondPostalCode.version_id == version.id,
            TariffBeyondPostalCode.postal_code == postal,
        )
    )
    rate = (
        db.scalar(
            select(TariffBeyondRate).where(
                TariffBeyondRate.version_id == version.id,
                TariffBeyondRate.beyond_code == beyond.beyond_code,
            )
        )
        if beyond
        else None
    )
    return pe.DeliveryPoint(
        postal_code=postal,
        ground_zone=zone.ground_zone if zone else None,
        express_zone=zone.express_zone if zone else None,
        beyond_code=beyond.beyond_code if beyond else None,
        beyond_status=BeyondRateStatus(rate.status)
        if rate
        else (BeyondRateStatus.NO_RATE if beyond else None),
        beyond_base_cad=rate.base_cad if rate else None,
        beyond_per_lb_cad=rate.per_lb_cad if rate else None,
    )


def _box_of(
    db: Session, packages: list, line: ShipmentFeeLine
) -> tuple[int | None, Decimal | None]:
    """Method v0.5: the customer's small box holding the line's item and its raw chargeable
    weight (the greater of actual and volumetric). A shipment with one box: that box."""
    package = None
    if line.item_id is not None:
        item = db.get(ShipmentItem, line.item_id)
        if item is not None and item.package_id is not None:
            package = next((p for p in packages if p.id == item.package_id), None)
    if package is None and len(packages) == 1:
        package = packages[0]
    if package is None or package.weight_kg is None:
        return None, None
    weight = Decimal(str(package.weight_kg))
    volumetric = pe.cw.volumetric_weight(
        Decimal(str(package.length_cm)) if package.length_cm is not None else None,
        Decimal(str(package.width_cm)) if package.width_cm is not None else None,
        Decimal(str(package.height_cm)) if package.height_cm is not None else None,
        6000,
    )
    return package.id, max(weight, volumetric) if volumetric is not None else weight


def _member_input(db: Session, shipment: Shipment) -> pe.MemberInput:
    packages = package_service.active_packages(db, shipment.id)
    lines = active_fee_lines(db, shipment.id)
    prices = manual_prices(db, [line.id for line in lines])
    boxes = {line.id: _box_of(db, packages, line) for line in lines}
    # DEC-0275: the item's own weight, for a line that has none (confirmed method only).
    item_ids = {line.item_id for line in lines if line.item_id is not None}
    item_kg = (
        {
            item.id: item.weight_kg
            for item in db.scalars(select(ShipmentItem).where(ShipmentItem.id.in_(item_ids)))
        }
        if item_ids
        else {}
    )
    return pe.MemberInput(
        shipment_id=shipment.id,
        public_id=shipment.public_id or str(shipment.id),
        packages=tuple(
            pe.PackageInput(
                Decimal(str(p.weight_kg)) if p.weight_kg is not None else None,
                Decimal(str(p.length_cm)) if p.length_cm is not None else None,
                Decimal(str(p.width_cm)) if p.width_cm is not None else None,
                Decimal(str(p.height_cm)) if p.height_cm is not None else None,
            )
            for p in packages
        ),
        fee_lines=tuple(
            pe.FeeLineInput(
                line.id,
                line.item_id,
                line.section,
                line.stt,
                line.quantity,
                line.weight_kg,
                line.manual_unit_price_vnd,
                prices.get(line.id),
                box_ref=boxes[line.id][0],
                box_kg=boxes[line.id][1],
                item_kg=item_kg.get(line.item_id),
            )
            for line in lines
        ),
    )


def _default_policy(db: Session) -> pe.RulePolicy:
    row = get_markup_default(db)
    return pe.RulePolicy(row.markup_kind, row.markup_value, None)


def estimate_for(
    db: Session, consolidation: Consolidation, *, now: datetime | None = None
) -> tuple[pe.Estimate, TariffVersion | None]:
    settings = get_settings(db)
    version = tariff_import_service.active_version(db, KANGO_VENDOR_KEY)
    product_view: pe.ProductView | None = None
    refusal: str | None = None
    # A booked master is priced at the tariff it was booked under, not a newer one.
    pinned = (
        db.get(TariffProduct, consolidation.tariff_product_id)
        if consolidation.tariff_product_id
        else None
    )
    if pinned is not None:
        version = db.get(TariffVersion, pinned.version_id)
        product_view = _product_view(db, pinned)
    else:
        try:
            version, product = consolidation_service.resolve_vendor_product(
                db, consolidation.solaris_service, consolidation.origin
            )
            product_view = _product_view(db, product)
        except ConflictError as error:
            refusal = str(error)
    rules: dict[tuple[str, int], pe.RuleView] = {}
    if version is not None:
        for rule in db.scalars(
            select(TariffSurchargeRule).where(TariffSurchargeRule.version_id == version.id)
        ):
            rules[(rule.section, rule.stt)] = _rule_view(rule)
    policies = {
        (p.section, p.stt): pe.RulePolicy(
            p.markup_kind,
            p.markup_value,
            SurchargeScope(p.scope_override) if p.scope_override else None,
        )
        for p in list_policies(db)
    }
    snapshot = fx_service.latest_snapshot(db)
    fx = (
        pe.FxView(
            snapshot.id,
            snapshot.cash_buy_vnd,
            snapshot.sell_vnd,
            fx_service.freshness(snapshot, now=now).value,
        )
        if snapshot
        else None
    )
    if pricing_method_service.uses_confirmed_method(db):
        return _estimate_method(
            db,
            consolidation,
            settings=settings,
            version=version,
            product_view=product_view,
            refusal=refusal,
            rules=rules,
            policies=policies,
            fx=fx,
        ), version
    est = pe.estimate(
        product=product_view,
        product_refusal=refusal,
        delivery=_delivery_point(db, version, settings.vendor_delivery_postal_code),
        master=pe.MasterInput(
            consolidation.actual_weight_kg,
            consolidation.length_cm,
            consolidation.width_cm,
            consolidation.height_cm,
            consolidation.carton_count,
            consolidation.chargeable_weight_kg,
            tuple(
                pe.PackageInput(c.weight_kg, c.length_cm, c.width_cm, c.height_cm)
                for c in list_cartons(db, consolidation.id)
            ),
        ),
        members=[
            _member_input(db, s)
            for s in consolidation_service.member_shipments(db, consolidation.id)
        ],
        rules=rules,
        rule_section=ORIGIN_SECTION.get(consolidation.origin, ""),
        policies=policies,
        fx=fx,
        settings=pe.Settings(
            Fraction(settings.trigger_share_numerator, settings.trigger_share_denominator),
            settings.defaults_owner_confirmed,
            _default_policy(db),
        ),
    )
    return est, version


#: Method v0.5: the vendor product a Sea master is priced through (rate file
#: ``HCM-SEA-CAD`` / ``HN-SEA-CAD``), and its surcharge section (Kango ocean list).
SEA_PRODUCT_CODE = "KSN-SEA-CAD-PURO"
SEA_SECTION = "sea_ca_au_uk_eu"


def _master_input(db: Session, consolidation: Consolidation) -> pe.MasterInput:
    flags = pricing_method_service.package_flags(db, consolidation.id)
    cartons = list_cartons(db, consolidation.id)
    rows = tuple(
        pe.PackageInput(
            c.weight_kg,
            c.length_cm,
            c.width_cm,
            c.height_cm,
            packed_as_one_box=flags.get(c.sequence, False),
        )
        for c in cartons
    )
    if not rows and flags.get(1):
        # A one-package master with no carton rows: the master itself is the package.
        rows = (
            pe.PackageInput(
                consolidation.actual_weight_kg,
                consolidation.length_cm,
                consolidation.width_cm,
                consolidation.height_cm,
                packed_as_one_box=True,
            ),
        )
    return pe.MasterInput(
        consolidation.actual_weight_kg,
        consolidation.length_cm,
        consolidation.width_cm,
        consolidation.height_cm,
        consolidation.carton_count,
        consolidation.chargeable_weight_kg,
        rows,
    )


def _estimate_method(
    db: Session,
    consolidation: Consolidation,
    *,
    settings: PricingSettings,
    version: TariffVersion | None,
    product_view: pe.ProductView | None,
    refusal: str | None,
    rules: dict[tuple[str, int], pe.RuleView],
    policies: dict[tuple[str, int], pe.RulePolicy],
    fx: pe.FxView | None,
) -> pe.Estimate:
    """Method v0.5 (``app/pricing/cost_method.py``) for one master."""
    service = consolidation.solaris_service
    section = ORIGIN_SECTION.get(consolidation.origin, "")
    if service == SolarisService.SEA:
        # v0.6 (Louis, 2026-11-03): sea is the sea vendor's rate, not the Kango sea sheet;
        # the Kango ocean surcharges are inactive (the engine refuses them on a sea master).
        section = SEA_SECTION
        product_view, refusal = None, None
    dated = consolidation.booked_at or consolidation.created_at
    classes = pricing_method_service.allocation_class_map(db)
    rules = {key: replace(rule, allocation_class=classes.get(key)) for key, rule in rules.items()}
    return mv.estimate_method(
        service=service,
        product=product_view,
        product_refusal=refusal,
        delivery=_delivery_point(db, version, settings.vendor_delivery_postal_code),
        master=_master_input(db, consolidation),
        members=[
            _member_input(db, s)
            for s in consolidation_service.member_shipments(db, consolidation.id)
        ],
        rules=rules,
        rule_section=section,
        policies=policies,
        fx=fx,
        settings=pe.Settings(
            Fraction(settings.trigger_share_numerator, settings.trigger_share_denominator),
            settings.defaults_owner_confirmed,
            None,
        ),
        method=pricing_method_service.engine_settings(
            db, settings, on=dated.date() if dated is not None else None
        ),
        manual=pricing_method_service.manual_view(db, consolidation.id),
        ups_bands=pricing_method_service.ups_bands(db),
        sea_rules=pricing_method_service.sea_rule_map(db),
        member_packages=pricing_method_service.package_members(db, consolidation.id),
    )


def member_default_rate(
    est: pe.Estimate, settings: PricingSettings, service: str, shipment_id: int
) -> Decimal | None:
    """The default selling rate for one customer: v0.5 by its own weight, else the service's."""
    if est.method_detail is not None:
        row = est.method_detail["members"].get(shipment_id)
        rate = row.get("rate_cad_kg") if row else None
        return Decimal(str(rate)).quantize(Decimal("0.01")) if rate is not None else None
    return default_rate(settings, service)


def _jsonable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_jsonable(v) for v in value]
    if hasattr(value, "value") and not isinstance(value, str | int | float | bool):
        return value.value
    return value


def snapshot_method_detail(snapshot_estimate: dict) -> dict | None:
    """The method detail of a stored estimate snapshot: ``method_detail`` since DEC-0267,
    ``v05`` in snapshots finalised before (frozen, never rewritten)."""
    return snapshot_estimate.get("method_detail") or snapshot_estimate.get("v05")


def estimate_dict(est: pe.Estimate) -> dict[str, Any]:
    return _jsonable(
        {
            "product_code": est.product_code,
            "zone": est.zone,
            "delivery_postal_code": est.delivery_postal_code,
            "master_chargeable_kg": est.master_chargeable_kg,
            "base_freight_vnd": est.base_freight_vnd,
            "base_freight_cad": est.base_freight_cad,
            "total_cost_vnd": est.total_cost_vnd,
            "piece_fee_vnd": est.piece_fee_vnd,
            "fx_snapshot_id": est.fx_snapshot_id,
            "fees": [asdict(f) for f in est.fees],
            "members": [asdict(m) for m in est.members.values()],
            "blocking": [asdict(i) for i in est.blocking],
            "provisional": [asdict(i) for i in est.provisional],
            # The confirmed method only, so an RC-UAT-25 snapshot keeps exactly its keys.
            **(
                {"method": est.method, "method_detail": est.method_detail}
                if est.method_detail is not None
                else {}
            ),
        }
    )


# --- Quotes ------------------------------------------------------------------------------------


def _require_consolidation(db: Session, shipment: Shipment) -> Consolidation:
    membership = consolidation_service.active_membership_for_shipment(db, shipment.id)
    if membership is None:
        raise ConflictError("Add the shipment to a consolidation before quoting it.")
    return consolidation_service.get_consolidation(db, membership.consolidation_id)


def _inputs_fingerprint(
    est: pe.Estimate,
    shipment_id: int,
    consolidation: Consolidation,
    lines: list[ShipmentFeeLine],
    *,
    rate_default: Decimal | None,
    tariff_version_id: int | None,
) -> str:
    """Everything that moves this shipment's customer price except the exchange rate
    (re-applied at finalisation, DEC-0189): a change revokes the rate confirmation."""
    member = est.members.get(shipment_id)
    shared = sorted(
        [f.key, sorted(f.triggers)] for f in est.fees if f.master_wide and shipment_id in f.triggers
    )
    triggered = sorted(
        [
            f.key,
            str(f.vendor_fee_vnd),
            f.markup_kind,
            str(f.markup_value),
            str(f.scope),
            sorted(
                [sid, str(est.members[sid].billable_kg) if sid in est.members else None]
                for sid in f.triggers
            ),
            # Only when entered, so a draft without one keeps its fingerprint (DEC-0228).
            *([str(f.customer_price_cad)] if f.customer_price_cad is not None else []),
        ]
        for f in est.fees
        if shipment_id in f.triggers
    )
    payload = {
        "consolidation": consolidation.id,
        "service": consolidation.solaris_service,
        "billable_kg": str(member.billable_kg) if member else None,
        "fee_lines": [
            [
                ln.id,
                ln.section,
                ln.stt,
                str(ln.quantity),
                str(ln.weight_kg),
                str(ln.manual_unit_price_vnd),
            ]
            for ln in lines
        ],
        "shared_triggers": shared,
        "triggered_fees": triggered,
        "master_kg": str(est.master_chargeable_kg),
        "default_rate": str(rate_default),
        "tariff_version": tariff_version_id,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def list_versions(db: Session, shipment_id: int) -> list[QuoteVersion]:
    return list(
        db.scalars(
            select(QuoteVersion)
            .where(QuoteVersion.shipment_id == shipment_id)
            .order_by(QuoteVersion.version)
        )
    )


def open_draft(db: Session, shipment_id: int) -> QuoteVersion | None:
    return db.scalar(
        select(QuoteVersion).where(
            QuoteVersion.shipment_id == shipment_id, QuoteVersion.status == "draft"
        )
    )


def reprice(
    db: Session, shipment: Shipment, *, actor: User | None, now: datetime | None = None
) -> tuple[QuoteVersion, pe.Estimate]:
    """Create the open draft, or re-price it against the current state."""
    consolidation = _require_consolidation(db, shipment)
    est, version = estimate_for(db, consolidation, now=now)
    settings = get_settings(db)
    lines = active_fee_lines(db, shipment.id)
    rate_default = member_default_rate(est, settings, consolidation.solaris_service, shipment.id)
    fingerprint = _inputs_fingerprint(
        est,
        shipment.id,
        consolidation,
        lines,
        rate_default=rate_default,
        tariff_version_id=version.id if version else None,
    )
    draft = open_draft(db, shipment.id)
    created = draft is None
    if draft is None:
        number = len(list_versions(db, shipment.id)) + 1
        draft = QuoteVersion(
            shipment_id=shipment.id,
            version=number,
            status="draft",
            solaris_service=consolidation.solaris_service,
            selling_rate_cad=rate_default,
            created_by_user_id=actor.id if actor else None,
            inputs_sha256=fingerprint,
        )
        db.add(draft)
    draft.consolidation_id = consolidation.id
    draft.tariff_version_id = version.id if version else None
    draft.fx_snapshot_id = est.fx_snapshot_id
    draft.solaris_service = consolidation.solaris_service
    draft.default_rate_cad = rate_default
    draft.inputs_sha256 = fingerprint
    revoked = (
        draft.confirmed_inputs_sha256 is not None and draft.confirmed_inputs_sha256 != fingerprint
    )
    if revoked:
        # SC-07: changing an input revokes the confirmation.
        draft.rate_confirmed_at = None
        draft.rate_confirmed_by_user_id = None
        draft.confirmed_inputs_sha256 = None
    # An unconfirmed draft with no override follows the current default (OD-45).
    if draft.selling_rate_cad is None or (
        draft.rate_confirmed_at is None and draft.override_reason is None
    ):
        draft.selling_rate_cad = rate_default
    _write_figures(db, draft, est, shipment.id)
    db.flush()
    if created or revoked:
        audit_service.record_audit(
            db,
            action="quote.draft_open" if created else "quote.confirmation_revoked",
            entity_type="shipment",
            entity_id=shipment.id,
            summary=(
                f"Opened quote version {draft.version} for {shipment.public_id}"
                if created
                else f"A changed input revoked the rate confirmation on {shipment.public_id}"
            ),
            actor=actor,
            detail={"quote_version_id": draft.id, "version": draft.version},
        )
    return draft, est


def _write_figures(db: Session, draft: QuoteVersion, est: pe.Estimate, shipment_id: int) -> None:
    figures = pe.quote_figures(est, shipment_id, draft.selling_rate_cad)
    draft.billable_weight_kg = figures.billable_kg
    draft.base_revenue_cad = figures.base_revenue_cad
    draft.surcharge_revenue_cad = figures.surcharge_revenue_cad
    draft.total_revenue_cad = figures.total_revenue_cad
    draft.allocated_cost_cad = figures.allocated_cost_cad
    draft.gross_profit_cad = figures.gross_profit_cad
    draft.blocking_json = json.dumps([asdict(i) for i in est.blocking], ensure_ascii=False)
    draft.provisional_json = json.dumps([asdict(i) for i in est.provisional], ensure_ascii=False)
    draft.snapshot_json = json.dumps(
        {"estimate": estimate_dict(est), "quote": _jsonable(asdict(figures))}, ensure_ascii=False
    )
    member = est.members[shipment_id]
    # Delete the previous lines and flush before inserting the new ones: in one flush the unit
    # of work inserts before it deletes, and (version_id, sequence) is unique.
    if draft.id is not None:
        for old_line in list(draft.lines):
            draft.lines.remove(old_line)
        db.flush()
    sequence = 1
    draft.lines.append(
        QuoteLine(
            sequence=sequence,
            kind="base_freight",
            description=f"{_service_label(draft.solaris_service)} freight",
            quantity=member.billable_kg,
            unit="kg",
            revenue_cad=figures.base_revenue_cad or Decimal(0),
            cost_vnd=member.base_cost_vnd,
            cost_cad=member.base_cost_cad,
            is_trigger=False,
        )
    )
    for fee in est.fees:
        cost_vnd = fee.cost_alloc_vnd.get(shipment_id)
        revenue = fee.revenue_alloc_cad.get(shipment_id)
        if cost_vnd is None and revenue is None and shipment_id not in fee.triggers:
            continue
        sequence += 1
        draft.lines.append(
            QuoteLine(
                sequence=sequence,
                kind="surcharge",
                description=fee.name[:300],
                section=fee.section,
                stt=fee.stt,
                quantity=fee.quantity or None,
                unit=None,
                revenue_cad=revenue or Decimal(0),
                cost_vnd=cost_vnd,
                cost_cad=fee.cost_alloc_cad.get(shipment_id),
                is_trigger=shipment_id in fee.triggers,
                markup_kind=fee.markup_kind,
                markup_value=fee.markup_value,
            )
        )


def _service_label(service: str) -> str:
    from app.core.enums import SOLARIS_SERVICE_LABELS  # noqa: PLC0415

    return SOLARIS_SERVICE_LABELS.get(service, service)


def confirm_rate(
    db: Session,
    shipment: Shipment,
    *,
    rate: Decimal | None,
    reason: str | None,
    actor: User | None,
    now: datetime | None = None,
) -> QuoteVersion:
    """Confirm the selling rate (OD-45: Operations confirms; any other rate needs a reason)."""
    draft, est = reprice(db, shipment, actor=actor, now=now)
    chosen = rate if rate is not None else draft.default_rate_cad
    if chosen is None:
        raise ValidationError(
            "This service has no default rate; enter the selling rate per kilogram.", field="rate"
        )
    chosen = Decimal(str(chosen)).quantize(Decimal("0.01"))
    if chosen <= 0:
        raise ValidationError("The selling rate must be positive.", field="rate")
    reason = (reason or "").strip() or None
    is_override = draft.default_rate_cad is None or chosen != draft.default_rate_cad
    if is_override and not reason:
        raise ValidationError("A rate other than the default needs a reason.", field="reason")
    draft.selling_rate_cad = chosen
    draft.override_reason = reason[:400] if is_override and reason else None
    draft.rate_confirmed_at = now or utcnow()
    draft.rate_confirmed_by_user_id = actor.id if actor else None
    draft.confirmed_inputs_sha256 = draft.inputs_sha256
    _write_figures(db, draft, est, shipment.id)
    db.flush()
    audit_service.record_audit(
        db,
        action="quote.rate_confirm",
        entity_type="shipment",
        entity_id=shipment.id,
        summary=(
            f"Confirmed the selling rate CAD {chosen}/kg on {shipment.public_id} quote "
            f"v{draft.version}" + (" (override)" if is_override else "")
        ),
        actor=actor,
        detail={
            "rate": str(chosen),
            "default": str(draft.default_rate_cad),
            "override_reason": draft.override_reason,
        },
    )
    return draft


def finalize(
    db: Session,
    shipment: Shipment,
    *,
    negative_margin_reason: str | None,
    actor: User | None,
    now: datetime | None = None,
) -> QuoteVersion:
    draft, est = reprice(db, shipment, actor=actor, now=now)
    problems: list[dict[str, Any]] = [asdict(i) for i in est.blocking]
    if draft.rate_confirmed_at is None:
        problems.append(
            {"code": "rate_not_confirmed", "message": "Confirm the selling rate before finalising."}
        )
    figures = pe.quote_figures(est, shipment.id, draft.selling_rate_cad)
    reason = (negative_margin_reason or "").strip() or None
    if figures.negative_margin_fees and not reason:
        problems.append(
            {
                "code": "negative_margin",
                "message": "These surcharges bill below their cost; give a reason to finalise: "
                + ", ".join(figures.negative_margin_fees),
            }
        )
    if problems:
        raise ConflictError(
            "This quote cannot be finalised yet.", detail={"problems": _jsonable(problems)}
        )
    now = now or utcnow()
    for previous in db.scalars(
        select(QuoteVersion).where(
            QuoteVersion.shipment_id == shipment.id, QuoteVersion.status == "finalized"
        )
    ):
        previous.status = "superseded"
        previous.superseded_at = now
    # Phase 13G: an unanswered offer is withdrawn; an accepted one is flagged for staff (the
    # customer accepted an earlier price). Acceptance re-checks the version too.
    quote_offer_service.on_version_finalized(db, shipment.id, draft.version, actor=actor, now=now)
    draft.negative_margin_reason = reason[:400] if figures.negative_margin_fees and reason else None
    draft.status = "finalized"
    draft.finalized_at = now
    draft.finalized_by_user_id = actor.id if actor else None
    db.flush()
    audit_service.record_audit(
        db,
        action="quote.finalize",
        entity_type="shipment",
        entity_id=shipment.id,
        summary=(
            f"Finalised quote v{draft.version} for {shipment.public_id}: "
            f"CAD {draft.total_revenue_cad}"
        ),
        actor=actor,
        detail={"version": draft.version, "total_revenue_cad": str(draft.total_revenue_cad)},
    )
    # Owner decision 8: a master unlocked for edits locks again once a member is re-quoted.
    master_lock_service.on_quote_finalized(
        db, draft.consolidation_id, shipment=shipment, version=draft.version, actor=actor, now=now
    )
    return draft
