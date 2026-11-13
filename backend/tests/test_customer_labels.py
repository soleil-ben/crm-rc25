"""No customer-facing output names the vendor (owner, Louis Tong, 2026-10-21; DEC-0222).

Unit tests for ``app.services.customer_labels`` and one end-to-end leak test: tariff surcharge
names carrying the vendor's name (``Kango``, ``KANGO``, ``Kangô``) and a second vendor in the
``vendors`` table (``Demo Carrier Co``) are priced onto a quote that is sent, accepted,
invoiced and paid; then every customer-facing output is scanned for every vendor name,
case- and diacritic-insensitively. Staff routes may still show the vendor's wording.
"""

from __future__ import annotations

import io
import json
import unicodedata

import pytest
from pypdf import PdfReader

from app.core.enums import Role, TrackingSourceMode
from app.models import (
    LegTrackingReference,
    ShipmentLeg,
    TariffSurchargeRule,
    Vendor,
)
from app.services import finance_service as fs
from app.services import invoice_draft_service
from app.services import quote_offer_service as qos
from app.services import tariff_import_service as tis
from app.services.customer_labels import (
    ALWAYS_HIDDEN,
    NEUTRAL_LABEL,
    NEUTRAL_WORD,
    customer_safe_label,
    customer_safe_text,
    names_a_vendor,
    refuse_vendor_name,
    vendor_names,
)
from app.services.errors import ValidationError
from tests.conftest import see_committed_changes, shown_tax

# --- Unit ------------------------------------------------------------------------------------


def test_kango_is_hidden_even_without_a_vendor_row():
    assert "kango" in ALWAYS_HIDDEN
    assert vendor_names(None) == ("kango",)


def test_matching_ignores_case_diacritics_and_spacing():
    names = vendor_names(None)
    for text in (
        "Phụ thu Kango",
        "KANGO surcharge",
        "kangô",
        "Phụ thu KANGÔ hàng giả",
        "x kAnGo y",
    ):
        assert names_a_vendor(text, names), text
    assert names_a_vendor("Demo  Carrier   co fee", ("Demo Carrier Co",))
    assert names_a_vendor("Phí Đông Á", ("dong a",))
    for text in ("Fake clothing", "Hàng giả thương hiệu", "", None):
        assert not names_a_vendor(text, names), text


def test_blank_names_never_match_everything():
    assert not names_a_vendor("Fake clothing", ("", "   "))


def test_customer_safe_label_neutral_in_the_customers_language():
    names = vendor_names(None)
    assert customer_safe_label("Phụ thu Kango", names) == NEUTRAL_LABEL["en"] == "Surcharge"
    assert customer_safe_label("Phụ thu Kango", names, language="vi") == "Phụ phí"
    assert customer_safe_label("Phụ thu Kango", names, language="fr") == "Surcharge"
    assert customer_safe_label("Fake clothing", names, language="vi") == "Fake clothing"
    assert customer_safe_label(None, names) == ""


def test_names_match_whole_words_only():
    """Review M2: a name inside a longer word is not a match ("ana" / "Canada")."""
    names = ("ana", "ups", "kango", "demo carrier co")
    for text in (
        "Delivered in Canada",
        "Banana boxes",
        "Shipping groups of parcels",
        "Startups welcome",
        "Ana Nguyen",
    ):
        assert not names_a_vendor(text, names), text
    # Names shorter than four letters are ignored unless listed in ALWAYS_HIDDEN.
    assert not names_a_vendor("UPS ground", names)
    assert names_a_vendor("x DHX y", ("dhx",)) is False
    assert names_a_vendor("Phụ thu Kango", names)
    assert names_a_vendor("handled by Demo Carrier Co.", names)


def test_obfuscated_names_still_match():
    """Review M2: punctuation or spacing inside a name of five or more letters is caught."""
    names = vendor_names(None)
    for text in ("Kan-go", "K.ango express", "K a n g o", "phí KAN_GO", "(Kangô)"):
        assert names_a_vendor(text, names), text
    # A four-letter name only matches as words: no squashed comparison below five letters.
    assert names_a_vendor("by Acme today", ("acme",))
    assert not names_a_vendor("A-cme", ("acme",))


