"""Internal 4 x 6 label PDFs: dimensions, contents, barcode and QR payloads.

Covers CRM.md AC-4. Page geometry, page count, visible text, and reference uniqueness
are asserted with ``pypdf``, which is a required dev dependency. Actual *decoding* of the
Code 128 and QR symbols needs a rasterizer plus a symbol reader; those are optional dev
extras and the decoding tests skip with a clear message when they are absent, rather than
silently passing.
"""

from __future__ import annotations

from decimal import Decimal
from io import BytesIO

import pytest
from pypdf import PdfReader
from sqlalchemy.orm import Session

from app.core.enums import RouteGroup
from app.models import LabelPrintJob
from app.services import booking_service, label_service, package_service
from app.services.errors import ConflictError, ValidationError
from tests.conftest import (
    ADDRESS_BY_COUNTRY,
    booked_shipment,
    draft_payload,
    make_customer,
    see_committed_changes,
)

EXPECTED_WIDTH_PT = 288
EXPECTED_HEIGHT_PT = 432


def _reader(pdf_bytes: bytes) -> PdfReader:
    return PdfReader(BytesIO(pdf_bytes))


def _page_text(reader: PdfReader, index: int) -> str:
    return reader.pages[index].extract_text() or ""


def _document(db, shipment, org=None, package_ids=None):
    return label_service.build_label_document(db, shipment, org=org, package_ids=package_ids)


# --- Page geometry and count ----------------------------------------------


def test_a_three_package_shipment_produces_exactly_three_4x6_pages(db: Session):
    """AC-4."""
    customer = make_customer(db, email="label3@demo.example.com")
    shipment = booked_shipment(db, customer, RouteGroup.VCA, packages=3)
    document, packages, kind = _document(db, shipment)

    reader = _reader(document.pdf_bytes)
    assert len(reader.pages) == 3
    assert document.page_count == 3
    assert kind == "all_active"
    for page in reader.pages:
        assert round(float(page.mediabox.width), 2) == EXPECTED_WIDTH_PT
        assert round(float(page.mediabox.height), 2) == EXPECTED_HEIGHT_PT
        # Portrait, and no rotation that would defeat the exact size.
        assert page.mediabox.height > page.mediabox.width
        assert (page.get("/Rotate") or 0) == 0


def test_one_package_produces_one_page(db: Session):
    customer = make_customer(db, email="label1@demo.example.com")
    shipment = booked_shipment(db, customer, RouteGroup.CAD)
    document, _packages, kind = _document(db, shipment)
    assert len(_reader(document.pdf_bytes).pages) == 1
    assert kind == "all_active"


def test_a_selected_subset_prints_only_those_pages(db: Session):
    customer = make_customer(db, email="labelsubset@demo.example.com")
    shipment = booked_shipment(db, customer, RouteGroup.VCA, packages=3)
    packages = package_service.active_packages(db, shipment.id)
    document, chosen, kind = _document(db, shipment, package_ids=[packages[1].id])

    assert len(_reader(document.pdf_bytes).pages) == 1
    assert kind == "single"
    assert chosen[0].id == packages[1].id
    assert packages[1].package_reference in _page_text(_reader(document.pdf_bytes), 0)


def test_cancelled_packages_are_never_printed(db: Session):
    customer = make_customer(db, email="labelcancelled@demo.example.com")
    shipment = booked_shipment(db, customer, RouteGroup.VCA, packages=3)
    packages = package_service.active_packages(db, shipment.id)
    package_service.cancel_package(db, packages[2], reason="Withdrawn")
    db.commit()

    document, chosen, _kind = _document(db, shipment)
    assert len(_reader(document.pdf_bytes).pages) == 2
    assert packages[2].id not in [package.id for package in chosen]

    with pytest.raises(ValidationError):
        _document(db, shipment, package_ids=[packages[2].id])


def test_a_draft_has_no_labels(db: Session):
    customer = make_customer(db, email="labeldraft@demo.example.com")
    payload = draft_payload(customer, RouteGroup.CAV)
    shipment = booking_service.create_draft(db, payload)
    db.commit()
    with pytest.raises(ConflictError) as excinfo:
        _document(db, shipment)
    assert "no Solaris Shipment ID" in str(excinfo.value)


