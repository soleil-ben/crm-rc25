"""Vendor rate-email intake, version diff and approval (Phase 13H, OD-76).

A vendor rate email -- an ``.eml`` file with the tariff workbook attached -- becomes a
**draft** tariff version through the existing importer (``tariff_import_service``). Only a
designated approver (a setting; by default Ben, OD-76) activates it. Nothing here ever
activates a version by itself.

**There is no live mailbox connection** (stand-in): no IMAP, Graph or Gmail call exists in
this code, and no credential is read. Emails arrive by staff upload
(``POST /api/v1/tariffs/intake/upload``) or from a folder the intake worker reads
(``app/workers/tariff_intake_worker.py``).

How an email is read, and why it is safe:

* **Bounded.** A file over ``tariff_intake_max_eml_bytes`` is refused before it is parsed;
  the workbook attachment is still held to ``tariff_import_max_bytes``.
* **Headers and attachments only.** Python's ``email`` package (``policy.default``) reads
  the headers it needs (Message-ID, From, Subject, Date) and the attachment parts. Text and
  HTML parts are never decoded, rendered or stored; no link is followed; nothing is run.
* **Exactly one ``.xlsx``.** No attachment: ``no_attachment``. Refused by rule -- attachments
  but no ``.xlsx``, more than one ``.xlsx``, a workbook over the size cap, bytes that are not
  a zip container at all, an archive bomb: ``rejected`` with the reason. A zip container that
  cannot be read as a workbook (here or by the importer), or an unreadable email: ``failed``.
* **The staff directory is stripped first.** Before any hash, store or parse, a worksheet
  named ``DS SDT...`` is removed at the zip level without reading its cells
  (``app/pricing/xlsx_guard.py``); the importer and the held folder only ever see the
  stripped workbook, and ``attachment_sha256`` is its digest.
* **Once.** One row per (Message-ID, sender) (or per file digest when there is no id); a
  second copy is answered with the first row. The same workbook in a different email is a
  ``duplicate`` (the importer's SHA-256 check).
* **Known senders only.** A sender whose domain is not in ``allowed_sender_domains`` is
  ``held_sender``: recorded, not imported, until an approver releases it. The default list
  is empty, so every email waits for an approver.

Approval: ``approve`` and ``reject`` (and the existing activate route) need the actor's
email in ``approver_emails`` **and** ``tariff:manage``. A service call with ``actor=None``
(seed scripts, demo and test fixtures) calls ``tariff_import_service.activate_version``
directly and is unaffected. ``TariffVersionStatus`` has no rejected state and the version
table is not altered (DEC-0181): a rejected draft stays ``draft``, and the rejection lives
on the intake row and in the audit log.
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from pathlib import Path
from zoneinfo import ZoneInfo

from email_validator import EmailNotValidError, validate_email
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import commit_with_retry, run_unit_with_retry
from app.core.enums import (
    Role,
    SurchargeSection,
    TariffIntakeSource,
    TariffIntakeStatus,
    TariffProductMode,
    TariffVersionStatus,
)
from app.core.permissions import Permission, has_permission
from app.core.time_utils import utcnow
from app.models import (
    TariffEmailIntake,
    TariffProduct,
    TariffRateBracket,
    TariffSurchargeRule,
    TariffVersion,
    TariffVersionReview,
    User,
)
from app.models.tariff_intake import (
    DEFAULT_APPROVER_EMAILS,
    DEFAULT_INTAKE_MAILBOX,
    TariffIntakeSettings,
)
from app.pricing import xlsx_guard
from app.services import audit_service, quote_expiry_service, tariff_import_service
from app.services.errors import (
    ConflictError,
    NotFoundError,
    PermissionDeniedError,
    ValidationError,
)

#: The business's time zone: the email's Date becomes the draft's effective date there.
BUSINESS_TZ = ZoneInfo("America/Toronto")
XLSX_MAGIC = b"PK\x03\x04"

MAX_MESSAGE_ID = 255
MAX_SUBJECT = 300
MAX_LABEL = 120
MAX_ERROR = 500
#: What the audit records as the old value on the first save of the intake settings.
DEFAULT_MARKER = "owner default"
MAX_REASON = 400
MAX_APPROVERS = 20
MAX_DOMAINS = 50
#: An email Date further than this from the intake time is not trusted as the effective date.
DATE_WINDOW_DAYS = 60
#: Entries per list in a diff; the counts are always complete.
MAX_DIFF_ENTRIES = 300

AIR_SECTIONS = (SurchargeSection.HCM_AIR.value, SurchargeSection.HAN_AIR.value)
_CONTROL = re.compile(r"[\x00-\x1f\x7f]+")
_DOMAIN = re.compile(r"^(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")

NOT_APPROVER_MESSAGE = (
    "Only a designated tariff approver may approve, reject or activate a tariff version "
    "(OD-76). An administrator can change the approver list under Tariff updates."
)


def normalize_email(value: str | None) -> str:
    return (value or "").strip().lower()


def _plain(value: str | None, limit: int) -> str | None:
    """One line of plain text, bounded. Control characters (and so newlines) become spaces."""
    if value is None:
        return None
    text = _CONTROL.sub(" ", str(value)).strip()
    return text[:limit] or None


# --- Settings ----------------------------------------------------------------------------


def get_settings(db: Session) -> TariffIntakeSettings:
    """The saved settings, or the owner's defaults as an unsaved row (reading never writes)."""
    row = db.get(TariffIntakeSettings, 1)
    if row is None:
        row = TariffIntakeSettings(
            id=1,
            mailbox_address=DEFAULT_INTAKE_MAILBOX,
            approver_emails=list(DEFAULT_APPROVER_EMAILS),
            allowed_sender_domains=[],
            updated_at=utcnow(),
        )
    return row


