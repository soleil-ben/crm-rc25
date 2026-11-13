"""Invoice PDFs, drawn on the server with ReportLab (owner decision 9a, 2026-10-21).

**The Solaris Invoicing layout** (owner Ben, 2026-10-24; DEC-0235) is what every draft and
every invoice issued from now on prints (``tax_layout: invoicing_v1``):

* **English only**, for every customer, and **no Vietnamese accented text at all**: every
  printed string (bill-to, address, descriptions, notes, PO) passes through ``plain`` (NFKD,
  combining marks dropped, đ -> d, Đ -> D);
* the company block -- Solaris Express Inc., 2446 Cawthra Rd Building 1 Unit 8, Mississauga ON
  L5A 3K6, solarisexpressinc@gmail.com, GST/HST BN 795093756RT0001 -- with the Terms ("Due on
  receipt" when the due date is the issue date, else "Net N days") and "Currency: CAD";
* the columns Description | Qty | Rate | Amount | Tax (Qty blank -> 1, Rate to 4 decimals,
  Amount before tax, Tax the line's code: "HST ON", "GST", "Zero-rated", ...);
* the summary Subtotal, one row per tax code ("HST ON @ 13%", "GST @ 0%"), Total (CAD); no
  "Prices include" sentence;
* how to pay (E-transfer, wire) and the footer "Thank you for your business! We accept payment
  via E-transfer to info@solarisexpress.ca" on every page.

An invoice issued before (no ``tax_layout``) prints with the layout below, as it always did
(only the company's details are today's).

Two documents, one layout:

* a **draft** (``GET /invoice-drafts/{id}/pdf``): the saved draft, with no invoice number
  (it is assigned on Send) and a large diagonal **DRAFT** watermark on every page;
* an **issued** invoice (``GET /invoices/{id}/pdf``): the numbered invoice as issued, from
  ``finance_service.invoice_document`` -- no watermark.

Both carry the company's details as on every invoice (OD-64: legal name, BN 795093756RT0001,
2446 Cawthra Road B1U8, Mississauga ON L5A 3K6), the bill-to, the lines, GST/HST, the total
and the due date. When the prices include the GST/HST (owner, 2026-10-22) both print "Prices
include GST/HST 13 %" ("Giá đã bao gồm GST/HST 13 %") beside the totals.
Every line description passes through ``customer_labels`` so no vendor name reaches the
customer (a label naming a vendor is replaced whole; the staff-typed bill-to, PO and notes
have only the vendor's words replaced). Revenue only: no cost, margin, exchange rate or master.
Long content continues on further pages; a void invoice is watermarked VOID.

The labels are in the customer's language (Vietnamese unless the customer chose English),
with the vendored Unicode font ``label_service`` embeds for Vietnamese diacritics.
"""

from __future__ import annotations

import io
import unicodedata
from datetime import datetime
from decimal import Decimal
from typing import Any

from reportlab.lib.pagesizes import LETTER
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas

from app.services import customer_labels, invoice_tax_math
from app.services.label_service import FONT_BOLD, FONT_REGULAR, register_fonts

LABELS = {
    "en": {
        "title": "INVOICE",
        "number": "Invoice number",
        "pending_number": "Assigned when the invoice is sent",
        "issued": "Issued",
        "due": "Due",
        "bill_to": "Bill to",
        "shipment": "Shipment",
        "service": "Service",
        "reference": "Your reference / PO",
        "description": "Description",
        "amount": "Amount (CAD)",
        "subtotal": "Subtotal",
        "subtotal_before_tax": "Subtotal before GST/HST",
        "tax": "GST/HST",
        "total": "Total",
        "notes": "Notes",
        "bn": "Business number",
        "watermark_note": "Not an invoice yet: this is a draft for review.",
    },
    "vi": {
        "title": "HÓA ĐƠN",
        "number": "Số hóa đơn",
        "pending_number": "Được cấp khi gửi hóa đơn",
        "issued": "Ngày lập",
        "due": "Hạn thanh toán",
        "bill_to": "Người thanh toán",
        "shipment": "Lô hàng",
        "service": "Dịch vụ",
        "reference": "Mã tham chiếu / PO của bạn",
        "description": "Mô tả",
        "amount": "Số tiền (CAD)",
        "subtotal": "Tạm tính",
        "subtotal_before_tax": "Tạm tính trước GST/HST",
        "tax": "GST/HST",
        "total": "Tổng cộng",
        "notes": "Ghi chú",
        "bn": "Mã số doanh nghiệp",
        "watermark_note": "Chưa phải hóa đơn: đây là bản nháp để xem lại.",
    },
}
WATERMARK = "DRAFT"
VOID_WATERMARK = "VOID"


