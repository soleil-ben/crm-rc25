"""Internal 4 x 6 inch package labels.

One portrait page per selected active package, exactly 288 x 432 PDF points, black and
white, thermal-printer friendly (CRM.md section 8).

**This is not postage.** Every page carries the fixed warning
``SOLARIS INTERNAL LABEL - NOT CARRIER POSTAGE.`` The layout deliberately avoids courier
conventions so it cannot be mistaken for a carrier label, and it supplements rather than
replaces the carrier's own label.

**Encoded identifiers are never sacrificed to layout.** Long Vietnamese names wrap and,
past two lines, ellipsize; the Solaris Shipment ID, the package reference, the barcode,
and the QR payload are never shortened, scaled below the readable minimum, or truncated.

**Barcode sizing.** The module width is 2 printer dots at 203 dpi (72/203 x 2 = 0.709 pt,
about 0.25 mm). That is an exact whole number of dots on a 203 dpi thermal head and
almost exactly three dots at 300 dpi, which avoids the width jitter a fractional module
produces. Quiet zones are a full 0.25 inch on each side, comfortably above the 10x module
minimum. ``tests/test_labels.py`` decodes the rendered pages at both densities.

**Nothing here claims a label was printed.** The service records that a PDF was
*generated and downloaded*; no print system reports back, so no such claim is made.
"""

from __future__ import annotations

import hashlib
import io
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from reportlab.graphics import renderPDF
from reportlab.graphics.barcode import code128
from reportlab.graphics.barcode.qr import QrCodeWidget
from reportlab.graphics.shapes import Drawing
from reportlab.lib.units import inch
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
from sqlalchemy.orm import Session

from app.core.enums import ROUTE_GROUP_LABELS, LabelJobKind, value_label
from app.core.time_utils import to_timezone, utcnow
from app.models import (
    LabelPrintJob,
    LabelPrintJobPackage,
    OrganizationSettings,
    Shipment,
    ShipmentPackage,
    User,
)
from app.services import audit_service, package_service
from app.services.errors import ConflictError, ValidationError

# --- Page geometry ---------------------------------------------------------

PAGE_WIDTH = 4 * inch  # 288.0 pt
PAGE_HEIGHT = 6 * inch  # 432.0 pt
MARGIN = 12.0

# 2 dots at 203 dpi. Kept as an expression so the reasoning survives a future edit.
BARCODE_MODULE_WIDTH = (72.0 / 203.0) * 2
BARCODE_QUIET_ZONE = 0.25 * inch
BARCODE_HEIGHT = 0.62 * inch
# Below roughly 0.19 mm a Code 128 symbol stops scanning reliably on cheap handhelds.
MIN_MODULE_WIDTH = (72.0 / 25.4) * 0.19

QR_SIZE = 1.05 * inch

WARNING_TEXT = "SOLARIS INTERNAL LABEL — NOT CARRIER POSTAGE."

# --- Fonts -----------------------------------------------------------------

FONT_DIR = Path(__file__).resolve().parents[1] / "assets" / "fonts"
FONT_REGULAR = "SolarisLabel"
FONT_BOLD = "SolarisLabel-Bold"
_FONTS_REGISTERED = False

# An approved Solaris mark would live here. None ships: CRM.md section 14 and Design.md
# section 3 forbid inventing one, so the label falls back to an honest text wordmark.
LOGO_PATH = Path(__file__).resolve().parents[1] / "assets" / "brand" / "solaris-logo.png"


def register_fonts() -> None:
    """Embed the vendored Unicode faces once per process.

    Vietnamese diacritics are the reason: the fonts bundled with ReportLab do not cover
    the Latin Extended Additional block. See ``app/assets/fonts/README.md`` for the
    licensing and provenance of the embedded files.
    """
    global _FONTS_REGISTERED
    if _FONTS_REGISTERED:
        return
    pdfmetrics.registerFont(TTFont(FONT_REGULAR, str(FONT_DIR / "Roboto-Regular.ttf")))
    pdfmetrics.registerFont(TTFont(FONT_BOLD, str(FONT_DIR / "Roboto-Bold.ttf")))
    pdfmetrics.registerFontFamily(FONT_REGULAR, normal=FONT_REGULAR, bold=FONT_BOLD)
    _FONTS_REGISTERED = True


# --- Label content ---------------------------------------------------------


