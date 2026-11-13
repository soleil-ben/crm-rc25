"""Human-readable identifier allocation.

Customer IDs (``STCA-000001``) are allocated from a durable counter row inside the
caller's transaction, so a rolled-back create does not burn a number and two concurrent
creates cannot collide (CRM.md section 4).

Route-prefixed Solaris Shipment IDs are Phase 2 work; the unambiguous alphabet used for
them is defined here so both generators share one definition.
"""

from __future__ import annotations

import secrets

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Counter

CUSTOMER_ID_COUNTER = "customer_public_id"
# "STCA" since OD-42 / DEC-0174 (2026-10-19); identifiers issued as "CUS-" before that were
# renamed by migration a7c3e1d9b2f4 and kept as aliases. Six digits are kept.
CUSTOMER_ID_PREFIX = "STCA"
CUSTOMER_ID_DIGITS = 6

# Unambiguous uppercase alphabet: no I, O, 0, 1 (CRM.md section 6).
UNAMBIGUOUS_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def _next_counter_value(db: Session, name: str) -> int:
    counter = db.scalar(select(Counter).where(Counter.name == name).with_for_update(nowait=False))
    if counter is None:
        counter = Counter(name=name, value=0)
        db.add(counter)
        db.flush()
    counter.value += 1
    db.flush()
    return counter.value


def next_customer_public_id(db: Session) -> str:
    value = _next_counter_value(db, CUSTOMER_ID_COUNTER)
    return f"{CUSTOMER_ID_PREFIX}-{value:0{CUSTOMER_ID_DIGITS}d}"


#: The Customer Account identity counter. A separate sequence from ``STCA-``: an account is
#: not a customer, and a shared sequence would imply the two are the same population.
ACCOUNT_ID_COUNTER = "customer_identity_public_id"
ACCOUNT_ID_PREFIX = "CA"
ACCOUNT_ID_DIGITS = 6


def next_account_public_id(db: Session) -> str:
    """``CA-000001``. The reference a customer quotes and the only identity id ever logged.

    Allocated from the same durable counter mechanism as ``STCA-``, inside the caller's
    transaction, so a rolled-back registration does not burn a number and two concurrent
    registrations cannot collide.
    """
    value = _next_counter_value(db, ACCOUNT_ID_COUNTER)
    return f"{ACCOUNT_ID_PREFIX}-{value:0{ACCOUNT_ID_DIGITS}d}"


def random_suffix(length: int = 12) -> str:
    """Cryptographically secure suffix for public shipment identifiers (Phase 2)."""
    return "".join(secrets.choice(UNAMBIGUOUS_ALPHABET) for _ in range(length))


#: Imported vendor tariff versions. Its own sequence: a tariff is neither a customer nor
#: an account, and the number is quoted in quotation snapshots and audit rows.
TARIFF_VERSION_ID_COUNTER = "tariff_version_public_id"
TARIFF_VERSION_ID_PREFIX = "TRF"


def next_tariff_version_public_id(db: Session) -> str:
    """``TRF-000001``, allocated inside the caller's transaction like the others."""
    value = _next_counter_value(db, TARIFF_VERSION_ID_COUNTER)
    return f"{TARIFF_VERSION_ID_PREFIX}-{value:06d}"


#: Consolidations (vendor bookings, the handoff's "master"). Its own sequence; the number
#: is the Solaris reference for the master and is never the vendor's booking number.
CONSOLIDATION_ID_COUNTER = "consolidation_public_id"
CONSOLIDATION_ID_PREFIX = "MST"


def next_consolidation_public_id(db: Session) -> str:
    """``MST-000001``, allocated inside the caller's transaction like the others."""
    value = _next_counter_value(db, CONSOLIDATION_ID_COUNTER)
    return f"{CONSOLIDATION_ID_PREFIX}-{value:06d}"


#: Customer invoices, receipts and vendor bills (Phase 13E). Each its own sequence, allocated
#: inside the caller's transaction, so a refused issue burns no number and numbers are
#: never reused: a voided invoice keeps its number.
INVOICE_ID_COUNTER = "customer_invoice_public_id"
RECEIPT_ID_COUNTER = "customer_receipt_public_id"
VENDOR_INVOICE_ID_COUNTER = "vendor_invoice_public_id"


def next_invoice_public_id(db: Session) -> str:
    """``INV-000001``."""
    return f"INV-{_next_counter_value(db, INVOICE_ID_COUNTER):06d}"


def next_receipt_public_id(db: Session) -> str:
    """``RCT-000001``: issued only for a recorded payment, never for a quote."""
    return f"RCT-{_next_counter_value(db, RECEIPT_ID_COUNTER):06d}"


def next_vendor_invoice_public_id(db: Session) -> str:
    """``VB-000001``: the Solaris reference for a vendor bill, never the vendor's number."""
    return f"VB-{_next_counter_value(db, VENDOR_INVOICE_ID_COUNTER):06d}"