def _money(value: Any) -> str:
    return f"{Decimal(str(value or 0)).quantize(Decimal('0.01')):,.2f}"


def _date(value: datetime | None) -> str:
    return value.date().isoformat() if value else "—"


def _wrap(text: str, width: float, measure) -> list[str]:
    """Lines of ``text`` no wider than ``width`` points; a word too long for one line (a URL,
    a reference with no spaces) is broken across lines instead of running off the page."""
    out: list[str] = []
    for paragraph in (text or "").splitlines() or [""]:
        line = ""
        for word in paragraph.split():
            while measure(word) > width:
                if line:
                    out.append(line)
                    line = ""
                cut = len(word) - 1
                while cut > 1 and measure(word[:cut]) > width:
                    cut -= 1
                out.append(word[:cut])
                word = word[cut:]
            candidate = f"{line} {word}".strip()
            if measure(candidate) > width and line:
                out.append(line)
                line = word
            else:
                line = candidate
        out.append(line)
    return out


def render(document: dict[str, Any], *, draft: bool, vendor_names: tuple[str, ...]) -> bytes:
    """Draw ``document`` (see ``draft_document`` / ``issued_document``) and return PDF bytes:
    the Solaris Invoicing layout when the document has one (DEC-0235), else the older one."""
    if document.get("tax_layout") == invoice_tax_math.LAYOUT:
        return _render_invoicing(document, draft=draft, vendor_names=vendor_names)
    return _render_legacy(document, draft=draft, vendor_names=vendor_names)