def _clean_emails(values: list[str]) -> list[str]:
    if not isinstance(values, list):
        raise ValidationError(
            "Approvers must be a list of email addresses.", field="approver_emails"
        )
    cleaned: list[str] = []
    for value in values:
        if not isinstance(value, str):
            raise ValidationError(
                "Each approver must be an email address.", field="approver_emails"
            )
        try:
            address = validate_email(value.strip(), check_deliverability=False).normalized
        except EmailNotValidError as error:
            raise ValidationError(
                f"{value.strip()[:80]!r} is not a valid email address.", field="approver_emails"
            ) from error
        address = normalize_email(address)
        if address not in cleaned:
            cleaned.append(address)
    if not cleaned:
        raise ValidationError(
            "At least one approver is required; otherwise no tariff could ever be approved.",
            field="approver_emails",
        )
    if len(cleaned) > MAX_APPROVERS:
        raise ValidationError(f"At most {MAX_APPROVERS} approvers.", field="approver_emails")
    return cleaned


def _clean_domains(values: list[str]) -> list[str]:
    if not isinstance(values, list):
        raise ValidationError("Sender domains must be a list.", field="allowed_sender_domains")
    cleaned: list[str] = []
    for value in values:
        domain = value.strip().lower().lstrip("@") if isinstance(value, str) else ""
        if not _DOMAIN.match(domain):
            raise ValidationError(
                f"{str(value)[:80]!r} is not a domain name such as vendor.example.com.",
                field="allowed_sender_domains",
            )
        if domain not in cleaned:
            cleaned.append(domain)
    if len(cleaned) > MAX_DOMAINS:
        raise ValidationError(f"At most {MAX_DOMAINS} domains.", field="allowed_sender_domains")
    return cleaned


def _approver_change_mode(db: Session, actor: User | None, current: list[str]) -> str:
    """Who may change the approver list: a current approver; scripts (no actor); or, when no
    current approver is an active administrator (nobody could ever change it), any
    administrator -- a recovery, audited as such."""
    if actor is None:
        return "system"
    if is_approver(db, actor):
        return "approver"
    from app.services import staff_grant_service  # noqa: PLC0415

    holders = staff_grant_service.holders(db, staff_grant_service.TARIFF_APPROVE)
    if not any(u.role == Role.ADMIN and u.is_active for u in holders):
        return "recovery"
    raise PermissionDeniedError(
        "Only a current tariff approver may change the approver list (OD-76).",
        detail={"reason": "not_approver"},
    )


def update_settings(
    db: Session,
    *,
    approver_emails: list[str] | None = None,
    allowed_sender_domains: list[str] | None = None,
    mailbox_address: str | None = None,
    actor: User | None,
) -> TariffIntakeSettings:
    """Save the intake settings.

    ``mailbox_address`` is service-only (no route sets it): it is the address shown as where
    rate emails go, and the UAT seed sets a reserved test address so the UAT database never
    holds the production default (Phase 17).

    On the first save the audit records the old values as ``"owner default"`` rather than
    copying the defaults (which name a real person) into the audit log; the defaults are in
    ``app.models.tariff_intake``.
    """
    row = get_settings(db)
    first_save = row not in db
    old_approvers = list(row.approver_emails or [])
    old_domains = list(row.allowed_sender_domains or [])
    old_mailbox = row.mailbox_address
    new_mailbox = old_mailbox
    if mailbox_address is not None:
        try:
            new_mailbox = normalize_email(
                validate_email(mailbox_address.strip(), check_deliverability=False).normalized
            )
        except EmailNotValidError as error:
            raise ValidationError(
                "The intake mailbox must be an email address.", field="mailbox_address"
            ) from error
    new_approvers = _clean_emails(approver_emails) if approver_emails is not None else old_approvers
    new_domains = (
        _clean_domains(allowed_sender_domains)
        if allowed_sender_domains is not None
        else old_domains
    )
    mode = None
    if new_approvers != old_approvers:
        mode = _approver_change_mode(db, actor, old_approvers)
    if row not in db:
        db.add(row)
    row.approver_emails = new_approvers
    row.allowed_sender_domains = new_domains
    row.mailbox_address = new_mailbox
    row.updated_at = utcnow()
    row.updated_by_user_id = actor.id if actor else None
    db.flush()
    if approver_emails is not None:
        # The list is a way to set the ``tariff:approve`` grants (DEC-0268).
        from app.services import staff_grant_service  # noqa: PLC0415

        staff_grant_service.sync_holders(
            db, staff_grant_service.TARIFF_APPROVE, new_approvers, actor=actor
        )
    audit_service.record_audit(
        db,
        action=(
            "tariff_intake.approvers_recovered"
            if mode == "recovery"
            else "tariff_intake.settings_updated"
        ),
        entity_type="tariff_intake_settings",
        entity_id=row.id,
        summary=(
            "Tariff approvers set by an administrator: no current approver was an active "
            "administrator (recovery)"
            if mode == "recovery"
            else "Tariff intake settings updated"
        ),
        actor=actor,
        detail={
            "approver_emails": {
                "old": DEFAULT_MARKER if first_save else old_approvers,
                "new": new_approvers,
            },
            "allowed_sender_domains": {"old": old_domains, "new": new_domains},
            "mailbox_address_changed": new_mailbox != old_mailbox,
            "approver_change": mode,
        },
    )
    return row


