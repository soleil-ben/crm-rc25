"""Shipment model to response mapping.

The financial rule is structural rather than cosmetic. A caller without
``financial:read`` gets ``financials: null`` — the object is not built, so no amount is
serialized. A caller with revenue access but without ``financial_cost:read`` gets
no ``financials.costs`` key at all, so ``shipping_cost`` and ``surcharges_amount`` never
appear in the payload. Nulling a field would still ship the key and invite a client to
treat Unknown as zero (CRM.md sections 11 and 12).

List responses batch their package and event lookups, so a page of shipments is a fixed
handful of statements rather than one per row.
"""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.core.enums import ROUTE_GROUP_LABELS, value_label
from app.core.permissions import Permission, permissions_for
from app.models import (
    Consolidation,
    Customer,
    LabelPrintJob,
    LabelPrintJobPackage,
    LegTrackingReference,
    Shipment,
    ShipmentEvent,
    ShipmentLeg,
    ShipmentLegPackage,
    ShipmentPackage,
    User,
)
from app.schemas.consolidation import ConsolidationSummaryOut, ShipmentItemOut
from app.schemas.shipment import (
    AddressSnapshotOut,
    CustomerSummary,
    EventOut,
    LabelJobOut,
    LegOut,
    PackageOut,
    PackageProgressOut,
    ShipmentDetail,
    ShipmentFinancialCostsOut,
    ShipmentFinancialsOut,
    ShipmentListItem,
    TrackingReferenceOut,
)
from app.services import (
    booking_service,
    consolidation_service,
    package_service,
    shipment_item_service,
)
from app.services import public_update_templates as templates
from app.services.package_service import PackageProgress
from app.services.public_tracking_service import tracking_name_key

COVERAGE_NOTE = (
    "Amounts are entered manually. A blank value means Unknown, never zero, and "
    "currencies are never combined without a recorded conversion."
)


def _staff(user: User | None):
    from app.api.presenters import staff_summary

    return staff_summary(user)


def _customer_summary(customer: Customer | None) -> CustomerSummary | None:
    if customer is None:
        return None
    return CustomerSummary(
        id=customer.id,
        public_id=customer.public_id,
        full_name=customer.full_name,
        preferred_language=customer.preferred_language,
    )


def progress_out(progress: PackageProgress) -> PackageProgressOut:
    return PackageProgressOut(
        total=progress.total,
        active=progress.active,
        cancelled=progress.cancelled,
        delivered=progress.delivered,
        summary=progress.summary,
    )


def package_out(package: ShipmentPackage, active: list[ShipmentPackage]) -> PackageOut:
    return PackageOut(
        id=package.id,
        shipment_id=package.shipment_id,
        sequence=package.sequence,
        package_reference=package.package_reference,
        position_label=package_service.position_label(package, active),
        is_active=package.is_active,
        cancelled_at=package.cancelled_at,
        cancellation_reason=package.cancellation_reason,
        length_value=package.length_value,
        width_value=package.width_value,
        height_value=package.height_value,
        dimension_unit=package.dimension_unit,
        length_cm=package.length_cm,
        width_cm=package.width_cm,
        height_cm=package.height_cm,
        weight_value=package.weight_value,
        weight_unit=package.weight_unit,
        weight_kg=package.weight_kg,
        contents_summary=package.contents_summary,
        handling_note=package.handling_note,
        warehouse_location=package.warehouse_location,
        operational_state=package.operational_state,
        delivered_to_recipient_at=package.delivered_to_recipient_at,
        created_at=package.created_at,
    )


def packages_out(db: Session, shipment_id: int) -> list[PackageOut]:
    rows = package_service.all_packages(db, shipment_id)
    active = [package for package in rows if package.is_active]
    return [package_out(package, active) for package in rows]


