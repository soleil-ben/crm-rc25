"""What a customer quote says about GST/HST (RC-UAT-21, P-9 stand-in pending Ben; DEC-0232).

The quote follows the RC-UAT-20 **invoice** rule (DEC-0227), read through the same route
detection (``tax_rate_service.route_tax``) and the same ``tax_rates`` table:

* **domestic** (both ends in Canada): the price **includes** GST/HST at the destination
  province's rate -- "Prices include HST 13 %" / "Giá đã bao gồm HST 13 %", the label (HST or
  GST) from ``tax_rates``. A domestic route whose province cannot be read says "Prices include
  GST/HST" with no rate (stand-in B-8), as the invoice leaves the rate to staff there;
* **international** (one end outside Canada): zero-rated -- "Zero-rated (0 %)" /
  "Thuế suất 0 (0 %)".

This **replaces** the RC-UAT-20 note "Taxes, if any, are added on the invoice" (OD-108's
note); the total label "Tổng cộng" stays. The quote email carries no amounts and is unchanged.

The figures themselves do not change: the quote total is the price the invoice later backs the
tax out of. The wording is computed when the quote is read, from the shipment's route as it is
then -- not frozen into the offer's customer view -- so it agrees with the invoice the
acceptance prepares (stand-in B-9).

The sentences are composed by the screens from ``band``, ``label`` and ``rate_percent`` in the
reader's language; the English and Vietnamese forms are also here so the backend tests pin the
same words the screens print (``finance_service`` holds the invoice's).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.models import Shipment
from app.services import finance_service, tax_rate_service

DOMESTIC = "domestic"
INTERNATIONAL = "international"

#: The domestic sentence without a rate (province unknown, stand-in B-8).
INCLUDED_NO_RATE = {"en": "Prices include GST/HST", "vi": "Giá đã bao gồm GST/HST"}


def quote_tax(db: Session, shipment: Shipment | None) -> dict[str, Any] | None:
    """``{"band", "label", "rate_percent"}`` for a shipment's quote, or None without one."""
    if shipment is None:
        return None
    route = tax_rate_service.route_tax(db, shipment)
    if route.route_band != DOMESTIC:
        return {"band": INTERNATIONAL, "label": None, "rate_percent": 0}
    return {
        "band": DOMESTIC,
        "label": route.tax_label or finance_service.GENERIC_TAX_LABEL,
        "rate_percent": route.rate_percent,
    }


def tax_sentence(tax: dict[str, Any] | None, language: str) -> str | None:
    """The sentence a quote prints under its total, in ``en`` or ``vi``."""
    if tax is None:
        return None
    lang = "en" if language == "en" else "vi"
    if tax["band"] == INTERNATIONAL:
        return finance_service.ZERO_RATED_LABEL[lang]
    if tax["rate_percent"] is None:
        return INCLUDED_NO_RATE[lang]
    return finance_service.TAX_INCLUDED_NOTE[lang].format(
        label=tax["label"], rate=tax["rate_percent"]
    )