def _render_legacy(
    document: dict[str, Any], *, draft: bool, vendor_names: tuple[str, ...]
) -> bytes:
    """The layout of an invoice issued before DEC-0235, unchanged.

    Long notes and many lines continue on further pages (each with the header and, for a draft
    or a void invoice, the watermark). A voided invoice is watermarked VOID.
    """
    register_fonts()
    language = "en" if document.get("language") == "en" else "vi"
    words = LABELS[language]
    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=LETTER, pageCompression=0)
    pdf.setTitle(f"{words['title']} {document.get('invoice_number') or WATERMARK}")
    pdf.setAuthor(document["company_name"])
    width, height = LETTER
    left, right = 0.75 * inch, width - 0.75 * inch
    bottom = 1.0 * inch
    mark = WATERMARK if draft else (VOID_WATERMARK if document.get("status") == "void" else None)

    def text(value: Any) -> str:
        # Staff-typed free text: only the words naming a vendor are replaced (DEC-0222).
        return customer_labels.customer_safe_text(value, vendor_names, language=language) or ""

    def wrap(value: str, font: str, size: float, room: float) -> list[str]:
        return _wrap(value, room, lambda part: pdf.stringWidth(part, font, size))

    def watermark() -> None:
        if not mark:
            return
        pdf.saveState()
        pdf.setFillColorRGB(0.85, 0.85, 0.85)
        pdf.setFont(FONT_BOLD, 120)
        pdf.translate(width / 2, height / 2)
        pdf.rotate(40)
        pdf.drawCentredString(0, -40, mark)
        pdf.restoreState()

    def header() -> float:
        watermark()
        y = height - 0.8 * inch
        pdf.setFillColorRGB(0, 0, 0)
        pdf.setFont(FONT_BOLD, 16)
        pdf.drawString(left, y, document["company_name"])
        pdf.setFont(FONT_REGULAR, 9)
        pdf.drawString(left, y - 14, document["company_trade_name"])
        pdf.drawString(left, y - 26, document["company_address"])
        pdf.drawString(left, y - 38, f"{words['bn']}: {document['company_business_number']}")
        pdf.setFont(FONT_BOLD, 20)
        pdf.drawRightString(right, y, words["title"])
        pdf.setFont(FONT_REGULAR, 9)
        number = document.get("invoice_number") or words["pending_number"]
        pdf.drawRightString(right, y - 16, f"{words['number']}: {number}")
        pdf.drawRightString(right, y - 28, f"{words['issued']}: {_date(document.get('issued_at'))}")
        pdf.drawRightString(right, y - 40, f"{words['due']}: {_date(document.get('due_at'))}")
        if draft:
            pdf.setFont(FONT_REGULAR, 8)
            pdf.drawString(left, 0.6 * inch, words["watermark_note"])
        return y - 70

    state = {"y": header()}

    def room_for(needed: float, font: str = FONT_REGULAR, size: float = 10) -> float:
        """The current y, after starting a new page when ``needed`` points do not fit."""
        if state["y"] - needed < bottom:
            pdf.showPage()
            state["y"] = header()
            pdf.setFont(font, size)
        return state["y"]

    half = (right - left) / 2 - 12
    y = top = state["y"]
    pdf.setFont(FONT_BOLD, 10)
    pdf.drawString(left, y, words["bill_to"])
    bill_lines = [
        *wrap(text(document.get("bill_to_name")), FONT_REGULAR, 10, half),
        *wrap(text(document.get("bill_to_address")), FONT_REGULAR, 10, half),
    ]
    bill_lines = [line for line in bill_lines if line]
    pdf.setFont(FONT_REGULAR, 10)
    facts = [
        (words["shipment"], document.get("shipment_reference")),
        (words["service"], document.get("service")),
        (words["reference"], text(document.get("purchase_order_reference"))),
    ]
    fact_lines = [
        line
        for label, value in facts
        if value
        for line in wrap(f"{label}: {value}", FONT_REGULAR, 10, half)
    ]
    for index, line in enumerate(fact_lines):
        pdf.drawRightString(right, y - 14 * index, line)
    state["y"] = y - 14
    for line in bill_lines:
        y = room_for(14)
        pdf.drawString(left, y, line)
        state["y"] = y - 14
    state["y"] = min(state["y"], top - 14 * len(fact_lines)) - 24

    def table_head() -> None:
        y = room_for(40, FONT_BOLD, 10)
        pdf.setFont(FONT_BOLD, 10)
        pdf.drawString(left, y, words["description"])
        pdf.drawRightString(right, y, words["amount"])
        pdf.line(left, y - 4, right, y - 4)
        state["y"] = y - 20
        pdf.setFont(FONT_REGULAR, 10)

    table_head()
    for line in document.get("lines", []):
        description = customer_labels.customer_safe_label(
            line.get("description"), vendor_names, language=language
        )
        wrapped = wrap(description, FONT_REGULAR, 10, right - left - 110)
        if state["y"] - 13 * len(wrapped) < bottom:
            pdf.showPage()
            state["y"] = header()
            table_head()
        y = state["y"]
        for index, part in enumerate(wrapped):
            pdf.drawString(left, y - 13 * index, part)
        pdf.drawRightString(right, y, _money(line.get("amount_cad")))
        state["y"] = y - (13 * len(wrapped) + 6)
    y = room_for(96)
    pdf.line(left, y + 2, right, y + 2)
    y -= 16
    included_note = document.get("tax_included_note")
    totals = [
        (
            words["subtotal_before_tax"] if included_note else words["subtotal"],
            document.get("subtotal_cad"),
        ),
        (
            document.get("tax_line_label") or f"{words['tax']} {document.get('tax_percent', 0)}%",
            document.get("tax_cad"),
        ),
    ]
    pdf.setFont(FONT_REGULAR, 10)
    if included_note:
        # Owner, 2026-10-22: the line amounts are all-in; say so beside the totals.
        pdf.drawRightString(right, y, included_note)
        y -= 16
    for label, value in totals:
        pdf.drawRightString(right - 120, y, label)
        pdf.drawRightString(right, y, _money(value))
        y -= 14
    pdf.setFont(FONT_BOLD, 11)
    pdf.drawRightString(right - 120, y, f"{words['total']} ({document.get('currency', 'CAD')})")
    pdf.drawRightString(right, y, _money(document.get("total_cad")))
    state["y"] = y - 28
    notes = text(document.get("notes"))
    if notes:
        y = room_for(30, FONT_BOLD, 10)
        pdf.setFont(FONT_BOLD, 10)
        pdf.drawString(left, y, words["notes"])
        state["y"] = y - 13
        pdf.setFont(FONT_REGULAR, 10)
        for part in wrap(notes, FONT_REGULAR, 10, right - left):
            y = room_for(13)
            pdf.drawString(left, y, part)
            state["y"] = y - 13
    pdf.showPage()
    pdf.save()
    return buffer.getvalue()


