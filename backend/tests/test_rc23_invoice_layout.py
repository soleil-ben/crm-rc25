"""RC-UAT-23: invoices follow the Solaris Invoicing desk rules (owner Ben, 2026-10-24;
DEC-0235), from the draft to the issued invoice and its PDF.

1. A domestic draft (NS 14 %, NB 15 %) works its GST/HST out **line by line**; the view carries
   the per-line breakdown and the summary rows; Send issues the same figures: each line stores
   its **net**, ``document_json`` the per-line facts and ``tax_layout: invoicing_v1``; subtotal
   = the nets, tax = the line taxes, total = what the customer pays. Revenue is the subtotal.
2. A surcharge stays its own line, at the base freight's tax treatment.
3. An international draft is zero-rated: each line "Zero-rated", the row "GST @ 0%".
4. The confirmation echo is checked against the per-line figures.
5. The PDF (draft and issued) is in English for every customer with no Vietnamese accented
   text at all; the columns, labels, company block, terms, payment and footer as the desk's.
6. The manual Issue invoice path adds the tax on top (its 0 / 5 / 13 picker), per line, on the
   new layout, with the quote lines' quantities.
7. An invoice issued before (no ``tax_layout``) reads and prints exactly as before.
8. "Net N days" when the finance settings give N > 0 due days.
"""

from __future__ import annotations

import io
import json
import unicodedata
from decimal import Decimal

import pytest
from pypdf import PdfReader

from app.core.enums import Role
from app.models import AuditEvent, Customer, CustomerInvoice, FinanceSettings, QuoteVersion
from app.services import finance_service as fs
from app.services import invoice_draft_service as drafts
from app.services import invoice_pdf_service as pdfs
from app.services import invoice_tax_math as tax_math
from app.services.errors import ValidationError
from tests.conftest import see_committed_changes, shown_tax
from tests.test_fixpack_f_lock_expiry_drafts import _accepted
from tests.test_quotes import _fee, priced_world  # noqa: F401 - fixture

D = Decimal
FOOTER = "Thank you for your business! We accept payment via E-transfer to info@solarisexpress.ca"
WIRE = (
    "Wire: Bank of Montreal, 2825 Eglinton Avenue West, Mississauga ON L5M 6J3 · SWIFT "
    "BOFMCAM2 · Account 1969380"
)
COMPANY_BLOCK = (
    "Solaris Express Inc.",
    "2446 Cawthra Rd Building 1 Unit 8, Mississauga ON L5A 3K6",
    "solarisexpressinc@gmail.com",
    "GST/HST BN: 795093756RT0001",
    "Currency: CAD",
    "Payment: E-transfer to info@solarisexpress.ca",
)
#: Vietnamese words the old layout printed, and the "included" sentence; none may appear.
NOT_ON_THE_NEW_LAYOUT = (
    "HÓA ĐƠN",
    "HOA DON",
    "Tạm tính",
    "Tong cong",
    "Prices include",
    "included",
    "bao gom",
    "Subtotal before",
)


def _route(db, shipment, origin, destination, province=None):
    shipment.origin_country_code = origin
    shipment.destination_country_code = destination
    shipment.sender_country_code = origin
    shipment.recipient_country_code = destination
    shipment.recipient_province_state = province
    shipment.recipient_postal_code = None
    db.commit()
    return shipment


def _pdf_text(content: bytes) -> str:
    assert content.startswith(b"%PDF")
    return "\n".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(content)).pages)


def _flat(text: str) -> str:
    return " ".join(text.split())


def _assert_plain_english(text: str) -> None:
    """No combining mark and no accented (non-ASCII) letter anywhere in the PDF's text."""
    for ch in text:
        assert not unicodedata.combining(ch), repr(ch)
        if ch.isalpha():
            assert ch.isascii(), repr(ch)
    for words in NOT_ON_THE_NEW_LAYOUT:
        assert words not in text, words