@dataclass(frozen=True)
class LabelContent:
    """Everything one label page shows. Built once and reused by preview and PDF."""

    shipment_public_id: str
    package_reference: str
    route_code: str
    route_name: str
    direction_label: str
    position_label: str
    booking_date: str
    recipient_name: str
    destination_lines: list[str]
    weight_display: str | None
    handling_note: str | None
    warehouse_location: str | None
    tracking_url: str
    warning: str = WARNING_TEXT
    wordmark: str = "Solaris Express"
    has_approved_logo: bool = False


@dataclass
class LabelDocument:
    pdf_bytes: bytes
    page_count: int
    contents: list[LabelContent] = field(default_factory=list)

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.pdf_bytes).hexdigest()


def tracking_base_url(org: OrganizationSettings | None) -> str:
    """Configured tracking base. Never a hard-coded production-domain assumption.

    The proposed ``track.solarisexpress.ca`` host does not exist yet, so the value comes
    from ``organization_settings.tracking_base_url`` (seeded from ``TRACKING_BASE_URL``)
    and the deployment owns it.
    """
    from app.core.config import settings as app_settings

    base = (org.tracking_base_url if org else None) or app_settings.tracking_base_url
    return base.rstrip("/")


def _weight_display(package: ShipmentPackage) -> str | None:
    """Gross weight in the unit it was recorded in, plus the canonical kg when different."""
    if package.weight_value is None:
        return None
    entered = Decimal(str(package.weight_value)).normalize()
    unit = package.weight_unit
    text = f"{entered:f} {unit}"
    if unit != "kg" and package.weight_kg is not None:
        canonical = Decimal(str(package.weight_kg)).normalize()
        text = f"{text} ({canonical:f} kg)"
    return text


def build_content(
    shipment: Shipment,
    package: ShipmentPackage,
    active: list[ShipmentPackage],
    *,
    base_url: str,
    timezone_name: str | None = None,
) -> LabelContent:
    if not shipment.public_id or not package.package_reference:
        raise ConflictError(
            "Labels are only available after a booking is confirmed, because an "
            "unconfirmed draft has no Solaris Shipment ID."
        )

    booking_at = shipment.booking_date or shipment.confirmed_at or shipment.created_at
    local = to_timezone(booking_at, timezone_name)

    destination = [
        ", ".join(
            part for part in (shipment.recipient_city, shipment.recipient_province_state) if part
        ),
        shipment.recipient_country_input or shipment.recipient_country_code or "",
    ]

    return LabelContent(
        shipment_public_id=shipment.public_id,
        package_reference=package.package_reference,
        route_code=shipment.route_group,
        route_name=ROUTE_GROUP_LABELS.get(shipment.route_group, shipment.route_group),
        direction_label=value_label(shipment.direction) if shipment.direction else "",
        position_label=package_service.position_label(package, active),
        booking_date=local.strftime("%d %b %Y") if local else "—",
        recipient_name=shipment.recipient_name or "—",
        destination_lines=[line for line in destination if line],
        weight_display=_weight_display(package),
        handling_note=package.handling_note,
        warehouse_location=package.warehouse_location,
        tracking_url=f"{base_url}/{package.package_reference}",
        has_approved_logo=LOGO_PATH.exists(),
    )


# --- Drawing helpers -------------------------------------------------------


def _wrap(text: str, font: str, size: float, width: float, max_lines: int) -> list[str]:
    """Wrap on word boundaries; ellipsize only the final line if it still overflows.

    Used for names and addresses only. Identifiers never pass through here.
    """
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if pdfmetrics.stringWidth(candidate, font, size) <= width or not current:
            current = candidate
        else:
            lines.append(current)
            current = word
            if len(lines) == max_lines:
                break
    if current and len(lines) < max_lines:
        lines.append(current)

    if not lines:
        return [""]
    remaining = " ".join(words)
    consumed = " ".join(" ".join(lines).split())
    if consumed != " ".join(remaining.split()) or (
        pdfmetrics.stringWidth(lines[-1], font, size) > width
    ):
        last = lines[-1]
        while last and pdfmetrics.stringWidth(last + "…", font, size) > width:
            last = last[:-1]
        lines[-1] = (last + "…") if last else "…"
    return lines


def _fit_identifier(text: str, font: str, max_size: float, width: float, floor: float) -> float:
    """Largest font size at which an identifier fits whole.

    An identifier is never shortened; if it will not fit even at ``floor`` the caller has
    a layout bug, and the floor is returned so the value still prints in full rather than
    silently losing characters.
    """
    size = max_size
    while size > floor and pdfmetrics.stringWidth(text, font, size) > width:
        size -= 0.25
    return max(size, floor)