# --- The Solaris Invoicing layout (DEC-0235) -----------------------------------------------------

#: English only, for every customer (DEC-0235).
INVOICING_LABELS = {
    "title": "INVOICE",
    "number": "Invoice number",
    "pending_number": "Assigned when the invoice is sent",
    "issued": "Issued",
    "due": "Due",
    "terms": "Terms",
    "currency": "Currency",
    "bn": "GST/HST BN",
    "bill_to": "Bill to",
    "shipment": "Shipment",
    "service": "Service",
    "reference": "Your reference / PO",
    "description": "Description",
    "quantity": "Qty",
    "rate": "Rate",
    "amount": "Amount",
    "tax": "Tax",
    "subtotal": "Subtotal",
    "total": "Total",
    "notes": "Notes",
    "payment": "Payment: E-transfer to {email}",
    "wire": "Wire: {wire}",
    "watermark_note": "Not an invoice yet: this is a draft for review.",
}
_LETTER_MAP = str.maketrans({"đ": "d", "Đ": "D"})


def plain(value: Any) -> str:
    """``value`` without diacritics (DEC-0235): NFKD, combining marks dropped, đ -> d, Đ -> D
    ("Nguyễn Văn Đức" -> "Nguyen Van Duc")."""
    text = unicodedata.normalize("NFKD", str(value or "").translate(_LETTER_MAP))
    return "".join(ch for ch in text if not unicodedata.combining(ch))


def _quantity(value: Any) -> str:
    """Qty as written ("60", "12.5"); blank reads as 1 (DEC-0235)."""
    if value in (None, ""):
        return "1"
    number = Decimal(str(value))
    return format(number.normalize(), "f") if number else "1"


def _unit(value: Any) -> str:
    return f"{Decimal(str(value or 0)).quantize(Decimal('0.0001')):,.4f}"