def _snapshot(shipment: Shipment, role: str) -> AddressSnapshotOut:
    def value(field: str):
        return getattr(shipment, f"{role}_{field}")

    return AddressSnapshotOut(
        name=value("name"),
        company=value("company"),
        phone_entered=value("phone_entered"),
        email=value("email"),
        address_line1=value("address_line1"),
        address_line2=value("address_line2"),
        city=value("city"),
        province_state=value("province_state"),
        postal_code=value("postal_code"),
        country_code=value("country_code"),
        country_input=value("country_input"),
        delivery_note=shipment.recipient_delivery_note if role == "recipient" else None,
        source_address_id=value("address_id"),
    )


def gross_profit(shipment: Shipment) -> Decimal | None:
    """Selling amount less discount, refund, shipping cost and surcharges.

    ``None`` unless both the selling amount and the shipping cost are recorded: a profit
    computed from half the figures is a number somebody will act on. Discount, refund and
    surcharges are optional adjustments and an absent one is zero, which is what their
    absence means -- "no discount", not "unknown discount". Amounts are never combined
    across currencies because a shipment has one currency for all of them.
    """
    if shipment.selling_amount is None or shipment.shipping_cost is None:
        return None

    def money(value) -> Decimal:
        # Through `str`, so a float the seed wrote does not expand into its binary tail.
        return Decimal(str(value)) if value is not None else Decimal("0")

    return (
        money(shipment.selling_amount)
        - money(shipment.discount_amount)
        - money(shipment.refund_amount)
        - money(shipment.shipping_cost)
        - money(shipment.surcharges_amount)
    )


def financials_out(shipment: Shipment, role: str) -> ShipmentFinancialsOut | None:
    """Build the financial block only for a role entitled to see it."""
    granted = permissions_for(role)
    if Permission.FINANCIAL_READ not in granted:
        return None
    costs = None
    if Permission.FINANCIAL_COST_READ in granted:
        costs = ShipmentFinancialCostsOut(
            shipping_cost=shipment.shipping_cost,
            surcharges_amount=shipment.surcharges_amount,
            gross_profit=gross_profit(shipment),
        )
    return ShipmentFinancialsOut(
        currency=shipment.currency,
        selling_amount=shipment.selling_amount,
        discount_amount=shipment.discount_amount,
        refund_amount=shipment.refund_amount,
        declared_value=shipment.declared_value,
        declared_value_currency=shipment.declared_value_currency,
        payment_state=shipment.payment_state,
        costs=costs,
        coverage_note=COVERAGE_NOTE,
    )


# --- Batched list helpers --------------------------------------------------


def _progress_map(db: Session, shipment_ids: list[int]) -> dict[int, PackageProgress]:
    rows = db.execute(
        select(
            ShipmentPackage.shipment_id,
            func.count(ShipmentPackage.id),
            # ``case`` rather than SQLite's ``iif``: no dialect-only SQL leaks into the
            # application, so a future PostgreSQL migration stays practical.
            func.sum(case((ShipmentPackage.is_active.is_(True), 1), else_=0)),
            func.sum(case((ShipmentPackage.delivered_to_recipient_at.is_not(None), 1), else_=0)),
        )
        .where(ShipmentPackage.shipment_id.in_(shipment_ids))
        .group_by(ShipmentPackage.shipment_id)
    ).all()
    result: dict[int, PackageProgress] = {}
    for shipment_id, total, active, delivered in rows:
        active_count = int(active or 0)
        result[shipment_id] = PackageProgress(
            total=int(total or 0),
            active=active_count,
            cancelled=int(total or 0) - active_count,
            delivered=int(delivered or 0),
        )
    return result


def _latest_event_map(db: Session, shipment_ids: list[int]) -> dict[int, ShipmentEvent]:
    rows = db.scalars(
        select(ShipmentEvent)
        .where(ShipmentEvent.shipment_id.in_(shipment_ids), ShipmentEvent.is_voided.is_(False))
        .order_by(ShipmentEvent.occurred_at.asc(), ShipmentEvent.id.asc())
    ).all()
    latest: dict[int, ShipmentEvent] = {}
    for event in rows:
        latest[event.shipment_id] = event
    return latest