# --- Who may approve -----------------------------------------------------------------------


def is_approver(db: Session, user: User | None) -> bool:
    """``tariff:manage`` from the role **and** the ``tariff:approve`` grant (DEC-0268) -- a
    permission held by named accounts, not an address on a list."""
    if user is None or not has_permission(user.role, Permission.TARIFF_MANAGE):
        return False
    from app.services import staff_grant_service  # noqa: PLC0415

    return staff_grant_service.has_grant(db, user, staff_grant_service.TARIFF_APPROVE)


def pending_counts(db: Session) -> tuple[int, int]:
    """Phase 15: ``(drafts awaiting a decision, held-sender intakes)`` for the approver badge.

    A draft awaits review while no approver decision is recorded for it (a rejected draft
    stays ``draft`` but has a decision, so it is not counted)."""
    decided = select(TariffVersionReview.id).where(
        TariffVersionReview.tariff_version_id == TariffVersion.id
    )
    drafts = (
        db.scalar(
            select(func.count())
            .select_from(TariffVersion)
            .where(TariffVersion.status == TariffVersionStatus.DRAFT, ~decided.exists())
        )
        or 0
    )
    held = (
        db.scalar(
            select(func.count())
            .select_from(TariffEmailIntake)
            .where(TariffEmailIntake.status == TariffIntakeStatus.HELD_SENDER)
        )
        or 0
    )
    return int(drafts), int(held)


def require_approver(db: Session, user: User | None) -> None:
    if not is_approver(db, user):
        raise PermissionDeniedError(NOT_APPROVER_MESSAGE, detail={"reason": "not_approver"})


def review_of(db: Session, version: TariffVersion) -> TariffVersionReview | None:
    return db.scalar(
        select(TariffVersionReview).where(TariffVersionReview.tariff_version_id == version.id)
    )


def check_can_activate(db: Session, version: TariffVersion, actor: User) -> None:
    """The route-level rule for every staff activation (approve and the activate route)."""
    require_approver(db, actor)
    review = review_of(db, version)
    if review is not None and review.decision == "rejected":
        raise ConflictError(
            f"{version.public_id} was rejected by an approver and cannot be activated."
        )


# --- Reading an email ---------------------------------------------------------------------


@dataclass
class ParsedEmail:
    message_id: str
    sender: str | None = None
    subject: str | None = None
    received_at: datetime | None = None
    #: (file name, bytes) for each attachment part. Text and HTML bodies are never read.
    attachments: list[tuple[str, bytes]] = field(default_factory=list)
    problem: str | None = None


def _header(message: EmailMessage, name: str) -> object | None:
    try:
        return message[name]
    except Exception:  # noqa: BLE001 - a malformed header is a missing header
        return None


def _message_id(message: EmailMessage, digest_id: str) -> str:
    value = _plain(str(_header(message, "Message-ID") or ""), 10_000)
    if not value:
        return digest_id
    if len(value) > MAX_MESSAGE_ID:
        return "sha256:" + hashlib.sha256(value.encode("utf-8", "replace")).hexdigest()
    return value


def _sender(message: EmailMessage) -> str | None:
    header = _header(message, "From")
    if header is None:
        return None
    try:
        addresses = getattr(header, "addresses", ())
        address = addresses[0].addr_spec if addresses else ""
    except Exception:  # noqa: BLE001
        address = ""
    address = normalize_email(_plain(address, 320))
    if "@" not in address or address.startswith("@") or address.endswith("@"):
        return None
    return address


def _received_at(message: EmailMessage) -> datetime | None:
    header = _header(message, "Date")
    moment = getattr(header, "datetime", None) if header is not None else None
    if not isinstance(moment, datetime):
        return None
    if moment.tzinfo is None:
        return moment
    return moment.astimezone(UTC).replace(tzinfo=None)


def _attachment_name(raw: str | None) -> str:
    name = _plain(raw, 1000) or ""
    name = name.replace("\\", "/").rsplit("/", 1)[-1]
    return name[:255] or "attachment"


def _attachments(message: EmailMessage) -> list[tuple[str, bytes]]:
    found: list[tuple[str, bytes]] = []
    for part in message.walk():
        if part.is_multipart():
            continue
        try:
            filename = part.get_filename()
            disposition = part.get_content_disposition()
        except Exception:  # noqa: BLE001
            continue
        if not filename and disposition != "attachment":
            continue  # a body part: never decoded
        try:
            payload = part.get_payload(decode=True)
        except Exception:  # noqa: BLE001
            payload = None
        found.append((_attachment_name(filename), payload if isinstance(payload, bytes) else b""))
    return found


