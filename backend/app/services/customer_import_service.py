"""Staged CSV customer import (CRM.md section 13).

The workflow is deliberately slow: select a file, parse it, look at what the parse found,
review the duplicates, and only then commit. Each stage has its own permission, and the
stage that writes is the last one.

**A preview writes nothing.** Not a staging row, not a draft customer, not a tag. An
abandoned preview leaves no trace, which is the only way to be sure that looking at a file
of other people's contact details is a reversible act (DEC-0078, DEC-0079).

**A commit re-does the whole parse and the whole validation.** It does not trust the
classification the preview returned, because that classification travelled through a
browser. The commit is handed the same file again — verified by a digest of its bytes, so
the operator cannot preview one file and commit another — and reaches its own conclusions.
The only thing it takes from the operator is *decisions*: which probable duplicates to
create, and how to treat a row that already exists.

**Nothing is merged automatically.** A probable duplicate is held until somebody says what
it is. Families share a phone number and an email address, and a merge is not reversible
(CRM.md section 13, AC-16).

**Customers are created through ``customer_service``**, never by inserting a model row, so
an imported customer goes through exactly the same normalization, validation, identifier
allocation, and audit as one typed into the drawer.

Two deliberate restrictions, both recorded as open decisions rather than quietly applied:

* **Consent is not importable.** A CSV cannot carry consent evidence, and ``CRM.md``
  section 11 is explicit that imported contact information is not automatically marketing
  eligible and that an import must not be able to override a suppression. The safest
  structure is to have no code path at all, so there is none.
* **A non-empty value is never overwritten.** The strictest conflict policy an operator
  can choose is "fill blanks", which writes only where the existing field is empty.
"""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.countries import normalize_country_code
from app.core.enums import (
    BusinessType,
    ContactChannel,
    CustomerCategory,
    PreferredLanguage,
    RouteGroup,
    ShippingFrequency,
    ShippingPurpose,
)
from app.core.normalization import (
    collapse_whitespace,
    name_match_key,
    normalize_email,
    normalize_phone,
    phone_match_key,
)
from app.core.time_utils import utcnow
from app.models import (
    CSV_SOURCE_SYSTEM,
    Customer,
    ImportBatch,
    ImportBatchRow,
    Tag,
    User,
)
from app.services import audit_service, csv_safety, customer_service, duplicate_service
from app.services.errors import ConflictError, ValidationError
from app.services.identifier_service import _next_counter_value

# --- The accepted field set ---------------------------------------------------
#
# An import may write these fields and no others. A column the file carries that is not
# here is reported as unmapped and its values are dropped. This list *is* the contract.

#: Canonical field -> the header spellings that map to it. Every spelling is compared
#: after ``csv_safety.normalize_header``, so case, spacing, punctuation, and accents do
#: not matter.
FIELD_SYNONYMS: dict[str, tuple[str, ...]] = {
    "full_name": ("full_name", "name", "customer_name", "ho_va_ten", "ten"),
    "email": ("email", "email_address", "e_mail"),
    "phone": ("phone", "phone_number", "mobile", "telephone", "so_dien_thoai"),
    "city": ("city", "town", "thanh_pho"),
    "province_state": ("province_state", "province", "state", "region", "tinh"),
    "country_code": ("country_code", "country", "quoc_gia"),
    "preferred_language": ("preferred_language", "language", "ngon_ngu"),
    "category": ("category", "customer_category", "type"),
    "business_name": ("business_name", "company", "company_name"),
    "business_type": ("business_type",),
    "primary_shipping_purpose": ("primary_shipping_purpose", "shipping_purpose", "purpose"),
    "primary_route_group": ("primary_route_group", "primary_route", "route", "route_group"),
    "shipping_frequency": ("shipping_frequency", "frequency"),
    "estimated_monthly_shipments": (
        "estimated_monthly_shipments",
        "monthly_shipments_estimate",
    ),
    "preferred_contact_channel": ("preferred_contact_channel", "contact_channel"),
    "best_contact_time": ("best_contact_time", "contact_time"),
    "contact_timezone": ("contact_timezone", "timezone"),
    "notes": ("notes", "note", "internal_notes", "ghi_chu"),
    "tags": ("tags", "tag"),
    "source_system": ("source_system", "source"),
    "source_record_id": ("source_record_id", "source_id", "external_id"),
    "source_created_at": ("source_created_at", "date_added", "created_at", "original_date"),
}