def _carrier_map(db: Session, shipment_ids: list[int]) -> dict[int, str]:
    """A short carrier summary per shipment, from active tracking references only."""
    rows = db.execute(
        select(ShipmentLeg.shipment_id, LegTrackingReference.carrier_name)
        .join(LegTrackingReference, LegTrackingReference.leg_id == ShipmentLeg.id)
        .where(
            ShipmentLeg.shipment_id.in_(shipment_ids),
            LegTrackingReference.is_active.is_(True),
        )
    ).all()
    grouped: dict[int, list[str]] = {}
    for shipment_id, carrier in rows:
        names = grouped.setdefault(shipment_id, [])
        if carrier not in names:
            names.append(carrier)
    return {shipment_id: ", ".join(names) for shipment_id, names in grouped.items()}


def _base_fields(
    shipment: Shipment,
    *,
    customer: Customer | None,
    owner: User | None,
    progress: PackageProgress,
    latest_event: ShipmentEvent | None,
    carrier_summary: str | None,
) -> dict:
    return {
        "id": shipment.id,
        "public_id": shipment.public_id,
        "booking_reference": shipment.booking_reference,
        "customer": _customer_summary(customer),
        "route_group": shipment.route_group,
        "route_label": ROUTE_GROUP_LABELS.get(shipment.route_group, shipment.route_group),
        "direction": shipment.direction,
        "direction_label": value_label(shipment.direction) if shipment.direction else None,
        "booking_state": shipment.booking_state,
        "operational_state": shipment.operational_state,
        "payment_state": shipment.payment_state,
        "service_type": shipment.service_type,
        "transport_mode": shipment.transport_mode,
        "package_progress": progress_out(progress),
        "carrier_summary": carrier_summary,
        # The latest *public* wording when one exists, otherwise the normalized state.
        # Internal detail is never promoted into this field.
        "latest_update": (
            (
                latest_event.public_update_text
                or templates.render(latest_event.public_update_template_key or "")
                or value_label(latest_event.event_type)
            )
            if latest_event
            else None
        ),
        "latest_update_at": latest_event.occurred_at if latest_event else None,
        "owner": _staff(owner),
        "booking_date": shipment.booking_date,
        "recipient_name": shipment.recipient_name,
        "destination_city": shipment.recipient_city or shipment.destination_city,
        "destination_country_code": (
            shipment.recipient_country_code or shipment.destination_country_code
        ),
        "is_demo_record": shipment.is_demo_record,
    }


def shipment_list_items(db: Session, shipments: list[Shipment]) -> list[ShipmentListItem]:
    if not shipments:
        return []
    ids = [shipment.id for shipment in shipments]
    progress = _progress_map(db, ids)
    latest = _latest_event_map(db, ids)
    carriers = _carrier_map(db, ids)

    customer_ids = {shipment.customer_id for shipment in shipments}
    customers = {
        customer.id: customer
        for customer in db.scalars(select(Customer).where(Customer.id.in_(customer_ids))).all()
    }
    owner_ids = {shipment.owner_user_id for shipment in shipments if shipment.owner_user_id}
    owners = (
        {user.id: user for user in db.scalars(select(User).where(User.id.in_(owner_ids))).all()}
        if owner_ids
        else {}
    )

    empty = PackageProgress(total=0, active=0, cancelled=0, delivered=0)
    return [
        ShipmentListItem(
            **_base_fields(
                shipment,
                customer=customers.get(shipment.customer_id),
                owner=owners.get(shipment.owner_user_id),
                progress=progress.get(shipment.id, empty),
                latest_event=latest.get(shipment.id),
                carrier_summary=carriers.get(shipment.id),
            )
        )
        for shipment in shipments
    ]


def consolidation_summary_out(
    db: Session, shipment_id: int, *, viewer_role: str | None = None
) -> ConsolidationSummaryOut | None:
    """The master a shipment currently rides in (Phase 13B), or None."""
    membership = consolidation_service.active_membership_for_shipment(db, shipment_id)
    if membership is None:
        return None
    row = db.get(Consolidation, membership.consolidation_id)
    if row is None:
        return None
    return ConsolidationSummaryOut(
        id=row.id,
        public_id=row.public_id,
        state=row.state,
        solaris_service=row.solaris_service,
        origin=row.origin,
        # The vendor's number is vendor data: shown to tariff readers only (DEC-0172).
        vendor_reference=(
            row.vendor_reference
            if viewer_role and Permission.TARIFF_READ in permissions_for(viewer_role)
            else None
        ),
    )