def parse_eml(raw: bytes) -> ParsedEmail:
    """Headers and attachment parts of an email. Never raises for a malformed file."""
    digest_id = "sha256:" + hashlib.sha256(raw).hexdigest()
    try:
        message = BytesParser(policy=policy.default).parsebytes(raw)
    except Exception:  # noqa: BLE001
        return ParsedEmail(message_id=digest_id, problem="The file is not a readable email.")
    parsed = ParsedEmail(message_id=_message_id(message, digest_id))
    parsed.sender = _sender(message)
    subject = _header(message, "Subject")
    parsed.subject = _plain(str(subject), MAX_SUBJECT) if subject is not None else None
    parsed.received_at = _received_at(message)
    if not list(message.keys()) or parsed.sender is None:
        parsed.problem = "The file is not a readable email (no sender address)."
        return parsed
    parsed.attachments = _attachments(message)
    return parsed


def effective_date(received_at: datetime | None, now: datetime) -> date:
    """The email's Date as a calendar date in Toronto (the intake time when it has none)."""
    moment = received_at or now
    return moment.replace(tzinfo=UTC).astimezone(BUSINESS_TZ).date()


# --- Intake --------------------------------------------------------------------------------


@dataclass
class IntakeResult:
    intake: TariffEmailIntake
    #: False when this email (by Message-ID and sender) had been received before; ``intake``
    #: is then the first row, unchanged.
    created: bool = True
    #: A held sender's (stripped) workbook, for the caller to keep in the held folder.
    held_attachment: bytes | None = None


@dataclass
class _Selection:
    status: str | None = None
    error: str | None = None
    name: str | None = None
    content: bytes | None = None
    dropped_sheets: list[str] = field(default_factory=list)


def _domain_allowed(row: TariffIntakeSettings, sender: str) -> bool:
    domain = sender.rsplit("@", 1)[-1]
    return domain in {d.lower() for d in row.allowed_sender_domains or []}


def _select_workbook(parsed: ParsedEmail) -> _Selection:
    """The one workbook to import, guarded and stripped of any staff-directory sheet.

    Statuses: an unreadable email is ``failed``; no attachment is ``no_attachment``; a
    refusal by rule (no ``.xlsx``, several, too large, not a zip container at all, an archive
    bomb) is ``rejected``; an ``.xlsx`` zip that cannot be read as a workbook is ``failed``
    (here, or by the importer). ``status`` None means: import ``content``.
    """
    if parsed.problem:
        return _Selection(TariffIntakeStatus.FAILED, parsed.problem)
    if not parsed.attachments:
        return _Selection(TariffIntakeStatus.NO_ATTACHMENT, "The email has no attachment.")
    xlsx = [(n, b) for n, b in parsed.attachments if n.lower().endswith(".xlsx")]
    if not xlsx:
        return _Selection(
            TariffIntakeStatus.REJECTED,
            f"No .xlsx workbook attached ({len(parsed.attachments)} other attachment(s)); "
            "only an .xlsx tariff workbook is imported.",
        )
    if len(xlsx) > 1:
        return _Selection(
            TariffIntakeStatus.REJECTED,
            f"{len(xlsx)} .xlsx attachments; exactly one workbook per email is imported. "
            "Upload the right workbook on its own instead.",
        )
    name, raw = xlsx[0]
    cap = settings.tariff_import_max_bytes
    if len(raw) > cap:
        return _Selection(
            TariffIntakeStatus.REJECTED,
            f"The workbook is larger than the {cap // (1024 * 1024)} MB limit.",
            name,
        )
    if not raw.startswith(XLSX_MAGIC):
        return _Selection(
            TariffIntakeStatus.REJECTED, "The attachment is not an .xlsx workbook.", name
        )
    try:
        content, dropped = xlsx_guard.check_and_strip(raw)
    except xlsx_guard.WorkbookRefused as error:
        return _Selection(TariffIntakeStatus.REJECTED, f"The workbook is refused: {error}.", name)
    except xlsx_guard.WorkbookUnreadable as error:
        return _Selection(
            TariffIntakeStatus.FAILED, f"The workbook could not be read: {error}.", name
        )
    return _Selection(None, None, name, content, dropped)


def effective_date_for(received_at: datetime | None, now: datetime) -> tuple[date, str | None]:
    """The email's Date as a Toronto calendar date, unless it is missing or more than
    ``DATE_WINDOW_DAYS`` from the intake time: then the intake date, with a warning."""
    if received_at is None:
        return effective_date(None, now), "The email has no Date; the intake date was used."
    if abs(received_at - now) > timedelta(days=DATE_WINDOW_DAYS):
        return effective_date(None, now), (
            f"The email's Date ({received_at.date().isoformat()}) is more than "
            f"{DATE_WINDOW_DAYS} days from the intake date; the intake date was used."
        )
    return effective_date(received_at, now), None


