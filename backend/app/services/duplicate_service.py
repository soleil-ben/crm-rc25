"""Duplicate candidate detection.

Families legitimately share a phone or an email, so matches are surfaced for staff
review and are never merged automatically (CRM.md section 13, AC-16).
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.normalization import name_match_key, normalize_email, normalize_phone, phone_match_key
from app.models import Customer

# Confidence is advisory only; it never authorizes an automatic merge.
MATCH_WEIGHTS = {
    "email": 60,
    "phone": 55,
    "name": 25,
}


@dataclass
class DuplicateCandidate:
    customer: Customer
    matched_on: list[str]
    confidence: int

    @property
    def requires_review(self) -> bool:
        return True


def find_duplicate_candidates(
    db: Session,
    *,
    full_name: str | None,
    email: str | None,
    phone: str | None,
    country_code: str | None = None,
    exclude_customer_id: int | None = None,
    limit: int = 10,
) -> list[DuplicateCandidate]:
    """Return possible duplicates ordered by advisory confidence."""
    _, email_normalized = normalize_email(email) if email else (None, None)
    phone_entered, phone_e164, _ = (
        normalize_phone(phone, country_code) if phone else (None, None, None)
    )
    phone_key = phone_match_key(phone_entered, phone_e164)
    name_key = name_match_key(full_name)

    conditions = []
    if email_normalized:
        conditions.append(Customer.email_normalized == email_normalized)
    if phone_key:
        conditions.append(Customer.phone_match_key == phone_key)
    if name_key:
        conditions.append(Customer.name_match_key == name_key)
    if not conditions:
        return []

    stmt = select(Customer).where(
        or_(*conditions),
        Customer.merged_into_customer_id.is_(None),
    )
    if exclude_customer_id is not None:
        stmt = stmt.where(Customer.id != exclude_customer_id)

    candidates: list[DuplicateCandidate] = []
    for customer in db.scalars(stmt.limit(limit * 3)).all():
        matched: list[str] = []
        if email_normalized and customer.email_normalized == email_normalized:
            matched.append("email")
        if phone_key and customer.phone_match_key == phone_key:
            matched.append("phone")
        if name_key and customer.name_match_key == name_key:
            matched.append("name")
        if not matched:
            continue
        confidence = min(99, sum(MATCH_WEIGHTS[reason] for reason in matched))
        candidates.append(
            DuplicateCandidate(customer=customer, matched_on=matched, confidence=confidence)
        )

    candidates.sort(key=lambda item: (-item.confidence, item.customer.id))
    return candidates[:limit]
