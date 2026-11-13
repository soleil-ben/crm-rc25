"""Draft invoices: prepared on acceptance, edited by staff, sent as the real invoice (OD 9a).

Owner decision 9a (Louis Tong, 2026-10-21): accepting a quote creates its invoice
automatically **as a draft**. The rules, each a test:

* **Created in the acceptance's own unit** (``quote_offer_service.accept``): the payer (the
  recorded payer, else the customer), the accepted version's revenue lines with any wording
  that names a vendor replaced by a neutral label, the payer's name and billing address,
  GST/HST 0 %. Audited ``invoice.draft_created`` with the customer's account as the actor.
  Not created when the shipment already has a live invoice; an older live draft (an earlier
  acceptance) is discarded first. **No ``INV-`` number** exists until Send.
* **Edited only while ``draft``**: bill-to name and address, the customer's reference or PO,
  notes, GST/HST (0, 5 or 13 %), and the lines (description and amount). A total different
  from the accepted quote needs a reason. Each save names the revision it read; a stale one
  is refused (409) and nothing is written. Audited ``invoice.draft_edited`` with a field diff.
* **Send** names the revision too: it issues the real invoice with ``finance_service``'s
  numbering, revenue month and tax from the saved draft, marks the draft ``issued`` and --
  after commit, outside any retried unit -- emails the customer through the account email
  seam (``invoice.sent.vi``/``.en``: number, total, due date; no vendor names). The email
  outcome is recorded on the draft; a failure is recorded, never raised.
* **A newer version** (independent review M1): when a quote version newer than the draft's is
  finalised, Send is refused (409 ``quote_superseded``) unless the request acknowledges it
  (``acknowledge_superseded``: send at the accepted price). Otherwise staff **withdraw** the
  draft (financial write, a reason, audited ``invoice.draft_discarded``) and issue from the
  latest version the normal way.
* **No vendor name** (owner, OD-84): a save whose lines, notes, bill-to or PO name a vendor is
  refused (422, the field named); the PDF and documents screen free text on output too.
* **Download** (the PDF) also names the revision, so what is printed is what was saved.
* An expired quote's draft is discarded (``quote_expiry_service``); an issued invoice keeps
  the existing void and reissue rules.

**GST/HST** (owner answer of 2026-10-22, Louis Tong; DEC-0223). Rates are usually all-in, so
every draft created from now on starts at GST/HST **13 %, included in the price**: the tax is
backed out of the lines' total (``tax = round_half_up(total * rate / (100 + rate))``,
``subtotal = total - tax``; now line by line, DEC-0235 below). Staff may change the rate
(0, 5, 13) and the mode (``included`` or ``added`` on top). The mode and the staff
**confirmation** live in ``invoice_draft_tax`` (the rate's source of truth stays
``invoice_drafts.tax_rate_percent``, mirrored there):

* a **Save** must carry ``tax_confirmed: true`` (the box "I have checked the GST/HST on this
  invoice"), else 422 ``tax_unconfirmed``; the confirmation is recorded for the revision the
  save produces (a save with nothing else changed only records the confirmation). A save
  that changes the lines, the rate or the mode must also echo what the screen showed --
  ``confirmed_total_cad``, ``confirmed_tax_mode``, ``confirmed_tax_rate_percent`` -- and is
  refused (422 ``tax_unconfirmed``) unless they equal the server's figures for that save, so
  a tick never confirms figures nobody saw (review, 2026-10-22). Echoed figures are checked
  on any save that sends them;
* **Send** is refused (422 ``tax_unconfirmed``) unless the saved revision was confirmed;
  any change (rate, mode, a line, any field) makes a new revision, which is unconfirmed until
  a save confirms it;
* a draft with no tax row (created before this) reads as mode ``added`` at its saved rate,
  unconfirmed.

Audited ``invoice.draft_tax_confirmed``; the edit diff names ``tax_mode`` and
``tax_rate_percent`` when they change. The manual Issue invoice path is unchanged (tax added).

**GST/HST by route** (owner Ben, 2026-10-23; DEC-0227) replaces the 13 % stand-in: a new draft
auto-fills its rate and mode from the shipment's route (``tax_rate_service.route_tax``):
international (one end outside Canada) 0 %; domestic, included in the price, at the
destination province's rate from ``tax_rates``. What it was filled from is kept in
``invoice_draft_tax_route``. When a domestic shipment's province is unknown the draft has **no
rate** (stand-in): the view shows none, a save must choose one (422 ``tax_rate_required``)
and, until then, the tax is unconfirmed, so Send and Download are refused (422
``tax_unconfirmed``). The allowed rates are 0, 5, 13, 14, 15 and whatever ``tax_rates`` holds.
**Download** (the PDF) is refused like Send until the saved revision's GST/HST is confirmed
(owner, 2026-10-23; DEC-0229).

**Per line** (owner Ben, 2026-10-24; DEC-0235, the Solaris Invoicing desk rules): the tax is
worked out line by line by ``invoice_tax_math`` -- included: each line's net backed out of its
all-in amount (nudged by a cent so net + tax is the amount exactly); added: the tax on each
line's amount -- and the draft's subtotal, tax and total are the sums. The view carries the
per-line breakdown (``tax_lines``) and the summary rows (``tax_rows``) exactly as the issued
invoice and the PDF will show them; the confirmation echo and the audit use the same figures.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.enums import ConsentChannel
from app.core.time_utils import utcnow
from app.models import (
    Customer,
    CustomerAddress,
    CustomerIdentity,
    CustomerInvoice,
    InvoiceDraft,
    InvoiceDraftTax,
    InvoiceDraftTaxRoute,
    QuoteOffer,
    QuoteVersion,
    Shipment,
    User,
)
from app.services import audit_service, customer_labels, tax_rate_service
from app.services import invoice_tax_math as tax_math
from app.services.errors import ConflictError, NotFoundError, ValidationError

logger = logging.getLogger("solaris.invoice_drafts")

CENT = Decimal("0.01")
#: The rates every draft may carry; ``allowed_tax_rates`` adds whatever ``tax_rates`` holds
#: (owner, 2026-10-23).
TAX_RATES = tax_rate_service.BASE_ALLOWED_RATES
#: included: the tax is inside the line amounts (backed out); added: charged on top.
TAX_MODES = ("included", "added")
#: A new draft's mode (owner, 2026-10-22 and 2026-10-23): included in the price. Its rate comes
#: from the shipment's route (``tax_rate_service.route_tax``).
DEFAULT_TAX_MODE = "included"
#: ``invoice_drafts.tax_rate_percent`` is not nullable: a draft whose rate staff must still
#: choose stores this placeholder, which is never shown, confirmed or sent.
UNSET_RATE_PLACEHOLDER = 0
#: A draft created before 2026-10-22 has no tax row: tax added on top, as it was.
LEGACY_TAX_MODE = "added"
MAX_LINES = 50
LIMITS = {
    "bill_to_name": 200,
    "bill_to_address": 1000,
    "customer_reference": 120,
    "notes": 2000,
    "total_change_reason": 400,
}
EDITABLE = (
    "bill_to_name",
    "bill_to_address",
    "customer_reference",
    "notes",
    "tax_rate_percent",
    "tax_mode",
    "tax_confirmed",
    "confirmed_total_cad",
    "confirmed_tax_mode",
    "confirmed_tax_rate_percent",
    "lines",
    "total_change_reason",
)


def template_key(language: str) -> str:
    return f"invoice.sent.{'en' if language == 'en' else 'vi'}"


# --- Reading -------------------------------------------------------------------------------------


def get(db: Session, draft_id: int) -> InvoiceDraft:
    row = db.get(InvoiceDraft, draft_id)
    if row is None:
        raise NotFoundError("That draft invoice does not exist.")
    return row


def live_for_shipment(db: Session, shipment_id: int) -> InvoiceDraft | None:
    return db.scalar(
        select(InvoiceDraft).where(
            InvoiceDraft.shipment_id == shipment_id, InvoiceDraft.status == "draft"
        )
    )


def latest_for_shipment(db: Session, shipment_id: int) -> InvoiceDraft | None:
    return db.scalar(
        select(InvoiceDraft)
        .where(InvoiceDraft.shipment_id == shipment_id)
        .order_by(InvoiceDraft.id.desc())
        .limit(1)
    )


def superseding_version(db: Session, draft: InvoiceDraft) -> QuoteVersion | None:
    """The newest finalised quote version newer than the draft's, or None."""
    own = db.get(QuoteVersion, draft.quote_version_id)
    if own is None:
        return None
    from app.services import quote_deletion_service  # noqa: PLC0415

    return db.scalar(
        select(QuoteVersion)
        .where(
            QuoteVersion.shipment_id == draft.shipment_id,
            QuoteVersion.status == "finalized",
            QuoteVersion.version > own.version,
            # RC-UAT-21 Phase D: a soft-deleted version never supersedes a draft.
            QuoteVersion.id.not_in(quote_deletion_service.open_deletions_subquery()),
        )
        .order_by(QuoteVersion.version.desc())
        .limit(1)
    )