def test_customer_safe_text_replaces_only_the_vendor_words():
    names = (*vendor_names(None), "demo carrier co")
    assert (
        customer_safe_text("Hàng đã giao cho Kango tại sân bay", names, language="vi")
        == "Hàng đã giao cho đối tác vận chuyển tại sân bay"
    )
    assert (
        customer_safe_text("Handed to Demo Carrier Co. at YYZ", names)
        == "Handed to carrier. at YYZ"
    )
    assert customer_safe_text("Picked up by K-ango today", names) == "Picked up by carrier today"
    assert customer_safe_text("Arrived in Canada", names) == "Arrived in Canada"
    assert customer_safe_text(None, names) is None
    assert NEUTRAL_WORD == {"vi": "đối tác vận chuyển", "en": "carrier"}
    # A label is still replaced as a whole.
    assert customer_safe_label("Phụ thu Kango", names, language="vi") == "Phụ phí"


def test_refuse_vendor_name_names_the_field():
    with pytest.raises(ValidationError) as caught:
        refuse_vendor_name("Kango fuel levy", vendor_names(None), field="notes")
    assert caught.value.field == "notes"
    refuse_vendor_name("Fuel levy", vendor_names(None), field="notes")


def test_vendor_names_reads_the_vendors_table(db):
    db.add(Vendor(key="democarrier", name="Demo Carrier Co"))
    db.add(Vendor(key="ab", name="X"))  # too short to match safely: ignored
    db.add(Vendor(key="dhx", name="DHX"))  # three letters: ignored too (minimum four)
    db.commit()
    names = vendor_names(db)
    assert {"kango", "democarrier", "demo carrier co"} <= set(names)
    assert "ab" not in names and "x" not in names and "dhx" not in names
    assert names_a_vendor("Phí DEMO CARRIER CO", names)


# --- The leak test ---------------------------------------------------------------------------

#: Every spelling a customer must never read, in folded form.
LEAK_NAMES = ("kango", "demo carrier co", "democarrier", "kango logistics")

#: The vendor's wording on the rate sheet, as the tariff would carry it.
VENDOR_LABELS = {
    14: "KANGO phụ thu hàng giả quần áo",
    15: "Phụ thu Kangô túi xách giả",
    18: "Phụ thu Kango đồng hồ",
    22: "Demo Carrier Co handling fee",
}


def _fold(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text.replace("đ", "d").replace("Đ", "D"))
    return " ".join("".join(c for c in decomposed if not unicodedata.combining(c)).lower().split())


def _pdf_text(content: bytes) -> str:
    assert content.startswith(b"%PDF")
    return "".join(page.extract_text() for page in PdfReader(io.BytesIO(content)).pages)


def _assert_no_vendor_name(label: str, text: str) -> None:
    folded = _fold(text)
    for name in LEAK_NAMES:
        assert name not in folded, (label, name)