KNOWN_HEADERS: dict[str, str] = {
    spelling: canonical for canonical, spellings in FIELD_SYNONYMS.items() for spelling in spellings
}

#: The header row of the downloadable template, in the order it is written.
TEMPLATE_HEADERS: tuple[str, ...] = (
    "full_name",
    "email",
    "phone",
    "country_code",
    "city",
    "province_state",
    "preferred_language",
    "category",
    "business_name",
    "primary_route_group",
    "primary_shipping_purpose",
    "shipping_frequency",
    "estimated_monthly_shipments",
    "preferred_contact_channel",
    "best_contact_time",
    "notes",
    "tags",
    "source_record_id",
    "source_created_at",
)

REQUIRED_FIELDS: tuple[str, ...] = ("full_name",)

#: Enumerated fields, and the values they accept. A value outside the set is a row-level
#: rejection with a message naming the allowed values, never a silent fallback to a
#: default: silently defaulting "Vietnamese" to "unknown" loses information the operator
#: believed they had supplied.
ENUM_FIELDS: dict[str, tuple[str, ...]] = {
    "preferred_language": tuple(item.value for item in PreferredLanguage),
    "category": tuple(item.value for item in CustomerCategory),
    "business_type": tuple(item.value for item in BusinessType),
    "primary_shipping_purpose": tuple(item.value for item in ShippingPurpose),
    "primary_route_group": tuple(item.value for item in RouteGroup),
    "shipping_frequency": tuple(item.value for item in ShippingFrequency),
    "preferred_contact_channel": tuple(item.value for item in ContactChannel),
}

#: Friendly spellings an operator is likely to type, folded to the stored value. Applied
#: only to enumerated fields, and only for exact matches after casefolding.
ENUM_ALIASES: dict[str, dict[str, str]] = {
    "preferred_language": {
        "english": "en",
        "vietnamese": "vi",
        "tieng viet": "vi",
        "french": "fr",
        "francais": "fr",
    },
    "category": {"individual": "individual", "business": "business", "company": "business"},
    "primary_route_group": {
        "vietnam to canada": "VCA",
        "canada to vietnam": "CAV",
        "domestic canada": "CAD",
        "us cross border": "XUS",
    },
}

# --- Outcomes -----------------------------------------------------------------

CREATED = "created"
MATCHED = "matched"
SKIPPED = "skipped"
REJECTED = "rejected"

#: Classifications the preview reports.
NEW = "new"
EXACT_MATCH = "exact_match"
DUPLICATE_REVIEW = "duplicate_review"

#: How a row whose source key already exists is treated. There is deliberately no
#: "overwrite": an import must not be able to destroy a value a staff member typed.
POLICY_SKIP = "skip"
POLICY_FILL_BLANKS = "fill_blanks"
CONFLICT_POLICIES = (POLICY_SKIP, POLICY_FILL_BLANKS)

#: What an operator may decide about one probable duplicate.
DECISION_CREATE = "create"
DECISION_SKIP = "skip"
DECISIONS = (DECISION_CREATE, DECISION_SKIP)

IMPORT_BATCH_COUNTER = "import_batch_public_id"


@dataclass
class RowIssue:
    field_name: str
    code: str
    message: str


@dataclass
class PreviewRow:
    row_number: int
    classification: str
    #: Normalized values, echoed back so the operator can see what the parse understood.
    #: This is the *only* place imported values are returned, and they are returned to the
    #: person who uploaded them, over an authenticated request.
    values: dict[str, str | None]
    issues: list[RowIssue] = field(default_factory=list)
    #: Existing customer this row reconciles to, when there is one.
    matched_customer_id: int | None = None
    matched_customer_public_id: str | None = None
    #: Possible duplicates for the operator to judge. Never acted on automatically.
    duplicate_candidates: list[dict] = field(default_factory=list)
    source_record_id: str | None = None
    #: What a commit would do to this row with no further decision.
    default_action: str = SKIPPED

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ImportPreview:
    content_sha256: str
    file_name: str | None
    row_count: int
    headers: list[str]
    raw_headers: list[str]
    unmapped_headers: list[str]
    rows: list[PreviewRow]
    counts: dict[str, int]
    notes: list[str]

    def to_dict(self) -> dict:
        return {
            "content_sha256": self.content_sha256,
            "file_name": self.file_name,
            "row_count": self.row_count,
            "headers": self.headers,
            "raw_headers": self.raw_headers,
            "unmapped_headers": self.unmapped_headers,
            "rows": [row.to_dict() for row in self.rows],
            "counts": self.counts,
            "notes": self.notes,
        }