def _import_into(
    db: Session,
    intake: TariffEmailIntake,
    content: bytes,
    *,
    actor: User | None,
    now: datetime,
) -> None:
    """Import the (stripped) workbook as a draft and record the outcome on the intake row."""
    label = _plain(intake.subject, MAX_LABEL)
    effective, intake.warning = effective_date_for(intake.received_at, now)
    try:
        with db.begin_nested():
            version = tariff_import_service.import_workbook(
                db,
                content,
                file_name=intake.attachment_name,
                effective_from=effective,
                label=label,
                actor=actor,
                now=now,
            )
    except ConflictError as error:
        intake.status = TariffIntakeStatus.DUPLICATE
        intake.error = _plain(error.message, MAX_ERROR)
        existing = db.scalar(
            select(TariffVersion).where(TariffVersion.source_sha256 == intake.attachment_sha256)
        )
        intake.tariff_version_id = existing.id if existing else None
        return
    except ValidationError as error:
        intake.status = TariffIntakeStatus.FAILED
        intake.error = _plain(error.message, MAX_ERROR)
        return
    intake.status = TariffIntakeStatus.IMPORTED
    intake.tariff_version_id = version.id
    intake.error = None


def _audit_outcome(db: Session, intake: TariffEmailIntake, actor: User | None) -> None:
    version = db.get(TariffVersion, intake.tariff_version_id) if intake.tariff_version_id else None
    audit_service.record_audit(
        db,
        action=f"tariff_intake.{intake.status}",
        entity_type="tariff_email_intake",
        entity_id=intake.id,
        summary=f"Rate email {intake.id}: {intake.status}"
        + (f" ({version.public_id}, draft)" if version and intake.status == "imported" else ""),
        actor=actor,
        detail={
            "source": intake.source,
            "status": intake.status,
            "attachment_sha256": intake.attachment_sha256,
            "tariff_version": version.public_id if version else None,
            "error": intake.error,
            "warning": intake.warning,
        },
    )


def _process(
    db: Session,
    intake: TariffEmailIntake,
    parsed: ParsedEmail,
    *,
    actor: User | None,
    now: datetime,
) -> bytes | None:
    """Decide and record what becomes of the email. Returns a held workbook to keep."""
    selection = _select_workbook(parsed)
    intake.attachment_name = selection.name
    intake.attachment_sha256 = (
        hashlib.sha256(selection.content).hexdigest() if selection.content is not None else None
    )
    intake.tariff_version_id = None
    intake.warning = None
    held: bytes | None = None
    if selection.status is not None:
        intake.status = selection.status
        intake.error = _plain(selection.error, MAX_ERROR)
    elif not _domain_allowed(get_settings(db), parsed.sender or ""):
        intake.status = TariffIntakeStatus.HELD_SENDER
        intake.error = (
            "The sender's domain is not on the allowed list; an approver must release "
            "this email before it is imported."
        )
        held = selection.content
    else:
        _import_into(db, intake, selection.content, actor=actor, now=now)
    db.flush()
    _audit_outcome(db, intake, actor)
    return held


def _find_existing(db: Session, message_id: str, sender: str | None) -> TariffEmailIntake | None:
    condition = (
        TariffEmailIntake.sender.is_(None) if sender is None else TariffEmailIntake.sender == sender
    )
    return db.scalar(
        select(TariffEmailIntake).where(TariffEmailIntake.message_id == message_id, condition)
    )


def ingest_eml(
    db: Session,
    raw_bytes: bytes,
    *,
    source: str,
    actor: User | None,
    now: datetime | None = None,
) -> IntakeResult:
    """Record one rate email and, when it qualifies, import its workbook as a draft.

    The caller commits. Never activates. A file over the size cap is refused with
    ``ValidationError`` before anything is parsed or recorded.
    """
    now = now or utcnow()
    source = TariffIntakeSource(source).value
    limit = settings.tariff_intake_max_eml_bytes
    if len(raw_bytes) > limit:
        raise ValidationError(
            f"The email is larger than the {limit // (1024 * 1024)} MB limit.", field="file"
        )
    parsed = parse_eml(raw_bytes)

    existing = _find_existing(db, parsed.message_id, parsed.sender)
    if existing is not None:
        audit_service.record_audit(
            db,
            action="tariff_intake.duplicate_message",
            entity_type="tariff_email_intake",
            entity_id=existing.id,
            summary=f"Rate email {existing.id} received again; not processed twice",
            actor=actor,
            detail={"source": source, "status": existing.status},
        )
        held = None
        # A held email whose kept workbook was lost: an identical re-send restores it.
        if (
            existing.status == TariffIntakeStatus.HELD_SENDER
            and not held_path(existing.id).exists()
        ):
            selection = _select_workbook(parsed)
            if (
                selection.content is not None
                and hashlib.sha256(selection.content).hexdigest() == existing.attachment_sha256
            ):
                held = selection.content
        return IntakeResult(intake=existing, created=False, held_attachment=held)

    intake = TariffEmailIntake(
        message_id=parsed.message_id,
        sender=parsed.sender,
        subject=parsed.subject,
        received_at=parsed.received_at,
        source=source,
        source_sha256=hashlib.sha256(raw_bytes).hexdigest(),
        status=TariffIntakeStatus.RECEIVED,
        created_at=now,
    )
    db.add(intake)
    db.flush()
    audit_service.record_audit(
        db,
        action="tariff_intake.received",
        entity_type="tariff_email_intake",
        entity_id=intake.id,
        summary=f"Rate email {intake.id} received ({source})",
        actor=actor,
        detail={
            "source": source,
            "sender_domain": parsed.sender.rsplit("@", 1)[-1] if parsed.sender else None,
        },
    )
    held = _process(db, intake, parsed, actor=actor, now=now)
    return IntakeResult(intake=intake, held_attachment=held)


