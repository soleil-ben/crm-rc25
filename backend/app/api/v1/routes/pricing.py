"""Staff pricing routes: settings, surcharge policies, fee lines, estimates, quotes (Phase 13C).

All on the staff router. Anything that shows vendor cost needs ``tariff:read`` (DEC-0172,
OD-45: Operations and Admin). Reading a quote adds ``financial:read``; changing one adds
``financial:write``. Pricing settings and surcharge policies are changed by Admin
(``settings:manage``): they move every future quote. Nothing here is on the public or
Customer Account routers.
"""

from __future__ import annotations

import json
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.encoders import jsonable_encoder

from app.api.deps import DbSession, require
from app.core.db import commit_with_retry, run_unit_with_retry
from app.core.permissions import Permission
from app.models import QuoteVersion, User
from app.schemas.pricing import (
    CartonOut,
    CartonsIn,
    ConfirmRateIn,
    EstimateOut,
    FeeLineAmountIn,
    FeeLineIn,
    FeeLineOut,
    FinalizeIn,
    ManualPricingIn,
    MethodSettingsUpdate,
    PackageMemberIn,
    PackageNoteIn,
    PackagesOut,
    PackedFlagIn,
    PieceTrackingIn,
    PricingSettingsOut,
    PricingSettingsUpdate,
    QuoteLineOut,
    QuoteVersionOut,
    SeaCostIn,
    SurchargePolicyIn,
    SurchargePolicyOut,
)
from app.services import (
    booking_service,
    consolidation_service,
    pricing_method_service,
    pricing_service,
    quote_deletion_service,
    quote_expiry_service,
    workspace_service,
)
from app.services.errors import NotFoundError

router = APIRouter(tags=["pricing"])

P = Permission
TariffReader = Annotated[User, Depends(require(P.TARIFF_READ))]
SettingsManager = Annotated[User, Depends(require(P.TARIFF_READ, P.SETTINGS_MANAGE))]
FeeReader = Annotated[User, Depends(require(P.SHIPMENT_READ, P.TARIFF_READ))]
FeeWriter = Annotated[User, Depends(require(P.SHIPMENT_READ, P.TARIFF_READ, P.SHIPMENT_WRITE))]
QuoteReader = Annotated[User, Depends(require(P.SHIPMENT_READ, P.TARIFF_READ, P.FINANCIAL_READ))]
QuoteWriter = Annotated[
    User,
    Depends(require(P.SHIPMENT_READ, P.TARIFF_READ, P.FINANCIAL_READ, P.FINANCIAL_WRITE)),
]


def quote_out(version: QuoteVersion, expiry: dict | None = None) -> QuoteVersionOut:
    return QuoteVersionOut(
        id=version.id,
        shipment_id=version.shipment_id,
        version=version.version,
        status=version.status,
        solaris_service=version.solaris_service,
        consolidation_id=version.consolidation_id,
        tariff_version_id=version.tariff_version_id,
        fx_snapshot_id=version.fx_snapshot_id,
        default_rate_cad=version.default_rate_cad,
        selling_rate_cad=version.selling_rate_cad,
        override_reason=version.override_reason,
        rate_confirmed=version.rate_confirmed_at is not None,
        rate_confirmed_at=version.rate_confirmed_at,
        negative_margin_reason=version.negative_margin_reason,
        billable_weight_kg=version.billable_weight_kg,
        base_revenue_cad=version.base_revenue_cad,
        surcharge_revenue_cad=version.surcharge_revenue_cad,
        total_revenue_cad=version.total_revenue_cad,
        allocated_cost_cad=version.allocated_cost_cad,
        gross_profit_cad=version.gross_profit_cad,
        blocking=json.loads(version.blocking_json or "[]"),
        provisional=json.loads(version.provisional_json or "[]"),
        lines=[QuoteLineOut.model_validate(line) for line in version.lines],
        finalized_at=version.finalized_at,
        created_at=version.created_at,
        expiry=expiry,
    )


# --- Settings and policies --------------------------------------------------------------------


@router.get("/pricing/settings", response_model=PricingSettingsOut)
def read_settings(db: DbSession, _user: TariffReader) -> PricingSettingsOut:
    return _settings_out(db, pricing_service.get_settings(db))