def shipment_detail(db: Session, shipment: Shipment, *, viewer: User) -> ShipmentDetail:
    customer = db.get(Customer, shipment.customer_id)
    owner = db.get(User, shipment.owner_user_id) if shipment.owner_user_id else None
    progress = package_service.progress(db, shipment.id)
    latest = _latest_event_map(db, [shipment.id]).get(shipment.id)
    carrier = _carrier_map(db, [shipment.id]).get(shipment.id)

    payer_id = booking_service.payer_customer_id(db, shipment.id)
    payer = db.get(Customer, payer_id) if payer_id else None

    def linked_public_id(shipment_id: int | None) -> str | None:
        if not shipment_id:
            return None
        return db.scalar(select(Shipment.public_id).where(Shipment.id == shipment_id))

    return ShipmentDetail(
        **_base_fields(
            shipment,
            customer=customer,
            owner=owner,
            progress=progress,
            latest_event=latest,
            carrier_summary=carrier,
        ),
        sender=_snapshot(shipment, "sender"),
        recipient=_snapshot(shipment, "recipient"),
        contents_description=shipment.contents_description,
        estimated_delivery_at=shipment.estimated_delivery_at,
        first_handoff_at=shipment.first_handoff_at,
        delivered_at=shipment.delivered_at,
        confirmed_at=shipment.confirmed_at,
        cancelled_at=shipment.cancelled_at,
        cancellation_reason=shipment.cancellation_reason,
        rebooked_from_shipment_id=shipment.rebooked_from_shipment_id,
        rebooked_to_shipment_id=shipment.rebooked_to_shipment_id,
        rebooked_from_public_id=linked_public_id(shipment.rebooked_from_shipment_id),
        rebooked_to_public_id=linked_public_id(shipment.rebooked_to_shipment_id),
        route_is_locked=shipment.route_is_locked,
        internal_notes=shipment.internal_notes,
        packages=packages_out(db, shipment.id),
        financials=financials_out(shipment, viewer.role),
        payer=_customer_summary(payer),
        consolidation=consolidation_summary_out(db, shipment.id, viewer_role=viewer.role),
        items=[
            ShipmentItemOut.model_validate(item)
            for item in shipment_item_service.list_items(db, shipment.id)
        ],
        created_at=shipment.created_at,
        updated_at=shipment.updated_at,
    )


# --- Legs, events, labels --------------------------------------------------


def tracking_reference_out(
    reference: LegTrackingReference, package_references: dict[int, str | None]
) -> TrackingReferenceOut:
    return TrackingReferenceOut(
        id=reference.id,
        leg_id=reference.leg_id,
        package_id=reference.package_id,
        package_reference=package_references.get(reference.package_id),
        carrier_name=reference.carrier_name,
        tracking_number=reference.tracking_number,
        public_url=reference.public_url,
        source_mode=reference.source_mode,
        source_mode_label=value_label(reference.source_mode),
        is_active=reference.is_active,
        retired_at=reference.retired_at,
        retired_reason=reference.retired_reason,
        created_at=reference.created_at,
    )


