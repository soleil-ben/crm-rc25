"""Customer Account profile routes (fix pack 2; CA-PRF-01 … CA-PRF-04).

``GET  /api/v1/account/profile``                     read the approved values on file
``POST /api/v1/account/profile/direct``              preferred language, applied at once
``POST /api/v1/account/profile/proposals``           a name, phone or address change for review
``POST /api/v1/account/profile/proposals/withdraw``  withdraw the one pending change request
``POST /api/v1/account/consent/marketing``           grant or withdraw marketing consent

The shipment routes' order of operations, reused rather than restated: privacy headers,
the Customer Account session (with its CSRF check on every POST), the per-account rate
limit, then authorization through ``customer_account_link_policy`` -- an ``active``
identity with exactly one effective link to a live customer. A pending or unlinked account
gets the same 403 the shipment routes give.

**What a response may contain is FIELD_MATRIX §3.3 and nothing else.** The profile is
built field by field below; the "Never" list (§3.4) has no slot in any model this module
returns. The bodies are read raw, as ``routes.py`` reads them, so a malformed request is
answered with this surface's narrow error and never with FastAPI's input-echoing 422.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request, Response

from app.api.account.deps import (
    AccountClientKey,
    AccountDb,
    CurrentAccountSession,
    account_client_ip,
)
from app.api.account.routes import _BadRequest, _read_json
from app.api.account.shipments import (
    RATE_LIMIT_MESSAGE,
    _apply_headers,
    _authorized_customer,
    _limit_or_refuse,
)
from app.core.db import commit_with_retry
from app.core.enums import PreferredLanguage
from app.core.security import rate_limiter
from app.models import CustomerDataProposal
from app.schemas.account_profile import (
    AccountProfileResponse,
    MarketingChoiceResponse,
    MarketingHistoryEntry,
    MarketingOut,
    ProfileAddress,
    ProfileDetails,
    ProposalFieldView,
    ProposalSubmittedResponse,
    ProposalView,
)
from app.services import customer_account_profile_service as profile
from app.services import public_tracking_service
from app.services.errors import RateLimitedError, ValidationError

router = APIRouter(tags=["customer-account"])

#: Writes are rarer than reads and each one lands a row a person reviews; thirty an hour
#: is generous for a person and tight for a script filling the review queue.
PROFILE_WRITE_ATTEMPTS = 30
PROFILE_WRITE_WINDOW_SECONDS = 3600


def _limit_write(identity_public_id: str) -> None:
    allowed, retry_after = rate_limiter.check(
        f"account:profile_write:{identity_public_id}",
        PROFILE_WRITE_ATTEMPTS,
        PROFILE_WRITE_WINDOW_SECONDS,
    )
    if not allowed:
        raise RateLimitedError(RATE_LIMIT_MESSAGE, retry_after=retry_after)


def _proposal_view(proposal: CustomerDataProposal) -> ProposalView:
    return ProposalView(
        status=proposal.status,
        submitted_at=proposal.submitted_at,
        reviewed_at=proposal.reviewed_at,
        fields=[
            ProposalFieldView(
                field_key=row.field_key, proposed_value=row.proposed_value, applied=row.applied
            )
            for row in sorted(proposal.fields, key=lambda item: item.field_key)
        ],
    )


def _profile_response(db, identity, customer) -> AccountProfileResponse:
    values = profile.current_values(db, customer)
    address = profile.default_pickup_address(db, customer)
    marketing = profile.marketing_state(db, customer)
    return AccountProfileResponse(
        account_reference=identity.public_id,
        details=ProfileDetails(
            customer_reference=customer.public_id,
            legal_name=values["legal_name"],
            display_name=values["display_name"],
            email=customer.email_entered,
            phone=values["phone"],
            preferred_language=profile.account_language(identity, customer),
            pickup_address=(
                ProfileAddress(
                    contact_name=address.contact_name,
                    address_line1=address.address_line1,
                    address_line2=address.address_line2,
                    city=address.city,
                    province_state=address.province_state,
                    postal_code=address.postal_code,
                    country_code=address.country_code,
                    phone=address.phone_entered,
                    delivery_note=address.delivery_note,
                )
                if address is not None
                else None
            ),
        ),
        marketing=_marketing_out(marketing),
        marketing_history=[
            MarketingHistoryEntry(status=status, recorded_at=recorded_at)
            for status, recorded_at in profile.marketing_history(db, customer)
        ],
        proposals=[_proposal_view(item) for item in profile.own_profile_proposals(db, identity)],
        proposable_fields=sorted(profile.PROPOSAL_FIELDS),
        languages=[language.value for language in PreferredLanguage if language.value != "unknown"],
        timezone=public_tracking_service.display_timezone(db),
    )


def _marketing_out(state: profile.MarketingState) -> MarketingOut:
    return MarketingOut(
        status=state.status,
        changed_at=state.changed_at,
        delivery_blocked=state.delivery_blocked,
    )


def _object(payload: dict[str, Any], key: str) -> dict[str, Any]:
    value = payload.get(key)
    if not isinstance(value, dict):
        raise _BadRequest("That request could not be read.")
    if set(payload) - {key}:
        raise _BadRequest("That request could not be read.")
    return value


@router.get("/profile", response_model=AccountProfileResponse, summary="Your profile")
def read_profile(
    request: Request,
    response: Response,
    db: AccountDb,
    session: CurrentAccountSession,
    client_key: AccountClientKey,
) -> AccountProfileResponse:
    _apply_headers(response)
    identity, _ = session
    _limit_or_refuse(identity.public_id, "profile")
    customer = _authorized_customer(db, request, identity, "profile")
    result = _profile_response(db, identity, customer)
    commit_with_retry(db)
    return result


@router.post(
    "/profile/direct",
    response_model=AccountProfileResponse,
    summary="Change your preferred language",
)
async def update_direct(
    request: Request,
    response: Response,
    db: AccountDb,
    session: CurrentAccountSession,
    client_key: AccountClientKey,
) -> AccountProfileResponse:
    """FIELD_MATRIX §3.1. Applied at once, audited, no proposal (CA-PRF-01)."""
    _apply_headers(response)
    identity, _ = session
    _limit_write(identity.public_id)
    customer = _authorized_customer(db, request, identity, "profile")
    payload = await _read_json(request)
    profile.update_direct(
        db,
        identity=identity,
        customer=customer,
        submitted=payload,
        ip_address=account_client_ip(request),
    )
    commit_with_retry(db)
    return _profile_response(db, identity, customer)


@router.post(
    "/profile/proposals",
    response_model=ProposalSubmittedResponse,
    summary="Ask for a name, phone or address change",
)
async def submit_proposal(
    request: Request,
    response: Response,
    db: AccountDb,
    session: CurrentAccountSession,
    client_key: AccountClientKey,
) -> ProposalSubmittedResponse:
    """FIELD_MATRIX §3.2. Nothing on file changes until a staff member approves (CA-PRF-02)."""
    _apply_headers(response)
    identity, _ = session
    _limit_write(identity.public_id)
    customer = _authorized_customer(db, request, identity, "profile")
    fields = _object(await _read_json(request), "fields")
    proposal = profile.submit_proposal(
        db,
        identity=identity,
        customer=customer,
        submitted=fields,
        ip_address=account_client_ip(request),
    )
    commit_with_retry(db)
    return ProposalSubmittedResponse(
        message=(
            "Thank you. A member of staff will review this change. Your details stay as "
            "they are until then."
        ),
        proposal=_proposal_view(proposal),
    )


@router.post(
    "/profile/proposals/withdraw",
    response_model=AccountProfileResponse,
    summary="Withdraw your pending change request",
)
def withdraw_proposal(
    request: Request,
    response: Response,
    db: AccountDb,
    session: CurrentAccountSession,
    client_key: AccountClientKey,
) -> AccountProfileResponse:
    _apply_headers(response)
    identity, _ = session
    _limit_write(identity.public_id)
    customer = _authorized_customer(db, request, identity, "profile")
    profile.withdraw_proposal(db, identity=identity, ip_address=account_client_ip(request))
    commit_with_retry(db)
    return _profile_response(db, identity, customer)


@router.post(
    "/consent/marketing",
    response_model=MarketingChoiceResponse,
    summary="Grant or withdraw marketing consent",
)
async def marketing_consent(
    request: Request,
    response: Response,
    db: AccountDb,
    session: CurrentAccountSession,
    client_key: AccountClientKey,
) -> MarketingChoiceResponse:
    """FIELD_MATRIX §4. Explicit, append-only, audited; a suppression is never named.

    A grant that cannot be delivered is flagged with ``delivery_blocked`` and nothing else.
    """
    _apply_headers(response)
    identity, _ = session
    _limit_write(identity.public_id)
    customer = _authorized_customer(db, request, identity, "consent")
    payload = await _read_json(request)
    granted = payload.get("granted")
    if set(payload) != {"granted"} or not isinstance(granted, bool):
        raise ValidationError("Choose to give or withdraw consent.", field="granted")
    state = profile.record_marketing_choice(
        db,
        identity=identity,
        customer=customer,
        granted=granted,
        ip_address=account_client_ip(request),
    )
    commit_with_retry(db)
    return MarketingChoiceResponse(marketing=_marketing_out(state))