def lines_of(draft: InvoiceDraft) -> list[dict[str, str]]:
    return json.loads(draft.lines_json or "[]")


def subtotal_of(lines: list[dict[str, str]]) -> Decimal:
    return sum((Decimal(line["amount_cad"]) for line in lines), Decimal(0))


def tax_of(subtotal: Decimal, rate: int) -> Decimal:
    return (subtotal * Decimal(rate) / Decimal(100)).quantize(CENT, rounding=ROUND_HALF_UP)


def included_tax_of(total: Decimal, rate: int) -> Decimal:
    """The tax inside an all-in ``total`` by the whole-total rule of DEC-0223
    (``round_half_up(total * rate / (100 + rate))``). Superseded by the per-line rule
    (DEC-0235): nothing new is computed with it; invoices issued before keep their figures."""
    return (Decimal(total) * Decimal(rate) / Decimal(100 + rate)).quantize(
        CENT, rounding=ROUND_HALF_UP
    )


def _amounts(lines: Any) -> list[Decimal]:
    if isinstance(lines, list | tuple):
        return [
            Decimal(str(line["amount_cad"] if isinstance(line, dict) else line)) for line in lines
        ]
    return [Decimal(lines)]


def breakdown(lines: Any, rate: int, mode: str, *, label: str | None = None) -> tax_math.Breakdown:
    """The per-line GST/HST of draft lines (DEC-0235): a draft line has no quantity (qty 1)."""
    return tax_math.breakdown(_amounts(lines), rate, mode, label=label)


def totals(lines: Any, rate: int, mode: str) -> tuple[Decimal, Decimal, Decimal]:
    """``(subtotal, tax, total)`` of the draft ``lines`` (line dicts or amounts; a single
    amount reads as one line) at ``rate`` in ``mode``, line by line (DEC-0235).

    included: the lines are all-in; each line's tax is backed out and the total is the lines'
    sum. added: the lines are before tax; each line's tax is charged on top.
    """
    return breakdown(lines, rate, mode).totals