@dataclass
class CommitResult:
    batch_public_id: str
    created: int
    matched: int
    skipped: int
    rejected: int
    row_count: int
    conflict_policy: str
    rows: list[dict]

    def to_dict(self) -> dict:
        return asdict(self)


# --- Template -----------------------------------------------------------------


def template_csv() -> str:
    """The downloadable template, with two rows of clearly synthetic sample data.

    The samples are real-shaped — a Vietnamese name with diacritics and an international
    phone number — because a template whose examples do not exercise the hard cases
    teaches the operator the wrong lesson. They use the reserved ``example.com`` domain and
    obviously fictional 555 numbers.
    """
    import csv
    import io

    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\r\n")
    writer.writerow(TEMPLATE_HEADERS)
    writer.writerow(
        [
            "Nguyễn Thị Bích Hạnh",
            "sample.hanh@example.com",
            "+1 416 555 0142",
            "CA",
            "Mississauga",
            "ON",
            "vi",
            "individual",
            "",
            "CAV",
            "gifts_family_support",
            "monthly",
            "2",
            "phone",
            "Evenings after 6pm",
            "Prefers to be called rather than emailed",
            "family;vip",
            "LEGACY-0001",
            "2024-03-15",
        ]
    )
    writer.writerow(
        [
            "Sample Trading Co.",
            "sample.orders@example.com",
            "+84 28 5555 0177",
            "VN",
            "Thành phố Hồ Chí Minh",
            "Hồ Chí Minh",
            "en",
            "business",
            "Sample Trading Co.",
            "VCA",
            "online_orders",
            "weekly",
            "20",
            "email",
            "",
            "Sample row - safe to delete",
            "reseller",
            "LEGACY-0002",
            "2025-01-08",
        ]
    )
    return "﻿" + buffer.getvalue()