def _barcode(reference: str) -> code128.Code128:
    bar = code128.Code128(
        reference,
        barHeight=BARCODE_HEIGHT,
        barWidth=BARCODE_MODULE_WIDTH,
        humanReadable=False,
        quiet=True,
        lquiet=BARCODE_QUIET_ZONE,
        rquiet=BARCODE_QUIET_ZONE,
    )
    available = PAGE_WIDTH - 2 * MARGIN
    if bar.width > available:  # pragma: no cover - guarded by test_labels
        raise ConflictError(
            "The package reference is too long to encode at a scannable module width on a "
            "4 x 6 label. The identifier is never shrunk to fit.",
            detail={"reference": reference, "required_width_pt": bar.width},
        )
    if BARCODE_MODULE_WIDTH < MIN_MODULE_WIDTH:  # pragma: no cover - constant guard
        raise ConflictError("Barcode module width is below the scannable minimum.")
    return bar


def _draw_label(pdf: canvas.Canvas, content: LabelContent) -> None:
    inner = PAGE_WIDTH - 2 * MARGIN
    y = PAGE_HEIGHT - MARGIN

    # --- Header: wordmark and route code ---------------------------------
    pdf.setFillGray(0)
    if content.has_approved_logo:  # pragma: no cover - no approved asset ships
        pdf.drawImage(
            str(LOGO_PATH),
            MARGIN,
            y - 26,
            width=96,
            height=24,
            preserveAspectRatio=True,
            mask="auto",
        )
    else:
        pdf.setFont(FONT_BOLD, 15)
        pdf.drawString(MARGIN, y - 18, content.wordmark)

    pdf.setFont(FONT_BOLD, 30)
    pdf.drawRightString(PAGE_WIDTH - MARGIN, y - 24, content.route_code)
    y -= 30

    pdf.setFont(FONT_REGULAR, 8.5)
    route_line = content.route_name
    if content.direction_label and content.direction_label != content.route_name:
        route_line = f"{content.route_name} · {content.direction_label}"
    pdf.drawRightString(PAGE_WIDTH - MARGIN, y - 8, route_line)
    y -= 16

    pdf.setLineWidth(1)
    pdf.line(MARGIN, y, PAGE_WIDTH - MARGIN, y)
    y -= 16

    # --- Shipment ID ------------------------------------------------------
    pdf.setFont(FONT_REGULAR, 7)
    pdf.drawString(MARGIN, y, "SOLARIS SHIPMENT ID")
    y -= 17
    size = _fit_identifier(content.shipment_public_id, FONT_BOLD, 16, inner, 11)
    pdf.setFont(FONT_BOLD, size)
    pdf.drawString(MARGIN, y, content.shipment_public_id)
    y -= 16

    pdf.setFont(FONT_REGULAR, 7)
    pdf.drawString(MARGIN, y, "PACKAGE REFERENCE")
    pdf.drawRightString(PAGE_WIDTH - MARGIN, y, content.position_label.upper())
    y -= 16
    size = _fit_identifier(content.package_reference, FONT_BOLD, 14, inner, 10)
    pdf.setFont(FONT_BOLD, size)
    pdf.drawString(MARGIN, y, content.package_reference)
    y -= 12

    # --- Code 128 barcode -------------------------------------------------
    bar = _barcode(content.package_reference)
    bar_x = (PAGE_WIDTH - bar.width) / 2
    y -= BARCODE_HEIGHT
    bar.drawOn(pdf, bar_x, y)
    y -= 11
    pdf.setFont(FONT_REGULAR, 8)
    pdf.drawCentredString(PAGE_WIDTH / 2, y, content.package_reference)
    y -= 12

    pdf.setLineWidth(0.5)
    pdf.line(MARGIN, y, PAGE_WIDTH - MARGIN, y)
    y -= 14

    # --- Recipient and destination ---------------------------------------
    pdf.setFont(FONT_REGULAR, 7)
    pdf.drawString(MARGIN, y, "DELIVER TO")
    y -= 15
    for line in _wrap(content.recipient_name, FONT_BOLD, 13, inner, 2):
        pdf.setFont(FONT_BOLD, 13)
        pdf.drawString(MARGIN, y, line)
        y -= 15
    for line in content.destination_lines:
        for wrapped in _wrap(line, FONT_REGULAR, 10.5, inner, 2):
            pdf.setFont(FONT_REGULAR, 10.5)
            pdf.drawString(MARGIN, y, wrapped)
            y -= 13

    # --- QR plus operational detail --------------------------------------
    qr_x = PAGE_WIDTH - MARGIN - QR_SIZE
    qr_y = MARGIN + 30
    _draw_qr(pdf, content.tracking_url, qr_x, qr_y)
    pdf.setFont(FONT_REGULAR, 6.5)
    pdf.drawCentredString(qr_x + QR_SIZE / 2, qr_y - 8, "Scan to track")

    detail_width = qr_x - MARGIN - 8
    detail_y = qr_y + QR_SIZE - 10
    rows: list[tuple[str, str]] = [("BOOKED", content.booking_date)]
    if content.weight_display:
        rows.append(("GROSS WEIGHT", content.weight_display))
    if content.warehouse_location:
        rows.append(("LOCATION", content.warehouse_location))
    for caption, value in rows:
        pdf.setFont(FONT_REGULAR, 6.5)
        pdf.drawString(MARGIN, detail_y, caption)
        pdf.setFont(FONT_BOLD, 10)
        for line in _wrap(value, FONT_BOLD, 10, detail_width, 1):
            pdf.drawString(MARGIN, detail_y - 12, line)
        detail_y -= 26

    if content.handling_note:
        pdf.setFont(FONT_REGULAR, 6.5)
        pdf.drawString(MARGIN, detail_y, "HANDLING")
        pdf.setFont(FONT_BOLD, 9)
        for line in _wrap(content.handling_note, FONT_BOLD, 9, detail_width, 2):
            pdf.drawString(MARGIN, detail_y - 11, line)
            detail_y -= 11
        detail_y -= 15

    # --- Fixed warning ----------------------------------------------------
    pdf.setLineWidth(0.5)
    pdf.line(MARGIN, MARGIN + 16, PAGE_WIDTH - MARGIN, MARGIN + 16)
    pdf.setFont(FONT_BOLD, 7.5)
    pdf.drawCentredString(PAGE_WIDTH / 2, MARGIN + 6, content.warning)