def tax_row(db: Session, draft: InvoiceDraft) -> InvoiceDraftTax | None:
    return db.scalar(select(InvoiceDraftTax).where(InvoiceDraftTax.draft_id == draft.id))


def tax_mode_of(db: Session, draft: InvoiceDraft) -> str:
    row = tax_row(db, draft)
    return row.mode if row is not None else LEGACY_TAX_MODE


def tax_confirmed(db: Session, draft: InvoiceDraft) -> bool:
    """Whether staff confirmed the GST/HST of exactly the saved revision (and chose a rate)."""
    row = tax_row(db, draft)
    return (
        row is not None
        and row.confirmed_revision == draft.revision
        and not rate_required(db, draft)
    )


def route_row(db: Session, draft: InvoiceDraft) -> InvoiceDraftTaxRoute | None:
    return db.scalar(select(InvoiceDraftTaxRoute).where(InvoiceDraftTaxRoute.draft_id == draft.id))


def rate_required(db: Session, draft: InvoiceDraft) -> bool:
    """True while a domestic draft with an unknown province has no rate chosen (DEC-0227)."""
    row = route_row(db, draft)
    return row is not None and row.rate_required and row.rate_chosen_at is None


def allowed_tax_rates(db: Session, draft: InvoiceDraft | None = None) -> tuple[int, ...]:
    """0, 5, 13, 14, 15, the table's rates and -- for a draft -- its own saved rate, which stays
    allowed (at Save and Send) even after the table changes (review, 2026-10-24)."""
    rates = set(tax_rate_service.allowed_rates(db))
    if draft is not None and not rate_required(db, draft):
        rates.add(draft.tax_rate_percent)
    return tuple(sorted(rates))


def tax_label_of(db: Session, draft: InvoiceDraft) -> str:
    """ "HST" or "GST" when the draft's rate is the one its destination province filled in from
    ``tax_rates``; otherwise (international, chosen by staff, an older draft) "GST/HST"
    (review, 2026-10-24)."""
    route = route_row(db, draft)
    if (
        route is None
        or route.destination_province is None
        or route.suggested_rate_percent is None
        or draft.tax_rate_percent != route.suggested_rate_percent
    ):
        return "GST/HST"
    rate = tax_rate_service.rate_table(db).get(route.destination_province)
    return rate.tax_label if rate is not None else "GST/HST"


def _whole_rate(value: Any, allowed: tuple[int, ...]) -> int:
    """A whole percent; 13.5 or "13.5" is refused (422), never truncated."""
    if isinstance(value, bool):
        raise _rate_error(allowed)
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    raise _rate_error(allowed)


def _rate_error(allowed: tuple[int, ...]) -> ValidationError:
    words = ", ".join(f"{rate}%" for rate in allowed)
    return ValidationError(f"GST/HST must be one of {words}.", field="tax_rate_percent")


def _set_tax(
    db: Session,
    draft: InvoiceDraft,
    *,
    mode: str,
    confirmed: bool,
    actor: User | None,
    now: datetime,
) -> InvoiceDraftTax:
    """Write the draft's tax row: the mode, the mirrored rate and the confirmation."""
    row = tax_row(db, draft)
    if row is None:
        row = InvoiceDraftTax(draft_id=draft.id, created_at=now)
        db.add(row)
    row.mode = mode
    row.rate_percent = draft.tax_rate_percent
    row.updated_at = now
    if confirmed:
        row.confirmed_revision = draft.revision
        row.confirmed_at = now
        row.confirmed_by_user_id = actor.id if actor else None
    db.flush()
    return row


def _audit_tax_confirmed(db: Session, draft: InvoiceDraft, mode: str, actor: User | None) -> None:
    subtotal, tax, total = totals(lines_of(draft), draft.tax_rate_percent, mode)
    audit_service.record_audit(
        db,
        action="invoice.draft_tax_confirmed",
        entity_type="invoice_draft",
        entity_id=draft.id,
        summary=(
            f"Confirmed GST/HST {draft.tax_rate_percent} % ({mode}) on draft invoice "
            f"{draft.id} revision {draft.revision}: tax CAD {tax}, total CAD {total}"
        )[:400],
        actor=actor,
        detail={
            "shipment_id": draft.shipment_id,
            "revision": draft.revision,
            "tax_mode": mode,
            "tax_rate_percent": draft.tax_rate_percent,
            "subtotal_cad": str(subtotal),
            "tax_cad": str(tax),
            "total_cad": str(total),
        },
    )


def _check_echoed_tax(
    payload: dict[str, Any], *, lines: list[dict[str, str]], rate: int, mode: str, required: bool
) -> None:
    """The figures the screen showed beside the ticked box must be the ones being saved."""
    echoed = {
        key: payload.get(key)
        for key in ("confirmed_total_cad", "confirmed_tax_mode", "confirmed_tax_rate_percent")
    }
    if all(value is None for value in echoed.values()):
        if required:
            raise ValidationError(
                "The GST/HST changed: confirm the new rate, mode and total shown on screen "
                "(send confirmed_total_cad, confirmed_tax_mode and confirmed_tax_rate_percent).",
                field="tax_confirmed",
                detail={"code": "tax_unconfirmed"},
            )
        return
    _subtotal, _tax, total = totals(lines, rate, mode)
    try:
        shown_total = Decimal(str(echoed["confirmed_total_cad"])).quantize(CENT)
        shown_rate = int(echoed["confirmed_tax_rate_percent"])
    except (InvalidOperation, TypeError, ValueError):
        shown_total, shown_rate = None, None
    if (shown_total, echoed["confirmed_tax_mode"], shown_rate) != (total, mode, rate):
        raise ValidationError(
            f"The GST/HST you confirmed is not what this save produces ({rate} %, "
            f"{'included in the price' if mode == 'included' else 'added on top'}, total CAD "
            f"{total}). Check it again and tick the box.",
            field="tax_confirmed",
            detail={
                "code": "tax_unconfirmed",
                "total_cad": str(total),
                "tax_mode": mode,
                "tax_rate_percent": rate,
            },
        )