# --- Row normalization and validation ------------------------------------------


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def content_digest(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _normalize_enum(field_name: str, raw: str) -> tuple[str | None, RowIssue | None]:
    value = collapse_whitespace(raw)
    if not value:
        return None, None
    allowed = ENUM_FIELDS[field_name]
    if value in allowed:
        return value, None
    folded = value.casefold()
    for candidate in allowed:
        if candidate.casefold() == folded:
            return candidate, None
    alias = ENUM_ALIASES.get(field_name, {}).get(folded)
    if alias:
        return alias, None
    return None, RowIssue(
        field_name=field_name,
        code="unknown_value",
        message=(
            f"'{value}' is not one of the accepted values for {field_name}. "
            f"Use one of: {', '.join(allowed)}."
        ),
    )


def _parse_source_date(raw: str) -> tuple[datetime | None, RowIssue | None]:
    value = collapse_whitespace(raw)
    if not value:
        return None, None
    for pattern in ("%Y-%m-%d", "%Y/%m/%d", "%d/%m/%Y", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(value, pattern), None
        except ValueError:
            continue
    return None, RowIssue(
        field_name="source_created_at",
        code="unparsed_date",
        message=(
            f"'{value}' is not a date this import recognizes. Use YYYY-MM-DD. The row can "
            "still be imported without it."
        ),
    )


@dataclass
class NormalizedRow:
    row_number: int
    data: dict[str, object]
    issues: list[RowIssue]
    email_normalized: str | None
    phone_key: str | None
    source_system: str
    source_record_id: str
    tags: list[str]

    @property
    def is_valid(self) -> bool:
        """An unparsed optional date is a warning, not a rejection.

        The row still identifies a real person and can be imported without their original
        source date; refusing it would lose the person over a formatting detail.
        """
        return not any(issue.code != "unparsed_date" for issue in self.issues)

    def has_duplicate_candidates(self, db: Session) -> bool:
        """Whether an existing customer plausibly *is* this person.

        Advisory only. It never merges and never decides — it routes the row to a human
        (CRM.md section 13, AC-16).
        """
        return bool(
            duplicate_service.find_duplicate_candidates(
                db,
                full_name=self.data.get("full_name"),
                email=self.data.get("email"),
                phone=self.data.get("phone"),
                country_code=self.data.get("country_code"),
                limit=1,
            )
        )


def normalize_row(row: csv_safety.ParsedRow, *, default_source_system: str) -> NormalizedRow:
    """Turn one text row into candidate customer data. Writes nothing."""
    values = row.values
    issues: list[RowIssue] = []
    data: dict[str, object] = {}

    full_name = collapse_whitespace(values.get("full_name", ""))
    if not full_name:
        issues.append(
            RowIssue("full_name", "missing_name", "Full name is required and this row has none.")
        )
    else:
        data["full_name"] = full_name

    # Country first: phone normalization is country-aware (CRM.md section 4).
    country_raw = collapse_whitespace(values.get("country_code", ""))
    country_code = None
    if country_raw:
        country_code = normalize_country_code(country_raw)
        if country_code is None:
            issues.append(
                RowIssue(
                    "country_code",
                    "unknown_country",
                    f"'{country_raw}' is not a country this system recognizes. Use a "
                    "two-letter code such as CA, VN, or US.",
                )
            )
        else:
            data["country_code"] = country_code

    email_normalized = None
    email_raw = collapse_whitespace(values.get("email", ""))
    if email_raw:
        try:
            entered, email_normalized = normalize_email(email_raw)
            data["email"] = entered
        except ValueError:
            issues.append(
                RowIssue(
                    "email",
                    "invalid_email",
                    f"'{email_raw}' is not a valid email address.",
                )
            )

    phone_key = None
    phone_raw = collapse_whitespace(values.get("phone", ""))
    if phone_raw:
        entered, e164, _ = normalize_phone(phone_raw, country_code)
        data["phone"] = entered
        phone_key = phone_match_key(entered, e164)

    if not email_normalized and not phone_key:
        issues.append(
            RowIssue(
                "phone",
                "missing_contact",
                "A customer needs at least one usable phone number or email address.",
            )
        )

    for field_name in ENUM_FIELDS:
        raw = values.get(field_name, "")
        value, issue = _normalize_enum(field_name, raw)
        if issue:
            issues.append(issue)
        elif value is not None:
            data[field_name] = value

    for field_name in ("city", "province_state", "business_name", "best_contact_time", "notes"):
        text = collapse_whitespace(values.get(field_name, ""))
        if text:
            data[field_name] = text

    timezone_raw = collapse_whitespace(values.get("contact_timezone", ""))
    if timezone_raw:
        from app.core.time_utils import is_known_timezone

        if is_known_timezone(timezone_raw):
            data["contact_timezone"] = timezone_raw
        else:
            issues.append(
                RowIssue(
                    "contact_timezone",
                    "unknown_timezone",
                    f"'{timezone_raw}' is not a recognized timezone name.",
                )
            )

    estimate_raw = collapse_whitespace(values.get("estimated_monthly_shipments", ""))
    if estimate_raw:
        try:
            estimate = float(estimate_raw.replace(",", ""))
            if estimate < 0:
                raise ValueError
            data["estimated_monthly_shipments"] = estimate
        except ValueError:
            issues.append(
                RowIssue(
                    "estimated_monthly_shipments",
                    "invalid_number",
                    f"'{estimate_raw}' is not a non-negative number.",
                )
            )

    source_date, date_issue = _parse_source_date(values.get("source_created_at", ""))
    if date_issue:
        issues.append(date_issue)
    if source_date:
        data["source_created_at"] = source_date

    tags = [
        tag
        for tag in (collapse_whitespace(part) or "" for part in values.get("tags", "").split(";"))
        if tag
    ]

    source_system = collapse_whitespace(values.get("source_system", "")) or default_source_system
    source_record_id = collapse_whitespace(values.get("source_record_id", "")) or _identity_key(
        full_name, email_normalized, phone_key
    )

    data["source_system"] = source_system
    data["source_record_id"] = source_record_id

    return NormalizedRow(
        row_number=row.row_number,
        data=data,
        issues=issues,
        email_normalized=email_normalized,
        phone_key=phone_key,
        source_system=source_system,
        source_record_id=source_record_id,
        tags=tags,
    )


def _identity_key(full_name: str | None, email: str | None, phone_key: str | None) -> str:
    """A stable key for a row the file gave no identifier of its own.

    Most real customer lists exported from a spreadsheet have no stable key, and without
    one a second import would create a second copy of every person (CRM.md section 13).
    The digest is over the *normalized* identity, so the same person written slightly
    differently in the same file still collides, and the digest itself is not reversible
    into the identity it covers.
    """
    parts = [
        name_match_key(full_name) or "",
        (email or "").lower(),
        phone_key or "",
    ]
    return f"row:{_digest('|'.join(parts))[:40]}"


# --- Preview -------------------------------------------------------------------


def build_preview(
    db: Session,
    content: bytes,
    *,
    file_name: str | None = None,
    default_source_system: str = CSV_SOURCE_SYSTEM,
) -> ImportPreview:
    """Parse, validate and classify. **Writes nothing.**"""
    parsed = csv_safety.parse(content, known_fields=KNOWN_HEADERS, required_headers=REQUIRED_FIELDS)

    rows: list[PreviewRow] = []
    counts = {NEW: 0, EXACT_MATCH: 0, DUPLICATE_REVIEW: 0, REJECTED: 0}
    #: Rows inside one file can collide with each other, not only with the database.
    seen_keys: dict[str, int] = {}

    for parsed_row in parsed.rows:
        normalized = normalize_row(parsed_row, default_source_system=default_source_system)
        preview_row = PreviewRow(
            row_number=normalized.row_number,
            classification=REJECTED,
            values={
                key: (str(value) if value is not None else None)
                for key, value in normalized.data.items()
                if key not in ("source_record_id", "source_system")
            },
            issues=list(normalized.issues),
            source_record_id=normalized.source_record_id,
        )

        if not normalized.is_valid:
            counts[REJECTED] += 1
            preview_row.default_action = REJECTED
            rows.append(preview_row)
            continue

        duplicate_within_file = seen_keys.get(normalized.source_record_id)
        if duplicate_within_file is not None:
            preview_row.classification = EXACT_MATCH
            preview_row.default_action = SKIPPED
            preview_row.issues.append(
                RowIssue(
                    "source_record_id",
                    "duplicate_within_file",
                    f"This row repeats row {duplicate_within_file} of the same file. It "
                    "will be skipped so the file cannot create the same person twice.",
                )
            )
            counts[EXACT_MATCH] += 1
            rows.append(preview_row)
            continue
        seen_keys[normalized.source_record_id] = normalized.row_number

        existing = _find_by_source_key(db, normalized.source_system, normalized.source_record_id)
        if existing is not None:
            preview_row.classification = EXACT_MATCH
            preview_row.matched_customer_id = existing.id
            preview_row.matched_customer_public_id = existing.public_id
            preview_row.default_action = MATCHED
            counts[EXACT_MATCH] += 1
            rows.append(preview_row)
            continue

        candidates = duplicate_service.find_duplicate_candidates(
            db,
            full_name=normalized.data.get("full_name"),
            email=normalized.data.get("email"),
            phone=normalized.data.get("phone"),
            country_code=normalized.data.get("country_code"),
        )
        if candidates:
            preview_row.classification = DUPLICATE_REVIEW
            # Held, never merged. A decision is required before this row does anything.
            preview_row.default_action = SKIPPED
            preview_row.duplicate_candidates = [
                {
                    "customer_id": candidate.customer.id,
                    "public_id": candidate.customer.public_id,
                    "full_name": candidate.customer.full_name,
                    "city": candidate.customer.city,
                    "country_code": candidate.customer.country_code,
                    "matched_on": candidate.matched_on,
                    "confidence": candidate.confidence,
                }
                for candidate in candidates
            ]
            counts[DUPLICATE_REVIEW] += 1
            rows.append(preview_row)
            continue

        preview_row.classification = NEW
        preview_row.default_action = CREATED
        counts[NEW] += 1
        rows.append(preview_row)

    notes = _preview_notes(counts, parsed)
    return ImportPreview(
        content_sha256=content_digest(content),
        file_name=collapse_whitespace(file_name)[:255] if file_name else None,
        row_count=len(parsed.rows),
        headers=parsed.headers,
        raw_headers=parsed.raw_headers,
        unmapped_headers=parsed.unmapped_headers,
        rows=rows,
        counts=counts,
        notes=notes,
    )


def _preview_notes(counts: dict[str, int], parsed: csv_safety.ParsedFile) -> list[str]:
    notes = [
        "Nothing has been imported. This is a preview: no customer record has been "
        "created, changed, or merged.",
    ]
    if parsed.unmapped_headers:
        notes.append(
            "These columns were not recognized and their values were ignored: "
            + ", ".join(parsed.unmapped_headers)
            + "."
        )
    if counts[DUPLICATE_REVIEW]:
        notes.append(
            f"{counts[DUPLICATE_REVIEW]} row(s) look like people already in the CRM. "
            "Nothing is merged automatically — families legitimately share a phone number "
            "or an email address. Decide for each one whether to create a separate "
            "customer or skip it."
        )
    if counts[EXACT_MATCH]:
        notes.append(
            f"{counts[EXACT_MATCH]} row(s) have already been imported before, matched on "
            "their source record ID. Re-importing the same file will not create them "
            "again."
        )
    if counts[REJECTED]:
        notes.append(
            f"{counts[REJECTED]} row(s) cannot be imported as written. They are excluded "
            "from the commit; the rest can still be imported."
        )
    notes.append(
        "Consent is never imported. Imported contact details are not marketing eligible "
        "until consent is recorded in the CRM with its evidence."
    )
    return notes


def _find_by_source_key(db: Session, source_system: str, source_record_id: str) -> Customer | None:
    return db.scalar(
        select(Customer).where(
            Customer.source_system == source_system,
            Customer.source_record_id == source_record_id,
        )
    )


# --- Commit --------------------------------------------------------------------


def commit_import(
    db: Session,
    content: bytes,
    *,
    expected_sha256: str,
    actor: User,
    file_name: str | None = None,
    default_source_system: str = CSV_SOURCE_SYSTEM,
    conflict_policy: str = POLICY_SKIP,
    decisions: dict[int, str] | None = None,
    ip_address: str | None = None,
) -> CommitResult:
    """Commit an import inside one transaction.

    The caller owns the surrounding commit. Every accepted row lands or none of them does
    (DEC-0079): a row that fails *during* the write means validation reached a conclusion
    the database disagrees with, and committing a partial result on top of a wrong premise
    leaves the operator with no way to know what landed.

    Rows rejected by validation are excluded *before* the transaction opens. They were
    never candidates, so they do not prevent the rest from committing.
    """
    if conflict_policy not in CONFLICT_POLICIES:
        raise ValidationError(
            f"Unknown conflict policy '{conflict_policy}'. Use one of: "
            f"{', '.join(CONFLICT_POLICIES)}.",
            field="conflict_policy",
        )

    actual = content_digest(content)
    if actual != expected_sha256:
        # The file changed between preview and commit. Refusing is the only safe answer:
        # the operator reviewed a different set of rows from the one about to be written.
        raise ConflictError(
            "This file is not the one that was previewed. Preview it again and review the "
            "result before importing."
        )

    decisions = {int(key): value for key, value in (decisions or {}).items()}
    for row_number, decision in decisions.items():
        if decision not in DECISIONS:
            raise ValidationError(
                f"Row {row_number}: '{decision}' is not a decision this import "
                f"understands. Use one of: {', '.join(DECISIONS)}.",
                field="decisions",
            )

    # Every row the preview held for review needs somebody's explicit answer. Skipping is
    # a decision too, and it is not one to arrive at by default (UAT-XX-05). The check
    # re-runs the preview, which writes nothing, so the rows it names are exactly the
    # ones the operator was shown, and it refuses before the batch exists.
    undecided = [
        row.row_number
        for row in build_preview(
            db, content, file_name=file_name, default_source_system=default_source_system
        ).rows
        if row.classification == DUPLICATE_REVIEW and row.row_number not in decisions
    ]
    if undecided:
        raise ValidationError(
            f"{len(undecided)} possible duplicate row(s) have no decision: row(s) "
            f"{', '.join(str(number) for number in undecided[:20])}"
            f"{' and more' if len(undecided) > 20 else ''}. Choose to skip or to create "
            "each one. Nothing has been imported.",
            field="decisions",
        )

    parsed = csv_safety.parse(content, known_fields=KNOWN_HEADERS, required_headers=REQUIRED_FIELDS)

    batch = ImportBatch(
        public_id=_next_batch_public_id(db),
        kind="customers",
        file_name=collapse_whitespace(file_name)[:255] if file_name else None,
        content_sha256=actual,
        source_system=default_source_system,
        conflict_policy=conflict_policy,
        row_count=len(parsed.rows),
        committed_at=utcnow(),
        committed_by_user_id=actor.id if actor else None,
    )
    db.add(batch)
    db.flush()

    counts = {CREATED: 0, MATCHED: 0, SKIPPED: 0, REJECTED: 0}
    seen_keys: set[str] = set()
    result_rows: list[dict] = []

    for parsed_row in parsed.rows:
        # Re-validated here rather than trusted from the preview: the preview's
        # conclusions travelled through a browser.
        normalized = normalize_row(parsed_row, default_source_system=default_source_system)
        outcome, reason, customer = _apply_row(
            db,
            normalized,
            conflict_policy=conflict_policy,
            decision=decisions.get(normalized.row_number),
            seen_keys=seen_keys,
            actor=actor,
        )
        counts[outcome] += 1
        db.add(
            ImportBatchRow(
                batch_id=batch.id,
                row_number=normalized.row_number,
                outcome=outcome,
                reason_code=reason,
                customer_id=customer.id if customer is not None else None,
                source_record_id=normalized.source_record_id,
            )
        )
        result_rows.append(
            {
                "row_number": normalized.row_number,
                "outcome": outcome,
                "reason_code": reason,
                "customer_id": customer.id if customer is not None else None,
                "customer_public_id": customer.public_id if customer is not None else None,
            }
        )

    batch.created_count = counts[CREATED]
    batch.matched_count = counts[MATCHED]
    batch.skipped_count = counts[SKIPPED]
    batch.rejected_count = counts[REJECTED]

    audit_service.record_audit(
        db,
        action="customer.import_commit",
        entity_type="import_batch",
        entity_id=batch.public_id,
        summary=(
            f"Imported {counts[CREATED]} new customer(s) from CSV; "
            f"{counts[MATCHED]} already existed, {counts[SKIPPED]} skipped, "
            f"{counts[REJECTED]} rejected"
        ),
        actor=actor,
        ip_address=ip_address,
        detail={
            # Counts, policy, and the digest. No row content, and no customer value.
            "batch_public_id": batch.public_id,
            "row_count": batch.row_count,
            "created": counts[CREATED],
            "matched": counts[MATCHED],
            "skipped": counts[SKIPPED],
            "rejected": counts[REJECTED],
            "conflict_policy": conflict_policy,
            "content_sha256": actual,
            "explicit_decisions": len(decisions),
            "decisions_to_create": sum(
                1 for value in decisions.values() if value == DECISION_CREATE
            ),
        },
    )

    return CommitResult(
        batch_public_id=batch.public_id,
        created=counts[CREATED],
        matched=counts[MATCHED],
        skipped=counts[SKIPPED],
        rejected=counts[REJECTED],
        row_count=batch.row_count,
        conflict_policy=conflict_policy,
        rows=result_rows,
    )


def _apply_row(
    db: Session,
    normalized: NormalizedRow,
    *,
    conflict_policy: str,
    decision: str | None,
    seen_keys: set[str],
    actor: User,
) -> tuple[str, str | None, Customer | None]:
    """Decide and perform what happens to one row. Returns ``(outcome, reason, customer)``."""
    if not normalized.is_valid:
        codes = sorted({issue.code for issue in normalized.issues if issue.code != "unparsed_date"})
        return REJECTED, ",".join(codes)[:60], None

    if normalized.source_record_id in seen_keys:
        return SKIPPED, "duplicate_within_file", None
    seen_keys.add(normalized.source_record_id)

    existing = _find_by_source_key(db, normalized.source_system, normalized.source_record_id)
    if existing is not None:
        if conflict_policy == POLICY_FILL_BLANKS:
            filled = _fill_blanks(existing, normalized.data)
            if filled:
                audit_service.record_audit(
                    db,
                    action="customer.import_fill_blanks",
                    entity_type="customer",
                    entity_id=existing.public_id,
                    summary=f"Import filled {len(filled)} empty field(s) on {existing.public_id}",
                    actor=actor,
                    # Field names only. Never the values that were written.
                    detail={"fields": sorted(filled)},
                )
            _apply_tags(db, existing, normalized.tags, actor=actor)
            return MATCHED, "filled_blanks" if filled else "already_complete", existing
        return MATCHED, "already_imported", existing

    # Held for review. Never merged, and never created without somebody saying so.
    # The refusal in ``commit_import`` means a row the preview showed as a duplicate always
    # arrives here with a decision; "not reviewed" is left for a row that only became a
    # duplicate of a customer this same commit created a moment earlier.
    if decision != DECISION_CREATE and normalized.has_duplicate_candidates(db):
        reason = "duplicate_skipped" if decision == DECISION_SKIP else "duplicate_not_reviewed"
        return SKIPPED, reason, None

    # Created through the service, so an imported customer goes through the same
    # normalization, validation, identifier allocation, and audit as a typed one.
    customer = customer_service.create_customer(db, dict(normalized.data), actor=actor)
    _apply_tags(db, customer, normalized.tags, actor=actor)
    reason = "created_after_review" if decision == DECISION_CREATE else "created_from_import"
    return CREATED, reason, customer


def _fill_blanks(customer: Customer, data: dict[str, object]) -> list[str]:
    """Write only where the existing field is empty. A non-empty value is never replaced.

    ``CRM.md`` section 13 forbids a blind overwrite, and an import is exactly the
    situation where one would go unnoticed: nobody reads five hundred rows.
    """
    fillable = (
        "city",
        "province_state",
        "country_code",
        "business_name",
        "business_type",
        "best_contact_time",
        "contact_timezone",
        "preferred_contact_channel",
        "primary_route_group",
    )
    filled: list[str] = []
    for field_name in fillable:
        new_value = data.get(field_name)
        if new_value in (None, ""):
            continue
        if getattr(customer, field_name) in (None, ""):
            setattr(customer, field_name, new_value)
            filled.append(field_name)
    return filled


def _apply_tags(db: Session, customer: Customer, tags: list[str], *, actor: User) -> None:
    """Attach tags as a set union. Re-importing the same row adds nothing new.

    Resolved to tag ids first and applied in a single call. Applying them one at a time
    would re-read ``customer.tag_links`` before the previous flush had reached it, and the
    second tag would try to insert the first one again.
    """
    if not tags:
        return
    wanted = {link.tag_id for link in customer.tag_links}
    for name in tags:
        slug = (name_match_key(name) or name.lower()).replace(" ", "-")[:60]
        tag = db.scalar(select(Tag).where(Tag.slug == slug))
        if tag is None:
            tag = Tag(name=name[:60], slug=slug)
            db.add(tag)
            db.flush()
        wanted.add(tag.id)
    customer_service.set_customer_tags(db, customer, sorted(wanted), actor=actor)


def _next_batch_public_id(db: Session) -> str:
    value = _next_counter_value(db, IMPORT_BATCH_COUNTER)
    return f"IMP-{value:06d}"


# --- Batch history --------------------------------------------------------------


def list_batches(
    db: Session, *, limit: int = 25, offset: int = 0, kind: str | None = None
) -> tuple[list[ImportBatch], int]:
    """Committed imports, newest first; ``kind`` narrows to one import kind (RC-UAT-21)."""
    from sqlalchemy import func

    conditions = [ImportBatch.kind == kind] if kind else []
    total = int(db.scalar(select(func.count(ImportBatch.id)).where(*conditions)) or 0)
    rows = list(
        db.scalars(
            select(ImportBatch)
            .where(*conditions)
            .order_by(ImportBatch.committed_at.desc(), ImportBatch.id.desc())
            .limit(limit)
            .offset(offset)
        ).all()
    )
    return rows, total


def batch_detail(db: Session, public_id: str) -> ImportBatch | None:
    return db.scalar(select(ImportBatch).where(ImportBatch.public_id == public_id))
