"""Staff-facing tariff and exchange-rate schemas (Phase 13A).

**Everything here is vendor cost data and is internal.** These models are returned only by
routes on the staff router behind ``tariff:read``; nothing in this module is imported by
the public or account routers, and ``tests/test_tariff_import.py`` asserts that no tariff
field name ever appears in a public or Customer Account schema.

No field here holds a person's name or telephone, a credential, or a response body.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class TariffModel(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")


class TariffVersionOut(TariffModel):
    id: int
    public_id: str
    vendor_key: str
    label: str
    source_file_name: str | None
    source_sha256: str
    effective_from: date
    effective_to: date | None
    status: str
    imported_at: datetime
    activated_at: datetime | None
    dim_divisor_default: int
    fixed_fx_vnd_per_cad: Decimal | None
    cost_currency: str
    #: The approver's decision (Phase 13H): ``approved`` | ``rejected`` | None. A rejected
    #: version stays ``draft`` and can never be activated; the tariff browser says so (14).
    review_decision: str | None = None


class TariffVersionListOut(TariffModel):
    items: list[TariffVersionOut]
    total: int


class TariffVersionDetailOut(TariffVersionOut):
    counts: dict[str, int]
    report: dict


class TariffImportWarningOut(TariffModel):
    """One importer warning (an anomaly in the stored import report). English, as written."""

    code: str
    message: str
    sheet: str | None = None
    cell: str | None = None


class TariffConfirmedPriceStepOut(TariffModel):
    """A price drop the owner confirmed as the vendor's intended rate (DEC-0222): shown,
    never counted as a warning."""

    sheet: str
    cell: str
    product_code: str | None = None
    zone: int | None = None
    label: str | None = None
    reference: str | None = None
    message: str | None = None
    price_vnd: str | None = None


class TariffImportWarningsOut(TariffModel):
    """RC-20: a version's import warnings, one page of them, with the confirmed steps apart."""

    version_id: int
    version_public_id: str
    count: int
    counts_by_code: dict[str, int]
    limit: int
    offset: int
    items: list[TariffImportWarningOut]
    confirmed_price_steps: list[TariffConfirmedPriceStepOut]


class TariffProductOut(TariffModel):
    id: int
    code: str
    origin: str
    mode: str
    last_mile: str
    dim_divisor: int
    per_kg_from_kg: Decimal | None
    piece_min_weight_kg: Decimal | None
    piece_min_fee_vnd: Decimal | None
    piece_min_applies_above_kg: Decimal | None
    min_chargeable_kg: Decimal | None
    customs_surcharges_waived: bool
    transit_text: str | None


class TariffRateBracketOut(TariffModel):
    kind: str
    zone: int
    label: str
    weight_from_kg: Decimal | None
    weight_to_kg: Decimal | None
    price_vnd: Decimal
    source_sheet: str
    source_cell: str


class TariffProductDetailOut(TariffProductOut):
    brackets: list[TariffRateBracketOut]


class TariffSurchargeTierOut(TariffModel):
    weight_from_kg: Decimal
    weight_to_kg: Decimal | None
    price_vnd: Decimal


class TariffSurchargeRuleOut(TariffModel):
    id: int
    section: str
    section_label: str
    stt: int
    name: str
    raw_price_text: str
    raw_note: str | None
    basis: str
    scope: str
    pricing_status: str
    unit_price_vnd: Decimal | None
    per_unit_price_vnd: Decimal | None
    per_unit_label: str | None
    min_charge_kg: Decimal | None
    max_kg_per_shipment: Decimal | None
    applies_to_canada: bool
    semantics_source: str
    semantics_note: str | None
    source_sheet: str
    source_row: int
    tiers: list[TariffSurchargeTierOut]
    #: Above the top tier: ``top`` (the top tier's price, OD-57) or ``manual`` (the
    #: vendor's quoted price, OD-59). Tells the fee picker when to ask for a price.
    above_top_tier: str = "manual"
    #: The confirmed method's allocation class (``surcharge_allocation_classes``): ``PARCEL``
    #: = Kango charges once per master piece (DEC-0276); ``WHOLE_MASTER`` / ``WHOLE_PACKAGE``
    #: = once per shipment / per piece. None when the row has no class.
    allocation_class: str | None = None


