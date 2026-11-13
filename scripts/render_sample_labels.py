"""Render representative sample 4 x 6 label PDFs for review.

CRM.md section 16 asks for sample label PDFs as a deliverable, and section 8 asks that
long Vietnamese names, long city names, and both measurement systems be validated. This
script builds those cases in a throwaway in-memory database and writes the PDFs to
``artifacts/sample-labels/``.

Everything here is synthetic and clearly fictional. Run from the repository root::

    python scripts/render_sample_labels.py

The script also reports each file's page count, page size, and — when the optional
decoding tools are installed — the decoded Code 128 and QR payloads at 203 and 300 dpi.
It prints exactly what it verified and says so when a check could not be run.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.core.db import build_engine  # noqa: E402
from app.core.enums import RouteGroup  # noqa: E402
from app.models import Base, OrganizationSettings  # noqa: E402
from app.services import booking_service, customer_service, label_service  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

OUTPUT_DIR = REPO_ROOT / "artifacts" / "sample-labels"

# A tracking base that is obviously not a real production host, but whose **path** is the
# real one. The host stays a reserved `.test` name because the tracking domain is still an
# open business decision; the `/track` path is not a placeholder, it is the route the
# public application actually serves (`frontend/src/public/PublicApp.jsx`), so a QR
# decoded from these samples addresses the page that exists.
#
# Phase 2 used `/t` here, which was arbitrary and became wrong the moment Phase 3
# registered the real route.
DEMO_TRACKING_BASE = "https://track.example.test/track"

SENDER_CA = {
    "name": "Solaris Express — Mississauga counter (demo)",
    "company": "Solaris Express Inc.",
    "phone_entered": "+1 905 555 0110",
    "address_line1": "4120 Dixie Road, Unit 6",
    "city": "Mississauga",
    "province_state": "ON",
    "postal_code": "L4W 1V2",
    "country_code": "CA",
}

SENDER_VN = {
    "name": "Trần Đặng Hoàng Việt (demo)",
    "phone_entered": "+84 28 3822 1234",
    "address_line1": "48 Lê Lợi",
    "city": "Thành phố Hồ Chí Minh",
    "province_state": "Hồ Chí Minh",
    "postal_code": "700000",
    "country_code": "VN",
}

SAMPLES = [
    {
        "file": "01-three-package-canada-to-vietnam.pdf",
        "note": "Three packages, metric input, one handling note and warehouse locations",
        "route": RouteGroup.CAV,
        "sender": SENDER_CA,
        "recipient": {
            "name": "Nguyễn Thị Bích Hạnh (demo)",
            "phone_entered": "+84 90 123 4567",
            "address_line1": "125 Đường Nguyễn Huệ",
            "city": "Thành phố Hồ Chí Minh",
            "province_state": "Hồ Chí Minh",
            "postal_code": "700000",
            "country_code": "VN",
        },
        "packages": [
            {
                "length_value": "45",
                "width_value": "35",
                "height_value": "25",
                "dimension_unit": "cm",
                "weight_value": "6.4",
                "weight_unit": "kg",
                "contents_summary": "Winter clothing (demo)",
                "warehouse_location": "A-04-1",
            },
            {
                "length_value": "40",
                "width_value": "30",
                "height_value": "20",
                "dimension_unit": "cm",
                "weight_value": "4.2",
                "weight_unit": "kg",
                "contents_summary": "Vitamins and dried fruit (demo)",
                "handling_note": "Keep dry — do not stack",
                "warehouse_location": "A-04-2",
            },
            {
                "length_value": "50",
                "width_value": "40",
                "height_value": "30",
                "dimension_unit": "cm",
                "weight_value": "9.8",
                "weight_unit": "kg",
                "contents_summary": "Kitchenware (demo)",
                "warehouse_location": "A-04-3",
            },
        ],
    },
    {
        "file": "02-long-vietnamese-name-and-destination.pdf",
        "note": "Long diacritic recipient name and a long destination line",
        "route": RouteGroup.CAV,
        "sender": SENDER_CA,
        "recipient": {
            "name": "Nguyễn Thị Hoàng Yến Phương Trần Đặng Bích Hạnh Nguyễn Văn Trường Giang",
            "phone_entered": "+84 90 555 0199",
            "address_line1": "Số 1234 Đường Nguyễn Văn Linh, Khu đô thị Phú Mỹ Hưng",
            "city": "Thành phố Hồ Chí Minh, Quận 7, Phường Tân Phú",
            "province_state": "Hồ Chí Minh",
            "postal_code": "700000",
            "country_code": "VN",
        },
        "packages": [
            {
                "length_value": "35",
                "width_value": "25",
                "height_value": "15",
                "dimension_unit": "cm",
                "weight_value": "3.75",
                "weight_unit": "kg",
                "contents_summary": "Gia dụng và quần áo (demo)",
                "handling_note": "Hàng dễ vỡ — xin nhẹ tay",
            }
        ],
    },
    {
        "file": "03-imperial-input-us-cross-border.pdf",
        "note": "Imperial input: inches and pounds, printed with the canonical values",
        "route": RouteGroup.XUS,
        "sender": SENDER_CA,
        "recipient": {
            "name": "Dana Whitfield (demo)",
            "phone_entered": "+1 206 555 0143",
            "address_line1": "900 Pike Street, Suite 410",
            "city": "Seattle",
            "province_state": "WA",
            "postal_code": "98101",
            "country_code": "US",
        },
        "packages": [
            {
                "length_value": "18",
                "width_value": "14",
                "height_value": "10",
                "dimension_unit": "in",
                "weight_value": "12.5",
                "weight_unit": "lb",
                "contents_summary": "Business samples (demo)",
                "warehouse_location": "B-11-2",
            }
        ],
    },
    {
        "file": "04-vietnam-to-canada-single.pdf",
        "note": "Inbound lane, French-accented recipient, no optional fields recorded",
        "route": RouteGroup.VCA,
        "sender": SENDER_VN,
        "recipient": {
            "name": "Marie-Ève Lafontaine (demo)",
            "phone_entered": "+1 514 555 0177",
            "address_line1": "2200 Rue Sainte-Catherine Ouest",
            "city": "Montréal",
            "province_state": "QC",
            "postal_code": "H3H 1M2",
            "country_code": "CA",
        },
        "packages": [{"contents_summary": "Dried longan and tea (demo)"}],
    },
]


def build() -> list[tuple[Path, dict]]:
    engine = build_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    db = session_factory()

    org = OrganizationSettings(tracking_base_url=DEMO_TRACKING_BASE)
    db.add(org)
    db.flush()

    customer = customer_service.create_customer(
        db,
        {
            "full_name": "Nguyễn Thị Bích Hạnh (demo)",
            "email": "sample.labels@demo.example.com",
            "phone": "+1 416 555 0142",
            "country_code": "CA",
        },
    )
    db.commit()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    written: list[tuple[Path, dict]] = []

    for index, sample in enumerate(SAMPLES, start=1):
        shipment = booking_service.create_draft(
            db,
            {
                "customer_id": customer.id,
                "route_group": sample["route"].value,
                "service_type": "standard_parcel",
                "transport_mode": "air",
                "contents_description": sample["note"],
                "sender": dict(sample["sender"]),
                "recipient": dict(sample["recipient"]),
                "packages": sample["packages"],
                "is_demo_record": True,
            },
        )
        db.commit()
        booking_service.confirm_booking(
            db, shipment_id=shipment.id, idempotency_key=f"sample-label-{index}"
        )
        db.commit()

        document, packages, _kind = label_service.build_label_document(db, shipment, org=org)
        path = OUTPUT_DIR / sample["file"]
        path.write_bytes(document.pdf_bytes)
        written.append(
            (
                path,
                {
                    "note": sample["note"],
                    "public_id": shipment.public_id,
                    "references": [package.package_reference for package in packages],
                    "pages": document.page_count,
                },
            )
        )

    db.close()
    engine.dispose()
    return written


def verify(path: Path) -> dict:
    """Report page geometry, and decode the symbols when the tools are installed."""
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    sizes = {
        (round(float(page.mediabox.width), 2), round(float(page.mediabox.height), 2))
        for page in reader.pages
    }
    result = {"pages": len(reader.pages), "sizes": sorted(sizes), "decoded": None}

    try:
        import pymupdf
        import zxingcpp
        from PIL import Image
    except ImportError:
        result["decoded"] = "not attempted — install the 'verify' extra (pymupdf, zxing-cpp)"
        return result

    decoded: list[dict] = []
    with pymupdf.open(str(path)) as document:
        for page_number, page in enumerate(document, start=1):
            per_dpi: dict[int, dict[str, str]] = {}
            for dpi in (203, 300):
                pixmap = page.get_pixmap(dpi=dpi)
                image = Image.frombytes("RGB", [pixmap.width, pixmap.height], pixmap.samples)
                per_dpi[dpi] = {
                    (
                        symbol.format.name if hasattr(symbol.format, "name") else str(symbol.format)
                    ): symbol.text
                    for symbol in zxingcpp.read_barcodes(image)
                }
            decoded.append({"page": page_number, "by_dpi": per_dpi})
    result["decoded"] = decoded
    return result


def main() -> int:
    written = build()
    print(f"Wrote {len(written)} sample label PDFs to {OUTPUT_DIR}\n")
    ok = True
    for path, meta in written:
        checks = verify(path)
        print(f"{path.name}")
        print(f"  {meta['note']}")
        print(f"  Solaris ID : {meta['public_id']}")
        print(f"  references : {', '.join(meta['references'])}")
        print(f"  pages      : {checks['pages']} (expected {meta['pages']})")
        print(f"  page sizes : {checks['sizes']} pt (expected [(288.0, 432.0)])")
        if checks["pages"] != meta["pages"] or checks["sizes"] != [(288.0, 432.0)]:
            ok = False
            print("  RESULT     : FAILED geometry check")
        if isinstance(checks["decoded"], str):
            print(f"  decoding   : {checks['decoded']}")
        else:
            for page in checks["decoded"]:
                for dpi, symbols in page["by_dpi"].items():
                    formats = ", ".join(f"{key}={value}" for key, value in sorted(symbols.items()))
                    print(f"  page {page['page']} @ {dpi} dpi: {formats or 'NOTHING DECODED'}")
                    if not symbols:
                        ok = False
        print()
    print("All geometry checks passed." if ok else "One or more checks FAILED.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