def tax_unconfirmed_error(action: str) -> ValidationError:
    return ValidationError(
        "Check the GST/HST on this invoice (rate, included in the price or added on top, and "
        "the amounts) and tick 'I have checked the GST/HST on this invoice' before you "
        f"{action}.",
        field="tax_confirmed",
        detail={"code": "tax_unconfirmed"},
    )


def tax_rate_required_error() -> ValidationError:
    return ValidationError(
        "The destination province of this domestic shipment is unknown, so no GST/HST rate "
        "was filled in: choose the rate before you save.",
        field="tax_rate_percent",
        detail={"code": "tax_rate_required"},
    )


def language_of(db: Session, draft: InvoiceDraft) -> str:
    from app.services import notification_service  # noqa: PLC0415

    return notification_service.language_for(db, db.get(Customer, draft.customer_id))


def expected_due_at(db: Session, moment: datetime) -> datetime:
    from app.services import finance_service  # noqa: PLC0415

    return moment + timedelta(days=finance_service.get_settings(db).invoice_due_days)


# --- Creation on acceptance ----------------------------------------------------------------------


def _billing_address(db: Session, customer: Customer | None) -> str | None:
    """The payer's billing address (else a both-ways one), as printable lines."""
    if customer is None:
        return None
    rows = list(
        db.scalars(
            select(CustomerAddress)
            .where(
                CustomerAddress.customer_id == customer.id,
                CustomerAddress.is_archived.is_(False),
                CustomerAddress.role.in_(("billing", "both")),
            )
            .order_by(CustomerAddress.id)
        )
    )
    rows.sort(key=lambda row: 0 if row.role == "billing" else 1)
    if not rows:
        return None
    row = rows[0]
    city_line = " ".join(
        part for part in (row.city, row.province_state, row.postal_code) if part
    ).strip()
    parts = [row.company_name, row.address_line1, row.address_line2, city_line, row.country_code]
    text = "\n".join(part.strip() for part in parts if part and part.strip())
    return text[: LIMITS["bill_to_address"]] or None


def create_for_acceptance(
    db: Session,
    offer: QuoteOffer,
    identity: CustomerIdentity | None,
    *,
    now: datetime | None = None,
) -> InvoiceDraft | None:
    """Prepare the draft invoice of an accepted offer, in the acceptance's unit."""
    from app.services import booking_service, finance_service, notification_service  # noqa: PLC0415

    now = now or utcnow()
    shipment = db.get(Shipment, offer.shipment_id)
    version = db.get(QuoteVersion, offer.quote_version_id)
    if shipment is None or version is None:
        return None
    if finance_service.live_invoice(db, shipment.id) is not None:
        # Already invoiced by hand before the customer answered: nothing to prepare.
        return None
    older = live_for_shipment(db, shipment.id)
    if older is not None:
        discard(
            db,
            older,
            reason=f"replaced by the draft for accepted quote v{version.version}",
            actor=None,
            actor_label=f"customer_account:{identity.public_id}" if identity else None,
            now=now,
        )
    payer_id = booking_service.payer_customer_id(db, shipment.id) or shipment.customer_id
    customer = db.get(Customer, payer_id)
    language = notification_service.language_for(db, customer)
    # Owner, 2026-10-23: the GST/HST comes from the route (DEC-0227).
    route = tax_rate_service.route_tax(db, shipment)
    names = customer_labels.vendor_names(db)
    lines = [
        {
            "description": customer_labels.customer_safe_label(
                line.description, names, language=language
            )[:300],
            "amount_cad": str(Decimal(line.revenue_cad).quantize(CENT)),
        }
        for line in version.lines
        if line.revenue_cad and line.revenue_cad > 0
    ]
    draft = InvoiceDraft(
        shipment_id=shipment.id,
        customer_id=payer_id,
        quote_version_id=version.id,
        offer_id=offer.id,
        status="draft",
        bill_to_name=(customer.full_name if customer else None),
        bill_to_address=_billing_address(db, customer),
        # Owner, 2026-10-23: by route; a placeholder when staff must choose (never shown).
        tax_rate_percent=(
            route.rate_percent if route.rate_percent is not None else UNSET_RATE_PLACEHOLDER
        ),
        lines_json=json.dumps(lines, ensure_ascii=False),
        quote_total_cad=subtotal_of(lines),
        revision=1,
        created_at=now,
        created_by_identity_id=identity.id if identity else None,
        updated_at=now,
    )
    db.add(draft)
    db.flush()
    _set_tax(db, draft, mode=route.mode, confirmed=False, actor=None, now=now)
    db.add(
        InvoiceDraftTaxRoute(
            draft_id=draft.id,
            route_band=route.route_band,
            origin_country_code=route.origin_country_code,
            destination_country_code=route.destination_country_code,
            destination_province=route.destination_province,
            suggested_rate_percent=route.rate_percent,
            suggested_mode=route.mode,
            rate_required=route.rate_required,
            created_at=now,
        )
    )
    db.flush()
    audit_service.record_audit(
        db,
        action="invoice.draft_created",
        entity_type="invoice_draft",
        entity_id=draft.id,
        summary=(
            f"Prepared the draft invoice for {shipment.public_id} from accepted quote "
            f"v{version.version}: CAD {draft.quote_total_cad} before tax"
        ),
        actor_label=f"customer_account:{identity.public_id}" if identity else None,
        detail={
            "shipment_id": shipment.id,
            "quote_version_id": version.id,
            "offer_id": offer.id,
            "account": identity.public_id if identity else None,
            "tax_rate_percent": route.rate_percent,
            "tax_mode": route.mode,
            "tax_route": {
                "route_band": route.route_band,
                "origin_country_code": route.origin_country_code,
                "destination_country_code": route.destination_country_code,
                "destination_province": route.destination_province,
                "rate_required": route.rate_required,
            },
        },
    )
    return draft