# --- Visible content -------------------------------------------------------


def test_every_page_carries_the_required_content(db: Session):
    customer = make_customer(db, email="labelcontent@demo.example.com")
    shipment = booked_shipment(db, customer, RouteGroup.VCA, packages=3)
    packages = package_service.active_packages(db, shipment.id)
    document, _packages, _kind = _document(db, shipment)
    reader = _reader(document.pdf_bytes)

    for index, package in enumerate(packages):
        text = _page_text(reader, index)
        assert shipment.public_id in text
        assert package.package_reference in text
        assert shipment.route_group in text
        assert "Vietnam to Canada" in text
        assert f"PACKAGE {index + 1} OF 3" in text.upper()
        assert "Solaris Express" in text
        assert label_service.WARNING_TEXT in text
        assert "Tran Quoc Tuan" in text  # recipient name
        assert "Mississauga" in text
        assert "5.5 kg" in text


def test_package_references_on_the_pages_are_unique(db: Session):
    customer = make_customer(db, email="labelunique@demo.example.com")
    shipment = booked_shipment(db, customer, RouteGroup.CAV, packages=3)
    document, _packages, _kind = _document(db, shipment)
    reader = _reader(document.pdf_bytes)

    found = set()
    for index in range(len(reader.pages)):
        text = _page_text(reader, index)
        references = {
            token
            for token in text.replace("\n", " ").split()
            if token.startswith(f"{shipment.public_id}-")
        }
        assert len(references) == 1
        found |= references
    assert len(found) == 3


def test_imperial_weight_prints_both_units(db: Session):
    customer = make_customer(db, email="labelimperial@demo.example.com")
    shipment = booked_shipment(db, customer, RouteGroup.CAD)
    package = package_service.active_packages(db, shipment.id)[0]
    package_service.update_package(
        db, package, {"weight_value": Decimal("12.5"), "weight_unit": "lb"}
    )
    db.commit()

    document, _packages, _kind = _document(db, shipment)
    text = _page_text(_reader(document.pdf_bytes), 0)
    assert "12.5 lb" in text
    assert "5.67 kg" in text


def test_handling_note_and_warehouse_location_appear_when_present(db: Session):
    customer = make_customer(db, email="labelnote@demo.example.com")
    shipment = booked_shipment(db, customer, RouteGroup.CAD)
    package = package_service.active_packages(db, shipment.id)[0]
    package_service.update_package(
        db, package, {"handling_note": "Fragile — do not stack", "warehouse_location": "A-12-3"}
    )
    db.commit()

    text = _page_text(_reader(_document(db, shipment)[0].pdf_bytes), 0)
    assert "Fragile" in text
    assert "A-12-3" in text


def test_the_font_covers_the_vietnamese_repertoire():
    """A missing glyph prints an empty box, so the coverage is asserted, not assumed."""
    from fontTools.ttLib import TTFont

    needed = [0x110, 0x111, 0x1A0, 0x1A1, 0x1AF, 0x1B0, *range(0x1EA0, 0x1EFA)]
    for name in ("Roboto-Regular.ttf", "Roboto-Bold.ttf"):
        cmap = TTFont(str(label_service.FONT_DIR / name)).getBestCmap()
        missing = [hex(codepoint) for codepoint in needed if codepoint not in cmap]
        assert missing == [], f"{name} is missing {missing}"


def test_a_long_vietnamese_name_never_truncates_the_identifiers(db: Session):
    customer = make_customer(db, email="labellongname@demo.example.com")
    payload = draft_payload(customer, RouteGroup.CAV)
    payload["recipient"] = dict(ADDRESS_BY_COUNTRY["VN"])
    payload["recipient"]["name"] = (
        "Nguyễn Thị Hoàng Yến Phương Trần Đặng Bích Hạnh Nguyễn Văn Trường Giang"
    )
    payload["recipient"]["city"] = "Thành phố Hồ Chí Minh, Quận Bình Thạnh Phường 25"
    shipment = booking_service.create_draft(db, payload)
    db.commit()
    from tests.conftest import confirm_draft

    confirm_draft(db, shipment, "longname-key-01")

    document, _packages, _kind = _document(db, shipment)
    reader = _reader(document.pdf_bytes)
    assert round(float(reader.pages[0].mediabox.width), 2) == EXPECTED_WIDTH_PT
    text = _page_text(reader, 0)
    # The identifiers print in full even though the name has to be shortened.
    assert shipment.public_id in text
    assert f"{shipment.public_id}-01" in text
    assert "Nguyễn Thị Hoàng Yến" in text