def _draw_qr(pdf: canvas.Canvas, payload: str, x: float, y: float) -> None:
    widget = QrCodeWidget(payload, barLevel="M")
    bounds = widget.getBounds()
    width = bounds[2] - bounds[0]
    height = bounds[3] - bounds[1]
    drawing = Drawing(QR_SIZE, QR_SIZE, transform=[QR_SIZE / width, 0, 0, QR_SIZE / height, 0, 0])
    drawing.add(widget)
    renderPDF.draw(drawing, pdf, x, y)


# --- Document generation ---------------------------------------------------


def render_pdf(contents: list[LabelContent]) -> LabelDocument:
    """One 288 x 432 pt portrait page per label. No other page size is ever produced."""
    if not contents:
        raise ValidationError("Select at least one active package to print.", field="package_ids")
    register_fonts()

    buffer = io.BytesIO()
    # ``invariant`` omits the creation timestamp and random document ID, so regenerating
    # the same packages produces byte-identical output. That is what makes the recorded
    # ``document_sha256`` a usable check that a reprint really is the same label.
    pdf = canvas.Canvas(buffer, pagesize=(PAGE_WIDTH, PAGE_HEIGHT), invariant=1)
    pdf.setTitle("Solaris Express internal package labels")
    pdf.setSubject("Internal label — not carrier postage")
    for content in contents:
        pdf.setPageSize((PAGE_WIDTH, PAGE_HEIGHT))
        _draw_label(pdf, content)
        pdf.showPage()
    pdf.save()
    return LabelDocument(pdf_bytes=buffer.getvalue(), page_count=len(contents), contents=contents)


def select_packages(
    db: Session, shipment: Shipment, package_ids: list[int] | None
) -> tuple[list[ShipmentPackage], str]:
    """Resolve the print selection to active packages plus the job kind.

    Cancelled packages are never printed: their references remain valid for lookup but a
    cancelled parcel must not receive a fresh label.
    """
    active = package_service.active_packages(db, shipment.id)
    if not package_ids:
        return active, LabelJobKind.ALL_ACTIVE

    wanted = list(dict.fromkeys(package_ids))
    by_id = {package.id: package for package in active}
    missing = [package_id for package_id in wanted if package_id not in by_id]
    if missing:
        raise ValidationError(
            "Some selected packages are not active packages on this shipment.",
            field="package_ids",
            detail={"package_ids": missing},
        )
    chosen = [by_id[package_id] for package_id in wanted]
    kind = LabelJobKind.SINGLE if len(chosen) == 1 else LabelJobKind.SELECTED
    if len(chosen) == len(active):
        kind = LabelJobKind.ALL_ACTIVE
    return chosen, kind