def _render_invoicing(
    document: dict[str, Any], *, draft: bool, vendor_names: tuple[str, ...]
) -> bytes:
    """The Solaris Invoicing layout (DEC-0235): see the module docstring. Long content continues
    on further pages, each with the header, the footer and any watermark."""
    register_fonts()
    words = INVOICING_LABELS
    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=LETTER, pageCompression=0)
    pdf.setTitle(f"{words['title']} {document.get('invoice_number') or WATERMARK}")
    pdf.setAuthor(plain(document["company_name"]))
    width, height = LETTER
    left, right = 0.75 * inch, width - 0.75 * inch
    bottom = 1.1 * inch
    mark = WATERMARK if draft else (VOID_WATERMARK if document.get("status") == "void" else None)
    # Column right edges: Tax, Amount, Rate, Qty; the description wraps left of Qty.
    tax_x, amount_x, rate_x, qty_x = right, right - 78, right - 158, right - 226
    description_room = qty_x - 40 - left

    def text(value: Any) -> str:
        # Staff-typed free text: only the words naming a vendor are replaced (DEC-0222).
        return plain(customer_labels.customer_safe_text(value, vendor_names, language="en"))

    def put(x: float, y: float, value: Any) -> None:
        pdf.drawString(x, y, plain(value))

    def put_right(x: float, y: float, value: Any) -> None:
        pdf.drawRightString(x, y, plain(value))

    def wrap(value: str, font: str, size: float, room: float) -> list[str]:
        return _wrap(plain(value), room, lambda part: pdf.stringWidth(part, font, size))

    def watermark() -> None:
        if not mark:
            return
        pdf.saveState()
        pdf.setFillColorRGB(0.85, 0.85, 0.85)
        pdf.setFont(FONT_BOLD, 120)
        pdf.translate(width / 2, height / 2)
        pdf.rotate(40)
        pdf.drawCentredString(0, -40, mark)
        pdf.restoreState()

    def header() -> float:
        watermark()
        y = height - 0.8 * inch
        pdf.setFillColorRGB(0, 0, 0)
        pdf.setFont(FONT_BOLD, 14)
        put(left, y, document["company_name"])
        pdf.setFont(FONT_REGULAR, 9)
        put(left, y - 14, document["company_address"])
        put(left, y - 26, document.get("company_email"))
        put(left, y - 38, f"{words['bn']}: {document['company_business_number']}")
        pdf.setFont(FONT_BOLD, 20)
        put_right(right, y, words["title"])
        pdf.setFont(FONT_REGULAR, 9)
        number = document.get("invoice_number") or words["pending_number"]
        facts = (
            f"{words['number']}: {number}",
            f"{words['issued']}: {_date(document.get('issued_at'))}",
            f"{words['due']}: {_date(document.get('due_at'))}",
            f"{words['terms']}: {document.get('payment_terms') or 'Due on receipt'}",
            f"{words['currency']}: {document.get('currency') or 'CAD'}",
        )
        for index, fact in enumerate(facts):
            put_right(right, y - 16 - 12 * index, fact)
        pdf.setFont(FONT_REGULAR, 8)
        pdf.drawCentredString(width / 2, 0.5 * inch, plain(document["footer"]))
        if draft:
            put(left, 0.7 * inch, words["watermark_note"])
        return y - 16 - 12 * len(facts) - 18

    state = {"y": header()}

    def room_for(needed: float, font: str = FONT_REGULAR, size: float = 10) -> float:
        """The current y, after starting a new page when ``needed`` points do not fit."""
        if state["y"] - needed < bottom:
            pdf.showPage()
            state["y"] = header()
            pdf.setFont(font, size)
        return state["y"]

    half = (right - left) / 2 - 12
    y = top = state["y"]
    pdf.setFont(FONT_BOLD, 10)
    put(left, y, words["bill_to"])
    bill_lines = [
        *wrap(text(document.get("bill_to_name")), FONT_REGULAR, 10, half),
        *wrap(text(document.get("bill_to_address")), FONT_REGULAR, 10, half),
    ]
    bill_lines = [line for line in bill_lines if line]
    pdf.setFont(FONT_REGULAR, 10)
    facts = [
        (words["shipment"], document.get("shipment_reference")),
        (words["service"], document.get("service")),
        (words["reference"], text(document.get("purchase_order_reference"))),
    ]
    fact_lines = [
        line
        for label, value in facts
        if value
        for line in wrap(f"{label}: {value}", FONT_REGULAR, 10, half)
    ]
    for index, line in enumerate(fact_lines):
        put_right(right, y - 14 * index, line)
    state["y"] = y - 14
    for line in bill_lines:
        y = room_for(14)
        put(left, y, line)
        state["y"] = y - 14
    state["y"] = min(state["y"], top - 14 * len(fact_lines)) - 24

    def table_head() -> None:
        y = room_for(40, FONT_BOLD, 10)
        pdf.setFont(FONT_BOLD, 10)
        put(left, y, words["description"])
        put_right(qty_x, y, words["quantity"])
        put_right(rate_x, y, words["rate"])
        put_right(amount_x, y, words["amount"])
        put_right(tax_x, y, words["tax"])
        pdf.line(left, y - 4, right, y - 4)
        state["y"] = y - 20
        pdf.setFont(FONT_REGULAR, 10)

    table_head()
    for line in document.get("lines", []):
        description = customer_labels.customer_safe_label(
            line.get("description"), vendor_names, language="en"
        )
        wrapped = wrap(description, FONT_REGULAR, 10, description_room)
        if state["y"] - 13 * len(wrapped) < bottom:
            pdf.showPage()
            state["y"] = header()
            table_head()
        y = state["y"]
        for index, part in enumerate(wrapped):
            put(left, y - 13 * index, part)
        put_right(qty_x, y, _quantity(line.get("quantity")))
        put_right(rate_x, y, _unit(line.get("unit_price_cad")))
        put_right(amount_x, y, _money(line.get("amount_cad")))
        put_right(tax_x, y, line.get("tax_code") or "")
        state["y"] = y - (13 * len(wrapped) + 6)
    rows = document.get("tax_rows") or []
    y = room_for(60 + 14 * len(rows))
    pdf.line(left, y + 2, right, y + 2)
    y -= 16
    pdf.setFont(FONT_REGULAR, 10)
    for label, value in [
        (words["subtotal"], document.get("subtotal_cad")),
        *((row["label"], row["tax_cad"]) for row in rows),
    ]:
        put_right(right - 120, y, label)
        put_right(right, y, _money(value))
        y -= 14
    pdf.setFont(FONT_BOLD, 11)
    put_right(right - 120, y, f"{words['total']} ({document.get('currency') or 'CAD'})")
    put_right(right, y, _money(document.get("total_cad")))
    state["y"] = y - 28
    pdf.setFont(FONT_REGULAR, 8)
    for part in (
        words["payment"].format(email=document["payment_etransfer"]),
        words["wire"].format(wire=document["payment_wire"]),
    ):
        for piece in wrap(part, FONT_REGULAR, 8, right - left):
            y = room_for(12, FONT_REGULAR, 8)
            put(left, y, piece)
            state["y"] = y - 12
    state["y"] -= 12
    notes = text(document.get("notes"))
    if notes:
        y = room_for(30, FONT_BOLD, 10)
        pdf.setFont(FONT_BOLD, 10)
        put(left, y, words["notes"])
        state["y"] = y - 13
        pdf.setFont(FONT_REGULAR, 10)
        for part in wrap(notes, FONT_REGULAR, 10, right - left):
            y = room_for(13)
            put(left, y, part)
            state["y"] = y - 13
    pdf.showPage()
    pdf.save()
    return buffer.getvalue()