# --- The held folder ------------------------------------------------------------------------


def held_path(intake_id: int) -> Path:
    return settings.tariff_intake_path / "held" / f"intake-{intake_id}.xlsx"


def _write_temp(intake_id: int, content: bytes) -> Path:
    """The held workbook, written **before** the commit under a temporary name."""
    final = held_path(intake_id)
    final.parent.mkdir(parents=True, exist_ok=True)
    temp = final.with_name(f"{final.name}.{uuid.uuid4().hex}.tmp")
    temp.write_bytes(content)
    return temp


def archive_held(intake_id: int) -> None:
    """Move a released workbook beside the processed emails. Never deletes."""
    path = held_path(intake_id)
    if path.exists():
        target = settings.tariff_intake_path / "processed" / f"released-intake-{intake_id}.xlsx"
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(path), str(target))


def _run_with_held(db: Session, work) -> IntakeResult:
    """Run ``work`` as one unit (DEC-0204) with its held workbook written to a temporary file
    before the commit and renamed into place after it; a failed unit leaves no file."""
    temps: list[Path] = []

    def unit():
        for temp in temps:
            temp.unlink(missing_ok=True)  # our own temporary file from a re-run attempt
        temps.clear()
        result = work()
        if result.held_attachment is not None:
            temps.append(_write_temp(result.intake.id, result.held_attachment))
        return result

    try:
        result = run_unit_with_retry(db, unit)
    except BaseException:
        for temp in temps:
            temp.unlink(missing_ok=True)
        raise
    for temp in temps:
        os.replace(temp, held_path(result.intake.id))
    return result


def ingest_and_commit(
    db: Session, raw_bytes: bytes, *, source: str, actor: User | None
) -> IntakeResult:
    """``ingest_eml`` as one committed unit. Two copies of one email at once: the second
    meets the unique key and is answered with the first row."""
    try:
        return _run_with_held(db, lambda: ingest_eml(db, raw_bytes, source=source, actor=actor))
    except IntegrityError:
        db.rollback()
        parsed = parse_eml(raw_bytes)
        existing = _find_existing(db, parsed.message_id, parsed.sender)
        if existing is None:
            raise
        return IntakeResult(intake=existing, created=False)


def get_intake(db: Session, intake_id: int) -> TariffEmailIntake:
    intake = db.get(TariffEmailIntake, intake_id)
    if intake is None:
        raise NotFoundError("Rate email not found.")
    return intake


def release(
    db: Session, intake: TariffEmailIntake, actor: User, *, now: datetime | None = None
) -> TariffEmailIntake:
    """An approver releases a held sender's email: its workbook is imported as a draft."""
    now = now or utcnow()
    require_approver(db, actor)
    if intake.status != TariffIntakeStatus.HELD_SENDER:
        raise ConflictError(f"Only a held email can be released; this one is {intake.status}.")
    path = held_path(intake.id)
    if not path.exists():
        raise ConflictError(
            "The held workbook is not in the intake folder; send the same email again to "
            "restore it, or ask the vendor to resend it."
        )
    content = path.read_bytes()
    if hashlib.sha256(content).hexdigest() != intake.attachment_sha256:
        raise ConflictError("The held workbook changed after it was received; it is not imported.")
    intake.reviewed_at = now
    intake.reviewed_by_user_id = actor.id
    intake.review_note = "Sender released by an approver."
    _import_into(db, intake, content, actor=actor, now=now)
    db.flush()
    audit_service.record_audit(
        db,
        action="tariff_intake.released",
        entity_type="tariff_email_intake",
        entity_id=intake.id,
        summary=f"Rate email {intake.id} released: {intake.status}",
        actor=actor,
        detail={"status": intake.status},
    )
    _audit_outcome(db, intake, actor)
    return intake


def stored_email_path(intake: TariffEmailIntake) -> Path | None:
    """The kept ``.eml`` of a folder intake, only if it is inside the intake folder."""
    if not intake.stored_file:
        return None
    root = settings.tariff_intake_path.resolve()
    path = (root / intake.stored_file).resolve()
    if not path.is_relative_to(root) or not path.is_file() or path.is_symlink():
        return None
    return path