def _confirm_and_send(db, draft):
    drafts.update_draft(
        db, draft, {"tax_confirmed": True}, expected_revision=draft.revision, actor=None
    )
    db.commit()
    invoice = drafts.send(db, draft, expected_revision=draft.revision, actor=None)
    db.commit()
    return invoice


def _with_surcharge(db, shipment):
    _fee(db, shipment, "hcm_air", 14, description="Fake clothing")
    return shipment


# === 1 + 2. A domestic draft, line by line, sent as the same figures ============================


def test_a_nova_scotia_draft_is_backed_out_line_by_line_and_sent_as_nets(
    db,
    priced_world,  # noqa: F811
    api_for,
):
    _con, kids = priced_world
    shipment = _route(db, _with_surcharge(db, kids[1]), "CA", "CA", "NS")
    _offer, draft = _accepted(db, shipment)
    assert draft.tax_rate_percent == 14
    lines = drafts.lines_of(draft)
    assert len(lines) >= 2, lines  # base freight and the surcharge, each its own line

    view = drafts.view(db, draft)
    assert view["tax_layout"] == "invoicing_v1"
    amounts = [D(line["amount_cad"]) for line in lines]
    expected = [tax_math.line_tax(amount, 14, "included") for amount in amounts]
    assert [line["description"] for line in view["tax_lines"]] == [
        line["description"] for line in lines
    ]
    for shown, line, amount in zip(view["tax_lines"], expected, amounts, strict=True):
        assert (D(shown["net_cad"]), D(shown["tax_cad"])) == (line.net_cad, line.tax_cad)
        assert D(shown["net_cad"]) + D(shown["tax_cad"]) == amount == D(shown["gross_cad"])
        assert (shown["quantity"], shown["tax_code"]) == ("1", "HST 14%")
        assert D(shown["unit_price_cad"]) == line.net_cad
    subtotal = sum((line.net_cad for line in expected), D(0))
    tax = sum((line.tax_cad for line in expected), D(0))
    assert (D(view["subtotal_cad"]), D(view["tax_cad"]), D(view["total_cad"])) == (
        subtotal,
        tax,
        sum(amounts, D(0)),
    )
    assert view["tax_rows"] == [{"label": "HST @ 14%", "tax_cad": str(tax)}]
    # The API carries the same breakdown.
    body = api_for(Role.OPERATIONS).get(f"/api/v1/invoice-drafts/{draft.id}").json()
    assert body["tax_lines"] == view["tax_lines"] and body["tax_rows"] == view["tax_rows"]
    see_committed_changes(db)

    invoice = _confirm_and_send(db, draft)
    assert [line.amount_cad for line in invoice.lines] == [line.net_cad for line in expected]
    assert [line.quantity for line in invoice.lines] == [None] * len(lines)
    assert (invoice.subtotal_cad, invoice.tax_cad, invoice.total_cad) == (
        subtotal,
        tax,
        sum(amounts, D(0)),
    )
    assert invoice.tax_status == "gst_hst_14"
    stored = json.loads(invoice.document_json)
    assert stored["tax_layout"] == "invoicing_v1" and stored["tax_mode"] == "included"
    assert stored["tax_lines"] == [
        {"sequence": index, **line.as_dict()} for index, line in enumerate(expected, start=1)
    ]
    assert stored["tax_rows"] == view["tax_rows"]

    document = fs.invoice_document(db, invoice)
    assert document["tax_layout"] == "invoicing_v1"
    assert document["tax_included_note"] is None
    assert document["tax_line_label"] == "HST @ 14%"
    assert document["tax_rows"] == view["tax_rows"]
    assert [line["tax_code"] for line in document["lines"]] == ["HST 14%"] * len(lines)
    assert [line["amount_cad"] for line in document["lines"]] == [x.net_cad for x in expected]
    assert all(line["quantity"] == D(1) for line in document["lines"])
    assert document["payment_terms"] == "Due on receipt"
    assert document["company_name"] == "Solaris Express Inc."
    assert document["company_email"] == "solarisexpressinc@gmail.com"

    detail = api_for(Role.OPERATIONS).get(f"/api/v1/invoices/{invoice.id}").json()
    assert detail["tax_layout"] == "invoicing_v1"
    assert detail["tax_rows"] == [{"label": "HST @ 14%", "tax_cad": str(tax)}]
    assert [D(line["amount_cad"]) for line in detail["lines"]] == [x.net_cad for x in expected]
    assert [line["tax_code"] for line in detail["lines"]] == ["HST 14%"] * len(lines)
    assert [D(line["unit_price_cad"]) for line in detail["lines"]] == [
        x.unit_price_cad for x in expected
    ]
    assert [D(line["gross_cad"]) for line in detail["lines"]] == amounts
    customer_doc = api_for(Role.OPERATIONS).get(f"/api/v1/invoices/{invoice.id}/document")
    assert customer_doc.status_code == 200, customer_doc.text

    # Revenue is the pre-tax subtotal.
    report = fs.profitability(db, invoice.period_month)
    assert report["summary"]["revenue_cad"] == invoice.subtotal_cad == subtotal