# --- Discarding ----------------------------------------------------------------------------------


def discard(
    db: Session,
    draft: InvoiceDraft,
    *,
    reason: str,
    actor: User | None,
    actor_label: str | None = None,
    now: datetime | None = None,
) -> InvoiceDraft:
    if draft.status != "draft":
        return draft
    now = now or utcnow()
    draft.status = "discarded"
    draft.discarded_at = now
    draft.discard_reason = reason[:400]
    draft.updated_at = now
    draft.revision += 1
    db.flush()
    audit_service.record_audit(
        db,
        action="invoice.draft_discarded",
        entity_type="invoice_draft",
        entity_id=draft.id,
        summary=f"Withdrew draft invoice {draft.id}: {reason}"[:400],
        actor=actor,
        actor_label=actor_label,
        detail={"shipment_id": draft.shipment_id, "reason": reason[:400]},
    )
    return draft


def withdraw(
    db: Session,
    draft: InvoiceDraft,
    *,
    reason: Any,
    actor: User | None,
    now: datetime | None = None,
) -> InvoiceDraft:
    """Staff discard a draft (with a reason) so the shipment can be invoiced the normal way."""
    require_draft(draft)
    if reason is not None and not isinstance(reason, str):
        raise ValidationError("A reason must be text.", field="reason")
    text = " ".join((reason or "").split())
    if not text:
        raise ValidationError("Say why the draft invoice is withdrawn.", field="reason")
    if len(text) > 300:
        raise ValidationError("At most 300 characters.", field="reason")
    return discard(db, draft, reason=f"withdrawn by staff: {text}", actor=actor, now=now)


# --- Editing -------------------------------------------------------------------------------------


def require_draft(draft: InvoiceDraft) -> None:
    if draft.status != "draft":
        raise ConflictError(
            f"This draft invoice is {draft.status}; only a draft is edited, sent or "
            "downloaded as a draft.",
            detail={"code": "not_a_draft", "status": draft.status},
        )


def check_revision(draft: InvoiceDraft, expected: Any) -> None:
    """Refuse a request made from a revision that is no longer the saved one."""
    try:
        number = int(expected)
    except (TypeError, ValueError) as error:
        raise ValidationError(
            "Say which revision of the draft you are working from.", field="expected_revision"
        ) from error
    if number != draft.revision:
        raise ConflictError(
            "This draft invoice was changed since you opened it. Reload it to see the saved "
            "version, then make your change again.",
            detail={"code": "stale_revision", "current_revision": draft.revision},
        )


def _text(payload: dict[str, Any], field: str) -> str | None:
    value = payload.get(field)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValidationError("This must be text.", field=field)
    if field in ("bill_to_address", "notes"):
        text = "\n".join(" ".join(line.split()) for line in value.strip().splitlines()).strip()
    else:
        text = " ".join(value.split())
    if len(text) > LIMITS[field]:
        raise ValidationError(f"At most {LIMITS[field]} characters.", field=field)
    return text or None


def _amount(value: Any) -> Decimal:
    try:
        number = Decimal(str(value).strip())
    except (InvalidOperation, ValueError) as error:
        raise ValidationError("Each amount must be a number.", field="lines") from error
    if not number.is_finite() or number < 0:
        raise ValidationError("Amounts cannot be negative.", field="lines")
    if number != number.quantize(CENT):
        raise ValidationError("Amounts have at most two decimals.", field="lines")
    return number.quantize(CENT)


def _lines(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list) or not value:
        raise ValidationError("An invoice needs at least one line.", field="lines")
    if len(value) > MAX_LINES:
        raise ValidationError(f"At most {MAX_LINES} lines.", field="lines")
    out = []
    for entry in value:
        if not isinstance(entry, dict) or set(entry) - {"description", "amount_cad"}:
            raise ValidationError("Each line is a description and an amount.", field="lines")
        description = " ".join(str(entry.get("description") or "").split())
        if not description:
            raise ValidationError("Describe every line.", field="lines")
        if len(description) > 300:
            raise ValidationError("A line description is at most 300 characters.", field="lines")
        out.append(
            {"description": description, "amount_cad": str(_amount(entry.get("amount_cad")))}
        )
    if subtotal_of(out) <= 0:
        raise ValidationError("The invoice total must be more than zero.", field="lines")
    return out