def reprocess(
    db: Session, intake: TariffEmailIntake, actor: User, *, now: datetime | None = None
) -> IntakeResult:
    """An approver reprocesses a ``failed`` folder intake from its kept email file (in
    ``failed/``), on the same row. The result is at most a draft, as always."""
    now = now or utcnow()
    require_approver(db, actor)
    if intake.status != TariffIntakeStatus.FAILED:
        raise ConflictError(f"Only a failed email can be reprocessed; this one is {intake.status}.")
    path = stored_email_path(intake)
    if intake.source != TariffIntakeSource.FOLDER or path is None:
        raise ConflictError(
            "Only an email from the intake folder whose file is still kept can be reprocessed; "
            "upload the corrected email instead."
        )
    raw = path.read_bytes()
    if len(raw) > settings.tariff_intake_max_eml_bytes:
        raise ConflictError("The kept email is larger than the limit.")
    parsed = parse_eml(raw)
    intake.sender = parsed.sender
    intake.subject = parsed.subject
    intake.received_at = parsed.received_at
    intake.source_sha256 = hashlib.sha256(raw).hexdigest()
    intake.reviewed_at = now
    intake.reviewed_by_user_id = actor.id
    intake.review_note = "Reprocessed by an approver."
    audit_service.record_audit(
        db,
        action="tariff_intake.reprocessed",
        entity_type="tariff_email_intake",
        entity_id=intake.id,
        summary=f"Rate email {intake.id} reprocessed",
        actor=actor,
        detail={"stored_file": intake.stored_file},
    )
    held = _process(db, intake, parsed, actor=actor, now=now)
    return IntakeResult(intake=intake, created=False, held_attachment=held)


def reprocess_and_commit(db: Session, intake_id: int, actor: User) -> IntakeResult:
    def work():
        return reprocess(db, get_intake(db, intake_id), actor)

    result = _run_with_held(db, work)
    intake = result.intake
    path = stored_email_path(intake)
    if (
        path is not None
        and intake.status != TariffIntakeStatus.FAILED
        and path.parent.name == "failed"
    ):
        target = settings.tariff_intake_path / "processed" / path.name
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            shutil.move(str(path), str(target))
            intake.stored_file = f"processed/{path.name}"
            commit_with_retry(db)
    return result


# --- Approval -------------------------------------------------------------------------------


def _intakes_for(db: Session, version: TariffVersion) -> list[TariffEmailIntake]:
    return list(
        db.scalars(
            select(TariffEmailIntake).where(
                TariffEmailIntake.tariff_version_id == version.id,
                TariffEmailIntake.status == TariffIntakeStatus.IMPORTED,
            )
        )
    )


def _record_review(
    db: Session, version: TariffVersion, decision: str, actor: User, note: str | None, now
) -> None:
    db.add(
        TariffVersionReview(
            tariff_version_id=version.id,
            decision=decision,
            reviewed_by_user_id=actor.id,
            reviewed_at=now,
            note=note,
        )
    )


def approve(
    db: Session, version: TariffVersion, actor: User, *, now: datetime | None = None
) -> TariffVersion:
    """The approver activates a draft. The previous active version is superseded."""
    now = now or utcnow()
    check_can_activate(db, version, actor)
    if version.status != TariffVersionStatus.DRAFT:
        raise ConflictError(
            f"Only a draft can be approved; {version.public_id} is {version.status}."
        )
    previous = tariff_import_service.active_version(db, version.vendor.key)
    tariff_import_service.activate_version(db, version, actor=actor, now=now)
    if review_of(db, version) is None:
        _record_review(db, version, "approved", actor, None, now)
    for intake in _intakes_for(db, version):
        intake.reviewed_at = now
        intake.reviewed_by_user_id = actor.id
        intake.review_note = "Approved and activated."
    db.flush()
    audit_service.record_audit(
        db,
        action="tariff_version.approved",
        entity_type="tariff_version",
        entity_id=version.public_id,
        summary=f"Approved tariff {version.public_id}",
        actor=actor,
        detail={"superseded": previous.public_id if previous else None},
    )
    # Owner decision 9: quotes for goods not yet received expire on the new tariff
    # (idempotent; ``activate_version`` runs it too).
    quote_expiry_service.expire_for_new_tariff(db, version, actor=actor, now=now)
    return version


def reject(
    db: Session, version: TariffVersion, actor: User, reason: str, *, now: datetime | None = None
) -> TariffVersion:
    """The approver rejects a draft, whatever its source (email or manual import). The
    version stays ``draft`` (no rejected state exists and its table is not altered); the
    decision is a ``tariff_version_reviews`` row, its intake rows become ``rejected``, and
    it can never be approved or activated."""
    now = now or utcnow()
    require_approver(db, actor)
    text = _plain(reason, MAX_REASON + 1)
    if not text:
        raise ValidationError("A reason is required to reject a tariff version.", field="reason")
    if len(text) > MAX_REASON:
        raise ValidationError(f"At most {MAX_REASON} characters.", field="reason")
    if version.status != TariffVersionStatus.DRAFT:
        raise ConflictError(
            f"Only a draft can be rejected; {version.public_id} is {version.status}."
        )
    if review_of(db, version) is not None:
        raise ConflictError(f"{version.public_id} has already been reviewed.")
    _record_review(db, version, "rejected", actor, text, now)
    intakes = _intakes_for(db, version)
    for intake in intakes:
        intake.status = TariffIntakeStatus.REJECTED
        intake.reviewed_at = now
        intake.reviewed_by_user_id = actor.id
        intake.review_note = text
    db.flush()
    audit_service.record_audit(
        db,
        action="tariff_version.rejected",
        entity_type="tariff_version",
        entity_id=version.public_id,
        summary=f"Rejected tariff {version.public_id}",
        actor=actor,
        detail={"reason": text, "intakes": [i.id for i in intakes]},
    )
    return version


# --- Diff ---------------------------------------------------------------------------------


def _money(value: Decimal | None) -> str | None:
    return None if value is None else format(Decimal(value).quantize(Decimal("0.01")), "f")