def test_the_draft_keeps_each_surcharge_its_own_line_at_the_same_treatment(db, priced_world):  # noqa: F811
    _con, kids = priced_world
    shipment = _route(db, _with_surcharge(db, kids[2]), "CA", "CA", "NB")
    _offer, draft = _accepted(db, shipment)
    version = db.get(QuoteVersion, draft.quote_version_id)
    billed = [line for line in version.lines if line.revenue_cad and line.revenue_cad > 0]
    lines = drafts.lines_of(draft)
    assert len(billed) >= 2 and len(lines) == len(billed)
    assert [D(line["amount_cad"]) for line in lines] == [
        D(line.revenue_cad).quantize(D("0.01")) for line in billed
    ]
    view = drafts.view(db, draft)
    assert {line["tax_code"] for line in view["tax_lines"]} == {"HST 15%"}
    assert view["tax_rows"][0]["label"] == "HST @ 15%"
    for line in view["tax_lines"]:
        assert D(line["net_cad"]) + D(line["tax_cad"]) == D(line["gross_cad"])


# === 3. International: zero-rated ================================================================


def test_an_international_draft_is_zero_rated_line_by_line(db, priced_world):  # noqa: F811
    _con, kids = priced_world
    _offer, draft = _accepted(db, _with_surcharge(db, kids[0]))
    assert draft.tax_rate_percent == 0
    view = drafts.view(db, draft)
    assert {line["tax_code"] for line in view["tax_lines"]} == {"Zero-rated"}
    assert all(line["tax_cad"] == "0.00" for line in view["tax_lines"])
    assert view["tax_rows"] == [{"label": "GST @ 0%", "tax_cad": "0.00"}]
    invoice = _confirm_and_send(db, draft)
    assert invoice.tax_cad == 0 and invoice.subtotal_cad == invoice.total_cad
    assert [line.amount_cad for line in invoice.lines] == [
        D(line["amount_cad"]) for line in drafts.lines_of(draft)
    ]
    document = fs.invoice_document(db, invoice)
    assert document["tax_line_label"] == "GST @ 0%"
    text = _pdf_text(pdfs.invoice_pdf(db, invoice))
    assert "Zero-rated" in text and "GST @ 0%" in text
    _assert_plain_english(text)


# === 4. The confirmation echo ====================================================================