def _settings_out(db, row) -> PricingSettingsOut:
    markup = pricing_service.get_markup_default(db)
    return PricingSettingsOut(
        air_standard_default_rate_cad=row.air_standard_default_rate_cad,
        air_express_default_rate_cad=row.air_express_default_rate_cad,
        trigger_share_numerator=row.trigger_share_numerator,
        trigger_share_denominator=row.trigger_share_denominator,
        defaults_owner_confirmed=row.defaults_owner_confirmed,
        vendor_delivery_postal_code=row.vendor_delivery_postal_code,
        updated_at=row.updated_at,
        default_markup_kind=markup.markup_kind,
        default_markup_value=markup.markup_value,
        default_markup_label="RC25 method only (no effect under v0.7)",
        default_markup_in_effect=not pricing_method_service.uses_confirmed_method(db),
    )


@router.patch("/pricing/settings", response_model=PricingSettingsOut)
def update_settings(
    payload: PricingSettingsUpdate, db: DbSession, user: SettingsManager
) -> PricingSettingsOut:
    changes = payload.model_dump(exclude_unset=True)
    kind = changes.pop("default_markup_kind", None)
    value = changes.pop("default_markup_value", None)

    def work():
        row = pricing_service.get_settings(db)
        if changes:
            row = pricing_service.update_settings(db, changes, actor=user)
        if kind is not None or value is not None:
            pricing_service.update_markup_default(db, kind, value, actor=user)
        return row

    row = run_unit_with_retry(db, work)
    if row.id is not None:
        db.refresh(row)
    return _settings_out(db, row)


@router.get("/pricing/surcharge-policies", response_model=list[SurchargePolicyOut])
def read_policies(db: DbSession, _user: TariffReader) -> list[SurchargePolicyOut]:
    return [SurchargePolicyOut.model_validate(p) for p in pricing_service.list_policies(db)]


@router.patch("/pricing/surcharge-policies/{section}/{stt}", response_model=SurchargePolicyOut)
def set_policy(
    section: str, stt: int, payload: SurchargePolicyIn, db: DbSession, user: SettingsManager
) -> SurchargePolicyOut:
    def work():
        row = pricing_service.set_policy(db, section, stt, payload.model_dump(), actor=user)
        return row

    row = run_unit_with_retry(db, work)
    db.refresh(row)
    return SurchargePolicyOut.model_validate(row)


# --- Fee lines ---------------------------------------------------------------------------------


def _fee_lines_out(db, lines) -> list[FeeLineOut]:
    """Each line with the customer price entered on it, if any (DEC-0228)."""
    prices = pricing_service.manual_prices(db, [line.id for line in lines])
    return [
        FeeLineOut.model_validate(line).model_copy(
            update={"customer_price_cad": prices.get(line.id)}
        )
        for line in lines
    ]


@router.get("/shipments/{shipment_id}/fee-lines", response_model=list[FeeLineOut])
def list_fee_lines(shipment_id: int, db: DbSession, _user: FeeReader) -> list[FeeLineOut]:
    shipment = booking_service.get_shipment(db, shipment_id)
    return _fee_lines_out(db, pricing_service.active_fee_lines(db, shipment.id))


@router.post("/shipments/{shipment_id}/fee-lines", response_model=FeeLineOut, status_code=201)
def add_fee_line(
    shipment_id: int, payload: FeeLineIn, db: DbSession, user: FeeWriter
) -> FeeLineOut:
    def work():
        shipment = booking_service.get_shipment(db, shipment_id)
        line = pricing_service.add_fee_line(db, shipment, payload.model_dump(), actor=user)
        return shipment, line

    shipment, line = run_unit_with_retry(db, work)
    db.refresh(line)
    return _fee_lines_out(db, [line])[0]


@router.patch("/shipments/{shipment_id}/fee-lines/{line_id}", response_model=FeeLineOut)
def set_fee_line_amount(
    shipment_id: int, line_id: int, payload: FeeLineAmountIn, db: DbSession, user: FeeWriter
) -> FeeLineOut:
    """Enter the vendor's cost (VND) and/or the customer price (CAD) on a line quoted case by
    case (HCM air row 27; DEC-0225, DEC-0228)."""

    def work():
        shipment = booking_service.get_shipment(db, shipment_id)
        return pricing_service.set_fee_line_amount(
            db,
            shipment,
            line_id,
            payload.manual_unit_price_vnd,
            customer_price_cad=payload.customer_price_cad,
            actor=user,
        )

    line = run_unit_with_retry(db, work)
    db.refresh(line)
    return _fee_lines_out(db, [line])[0]