def _tax_percent(tax_status: str | None) -> int:
    try:
        return int(str(tax_status or "").rsplit("_", 1)[-1])
    except ValueError:
        return 0


def draft_document(db, draft) -> dict[str, Any]:
    """The draft as it will print: saved fields only, no invoice number, the Solaris Invoicing
    layout (DEC-0235) with the per-line figures Send will issue."""
    from app.core.enums import SOLARIS_SERVICE_LABELS  # noqa: PLC0415
    from app.core.time_utils import utcnow  # noqa: PLC0415
    from app.models import QuoteVersion  # noqa: PLC0415
    from app.services import finance_service, invoice_draft_service  # noqa: PLC0415

    view = invoice_draft_service.view(db, draft)
    version = db.get(QuoteVersion, draft.quote_version_id)
    today = utcnow()
    return {
        **finance_service.COMPANY,
        **finance_service.PAYMENT,
        "footer": finance_service.INVOICE_FOOTER,
        "tax_layout": view["tax_layout"],
        "invoice_number": None,
        "issued_at": today,
        "due_at": invoice_draft_service.expected_due_at(db, today),
        "payment_terms": finance_service.payment_terms(
            finance_service.get_settings(db).invoice_due_days
        ),
        "bill_to_name": view["bill_to_name"],
        "bill_to_address": view["bill_to_address"],
        "purchase_order_reference": view["customer_reference"],
        "shipment_reference": view["shipment_reference"],
        "service": SOLARIS_SERVICE_LABELS.get(version.solaris_service, version.solaris_service)
        if version
        else None,
        "lines": [
            {
                "description": line["description"],
                "quantity": line["quantity"],
                "unit_price_cad": line["unit_price_cad"],
                # The Amount column is before tax (DEC-0235).
                "amount_cad": line["net_cad"],
                "tax_code": line["tax_code"],
            }
            for line in view["tax_lines"] or []
        ],
        "subtotal_cad": view["subtotal_cad"],
        "tax_cad": view["tax_cad"],
        "tax_rows": view["tax_rows"] or [],
        "tax_mode": view["tax_mode"],
        "total_cad": view["total_cad"],
        "currency": "CAD",
        "notes": view["notes"],
        "language": "en",
    }


def issued_document(db, invoice) -> dict[str, Any]:
    """The issued invoice as it prints, from the customer's allowlisted document."""
    from app.models import Customer  # noqa: PLC0415
    from app.services import finance_service, notification_service  # noqa: PLC0415

    document = finance_service.invoice_document(db, invoice)
    return {
        **document,
        "footer": finance_service.INVOICE_FOOTER,
        "tax_percent": _tax_percent(document.get("tax_status")),
        "notes": document.get("invoice_notes"),
        "language": "en"
        if document.get("tax_layout")
        else notification_service.language_for(db, db.get(Customer, invoice.customer_id)),
    }


def draft_pdf(db, draft) -> bytes:
    return render(
        draft_document(db, draft), draft=True, vendor_names=customer_labels.vendor_names(db)
    )


def invoice_pdf(db, invoice) -> bytes:
    return render(
        issued_document(db, invoice), draft=False, vendor_names=customer_labels.vendor_names(db)
    )