def test_no_customer_facing_output_names_a_vendor(
    account_client, account_db, account_users, captured_mail
):
    from tests.approval_fixtures import staff
    from tests.test_account_profile import _customer, _setup
    from tests.test_quote_offers import _account_world, _fee, _finalize, _send

    _reference, me = _setup(account_client, account_users, captured_mail)
    owner = _customer(account_db)
    owner.preferred_language = "vi"
    account_db.add(Vendor(key="democarrier", name="Demo Carrier Co"))
    account_db.commit()
    kids = _account_world(account_db, owner)
    mine = kids[2]
    version = tis.active_version(account_db)
    for stt, label in VENDOR_LABELS.items():
        rule = (
            account_db.query(TariffSurchargeRule)
            .filter_by(version_id=version.id, section="hcm_air", stt=stt)
            .one()
        )
        rule.name = label
    account_db.commit()
    for stt in VENDOR_LABELS:
        # Row 22 is per item kg under method v0.5 (allocation class ITEM, DEC-0252).
        extra = {"weight_kg": "2"} if stt == 22 else {}
        _fee(account_db, mine, stt=stt, description=f"Goods {stt}", **extra)
    _finalize(account_db, mine)
    offer_id = _send(account_db, mine).id
    qos.send_email(account_db, offer_id)  # what the staff send route does after its commit

    # A last-mile carrier link whose staff-typed carrier name names the vendor, and a second,
    # clean one. Since the owner's answer of 2026-10-22 (DEC-0224) the first is shown, under
    # the leg's generic name: the stored label is never output.
    leg = ShipmentLeg(
        shipment_id=mine.id,
        sequence=1,
        leg_type="last_mile",
        provider_name="Kango Logistics",
        service_display="Kango Express",
    )
    account_db.add(leg)
    account_db.commit()
    account_db.add(
        LegTrackingReference(
            leg_id=leg.id,
            carrier_name="Kango Express",
            tracking_number="1Z999AA10123456784",
            public_url="https://www.ups.com/track?loc=en_CA&tracknum=1Z999AA10123456784",
            source_mode=TrackingSourceMode.EXTERNAL_LINK,
            is_active=True,
        )
    )
    account_db.add(
        LegTrackingReference(
            leg_id=leg.id,
            carrier_name="UPS",
            tracking_number="1Z999AA10123456785",
            public_url="https://www.ups.com/track?loc=en_CA&tracknum=1Z999AA10123456785",
            source_mode=TrackingSourceMode.EXTERNAL_LINK,
            is_active=True,
        )
    )
    account_db.commit()

    outputs: dict[str, str] = {}
    for path in ("/quotes", f"/quotes/{offer_id}", "/shipments", f"/shipments/{mine.public_id}"):
        response = me.get(path)
        assert response.status_code == 200, (path, response.text)
        outputs[f"account {path}"] = response.text
    outputs["notifications"] = me.get("/notifications").text
    accepted = me.post(f"/quotes/{offer_id}/accept")
    assert accepted.status_code == 200, accepted.text
    outputs["account accept"] = accepted.text

    # Staff type a published milestone and a location that name the vendor: the customer
    # reads the sentence with the vendor's name replaced, in their language (Vietnamese).
    from app.services import event_service

    event_service.record_event(
        account_db,
        mine,
        {
            "event_type": "in_transit",
            "is_public_update": True,
            "public_update_text": "Lô hàng đã giao cho Kango Logistics tại Tân Sơn Nhất",
            "location_label": "Kho K-ango HCM",
            "location_country_code": "VN",
        },
        actor=None,
    )
    account_db.commit()
    shipment_detail = me.get(f"/shipments/{mine.public_id}")
    assert shipment_detail.status_code == 200, shipment_detail.text
    outputs["account shipment after milestone"] = shipment_detail.text
    timeline = shipment_detail.json()["timeline"]
    assert timeline[0]["message"] == "Lô hàng đã giao cho đối tác vận chuyển tại Tân Sơn Nhất"
    assert timeline[0]["location"]["city"] == "Kho đối tác vận chuyển HCM"
    detail = json.loads(outputs[f"account /quotes/{offer_id}"])
    assert {s["name"] for s in detail["surcharges"]} == {"Phụ phí"}

    # Accepting created a draft invoice (fix pack F). Staff add a line in the vendor's
    # wording, print the draft, and send it: the numbered invoice and its email follow.
    see_committed_changes(account_db)
    draft = invoice_draft_service.live_for_shipment(account_db, mine.id)
    assert draft is not None
    ops = staff(account_client, account_users[Role.OPERATIONS].email)
    url = f"/api/v1/invoice-drafts/{draft.id}"
    read = ops.get(url).json()
    # A staff line, note, bill-to or PO naming a vendor is refused on save (422, field named).
    for field, value in (
        (
            "lines",
            [*read["lines"], {"description": "Demo Carrier Co fuel levy", "amount_cad": "5"}],
        ),
        ("notes", "Shipped with K-ango"),
        ("bill_to_name", "Kango Logistics"),
        ("customer_reference", "KANGO-PO-1"),
        ("bill_to_address", "c/o Demo Carrier Co, Toronto"),
    ):
        refused = ops.client.patch(
            url,
            headers=ops.headers,
            json={
                "expected_revision": read["revision"],
                field: value,
                "total_change_reason": "extra fuel",
            },
        )
        assert refused.status_code == 422, (field, refused.text)
        assert refused.json()["field"] == field
    lines = [*read["lines"], {"description": "Fuel levy", "amount_cad": "5.00"}]
    edited = ops.client.patch(
        url,
        headers=ops.headers,
        json={
            "expected_revision": read["revision"],
            "lines": lines,
            "total_change_reason": "extra fuel",
            "tax_confirmed": True,  # RC-UAT-19: the GST/HST is confirmed on every save
            # ... with the figures the screen showed, at the draft's own rate (RC-UAT-20,
            # DEC-0227: this VN-CA draft is zero-rated; it was 13 % in RC-UAT-19).
            **shown_tax(lines, read["tax_rate_percent"], "included"),
        },
    )
    assert edited.status_code == 200, edited.text
    revision = edited.json()["revision"]
    draft_pdf = ops.get(f"{url}/pdf", params={"revision": revision})
    assert draft_pdf.status_code == 200, draft_pdf.text
    outputs["draft invoice pdf"] = _pdf_text(draft_pdf.content)
    # DEC-0235: the invoice PDF is English with no accents; the neutral label stored on the
    # Vietnamese customer's draft line prints without its diacritics.
    assert "Phu phi" in outputs["draft invoice pdf"]
    assert "Phụ phí" not in outputs["draft invoice pdf"]
    sent = ops.post(f"{url}/send", json={"expected_revision": revision})
    assert sent.status_code == 200, sent.text
    invoice_id = sent.json()["invoice_id"]
    see_committed_changes(account_db)
    invoice = fs.get_invoice(account_db, invoice_id)
    payment = fs.record_payment(
        account_db, invoice, {"amount_cad": "1.00", "method": "cash"}, actor=None
    )
    account_db.commit()
    payment_id = payment.id

    issued_pdf = ops.get(f"/api/v1/invoices/{invoice_id}/pdf")
    assert issued_pdf.status_code == 200, issued_pdf.text
    outputs["invoice pdf"] = _pdf_text(issued_pdf.content)
    for label, path in (
        ("quote document", f"/api/v1/shipments/{mine.id}/quotes/1/document"),
        ("invoice document", f"/api/v1/invoices/{invoice_id}/document"),
        ("receipt", f"/api/v1/payments/{payment_id}/receipt"),
    ):
        response = ops.get(path)
        assert response.status_code == 200, (label, response.text)
        outputs[label] = response.text
    invoice_lines = json.loads(outputs["invoice document"])["lines"]
    neutral = sum(1 for line in invoice_lines if line["description"] == "Phụ phí")
    assert neutral == len(VENDOR_LABELS)  # the four tariff lines

    # Staff screens are unchanged: staff may read the vendor's own wording.
    staff_quotes = ops.get(f"/api/v1/shipments/{mine.id}/quotes")
    assert staff_quotes.status_code == 200
    assert "Kango" in staff_quotes.text
    assert ops.get(f"/api/v1/invoices/{invoice_id}").status_code == 200

    account_client.cookies.clear()
    public = account_client.get(f"/api/v1/public/track/{mine.public_id}")
    assert public.status_code == 200, public.text
    outputs["public tracking"] = public.text
    # A link labelled with the vendor's name is shown under the leg's generic name (owner,
    # 2026-10-22; DEC-0224 reverts the RC-UAT-18 rule that hid it).
    link = public.json().get("carrier_link")
    assert link is not None and link["url"].endswith("1Z999AA10123456784")
    assert link["carrier_name"] == "Last Mile Tracking"
    assert link["tracking_name_key"] == "last_mile_tracking"
    public_timeline = public.json()["timeline"]
    assert "đối tác vận chuyển" in public_timeline[0]["message"]
    assert public_timeline[0]["location"]["city"] == "Kho đối tác vận chuyển HCM"

    for index, message in enumerate(captured_mail.messages):
        key = f"email {index} {message.get('template_key')}"
        outputs[key] = json.dumps(message, ensure_ascii=False)
    assert any("quote.sent" in key for key in outputs)
    assert any("invoice.sent.vi" in key for key in outputs)

    for label, text in outputs.items():
        _assert_no_vendor_name(label, text)