def test_english_names_render_too(db: Session):
    customer = make_customer(db, email="labelenglish@demo.example.com")
    shipment = booked_shipment(db, customer, RouteGroup.XUS)
    text = _page_text(_reader(_document(db, shipment)[0].pdf_bytes), 0)
    assert "Dana Whitfield" in text
    assert "Seattle" in text


# --- QR destination and configuration -------------------------------------


def test_the_qr_url_comes_from_configuration_not_a_hard_coded_domain(db: Session):
    from app.models import OrganizationSettings

    customer = make_customer(db, email="labelqr@demo.example.com")
    shipment = booked_shipment(db, customer, RouteGroup.CAV, packages=2)
    org = db.query(OrganizationSettings).first()
    org.tracking_base_url = "https://track.example.test/t/"
    db.commit()

    payload = label_service.preview_payload(db, shipment, org=org)
    references = [item["package_reference"] for item in payload["labels"]]
    urls = [item["tracking_url"] for item in payload["labels"]]

    assert urls == [f"https://track.example.test/t/{reference}" for reference in references]
    assert payload["tracking_base_url"] == "https://track.example.test/t"
    # Nothing assumes the proposed production host exists.
    assert "solarisexpress.ca" not in " ".join(urls)


def test_preview_reports_the_exact_page_size_and_instruction(db: Session):
    customer = make_customer(db, email="labelpreview@demo.example.com")
    shipment = booked_shipment(db, customer, RouteGroup.CAV, packages=2)
    payload = label_service.preview_payload(db, shipment, org=None)

    assert payload["page_width_pt"] == EXPECTED_WIDTH_PT
    assert payload["page_height_pt"] == EXPECTED_HEIGHT_PT
    assert "100% scale" in payload["print_instruction"]
    assert len(payload["labels"]) == 2
    assert payload["labels"][0]["position_label"] == "Package 1 of 2"
    assert payload["labels"][0]["has_approved_logo"] is False
    assert payload["labels"][0]["wordmark"] == "Solaris Express"
    assert payload["labels"][0]["warning"] == label_service.WARNING_TEXT


# --- Barcode and QR decoding ----------------------------------------------


def _decode_pages(pdf_bytes: bytes, dpi: int):
    """Rasterize each page and decode every symbol on it.

    Skips rather than passing when the optional decoding tools are unavailable, so a
    missing tool can never be mistaken for a successful scan check.
    """
    pymupdf = pytest.importorskip(
        "pymupdf", reason="PDF rasterizer not installed; barcode decoding not attempted"
    )
    zxingcpp = pytest.importorskip(
        "zxingcpp", reason="zxing-cpp not installed; barcode decoding not attempted"
    )
    from PIL import Image

    results = []
    with pymupdf.open(stream=pdf_bytes, filetype="pdf") as document:
        for page in document:
            pixmap = page.get_pixmap(dpi=dpi)
            image = Image.frombytes("RGB", [pixmap.width, pixmap.height], pixmap.samples)
            results.append(
                {
                    (
                        symbol.format.name if hasattr(symbol.format, "name") else str(symbol.format)
                    ): symbol.text
                    for symbol in zxingcpp.read_barcodes(image)
                }
            )
    return results


