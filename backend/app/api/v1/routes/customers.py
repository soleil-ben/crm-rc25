"""Customer routes: list, create, read, update, archive, duplicates, and merge.

CSV export moved to ``app/api/v1/routes/exports.py`` in Phase 5A. It lives with the other
exports so there is one column allowlist, one formula-injection guard, one streaming
implementation, and one audit shape rather than a per-route copy of each (DEC-0080).
"""

from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, or_, select

from app.api import presenters
from app.api.deps import (
    DbSession,
    Thresholds,
    client_ip,
    has,
    require,
)
from app.core.db import commit_with_retry, persist_refusal_audit
from app.core.permissions import Permission
from app.models import Customer, User
from app.schemas.common import Page
from app.schemas.customer import (
    ArchiveRequest,
    CustomerCreate,
    CustomerDetail,
    CustomerFinancialSummaryOut,
    CustomerListItem,
    CustomerUpdate,
    DuplicateCheckRequest,
    DuplicateCheckResponse,
    MergeRequest,
    ReferralCreate,
    ReferralOut,
)
from app.services import customer_service, duplicate_service
from app.services.activity_service import (
    compute_customer_activity,
)
from app.services.errors import DomainError, ValidationError

router = APIRouter(prefix="/customers", tags=["customers"])

SORT_COLUMNS = {
    "full_name": Customer.full_name,
    "public_id": Customer.public_id,
    "created_at": Customer.created_at,
    "city": Customer.city,
}


def _load_customer(db, customer_id: int) -> Customer:
    return customer_service.get_customer(db, customer_id)