def legs_out(db: Session, shipment_id: int) -> list[LegOut]:
    legs = list(
        db.scalars(
            select(ShipmentLeg)
            .where(ShipmentLeg.shipment_id == shipment_id)
            .order_by(ShipmentLeg.sequence)
        ).all()
    )
    if not legs:
        return []
    references = {
        package.id: package.package_reference
        for package in package_service.all_packages(db, shipment_id)
    }
    links = db.execute(
        select(ShipmentLegPackage.leg_id, ShipmentLegPackage.package_id).where(
            ShipmentLegPackage.leg_id.in_([leg.id for leg in legs])
        )
    ).all()
    grouped: dict[int, list[int]] = {}
    for leg_id, package_id in links:
        grouped.setdefault(leg_id, []).append(package_id)

    return [
        LegOut(
            id=leg.id,
            shipment_id=leg.shipment_id,
            sequence=leg.sequence,
            leg_type=leg.leg_type,
            leg_type_label=value_label(leg.leg_type),
            tracking_name_key=tracking_name_key(leg.leg_type),
            provider_name=leg.provider_name,
            service_display=leg.service_display,
            origin_label=leg.origin_label,
            origin_country_code=leg.origin_country_code,
            destination_label=leg.destination_label,
            destination_country_code=leg.destination_country_code,
            is_final_recipient_delivery=leg.is_final_recipient_delivery,
            consolidation_reference=leg.consolidation_reference,
            status=leg.status,
            scheduled_at=leg.scheduled_at,
            completed_at=leg.completed_at,
            internal_notes=leg.internal_notes,
            package_ids=sorted(grouped.get(leg.id, [])),
            package_references=[
                references[package_id]
                for package_id in sorted(grouped.get(leg.id, []))
                if references.get(package_id)
            ],
            tracking_references=[
                tracking_reference_out(reference, references)
                for reference in sorted(
                    leg.tracking_references, key=lambda item: (not item.is_active, item.id)
                )
            ],
        )
        for leg in legs
    ]


def events_out(db: Session, events: list[ShipmentEvent]) -> list[EventOut]:
    if not events:
        return []
    package_ids = {event.package_id for event in events if event.package_id}
    references = (
        {
            package.id: package.package_reference
            for package in db.scalars(
                select(ShipmentPackage).where(ShipmentPackage.id.in_(package_ids))
            ).all()
        }
        if package_ids
        else {}
    )
    user_ids = {event.recorded_by_user_id for event in events if event.recorded_by_user_id}
    users = (
        {user.id: user for user in db.scalars(select(User).where(User.id.in_(user_ids))).all()}
        if user_ids
        else {}
    )
    return [
        EventOut(
            id=event.id,
            shipment_id=event.shipment_id,
            package_id=event.package_id,
            package_reference=references.get(event.package_id),
            leg_id=event.leg_id,
            event_type=event.event_type,
            event_type_label=value_label(event.event_type),
            operational_state=event.operational_state,
            occurred_at=event.occurred_at,
            recorded_at=event.recorded_at,
            location_label=event.location_label,
            location_country_code=event.location_country_code,
            internal_detail=event.internal_detail,
            is_public_update=event.is_public_update,
            public_update_text=event.public_update_text,
            public_update_template_key=event.public_update_template_key,
            public_update_template_text=templates.render(event.public_update_template_key or ""),
            is_final_recipient_delivery=event.is_final_recipient_delivery,
            source=event.source,
            is_voided=event.is_voided,
            voided_reason=event.voided_reason,
            recorded_by=_staff(users.get(event.recorded_by_user_id)),
        )
        for event in events
    ]


def label_jobs_out(db: Session, jobs: list[LabelPrintJob]) -> list[LabelJobOut]:
    if not jobs:
        return []
    links = db.execute(
        select(LabelPrintJobPackage.job_id, LabelPrintJobPackage.package_reference).where(
            LabelPrintJobPackage.job_id.in_([job.id for job in jobs])
        )
    ).all()
    grouped: dict[int, list[str]] = {}
    for job_id, reference in links:
        grouped.setdefault(job_id, []).append(reference)

    user_ids = {job.generated_by_user_id for job in jobs if job.generated_by_user_id}
    users = (
        {user.id: user for user in db.scalars(select(User).where(User.id.in_(user_ids))).all()}
        if user_ids
        else {}
    )
    return [
        LabelJobOut(
            id=job.id,
            shipment_id=job.shipment_id,
            kind=job.kind,
            is_reprint=job.is_reprint,
            page_count=job.page_count,
            document_sha256=job.document_sha256,
            generated_at=job.generated_at,
            generated_by=_staff(users.get(job.generated_by_user_id)),
            package_references=sorted(grouped.get(job.id, [])),
        )
        for job in jobs
    ]
