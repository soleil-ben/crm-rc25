"""RC-UAT-21 (P-9 stand-in pending Ben; DEC-0232): the customer quote's GST/HST wording follows
the RC-UAT-20 invoice rule (DEC-0227).

* domestic: "Prices include HST 13 %" / "Giá đã bao gồm HST 13 %" at the destination
  province's rate and label from ``tax_rates``; a domestic route whose province is unknown says
  "Prices include GST/HST" with no rate (stand-in);
* international: "Zero-rated (0 %)" / "Thuế suất 0 (0 %)";
* the total label "Tổng cộng" stays, and this replaces OD-108's note "Taxes, if any, are added
  on the invoice" (registered in ``docs/customer_account/SUPERSEDED_ASSERTIONS.md``);
* the Customer Account quote (list and detail) and the printed quote document carry it; the
  quote email carries no amounts (unchanged).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core.enums import RouteGroup
from app.models import Shipment, TaxRate
from app.services import quote_tax_wording as qtw
from tests.conftest import see_committed_changes
from tests.test_rc20_golden import _build, _finalize, _route

REPO_ROOT = Path(__file__).resolve().parents[2]


def _bare(route_group=RouteGroup.VCA, **fields) -> Shipment:
    return Shipment(route_group=route_group, **fields)


@pytest.mark.parametrize(
    ("province", "postal", "rate", "label", "en", "vi"),
    [
        ("ON", "M5V 2T6", 13, "HST", "Prices include HST 13 %", "Giá đã bao gồm HST 13 %"),
        ("NS", "B3H 1A1", 14, "HST", "Prices include HST 14 %", "Giá đã bao gồm HST 14 %"),
        ("NB", "E1C 1A1", 15, "HST", "Prices include HST 15 %", "Giá đã bao gồm HST 15 %"),
        ("BC", "V6B 1A1", 5, "GST", "Prices include GST 5 %", "Giá đã bao gồm GST 5 %"),
        ("QC", "H2X 1Y4", 5, "GST", "Prices include GST 5 %", "Giá đã bao gồm GST 5 %"),
    ],
)
def test_a_domestic_quote_includes_the_destination_provinces_tax(
    db, province, postal, rate, label, en, vi
):
    shipment = _bare(
        RouteGroup.CAD,
        origin_country_code="CA",
        destination_country_code="CA",
        recipient_province_state=province,
        recipient_postal_code=postal,
    )
    tax = qtw.quote_tax(db, shipment)
    assert tax == {"band": "domestic", "label": label, "rate_percent": rate}
    assert qtw.tax_sentence(tax, "en") == en
    assert qtw.tax_sentence(tax, "vi") == vi


@pytest.mark.parametrize(
    ("origin", "destination", "group"),
    [("VN", "CA", RouteGroup.VCA), ("CA", "VN", RouteGroup.CAV), ("CA", "US", RouteGroup.XUS)],
)
def test_an_international_quote_is_zero_rated(db, origin, destination, group):
    tax = qtw.quote_tax(
        db,
        _bare(group, origin_country_code=origin, destination_country_code=destination),
    )
    assert tax == {"band": "international", "label": None, "rate_percent": 0}
    assert qtw.tax_sentence(tax, "en") == "Zero-rated (0 %)"
    assert qtw.tax_sentence(tax, "vi") == "Thuế suất 0 (0 %)"


def test_a_domestic_quote_with_an_unknown_province_names_no_rate(db):
    tax = qtw.quote_tax(
        db, _bare(RouteGroup.CAD, origin_country_code="CA", destination_country_code="CA")
    )
    assert tax == {"band": "domestic", "label": "GST/HST", "rate_percent": None}
    assert qtw.tax_sentence(tax, "en") == "Prices include GST/HST"
    assert qtw.tax_sentence(tax, "vi") == "Giá đã bao gồm GST/HST"


def test_the_rate_comes_from_the_tax_rates_table(db):
    from app.core.time_utils import utcnow

    db.add(TaxRate(province_code="ON", rate_percent=15, tax_label="HST", updated_at=utcnow()))
    db.commit()
    shipment = _bare(
        RouteGroup.CAD,
        origin_country_code="CA",
        destination_country_code="CA",
        recipient_postal_code="M5V 2T6",
    )
    assert qtw.quote_tax(db, shipment)["rate_percent"] == 15


@pytest.fixture
def quote_world(account_client, account_db, account_users, captured_mail):
    return _build(account_client, account_db, account_users, captured_mail, ["dom", "intl"])


def test_the_account_quote_and_the_printed_document_carry_the_wording(quote_world):
    g = quote_world
    ops = g["ops"]
    _route(g, "dom", "CA", "CA", "ON")
    _route(g, "intl", "VN", "CA", "ON")
    offers = {}
    for kid in ("dom", "intl"):
        sid, _ref = g["kids"][kid]
        assert _finalize(ops, sid).status_code == 200
        sent = ops.post(f"/shipments/{sid}/quotes/send")
        assert sent.status_code == 201, sent.text
        offers[kid] = sent.json()["id"]

    listed = {row["id"]: row for row in g["me"].get("/quotes").json()["items"]}
    expected = {
        "dom": {"band": "domestic", "label": "HST", "rate_percent": 13},
        "intl": {"band": "international", "label": None, "rate_percent": 0},
    }
    for kid, offer_id in offers.items():
        assert listed[offer_id]["tax"] == expected[kid]
        detail = g["me"].get(f"/quotes/{offer_id}")
        assert detail.status_code == 200 and detail.json()["tax"] == expected[kid]
        sid, _ref = g["kids"][kid]
        doc = ops.get(f"/shipments/{sid}/quotes/1/document")
        assert doc.status_code == 200 and doc.json()["tax"] == expected[kid]

    # The quote email still carries no amount.
    see_committed_changes(g["db"])
    from app.services import account_email_service as email

    transport = email.get_transport()
    quote_mail = [m for m in transport.messages if m["template_key"].startswith("quote.sent")]
    assert quote_mail and all("$" not in m["body"] and "CAD" not in m["body"] for m in quote_mail)


def test_the_screens_print_the_invoice_rule_and_keep_tong_cong():
    """OD-108's note is replaced by the invoice rule; the total label stays "Tổng cộng"."""
    vi = (REPO_ROOT / "frontend/src/account/i18n/vi.js").read_text(encoding="utf-8")
    en = (REPO_ROOT / "frontend/src/account/i18n/en.js").read_text(encoding="utf-8")
    assert "'quotes.colTotal': 'Tổng cộng'," in vi
    assert "'quotes.taxIncluded': 'Giá đã bao gồm {label} {rate} %'," in vi
    assert "'quotes.taxIncludedNoRate': 'Giá đã bao gồm GST/HST'," in vi
    assert "'quotes.taxZeroRated': 'Thuế suất 0 (0 %)'," in vi
    assert "'quotes.taxIncluded': 'Prices include {label} {rate} %'," in en
    assert "'quotes.taxZeroRated': 'Zero-rated (0 %)'," in en
    for text in (vi, en):
        assert "quotes.taxNote" not in text
    assert "sẽ được tính trên hóa đơn" not in vi and "added on the invoice" not in en