@pytest.mark.parametrize("dpi", [203, 300])
def test_barcode_and_qr_decode_at_thermal_printer_densities(db: Session, dpi):
    from app.models import OrganizationSettings

    customer = make_customer(db, email=f"labeldecode{dpi}@demo.example.com")
    shipment = booked_shipment(db, customer, RouteGroup.VCA, packages=3)
    org = db.query(OrganizationSettings).first()
    org.tracking_base_url = "https://track.example.test/t"
    db.commit()

    packages = package_service.active_packages(db, shipment.id)
    document, _packages, _kind = _document(db, shipment, org=org)
    decoded = _decode_pages(document.pdf_bytes, dpi)

    assert len(decoded) == 3
    for package, symbols in zip(packages, decoded, strict=True):
        assert symbols.get("Code128") == package.package_reference
        assert symbols.get("QRCode") == (
            f"https://track.example.test/t/{package.package_reference}"
        )


def test_the_barcode_module_width_stays_scannable():
    assert label_service.BARCODE_MODULE_WIDTH >= label_service.MIN_MODULE_WIDTH
    # Quiet zones of at least ten module widths on each side.
    assert label_service.BARCODE_QUIET_ZONE >= 10 * label_service.BARCODE_MODULE_WIDTH
    # The whole symbol plus quiet zones fits inside the printable width.
    bar = label_service._barcode("SX-VCA-7K9D2M4R8T6W-01")
    assert bar.width <= label_service.PAGE_WIDTH - 2 * label_service.MARGIN


# --- Generation records and reprints --------------------------------------


def test_reprints_preserve_every_identifier(db: Session):
    customer = make_customer(db, email="labelreprint@demo.example.com")
    shipment = booked_shipment(db, customer, RouteGroup.VCA, packages=3)
    packages = package_service.active_packages(db, shipment.id)
    before = [package.package_reference for package in packages]

    first, chosen, kind = _document(db, shipment)
    label_service.record_generation(db, shipment, chosen, first, kind=kind)
    db.commit()
    second, chosen_again, kind_again = _document(db, shipment)
    job = label_service.record_generation(db, shipment, chosen_again, second, kind=kind_again)
    db.commit()

    db.expire_all()
    after = [
        package.package_reference for package in package_service.active_packages(db, shipment.id)
    ]
    assert after == before
    assert db.get(type(shipment), shipment.id).public_id == shipment.public_id
    assert job.is_reprint is True
    assert job.page_count == 3
    # The bytes are identical, which is what "the reprint is the same label" means.
    assert first.sha256 == second.sha256

    history = label_service.print_history(db, shipment.id)
    assert len(history) == 2
    assert [record.is_reprint for record in history] == [True, False]


def test_generation_is_recorded_without_claiming_a_printer_ran(as_admin, db: Session):
    customer = make_customer(db, email="labelapi@demo.example.com")
    shipment = booked_shipment(db, customer, RouteGroup.CAV, packages=2)

    response = as_admin.get(f"/api/v1/shipments/{shipment.id}/labels.pdf")
    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["x-solaris-label-pages"] == "2"
    assert shipment.public_id in response.headers["content-disposition"]
    assert len(_reader(response.content).pages) == 2

    jobs = as_admin.get(f"/api/v1/shipments/{shipment.id}/label-jobs").json()
    assert len(jobs) == 1
    assert jobs[0]["page_count"] == 2
    assert jobs[0]["is_reprint"] is False
    assert sorted(jobs[0]["package_references"]) == [
        f"{shipment.public_id}-01",
        f"{shipment.public_id}-02",
    ]

    audit = as_admin.get("/api/v1/audit", params={"action": "shipment.label_generate"}).json()
    summary = audit["items"][0]["summary"]
    assert "Generated" in summary
    assert "printed" not in summary.lower()


def test_selected_package_generation_over_the_api(as_admin, db: Session):
    customer = make_customer(db, email="labelselect@demo.example.com")
    shipment = booked_shipment(db, customer, RouteGroup.VCA, packages=3)
    packages = package_service.active_packages(db, shipment.id)

    response = as_admin.get(
        f"/api/v1/shipments/{shipment.id}/labels.pdf",
        params={"package_id": [packages[0].id, packages[2].id]},
    )
    assert response.status_code == 200
    see_committed_changes(db)
    reader = _reader(response.content)
    assert len(reader.pages) == 2
    assert packages[0].package_reference in _page_text(reader, 0)
    assert packages[2].package_reference in _page_text(reader, 1)

    job = db.query(LabelPrintJob).one()
    assert job.kind == "selected"