def test_the_echo_is_checked_against_the_per_line_figures(db, priced_world, api_for):  # noqa: F811
    _con, kids = priced_world
    _offer, draft = _accepted(db, _route(db, kids[1], "CA", "CA", "ON"))
    url = f"/api/v1/invoice-drafts/{draft.id}"
    ops = api_for(Role.OPERATIONS)
    lines = [
        {"description": "Courier, box 1", "amount_cad": "0.10"},
        {"description": "Courier, box 2", "amount_cad": "0.10"},
    ]
    change = {
        "expected_revision": 1,
        "tax_mode": "added",
        "tax_rate_percent": 5,
        "lines": lines,
        "total_change_reason": "two small boxes",
        "tax_confirmed": True,
    }
    # The whole-total rule would show 0.21 (0.20 + 0.01); per line it is 0.22 (0.01 each).
    stale = ops.patch(
        url,
        json={
            **change,
            "confirmed_total_cad": "0.21",
            "confirmed_tax_mode": "added",
            "confirmed_tax_rate_percent": 5,
        },
    )
    assert stale.status_code == 422 and stale.json()["detail"]["total_cad"] == "0.22"
    assert shown_tax(lines, 5, "added")["confirmed_total_cad"] == "0.22"
    saved = ops.patch(url, json={**change, **shown_tax(lines, 5, "added")})
    assert saved.status_code == 200, saved.text
    body = saved.json()
    assert (body["subtotal_cad"], body["tax_cad"], body["total_cad"]) == ("0.20", "0.02", "0.22")
    assert [line["tax_code"] for line in body["tax_lines"]] == ["GST", "GST"]
    assert body["tax_rows"] == [{"label": "GST @ 5%", "tax_cad": "0.02"}]
    see_committed_changes(db)
    audit = (
        db.query(AuditEvent)
        .filter_by(action="invoice.draft_tax_confirmed")
        .order_by(AuditEvent.id.desc())
        .first()
    )
    assert json.loads(audit.detail_json)["total_cad"] == "0.22"
    sent = ops.post(f"{url}/send", json={"expected_revision": 2})
    assert sent.status_code == 200, sent.text
    see_committed_changes(db)
    invoice = db.get(CustomerInvoice, sent.json()["invoice_id"])
    assert (invoice.subtotal_cad, invoice.tax_cad, invoice.total_cad) == (
        D("0.20"),
        D("0.02"),
        D("0.22"),
    )


# === 5. The PDF: English, no accents, the desk's labels ==========================================


def test_the_pdf_is_english_without_accents_for_a_vietnamese_customer(db, priced_world):  # noqa: F811
    _con, kids = priced_world
    shipment = _route(db, kids[1], "CA", "CA", "NS")
    customer = db.get(Customer, shipment.customer_id)
    assert customer.preferred_language != "en"  # the Vietnamese default
    _offer, draft = _accepted(db, shipment)
    lines = [
        {**line, "description": f"Cước vận chuyển {index} - Đà Nẵng"}
        for index, line in enumerate(drafts.lines_of(draft), start=1)
    ]
    drafts.update_draft(
        db,
        draft,
        {
            "bill_to_name": "Nguyễn Văn Đức",
            "bill_to_address": "12 Đường Lê Lợi\nHalifax NS B3H 1A1",
            "customer_reference": "ĐH-Ưu-01",
            "notes": "Cảm ơn quý khách đã tin tưởng",
            "lines": lines,
            "tax_confirmed": True,
            **shown_tax(lines, 14, "included"),
        },
        expected_revision=1,
        actor=None,
    )
    db.commit()

    draft_text = _pdf_text(pdfs.draft_pdf(db, draft))
    invoice = drafts.send(db, draft, expected_revision=draft.revision, actor=None)
    db.commit()
    issued_text = _pdf_text(pdfs.invoice_pdf(db, invoice))
    for text in (draft_text, issued_text):
        _assert_plain_english(text)
        flat = _flat(text)
        for words in COMPANY_BLOCK:
            assert words in flat, words
        assert FOOTER in flat
        assert _flat(WIRE) in flat
        assert "Terms: Due on receipt" in flat
        assert "INVOICE" in flat
        for heading in ("Description", "Qty", "Rate", "Amount", "Tax", "Subtotal"):
            assert heading in flat, heading
        assert "Total (CAD)" in flat
        assert "HST 14%" in flat and "HST @ 14%" in flat
        assert "Nguyen Van Duc" in flat
        assert "12 Duong Le Loi" in flat
        assert "DH-Uu-01" in flat
        assert "Cam on quy khach da tin tuong" in flat
        assert "Cuoc van chuyen 1 - Da Nang" in flat
        assert "Soleil Global" not in flat
    assert "DRAFT" in draft_text and "Assigned when the invoice is sent" in _flat(draft_text)
    assert invoice.public_id in issued_text
    for figure in invoice.lines:
        assert f"{figure.amount_cad:,.2f}" in issued_text
    assert f"{invoice.subtotal_cad:,.2f}" in issued_text
    assert f"{invoice.total_cad:,.2f}" in issued_text