def build_label_document(
    db: Session,
    shipment: Shipment,
    *,
    org: OrganizationSettings | None,
    package_ids: list[int] | None = None,
) -> tuple[LabelDocument, list[ShipmentPackage], str]:
    packages, kind = select_packages(db, shipment, package_ids)
    if not packages:
        raise ValidationError("This shipment has no active packages to print.", field="package_ids")
    active = package_service.active_packages(db, shipment.id)
    base = tracking_base_url(org)
    timezone_name = org.office_timezone if org else None
    contents = [
        build_content(shipment, package, active, base_url=base, timezone_name=timezone_name)
        for package in packages
    ]
    return render_pdf(contents), packages, kind


def record_generation(
    db: Session,
    shipment: Shipment,
    packages: list[ShipmentPackage],
    document: LabelDocument,
    *,
    kind: str,
    actor: User | None = None,
    ip_address: str | None = None,
) -> LabelPrintJob:
    """Record that labels were generated and downloaded.

    Deliberately not called a print record: nothing confirms a physical printer produced
    anything (CRM.md section 8).
    """
    previous = db.query(LabelPrintJob).filter(LabelPrintJob.shipment_id == shipment.id).count()
    job = LabelPrintJob(
        shipment_id=shipment.id,
        kind=kind,
        is_reprint=previous > 0,
        page_count=document.page_count,
        document_sha256=document.sha256,
        generated_at=utcnow(),
        generated_by_user_id=actor.id if actor else None,
    )
    db.add(job)
    db.flush()
    for package in packages:
        db.add(
            LabelPrintJobPackage(
                job_id=job.id,
                package_id=package.id,
                package_reference=package.package_reference or "",
            )
        )
    db.flush()

    audit_service.record_audit(
        db,
        action="shipment.label_generate",
        entity_type="shipment",
        entity_id=shipment.id,
        summary=(
            f"Generated {document.page_count} label page(s) for {shipment.public_id}"
            + (" (reprint)" if job.is_reprint else "")
        ),
        actor=actor,
        ip_address=ip_address,
        detail={
            "kind": kind,
            "is_reprint": job.is_reprint,
            "page_count": document.page_count,
            "package_references": [package.package_reference for package in packages],
            "document_sha256": document.sha256,
        },
    )
    return job


def print_history(db: Session, shipment_id: int, limit: int = 50) -> list[LabelPrintJob]:
    return list(
        db.query(LabelPrintJob)
        .filter(LabelPrintJob.shipment_id == shipment_id)
        .order_by(LabelPrintJob.generated_at.desc(), LabelPrintJob.id.desc())
        .limit(limit)
        .all()
    )


def preview_payload(db: Session, shipment: Shipment, *, org: OrganizationSettings | None) -> dict:
    """Metadata the browser preview renders at the exact 4 x 6 ratio.

    The screen preview may simplify visual detail; the PDF is the authority on
    dimensions and scan quality (Design.md section 10).
    """
    active = package_service.active_packages(db, shipment.id)
    base = tracking_base_url(org)
    timezone_name = org.office_timezone if org else None
    labels = []
    for package in active:
        content = build_content(
            shipment, package, active, base_url=base, timezone_name=timezone_name
        )
        labels.append(
            {
                "package_id": package.id,
                "package_reference": content.package_reference,
                "position_label": content.position_label,
                "shipment_public_id": content.shipment_public_id,
                "route_code": content.route_code,
                "route_name": content.route_name,
                "direction_label": content.direction_label,
                "booking_date": content.booking_date,
                "recipient_name": content.recipient_name,
                "destination_lines": content.destination_lines,
                "weight_display": content.weight_display,
                "handling_note": content.handling_note,
                "warehouse_location": content.warehouse_location,
                "tracking_url": content.tracking_url,
                "warning": content.warning,
                "wordmark": content.wordmark,
                "has_approved_logo": content.has_approved_logo,
            }
        )
    return {
        "shipment_id": shipment.id,
        "shipment_public_id": shipment.public_id,
        "page_width_pt": PAGE_WIDTH,
        "page_height_pt": PAGE_HEIGHT,
        "print_instruction": (
            "Print at actual size: 4 × 6 in, portrait, 100% scale, browser headers and footers off."
        ),
        "tracking_base_url": base,
        "labels": labels,
    }


def label_filename(shipment: Shipment, page_count: int) -> str:
    stem = shipment.public_id or f"draft-{shipment.id}"
    suffix = "label" if page_count == 1 else f"labels-{page_count}"
    return f"solaris-{stem}-{suffix}.pdf"


def generated_at_display(job: LabelPrintJob, timezone_name: str | None = None) -> datetime | None:
    return to_timezone(job.generated_at, timezone_name)