@router.post("/shipments/{shipment_id}/fee-lines/{line_id}/remove", response_model=FeeLineOut)
def remove_fee_line(shipment_id: int, line_id: int, db: DbSession, user: FeeWriter) -> FeeLineOut:
    def work():
        shipment = booking_service.get_shipment(db, shipment_id)
        line = pricing_service.remove_fee_line(db, shipment, line_id, actor=user)
        return shipment, line

    shipment, line = run_unit_with_retry(db, work)
    db.refresh(line)
    return FeeLineOut.model_validate(line)


# --- Master cartons (OD-62) ---------------------------------------------------------------------


@router.get("/consolidations/{consolidation_id}/cartons", response_model=list[CartonOut])
def list_cartons(consolidation_id: int, db: DbSession, _user: FeeReader) -> list[CartonOut]:
    consolidation = consolidation_service.get_consolidation(db, consolidation_id)
    return [CartonOut.model_validate(c) for c in pricing_service.list_cartons(db, consolidation.id)]


@router.patch("/consolidations/{consolidation_id}/cartons", response_model=list[CartonOut])
def replace_cartons(
    consolidation_id: int, payload: CartonsIn, db: DbSession, user: FeeWriter
) -> list[CartonOut]:
    def work():
        consolidation = consolidation_service.get_consolidation(db, consolidation_id)
        rows = pricing_service.replace_cartons(
            db, consolidation, [c.model_dump() for c in payload.cartons], actor=user
        )
        return consolidation, rows

    consolidation, rows = run_unit_with_retry(db, work)
    return [CartonOut.model_validate(c) for c in rows]


# --- The confirmed method's inputs (v0.7 routes for v0.5/v0.6 service functions, DEC-0266) -----


def _method_settings_out(db) -> dict:
    row = pricing_method_service.get_method_settings(db)
    fields = (
        "pricing_method", "air_std_rate_low_cad", "air_std_threshold_kg", "threshold_basis",
        "sea_rate_cad", "markup_kind", "markup_value", "fx_source_cost", "fx_source_quote",
        "kango_fixed_rate_vnd", "residual_mode", "pkg_surcharge_billing",
        "parcel_band_cost_basis", "parcel_quote_mode", "vendor_bill_rounding",
    )  # fmt: skip
    out = {f: getattr(row, f) for f in fields}
    out["air_std_rate_high_cad"] = pricing_service.get_settings(db).air_standard_default_rate_cad
    out["sea_cost_vnd_per_kg"] = pricing_method_service.sea_cost_vnd_per_kg(db)
    out["sea_cost_history"] = pricing_method_service.sea_cost_rows(db)
    out["saved"] = row.id is not None
    return jsonable_encoder(out)


@router.get("/pricing/method-settings")
def read_method_settings(db: DbSession, _user: TariffReader) -> dict:
    return _method_settings_out(db)


@router.patch("/pricing/method-settings")
def update_method_settings(
    payload: MethodSettingsUpdate, db: DbSession, user: SettingsManager
) -> dict:
    """``pricing_method`` takes ``rc25`` or ``confirmed``; ``v0_5`` / ``v0_6`` / ``v0_7`` are
    stored as ``confirmed`` (DEC-0267)."""
    changes = payload.model_dump(exclude_unset=True)
    run_unit_with_retry(
        db, lambda: pricing_method_service.update_method_settings(db, changes, actor=user)
    )
    return _method_settings_out(db)


@router.post("/pricing/sea-cost", status_code=201)
def set_sea_cost(payload: SeaCostIn, db: DbSession, user: SettingsManager) -> dict:
    """A new sea vendor cost per kg from a date; earlier rates stay for earlier masters."""
    run_unit_with_retry(
        db,
        lambda: pricing_method_service.set_sea_cost(
            db, payload.sea_cost_vnd_per_kg, payload.effective_from, actor=user
        ),
    )
    return _method_settings_out(db)