def test_plain_strips_every_vietnamese_mark():
    assert pdfs.plain("Nguyễn Văn Đức, Hồ Chí Minh, Ưu, ơ, đ") == (
        "Nguyen Van Duc, Ho Chi Minh, Uu, o, d"
    )
    sample = "ÀÁẢÃẠĂẰẮẲẴẶÂẦẤẨẪẬĐÈÉẺẼẸÊỀẾỂỄỆÌÍỈĨỊÒÓỎÕỌÔỒỐỔỖỘƠỜỚỞỠỢÙÚỦŨỤƯỪỨỬỮỰỲÝỶỸỴ"
    for ch in pdfs.plain(sample + sample.lower()):
        assert ch.isascii() and not unicodedata.combining(ch)


# === 6. The manual path: added on top, per line, new layout ======================================


def test_the_manual_issue_path_adds_the_tax_per_line_on_the_new_layout(db, priced_world):  # noqa: F811
    from tests.test_quote_offers import _finalize

    _con, kids = priced_world
    version = _finalize(db, _with_surcharge(db, kids[1]))
    with pytest.raises(ValidationError):
        fs.issue_invoice(db, kids[1], actor=None, tax_rate_percent=14)
    db.rollback()
    invoice = fs.issue_invoice(db, kids[1], actor=None, tax_rate_percent=13)
    db.commit()
    billed = [line for line in version.lines if line.revenue_cad and line.revenue_cad > 0]
    expected = [
        tax_math.line_tax(line.revenue_cad, 13, "added", quantity=line.quantity) for line in billed
    ]
    assert [line.amount_cad for line in invoice.lines] == [
        D(line.revenue_cad).quantize(D("0.01")) for line in billed
    ]
    assert [line.quantity for line in invoice.lines] == [line.quantity for line in billed]
    assert invoice.subtotal_cad == sum((x.net_cad for x in expected), D(0))
    assert invoice.tax_cad == sum((x.tax_cad for x in expected), D(0))
    assert invoice.total_cad == invoice.subtotal_cad + invoice.tax_cad
    stored = json.loads(invoice.document_json)
    assert (stored["tax_layout"], stored["tax_mode"]) == ("invoicing_v1", "added")
    assert [row["unit_price_cad"] for row in stored["tax_lines"]] == [
        str(x.unit_price_cad) for x in expected
    ]
    document = fs.invoice_document(db, invoice)
    assert document["tax_mode"] == "added" and document["tax_included_note"] is None
    assert document["tax_line_label"] == "HST ON @ 13%"
    text = _flat(_pdf_text(pdfs.invoice_pdf(db, invoice)))
    assert "HST ON @ 13%" in text and "HST ON" in text
    _assert_plain_english(text)


# === 7. An invoice issued before keeps its figures and its print ==================================


