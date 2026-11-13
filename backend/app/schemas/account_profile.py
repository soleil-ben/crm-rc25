"""Customer Account profile responses (fix pack 2; FIELD_MATRIX.md §3).

Every model here is built **field by field** in the route, never validated from an ORM
object (`from_attributes=False`, `extra="forbid"`, inherited from ``AccountModel``). A
field appears in a profile response because a line in `app/api/account/profile.py` put it
there. Nothing from FIELD_MATRIX §3.4 has a slot: no tag, note, interaction, owner,
lifecycle, financial value, match key, suppression, archive or merge state, demo flag or
integer id.
"""

from __future__ import annotations

from datetime import datetime

from app.schemas.account import AccountModel


class ProfileAddress(AccountModel):
    contact_name: str | None
    address_line1: str | None
    address_line2: str | None
    city: str | None
    province_state: str | None
    postal_code: str | None
    country_code: str | None
    phone: str | None
    delivery_note: str | None


class ProfileDetails(AccountModel):
    """The approved values on file (§3.3). Read-only on this surface."""

    customer_reference: str
    legal_name: str | None
    display_name: str | None
    email: str | None
    phone: str | None
    preferred_language: str
    pickup_address: ProfileAddress | None


class MarketingOut(AccountModel):
    #: ``granted``, ``withdrawn`` or ``not_given``. Never anything about a suppression.
    status: str
    changed_at: datetime | None
    #: Opted in, but marketing email cannot be sent to this address right now. A boolean
    #: and nothing more: no reason, no source, no date (UAT round 3).
    delivery_blocked: bool


class MarketingHistoryEntry(AccountModel):
    status: str
    recorded_at: datetime


class ProposalFieldView(AccountModel):
    field_key: str
    proposed_value: str | None
    applied: bool


class ProposalView(AccountModel):
    """One of the customer's own change requests. No id: there is at most one pending."""

    status: str
    submitted_at: datetime
    reviewed_at: datetime | None
    fields: list[ProposalFieldView]


class AccountProfileResponse(AccountModel):
    account_reference: str
    details: ProfileDetails
    marketing: MarketingOut
    marketing_history: list[MarketingHistoryEntry]
    proposals: list[ProposalView]
    #: The proposable field keys, so the form names exactly what the server accepts.
    proposable_fields: list[str]
    #: The languages the direct setting accepts.
    languages: list[str]
    timezone: str


class MarketingChoiceResponse(AccountModel):
    marketing: MarketingOut


class ProposalSubmittedResponse(AccountModel):
    message: str
    proposal: ProposalView
