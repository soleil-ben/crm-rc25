"""RC-UAT-20, owner Ben, 2026-10-23: GST/HST by route (DEC-0227), Download needs the tax
confirmed (DEC-0229), and two customer-facing wordings that stay as they are.

1. A new draft invoice's GST/HST follows the shipment's route: international (one end outside
   Canada) 0 %; domestic, included in the price and backed out, at the destination
   province's rate from ``tax_rates`` (ON 13; NS 14; NB, NL, PE 15; the rest 5 GST). An
   unknown province on a domestic route leaves the rate unset until staff choose one.
2. Admin views and edits the rates (audited); an edit changes the next auto-fill; the allowed
   rates are 0, 5, 13, 14, 15 and whatever the table holds. The manual Issue invoice path is
   unchanged.
3. ``GET /invoice-drafts/{id}/pdf`` is refused (422 ``tax_unconfirmed``) like Send until the
   saved revision's GST/HST is confirmed.
4. Wording kept: the customer quote's "Tổng cộng" with the note that tax is added on the
   invoice, and the staff note label "Ghi chú từ Solaris Express".
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest

from app.core.enums import Role, RouteGroup
from app.models import (
    AuditEvent,
    CustomerInvoice,
    InvoiceDraftTax,
    InvoiceDraftTaxRoute,
    Shipment,
    TaxRate,
)
from app.services import finance_service as fs
from app.services import invoice_draft_service as drafts
from app.services import tax_rate_service as trs
from app.services.errors import ValidationError
from tests.conftest import see_committed_changes, shown_tax
from tests.test_fixpack_f_lock_expiry_drafts import _accepted
from tests.test_quotes import priced_world  # noqa: F401 - fixture

D = Decimal
REPO_ROOT = Path(__file__).resolve().parents[2]


def _audits(db, action):
    return db.query(AuditEvent).filter_by(action=action).order_by(AuditEvent.id).all()


def _route(db, shipment, origin, destination, province=None):
    shipment.origin_country_code = origin
    shipment.destination_country_code = destination
    shipment.sender_country_code = origin
    shipment.recipient_country_code = destination
    shipment.recipient_province_state = province
    shipment.recipient_postal_code = None  # read first; the fixture's is Ontario's (L4W)
    db.commit()
    return shipment


def _bare(route_group=RouteGroup.VCA, **fields) -> Shipment:
    """An unsaved shipment: ``route_tax`` reads only its route fields."""
    return Shipment(route_group=route_group, **fields)


# === 1. The bands ================================================================================


@pytest.mark.parametrize(
    ("origin", "destination", "group"),
    [
        ("VN", "CA", RouteGroup.VCA),
        ("CA", "VN", RouteGroup.CAV),
        ("CA", "US", RouteGroup.XUS),
        ("US", "CA", RouteGroup.XUS),
    ],
)
def test_international_routes_are_zero_rated(db, origin, destination, group):
    route = trs.route_tax(
        db,
        _bare(
            group,
            origin_country_code=origin,
            destination_country_code=destination,
            recipient_province_state="ON",  # a Canadian address does not make it domestic
        ),
    )
    assert (route.route_band, route.rate_percent, route.mode) == ("international", 0, "included")
    assert route.rate_required is False


@pytest.mark.parametrize(
    ("province", "rate", "label"),
    [
        ("ON", 13, "HST"),
        ("NS", 14, "HST"),
        ("NB", 15, "HST"),
        ("NL", 15, "HST"),
        ("PE", 15, "HST"),
        ("AB", 5, "GST"),
        ("BC", 5, "GST"),
        ("MB", 5, "GST"),
        ("QC", 5, "GST"),
        ("SK", 5, "GST"),
        ("NT", 5, "GST"),
        ("NU", 5, "GST"),
        ("YT", 5, "GST"),
    ],
)
def test_domestic_routes_take_the_destination_province_rate_included(db, province, rate, label):
    shipment = _bare(
        RouteGroup.CAD,
        origin_country_code="CA",
        destination_country_code="CA",
        sender_province_state="ON",  # the origin province never counts
        recipient_province_state=province,
    )
    route = trs.route_tax(db, shipment)
    assert (route.route_band, route.destination_province) == ("domestic", province)
    assert (route.rate_percent, route.tax_label, route.mode) == (rate, label, "included")


@pytest.mark.parametrize(
    ("written", "code"),
    [
        ("Ontario", "ON"),
        ("ontario ", "ON"),
        ("Québec", "QC"),
        ("Nouvelle-Écosse", "NS"),
        ("Prince Edward Island", "PE"),
        ("P.E.I.", "PE"),
        ("Newfoundland and Labrador", "NL"),
        ("Toronto, ON", "ON"),
        ("YT", "YT"),
        ("Newfoundland & Labrador", "NL"),
        ("Terre-Neuve-et-Labrador", "NL"),
        ("Montréal (Québec)", "QC"),
        ("Alta.", "AB"),
        ("Sask.", "SK"),
        ("Man.", "MB"),
        ("Ile-du-Prince-Édouard", "PE"),
        ("Colombie-Britannique", "BC"),
        ("Territoires du Nord-Ouest", "NT"),
        ("Halifax NS", "NS"),
    ],
)
def test_a_province_is_recognised_by_code_or_name(written, code):
    assert trs.province_code(written) == code


@pytest.mark.parametrize(
    "written",
    [
        None,
        "",
        "  ",
        "Ontaryo",
        "California",
        "WA",
        "XX",
        "yt",  # codes are case-sensitive
        "Niagara on the Lake",  # "on" is not ON
        "ON or NS",  # two provinces named
        "Ontario / Quebec",
    ],
)
def test_an_unknown_or_ambiguous_province_is_none(written):
    assert trs.province_code(written) is None


@pytest.mark.parametrize(
    ("postal", "code"),
    [
        ("A1C 5M2", "NL"),
        ("B3H 1A1", "NS"),
        ("C1A 4P3", "PE"),
        ("E1C 4M3", "NB"),
        ("G1R 4P5", "QC"),
        ("H2X 1Y4", "QC"),
        ("J8X 3X7", "QC"),
        ("K1A 0B1", "ON"),
        ("L4W 1V2", "ON"),
        ("M5V 2T6", "ON"),
        ("N2L 3G1", "ON"),
        ("P3E 2C6", "ON"),
        ("R3C 4T3", "MB"),
        ("S4P 3V7", "SK"),
        ("T2P 1J9", "AB"),
        ("V6B 1A1", "BC"),
        ("X0A 0H0", "NU"),
        ("X1A 2P7", "NT"),
        ("Y1A 1B1", "YT"),
        ("b3h1a1", "NS"),
    ],
)
def test_the_postal_code_names_the_province(postal, code):
    assert trs.postal_province(postal) == code


@pytest.mark.parametrize("postal", [None, "", "90210", "D1A 1A1", "B3H", "B3H 1A1 X"])
def test_a_postal_code_that_is_not_canadian_names_none(postal):
    assert trs.postal_province(postal) is None


@pytest.mark.parametrize(
    ("postal", "text", "province"),
    [
        ("B3H 1A1", None, "NS"),  # postal code alone
        ("B3H 1A1", "", "NS"),
        (None, "NS", "NS"),  # text alone
        ("B3H 1A1", "Nova Scotia", "NS"),  # both agree
        ("L4W 1V2", "NS", None),  # disagree: staff choose
        ("B3H 1A1", "ON or NS", None),  # the text names two
        ("90210", "NB", "NB"),  # not a Canadian postal code: the text decides
        ("L0S 1J0", "Niagara on the Lake", "ON"),
        (None, None, None),
    ],
)
def test_the_destination_province_postal_code_first_then_text(postal, text, province):
    assert trs.destination_province(postal, text) == province


def test_countries_fall_back_to_the_route_group(db):
    assert trs.route_tax(db, _bare(RouteGroup.VCA)).rate_percent == 0
    assert trs.route_tax(db, _bare(RouteGroup.CAV)).rate_percent == 0
    assert trs.route_tax(db, _bare(RouteGroup.XUS)).rate_percent == 0
    domestic = trs.route_tax(db, _bare(RouteGroup.CAD, recipient_province_state="NS"))
    assert (domestic.route_band, domestic.rate_percent) == ("domestic", 14)


def test_a_domestic_route_reads_the_postal_code_before_the_text(db):
    route = trs.route_tax(
        db,
        _bare(
            RouteGroup.CAD,
            origin_country_code="CA",
            destination_country_code="CA",
            recipient_postal_code="E1C 4M3",
            recipient_province_state=None,
        ),
    )
    assert (route.destination_province, route.rate_percent) == ("NB", 15)
    conflict = trs.route_tax(
        db,
        _bare(
            RouteGroup.CAD,
            origin_country_code="CA",
            destination_country_code="CA",
            recipient_postal_code="E1C 4M3",
            recipient_province_state="ON",
        ),
    )
    assert conflict.rate_required and conflict.destination_province is None


def test_a_domestic_route_with_an_unknown_province_has_no_rate(db):
    for province in (None, "", "Somewhere", "Niagara on the Lake"):
        route = trs.route_tax(
            db,
            _bare(
                RouteGroup.CAD,
                origin_country_code="CA",
                destination_country_code="CA",
                recipient_province_state=province,
            ),
        )
        assert route.route_band == "domestic"
        assert route.rate_percent is None and route.rate_required is True


# === 1b. Auto-fill on acceptance =================================================================


def test_a_vn_ca_draft_auto_fills_zero_rated_and_records_its_route(db, priced_world):  # noqa: F811
    _con, kids = priced_world
    _offer, draft = _accepted(db, kids[0])
    assert draft.tax_rate_percent == 0
    route = db.query(InvoiceDraftTaxRoute).filter_by(draft_id=draft.id).one()
    assert (route.route_band, route.suggested_rate_percent, route.rate_required) == (
        "international",
        0,
        False,
    )
    view = drafts.view(db, draft)
    lines_total = drafts.subtotal_of(drafts.lines_of(draft))
    assert (view["tax_rate_percent"], view["tax_mode"], view["tax_rate_required"]) == (
        0,
        "included",
        False,
    )
    assert D(view["tax_cad"]) == 0 and D(view["total_cad"]) == lines_total
    assert view["tax_route"]["route_band"] == "international"
    assert view["allowed_tax_rates"] == [0, 5, 13, 14, 15]
    created = json.loads(_audits(db, "invoice.draft_created")[-1].detail_json)
    assert (created["tax_rate_percent"], created["tax_mode"]) == (0, "included")
    assert created["tax_route"]["route_band"] == "international"


@pytest.mark.parametrize(("province", "rate"), [("NS", 14), ("PE", 15), ("BC", 5), ("ON", 13)])
def test_a_domestic_draft_backs_the_province_rate_out_and_sends_it(
    db,
    priced_world,  # noqa: F811
    province,
    rate,
):
    _con, kids = priced_world
    _offer, draft = _accepted(db, _route(db, kids[1], "CA", "CA", province))
    assert draft.tax_rate_percent == rate
    view = drafts.view(db, draft)
    lines_total = drafts.subtotal_of(drafts.lines_of(draft))
    # DEC-0235: backed out line by line.
    tax = drafts.totals(drafts.lines_of(draft), rate, "included")[1]
    assert (D(view["subtotal_cad"]), D(view["tax_cad"]), D(view["total_cad"])) == (
        lines_total - tax,
        tax,
        lines_total,
    )
    assert view["tax_route"]["destination_province"] == province
    drafts.update_draft(db, draft, {"tax_confirmed": True}, expected_revision=1, actor=None)
    invoice = drafts.send(db, draft, expected_revision=1, actor=None)
    db.commit()
    assert (invoice.subtotal_cad, invoice.tax_cad, invoice.total_cad) == (
        lines_total - tax,
        tax,
        lines_total,
    )
    assert invoice.tax_status == f"gst_hst_{rate}"


# === 1c. The back-out, to the cent ===============================================================


@pytest.mark.parametrize(
    ("total", "rate", "tax"),
    [
        ("114.00", 14, "14.00"),
        ("100.00", 14, "12.28"),  # 12.2807 -> 12.28
        ("0.03", 14, "0.00"),  # 0.00368 -> 0.00
        # DEC-0235 (per line): net 0.04 -> tax 0.01, the net nudged to 0.03 (the whole-total
        # rule of DEC-0223 read 0.00491 -> 0.00).
        ("0.04", 14, "0.01"),
        ("0.05", 14, "0.01"),  # 0.00614 -> 0.01
        ("115.00", 15, "15.00"),
        ("100.00", 15, "13.04"),  # 13.0434 -> 13.04
        ("1.00", 15, "0.13"),  # 0.1304 -> 0.13
        ("0.07", 15, "0.01"),  # 0.00913 -> 0.01
        ("0.03", 15, "0.00"),  # 0.00391 -> 0.00
        ("999999.99", 15, "130434.78"),  # 130434.7813 -> .78
        ("10.00", 5, "0.48"),  # 0.4761 -> 0.48
        ("0.21", 5, "0.01"),  # 0.01 exactly
        # DEC-0235 (per line): net 0.10 -> tax 0.005 -> 0.01, the net nudged to 0.09 (the
        # whole-total rule read 0.00476 -> 0.00).
        ("0.10", 5, "0.01"),
        ("0.11", 5, "0.01"),  # 0.005238 -> 0.01 (above the half cent: up)
        ("250.00", 0, "0.00"),
    ],
)
def test_the_back_out_rounds_half_up_to_the_cent(total, rate, tax):
    subtotal, got_tax, got_total = drafts.totals(D(total), rate, "included")
    assert got_tax == D(tax) and got_total == D(total)
    assert subtotal == D(total) - D(tax)


# === 1d. Unknown province: staff choose ==========================================================


def test_an_unknown_province_leaves_the_rate_unset_until_staff_choose(
    db,
    priced_world,  # noqa: F811
    api_for,
):
    _con, kids = priced_world
    _offer, draft = _accepted(db, _route(db, kids[2], "CA", "CA", None))
    url = f"/api/v1/invoice-drafts/{draft.id}"
    ops = api_for(Role.OPERATIONS)
    view = ops.get(url).json()
    assert view["tax_rate_percent"] is None and view["tax_rate_required"] is True
    assert view["subtotal_cad"] is None and view["tax_cad"] is None and view["total_cad"] is None
    assert view["tax_route"]["route_band"] == "domestic"
    assert view["tax_route"]["destination_province"] is None
    assert view["tax_confirmed"] is False

    # No rate chosen: a save is refused (tax_rate_required), Send and Download too.
    refused = ops.patch(url, json={"expected_revision": 1, "tax_confirmed": True})
    assert refused.status_code == 422, refused.text
    assert refused.json()["detail"]["code"] == "tax_rate_required"
    assert refused.json()["field"] == "tax_rate_percent"
    assert ops.post(f"{url}/send", json={"expected_revision": 1}).json()["detail"]["code"] == (
        "tax_unconfirmed"
    )
    pdf = ops.get(f"{url}/pdf", params={"revision": 1})
    assert pdf.status_code == 422 and pdf.json()["detail"]["code"] == "tax_unconfirmed"

    # Choosing a rate needs the figures echoed, even 0 (the placeholder is never a rate).
    lines = view["lines"]
    unechoed = ops.patch(
        url, json={"expected_revision": 1, "tax_rate_percent": 0, "tax_confirmed": True}
    )
    assert unechoed.status_code == 422 and unechoed.json()["detail"]["code"] == "tax_unconfirmed"
    chosen = ops.patch(
        url,
        json={
            "expected_revision": 1,
            "tax_rate_percent": 13,
            "tax_confirmed": True,
            **shown_tax(lines, 13, "included"),
        },
    )
    assert chosen.status_code == 200, chosen.text
    body = chosen.json()
    assert (body["tax_rate_percent"], body["tax_rate_required"], body["tax_confirmed"]) == (
        13,
        False,
        True,
    )
    assert body["revision"] == 2 and body["total_cad"] is not None
    see_committed_changes(db)
    route = db.query(InvoiceDraftTaxRoute).filter_by(draft_id=draft.id).one()
    assert route.rate_chosen_at is not None and route.rate_chosen_by_user_id is not None
    changes = json.loads(_audits(db, "invoice.draft_edited")[-1].detail_json)["changes"]
    assert changes["tax_rate_percent"] == {"from": None, "to": 13}
    assert ops.get(f"{url}/pdf", params={"revision": 2}).status_code == 200
    sent = ops.post(f"{url}/send", json={"expected_revision": 2})
    assert sent.status_code == 200, sent.text


def test_choosing_zero_on_an_unknown_province_is_a_real_choice(db, priced_world):  # noqa: F811
    _con, kids = priced_world
    _offer, draft = _accepted(db, _route(db, kids[2], "CA", "CA", "Atlantis"))
    lines = drafts.lines_of(draft)
    drafts.update_draft(
        db,
        draft,
        {"tax_rate_percent": 0, "tax_confirmed": True, **shown_tax(lines, 0, "included")},
        expected_revision=1,
        actor=None,
    )
    db.commit()
    assert draft.revision == 2 and drafts.tax_confirmed(db, draft)
    assert drafts.view(db, draft)["tax_rate_percent"] == 0


# === 2. Allowed rates, the table, Admin ===========================================================


def test_a_draft_accepts_14_and_15_and_refuses_a_rate_outside_the_table(db, priced_world):  # noqa: F811
    _con, kids = priced_world
    _offer, draft = _accepted(db, kids[0])
    lines = drafts.lines_of(draft)
    for rate in (7, 16, -1, 100):
        with pytest.raises(ValidationError) as caught:
            drafts.update_draft(
                db,
                draft,
                {"tax_rate_percent": rate, "tax_confirmed": True, **shown_tax(lines, 0, "added")},
                expected_revision=draft.revision,
                actor=None,
            )
        assert caught.value.field == "tax_rate_percent"
        db.rollback()
    for rate in (14, 15):
        drafts.update_draft(
            db,
            draft,
            {"tax_rate_percent": rate, "tax_confirmed": True, **shown_tax(lines, rate, "included")},
            expected_revision=draft.revision,
            actor=None,
        )
        db.commit()
        assert draft.tax_rate_percent == rate


def test_the_manual_issue_path_keeps_0_5_13(db, priced_world):  # noqa: F811
    from tests.test_quote_offers import _finalize

    _con, kids = priced_world
    _finalize(db, kids[1])
    with pytest.raises(ValidationError, match=r"0%, 5% or 13%"):
        fs.issue_invoice(db, kids[1], actor=None, tax_rate_percent=14)
    db.rollback()
    invoice = fs.issue_invoice(db, kids[1], actor=None, tax_rate_percent=13)
    db.commit()
    assert invoice.tax_status == "gst_hst_13"
    assert invoice.total_cad == invoice.subtotal_cad + drafts.tax_of(invoice.subtotal_cad, 13)


def test_the_table_reads_defaults_without_rows_and_never_writes(db):
    assert db.query(TaxRate).count() == 0
    table = trs.rate_table(db)
    assert {code: (r.rate_percent, r.tax_label) for code, r in table.items()} == trs.DEFAULT_RATES
    assert db.query(TaxRate).count() == 0


def test_admin_views_and_edits_the_rates_audited_and_the_next_draft_follows(
    db,
    priced_world,  # noqa: F811
    api_for,
):
    # One client underneath: each role signs in right before it is used.
    ops = api_for(Role.OPERATIONS)
    listed = ops.get("/api/v1/finance/tax-rates")
    assert listed.status_code == 200, listed.text
    rows = {row["province_code"]: row for row in listed.json()["items"]}
    assert len(rows) == 13
    assert (rows["ON"]["rate_percent"], rows["ON"]["tax_label"]) == (13, "HST")
    assert rows["ON"]["province_name"] == "Ontario"
    assert (rows["NS"]["rate_percent"], rows["YT"]["tax_label"]) == (14, "GST")

    # Only Admin edits; Marketing (no financial:read) does not even read.
    assert ops.patch("/api/v1/finance/tax-rates/ON", json={"rate_percent": 15}).status_code == 403
    assert api_for(Role.MARKETING).get("/api/v1/finance/tax-rates").status_code == 403
    manager = api_for(Role.READ_ONLY_MANAGER)
    assert manager.get("/api/v1/finance/tax-rates").status_code == 200
    assert manager.patch("/api/v1/finance/tax-rates/ON", json={"rate_percent": 15}).status_code == (
        403
    )
    admin = api_for(Role.ADMIN)
    for bad in ({"rate_percent": 31}, {"rate_percent": -1}, {"tax_label": "VAT"}, {"x": 1}):
        assert admin.patch("/api/v1/finance/tax-rates/ON", json=bad).status_code == 422, bad
    assert admin.patch("/api/v1/finance/tax-rates/ZZ", json={"rate_percent": 5}).status_code == 404

    edited = admin.patch("/api/v1/finance/tax-rates/ON", json={"rate_percent": 15})
    assert edited.status_code == 200, edited.text
    after = {row["province_code"]: row for row in edited.json()["items"]}
    assert after["ON"]["rate_percent"] == 15 and after["ON"]["updated_by"]
    # A table rate outside 0/5/13/14/15 becomes allowed on drafts.
    seven = admin.patch("/api/v1/finance/tax-rates/YT", json={"rate_percent": 7})
    assert 7 in seven.json()["allowed_rates"]
    see_committed_changes(db)
    audits = _audits(db, "tax_rate.update")
    assert len(audits) == 2
    detail = json.loads(audits[0].detail_json)
    assert detail["changes"]["rate_percent"] == {"from": 13, "to": 15}
    # Saving the same value again writes nothing.
    assert admin.patch("/api/v1/finance/tax-rates/ON", json={"rate_percent": 15}).status_code == 200
    see_committed_changes(db)
    assert len(_audits(db, "tax_rate.update")) == 2

    _con, kids = priced_world
    _offer, draft = _accepted(db, _route(db, kids[0], "CA", "CA", "Ontario"))
    assert draft.tax_rate_percent == 15
    _offer, other = _accepted(db, _route(db, kids[1], "CA", "CA", "YT"))
    assert other.tax_rate_percent == 7
    assert 7 in drafts.view(db, other)["allowed_tax_rates"]


# === 3. Download needs the tax confirmed ==========================================================


def test_download_is_refused_like_send_until_the_saved_revision_is_confirmed(
    db,
    priced_world,  # noqa: F811
    api_for,
):
    _con, kids = priced_world
    _offer, draft = _accepted(db, kids[0])
    url = f"/api/v1/invoice-drafts/{draft.id}"
    ops = api_for(Role.OPERATIONS)
    refused = ops.get(f"{url}/pdf", params={"revision": 1})
    assert refused.status_code == 422, refused.text
    assert refused.json()["detail"]["code"] == "tax_unconfirmed"
    assert refused.json()["field"] == "tax_confirmed"
    sent = ops.post(f"{url}/send", json={"expected_revision": 1})
    assert sent.json()["detail"]["code"] == refused.json()["detail"]["code"]
    # The revision check still comes first.
    assert ops.get(f"{url}/pdf", params={"revision": 9}).status_code == 409

    assert ops.patch(url, json={"expected_revision": 1, "tax_confirmed": True}).status_code == 200
    ok = ops.get(f"{url}/pdf", params={"revision": 1})
    assert ok.status_code == 200 and ok.content.startswith(b"%PDF")

    # A revision moved on without a confirming save is unconfirmed again: no PDF.
    see_committed_changes(db)
    draft = drafts.get(db, draft.id)
    draft.revision += 1
    db.commit()
    again = ops.get(f"{url}/pdf", params={"revision": draft.revision})
    assert again.status_code == 422 and again.json()["detail"]["code"] == "tax_unconfirmed"
    assert db.query(CustomerInvoice).count() == 0
    assert db.query(InvoiceDraftTax).filter_by(draft_id=draft.id).one().confirmed_revision == 1


# === 4. Wording kept ==============================================================================


def test_the_customer_quote_wording_follows_the_invoice_rule():
    """Owner, 2026-10-23: the quote total stays "Tổng cộng" and the staff note label stays "Ghi
    chú từ Solaris Express". RC-UAT-21 (P-9 stand-in, pending Ben): the note that tax is added
    on the invoice is replaced by the invoice's GST/HST rule -- AS-38 in
    SUPERSEDED_ASSERTIONS.md."""
    vi = (REPO_ROOT / "frontend/src/account/i18n/vi.js").read_text(encoding="utf-8")
    en = (REPO_ROOT / "frontend/src/account/i18n/en.js").read_text(encoding="utf-8")
    assert "'quotes.colTotal': 'Tổng cộng'," in vi
    assert "'quotes.taxIncluded': 'Giá đã bao gồm {label} {rate} %'," in vi
    assert "'quotes.taxZeroRated': 'Thuế suất 0 (0 %)'," in vi
    assert "'detail.staffNote': 'Ghi chú từ Solaris Express'," in vi
    assert "'quotes.taxIncluded': 'Prices include {label} {rate} %'," in en
    assert "'quotes.taxZeroRated': 'Zero-rated (0 %)'," in en
    page = (REPO_ROOT / "frontend/src/account/pages/QuoteDetailPage.jsx").read_text(
        encoding="utf-8"
    )
    assert "quoteTaxSentence(t, data.tax)" in page


def test_the_customer_quote_view_still_says_tax_is_not_included(db, priced_world):  # noqa: F811
    from app.services import quote_offer_service as qos
    from tests.test_quote_offers import _finalize

    _con, kids = priced_world
    version = _finalize(db, kids[0])
    view = qos.build_customer_view(kids[0], version)
    assert view["tax_included"] is False


# === 5. The migration =============================================================================


def test_the_migration_adds_three_seeded_tables_alters_nothing_and_round_trips(tmp_path):
    import sqlite3

    from tests.test_migrations_phase13c import _alembic, _tables

    path = tmp_path / "m.db"
    url = f"sqlite:///{path.as_posix()}"
    assert _alembic(url, "upgrade", "e6b1c4a8d2f3").returncode == 0
    before = _tables(path)
    with sqlite3.connect(path) as c:
        schema_before = dict(c.execute("select name, sql from sqlite_master where sql is not null"))
    assert _alembic(url, "upgrade", "f7c2d9e3a1b5").returncode == 0
    assert "f7c2d9e3a1b5" in _alembic(url, "current").stdout
    new = {"tax_rates", "invoice_draft_tax_route", "fee_line_manual_prices"}
    assert _tables(path) - before == new
    with sqlite3.connect(path) as c:
        schema_after = dict(c.execute("select name, sql from sqlite_master where sql is not null"))
        rates = {
            code: (rate, label)
            for code, rate, label in c.execute(
                "select province_code, rate_percent, tax_label from tax_rates"
            )
        }
        route_fks = {
            r[3]: (r[2], r[6])
            for r in c.execute("pragma foreign_key_list(invoice_draft_tax_route)")
        }
        price_fks = {
            r[3]: (r[2], r[6]) for r in c.execute("pragma foreign_key_list(fee_line_manual_prices)")
        }
    for name, sql in schema_before.items():
        assert schema_after[name] == sql, name  # nothing existing altered
    assert rates == trs.DEFAULT_RATES
    assert route_fks["draft_id"] == ("invoice_drafts", "CASCADE")
    assert price_fks["fee_line_id"] == ("shipment_fee_lines", "CASCADE")
    # No `alembic check` here: below head it reports the later revisions' tables (RC-UAT-21
    # chain); the head is checked in test_migrations_phase13f.py.
    assert _alembic(url, "downgrade", "e6b1c4a8d2f3").returncode == 0
    assert new.isdisjoint(_tables(path))
    assert _alembic(url, "upgrade", "head").returncode == 0


# === 6. Review, 2026-10-24: a draft's own rate, whole rates, document labels ======================


def test_a_draft_keeps_its_saved_rate_after_the_table_changes(db, priced_world):  # noqa: F811
    _con, kids = priced_world
    db.add(TaxRate(province_code="YT", rate_percent=7, tax_label="GST", updated_at=fs.utcnow()))
    db.commit()
    _offer, draft = _accepted(db, _route(db, kids[0], "CA", "CA", "YT"))
    assert draft.tax_rate_percent == 7
    trs.update_rate(db, "YT", {"rate_percent": 5}, actor=None)
    db.commit()
    assert 7 not in trs.allowed_rates(db)
    view = drafts.view(db, draft)
    assert 7 in view["allowed_tax_rates"]  # the screen still offers the saved rate
    lines = drafts.lines_of(draft)
    drafts.update_draft(
        db,
        draft,
        {"tax_rate_percent": 7, "tax_confirmed": True, **shown_tax(lines, 7, "included")},
        expected_revision=1,
        actor=None,
    )
    db.commit()
    invoice = drafts.send(db, draft, expected_revision=draft.revision, actor=None)
    db.commit()
    assert invoice.tax_status == "gst_hst_7"
    # Another draft cannot pick 7 any more.
    _offer, other = _accepted(db, kids[1])
    with pytest.raises(ValidationError):
        drafts.update_draft(
            db,
            other,
            {"tax_rate_percent": 7, "tax_confirmed": True, **shown_tax(lines, 7, "included")},
            expected_revision=1,
            actor=None,
        )
    db.rollback()


@pytest.mark.parametrize("value", [13.5, "13.5", "13%", 12.999, "", "abc"])
def test_a_non_whole_rate_is_refused_not_truncated(db, priced_world, value):  # noqa: F811
    _con, kids = priced_world
    _offer, draft = _accepted(db, kids[0])
    with pytest.raises(ValidationError) as caught:
        drafts.update_draft(
            db,
            draft,
            {"tax_rate_percent": value, "tax_confirmed": True},
            expected_revision=1,
            actor=None,
        )
    assert caught.value.field == "tax_rate_percent"
    db.rollback()


def test_a_non_whole_rate_is_a_422_over_http(db, priced_world, api_for):  # noqa: F811
    _con, kids = priced_world
    _offer, draft = _accepted(db, kids[0])
    ops = api_for(Role.OPERATIONS)
    for value in (13.5, "13.5"):
        refused = ops.patch(
            f"/api/v1/invoice-drafts/{draft.id}",
            json={"expected_revision": 1, "tax_rate_percent": value, "tax_confirmed": True},
        )
        assert refused.status_code == 422, refused.text
    assert ops.get(f"/api/v1/invoice-drafts/{draft.id}").json()["tax_rate_percent"] == 0


def _send_confirmed(db, draft):
    drafts.update_draft(db, draft, {"tax_confirmed": True}, expected_revision=1, actor=None)
    invoice = drafts.send(db, draft, expected_revision=1, actor=None)
    db.commit()
    return invoice


def test_a_zero_rated_invoice_says_so_on_the_document_and_pdf(db, priced_world):  # noqa: F811
    from app.models import Customer
    from app.services import invoice_pdf_service as pdfs
    from tests.test_owner_answers_2026_10_22 import _pdf_text

    _con, kids = priced_world
    english = db.get(Customer, kids[0].customer_id)
    english.preferred_language = "en"
    db.commit()
    _offer, draft = _accepted(db, kids[0])
    # DEC-0235: each line's Tax column "Zero-rated", the summary row "GST @ 0%".
    draft_text = _pdf_text(pdfs.draft_pdf(db, draft))
    assert "Zero-rated" in draft_text and "GST @ 0%" in draft_text
    invoice = _send_confirmed(db, draft)
    document = fs.invoice_document(db, invoice)
    assert document["tax_line_label"] == "GST @ 0%"
    assert {line["tax_code"] for line in document["lines"]} == {"Zero-rated"}
    assert document["tax_included_note"] is None
    issued_text = _pdf_text(pdfs.invoice_pdf(db, invoice))
    assert "Zero-rated" in issued_text and "GST @ 0%" in issued_text
    # Vietnamese customer: English too (DEC-0235; it read "Thuế suất 0 (0 %)").
    _offer, vi_draft = _accepted(db, kids[2])
    vi_invoice = _send_confirmed(db, vi_draft)
    assert fs.invoice_document(db, vi_invoice)["tax_line_label"] == "GST @ 0%"
    # The manual path at 0 % reads the same.
    from tests.test_quote_offers import _finalize

    _finalize(db, kids[1])
    manual = fs.issue_invoice(db, kids[1], actor=None, tax_rate_percent=0)
    db.commit()
    assert fs.invoice_document(db, manual)["tax_line_label"] == "GST @ 0%"


@pytest.mark.parametrize(
    # DEC-0235: the summary row of the Solaris Invoicing layout (was "HST 14 %", "GST 5 %").
    ("province", "label", "line"),
    [("NS", "HST", "HST @ 14%"), ("BC", "GST", "GST @ 5%")],
)
def test_a_table_rate_prints_the_table_label(db, priced_world, province, label, line):  # noqa: F811
    _con, kids = priced_world
    _offer, draft = _accepted(db, _route(db, kids[0], "CA", "CA", province))
    assert drafts.view(db, draft)["tax_label"] == label
    document = fs.invoice_document(db, _send_confirmed(db, draft))
    assert (document["tax_label"], document["tax_line_label"]) == (label, line)
    # DEC-0235: no "Prices include" sentence on the new layout (the lines are before tax).
    assert document["tax_included_note"] is None


def test_a_rate_staff_changed_prints_gst_hst(db, priced_world):  # noqa: F811
    _con, kids = priced_world
    _offer, draft = _accepted(db, _route(db, kids[0], "CA", "CA", "NS"))
    lines = drafts.lines_of(draft)
    drafts.update_draft(
        db,
        draft,
        {"tax_rate_percent": 13, "tax_confirmed": True, **shown_tax(lines, 13, "included")},
        expected_revision=1,
        actor=None,
    )
    db.commit()
    assert drafts.view(db, draft)["tax_label"] == "GST/HST"
    invoice = drafts.send(db, draft, expected_revision=2, actor=None)
    db.commit()
    # DEC-0235: 13 % is "HST ON" whatever the label (was "GST/HST 13 %").
    assert fs.invoice_document(db, invoice)["tax_line_label"] == "HST ON @ 13%"