def update_draft(
    db: Session,
    draft: InvoiceDraft,
    payload: dict[str, Any],
    *,
    expected_revision: Any,
    actor: User | None,
    now: datetime | None = None,
) -> InvoiceDraft:
    """Save the edited fields; refused on a stale revision. Audited with a field diff."""
    require_draft(draft)
    check_revision(draft, expected_revision)
    unknown = set(payload) - set(EDITABLE)
    if unknown:
        raise ValidationError(f"These cannot be edited: {', '.join(sorted(unknown))}.")
    confirmed = payload.get("tax_confirmed")
    if confirmed is not None and not isinstance(confirmed, bool):
        raise ValidationError("The GST/HST check is ticked or not.", field="tax_confirmed")
    values: dict[str, Any] = {}
    names = customer_labels.vendor_names(db)
    for field in ("bill_to_name", "bill_to_address", "customer_reference", "notes"):
        if field in payload:
            values[field] = _text(payload, field)
            # Customer-facing: a vendor's name is refused on save (owner, OD-84).
            customer_labels.refuse_vendor_name(values[field], names, field=field)
    needs_rate = rate_required(db, draft)
    if payload.get("tax_rate_percent") is not None:
        allowed = allowed_tax_rates(db, draft)
        rate = _whole_rate(payload["tax_rate_percent"], allowed)
        if rate not in allowed:
            raise _rate_error(allowed)
        values["tax_rate_percent"] = rate
    elif needs_rate:
        # Domestic, province unknown (DEC-0227): staff must choose a rate first.
        raise tax_rate_required_error()
    old_mode = tax_mode_of(db, draft)
    mode = old_mode
    if payload.get("tax_mode") is not None:
        mode = payload["tax_mode"]
        if mode not in TAX_MODES:
            raise ValidationError(
                "GST/HST is either included in the price or added on top.", field="tax_mode"
            )
    lines = lines_of(draft)
    if "lines" in payload:
        lines = _lines(payload["lines"])
        for line in lines:
            customer_labels.refuse_vendor_name(line["description"], names, field="lines")
        values["lines_json"] = json.dumps(lines, ensure_ascii=False)
    # A total that is not the accepted quote's needs a reason; an unchanged one carries none.
    differs = subtotal_of(lines) != Decimal(draft.quote_total_cad)
    reason = (
        _text(payload, "total_change_reason")
        if "total_change_reason" in payload
        else draft.total_change_reason
    )
    if differs and not reason:
        raise ValidationError(
            "The total differs from the accepted quote "
            f"(CAD {Decimal(draft.quote_total_cad).quantize(CENT)}); say why.",
            field="total_change_reason",
        )
    values["total_change_reason"] = reason if differs else None
    # Owner, 2026-10-22: no save without the GST/HST confirmed for what is being saved.
    if confirmed is not True:
        raise tax_unconfirmed_error("save")
    _check_echoed_tax(
        payload,
        lines=lines,
        rate=values.get("tax_rate_percent", draft.tax_rate_percent),
        mode=mode,
        required=(
            needs_rate
            or values.get("tax_rate_percent", draft.tax_rate_percent) != draft.tax_rate_percent
            or mode != old_mode
            or ("lines_json" in values and lines != lines_of(draft))
        ),
    )

    changes: dict[str, dict[str, Any]] = {}
    for field, new in values.items():
        old = getattr(draft, field)
        if field == "lines_json":
            if json.loads(old or "[]") != lines:
                changes["lines"] = {"from": json.loads(old or "[]"), "to": lines}
        elif field == "tax_rate_percent" and needs_rate:
            # The placeholder was never a rate: choosing one is always a change.
            changes[field] = {"from": None, "to": new}
        elif old != new:
            changes[field] = {"from": old, "to": new}
    if mode != old_mode:
        changes["tax_mode"] = {"from": old_mode, "to": mode}
    now = now or utcnow()
    if not changes:
        # Nothing else changed: the save only records the confirmation of this revision.
        if not tax_confirmed(db, draft):
            _set_tax(db, draft, mode=mode, confirmed=True, actor=actor, now=now)
            _audit_tax_confirmed(db, draft, mode, actor)
        return draft
    changed = db.execute(
        update(InvoiceDraft)
        .where(
            InvoiceDraft.id == draft.id,
            InvoiceDraft.revision == draft.revision,
            InvoiceDraft.status == "draft",
        )
        .values(
            **values,
            revision=draft.revision + 1,
            updated_at=now,
            updated_by_user_id=actor.id if actor else None,
        )
        .execution_options(synchronize_session=False)
    ).rowcount
    if changed != 1:
        db.refresh(draft)
        raise ConflictError(
            "This draft invoice was changed since you opened it. Reload it to see the saved "
            "version, then make your change again.",
            detail={"code": "stale_revision", "current_revision": draft.revision},
        )
    db.refresh(draft)
    _set_tax(db, draft, mode=mode, confirmed=True, actor=actor, now=now)
    if needs_rate:
        route = route_row(db, draft)
        route.rate_chosen_at = now
        route.rate_chosen_by_user_id = actor.id if actor else None
        db.flush()
    audit_service.record_audit(
        db,
        action="invoice.draft_edited",
        entity_type="invoice_draft",
        entity_id=draft.id,
        summary=f"Edited draft invoice {draft.id} ({', '.join(sorted(changes))})"[:400],
        actor=actor,
        detail={
            "shipment_id": draft.shipment_id,
            "revision": draft.revision,
            "changes": changes,
            "tax": {"mode": mode, "rate_percent": draft.tax_rate_percent},
        },
    )
    _audit_tax_confirmed(db, draft, mode, actor)
    return draft