def _manual_out(db, consolidation_id: int) -> dict:
    row = pricing_method_service.get_manual_pricing(db, consolidation_id)
    return jsonable_encoder(
        {
            "consolidation_id": consolidation_id,
            "manual_cost_vnd_per_kg": row.manual_cost_vnd_per_kg if row else None,
            "manual_cost_vnd_total": row.manual_cost_vnd_total if row else None,
            "manual_sell_cad_per_kg": row.manual_sell_cad_per_kg if row else None,
            "reason": row.reason if row else None,
            "set_at": row.set_at if row else None,
        }
    )


@router.get("/consolidations/{consolidation_id}/manual-pricing")
def read_manual_pricing(consolidation_id: int, db: DbSession, _user: QuoteReader) -> dict:
    consolidation = consolidation_service.get_consolidation(db, consolidation_id)
    return _manual_out(db, consolidation.id)


@router.patch("/consolidations/{consolidation_id}/manual-pricing")
def set_manual_pricing(
    consolidation_id: int, payload: ManualPricingIn, db: DbSession, user: QuoteWriter
) -> dict:
    """Air Express / UPS: the vendor cost (VND per kg or a total) and the selling rate (CAD/kg)
    for this master. Replaces what was entered; audited."""

    def work():
        consolidation = consolidation_service.get_consolidation(db, consolidation_id)
        pricing_method_service.set_manual_pricing(
            db, consolidation.id, payload.model_dump(), actor=user
        )
        return consolidation

    consolidation = run_unit_with_retry(db, work)
    return _manual_out(db, consolidation.id)


@router.patch(
    "/consolidations/{consolidation_id}/packages/{carton_sequence}/packed",
    response_model=PackagesOut,
)
def set_packed_flag(
    consolidation_id: int, carton_sequence: int, payload: PackedFlagIn, db: DbSession,
    user: FeeWriter,
) -> PackagesOut:  # fmt: skip
    """ "Packed as one box for Kango" (only on a master with one package, DEC-0262)."""

    def work():
        consolidation = consolidation_service.get_consolidation(db, consolidation_id)
        pricing_method_service.set_package_flag(
            db, consolidation.id, carton_sequence, payload.packed_as_one_box, actor=user
        )
        return consolidation

    consolidation = run_unit_with_retry(db, work)
    return _packages_out(db, consolidation.id)


# --- Packages: customer note and customer ↔ package (method v0.6) ------------------------------


def _packages_out(db, consolidation_id: int) -> PackagesOut:
    return PackagesOut(
        notes=pricing_method_service.package_notes(db, consolidation_id),
        members=pricing_method_service.package_members(db, consolidation_id),
        packed=pricing_method_service.package_flags(db, consolidation_id),
        tracking=workspace_service.piece_tracking(db, consolidation_id),
    )


@router.patch(
    "/consolidations/{consolidation_id}/packages/{carton_sequence}/tracking",
    response_model=PackagesOut,
)
def set_piece_tracking(
    consolidation_id: int, carton_sequence: int, payload: PieceTrackingIn, db: DbSession,
    user: FeeWriter,
) -> PackagesOut:  # fmt: skip
    """Last-mile tracking for one master piece (optional; empty clears it; DEC-0272)."""

    def work():
        consolidation = consolidation_service.get_consolidation(db, consolidation_id)
        workspace_service.set_piece_tracking(
            db, consolidation, carton_sequence, payload.last_mile_tracking, actor=user
        )
        return consolidation

    consolidation = run_unit_with_retry(db, work)
    return _packages_out(db, consolidation.id)


@router.get("/consolidations/{consolidation_id}/packages", response_model=PackagesOut)
def list_packages(consolidation_id: int, db: DbSession, _user: FeeReader) -> PackagesOut:
    consolidation = consolidation_service.get_consolidation(db, consolidation_id)
    return _packages_out(db, consolidation.id)


@router.patch(
    "/consolidations/{consolidation_id}/packages/{carton_sequence}/note",
    response_model=PackagesOut,
)
def set_package_note(
    consolidation_id: int, carton_sequence: int, payload: PackageNoteIn, db: DbSession,
    user: FeeWriter,
) -> PackagesOut:  # fmt: skip
    def work():
        consolidation = consolidation_service.get_consolidation(db, consolidation_id)
        pricing_method_service.set_package_note(
            db, consolidation.id, carton_sequence, payload.customer_note, actor=user
        )
        return consolidation

    consolidation = run_unit_with_retry(db, work)
    return _packages_out(db, consolidation.id)