@router.get("", response_model=Page[CustomerListItem])
def list_customers(
    db: DbSession,
    thresholds: Thresholds,
    _user: Annotated[User, Depends(require(Permission.CUSTOMER_READ))],
    search: str | None = None,
    # `q` is the name the global search uses and the one a person types into a URL by
    # hand; the UAT run did exactly that and got an unfiltered list (fix pack item 4).
    # Either spelling works; `search` wins when both are present.
    q: str | None = Query(default=None, max_length=120),
    category: list[str] | None = Query(default=None),
    lifecycle_status: list[str] | None = Query(default=None),
    preferred_language: list[str] | None = Query(default=None),
    primary_route: list[str] | None = Query(default=None),
    observed_route: str | None = None,
    owner_user_id: int | None = None,
    tag_id: list[int] | None = Query(default=None),
    has_overdue_task: bool | None = None,
    has_service_issue: bool | None = None,
    last_shipment_within_days: int | None = Query(default=None, ge=0),
    last_shipment_before_days: int | None = Query(default=None, ge=0),
    created_from: date | None = None,
    created_to: date | None = None,
    include_archived: bool = False,
    sort: str = Query(default="full_name"),
    direction: str = Query(default="asc", pattern="^(asc|desc)$"),
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> Page[CustomerListItem]:
    search = search or q
    conditions = customer_service.build_list_conditions(
        db,
        thresholds,
        search=search,
        category=category,
        lifecycle_status=lifecycle_status,
        preferred_language=preferred_language,
        primary_route=primary_route,
        observed_route=observed_route,
        owner_user_id=owner_user_id,
        tag_id=tag_id,
        has_overdue_task=has_overdue_task,
        has_service_issue=has_service_issue,
        last_shipment_within_days=last_shipment_within_days,
        last_shipment_before_days=last_shipment_before_days,
        created_from=created_from,
        created_to=created_to,
        include_archived=include_archived,
    )
    total = int(db.scalar(select(func.count(Customer.id)).where(*conditions)) or 0)
    column = SORT_COLUMNS.get(sort, Customer.full_name)
    order = column.asc() if direction == "asc" else column.desc()
    rows = list(
        db.scalars(
            select(Customer)
            .where(*conditions)
            .order_by(order, Customer.id.asc())
            .limit(limit)
            .offset(offset)
        ).all()
    )
    items = presenters.customer_list_items(db, rows, thresholds)
    return Page[CustomerListItem](items=items, total=total, limit=limit, offset=offset)


@router.post("", response_model=CustomerDetail, status_code=201)
def create_customer(
    payload: CustomerCreate,
    request: Request,
    db: DbSession,
    thresholds: Thresholds,
    user: Annotated[User, Depends(require(Permission.CUSTOMER_CREATE))],
) -> CustomerDetail:
    data = payload.model_dump(exclude={"tag_ids", "acknowledge_duplicates"})
    data["additional_route_interests"] = (
        [route.value for route in payload.additional_route_interests]
        if payload.additional_route_interests is not None
        else None
    )
    for key in (
        "preferred_language",
        "category",
        "business_type",
        "primary_shipping_purpose",
        "primary_route_group",
        "shipping_frequency",
        "preferred_contact_channel",
    ):
        value = data.get(key)
        if value is not None and hasattr(value, "value"):
            data[key] = value.value

    customer = customer_service.create_customer(db, data, actor=user, ip_address=client_ip(request))
    if payload.tag_ids:
        customer_service.set_customer_tags(db, customer, payload.tag_ids, actor=user)
    commit_with_retry(db)
    db.refresh(customer)
    return presenters.customer_detail(db, customer, thresholds)


@router.post("/duplicate-check", response_model=DuplicateCheckResponse)
def duplicate_check(
    payload: DuplicateCheckRequest,
    db: DbSession,
    thresholds: Thresholds,
    _user: Annotated[User, Depends(require(Permission.CUSTOMER_READ, Permission.DUPLICATE_REVIEW))],
) -> DuplicateCheckResponse:
    """Surface possible duplicates before save. Never merges anything (AC-16).

    Gated on ``duplicate:review`` as well as ``customer:read``: this endpoint puts two
    people's contact details side by side so a reviewer can decide whether they are one
    person, which is a different act from reading one record.
    """
    try:
        candidates = duplicate_service.find_duplicate_candidates(
            db,
            full_name=payload.full_name,
            email=payload.email,
            phone=payload.phone,
            country_code=payload.country_code,
            exclude_customer_id=payload.exclude_customer_id,
        )
    except ValueError:
        candidates = []
    return DuplicateCheckResponse(
        candidates=presenters.duplicate_candidates_out(db, candidates, thresholds)
    )


@router.get("/{customer_id}", response_model=CustomerDetail)
def get_customer(
    customer_id: int,
    db: DbSession,
    thresholds: Thresholds,
    _user: Annotated[User, Depends(require(Permission.CUSTOMER_READ))],
) -> CustomerDetail:
    customer = _load_customer(db, customer_id)
    candidates = duplicate_service.find_duplicate_candidates(
        db,
        full_name=customer.full_name,
        email=customer.email_entered,
        phone=customer.phone_entered,
        country_code=customer.country_code,
        exclude_customer_id=customer.id,
        limit=1,
    )
    return presenters.customer_detail(db, customer, thresholds, has_duplicates=bool(candidates))


@router.patch("/{customer_id}", response_model=CustomerDetail)
def update_customer(
    customer_id: int,
    payload: CustomerUpdate,
    request: Request,
    db: DbSession,
    thresholds: Thresholds,
    user: Annotated[User, Depends(require(Permission.CUSTOMER_UPDATE))],
) -> CustomerDetail:
    customer = _load_customer(db, customer_id)
    data = payload.model_dump(exclude_unset=True, exclude={"tag_ids"})
    if "additional_route_interests" in data and data["additional_route_interests"] is not None:
        data["additional_route_interests"] = [
            route.value if hasattr(route, "value") else route
            for route in data["additional_route_interests"]
        ]
    for key, value in list(data.items()):
        if value is not None and hasattr(value, "value"):
            data[key] = value.value

    customer_service.update_customer(db, customer, data, actor=user, ip_address=client_ip(request))
    if payload.tag_ids is not None:
        customer_service.set_customer_tags(db, customer, payload.tag_ids, actor=user)
    commit_with_retry(db)
    db.refresh(customer)
    return presenters.customer_detail(db, customer, thresholds)


@router.post("/{customer_id}/archive", response_model=CustomerDetail)
def archive_customer(
    customer_id: int,
    payload: ArchiveRequest,
    request: Request,
    db: DbSession,
    thresholds: Thresholds,
    user: Annotated[User, Depends(require(Permission.CUSTOMER_ARCHIVE))],
) -> CustomerDetail:
    customer = _load_customer(db, customer_id)
    customer_service.archive_customer(
        db, customer, reason=payload.reason, actor=user, ip_address=client_ip(request)
    )
    commit_with_retry(db)
    return presenters.customer_detail(db, customer, thresholds)


@router.post("/{customer_id}/restore", response_model=CustomerDetail)
def restore_customer(
    customer_id: int,
    request: Request,
    db: DbSession,
    thresholds: Thresholds,
    user: Annotated[User, Depends(require(Permission.CUSTOMER_ARCHIVE))],
) -> CustomerDetail:
    customer = _load_customer(db, customer_id)
    customer_service.restore_customer(db, customer, actor=user, ip_address=client_ip(request))
    commit_with_retry(db)
    return presenters.customer_detail(db, customer, thresholds)


@router.get("/{customer_id}/duplicate-candidates", response_model=DuplicateCheckResponse)
def customer_duplicates(
    customer_id: int,
    db: DbSession,
    thresholds: Thresholds,
    _user: Annotated[User, Depends(require(Permission.CUSTOMER_READ, Permission.DUPLICATE_REVIEW))],
) -> DuplicateCheckResponse:
    customer = _load_customer(db, customer_id)
    candidates = duplicate_service.find_duplicate_candidates(
        db,
        full_name=customer.full_name,
        email=customer.email_entered,
        phone=customer.phone_entered,
        country_code=customer.country_code,
        exclude_customer_id=customer.id,
    )
    return DuplicateCheckResponse(
        candidates=presenters.duplicate_candidates_out(db, candidates, thresholds)
    )


@router.post("/merge", response_model=CustomerDetail)
def merge_customers(
    payload: MergeRequest,
    request: Request,
    db: DbSession,
    thresholds: Thresholds,
    user: Annotated[User, Depends(require(Permission.CUSTOMER_MERGE))],
) -> CustomerDetail:
    source = _load_customer(db, payload.source_customer_id)
    target = _load_customer(db, payload.target_customer_id)
    if payload.confirmation.strip().upper() != source.public_id:
        raise ValidationError(
            "Type the source customer ID exactly to confirm the merge.", field="confirmation"
        )
    try:
        customer_service.merge_customers(
            db, source=source, target=target, actor=user, ip_address=client_ip(request)
        )
    except DomainError as exc:
        # A refused merge writes nothing, including no audit row. The record of the refusal
        # is attached to the exception and written afterwards, on a session this call rolls
        # back clean first -- which is how OD-40 gets both "no mutation on refusal" and
        # "audit the refusal" (DEC-0111). A refusal carrying no hook is untouched.
        persist_refusal_audit(db, exc)
        raise
    commit_with_retry(db)
    db.refresh(target)
    return presenters.customer_detail(db, target, thresholds)


@router.get("/{customer_id}/financials", response_model=CustomerFinancialSummaryOut)
def customer_financials(
    customer_id: int,
    db: DbSession,
    thresholds: Thresholds,
    user: Annotated[User, Depends(require(Permission.FINANCIAL_READ))],
) -> CustomerFinancialSummaryOut:
    customer = _load_customer(db, customer_id)
    include_costs = has(user, Permission.FINANCIAL_COST_READ)
    activity = compute_customer_activity(
        db, customer, thresholds, include_financials=True, include_costs=include_costs
    )
    return presenters.financial_summary_out(activity, include_costs=include_costs)


@router.get("/{customer_id}/referrals", response_model=list[ReferralOut])
def list_referrals(
    customer_id: int,
    db: DbSession,
    thresholds: Thresholds,
    _user: Annotated[User, Depends(require(Permission.REFERRAL_READ))],
) -> list[ReferralOut]:
    from app.models import Referral

    customer = _load_customer(db, customer_id)
    rows = list(
        db.scalars(
            select(Referral).where(
                or_(
                    Referral.referrer_customer_id == customer.id,
                    Referral.referred_customer_id == customer.id,
                )
            )
        ).all()
    )
    return presenters.referral_list(db, rows, thresholds)


@router.post("/{customer_id}/referrals", response_model=ReferralOut, status_code=201)
def create_referral(
    customer_id: int,
    payload: ReferralCreate,
    db: DbSession,
    thresholds: Thresholds,
    user: Annotated[User, Depends(require(Permission.REFERRAL_WRITE))],
) -> ReferralOut:
    referrer = _load_customer(db, customer_id)
    referred = _load_customer(db, payload.referred_customer_id)
    referral = customer_service.add_referral(
        db, referrer=referrer, referred=referred, note=payload.note, actor=user
    )
    commit_with_retry(db)
    return presenters.referral_list(db, [referral], thresholds)[0]
