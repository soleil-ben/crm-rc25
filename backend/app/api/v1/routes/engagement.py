"""Address book, interactions, consent, service issues, and tags."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, select

from app.api import presenters
from app.api.deps import DbSession, client_ip, require
from app.core.db import commit_with_retry
from app.core.enums import ServiceIssueStatus
from app.core.normalization import normalize_email, normalize_phone
from app.core.permissions import Permission
from app.core.time_utils import utcnow
from app.models import (
    CustomerAddress,
    Interaction,
    ServiceIssue,
    Tag,
    User,
)
from app.schemas.common import OkResponse, Page
from app.schemas.customer import AddressCreate, AddressOut, AddressUpdate, TagCreate, TagOut
from app.schemas.engagement import (
    ConsentEventCreate,
    ConsentOverview,
    InteractionCreate,
    InteractionOut,
    ServiceIssueCreate,
    ServiceIssueOut,
    SuppressionCreateRequest,
    SuppressionReleaseRequest,
)
from app.services import (
    audit_service,
    consent_service,
    customer_address_service,
    customer_service,
)
from app.services.errors import NotFoundError, ValidationError

router = APIRouter(tags=["engagement"])


# --- Address book ---------------------------------------------------------


@router.get("/customers/{customer_id}/addresses", response_model=list[AddressOut])
def list_addresses(
    customer_id: int,
    db: DbSession,
    _user: Annotated[User, Depends(require(Permission.ADDRESS_READ))],
    include_archived: bool = False,
) -> list[AddressOut]:
    customer = customer_service.get_customer(db, customer_id)
    conditions = [CustomerAddress.customer_id == customer.id]
    if not include_archived:
        conditions.append(CustomerAddress.is_archived.is_(False))
    rows = db.scalars(
        select(CustomerAddress)
        .where(*conditions)
        .order_by(CustomerAddress.label.asc(), CustomerAddress.id.asc())
    ).all()
    return [presenters.address_out(row) for row in rows]


@router.post("/customers/{customer_id}/addresses", response_model=AddressOut, status_code=201)
def create_address(
    customer_id: int,
    payload: AddressCreate,
    request: Request,
    db: DbSession,
    user: Annotated[User, Depends(require(Permission.ADDRESS_WRITE))],
) -> AddressOut:
    customer = customer_service.get_customer(db, customer_id)
    data = payload.model_dump()
    address = customer_address_service.create_address(
        db,
        customer,
        {key: value for key, value in data.items() if key not in {"contact_name", "role"}},
        contact_name=payload.contact_name,
        role=payload.role.value if hasattr(payload.role, "value") else payload.role,
    )
    audit_service.record_audit(
        db,
        action="address.create",
        entity_type="customer_address",
        entity_id=address.id,
        summary=f"Added address book entry for {customer.public_id}",
        actor=user,
        ip_address=client_ip(request),
    )
    commit_with_retry(db)
    return presenters.address_out(address)


@router.patch("/addresses/{address_id}", response_model=AddressOut)
def update_address(
    address_id: int,
    payload: AddressUpdate,
    request: Request,
    db: DbSession,
    user: Annotated[User, Depends(require(Permission.ADDRESS_WRITE))],
) -> AddressOut:
    """Editing an address book entry never rewrites a confirmed shipment snapshot (AC-5).

    Shipment address snapshots are separate columns written at confirmation time.
    """
    address = db.get(CustomerAddress, address_id)
    if address is None:
        raise NotFoundError("Address not found.")
    customer_address_service.apply_address_payload(address, payload.model_dump(exclude_unset=True))
    customer_address_service.enforce_single_default(db, address)
    audit_service.record_audit(
        db,
        action="address.update",
        entity_type="customer_address",
        entity_id=address.id,
        summary=f"Updated address book entry {address.id}",
        actor=user,
        ip_address=client_ip(request),
    )
    commit_with_retry(db)
    return presenters.address_out(address)


@router.delete("/addresses/{address_id}", response_model=OkResponse)
def archive_address(
    address_id: int,
    request: Request,
    db: DbSession,
    user: Annotated[User, Depends(require(Permission.ADDRESS_WRITE))],
) -> OkResponse:
    address = db.get(CustomerAddress, address_id)
    if address is None:
        raise NotFoundError("Address not found.")
    address.is_archived = True
    audit_service.record_audit(
        db,
        action="address.archive",
        entity_type="customer_address",
        entity_id=address.id,
        summary=f"Archived address book entry {address.id}",
        actor=user,
        ip_address=client_ip(request),
    )
    commit_with_retry(db)
    return OkResponse(message="Address archived. Existing shipment snapshots are unchanged.")


# --- Interactions ---------------------------------------------------------


@router.get("/customers/{customer_id}/interactions", response_model=Page[InteractionOut])
def list_interactions(
    customer_id: int,
    db: DbSession,
    _user: Annotated[User, Depends(require(Permission.INTERACTION_READ))],
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> Page[InteractionOut]:
    customer = customer_service.get_customer(db, customer_id)
    total = int(
        db.scalar(select(func.count(Interaction.id)).where(Interaction.customer_id == customer.id))
        or 0
    )
    rows = list(
        db.scalars(
            select(Interaction)
            .where(Interaction.customer_id == customer.id)
            .order_by(Interaction.occurred_at.desc(), Interaction.id.desc())
            .limit(limit)
            .offset(offset)
        ).all()
    )
    return Page[InteractionOut](
        items=presenters.interaction_list(db, rows), total=total, limit=limit, offset=offset
    )


@router.post(
    "/customers/{customer_id}/interactions", response_model=InteractionOut, status_code=201
)
def create_interaction(
    customer_id: int,
    payload: InteractionCreate,
    db: DbSession,
    user: Annotated[User, Depends(require(Permission.INTERACTION_WRITE))],
) -> InteractionOut:
    """CRM notes are internal. Public shipment updates are a separate Phase 3 concept."""
    customer = customer_service.get_customer(db, customer_id)
    interaction = Interaction(
        customer_id=customer.id,
        shipment_id=payload.shipment_id,
        occurred_at=payload.occurred_at or utcnow(),
        channel=payload.channel.value,
        direction=payload.direction.value,
        subject=payload.subject,
        body=payload.body,
        outcome=payload.outcome,
        author_user_id=user.id,
    )
    db.add(interaction)
    commit_with_retry(db)
    return presenters.interaction_out(db, interaction)


# --- Consent --------------------------------------------------------------


@router.get("/customers/{customer_id}/consent", response_model=ConsentOverview)
def get_consent(
    customer_id: int,
    db: DbSession,
    _user: Annotated[User, Depends(require(Permission.CONSENT_READ))],
) -> ConsentOverview:
    customer = customer_service.get_customer(db, customer_id)
    states = consent_service.all_states(db, customer)
    events = consent_service.history(db, customer)
    return ConsentOverview(
        states=[presenters.consent_state_out(state) for state in states],
        history=presenters.consent_event_list(db, events),
        do_not_contact=customer.do_not_contact,
    )


@router.post("/customers/{customer_id}/consent", response_model=ConsentOverview, status_code=201)
def record_consent(
    customer_id: int,
    payload: ConsentEventCreate,
    request: Request,
    db: DbSession,
    user: Annotated[User, Depends(require(Permission.CONSENT_WRITE))],
) -> ConsentOverview:
    customer = customer_service.get_customer(db, customer_id)
    consent_service.record_consent_event(
        db,
        customer,
        channel=payload.channel.value,
        status=payload.status.value,
        basis=payload.basis.value,
        address_value=payload.address_value,
        obtained_at=payload.obtained_at,
        expires_at=payload.expires_at,
        source=payload.source,
        evidence_reference=payload.evidence_reference,
        note=payload.note,
        actor=user,
        ip_address=client_ip(request),
    )
    commit_with_retry(db)
    return get_consent(customer_id, db, user)


@router.post(
    "/customers/{customer_id}/consent/suppressions",
    response_model=ConsentOverview,
    status_code=201,
)
def suppress_customer_address(
    customer_id: int,
    payload: SuppressionCreateRequest,
    request: Request,
    db: DbSession,
    user: Annotated[User, Depends(require(Permission.CONSENT_READ, Permission.SUPPRESSION_ADD))],
) -> ConsentOverview:
    """Suppress the customer's address on a channel, with evidence and a reason (UAT round 4).

    Marketing and Admin hold ``suppression:add``. The consent history gains a
    ``suppressed`` event, the global suppression is written, and the audit log names who
    did it. A customer can neither see nor lift it (FIELD_MATRIX §4).
    """
    customer = customer_service.get_customer(db, customer_id)
    consent_service.suppress_address(
        db,
        customer,
        channel=payload.channel.value,
        evidence_reference=payload.evidence_reference,
        reason=payload.reason,
        actor=user,
        ip_address=client_ip(request),
    )
    commit_with_retry(db)
    return get_consent(customer_id, db, user)


@router.post("/consent/suppressions/release", response_model=OkResponse)
def release_suppression(
    payload: SuppressionReleaseRequest,
    request: Request,
    db: DbSession,
    user: Annotated[User, Depends(require(Permission.SUPPRESSION_RELEASE))],
) -> OkResponse:
    """Releasing a suppression is an explicit, audited admin action (CRM.md section 11)."""
    channel = payload.channel.value
    if channel == "email":
        _, normalized = normalize_email(payload.address_value)
    else:
        from app.core.normalization import phone_match_key

        entered, e164, _ = normalize_phone(payload.address_value, None)
        normalized = phone_match_key(entered, e164)
    if not normalized:
        raise ValidationError("That address could not be normalized.", field="address_value")
    consent_service.release_suppression(
        db,
        channel=channel,
        address_value=normalized,
        reason=payload.reason,
        actor=user,
        ip_address=client_ip(request),
    )
    commit_with_retry(db)
    return OkResponse(message="Suppression released and recorded in the audit log.")


# --- Service issues -------------------------------------------------------


@router.get("/customers/{customer_id}/service-issues", response_model=list[ServiceIssueOut])
def list_service_issues(
    customer_id: int,
    db: DbSession,
    _user: Annotated[User, Depends(require(Permission.CUSTOMER_READ))],
) -> list[ServiceIssueOut]:
    customer = customer_service.get_customer(db, customer_id)
    rows = db.scalars(
        select(ServiceIssue)
        .where(ServiceIssue.customer_id == customer.id)
        .order_by(ServiceIssue.opened_at.desc())
    ).all()
    return [ServiceIssueOut.model_validate(row) for row in rows]


@router.post(
    "/customers/{customer_id}/service-issues", response_model=ServiceIssueOut, status_code=201
)
def create_service_issue(
    customer_id: int,
    payload: ServiceIssueCreate,
    db: DbSession,
    user: Annotated[User, Depends(require(Permission.INTERACTION_WRITE))],
) -> ServiceIssueOut:
    customer = customer_service.get_customer(db, customer_id)
    issue = ServiceIssue(
        customer_id=customer.id,
        shipment_id=payload.shipment_id,
        title=payload.title,
        detail=payload.detail,
        status=ServiceIssueStatus.OPEN,
        opened_at=utcnow(),
        opened_by_user_id=user.id,
    )
    db.add(issue)
    commit_with_retry(db)
    return ServiceIssueOut.model_validate(issue)


@router.post("/service-issues/{issue_id}/resolve", response_model=ServiceIssueOut)
def resolve_service_issue(
    issue_id: int,
    db: DbSession,
    user: Annotated[User, Depends(require(Permission.INTERACTION_WRITE))],
) -> ServiceIssueOut:
    issue = db.get(ServiceIssue, issue_id)
    if issue is None:
        raise NotFoundError("Service issue not found.")
    issue.status = ServiceIssueStatus.RESOLVED
    issue.resolved_at = utcnow()
    audit_service.record_audit(
        db,
        action="service_issue.resolve",
        entity_type="service_issue",
        entity_id=issue.id,
        summary=f"Resolved service issue {issue.id}",
        actor=user,
    )
    commit_with_retry(db)
    return ServiceIssueOut.model_validate(issue)


# --- Tags -----------------------------------------------------------------


@router.get("/tags", response_model=list[TagOut])
def list_tags(
    db: DbSession, _user: Annotated[User, Depends(require(Permission.TAG_READ))]
) -> list[TagOut]:
    rows = db.scalars(select(Tag).order_by(Tag.name.asc())).all()
    return [presenters.tag_out(tag) for tag in rows]


@router.post("/tags", response_model=TagOut, status_code=201)
def create_tag(
    payload: TagCreate,
    db: DbSession,
    user: Annotated[User, Depends(require(Permission.TAG_WRITE))],
) -> TagOut:
    slug = payload.slug.strip().lower().replace(" ", "-")
    if db.scalar(select(Tag).where(Tag.slug == slug)) is not None:
        raise ValidationError("A tag with that slug already exists.", field="slug")
    tag = Tag(
        slug=slug,
        name=payload.name.strip(),
        description=payload.description,
        color_token=payload.color_token,
        created_by_user_id=user.id,
    )
    db.add(tag)
    commit_with_retry(db)
    return presenters.tag_out(tag)