# --- Sending -------------------------------------------------------------------------------------


def send(
    db: Session,
    draft: InvoiceDraft,
    *,
    expected_revision: Any,
    actor: User | None,
    acknowledge_superseded: bool = False,
    now: datetime | None = None,
) -> CustomerInvoice:
    """Issue the real invoice from the saved draft. The caller commits, then ``send_email``.

    A draft whose quote has a newer finalised version is sent only when the caller
    acknowledges it (the accepted price stands); the acknowledgement is audited.
    """
    from app.services import finance_service, quote_expiry_service  # noqa: PLC0415

    require_draft(draft)
    check_revision(draft, expected_revision)
    if quote_expiry_service.is_expired(db, draft.quote_version_id):
        raise ConflictError(
            "The quote behind this draft has expired: re-quote on the new rate.",
            detail={"code": "quote_expired"},
        )
    version = db.get(QuoteVersion, draft.quote_version_id)
    newer = superseding_version(db, draft)
    if newer is not None and not acknowledge_superseded:
        raise ConflictError(
            f"Quote v{newer.version} was finalised after this draft's accepted quote "
            f"v{version.version}. Confirm sending at the accepted price (v{version.version}), "
            "or withdraw this draft and invoice from the latest version.",
            detail={
                "code": "quote_superseded",
                "draft_version": version.version,
                "latest_version": newer.version,
            },
        )
    if not tax_confirmed(db, draft):
        raise tax_unconfirmed_error("send")
    mode = tax_mode_of(db, draft)
    now = now or utcnow()
    shipment = db.get(Shipment, draft.shipment_id)
    lines = lines_of(draft)
    invoice = finance_service.issue_invoice_from_draft(
        db,
        shipment,
        version=version,
        payer_id=draft.customer_id,
        lines=[(line["description"], Decimal(line["amount_cad"])) for line in lines],
        tax_rate_percent=draft.tax_rate_percent,
        tax_mode=mode,
        allowed_rates=allowed_tax_rates(db, draft),
        extra_document={
            "invoice_draft_id": draft.id,
            "tax_mode": mode,
            "tax_rate_percent": draft.tax_rate_percent,
            "tax_label": tax_label_of(db, draft),
            "bill_to_name": draft.bill_to_name,
            "bill_to_address": draft.bill_to_address,
            "purchase_order_reference": draft.customer_reference,
            "invoice_notes": draft.notes,
            "language": language_of(db, draft),
        },
        actor=actor,
        now=now,
    )
    changed = db.execute(
        update(InvoiceDraft)
        .where(
            InvoiceDraft.id == draft.id,
            InvoiceDraft.revision == draft.revision,
            InvoiceDraft.status == "draft",
        )
        .values(
            status="issued",
            issued_invoice_id=invoice.id,
            issued_at=now,
            revision=draft.revision + 1,
            updated_at=now,
            updated_by_user_id=actor.id if actor else None,
        )
        .execution_options(synchronize_session=False)
    ).rowcount
    if changed != 1:
        raise ConflictError(
            "This draft invoice was changed since you opened it. Reload it to see the saved "
            "version, then make your change again.",
            detail={"code": "stale_revision"},
        )
    db.refresh(draft)
    audit_service.record_audit(
        db,
        action="invoice.draft_sent",
        entity_type="invoice_draft",
        entity_id=draft.id,
        summary=f"Sent draft invoice {draft.id} as {invoice.public_id}",
        actor=actor,
        detail={
            "shipment_id": draft.shipment_id,
            "invoice": invoice.public_id,
            "sent_despite_newer_version": newer.version if newer is not None else None,
            "tax_mode": mode,
            "tax_rate_percent": draft.tax_rate_percent,
        },
    )
    return invoice


# --- The invoice email: decide, send outside any unit, record ------------------------------------


def _money(value: Decimal) -> str:
    return f"CAD {Decimal(value).quantize(CENT):,.2f}"


def _decide_email(db: Session, draft: InvoiceDraft) -> tuple[str | None, Any]:
    from app.services import account_email_service, consent_service  # noqa: PLC0415

    invoice = db.get(CustomerInvoice, draft.issued_invoice_id) if draft.issued_invoice_id else None
    if draft.status != "issued" or invoice is None:
        return "skipped", None
    customer = db.get(Customer, draft.customer_id)
    address = (
        consent_service.normalized_address_for(customer, ConsentChannel.EMAIL) if customer else None
    )
    if not address:
        return "no_email", None
    # An invoice is operational email: a marketing suppression does not block it (DEC-0143).
    language = language_of(db, draft)
    message = account_email_service.OutboundEmail(
        to_email=customer.email_entered or address,
        template_key=template_key(language),
        language=language,
        parameters={
            "invoice_number": invoice.public_id,
            "total": _money(invoice.total_cad),
            "due_date": invoice.due_at.date().isoformat(),
        },
    )
    return None, message


def _record_email(db: Session, draft_id: int, status: str) -> None:
    from app.core.db import run_unit_with_retry  # noqa: PLC0415

    def work() -> None:
        row = db.get(InvoiceDraft, draft_id)
        row.email_status = status
        db.flush()

    run_unit_with_retry(db, work)