def _make_legacy(db, invoice: CustomerInvoice, *, language: str) -> CustomerInvoice:
    """What an included-mode invoice issued before DEC-0235 holds: gross lines, the tax backed
    out of the whole total, no ``tax_layout``."""
    document = json.loads(invoice.document_json)
    for key in ("tax_layout", "tax_lines", "tax_rows"):
        document.pop(key)
    facts = {row["sequence"]: row for row in json.loads(invoice.document_json)["tax_lines"]}
    for line in invoice.lines:
        line.amount_cad = D(facts[line.sequence]["gross_cad"])
    total = sum((line.amount_cad for line in invoice.lines), D(0))
    tax = drafts.included_tax_of(total, 13)
    invoice.subtotal_cad, invoice.tax_cad, invoice.total_cad = total - tax, tax, total
    invoice.document_json = json.dumps(document, ensure_ascii=False)
    db.get(Customer, invoice.customer_id).preferred_language = language
    db.commit()
    return invoice


def test_an_invoice_issued_before_reads_and_prints_as_before(db, priced_world, api_for):  # noqa: F811
    _con, kids = priced_world
    _offer, draft = _accepted(db, _route(db, _with_surcharge(db, kids[1]), "CA", "CA", "ON"))
    invoice = _make_legacy(db, _confirm_and_send(db, draft), language="en")
    stored = (invoice.subtotal_cad, invoice.tax_cad, invoice.total_cad, invoice.document_json)
    gross = [line.amount_cad for line in invoice.lines]

    document = fs.invoice_document(db, invoice)
    assert document["tax_layout"] is None and document["tax_rows"] is None
    assert document["tax_included_note"] == "Prices include HST 13 %"
    assert document["tax_line_label"] == "HST 13 %"
    assert [line["amount_cad"] for line in document["lines"]] == gross
    assert all("tax_code" not in line for line in document["lines"])
    assert (document["subtotal_cad"], document["tax_cad"], document["total_cad"]) == stored[:3]
    detail = api_for(Role.OPERATIONS).get(f"/api/v1/invoices/{invoice.id}").json()
    assert detail["tax_layout"] is None and detail["tax_rows"] is None
    assert [D(line["amount_cad"]) for line in detail["lines"]] == gross
    assert all(line["tax_code"] is None for line in detail["lines"])

    text = _pdf_text(pdfs.invoice_pdf(db, invoice))
    assert "Prices include HST 13 %" in text
    assert "Subtotal before GST/HST" in text and "Amount (CAD)" in text
    assert "Solaris Express Inc." in text  # today's company details
    # Reading never rewrites it.
    see_committed_changes(db)
    again = db.get(CustomerInvoice, invoice.id)
    assert (again.subtotal_cad, again.tax_cad, again.total_cad, again.document_json) == stored
    assert [line.amount_cad for line in again.lines] == gross

    # A Vietnamese customer's older invoice keeps its Vietnamese labels.
    db.get(Customer, invoice.customer_id).preferred_language = "vi"
    db.commit()
    assert fs.invoice_document(db, invoice)["tax_included_note"] == "Giá đã bao gồm HST 13 %"
    assert "HÓA ĐƠN" in _pdf_text(pdfs.invoice_pdf(db, invoice))


# === 8. Terms =====================================================================================


def test_terms_read_net_n_days_when_the_settings_give_due_days(db, priced_world):  # noqa: F811
    _con, kids = priced_world
    db.add(
        FinanceSettings(invoice_due_days=15, tax_status="review_pending", updated_at=fs.utcnow())
    )
    db.commit()
    _offer, draft = _accepted(db, kids[2])
    drafts.update_draft(db, draft, {"tax_confirmed": True}, expected_revision=1, actor=None)
    db.commit()
    assert "Terms: Net 15 days" in _flat(_pdf_text(pdfs.draft_pdf(db, draft)))
    invoice = drafts.send(db, draft, expected_revision=1, actor=None)
    db.commit()
    assert fs.invoice_document(db, invoice)["payment_terms"] == "Net 15 days"
    assert "Terms: Net 15 days" in _flat(_pdf_text(pdfs.invoice_pdf(db, invoice)))
    assert fs.payment_terms(0) == "Due on receipt"