def _brackets(db: Session, version: TariffVersion | None) -> dict[tuple, Decimal]:
    if version is None:
        return {}
    rows = db.execute(
        select(
            TariffProduct.origin,
            TariffProduct.code,
            TariffRateBracket.kind,
            TariffRateBracket.zone,
            TariffRateBracket.label,
            TariffRateBracket.price_vnd,
        )
        .join(TariffRateBracket, TariffRateBracket.product_id == TariffProduct.id)
        .where(
            TariffProduct.version_id == version.id,
            TariffProduct.mode == TariffProductMode.AIR.value,
        )
    ).all()
    return {(r[0], r[1], r[2], r[3], r[4]): r[5] for r in rows}


def _products(db: Session, version: TariffVersion | None) -> set[tuple[str, str]]:
    if version is None:
        return set()
    rows = db.execute(
        select(TariffProduct.origin, TariffProduct.code).where(
            TariffProduct.version_id == version.id,
            TariffProduct.mode == TariffProductMode.AIR.value,
        )
    ).all()
    return {(r[0], r[1]) for r in rows}


_RULE_FIELDS = ("name", "raw_price_text", "pricing_status", "basis", "scope", "unit_price_vnd")


def _rules(db: Session, version: TariffVersion | None) -> dict[tuple[str, int], dict]:
    if version is None:
        return {}
    rows = db.scalars(
        select(TariffSurchargeRule).where(
            TariffSurchargeRule.version_id == version.id,
            TariffSurchargeRule.section.in_(AIR_SECTIONS),
        )
    ).all()
    return {
        (r.section, r.stt): {
            "name": r.name,
            "raw_price_text": r.raw_price_text,
            "pricing_status": r.pricing_status,
            "basis": r.basis,
            "scope": r.scope,
            "unit_price_vnd": _money(r.unit_price_vnd),
        }
        for r in rows
    }


def _bracket_entry(key: tuple, old: Decimal | None, new: Decimal | None) -> dict:
    origin, code, kind, zone, label = key
    return {
        "origin": origin,
        "product_code": code,
        "kind": kind,
        "zone": zone,
        "label": label,
        "old_price_vnd": _money(old),
        "new_price_vnd": _money(new),
    }


def _bounded(entries: list[dict]) -> list[dict]:
    return entries[:MAX_DIFF_ENTRIES]


def version_diff(db: Session, version: TariffVersion) -> dict:
    """What this version changes against the vendor's active one. Air only; bounded."""
    active = tariff_import_service.active_version(db, version.vendor.key)
    base = None if active is not None and active.id == version.id else active

    new_b, old_b = _brackets(db, version), _brackets(db, base)
    changed = [
        _bracket_entry(k, old_b[k], new_b[k])
        for k in sorted(new_b.keys() & old_b.keys())
        if Decimal(new_b[k]) != Decimal(old_b[k])
    ]
    added = [_bracket_entry(k, None, new_b[k]) for k in sorted(new_b.keys() - old_b.keys())]
    removed = [_bracket_entry(k, old_b[k], None) for k in sorted(old_b.keys() - new_b.keys())]

    new_p, old_p = _products(db, version), _products(db, base)
    new_r, old_r = _rules(db, version), _rules(db, base)
    rules_changed = []
    for key in sorted(new_r.keys() & old_r.keys()):
        fields = [f for f in _RULE_FIELDS if new_r[key][f] != old_r[key][f]]
        if fields:
            rules_changed.append(
                {
                    "section": key[0],
                    "stt": key[1],
                    "name": new_r[key]["name"],
                    "fields": fields,
                    "old": {f: old_r[key][f] for f in fields},
                    "new": {f: new_r[key][f] for f in fields},
                }
            )
    rules_added = [
        {"section": k[0], "stt": k[1], "name": new_r[k]["name"]}
        for k in sorted(new_r.keys() - old_r.keys())
    ]
    rules_removed = [
        {"section": k[0], "stt": k[1], "name": old_r[k]["name"]}
        for k in sorted(old_r.keys() - new_r.keys())
    ]
    lists = {
        "brackets_changed": changed,
        "brackets_added": added,
        "brackets_removed": removed,
        "surcharges_changed": rules_changed,
        "surcharges_added": rules_added,
        "surcharges_removed": rules_removed,
    }
    return {
        "version_id": version.id,
        "version_public_id": version.public_id,
        "version_status": version.status,
        "against_version_id": base.id if base else None,
        "against_version_public_id": base.public_id if base else None,
        "mode": TariffProductMode.AIR.value,
        "products_added": [{"origin": o, "code": c} for o, c in sorted(new_p - old_p)],
        "products_removed": [{"origin": o, "code": c} for o, c in sorted(old_p - new_p)],
        "summary": {name: len(entries) for name, entries in lists.items()},
        "truncated": any(len(entries) > MAX_DIFF_ENTRIES for entries in lists.values()),
        "max_entries": MAX_DIFF_ENTRIES,
        "counts": {
            "version": tariff_import_service.version_counts(db, version),
            "against": tariff_import_service.version_counts(db, base) if base else None,
        },
        **{name: _bounded(entries) for name, entries in lists.items()},
    }