def send_email(db: Session, draft_id: int) -> str:
    """Email the customer their invoice. Call after the send is committed. Never raises."""
    from app.services import account_email_service  # noqa: PLC0415

    try:
        draft = db.get(InvoiceDraft, draft_id)
        reason, message = _decide_email(db, draft)
    except Exception:  # noqa: BLE001 - the invoice stands whatever the email does
        db.rollback()
        logger.warning("invoice_email_undecided draft=%s", draft_id, exc_info=True)
        status = "failed"
    else:
        db.rollback()  # end the read transaction before the side effect
        if reason is not None:
            status = reason
        else:
            try:
                result = account_email_service.send(message)
                status = "sent" if result.delivered else "recorded"
            except Exception:  # noqa: BLE001 - recorded, never raised
                logger.warning("invoice_email_failed draft=%s", draft_id, exc_info=True)
                status = "failed"
    try:
        _record_email(db, draft_id, status)
    except Exception:  # noqa: BLE001 - recorded in the log instead
        db.rollback()
        logger.warning("invoice_email_unrecorded draft=%s", draft_id, exc_info=True)
    return status


# --- Views ---------------------------------------------------------------------------------------


def view(db: Session, draft: InvoiceDraft) -> dict[str, Any]:
    """The staff view of a draft: revenue only (no cost, margin or rate)."""
    from app.services import quote_expiry_service  # noqa: PLC0415

    shipment = db.get(Shipment, draft.shipment_id)
    customer = db.get(Customer, draft.customer_id)
    version = db.get(QuoteVersion, draft.quote_version_id)
    invoice = db.get(CustomerInvoice, draft.issued_invoice_id) if draft.issued_invoice_id else None
    lines = lines_of(draft)
    lines_total = subtotal_of(lines)
    tax_entry = tax_row(db, draft)
    mode = tax_entry.mode if tax_entry is not None else LEGACY_TAX_MODE
    needs_rate = rate_required(db, draft)
    route = route_row(db, draft)
    label = tax_label_of(db, draft)
    if needs_rate:
        # No rate yet (domestic, province unknown): no tax figures to show.
        subtotal = tax = total = None
        figures = None
    else:
        figures = breakdown(lines, draft.tax_rate_percent, mode, label=label)
        subtotal, tax, total = figures.totals
    confirmed = (
        tax_entry is not None and tax_entry.confirmed_revision == draft.revision and not needs_rate
    )
    confirmer = (
        db.get(User, tax_entry.confirmed_by_user_id)
        if confirmed and tax_entry.confirmed_by_user_id
        else None
    )
    newer = superseding_version(db, draft) if draft.status == "draft" else None
    return {
        "id": draft.id,
        "shipment_id": draft.shipment_id,
        "shipment_reference": shipment.public_id if shipment else None,
        "consolidation_id": version.consolidation_id if version else None,
        "customer_id": draft.customer_id,
        "customer_name": customer.full_name if customer else None,
        # Where Send will email the invoice (shown in the confirmation), or None.
        "customer_email": (customer.email_entered or customer.email_normalized)
        if customer
        else None,
        "quote_version_id": draft.quote_version_id,
        "quote_version": version.version if version else None,
        "offer_id": draft.offer_id,
        "status": draft.status,
        "bill_to_name": draft.bill_to_name,
        "bill_to_address": draft.bill_to_address,
        "customer_reference": draft.customer_reference,
        "notes": draft.notes,
        "tax_rate_percent": None if needs_rate else draft.tax_rate_percent,
        "tax_mode": mode,
        # Owner, 2026-10-23 (DEC-0227): what the rate was filled from, and the choices.
        "tax_rate_required": needs_rate,
        "tax_label": label,
        "allowed_tax_rates": list(allowed_tax_rates(db, draft)),
        "tax_route": (
            {
                "route_band": route.route_band,
                "origin_country_code": route.origin_country_code,
                "destination_country_code": route.destination_country_code,
                "destination_province": route.destination_province,
                "suggested_rate_percent": route.suggested_rate_percent,
                "suggested_mode": route.suggested_mode,
            }
            if route is not None
            else None
        ),
        # Confirmed for the saved revision (owner, 2026-10-22): Send and Download need it.
        "tax_confirmed": confirmed,
        "tax_confirmed_at": tax_entry.confirmed_at if confirmed else None,
        "tax_confirmed_by": confirmer.email if confirmer else None,
        "lines": lines,
        # DEC-0235: the per-line figures and the summary rows exactly as the issued invoice and
        # the PDF show them (None while no rate is chosen).
        "tax_layout": tax_math.LAYOUT,
        "tax_lines": (
            [
                {"description": line["description"], **figure.as_dict()}
                for line, figure in zip(lines, figures.lines, strict=True)
            ]
            if figures is not None
            else None
        ),
        "tax_rows": figures.rows_as_dicts() if figures is not None else None,
        "lines_total_cad": str(lines_total),
        "subtotal_cad": None if subtotal is None else str(subtotal),
        "tax_cad": None if tax is None else str(tax),
        "total_cad": None if total is None else str(total),
        "quote_total_cad": str(Decimal(draft.quote_total_cad).quantize(CENT)),
        "total_change_reason": draft.total_change_reason,
        "revision": draft.revision,
        "created_at": draft.created_at,
        "updated_at": draft.updated_at,
        "issued_invoice_id": draft.issued_invoice_id,
        "issued_invoice_public_id": invoice.public_id if invoice else None,
        "issued_at": draft.issued_at,
        "discarded_at": draft.discarded_at,
        "discard_reason": draft.discard_reason,
        "email_status": draft.email_status,
        "quote_expired": quote_expiry_service.is_expired(db, draft.quote_version_id),
        "superseded_by_version": newer.version if newer is not None else None,
        "language": language_of(db, draft),
    }
