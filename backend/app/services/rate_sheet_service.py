"""Admin "Import Kango rate sheet" (method v0.7, Louis 2026-11-03 entry 33; DEC-0264).

The CRM runs on Louis's own PC, so he loads each new Kango sheet himself. The flow, all on
the existing tariff tables (nothing new in the schema):

1. **Upload** -- ``import_sheet``: the workbook is parsed by the normal importer into a
   **draft** version (both origins, both air services, every zone; piece-fee text; FX line;
   Zone CAD; PHỤ THU). Nothing prices against a draft.
2. **Diff** -- ``sheet_diff``: what the draft changes against the active version: per origin
   / service / zone / band-or-tier, the piece fees, the FX line, the zones and the surcharge
   rows (added / removed / changed). Rows that apply only to other routes are marked
   excluded (Vietnam → Canada only, DEC-0263).
3. **Confirm** -- the existing approve route (``tariff_intake_service.approve``): only an
   explicit confirmation by a designated approver activates it.
4. **History / rollback** -- ``history`` lists every version with its effective date, file
   name, file hash, who imported / activated it and when; ``rollback`` re-activates an
   earlier (superseded) version. A booked master keeps the version it was booked under and a
   finalised quote keeps the version it was priced with.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.enums import TariffProductMode, TariffVersionStatus
from app.core.time_utils import utcnow
from app.models import (
    AuditEvent,
    TariffProduct,
    TariffSurchargeRule,
    TariffVersion,
    TariffZoneFsa,
    User,
)
from app.services import audit_service, quote_expiry_service, tariff_intake_service
from app.services import tariff_import_service as tis
from app.services.errors import ConflictError

#: The Soleil warehouse FSA (Mississauga, ON, L5A 3K6): its zone change is called out.
WAREHOUSE_FSA = "L5A"
VERSION_ACTIONS = (
    "tariff_version.imported",
    "tariff_version.activated",
    "tariff_version.approved",
    "tariff_version.rejected",
    "tariff_version.rolled_back",
)


def import_sheet(
    db: Session,
    content: bytes,
    *,
    file_name: str | None,
    effective_from: date,
    label: str | None,
    actor: User | None,
) -> tuple[TariffVersion, dict]:
    """Parse the workbook into a draft and return it with its diff against the active version.
    Nothing is activated."""
    version = tis.import_workbook(
        db, content, file_name=file_name, effective_from=effective_from, label=label, actor=actor
    )
    return version, sheet_diff(db, version)


def _money(value) -> str | None:
    return None if value is None else str(Decimal(str(value)).quantize(Decimal("0.01")))


def _piece_fees(db: Session, version: TariffVersion | None) -> dict[tuple[str, str], dict]:
    if version is None:
        return {}
    rows = db.scalars(
        select(TariffProduct).where(
            TariffProduct.version_id == version.id,
            TariffProduct.mode == TariffProductMode.AIR.value,
        )
    )
    return {
        (p.origin, p.code): {
            "piece_min_fee_vnd": _money(p.piece_min_fee_vnd),
            "piece_min_weight_kg": _money(p.piece_min_weight_kg),
            "piece_min_applies_above_kg": _money(p.piece_min_applies_above_kg),
            "per_kg_from_kg": _money(p.per_kg_from_kg),
        }
        for p in rows
    }


def _zones(db: Session, version: TariffVersion | None) -> dict[str, tuple]:
    if version is None:
        return {}
    return {
        z.fsa: (z.province, z.ground_zone, z.express_zone)
        for z in db.scalars(select(TariffZoneFsa).where(TariffZoneFsa.version_id == version.id))
    }


def _excluded_rules(db: Session, version: TariffVersion | None) -> list[dict]:
    if version is None:
        return []
    return [
        {"section": r.section, "stt": r.stt, "name": r.name, "note": r.raw_note}
        for r in db.scalars(
            select(TariffSurchargeRule)
            .where(
                TariffSurchargeRule.version_id == version.id,
                TariffSurchargeRule.applies_to_canada.is_(False),
            )
            .order_by(TariffSurchargeRule.section, TariffSurchargeRule.stt)
        )
    ]


def sheet_diff(db: Session, version: TariffVersion) -> dict:
    """The intake diff (brackets, surcharges, products) plus, for the rate-sheet screen: a
    summary per origin / product / zone / kind, the FX line, the piece fees and the zones."""
    base = tariff_intake_service.version_diff(db, version)
    active = tis.active_version(db, version.vendor.key)
    against = None if active is not None and active.id == version.id else active

    # Every changed bracket, grouped (the intake lists are bounded; these counts are not).
    new_b = tariff_intake_service._brackets(db, version)
    old_b = tariff_intake_service._brackets(db, against)
    groups: dict[tuple, dict] = defaultdict(
        lambda: {"changed": 0, "added": 0, "removed": 0, "deltas": []}
    )
    for key in new_b.keys() | old_b.keys():
        origin, code, kind, zone, _label = key
        group = groups[(origin, code, zone, kind)]
        if key not in old_b:
            group["added"] += 1
        elif key not in new_b:
            group["removed"] += 1
        elif Decimal(new_b[key]) != Decimal(old_b[key]):
            group["changed"] += 1
            group["deltas"].append(Decimal(new_b[key]) - Decimal(old_b[key]))
    bracket_groups = [
        {
            "origin": origin,
            "product_code": code,
            "zone": zone,
            "kind": kind,
            "changed": g["changed"],
            "added": g["added"],
            "removed": g["removed"],
            "delta_min_vnd": _money(min(g["deltas"])) if g["deltas"] else None,
            "delta_max_vnd": _money(max(g["deltas"])) if g["deltas"] else None,
        }
        for (origin, code, zone, kind), g in sorted(groups.items())
    ]

    new_p, old_p = _piece_fees(db, version), _piece_fees(db, against)
    piece_fees = [
        {"origin": k[0], "product_code": k[1], "old": old_p.get(k), "new": new_p.get(k)}
        for k in sorted(new_p.keys() | old_p.keys())
        if new_p.get(k) != old_p.get(k)
    ]

    new_z, old_z = _zones(db, version), _zones(db, against)
    zones_changed = [
        {
            "fsa": f,
            "old": dict(zip(("province", "ground_zone", "express_zone"), old_z[f], strict=True)),
            "new": dict(zip(("province", "ground_zone", "express_zone"), new_z[f], strict=True)),
        }
        for f in sorted(new_z.keys() & old_z.keys())
        if new_z[f] != old_z[f]
    ]
    warehouse = new_z.get(WAREHOUSE_FSA)
    fx_old = against.fixed_fx_vnd_per_cad if against else None
    return {
        **base,
        "effective_from": version.effective_from.isoformat(),
        "source_file_name": version.source_file_name,
        "source_sha256": version.source_sha256,
        "fx": {
            "old_vnd_per_cad": _money(fx_old),
            "new_vnd_per_cad": _money(version.fixed_fx_vnd_per_cad),
            "changed": against is not None and fx_old != version.fixed_fx_vnd_per_cad,
        },
        "bracket_groups": bracket_groups,
        "piece_fees_changed": piece_fees,
        "zones_changed": tariff_intake_service._bounded(zones_changed),
        "zones_added": sorted(new_z.keys() - old_z.keys())[
            : tariff_intake_service.MAX_DIFF_ENTRIES
        ],
        "zones_removed": sorted(old_z.keys() - new_z.keys())[
            : tariff_intake_service.MAX_DIFF_ENTRIES
        ],
        "zones_summary": {
            "changed": len(zones_changed),
            "added": len(new_z.keys() - old_z.keys()),
            "removed": len(old_z.keys() - new_z.keys()),
        },
        "warehouse_zone": (
            {"fsa": WAREHOUSE_FSA, "ground_zone": warehouse[1], "express_zone": warehouse[2]}
            if warehouse
            else None
        ),
        "surcharges_excluded_non_canada": _excluded_rules(db, version),
    }


# --- History and rollback -----------------------------------------------------------------------


def history(db: Session, vendor_key: str = tis.KANGO_VENDOR_KEY) -> list[dict]:
    """Every version, newest first, with who / when and its lifecycle events."""
    vendor = tis.get_or_create_vendor(db, vendor_key)
    versions = list(
        db.scalars(
            select(TariffVersion)
            .where(TariffVersion.vendor_id == vendor.id)
            .order_by(TariffVersion.imported_at.desc(), TariffVersion.id.desc())
        )
    )
    events: dict[str, list[dict]] = defaultdict(list)
    ids = [v.public_id for v in versions]
    if ids:
        for e in db.scalars(
            select(AuditEvent)
            .where(
                AuditEvent.entity_type == "tariff_version",
                AuditEvent.entity_id.in_(ids),
                AuditEvent.action.in_(VERSION_ACTIONS),
            )
            .order_by(AuditEvent.id)
        ):
            events[e.entity_id].append(
                {"action": e.action, "at": e.occurred_at, "actor_user_id": e.actor_user_id}
            )
    return [
        {
            "id": v.id,
            "public_id": v.public_id,
            "label": v.label,
            "status": v.status,
            "effective_from": v.effective_from,
            "effective_to": v.effective_to,
            "source_file_name": v.source_file_name,
            "source_sha256": v.source_sha256,
            "imported_at": v.imported_at,
            "imported_by_user_id": v.imported_by_user_id,
            "activated_at": v.activated_at,
            "activated_by_user_id": v.activated_by_user_id,
            "events": events.get(v.public_id, []),
        }
        for v in versions
    ]


def rollback(db: Session, version: TariffVersion, *, actor: User | None) -> TariffVersion:
    """Re-activate an earlier (superseded) version; the active one is superseded. Staff calls
    pass the approver check (``tariff_intake_service.check_can_activate``) at the route."""
    if version.status != TariffVersionStatus.SUPERSEDED:
        raise ConflictError(
            f"Only an earlier, superseded version can be rolled back to; {version.public_id} "
            f"is {version.status}."
        )
    now = utcnow()
    current = tis.active_version(db, version.vendor.key)
    if current is not None:
        current.status = TariffVersionStatus.SUPERSEDED
        current.effective_to = now.date()
    version.status = TariffVersionStatus.ACTIVE
    version.effective_to = None
    version.activated_at = now
    version.activated_by_user_id = actor.id if actor else None
    db.flush()
    audit_service.record_audit(
        db,
        action="tariff_version.rolled_back",
        entity_type="tariff_version",
        entity_id=version.public_id,
        summary=f"Rolled back to tariff {version.public_id}"
        + (f" (superseding {current.public_id})" if current else ""),
        actor=actor,
        detail={"from": current.public_id if current else None, "to": version.public_id},
    )
    # As on any activation: quotes for goods not yet received expire (owner decision 9).
    quote_expiry_service.expire_for_new_tariff(db, version, actor=actor, now=now)
    return version
