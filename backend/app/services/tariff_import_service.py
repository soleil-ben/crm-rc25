"""Import a vendor tariff workbook as a new, immutable tariff version (Phase 13A).

The reader (``app/pricing/kango_workbook.py``) returns the vendor's tables with their
cells; the semantics module (``app/pricing/kango_semantics.py``) says what the prose
means; this service persists both as one ``TariffVersion`` and writes the import report.

Rules this service enforces:

* **Same bytes, same tariff.** A file whose SHA-256 already exists for the vendor is
  refused with ``ConflictError``; the existing version is named in the message.
* **Draft first.** A new version is ``draft``. Pricing uses only the ``active`` version;
  ``activate_version`` is a separate, audited, admin-only act that supersedes the previous
  one and never deletes it.
* **Ambiguity is stored as a state.** Unpriced, conflicting and route-excluded surcharge
  rows are written with that status; a beyond code with postal codes but no rate is
  written as ``no_rate``. Nothing is coerced into a number.
* **Curated semantics must still fit the row.** A curated entry applies only when the
  row's name contains the expected words; otherwise the parser's reading is used and a
  ``curated_entry_unmatched`` anomaly is added to the report, so a reworded workbook is a
  review item rather than a silent mis-price.
* **No personal data.** The reader never reads the vendor staff sheet; the report holds
  counts, anomalies and tariff rule text only.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime

from sqlalchemy import func, insert, select
from sqlalchemy.orm import Session

from app.core.enums import (
    BeyondRateStatus,
    SemanticsSource,
    SurchargeBasis,
    SurchargePricingStatus,
    TariffVersionStatus,
)
from app.core.time_utils import utcnow
from app.models import (
    KANGO_VENDOR_KEY,
    ServiceVendorProduct,
    TariffAccessorial,
    TariffBeyondPostalCode,
    TariffBeyondRate,
    TariffProduct,
    TariffRateBracket,
    TariffSurchargeRule,
    TariffSurchargeRuleTier,
    TariffVersion,
    TariffVersionReview,
    TariffZoneFsa,
    User,
    Vendor,
)
from app.pricing import kango_semantics as semantics
from app.pricing.kango_workbook import (
    Anomaly,
    ParsedSurchargeRow,
    ParsedWorkbook,
    WorkbookLayoutError,
    dedupe_beyond_rates,
    parse_workbook,
)
from app.pricing.service_mapping import AIR_SERVICE_PRODUCTS
from app.services import audit_service, quote_expiry_service
from app.services.errors import ConflictError, NotFoundError, ValidationError
from app.services.identifier_service import next_tariff_version_public_id

KANGO_VENDOR_NAME = "Kango Logistics"


def get_or_create_vendor(db: Session, key: str = KANGO_VENDOR_KEY) -> Vendor:
    vendor = db.scalar(select(Vendor).where(Vendor.key == key))
    if vendor is None:
        vendor = Vendor(key=key, name=KANGO_VENDOR_NAME if key == KANGO_VENDOR_KEY else key)
        db.add(vendor)
        db.flush()
    return vendor


def active_version(db: Session, vendor_key: str = KANGO_VENDOR_KEY) -> TariffVersion | None:
    return db.scalar(
        select(TariffVersion)
        .join(Vendor)
        .where(Vendor.key == vendor_key, TariffVersion.status == TariffVersionStatus.ACTIVE)
    )


def get_version(db: Session, version_id: int) -> TariffVersion:
    version = db.get(TariffVersion, version_id)
    if version is None:
        raise NotFoundError("Tariff version not found.")
    return version


# --- Import ----------------------------------------------------------------------------


def import_workbook(
    db: Session,
    content: bytes,
    *,
    file_name: str | None,
    effective_from: date,
    label: str | None,
    actor: User | None,
    vendor_key: str = KANGO_VENDOR_KEY,
    now: datetime | None = None,
) -> TariffVersion:
    """Parse the workbook and persist it as a draft version. The caller commits."""
    now = now or utcnow()
    # The digest is checked before the parse: a re-upload of a known file answers at once.
    digest = hashlib.sha256(content).hexdigest()
    vendor = get_or_create_vendor(db, vendor_key)
    existing = db.scalar(
        select(TariffVersion).where(
            TariffVersion.vendor_id == vendor.id,
            TariffVersion.source_sha256 == digest,
        )
    )
    if existing is not None:
        raise ConflictError(
            f"This exact file was already imported as {existing.public_id} ({existing.status})."
        )
    try:
        parsed = parse_workbook(content)
    except WorkbookLayoutError as error:
        raise ValidationError(
            f"The workbook could not be read as a Kango tariff: {error}"
        ) from error

    version = TariffVersion(
        public_id=next_tariff_version_public_id(db),
        vendor_id=vendor.id,
        label=label or f"Kango Canada rates effective {effective_from.isoformat()}",
        source_file_name=file_name[:255] if file_name else None,
        source_sha256=parsed.source_sha256,
        effective_from=effective_from,
        status=TariffVersionStatus.DRAFT,
        imported_at=now,
        imported_by_user_id=actor.id if actor else None,
        dim_divisor_default=6000,
        fixed_fx_vnd_per_cad=parsed.fixed_fx_vnd_per_cad,
        import_report_json="{}",
    )
    db.add(version)
    db.flush()

    anomalies: list[Anomaly] = list(parsed.anomalies)
    _write_products_and_brackets(db, version, parsed, anomalies)
    _write_zones(db, version, parsed)
    _write_beyond(db, version, parsed)
    _write_accessorials(db, version)
    rule_status_counts = _write_surcharge_rules(db, version, parsed, anomalies)
    _write_service_mapping(db, version, anomalies, now)

    version.import_report_json = json.dumps(
        _build_report(parsed, anomalies, rule_status_counts), ensure_ascii=False
    )
    audit_service.record_audit(
        db,
        action="tariff_version.imported",
        entity_type="tariff_version",
        entity_id=version.public_id,
        summary=f"Imported {vendor.key} tariff {version.public_id} (draft)",
        actor=actor,
        detail={"sha256": parsed.source_sha256, "counts": parsed.counts()},
    )
    return version


def _write_products_and_brackets(
    db: Session, version: TariffVersion, parsed: ParsedWorkbook, anomalies: list[Anomaly]
) -> None:
    product_ids: dict[tuple[str, str], int] = {}
    for product in parsed.products:
        rules = semantics.PRODUCT_RULES.get((product.code, product.last_mile))
        if rules is None:
            anomalies.append(
                Anomaly(
                    "product_rules_missing",
                    f"no reviewed divisor / minimum rules for {product.code}; defaults applied",
                    product.sheet,
                    None,
                )
            )
        row = TariffProduct(
            version_id=version.id,
            code=product.code,
            origin=product.origin.value,
            mode=product.mode.value,
            last_mile=product.last_mile.value,
            dim_divisor=rules.dim_divisor if rules else version.dim_divisor_default,
            per_kg_from_kg=rules.per_kg_from_kg if rules else None,
            piece_min_weight_kg=rules.piece_min_weight_kg if rules else None,
            piece_min_fee_vnd=rules.piece_min_fee_vnd if rules else None,
            piece_min_applies_above_kg=rules.piece_min_applies_above_kg if rules else None,
            min_chargeable_kg=rules.min_chargeable_kg if rules else None,
            customs_surcharges_waived=product.customs_surcharges_waived,
            transit_text=product.transit_text[:200] if product.transit_text else None,
            source_sheet=product.sheet,
        )
        db.add(row)
        db.flush()
        product_ids[(product.origin.value, product.code)] = row.id

    db.execute(
        insert(TariffRateBracket),
        [
            {
                "product_id": product_ids[(b.origin.value, b.product_code)],
                "kind": b.kind,
                "zone": b.zone,
                "label": b.label,
                "weight_from_kg": b.weight_from_kg,
                "weight_to_kg": b.weight_to_kg,
                "price_vnd": b.price_vnd,
                "source_sheet": b.sheet,
                "source_cell": b.cell,
            }
            for b in parsed.brackets
        ],
    )


def _write_service_mapping(
    db: Session, version: TariffVersion, anomalies: list[Anomaly], now: datetime
) -> None:
    """Solaris service → vendor product rows for this version, per origin (OD-43, air only).

    A service whose product is missing from the import is reported, not invented.
    """
    products = {
        (p.origin, p.code, p.last_mile): p.id
        for p in db.scalars(select(TariffProduct).where(TariffProduct.version_id == version.id))
    }
    origins = sorted({origin for origin, _, _ in products})
    for service, (code, last_mile) in AIR_SERVICE_PRODUCTS.items():
        for origin in origins:
            product_id = products.get((origin, code, last_mile.value))
            if product_id is None:
                anomalies.append(
                    Anomaly(
                        "service_mapping_product_missing",
                        f"{service.value} from {origin} maps to {code!r}, which this workbook "
                        "does not price",
                        None,
                        None,
                    )
                )
                continue
            db.add(
                ServiceVendorProduct(
                    tariff_version_id=version.id,
                    solaris_service=service.value,
                    origin=origin,
                    tariff_product_id=product_id,
                    created_at=now,
                )
            )
    db.flush()


def _write_zones(db: Session, version: TariffVersion, parsed: ParsedWorkbook) -> None:
    db.execute(
        insert(TariffZoneFsa),
        [
            {
                "version_id": version.id,
                "fsa": z.fsa,
                "province": z.province,
                "ground_zone": z.ground_zone,
                "express_zone": z.express_zone,
            }
            for z in parsed.zone_fsas
        ],
    )


def _write_beyond(db: Session, version: TariffVersion, parsed: ParsedWorkbook) -> None:
    db.execute(
        insert(TariffBeyondPostalCode),
        [
            {
                "version_id": version.id,
                "postal_code": p.postal_code,
                "city": p.city[:80] if p.city else None,
                "province": p.province,
                "beyond_code": p.beyond_code,
            }
            for p in parsed.beyond_postal_codes
        ],
    )
    rated = dedupe_beyond_rates(parsed)
    rows = [
        {
            "version_id": version.id,
            "beyond_code": r.beyond_code,
            "status": BeyondRateStatus.PRICED.value,
            "base_cad": r.base_cad,
            "per_lb_cad": r.per_lb_cad,
            "source_sheet": r.sheet,
            "source_cell": r.cell,
        }
        for r in rated
    ]
    rated_codes = {r.beyond_code for r in rated}
    for code in sorted({p.beyond_code for p in parsed.beyond_postal_codes} - rated_codes):
        rows.append(
            {
                "version_id": version.id,
                "beyond_code": code,
                "status": BeyondRateStatus.NO_RATE.value,
                "base_cad": None,
                "per_lb_cad": None,
                "source_sheet": None,
                "source_cell": None,
            }
        )
    db.execute(insert(TariffBeyondRate), rows)


def _write_accessorials(db: Session, version: TariffVersion) -> None:
    db.execute(
        insert(TariffAccessorial),
        [
            {
                "version_id": version.id,
                "key": a.key,
                "description": a.description,
                "amount": a.amount,
                "currency": a.currency,
                "basis": a.basis.value,
                "applies_to_modes": ",".join(m.value for m in a.modes),
                "source_sheet": a.sheet,
                "source_cell": a.cell,
            }
            for a in semantics.ACCESSORIALS
        ],
    )


def resolve_rule(row: ParsedSurchargeRow, anomalies: list[Anomaly]) -> dict:
    """Merge the strict parse with the curated reading. Returns column values."""
    parsed = semantics.parse_price_text(row.price_text)
    curated = semantics.CURATED_RULES.get((row.section, row.stt))
    source = SemanticsSource.PARSED
    if curated is not None:
        if curated.name_contains in semantics.fold(row.name):
            source = SemanticsSource.CURATED
        else:
            anomalies.append(
                Anomaly(
                    "curated_entry_unmatched",
                    f"section {row.section.value} row {row.stt}: reviewed reading expects a row "
                    f"about {curated.name_contains!r}, found a different name; parser "
                    "reading used instead",
                    row.sheet,
                    f"B{row.row}",
                )
            )
            curated = None

    status = curated.pricing_status if curated and curated.pricing_status else parsed.status
    basis = curated.basis if curated and curated.basis else parsed.basis
    scope = curated.scope if curated and curated.scope else semantics.default_scope(basis)
    unit_price = (
        curated.unit_price_vnd
        if curated and curated.unit_price_vnd is not None
        else parsed.unit_price_vnd
    )
    if status in {
        SurchargePricingStatus.UNPRICED_VENDOR_REVIEW,
        SurchargePricingStatus.CONFLICT,
        SurchargePricingStatus.FREE,
        SurchargePricingStatus.NOT_APPLICABLE_CANADA,
    }:
        # A number on an unusable row is a number somebody will eventually use.
        unit_price = None
    if status == SurchargePricingStatus.TIERED:
        unit_price = None
    if basis == SurchargeBasis.MANUAL_AMOUNT:
        # Quoted case by case: staff enter the line's amount; no prefill (DEC-0225).
        unit_price = None
    applies = semantics.SECTION_APPLIES_TO_CANADA[row.section]
    if curated and curated.applies_to_canada is not None:
        applies = curated.applies_to_canada
    if status == SurchargePricingStatus.NOT_APPLICABLE_CANADA:
        applies = False

    note_parts = []
    if curated:
        note_parts.append(curated.note)
    elif parsed.reason:
        note_parts.append(parsed.reason)
    return {
        "basis": basis.value,
        "scope": scope.value,
        "pricing_status": status.value,
        "unit_price_vnd": unit_price,
        "per_unit_price_vnd": curated.per_unit_price_vnd if curated else None,
        "per_unit_label": curated.per_unit_label if curated else None,
        "min_charge_kg": (
            curated.min_charge_kg
            if curated and curated.min_charge_kg is not None
            else parsed.min_charge_kg
        ),
        "max_kg_per_shipment": curated.max_kg_per_shipment if curated else None,
        "applies_to_canada": applies,
        "semantics_source": source.value,
        "semantics_note": " ".join(note_parts)[:500] or None,
        "tiers": curated.tiers if curated else (),
    }


def _write_surcharge_rules(
    db: Session, version: TariffVersion, parsed: ParsedWorkbook, anomalies: list[Anomaly]
) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in parsed.surcharge_rows:
        resolved = resolve_rule(row, anomalies)
        tiers = resolved.pop("tiers")
        rule = TariffSurchargeRule(
            version_id=version.id,
            section=row.section.value,
            section_label=row.section_label[:200],
            stt=row.stt,
            name=row.name[:300],
            raw_price_text=row.price_text[:200],
            raw_note=row.note,
            source_sheet=row.sheet,
            source_row=row.row,
            **resolved,
        )
        db.add(rule)
        db.flush()
        for tier in tiers:
            db.add(
                TariffSurchargeRuleTier(
                    rule_id=rule.id,
                    weight_from_kg=tier.weight_from_kg,
                    weight_to_kg=tier.weight_to_kg,
                    price_vnd=tier.price_vnd,
                )
            )
        counts[rule.pricing_status] = counts.get(rule.pricing_status, 0) + 1
    # Every curated entry should have found its row; one that did not is worth knowing.
    seen = {(r.section, r.stt) for r in parsed.surcharge_rows}
    for key in semantics.CURATED_RULES:
        if key not in seen:
            anomalies.append(
                Anomaly(
                    "curated_entry_row_missing",
                    f"reviewed reading for section {key[0].value} row {key[1]} found no such row",
                    None,
                    None,
                )
            )
    return counts


def _build_report(
    parsed: ParsedWorkbook, anomalies: list[Anomaly], rule_status_counts: dict[str, int]
) -> dict:
    anomaly_counts: dict[str, int] = {}
    for a in anomalies:
        anomaly_counts[a.code] = anomaly_counts.get(a.code, 0) + 1
    return {
        "source_sha256": parsed.source_sha256,
        "sheets": parsed.sheet_names,
        "skipped_sheets": parsed.skipped_sheets,
        "counts": parsed.counts(),
        "surcharge_rows_by_status": rule_status_counts,
        "surcharge_advisory_rows": [
            {"section": s, "stt": n, "text": t[:200]} for s, n, t in parsed.surcharge_advisory_rows
        ],
        "fixed_fx_vnd_per_cad": str(parsed.fixed_fx_vnd_per_cad)
        if parsed.fixed_fx_vnd_per_cad
        else None,
        "anomaly_counts": anomaly_counts,
        "anomalies": [a.as_dict() for a in anomalies],
        # Informational: drops the owner confirmed as the vendor's intended rate (DEC-0222).
        "confirmed_price_steps": [s.as_dict() for s in parsed.confirmed_price_steps],
        "rules_in_prose": {
            "rounding": semantics.ROUNDING_RULE,
            "refusal": semantics.REFUSAL_RULE,
            "rule_text_cells": [f"{r.sheet}!{r.cell}" for r in parsed.rule_texts],
        },
        "not_imported": [
            "trucking pallet delivery fees (C$ by pallet count and area; quoted per case)",
            "compensation policy sheet (prose; not a price)",
        ],
    }


# --- Activation ------------------------------------------------------------------------


def activate_version(
    db: Session, version: TariffVersion, *, actor: User | None, now: datetime | None = None
) -> TariffVersion:
    """Make this version the one quotations price against. Supersedes, never deletes."""
    now = now or utcnow()
    if version.status == TariffVersionStatus.ACTIVE:
        return version
    if version.status == TariffVersionStatus.SUPERSEDED:
        raise ConflictError("A superseded tariff version cannot be re-activated; import it again.")
    # Phase 13H: a version an approver rejected is never activated, by any path.
    rejected = db.scalar(
        select(TariffVersionReview).where(
            TariffVersionReview.tariff_version_id == version.id,
            TariffVersionReview.decision == "rejected",
        )
    )
    if rejected is not None:
        raise ConflictError(
            f"{version.public_id} was rejected by an approver and cannot be activated."
        )
    previous = active_version(db, version.vendor.key)
    if previous is not None:
        previous.status = TariffVersionStatus.SUPERSEDED
        previous.effective_to = version.effective_from
    version.status = TariffVersionStatus.ACTIVE
    version.activated_at = now
    version.activated_by_user_id = actor.id if actor else None
    db.flush()
    audit_service.record_audit(
        db,
        action="tariff_version.activated",
        entity_type="tariff_version",
        entity_id=version.public_id,
        summary=f"Activated tariff {version.public_id}"
        + (f", superseding {previous.public_id}" if previous else ""),
        actor=actor,
        detail={"superseded": previous.public_id if previous else None},
    )
    quote_expiry_service.expire_for_new_tariff(db, version, actor=actor, now=now)
    return version


# --- Read helpers for the routes -------------------------------------------------------


def report(version: TariffVersion) -> dict:
    try:
        return json.loads(version.import_report_json or "{}")
    except json.JSONDecodeError:
        return {}


def version_counts(db: Session, version: TariffVersion) -> dict[str, int]:
    def count(model, where) -> int:
        return db.scalar(select(func.count()).select_from(model).where(where)) or 0

    product_ids = select(TariffProduct.id).where(TariffProduct.version_id == version.id)
    return {
        "products": count(TariffProduct, TariffProduct.version_id == version.id),
        "rate_brackets": count(TariffRateBracket, TariffRateBracket.product_id.in_(product_ids)),
        "zone_fsas": count(TariffZoneFsa, TariffZoneFsa.version_id == version.id),
        "beyond_postal_codes": count(
            TariffBeyondPostalCode, TariffBeyondPostalCode.version_id == version.id
        ),
        "beyond_rates": count(TariffBeyondRate, TariffBeyondRate.version_id == version.id),
        "accessorials": count(TariffAccessorial, TariffAccessorial.version_id == version.id),
        "surcharge_rules": count(TariffSurchargeRule, TariffSurchargeRule.version_id == version.id),
    }