class TariffSurchargeRuleListOut(TariffModel):
    items: list[TariffSurchargeRuleOut]
    total: int


class TariffAccessorialOut(TariffModel):
    key: str
    description: str
    amount: Decimal | None
    currency: str
    basis: str
    applies_to_modes: str
    source_sheet: str
    source_cell: str


class TariffBeyondRateOut(TariffModel):
    beyond_code: str
    status: str
    base_cad: Decimal | None
    per_lb_cad: Decimal | None


class FxSnapshotOut(TariffModel):
    id: int
    bank: str
    currency: str
    cash_buy_vnd: Decimal
    transfer_buy_vnd: Decimal | None
    sell_vnd: Decimal
    bank_published_raw: str | None
    bank_published_at: datetime | None
    retrieved_at: datetime
    source_url: str | None = None
    #: A fixed demo reading (``app.seed_pricing``), never a bank reading.
    is_demo: bool = False


class FxAttemptOut(TariffModel):
    id: int
    attempted_at: datetime
    outcome: str
    error_summary: str | None
    worker_name: str


class FxLatestOut(TariffModel):
    """What the pricing engine will be told about the exchange rate right now."""

    freshness: str
    stale_after_minutes: int
    snapshot: FxSnapshotOut | None
    last_attempt: FxAttemptOut | None


class FxHistoryOut(TariffModel):
    snapshots: list[FxSnapshotOut]
    attempts: list[FxAttemptOut]


# --- Vendor rate-email intake (Phase 13H, OD-76) -------------------------------------------
#
# An intake row carries provenance only: the sender's address and the subject are the only
# personal data, and no email body or workbook content is ever returned.


class TariffIntakeOut(TariffModel):
    id: int
    message_id: str
    sender: str | None
    subject: str | None
    received_at: datetime | None
    source: str
    attachment_name: str | None
    attachment_sha256: str | None
    status: str
    tariff_version_id: int | None
    tariff_version_public_id: str | None = None
    tariff_version_status: str | None = None
    error: str | None
    warning: str | None = None
    reviewed_at: datetime | None
    review_note: str | None
    created_at: datetime


class TariffIntakeUploadOut(TariffIntakeOut):
    #: False when this email had been received before (same Message-ID): nothing new happened.
    created: bool


class TariffIntakeListOut(TariffModel):
    items: list[TariffIntakeOut]
    total: int
    #: Whether the signed-in user may approve, reject and release. The server re-checks.
    viewer_is_approver: bool


class TariffPendingCountOut(TariffModel):
    """Phase 15: what waits for a tariff approver -- draft versions with no decision yet and
    rate emails held because their sender is not on the allowed list. Counts only."""

    #: Whether the signed-in user is a designated approver. The badge is shown only to them.
    viewer_is_approver: bool
    drafts_awaiting: int
    held_senders: int
    total: int


class TariffIntakeSettingsOut(TariffModel):
    mailbox_address: str
    approver_emails: list[str]
    allowed_sender_domains: list[str]
    updated_at: datetime | None
    #: True until an administrator saves (the owner's defaults, OD-76).
    is_default: bool


class TariffIntakeSettingsUpdate(TariffModel):
    approver_emails: list[str] | None = None
    allowed_sender_domains: list[str] | None = None


class TariffRejectIn(TariffModel):
    reason: str


class TariffVersionDiffOut(TariffModel):
    version_id: int
    version_public_id: str
    version_status: str
    against_version_id: int | None
    against_version_public_id: str | None
    mode: str
    products_added: list[dict]
    products_removed: list[dict]
    summary: dict[str, int]
    truncated: bool
    max_entries: int
    counts: dict
    brackets_changed: list[dict]
    brackets_added: list[dict]
    brackets_removed: list[dict]
    surcharges_changed: list[dict]
    surcharges_added: list[dict]
    surcharges_removed: list[dict]