@router.patch(
    "/consolidations/{consolidation_id}/members/{shipment_id}/package",
    response_model=PackagesOut,
)
def set_package_member(
    consolidation_id: int, shipment_id: int, payload: PackageMemberIn, db: DbSession,
    user: FeeWriter,
) -> PackagesOut:  # fmt: skip
    def work():
        consolidation = consolidation_service.get_consolidation(db, consolidation_id)
        membership = consolidation_service.active_membership_for_shipment(db, shipment_id)
        if membership is None or membership.consolidation_id != consolidation.id:
            raise NotFoundError("That shipment is not in this consolidation.")
        pricing_method_service.set_package_member(
            db, consolidation.id, shipment_id, payload.carton_sequence, actor=user
        )
        return consolidation

    consolidation = run_unit_with_retry(db, work)
    return _packages_out(db, consolidation.id)


# --- Estimates and quotes ----------------------------------------------------------------------


@router.get("/consolidations/{consolidation_id}/pricing", response_model=EstimateOut)
def consolidation_pricing(consolidation_id: int, db: DbSession, _user: QuoteReader) -> EstimateOut:
    consolidation = consolidation_service.get_consolidation(db, consolidation_id)
    est, _version = pricing_service.estimate_for(db, consolidation)
    commit_with_retry(db)
    return EstimateOut(
        consolidation_id=consolidation.id, estimate=pricing_service.estimate_dict(est)
    )


@router.get("/shipments/{shipment_id}/quotes", response_model=list[QuoteVersionOut])
def list_quotes(shipment_id: int, db: DbSession, _user: QuoteReader) -> list[QuoteVersionOut]:
    shipment = booking_service.get_shipment(db, shipment_id)
    expiries = quote_expiry_service.expiries_for_shipment(db, shipment.id)
    # RC-UAT-21 Phase D (DEC-0233): a version an Admin soft-deleted is not listed; the Admin
    # sees deleted ones on the quote history (``/shipments/{id}/quote-history``).
    deleted = quote_deletion_service.deleted_version_ids(db, shipment.id)
    return [
        quote_out(v, quote_expiry_service.expiry_view(db, expiries.get(v.id)))
        for v in pricing_service.list_versions(db, shipment.id)
        if v.id not in deleted
    ]


@router.post("/shipments/{shipment_id}/quotes", response_model=QuoteVersionOut, status_code=201)
def reprice(
    shipment_id: int, request: Request, db: DbSession, user: QuoteWriter
) -> QuoteVersionOut:
    def work():
        shipment = booking_service.get_shipment(db, shipment_id)
        draft, _est = pricing_service.reprice(db, shipment, actor=user)
        return shipment, draft, _est

    shipment, draft, _est = run_unit_with_retry(db, work)
    db.refresh(draft)
    return quote_out(draft)


@router.post("/shipments/{shipment_id}/quotes/confirm-rate", response_model=QuoteVersionOut)
def confirm_rate(
    shipment_id: int, payload: ConfirmRateIn, db: DbSession, user: QuoteWriter
) -> QuoteVersionOut:
    def work():
        shipment = booking_service.get_shipment(db, shipment_id)
        draft = pricing_service.confirm_rate(
            db, shipment, rate=payload.rate, reason=payload.reason, actor=user
        )
        return shipment, draft

    shipment, draft = run_unit_with_retry(db, work)
    db.refresh(draft)
    return quote_out(draft)


@router.post("/shipments/{shipment_id}/quotes/finalize", response_model=QuoteVersionOut)
def finalize(
    shipment_id: int, payload: FinalizeIn, db: DbSession, user: QuoteWriter
) -> QuoteVersionOut:
    def work():
        shipment = booking_service.get_shipment(db, shipment_id)
        version = pricing_service.finalize(
            db, shipment, negative_margin_reason=payload.negative_margin_reason, actor=user
        )
        return shipment, version

    shipment, version = run_unit_with_retry(db, work)
    db.refresh(version)
    return quote_out(version)
